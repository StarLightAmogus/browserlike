"""Engines that send requests with a browser's TLS and HTTP/2 fingerprint."""

from __future__ import annotations

from ..exceptions import EngineUnavailable
from .base import (
    Engine,
    EngineProfile,
    ErrorKind,
    Transport,
    TransportError,
    TransportOptions,
    WireRequest,
    WireResponse,
)
from .curl_cffi_engine import CurlCffiEngine
from .httpcloak_engine import HttpcloakEngine
from .wreq_engine import WreqEngine

__all__ = [
    "CurlCffiEngine",
    "Engine",
    "EngineProfile",
    "ErrorKind",
    "HttpcloakEngine",
    "Transport",
    "TransportError",
    "TransportOptions",
    "WireRequest",
    "WireResponse",
    "WreqEngine",
    "available_engines",
    "resolve_engine",
]

# Preference order when no engine is named: the stand ranks httpcloak first.
ENGINES: tuple[type[Engine], ...] = (HttpcloakEngine, CurlCffiEngine, WreqEngine)


def available_engines() -> list[str]:
    """Names of engines whose libraries are installed, preferred first."""
    return [engine.name for engine in ENGINES if engine.is_available()]


def resolve_engine(engine: str | Engine | None = None) -> Engine:
    """An engine instance from a name, an instance or ``None`` (best available).

    Raises:
        EngineUnavailable: The engine is unknown or not installed.
    """
    if isinstance(engine, Engine):
        return engine
    if engine is None:
        for cls in ENGINES:
            if cls.is_available():
                return cls()
        raise EngineUnavailable(
            "no engine installed: httpcloak, the default engine, has no wheel for this platform or was removed; "
            "add another one with: pip install 'browserlike[curl]' (or [wreq])"
        )
    for cls in ENGINES:
        if cls.name == engine:
            if not cls.is_available():
                raise EngineUnavailable(f"engine {engine!r} is not installed; install it with: {cls.install_hint}")
            return cls()
    known = ", ".join(cls.name for cls in ENGINES)
    raise EngineUnavailable(f"unknown engine {engine!r}; known: {known}")
