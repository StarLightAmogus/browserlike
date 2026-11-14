"""Fetch Metadata, Referer and Origin for a request, as a browser computes them."""

from __future__ import annotations

from dataclasses import dataclass

from .context import Kind, RequestContext
from .sites import Origin, SiteRelation, SiteResolver, referrer_for

__all__ = ["FetchMetadata", "FetchMetadataPolicy"]

_SAFE_METHODS = ("GET", "HEAD")


@dataclass(frozen=True)
class FetchMetadata:
    """Context-dependent header values.

    Attributes:
        site: ``Sec-Fetch-Site`` value.
        referer: ``Referer`` value, or ``None`` when the browser sends none.
        origin: ``Origin`` value, or ``None`` when the browser sends none.
    """

    site: SiteRelation
    referer: str | None
    origin: str | None


class FetchMetadataPolicy:
    """Derives :class:`FetchMetadata` from a request context.

    Follows the Fetch Metadata rules (``none`` for browser-initiated
    navigations, the most cross-site relation over a redirect chain), the
    default ``strict-origin-when-cross-origin`` referrer policy, and Chrome's
    Origin rules: navigations send Origin only for non-GET methods, fetches
    send it for cross-origin requests and for every non-GET method.

    Args:
        sites: Site resolver backed by the Public Suffix List.
    """

    def __init__(self, sites: SiteResolver | None = None) -> None:
        self._sites = sites or SiteResolver()

    @property
    def sites(self) -> SiteResolver:
        return self._sites

    def compute(self, ctx: RequestContext) -> FetchMetadata:
        initiator = ctx.initiator
        if initiator is None and ctx.kind is Kind.FETCH:
            initiator = ctx.origin.serialize() + "/"

        site = self._sites.chain_relation(initiator, [*ctx.url_list, ctx.url])
        referer = referrer_for(initiator, ctx.url) if initiator else None

        origin: str | None = None
        unsafe = ctx.method.upper() not in _SAFE_METHODS
        if ctx.kind is Kind.NAVIGATE:
            if unsafe:
                origin = Origin.of(initiator).serialize() if initiator else "null"
        elif initiator is not None:
            cross_origin = Origin.of(initiator) != ctx.origin
            if unsafe or cross_origin:
                origin = Origin.of(initiator).serialize()
        return FetchMetadata(site=site, referer=referer, origin=origin)
