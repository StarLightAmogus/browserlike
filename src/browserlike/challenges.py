"""Recognizing anti-bot challenge and block pages.

The rules are heuristics built from publicly documented markers of each
vendor (status codes, headers, cookies, page snippets). They tell the caller
*whose* check stopped the request, so it can rotate the session or hand the
page to a solver; they do not solve anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    import requests

__all__ = [
    "AkamaiRule",
    "Challenge",
    "ChallengeDetector",
    "ChallengeHandler",
    "ChallengeRule",
    "CloudflareRule",
    "DataDomeRule",
    "DdosGuardRule",
    "ImpervaRule",
    "KasadaRule",
    "PerimeterXRule",
    "QratorRule",
    "ResponseView",
    "YandexSmartCaptchaRule",
]

_BODY_LIMIT = 64 * 1024


@dataclass(frozen=True)
class Challenge:
    """A detected challenge.

    Attributes:
        vendor: Protection vendor, e.g. ``"cloudflare"``.
        reason: The marker that matched.
    """

    vendor: str
    reason: str


@dataclass(frozen=True)
class ResponseView:
    """The parts of a response the rules look at, lower-cased."""

    status: int
    url: str
    headers: dict[str, str]
    cookies: frozenset[str]
    body: str

    @classmethod
    def of(cls, response: requests.Response) -> ResponseView:
        headers = {k.lower(): v.lower() for k, v in response.headers.items()}
        cookies = frozenset(c.name.lower() for c in response.cookies)
        content_type = headers.get("content-type", "")
        body = ""
        if "html" in content_type or "text" in content_type or not content_type:
            body = response.content[:_BODY_LIMIT].decode("utf-8", "replace").lower()
        return cls(response.status_code, response.url.lower(), headers, cookies, body)

    def has_cookie(self, prefix: str) -> bool:
        return any(name.startswith(prefix) for name in self.cookies)


class ChallengeRule(ABC):
    """One vendor's markers."""

    vendor: ClassVar[str]

    @abstractmethod
    def match(self, view: ResponseView) -> str | None:
        """The matched marker, or ``None``."""


class CloudflareRule(ChallengeRule):
    vendor = "cloudflare"

    def match(self, view: ResponseView) -> str | None:
        if view.headers.get("cf-mitigated") == "challenge":
            return "cf-mitigated: challenge"
        if view.status in (403, 429, 503) and "cloudflare" in view.headers.get("server", ""):
            for marker in ("/cdn-cgi/challenge-platform/", "just a moment...", "cf-chl-", "attention required!"):
                if marker in view.body:
                    return f"{view.status} page with {marker!r}"
        return None


class DataDomeRule(ChallengeRule):
    vendor = "datadome"

    def match(self, view: ResponseView) -> str | None:
        if view.status in (403, 429):
            if "x-datadome" in view.headers or "x-dd-b" in view.headers:
                return f"{view.status} with x-datadome header"
            if "captcha-delivery.com" in view.body:
                return "captcha-delivery.com page"
        return None


class PerimeterXRule(ChallengeRule):
    vendor = "perimeterx"

    def match(self, view: ResponseView) -> str | None:
        if view.status in (403, 429):
            for marker in ("px-captcha", "_pxappid", "perimeterx", "/_px/", "px-cloud.net"):
                if marker in view.body:
                    return f"{view.status} page with {marker!r}"
        return None


class AkamaiRule(ChallengeRule):
    vendor = "akamai"

    def match(self, view: ResponseView) -> str | None:
        server = view.headers.get("server", "")
        if view.status == 403 and "akamaighost" in server and "access denied" in view.body:
            return "AkamaiGHost access denied"
        for marker in ("/_sec/cp_challenge/", "bm-verify", "sec-if-cpt"):
            if marker in view.body:
                return f"page with {marker!r}"
        return None


class ImpervaRule(ChallengeRule):
    vendor = "imperva"

    def match(self, view: ResponseView) -> str | None:
        for marker in ("_incapsula_resource", "incapsula incident id"):
            if marker in view.body:
                return f"page with {marker!r}"
        if view.status in (403, 503) and "x-iinfo" in view.headers and view.has_cookie("incap_ses"):
            return f"{view.status} with x-iinfo and incap_ses cookie"
        return None


class KasadaRule(ChallengeRule):
    vendor = "kasada"

    def match(self, view: ResponseView) -> str | None:
        if view.status in (403, 429) and any(h.startswith("x-kpsdk") for h in view.headers):
            return f"{view.status} with x-kpsdk-* headers"
        if view.status == 429 and "ips.js" in view.body:
            return "429 page loading ips.js"
        return None


class QratorRule(ChallengeRule):
    vendor = "qrator"

    def match(self, view: ResponseView) -> str | None:
        if "/__qrator/" in view.body:
            return f"{view.status} page loading /__qrator/"
        if "qrator" in view.headers.get("server", "") and view.status in (401, 403, 429, 503):
            return f"{view.status} from a Qrator server"
        return None


class DdosGuardRule(ChallengeRule):
    vendor = "ddos-guard"

    def match(self, view: ResponseView) -> str | None:
        server = view.headers.get("server", "")
        if "ddos-guard" in server and view.status in (403, 429, 503):
            return f"{view.status} from ddos-guard"
        if "/.well-known/ddos-guard/" in view.body:
            return "ddos-guard check page"
        return None


class YandexSmartCaptchaRule(ChallengeRule):
    vendor = "yandex-smartcaptcha"

    def match(self, view: ResponseView) -> str | None:
        if "/showcaptcha" in view.url or "/checkcaptcha" in view.url:
            return "showcaptcha URL"
        if "smartcaptcha" in view.body and view.status in (200, 403, 429):
            return "SmartCaptcha page"
        return None


DEFAULT_RULES: tuple[type[ChallengeRule], ...] = (
    CloudflareRule,
    DataDomeRule,
    PerimeterXRule,
    AkamaiRule,
    ImpervaRule,
    KasadaRule,
    QratorRule,
    DdosGuardRule,
    YandexSmartCaptchaRule,
)


class ChallengeDetector:
    """Runs vendor rules over a response.

    Args:
        rules: Rules to use; all built-in vendors when omitted.
    """

    def __init__(self, rules: Sequence[ChallengeRule] | None = None) -> None:
        self._rules = tuple(rules) if rules is not None else tuple(rule() for rule in DEFAULT_RULES)

    def detect(self, response: requests.Response) -> Challenge | None:
        """The first matching challenge, or ``None``."""
        view = ResponseView.of(response)
        for rule in self._rules:
            reason = rule.match(view)
            if reason:
                return Challenge(rule.vendor, reason)
        return None


class ChallengeHandler(Protocol):
    """Hook for solving or sidestepping a challenge.

    Called by :class:`browserlike.Session` with the challenge response. It may,
    for example, import cookies from a solver or a real browser into
    ``session.cookies`` (keeping the session identity, or the clearance will be
    rejected). Return ``True`` to retry the request once.
    """

    def __call__(self, session: requests.Session, response: requests.Response, challenge: Challenge) -> bool: ...
