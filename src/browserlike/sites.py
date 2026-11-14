"""Origins, sites and the browser's default referrer policy.

Sites are computed with the Public Suffix List bundled in ``publicsuffixlist``,
so ``a.github.io`` and ``b.github.io`` are different sites, as in a browser.
No list is downloaded at runtime.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit, urlunsplit

from publicsuffixlist import PublicSuffixList

__all__ = ["Origin", "SiteRelation", "SiteResolver", "referrer_for"]

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


@dataclass(frozen=True)
class Origin:
    """A URL origin: scheme, host and port."""

    scheme: str
    host: str
    port: int

    @classmethod
    def of(cls, url: str) -> Origin:
        """Origin of an absolute URL."""
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port or _DEFAULT_PORTS.get(scheme, 0)
        return cls(scheme, host, port)

    def serialize(self) -> str:
        """``https://host`` form, with the port only when it is not the default."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        if _DEFAULT_PORTS.get(self.scheme) == self.port:
            return f"{self.scheme}://{host}"
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def potentially_trustworthy(self) -> bool:
        """HTTPS, or a loopback host (the browser's secure-context rule)."""
        if self.scheme in ("https", "wss"):
            return True
        if self.host == "localhost" or self.host.endswith(".localhost"):
            return True
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return False


class SiteRelation(str, Enum):
    """Values of ``Sec-Fetch-Site``."""

    NONE = "none"
    SAME_ORIGIN = "same-origin"
    SAME_SITE = "same-site"
    CROSS_SITE = "cross-site"


_RELATION_RANK = {
    SiteRelation.NONE: 0,
    SiteRelation.SAME_ORIGIN: 1,
    SiteRelation.SAME_SITE: 2,
    SiteRelation.CROSS_SITE: 3,
}


class SiteResolver:
    """Computes sites and site relations with the Public Suffix List.

    Args:
        psl: A prepared list; the bundled snapshot is used when omitted.
    """

    def __init__(self, psl: PublicSuffixList | None = None) -> None:
        self._psl = psl or PublicSuffixList()

    def registrable_domain(self, host: str) -> str:
        """eTLD+1 of a host; IP addresses and bare suffixes stay as they are."""
        if not host:
            return host
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            return host
        domain = self._psl.privatesuffix(host)
        return domain or host

    def same_site(self, a: Origin, b: Origin) -> bool:
        """Schemeful same-site check, as Fetch Metadata uses it."""
        return a.scheme == b.scheme and self.registrable_domain(a.host) == self.registrable_domain(b.host)

    def relation(self, initiator: str | None, target: str) -> SiteRelation:
        """``Sec-Fetch-Site`` value for a request from ``initiator`` to ``target``.

        Args:
            initiator: URL of the document that made the request; ``None``
                for browser-initiated navigations (typed URL, bookmark).
            target: Request URL.
        """
        if initiator is None:
            return SiteRelation.NONE
        a, b = Origin.of(initiator), Origin.of(target)
        if a == b:
            return SiteRelation.SAME_ORIGIN
        if self.same_site(a, b):
            return SiteRelation.SAME_SITE
        return SiteRelation.CROSS_SITE

    def chain_relation(self, initiator: str | None, urls: list[str]) -> SiteRelation:
        """The most cross-site relation over a redirect chain.

        A browser-initiated navigation stays ``none`` through redirects.
        """
        if initiator is None:
            return SiteRelation.NONE
        relations = [self.relation(initiator, url) for url in urls]
        return max(relations, key=_RELATION_RANK.__getitem__)


def referrer_for(document_url: str, target_url: str) -> str | None:
    """Referer value under the default ``strict-origin-when-cross-origin`` policy.

    Same-origin requests get the full URL without fragment and credentials;
    cross-origin ones get the origin with a trailing slash; an HTTPS page sends
    nothing to a plain-HTTP target.
    """
    source, target = Origin.of(document_url), Origin.of(target_url)
    if source.scheme == "https" and target.scheme == "http" and not target.potentially_trustworthy:
        return None
    parts = urlsplit(document_url)
    netloc = parts.hostname or ""
    if ":" in netloc:
        netloc = f"[{netloc}]"
    if parts.port and parts.port != _DEFAULT_PORTS.get(parts.scheme.lower()):
        netloc = f"{netloc}:{parts.port}"
    if source == target:
        return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    return source.serialize() + "/"
