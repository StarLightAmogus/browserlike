"""What kind of browser request a ``requests`` call stands for.

A browser never sends "a request"; it opens a page, submits a form or runs
``fetch()`` from a page, and each of these looks different on the wire. This
module turns a prepared ``requests`` request into a :class:`RequestContext`
that the header builder can render.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import Enum

from .sites import Origin

__all__ = ["ContextResolver", "Destination", "Kind", "Mode", "RequestContext", "requested_kind"]


class Kind(str, Enum):
    """Request kinds a session can emulate."""

    NAVIGATE = "navigate"
    """Opening a page: typed URL, link click or form submission."""
    FETCH = "fetch"
    """``fetch()`` or XHR from a page, e.g. a JSON API call."""


class Destination(str, Enum):
    """Values of ``Sec-Fetch-Dest`` the session produces."""

    DOCUMENT = "document"
    EMPTY = "empty"


class Mode(str, Enum):
    """Values of ``Sec-Fetch-Mode`` the session produces."""

    NAVIGATE = "navigate"
    CORS = "cors"


_FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data", "text/plain")
_API_ACCEPT_HINTS = ("application/json", "text/event-stream", "+json")


@dataclass(frozen=True)
class RequestContext:
    """How the current request was triggered.

    Attributes:
        kind: Navigation or fetch.
        method: HTTP method.
        url: Request URL.
        initiator: URL of the document that caused the request, or ``None``
            for a browser-initiated navigation (typed URL).
        user_activation: Whether a user gesture triggered it (``Sec-Fetch-User``).
        url_list: URLs of earlier hops when this request follows a redirect.
    """

    kind: Kind
    method: str
    url: str
    initiator: str | None = None
    user_activation: bool = True
    url_list: tuple[str, ...] = field(default=())

    @property
    def destination(self) -> Destination:
        return Destination.DOCUMENT if self.kind is Kind.NAVIGATE else Destination.EMPTY

    @property
    def mode(self) -> Mode:
        return Mode.NAVIGATE if self.kind is Kind.NAVIGATE else Mode.CORS

    @property
    def origin(self) -> Origin:
        return Origin.of(self.url)

    @property
    def secure(self) -> bool:
        """True when the target is potentially trustworthy (HTTPS or loopback)."""
        return self.origin.potentially_trustworthy

    @property
    def form_submission(self) -> bool:
        """A navigation that carries a body, i.e. an HTML form POST."""
        return self.kind is Kind.NAVIGATE and self.method == "POST"

    def redirected(self, url: str, method: str) -> RequestContext:
        """The same request continued at ``url`` after a redirect."""
        return replace(self, url=url, method=method, url_list=(*self.url_list, self.url))


_REQUESTED_KIND: ContextVar[Kind | None] = ContextVar("browserlike_requested_kind", default=None)


@contextlib.contextmanager
def requested_kind(kind: Kind | str | None) -> Iterator[None]:
    """Makes ``kind`` the explicit request kind for calls made inside the block.

    :class:`browserlike.Session` uses this for its ``kind=`` argument, so the
    value reaches the adapter through ``requests`` without extra plumbing,
    including redirect hops.
    """
    token = _REQUESTED_KIND.set(Kind(kind) if kind is not None else None)
    try:
        yield
    finally:
        _REQUESTED_KIND.reset(token)


class ContextResolver:
    """Infers the request kind from a ``requests`` call.

    Rules, first match wins:

    1. an explicit ``kind`` (``Session.request(..., kind=...)``);
    2. ``Sec-Fetch-Mode`` set by the caller;
    3. ``X-Requested-With`` set by the caller: fetch;
    4. GET/HEAD: fetch when ``Accept`` asks for JSON or an event stream,
       otherwise navigation;
    5. POST with a form body (urlencoded, multipart, text/plain): navigation
       (form submission);
    6. anything else, including JSON bodies: fetch.
    """

    def kind_for(self, method: str, headers: Mapping[str, str]) -> Kind:
        explicit = _REQUESTED_KIND.get()
        if explicit is not None:
            return explicit
        lowered = {k.lower(): v for k, v in headers.items()}
        mode = lowered.get("sec-fetch-mode")
        if mode:
            return Kind.NAVIGATE if mode.strip().lower() == "navigate" else Kind.FETCH
        if "x-requested-with" in lowered:
            return Kind.FETCH
        method = method.upper()
        if method in ("GET", "HEAD"):
            accept = lowered.get("accept", "").lower()
            if any(hint in accept for hint in _API_ACCEPT_HINTS):
                return Kind.FETCH
            return Kind.NAVIGATE
        if method == "POST":
            content_type = lowered.get("content-type", "").lower()
            if content_type.startswith(_FORM_TYPES):
                return Kind.NAVIGATE
        return Kind.FETCH
