from __future__ import annotations

from collections import Counter

import pytest

from browserlike.identity import (
    BrowserFamily,
    Identity,
    IdentityGenerator,
    Locale,
    OperatingSystem,
    Platform,
    locale_for_country,
    locale_from_tag,
)


def test_accept_language_matches_real_chrome_ru() -> None:
    assert locale_for_country("RU").accept_language == "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("en-US", "en-US,en;q=0.9"),
        ("de-DE", "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"),
        ("de-CH", "de-CH,de;q=0.9,en-US;q=0.8,en;q=0.7"),
        ("en-GB", "en-GB,en-US;q=0.9,en;q=0.8"),
        ("ja", "ja,en-US;q=0.9,en;q=0.8"),
    ],
)
def test_locale_from_tag(tag: str, expected: str) -> None:
    assert locale_from_tag(tag).accept_language == expected


def test_accept_language_weight_floor() -> None:
    langs = tuple(f"l{i}" for i in range(12))
    assert Locale(langs).accept_language.endswith("l10;q=0.1,l11;q=0.1")


def test_unknown_country() -> None:
    with pytest.raises(KeyError, match="known"):
        locale_for_country("ZZ")


def test_same_seed_same_identity() -> None:
    gen = IdentityGenerator()
    assert gen.generate(seed=42) == gen.generate(seed=42)
    assert gen.generate(seed=42).seed == 42


def test_random_seed_is_recorded() -> None:
    identity = IdentityGenerator().generate()
    assert identity.seed is not None
    assert IdentityGenerator().generate(seed=identity.seed) == identity


def test_constraints_are_honoured() -> None:
    identity = IdentityGenerator().generate(seed=1, platform="macos", locale="de-DE", major=155)
    assert identity.platform is Platform.MACOS
    assert identity.locale.primary == "de-DE"
    assert identity.major == 155
    assert identity.full_version == "155.0.8059.86"


def test_country_picks_languages() -> None:
    assert IdentityGenerator().generate(seed=1, country="RU").locale.primary == "ru-RU"


def test_only_verified_versions_and_weights() -> None:
    gen = IdentityGenerator()
    majors = Counter(gen.generate(seed=s).major for s in range(400))
    assert set(majors) == {155, 156}
    assert majors[156] > majors[155]


def test_unverified_major_is_refused() -> None:
    with pytest.raises(ValueError, match="not a verified version"):
        IdentityGenerator().generate(major=157)


def test_custom_platform_weights() -> None:
    gen = IdentityGenerator(platform_weights={"linux": 1.0})
    assert gen.generate(seed=3).platform is Platform.LINUX


def test_identity_roundtrip() -> None:
    identity = IdentityGenerator().generate(seed=9, country="RU")
    assert Identity.from_dict(identity.to_dict()) == identity


def test_full_version_must_match_major() -> None:
    with pytest.raises(ValueError, match="does not match"):
        Identity(
            family=BrowserFamily.CHROME,
            major=156,
            full_version="155.0.1.2",
            os=OperatingSystem(Platform.WINDOWS, "10.0.0"),
            locale=Locale(("en-US",)),
        )
