from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field

from .base import PyrusModel
from .file import Attachment
from .form import FormField
from .user import Person, Role


class ApprovalChoice(str, Enum):
    approved = "approved"
    rejected = "rejected"
    acknowledged = "acknowledged"
    revoked = "revoked"
    waiting = "waiting"


class TaskAction(str, Enum):
    finished = "finished"
    reopened = "reopened"


class ChannelType(str, Enum):
    """External channel types (GET response from Pyrus)."""

    email = "email"
    telegram = "telegram"
    sms = "sms"
    facebook = "facebook"
    vk = "vk"
    viber = "viber"
    mobile_app = "mobile_app"
    web_widget = "web_widget"
    avito_job = "avito_job"
    avito_messenger = "avito_messenger"
    zadarma = "zadarma"
    amo_crm = "amo_crm"
    private_channel = "private_channel"  # corp instances


# Kept for backwards compatibility and for use in request payloads
CommentChannel = ChannelType


class ChannelContact(PyrusModel):
    """Email address or display name of a channel participant."""

    email: str | None = None
    name: str | None = None


class Channel(PyrusModel):
    """External communication channel metadata attached to a comment.

    Pyrus returns this as an object (not a bare string) in GET responses.
    Use :class:`ChannelType` (= ``CommentChannel``) when *sending* a comment.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: ChannelType | None = None
    to: ChannelContact | None = None
    # ``from`` is a reserved keyword in Python — alias maps "from" → from_
    from_: ChannelContact | None = Field(None, alias="from")


class ApprovalEntry(PyrusModel):
    """One approver inside a workflow step — person + their current choice.

    In ``approvals_added`` / ``approvals_rerequested`` comment fields the API
    also returns ``step`` (int) indicating which workflow step was affected.
    """

    person: Person
    approval_choice: ApprovalChoice | None = None
    step: int | None = None

    @property
    def is_waiting(self) -> bool:
        return self.approval_choice in (ApprovalChoice.waiting, None)

    @property
    def is_approved(self) -> bool:
        return self.approval_choice == ApprovalChoice.approved

    @property
    def is_rejected(self) -> bool:
        return self.approval_choice == ApprovalChoice.rejected


class SubscriberEntry(PyrusModel):
    """A task subscriber/participant — person + optional notification settings.

    Corp Pyrus instances return ``{person: {...}, settings: {...}}`` objects
    instead of bare Person objects in the ``subscribers`` list.
    """

    person: Person
    settings: Any | None = None
    approval_choice: ApprovalChoice | None = None


class Comment(PyrusModel):
    """A comment on a task (also represents task state changes)."""

    id: int
    text: str | None = None
    formatted_text: str | None = None  # HTML-formatted version
    create_date: datetime | None = None
    author: Person | None = None

    # --- Workflow actions ---
    action: TaskAction | None = None
    changed_step: int | None = None  # new step after action (form tasks)
    reset_to_step: int | None = None  # previous step when workflow is reverted

    # --- Editing ---
    edit_comment_id: int | None = None  # id of the original comment being edited

    # --- Approval ---
    approval_choice: ApprovalChoice | None = None
    approval_step: int | None = None
    approvals_added: list[list[ApprovalEntry]] | None = None
    approvals_removed: list[list[ApprovalEntry]] | None = None
    approvals_rerequested: list[list[ApprovalEntry]] | None = None

    # --- Reassignment ---
    # "reassigned_to" is the field name in the API response
    reassigned_to: Person | None = None

    # --- Participants / subscribers ---
    participants_added: list[Person] | None = None
    participants_removed: list[Person] | None = None
    subscribers_added: list[Person] | None = None
    subscribers_removed: list[Person] | None = None
    subscribers_rerequested: list[Person] | None = None

    # --- Form fields ---
    field_updates: list[FormField] | None = None

    # --- Lists ---
    added_list_ids: list[int] | None = None
    removed_list_ids: list[int] | None = None

    # --- Attachments ---
    attachments: list[Attachment] | None = None

    # --- Time tracking ---
    spent_minutes: int | None = None

    # --- Due date ---
    # API returns "due" (not "due_date") when a comment sets the task due date
    due: str | None = None
    due_date: str | None = None
    cancel_due: bool | None = None

    # --- Scheduling ---
    scheduled_date: str | None = None
    scheduled_datetime_utc: datetime | None = None

    # --- Mentions ---
    mentions: list[int] | None = None  # list of mentioned person IDs
    reply_note_id: int | None = None  # comment this replies to

    # --- External channel ---
    channel: Channel | None = None

    # --- Role-based comment ---
    comment_as_roles: list[Role] | None = None

    # ---- Convenience properties ----

    @property
    def is_approval(self) -> bool:
        return self.approval_choice is not None

    @property
    def is_approved(self) -> bool:
        return self.approval_choice == ApprovalChoice.approved

    @property
    def is_rejected(self) -> bool:
        return self.approval_choice == ApprovalChoice.rejected

    @property
    def is_finished(self) -> bool:
        return self.action == TaskAction.finished


class TaskStep(PyrusModel):
    """Workflow step progress embedded in a task response.

    Шаг маршрута внутри ответа по задаче — имя этапа + затраченное время.
    """

    step: int
    name: str = ""
    elapsed_time: int | None = None  # milliseconds spent on this step


class Task(PyrusModel):
    """A Pyrus task — either a free task or a form task.

    Задача Pyrus — свободная или по форме.

    Note: field availability depends on the API endpoint:

    - ``GET /inbox`` — only ``id``, ``author``, ``responsible``, ``text``,
      ``create_date``, ``last_modified_date``.  Everything else is ``None``/empty.
    - ``GET /forms/{id}/register`` — includes ``current_step`` and ``fields``,
      but ``form_id`` is always ``None`` (API omits it since you query by form).
    - ``GET /tasks/{id}`` — returns all fields including ``form_id``,
      ``current_step``, ``fields``, ``approvals``, ``comments``, etc.
    """

    id: int
    text: str | None = None
    formatted_text: str | None = None
    subject: str | None = None
    create_date: datetime | None = None
    last_modified_date: datetime | None = None
    close_date: datetime | None = None
    due_date: str | None = None
    due: datetime | None = None
    duration: int | None = None  # minutes (for calendar events)
    scheduled_date: str | None = None
    scheduled_datetime_utc: datetime | None = None

    # --- People ---
    author: Person | None = None
    responsible: Person | None = None
    participants: list[Person] = []
    subscribers: list[SubscriberEntry] = []  # observers (corp: {person, settings})
    # approvals[step_index][approver_index]
    approvals: list[list[ApprovalEntry]] | None = None

    # --- Hierarchy ---
    parent_task_id: int | None = None
    linked_task_ids: list[int] = []

    # --- Form-specific ---
    form_id: int | None = None
    fields: list[FormField] = []
    current_step: int | None = None
    flat: bool | None = None

    # --- Content ---
    comments: list[Comment] = []
    attachments: list[Attachment] = []

    # --- Lists / organisation ---
    list_ids: list[int] = []

    # --- Status ---
    deleted: bool | None = None
    close_comment: str | None = None
    # Corporate Pyrus instances return is_closed instead of / alongside close_date
    is_closed: bool | None = None
    # Workflow step definitions embedded in the task (corp instances return a list)
    steps: list[TaskStep] | None = None
    # Last comment id (present in register responses)
    last_note_id: int | None = None

    # ---- Convenience properties ----

    @property
    def is_form_task(self) -> bool:
        return self.form_id is not None

    @property
    def closed(self) -> bool:
        """True if the task is closed (works for both cloud and corp instances)."""
        return self.is_closed is True or self.close_date is not None

    @property
    def latest_comment(self) -> Comment | None:
        return self.comments[-1] if self.comments else None

    def get_field(self, id_or_name_or_code: int | str) -> FormField | None:
        """Find a field by id, name, or code.

        Searches recursively through nested fields inside ``title`` sections.
        """
        return self._find_field(self.fields, id_or_name_or_code)

    @staticmethod
    def _find_field(fields: list, key: int | str) -> FormField | None:
        for field in fields:
            if isinstance(key, int):
                if field.id == key:
                    return field
            else:
                if field.name == key or field.code == key:
                    return field
            # Recurse into title sub-fields
            title = field.as_title() if field.type and field.type.value == "title" else None
            if title and title.fields:
                found = Task._find_field(title.fields, key)
                if found:
                    return found
        return None

    def find_fields(
        self,
        *,
        name: str | None = None,
        value_contains: str | None = None,
        field_type: str | None = None,
        only_filled: bool = False,
    ) -> list[FormField]:
        """Search fields by partial name / value content / type.

        All criteria are combined with AND.

        Args:
            name:           Case-insensitive substring match against field name.
            value_contains: Case-insensitive substring search inside the string
                            representation of field.value.
            field_type:     Filter by field type string (e.g. ``"text"``,
                            ``"catalog"``, ``"multiple_choice"``).
            only_filled:    If True, skip fields whose value is None.

        Example::

            # Find all filled catalog fields whose name contains "тип"
            fields = task.find_fields(name="тип", field_type="catalog", only_filled=True)

            # Find the field that currently holds the value "ivanov"
            fields = task.find_fields(value_contains="ivanov")
        """
        results: list[FormField] = []
        self._collect_fields(self.fields, name, value_contains, field_type, only_filled, results)
        return results

    @staticmethod
    def _collect_fields(
        fields: list,
        name: str | None,
        value_contains: str | None,
        field_type: str | None,
        only_filled: bool,
        results: list,
    ) -> None:
        name_lo = name.lower() if name else None
        val_lo = value_contains.lower() if value_contains else None

        for field in fields:
            # Recurse into title sub-fields first (so sub-fields are also searched)
            title = field.as_title() if field.type and field.type.value == "title" else None
            if title and title.fields:
                Task._collect_fields(
                    title.fields, name, value_contains, field_type, only_filled, results
                )

            # Apply filters
            if only_filled and field.value is None:
                continue
            if name_lo and (not field.name or name_lo not in field.name.lower()):
                continue
            if field_type and (not field.type or field.type.value != field_type):
                continue
            if val_lo:
                field_val_str = str(field.value).lower() if field.value is not None else ""
                if val_lo not in field_val_str:
                    continue
            results.append(field)

    # ---- Approval helpers ----

    def get_approvals(
        self,
        step: int,
        *,
        choice: ApprovalChoice | str | None = None,
    ) -> list[ApprovalEntry]:
        """Get approvers for a workflow step, optionally filtered by choice.

        Получить согласующих на этапе, опционально отфильтровав по выбору.

        Args:
            step:   Workflow step number (1-based).
            choice: Filter by approval choice (e.g. ``ApprovalChoice.approved``).

        Example::

            task.get_approvals(2)
            task.get_approvals(2, choice="approved")
            task.get_approvals(2, choice=ApprovalChoice.waiting)
        """
        if not self.approvals or step < 1 or step > len(self.approvals):
            return []
        entries = self.approvals[step - 1]
        if choice is None:
            return list(entries)
        choice_val = choice.value if isinstance(choice, ApprovalChoice) else str(choice)
        return [
            e
            for e in entries
            if (e.approval_choice is not None and e.approval_choice.value == choice_val)
            or (choice_val == "waiting" and e.approval_choice is None)
        ]

    @property
    def approvals_by_step(self) -> dict[int, list[ApprovalEntry]]:
        """Approvals indexed by step number (1-based).

        Согласования, индексированные по номеру этапа (с 1).

        Returns:
            ``{1: [ApprovalEntry, ...], 2: [...]}``
        """
        if not self.approvals:
            return {}
        return {i + 1: list(entries) for i, entries in enumerate(self.approvals)}

    def get_approver_names(
        self, step: int, *, choice: ApprovalChoice | str | None = None
    ) -> list[str]:
        """Get approver full names for a step.

        Имена согласующих на этапе.
        """
        return [e.person.full_name for e in self.get_approvals(step, choice=choice)]

    def get_approver_emails(
        self, step: int, *, choice: ApprovalChoice | str | None = None
    ) -> list[str]:
        """Get approver emails for a step (skips persons without email).

        Email-адреса согласующих на этапе.
        """
        return [e.person.email for e in self.get_approvals(step, choice=choice) if e.person.email]

    def get_approver_ids(
        self, step: int, *, choice: ApprovalChoice | str | None = None
    ) -> list[int]:
        """Get approver person IDs for a step.

        ID согласующих на этапе.
        """
        return [e.person.id for e in self.get_approvals(step, choice=choice)]

    # ---- Convenience ----

    def context(self, client: Any) -> Any:
        """Обернуть задачу в aiogram-стайл TaskContext.

        Example::

            task = await client.get_task(12345678)
            ctx  = task.context(client)

            description = ctx["Описание"]
            ctx.set("Статус задачи", "В работе")
            await ctx.answer("Принято")
        """
        from aiopyrus.utils.context import TaskContext

        return TaskContext(self, client)

    def __repr__(self) -> str:
        return f"<Task id={self.id} form_id={self.form_id} step={self.current_step}>"


class TaskResponse(PyrusModel):
    task: Task


class InboxResponse(PyrusModel):
    tasks: list[Task] = []
    has_more: bool | None = None
    task_groups: list[Any] | None = None


class RegisterResponse(PyrusModel):
    tasks: list[Task] = []
    has_more: bool | None = None
    total_count: int | None = None


class AnnouncementComment(PyrusModel):
    id: int
    text: str | None = None
    create_date: datetime | None = None
    author: Person | None = None
    attachments: list[Attachment] | None = None


class TaskList(PyrusModel):
    """A Pyrus task list (project / kanban board).

    Список задач Pyrus (проект / канбан-доска).
    """

    id: int
    name: str = ""
    children: list[TaskList] = []
    color: str | None = None
    has_form: bool | None = None
    list_type: str | None = None  # "private" | "public" | ...
    version: int | None = None
    external_id: int | None = None
    manager_ids: list[int] = []


TaskList.model_rebuild()


class Announcement(PyrusModel):
    id: int
    text: str | None = None
    create_date: datetime | None = None
    last_modified_date: datetime | None = None
    author: Person | None = None
    subscribers: list[Person] = []
    comments: list[AnnouncementComment] = []
    attachments: list[Attachment] = []
