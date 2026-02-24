from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiopyrus.bot.bot import PyrusBot
from aiopyrus.bot.middleware import BaseMiddleware
from aiopyrus.bot.router import Router
from aiopyrus.exceptions import PyrusWebhookSignatureError
from aiopyrus.types.webhook import BotResponse

log = logging.getLogger("aiopyrus.dispatcher")


class Dispatcher(Router):
    """Top-level event dispatcher — the heart of the aiopyrus bot.

    Usage::

        bot = PyrusBot(login="bot@example", security_key="SECRET")
        dp  = Dispatcher()

        dp.include_router(my_router)
        dp.middleware(LoggingMiddleware())

        # Start the webhook server
        await dp.start_webhook(bot, host="0.0.0.0", port=8080, path="/pyrus")
    """

    def __init__(self) -> None:
        super().__init__(name="root")
        self._middlewares: list[BaseMiddleware] = []

    # ------------------------------------------------------------------
    # Middleware registration
    # ------------------------------------------------------------------

    def middleware(self, mw: BaseMiddleware) -> BaseMiddleware:
        """Register a middleware.

        Can be used as a regular method::

            dp.middleware(LoggingMiddleware())

        Or as a decorator::

            @dp.middleware
            class MyMW(BaseMiddleware): ...
        """
        self._middlewares.append(mw)
        log.debug("Middleware %r registered", type(mw).__name__)
        return mw

    # ------------------------------------------------------------------
    # Webhook processing
    # ------------------------------------------------------------------

    async def process_webhook(
        self,
        payload_data: dict,
        bot: PyrusBot,
        *,
        verify_signature: bool = False,
        raw_body: bytes | None = None,
        signature: str | None = None,
    ) -> dict:
        """Parse and dispatch a webhook payload.

        Returns a dict that should be sent back as the HTTP response body
        (an empty dict ``{}`` is valid and means "no inline action").

        Parameters
        ----------
        payload_data:
            Parsed JSON dict from Pyrus.
        bot:
            The PyrusBot instance. Its token will be updated from the payload.
        verify_signature:
            If True, verify the HMAC-SHA1 signature before processing.
        raw_body:
            Raw request body bytes (required when ``verify_signature=True``).
        signature:
            Value of the ``X-Pyrus-Sig`` header (required when verifying).
        """
        if verify_signature:
            if not raw_body or not signature:
                raise PyrusWebhookSignatureError(
                    "raw_body and signature are required for verification."
                )
            if not bot.verify_signature(raw_body, signature):
                raise PyrusWebhookSignatureError("Webhook signature verification failed.")

        payload = bot.parse_webhook(payload_data)

        # Inject the fresh token from the webhook so the bot can make API calls
        bot.inject_token(payload)

        try:
            result = await self.process_event(payload, bot, middlewares=self._middlewares)
        except Exception:
            log.exception("Unhandled exception in handler for task_id=%s", payload.task_id)
            return {}

        # If the handler returned a BotResponse or a dict, send it back
        if isinstance(result, BotResponse):
            return result.model_dump_clean()
        if isinstance(result, dict):
            return result
        return {}

    # ------------------------------------------------------------------
    # Webhook server (aiohttp)
    # ------------------------------------------------------------------

    async def start_polling(
        self,
        bot: PyrusBot,
        *,
        form_id: int | list[int],
        steps: list[int] | int | None = None,
        interval: float = 30.0,
        skip_old: bool = True,
        on_startup: Any = None,
        on_shutdown: Any = None,
    ) -> None:
        """Poll the form register and dispatch tasks through the same handlers as webhook mode.

        No server needed — works behind any firewall.
        Use the same ``@router.task_received(FormFilter(...), StepFilter(...))`` handlers.

        Tracks ``last_modified_date`` per task — a handler fires only when the task changes.

        Parameters
        ----------
        bot:
            Bot instance (already configured with credentials).
        form_id:
            Form(s) to poll. Single int or list of ints.
            Pyrus API requires form_id — there is no "all forms" endpoint.
            To poll all forms, call ``bot.get_forms()`` first and pass IDs.
        steps:
            Step number(s) to filter by. ``None`` — all steps.
        interval:
            Seconds between polls (default ``30``).
        skip_old:
            If ``True`` (default), the **first poll** is a snapshot — existing
            tasks are recorded in ``seen`` but handlers are **not** called.
            Handlers only fire for tasks that **change after** the bot starts.

            If ``False``, all matching tasks trigger handlers on the very first
            poll (useful for backlog processing).

            Note: even with ``skip_old=True``, if an old task receives an update
            (new comment, step change, field edit) after the bot starts, the
            handler **will** fire because the task's ``last_modified_date`` has
            changed since the snapshot.
        on_startup / on_shutdown:
            Optional async callables executed at start/stop.

        Example::

            bot = PyrusBot(login="bot@...", security_key="SECRET", api_url="...")
            dp  = Dispatcher()

            @dp.task_received(FormFilter(321), StepFilter(6))
            async def on_step6(ctx: TaskContext):
                await ctx.approve("Auto-approved")

            # skip_old=True (default) — only new changes trigger handlers
            asyncio.run(dp.start_polling(bot, form_id=321, steps=6, interval=30))

            # skip_old=False — process the entire backlog on start
            asyncio.run(dp.start_polling(bot, form_id=321, steps=6, skip_old=False))
        """
        from aiopyrus.types.webhook import WebhookPayload

        form_ids = [form_id] if isinstance(form_id, int) else list(form_id)
        step_list = [steps] if isinstance(steps, int) else steps

        if on_startup:
            await on_startup()

        log.info(
            "Polling started: form_ids=%s  steps=%s  interval=%.0fs  skip_old=%s",
            form_ids,
            step_list,
            interval,
            skip_old,
        )

        # task_id → last_modified_date string (tracks what we've already processed)
        seen: dict[int, str] = {}
        is_first_poll = True

        _BACKOFF_BASE = 5.0  # first retry after 5 s
        _BACKOFF_MAX = 300.0  # cap at 5 min
        backoff = _BACKOFF_BASE

        try:
            while True:
                try:
                    tasks = []
                    for fid in form_ids:
                        tasks.extend(await bot.get_register(fid, steps=step_list))
                    backoff = _BACKOFF_BASE  # reset on success

                    for task in tasks:
                        stamp = str(task.last_modified_date or task.id)
                        if seen.get(task.id) == stamp:
                            continue
                        seen[task.id] = stamp

                        # First poll + skip_old: snapshot only, don't call handlers
                        if is_first_poll and skip_old:
                            continue

                        payload = WebhookPayload(
                            event="task_polled",
                            task_id=task.id,
                            task=task,
                        )
                        try:
                            await self.process_event(payload, bot, middlewares=self._middlewares)
                        except Exception:
                            log.exception("Handler error for task_id=%d", task.id)

                    if is_first_poll:
                        if skip_old:
                            log.info(
                                "Snapshot taken: %d tasks recorded, waiting for changes", len(seen)
                            )
                        is_first_poll = False

                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Polling error, retrying in %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _BACKOFF_MAX)
                    continue  # skip normal interval after an error

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            log.info("Polling cancelled.")
        finally:
            if on_shutdown:
                await on_shutdown()
            await bot.close()

    async def start_webhook(
        self,
        bot: PyrusBot,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        path: str = "/",
        verify_signature: bool = True,
        on_startup: Any = None,
        on_shutdown: Any = None,
    ) -> None:
        """Start an aiohttp server to receive Pyrus webhook calls.

        This is a blocking call — it runs until interrupted.

        Parameters
        ----------
        bot:
            Bot instance to inject into every handler.
        host / port:
            Server listen address.
        path:
            URL path for the webhook endpoint (e.g. ``"/pyrus"``).
        verify_signature:
            Whether to verify the ``X-Pyrus-Sig`` header on each request.
        on_startup / on_shutdown:
            Optional async callables executed at server start/stop.
        """
        from aiopyrus.bot.webhook.server import create_app, run_app

        app = create_app(dispatcher=self, bot=bot, path=path, verify_signature=verify_signature)

        if on_startup:
            app.on_startup.append(on_startup)
        if on_shutdown:
            app.on_shutdown.append(on_shutdown)

        log.info("Starting webhook server on http://%s:%d%s", host, port, path)
        await run_app(app, host=host, port=port)
