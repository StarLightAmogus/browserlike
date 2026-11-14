"""One request per engine to https://tls.peet.ws/api/all, compared with real Chrome 156.

Opt-in (``pytest --run-network``): tls.peet.ws is a shared free service.
"""

from __future__ import annotations

from typing import Any

import pytest

from browserlike import Session
from browserlike.browsers import ChromeProfile
from browserlike.engines import ENGINES, resolve_engine
from browserlike.identity import IdentityGenerator

from ..helpers import peet_headers, peetprint_without_psk

pytestmark = pytest.mark.network

INSTALLED = [engine.name for engine in ENGINES if engine.is_available()]


@pytest.mark.parametrize("engine", INSTALLED)
def test_tls_peet_sees_chrome_156(engine: str, chrome156_reference: dict[str, Any]) -> None:
    identity = IdentityGenerator().generate(seed=1, platform="windows", locale="ru-RU", major=156)
    with Session(identity=identity, engine=engine, navigation="direct") as session:
        report = session.get("https://tls.peet.ws/api/all", timeout=30).json()

    era = ChromeProfile().tls_era(156)
    assert era is not None
    assert report["http_version"] == "h2"
    assert report["tls"]["ja4"] in (era.ja4, era.ja4_resumed)
    assert report["http2"]["akamai_fingerprint"] == chrome156_reference["http2"]["akamai_fingerprint"]
    assert peet_headers(report) == peet_headers(chrome156_reference)

    profile = resolve_engine(engine).profiles()[0]
    if profile.exact:
        ours = peetprint_without_psk(report["tls"]["peetprint"])
        theirs = peetprint_without_psk(chrome156_reference["tls"]["peetprint"])
        assert ours == theirs
