"""Google Chrome (desktop) profile."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from ..context import Destination, Kind
from ..data import load
from ..identity.model import BrowserFamily, Platform
from .base import BrowserProfile, TlsEra, VersionInfo

if TYPE_CHECKING:
    from ..context import RequestContext
    from ..fetch_metadata import FetchMetadata
    from ..headers import Header
    from ..identity.model import Identity

__all__ = ["ChromeProfile", "chrome_brands"]

# Chromium derives the "greased" brand in sec-ch-ua from the major version
# (components/embedder_support/user_agent_utils.cc). Checked against real
# Chrome 150, 152, 153, 155 and 156.
_GREASE_CHARS = (" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_")
_GREASE_VERSIONS = ("8", "99", "24")
_BRAND_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))


def chrome_brands(major: int, brand: str = "Google Chrome") -> list[tuple[str, str]]:
    """Brand list of ``sec-ch-ua`` in Chrome's order: ``[(brand, version), ...]``.

    The versions are majors; the GREASE brand gets one of 8, 99 or 24.
    """
    grease = (
        f"Not{_GREASE_CHARS[major % 11]}A{_GREASE_CHARS[(major + 1) % 11]}Brand",
        _GREASE_VERSIONS[major % 3],
    )
    slots: list[tuple[str, str]] = [("", "")] * 3
    order = _BRAND_ORDERS[major % 6]
    slots[order[0]] = grease
    slots[order[1]] = ("Chromium", str(major))
    slots[order[2]] = (brand, str(major))
    return slots


def _brand_header(brands: list[tuple[str, str]]) -> str:
    return ", ".join(f'"{name}";v="{version}"' for name, version in brands)


class ChromeProfile(BrowserProfile):
    """Chrome on Windows, macOS and Linux.

    Args:
        data: Parsed ``chrome.json``; the bundled file is used when omitted.
    """

    family: ClassVar[BrowserFamily] = BrowserFamily.CHROME

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        raw = data if data is not None else load("chrome.json")
        self._versions = tuple(
            VersionInfo(
                major=int(v["major"]),
                verified=bool(v["verified"]),
                weight=float(v["weight"]),
                full={Platform(p): str(full) for p, full in v["full"].items()},
                evidence=tuple(v.get("evidence", ())),
            )
            for v in raw["versions"]
        )
        self._eras = tuple(
            TlsEra(id=e["id"], ja4=e["ja4"], ja4_resumed=e["ja4_resumed"], since=e["since"], until=e["until"])
            for e in raw["tls_eras"]
        )
        self._ua_templates: dict[Platform, str] = {
            Platform(p): str(t) for p, t in raw["user_agent"]["template"].items()
        }
        self._platform_tokens: dict[Platform, str] = {
            Platform(p): str(t) for p, t in raw["user_agent"]["platform_token"].items()
        }
        self._accept = {
            Destination(dest): sorted(((int(e["since"]), str(e["value"])) for e in entries), reverse=True)
            for dest, entries in raw["accept"].items()
        }
        self._encoding_secure = str(raw["accept_encoding"]["secure"])
        self._encoding_insecure = str(raw["accept_encoding"]["insecure"])
        self._priority = {Destination(d): str(v) for d, v in raw["priority"].items() if d in ("document", "empty")}
        self._high_entropy = frozenset(raw["client_hints"]["high_entropy"])
        self._order_navigate = tuple(raw["header_order"]["navigate"]["names"])
        self._order_subresource = tuple(raw["header_order"]["subresource"]["names"])
        self._casing: dict[str, str] = dict(raw["http1_casing"]["names"])
        self._known = frozenset(self._order_navigate) | frozenset(self._order_subresource) | frozenset(self._casing)

    # --- data -------------------------------------------------------------------

    def versions(self) -> tuple[VersionInfo, ...]:
        return self._versions

    def tls_eras(self) -> tuple[TlsEra, ...]:
        return self._eras

    def supported_client_hints(self) -> frozenset[str]:
        return self._high_entropy

    # --- rendering ----------------------------------------------------------------

    def user_agent(self, identity: Identity) -> str:
        return self._ua_templates[identity.platform].format(major=identity.major)

    def accept(self, major: int, destination: Destination) -> str:
        for since, value in self._accept[destination]:
            if major >= since:
                return value
        raise LookupError(f"no Accept value for Chrome {major} {destination.value}")

    def client_hints(self, identity: Identity, requested: frozenset[str]) -> list[Header]:
        """Low-entropy hints plus the requested high-entropy ones, lower-case names."""
        brands = chrome_brands(identity.major)
        hints: list[Header] = [
            ("sec-ch-ua", _brand_header(brands)),
            ("sec-ch-ua-mobile", "?0"),
            ("sec-ch-ua-platform", f'"{self._platform_tokens[identity.platform]}"'),
        ]
        wanted = requested & self._high_entropy
        if not wanted:
            return hints
        full_brands = [
            (name, f"{version}.0.0.0" if name.startswith("Not") else identity.full_version) for name, version in brands
        ]
        values = {
            "sec-ch-ua-arch": f'"{identity.os.arch}"',
            "sec-ch-ua-bitness": f'"{identity.os.bitness}"',
            "sec-ch-ua-form-factors": '"Desktop"',
            "sec-ch-ua-full-version": f'"{identity.full_version}"',
            "sec-ch-ua-full-version-list": _brand_header(full_brands),
            "sec-ch-ua-model": '""',
            "sec-ch-ua-platform-version": f'"{identity.os.version}"',
            "sec-ch-ua-wow64": "?0",
        }
        hints += [(name, values[name]) for name in sorted(wanted)]
        return hints

    def browser_headers(
        self, identity: Identity, ctx: RequestContext, meta: FetchMetadata, client_hints: frozenset[str]
    ) -> list[Header]:
        navigate = ctx.kind is Kind.NAVIGATE
        out: list[Header] = [("connection", "keep-alive")]
        if ctx.form_submission:
            out.append(("cache-control", "max-age=0"))
        if ctx.secure:
            out += self.client_hints(identity, client_hints)
        if navigate:
            out.append(("upgrade-insecure-requests", "1"))
        out.append(("user-agent", self.user_agent(identity)))
        out.append(("accept", self.accept(identity.major, ctx.destination)))
        if meta.origin:
            out.append(("origin", meta.origin))
        if ctx.secure:
            out.append(("sec-fetch-site", meta.site.value))
            out.append(("sec-fetch-mode", ctx.mode.value))
            if navigate and ctx.user_activation:
                out.append(("sec-fetch-user", "?1"))
            out.append(("sec-fetch-dest", ctx.destination.value))
        if meta.referer:
            out.append(("referer", meta.referer))
        out.append(("accept-encoding", self._encoding_secure if ctx.secure else self._encoding_insecure))
        out.append(("accept-language", identity.locale.accept_language))
        if ctx.origin.scheme == "https":
            out.append(("priority", self._priority[ctx.destination]))
        return out

    def header_order(self, ctx: RequestContext) -> tuple[str, ...]:
        return self._order_navigate if ctx.kind is Kind.NAVIGATE else self._order_subresource

    def wire_name(self, name: str) -> str:
        return self._casing.get(name, name)

    def knows(self, name: str) -> bool:
        return name in self._known
