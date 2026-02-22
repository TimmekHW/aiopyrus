from __future__ import annotations

import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable

from aiopyrus.bot.filters.base import Filter

if TYPE_CHECKING:
    from aiopyrus.bot.bot import PyrusBot
    from aiopyrus.types.webhook import WebhookPayload

log = logging.getLogger("aiopyrus.router")


class Handler:
    """Wraps a single event handler function together with its filters."""

    def __init__(self, func: Callable, filters: tuple[Filter, ...]) -> None:
        self.func = func
        self.filters = filters

    async def check(self, payload: "WebhookPayload") -> dict | bool:
        """Run all filters. Returns merged extra-kwargs dict on pass, False on fail."""
        extra: dict = {}
        for f in self.filters:
            result = await f(payload)
            if not result:
                return False
            if isinstance(result, dict):
                extra.update(result)
        return extra or True

    async def call(self, payload: "WebhookPayload", bot: "PyrusBot", extra: dict) -> Any:
        """Invoke the handler, injecting only the parameters it accepts."""
        sig = inspect.signature(self.func)
        kwargs: dict[str, Any] = {}
        ctx: Any = None  # lazy-init TaskContext only when needed
        for name in sig.parameters:
            if name == "payload":
                kwargs["payload"] = payload
            elif name == "task":
                kwargs["task"] = payload.task
            elif name == "bot":
                kwargs["bot"] = bot
            elif name == "ctx":
                if ctx is None:
                    from aiopyrus.utils.context import TaskContext
                    ctx = TaskContext(payload.task, bot)
                kwargs["ctx"] = ctx
            elif name in extra:
                kwargs[name] = extra[name]
        return await self.func(**kwargs)


class Router:
    """Aiogram-style router for Pyrus bot events.

    Usage::

        router = Router()

        @router.task_received()
        async def on_any_task(task, bot):
            await bot.comment_task(task.id, text="Получил!")

        @router.task_received(FormFilter(321), StepFilter(2))
        async def on_step2(task, bot):
            await bot.approve_task(task.id)
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or "router"
        self._handlers: list[Handler] = []
        self._sub_routers: list["Router"] = []

    # ------------------------------------------------------------------
    # Registration decorators
    # ------------------------------------------------------------------

    def task_received(self, *filters: Filter) -> Callable:
        """Register a handler that fires when the bot receives a webhook event.

        Filters are ANDed together — all must pass for the handler to trigger.

        The decorated function may accept any combination of:
        - ``ctx``     — :class:`~aiopyrus.utils.context.TaskContext` (recommended)
        - ``task``    — shortcut for ``payload.task`` (low-level)
        - ``bot``     — the :class:`~aiopyrus.bot.PyrusBot` instance (low-level)
        - ``payload`` — the full :class:`~aiopyrus.types.WebhookPayload` (raw)
        """

        def decorator(func: Callable) -> Callable:
            if not asyncio.iscoroutinefunction(func):
                raise TypeError(f"Handler {func.__name__!r} must be an async function.")
            self._handlers.append(Handler(func, filters))
            log.debug("Registered handler %r on %r", func.__name__, self.name)
            return func

        return decorator

    # ------------------------------------------------------------------
    # Router nesting
    # ------------------------------------------------------------------

    def include_router(self, router: "Router") -> None:
        """Nest another router under this one."""
        self._sub_routers.append(router)
        log.debug("Router %r included into %r", router.name, self.name)

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    async def process_event(
        self,
        payload: "WebhookPayload",
        bot: "PyrusBot",
        *,
        middlewares: list | tuple = (),
    ) -> Any:
        """Try each handler in registration order; stop at the first match."""
        # Try this router's own handlers first
        for handler in self._handlers:
            check_result = await handler.check(payload)
            if check_result is not False:
                extra = check_result if isinstance(check_result, dict) else {}
                return await _apply_middlewares(handler, payload, bot, extra, middlewares)

        # Then sub-routers
        for sub in self._sub_routers:
            result = await sub.process_event(payload, bot, middlewares=middlewares)
            if result is not None:
                return result

        return None


async def _apply_middlewares(
    handler: Handler,
    payload: "WebhookPayload",
    bot: "PyrusBot",
    extra: dict,
    middlewares: list | tuple,
) -> Any:
    """Build a middleware chain and call the handler through it."""
    if not middlewares:
        return await handler.call(payload, bot, extra)

    async def call_next(pl: "WebhookPayload", b: "PyrusBot", data: dict) -> Any:
        return await handler.call(pl, b, data)

    # Build the chain from innermost outward
    func = call_next
    for mw in reversed(middlewares):
        _outer_mw = mw
        _inner = func

        async def wrapped(pl, b, data, _mw=_outer_mw, _next=_inner):
            return await _mw(_next, pl, b, data)

        func: Any = wrapped

    return await func(payload, bot, extra)
