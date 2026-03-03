"""TaskContext — aiogram-style wrapper for Pyrus task automation.

Work with tasks using human-readable field names (as shown in the Pyrus UI)
without knowing field IDs, type codes, choice_id, or person_id internals.

Работайте с задачей через имена полей, как в интерфейсе Pyrus — без знания
ID полей, типов, форматов choice_id и person_id.

Method reference / Справочник методов
--------------------------------------

**Reading fields / Чтение полей**

.. code-block:: python

    ctx["Description"]                    # → str / list / bool / None
    ctx["Описание"]                       # same — field names are as in your Pyrus form
    ctx.get("Status", "Open")             # with default / с дефолтом
    ctx.raw("Executor")                   # → raw FormField object

**Writing fields (lazy — applied on next send) / Запись полей (ленивая)**

.. code-block:: python

    ctx.fill("Status",   "In progress")    # multiple_choice: name → choice_id auto
    ctx.fill("Executor", "john.doe")       # person: name/login/email → person_id auto
    ctx.fill("Notes",    "updated text")   # text: passed through
    ctx.fill("Checkbox", True)             # checkmark / flag
    ctx.fill("Field",    None)             # clear the field / очистить поле
    ctx.discard()                          # drop all uncommitted fill()-s

    # Chaining / Чейнинг
    ctx.fill("Status", "In progress").fill("Executor", "john.doe")

    # Aliases: ctx.set() and ctx.put() work too
    ctx.set("Status", "In progress")
    ctx.put("Status", "In progress")

**Sending (flushes accumulated fill()-s) / Отправка (сбрасывает fill()-ы)**

.. code-block:: python

    await ctx.answer("comment text")                         # add a comment
    await ctx.answer(formatted_text="<b>bold</b>")          # HTML formatting
    await ctx.answer("text", attachments=["guid"])           # with attachment
    await ctx.answer("text", private=True)                   # private comment

    await ctx.approve("Approved")    # approve current approval step / утвердить шаг
    await ctx.reject("Rejected")     # reject current step / отклонить
    await ctx.finish("Done")         # finish the task / завершить задачу

**Reassignment / Переназначение**

.. code-block:: python

    await ctx.reassign("Jane Smith")                  # name/login/email → person_id auto
    await ctx.reassign("Jane Smith", "Passing to you")  # with comment / с комментарием

**Time tracking / Трекинг времени**

.. code-block:: python

    await ctx.log_time(90)                            # 90 minutes / 90 минут
    await ctx.log_time(30, "Incident analysis")       # with comment / с комментарием

**Reply to a comment / Ответить на комментарий**

.. code-block:: python

    await ctx.reply(comment.id, "Please clarify")

**Introspection — IDs, types, raw data / Интроспекция**

.. code-block:: python

    ctx.get_id("Статус задачи")              # → 5  (field ID)
    ctx.get_type("Статус задачи")            # → "multiple_choice"
    ctx.get_value_id("Статус задачи")        # → 3  (choice_id of current value)
    ctx.get_value_id("Тип запроса")          # → 11148054  (item_id)
    ctx.get_value_id("Исполнитель")          # → 100500  (person_id)
    await ctx.get_catalog_id("Тип запроса")  # → 1910  (catalog ID from form)

    ctx.raw("Тип запроса")     # → FormField pydantic object
    ctx.dump("Тип запроса")    # → dict (JSON-like) of the field
    ctx.dump()                 # → dict of the entire task

    # Aliases / Алиасы: field_id, field_type, value_id, catalog_id

**Properties / Свойства**

.. code-block:: python

    ctx.id       # int       — task ID
    ctx.step     # int|None  — current route step / текущий шаг маршрута
    ctx.closed   # bool      — is task closed? / задача закрыта?
    ctx.form_id  # int|None  — form ID
    ctx.task     # Task      — underlying Pydantic object

Full flow example / Пример полного флоу::

    async with UserClient(**credentials) as client:
        ctx = await client.task_context(TASK_ID)

        # Read fields (names from your Pyrus form)
        problem_type = ctx["Тип проблемы"]
        description  = ctx["Описание"]

        # Take to work
        ctx.fill("Статус задачи", "В работе").fill("Исполнитель", "ivanov")
        await ctx.answer(f"Accepted. Type: {problem_type}")

        # Process and close
        ctx.fill("Статус задачи", "Выполнена").fill("Номер кейса", "INC-001")
        await ctx.approve("Processing complete")
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
from typing import TYPE_CHECKING, Any

from aiopyrus.types.task import ApprovalChoice, Task, TaskAction
from aiopyrus.utils.fields import FieldUpdate

if TYPE_CHECKING:
    from aiopyrus.types.catalog import CatalogItem
    from aiopyrus.types.form import FormField
    from aiopyrus.user.client import UserClient

log = logging.getLogger("aiopyrus.context")


# ---------------------------------------------------------------------------
# Catalog item search helper
# ---------------------------------------------------------------------------


def _catalog_display(values: list[str]) -> str:
    """Build display text for a catalog item (same logic as _read_field)."""
    human = [v for v in values if v and not v.strip().lstrip("-").isdigit()]
    if not human:
        return ""
    return " / ".join(human) if len(human) > 1 else human[0]


def _find_catalog_item(items: list[CatalogItem], text: str) -> CatalogItem | None:
    """Search catalog items by display text or column value.

    Matching order:
    1. Exact display text (non-numeric columns joined with " / ").
    2. Exact match on any individual column value.
    3. All " / "-separated parts found among item's column values.
    4. Case-insensitive versions of 1–3.
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Pass 1: exact display text
    for item in items:
        if item.deleted:
            continue
        if _catalog_display(item.values) == text_stripped:
            return item

    # Pass 2: exact match on any single column value
    for item in items:
        if item.deleted:
            continue
        if text_stripped in item.values:
            return item

    # Pass 3: all user-provided parts found among columns
    parts = [p.strip() for p in text_stripped.split(" / ") if p.strip()]
    if len(parts) > 1:
        for item in items:
            if item.deleted:
                continue
            if all(p in item.values for p in parts):
                return item

    # Pass 4: case-insensitive display text
    for item in items:
        if item.deleted:
            continue
        if _catalog_display(item.values).lower() == text_lower:
            return item

    # Pass 5: case-insensitive column value
    for item in items:
        if item.deleted:
            continue
        if any(v.lower() == text_lower for v in item.values if v):
            return item

    # Pass 6: case-insensitive parts matching
    if len(parts) > 1:
        parts_lower = [p.lower() for p in parts]
        for item in items:
            if item.deleted:
                continue
            vals_lower = [v.lower() for v in item.values if v]
            if all(p in vals_lower for p in parts_lower):
                return item

    return None


# ---------------------------------------------------------------------------
# Required-field detection helper
# ---------------------------------------------------------------------------


def _collect_task_values(fields: list, out: dict[int, Any]) -> None:
    """Recursively collect field_id → value for all task fields (including title sub-fields)."""
    for field in fields:
        if field.value is not None:
            out[field.id] = field.value
        # Recurse into title sub-fields
        title = field.as_title() if field.type and field.type.value == "title" else None
        if title and title.fields:
            _collect_task_values(title.fields, out)


def _collect_required_missing(
    form_fields: list,
    task_values: dict[int, Any],
    step: int,
    result: list[str],
) -> None:
    """Recursively collect names of required-at-step fields that have no value in the task."""
    for field_def in form_fields:
        info = field_def.info if isinstance(field_def.info, dict) else {}

        required_step = getattr(field_def, "required_step", None) or info.get("required_step")
        if required_step == step and field_def.id not in task_values:
            result.append(field_def.name or f"id={field_def.id}")

        # Recurse into sub-fields stored in info["fields"] (form definition structure)
        sub_raw = info.get("fields") if isinstance(info, dict) else None
        if sub_raw:
            from aiopyrus.types.form import FormField as FF

            sub: list = []
            for s in sub_raw:
                if isinstance(s, dict):
                    with contextlib.suppress(Exception):
                        sub.append(FF.model_validate(s))
            if sub:
                _collect_required_missing(sub, task_values, step, result)


# ---------------------------------------------------------------------------
# Field value reader — returns human-readable value
# ---------------------------------------------------------------------------


def _read_field(field: FormField) -> Any:
    """Return the human-readable value for a field.

    - text / email / phone / number / money / date / … → str / int / float
    - checkmark / flag                                  → True / False
    - multiple_choice                                   → str (first selected name)
                                                          or list[str] if multiple
    - person / author                                   → "First Last" (str)
    - catalog                                           → "Col1 / Col2 / …" (str)
    - title                                             → True / False (checkmark)
                                                          or None
    - file                                              → list[Attachment]
    - everything else                                   → raw field.value
    """
    if field.value is None:
        return None

    ftype = field.type.value if field.type else None

    if ftype in ("checkmark", "flag"):
        return field.value == "checked"

    if ftype == "multiple_choice":
        mc = field.as_multiple_choice()
        if mc and mc.choice_names:
            names = mc.choice_names
            return names[0] if len(names) == 1 else names
        return field.value

    if ftype in ("person", "author"):
        p = field.as_person()
        return p.full_name if p else None

    if ftype == "catalog":
        cat = field.as_catalog()
        if cat and cat.values:
            # Pyrus catalogs often have a numeric ID as the first column (not shown in UI).
            # Filter out purely-numeric values to match what the web interface shows.
            human = [v for v in cat.values if v and not v.strip().lstrip("-").isdigit()]
            vals = human if human else [v for v in cat.values if v]
            if not vals:
                return None
            return " / ".join(vals) if len(vals) > 1 else vals[0]
        return None

    if ftype == "title":
        title = field.as_title()
        if title and title.checkmark is not None:
            return title.checkmark == "checked"
        return None

    if ftype == "file":
        return field.as_files()

    # text, email, phone, note, number, money, date, time,
    # due_date, due_date_time, step, status, creation_date, …
    return field.value


# ---------------------------------------------------------------------------
# TaskContext
# ---------------------------------------------------------------------------


class TaskContext:
    """Aiogram-style wrapper over a Pyrus Task.

    Use field names exactly as they appear in the Pyrus UI —
    no IDs, no type codes, no manual payload construction.

    +---------------------------------------+----------------------------------------------+
    | Read / Чтение                         | ``ctx["Field"]``, ``ctx.get("Field")``       |
    +---------------------------------------+----------------------------------------------+
    | Find / Поиск                          | ``ctx.find("%pattern%")``                    |
    +---------------------------------------+----------------------------------------------+
    | Raw object / Объект                   | ``ctx.raw("Field")``                         |
    +---------------------------------------+----------------------------------------------+
    | Raw dict (JSON)                       | ``ctx.dump("Field")`` / ``ctx.dump()``       |
    +---------------------------------------+----------------------------------------------+
    | Write (lazy) / Запись (ленивая)       | ``ctx.fill()`` / ``set()`` / ``put()``       |
    +---------------------------------------+----------------------------------------------+
    | Field ID / ID поля                    | ``ctx.get_id("Field")``                      |
    +---------------------------------------+----------------------------------------------+
    | Field type / Тип поля                 | ``ctx.get_type("Field")``                    |
    +---------------------------------------+----------------------------------------------+
    | Value ID / ID значения                | ``ctx.get_value_id("Field")``                |
    +---------------------------------------+----------------------------------------------+
    | Catalog ID / ID каталога              | ``await ctx.get_catalog_id("Field")``        |
    +---------------------------------------+----------------------------------------------+
    | Comment + flush / Комментарий         | ``await ctx.answer("text")``                 |
    +---------------------------------------+----------------------------------------------+
    | Approve step / Утвердить шаг          | ``await ctx.approve("text")``                |
    +---------------------------------------+----------------------------------------------+
    | Reject step / Отклонить шаг           | ``await ctx.reject("text")``                 |
    +---------------------------------------+----------------------------------------------+
    | Finish task / Завершить задачу        | ``await ctx.finish("text")``                 |
    +---------------------------------------+----------------------------------------------+
    | Reassign / Переназначить              | ``await ctx.reassign("Jane Smith")``         |
    +---------------------------------------+----------------------------------------------+
    | Log time / Трекинг времени            | ``await ctx.log_time(90, "text")``           |
    +---------------------------------------+----------------------------------------------+
    | Reply to comment / Ответить           | ``await ctx.reply(comment_id, "text")``      |
    +---------------------------------------+----------------------------------------------+

    ``fill()`` / ``set()`` / ``put()`` return *self* — chainable::

        ctx.fill("Статус задачи", "В работе").fill("Исполнитель", "ivanov")
        ctx.set("Статус задачи", "В работе")   # alias / алиас
        ctx.put("Статус задачи", "В работе")   # alias / алиас
        await ctx.answer()

    All pending writes are flushed in a single API call on the next
    ``answer()`` / ``approve()`` / ``finish()`` / ``reject()`` /
    ``reassign()`` / ``log_time()`` / ``reply()``.
    """

    def __init__(self, task: Task, client: UserClient) -> None:
        self._task = task
        self._client = client
        self._pending: list[tuple[FormField, Any]] = []

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def __getitem__(self, field_name: str) -> Any:
        """Return the human-readable value of a field by its name.

        Field name must match the Pyrus UI label exactly (case-sensitive).
        Raises ``KeyError`` if the field is not found in this task.
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        return _read_field(field)

    def get(self, field_name: str, default: Any = None) -> Any:
        """Return field value, or *default* if the field is missing or empty."""
        field = self._task.get_field(field_name)
        if field is None:
            return default
        val = _read_field(field)
        return val if val is not None else default

    def raw(self, field_name: str) -> FormField | None:
        """Return the raw ``FormField`` object (useful for catalog headers, choice IDs, etc.)."""
        return self._task.get_field(field_name)

    def find(self, name_pattern: str, default: Any = None) -> Any:
        """Find the first field whose name matches *name_pattern*, return its value.

        Supports SQL ``LIKE`` wildcards:

        - ``%`` — matches any sequence of characters (including empty).
        - No ``%`` — treated as a **case-insensitive substring**.

        Returns the human-readable value (same as ``ctx["Field"]``),
        or *default* if no matching field is found or the field is empty.

        Examples::

            ctx.find("%описание%")          # any field whose name contains "описание"
            ctx.find("Описание изменения")  # exact name (case-insensitive substring)
            ctx.find("Тип проблемы%")       # name starts with "Тип проблемы"
            ctx.find("%кейса%", "N/A")      # with explicit default
        """
        if "%" in name_pattern:
            fnm = name_pattern.lower().replace("%", "*")
            # find_fields() with no name arg returns all fields (recursive)
            candidates = self._task.find_fields()
            for field in candidates:
                if field.name and fnmatch.fnmatch(field.name.lower(), fnm):
                    val = _read_field(field)
                    return val if val is not None else default
        else:
            # Plain substring match (case-insensitive) via existing find_fields
            candidates = self._task.find_fields(name=name_pattern)
            if candidates:
                val = _read_field(candidates[0])
                return val if val is not None else default
        return default

    # ------------------------------------------------------------------
    # Writing (lazy — applied on the next answer/approve/finish/reject)
    # ------------------------------------------------------------------

    def fill(self, field_name: str, value: Any) -> TaskContext:
        """Fill a field — schedule update (lazy, sent on next answer/approve/etc.).

        Заполнить поле — отложенная запись, отправится при следующем
        ``answer()`` / ``approve()`` / ``reject()`` / ``finish()``.

        String values are resolved to IDs automatically:

        - **multiple_choice** — choice name (``"In progress"``) or int choice_id.
          String → choice_id looked up via the form API.
        - **person / author**  — name, login, or email, or int person_id.
          String → person_id looked up via the contacts API.
        - **catalog**          — display text or column value, or int item_id.
          String → item_id looked up via the catalog API.
        - **text / number / …** — passed through as-is.
        - **checkmark / flag**  — ``True`` / ``False``.
        - ``None``              — clears the field.

        Example::

            ctx.fill("Статус задачи", "В работе").fill("Исполнитель", "ivanov")
            await ctx.answer("Принято в работу")

        Raises:
            KeyError:   field not found in this task.
            ValueError: value incompatible with field type (raised on flush,
                        not at the ``fill()`` call site).

        Returns *self* for chaining.
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        self._pending.append((field, value))
        return self

    # Aliases — ctx.set() and ctx.put() work too
    set = fill
    put = fill

    def discard(self) -> TaskContext:
        """Drop all uncommitted ``fill()``-s without sending them."""
        self._pending.clear()
        return self

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def answer(self, text: str | None = None, **kwargs: Any) -> Task:
        """Post a comment and flush all pending ``set()``-s in one API call.

        Args:
            text:     Comment text (optional — you can send only field updates).
            **kwargs: Extra parameters forwarded to ``comment_task()``:
                      ``formatted_text``, ``attachments``, ``due_date``,
                      ``spent_minutes``, ``skip_notification``, ``channel``,
                      ``private``, ``reply_to_comment_id``, …

        Tip:
            Use ``reassign()``, ``log_time()``, ``reply()`` for those specific actions.

        Returns:
            Updated ``Task`` object.
        """
        updates = await self._flush()
        result = await self._client.comment_task(
            self._task.id,
            text=text,
            field_updates=updates or None,
            **kwargs,
        )
        self._task = result
        return result

    # Aliases — use whichever name you prefer
    comment = answer  # ctx.comment("text")
    send = answer  # ctx.send("text")

    async def reassign(
        self,
        to: str | int,
        text: str | None = None,
        **kwargs: Any,
    ) -> Task:
        """Reassign the task and flush pending ``set()``-s.

        Args:
            to:   Name, login, email, or int person_id of the new assignee.
                  A string is resolved to person_id automatically.
            text: Optional comment to attach to the reassignment.

        Example::

            await ctx.reassign("Иванов Иван", "Passing this to you")
        """
        if isinstance(to, str):
            person = await self._client.find_member(to)
            if person is None:
                raise ValueError(
                    f"Person {to!r} not found. "
                    f"Try: await client.find_members('{to}') to see candidates."
                )
            person_id: int = person.id
        else:
            person_id = to
        updates = await self._flush()
        result = await self._client.comment_task(
            self._task.id,
            text=text,
            field_updates=updates or None,
            reassign_to=person_id,
            **kwargs,
        )
        self._task = result
        return result

    async def log_time(
        self,
        minutes: int,
        text: str | None = None,
        **kwargs: Any,
    ) -> Task:
        """Log time spent on the task and flush pending ``set()``-s.

        Args:
            minutes: Number of minutes to log.
            text:    Optional comment.

        Example::

            await ctx.log_time(90, "Incident analysis")
        """
        updates = await self._flush()
        result = await self._client.comment_task(
            self._task.id,
            text=text,
            field_updates=updates or None,
            spent_minutes=minutes,
            **kwargs,
        )
        self._task = result
        return result

    async def reply(
        self,
        comment_id: int,
        text: str | None = None,
        **kwargs: Any,
    ) -> Task:
        """Reply to a specific comment (threaded comment).

        Создаёт ответ в тред комментария. Pyrus API требует
        ``<quote data-noteid="...">`` в ``formatted_text`` для создания
        треда — ``reply_note_id`` в теле запроса является read-only.

        Creates a threaded reply. The Pyrus API requires a
        ``<quote data-noteid="...">`` tag inside ``formatted_text``
        to create a thread — ``reply_note_id`` in the request body
        is read-only and ignored by the server.

        Args:
            comment_id: ID of the comment to reply to.
            text:       Reply text.

        Example::

            await ctx.reply(comment.id, "Please clarify the details")
        """
        updates = await self._flush()

        # Build formatted_text with <quote> — the only way Pyrus creates threads.
        formatted_text = kwargs.pop("formatted_text", None)
        if formatted_text is None:
            source = None
            for c in self._task.comments or []:
                if c.id == comment_id:
                    source = c
                    break
            if source is not None:
                person_id = source.author.id if source.author else 0
                person_name = source.author.full_name if source.author else ""
                quoted = source.text or source.formatted_text or ""
                formatted_text = (
                    f'<quote data-noteid="{comment_id}" '
                    f'data-personid="{person_id}" '
                    f'data-personname="{person_name}">'
                    f"{quoted}</quote>"
                    f"{text or ''}"
                )
            else:
                # Comment not found in loaded task — minimal quote tag.
                formatted_text = f'<quote data-noteid="{comment_id}"></quote>{text or ""}'

        result = await self._client.comment_task(
            self._task.id,
            formatted_text=formatted_text,
            field_updates=updates or None,
            reply_to_comment_id=comment_id,
            **kwargs,
        )
        self._task = result
        return result

    async def approve(self, text: str | None = None, **kwargs: Any) -> Task:
        """Approve the current approval step and flush pending ``set()``-s.

        Note:
            The Pyrus API silently drops ``approval_choice`` when ``field_updates``
            are present in the same request. Pending ``set()``-s are therefore
            flushed in a separate API call *before* casting the approval vote.
        """
        await self._warn_required_missing("approve")
        updates = await self._flush()
        if updates:
            self._task = await self._client.comment_task(self._task.id, field_updates=updates)
        old_step, old_closed = self._task.current_step, self._task.closed
        result = await self._client.comment_task(
            self._task.id,
            approval_choice=ApprovalChoice.approved,
            text=text,
            **kwargs,
        )
        self._task = result
        if result.current_step == old_step and not result.closed and not old_closed:
            await self._raise_if_blocked("approve")
        return result

    async def reject(self, text: str | None = None, **kwargs: Any) -> Task:
        """Reject the current approval step and flush pending ``set()``-s."""
        await self._warn_required_missing("reject")
        updates = await self._flush()
        if updates:
            self._task = await self._client.comment_task(self._task.id, field_updates=updates)
        result = await self._client.comment_task(
            self._task.id,
            approval_choice=ApprovalChoice.rejected,
            text=text,
            **kwargs,
        )
        self._task = result
        return result

    async def finish(self, text: str | None = None, **kwargs: Any) -> Task:
        """Finish (close) the task and flush pending ``set()``-s."""
        await self._warn_required_missing("finish")
        updates = await self._flush()
        if updates:
            self._task = await self._client.comment_task(self._task.id, field_updates=updates)
        old_step, old_closed = self._task.current_step, self._task.closed
        result = await self._client.comment_task(
            self._task.id,
            action=TaskAction.finished,
            text=text,
            **kwargs,
        )
        self._task = result
        if result.current_step == old_step and not result.closed and not old_closed:
            await self._raise_if_blocked("finish")
        return result

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> int:
        """Task ID."""
        return self._task.id

    @property
    def task(self) -> Task:
        """Underlying ``Task`` Pydantic object."""
        return self._task

    @property
    def step(self) -> int | None:
        """Current approval/route step number, or ``None`` for simple tasks."""
        return self._task.current_step

    @property
    def closed(self) -> bool:
        """``True`` if the task is closed."""
        return self._task.closed

    @property
    def form_id(self) -> int | None:
        """Form ID, or ``None`` if this is a free (non-form) task."""
        return self._task.form_id

    def get_id(self, field_name: str) -> int:
        """Return the numeric ID of a field by its UI name.

        Получить числовой ID поля по имени из интерфейса Pyrus.

        Example::

            fid = ctx.get_id("Тип запроса")     # → 5
            ftype = ctx.get_type("Тип запроса")  # → "catalog"

        Raises:
            KeyError: field not found in this task.
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        return field.id

    def get_type(self, field_name: str) -> str:
        """Return the type of a field by its UI name.

        Получить тип поля по имени из интерфейса Pyrus.

        Common types: ``text``, ``multiple_choice``, ``catalog``,
        ``checkmark``, ``person``, ``number``, ``date``, ``note``, ``file``.

        Example::

            ctx.get_type("Статус задачи")  # → "multiple_choice"
            ctx.get_type("Тип запроса")    # → "catalog"
            ctx.get_type("Описание")       # → "text"

        Raises:
            KeyError: field not found in this task.
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        return field.type.value if field.type else "unknown"

    def get_value_id(self, field_name: str) -> int | list[int]:
        """Return the ID of the current value inside a field.

        Получить ID текущего значения поля.

        Works for:

        - **multiple_choice** → ``choice_id`` (int) or list of ``choice_ids``
        - **catalog**         → ``item_id`` (int)
        - **person / author** → ``person_id`` (int)
        - **form_link**       → list of linked ``task_ids``

        Example::

            ctx.get_value_id("Статус задачи")   # → 3  (choice_id)
            ctx.get_value_id("Тип запроса")      # → 11148054  (item_id)
            ctx.get_value_id("Исполнитель")      # → 100500  (person_id)

        Raises:
            KeyError:  field not found in this task.
            TypeError: field type does not have an internal ID
                       (e.g. text, number, date).
            ValueError: field value is empty (None).
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        if field.value is None:
            raise ValueError(
                f"Field {field_name!r} (id={field.id}) has no value (None)."
            )
        ftype = field.type.value if field.type else None

        if ftype == "multiple_choice":
            mc = field.as_multiple_choice()
            if mc and mc.choice_ids:
                return mc.choice_ids[0] if len(mc.choice_ids) == 1 else mc.choice_ids
            raise ValueError(f"Field {field_name!r} has no choice_ids.")

        if ftype == "catalog":
            cat = field.as_catalog()
            if cat and cat.item_id is not None:
                return cat.item_id
            raise ValueError(f"Field {field_name!r} has no item_id.")

        if ftype in ("person", "author"):
            p = field.as_person()
            if p and p.id:
                return p.id
            raise ValueError(f"Field {field_name!r} has no person_id.")

        if ftype == "form_link":
            fl = field.as_form_link()
            if fl and fl.task_ids:
                return fl.task_ids
            raise ValueError(f"Field {field_name!r} has no task_ids.")

        raise TypeError(
            f"Field {field_name!r} (type={ftype!r}) does not have "
            f"an internal ID. Use ctx.raw({field_name!r}) for the "
            f"raw FormField object."
        )

    # Alias
    value_id = get_value_id

    def dump(self, field_name: str | None = None) -> dict:
        """Return raw JSON-like dict of a field or the entire task.

        Получить «сырые» данные поля или задачи целиком в виде dict.

        - ``ctx.dump("Поле")`` → dict of that field (id, name, type, value, …)
        - ``ctx.dump()``       → dict of the entire task (all fields, comments, …)

        Example::

            ctx.dump("Тип запроса")
            # → {'id': 5, 'type': 'catalog', 'name': 'Тип запроса',
            #    'value': {'item_id': 123, 'values': ['10', 'Alpha', 'Web'], ...}}

            ctx.dump()  # → full task dict
        """
        if field_name is None:
            return self._task.model_dump(mode="python")
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        return field.model_dump(mode="python")

    # Aliases — both names work / Оба имени работают
    field_id = get_id
    field_type = get_type

    async def get_catalog_id(self, field_name: str) -> int:
        """Return the catalog ID linked to a catalog-type field.

        Получить ID каталога, привязанного к полю типа ``catalog``.

        Fetches the form definition to resolve the catalog reference
        (catalog_id is not available in the task response, only in the form).

        Example::

            cat_id = await ctx.get_catalog_id("Тип запроса")  # → 1910
            catalog = await client.get_catalog(cat_id)
            for item in catalog.items:
                print(item.item_id, item.values[:3])

        Raises:
            KeyError:  field not found in this task.
            TypeError: field is not a catalog field.
            ValueError: catalog_id could not be resolved from the form definition.
        """
        field = self._task.get_field(field_name)
        if field is None:
            raise KeyError(
                f"Field {field_name!r} not found in task {self._task.id}. "
                f"Use task.find_fields(name='{field_name}') to inspect."
            )
        ftype = field.type.value if field.type else None
        if ftype != "catalog":
            raise TypeError(
                f"Field {field_name!r} (id={field.id}) is {ftype!r}, not 'catalog'."
            )
        form_id = self._task.form_id
        if form_id is None:
            raise ValueError(
                f"Task {self._task.id} has no form_id — cannot resolve catalog_id."
            )
        form = await self._client.get_form(form_id)
        form_field = form.get_field(field.id)
        cid = (
            form_field.info.get("catalog_id")
            if form_field and isinstance(form_field.info, dict)
            else None
        )
        if cid is None:
            raise ValueError(
                f"catalog_id not found in form definition for field "
                f"{field.id} ({field_name!r})."
            )
        return cid

    # Alias
    catalog_id = get_catalog_id

    def pending_count(self) -> int:
        """Number of uncommitted ``set()``-s waiting to be flushed."""
        return len(self._pending)

    def __repr__(self) -> str:
        return (
            f"<TaskContext task_id={self._task.id} "
            f"step={self._task.current_step} "
            f"pending={len(self._pending)}>"
        )

    # ------------------------------------------------------------------
    # Internal resolution
    # ------------------------------------------------------------------

    async def _warn_required_missing(self, action: str) -> None:
        """Pre-check: warn if required fields for the current step are empty.

        Called before approve/reject/finish to give the user early feedback.
        Accounts for pending ``set()``-s that haven't been flushed yet.

        Pre-check: предупреждение если обязательные поля текущего этапа
        не заполнены. Учитывает ещё не отправленные ``set()``-ы.
        """
        form_id = self._task.form_id
        step = self._task.current_step
        if not form_id or step is None:
            return
        try:
            form = await self._client.get_form(form_id)
            task_values: dict[int, Any] = {}
            _collect_task_values(self._task.fields, task_values)
            # Account for pending set()-s not yet flushed.
            for field, value in self._pending:
                task_values[field.id] = value
            missing: list[str] = []
            _collect_required_missing(form.fields, task_values, step, missing)
            if missing:
                names = ", ".join(missing)
                log.warning(
                    "%s(): required fields not filled for step %d: %s",
                    action,
                    step,
                    names,
                )
        except Exception:  # noqa: BLE001
            pass  # Don't block if form is unavailable.

    async def _raise_if_blocked(self, action: str) -> None:
        """Pyrus accepted the request (200 OK) but the step did not advance.

        Diagnoses the cause in this order:
        1. No approval rights (current user not in the approvers list for this step).
        2. Required fields not filled for this step.
        3. Generic message if the reason cannot be determined.
        """
        step = self._task.current_step

        # ── 1. Check approval rights ───────────────────────────────────────
        if step is not None and self._task.approvals:
            step_idx = step - 1
            if 0 <= step_idx < len(self._task.approvals):
                step_approvers = self._task.approvals[step_idx]
                if step_approvers:
                    approver_ids = {e.person.id for e in step_approvers if e.person}
                    approver_names = [
                        e.person.full_name or f"id={e.person.id}"
                        for e in step_approvers
                        if e.person
                    ]
                    current_user_id: int | None = None
                    try:
                        profile = await self._client.get_profile()
                        current_user_id = profile.person_id
                    except Exception:
                        pass
                    if current_user_id is not None and current_user_id not in approver_ids:
                        names_str = ", ".join(f"'{n}'" for n in approver_names[:5])
                        raise ValueError(
                            f"{action}() was accepted by the server, but step {step} did not advance.\n"
                            f"No approval rights: current user (id={current_user_id}) "
                            f"is not in the approvers list for step {step}.\n"
                            f"Approvers / Утверждающие: {names_str}"
                        )

        # ── 2. Required fields missing ─────────────────────────────────────
        missing: list[str] = []
        form_id = self._task.form_id
        if form_id and step is not None:
            try:
                form = await self._client.get_form(form_id)
                task_values: dict[int, Any] = {}
                _collect_task_values(self._task.fields, task_values)
                _collect_required_missing(form.fields, task_values, step, missing)
            except Exception:
                pass

        if missing:
            fields_str = "\n".join(f"  • {name}" for name in missing)
            raise ValueError(
                f"{action}() was accepted by the server, but step {step} did not advance.\n"
                f"Required fields not filled / Не заполнены обязательные поля:\n{fields_str}\n\n"
                f"Use ctx.fill(name, value) before calling {action}()."
            )

        # ── 3. Unknown reason ──────────────────────────────────────────────
        raise ValueError(
            f"{action}() was accepted by the server, but step {step} did not advance.\n"
            f"Possible reasons / Возможные причины:\n"
            f"  • required fields not filled for this step\n"
            f"  • no approval rights for this step"
        )

    async def _flush(self) -> list[dict]:
        """Resolve pending (field, value) → list[dict] for the API. Clears queue."""
        if not self._pending:
            return []
        updates: list[dict] = []
        for field, value in self._pending:
            updates.append(await self._resolve(field, value))
        self._pending.clear()
        return updates

    async def _resolve(self, field: FormField, value: Any) -> dict:
        """Resolve a single (field, value) to an API payload dict."""
        if value is None:
            return FieldUpdate.clear(field.id)

        ftype = field.type.value if field.type else None

        # --- multiple_choice: accept str (choice name) → auto lookup ---
        if ftype == "multiple_choice" and isinstance(value, str):
            form_id = self._task.form_id
            if form_id is None:
                raise ValueError(
                    f"Cannot resolve choice name {value!r}: task has no form_id "
                    f"(it's a free task, not a form task). Pass choice_id as int."
                )
            choices = await self._client.get_form_choices(form_id, field.id)
            if value not in choices:
                available = ", ".join(f"'{k}'" for k in list(choices.keys())[:15])
                raise ValueError(
                    f"Choice {value!r} not found in field {field.name!r} (id={field.id}).\n"
                    f"Available: {available}"
                )
            return FieldUpdate.choice(field.id, choices[value])

        # --- person / author: accept str (name / login / email) → auto lookup ---
        if ftype in ("person", "author") and isinstance(value, str):
            person = await self._client.find_member(value)
            if person is None:
                raise ValueError(
                    f"Person {value!r} not found.\n"
                    f"Try: await client.find_members('{value}') to see all candidates."
                )
            return FieldUpdate.person(field.id, person.id)

        # --- catalog: accept str (display text / column value) → auto lookup ---
        if ftype == "catalog" and isinstance(value, str):
            form_id = self._task.form_id
            if form_id is None:
                raise ValueError(
                    f"Cannot resolve catalog value {value!r}: task has no form_id "
                    f"(it's a free task, not a form task). Pass item_id as int."
                )
            # catalog_id lives in the form definition, not in the task field
            form = await self._client.get_form(form_id)
            form_field = form.get_field(field.id)
            catalog_id = (
                form_field.info.get("catalog_id")
                if form_field and isinstance(form_field.info, dict)
                else None
            )
            if catalog_id is None:
                raise ValueError(
                    f"Cannot resolve catalog value {value!r}: catalog_id not found "
                    f"for field {field.id} ({field.name!r}). Pass item_id as int."
                )
            catalog = await self._client.get_catalog(catalog_id)
            item = _find_catalog_item(catalog.items, value)
            if item is None:
                # Show first few items as hints
                hints: list[str] = []
                for it in catalog.items[:10]:
                    h = [v for v in it.values if v and not v.strip().lstrip("-").isdigit()]
                    if h:
                        hints.append(" / ".join(h[:3]))
                hint_str = ", ".join(f"'{h}'" for h in hints)
                raise ValueError(
                    f"Catalog item {value!r} not found in catalog "
                    f"{catalog.name!r} (id={catalog_id}, {len(catalog.items)} items).\n"
                    f"Examples: {hint_str}\n"
                    f"Pass item_id as int to set by ID."
                )
            return FieldUpdate.catalog(field.id, item.item_id)

        # --- everything else: delegate to typed FieldUpdate factory ---
        return FieldUpdate.from_field(field, value)
