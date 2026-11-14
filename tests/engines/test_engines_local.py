"""Every engine against the local echo server: what goes out on the wire."""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
import requests

from browserlike import Session
from browserlike.engines import ENGINES

from .echo_server import EchoServer

pytestmark = pytest.mark.engine

# Engines that split the HTTP/2 cookie header into crumbs like Chromium.
CRUMBLES = {"httpcloak": True, "curl_cffi": False, "wreq": False}
INSTALLED = [engine.name for engine in ENGINES if engine.is_available()]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[EchoServer]:
    srv = EchoServer(tmp_path_factory.mktemp("echo")).start()
    yield srv
    srv.stop()


@pytest.fixture(params=INSTALLED)
def session(request: pytest.FixtureRequest) -> Iterator[Session]:
    s = Session(seed=21, platform="windows", locale="ru-RU", engine=request.param)
    s.verify = False
    yield s
    s.close()


def _expected(session: Session, url: str, cookies: str | None = None) -> list[tuple[str, str]]:
    adapter = session.browser_adapter
    caller = [("Cookie", cookies)] if cookies else []
    ctx = adapter.context_for("GET", url)
    built = list(adapter.build_headers(ctx, caller, frozenset()).for_http2())
    if not CRUMBLES[adapter.engine.name] and cookies:
        crumbs = [i for i, (k, _) in enumerate(built) if k == "cookie"]
        built[crumbs[0] : crumbs[-1] + 1] = [("cookie", cookies)]
    return built


def _wire(report: dict[str, object]) -> list[tuple[str, str]]:
    headers = report["headers"]
    assert isinstance(headers, list)
    return [(str(k), str(v)) for k, v in headers if not str(k).startswith(":")]


def test_sends_exactly_our_headers(server: EchoServer, session: Session) -> None:
    url = server.base_url + "/echo"
    expected = _expected(session, url)
    report = session.get(url).json()
    assert report["http_version"] == "2"
    assert _wire(report) == expected


def test_cookies_come_only_from_requests(server: EchoServer, session: Session) -> None:
    session.get(server.base_url + "/set-cookies")
    assert dict(session.cookies) == {"a": "1", "b": "2", "short": "x"}
    url = server.base_url + "/echo"
    expected = _expected(session, url, cookies="a=1; b=2; short=x")
    assert _wire(session.get(url).json()) == expected


def test_pseudo_header_order(server: EchoServer, session: Session) -> None:
    report = session.get(server.base_url + "/echo").json()
    pseudo = [k for k, _ in report["headers"] if k.startswith(":")]
    assert pseudo == [":method", ":authority", ":scheme", ":path"]


def test_redirects_are_left_to_requests(server: EchoServer, session: Session) -> None:
    response = session.get(server.base_url + "/redirect?to=/echo")
    assert [r.status_code for r in response.history] == [302]
    assert response.json()["path"] == "/echo"


@pytest.mark.parametrize("path", ["/gzip", "/zstd"])
def test_bodies_come_back_decoded(server: EchoServer, session: Session, path: str) -> None:
    assert session.get(server.base_url + path).json()["path"] == path


def test_json_post_body(server: EchoServer, session: Session) -> None:
    report = session.post(server.base_url + "/echo", json={"x": [1, 2]}).json()
    assert report["method"] == "POST"
    assert report["body"] == '{"x": [1, 2]}'


def test_timeout_maps_to_requests_timeout(server: EchoServer, session: Session) -> None:
    with pytest.raises(requests.exceptions.Timeout):
        session.get(server.base_url + "/slow?delay=3", timeout=1)


def test_refused_connection_raises_requests_error(session: Session) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises((requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        session.get(f"https://127.0.0.1:{port}/", timeout=3)


def test_challenge_page_is_flagged(server: EchoServer, session: Session) -> None:
    response = session.get(server.base_url + "/challenge")
    assert response.challenge.vendor == "cloudflare"  # type: ignore[attr-defined]
