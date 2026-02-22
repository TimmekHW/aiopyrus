from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

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
    private_channel = "private_channel"   # corp instances


# Kept for backwards compatibility and for use in request payloads
CommentChannel = ChannelType


class ChannelContact(PyrusModel):
    """Email address or display name of a channel participant."""

    email: Optional[str] = None
    name: Optional[str] = None


class Channel(PyrusModel):
    """External communication channel metadata attached to a comment.

    Pyrus returns this as an object (not a bare string) in GET responses.
    Use :class:`ChannelType` (= ``CommentChannel``) when *sending* a comment.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: Optional[ChannelType] = None
    to: Optional[ChannelContact] = None
    # ``from`` is a reserved keyword in Python — alias maps "from" → from_
    from_: Optional[ChannelContact] = Field(None, alias="from")


class ApprovalEntry(PyrusModel):
    """One approver inside a workflow step — person + their current choice.

    In ``approvals_added`` / ``approvals_rerequested`` comment fields the API
    also returns ``step`` (int) indicating which workflow step was affected.
    """

    person: Person
    approval_choice: Optional[ApprovalChoice] = None
    step: Optional[int] = None

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
    settings: Optional[Any] = None
    approval_choice: Optional[ApprovalChoice] = None


class Comment(PyrusModel):
    """A comment on a task (also represents task state changes)."""

    id: int
    text: Optional[str] = None
    formatted_text: Optional[str] = None   # HTML-formatted version
    create_date: Optional[datetime] = None
    author: Optional[Person] = None

    # --- Workflow actions ---
    action: Optional[TaskAction] = None
    changed_step: Optional[int] = None     # new step after action (form tasks)
    reset_to_step: Optional[int] = None    # previous step when workflow is reverted

    # --- Editing ---
    edit_comment_id: Optional[int] = None  # id of the original comment being edited

    # --- Approval ---
    approval_choice: Optional[ApprovalChoice] = None
    approval_step: Optional[int] = None
    approvals_added: Optional[list[list[ApprovalEntry]]] = None
    approvals_removed: Optional[list[ApprovalEntry]] = None
    approvals_rerequested: Optional[list[list[ApprovalEntry]]] = None

    # --- Reassignment ---
    # "reassigned_to" is the field name in the API response
    reassigned_to: Optional[Person] = None

    # --- Participants / subscribers ---
    participants_added: Optional[list[Person]] = None
    participants_removed: Optional[list[Person]] = None
    subscribers_added: Optional[list[Person]] = None
    subscribers_removed: Optional[list[Person]] = None
    subscribers_rerequested: Optional[list[Person]] = None

    # --- Form fields ---
    field_updates: Optional[list[FormField]] = None

    # --- Lists ---
    added_list_ids: Optional[list[int]] = None
    removed_list_ids: Optional[list[int]] = None

    # --- Attachments ---
    attachments: Optional[list[Attachment]] = None

    # --- Time tracking ---
    spent_minutes: Optional[int] = None

    # --- Due date ---
    # API returns "due" (not "due_date") when a comment sets the task due date
    due: Optional[str] = None
    due_date: Optional[str] = None
    cancel_due: Optional[bool] = None

    # --- Scheduling ---
    scheduled_date: Optional[str] = None
    scheduled_datetime_utc: Optional[datetime] = None

    # --- Mentions ---
    mentions: Optional[list[int]] = None     # list of mentioned person IDs
    reply_note_id: Optional[int] = None      # comment this replies to

    # --- External channel ---
    channel: Optional[Channel] = None

    # --- Role-based comment ---
    comment_as_roles: Optional[list[Role]] = None

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


class Task(PyrusModel):
    """A Pyrus task — either a free task or a form task."""

    id: int
    text: Optional[str] = None
    formatted_text: Optional[str] = None
    subject: Optional[str] = None
    create_date: Optional[datetime] = None
    last_modified_date: Optional[datetime] = None
    close_date: Optional[datetime] = None
    due_date: Optional[str] = None
    due: Optional[datetime] = None
    duration: Optional[int] = None           # minutes (for calendar events)
    scheduled_date: Optional[str] = None
    scheduled_datetime_utc: Optional[datetime] = None

    # --- People ---
    author: Optional[Person] = None
    responsible: Optional[Person] = None
    participants: list[Person] = []
    subscribers: list[SubscriberEntry] = []  # observers (corp: {person, settings})
    # approvals[step_index][approver_index]
    approvals: Optional[list[list[ApprovalEntry]]] = None

    # --- Hierarchy ---
    parent_task_id: Optional[int] = None
    linked_task_ids: list[int] = []

    # --- Form-specific ---
    form_id: Optional[int] = None
    fields: list[FormField] = []
    current_step: Optional[int] = None
    flat: Optional[bool] = None

    # --- Content ---
    comments: list[Comment] = []
    attachments: list[Attachment] = []

    # --- Lists / organisation ---
    list_ids: list[int] = []

    # --- Status ---
    deleted: Optional[bool] = None
    close_comment: Optional[str] = None
    # Corporate Pyrus instances return is_closed instead of / alongside close_date
    is_closed: Optional[bool] = None
    # Workflow step definitions embedded in the task (corp instances return a list)
    steps: Optional[list[dict]] = None

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
                Task._collect_fields(title.fields, name, value_contains, field_type, only_filled, results)

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
    has_more: Optional[bool] = None


class RegisterResponse(PyrusModel):
    tasks: list[Task] = []
    has_more: Optional[bool] = None
    total_count: Optional[int] = None


class AnnouncementComment(PyrusModel):
    id: int
    text: Optional[str] = None
    create_date: Optional[datetime] = None
    author: Optional[Person] = None
    attachments: Optional[list[Attachment]] = None


class Announcement(PyrusModel):
    id: int
    text: Optional[str] = None
    create_date: Optional[datetime] = None
    last_modified_date: Optional[datetime] = None
    author: Optional[Person] = None
    subscribers: list[Person] = []
    comments: list[AnnouncementComment] = []
    attachments: list[Attachment] = []
