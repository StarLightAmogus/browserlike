"""``browserlike.Session``: a ``requests.Session`` with a browser identity."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterable
from http.cookiejar import Cookie
from typing import Any, cast

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict
from urllib3.util.retry import Retry

from .adapters import BrowserAdapter
from .challenges import ChallengeHandler
from .client_hints import ClientHintsStore
from .context import Kind, requested_kind
from .engines import Engine
from .exceptions import ChallengeDetected, IdentityConflictWarning
from .identity import Identity, IdentityGenerator, Locale, Platform
from .navigation import NavigationPolicy, NavigationState
from .persistence import SessionState

__all__ = ["Session"]


def _version() -> str:
    from . import __version__

    return __version__


class Session(requests.Session):
    """A ``requests.Session`` whose every request looks like one browser.

    The identity (browser version, OS, languages) is chosen once and drives
    the TLS fingerprint, HTTP/2 settings, User-Agent, client hints and header
    order of all requests. Everything else works as in ``requests``: cookies,
    redirects, auth, hooks, proxies, ``mount``.

    Args:
        identity: Identity to use. Mutually exclusive with the generator
            constraints below.
        seed: Seed for a reproducible random identity.
        platform: Fix the OS (``"windows"``, ``"macos"``, ``"linux"``).
        locale: Fix the languages, e.g. ``"ru-RU"``.
        country: Languages typical for a country, e.g. ``"RU"``.
        engine: Engine name or instance; the best installed one by default.
        navigation: ``"chain"`` (same-site navigations look like link clicks)
            or ``"direct"`` (every navigation looks typed).
        max_retries: Like ``HTTPAdapter(max_retries=...)``.
        raise_on_challenge: Raise :class:`ChallengeDetected` for anti-bot pages.
        challenge_handler: Called with challenge responses; returning ``True``
            retries the request once.
        allow_unverified: Allow browser versions without verified TLS data.
        adapter: A prepared :class:`BrowserAdapter`; overrides the arguments
            above that configure one.

    Example:
        >>> import browserlike as requests
        >>> s = requests.Session(country="RU", seed=7)
        >>> r = s.get("https://example.com/")            # doctest: +SKIP
        >>> api = s.get("https://example.com/api", kind="fetch")  # doctest: +SKIP
    """

    def __init__(
        self,
        *,
        identity: Identity | None = None,
        seed: int | None = None,
        platform: Platform | str | None = None,
        locale: Locale | str | None = None,
        country: str | None = None,
        engine: str | Engine | None = None,
        navigation: NavigationPolicy | str | NavigationState = NavigationPolicy.CHAIN,
        max_retries: int | Retry | None = 0,
        raise_on_challenge: bool = False,
        challenge_handler: ChallengeHandler | None = None,
        allow_unverified: bool = False,
        adapter: BrowserAdapter | None = None,
    ) -> None:
        self._mounting_own = True
        super().__init__()
        self.headers = CaseInsensitiveDict()
        if adapter is None:
            constraints = (seed, platform, locale, country)
            if identity is None:
                identity = IdentityGenerator().generate(seed=seed, platform=platform, locale=locale, country=country)
            elif any(value is not None for value in constraints):
                raise TypeError("pass either identity= or seed/platform/locale/country, not both")
            adapter = BrowserAdapter(
                identity,
                engine=engine,
                navigation=navigation,
                max_retries=max_retries,
                allow_unverified=allow_unverified,
            )
        self.browser_adapter = adapter
        self.mount("https://", adapter)
        self.mount("http://", adapter)
        self._mounting_own = False
        self.raise_on_challenge = raise_on_challenge
        self.challenge_handler = challenge_handler

    @property
    def identity(self) -> Identity:
        """The session identity."""
        return self.browser_adapter.identity

    def request(
        self, method: str | bytes, url: str | bytes, *args: Any, kind: Kind | str | None = None, **kwargs: Any
    ) -> requests.Response:
        """Same as ``requests.Session.request`` plus ``kind``.

        Args:
            kind: ``"navigate"`` (open a page) or ``"fetch"`` (``fetch()``/XHR
                from the current page). Inferred when omitted: GET without a
                JSON ``Accept`` and form POSTs navigate, the rest fetch.
        """
        with requested_kind(kind):
            return super().request(method, url, *args, **kwargs)

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        response = super().send(request, **kwargs)
        challenge = getattr(response, "challenge", None)
        if challenge is None:
            return response
        retried = getattr(request, "_browserlike_retried", False)
        if self.challenge_handler is not None and not retried and self.challenge_handler(self, response, challenge):
            retry = request.copy()
            retry.headers.pop("Cookie", None)
            retry.prepare_cookies(self.cookies)
            retry._browserlike_retried = True  # type: ignore[attr-defined]
            return self.send(retry, **kwargs)
        if self.raise_on_challenge:
            raise ChallengeDetected(challenge, response=response, request=request)
        return response

    def mount(self, prefix: str | bytes, adapter: BaseAdapter) -> None:
        """Same as ``requests.Session.mount``; warns when it bypasses the identity."""
        own = getattr(self, "_mounting_own", False)
        text = prefix.decode() if isinstance(prefix, bytes) else prefix
        if not own and text.startswith(("http://", "https://")) and not isinstance(adapter, BrowserAdapter):
            warnings.warn(
                f"mounting {type(adapter).__name__} on {text!r} sends those requests without the browser "
                "identity; use Session(max_retries=...) for retries instead",
                IdentityConflictWarning,
                stacklevel=2,
            )
        super().mount(prefix, adapter)

    # --- persistence ----------------------------------------------------------------

    def state(self) -> SessionState:
        """Snapshot of identity, cookies, client hints and navigation."""
        adapter = self.browser_adapter
        return SessionState(
            identity=adapter.identity,
            engine=adapter.engine.name,
            navigation=adapter.navigation.to_dict(),
            client_hints=adapter.client_hints.to_dict(),
            cookies=SessionState.dump_cookies(cast("Iterable[Cookie]", self.cookies)),
            library_version=_version(),
        )

    def save(self, path: str | os.PathLike[str]) -> None:
        """Writes the session to a JSON file (see :class:`SessionState`)."""
        self.state().write(path)

    @classmethod
    def load(cls, path: str | os.PathLike[str], **kwargs: Any) -> Session:
        """Restores a session saved with :meth:`save`.

        Expired cookies are dropped; session cookies (no expiry) are kept, as a
        browser with session restore does. ``kwargs`` go to the constructor;
        ``engine`` defaults to the saved one.
        """
        state = SessionState.read(path)
        return cls.from_state(state, **kwargs)

    @classmethod
    def from_state(cls, state: SessionState, **kwargs: Any) -> Session:
        """Builds a session from a :class:`SessionState`."""
        from .browsers import profile_for

        browser = profile_for(state.identity.family)
        navigation = NavigationState.from_dict(state.navigation)
        adapter = BrowserAdapter(
            state.identity,
            engine=kwargs.pop("engine", None) or state.engine or None,
            browser=browser,
            navigation=navigation,
            client_hints=ClientHintsStore(browser.supported_client_hints(), state.client_hints),
            max_retries=kwargs.pop("max_retries", 0),
            allow_unverified=kwargs.pop("allow_unverified", False),
        )
        session = cls(adapter=adapter, **kwargs)
        session.cookies.update(state.live_cookies())
        return session
