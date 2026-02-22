from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiopyrus.bot.bot import PyrusBot
    from aiopyrus.types.webhook import WebhookPayload

# Handler type: async (payload, bot, **data) → BotResponse | None
HandlerType = Callable[..., Awaitable[Any]]


class BaseMiddleware(ABC):
    """Base class for aiopyrus middleware.

    Middleware wraps every handler call. Override ``__call__`` to add logic
    before and/or after the handler.

    Example — logging middleware::

        class LoggingMiddleware(BaseMiddleware):
            async def __call__(self, handler, payload, bot, data):
                print(f"[IN] task_id={payload.task_id}")
                result = await handler(payload, bot, data)
                print(f"[OUT] task_id={payload.task_id}")
                return result
    """

    @abstractmethod
    async def __call__(
        self,
        handler: HandlerType,
        payload: WebhookPayload,
        bot: PyrusBot,
        data: dict[str, Any],
    ) -> Any: ...
