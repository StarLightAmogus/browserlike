"""Session and adapter behaviour through the real requests machinery, fake engine."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
import requests
from urllib3.util.retry import Retry

import browserlike
from browserlike import BrowserAdapter, Session
from browserlike.engines import ErrorKind, WireRequest, WireResponse
from browserlike.exceptions import ChallengeDetected, IdentityConflictWarning, UnverifiedVersionError
from browserlike.identity import BrowserFamily, Identity, IdentityGenerator, Locale, OperatingSystem, Platform

from .fakes import FakeEngine, failing, ok


def _session(engine: FakeEngine, **kwargs: Any) -> Session:
    return Session(seed=11, platform="windows", locale="ru-RU", engine=engine, **kwargs)


def _sent(engine: FakeEngine, index: int = -1) -> dict[str, str]:
    return {k.lower(): v for k, v in engine.sent[index].headers.for_http2()}


def test_no_requests_defaults_leak() -> None:
    engine = FakeEngine()
    _session(engine).get("https://example.com/")
    headers = _sent(engine)
    assert headers["user-agent"].startswith("Mozilla/5.0 (Windows NT 10.0")
    assert headers["accept"].startswith("text/html")
    assert "python-requests" not in json.dumps(headers)


def test_plain_requests_session_with_mounted_adapter() -> None:
    engine = FakeEngine()
    session = requests.Session()
    adapter = BrowserAdapter(IdentityGenerator().generate(seed=2), engine=engine)
    session.mount("https://", adapter)
    session.get("https://example.com/")
    headers = _sent(engine)
    assert headers["accept-encoding"] == "gzip, deflate, br, zstd"
    assert "python-requests" not in headers["user-agent"]


def test_cookies_flow_through_requests_jar() -> None:
    def respond(request: WireRequest) -> WireResponse:
        if request.url.endswith("/login"):
            return ok(request, headers=(("set-cookie", "sid=1; Path=/"), ("set-cookie", "theme=dark; Path=/")))
        return ok(request)

    engine = FakeEngine(respond)
    session = _session(engine)
    session.get("https://example.com/login")
    assert dict(session.cookies) == {"sid": "1", "theme": "dark"}
    session.get("https://example.com/next")
    assert engine.sent[-1].headers.get("cookie") == "sid=1; theme=dark"


def test_redirect_hop_keeps_context_and_history() -> None:
    def respond(request: WireRequest) -> WireResponse:
        if request.url == "https://example.com/start":
            return ok(request, status=302, headers=(("location", "https://www.example.com/landing"),))
        return ok(request)

    engine = FakeEngine(respond)
    response = _session(engine).get("https://example.com/start")
    assert response.url == "https://www.example.com/landing"
    assert [r.status_code for r in response.history] == [302]
    hop = _sent(engine)
    assert hop["sec-fetch-site"] == "none"
    assert "referer" not in hop


def test_same_site_navigation_chains_like_a_link_click() -> None:
    engine = FakeEngine()
    session = _session(engine)
    session.get("https://shop.example.com/catalog")
    session.get("https://shop.example.com/item/1")
    second = _sent(engine)
    assert second["referer"] == "https://shop.example.com/catalog"
    assert second["sec-fetch-site"] == "same-origin"
    session.get("https://other.org/")
    third = _sent(engine)
    assert third["sec-fetch-site"] == "none"
    assert "referer" not in third


def test_direct_navigation_policy() -> None:
    engine = FakeEngine()
    session = _session(engine, navigation="direct")
    session.get("https://example.com/a")
    session.get("https://example.com/b")
    assert _sent(engine)["sec-fetch-site"] == "none"


def test_explicit_referer_is_trimmed_by_policy() -> None:
    engine = FakeEngine()
    _session(engine).get("https://example.com/", headers={"Referer": "https://www.google.com/search?q=x"})
    sent = _sent(engine)
    assert sent["referer"] == "https://www.google.com/"
    assert sent["sec-fetch-site"] == "cross-site"


def test_kind_fetch_and_json_post() -> None:
    engine = FakeEngine()
    session = _session(engine)
    session.get("https://example.com/page")
    session.get("https://example.com/api/items", kind="fetch")
    fetch = _sent(engine)
    assert (fetch["sec-fetch-mode"], fetch["sec-fetch-dest"], fetch["accept"]) == ("cors", "empty", "*/*")
    assert fetch["referer"] == "https://example.com/page"
    session.post("https://example.com/api/items", json={"a": 1})
    post = _sent(engine)
    assert post["origin"] == "https://example.com"
    assert post["content-type"] == "application/json"
    assert engine.sent[-1].body == b'{"a": 1}'


def test_params_and_form_post() -> None:
    engine = FakeEngine()
    session = _session(engine)
    session.get("https://example.com/search", params={"q": "кофе"})
    assert engine.sent[-1].url == "https://example.com/search?q=%D0%BA%D0%BE%D1%84%D0%B5"
    session.post("https://example.com/login", data={"user": "u"})
    form = _sent(engine)
    assert (form["sec-fetch-mode"], form["cache-control"]) == ("navigate", "max-age=0")
    assert form["origin"] == "https://example.com"


def test_accept_ch_then_critical_ch_retry() -> None:
    calls: list[str] = []

    def respond(request: WireRequest) -> WireResponse:
        calls.append(request.url)
        if request.headers.get("sec-ch-ua-platform-version") is None:
            return ok(
                request,
                headers=(("accept-ch", "Sec-CH-UA-Platform-Version"), ("critical-ch", "Sec-CH-UA-Platform-Version")),
            )
        return ok(request, body=b"with hints")

    engine = FakeEngine(respond)
    response = _session(engine).get("https://example.com/")
    assert response.content == b"with hints"
    assert len(calls) == 2


def test_hooks_and_exceptions_are_requests_classes() -> None:
    seen: list[int] = []
    engine = FakeEngine(failing(ErrorKind.CONNECT, 1))
    session = _session(engine)
    with pytest.raises(requests.exceptions.ConnectionError):
        session.get("https://example.com/")
    session.get("https://example.com/", hooks={"response": lambda r, *a, **k: seen.append(r.status_code)})
    assert seen == [200]


@pytest.mark.parametrize(
    ("kind", "exception"),
    [
        (ErrorKind.TIMEOUT, requests.exceptions.Timeout),
        (ErrorKind.READ_TIMEOUT, requests.exceptions.ReadTimeout),
        (ErrorKind.CONNECT_TIMEOUT, requests.exceptions.ConnectTimeout),
        (ErrorKind.SSL, requests.exceptions.SSLError),
        (ErrorKind.PROXY, requests.exceptions.ProxyError),
    ],
)
def test_error_mapping(kind: ErrorKind, exception: type[Exception]) -> None:
    session = _session(FakeEngine(failing(kind, 1)))
    with pytest.raises(exception):
        session.get("https://example.com/")


def test_retries_on_connection_error_and_status() -> None:
    engine = FakeEngine(failing(ErrorKind.CONNECT, 2))
    _session(engine, max_retries=Retry(total=2, backoff_factor=0)).get("https://example.com/")
    assert len(engine.sent) == 3

    statuses = iter([503, 200])
    engine = FakeEngine(lambda request: ok(request, status=next(statuses)))
    response = _session(engine, max_retries=Retry(total=1, status_forcelist=[503], backoff_factor=0)).get(
        "https://example.com/"
    )
    assert response.status_code == 200


def test_proxy_selects_transport() -> None:
    engine = FakeEngine()
    session = _session(engine)
    session.get("https://example.com/", proxies={"https": "socks5://127.0.0.1:1080"})
    session.get("https://example.com/")
    assert [o.proxy for o in engine.options_seen] == ["socks5://127.0.0.1:1080", None]
    assert len(engine.transports) == 2
    session.close()
    assert all(t.closed for t in engine.transports)


def test_challenge_flag_raise_and_handler() -> None:
    def respond(request: WireRequest) -> WireResponse:
        if request.headers.get("cookie") == "cf_clearance=ok":
            return ok(request, body=b"content")
        return ok(request, status=403, headers=(("cf-mitigated", "challenge"),))

    response = _session(FakeEngine(respond)).get("https://example.com/")
    assert response.challenge.vendor == "cloudflare"  # type: ignore[attr-defined]

    with pytest.raises(ChallengeDetected) as caught:
        _session(FakeEngine(respond), raise_on_challenge=True).get("https://example.com/")
    assert isinstance(caught.value, requests.exceptions.HTTPError)

    def handler(session: requests.Session, response: requests.Response, challenge: object) -> bool:
        session.cookies.set("cf_clearance", "ok", domain="example.com")
        return True

    solved = _session(FakeEngine(respond), challenge_handler=handler).get("https://example.com/")
    assert solved.content == b"content"


def test_mounting_plain_adapter_warns() -> None:
    session = _session(FakeEngine())
    with pytest.warns(IdentityConflictWarning, match="without the browser identity"):
        session.mount("https://", requests.adapters.HTTPAdapter())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        session.mount("https://", BrowserAdapter(session.identity, engine=FakeEngine()))


def test_save_and_load(tmp_path: Path) -> None:
    def respond(request: WireRequest) -> WireResponse:
        return ok(request, headers=(("set-cookie", "sid=7; Path=/; Max-Age=3600"), ("accept-ch", "Sec-CH-UA-Arch")))

    engine = FakeEngine(respond)
    session = _session(engine)
    session.get("https://example.com/home")
    path = tmp_path / "profile.session.json"
    session.save(path)

    again = Session.load(path, engine=engine)
    assert again.identity == session.identity
    assert dict(again.cookies) == {"sid": "7"}
    again.get("https://example.com/next")
    sent = _sent(engine)
    assert sent["cookie"] == "sid=7"
    assert sent["referer"] == "https://example.com/home"
    assert sent["sec-ch-ua-arch"] == '"x86"'


def test_identity_and_constraints_are_exclusive() -> None:
    identity = IdentityGenerator().generate(seed=1)
    with pytest.raises(TypeError):
        Session(identity=identity, seed=2, engine=FakeEngine())


def test_unverified_version_needs_opt_in() -> None:
    identity = Identity(
        family=BrowserFamily.CHROME,
        major=157,
        full_version="157.0.8103.80",
        os=OperatingSystem(Platform.WINDOWS, "19.0.0"),
        locale=Locale(("en-US", "en")),
    )
    with pytest.raises(UnverifiedVersionError):
        Session(identity=identity, engine=FakeEngine())
    session = Session(identity=identity, engine=FakeEngine(), allow_unverified=True)
    assert session.identity.major == 157


def test_drop_in_names_exist() -> None:
    for name in ("get", "post", "Session", "Response", "codes", "exceptions", "HTTPError", "Timeout", "utils", "auth"):
        assert hasattr(browserlike, name), name
    assert browserlike.exceptions.HTTPError is requests.exceptions.HTTPError
    assert browserlike.adapters.HTTPAdapter is requests.adapters.HTTPAdapter
    assert browserlike.codes.ok == 200
