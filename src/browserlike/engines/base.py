"""Engine interface: the part that puts bytes on the wire with a browser's TLS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from ..exceptions import EngineUnavailable, UnverifiedVersionError

if TYPE_CHECKING:
    from ..browsers.base import BrowserProfile
    from ..headers import HeaderList
    from ..identity.model import BrowserFamily, Identity

__all__ = [
    "Engine",
    "EngineProfile",
    "ErrorKind",
    "Transport",
    "TransportError",
    "TransportOptions",
    "WireRequest",
    "WireResponse",
]


@dataclass(frozen=True)
class EngineProfile:
    """A TLS/HTTP2 fingerprint an engine can produce.

    Attributes:
        name: Engine-specific profile id, e.g. ``"chrome-155"``.
        family: Browser family it imitates.
        tls_era: Id of the TLS era it reproduces (see ``chrome.json``).
        exact: Whether it matched the real browser byte for byte on the stand
            (JA4, peetprint, HTTP/2); ``False`` means known differences.
        note: Known differences, if any.
    """

    name: str
    family: BrowserFamily
    tls_era: str
    exact: bool = True
    note: str = ""


@dataclass(frozen=True)
class TransportOptions:
    """Connection settings fixed for the life of a transport.

    Attributes:
        proxy: Proxy URL (``http://``, ``https://``, ``socks5://``), or ``None``.
        verify: ``True``, ``False`` or a CA bundle path, as in ``requests``.
        cert: Client certificate, as in ``requests``.
    """

    proxy: str | None = None
    verify: bool | str = True
    cert: str | tuple[str, str] | None = None


@dataclass(frozen=True)
class WireRequest:
    """One request exactly as it should go out."""

    method: str
    url: str
    headers: HeaderList
    body: bytes | None
    timeout: float | tuple[float, float] | None


@dataclass(frozen=True)
class WireResponse:
    """One response as the engine received it, body already decoded.

    Attributes:
        status: Status code.
        headers: Raw header pairs, repeated names kept.
        body: Decoded body.
        url: URL that answered (equals the request URL; engines never redirect).
        http_version: ``"HTTP/2"`` or ``"HTTP/1.1"``.
    """

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    url: str
    http_version: str


class ErrorKind(str, Enum):
    """Engine-independent failure classes."""

    CONNECT = "connect"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    TIMEOUT = "timeout"
    SSL = "ssl"
    PROXY = "proxy"
    PROTOCOL = "protocol"


class TransportError(Exception):
    """A failed exchange, classified for mapping to ``requests`` exceptions."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class Transport(ABC):
    """An engine session: connection pool, TLS session cache, one proxy."""

    @abstractmethod
    def send(self, request: WireRequest) -> WireResponse:
        """Sends one request without following redirects or touching cookies.

        Raises:
            TransportError: The exchange failed.
        """

    @abstractmethod
    def close(self) -> None:
        """Releases connections."""


class Engine(ABC):
    """Factory of transports with a given browser fingerprint.

    Attributes:
        name: Engine name, as passed to ``Session(engine=...)``.
        install_hint: Command that installs the backing library, shown when it is missing.
    """

    name: ClassVar[str]
    install_hint: ClassVar[str] = ""

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Whether the backing library is installed."""

    @abstractmethod
    def profiles(self) -> tuple[EngineProfile, ...]:
        """Fingerprints this engine can produce."""

    @abstractmethod
    def open(self, profile: EngineProfile, options: TransportOptions) -> Transport:
        """A new transport using ``profile``."""

    def profile_for(
        self, identity: Identity, browser: BrowserProfile, *, allow_unverified: bool = False
    ) -> EngineProfile:
        """The engine profile whose TLS era matches the identity's version.

        Args:
            identity: Session identity.
            browser: Browser profile with the TLS-era data.
            allow_unverified: Accept a version newer than the last verified
                one by assuming the latest era still applies.

        Raises:
            UnverifiedVersionError: No TLS era is verified for the version.
            EngineUnavailable: The engine has no profile for that era.
        """
        era = browser.tls_era(identity.major)
        if era is None:
            latest = max(browser.tls_eras(), key=lambda e: e.until, default=None)
            if not allow_unverified or latest is None or identity.major < latest.until:
                raise UnverifiedVersionError(
                    f"{identity.family.value} {identity.major} has no verified TLS fingerprint; "
                    "capture a reference and extend the TLS era in the data, or pass allow_unverified=True"
                )
            era = latest
        for profile in self.profiles():
            if profile.family == identity.family and profile.tls_era == era.id:
                return profile
        raise EngineUnavailable(f"engine {self.name} has no profile for {identity.family.value} TLS era {era.id}")
