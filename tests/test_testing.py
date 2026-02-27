"""Tests for aiopyrus.testing — mock client factory."""

from __future__ import annotations

from aiopyrus.testing import create_mock_client
from aiopyrus.types.task import Task


class TestCreateMockClient:
    async def test_basic_mock(self):
        mock = create_mock_client()
        assert mock is not None

    async def test_return_values(self):
        task = Task(id=12345678, text="Test")
        mock = create_mock_client(get_task=task, get_members=[])

        result = await mock.get_task(12345678)
        assert result.id == 12345678
        assert result.text == "Test"

        members = await mock.get_members()
        assert members == []

    async def test_assert_calls(self):
        mock = create_mock_client(get_task=Task(id=1))
        await mock.get_task(1)
        mock.get_task.assert_awaited_once_with(1)

    async def test_context_manager(self):
        mock = create_mock_client()
        async with mock as client:
            assert client is mock

    async def test_unconfigured_methods_return_async_mock(self):
        mock = create_mock_client()
        result = await mock.get_inbox()
        # Should not raise — returns an AsyncMock
        assert result is not None

    async def test_multiple_methods(self):
        mock = create_mock_client(
            get_task=Task(id=1, text="A"),
            get_inbox=[Task(id=2), Task(id=3)],
            get_members=[],
        )
        task = await mock.get_task(1)
        assert task.id == 1

        inbox = await mock.get_inbox()
        assert len(inbox) == 2

        members = await mock.get_members()
        assert members == []
