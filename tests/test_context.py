"""Tests for TaskContext — field reading, lazy writing, sending."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from aiopyrus.types.task import ApprovalChoice, TaskAction
from aiopyrus.utils.context import TaskContext, _read_field

from .conftest import make_field, make_person, make_task

# ── _read_field (human-readable value extractor) ─────────────


class TestReadField:
    def test_text(self):
        f = make_field(type="text", value="hello")
        assert _read_field(f) == "hello"

    def test_number(self):
        f = make_field(type="number", value=42)
        assert _read_field(f) == 42

    def test_none_value(self):
        f = make_field(type="text", value=None)
        assert _read_field(f) is None

    def test_checkmark_checked(self):
        f = make_field(type="checkmark", value="checked")
        assert _read_field(f) is True

    def test_checkmark_unchecked(self):
        f = make_field(type="checkmark", value="unchecked")
        assert _read_field(f) is False

    def test_flag(self):
        f = make_field(type="flag", value="checked")
        assert _read_field(f) is True

    def test_multiple_choice_single(self):
        f = make_field(
            type="multiple_choice",
            value={"choice_ids": [1], "choice_names": ["Open"]},
        )
        assert _read_field(f) == "Open"

    def test_multiple_choice_multi(self):
        f = make_field(
            type="multiple_choice",
            value={"choice_ids": [1, 2], "choice_names": ["Open", "In Progress"]},
        )
        assert _read_field(f) == ["Open", "In Progress"]

    def test_multiple_choice_no_names(self):
        """If choice_names missing, return raw value."""
        f = make_field(type="multiple_choice", value={"choice_ids": [1]})
        assert _read_field(f) == {"choice_ids": [1]}

    def test_person(self):
        f = make_field(
            type="person",
            value={"id": 100500, "first_name": "Ivan", "last_name": "Ivanov"},
        )
        assert _read_field(f) == "Ivan Ivanov"

    def test_author(self):
        f = make_field(
            type="author",
            value={"id": 100500, "first_name": "Ivan", "last_name": "Ivanov"},
        )
        assert _read_field(f) == "Ivan Ivanov"

    def test_catalog(self):
        f = make_field(
            type="catalog",
            value={"item_id": 1, "headers": ["ID", "City"], "values": ["1", "Moscow"]},
        )
        # Numeric-only values are filtered
        assert _read_field(f) == "Moscow"

    def test_catalog_multi_values(self):
        f = make_field(
            type="catalog",
            value={"item_id": 1, "values": ["IT", "Development"]},
        )
        assert _read_field(f) == "IT / Development"

    def test_catalog_empty(self):
        f = make_field(type="catalog", value={"item_id": None, "values": []})
        assert _read_field(f) is None

    def test_title_checkmark(self):
        f = make_field(type="title", value={"checkmark": "checked"})
        assert _read_field(f) is True

    def test_title_no_checkmark(self):
        f = make_field(type="title", value={"fields": []})
        assert _read_field(f) is None

    def test_file(self):
        f = make_field(
            type="file",
            value=[{"id": 1, "name": "doc.pdf", "size": 1024}],
        )
        result = _read_field(f)
        assert len(result) == 1
        assert result[0].name == "doc.pdf"


# ── TaskContext reading ──────────────────────────────────────


class TestContextRead:
    def _ctx(self, fields=None):
        task = make_task(fields=fields or [])
        client = AsyncMock()
        return TaskContext(task, client)

    def test_getitem(self):
        ctx = self._ctx([make_field(name="Status", type="text", value="Open")])
        assert ctx["Status"] == "Open"

    def test_getitem_missing(self):
        ctx = self._ctx([])
        with pytest.raises(KeyError):
            ctx["Missing"]

    def test_get_with_default(self):
        ctx = self._ctx([])
        assert ctx.get("Missing", "N/A") == "N/A"

    def test_get_none_value_uses_default(self):
        ctx = self._ctx([make_field(name="Status", type="text", value=None)])
        assert ctx.get("Status", "default") == "default"

    def test_raw(self):
        field = make_field(name="Status", type="text", value="Open")
        ctx = self._ctx([field])
        result = ctx.raw("Status")
        assert result is not None
        assert result.id == field.id

    def test_find_with_wildcard(self):
        ctx = self._ctx(
            [
                make_field(id=1, name="Request Description", type="text", value="Something"),
                make_field(id=2, name="Other Field", type="text", value="Other"),
            ]
        )
        assert ctx.find("%description%") == "Something"

    def test_find_substring(self):
        ctx = self._ctx(
            [
                make_field(id=1, name="Request Description", type="text", value="Something"),
            ]
        )
        assert ctx.find("Description") == "Something"

    def test_find_not_found(self):
        ctx = self._ctx([])
        assert ctx.find("Missing", "N/A") == "N/A"


# ── TaskContext properties ───────────────────────────────────


class TestContextProperties:
    def test_id(self):
        ctx = TaskContext(make_task(id=42), AsyncMock())
        assert ctx.id == 42

    def test_step(self):
        ctx = TaskContext(make_task(current_step=3), AsyncMock())
        assert ctx.step == 3

    def test_form_id(self):
        ctx = TaskContext(make_task(form_id=321), AsyncMock())
        assert ctx.form_id == 321

    def test_closed(self):
        ctx = TaskContext(make_task(is_closed=True), AsyncMock())
        assert ctx.closed is True


# ── TaskContext writing & sending ────────────────────────────


class TestContextWrite:
    def test_set_returns_self(self):
        field = make_field(name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        result = ctx.set("Status", "Closed")
        assert result is ctx

    def test_set_chaining(self):
        f1 = make_field(id=1, name="A", type="text", value="x")
        f2 = make_field(id=2, name="B", type="text", value="y")
        ctx = TaskContext(make_task(fields=[f1, f2]), AsyncMock())
        ctx.set("A", "1").set("B", "2")
        assert ctx.pending_count() == 2

    def test_set_missing_field(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError):
            ctx.set("Missing", "value")

    def test_discard(self):
        field = make_field(name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        ctx.set("Status", "Closed")
        assert ctx.pending_count() == 1
        ctx.discard()
        assert ctx.pending_count() == 0

    async def test_answer_calls_comment_task(self):
        field = make_field(id=10, name="Status", type="text", value="Open")
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        result = await ctx.answer("Done")

        client.comment_task.assert_called_once()
        call_kwargs = client.comment_task.call_args
        assert call_kwargs[1]["text"] == "Done"
        assert result.id == 42

    async def test_answer_flushes_pending(self):
        field = make_field(id=10, name="Status", type="text", value="Open")
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Status", "Closed")
        await ctx.answer()

        assert ctx.pending_count() == 0
        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["field_updates"] is not None

    async def test_reassign_by_int(self):
        returned_task = make_task(id=42)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42), client)
        await ctx.reassign(100500, "Take it")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["reassign_to"] == 100500
        assert call_kwargs["text"] == "Take it"

    async def test_reassign_by_name(self):
        returned_task = make_task(id=42)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)
        client.find_member = AsyncMock(return_value=make_person(id=100500))

        ctx = TaskContext(make_task(id=42), client)
        await ctx.reassign("Ivan Ivanov")

        client.find_member.assert_called_once_with("Ivan Ivanov")
        assert client.comment_task.call_args[1]["reassign_to"] == 100500

    async def test_reassign_person_not_found(self):
        client = AsyncMock()
        client.find_member = AsyncMock(return_value=None)

        ctx = TaskContext(make_task(id=42), client)
        with pytest.raises(ValueError, match="not found"):
            await ctx.reassign("Nobody")

    async def test_log_time(self):
        returned_task = make_task(id=42)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42), client)
        await ctx.log_time(90, "Analysis")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["spent_minutes"] == 90

    async def test_reply(self):
        returned_task = make_task(id=42)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42), client)
        await ctx.reply(555, "Clarification")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["reply_to_comment_id"] == 555

    async def test_approve_sends_separate_calls_with_updates(self):
        """Approve flushes field_updates in a separate call before approval."""
        field = make_field(id=10, name="Status", type="text", value="Open")
        # First call returns task still at step=2, second call returns step=3 (advanced).
        task_mid = make_task(id=42, current_step=2, fields=[field])
        task_after = make_task(id=42, current_step=3, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(side_effect=[task_mid, task_after])

        ctx = TaskContext(make_task(id=42, current_step=2, fields=[field]), client)
        ctx.set("Status", "Done")
        await ctx.approve("Approved")

        assert client.comment_task.call_count == 2
        # First call: field_updates only
        first_call = client.comment_task.call_args_list[0][1]
        assert "field_updates" in first_call
        # Second call: approval_choice
        second_call = client.comment_task.call_args_list[1][1]
        assert second_call["approval_choice"] == ApprovalChoice.approved

    async def test_reject(self):
        task_after = make_task(id=42, current_step=2)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, current_step=2), client)
        await ctx.reject("Rejected")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["approval_choice"] == ApprovalChoice.rejected

    async def test_finish(self):
        task_after = make_task(id=42, is_closed=True)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, current_step=2), client)
        await ctx.finish("Done")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["action"] == TaskAction.finished
