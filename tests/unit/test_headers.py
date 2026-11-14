from __future__ import annotations

from typing import Any

import pytest

from browserlike.adapters import BrowserAdapter
from browserlike.context import Kind, RequestContext
from browserlike.exceptions import IdentityConflictWarning
from browserlike.headers import HeaderList
from browserlike.identity import IdentityGenerator

from ..helpers import peet_headers
from .fakes import FakeEngine


def _adapter(**kwargs: Any) -> BrowserAdapter:
    identity = IdentityGenerator().generate(seed=1, platform="windows", locale="ru-RU", major=156)
    return BrowserAdapter(identity, engine=FakeEngine(), **kwargs)


def _build(adapter: BrowserAdapter, ctx: RequestContext, caller: list[tuple[str, str]] | None = None) -> HeaderList:
    return adapter.build_headers(ctx, caller or [], frozenset())


def test_golden_navigation_equals_real_chrome_156(chrome156_reference: dict[str, Any]) -> None:
    """Typed-URL navigation to tls.peet.ws: identical to the real browser, byte for byte."""
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://tls.peet.ws/api/all")
    built = list(_build(adapter, ctx).for_http2())
    assert built == peet_headers(chrome156_reference)


def test_caller_value_replaces_in_place() -> None:
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://example.com/")
    headers = _build(adapter, ctx, [("Accept-Language", "de-DE,de;q=0.9")])
    names = headers.for_http2().names()
    assert headers.get("accept-language") == "de-DE,de;q=0.9"
    assert names.index("accept-language") == names.index("accept-encoding") + 1


def test_custom_header_goes_to_custom_slot() -> None:
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://example.com/")
    names = _build(adapter, ctx, [("X-Token", "1")]).names()
    assert names.index("X-Token") == names.index("Accept-Encoding") - 1
    fetch = RequestContext(Kind.FETCH, "POST", "https://example.com/api", "https://example.com/")
    names = _build(adapter, fetch, [("X-Token", "1"), ("Content-Type", "application/json")]).names()
    assert names.index("X-Token") == names.index("Content-Type") - 1


def test_identity_override_warns() -> None:
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://example.com/")
    with pytest.warns(IdentityConflictWarning, match="User-Agent"):
        headers = _build(adapter, ctx, [("User-Agent", "curl/8")])
    assert headers.get("user-agent") == "curl/8"


def test_engine_owned_headers_are_dropped() -> None:
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://example.com/")
    headers = _build(adapter, ctx, [("Host", "evil.example"), ("Transfer-Encoding", "chunked")])
    assert headers.get("host") is None
    assert headers.get("transfer-encoding") is None


def test_http2_rendering_splits_cookies_and_drops_connection() -> None:
    headers = HeaderList.of([("Connection", "keep-alive"), ("User-Agent", "x"), ("Cookie", "a=1; b=2")])
    assert list(headers.for_http2()) == [("user-agent", "x"), ("cookie", "a=1"), ("cookie", "b=2")]


def test_http1_casing_keeps_client_hints_lower_case() -> None:
    adapter = _adapter()
    names = _build(adapter, adapter.context_for("GET", "https://example.com/")).names()
    assert names[:5] == [
        "Connection",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "Upgrade-Insecure-Requests",
    ]
    assert "Priority" in names


def test_plain_http_has_no_client_hints_or_fetch_metadata() -> None:
    adapter = _adapter()
    headers = _build(adapter, adapter.context_for("GET", "http://example.com/"))
    names = [n.lower() for n in headers.names()]
    assert not [n for n in names if n.startswith(("sec-ch-", "sec-fetch-"))]
    assert headers.get("accept-encoding") == "gzip, deflate"
    assert "priority" not in names


def test_form_post_navigation() -> None:
    adapter = _adapter()
    ctx = RequestContext(Kind.NAVIGATE, "POST", "https://example.com/login", "https://example.com/form")
    caller = [("Content-Type", "application/x-www-form-urlencoded"), ("Content-Length", "7")]
    headers = _build(adapter, ctx, caller).for_http2()
    names = headers.names()
    assert names[0] == "cache-control"
    assert headers.get("origin") == "https://example.com"
    assert headers.get("sec-fetch-site") == "same-origin"
    assert names.index("content-type") < names.index("accept") < names.index("origin")


def test_fetch_order() -> None:
    adapter = _adapter()
    ctx = RequestContext(Kind.FETCH, "GET", "https://example.com/api", "https://example.com/page")
    names = _build(adapter, ctx).for_http2().names()
    assert names == [
        "sec-ch-ua-platform",
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "accept",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "referer",
        "accept-encoding",
        "accept-language",
        "priority",
    ]


def test_client_hints_after_accept_ch_are_alphabetical() -> None:
    adapter = _adapter()
    ctx = adapter.context_for("GET", "https://example.com/")
    hints = frozenset({"sec-ch-ua-platform-version", "sec-ch-ua-full-version-list", "sec-ch-ua-arch"})
    names = adapter.build_headers(ctx, [], hints).for_http2().names()
    assert names[:6] == [
        "sec-ch-ua",
        "sec-ch-ua-arch",
        "sec-ch-ua-full-version-list",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-ch-ua-platform-version",
    ]
