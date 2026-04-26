from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiopyrus.bot.bot import PyrusBot
    from aiopyrus.types.webhook import WebhookPayload


class Filter(ABC):
    """Base class for all aiopyrus filters.

    A filter receives the webhook payload and returns True/False (or a dict
    of extra kwargs to inject into the handler).
    """

    @abstractmethod
    async def __call__(self, payload: WebhookPayload) -> bool | dict: ...

    async def resolve(self, bot: PyrusBot) -> None:
        """Optional one-shot async setup before the first event.

        Override in filters that need to resolve names/IDs via the API
        (e.g., :class:`FormFilter` resolves form names to IDs).  Default is
        a no-op.  Composite filters (And/Or/Not) propagate to children.
        """
        return None

    def __and__(self, other: Filter) -> AndFilter:
        return AndFilter(self, other)

    def __or__(self, other: Filter) -> OrFilter:
        return OrFilter(self, other)

    def __invert__(self) -> NotFilter:
        return NotFilter(self)


class AndFilter(Filter):
    def __init__(self, *filters: Filter) -> None:
        self._filters = filters

    async def __call__(self, payload: WebhookPayload) -> bool | dict:
        result: dict = {}
        for f in self._filters:
            r = await f(payload)
            if not r:
                return False
            if isinstance(r, dict):
                result.update(r)
        return result or True

    async def resolve(self, bot: PyrusBot) -> None:
        for f in self._filters:
            await f.resolve(bot)


class OrFilter(Filter):
    def __init__(self, *filters: Filter) -> None:
        self._filters = filters

    async def __call__(self, payload: WebhookPayload) -> bool | dict:
        for f in self._filters:
            r = await f(payload)
            if r:
                return r
        return False

    async def resolve(self, bot: PyrusBot) -> None:
        for f in self._filters:
            await f.resolve(bot)


class NotFilter(Filter):
    def __init__(self, inner: Filter) -> None:
        self._inner = inner

    async def __call__(self, payload: WebhookPayload) -> bool:
        result = await self._inner(payload)
        return not result

    async def resolve(self, bot: PyrusBot) -> None:
        await self._inner.resolve(bot)
