"""Extended tests for TaskContext — _resolve, _flush, _raise_if_blocked, _read_field edge cases."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiopyrus.types.catalog import Catalog, CatalogItem
from aiopyrus.types.form import FieldType, FormField
from aiopyrus.types.task import ApprovalChoice, ApprovalEntry, TaskAction
from aiopyrus.types.user import Person
from aiopyrus.utils.context import (
    TaskContext,
    _catalog_display,
    _collect_required_missing,
    _collect_task_values,
    _find_catalog_item,
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


# ── TaskContext._warn_required_missing ────────────────────────


class TestWarnRequiredMissing:
    async def test_warns_on_empty_required_field(self, caplog):
        """approve() logs warning when required field is empty."""
        form = MagicMock()
        form.fields = [
            FormField(
                id=10,
                name="Case Number",
                type=FieldType.text,
                info={"required_step": 1},
            )
        ]
        # Task has no value for field 10 → should warn
        task_after = make_task(id=42, form_id=321, current_step=2, is_closed=True)
        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1), client)
        with caplog.at_level(logging.WARNING, logger="aiopyrus.context"):
            await ctx.approve("Go")

        assert "Case Number" in caplog.text
        assert "required fields not filled" in caplog.text

    async def test_no_warning_when_field_filled(self, caplog):
        """approve() does NOT warn when required field has a value."""
        form = MagicMock()
        form.fields = [
            FormField(
                id=10,
                name="Case Number",
                type=FieldType.text,
                info={"required_step": 1},
            )
        ]
        field = make_field(id=10, name="Case Number", type="text", value="INC-001")
        task_after = make_task(id=42, form_id=321, current_step=2, fields=[field], is_closed=True)
        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1, fields=[field]), client)
        with caplog.at_level(logging.WARNING, logger="aiopyrus.context"):
            await ctx.approve("Go")

        assert "required fields not filled" not in caplog.text

    async def test_pending_set_counts_as_filled(self, caplog):
        """Pending set() should count as filled — no warning."""
        form = MagicMock()
        form.fields = [
            FormField(
                id=10,
                name="Case Number",
                type=FieldType.text,
                info={"required_step": 1},
            )
        ]
        field = make_field(id=10, name="Case Number", type="text", value=None)
        task_after = make_task(id=42, form_id=321, current_step=2, is_closed=True)
        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1, fields=[field]), client)
        ctx.set("Case Number", "INC-001")
        with caplog.at_level(logging.WARNING, logger="aiopyrus.context"):
            await ctx.approve("Go")

        assert "required fields not filled" not in caplog.text

    async def test_no_crash_when_form_unavailable(self, caplog):
        """If get_form() fails, warn is silently skipped."""
        task_after = make_task(id=42, form_id=321, current_step=2, is_closed=True)
        client = AsyncMock()
        client.get_form = AsyncMock(side_effect=RuntimeError("network"))
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, form_id=321, current_step=1), client)
        with caplog.at_level(logging.WARNING, logger="aiopyrus.context"):
            await ctx.approve("Go")  # should not raise

    async def test_no_crash_when_no_form_id(self, caplog):
        """If task has no form_id, skip validation silently."""
        task_after = make_task(id=42, form_id=None, current_step=2, is_closed=True)
        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=task_after)

        ctx = TaskContext(make_task(id=42, form_id=None, current_step=1), client)
        with caplog.at_level(logging.WARNING, logger="aiopyrus.context"):
            await ctx.approve("Go")  # should not raise, should not call get_form

        client.get_form.assert_not_called()


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

    def test_set_is_fill(self):
        """set is a class-level alias for fill."""
        assert TaskContext.set is TaskContext.fill

    def test_field_id_is_get_id(self):
        """field_id is a class-level alias for get_id."""
        assert TaskContext.field_id is TaskContext.get_id

    def test_field_type_is_get_type(self):
        """field_type is a class-level alias for get_type."""
        assert TaskContext.field_type is TaskContext.get_type

    def test_catalog_id_is_get_catalog_id(self):
        """catalog_id is a class-level alias for get_catalog_id."""
        assert TaskContext.catalog_id is TaskContext.get_catalog_id

    def test_put_is_fill(self):
        """put is a class-level alias for fill."""
        assert TaskContext.put is TaskContext.fill

    def test_value_id_is_get_value_id(self):
        """value_id is a class-level alias for get_value_id."""
        assert TaskContext.value_id is TaskContext.get_value_id


# ── ctx.get_value_id ──────────────────────────────────────────


class TestGetValueId:
    def test_multiple_choice_single(self):
        """Returns single choice_id for multiple_choice with one selection."""
        field = make_field(
            id=10, name="Status", type="multiple_choice",
            value={"choice_ids": [3], "choice_names": ["In progress"]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_value_id("Status") == 3

    def test_multiple_choice_multi(self):
        """Returns list of choice_ids when multiple selections."""
        field = make_field(
            id=10, name="Tags", type="multiple_choice",
            value={"choice_ids": [1, 5, 7], "choice_names": ["A", "B", "C"]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_value_id("Tags") == [1, 5, 7]

    def test_catalog(self):
        """Returns item_id for catalog field."""
        field = make_field(
            id=5, name="Type", type="catalog",
            value={"item_id": 1001, "values": ["10", "Alpha"]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_value_id("Type") == 1001

    def test_person(self):
        """Returns person_id for person field."""
        field = make_field(
            id=8, name="Exec", type="person",
            value={"id": 100500, "first_name": "Ivan", "last_name": "Ivanov"},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_value_id("Exec") == 100500

    def test_form_link(self):
        """Returns task_ids for form_link field."""
        field = make_field(
            id=20, name="Linked", type="form_link",
            value={"task_ids": [111, 222]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_value_id("Linked") == [111, 222]

    def test_text_raises_type_error(self):
        """Text fields don't have an internal ID → TypeError."""
        field = make_field(id=1, name="Note", type="text", value="hello")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        with pytest.raises(TypeError, match="does not have"):
            ctx.get_value_id("Note")

    def test_none_value_raises_value_error(self):
        """Empty field → ValueError."""
        field = make_field(id=1, name="Status", type="multiple_choice", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        with pytest.raises(ValueError, match="no value"):
            ctx.get_value_id("Status")

    def test_missing_field_raises_key_error(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError, match="Missing"):
            ctx.get_value_id("Missing")

    def test_value_id_alias_works(self):
        """value_id() is an alias for get_value_id()."""
        field = make_field(
            id=5, name="Type", type="catalog",
            value={"item_id": 42, "values": ["Alpha"]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.value_id("Type") == 42


# ── ctx.dump ──────────────────────────────────────────────────


class TestDump:
    def test_dump_field(self):
        """dump('Field') returns dict with id, name, type, value."""
        field = make_field(id=10, name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        d = ctx.dump("Status")
        assert d["id"] == 10
        assert d["name"] == "Status"
        assert d["value"] == "Open"

    def test_dump_catalog_field(self):
        """dump() on catalog field returns the raw value dict."""
        field = make_field(
            id=5, name="Type", type="catalog",
            value={"item_id": 1001, "values": ["10", "Alpha", "Web"]},
        )
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        d = ctx.dump("Type")
        assert d["value"]["item_id"] == 1001
        assert d["value"]["values"] == ["10", "Alpha", "Web"]

    def test_dump_whole_task(self):
        """dump() with no args returns the entire task as dict."""
        field = make_field(id=1, name="X", type="text", value="Y")
        ctx = TaskContext(make_task(id=42, fields=[field]), AsyncMock())
        d = ctx.dump()
        assert d["id"] == 42
        assert isinstance(d["fields"], list)

    def test_dump_missing_field_raises_key_error(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError, match="Missing"):
            ctx.dump("Missing")


# ── _find_catalog_item / _catalog_display ──────────────────────


def _item(item_id: int, values: list[str], deleted: bool = False) -> CatalogItem:
    return CatalogItem(item_id=item_id, values=values, deleted=deleted or None)


class TestCatalogDisplay:
    def test_filters_numeric(self):
        assert _catalog_display(["123", "Moscow", "Russia"]) == "Moscow / Russia"

    def test_all_numeric_fallback(self):
        """When all values are numeric, returns empty (fallback to raw)."""
        assert _catalog_display(["1", "2", "3"]) == ""

    def test_single_non_numeric(self):
        assert _catalog_display(["42", "Development"]) == "Development"

    def test_empty_strings_skipped(self):
        assert _catalog_display(["", "IT", "", "Dev"]) == "IT / Dev"

    def test_negative_numbers_filtered(self):
        assert _catalog_display(["-5", "Value"]) == "Value"


class TestFindCatalogItem:
    """Tests for _find_catalog_item — 6-pass matching strategy."""

    ITEMS = [
        _item(1, ["10", "FooTracker", "App\\Web"]),
        _item(2, ["20", "BarBoard", "App\\Web"]),
        _item(3, ["30", "BazMail", "Desktop"]),
        _item(4, ["40", "QuxChat", "App\\Web", "SaaS"]),
        _item(5, ["50", "Deleted Tool", "Desktop"], deleted=True),
    ]

    def test_exact_display_text(self):
        """Pass 1: exact match on display text."""
        item = _find_catalog_item(self.ITEMS, "FooTracker / App\\Web")
        assert item is not None
        assert item.item_id == 1

    def test_exact_column_value(self):
        """Pass 2: exact match on single column."""
        item = _find_catalog_item(self.ITEMS, "BazMail")
        assert item is not None
        assert item.item_id == 3

    def test_parts_matching(self):
        """Pass 3: all ' / '-separated parts found in columns."""
        item = _find_catalog_item(self.ITEMS, "App\\Web / SaaS")
        assert item is not None
        assert item.item_id == 4  # only QuxChat has both

    def test_case_insensitive_display(self):
        """Pass 4: case-insensitive display text."""
        item = _find_catalog_item(self.ITEMS, "footracker / app\\web")
        assert item is not None
        assert item.item_id == 1

    def test_case_insensitive_column(self):
        """Pass 5: case-insensitive column value."""
        item = _find_catalog_item(self.ITEMS, "bazmail")
        assert item is not None
        assert item.item_id == 3

    def test_case_insensitive_parts(self):
        """Pass 6: case-insensitive parts matching."""
        item = _find_catalog_item(self.ITEMS, "app\\web / saas")
        assert item is not None
        assert item.item_id == 4

    def test_not_found(self):
        assert _find_catalog_item(self.ITEMS, "NonExistent") is None

    def test_deleted_items_skipped(self):
        """Deleted items must never match."""
        item = _find_catalog_item(self.ITEMS, "Deleted Tool")
        assert item is None

    def test_numeric_id_not_matched_in_display(self):
        """Passing a numeric ID should NOT match via display text."""
        item = _find_catalog_item(self.ITEMS, "10")
        # "10" is in item 1's values column — matched by pass 2 (exact column)
        assert item is not None
        assert item.item_id == 1


# ── ctx.get_id / ctx.get_type / ctx.get_catalog_id ─────────────


class TestGetId:
    def test_returns_field_id(self):
        field = make_field(id=42, name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_id("Status") == 42

    def test_missing_field_raises_key_error(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError, match="Missing"):
            ctx.get_id("Missing")

    def test_field_id_alias_works(self):
        """field_id() is an alias for get_id()."""
        field = make_field(id=42, name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.field_id("Status") == 42


class TestGetType:
    def test_returns_field_type(self):
        field = make_field(id=1, name="Status", type="multiple_choice", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_type("Status") == "multiple_choice"

    def test_catalog_type(self):
        field = make_field(id=2, name="Type", type="catalog", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.get_type("Type") == "catalog"

    def test_missing_field_raises_key_error(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError, match="Missing"):
            ctx.get_type("Missing")

    def test_field_type_alias_works(self):
        """field_type() is an alias for get_type()."""
        field = make_field(id=1, name="Status", type="text", value=None)
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        assert ctx.field_type("Status") == "text"


class TestGetCatalogId:
    async def test_returns_catalog_id(self):
        """get_catalog_id() fetches form definition and returns catalog_id from info."""
        field = make_field(id=5, name="Request Type", type="catalog", value={"item_id": 1})
        form_field = FormField(
            id=5,
            name="Request Type",
            type=FieldType.catalog,
            info={"catalog_id": 1910},
        )
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        result = await ctx.get_catalog_id("Request Type")
        assert result == 1910
        client.get_form.assert_called_once_with(321)

    async def test_catalog_id_alias_works(self):
        """catalog_id() is an alias for get_catalog_id()."""
        field = make_field(id=5, name="Request Type", type="catalog", value={"item_id": 1})
        form_field = FormField(
            id=5,
            name="Request Type",
            type=FieldType.catalog,
            info={"catalog_id": 1910},
        )
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        result = await ctx.catalog_id("Request Type")
        assert result == 1910

    async def test_missing_field_raises_key_error(self):
        ctx = TaskContext(make_task(fields=[]), AsyncMock())
        with pytest.raises(KeyError):
            await ctx.get_catalog_id("Missing")

    async def test_non_catalog_field_raises_type_error(self):
        field = make_field(id=5, name="Status", type="text", value="Open")
        ctx = TaskContext(make_task(fields=[field]), AsyncMock())
        with pytest.raises(TypeError, match="not 'catalog'"):
            await ctx.get_catalog_id("Status")

    async def test_no_form_id_raises_value_error(self):
        field = make_field(id=5, name="Cat", type="catalog", value={"item_id": 1})
        ctx = TaskContext(make_task(form_id=None, fields=[field]), AsyncMock())
        with pytest.raises(ValueError, match="no form_id"):
            await ctx.get_catalog_id("Cat")

    async def test_no_catalog_id_in_form_raises_value_error(self):
        field = make_field(id=5, name="Cat", type="catalog", value={"item_id": 1})
        form_field = FormField(id=5, name="Cat", type=FieldType.catalog, info={})
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)

        ctx = TaskContext(make_task(form_id=321, fields=[field]), client)
        with pytest.raises(ValueError, match="catalog_id not found"):
            await ctx.get_catalog_id("Cat")


# ── ctx.set() catalog string resolution ────────────────────────


class TestResolveCatalog:
    async def test_resolve_catalog_by_string(self):
        """String value for catalog triggers form + catalog lookup."""
        field = make_field(id=5, name="Type", type="catalog", value={"item_id": 1})
        returned_task = make_task(id=42, form_id=321, fields=[field])

        form_field = FormField(
            id=5, name="Type", type=FieldType.catalog, info={"catalog_id": 99}
        )
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        catalog = Catalog(
            catalog_id=99,
            name="Programs",
            items=[
                CatalogItem(item_id=1001, values=["10", "Alpha", "Web"]),
                CatalogItem(item_id=1002, values=["20", "Beta", "Desktop"]),
            ],
        )

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)
        client.get_form = AsyncMock(return_value=form)
        client.get_catalog = AsyncMock(return_value=catalog)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Type", "Beta")
        await ctx.answer()

        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 5, "value": {"item_id": 1002}}]

    async def test_resolve_catalog_by_display_text(self):
        """Multi-column display text ('Web / Alpha') resolves correctly."""
        field = make_field(id=5, name="Type", type="catalog", value={"item_id": 1})
        returned_task = make_task(id=42, form_id=321, fields=[field])

        form_field = FormField(
            id=5, name="Type", type=FieldType.catalog, info={"catalog_id": 99}
        )
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        catalog = Catalog(
            catalog_id=99,
            name="Programs",
            items=[
                CatalogItem(item_id=1001, values=["10", "Alpha", "Web"]),
                CatalogItem(item_id=1002, values=["20", "Beta", "Desktop"]),
            ],
        )

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)
        client.get_form = AsyncMock(return_value=form)
        client.get_catalog = AsyncMock(return_value=catalog)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Type", "Alpha / Web")
        await ctx.answer()

        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 5, "value": {"item_id": 1001}}]

    async def test_resolve_catalog_by_int(self):
        """Int value for catalog is passed through as item_id (no lookup)."""
        field = make_field(id=5, name="Type", type="catalog", value={"item_id": 1})
        returned_task = make_task(id=42, form_id=321, fields=[field])

        client = AsyncMock()
        client.comment_task = AsyncMock(return_value=returned_task)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Type", 1002)
        await ctx.answer()

        updates = client.comment_task.call_args[1]["field_updates"]
        assert updates == [{"id": 5, "value": {"item_id": 1002}}]
        # No form/catalog API calls needed
        client.get_form.assert_not_called()

    async def test_resolve_catalog_not_found_error(self):
        """Unknown catalog value → ValueError with hints."""
        field = make_field(id=5, name="Type", type="catalog", value={"item_id": 1})

        form_field = FormField(
            id=5, name="Type", type=FieldType.catalog, info={"catalog_id": 99}
        )
        form = MagicMock()
        form.get_field = MagicMock(return_value=form_field)

        catalog = Catalog(
            catalog_id=99,
            name="Programs",
            items=[CatalogItem(item_id=1001, values=["10", "Alpha", "Web"])],
        )

        client = AsyncMock()
        client.get_form = AsyncMock(return_value=form)
        client.get_catalog = AsyncMock(return_value=catalog)

        ctx = TaskContext(make_task(id=42, form_id=321, fields=[field]), client)
        ctx.set("Type", "NonExistent")
        with pytest.raises(ValueError, match="not found"):
            await ctx.answer()

    async def test_resolve_catalog_no_form_id(self):
        """Catalog string on a free task (no form_id) → ValueError."""
        field = make_field(id=5, name="Type", type="catalog", value={"item_id": 1})
        client = AsyncMock()

        ctx = TaskContext(make_task(id=42, form_id=None, fields=[field]), client)
        ctx.set("Type", "Alpha")
        with pytest.raises(ValueError, match="no form_id"):
            await ctx.answer()
