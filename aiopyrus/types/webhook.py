from __future__ import annotations

from typing import Any

from .base import PyrusModel
from .task import Task


class WebhookPayload(PyrusModel):
    """Incoming webhook payload from Pyrus when a task is delivered to a bot.

    In polling mode ``access_token`` is empty — the bot uses its own session token.
    """

    event: str
    access_token: str = ""
    task_id: int
    user_id: int | None = None
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

    text: str | None = None
    action: str | None = None  # "finished" | "reopened"
    approval_choice: str | None = None  # "approved" | "rejected" | ...
    field_updates: list[dict[str, Any]] | None = None
    reassign_to: dict[str, Any] | None = None
    approvals_added: list[list[dict[str, Any]]] | None = None
    approvals_removed: list[dict[str, Any]] | None = None
    participants_added: list[dict[str, Any]] | None = None
    participants_removed: list[dict[str, Any]] | None = None
    due_date: str | None = None
    cancel_due: bool | None = None
    scheduled_date: str | None = None
    spent_minutes: int | None = None
    attachments: list[str] | None = None  # list of GUIDs

    def model_dump_clean(self) -> dict[str, Any]:
        """Dump only set (non-None) fields for the response body."""
        return self.model_dump(exclude_none=True)
