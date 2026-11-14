"""Which page a request comes from: the session's browsing history."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from .context import Kind
from .sites import Origin, SiteResolver

__all__ = ["NavigationPolicy", "NavigationState"]


class NavigationPolicy(str, Enum):
    """How navigations relate to each other.

    ``CHAIN``: a navigation to the same site as the current page looks like a
    link click on that page (Referer, ``Sec-Fetch-Site: same-origin`` or
    ``same-site``); a jump to another site looks like a typed URL.

    ``DIRECT``: every navigation looks like a typed URL.
    """

    CHAIN = "chain"
    DIRECT = "direct"


class NavigationState:
    """The current document and how new requests attach to it.

    Args:
        policy: Navigation policy.
        sites: Site resolver.
        current: URL of the current document, e.g. from saved state.
    """

    def __init__(
        self,
        policy: NavigationPolicy | str = NavigationPolicy.CHAIN,
        sites: SiteResolver | None = None,
        current: str | None = None,
    ) -> None:
        self.policy = NavigationPolicy(policy)
        self._sites = sites or SiteResolver()
        self.current: str | None = current

    def initiator_for(self, kind: Kind, url: str) -> str | None:
        """The document a new request is attributed to.

        Navigations: the current document when the policy chains and the target
        is on the same site, else ``None`` (typed URL). Fetches: the current
        document when it is on the same site, else the target's origin root, as
        if the call came from the site's own page.
        """
        target = Origin.of(url)
        current = self.current
        same_site = current is not None and self._sites.same_site(Origin.of(current), target)
        if kind is Kind.NAVIGATE:
            if self.policy is NavigationPolicy.CHAIN and same_site:
                return current
            return None
        if same_site:
            return current
        return target.serialize() + "/"

    def record(self, url: str) -> None:
        """Marks ``url`` as the current document after a finished navigation."""
        self.current = url

    def to_dict(self) -> dict[str, Any]:
        return {"policy": self.policy.value, "current": self.current}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], sites: SiteResolver | None = None) -> NavigationState:
        return cls(policy=data.get("policy", "chain"), sites=sites, current=data.get("current"))
