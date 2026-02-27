"""Утилиты для тестирования — фабрика мок-клиента.

Test utilities for aiopyrus — mock client factory.

Example::

    from aiopyrus.testing import create_mock_client
    from aiopyrus.types import Task

    client = create_mock_client(
        get_task=Task(id=12345678, text="Test"),
        get_members=[],
    )

    task = await client.get_task(12345678)
    assert task.id == 12345678
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from aiopyrus.user.client import UserClient


def create_mock_client(**method_returns: Any) -> AsyncMock:
    """Создать AsyncMock с spec=UserClient и заданными возвратными значениями.

    Create an AsyncMock with spec=UserClient and pre-configured return values.

    Каждый keyword argument — имя метода и его return_value.
    Методы без return_value возвращают стандартный AsyncMock.

    Example::

        from aiopyrus.testing import create_mock_client

        mock = create_mock_client(
            get_task=Task(id=1, text="Test"),
            get_inbox=[],
        )
        task = await mock.get_task(1)
        assert task.id == 1
        mock.get_task.assert_awaited_once_with(1)
    """
    mock = AsyncMock(spec=UserClient)

    for method_name, return_value in method_returns.items():
        getattr(mock, method_name).return_value = return_value

    # Context manager support
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    return mock
