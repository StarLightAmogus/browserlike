from __future__ import annotations

import pytest

from browserlike.context import ContextResolver, Kind, RequestContext, requested_kind
from browserlike.fetch_metadata import FetchMetadata, FetchMetadataPolicy
from browserlike.sites import SiteRelation

resolver = ContextResolver()


@pytest.mark.parametrize(
    ("method", "headers", "kind"),
    [
        ("GET", {}, Kind.NAVIGATE),
        ("HEAD", {}, Kind.NAVIGATE),
        ("GET", {"Accept": "application/json"}, Kind.FETCH),
        ("GET", {"Accept": "application/vnd.api+json"}, Kind.FETCH),
        ("GET", {"X-Requested-With": "XMLHttpRequest"}, Kind.FETCH),
        ("GET", {"Sec-Fetch-Mode": "cors"}, Kind.FETCH),
        ("POST", {"Sec-Fetch-Mode": "navigate", "Content-Type": "application/json"}, Kind.NAVIGATE),
        ("POST", {"Content-Type": "application/x-www-form-urlencoded"}, Kind.NAVIGATE),
        ("POST", {"Content-Type": "multipart/form-data; boundary=x"}, Kind.NAVIGATE),
        ("POST", {"Content-Type": "application/json"}, Kind.FETCH),
        ("POST", {}, Kind.FETCH),
        ("PUT", {"Content-Type": "application/x-www-form-urlencoded"}, Kind.FETCH),
        ("DELETE", {}, Kind.FETCH),
    ],
)
def test_kind_inference(method: str, headers: dict[str, str], kind: Kind) -> None:
    assert resolver.kind_for(method, headers) is kind


def test_explicit_kind_wins() -> None:
    with requested_kind("fetch"):
        assert resolver.kind_for("GET", {}) is Kind.FETCH
    assert resolver.kind_for("GET", {}) is Kind.NAVIGATE


policy = FetchMetadataPolicy()


def _meta(kind: Kind, method: str, url: str, initiator: str | None) -> FetchMetadata:
    return policy.compute(RequestContext(kind=kind, method=method, url=url, initiator=initiator))


def test_typed_navigation() -> None:
    meta = _meta(Kind.NAVIGATE, "GET", "https://example.com/", None)
    assert (meta.site, meta.referer, meta.origin) == (SiteRelation.NONE, None, None)


def test_link_click() -> None:
    meta = _meta(Kind.NAVIGATE, "GET", "https://example.com/b", "https://example.com/a?x=1")
    assert (meta.site, meta.referer, meta.origin) == (SiteRelation.SAME_ORIGIN, "https://example.com/a?x=1", None)


def test_form_post_sends_origin() -> None:
    meta = _meta(Kind.NAVIGATE, "POST", "https://example.com/login", "https://example.com/form")
    assert meta.origin == "https://example.com"
    assert meta.site is SiteRelation.SAME_ORIGIN


def test_fetch_same_origin_get_has_no_origin() -> None:
    assert _meta(Kind.FETCH, "GET", "https://example.com/api", "https://example.com/page").origin is None


def test_fetch_cross_origin_and_post_send_origin() -> None:
    cross = _meta(Kind.FETCH, "GET", "https://api.example.com/v1", "https://www.example.com/page")
    assert (cross.origin, cross.site) == ("https://www.example.com", SiteRelation.SAME_SITE)
    assert cross.referer == "https://www.example.com/"
    post = _meta(Kind.FETCH, "POST", "https://example.com/api", "https://example.com/page")
    assert post.origin == "https://example.com"


def test_fetch_without_document_uses_target_root() -> None:
    meta = _meta(Kind.FETCH, "GET", "https://example.com/api?x=1", None)
    assert (meta.site, meta.referer) == (SiteRelation.SAME_ORIGIN, "https://example.com/")


def test_redirect_keeps_context() -> None:
    ctx = RequestContext(
        kind=Kind.NAVIGATE, method="POST", url="https://example.com/a", initiator="https://example.com/f"
    )
    hop = ctx.redirected("https://other.org/b", "GET")
    assert hop.initiator == "https://example.com/f"
    assert hop.url_list == ("https://example.com/a",)
    assert not hop.form_submission
    assert policy.compute(hop).site is SiteRelation.CROSS_SITE
