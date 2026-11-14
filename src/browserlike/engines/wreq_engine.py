"""wreq engine (optional): Rust TLS stack, formerly published as rnet.

Uses an emulation profile with ``headers=False``, so wreq adds no browser
headers, and passes our order through ``orig_headers``. Its cookie store and
redirects are off.

Known differences, seen on the local echo server:

* on HTTP/2 the cookie header is sent as one field, Chrome splits it;
* on HTTP/1.1 ``host`` goes last and lower-case, Chrome sends ``Host`` first.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar

from ..identity.model import BrowserFamily
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

__all__ = ["WreqEngine"]

_PROFILES = (
    EngineProfile(
        name="Chrome154",
        family=BrowserFamily.CHROME,
        tls_era="cb7bf5808d99",
        exact=True,
        note="HTTP/2 cookies not split; HTTP/1.1 Host placement differs",
    ),
)

_ERRORS: tuple[tuple[str, ErrorKind], ...] = (
    ("ProxyConnectionError", ErrorKind.PROXY),
    ("TlsError", ErrorKind.SSL),
    ("TimeoutError", ErrorKind.TIMEOUT),
    ("ConnectionError", ErrorKind.CONNECT),
    ("ConnectionResetError", ErrorKind.CONNECT),
)


def _classify(exc: Exception) -> ErrorKind:
    names = {cls.__name__ for cls in type(exc).__mro__}
    for name, kind in _ERRORS:
        if name in names:
            return kind
    return ErrorKind.PROTOCOL


def _seconds(value: float) -> timedelta:
    return timedelta(seconds=value)


def _text(raw: Any) -> str:
    return bytes(raw).decode("latin-1") if isinstance(raw, (bytes, bytearray, memoryview)) else str(raw)


class _WreqTransport(Transport):
    def __init__(self, profile: EngineProfile, options: TransportOptions) -> None:
        from pathlib import Path

        import wreq
        from wreq import redirect
        from wreq.blocking import Client
        from wreq.emulation import Emulation, Profile

        verify: bool | Path = Path(options.verify) if isinstance(options.verify, str) else options.verify
        config: dict[str, Any] = {
            "emulation": Emulation(profile=getattr(Profile, profile.name), headers=False),
            "redirect": redirect.Policy.none(),
            "cookie_store": False,
            "tls_verify": verify,
            "gzip": True,
            "brotli": True,
            "deflate": True,
            "zstd": True,
        }
        if options.proxy:
            config["proxies"] = [wreq.Proxy.all(options.proxy)]
        if options.cert:
            raise TransportError(ErrorKind.SSL, "client certificates are not wired for the wreq engine yet")
        self._client = Client(**config)
        self._method = wreq.Method
        from wreq.header import HeaderMap, OrigHeaderMap

        self._header_map = HeaderMap
        self._orig_header_map = OrigHeaderMap

    def send(self, request: WireRequest) -> WireResponse:
        headers = self._header_map()
        order = self._orig_header_map()
        for name, value in request.headers:
            headers.append(name, value)
            order.insert(name)
        kwargs: dict[str, Any] = {"headers": headers, "orig_headers": order, "default_headers": False}
        timeout = request.timeout
        if isinstance(timeout, tuple):
            kwargs["timeout"] = _seconds(sum(timeout))
            kwargs["read_timeout"] = _seconds(timeout[1])
        elif timeout is not None:
            kwargs["timeout"] = _seconds(timeout)
        if request.body is not None:
            kwargs["body"] = request.body
        try:
            response = self._client.request(getattr(self._method, request.method.upper()), request.url, **kwargs)
            body = bytes(response.bytes())
        except Exception as exc:
            raise TransportError(_classify(exc), str(exc)) from exc

        pairs = tuple((_text(name), _text(value)) for name, value in response.headers)
        version = "HTTP/2" if "2" in str(response.version) else "HTTP/1.1"
        return WireResponse(
            status=response.status.as_int(),
            headers=pairs,
            body=body,
            url=request.url,
            http_version=version,
        )

    def close(self) -> None:
        self._client.close()


class WreqEngine(Engine):
    """Optional engine; Chrome 154 profile in the same TLS era as 152-156."""

    name: ClassVar[str] = "wreq"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import wreq  # noqa: F401
        except ImportError:
            return False
        return True

    def profiles(self) -> tuple[EngineProfile, ...]:
        return _PROFILES

    def open(self, profile: EngineProfile, options: TransportOptions) -> Transport:
        return _WreqTransport(profile, options)
