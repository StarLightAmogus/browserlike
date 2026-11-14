"""The ``requests`` transport adapter that makes requests look like a browser.

``BrowserAdapter`` sits where ``requests.adapters.HTTPAdapter`` normally sits.
For every prepared request it works out what kind of browser request it is,
renders the browser's headers for the session identity, sends the request
through a fingerprinting engine and turns the answer back into a regular
``requests.Response``. Redirects, cookies, auth and hooks stay with
``requests``.
"""

from __future__ import annotations

import http.client
import io
from collections.abc import Iterable, Mapping
from http import HTTPStatus
from typing import Any
from urllib.parse import urldefrag, urljoin

import requests

# HTTPAdapter is re-exported so ``browserlike.adapters.HTTPAdapter`` resolves as in
# requests; mounting it on a browserlike.Session bypasses the identity (and warns).
from requests.adapters import BaseAdapter, HTTPAdapter
from requests.cookies import extract_cookies_to_jar
from requests.models import PreparedRequest, Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers, requote_uri, select_proxy
from urllib3 import HTTPHeaderDict, HTTPResponse
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, ProtocolError, ReadTimeoutError, ResponseError
from urllib3.util.retry import Retry

from .browsers import BrowserProfile, profile_for
from .challenges import ChallengeDetector
from .client_hints import ClientHintsStore
from .context import ContextResolver, Kind, RequestContext
from .engines import (
    Engine,
    ErrorKind,
    Transport,
    TransportError,
    TransportOptions,
    WireRequest,
    WireResponse,
    resolve_engine,
)
from .fetch_metadata import FetchMetadataPolicy
from .headers import Header, HeaderBuilder, HeaderList
from .identity import BrowserFamily, Identity, IdentityGenerator
from .navigation import NavigationPolicy, NavigationState
from .sites import Origin, SiteResolver

__all__ = ["BrowserAdapter", "HTTPAdapter"]

TimeoutValue = float | tuple[float, float] | None

_EXCEPTIONS: dict[ErrorKind, type[requests.RequestException]] = {
    ErrorKind.CONNECT: requests.exceptions.ConnectionError,
    ErrorKind.CONNECT_TIMEOUT: requests.exceptions.ConnectTimeout,
    ErrorKind.READ_TIMEOUT: requests.exceptions.ReadTimeout,
    ErrorKind.TIMEOUT: requests.exceptions.Timeout,
    ErrorKind.SSL: requests.exceptions.SSLError,
    ErrorKind.PROXY: requests.exceptions.ProxyError,
    ErrorKind.PROTOCOL: requests.exceptions.ConnectionError,
}


class _MessageCarrier:
    """Stands in for ``http.client.HTTPResponse`` so requests can read cookies."""

    def __init__(self, headers: Iterable[Header]) -> None:
        self.msg = http.client.HTTPMessage()
        for name, value in headers:
            self.msg[name] = value

    def isclosed(self) -> bool:
        return True

    def close(self) -> None:
        return None


def _as_urllib3_error(exc: TransportError) -> Exception:
    if exc.kind in (ErrorKind.CONNECT_TIMEOUT, ErrorKind.CONNECT, ErrorKind.PROXY):
        return ConnectTimeoutError(str(exc))
    if exc.kind in (ErrorKind.READ_TIMEOUT, ErrorKind.TIMEOUT):
        return ReadTimeoutError(None, None, str(exc))  # type: ignore[arg-type]
    return ProtocolError(str(exc))


def _normalize_timeout(timeout: Any) -> TimeoutValue:
    if timeout is None:
        return None
    if hasattr(timeout, "connect_timeout"):  # urllib3 Timeout object
        timeout = (timeout.connect_timeout, timeout.read_timeout)
    if isinstance(timeout, tuple):
        connect, read = timeout
        return (float(connect or 0.0), float(read or 0.0))
    return float(timeout)


def _body_bytes(body: Any) -> bytes | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if hasattr(body, "read"):
        data = body.read()
        return data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return b"".join(chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk) for chunk in body)


def _url_key(url: str) -> str:
    return urldefrag(requote_uri(url))[0]


class BrowserAdapter(BaseAdapter):
    """Transport adapter that sends requests with a browser identity.

    Mount it on any ``requests.Session``; :class:`browserlike.Session` does
    that for you::

        session = requests.Session()
        adapter = BrowserAdapter()
        session.mount("https://", adapter)
        session.mount("http://", adapter)

    Args:
        identity: Identity to use; a random one is generated when omitted.
        engine: Engine name (``"httpcloak"``, ``"curl_cffi"``, ``"wreq"``),
            instance, or ``None`` for the best installed one.
        browser: Browser profile; derived from the identity when omitted.
        navigation: Navigation policy or a prepared navigation state.
        client_hints: Client-hint store, e.g. restored from saved state.
        challenge_detector: Detector for anti-bot pages.
        max_retries: Like ``HTTPAdapter``: an int or a ``urllib3`` ``Retry``.
        allow_unverified: Allow a browser version without verified TLS data.
        sites: Site resolver (Public Suffix List).

    Raises:
        UnverifiedVersionError: The identity's version has no verified TLS data.
        EngineUnavailable: No suitable engine is installed.
    """

    def __init__(
        self,
        identity: Identity | None = None,
        *,
        engine: str | Engine | None = None,
        browser: BrowserProfile | None = None,
        navigation: NavigationPolicy | str | NavigationState = NavigationPolicy.CHAIN,
        client_hints: ClientHintsStore | None = None,
        challenge_detector: ChallengeDetector | None = None,
        max_retries: int | Retry | None = 0,
        allow_unverified: bool = False,
        sites: SiteResolver | None = None,
    ) -> None:
        super().__init__()
        family = identity.family if identity is not None else BrowserFamily.CHROME
        self.browser = browser or profile_for(family)
        self.identity = identity or IdentityGenerator(self.browser).generate()
        self.engine = resolve_engine(engine)
        self.engine_profile = self.engine.profile_for(self.identity, self.browser, allow_unverified=allow_unverified)
        self.sites = sites or SiteResolver()
        if isinstance(navigation, NavigationState):
            self.navigation = navigation
        else:
            self.navigation = NavigationState(navigation, self.sites)
        self.client_hints = client_hints or ClientHintsStore(self.browser.supported_client_hints())
        self.challenge_detector = challenge_detector or ChallengeDetector()
        if isinstance(max_retries, Retry):
            self.max_retries = max_retries
        elif not max_retries:
            self.max_retries = Retry(0, read=False)
        else:
            self.max_retries = Retry.from_int(max_retries)
        self._builder = HeaderBuilder(self.browser)
        self._metadata = FetchMetadataPolicy(self.sites)
        self._resolver = ContextResolver()
        self._requests_defaults = CaseInsensitiveDict(requests.utils.default_headers())
        self._transports: dict[tuple[str | None, str, str], Transport] = {}
        self._pending_redirect: tuple[str, RequestContext] | None = None

    # --- requests.adapters.BaseAdapter -------------------------------------------

    def send(  # type: ignore[override]  # noqa: PLR0917 - requests' signature
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: bool | str = True,
        cert: str | tuple[str, str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        """Sends a prepared request; see ``requests.adapters.BaseAdapter.send``.

        The body is always read fully: ``stream=True`` is accepted, but the
        response is buffered before it is returned.
        """
        url = request.url or ""
        method = (request.method or "GET").upper()
        caller = self._caller_headers(request)
        ctx = self._context(method, url, caller)
        consumed = {"referer", "origin"}
        caller = [(k, v) for k, v in caller if k.lower() not in consumed]

        hints = self._hints_for(ctx)
        wire = WireRequest(
            method=method,
            url=url,
            headers=self.build_headers(ctx, caller, hints),
            body=_body_bytes(request.body),
            timeout=_normalize_timeout(timeout),
        )
        transport = self._transport(url, proxies, verify, cert)
        answer = self._exchange(transport, wire, request)
        response = self._build_response(request, answer)

        if ctx.kind is Kind.NAVIGATE:
            self.client_hints.update(url, response.headers.get("accept-ch"))
            missing = self.client_hints.missing_critical(url, response.headers.get("critical-ch"), hints)
            if missing:
                hints = hints | missing
                wire = WireRequest(method, url, self.build_headers(ctx, caller, hints), wire.body, wire.timeout)
                answer = self._exchange(transport, wire, request)
                response = self._build_response(request, answer)

        if response.is_redirect and response.headers.get("location"):
            target = urljoin(url, response.headers["location"])
            self._pending_redirect = (_url_key(target), ctx)
        elif ctx.kind is Kind.NAVIGATE:
            self.navigation.record(url)

        response.challenge = self.challenge_detector.detect(response)  # type: ignore[attr-defined]
        response.http_version = answer.http_version  # type: ignore[attr-defined]
        return response

    def close(self) -> None:
        for transport in self._transports.values():
            transport.close()
        self._transports.clear()

    # --- pieces, public for tests and advanced use ----------------------------------

    def build_headers(self, ctx: RequestContext, caller: list[Header], hints: frozenset[str]) -> HeaderList:
        """Header list for a request context, as it will be handed to the engine."""
        meta = self._metadata.compute(ctx)
        return self._builder.build(self.identity, ctx, meta, caller, hints)

    def context_for(self, method: str, url: str, headers: Mapping[str, str] | None = None) -> RequestContext:
        """The request context a call would get now, without sending anything."""
        pairs = [(k, v) for k, v in (headers or {}).items()]
        return self._context(method.upper(), url, pairs)

    # --- internals ---------------------------------------------------------------------

    def _caller_headers(self, request: PreparedRequest) -> list[Header]:
        pairs: list[Header] = []
        for name, value in request.headers.items():
            if value is None:
                continue
            if self._requests_defaults.get(name) == value:
                continue
            pairs.append((name, value))
        return pairs

    def _context(self, method: str, url: str, caller: list[Header]) -> RequestContext:
        pending, self._pending_redirect = self._pending_redirect, None
        if pending is not None and pending[0] == _url_key(url):
            return pending[1].redirected(url, method)

        lowered = {k.lower(): v for k, v in caller}
        kind = self._resolver.kind_for(method, lowered)
        referer = lowered.get("referer")
        origin = lowered.get("origin")
        initiator: str | None
        if referer:
            initiator = referer
        elif origin and origin != "null" and kind is Kind.FETCH:
            initiator = origin.rstrip("/") + "/"
        else:
            initiator = self.navigation.initiator_for(kind, url)
        user_activation = lowered.get("sec-fetch-user", "?1") == "?1"
        return RequestContext(kind=kind, method=method, url=url, initiator=initiator, user_activation=user_activation)

    def _hints_for(self, ctx: RequestContext) -> frozenset[str]:
        if not ctx.secure:
            return frozenset()
        if ctx.kind is Kind.FETCH:
            initiator = ctx.initiator or ctx.url
            if Origin.of(initiator) != ctx.origin:
                return frozenset()
        return self.client_hints.hints_for(ctx.url)

    def _transport(
        self, url: str, proxies: Mapping[str, str] | None, verify: bool | str, cert: str | tuple[str, str] | None
    ) -> Transport:
        proxy = select_proxy(url, dict(proxies or {}))
        key = (proxy, repr(verify), repr(cert))
        transport = self._transports.get(key)
        if transport is None:
            options = TransportOptions(proxy=proxy, verify=verify, cert=cert)
            transport = self.engine.open(self.engine_profile, options)
            self._transports[key] = transport
        return transport

    def _exchange(self, transport: Transport, wire: WireRequest, request: PreparedRequest) -> WireResponse:
        retries = self.max_retries
        while True:
            try:
                answer = transport.send(wire)
            except TransportError as exc:
                try:
                    retries = retries.increment(method=wire.method, url=wire.url, error=_as_urllib3_error(exc))
                except (MaxRetryError, ConnectTimeoutError, ReadTimeoutError, ProtocolError):
                    # Retries exhausted, or this kind of error is not retried at all.
                    raise _EXCEPTIONS[exc.kind](str(exc), request=request) from exc
                retries.sleep()
                continue

            has_retry_after = any(name.lower() == "retry-after" for name, _ in answer.headers)
            if retries.is_retry(wire.method, answer.status, has_retry_after):
                stub = HTTPResponse(
                    body=b"", headers=HTTPHeaderDict(answer.headers), status=answer.status, preload_content=False
                )
                try:
                    retries = retries.increment(method=wire.method, url=wire.url, response=stub)
                except MaxRetryError as exc:
                    if isinstance(exc.reason, ResponseError) and retries.raise_on_status:
                        raise requests.exceptions.RetryError(exc, request=request) from exc
                    return answer
                retries.sleep(stub)
                continue
            return answer

    def _build_response(self, request: PreparedRequest, answer: WireResponse) -> Response:
        response = Response()
        response.status_code = answer.status
        merged = HTTPHeaderDict(answer.headers)
        response.headers = CaseInsensitiveDict(merged)
        response.raw = HTTPResponse(
            body=io.BytesIO(answer.body),
            headers=merged,
            status=answer.status,
            preload_content=False,
            decode_content=False,
            original_response=_MessageCarrier(answer.headers),  # type: ignore[arg-type]
            request_method=request.method,
            request_url=request.url,
        )
        try:
            response.reason = HTTPStatus(answer.status).phrase
        except ValueError:
            response.reason = ""
        response.url = request.url or answer.url
        response.encoding = get_encoding_from_headers(response.headers)
        response.request = request
        response.connection = self  # type: ignore[assignment]
        response._content = answer.body
        response._content_consumed = True  # type: ignore[attr-defined]
        extract_cookies_to_jar(response.cookies, request, response.raw)  # type: ignore[no-untyped-call]
        return response
