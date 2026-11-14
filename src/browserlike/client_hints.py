"""Per-origin client-hint opt-ins (``Accept-CH`` / ``Critical-CH``)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .sites import Origin

__all__ = ["ClientHintsStore", "parse_hint_list"]


def parse_hint_list(value: str | None) -> frozenset[str]:
    """Lower-cased tokens of an ``Accept-CH`` / ``Critical-CH`` header value."""
    if not value:
        return frozenset()
    return frozenset(token.strip().lower() for token in value.split(",") if token.strip())


class ClientHintsStore:
    """Remembers which high-entropy client hints each origin asked for.

    A browser stores the ``Accept-CH`` of a top-level navigation response per
    origin and keeps sending those hints to that origin, also after restarts.
    The latest ``Accept-CH`` replaces the earlier one; an empty value clears it.

    Args:
        supported: Hints the browser profile can send; others are ignored.
        state: Previously saved state from :meth:`to_dict`.
    """

    def __init__(self, supported: Iterable[str], state: Mapping[str, Iterable[str]] | None = None) -> None:
        self._supported = frozenset(supported)
        self._by_origin: dict[str, frozenset[str]] = {}
        for origin, hints in (state or {}).items():
            self._by_origin[origin] = frozenset(hints) & self._supported

    def hints_for(self, url: str) -> frozenset[str]:
        """Hints to send to the origin of ``url``."""
        return self._by_origin.get(Origin.of(url).serialize(), frozenset())

    def update(self, url: str, accept_ch: str | None) -> frozenset[str]:
        """Applies the ``Accept-CH`` of a navigation response; returns the new set.

        Only secure origins can opt in. ``None`` (no header) keeps the
        current set.
        """
        origin = Origin.of(url)
        key = origin.serialize()
        if accept_ch is None or not origin.potentially_trustworthy:
            return self._by_origin.get(key, frozenset())
        hints = parse_hint_list(accept_ch) & self._supported
        if hints:
            self._by_origin[key] = hints
        else:
            self._by_origin.pop(key, None)
        return hints

    def missing_critical(self, url: str, critical_ch: str | None, sent: frozenset[str]) -> frozenset[str]:
        """Critical hints the origin now wants but the request did not carry."""
        return (parse_hint_list(critical_ch) & self.hints_for(url)) - sent

    def to_dict(self) -> dict[str, list[str]]:
        return {origin: sorted(hints) for origin, hints in self._by_origin.items()}
