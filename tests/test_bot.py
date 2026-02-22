"""Tests for PyrusBot convenience methods and webhook helpers."""

from __future__ import annotations

import httpx
import pytest
import respx

from aiopyrus.bot.bot import PyrusBot
from aiopyrus.types.task import ApprovalChoice, TaskAction
from aiopyrus.types.webhook import WebhookPayload

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"
FILES_BASE = "https://files.pyrus.com/"


def _mock_auth(token: str = "test-token") -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": token,
                "api_url": API_BASE,
                "files_url": FILES_BASE,
            },
        )
    )


def _mock_comment(task_id: int = 42) -> None:
    respx.post(f"{API_BASE}tasks/{task_id}/comments").mock(
        return_value=httpx.Response(
            200,
            json={"task": {"id": task_id, "text": "Test"}},
        )
    )


@pytest.fixture
def bot():
    return PyrusBot(login="bot@example", security_key="SECRET")


# ── Webhook helpers ─────────────────────────────────────────


class TestWebhookHelpers:
    def test_verify_signature(self, bot):
        import hashlib
        import hmac

        body = b'{"task_id": 42}'
        sig = hmac.new(b"SECRET", body, hashlib.sha1).hexdigest()
        assert bot.verify_signature(body, sig) is True

    def test_verify_signature_invalid(self, bot):
        assert bot.verify_signature(b"body", "wrong") is False

    def test_parse_webhook(self, bot):
        data = {
            "event": "task_received",
            "access_token": "tok",
            "task_id": 42,
            "task": {"id": 42, "text": "Test"},
        }
        payload = bot.parse_webhook(data)
        assert isinstance(payload, WebhookPayload)
        assert payload.task_id == 42

    def test_inject_token(self, bot):
        from aiopyrus.types.task import Task

        payload = WebhookPayload(
            event="task_received",
            access_token="fresh-token",
            task_id=42,
            task=Task(id=42, text="Test"),
        )
        bot.inject_token(payload)
        assert bot._session._access_token == "fresh-token"


# ── Convenience methods ─────────────────────────────────────


class TestConvenienceMethods:
    @respx.mock
    async def test_finish(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        task = await bot.finish(42, text="Done")
        assert task.id == 42
        call_body = respx.calls.last.request.content
        import json

        body = json.loads(call_body)
        assert body["action"] == TaskAction.finished.value
        assert body["text"] == "Done"
        await bot.close()

    @respx.mock
    async def test_reopen(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.reopen(42)
        body_bytes = respx.calls.last.request.content
        import json

        body = json.loads(body_bytes)
        assert body["action"] == TaskAction.reopened.value
        await bot.close()

    @respx.mock
    async def test_approve(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.approve(42, text="OK")
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == ApprovalChoice.approved.value
        await bot.close()

    @respx.mock
    async def test_reject(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.reject(42)
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == ApprovalChoice.rejected.value
        await bot.close()

    @respx.mock
    async def test_acknowledge(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.acknowledge(42, text="Seen")
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == ApprovalChoice.acknowledged.value
        await bot.close()

    @respx.mock
    async def test_reassign(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.reassign(42, to=100500, text="Take it")
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["reassign_to"] == {"id": 100500}
        assert body["text"] == "Take it"
        await bot.close()

    @respx.mock
    async def test_reassign_dict(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        await bot.reassign(42, to={"id": 100500})
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["reassign_to"] == {"id": 100500}
        await bot.close()

    @respx.mock
    async def test_update_fields(self, bot):
        _mock_auth()
        _mock_comment()
        await bot.auth()
        updates = [{"id": 1, "value": "test"}]
        await bot.update_fields(42, updates, text="Updated")
        import json

        body = json.loads(respx.calls.last.request.content)
        assert body["field_updates"] == updates
        assert body["text"] == "Updated"
        await bot.close()
