"""SyncClient — synchronous wrapper around :class:`UserClient`.

Синхронная обёртка для скриптов, Jupyter-ноутбуков и простых интеграций,
где ``async/await`` не нужен.

Quick start::

    from aiopyrus import SyncClient

    with SyncClient(login="user@example.com", security_key="KEY") as client:
        task = client.get_task(12345678)
        print(task.text)

Every public async method of :class:`UserClient` is available as a regular
(blocking) call.  Non-async attributes and properties are proxied as-is.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any

from aiopyrus.user.client import UserClient


class SyncClient:
    """Synchronous Pyrus API client (wraps :class:`UserClient`).

    Синхронный клиент Pyrus API — обёртка вокруг :class:`UserClient`.
    Принимает те же параметры::

        client = SyncClient(
            login="user@example.com",
            security_key="KEY",
            base_url="https://pyrus.mycompany.com",  # for on-premise
            ssl_verify=False,
        )
    """

    def __init__(self, **kwargs: Any) -> None:
        self._loop = asyncio.new_event_loop()
        self._async = UserClient(**kwargs)

    # -- helpers -----------------------------------------------------------

    def _run(self, coro: Any) -> Any:
        """Run a coroutine on the dedicated event loop."""
        return self._loop.run_until_complete(coro)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP session and event loop."""
        self._run(self._async.close())
        self._loop.close()

    def __enter__(self) -> SyncClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- proxy everything else to UserClient -------------------------------

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._async, name)
        if asyncio.iscoroutinefunction(attr):

            @functools.wraps(attr)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._run(attr(*args, **kwargs))

            return wrapper
        return attr
