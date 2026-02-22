from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiopyrus.utils.context import _read_field

from .base import Filter

if TYPE_CHECKING:
    from aiopyrus.types.webhook import WebhookPayload


class FormFilter(Filter):
    """Match tasks belonging to specific form(s).

    Usage::

        @router.task_received(FormFilter(321))
        async def handle(payload, bot):
            ...

        @router.task_received(FormFilter([321, 322]))
        async def handle_multi(payload, bot):
            ...
    """

    def __init__(self, form_id: int | list[int]) -> None:
        self._ids: set[int] = {form_id} if isinstance(form_id, int) else set(form_id)

    async def __call__(self, payload: WebhookPayload) -> bool:
        return payload.task.form_id in self._ids


class StepFilter(Filter):
    """Match tasks currently at a specific workflow step.

    Usage::

        @router.task_received(StepFilter(2))
        async def on_step_2(payload, bot): ...
    """

    def __init__(self, step: int | list[int]) -> None:
        self._steps: set[int] = {step} if isinstance(step, int) else set(step)

    async def __call__(self, payload: WebhookPayload) -> bool:
        return payload.task.current_step in self._steps


class ResponsibleFilter(Filter):
    """Match tasks where the responsible person is one of the given IDs.

    Usage::

        @router.task_received(ResponsibleFilter(12345))
        async def handle(payload, bot): ...
    """

    def __init__(self, person_id: int | list[int]) -> None:
        self._ids: set[int] = {person_id} if isinstance(person_id, int) else set(person_id)

    async def __call__(self, payload: WebhookPayload) -> bool:
        r = payload.task.responsible
        return r is not None and r.id in self._ids


class TextFilter(Filter):
    """Match tasks/comments whose text contains a substring (case-insensitive by default).

    Usage::

        @router.task_received(TextFilter("оплата"))
        async def handle(payload, bot): ...
    """

    def __init__(self, substring: str, *, case_sensitive: bool = False) -> None:
        self._sub = substring if case_sensitive else substring.lower()
        self._case_sensitive = case_sensitive

    async def __call__(self, payload: WebhookPayload) -> bool:
        text = payload.task.text or ""
        if not self._case_sensitive:
            text = text.lower()
        return self._sub in text


class EventFilter(Filter):
    """Match specific webhook event types.

    Usage::

        @router.task_received(EventFilter("task_created"))
        async def on_create(payload, bot): ...
    """

    def __init__(self, *events: str) -> None:
        self._events = set(events)

    async def __call__(self, payload: WebhookPayload) -> bool:
        return payload.event in self._events


class FieldValueFilter(Filter):
    """Match tasks where a specific field has a given value.

    Uses human-readable values — the same strings you see in the Pyrus UI
    (no raw IDs, choice_ids, or dict payloads).

    Pass ``value=None`` to match tasks where the field is **empty**.

    Usage::

        # Exact value match (catalog, multiple_choice, text, person, …)
        FieldValueFilter(field_name="Request category *", value="Something is broken")
        FieldValueFilter(field_name="Problem type *", value="Report export")

        # Check that a field is empty
        FieldValueFilter(field_name="Case number *", value=None)

        # Combine with other filters
        @router.task_received(
            StepFilter(6)
            & FieldValueFilter(field_name="Request category *", value="Something is broken")
            & FieldValueFilter(field_name="Case number *", value=None)
        )
        async def handle(payload, bot): ...
    """

    def __init__(
        self,
        *,
        field_id: int | None = None,
        field_name: str | None = None,
        value: Any,
    ) -> None:
        self._field_id = field_id
        self._field_name = field_name
        self._value = value

    async def __call__(self, payload: WebhookPayload) -> bool:
        task = payload.task
        key: int | str | None = self._field_id or self._field_name
        if key is None:
            return False
        field = task.get_field(key)
        if field is None:
            return False
        human = _read_field(field)
        # value=None means "field must be empty"
        if self._value is None:
            return human is None
        # Case-insensitive string comparison (mirrors what the UI shows)
        return str(human).lower() == str(self._value).lower()


def _ensure_aware(dt: datetime) -> datetime:
    """Add UTC tzinfo to naive datetimes so comparisons always work."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class ModifiedAfterFilter(Filter):
    """Match tasks whose ``last_modified_date`` is after a given moment.

    If ``since`` is omitted it defaults to **now** — i.e., the moment the
    filter object is created (typically at import / bot startup).  This gives
    per-handler "skip old tasks" behaviour.

    Usage::

        # Only tasks modified after the bot starts
        @router.task_received(ModifiedAfterFilter())
        async def handle(payload, bot): ...

        # Only tasks modified after a specific point in time
        from datetime import datetime
        @router.task_received(ModifiedAfterFilter(since=datetime(2025, 6, 1)))
        async def handle(payload, bot): ...

        # Combine with other filters
        @router.task_received(
            StepFilter(6) & ModifiedAfterFilter()
        )
        async def on_step6_fresh(payload, bot): ...
    """

    def __init__(self, since: datetime | None = None) -> None:
        self._since = _ensure_aware(since or datetime.now(timezone.utc))

    async def __call__(self, payload: WebhookPayload) -> bool:
        ts = payload.task.last_modified_date
        if ts is None:
            return False
        return _ensure_aware(ts) > self._since


class CreatedAfterFilter(Filter):
    """Match tasks whose ``create_date`` is after a given moment.

    Defaults to **now** when ``since`` is omitted (same as :class:`ModifiedAfterFilter`).

    Usage::

        # Ignore tasks created before the bot started
        @router.task_received(CreatedAfterFilter())
        async def handle(payload, bot): ...
    """

    def __init__(self, since: datetime | None = None) -> None:
        self._since = _ensure_aware(since or datetime.now(timezone.utc))

    async def __call__(self, payload: WebhookPayload) -> bool:
        ts = payload.task.create_date
        if ts is None:
            return False
        return _ensure_aware(ts) > self._since
