from __future__ import annotations

import pytest

from browserlike.sites import Origin, SiteRelation, SiteResolver, referrer_for

sites = SiteResolver()


@pytest.mark.parametrize(
    ("initiator", "target", "relation"),
    [
        (None, "https://example.com/", SiteRelation.NONE),
        ("https://example.com/a", "https://example.com/b", SiteRelation.SAME_ORIGIN),
        ("https://www.example.com/", "https://api.example.com/", SiteRelation.SAME_SITE),
        ("https://shop.example.co.uk/", "https://www.example.co.uk/", SiteRelation.SAME_SITE),
        ("https://a.github.io/", "https://b.github.io/", SiteRelation.CROSS_SITE),
        ("http://example.com/", "https://example.com/", SiteRelation.CROSS_SITE),
        ("https://example.com/", "https://example.org/", SiteRelation.CROSS_SITE),
        ("https://127.0.0.1:8443/", "https://127.0.0.1:8443/x", SiteRelation.SAME_ORIGIN),
        ("https://localhost:1/", "https://localhost:2/", SiteRelation.SAME_SITE),
    ],
)
def test_relation(initiator: str | None, target: str, relation: SiteRelation) -> None:
    assert sites.relation(initiator, target) is relation


def test_chain_takes_the_most_cross_site_hop() -> None:
    chain = ["https://example.com/a", "https://tracker.net/r", "https://example.com/b"]
    assert sites.chain_relation("https://example.com/", chain) is SiteRelation.CROSS_SITE
    assert sites.chain_relation(None, chain) is SiteRelation.NONE


@pytest.mark.parametrize(
    ("document", "target", "referer"),
    [
        ("https://example.com/p?q=1#frag", "https://example.com/x", "https://example.com/p?q=1"),
        ("https://user:pw@example.com/p", "https://example.com/x", "https://example.com/p"),
        ("https://example.com/p?q=1", "https://other.org/x", "https://example.com/"),
        ("https://example.com:443/p", "https://example.com/x", "https://example.com/p"),
        ("https://example.com:8443/p", "https://api.example.com/", "https://example.com:8443/"),
        ("https://example.com/p", "http://example.com/x", None),
        ("http://example.com/p", "http://example.com/x", "http://example.com/p"),
    ],
)
def test_strict_origin_when_cross_origin(document: str, target: str, referer: str | None) -> None:
    assert referrer_for(document, target) == referer


def test_origin_serialization_and_trust() -> None:
    assert Origin.of("https://Example.com:443/x").serialize() == "https://example.com"
    assert Origin.of("http://example.com:8080/").serialize() == "http://example.com:8080"
    assert Origin.of("https://example.com/").potentially_trustworthy
    assert Origin.of("http://localhost:8000/").potentially_trustworthy
    assert Origin.of("http://127.0.0.1/").potentially_trustworthy
    assert not Origin.of("http://example.com/").potentially_trustworthy
