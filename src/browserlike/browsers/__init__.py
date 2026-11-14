"""Browser profiles, one per browser family."""

from __future__ import annotations

from ..identity.model import BrowserFamily
from .base import BrowserProfile, TlsEra, VersionInfo
from .chrome import ChromeProfile, chrome_brands

__all__ = ["BrowserProfile", "ChromeProfile", "TlsEra", "VersionInfo", "chrome_brands", "profile_for"]

_PROFILES: tuple[tuple[BrowserFamily, type[BrowserProfile]], ...] = ((BrowserFamily.CHROME, ChromeProfile),)


def profile_for(family: BrowserFamily) -> BrowserProfile:
    """A fresh profile for a browser family.

    Raises:
        NotImplementedError: The family has no profile yet.
    """
    for known, cls in _PROFILES:
        if known is family:
            return cls()
    raise NotImplementedError(f"no browser profile for {family.value}")
