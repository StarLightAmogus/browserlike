"""A scripted engine for adapter tests: records requests, replays responses."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from browserlike.engines import (
    Engine,
    EngineProfile,
    ErrorKind,
    Transport,
    TransportError,
    TransportOptions,
    WireRequest,
    WireResponse,
)
from browserlike.identity import BrowserFamily

Responder = Callable[[WireRequest], WireResponse | TransportError]


def ok(
    request: WireRequest, *, status: int = 200, headers: tuple[tuple[str, str], ...] = (), body: bytes = b""
) -> WireResponse:
    return WireResponse(status=status, headers=headers, body=body, url=request.url, http_version="HTTP/2")


@dataclass
class FakeTransport(Transport):
    engine: FakeEngine
    options: TransportOptions
    closed: bool = False

    def send(self, request: WireRequest) -> WireResponse:
        self.engine.sent.append(request)
        self.engine.options_seen.append(self.options)
        outcome = self.engine.responder(request)
        if isinstance(outcome, TransportError):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeEngine(Engine):
    responder: Responder = ok
    sent: list[WireRequest] = field(default_factory=list)
    options_seen: list[TransportOptions] = field(default_factory=list)
    transports: list[FakeTransport] = field(default_factory=list)

    name: ClassVar[str] = "fake"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def profiles(self) -> tuple[EngineProfile, ...]:
        return (EngineProfile("fake-chrome", BrowserFamily.CHROME, "cb7bf5808d99"),)

    def open(self, profile: EngineProfile, options: TransportOptions) -> Transport:
        transport = FakeTransport(self, options)
        self.transports.append(transport)
        return transport


def failing(kind: ErrorKind, times: int, then: Responder | None = None) -> Responder:
    """Fails ``times`` times with ``kind``, then answers with ``then`` (200 by default)."""
    state = {"left": times}

    def respond(request: WireRequest) -> WireResponse | TransportError:
        if state["left"] > 0:
            state["left"] -= 1
            return TransportError(kind, f"scripted {kind.value}")
        return (then or ok)(request)

    return respond
