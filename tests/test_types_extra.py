"""Extended type tests — Task.find_fields, Catalog.find_item, Form.get_field, nested fields."""

from __future__ import annotations

from aiopyrus.types.catalog import Catalog, CatalogItem
from aiopyrus.types.form import (
    FieldType,
    Form,
    FormField,
)
from aiopyrus.types.task import (
    Announcement,
    ApprovalChoice,
    ApprovalEntry,
    Comment,
    Task,
    TaskAction,
)
from aiopyrus.types.user import Person
from aiopyrus.types.webhook import BotResponse

# ── Task.find_fields ────────────────────────────────────────


class TestFindFields:
    def _task_with_fields(self, fields: list[FormField]) -> Task:
        return Task(id=1, fields=fields)

    def test_find_by_name(self):
        f1 = FormField(id=1, name="Status", type=FieldType.text, value="Open")
        f2 = FormField(id=2, name="Priority", type=FieldType.text, value="High")
        task = self._task_with_fields([f1, f2])
        result = task.find_fields(name="stat")
        assert len(result) == 1
        assert result[0].id == 1

    def test_find_by_name_case_insensitive(self):
        f = FormField(id=1, name="Description", type=FieldType.text, value="test")
        task = self._task_with_fields([f])
        result = task.find_fields(name="DESCRIPTION")
        assert len(result) == 1

    def test_find_by_value_contains(self):
        f1 = FormField(id=1, name="A", type=FieldType.text, value="Hello World")
        f2 = FormField(id=2, name="B", type=FieldType.text, value="Goodbye")
        task = self._task_with_fields([f1, f2])
        result = task.find_fields(value_contains="hello")
        assert len(result) == 1
        assert result[0].id == 1

    def test_find_by_field_type(self):
        f1 = FormField(id=1, name="A", type=FieldType.text, value="x")
        f2 = FormField(id=2, name="B", type=FieldType.number, value=42)
        task = self._task_with_fields([f1, f2])
        result = task.find_fields(field_type="number")
        assert len(result) == 1
        assert result[0].id == 2

    def test_find_only_filled(self):
        f1 = FormField(id=1, name="A", type=FieldType.text, value="x")
        f2 = FormField(id=2, name="B", type=FieldType.text, value=None)
        task = self._task_with_fields([f1, f2])
        result = task.find_fields(only_filled=True)
        assert len(result) == 1

    def test_find_combined_filters(self):
        f1 = FormField(id=1, name="Status", type=FieldType.text, value="Open")
        f2 = FormField(id=2, name="Status Note", type=FieldType.text, value=None)
        f3 = FormField(id=3, name="Other", type=FieldType.text, value="Open")
        task = self._task_with_fields([f1, f2, f3])
        result = task.find_fields(name="Status", only_filled=True)
        assert len(result) == 1
        assert result[0].id == 1

    def test_find_in_nested_title(self):
        """Fields inside title sections should be found."""
        inner = FormField(id=10, name="Inner Field", type=FieldType.text, value="nested")
        title_field = FormField(
            id=100,
            name="Section",
            type=FieldType.title,
            value={"fields": [inner.model_dump()]},
        )
        task = self._task_with_fields([title_field])
        result = task.find_fields(name="Inner")
        assert len(result) == 1
        assert result[0].id == 10

    def test_find_empty_returns_empty(self):
        task = self._task_with_fields([])
        assert task.find_fields(name="anything") == []


# ── Task.get_field nested ───────────────────────────────────


class TestGetFieldNested:
    def test_get_field_in_title_by_name(self):
        inner = FormField(id=10, name="Nested", type=FieldType.text, value="val")
        title = FormField(
            id=100,
            name="Section",
            type=FieldType.title,
            value={"fields": [inner.model_dump()]},
        )
        task = Task(id=1, fields=[title])
        found = task.get_field("Nested")
        assert found is not None
        assert found.id == 10

    def test_get_field_in_title_by_id(self):
        inner = FormField(id=10, name="Nested", type=FieldType.text, value="val")
        title = FormField(
            id=100,
            name="Section",
            type=FieldType.title,
            value={"fields": [inner.model_dump()]},
        )
        task = Task(id=1, fields=[title])
        found = task.get_field(10)
        assert found is not None
        assert found.name == "Nested"

    def test_get_field_by_code(self):
        f = FormField(id=1, name="Status", code="status_field", type=FieldType.text, value="Open")
        task = Task(id=1, fields=[f])
        found = task.get_field("status_field")
        assert found is not None
        assert found.id == 1


# ── Task.context ────────────────────────────────────────────


class TestTaskContext:
    def test_task_context_factory(self):
        from unittest.mock import MagicMock

        task = Task(id=42)
        client = MagicMock()
        ctx = task.context(client)
        assert ctx.id == 42


# ── Comment properties ──────────────────────────────────────


class TestCommentProperties:
    def test_is_approval_true(self):
        c = Comment(id=1, approval_choice=ApprovalChoice.approved)
        assert c.is_approval is True
        assert c.is_approved is True
        assert c.is_rejected is False

    def test_is_rejected(self):
        c = Comment(id=1, approval_choice=ApprovalChoice.rejected)
        assert c.is_rejected is True
        assert c.is_approved is False

    def test_is_finished(self):
        c = Comment(id=1, action=TaskAction.finished)
        assert c.is_finished is True

    def test_not_approval(self):
        c = Comment(id=1, text="Just a comment")
        assert c.is_approval is False
        assert c.is_finished is False


# ── ApprovalEntry ───────────────────────────────────────────


class TestApprovalEntryExtra:
    def test_is_rejected(self):
        entry = ApprovalEntry(
            person=Person(id=1, first_name="A", last_name="B"),
            approval_choice=ApprovalChoice.rejected,
        )
        assert entry.is_rejected is True
        assert entry.is_approved is False
        assert entry.is_waiting is False


# ── Catalog.find_item ───────────────────────────────────────


class TestCatalogFindItem:
    def test_found(self):
        cat = Catalog(
            catalog_id=1,
            name="Cities",
            items=[
                CatalogItem(item_id=1, values=["Moscow", "MSK"]),
                CatalogItem(item_id=2, values=["London", "LDN"]),
            ],
        )
        item = cat.find_item("Moscow")
        assert item is not None
        assert item.item_id == 1

    def test_not_found(self):
        cat = Catalog(
            catalog_id=1,
            name="Cities",
            items=[CatalogItem(item_id=1, values=["Moscow"])],
        )
        assert cat.find_item("London") is None

    def test_empty_items(self):
        cat = Catalog(catalog_id=1, name="Empty")
        assert cat.find_item("anything") is None

    def test_empty_values_in_item(self):
        cat = Catalog(
            catalog_id=1,
            name="Test",
            items=[CatalogItem(item_id=1, values=[])],
        )
        assert cat.find_item("x") is None


# ── Form.get_field ──────────────────────────────────────────


class TestFormGetField:
    def test_top_level(self):
        form = Form(
            id=321,
            name="Test",
            fields=[FormField(id=10, name="Status", type=FieldType.text)],
        )
        found = form.get_field(10)
        assert found is not None
        assert found.name == "Status"

    def test_nested_in_info_fields(self):
        form = Form(
            id=321,
            name="Test",
            fields=[
                FormField(
                    id=100,
                    name="Section",
                    type=FieldType.title,
                    info={"fields": [{"id": 10, "name": "Inner", "type": "text"}]},
                )
            ],
        )
        found = form.get_field(10)
        assert found is not None
        assert found.name == "Inner"

    def test_deeply_nested(self):
        form = Form(
            id=321,
            name="Test",
            fields=[
                FormField(
                    id=100,
                    name="L1",
                    type=FieldType.title,
                    info={
                        "fields": [
                            {
                                "id": 200,
                                "name": "L2",
                                "type": "title",
                                "info": {"fields": [{"id": 10, "name": "Deep", "type": "text"}]},
                            }
                        ]
                    },
                )
            ],
        )
        found = form.get_field(10)
        assert found is not None
        assert found.name == "Deep"

    def test_not_found(self):
        form = Form(id=321, name="Test", fields=[])
        assert form.get_field(999) is None

    def test_non_dict_in_info_fields(self):
        """Non-dict items in info['fields'] should be skipped."""
        form = Form(
            id=321,
            name="Test",
            fields=[
                FormField(
                    id=100,
                    name="Section",
                    type=FieldType.title,
                    info={"fields": ["not_a_dict", {"id": 10, "name": "OK", "type": "text"}]},
                )
            ],
        )
        found = form.get_field(10)
        assert found is not None


# ── FormField accessors edge cases ──────────────────────────


class TestFormFieldAccessors:
    def test_as_person_non_dict(self):
        f = FormField(id=1, type=FieldType.person, value="not a dict")
        assert f.as_person() is None

    def test_as_files_non_list(self):
        f = FormField(id=1, type=FieldType.file, value="not a list")
        assert f.as_files() == []

    def test_as_catalog_non_dict(self):
        f = FormField(id=1, type=FieldType.catalog, value=123)
        assert f.as_catalog() is None

    def test_as_multiple_choice_non_dict(self):
        f = FormField(id=1, type=FieldType.multiple_choice, value="wrong")
        assert f.as_multiple_choice() is None

    def test_as_title_non_dict(self):
        f = FormField(id=1, type=FieldType.title, value=42)
        assert f.as_title() is None

    def test_as_form_link(self):
        f = FormField(
            id=1,
            type=FieldType.form_link,
            value={"task_ids": [1, 2], "subject": "Linked"},
        )
        link = f.as_form_link()
        assert link is not None
        assert link.task_ids == [1, 2]

    def test_as_form_link_non_dict(self):
        f = FormField(id=1, type=FieldType.form_link, value="wrong")
        assert f.as_form_link() is None

    def test_as_table_rows(self):
        f = FormField(
            id=1,
            type=FieldType.table,
            value=[
                {"row_id": 1, "cells": [{"id": 10, "value": "A"}]},
                {"row_id": 2, "cells": [{"id": 10, "value": "B"}]},
            ],
        )
        rows = f.as_table_rows()
        assert len(rows) == 2
        assert rows[0].row_id == 1

    def test_as_table_rows_non_list(self):
        f = FormField(id=1, type=FieldType.table, value="not a list")
        assert f.as_table_rows() == []

    def test_repr(self):
        f = FormField(id=42, type=FieldType.text, name="Test", value="hello")
        r = repr(f)
        assert "42" in r
        assert "Test" in r


# ── BotResponse ─────────────────────────────────────────────


class TestBotResponseExtra:
    def test_dump_clean_removes_none(self):
        resp = BotResponse(text="Hello")
        dumped = resp.model_dump_clean()
        assert "text" in dumped
        assert "formatted_text" not in dumped

    def test_dump_clean_all_none(self):
        resp = BotResponse()
        dumped = resp.model_dump_clean()
        assert dumped == {}

    def test_dump_clean_with_field_updates(self):
        resp = BotResponse(
            text="Updated",
            field_updates=[{"id": 1, "value": "x"}],
        )
        dumped = resp.model_dump_clean()
        assert dumped["text"] == "Updated"
        assert dumped["field_updates"] == [{"id": 1, "value": "x"}]


# ── Person ──────────────────────────────────────────────────


class TestPersonExtra:
    def test_full_name_only_first(self):
        p = Person(id=1, first_name="Ivan")
        assert p.full_name == "Ivan"

    def test_full_name_only_last(self):
        p = Person(id=1, last_name="Ivanov")
        assert p.full_name == "Ivanov"

    def test_full_name_none(self):
        p = Person(id=1)
        assert p.full_name == ""


# ── Announcement ────────────────────────────────────────────


class TestAnnouncement:
    def test_parse(self):
        ann = Announcement(id=1, text="Hello")
        assert ann.id == 1
        assert ann.text == "Hello"

    def test_with_comments(self):
        data = {
            "id": 1,
            "text": "Main",
            "comments": [{"id": 10, "text": "Reply"}],
        }
        ann = Announcement.model_validate(data)
        assert len(ann.comments) == 1
        assert ann.comments[0].text == "Reply"
