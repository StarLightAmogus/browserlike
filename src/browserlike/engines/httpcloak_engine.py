"""httpcloak engine (default): Go TLS stack with captured browser presets.

Runs httpcloak in "TLS only" mode with ``exact_headers``: httpcloak supplies the
TLS ClientHello and HTTP/2 framing of its preset, we supply every header. Its
own cookie jar, conditional cache, client hints and redirects are switched off
so that ``requests`` stays the single owner of that state.

Checked on the local echo server and tls.peet.ws: header order and casing are
kept, HTTP/2 cookies are split into crumbs like Chromium does, ``Connection``
is dropped on HTTP/2, gzip/zstd bodies come back decoded.
"""

from __future__ import annotations

import warnings
from typing import Any, ClassVar

from ..exceptions import EngineCapabilityError, EngineCapabilityWarning
from ..identity.model import BrowserFamily
from ..sites import Origin
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

__all__ = ["HttpcloakEngine"]

_PROFILES = (EngineProfile(name="chrome-155", family=BrowserFamily.CHROME, tls_era="cb7bf5808d99", exact=True),)


def _classify(message: str) -> ErrorKind:
    text = message.lower()
    if "proxy" in text:
        return ErrorKind.PROXY
    if "x509" in text or "certificate" in text or "tls:" in text or "handshake" in text:
        return ErrorKind.SSL
    if "deadline exceeded" in text or "timeout" in text:
        return ErrorKind.TIMEOUT
    if "refused" in text or "no such host" in text or "dial" in text or "unreachable" in text:
        return ErrorKind.CONNECT
    return ErrorKind.PROTOCOL


class _HttpcloakTransport(Transport):
    def __init__(self, profile: EngineProfile, options: TransportOptions, *, ech: bool) -> None:
        import httpcloak

        verify = options.verify
        if isinstance(verify, str):
            warnings.warn(
                "httpcloak cannot load a custom CA bundle; verifying against the system store instead",
                EngineCapabilityWarning,
                stacklevel=4,
            )
            verify = True
        if options.cert:
            raise EngineCapabilityError("httpcloak does not support client certificates; use engine='curl_cffi'")
        self._session = httpcloak.Session(
            preset=profile.name,
            proxy=options.proxy,
            timeout=0,
            verify=bool(verify),
            allow_redirects=False,
            retry=0,
            tls_only=True,
            without_cookie_jar=True,
            without_conditional_cache=True,
            without_client_hints=True,
            without_high_entropy_client_hints=True,
            disable_ech=not ech,
            disable_http3=True,
        )
        self._http1_origins: set[str] = set()
        self._error_type: type[Exception] = httpcloak.HTTPCloakError

    def send(self, request: WireRequest) -> WireResponse:
        origin = Origin.of(request.url).serialize()
        headers = request.headers
        if origin in self._http1_origins:
            headers = headers.without("priority")
        timeout = request.timeout
        seconds = sum(timeout) if isinstance(timeout, tuple) else timeout
        kwargs: dict[str, Any] = {"exact_headers": list(headers), "allow_redirects": False}
        if seconds:
            kwargs["timeout"] = seconds
        if request.body is not None:
            kwargs["data"] = request.body
        try:
            response = self._session.request(request.method, request.url, **kwargs)
        except self._error_type as exc:
            raise TransportError(_classify(str(exc)), str(exc)) from exc

        protocol = str(response.protocol).lower()
        if protocol in ("h1", "http/1.1", "http/1.0"):
            self._http1_origins.add(origin)
            version = "HTTP/1.1"
        else:
            version = "HTTP/2"
        pairs = tuple(
            (str(name), str(value))
            for name, values in response.headers.items()
            for value in (values if isinstance(values, list) else [values])
        )
        return WireResponse(
            status=int(response.status_code),
            headers=pairs,
            body=bytes(response.content),
            url=request.url,
            http_version=version,
        )

    def close(self) -> None:
        self._session.close()


class HttpcloakEngine(Engine):
    """Default engine; reproduces Chrome 152-156 TLS exactly.

    Args:
        ech: Look up ECH configs in DNS (httpcloak queries public resolvers
            8.8.8.8, 1.1.1.1 and 9.9.9.9 for this). Off by default: the
            ClientHello still carries a GREASE ECH extension, as Chrome does
            for sites without ECH, and no hostnames leave through extra DNS.
    """

    name: ClassVar[str] = "httpcloak"

    def __init__(self, *, ech: bool = False) -> None:
        self._ech = ech

    @classmethod
    def is_available(cls) -> bool:
        try:
            import httpcloak  # noqa: F401
        except ImportError:
            return False
        return True

    def profiles(self) -> tuple[EngineProfile, ...]:
        return _PROFILES

    def open(self, profile: EngineProfile, options: TransportOptions) -> Transport:
        return _HttpcloakTransport(profile, options, ech=self._ech)
