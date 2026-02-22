"""Tests for Dispatcher.start_polling and start_webhook — the 42% coverage gap."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aiopyrus.bot.dispatcher import Dispatcher
from aiopyrus.types.task import Task


def _make_bot(tasks: list[Task] | None = None, fail: bool = False) -> MagicMock:
    """Create a mock bot with get_register that returns the given tasks."""
    bot = MagicMock()
    bot.close = AsyncMock()
    if fail:
        bot.get_register = AsyncMock(side_effect=RuntimeError("API error"))
    else:
        bot.get_register = AsyncMock(return_value=tasks or [])
    bot.verify_signature = MagicMock(return_value=True)
    bot.parse_webhook = MagicMock()
    bot.inject_token = MagicMock()
    return bot


def _make_task(task_id: int, modified: str = "2026-01-01T00:00:00") -> Task:
    from datetime import datetime

    dt = datetime.fromisoformat(modified)
    return Task(id=task_id, last_modified_date=dt)


# ── start_polling ─────────────────────────────────────────────


class TestStartPolling:
    async def test_skip_old_first_poll(self):
        """skip_old=True: first poll snapshots tasks, doesn't call handlers."""
        tasks = [_make_task(1), _make_task(2)]
        bot = _make_bot(tasks)
        dp = Dispatcher()
        handler_calls: list[int] = []

        @dp.task_received()
        async def handler(task):
            handler_calls.append(task.id)

        poll_count = 0
        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 2:
                raise asyncio.CancelledError()
            await original_sleep(0)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, interval=0.01, skip_old=True)

        # Handler was NOT called on first poll (snapshot)
        assert handler_calls == []
        bot.close.assert_called_once()

    async def test_skip_old_false_processes_all(self):
        """skip_old=False: first poll processes all tasks immediately."""
        tasks = [_make_task(1), _make_task(2)]
        bot = _make_bot(tasks)
        dp = Dispatcher()
        handler_calls: list[int] = []

        @dp.task_received()
        async def handler(task):
            handler_calls.append(task.id)

        poll_count = 0

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, interval=0.01, skip_old=False)

        assert sorted(handler_calls) == [1, 2]
        bot.close.assert_called_once()

    async def test_detects_task_changes(self):
        """Second poll with changed modified date triggers handler."""
        task_v1 = _make_task(1, modified="2026-01-01T00:00:00")
        task_v2 = _make_task(1, modified="2026-01-02T00:00:00")
        bot = MagicMock()
        bot.close = AsyncMock()

        call_count = 0

        async def get_register_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [task_v1]  # first poll: snapshot
            return [task_v2]  # second poll: modified

        bot.get_register = AsyncMock(side_effect=get_register_side_effect)

        dp = Dispatcher()
        handler_calls: list[int] = []

        @dp.task_received()
        async def handler(task):
            handler_calls.append(task.id)

        poll_count = 0

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, interval=0.01, skip_old=True)

        # task 1 was modified → handler called on second poll
        assert handler_calls == [1]

    async def test_unchanged_task_not_reprocessed(self):
        """If modified date stays the same, handler is NOT called again."""
        task = _make_task(1, modified="2026-01-01T00:00:00")
        bot = _make_bot([task])
        dp = Dispatcher()
        handler_calls: list[int] = []

        @dp.task_received()
        async def handler(task):
            handler_calls.append(task.id)

        poll_count = 0

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 3:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, interval=0.01, skip_old=False)

        # Only called once (first poll), not on subsequent polls
        assert handler_calls == [1]

    async def test_steps_as_int(self):
        """steps=6 should be converted to [6]."""
        bot = _make_bot([])
        dp = Dispatcher()

        poll_count = 0

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, steps=6, interval=0.01)

        bot.get_register.assert_called_with(321, steps=[6])

    async def test_on_startup_shutdown_called(self):
        """on_startup and on_shutdown callbacks are invoked."""
        bot = _make_bot([])
        dp = Dispatcher()
        startup_called = False
        shutdown_called = False

        async def on_startup():
            nonlocal startup_called
            startup_called = True

        async def on_shutdown():
            nonlocal shutdown_called
            shutdown_called = True

        async def fake_sleep(seconds):
            raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(
                bot, form_id=321, interval=0.01,
                on_startup=on_startup, on_shutdown=on_shutdown,
            )

        assert startup_called
        assert shutdown_called

    async def test_handler_exception_does_not_crash(self):
        """If a handler raises, polling continues."""
        tasks = [_make_task(1)]
        bot = _make_bot(tasks)
        dp = Dispatcher()

        @dp.task_received()
        async def handler(task):
            raise RuntimeError("boom")

        poll_count = 0

        async def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            # Should NOT raise — the error is logged and swallowed
            await dp.start_polling(bot, form_id=321, interval=0.01, skip_old=False)

    async def test_api_error_backoff(self):
        """On API error, backoff is applied and polling retries."""
        bot = _make_bot(fail=True)
        dp = Dispatcher()

        sleep_durations: list[float] = []

        async def fake_sleep(seconds):
            sleep_durations.append(seconds)
            if len(sleep_durations) >= 3:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await dp.start_polling(bot, form_id=321, interval=0.01)

        # First retry after 5s, second after 10s
        assert sleep_durations[0] == 5.0
        assert sleep_durations[1] == 10.0


# ── start_webhook ─────────────────────────────────────────────


class TestStartWebhook:
    async def test_start_webhook_creates_app(self):
        """start_webhook calls create_app and run_app."""
        dp = Dispatcher()
        bot = _make_bot()

        with (
            patch("aiopyrus.bot.webhook.server.create_app") as mock_create,
            patch("aiopyrus.bot.webhook.server.run_app", new_callable=AsyncMock) as mock_run,
        ):
            mock_app = MagicMock()
            mock_app.on_startup = []
            mock_app.on_shutdown = []
            mock_create.return_value = mock_app

            await dp.start_webhook(bot, host="127.0.0.1", port=9090, path="/pyrus")

            mock_create.assert_called_once_with(
                dispatcher=dp, bot=bot, path="/pyrus", verify_signature=True,
            )
            mock_run.assert_called_once_with(mock_app, host="127.0.0.1", port=9090)

    async def test_start_webhook_with_callbacks(self):
        """on_startup/on_shutdown are attached to the aiohttp app."""
        dp = Dispatcher()
        bot = _make_bot()

        startup = AsyncMock()
        shutdown = AsyncMock()

        with (
            patch("aiopyrus.bot.webhook.server.create_app") as mock_create,
            patch("aiopyrus.bot.webhook.server.run_app", new_callable=AsyncMock),
        ):
            mock_app = MagicMock()
            mock_app.on_startup = []
            mock_app.on_shutdown = []
            mock_create.return_value = mock_app

            await dp.start_webhook(
                bot,
                on_startup=startup,
                on_shutdown=shutdown,
            )

            assert startup in mock_app.on_startup
            assert shutdown in mock_app.on_shutdown
