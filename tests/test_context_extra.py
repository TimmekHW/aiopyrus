"""Extended tests for TaskContext — _resolve, _flush, _raise_if_blocked, _read_field edge cases."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiopyrus.types.form import FieldType, FormField
from aiopyrus.types.task import ApprovalChoice, ApprovalEntry, TaskAction
from aiopyrus.types.user import Person
from aiopyrus.utils.context import (
    TaskContext,
    _collect_required_missing,
    _collect_task_values,
    _read_field,
)

from .conftest import make_field, make_person, make_task

# ── _collect_task_values ─────────────────────────────────────


class TestCollectTaskValues:
    def test_simple_fields(self):
        f1 = make_field(id=1, type="text", value="hello")
        f2 = make_field(id=2, type="number", value=42)
        out: dict[int, Any] = {}
        _collect_task_values([f1, f2], out)
        assert out == {1: "hello", 2: 42}

    def test_none_values_skipped(self):
        f1 = make_field(id=1, type="text", value=None)
        f2 = make_field(id=2, type="text", value="val")
        out: dict[int, Any] = {}
        _collect_task_values([f1, f2], out)
        assert out == {2: "val"}

    def test_nested_title_fields(self):
        inner = make_field(id=10, type="text", value="nested_val")
        title = FormField(
            id=100,
            name="Section",
            type=FieldType.title,
            value={"checkmark": None, "fields": [inner]},
        )
        out: dict[int, Any] = {}
        _collect_task_values([title], out)
        # title itself has a dict value → collected, plus inner
        assert 100 in out
        assert 10 in out
        assert out[10] == "nested_val"

    def test_empty_fields(self):
        out: dict[int, Any] = {}
        _collect_task_values([], out)
        assert out == {}


# ── _collect_required_missing ────────────────────────────────


class TestCollectRequiredMissing:
    def test_required_field_present(self):
        """If a required field has a value, it's NOT reported missing."""
        field_def = FormField(
            id=10,
            name="Status",
            type=FieldType.text,
            info={"required_step": 2},
        )
        task_values = {10: "Open"}
        result: list[str] = []
        _collect_required_missing([field_def], task_values, step=2, result=result)
        assert result == []

    def test_required_field_missing(self):
        """If a required field has no value, it IS reported."""
        field_def = FormField(
            id=10,
            name="Status",
            type=FieldType.text,
            info={"required_step": 2},
        )
        task_values: dict[int, Any] = {}
        result: list[str] = []
        _collect_required_missing([field_def], task_values, step=2, result=result)
        assert "Status" in result

    def test_different_step_not_reported(self):
        field_def = FormField(
            id=10,
            name="Status",
            type=FieldType.text,
            info={"required_step": 3},
        )
        task_values: dict[int, Any] = {}
        result: list[str] = []
        _collect_required_missing([field_def], task_values, step=2, result=result)
        assert result == []

    def test_no_info(self):
        field_def = FormField(id=10, name="Status", type=FieldType.text)
        result: list[str] = []
        _collect_required_missing([field_def], {}, step=2, result=result)
        assert result == []

    def test_nested_required_in_title(self):
        """Required field inside title's info['fields'] should be found."""
        field_def = FormField(
            id=100,
            name="Section",
            type=FieldType.title,
            info={
                "fields": [
                    {"id": 10, "name": "Inner", "type": "text", "info": {"required_step": 2}}
                ]
            },
        )
        result: list[str] = []
        _collect_required_missing([field_def], {}, step=2, result=result)
        assert "Inner" in result

    def test_missing_field_no_name_uses_id(self):
        field_def = FormField(
            id=10,
            name=None,
            type=FieldType.text,
            info={"required_step": 2},
        )
        result: list[str] = []
        _collect_required_missing([field_def], {}, step=2, result=result)
        assert "id=10" in result[0]


# ── _read_field edge cases ───────────────────────────────────


class TestReadFieldEdgeCases:
    def test_catalog_all_numeric(self):
        """When all catalog values are numeric, return them anyway."""
        f = make_field(
            type="catalog",
            value={"item_id": 1, "values": ["123", "456"]},
        )
        assert _read_field(f) == "123 / 456"

    def test_catalog_empty_strings(self):
        """Catalog with only empty strings → None."""
        f = make_field(
            type="catalog",
            value={"item_id": 1, "values": ["", ""]},
        )
        assert _read_field(f) is None

    def test_person_returns_none_on_bad_value(self):
        f = make_field(type="person", value="not a dict")
        assert _read_field(f) is None

    def test_no_type(self):
        """Field with type=None → return value as-is."""
        f = FormField(id=1, name="X", type=None, value="raw_value")
        assert _read_field(f) == "raw_value"

    def test_contains_none_in_text(self):
        f = make_field(type="text", value=None)
        assert _read_field(f) is None


# ── TaskContext.__repr__ ─────────────────────────────────────


class TestContextRepr:
    def test_repr(self):
        ctx = TaskContext(make_task(id=42, current_step=3), AsyncMock())
        r = repr(ctx)
        assert "42" in r
        assert "step=3" in r
        assert "pending=0" in r

    def test_repr_with_pending(self):
        field = make_field(name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(id=42, fields=[field]), AsyncMock())
        ctx.set("Status", "Closed")
        r = repr(ctx)
        assert "pending=1" in r


# ── TaskContext._flush / _resolve ─────────────────────────────


class TestContextResolve:
    async def test_resolve_text(self):
        """Text field → FieldUpdate.text."""
        field = make_field(id=10, name="Name", type="text", value="old")
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Name", "new_value")
        await ctx.answer()

        call_kwargs = client.comment_task.call_args[1]
        updates = call_kwargs["field_updates"]
        assert updates == [{"id": 10, "value": "new_value"}]

    async def test_resolve_clear(self):
        """Setting None → FieldUpdate.clear."""
        field = make_field(id=10, name="Name", type="text", value="old")
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Name", None)
        await ctx.answer()

        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 10, "value": None}]

    async def test_resolve_checkmark(self):
        field = make_field(id=10, name="Done", type="checkmark", value="unchecked")
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Done", True)
        await ctx.answer()

        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 10, "value": "checked"}]

    async def test_resolve_multiple_choice_by_string(self):
        """String value for multiple_choice triggers form API lookup."""
        field = make_field(
            id=10,
            name="Status",
            type="multiple_choice",
            value={"choice_ids": [1], "choice_names": ["Open"]},
        )
        returned_task = make_task(id=42, form_id=321, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)
        client.get_form_choices = AsyncMock(return_value={"Open": 1, "Closed": 2})

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Status", "Closed")
        await ctx.answer()

        client.get_form_choices.assert_called_once_with(321, 10)
        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 10, "value": {"choice_ids": [2]}}]

    async def test_resolve_multiple_choice_str_not_found(self):
        """Unknown choice name → ValueError."""
        field = make_field(
            id=10,
            name="Status",
            type="multiple_choice",
            value={"choice_ids": [1]},
        )
        client = AsyncMock()
        client.get_form_choices = AsyncMock(return_value={"Open": 1, "Closed": 2})

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Status", "Invalid")
        with pytest.raises(ValueError, match="not found"):
            await ctx.answer()

    async def test_resolve_multiple_choice_no_form_id(self):
        """String choice on a free task (no form_id) → ValueError."""
        field = make_field(
            id=10,
            name="Status",
            type="multiple_choice",
            value={"choice_ids": [1]},
        )
        client = AsyncMock()

        ctx = TaskContext(make_task(id=42, form_id=None, fields=[field]), client)
        ctx.set("Status", "Open")
        with pytest.raises(ValueError, match="no form_id"):
            await ctx.answer()

    async def test_resolve_person_by_string(self):
        """String value for person triggers member lookup."""
        field = make_field(id=10, name="Exec", type="person", value={"id": 1})
        returned_task = make_task(id=42, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)
        client.find_member = AsyncMock(return_value=make_person(id=100500))

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Exec", "Ivan Ivanov")
        await ctx.answer()

        client.find_member.assert_called_once_with("Ivan Ivanov")
        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 10, "value": {"id": 100500}}]

    async def test_resolve_person_str_not_found(self):
        """Unknown person name → ValueError."""
        field = make_field(id=10, name="Exec", type="person", value={"id": 1})
        client = AsyncMock()
        client.find_member = AsyncMock(return_value=None)

        ctx = TaskContext(make_task(id=42, fields=[field]), client)
        ctx.set("Exec", "Nobody")
        with pytest.raises(ValueError, match="not found"):
            await ctx.answer()

    async def test_flush_empty_returns_empty(self):
        """No pending changes → empty list, no API calls."""
        returned_task = make_task(id=42)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42), client)
        await ctx.answer("Just a comment")

        call_kwargs = client.comment_task.call_args[1]
        assert call_kwargs["field_updates"] is None


# ── TaskContext._raise_if_blocked ─────────────────────────────


class TestRaiseIfBlocked:
    async def test_approve_step_not_advanced_no_rights(self):
        """Step didn't advance, current user NOT in approvers → ValueError."""
        approver = ApprovalEntry(
            person=Person(id=999, first_name="Other", last_name="Guy"),
            approval_choice=ApprovalChoice.waiting,
        )
        # current_step=1 → step_idx=0 → approvals[0] has 'approver' (id=999)
        task_after = make_task(
            id=42,
            current_step=1,
            approvals=[[approver]],
        )
        # get_profile returns a different person (id=100500 ≠ 999)
        profile = MagicMock()
        profile.person_id = 100500

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)
        client.get_profile = AsyncMock(return_value=profile)

        ctx = TaskContext(make_task(id=42, current_step=1), client)
        with pytest.raises(ValueError, match="No approval rights"):
            await ctx.approve("Let's go")

    async def test_approve_step_not_advanced_required_fields(self):
        """Step didn't advance, user IS approver but required fields missing → ValueError."""
        approver = ApprovalEntry(
            person=Person(id=100500, first_name="Me", last_name="Me"),
            approval_choice=ApprovalChoice.waiting,
        )
        task_after = make_task(
            id=42,
            form_id=321,
            current_step=1,
            approvals=[[approver]],
        )
        profile = MagicMock()
        profile.person_id = 100500

        form = MagicMock()
        form.fields = [
            FormField(
                id=10,
                name="Required Field",
                type=FieldType.text,
                info={"required_step": 1},
            )
        ]

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)
        client.get_profile = AsyncMock(return_value=profile)
        client.get_form = AsyncMock(return_value=form)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1), client)
        with pytest.raises(ValueError, match="Required fields"):
            await ctx.approve("Approved")

    async def test_approve_step_not_advanced_unknown_reason(self):
        """Step didn't advance, user IS approver, no required fields → generic error."""
        approver = ApprovalEntry(
            person=Person(id=100500, first_name="Me", last_name="Me"),
            approval_choice=ApprovalChoice.waiting,
        )
        task_after = make_task(
            id=42,
            form_id=321,
            current_step=1,
            approvals=[[approver]],
        )
        profile = MagicMock()
        profile.person_id = 100500

        form = MagicMock()
        form.fields = []  # no required fields

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)
        client.get_profile = AsyncMock(return_value=profile)
        client.get_form = AsyncMock(return_value=form)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1), client)
        with pytest.raises(ValueError, match="Possible reasons"):
            await ctx.approve("Approved")

    async def test_approve_step_advanced_no_error(self):
        """If step advances, no error is raised."""
        task_after = make_task(id=42, current_step=3)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, current_step=2), client)
        result = await ctx.approve("OK")
        assert result.current_step == 3

    async def test_approve_task_closed_no_error(self):
        """If task becomes closed, no error is raised."""
        task_after = make_task(id=42, current_step=2, is_closed=True)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, current_step=2), client)
        result = await ctx.approve("Closing")
        assert result.closed is True

    async def test_finish_step_not_advanced(self):
        """finish() uses _raise_if_blocked too."""
        approver = ApprovalEntry(
            person=Person(id=999, first_name="Other", last_name="Guy"),
            approval_choice=ApprovalChoice.waiting,
        )
        task_after = make_task(id=42, current_step=1, approvals=[[approver]])
        profile = MagicMock()
        profile.person_id = 100500

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)
        client.get_profile = AsyncMock(return_value=profile)

        ctx = TaskContext(make_task(id=42, current_step=1), client)
        with pytest.raises(ValueError, match="No approval rights"):
            await ctx.finish("Done")

    async def test_raise_if_blocked_profile_exception(self):
        """If get_profile raises, skip the approval-rights check gracefully."""
        task_after = make_task(id=42, current_step=1, form_id=None, approvals=[[]])

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)
        client.get_profile = AsyncMock(side_effect=RuntimeError("network"))

        ctx = TaskContext(make_task(id=42, current_step=1), client)
        # Should still raise, but with "Possible reasons" (unknown), not crash
        with pytest.raises(ValueError, match="Possible reasons"):
            await ctx.approve("test")


# ── TaskContext.reject with pending updates ───────────────────


class TestRejectWithUpdates:
    async def test_reject_flushes_updates_separately(self):
        """Reject flushes field_updates in a separate call before rejection."""
        field = make_field(id=10, name="Status", type="text", value="Open")
        task_mid = make_task(id=42, current_step=2, fields=[field])
        task_after = make_task(id=42, current_step=2, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(side_effect=[task_mid, task_after])

        ctx = TaskContext(make_task(id=42, current_step=2, fields=[field]), client)
        ctx.set("Status", "Rejected")
        await ctx.reject("No good")

        assert client.comment_task.call_count == 2
        first = client.comment_task.call_args_list[0][1]
        assert "field_updates" in first
        second = client.comment_task.call_args_list[1][1]
        assert second["approval_choice"] == ApprovalChoice.rejected


# ── TaskContext.finish with pending updates ───────────────────


class TestFinishWithUpdates:
    async def test_finish_flushes_updates_separately(self):
        field = make_field(id=10, name="Note", type="text", value="x")
        task_mid = make_task(id=42, current_step=2, fields=[field])
        task_after = make_task(id=42, is_closed=True, fields=[field])
        client = AsyncMock()
        client.comment_task = AsyncMock(side_effect=[task_mid, task_after])

        ctx = TaskContext(make_task(id=42, current_step=2, fields=[field]), client)
        ctx.set("Note", "Final")
        await ctx.finish("Done")

        assert client.comment_task.call_count == 2
        second = client.comment_task.call_args_list[1][1]
        assert second["action"] == TaskAction.finished


# ── TaskContext.find edge cases ───────────────────────────────


class TestFindEdgeCases:
    def test_find_wildcard_none_value_returns_default(self):
        """Wildcard match found but value is None → return default."""
        field = make_field(id=1, name="Description", type="text", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.find("%Description%", "N/A") == "N/A"

    def test_find_substring_none_value_returns_default(self):
        """Substring match found but value is None → return default."""
        field = make_field(id=1, name="Description", type="text", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.find("Description", "N/A") == "N/A"


# ── TaskContext aliases ───────────────────────────────────────


class TestContextAliases:
    def test_comment_is_answer(self):
        """comment is a class-level alias for answer."""
        assert TaskContext.comment is TaskContext.answer

    def test_send_is_answer(self):
        """send is a class-level alias for answer."""
        assert TaskContext.send is TaskContext.answer
