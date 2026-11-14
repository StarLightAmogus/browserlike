"""Seeded generation of consistent identities."""

from __future__ import annotations

import random
import secrets
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from ..data import load
from .locales import locale_for_country, locale_from_tag
from .model import BrowserFamily, Identity, Locale, OperatingSystem, Platform

if TYPE_CHECKING:
    from ..browsers.base import BrowserProfile

__all__ = ["IdentityGenerator"]

T = TypeVar("T")


def _pick(rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    values = [value for value, _ in options]
    weights = [weight for _, weight in options]
    return rng.choices(values, weights=weights, k=1)[0]


class IdentityGenerator:
    """Builds identities from weighted, evidence-backed data.

    Only verified browser versions are chosen. Platform weights are
    approximate desktop shares (see ``data/platforms.json``); pass your own to
    match your traffic.

    Args:
        profile: Browser profile; Chrome when omitted.
        platform_weights: Relative weight per platform.
        platforms_data: Parsed ``platforms.json``, for tests.
    """

    def __init__(
        self,
        profile: BrowserProfile | None = None,
        *,
        platform_weights: Mapping[Platform | str, float] | None = None,
        platforms_data: Mapping[str, Any] | None = None,
    ) -> None:
        if profile is None:
            from ..browsers.chrome import ChromeProfile

            profile = ChromeProfile()
        self._profile = profile
        data = platforms_data if platforms_data is not None else load("platforms.json")
        weights = platform_weights or {k: v for k, v in data["platform_weights"].items() if k != "evidence"}
        self._platform_weights = tuple((Platform(k), float(v)) for k, v in weights.items())
        self._os_data: Mapping[str, Any] = data["os"]

    @property
    def profile(self) -> BrowserProfile:
        return self._profile

    def generate(
        self,
        *,
        seed: int | None = None,
        platform: Platform | str | None = None,
        locale: Locale | str | None = None,
        country: str | None = None,
        major: int | None = None,
    ) -> Identity:
        """A new identity; the same seed and constraints give the same result.

        Args:
            seed: Random seed; a fresh one is drawn and stored when omitted.
            platform: Fix the operating system.
            locale: Fix the languages, as a :class:`Locale` or a tag like
                ``"ru-RU"``.
            country: Pick languages typical for a country (``"RU"``); ignored
                when ``locale`` is given.
            major: Fix the browser version; it must be a verified one.

        Raises:
            ValueError: ``major`` is unknown or not verified.
        """
        if seed is None:
            seed = secrets.randbits(63)
        rng = random.Random(seed)

        versions = [v for v in self._profile.versions() if v.verified and v.weight > 0]
        if major is not None:
            versions = [v for v in self._profile.versions() if v.major == major and v.verified]
            if not versions:
                raise ValueError(f"{self._profile.family.value} {major} is not a verified version")
        version = _pick(rng, [(v, v.weight or 1.0) for v in versions])

        chosen_platform = Platform(platform) if platform is not None else _pick(rng, self._platform_weights)
        os_entry = self._os_data[chosen_platform.value]
        os = OperatingSystem(
            platform=chosen_platform,
            version=str(_pick(rng, [(str(p[0]), float(p[1])) for p in os_entry["platform_version"]])),
            arch=str(_pick(rng, [(str(a[0]), float(a[1])) for a in os_entry["arch"]])),
            bitness=str(os_entry["bitness"]),
        )

        if isinstance(locale, Locale):
            chosen_locale = locale
        elif isinstance(locale, str):
            chosen_locale = locale_from_tag(locale)
        else:
            chosen_locale = locale_for_country(country or load("locales.json")["default_country"])

        return Identity(
            family=BrowserFamily(self._profile.family.value),
            major=version.major,
            full_version=version.full[chosen_platform],
            os=os,
            locale=chosen_locale,
            seed=seed,
        )
