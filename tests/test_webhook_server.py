"""Tests for webhook server (aiohttp handler, signature verification)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from aiopyrus.bot.webhook.server import create_app
from aiopyrus.exceptions import PyrusWebhookSignatureError


def _make_app(
    *,
    verify_signature: bool = False,
    process_webhook_result: dict | None = None,
    process_webhook_side_effect: Exception | None = None,
) -> tuple[web.Application, MagicMock, MagicMock]:
    """Create a test app with mocked bot and dispatcher."""
    bot = MagicMock()
    bot.verify_signature = MagicMock(return_value=True)

    dp = MagicMock()
    if process_webhook_side_effect:
        dp.process_webhook = AsyncMock(side_effect=process_webhook_side_effect)
    else:
        dp.process_webhook = AsyncMock(return_value=process_webhook_result or {})

    app = create_app(dispatcher=dp, bot=bot, path="/pyrus", verify_signature=verify_signature)
    return app, bot, dp


class TestWebhookHandler:
    """Test the webhook handler using aiohttp test client."""

    async def test_valid_json_returns_200(self):
        app, bot, dp = _make_app(process_webhook_result={"task": "ok"})
        async with TestClient(TestServer(app)) as client:
            payload = {"event": "task_received", "task_id": 42}
            resp = await client.post("/pyrus", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data == {"task": "ok"}
            dp.process_webhook.assert_called_once()

    async def test_invalid_json_returns_400(self):
        app, bot, dp = _make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", data=b"not json{{{")
            assert resp.status == 400
            text = await resp.text()
            assert "Invalid JSON" in text

    async def test_dispatcher_exception_returns_500(self):
        app, bot, dp = _make_app(process_webhook_side_effect=RuntimeError("boom"))
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", json={"event": "test"})
            assert resp.status == 500

    async def test_signature_failure_returns_403(self):
        app, bot, dp = _make_app(
            verify_signature=True,
            process_webhook_side_effect=PyrusWebhookSignatureError("bad sig"),
        )
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/pyrus",
                json={"event": "test"},
                headers={"X-Pyrus-Sig": "invalid"},
            )
            assert resp.status == 403

    async def test_empty_response_returns_empty_dict(self):
        app, bot, dp = _make_app(process_webhook_result={})
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/pyrus", json={"event": "test"})
            assert resp.status == 200
            data = await resp.json()
            assert data == {}

    async def test_retry_header_passed(self):
        app, bot, dp = _make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/pyrus",
                json={"event": "test"},
                headers={"X-Pyrus-Retry": "1"},
            )
            assert resp.status == 200


class TestCreateApp:
    def test_custom_path(self):
        app, _, _ = _make_app()
        # The route should be registered at /pyrus
        resources = [r.get_info().get("path", "") for r in app.router.resources()]
        assert "/pyrus" in resources

    def test_app_stores_settings(self):
        app, bot, dp = _make_app(verify_signature=True)
        assert app["dispatcher"] is dp
        assert app["bot"] is bot
        assert app["verify_signature"] is True
