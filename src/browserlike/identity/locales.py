"""Turning a country or a language tag into the browser's language list."""

from __future__ import annotations

from ..data import load
from .model import Locale

__all__ = ["locale_for_country", "locale_from_tag"]


def locale_for_country(country: str) -> Locale:
    """Typical Chrome language list for a country's default UI language.

    Args:
        country: ISO 3166-1 alpha-2 code, e.g. ``"RU"``.

    Raises:
        KeyError: The country is not in the bundled table.
    """
    countries = load("locales.json")["countries"]
    entry = countries.get(country.upper())
    if entry is None:
        known = ", ".join(sorted(countries))
        raise KeyError(f"No language data for country {country!r}; known: {known}")
    return Locale(tuple(entry["languages"]))


def locale_from_tag(tag: str) -> Locale:
    """Language list for a primary language tag such as ``"ru-RU"`` or ``"de"``.

    If the tag's region is in the bundled table and its first language equals
    the tag, that list is used. Otherwise the list is built the way Chrome
    expands it: the tag, its base language, then ``en-US`` and ``en`` for
    non-English tags.
    """
    language, _, region = tag.partition("-")
    countries = load("locales.json")["countries"]
    entry = countries.get(region.upper()) if region else None
    if entry and entry["languages"][0].lower() == tag.lower():
        return Locale(tuple(entry["languages"]))

    languages: list[str] = [tag]
    if region:
        languages.append(language)
    if language.lower() != "en":
        languages += ["en-US", "en"]
    elif tag.lower() != "en-us":
        languages.insert(1, "en-US")
    deduped = tuple(dict.fromkeys(languages))
    return Locale(deduped)
