"""Browser profile interface: everything that differs between browsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from ..identity.model import BrowserFamily, Platform

if TYPE_CHECKING:
    from ..context import RequestContext
    from ..fetch_metadata import FetchMetadata
    from ..headers import Header
    from ..identity.model import Identity

__all__ = ["BrowserProfile", "TlsEra", "VersionInfo"]


@dataclass(frozen=True)
class TlsEra:
    """A span of browser versions that share one TLS ClientHello.

    Attributes:
        id: Short id, the third part of the JA4 hash of a fresh connection.
        ja4: JA4 of a fresh connection.
        ja4_resumed: JA4 of a resumed connection (adds ``pre_shared_key``).
        since: First major version verified in this era.
        until: Last major version verified in this era.
    """

    id: str
    ja4: str
    ja4_resumed: str
    since: int
    until: int

    def covers(self, major: int) -> bool:
        return self.since <= major <= self.until


@dataclass(frozen=True)
class VersionInfo:
    """One browser major version the package knows about.

    Attributes:
        major: Major version.
        verified: Whether TLS and headers for it were checked against
            evidence; unverified versions are never picked automatically.
        weight: Relative share when generating identities.
        full: Full version per platform, for high-entropy client hints.
        evidence: Keys of the evidence entries backing it.
    """

    major: int
    verified: bool
    weight: float
    full: Mapping[Platform, str]
    evidence: tuple[str, ...]


class BrowserProfile(ABC):
    """Renders one browser family's headers for a given identity and request."""

    family: ClassVar[BrowserFamily]

    @abstractmethod
    def versions(self) -> tuple[VersionInfo, ...]:
        """Known major versions, verified or not."""

    @abstractmethod
    def tls_eras(self) -> tuple[TlsEra, ...]:
        """TLS eras with the versions verified in each."""

    @abstractmethod
    def user_agent(self, identity: Identity) -> str:
        """The ``User-Agent`` string."""

    @abstractmethod
    def supported_client_hints(self) -> frozenset[str]:
        """High-entropy client hints the browser sends when asked (lower case)."""

    @abstractmethod
    def browser_headers(
        self, identity: Identity, ctx: RequestContext, meta: FetchMetadata, client_hints: frozenset[str]
    ) -> list[Header]:
        """Headers the browser itself adds to this request, lower-case names."""

    @abstractmethod
    def header_order(self, ctx: RequestContext) -> tuple[str, ...]:
        """Lower-case header names in wire order; ``"*"`` marks custom headers."""

    @abstractmethod
    def wire_name(self, name: str) -> str:
        """HTTP/1.1 casing for a known lower-case header name."""

    @abstractmethod
    def knows(self, name: str) -> bool:
        """Whether ``name`` (lower case) has a fixed place in the header order."""

    def version(self, major: int) -> VersionInfo:
        """Data for one major version.

        Raises:
            KeyError: The version is unknown.
        """
        for info in self.versions():
            if info.major == major:
                return info
        raise KeyError(f"{self.family.value} {major} is not in the bundled data")

    def tls_era(self, major: int) -> TlsEra | None:
        """TLS era verified for ``major``, if any."""
        for era in self.tls_eras():
            if era.covers(major):
                return era
        return None
