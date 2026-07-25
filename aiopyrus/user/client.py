from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import pathlib
import warnings
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

import aiofiles

from aiopyrus.api.session import PyrusSession
from aiopyrus.exceptions import PyrusFileSizeError, PyrusNotFoundError, PyrusPermissionError
from aiopyrus.types.award import AwardThreshold, MemberAwardCounter
from aiopyrus.types.catalog import Catalog, CatalogSyncResult
from aiopyrus.types.file import UploadedFile
from aiopyrus.types.form import Form
from aiopyrus.types.knowledge_base import (
    KnowledgeBaseItem,
    KnowledgeBasePermissions,
    KnowledgeBaseStructure,
)
from aiopyrus.types.task import (
    Announcement,
    ApprovalChoice,
    CommentChannel,
    Task,
    TaskAction,
    TaskList,
)
from aiopyrus.types.telephony import (
    AttachCallRecordResponse,
    CallMapping,
    RegisterCallResponse,
)
from aiopyrus.types.user import ContactsResponse, Person, Profile, Role

if TYPE_CHECKING:
    from aiopyrus.utils.context import TaskContext

from aiopyrus.types.params import (
    MemberUpdate,
    NewRole,
    NewTask,
    PersonRef,
    PrintFormItem,
    RoleUpdate,
)

log = logging.getLogger("aiopyrus.client")

_MAX_UPLOAD_SIZE = 250 * 1024 * 1024  # 250 MB — Pyrus API limit


async def _iter_json_array(chunks: AsyncIterator[str], key: str) -> AsyncIterator[dict[str, Any]]:
    """Parse a JSON response stream, yielding dicts from the array at *key*.

    Uses ``json.JSONDecoder.raw_decode`` to extract complete objects one by one
    without loading the entire response into memory.  No external dependencies.
    """
    buf = ""
    decoder = json.JSONDecoder()
    in_array = False
    min_tail = len(key) + 10

    async for chunk in chunks:
        buf += chunk
        if not in_array:
            idx = buf.find(f'"{key}"')
            if idx == -1:
                # Keep a small tail in case the key spans two chunks
                if len(buf) > min_tail:
                    buf = buf[-min_tail:]
                continue
            bracket = buf.find("[", idx)
            if bracket == -1:
                continue
            buf = buf[bracket + 1 :]
            in_array = True

        while True:
            buf = buf.lstrip(" ,\n\r\t")
            if not buf:
                break  # need more data
            if buf[0] == "]":
                return  # end of array
            try:
                obj, end = decoder.raw_decode(buf)
                yield obj
                buf = buf[end:]
            except json.JSONDecodeError:
                break  # incomplete object — need more data


def _task_has_pending_approver(task: Task, ids: set[int], *, any_step: bool) -> bool:
    """True if any of *ids* is a waiting approver on the task.

    Same matching logic as :class:`~aiopyrus.bot.filters.ApprovalPendingFilter`.
    ``any_step=False`` checks only the current step; ``True`` checks all steps.
    """
    if not task.approvals:
        return False
    if any_step:
        steps_to_check = task.approvals
    else:
        if not task.current_step:
            return False
        idx = task.current_step - 1
        if idx >= len(task.approvals):
            return False
        steps_to_check = [task.approvals[idx]]
    return any(
        entry.person.id in ids and entry.is_waiting
        for step_entries in steps_to_check
        for entry in step_entries
    )


class UserClient:
    """Full Pyrus API client acting on behalf of a user.

    Usage::

        async with UserClient(login="user@example.com", security_key="KEY") as client:
            tasks = await client.get_inbox()
            task  = await client.get_task(12345678)
            await client.comment_task(task.id, text="Привет из aiopyrus!")
    """

    def __init__(
        self,
        login: str,
        security_key: str,
        person_id: int | None = None,
        *,
        timeout: float = 60.0,
        base_url: str | None = None,
        api_version: str = "v4",
        auth_url: str | None = None,
        api_url: str | None = None,
        proxy: str | None = None,
        ssl_verify: bool = True,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
        max_concurrent: int = 10,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session = PyrusSession(
            login,
            security_key,
            person_id,
            timeout=timeout,
            base_url=base_url,
            api_version=api_version,
            auth_url=auth_url,
            api_url=api_url,
            proxy=proxy,
            ssl_verify=ssl_verify,
            requests_per_second=requests_per_second,
            requests_per_minute=requests_per_minute,
            requests_per_10min=requests_per_10min,
        )

    # ------------------------------------------------------------------
    # Context manager / lifecycle
    # ------------------------------------------------------------------

    async def _bounded(self, coro: Any) -> Any:
        """Run *coro* under the concurrency semaphore."""
        async with self._semaphore:
            return await coro

    async def auth(self) -> str:
        """Manually authenticate and obtain the access token."""
        return await self._session.auth()

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.close()

    async def __aenter__(self) -> UserClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def get_task_url(self, task_id: int) -> str:
        """Browser URL for a task.

        Ссылка на задачу в браузере::

            url = client.get_task_url(12345678)
            # → "https://pyrus.com/t#id12345678"
        """
        return f"{self._session.web_base}/t#id{task_id}"

    def get_form_url(self, form_id: int) -> str:
        """Browser URL for a form.

        Ссылка на форму в браузере::

            url = client.get_form_url(321)
            # → "https://pyrus.com/form/321"
        """
        return f"{self._session.web_base}/form/{form_id}"

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    async def get_profile(self) -> Profile:
        """GET /profile — current user profile."""
        data = await self._session.get("profile")
        return Profile.model_validate(data)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def get_task(self, task_id: int) -> Task:
        """GET /tasks/{task_id} — retrieve a task with all its comments."""
        data = await self._session.get(f"tasks/{task_id}")
        return Task.model_validate(data.get("task", data))

    async def create_task(
        self,
        *,
        # Simple task
        text: str | None = None,
        formatted_text: str | None = None,
        subject: str | None = None,
        # Form task
        form_id: int | None = None,
        fields: list[dict[str, Any]] | None = None,
        fill_defaults: bool | None = None,
        approvals: list[list[PersonRef]] | None = None,
        # People
        responsible: PersonRef | None = None,
        participants: list[PersonRef] | None = None,
        subscribers: list[PersonRef] | None = None,
        # Time
        due_date: str | None = None,
        due: str | None = None,
        duration: int | None = None,
        scheduled_date: str | None = None,
        scheduled_datetime_utc: str | None = None,
        # Organisation
        parent_task_id: int | None = None,
        list_ids: list[int] | None = None,
        attachments: list[str] | None = None,
    ) -> Task:
        """POST /tasks — create a simple or form task."""
        payload: dict[str, Any] = {}

        if form_id is not None:
            payload["form_id"] = form_id
        if text is not None:
            payload["text"] = text
        if formatted_text is not None:
            payload["formatted_text"] = formatted_text
        if subject is not None:
            payload["subject"] = subject
        if fields is not None:
            payload["fields"] = fields
        if fill_defaults is not None:
            payload["fill_defaults"] = fill_defaults
        if approvals is not None:
            payload["approvals"] = [
                [{"id": p} if isinstance(p, int) else p for p in step] for step in approvals
            ]
        if responsible is not None:
            payload["responsible"] = (
                {"id": responsible} if isinstance(responsible, int) else responsible
            )
        if participants is not None:
            payload["participants"] = [{"id": p} if isinstance(p, int) else p for p in participants]
        if subscribers is not None:
            payload["subscribers"] = [{"id": p} if isinstance(p, int) else p for p in subscribers]
        if due_date is not None:
            payload["due_date"] = due_date
        if due is not None:
            payload["due"] = due
        if duration is not None:
            payload["duration"] = duration
        if scheduled_date is not None:
            payload["scheduled_date"] = scheduled_date
        if scheduled_datetime_utc is not None:
            payload["scheduled_datetime_utc"] = scheduled_datetime_utc
        if parent_task_id is not None:
            payload["parent_task_id"] = parent_task_id
        if list_ids is not None:
            payload["list_ids"] = list_ids
        if attachments is not None:
            payload["attachments"] = [{"guid": a} for a in attachments]

        data = await self._session.post("tasks", json=payload)
        return Task.model_validate(data.get("task", data))

    async def comment_task(
        self,
        task_id: int,
        *,
        text: str | None = None,
        formatted_text: str | None = None,
        # Editing an existing comment
        edit_comment_id: int | None = None,
        # Threading — reply to a specific comment.
        # Note: maps to ``reply_note_id`` in the JSON payload, but the Pyrus
        # API treats this field as *read-only* and ignores it.  To actually
        # create a threaded reply, include a ``<quote data-noteid="...">``
        # tag inside *formatted_text*.  See ``TaskContext.reply()`` for the
        # high-level helper that does this automatically.
        reply_to_comment_id: int | None = None,
        # Workflow
        action: TaskAction | str | None = None,
        # Approvals
        approval_choice: ApprovalChoice | str | None = None,
        approvals_added: list[list[PersonRef]] | None = None,
        approvals_removed: list[PersonRef] | None = None,
        approvals_rerequested: list[PersonRef] | None = None,
        # People
        reassign_to: PersonRef | None = None,
        participants_added: list[PersonRef] | None = None,
        participants_removed: list[PersonRef] | None = None,
        subscribers_added: list[PersonRef] | None = None,
        subscribers_removed: list[PersonRef] | None = None,
        subscribers_rerequested: list[PersonRef] | None = None,
        # Form fields
        field_updates: list[dict[str, Any]] | None = None,
        # Lists
        added_list_ids: list[int] | None = None,
        removed_list_ids: list[int] | None = None,
        # Due date
        due_date: str | None = None,
        cancel_due: bool | None = None,
        # Scheduling
        scheduled_date: str | None = None,
        scheduled_datetime_utc: str | None = None,
        cancel_schedule: bool | None = None,
        # Time tracking
        spent_minutes: int | None = None,
        # Attachments
        attachments: list[str] | None = None,
        # Notification flags
        skip_notification: bool | None = None,
        skip_satisfaction: bool | None = None,
        skip_auto_reopen: bool | None = None,
        # Private comment — convenience shortcut for channel=private_channel
        private: bool | None = None,
        # External channel (send comment via email / telegram / sms …)
        channel: CommentChannel | str | None = None,
        # Send comment on behalf of a role (corp instances)
        comment_as_roles: list[PersonRef] | None = None,
    ) -> Task:
        """POST /tasks/{task_id}/comments — add a comment / modify a task.

        Returns the updated task.
        """

        def _persons(items: list[PersonRef]) -> list[dict[str, Any]]:
            return [{"id": p} if isinstance(p, int) else p for p in items]

        payload: dict[str, Any] = {}
        if text is not None:
            payload["text"] = text
        if formatted_text is not None:
            payload["formatted_text"] = formatted_text
        if edit_comment_id is not None:
            payload["edit_comment_id"] = edit_comment_id
        if reply_to_comment_id is not None:
            payload["reply_note_id"] = reply_to_comment_id
        if action is not None:
            payload["action"] = action.value if isinstance(action, TaskAction) else str(action)
        if approval_choice is not None:
            payload["approval_choice"] = (
                approval_choice.value
                if isinstance(approval_choice, ApprovalChoice)
                else str(approval_choice)
            )
        if approvals_added is not None:
            payload["approvals_added"] = [_persons(step) for step in approvals_added]
        if approvals_removed is not None:
            payload["approvals_removed"] = _persons(approvals_removed)
        if approvals_rerequested is not None:
            payload["approvals_rerequested"] = _persons(approvals_rerequested)
        if reassign_to is not None:
            payload["reassign_to"] = (
                {"id": reassign_to} if isinstance(reassign_to, int) else reassign_to
            )
        if participants_added is not None:
            payload["participants_added"] = _persons(participants_added)
        if participants_removed is not None:
            payload["participants_removed"] = _persons(participants_removed)
        if subscribers_added is not None:
            payload["subscribers_added"] = _persons(subscribers_added)
        if subscribers_removed is not None:
            payload["subscribers_removed"] = _persons(subscribers_removed)
        if subscribers_rerequested is not None:
            payload["subscribers_rerequested"] = _persons(subscribers_rerequested)
        if field_updates is not None:
            payload["field_updates"] = field_updates
        if added_list_ids is not None:
            payload["added_list_ids"] = added_list_ids
        if removed_list_ids is not None:
            payload["removed_list_ids"] = removed_list_ids
        if due_date is not None:
            payload["due_date"] = due_date
        if cancel_due is not None:
            payload["cancel_due"] = cancel_due
        if scheduled_date is not None:
            payload["scheduled_date"] = scheduled_date
        if scheduled_datetime_utc is not None:
            payload["scheduled_datetime_utc"] = scheduled_datetime_utc
        if cancel_schedule is not None:
            payload["cancel_schedule"] = cancel_schedule
        if spent_minutes is not None:
            payload["spent_minutes"] = spent_minutes
        if attachments is not None:
            payload["attachments"] = [{"guid": a} for a in attachments]
        if skip_notification is not None:
            payload["skip_notification"] = skip_notification
        if skip_satisfaction is not None:
            payload["skip_satisfaction"] = skip_satisfaction
        if skip_auto_reopen is not None:
            payload["skip_auto_reopen"] = skip_auto_reopen
        # private=True → shortcut for channel=private_channel
        if private:
            payload["channel"] = {"type": "private_channel"}
        elif channel is not None:
            payload["channel"] = {"type": str(channel)}
        if comment_as_roles is not None:
            payload["comment_as_roles"] = [
                {"id": r} if isinstance(r, int) else r for r in comment_as_roles
            ]

        data = await self._session.post(f"tasks/{task_id}/comments", json=payload)
        return Task.model_validate(data.get("task", data))

    async def delete_task(self, task_id: int) -> bool:
        """DELETE /tasks/{task_id}."""
        data = await self._session.delete(f"tasks/{task_id}")
        return bool(data.get("deleted"))

    # ------------------------------------------------------------------
    # Shortcuts for common comment actions
    # ------------------------------------------------------------------

    async def finish_task(self, task_id: int, *, text: str | None = None) -> Task:
        """Mark the task as finished (done)."""
        return await self.comment_task(task_id, action=TaskAction.finished, text=text)

    async def reopen_task(self, task_id: int, *, text: str | None = None) -> Task:
        """Reopen a finished task."""
        return await self.comment_task(task_id, action=TaskAction.reopened, text=text)

    async def approve_task(self, task_id: int, *, text: str | None = None) -> Task:
        """Approve the current approval step."""
        return await self.comment_task(task_id, approval_choice=ApprovalChoice.approved, text=text)

    async def reject_task(self, task_id: int, *, text: str | None = None) -> Task:
        """Reject the current approval step."""
        return await self.comment_task(task_id, approval_choice=ApprovalChoice.rejected, text=text)

    async def acknowledge_task(self, task_id: int, *, text: str | None = None) -> Task:
        """Acknowledge (ознакомился) the task without approval."""
        return await self.comment_task(
            task_id, approval_choice=ApprovalChoice.acknowledged, text=text
        )

    # ------------------------------------------------------------------
    # Inbox / Calendar
    # ------------------------------------------------------------------

    async def get_inbox(self, *, item_count: int | None = None) -> list[Task]:
        """GET /inbox — tasks in the current user's inbox.

        Задачи из входящих текущего пользователя.

        **Warning:** the inbox API returns sparse data — only ``id``,
        ``author``, ``responsible``, ``text``, ``create_date`` and
        ``last_modified_date``.  Fields like ``form_id``, ``current_step``,
        ``fields`` and ``approvals`` will be ``None``/empty.
        Use ``get_task(id)`` to fetch full task data when needed.
        """
        params: dict = {}
        if item_count is not None:
            params["item_count"] = item_count
        data = await self._session.get("inbox", params=params or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def get_calendar(
        self,
        *,
        start_date_utc: str | None = None,
        end_date_utc: str | None = None,
        include_meetings: bool | None = None,
        filter_mask: int | None = None,
        all_accessed_tasks: bool | None = None,
        item_count: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[Task]:
        """GET /calendar — scheduled tasks.

        Задачи из календаря.

        Args:
            start_date_utc: Начало периода — ISO 8601 datetime
                (``"2026-05-29T00:00:00Z"``).  По умолчанию — сегодня.
            end_date_utc:   Конец периода — ISO 8601 datetime.
                По умолчанию — +1 неделя.
            include_meetings: Включить календарные встречи в выдачу
                (помимо задач со сроками).
            filter_mask: Битовая маска типов задач:
                1 = Due, 2 = DueDate, 4 = DueForCurrentStep, 8 = Reminded.
                Комбинируй через ``|``: ``filter_mask=1|4``.
            all_accessed_tasks: Включить задачи из всех доступных форм.
            item_count: Макс. количество задач (не более 100).
            from_date: **Deprecated**. Старый параметр (``YYYY-MM-DD``).
                Если задан — переадресуется в ``start_date_utc`` с полуночью UTC,
                с ``DeprecationWarning``.
            to_date: **Deprecated**. Аналог ``end_date_utc``.

        Note:
            В 2026 году Pyrus поменял имена параметров
            ``from``/``to`` (только дата) на ``start_date_utc``/``end_date_utc``
            (datetime) и добавил ``include_meetings``.  Старые параметры
            ``from_date`` / ``to_date`` остаются как deprecated alias'ы
            для обратной совместимости.
        """
        params: dict[str, Any] = {}

        # Deprecated aliases → новые параметры
        if from_date is not None:
            import warnings

            warnings.warn(
                "from_date is deprecated; use start_date_utc instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            if start_date_utc is None:
                start_date_utc = f"{from_date}T00:00:00Z" if "T" not in from_date else from_date
        if to_date is not None:
            import warnings

            warnings.warn(
                "to_date is deprecated; use end_date_utc instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            if end_date_utc is None:
                end_date_utc = f"{to_date}T00:00:00Z" if "T" not in to_date else to_date

        if start_date_utc:
            params["start_date_utc"] = start_date_utc
        if end_date_utc:
            params["end_date_utc"] = end_date_utc
        if include_meetings is not None:
            # Pyrus ждёт "true"/"false" (не "y"/"n", как у других булевых
            # параметров) — подтверждено live-probe на корп Pyrus 2026.
            params["include_meetings"] = "true" if include_meetings else "false"
        if filter_mask is not None:
            params["filter_mask"] = filter_mask
        if all_accessed_tasks is not None:
            params["all_accessed_tasks"] = "y" if all_accessed_tasks else "n"
        if item_count is not None:
            params["item_count"] = item_count
        data = await self._session.get("calendar", params=params or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    # ------------------------------------------------------------------
    # Forms
    # ------------------------------------------------------------------

    async def get_forms(self) -> list[Form]:
        """GET /forms — all forms accessible to the current user."""
        data = await self._session.get("forms")
        return [Form.model_validate(f) for f in data.get("forms", [])]

    async def get_form(self, form_id: int) -> Form:
        """GET /forms/{form_id} — a single form template."""
        data = await self._session.get(f"forms/{form_id}")
        return Form.model_validate(data)

    async def get_register(
        self,
        form_id: int,
        *,
        steps: list[int] | None = None,
        task_ids: list[int] | None = None,
        include_archived: bool = False,
        # Поля, которые вернуть в каждой задаче (по умолчанию — все)
        field_ids: list[int] | None = None,
        # Сортировка: "id" — по возрастанию id, "tsk" — по умолчанию
        sort: str | None = None,
        item_count: int | None = None,
        # Фильтры по дате
        created_before: str | None = None,
        created_after: str | None = None,
        modified_before: str | None = None,
        modified_after: str | None = None,
        closed_before: str | None = None,
        closed_after: str | None = None,
        # Фильтр по просрочке:
        #   "overdue"         — задачи с истекшим общим сроком
        #   "overdue_on_step" — просрочка на текущем этапе
        #   "past_due"        — истёкший срок (общий или на этапе)
        due_filter: str | None = None,
        # Фильтр по id задачи (диапазон): например "gt12345" или "12345,12346"
        id_filter: str | None = None,
        # Фильтры по полям формы {"fld{id}": "значение"} или {"fld{id}": "gt10000,lt15000"}
        field_filters: dict[str, str] | None = None,
    ) -> list[Task]:
        """GET /forms/{form_id}/register — реестр задач по форме.

        **Note:** the register API returns ``current_step`` and ``fields``,
        but ``form_id`` is always ``None`` in the response (Pyrus omits it
        since the form is already specified in the URL).
        ``Dispatcher.start_polling()`` automatically backfills ``form_id``.
        If you call this method directly, be aware of this.

        ``approvals`` are also **not** returned — use ``get_task(id)``
        if you need approval data.

        Параметры фильтрации полей (``field_filters``):

        - Точное значение:    ``{"fld5": "Москва"}``
        - eq:                 ``{"fld5": "eq.Москва"}``
        - Диапазон (числа):   ``{"fld3": "gt10000,lt15000"}``
        - Пусто:              ``{"fld5": "empty"}``
        - Любое значение:     ``{"fld5": "*"}``

        При большом числе параметров Pyrus также принимает POST — используй
        ``get_register_post`` для такого сценария.
        """
        params: dict[str, Any] = {}
        if steps:
            params["steps"] = ",".join(str(s) for s in steps)
        if task_ids:
            params["task_ids"] = ",".join(str(i) for i in task_ids)
        if include_archived:
            params["include_archived"] = "y"
        if field_ids:
            params["field_ids"] = ",".join(str(i) for i in field_ids)
        if sort is not None:
            params["sort"] = sort
        if item_count is not None:
            params["item_count"] = item_count
        if created_before:
            params["created_before"] = created_before
        if created_after:
            params["created_after"] = created_after
        if modified_before:
            params["modified_before"] = modified_before
        if modified_after:
            params["modified_after"] = modified_after
        if closed_before:
            params["closed_before"] = closed_before
        if closed_after:
            params["closed_after"] = closed_after
        if due_filter:
            params["due_filter"] = due_filter
        if id_filter:
            params["id"] = id_filter
        if field_filters:
            params.update(field_filters)

        data = await self._session.get(f"forms/{form_id}/register", params=params or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def get_register_post(
        self,
        form_id: int,
        filters: dict[str, Any],
    ) -> list[Task]:
        """POST /forms/{form_id}/register — реестр с фильтрами через тело запроса.

        Используй когда параметров много и они не помещаются в URL.

        ``filters`` — любой словарь параметров (те же поля, что в GET).

        Пример::

            tasks = await client.get_register_post(321, {
                "fld2": "gt10000,lt15000",
                "fld1": "Москва",
                "include_archived": "y",
                "sort": "tsk",
                "steps": "1,2",
            })
        """
        data = await self._session.post(f"forms/{form_id}/register", json=filters)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def get_register_csv(
        self,
        form_id: int,
        *,
        steps: list[int] | None = None,
        include_archived: bool = False,
        field_ids: list[int] | None = None,
        item_count: int | None = None,
        created_before: str | None = None,
        created_after: str | None = None,
        modified_before: str | None = None,
        modified_after: str | None = None,
        closed_before: str | None = None,
        closed_after: str | None = None,
        due_filter: str | None = None,
        field_filters: dict[str, str] | None = None,
        delimiter: str | None = None,
    ) -> str:
        """GET /forms/{form_id}/register?format=csv — реестр в CSV.

        Export form register as CSV text.

        Возвращает строку CSV. Параметры фильтрации аналогичны ``get_register()``.

        Args:
            delimiter: Разделитель CSV (по умолчанию ``,``).

        Example::

            csv_text = await client.get_register_csv(321, steps=[1, 2])
            with open("export.csv", "w", encoding="utf-8") as f:
                f.write(csv_text)
        """
        params: dict[str, Any] = {"format": "csv"}
        if steps:
            params["steps"] = ",".join(str(s) for s in steps)
        if include_archived:
            params["include_archived"] = "y"
        if field_ids:
            params["field_ids"] = ",".join(str(i) for i in field_ids)
        if item_count is not None:
            params["item_count"] = item_count
        if created_before:
            params["created_before"] = created_before
        if created_after:
            params["created_after"] = created_after
        if modified_before:
            params["modified_before"] = modified_before
        if modified_after:
            params["modified_after"] = modified_after
        if closed_before:
            params["closed_before"] = closed_before
        if closed_after:
            params["closed_after"] = closed_after
        if due_filter:
            params["due_filter"] = due_filter
        if field_filters:
            params.update(field_filters)
        if delimiter:
            params["delimiter"] = delimiter

        response = await self._session.request_raw(
            "GET", f"forms/{form_id}/register", params=params
        )
        return response.text

    async def stream_register(
        self,
        form_id: int,
        *,
        steps: list[int] | None = None,
        include_archived: bool = False,
        field_ids: list[int] | None = None,
        item_count: int | None = None,
        created_before: str | None = None,
        created_after: str | None = None,
        modified_before: str | None = None,
        modified_after: str | None = None,
        closed_before: str | None = None,
        closed_after: str | None = None,
        due_filter: str | None = None,
        field_filters: dict[str, str] | None = None,
        predicate: Any | None = None,
    ) -> AsyncIterator[Task]:
        """Stream register tasks one by one without loading entire response.

        Потоковое чтение реестра — задачи приходят по одной, не загружая
        весь JSON в память. Полезно для реестров с 10 000+ задач.

        Принимает те же параметры фильтрации, что и ``get_register()``.

        Args:
            predicate: Optional callable ``(Task) -> bool`` — only yield tasks
                       where ``predicate(task)`` returns True.  Saves memory
                       by skipping non-matching tasks during streaming.
                       Use for conditions the server can't filter (field values,
                       combined logic).  For step filtering use ``steps=``.

        Example::

            async for task in client.stream_register(321, steps=[1, 2]):
                print(task.id, task.current_step)

            # Client-side filter — e.g. only tasks with text
            async for task in client.stream_register(321,
                predicate=lambda t: t.text):
                process(task)
        """
        params: dict[str, Any] = {}
        if steps:
            params["steps"] = ",".join(str(s) for s in steps)
        if include_archived:
            params["include_archived"] = "y"
        if field_ids:
            params["field_ids"] = ",".join(str(i) for i in field_ids)
        if item_count is not None:
            params["item_count"] = item_count
        if created_before:
            params["created_before"] = created_before
        if created_after:
            params["created_after"] = created_after
        if modified_before:
            params["modified_before"] = modified_before
        if modified_after:
            params["modified_after"] = modified_after
        if closed_before:
            params["closed_before"] = closed_before
        if closed_after:
            params["closed_after"] = closed_after
        if due_filter:
            params["due_filter"] = due_filter
        if field_filters:
            params.update(field_filters)

        chunks = self._session.stream_get(f"forms/{form_id}/register", params=params or None)
        async for obj in _iter_json_array(chunks, "tasks"):
            task = Task.model_validate(obj)
            if predicate is None or predicate(task):
                yield task

    # ------------------------------------------------------------------
    # Event log (on-premise only)
    # ------------------------------------------------------------------

    async def get_event_history(
        self,
        *,
        after: int | None = None,
        count: int | None = None,
    ) -> str:
        """GET /eventhistory — журнал событий безопасности (CSV, on-premise).

        Security event log: logins, password changes, role modifications,
        file operations, and more (113 event types).
        Available only on Pyrus server (on-premise) instances.

        Args:
            after: Вернуть события с ID >= этого значения.
            count: Количество событий (макс. 100 000).

        Raises:
            PyrusPermissionError: ``403 access_denied`` when the account lacks
                the security-log access role. Being on a Pyrus server
                (on-premise) instance alone is **not** sufficient — an admin
                must explicitly grant the role on top of on-premise access.
        """
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if count is not None:
            params["count"] = count
        resp = await self._session.request_raw("GET", "eventhistory", params=params)
        return resp.text

    async def get_file_access_history(
        self,
        *,
        after: int | None = None,
        count: int | None = None,
    ) -> str:
        """GET /fileaccesshistory — история доступа к файлам (CSV, on-premise).

        File upload/download activity log.
        Available only on Pyrus server (on-premise) instances.

        Args:
            after: Вернуть события с ID >= этого значения.
            count: Количество событий (макс. 100 000).

        Raises:
            PyrusPermissionError: ``403 access_denied`` when the account lacks
                the security-log access role. Being on a Pyrus server
                (on-premise) instance alone is **not** sufficient — an admin
                must explicitly grant the role on top of on-premise access.
        """
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if count is not None:
            params["count"] = count
        resp = await self._session.request_raw("GET", "fileaccesshistory", params=params)
        return resp.text

    async def get_task_access_history(
        self,
        *,
        after: int | None = None,
        count: int | None = None,
    ) -> str:
        """GET /taskaccesshistory — история доступа к задачам (CSV, on-premise).

        Task access monitoring log.
        Available only on Pyrus server (on-premise) instances.

        Args:
            after: Вернуть события с ID >= этого значения.
            count: Количество событий (макс. 100 000).

        Raises:
            PyrusPermissionError: ``403 access_denied`` when the account lacks
                the security-log access role. Being on a Pyrus server
                (on-premise) instance alone is **not** sufficient — an admin
                must explicitly grant the role on top of on-premise access.
        """
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if count is not None:
            params["count"] = count
        resp = await self._session.request_raw("GET", "taskaccesshistory", params=params)
        return resp.text

    async def get_task_export_history(
        self,
        *,
        after: int | None = None,
        count: int | None = None,
    ) -> str:
        """GET /taskexporthistory — история экспорта задач (CSV, on-premise).

        Task export activity log.
        Available only on Pyrus server (on-premise) instances.

        Args:
            after: Вернуть события с ID >= этого значения.
            count: Количество событий (макс. 100 000).

        Raises:
            PyrusPermissionError: ``403 access_denied`` when the account lacks
                the security-log access role. Being on a Pyrus server
                (on-premise) instance alone is **not** sufficient — an admin
                must explicitly grant the role on top of on-premise access.
        """
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if count is not None:
            params["count"] = count
        resp = await self._session.request_raw("GET", "taskexporthistory", params=params)
        return resp.text

    async def get_registry_download_history(
        self,
        *,
        after: int | None = None,
        count: int | None = None,
    ) -> str:
        """GET /registrydownloadhistory — история скачивания реестров (CSV, on-premise).

        Form registry download activity log.
        Available only on Pyrus server (on-premise) instances.

        Args:
            after: Вернуть события с ID >= этого значения.
            count: Количество событий (макс. 100 000).

        Raises:
            PyrusPermissionError: ``403 access_denied`` when the account lacks
                the security-log access role. Being on a Pyrus server
                (on-premise) instance alone is **not** sufficient — an admin
                must explicitly grant the role on top of on-premise access.
        """
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        if count is not None:
            params["count"] = count
        resp = await self._session.request_raw("GET", "registrydownloadhistory", params=params)
        return resp.text

    async def search_tasks(
        self,
        forms: dict[int, list[int] | None],
        *,
        field_filters: dict[str, str] | None = None,
        include_archived: bool = False,
        item_count: int | None = None,
    ) -> list[Task]:
        """Search tasks across multiple forms in parallel (documented API v4).

        Runs ``get_register()`` for every form concurrently via
        ``asyncio.gather`` and merges the results.

        Args:
            forms:  ``{form_id: [step, ...]}`` — steps to query per form.
                    Pass ``None`` instead of a list to fetch all steps.
            field_filters: ``{"fld{id}": "value"}`` filters applied to **every** form.
            include_archived: include archived tasks.
            item_count: max items **per form** (not total).

        Returns:
            Combined list of ``Task`` objects.  If a form query fails
            (e.g. 403 / 404), it is logged and skipped — other forms
            still return results.

        Example::

            tasks = await client.search_tasks({
                100001: [4, 5],   # Форма «Заявки» → шаги согласования
                100002: [3],      # Форма «Задачи» → шаг 3
                100003: None,     # Форма «Инциденты» → все шаги
            })
        """
        coros = [
            self.get_register(
                form_id,
                steps=steps,
                field_filters=field_filters,
                include_archived=include_archived,
                item_count=item_count,
            )
            for form_id, steps in forms.items()
        ]
        batches = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        result: list[Task] = []
        for form_id, batch in zip(forms, batches, strict=True):
            if isinstance(batch, BaseException):
                log.warning("search_tasks: form %d failed: %s", form_id, batch)
                continue
            result.extend(batch)
        return result

    async def get_registers(
        self,
        form_ids: list[int],
        **kwargs: Any,
    ) -> dict[int, list[Task]]:
        """Fetch registers for multiple forms in parallel.

        Реестры нескольких форм параллельно. Формы с ошибками (403/404)
        пропускаются и логируются — остальные возвращаются.

        Args:
            form_ids: Список ID форм.
            **kwargs: Параметры ``get_register()`` (steps, field_ids, …).

        Returns:
            ``{form_id: [Task, ...]}`` — dict с задачами по каждой форме.

        Example::

            regs = await client.get_registers([100001, 100002, 100003])
            for form_id, tasks in regs.items():
                print(f"Form {form_id}: {len(tasks)} tasks")
        """

        async def _one(fid: int) -> tuple[int, list[Task]]:
            return fid, await self.get_register(fid, **kwargs)

        coros = [_one(fid) for fid in form_ids]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        out: dict[int, list[Task]] = {}
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                log.warning("get_registers: form %d failed: %s", form_ids[i], r)
            else:
                out[r[0]] = r[1]
        return out

    # ------------------------------------------------------------------
    # Task Lists
    # ------------------------------------------------------------------

    async def get_lists(self) -> list[TaskList]:
        """GET /lists — все списки задач (проекты / канбан-доски).

        All task lists accessible to the current user.
        """
        data = await self._session.get("lists")
        return [TaskList.model_validate(lst) for lst in data.get("lists", [])]

    async def get_task_list(
        self,
        list_id: int,
        *,
        item_count: int | None = None,
        include_archived: bool = False,
    ) -> list[Task]:
        """POST /lists/{list_id}/tasks — задачи из конкретного списка (POST вариант).

        Tasks in a specific list.

        Note:
            Pyrus принимает и ``GET /lists/{list_id}/tasks`` без тела —
            обёртка для GET-варианта называется :meth:`get_list_tasks`.
            POST-вариант здесь используется когда параметры фильтрации
            могут быть громоздкими.

            Pyrus also accepts ``GET /lists/{list_id}/tasks`` without a
            body — use :meth:`get_list_tasks` for the GET variant.
        """
        payload: dict[str, Any] = {}
        if item_count is not None:
            payload["item_count"] = item_count
        if include_archived:
            payload["include_archived"] = True
        data = await self._session.post(f"lists/{list_id}/tasks", json=payload or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def get_list(self, list_id: int) -> TaskList:
        """GET /lists/{list_id} — получить один список задач по ID.

        Get a single task list (project / kanban board) by ID.

        Example::

            lst = await client.get_list(42)
            print(lst.name, lst.list_type, len(lst.children))
        """
        data = await self._session.get(f"lists/{list_id}")
        return TaskList.model_validate(data)

    async def get_list_tasks(
        self,
        list_id: int,
        *,
        item_count: int | None = None,
        include_archived: bool = False,
    ) -> list[Task]:
        """GET /lists/{list_id}/tasks — задачи из конкретного списка (REST вариант).

        Tasks in a specific list (REST GET variant).

        REST-эквивалент :meth:`get_task_list` (POST). Параметры
        передаются как query-string — выбирай GET, когда параметров
        мало; POST — когда нужен большой filter payload.

        Example::

            tasks = await client.get_list_tasks(42, item_count=100)
        """
        params: dict[str, Any] = {}
        if item_count is not None:
            params["item_count"] = item_count
        if include_archived:
            params["include_archived"] = "y"
        data = await self._session.get(f"lists/{list_id}/tasks", params=params or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def update_list(
        self,
        list_id: int,
        *,
        name: str | None = None,
        member_ids: list[int] | None = None,
        manager_ids: list[int] | None = None,
        added_member_ids: list[int] | None = None,
        removed_member_ids: list[int] | None = None,
    ) -> TaskList:
        """POST /lists/{list_id} — обновить метаданные списка задач.

        Update task list metadata (name, members, managers).

        Note:
            Pyrus использует один и тот же URL для **POST /lists/{id}**
            (обновление метаданных, тело = ``{name, member_ids, ...}``)
            и для :meth:`get_task_list` (получение задач,
            ``POST /lists/{id}/tasks``).  Здесь — именно метаданные.

            Pyrus uses the same URL pattern for metadata update and
            task listing — disambiguated by sub-path ``/tasks``.

        Args:
            list_id: ID списка.
            name: Новое название.
            member_ids: Полная замена участников.
            manager_ids: Полная замена менеджеров.
            added_member_ids: Добавить участников (incremental).
            removed_member_ids: Удалить участников (incremental).

        Example::

            await client.update_list(42, name="Архив 2026", added_member_ids=[100500])
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if member_ids is not None:
            payload["member_ids"] = member_ids
        if manager_ids is not None:
            payload["manager_ids"] = manager_ids
        if added_member_ids is not None:
            payload["added_member_ids"] = added_member_ids
        if removed_member_ids is not None:
            payload["removed_member_ids"] = removed_member_ids
        data = await self._session.post(f"lists/{list_id}", json=payload)
        return TaskList.model_validate(data)

    # ------------------------------------------------------------------
    # Internal WCF API (experimental / on-premise)
    # ------------------------------------------------------------------

    async def search_tasks_internal(
        self,
        *,
        approver_ids: list[int] | None = None,
        participant_ids: list[int] | None = None,
        project_ids: list[int] | None = None,
        catalog_ids: list[int] | None = None,
        catalog_item_ids: list[int] | None = None,
        search_string: str = "",
        search_exclude: str = "",
        include_closed: bool = False,
        max_items: int = 200,
        sort_type: int = 7,
        activity_state: int = 1,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """**EXPERIMENTAL** — internal Pyrus WCF endpoint, NOT part of public API v4.

        ``POST /Services/ClientServiceV2.svc/GetTaskList``

        Uses the same internal API as the Pyrus web interface for
        **cross-form** task search with approver/participant filtering —
        something not available in the documented API v4.

        .. warning::

            - Undocumented, may break on any Pyrus update without notice.
            - Tested on Pyrus **on-premise (2024)**; SaaS (2026) may differ.
            - Response format differs from API v4 — returns **raw dict**.
            - Base URL is derived from ``auth_url``; for SaaS you may need
              to override via ``extra_params``.

        Args:
            approver_ids:     Filter by approver person/role IDs.
            participant_ids:  Filter by participant IDs.
            project_ids:      Filter by project (≈ form) IDs.
            catalog_ids:      Filter by catalog IDs.
            catalog_item_ids: Filter by catalog item IDs.
            search_string:    Full-text search query.
            search_exclude:   Exclude tasks containing this text.
            include_closed:   Include closed/archived tasks.
            max_items:        Maximum number of tasks to return (default 200).
            sort_type:        Sort order (7 = default UI sort).
            activity_state:   1 = active only, 0 = all.
            extra_params:     Arbitrary extra keys merged into ``Params``.

        Returns:
            Raw response dict from the internal API.

        Example::

            # Все задачи на согласовании у роли 42
            data = await client.search_tasks_internal(
                approver_ids=[42],
            )

            # Достать task_id и запросить через публичный API
            for item in data.get("Tasks", data.get("tasks", [])):
                task_id = item.get("Id") or item.get("id")
                if task_id:
                    task = await client.get_task(task_id)
        """
        warnings.warn(
            "search_tasks_internal() uses an undocumented Pyrus WCF endpoint. "
            "It may break on any Pyrus update.",
            stacklevel=2,
        )

        # Derive base URL from auth_url: https://pyrus.example.com/api/v4/auth → https://pyrus.example.com
        parsed = urlparse(self._session._auth_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        url = f"{base}/Services/ClientServiceV2.svc/GetTaskList"

        params: dict[str, Any] = {
            "Type": 4,
            "MaxItemCount": max_items,
            "MaxGroupItemCount": 50,
            "InboxGroupId": None,
            "SearchString": search_string,
            "SearchExclude": search_exclude,
            "ParticipantIds": participant_ids or [],
            "ApproverIds": approver_ids or [],
            "ProjectIds": project_ids or [],
            "CatalogIds": catalog_ids or [],
            "CatalogItemIds": catalog_item_ids or [],
            "IncludeClosedTasks": include_closed,
            "SortType": sort_type,
            "ActivityState": activity_state,
            "SnippetFragmentSize": 150,
        }
        if extra_params:
            params.update(extra_params)

        body: dict[str, Any] = {
            "req": {
                "Params": params,
                "Locale": 1,
            },
        }

        log.debug("→ POST %s (experimental WCF)", url)

        # Lazy auth
        if not self._session._access_token:
            await self._session.auth()

        client = await self._session._get_client()
        response = await client.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {self._session._access_token}"},
        )

        try:
            data: dict = response.json()
        except Exception:
            data = {"_raw_text": response.text, "_status": response.status_code}

        log.debug("← %d  keys=%s", response.status_code, list(data.keys()))
        return data

    async def find_tasks_by_field(
        self,
        form_id: int,
        field: int | str,
        value: str,
        *,
        item_count: int | None = None,
        include_archived: bool = True,
    ) -> list[Task]:
        """Найти задачи формы по значению поля (``GET /register?fld{id}=...``).

        Find tasks of a form by a field value.

        Использует документированный фильтр реестра ``fld{field_id}=value``.
        Совпадение — **по префиксу** (``"ABC-00012"`` найдётся по ``"ABC-000"``,
        но **не** по ``"0012"``), регистр учитывается сервером.

        Args:
            form_id: ID формы, в которой ищем.
            field: ID поля (``int``) или его **имя** из интерфейса (``str``) —
                имя резолвится в ID через определение формы.
            value: Значение (или его начало) для поиска.
            item_count: Максимум задач в ответе.
            include_archived: Включать закрытые/архивные задачи (по умолчанию да —
                связанные задачи часто уже закрыты).

        Returns:
            Список найденных ``Task`` (данные реестра — без ``approvals``).

        Raises:
            KeyError: имя поля не найдено в определении формы.

        Example::

            # По ID поля
            tasks = await client.find_tasks_by_field(321, 295, "ABC-00012")

            # По имени поля
            tasks = await client.find_tasks_by_field(321, "Номер тикета", "ABC-00012")
        """
        field_id = await self._resolve_field_id(form_id, field)
        params: dict[str, Any] = {f"fld{field_id}": value}
        if item_count is not None:
            params["item_count"] = item_count
        if include_archived:
            params["include_archived"] = "y"
        data = await self._session.get(f"forms/{form_id}/register", params=params)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def _resolve_field_id(self, form_id: int, field: int | str) -> int:
        """Field ID as-is, or resolve a field **name** via the form definition."""
        if isinstance(field, int):
            return field
        form = await self.get_form(form_id)

        def walk(fields: list[Any]) -> int | None:
            for f in fields:
                if (f.name or "") == field or (f.code or "") == field:
                    return f.id
                info = f.info if isinstance(f.info, dict) else {}
                sub_raw = info.get("fields") or []
                from aiopyrus.types.form import FormField as FF

                sub: list[Any] = []
                for s in sub_raw:
                    if isinstance(s, dict):
                        with contextlib.suppress(Exception):
                            sub.append(FF.model_validate(s))
                if sub:
                    got = walk(sub)
                    if got is not None:
                        return got
            return None

        found = walk(form.fields)
        if found is None:
            raise KeyError(f"Field {field!r} not found in form {form_id}.")
        return found

    async def find_pending_approvals(
        self,
        approver_ids: int | list[int],
        *,
        forms: int | list[int],
        steps: list[int] | int | None = None,
        any_step: bool = True,
    ) -> list[Task]:
        """Найти задачи, ожидающие согласования у указанных approver.

        Find tasks pending approval by the given person/role IDs.

        Реестр (``GET /forms/{id}/register``) **не отдаёт** ``approvals``,
        поэтому фильтрация по approver на уровне реестра невозможна напрямую.
        Этот helper делает two-step:

        1. ``get_registers(forms, steps)`` — собрать задачи форм (без approvals);
        2. ``get_tasks(...)`` — обогатить каждую полными данными (с approvals);
        3. отфильтровать по approver, ожидающему согласования.

        Args:
            approver_ids: Один ID или список (person_id **или** role_id).
                Совпадение по любому из них (OR). Если согласование назначено
                на роль — передавай **role_id**, не person_id членов роли.
            forms: Форма или список форм для поиска (обязательно —
                реестр требует ``form_id``). Для cross-form поиска без
                перечисления форм см. :meth:`search_tasks_internal`.
            steps: Ограничить шагами реестра (ускоряет — меньше задач
                на обогащение). ``None`` — все шаги.
            any_step: Если ``True`` (по умолчанию) — approver ждёт на
                **любом** шаге маршрута. ``False`` — только на текущем шаге
                задачи.

        Returns:
            Список ``Task`` (обогащённых, с ``approvals``), где хотя бы один
            из ``approver_ids`` ожидает согласования.

        Example::

            # Все задачи форм 321 и 322, ждущие согласования у роли 5555 или 6666
            tasks = await client.find_pending_approvals(
                [5555, 6666], forms=[321, 322]
            )
            for t in tasks:
                print(t.id, t.current_step, t.get_approver_names(t.current_step))
        """
        ids: set[int] = {approver_ids} if isinstance(approver_ids, int) else set(approver_ids)
        form_ids = [forms] if isinstance(forms, int) else list(forms)
        step_list = [steps] if isinstance(steps, int) else steps

        # 1. Реестры форм (без approvals) — параллельно
        regs = await self.get_registers(form_ids, steps=step_list)
        task_ids: list[int] = []
        for tasks in regs.values():
            task_ids.extend(t.id for t in tasks)
        if not task_ids:
            return []

        # 2. Обогатить полными данными (approvals) — батч
        enriched = await self.get_tasks(task_ids)

        # 3. Фильтр по approver, ожидающему согласования
        result: list[Task] = []
        for task in enriched:
            if _task_has_pending_approver(task, ids, any_step=any_step):
                result.append(task)
        return result

    async def get_form_permissions(self, form_id: int) -> dict[str, Any]:
        """GET /forms/{form_id}/permissions."""
        return await self._session.get(f"forms/{form_id}/permissions")

    async def set_form_permissions(
        self, form_id: int, permissions: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /forms/{form_id}/permissions — set user access levels."""
        return await self._session.post(
            f"forms/{form_id}/permissions", json={"permissions": permissions}
        )

    # ------------------------------------------------------------------
    # Catalogs
    # ------------------------------------------------------------------

    async def get_catalogs(self) -> list[Catalog]:
        """GET /catalogs — all catalogs (without items)."""
        data = await self._session.get("catalogs")
        return [Catalog.model_validate(c) for c in data.get("catalogs", [])]

    async def get_catalog(self, catalog_id: int) -> Catalog:
        """GET /catalogs/{catalog_id} — full catalog with all items."""
        data = await self._session.get(f"catalogs/{catalog_id}")
        return Catalog.model_validate(data)

    async def create_catalog(
        self,
        name: str,
        headers: list[str | dict[str, Any]],
        items: list[list[str]],
    ) -> Catalog:
        """PUT /catalogs — create a new catalog."""
        catalog_headers = [{"name": h} if isinstance(h, str) else h for h in headers]
        catalog_items = [{"values": row} for row in items]
        data = await self._session.put(
            "catalogs",
            json={"name": name, "catalog_headers": catalog_headers, "items": catalog_items},
        )
        return Catalog.model_validate(data)

    async def sync_catalog(
        self,
        catalog_id: int,
        *,
        headers: list[str | dict[str, Any]],
        items: list[list[str]],
        apply: bool = True,
    ) -> CatalogSyncResult:
        """POST /catalogs/{catalog_id} — replace all catalog items."""
        catalog_headers = [{"name": h} if isinstance(h, str) else h for h in headers]
        catalog_items = [{"values": row} for row in items]
        data = await self._session.post(
            f"catalogs/{catalog_id}",
            json={
                "apply": apply,
                "catalog_headers": catalog_headers,
                "items": catalog_items,
            },
        )
        return CatalogSyncResult.model_validate(data)

    async def update_catalog(
        self,
        catalog_id: int,
        *,
        upsert: list[list[str]] | None = None,
        delete: list[str] | None = None,
    ) -> CatalogSyncResult:
        """POST /catalogs/{catalog_id}/diff — insert/update/delete specific items."""
        payload: dict[str, Any] = {}
        if upsert is not None:
            payload["upsert"] = [{"values": row} for row in upsert]
        if delete is not None:
            payload["delete"] = delete
        data = await self._session.post(f"catalogs/{catalog_id}/diff", json=payload)
        return CatalogSyncResult.model_validate(data)

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def upload_file(
        self,
        file: BinaryIO | bytes | pathlib.Path | str,
        filename: str | None = None,
    ) -> UploadedFile:
        """POST /files/upload — upload a file and return its GUID."""
        if isinstance(file, (str, pathlib.Path)):
            path = pathlib.Path(file)
            filename = filename or path.name
            size = path.stat().st_size
            if size > _MAX_UPLOAD_SIZE:
                raise PyrusFileSizeError(
                    f"File size {size / 1024 / 1024:.1f} MB exceeds "
                    f"the maximum upload size of 250 MB"
                )
            async with aiofiles.open(path, "rb") as fh:
                file_bytes = await fh.read()
        elif isinstance(file, bytes):
            file_bytes = file
        else:
            # BinaryIO — check size via seek if possible
            if hasattr(file, "seek") and hasattr(file, "tell"):
                pos = file.tell()
                file.seek(0, 2)
                size = file.tell()
                file.seek(pos)
                if size > _MAX_UPLOAD_SIZE:
                    raise PyrusFileSizeError(
                        f"File size {size / 1024 / 1024:.1f} MB exceeds "
                        f"the maximum upload size of 250 MB"
                    )
            file_bytes = file.read()

        filename = filename or "upload"
        if len(file_bytes) > _MAX_UPLOAD_SIZE:
            raise PyrusFileSizeError(
                f"File size {len(file_bytes) / 1024 / 1024:.1f} MB exceeds "
                f"the maximum upload size of 250 MB"
            )
        files = {"file": (filename, file_bytes)}
        data = await self._session.post("files/upload", files=files)
        return UploadedFile.model_validate(data)

    async def download_file(self, file_id: str) -> bytes:
        """GET /files/download/{file_id} — download a file as bytes."""
        response = await self._session.request_raw(
            "GET", f"files/download/{file_id}", use_files_url=True
        )
        return response.content

    async def download_print_form(self, task_id: int, print_form_id: int) -> bytes:
        """GET /tasks/{task_id}/print_forms/{print_form_id} — скачать печатную форму (PDF).

        Download a print form as PDF bytes.

        Args:
            task_id: ID задачи.
            print_form_id: ID шаблона печатной формы (из ``Form.print_forms``).

        Returns:
            Сырые байты PDF.
        """
        response = await self._session.request_raw(
            "GET", f"tasks/{task_id}/print_forms/{print_form_id}"
        )
        return response.content

    async def download_print_forms(
        self,
        items: list[PrintFormItem],
    ) -> list[bytes | BaseException]:
        """Скачать несколько печатных форм параллельно.

        Download multiple print forms in parallel.

        Args:
            items: Список ``PrintFormItem(task_id=..., print_form_id=...)`` объектов.

        Returns:
            Список байтов PDF или BaseException для ошибок.

        Example::

            from aiopyrus.types.params import PrintFormItem

            pdfs = await client.download_print_forms([
                PrintFormItem(task_id=12345678, print_form_id=1),
                PrintFormItem(task_id=12345679, print_form_id=2),
            ])
        """
        coros = [self.download_print_form(item.task_id, item.print_form_id) for item in items]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return list(results)

    # ------------------------------------------------------------------
    # Contacts & Members
    # ------------------------------------------------------------------

    async def get_contacts(self, *, include_inactive: bool = False) -> ContactsResponse:
        """GET /contacts — contacts grouped by organization."""
        params = {"include_inactive": "true"} if include_inactive else None
        data = await self._session.get("contacts", params=params)
        return ContactsResponse.model_validate(data)

    async def get_members(self) -> list[Person]:
        """GET /members — all organization members."""
        data = await self._session.get("members")
        return [Person.model_validate(m) for m in data.get("members", [])]

    async def get_member(self, member_id: int) -> Person:
        """GET /members/{member_id}."""
        data = await self._session.get(f"members/{member_id}")
        return Person.model_validate(data)

    async def create_member(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        position: str | None = None,
        department_id: int | None = None,
    ) -> Person:
        """POST /members — add a new member to the organization."""
        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
        }
        if position:
            payload["position"] = position
        if department_id is not None:
            payload["department_id"] = department_id
        data = await self._session.post("members", json=payload)
        return Person.model_validate(data)

    async def update_member(self, member_id: int, **fields: Any) -> Person:
        """PUT /members/{member_id} — update member profile fields."""
        data = await self._session.put(f"members/{member_id}", json=fields)
        return Person.model_validate(data)

    async def set_avatar(self, member_id: int, file_guid: str) -> Person:
        """POST /members/{member_id}/avatar — установить аватар.

        Set a member's avatar.

        Args:
            member_id: ID сотрудника.
            file_guid: GUID ранее загруженного файла (из ``upload_file()``).

        Example::

            uploaded = await client.upload_file("photo.jpg")
            person = await client.set_avatar(100500, uploaded.guid)
        """
        data = await self._session.post(
            f"members/{member_id}/avatar",
            json={"file_guid": file_guid},
        )
        return Person.model_validate(data)

    async def block_member(self, member_id: int) -> bool:
        """DELETE /members/{member_id} — block a member."""
        data = await self._session.delete(f"members/{member_id}")
        return bool(data.get("banned"))

    async def find_member(self, name: str | int) -> Person | None:
        """Найти сотрудника по имени, email, логину или числовому person_id.

        Find a member by name, email, login or numeric person_id.

        Поведение / Behaviour:

        - ``int`` или строка из цифр (``"100500"``) → прямой ``get_member()`` по ID.
          Возвращает ``None`` если такого ID нет или нет прав на чтение.
        - ``str`` → частичное совпадение (регистронезависимое) по полному имени,
          имени, фамилии, логину или email. Возвращает первое совпадение.

        Числовая строка трактуется как ID — это типичный кейс, когда person_id
        приходит из БД/CSV/JSON в строковом виде.

        Example::

            person = await client.find_member("Колбасенко")             # by name
            person = await client.find_member("kolbasenko@example.com")  # by email
            person = await client.find_member(100500)                   # by id (int)
            person = await client.find_member("100500")                 # by id (str)
        """
        # Numeric → person_id direct lookup.
        if isinstance(name, int) or (isinstance(name, str) and name.strip().lstrip("-").isdigit()):
            try:
                return await self.get_member(int(name))
            except (PyrusNotFoundError, PyrusPermissionError):
                return None

        query = name.lower()
        members = await self.get_members()
        for m in members:
            full = f"{m.first_name} {m.last_name}".lower()
            rev = f"{m.last_name} {m.first_name}".lower()
            if (
                query in full
                or query in rev
                or query in (m.first_name or "").lower()
                or query in (m.last_name or "").lower()
                or query in (m.email or "").lower()
            ):
                return m
        return None

    async def find_members(self, name: str) -> list[Person]:
        """Найти всех сотрудников с частичным совпадением имени.

        Используй когда имя неоднозначно и нужно выбрать из нескольких.
        """
        query = name.lower()
        members = await self.get_members()
        result = []
        for m in members:
            full = f"{m.first_name} {m.last_name}".lower()
            rev = f"{m.last_name} {m.first_name}".lower()
            if (
                query in full
                or query in rev
                or query in (m.first_name or "").lower()
                or query in (m.last_name or "").lower()
                or query in (m.email or "").lower()
            ):
                result.append(m)
        return result

    async def find_member_by_id(self, person_id: int | str) -> Person | None:
        """Найти сотрудника **строго** по числовому ``person_id``.

        Find a member by ``person_id`` only — strict, unambiguous lookup.

        В отличие от :meth:`find_member` (умный поиск по имени/email/ID
        с подстрокой), этот метод смотрит **только** на численный ID.
        Возвращает ``None`` если такого ID нет или нет прав на чтение
        (никаких исключений — симметрично :meth:`find_member_by_email`).

        Принимает ``int`` или строку из цифр (``"100500"`` из БД / CSV).

        Example::

            # 3 тёзки в компании — выбрать конкретного по ID
            person = await client.find_member_by_id(192431)
            person = await client.find_member_by_id("192431")  # str из БД
        """
        if isinstance(person_id, str):
            stripped = person_id.strip()
            if not stripped.lstrip("-").isdigit():
                raise ValueError(
                    f"find_member_by_id expects a numeric value, got {person_id!r}. "
                    f"Use find_member() for name/email search."
                )
            person_id = int(stripped)
        try:
            return await self.get_member(person_id)
        except (PyrusNotFoundError, PyrusPermissionError):
            return None

    async def find_member_by_email(self, email: str) -> Person | None:
        """Find a member by exact email address (case-insensitive).

        Поиск участника по точному email (регистронезависимый).

        Example::

            person = await client.find_member_by_email("kolbasenko@example.com")
            if person:
                print(person.full_name)
        """
        query = email.lower()
        members = await self.get_members()
        for m in members:
            if m.email and m.email.lower() == query:
                return m
        return None

    async def find_members_by_emails(self, emails: list[str]) -> dict[str, Person]:
        """Find members by email addresses. Returns ``{email: Person}`` dict.

        Поиск участников по email. Возвращает ``{email: Person}`` для найденных.

        Example::

            found = await client.find_members_by_emails(["a@ex.com", "b@ex.com"])
            for email, person in found.items():
                print(f"{email} → {person.full_name}")
        """
        query = {e.lower() for e in emails}
        members = await self.get_members()
        result: dict[str, Person] = {}
        for m in members:
            if m.email and m.email.lower() in query:
                result[m.email.lower()] = m
        return result

    async def task_context(self, task_id: int) -> TaskContext:
        """Получить задачу и вернуть TaskContext — aiogram-стайл обёртку.

        Shortcut для::

            task = await client.get_task(task_id)
            ctx  = task.context(client)

        Example::

            ctx = await client.task_context(12345678)

            description = ctx["Описание"]
            ctx.set("Статус задачи", "В работе").set("Исполнитель", "Ivanov")
            await ctx.answer("Задача принята в работу")

            ctx.set("Статус задачи", "Выполнена")
            await ctx.approve("Обработка завершена")
        """
        from aiopyrus.utils.context import TaskContext

        task = await self.get_task(task_id)
        return TaskContext(task, self)

    async def task_contexts(self, task_ids: list[int]) -> list[TaskContext]:
        """Получить несколько TaskContext параллельно — батч-версия ``task_context()``.

        Fetch multiple TaskContext objects in parallel.

        Задачи, которые не удалось загрузить (404, 403), пропускаются.

        Example::

            ctxs = await client.task_contexts([1001, 1002, 1003])
            ctxs[0].set("Статус", "Выполнена")
            ctxs[1].set("Статус", "В работе")
            await asyncio.gather(
                ctxs[0].approve("OK"),
                ctxs[1].answer("Принято в работу"),
            )
        """
        from aiopyrus.utils.context import TaskContext

        tasks = await self.get_tasks(task_ids)
        return [TaskContext(task, self) for task in tasks]

    async def get_form_choices(self, form_id: int, field_id: int) -> dict[str, int]:
        """Получить варианты multiple_choice поля в виде {название: choice_id}.

        Запрашивает определение формы и возвращает словарь вариантов для
        указанного поля. Используй для получения choice_id по названию варианта.

        Example::

            choices = await client.get_form_choices(task.form_id, 1014)
            # → {'Открыта': 1, 'В работе': 2, 'Закрыта': 3}

            # Затем:
            from aiopyrus.utils.fields import FieldUpdate
            update = FieldUpdate.choice(1014, choices['В работе'])
        """
        form = await self.get_form(form_id)
        field = form.get_field(field_id)
        if field is None or not field.info:
            return {}
        options = field.info.get("options", [])
        # choice_value не name, потому что стандарты это не про нас.
        result: dict[str, int] = {}
        for opt in options:
            if not isinstance(opt, dict):
                continue
            cid = opt.get("choice_id")
            name = opt.get("choice_value") or opt.get("name")
            if name is not None and cid is not None:
                result[name] = cid
        return result

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    async def get_roles(self) -> list[Role]:
        """GET /roles."""
        data = await self._session.get("roles")
        return [Role.model_validate(r) for r in data.get("roles", [])]

    async def create_role(self, name: str, member_ids: list[int] | None = None) -> Role:
        """POST /roles."""
        payload: dict[str, Any] = {"name": name}
        if member_ids:
            payload["member_ids"] = member_ids
        data = await self._session.post("roles", json=payload)
        return Role.model_validate(data)

    async def update_role(
        self,
        role_id: int,
        *,
        name: str | None = None,
        member_ids: list[int] | None = None,
        banned: bool | None = None,
    ) -> Role:
        """PUT /roles/{role_id}."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if member_ids is not None:
            payload["member_ids"] = member_ids
        if banned is not None:
            payload["banned"] = banned
        data = await self._session.put(f"roles/{role_id}", json=payload)
        return Role.model_validate(data)

    async def get_role(self, role_id: int) -> Role:
        """GET /roles/{role_id} — получить одну роль по ID.

        Get a single role by ID.

        Example::

            role = await client.get_role(42)
            print(role.name, role.member_ids)
        """
        data = await self._session.get(f"roles/{role_id}")
        return Role.model_validate(data)

    async def delete_role(self, role_id: int, *, task_receiver_id: int) -> bool:
        """DELETE /roles/{role_id} — удалить роль.

        Delete a role. Pyrus requires ``task_receiver_id`` in the body —
        the user/role that inherits open tasks assigned to the deleted role.

        Pyrus требует ``task_receiver_id`` в теле запроса — это
        пользователь/роль, которой переходят открытые задачи
        удаляемой роли.

        Args:
            role_id: ID удаляемой роли.
            task_receiver_id: Кому переходят задачи удаляемой роли.

        Example::

            await client.delete_role(42, task_receiver_id=100500)
        """
        # The session helper uses GET-style signature for delete; build payload via raw request.
        data = await self._session.request(
            "DELETE", f"roles/{role_id}", json={"task_receiver_id": task_receiver_id}
        )
        return bool(data.get("deleted", True))

    # ------------------------------------------------------------------
    # Announcements
    # ------------------------------------------------------------------

    async def get_announcements(self) -> list[Announcement]:
        """GET /announcements."""
        data = await self._session.get("announcements")
        return [Announcement.model_validate(a) for a in data.get("announcements", [])]

    async def get_announcement(self, announcement_id: int) -> Announcement:
        """GET /announcements/{id}."""
        data = await self._session.get(f"announcements/{announcement_id}")
        return Announcement.model_validate(data.get("announcement", data))

    async def create_announcement(
        self,
        *,
        text: str,
        attachments: list[str] | None = None,
    ) -> Announcement:
        """POST /announcements."""
        payload: dict[str, Any] = {"text": text}
        if attachments:
            payload["attachments"] = [{"guid": a} for a in attachments]
        data = await self._session.post("announcements", json=payload)
        return Announcement.model_validate(data.get("announcement", data))

    async def comment_announcement(
        self,
        announcement_id: int,
        *,
        text: str,
        attachments: list[str] | None = None,
    ) -> Announcement:
        """POST /announcements/{id}/comments."""
        payload: dict[str, Any] = {"text": text}
        if attachments:
            payload["attachments"] = [{"guid": a} for a in attachments]
        data = await self._session.post(f"announcements/{announcement_id}/comments", json=payload)
        return Announcement.model_validate(data.get("announcement", data))

    # ------------------------------------------------------------------
    # External ID resolution (corp / on-premise)
    # ------------------------------------------------------------------

    async def get_member_external_id(self, member_id: int) -> int | None:
        """Получить external_id сотрудника (корп / on-premise).

        Get the external_id of a member (corp / on-premise instances).

        Возвращает None если инстанс не поддерживает external_id
        или у сотрудника его нет.
        """
        person = await self.get_member(member_id)
        return person.external_id

    async def get_members_external_ids(self, member_ids: list[int]) -> list[int | None]:
        """Получить external_id для нескольких сотрудников параллельно.

        Get external_ids for multiple members in parallel.
        """
        coros = [self.get_member_external_id(mid) for mid in member_ids]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return [None if isinstance(r, BaseException) else r for r in results]

    async def get_roles_external_ids(self, role_ids: list[int]) -> list[int | None]:
        """Получить external_id для ролей.

        Get external_ids for roles (wraps get_member for each role).
        """
        return await self.get_members_external_ids(role_ids)

    # ------------------------------------------------------------------
    # Batch task operations
    # ------------------------------------------------------------------

    async def get_tasks(self, task_ids: list[int]) -> list[Task]:
        """Получить несколько задач по ID параллельно.

        Fetch multiple tasks by ID in parallel.
        Ошибки (404, 403 и т.д.) логируются и пропускаются.
        """
        coros = [self.get_task(tid) for tid in task_ids]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        tasks: list[Task] = []
        for tid, result in zip(task_ids, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("get_tasks: task %d failed: %s", tid, result)
                continue
            tasks.append(result)
        return tasks

    async def create_tasks(self, tasks: list[NewTask]) -> list[Task | BaseException]:
        """Создать несколько задач параллельно.

        Create multiple tasks in parallel.

        Args:
            tasks: Список ``NewTask`` с параметрами для каждой задачи.

        Returns:
            Список Task или BaseException для каждого входа.

        Example::

            from aiopyrus.types.params import NewTask

            results = await client.create_tasks([
                NewTask(form_id=321, fields=[...]),
                NewTask(text="Простая задача"),
            ])
        """
        coros = [self.create_task(**t.model_dump(exclude_none=True)) for t in tasks]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return list(results)

    async def delete_tasks(self, task_ids: list[int]) -> list[bool]:
        """Удалить несколько задач параллельно.

        Delete multiple tasks in parallel.

        Returns:
            Список bool (True = удалена, False = ошибка).
        """
        coros = [self.delete_task(tid) for tid in task_ids]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return [r if isinstance(r, bool) else False for r in results]

    # ------------------------------------------------------------------
    # Batch role / member operations
    # ------------------------------------------------------------------

    async def create_roles(self, roles: list[NewRole]) -> list[Role | BaseException]:
        """Создать несколько ролей параллельно.

        Create multiple roles in parallel.

        Example::

            from aiopyrus.types.params import NewRole

            results = await client.create_roles([
                NewRole(name="Administrators", member_ids=[100500, 100501]),
                NewRole(name="Viewers"),
            ])
        """
        coros = [self.create_role(r.name, r.member_ids) for r in roles]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return list(results)

    async def update_roles(self, updates: list[RoleUpdate]) -> list[Role | BaseException]:
        """Обновить несколько ролей параллельно.

        Update multiple roles in parallel.

        Example::

            from aiopyrus.types.params import RoleUpdate

            results = await client.update_roles([
                RoleUpdate(role_id=42, name="Super Admins"),
                RoleUpdate(role_id=43, banned=True),
            ])
        """
        coros = [
            self.update_role(
                u.role_id,
                **u.model_dump(exclude={"role_id"}, exclude_none=True),
            )
            for u in updates
        ]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return list(results)

    async def update_members(self, updates: list[MemberUpdate]) -> list[Person | BaseException]:
        """Обновить несколько сотрудников параллельно.

        Update multiple members in parallel.

        Example::

            from aiopyrus.types.params import MemberUpdate

            results = await client.update_members([
                MemberUpdate(member_id=100500, position="Lead Developer"),
                MemberUpdate(member_id=100501, status="В отпуске"),
            ])
        """
        coros = [
            self.update_member(
                u.member_id,
                **u.model_dump(exclude={"member_id"}, exclude_none=True),
            )
            for u in updates
        ]
        results = await asyncio.gather(*[self._bounded(c) for c in coros], return_exceptions=True)
        return list(results)

    # ==================================================================
    # Knowledge Base API (Pyrus v1.24, появилась 24.04.2026)
    # ==================================================================
    #
    # База знаний — статьи и темы с разрешениями.  Особенность: ID
    # элементов БЗ — строки (``"BxqPU8UrjlC"``), не int.

    async def get_knowledge_base_structure(
        self,
        *,
        parent_topic_id: str | None = None,
        depth: int | None = None,
    ) -> KnowledgeBaseStructure:
        """GET /knowledgebase/structure — иерархия базы знаний.

        Get knowledge base structure (recursive tree of topics + articles).

        Args:
            parent_topic_id: ID родительской темы — если задан, возвращается
                только её поддерево.  По умолчанию — корень.
            depth: Максимальная глубина обхода.

        Example::

            kb = await client.get_knowledge_base_structure()
            for node in kb.items:
                print(node.id, node.type, node.title)
        """
        params: dict[str, Any] = {}
        if parent_topic_id is not None:
            params["parent_topic_id"] = parent_topic_id
        if depth is not None:
            params["depth"] = depth
        data = await self._session.get("knowledgebase/structure", params=params or None)
        return KnowledgeBaseStructure.model_validate(data)

    async def get_knowledge_base_item(self, item_id: str) -> KnowledgeBaseItem:
        """GET /knowledgebase/{item_id} — статья или тема по ID.

        Get a knowledge base item by string ID.

        Note:
            ``item_id`` — это **строка** (например ``"BxqPU8UrjlC"``),
            не число. См. :class:`~aiopyrus.types.KnowledgeBaseItem`.
        """
        data = await self._session.get(f"knowledgebase/{item_id}")
        return KnowledgeBaseItem.model_validate(data)

    async def create_knowledge_base_item(
        self,
        *,
        title: str,
        type: str = "article",
        parent_topic_id: str | None = None,
        body: str | None = None,
    ) -> KnowledgeBaseItem:
        """POST /knowledgebase — создать статью или тему.

        Create a knowledge base item.

        Args:
            title: Заголовок.
            type: ``"article"`` или ``"topic"``.
            parent_topic_id: ID родительской темы (опционально).
            body: Markdown-текст — обязателен для статей.

        Raises:
            ValueError: если для ``type='article'`` не передан ``body``.
        """
        if type == "article" and not body:
            raise ValueError("body is required when type='article'")
        payload: dict[str, Any] = {"title": title, "type": type}
        if parent_topic_id is not None:
            payload["parent_topic_id"] = parent_topic_id
        if body is not None:
            payload["body"] = body
        data = await self._session.post("knowledgebase", json=payload)
        return KnowledgeBaseItem.model_validate(data)

    async def update_knowledge_base_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        parent_topic_id: str | None = None,
        parent_topic_id_changed: bool | None = None,
    ) -> KnowledgeBaseItem:
        """PUT /knowledgebase/{item_id} — обновить статью/тему.

        Update a knowledge base item.

        Note:
            Если хочешь переместить элемент в корень (без родителя),
            передай ``parent_topic_id=None, parent_topic_id_changed=True``.
            Без второго флага ``None`` игнорируется (это not-set, не
            «очистить родителя»).
        """
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if parent_topic_id_changed is True:
            payload["parent_topic_id"] = parent_topic_id  # may be None ⇒ move to root
            payload["parent_topic_id_changed"] = True
        elif parent_topic_id is not None:
            payload["parent_topic_id"] = parent_topic_id
        data = await self._session.put(f"knowledgebase/{item_id}", json=payload)
        return KnowledgeBaseItem.model_validate(data)

    async def delete_knowledge_base_item(
        self,
        item_id: str,
        *,
        delete_with_children: bool | None = None,
    ) -> bool:
        """DELETE /knowledgebase/{item_id} — удалить статью/тему.

        Args:
            delete_with_children: Если ``True`` — удалить вместе с
                вложенными элементами.
        """
        params: dict[str, Any] = {}
        if delete_with_children is not None:
            params["delete_with_children"] = delete_with_children
        data = await self._session.request(
            "DELETE", f"knowledgebase/{item_id}", params=params or None
        )
        return bool(data.get("deleted", True))

    async def get_knowledge_base_permissions(self, item_id: str) -> KnowledgeBasePermissions:
        """GET /knowledgebase/{item_id}/permissions — разрешения элемента.

        Get permissions for a knowledge base item.

        Note:
            Эндпоинт admin-gated: для обычного пользователя вернётся
            403 ``knowledge_base_access_denied``.
        """
        data = await self._session.get(f"knowledgebase/{item_id}/permissions")
        return KnowledgeBasePermissions.model_validate(data)

    async def update_knowledge_base_permissions(
        self,
        item_id: str,
        *,
        inherit: bool | None = None,
        readers: list[int] | None = None,
        editors: list[int] | None = None,
    ) -> KnowledgeBasePermissions:
        """PUT /knowledgebase/{item_id}/permissions — обновить разрешения.

        Note:
            На вход — ``list[int]`` (ID людей), на выходе — ``list[Person]``
            (объекты целиком). Это асимметрия API Pyrus.
        """
        payload: dict[str, Any] = {}
        if inherit is not None:
            payload["inherit"] = inherit
        if readers is not None:
            payload["readers"] = readers
        if editors is not None:
            payload["editors"] = editors
        data = await self._session.put(f"knowledgebase/{item_id}/permissions", json=payload)
        return KnowledgeBasePermissions.model_validate(data)

    # ==================================================================
    # Awards API (Pyrus v1.22+, cloud / fresh on-premise only)
    # ==================================================================
    #
    # На legacy on-premise сборках эндпоинты могут вернуть 202 «No HTTP
    # resource was found» — это значит, что Awards не развёрнуты на
    # сервере.  Используй обычные try/except — мы не оборачиваем 202
    # в специальную ошибку, чтобы не ломать совместимость остального
    # API.

    async def get_award_threshold(self, award_id: int) -> AwardThreshold:
        """GET /awards/{award_id}/threshold — пороги выдачи/отзыва награды.

        Note:
            На legacy on-premise может вернуться 202 + не-JSON тело — это
            «эндпоинт не развёрнут».
        """
        data = await self._session.get(f"awards/{award_id}/threshold")
        return AwardThreshold.model_validate(data)

    async def set_award_threshold(
        self,
        award_id: int,
        *,
        grant_threshold: int,
        revoke_threshold: int,
    ) -> AwardThreshold:
        """PUT /awards/{award_id}/threshold — задать пороги награды.

        Raises:
            ValueError: если оба порога ненулевые и ``revoke_threshold``
                не строго больше ``grant_threshold``.
        """
        if grant_threshold > 0 and revoke_threshold > 0 and revoke_threshold <= grant_threshold:
            raise ValueError("revoke_threshold must exceed grant_threshold when both are non-zero")
        payload = {
            "grant_threshold": grant_threshold,
            "revoke_threshold": revoke_threshold,
        }
        data = await self._session.put(f"awards/{award_id}/threshold", json=payload)
        return AwardThreshold.model_validate(data)

    async def get_member_award_counter(self, member_id: int, award_id: int) -> MemberAwardCounter:
        """GET /members/{member_id}/awards/{award_id}/counter — счётчик награды."""
        data = await self._session.get(f"members/{member_id}/awards/{award_id}/counter")
        return MemberAwardCounter.model_validate(data)

    async def increment_member_award_counter(
        self, member_id: int, award_id: int
    ) -> MemberAwardCounter:
        """POST /members/{member_id}/awards/{award_id}/counter/increment — увеличить счётчик."""
        data = await self._session.post(
            f"members/{member_id}/awards/{award_id}/counter/increment",
            json={},
        )
        return MemberAwardCounter.model_validate(data)

    async def set_member_award_counter(
        self, member_id: int, award_id: int, *, value: int
    ) -> MemberAwardCounter:
        """PUT /members/{member_id}/awards/{award_id}/counter — выставить счётчик.

        Note:
            ``value`` передаётся как **query-string** (``?value=N``),
            не в теле — особенность Pyrus API.
        """
        # PUT через _session.request — params вместо json
        data = await self._session.request(
            "PUT",
            f"members/{member_id}/awards/{award_id}/counter",
            params={"value": value},
        )
        return MemberAwardCounter.model_validate(data)

    # ==================================================================
    # Telephony — интеграция с call-центром (Zadarma, asterisk и др.)
    # ==================================================================

    async def register_call(
        self,
        *,
        account_id: str,
        from_number: str,
        to_number: str,
        internal_number: str | None = None,
        external_id: str | None = None,
        mappings: list[CallMapping] | None = None,
    ) -> RegisterCallResponse:
        """POST /integrations/call — зарегистрировать звонок.

        Args:
            account_id: ID аккаунта телефонии (из настроек интеграции).
            from_number: Номер откуда.
            to_number: Номер куда.
            internal_number: Внутренний номер сотрудника, если есть.
            external_id: Внешний ID звонка (для последующего
                :meth:`attach_call_record`).
            mappings: Дополнительные данные (время, длительность,
                рейтинг) в виде :class:`CallMapping`.

        Returns:
            RegisterCallResponse с ``task_id`` созданной задачи (если
            форма звонков настроена) и ``responsible_person``.
        """
        payload: dict[str, Any] = {
            "account_id": account_id,
            "from": from_number,
            "to": to_number,
        }
        if internal_number is not None:
            payload["internal_number"] = internal_number
        if external_id is not None:
            payload["external_id"] = external_id
        if mappings is not None:
            payload["mappings"] = [m.model_dump() for m in mappings]
        data = await self._session.post("integrations/call", json=payload)
        return RegisterCallResponse.model_validate(data)

    async def attach_call_record(
        self,
        *,
        account_id: str,
        record_file: str,
        task_id: int | None = None,
        external_id: str | None = None,
        from_number: str | None = None,
        to_number: str | None = None,
        mappings: list[CallMapping] | None = None,
    ) -> AttachCallRecordResponse:
        """POST /integrations/attachcallrecord — прикрепить запись звонка.

        Args:
            account_id: ID аккаунта телефонии.
            record_file: GUID загруженного файла (из :meth:`upload_file`).
                Допустимые форматы: ac3, mp3, ogg, wav, wma.
            task_id: ID задачи звонка (если знаем).
            external_id: Или внешний ID звонка из :meth:`register_call`.
            from_number, to_number: Или пара номеров для поиска задачи.

        Raises:
            ValueError: если не передан ни ``task_id``, ни ``external_id``,
                ни пара ``from_number+to_number``.
        """
        has_task = task_id is not None
        has_external = external_id is not None
        has_phones = from_number is not None and to_number is not None
        if not (has_task or has_external or has_phones):
            raise ValueError("Must supply task_id, external_id, or both from_number+to_number")
        payload: dict[str, Any] = {
            "account_id": account_id,
            "record_file": record_file,
        }
        if task_id is not None:
            payload["task_id"] = task_id
        if external_id is not None:
            payload["external_id"] = external_id
        if from_number is not None:
            payload["from"] = from_number
        if to_number is not None:
            payload["to"] = to_number
        if mappings is not None:
            payload["mappings"] = [m.model_dump() for m in mappings]
        data = await self._session.post("integrations/attachcallrecord", json=payload)
        return AttachCallRecordResponse.model_validate(data)
