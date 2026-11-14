"""Client hints store, challenge rules and session persistence."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import requests

from browserlike.challenges import ChallengeDetector
from browserlike.client_hints import ClientHintsStore
from browserlike.identity import IdentityGenerator
from browserlike.persistence import SessionState, cookie_from_dict, cookie_to_dict

SUPPORTED = {"sec-ch-ua-full-version-list", "sec-ch-ua-platform-version", "sec-ch-ua-arch"}


def test_accept_ch_is_stored_per_origin_and_replaced() -> None:
    store = ClientHintsStore(SUPPORTED)
    store.update("https://example.com/a", "Sec-CH-UA-Full-Version-List, Sec-CH-UA-Platform-Version, X-Nope")
    assert store.hints_for("https://example.com/other") == {"sec-ch-ua-full-version-list", "sec-ch-ua-platform-version"}
    assert store.hints_for("https://api.example.com/") == frozenset()
    store.update("https://example.com/", "sec-ch-ua-arch")
    assert store.hints_for("https://example.com/") == {"sec-ch-ua-arch"}
    store.update("https://example.com/", None)
    assert store.hints_for("https://example.com/") == {"sec-ch-ua-arch"}
    store.update("https://example.com/", "")
    assert store.hints_for("https://example.com/") == frozenset()


def test_accept_ch_ignored_on_insecure_origin() -> None:
    store = ClientHintsStore(SUPPORTED)
    store.update("http://example.com/", "Sec-CH-UA-Arch")
    assert store.hints_for("http://example.com/") == frozenset()


def test_missing_critical_hints() -> None:
    store = ClientHintsStore(SUPPORTED)
    store.update("https://example.com/", "Sec-CH-UA-Arch, Sec-CH-UA-Platform-Version")
    missing = store.missing_critical("https://example.com/", "Sec-CH-UA-Arch", frozenset())
    assert missing == {"sec-ch-ua-arch"}
    assert store.missing_critical("https://example.com/", "Sec-CH-UA-Arch", frozenset({"sec-ch-ua-arch"})) == set()


def test_store_roundtrip() -> None:
    store = ClientHintsStore(SUPPORTED)
    store.update("https://example.com/", "Sec-CH-UA-Arch")
    again = ClientHintsStore(SUPPORTED, store.to_dict())
    assert again.hints_for("https://example.com/") == {"sec-ch-ua-arch"}


def _response(
    status: int = 200,
    body: str = "<html></html>",
    headers: dict[str, str] | None = None,
    url: str = "https://example.com/",
    cookies: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode()
    response.headers.update({"content-type": "text/html", **(headers or {})})
    response.url = url
    for name, value in (cookies or {}).items():
        response.cookies.set(name, value)
    return response


@pytest.mark.parametrize(
    ("response", "vendor"),
    [
        (_response(403, headers={"cf-mitigated": "challenge"}), "cloudflare"),
        (_response(503, "<title>Just a moment...</title>", {"server": "cloudflare"}), "cloudflare"),
        (_response(403, headers={"x-datadome": "protected"}), "datadome"),
        (_response(403, '<script src="https://geo.captcha-delivery.com/c.js">'), "datadome"),
        (_response(403, '<div id="px-captcha"></div>'), "perimeterx"),
        (_response(403, "<h1>Access Denied</h1>Reference #18", {"server": "AkamaiGHost"}), "akamai"),
        (_response(200, '<script src="/_Incapsula_Resource?x=1">'), "imperva"),
        (_response(429, "", {"x-kpsdk-ct": "abc"}), "kasada"),
        (_response(401, '<script src="/__qrator/qauth.js">'), "qrator"),
        (_response(403, "", {"server": "ddos-guard"}), "ddos-guard"),
        (_response(200, url="https://ya.ru/showcaptcha?retpath=x"), "yandex-smartcaptcha"),
    ],
)
def test_challenge_rules(response: requests.Response, vendor: str) -> None:
    challenge = ChallengeDetector().detect(response)
    assert challenge is not None
    assert challenge.vendor == vendor


@pytest.mark.parametrize(
    "response",
    [
        _response(200, "<html>Welcome</html>", {"server": "cloudflare"}),
        _response(404, "<html>Not found</html>", {"server": "nginx"}),
        _response(403, "<html>Forbidden</html>"),
    ],
)
def test_ordinary_pages_are_not_challenges(response: requests.Response) -> None:
    assert ChallengeDetector().detect(response) is None


def _jar() -> requests.cookies.RequestsCookieJar:
    jar = requests.cookies.RequestsCookieJar()
    now = int(time.time())
    jar.set("live", "1", domain="example.com", path="/", expires=now + 3600, secure=True, rest={"HttpOnly": None})
    jar.set("gone", "2", domain="example.com", path="/", expires=now - 10)
    jar.set("session", "3", domain="example.com", path="/")
    return jar


def test_cookie_roundtrip_keeps_attributes() -> None:
    live = next(c for c in _jar() if c.name == "live")
    again = cookie_from_dict(json.loads(json.dumps(cookie_to_dict(live))))
    assert (again.name, again.value, again.domain, again.secure, again.expires) == (
        "live",
        "1",
        "example.com",
        True,
        live.expires,
    )
    assert again.has_nonstandard_attr("HttpOnly")


def test_state_file_roundtrip_drops_expired_cookies(tmp_path: Path) -> None:
    identity = IdentityGenerator().generate(seed=5, country="RU")
    state = SessionState(
        identity=identity,
        engine="httpcloak",
        navigation={"policy": "chain", "current": "https://example.com/p"},
        client_hints={"https://example.com": ["sec-ch-ua-arch"]},
        cookies=SessionState.dump_cookies(_jar()),
        library_version="0.1.0",
    )
    path = tmp_path / "s.session.json"
    state.write(path)
    loaded = SessionState.read(path)
    assert loaded.identity == identity
    assert loaded.navigation["current"] == "https://example.com/p"
    assert sorted(c.name for c in loaded.live_cookies()) == ["live", "session"]


def test_state_rejects_unknown_schema() -> None:
    with pytest.raises(ValueError, match="schema"):
        SessionState.from_dict({"schema": 99})
