"""Saving and restoring a session: identity, cookies, client hints, history.

A saved session is the HTTP equivalent of a browser profile on disk. Loading
it gives the same identity, so cookies issued to that identity (and bound to
its fingerprint by anti-bot systems) stay valid as long as the site allows.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any

from requests.cookies import RequestsCookieJar

from .identity import Identity

__all__ = ["SCHEMA_VERSION", "SessionState", "cookie_from_dict", "cookie_to_dict"]

SCHEMA_VERSION = 1


def cookie_to_dict(cookie: Cookie) -> dict[str, Any]:
    """All attributes of a cookie as plain JSON."""
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "secure": cookie.secure,
        "expires": cookie.expires,
        "discard": cookie.discard,
        "port": cookie.port,
        "port_specified": cookie.port_specified,
        "domain_initial_dot": cookie.domain_initial_dot,
        "domain_specified": cookie.domain_specified,
        "path_specified": cookie.path_specified,
        "version": cookie.version,
        "comment": cookie.comment,
        "comment_url": cookie.comment_url,
        "rfc2109": cookie.rfc2109,
        "rest": dict(getattr(cookie, "_rest", {})),  # HttpOnly, SameSite live here
    }


def cookie_from_dict(data: Mapping[str, Any]) -> Cookie:
    """Inverse of :func:`cookie_to_dict`."""
    domain = str(data.get("domain", ""))
    port = data.get("port")
    return Cookie(
        version=data.get("version", 0),
        name=str(data["name"]),
        value=data.get("value"),
        port=port,
        port_specified=bool(data.get("port_specified", port is not None)),
        domain=domain,
        domain_specified=bool(data.get("domain_specified", bool(domain))),
        domain_initial_dot=bool(data.get("domain_initial_dot", domain.startswith("."))),
        path=str(data.get("path", "/")),
        path_specified=bool(data.get("path_specified", True)),
        secure=bool(data.get("secure", False)),
        expires=data.get("expires"),
        discard=bool(data.get("discard", data.get("expires") is None)),
        comment=data.get("comment"),
        comment_url=data.get("comment_url"),
        rest=dict(data.get("rest") or {}),
        rfc2109=bool(data.get("rfc2109", False)),
    )


@dataclass(frozen=True)
class SessionState:
    """Everything needed to bring a session back.

    Attributes:
        identity: Session identity.
        engine: Name of the engine the session used.
        navigation: Navigation policy and current document.
        client_hints: Accept-CH opt-ins per origin.
        cookies: Cookies as dictionaries (see :func:`cookie_to_dict`).
        library_version: Version of the package that wrote the file.
    """

    identity: Identity
    engine: str
    navigation: Mapping[str, Any] = field(default_factory=dict)
    client_hints: Mapping[str, list[str]] = field(default_factory=dict)
    cookies: tuple[Mapping[str, Any], ...] = ()
    library_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "library_version": self.library_version,
            "engine": self.engine,
            "identity": self.identity.to_dict(),
            "navigation": dict(self.navigation),
            "client_hints": dict(self.client_hints),
            "cookies": [dict(c) for c in self.cookies],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionState:
        schema = data.get("schema")
        if schema != SCHEMA_VERSION:
            raise ValueError(f"unsupported session file schema {schema!r}, expected {SCHEMA_VERSION}")
        return cls(
            identity=Identity.from_dict(data["identity"]),
            engine=str(data.get("engine", "")),
            navigation=data.get("navigation", {}),
            client_hints=data.get("client_hints", {}),
            cookies=tuple(data.get("cookies", ())),
            library_version=str(data.get("library_version", "")),
        )

    def write(self, path: str | os.PathLike[str]) -> None:
        """Writes the state atomically (temporary file, then rename)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @classmethod
    def read(cls, path: str | os.PathLike[str]) -> SessionState:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def live_cookies(self) -> RequestsCookieJar:
        """A cookie jar with the saved cookies, expired ones dropped."""
        jar = RequestsCookieJar()
        for data in self.cookies:
            cookie = cookie_from_dict(data)
            if not cookie.is_expired():
                jar.set_cookie(cookie)
        return jar

    @staticmethod
    def dump_cookies(cookies: Iterable[Cookie]) -> tuple[dict[str, Any], ...]:
        return tuple(cookie_to_dict(c) for c in cookies)
