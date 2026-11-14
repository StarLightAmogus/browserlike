"""Exceptions and warnings.

Everything ``requests`` raises is re-exported here unchanged, so code that
catches ``requests.exceptions.*`` keeps working after switching imports. The
package's own errors derive from :class:`requests.RequestException`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,  # noqa: A004 - same name as in requests on purpose
    ConnectTimeout,
    ContentDecodingError,
    HTTPError,
    InvalidHeader,
    InvalidJSONError,
    InvalidSchema,
    InvalidURL,
    JSONDecodeError,
    MissingSchema,
    ProxyError,
    ReadTimeout,
    RequestException,
    RetryError,
    SSLError,
    StreamConsumedError,
    Timeout,
    TooManyRedirects,
    URLRequired,
)

if TYPE_CHECKING:
    from .challenges import Challenge

__all__ = [
    "BrowserlikeError",
    "BrowserlikeWarning",
    "ChallengeDetected",
    "ChunkedEncodingError",
    "ConnectTimeout",
    "ConnectionError",
    "ContentDecodingError",
    "EngineCapabilityError",
    "EngineCapabilityWarning",
    "EngineUnavailable",
    "HTTPError",
    "IdentityConflictWarning",
    "InvalidHeader",
    "InvalidJSONError",
    "InvalidSchema",
    "InvalidURL",
    "JSONDecodeError",
    "MissingSchema",
    "ProxyError",
    "ReadTimeout",
    "RequestException",
    "RetryError",
    "SSLError",
    "StreamConsumedError",
    "Timeout",
    "TooManyRedirects",
    "URLRequired",
    "UnverifiedVersionError",
]


class BrowserlikeError(RequestException):
    """Base class for errors raised by this package."""


class EngineUnavailable(BrowserlikeError):
    """No installed engine can emulate the requested identity."""


class EngineCapabilityError(BrowserlikeError):
    """The engine cannot do what the request needs (e.g. client certificates)."""


class UnverifiedVersionError(BrowserlikeError, ValueError):
    """The identity claims a browser version without verified fingerprint data."""


class ChallengeDetected(BrowserlikeError, HTTPError):
    """The response is an anti-bot challenge or block page.

    Attributes:
        challenge: What was detected.
    """

    def __init__(self, challenge: Challenge, *args: Any, **kwargs: Any) -> None:
        self.challenge = challenge
        super().__init__(f"{challenge.vendor} challenge: {challenge.reason}", *args, **kwargs)


class BrowserlikeWarning(UserWarning):
    """Base class for warnings issued by this package."""


class IdentityConflictWarning(BrowserlikeWarning):
    """A caller setting contradicts the session identity or bypasses it."""


class EngineCapabilityWarning(BrowserlikeWarning):
    """The engine ignored or approximated a setting it does not support."""
