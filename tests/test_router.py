"""Tests for Router, Handler, Dispatcher, and middleware pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from aiopyrus.bot.dispatcher import Dispatcher
from aiopyrus.bot.filters.builtin import FormFilter, StepFilter
from aiopyrus.bot.middleware import BaseMiddleware
from aiopyrus.bot.router import Handler, Router
from aiopyrus.types.webhook import BotResponse

from .conftest import make_payload

# ── Handler ──────────────────────────────────────────────────


class TestHandler:
    async def test_check_all_pass(self):
        p = make_payload(form_id=321, current_step=2)
        h = Handler(AsyncMock(), (FormFilter(321), StepFilter(2)))
        result = await h.check(p)
        assert result is True

    async def test_check_one_fails(self):
        p = make_payload(form_id=321, current_step=3)
        h = Handler(AsyncMock(), (FormFilter(321), StepFilter(2)))
        result = await h.check(p)
        assert result is False

    async def test_check_no_filters(self):
        p = make_payload()
        h = Handler(AsyncMock(), ())
        result = await h.check(p)
        assert result is True

    async def test_call_injects_task(self):
        called_with = {}

        async def handler(task):
            called_with["task"] = task

        p = make_payload()
        bot = AsyncMock()
        h = Handler(handler, ())
        await h.call(p, bot, {})
        assert called_with["task"].id == p.task.id

    async def test_call_injects_bot(self):
        called_with = {}

        async def handler(bot):
            called_with["bot"] = bot

        p = make_payload()
        bot = AsyncMock()
        h = Handler(handler, ())
        await h.call(p, bot, {})
        assert called_with["bot"] is bot

    async def test_call_injects_payload(self):
        called_with = {}

        async def handler(payload):
            called_with["payload"] = payload

        p = make_payload()
        h = Handler(handler, ())
        await h.call(p, AsyncMock(), {})
        assert called_with["payload"] is p

    async def test_call_injects_ctx(self):
        called_with = {}

        async def handler(ctx):
            called_with["ctx"] = ctx

        p = make_payload()
        h = Handler(handler, ())
        await h.call(p, AsyncMock(), {})
        assert called_with["ctx"] is not None
        assert called_with["ctx"].id == p.task.id


# ── Router ───────────────────────────────────────────────────


class TestRouter:
    async def test_register_handler(self):
        router = Router()

        @router.task_received(FormFilter(321))
        async def handler(task):
            pass

        assert len(router._handlers) == 1

    def test_sync_handler_raises(self):
        router = Router()
        with pytest.raises(TypeError, match="async"):

            @router.task_received()
            def handler(task):  # NOT async
                pass

    async def test_dispatch_first_match(self):
        router = Router()
        calls = []

        @router.task_received(FormFilter(321))
        async def h1(task):
            calls.append("h1")

        @router.task_received(FormFilter(321))
        async def h2(task):
            calls.append("h2")

        p = make_payload(form_id=321)
        await router.process_event(p, AsyncMock())
        assert calls == ["h1"]  # only first handler

    async def test_dispatch_no_match(self):
        router = Router()

        @router.task_received(FormFilter(999))
        async def handler(task):
            pass

        p = make_payload(form_id=321)
        result = await router.process_event(p, AsyncMock())
        assert result is None

    async def test_subrouter(self):
        parent = Router(name="parent")
        child = Router(name="child")
        calls = []

        @child.task_received(FormFilter(321))
        async def handler(task):
            calls.append("child")

        parent.include_router(child)
        p = make_payload(form_id=321)
        await parent.process_event(p, AsyncMock())
        assert calls == ["child"]

    async def test_parent_handler_takes_priority(self):
        parent = Router(name="parent")
        child = Router(name="child")
        calls = []

        @parent.task_received(FormFilter(321))
        async def parent_handler(task):
            calls.append("parent")

        @child.task_received(FormFilter(321))
        async def child_handler(task):
            calls.append("child")

        parent.include_router(child)
        p = make_payload(form_id=321)
        await parent.process_event(p, AsyncMock())
        assert calls == ["parent"]


# ── Middleware ────────────────────────────────────────────────


class TestMiddleware:
    async def test_middleware_wraps_handler(self):
        order = []

        class TrackingMiddleware(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("before")
                result = await handler(payload, bot, data)
                order.append("after")
                return result

        router = Router()

        @router.task_received()
        async def handler(task):
            order.append("handler")

        p = make_payload()
        await router.process_event(p, AsyncMock(), middlewares=[TrackingMiddleware()])
        assert order == ["before", "handler", "after"]

    async def test_multiple_middlewares(self):
        order = []

        class MW1(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("mw1-before")
                result = await handler(payload, bot, data)
                order.append("mw1-after")
                return result

        class MW2(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("mw2-before")
                result = await handler(payload, bot, data)
                order.append("mw2-after")
                return result

        router = Router()

        @router.task_received()
        async def handler(task):
            order.append("handler")

        p = make_payload()
        await router.process_event(p, AsyncMock(), middlewares=[MW1(), MW2()])
        # MW1 is outermost, MW2 is inner
        assert order == ["mw1-before", "mw2-before", "handler", "mw2-after", "mw1-after"]


# ── Dispatcher ───────────────────────────────────────────────


class TestDispatcher:
    async def test_process_webhook(self):
        dp = Dispatcher()

        @dp.task_received()
        async def handler(task):
            return BotResponse(text="OK")

        payload_data = {
            "event": "task_received",
            "access_token": "tok",
            "task_id": 1,
            "task": {"id": 1, "text": "Test"},
        }
        bot = AsyncMock()
        bot.parse_webhook = lambda data: __import__(
            "aiopyrus.types.webhook", fromlist=["WebhookPayload"]
        ).WebhookPayload.model_validate(data)
        bot.inject_token = lambda p: None
        bot.verify_signature = lambda b, s: True

        result = await dp.process_webhook(payload_data, bot)
        assert result.get("text") == "OK"

    async def test_process_webhook_no_match_returns_empty(self):
        dp = Dispatcher()

        @dp.task_received(FormFilter(999))
        async def handler(task):
            return BotResponse(text="OK")

        payload_data = {
            "event": "task_received",
            "access_token": "tok",
            "task_id": 1,
            "task": {"id": 1, "form_id": 321},
        }
        bot = AsyncMock()
        bot.parse_webhook = lambda data: __import__(
            "aiopyrus.types.webhook", fromlist=["WebhookPayload"]
        ).WebhookPayload.model_validate(data)
        bot.inject_token = lambda p: None

        result = await dp.process_webhook(payload_data, bot)
        assert result == {}

    async def test_middleware_registration(self):
        dp = Dispatcher()
        order = []

        class TestMW(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                order.append("mw")
                return await handler(payload, bot, data)

        dp.middleware(TestMW())

        @dp.task_received()
        async def handler(task):
            order.append("handler")

        payload_data = {
            "event": "task_received",
            "access_token": "tok",
            "task_id": 1,
            "task": {"id": 1},
        }
        bot = AsyncMock()
        bot.parse_webhook = lambda data: __import__(
            "aiopyrus.types.webhook", fromlist=["WebhookPayload"]
        ).WebhookPayload.model_validate(data)
        bot.inject_token = lambda p: None

        await dp.process_webhook(payload_data, bot)
        assert order == ["mw", "handler"]
