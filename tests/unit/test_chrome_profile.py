from __future__ import annotations

import pytest

from browserlike.browsers import ChromeProfile, chrome_brands
from browserlike.context import Destination
from browserlike.identity import BrowserFamily, Identity, Locale, OperatingSystem, Platform


def _header(major: int) -> str:
    return ", ".join(f'"{b}";v="{v}"' for b, v in chrome_brands(major))


# Real sec-ch-ua values and where each was seen.
@pytest.mark.parametrize(
    ("major", "expected"),
    [
        # curl_cffi 0.17 chrome152 target
        (152, '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"'),
        # wreq 0.13 Chrome154 profile
        (154, '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"'),
        # httpcloak 1.7.3 chrome-155 preset
        (155, '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"'),
        # real Chrome 156 (tests/fixtures/chrome-156-windows.json)
        (156, '"Not:A-Brand";v="8", "Chromium";v="156", "Google Chrome";v="156"'),
    ],
)
def test_grease_brand_matches_real_chrome(major: int, expected: str) -> None:
    assert _header(major) == expected


def _identity(platform: Platform = Platform.WINDOWS, major: int = 156) -> Identity:
    full = {156: "156.0.8078.82", 155: "155.0.8059.86"}[major]
    return Identity(
        family=BrowserFamily.CHROME,
        major=major,
        full_version=full,
        os=OperatingSystem(platform, "19.0.0", "x86", "64"),
        locale=Locale(("en-US", "en")),
    )


@pytest.mark.parametrize(
    ("platform", "token"),
    [
        (Platform.WINDOWS, "Windows NT 10.0; Win64; x64"),
        (Platform.MACOS, "Macintosh; Intel Mac OS X 10_15_7"),
        (Platform.LINUX, "X11; Linux x86_64"),
    ],
)
def test_reduced_user_agent(platform: Platform, token: str) -> None:
    ua = ChromeProfile().user_agent(_identity(platform))
    assert ua == f"Mozilla/5.0 ({token}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"


def test_accept_adds_jpeg_xl_from_155() -> None:
    profile = ChromeProfile()
    assert "image/jxl" in profile.accept(155, Destination.DOCUMENT)
    assert "image/jxl" not in profile.accept(154, Destination.DOCUMENT)
    assert profile.accept(156, Destination.EMPTY) == "*/*"


def test_low_entropy_hints_only_by_default() -> None:
    hints = ChromeProfile().client_hints(_identity(), frozenset())
    assert [name for name, _ in hints] == ["sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"]
    assert dict(hints)["sec-ch-ua-platform"] == '"Windows"'


def test_high_entropy_hints_follow_identity() -> None:
    requested = frozenset({"sec-ch-ua-full-version-list", "sec-ch-ua-platform-version", "sec-ch-ua-arch", "x-unknown"})
    hints = dict(ChromeProfile().client_hints(_identity(), requested))
    assert hints["sec-ch-ua-full-version-list"] == (
        '"Not:A-Brand";v="8.0.0.0", "Chromium";v="156.0.8078.82", "Google Chrome";v="156.0.8078.82"'
    )
    assert hints["sec-ch-ua-platform-version"] == '"19.0.0"'
    assert hints["sec-ch-ua-arch"] == '"x86"'
    assert "x-unknown" not in hints


def test_versions_data_only_verifies_known_eras() -> None:
    profile = ChromeProfile()
    verified = {v.major for v in profile.versions() if v.verified}
    assert verified == {155, 156}
    assert profile.tls_era(156) is not None
    assert profile.tls_era(157) is None
