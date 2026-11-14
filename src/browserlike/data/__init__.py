"""Browser and platform facts shipped with the package.

Every fact lives in a JSON file next to this module and names its evidence:
which observation verified it and when. Code reads the files through
:func:`load`; nothing here touches the network.
"""

from __future__ import annotations

import functools
import json
from importlib import resources
from typing import Any

__all__ = ["load"]


@functools.cache
def load(name: str) -> dict[str, Any]:
    """Returns the parsed contents of a bundled data file, e.g. ``"chrome.json"``.

    The result is cached and shared, so callers must treat it as read-only.
    """
    text = resources.files(__name__).joinpath(name).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data
