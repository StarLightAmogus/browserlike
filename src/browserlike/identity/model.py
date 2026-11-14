"""Value objects describing who the session pretends to be."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = ["BrowserFamily", "Identity", "Locale", "OperatingSystem", "Platform"]


class Platform(str, Enum):
    """Desktop operating system family."""

    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class BrowserFamily(str, Enum):
    """Browser family. Only Chrome is implemented for now."""

    CHROME = "chrome"


@dataclass(frozen=True)
class OperatingSystem:
    """Operating system details that surface through client hints.

    Attributes:
        platform: OS family.
        version: Value for ``sec-ch-ua-platform-version`` (Chromium's notion:
            Windows API contract version, macOS version, Linux kernel version).
        arch: ``sec-ch-ua-arch`` value, ``"x86"`` or ``"arm"``.
        bitness: ``sec-ch-ua-bitness`` value, normally ``"64"``.
    """

    platform: Platform
    version: str
    arch: str = "x86"
    bitness: str = "64"

    def to_dict(self) -> dict[str, str]:
        return {"platform": self.platform.value, "version": self.version, "arch": self.arch, "bitness": self.bitness}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperatingSystem:
        return cls(
            platform=Platform(data["platform"]),
            version=str(data["version"]),
            arch=str(data.get("arch", "x86")),
            bitness=str(data.get("bitness", "64")),
        )


@dataclass(frozen=True)
class Locale:
    """Preferred languages, most preferred first, as in the browser settings.

    Attributes:
        languages: Language tags such as ``("ru-RU", "ru", "en-US", "en")``.
    """

    languages: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.languages:
            raise ValueError("Locale needs at least one language")

    @property
    def primary(self) -> str:
        """The most preferred language tag."""
        return self.languages[0]

    @property
    def accept_language(self) -> str:
        """The ``Accept-Language`` value Chrome builds from this list.

        The first language has no weight; each next one gets 0.1 less, down
        to 0.1 (``ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7``).
        """
        parts = [self.languages[0]]
        for index, tag in enumerate(self.languages[1:], start=1):
            weight = max(1.0 - index / 10, 0.1)
            parts.append(f"{tag};q={weight:.1f}")
        return ",".join(parts)


@dataclass(frozen=True)
class Identity:
    """One consistent browser identity, shared by every request of a session.

    Attributes:
        family: Browser family.
        major: Major browser version claimed in the UA and client hints.
        full_version: Full version for high-entropy client hints, e.g.
            ``"156.0.8078.82"``.
        os: Operating system details.
        locale: Preferred languages.
        seed: Seed the identity was generated from, if any; generating again
            with the same seed and constraints gives the same identity.
    """

    family: BrowserFamily
    major: int
    full_version: str
    os: OperatingSystem
    locale: Locale
    seed: int | None = None

    def __post_init__(self) -> None:
        if not self.full_version.startswith(f"{self.major}."):
            raise ValueError(f"full_version {self.full_version!r} does not match major {self.major}")

    @property
    def platform(self) -> Platform:
        """Shortcut for ``identity.os.platform``."""
        return self.os.platform

    def to_dict(self) -> dict[str, Any]:
        """Plain-JSON form, inverse of :meth:`from_dict`."""
        return {
            "family": self.family.value,
            "major": self.major,
            "full_version": self.full_version,
            "os": self.os.to_dict(),
            "languages": list(self.locale.languages),
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Identity:
        """Rebuilds an identity saved with :meth:`to_dict`."""
        return cls(
            family=BrowserFamily(data["family"]),
            major=int(data["major"]),
            full_version=str(data["full_version"]),
            os=OperatingSystem.from_dict(data["os"]),
            locale=Locale(tuple(data["languages"])),
            seed=data.get("seed"),
        )
