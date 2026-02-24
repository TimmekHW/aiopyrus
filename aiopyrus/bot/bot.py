from __future__ import annotations

import logging

from aiopyrus.types.task import ApprovalChoice, Task, TaskAction
from aiopyrus.types.webhook import WebhookPayload
from aiopyrus.user.client import UserClient
from aiopyrus.utils.crypto import verify_webhook_signature

log = logging.getLogger("aiopyrus.bot")


class PyrusBot(UserClient):
    """Pyrus bot client — extends UserClient with webhook verification
    and bot-specific convenience methods.

    PyrusBot inherits **all** UserClient methods (get_task, comment_task,
    get_register, get_inbox, etc.). The only addition is ``verify_signature``
    for webhook HMAC-SHA1 verification.

    For polling mode there is no difference between PyrusBot and UserClient —
    both work identically with ``Dispatcher.start_polling()``.

    Usage::

        bot = PyrusBot(login="bot@example", security_key="SECRET")
        await bot.auth()

    On-premise::

        bot = PyrusBot(
            login="user@corp.ru",
            security_key="KEY",
            base_url="https://pyrus.mycompany.ru",
            ssl_verify=False,
        )
    """

    def __init__(
        self,
        login: str,
        security_key: str,
        *,
        timeout: float = 30.0,
        base_url: str | None = None,
        api_version: str = "v4",
        auth_url: str | None = None,
        api_url: str | None = None,
        proxy: str | None = None,
        ssl_verify: bool = True,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
    ) -> None:
        super().__init__(
            login,
            security_key,
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
        self._security_key = security_key

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the HMAC-SHA1 signature from the ``X-Pyrus-Sig`` header."""
        return verify_webhook_signature(body, signature, self._security_key)

    def parse_webhook(self, data: dict) -> WebhookPayload:
        """Parse a raw webhook payload dict into a :class:`WebhookPayload`."""
        return WebhookPayload.model_validate(data)

    def inject_token(self, payload: WebhookPayload) -> None:
        """Use the access_token from the webhook payload for this bot session.

        Pyrus sends a fresh token with each webhook call — this injects it
        so subsequent API calls within the handler don't need a separate auth.
        """
        self._session.set_token(payload.access_token)

    # ------------------------------------------------------------------
    # Bot-specific shortcut actions
    # ------------------------------------------------------------------

    async def finish(self, task_id: int, *, text: str | None = None) -> Task:
        """Move the task to the next step (finished)."""
        return await self.comment_task(task_id, action=TaskAction.finished, text=text)

    async def reopen(self, task_id: int, *, text: str | None = None) -> Task:
        """Send the task back (reopen)."""
        return await self.comment_task(task_id, action=TaskAction.reopened, text=text)

    async def approve(self, task_id: int, *, text: str | None = None) -> Task:
        """Approve the current approval step."""
        return await self.comment_task(task_id, approval_choice=ApprovalChoice.approved, text=text)

    async def reject(self, task_id: int, *, text: str | None = None) -> Task:
        """Reject the current approval step."""
        return await self.comment_task(task_id, approval_choice=ApprovalChoice.rejected, text=text)

    async def acknowledge(self, task_id: int, *, text: str | None = None) -> Task:
        """Acknowledge the task without approving/rejecting."""
        return await self.comment_task(
            task_id, approval_choice=ApprovalChoice.acknowledged, text=text
        )

    async def reassign(self, task_id: int, to: int | dict, *, text: str | None = None) -> Task:
        """Reassign the task to another person."""
        return await self.comment_task(task_id, reassign_to=to, text=text)

    async def update_fields(
        self, task_id: int, updates: list[dict], *, text: str | None = None
    ) -> Task:
        """Update form fields and optionally leave a comment."""
        return await self.comment_task(task_id, field_updates=updates, text=text)
