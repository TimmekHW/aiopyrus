from __future__ import annotations

import asyncio
import logging
import pathlib
import warnings
from typing import TYPE_CHECKING, Any, BinaryIO
from urllib.parse import urlparse

import aiofiles

log = logging.getLogger("aiopyrus.client")

if TYPE_CHECKING:
    from aiopyrus.utils.context import TaskContext

from aiopyrus.api.session import PyrusSession
from aiopyrus.types.catalog import Catalog, CatalogSyncResult
from aiopyrus.types.file import UploadedFile
from aiopyrus.types.form import Form
from aiopyrus.types.task import (
    Announcement,
    ApprovalChoice,
    CommentChannel,
    Task,
    TaskAction,
)
from aiopyrus.types.user import ContactsResponse, Person, Profile, Role


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
        timeout: float = 30.0,
        auth_url: str | None = None,
        api_url: str | None = None,
        proxy: str | None = None,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
    ) -> None:
        self._session = PyrusSession(
            login, security_key, person_id,
            timeout=timeout,
            auth_url=auth_url,
            api_url=api_url,
            proxy=proxy,
            requests_per_second=requests_per_second,
            requests_per_minute=requests_per_minute,
            requests_per_10min=requests_per_10min,
        )

    # ------------------------------------------------------------------
    # Context manager / lifecycle
    # ------------------------------------------------------------------

    async def auth(self) -> str:
        """Manually authenticate and obtain the access token."""
        return await self._session.auth()

    async def close(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> UserClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    async def get_profile(self) -> Profile:
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
        fields: list[dict] | None = None,
        fill_defaults: bool | None = None,
        approvals: list[list[dict | int]] | None = None,
        # People
        responsible: dict | int | None = None,
        participants: list[dict | int] | None = None,
        subscribers: list[dict | int] | None = None,
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
                [{"id": p} if isinstance(p, int) else p for p in step]
                for step in approvals
            ]
        if responsible is not None:
            payload["responsible"] = {"id": responsible} if isinstance(responsible, int) else responsible
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
            payload["attachments"] = [{"id": a} for a in attachments]

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
        # Threading — reply to a specific comment
        reply_to_comment_id: int | None = None,
        # Workflow
        action: TaskAction | str | None = None,
        # Approvals
        approval_choice: ApprovalChoice | str | None = None,
        approvals_added: list[list[dict | int]] | None = None,
        approvals_removed: list[dict | int] | None = None,
        approvals_rerequested: list[dict | int] | None = None,
        # People
        reassign_to: dict | int | None = None,
        participants_added: list[dict | int] | None = None,
        participants_removed: list[dict | int] | None = None,
        subscribers_added: list[dict | int] | None = None,
        subscribers_removed: list[dict | int] | None = None,
        subscribers_rerequested: list[dict | int] | None = None,
        # Form fields
        field_updates: list[dict] | None = None,
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
        comment_as_roles: list[dict | int] | None = None,
    ) -> Task:
        """POST /tasks/{task_id}/comments — add a comment / modify a task.

        Returns the updated task.
        """

        def _persons(items: list[dict | int]) -> list[dict]:
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
            payload["action"] = (
                action.value if isinstance(action, TaskAction) else str(action)
            )
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
            payload["reassign_to"] = {"id": reassign_to} if isinstance(reassign_to, int) else reassign_to
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
            payload["attachments"] = [{"id": a} for a in attachments]
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
            payload["comment_as_roles"] = [{"id": r} if isinstance(r, int) else r for r in comment_as_roles]

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
        return await self.comment_task(task_id, approval_choice=ApprovalChoice.acknowledged, text=text)

    # ------------------------------------------------------------------
    # Inbox / Calendar
    # ------------------------------------------------------------------

    async def get_inbox(self, *, item_count: int | None = None) -> list[Task]:
        """GET /inbox — tasks in the current user's inbox."""
        params: dict = {}
        if item_count is not None:
            params["item_count"] = item_count
        data = await self._session.get("inbox", params=params or None)
        return [Task.model_validate(t) for t in data.get("tasks", [])]

    async def get_calendar(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[Task]:
        """GET /calendar — scheduled tasks."""
        params: dict = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
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
        # Фильтр по просрочке: "overdue" | "overdue_on_step" | "past_due"
        due_filter: str | None = None,
        # Фильтр по id задачи (диапазон): например "gt12345" или "12345,12346"
        id_filter: str | None = None,
        # Фильтры по полям формы {"fld{id}": "значение"} или {"fld{id}": "gt10000,lt15000"}
        field_filters: dict[str, str] | None = None,
    ) -> list[Task]:
        """GET /forms/{form_id}/register — реестр задач по форме.

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
        batches = await asyncio.gather(*coros, return_exceptions=True)
        result: list[Task] = []
        for form_id, batch in zip(forms, batches):
            if isinstance(batch, BaseException):
                log.warning("search_tasks: form %d failed: %s", form_id, batch)
                continue
            result.extend(batch)
        return result

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

    async def get_form_permissions(self, form_id: int) -> dict:
        """GET /forms/{form_id}/permissions."""
        return await self._session.get(f"forms/{form_id}/permissions")

    async def set_form_permissions(self, form_id: int, permissions: dict) -> dict:
        """POST /forms/{form_id}/permissions — set user access levels."""
        return await self._session.post(f"forms/{form_id}/permissions", json={"permissions": permissions})

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
        headers: list[str | dict],
        items: list[list[str]],
    ) -> Catalog:
        """PUT /catalogs — create a new catalog."""
        catalog_headers = [
            {"name": h} if isinstance(h, str) else h for h in headers
        ]
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
        headers: list[str | dict],
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
            async with aiofiles.open(path, "rb") as fh:
                file_bytes = await fh.read()
        elif isinstance(file, bytes):
            file_bytes = file
        else:
            file_bytes = file.read()

        filename = filename or "upload"
        files = {"file": (filename, file_bytes)}
        data = await self._session.post("files/upload", files=files)
        return UploadedFile.model_validate(data)

    async def download_file(self, file_id: str) -> bytes:
        """GET /files/download/{file_id} — download a file as bytes."""
        url = f"{self._session._files_url.rstrip('/')}/files/download/{file_id}"
        client = await self._session._get_client()
        response = await client.get(url, headers=self._session._auth_headers())
        response.raise_for_status()
        return response.content

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

    async def block_member(self, member_id: int) -> bool:
        """DELETE /members/{member_id} — block a member."""
        data = await self._session.delete(f"members/{member_id}")
        return bool(data.get("banned"))

    async def find_member(self, name: str) -> Person | None:
        """Найти сотрудника по частичному совпадению имени (регистронезависимо).

        Ищет по полному имени, имени и фамилии по отдельности, логину и email.
        Возвращает первое совпадение или None.

        Example::

            person = await client.find_member("Ivanov")
            # → Person(id=100500, first_name='Ivan', last_name='Ivanov', …)

            person = await client.find_member("Petrov Sergey")
        """
        query = name.lower()
        members = await self.get_members()
        for m in members:
            full = f"{m.first_name} {m.last_name}".lower()
            rev  = f"{m.last_name} {m.first_name}".lower()
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
            rev  = f"{m.last_name} {m.first_name}".lower()
            if (
                query in full
                or query in rev
                or query in (m.first_name or "").lower()
                or query in (m.last_name or "").lower()
                or query in (m.email or "").lower()
            ):
                result.append(m)
        return result

    async def task_context(self, task_id: int) -> "TaskContext":
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

    async def update_role(self, role_id: int, *, name: str | None = None, member_ids: list[int] | None = None, banned: bool | None = None) -> Role:
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
            payload["attachments"] = [{"id": a} for a in attachments]
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
            payload["attachments"] = [{"id": a} for a in attachments]
        data = await self._session.post(f"announcements/{announcement_id}/comments", json=payload)
        return Announcement.model_validate(data.get("announcement", data))
