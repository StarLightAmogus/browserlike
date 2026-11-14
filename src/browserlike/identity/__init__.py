"""Who the session pretends to be: browser, OS, languages."""

from __future__ import annotations

from .generator import IdentityGenerator
from .locales import locale_for_country, locale_from_tag
from .model import BrowserFamily, Identity, Locale, OperatingSystem, Platform

__all__ = [
    "BrowserFamily",
    "Identity",
    "IdentityGenerator",
    "Locale",
    "OperatingSystem",
    "Platform",
    "locale_for_country",
    "locale_from_tag",
]
