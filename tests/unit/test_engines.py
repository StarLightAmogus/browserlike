"""Engine resolution: preference order and what the user is told when an engine is missing."""

from __future__ import annotations

import re
from typing import Any

import pytest

from browserlike.engines import ENGINES, CurlCffiEngine, HttpcloakEngine, WreqEngine, resolve_engine
from browserlike.exceptions import EngineUnavailable

from .fakes import FakeEngine


def _available(value: bool) -> Any:
    return classmethod(lambda cls: value)


def _installed(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Pretends that only the engines ``names`` are installed."""
    for cls in ENGINES:
        monkeypatch.setattr(cls, "is_available", _available(cls.name in names))


def test_httpcloak_is_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, "httpcloak", "curl_cffi", "wreq")
    assert isinstance(resolve_engine(), HttpcloakEngine)


def test_falls_back_in_preference_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, "curl_cffi", "wreq")
    assert isinstance(resolve_engine(), CurlCffiEngine)
    _installed(monkeypatch, "wreq")
    assert isinstance(resolve_engine(), WreqEngine)


def test_no_engine_points_to_another_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch)
    with pytest.raises(EngineUnavailable, match=r"httpcloak.*no wheel.*browserlike\[curl\]"):
        resolve_engine()


@pytest.mark.parametrize(
    ("name", "hint"),
    [
        ("httpcloak", "pip install httpcloak"),
        ("curl_cffi", "pip install 'browserlike[curl]'"),
        ("wreq", "pip install 'browserlike[wreq]'"),
    ],
)
def test_missing_named_engine_says_how_to_install_it(monkeypatch: pytest.MonkeyPatch, name: str, hint: str) -> None:
    _installed(monkeypatch)
    with pytest.raises(EngineUnavailable, match=re.escape(hint)):
        resolve_engine(name)


def test_unknown_engine_lists_the_known_ones() -> None:
    with pytest.raises(EngineUnavailable, match="known: httpcloak, curl_cffi, wreq"):
        resolve_engine("chrome")


def test_engine_instance_is_used_as_is() -> None:
    engine = FakeEngine()
    assert resolve_engine(engine) is engine
