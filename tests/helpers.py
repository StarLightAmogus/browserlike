"""Shared test helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def peet_headers(response: dict[str, Any]) -> list[tuple[str, str]]:
    """Header pairs of a tls.peet.ws report, pseudo-headers excluded, in wire order."""
    for frame in response["http2"]["sent_frames"]:
        if frame["frame_type"] == "HEADERS":
            pairs = [tuple(h.split(": ", 1)) for h in frame["headers"]]
            return [(k, v) for k, v in pairs if not k.startswith(":")]
    raise AssertionError("no HEADERS frame in the report")


def peetprint_without_psk(peetprint: str) -> str:
    """peetprint with ``pre_shared_key`` (41) removed from the extension list.

    A resumed connection adds that one extension; dropping it lets a fresh
    connection be compared with a resumed reference capture.
    """
    parts = peetprint.split("|")
    parts[-1] = "-".join(ext for ext in parts[-1].split("-") if ext != "41")
    return "|".join(parts)
