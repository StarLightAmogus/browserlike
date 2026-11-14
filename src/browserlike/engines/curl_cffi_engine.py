"""curl_cffi engine (fallback): libcurl-impersonate with BoringSSL.

Uses ``default_headers=False`` so curl adds no browser headers, and sets
``CURLOPT_HTTPHEADER_ORDER`` per request so our order survives. curl_cffi
discards response cookies; cookies live in ``requests``.

Known differences, seen on the stand and the local echo server:

* the ``chrome152`` target sends no GREASE value in signature_algorithms, so
  peetprint differs from Chrome 152+ even though JA4 matches;
* on HTTP/2 the cookie header is sent as one field, Chrome splits it;
* on HTTP/1.1 curl drops the ``Priority`` header (as Chrome does).
"""

from __future__ import annotations

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

__all__ = ["CurlCffiEngine"]

_PROFILES = (
    EngineProfile(
        name="chrome152",
        family=BrowserFamily.CHROME,
        tls_era="cb7bf5808d99",
        exact=False,
        note="no GREASE in signature_algorithms; HTTP/2 cookies not split",
    ),
)

_ERRORS: tuple[tuple[str, ErrorKind], ...] = (
    ("ProxyError", ErrorKind.PROXY),
    ("SSLError", ErrorKind.SSL),
    ("CertificateVerifyError", ErrorKind.SSL),
    ("ConnectTimeout", ErrorKind.CONNECT_TIMEOUT),
    ("ReadTimeout", ErrorKind.READ_TIMEOUT),
    ("Timeout", ErrorKind.TIMEOUT),
    ("DNSError", ErrorKind.CONNECT),
    ("ConnectionError", ErrorKind.CONNECT),
)


def _classify(exc: Exception) -> ErrorKind:
    names = {cls.__name__ for cls in type(exc).__mro__}
    for name, kind in _ERRORS:
        if name in names:
            return kind
    return ErrorKind.PROTOCOL


class _CurlCffiTransport(Transport):
    def __init__(self, profile: EngineProfile, options: TransportOptions) -> None:
        from curl_cffi import requests as curl_requests
        from curl_cffi.const import CurlOpt

        self._order_option = CurlOpt.HTTPHEADER_ORDER
        session_options: dict[str, Any] = {"verify": options.verify}
        self._session: Any = curl_requests.Session(
            impersonate=profile.name,
            default_headers=False,
            allow_redirects=False,
            **session_options,
            proxy=options.proxy,
            cert=options.cert,
            trust_env=False,
            discard_cookies=True,
            curl_options={},
        )
        self._error_type: type[Exception] = curl_requests.RequestsError

    def send(self, request: WireRequest) -> WireResponse:
        names = ["host", *(name.lower() for name, _ in request.headers)]
        self._session.curl_options[self._order_option] = ",".join(dict.fromkeys(names))
        kwargs: dict[str, Any] = {
            "headers": list(request.headers),
            "allow_redirects": False,
            "accept_encoding": "gzip, deflate, br, zstd",
        }
        if request.timeout is not None:
            kwargs["timeout"] = request.timeout
        if request.body is not None:
            kwargs["data"] = request.body
        try:
            response = self._session.request(request.method, request.url, **kwargs)
        except self._error_type as exc:
            raise TransportError(_classify(exc), str(exc)) from exc

        version = "HTTP/1.1" if int(response.http_version) <= 2 else "HTTP/2"
        return WireResponse(
            status=int(response.status_code),
            headers=tuple((str(k), str(v)) for k, v in response.headers.multi_items()),
            body=bytes(response.content),
            url=request.url,
            http_version=version,
        )

    def close(self) -> None:
        self._session.close()


class CurlCffiEngine(Engine):
    """Fallback engine with a near-Chrome TLS (see the module notes)."""

    name: ClassVar[str] = "curl_cffi"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            return False
        return True

    def profiles(self) -> tuple[EngineProfile, ...]:
        return _PROFILES

    def open(self, profile: EngineProfile, options: TransportOptions) -> Transport:
        return _CurlCffiTransport(profile, options)
