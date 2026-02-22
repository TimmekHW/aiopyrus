from __future__ import annotations

from typing import Optional

from .base import PyrusModel
from .task import Task


class WebhookPayload(PyrusModel):
    """Incoming webhook payload from Pyrus when a task is delivered to a bot.

    In polling mode ``access_token`` is empty — the bot uses its own session token.
    """

    event: str
    access_token: str = ""
    task_id: int
    user_id: Optional[int] = None
    task: Task

    @property
    def is_task_created(self) -> bool:
        return self.event == "task_created"

    @property
    def is_comment(self) -> bool:
        return self.event == "comment"


class BotResponse(PyrusModel):
    """Inline response body the bot can return to Pyrus.

    The structure mirrors POST /tasks/{task-id}/comments.
    All fields are optional — return an empty dict to do nothing inline.
    """

    text: Optional[str] = None
    action: Optional[str] = None  # "finished" | "reopened"
    approval_choice: Optional[str] = None  # "approved" | "rejected" | ...
    field_updates: Optional[list[dict]] = None
    reassign_to: Optional[dict] = None
    approvals_added: Optional[list[list[dict]]] = None
    approvals_removed: Optional[list[dict]] = None
    participants_added: Optional[list[dict]] = None
    participants_removed: Optional[list[dict]] = None
    due_date: Optional[str] = None
    cancel_due: Optional[bool] = None
    scheduled_date: Optional[str] = None
    spent_minutes: Optional[int] = None
    attachments: Optional[list[str]] = None  # list of GUIDs

    def model_dump_clean(self) -> dict:
        """Dump only set (non-None) fields for the response body."""
        return self.model_dump(exclude_none=True)
