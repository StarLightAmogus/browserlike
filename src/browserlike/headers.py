"""Ordered header lists and the builder that merges browser and caller headers."""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import IdentityConflictWarning

if TYPE_CHECKING:
    from .browsers.base import BrowserProfile
    from .context import RequestContext
    from .fetch_metadata import FetchMetadata
    from .identity.model import Identity

__all__ = ["Header", "HeaderBuilder", "HeaderList"]

Header = tuple[str, str]

# Connection-level headers that HTTP/2 forbids; engines strip them on h2.
_CONNECTION_SPECIFIC = frozenset({"connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade"})

# Headers that only the identity may set: a different value from the caller
# breaks the link between UA, client hints and the TLS fingerprint.
_IDENTITY_BOUND_PREFIXES = ("user-agent", "sec-ch-ua")

# Caller headers the builder never forwards: the engine owns them.
_ENGINE_OWNED = frozenset({"host", "connection", "keep-alive", "proxy-connection", "transfer-encoding", "te"})


@dataclass(frozen=True)
class HeaderList:
    """An immutable, ordered list of ``(name, value)`` pairs.

    Names keep the casing a browser uses on HTTP/1.1; HTTP/2 engines lower-case
    them on the wire.
    """

    items: tuple[Header, ...] = ()

    @classmethod
    def of(cls, pairs: Iterable[Header]) -> HeaderList:
        return cls(tuple((str(k), str(v)) for k, v in pairs))

    def __iter__(self) -> Iterator[Header]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def names(self) -> list[str]:
        return [name for name, _ in self.items]

    def get(self, name: str, default: str | None = None) -> str | None:
        """First value for ``name``, case-insensitively."""
        wanted = name.lower()
        for key, value in self.items:
            if key.lower() == wanted:
                return value
        return default

    def without(self, *names: str) -> HeaderList:
        """A copy without the given headers (case-insensitive)."""
        drop = {n.lower() for n in names}
        return HeaderList(tuple(h for h in self.items if h[0].lower() not in drop))

    def for_http2(self) -> HeaderList:
        """What the list becomes on an HTTP/2 connection.

        Names are lower-cased, connection-specific headers dropped and the
        cookie header split into one field per cookie ("cookie crumbling"),
        as Chromium's HPACK encoder does.
        """
        out: list[Header] = []
        for name, value in self.items:
            lname = name.lower()
            if lname in _CONNECTION_SPECIFIC:
                continue
            if lname == "cookie":
                out += [("cookie", crumb.strip()) for crumb in value.split(";") if crumb.strip()]
            else:
                out.append((lname, value))
        return HeaderList(tuple(out))


class HeaderBuilder:
    """Merges the browser's headers for a request with the caller's headers.

    The browser profile decides which headers exist, their values and their
    order. A caller header with the same name replaces the value in place;
    unknown caller headers go to the profile's custom-header slot (``"*"`` in
    its order list).

    Args:
        profile: Browser profile that renders the headers.
    """

    def __init__(self, profile: BrowserProfile) -> None:
        self._profile = profile

    def build(
        self,
        identity: Identity,
        ctx: RequestContext,
        meta: FetchMetadata,
        caller_headers: Sequence[Header],
        client_hints: frozenset[str],
    ) -> HeaderList:
        """Final header list for one request.

        Args:
            identity: Session identity.
            ctx: Request context.
            meta: Fetch metadata (site relation, referer, origin).
            caller_headers: Headers from the caller and from ``requests``
                itself (cookies, content type and length), already stripped of
                ``requests`` defaults and of the headers consumed for context.
            client_hints: High-entropy hints the origin asked for.
        """
        profile = self._profile
        merged: dict[str, Header] = {}
        for name, value in profile.browser_headers(identity, ctx, meta, client_hints):
            merged[name] = (profile.wire_name(name), value)

        for name, value in caller_headers:
            lname = name.lower()
            if lname in _ENGINE_OWNED:
                continue
            current = merged.get(lname)
            if current is not None:
                if lname.startswith(_IDENTITY_BOUND_PREFIXES) and current[1] != value:
                    warnings.warn(
                        f"{name} override {value!r} differs from the session identity "
                        f"({current[1]!r}); the TLS fingerprint still claims "
                        f"{identity.family.value} {identity.major}",
                        IdentityConflictWarning,
                        stacklevel=6,
                    )
                merged[lname] = (current[0], value)
            elif profile.knows(lname):
                merged[lname] = (profile.wire_name(lname), value)
            else:
                merged[lname] = (name, value)

        order = profile.header_order(ctx)
        position = {name: index for index, name in enumerate(order)}
        custom = position.get("*", len(order))
        ranked = sorted(merged.items(), key=lambda item: position.get(item[0], custom))
        return HeaderList(tuple(header for _, header in ranked))
