"""Tests for Dispatcher — webhook processing, signature verification, BotResponse handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aiopyrus.bot.dispatcher import Dispatcher
from aiopyrus.bot.middleware import BaseMiddleware
from aiopyrus.exceptions import PyrusWebhookSignatureError
from aiopyrus.types.webhook import BotResponse


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.verify_signature = MagicMock(return_value=True)
    bot.parse_webhook = MagicMock(
        return_value=MagicMock(
            task_id=42,
            task=MagicMock(id=42),
            access_token="tok",
        )
    )
    bot.inject_token = MagicMock()
    return bot


class TestProcessWebhook:
    async def test_basic_webhook(self):
        dp = Dispatcher()
        bot = _make_bot()
        result = await dp.process_webhook({"event": "task_received"}, bot)
        assert isinstance(result, dict)
        bot.parse_webhook.assert_called_once()
        bot.inject_token.assert_called_once()

    async def test_verify_signature_success(self):
        dp = Dispatcher()
        bot = _make_bot()
        bot.verify_signature.return_value = True
        result = await dp.process_webhook(
            {"event": "test"},
            bot,
            verify_signature=True,
            raw_body=b"body",
            signature="valid-sig",
        )
        assert isinstance(result, dict)

    async def test_verify_signature_failure(self):
        dp = Dispatcher()
        bot = _make_bot()
        bot.verify_signature.return_value = False
        with pytest.raises(PyrusWebhookSignatureError):
            await dp.process_webhook(
                {"event": "test"},
                bot,
                verify_signature=True,
                raw_body=b"body",
                signature="bad-sig",
            )

    async def test_verify_signature_missing_body(self):
        dp = Dispatcher()
        bot = _make_bot()
        with pytest.raises(PyrusWebhookSignatureError, match="required"):
            await dp.process_webhook(
                {"event": "test"},
                bot,
                verify_signature=True,
                raw_body=None,
                signature=None,
            )

    async def test_handler_returns_bot_response(self):
        dp = Dispatcher()
        bot = _make_bot()

        async def handler(task):
            return BotResponse(text="Reply")

        dp.task_received()(handler)
        result = await dp.process_webhook({"event": "task_received"}, bot)
        assert result.get("text") == "Reply"

    async def test_handler_returns_dict(self):
        dp = Dispatcher()
        bot = _make_bot()

        async def handler(task):
            return {"text": "Direct dict"}

        dp.task_received()(handler)
        result = await dp.process_webhook({"event": "task_received"}, bot)
        assert result == {"text": "Direct dict"}

    async def test_handler_returns_none(self):
        dp = Dispatcher()
        bot = _make_bot()

        async def handler(task):
            return None

        dp.task_received()(handler)
        result = await dp.process_webhook({"event": "task_received"}, bot)
        assert result == {}

    async def test_handler_exception_returns_empty(self):
        dp = Dispatcher()
        bot = _make_bot()

        async def handler(task):
            raise RuntimeError("boom")

        dp.task_received()(handler)
        result = await dp.process_webhook({"event": "task_received"}, bot)
        assert result == {}


class TestDispatcherMiddleware:
    async def test_middleware_chain(self):
        dp = Dispatcher()
        bot = _make_bot()
        order: list[str] = []

        class MW1(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("mw1_before")
                result = await handler(payload, bot, data)
                order.append("mw1_after")
                return result

        class MW2(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("mw2_before")
                result = await handler(payload, bot, data)
                order.append("mw2_after")
                return result

        dp.middleware(MW1())
        dp.middleware(MW2())

        async def handler(task):
            order.append("handler")

        dp.task_received()(handler)
        await dp.process_webhook({"event": "task_received"}, bot)
        # MW1 wraps MW2 wraps handler
        assert order == ["mw1_before", "mw2_before", "handler", "mw2_after", "mw1_after"]

    async def test_middleware_registered_via_method(self):
        dp = Dispatcher()

        class MyMW(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):  # type: ignore[override]
                return await handler(payload, bot, data)

        dp.middleware(MyMW())

        assert len(dp._middlewares) == 1
