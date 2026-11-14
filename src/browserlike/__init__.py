"""browserlike: ``requests`` with one consistent browser identity per session.

Drop-in use::

    import browserlike as requests

    s = requests.Session(country="RU")
    r = s.get("https://example.com/")

The TLS ClientHello, HTTP/2 settings, User-Agent, client hints and header
order all match the same real browser version, and stay the same for the
whole session.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from requests import (
    PreparedRequest,
    Request,
    Response,
    auth,
    codes,
    cookies,
    hooks,
    models,
    status_codes,
    structures,
    utils,
)

from . import adapters, exceptions
from .adapters import BrowserAdapter
from .api import delete, get, head, options, patch, post, put, request
from .challenges import Challenge, ChallengeDetector, ChallengeHandler
from .context import Kind
from .engines import available_engines
from .exceptions import (
    BrowserlikeError,
    ChallengeDetected,
    ConnectionError,  # noqa: A004 - same name as in requests on purpose
    ConnectTimeout,
    EngineUnavailable,
    HTTPError,
    IdentityConflictWarning,
    JSONDecodeError,
    ReadTimeout,
    RequestException,
    Timeout,
    TooManyRedirects,
    UnverifiedVersionError,
    URLRequired,
)
from .identity import Identity, IdentityGenerator, Locale, OperatingSystem, Platform
from .navigation import NavigationPolicy
from .sessions import Session

try:
    __version__ = _dist_version("browserlike")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0"

__all__ = [
    "BrowserAdapter",
    "BrowserlikeError",
    "Challenge",
    "ChallengeDetected",
    "ChallengeDetector",
    "ChallengeHandler",
    "ConnectTimeout",
    "ConnectionError",
    "EngineUnavailable",
    "HTTPError",
    "Identity",
    "IdentityConflictWarning",
    "IdentityGenerator",
    "JSONDecodeError",
    "Kind",
    "Locale",
    "NavigationPolicy",
    "OperatingSystem",
    "Platform",
    "PreparedRequest",
    "ReadTimeout",
    "Request",
    "RequestException",
    "Response",
    "Session",
    "Timeout",
    "TooManyRedirects",
    "URLRequired",
    "UnverifiedVersionError",
    "__version__",
    "adapters",
    "auth",
    "available_engines",
    "codes",
    "cookies",
    "delete",
    "exceptions",
    "get",
    "head",
    "hooks",
    "models",
    "options",
    "patch",
    "post",
    "put",
    "request",
    "status_codes",
    "structures",
    "utils",
]
