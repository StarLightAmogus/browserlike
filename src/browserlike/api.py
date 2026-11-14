"""Module-level helpers mirroring ``requests.api``.

Each call opens a fresh :class:`~browserlike.Session` with a fresh random
identity and closes it afterwards, like ``requests.get`` does with its
sessions. Use a ``Session`` to keep one identity, cookies and connections.
"""

from __future__ import annotations

from typing import Any

import requests

from .sessions import Session

__all__ = ["delete", "get", "head", "options", "patch", "post", "put", "request"]


def request(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Sends a request; see ``requests.request``. Accepts ``kind=`` too."""
    with Session() as session:
        return session.request(method=method, url=url, **kwargs)


def get(url: str, params: Any = None, **kwargs: Any) -> requests.Response:
    return request("get", url, params=params, **kwargs)


def options(url: str, **kwargs: Any) -> requests.Response:
    return request("options", url, **kwargs)


def head(url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("allow_redirects", False)
    return request("head", url, **kwargs)


def post(url: str, data: Any = None, json: Any = None, **kwargs: Any) -> requests.Response:
    return request("post", url, data=data, json=json, **kwargs)


def put(url: str, data: Any = None, **kwargs: Any) -> requests.Response:
    return request("put", url, data=data, **kwargs)


def patch(url: str, data: Any = None, **kwargs: Any) -> requests.Response:
    return request("patch", url, data=data, **kwargs)


def delete(url: str, **kwargs: Any) -> requests.Response:
    return request("delete", url, **kwargs)
