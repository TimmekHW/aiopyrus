"""Magic filter — Aiogram-style F object for concise inline filters.

Examples::

    F.form_id == 321
    F.current_step == 2
    F.text.contains("оплата")
    F.responsible.id == 12345
    (F.form_id == 321) & (F.current_step == 2)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from .base import Filter

if TYPE_CHECKING:
    from aiopyrus.types.webhook import WebhookPayload


class MagicFilter(Filter):
    """Lazily-evaluated attribute-access filter on WebhookPayload.task."""

    def __init__(self, accessor: Callable[["WebhookPayload"], Any]) -> None:
        self._accessor = accessor

    # ------------------------------------------------------------------
    # Comparisons → new MagicFilter instances
    # ------------------------------------------------------------------

    def __eq__(self, other: Any) -> "MagicFilter":  # type: ignore[override]
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) == other)

    def __ne__(self, other: Any) -> "MagicFilter":  # type: ignore[override]
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) != other)

    def __lt__(self, other: Any) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) < other)

    def __le__(self, other: Any) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) <= other)

    def __gt__(self, other: Any) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) > other)

    def __ge__(self, other: Any) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) >= other)

    def contains(self, substring: str, *, case_sensitive: bool = False) -> "MagicFilter":
        acc = self._accessor
        sub = substring if case_sensitive else substring.lower()

        def _check(p: "WebhookPayload") -> bool:
            val = acc(p)
            if val is None:
                return False
            text = str(val)
            return sub in (text if case_sensitive else text.lower())

        return MagicFilter(_check)

    def in_(self, collection: Any) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) in collection)

    def is_none(self) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) is None)

    def is_not_none(self) -> "MagicFilter":
        acc = self._accessor
        return MagicFilter(lambda p: acc(p) is not None)

    # ------------------------------------------------------------------
    # Attribute navigation
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> "MagicFilter":
        acc = self._accessor

        def navigate(p: "WebhookPayload") -> Any:
            obj = acc(p)
            return getattr(obj, name, None)

        return MagicFilter(navigate)

    # ------------------------------------------------------------------
    # Filter protocol
    # ------------------------------------------------------------------

    async def __call__(self, payload: "WebhookPayload") -> bool:
        try:
            result = self._accessor(payload)
            return bool(result)
        except Exception:
            return False


class _F:
    """Entrypoint for magic filters: ``F.form_id == 321``."""

    def __getattr__(self, name: str) -> MagicFilter:
        def accessor(p: "WebhookPayload") -> Any:
            return getattr(p.task, name, None)

        return MagicFilter(accessor)

    # Also allow F.event == "comment" (top-level payload field)
    def __call__(self, accessor: Callable[["WebhookPayload"], Any]) -> MagicFilter:
        return MagicFilter(accessor)


F = _F()
