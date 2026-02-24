"""Tests for Pydantic type models."""

from __future__ import annotations

from datetime import datetime

from aiopyrus.types.form import (
    FieldType,
    FormField,
)
from aiopyrus.types.task import ApprovalChoice, ApprovalEntry, Comment, Task, TaskAction
from aiopyrus.types.user import Person, PersonType
from aiopyrus.types.webhook import BotResponse, WebhookPayload


class TestTask:
    def test_basic(self):
        t = Task(id=1)
        assert t.id == 1
        assert t.form_id is None
        assert t.fields == []

    def test_is_form_task(self):
        assert Task(id=1, form_id=321).is_form_task is True
        assert Task(id=1).is_form_task is False

    def test_closed(self):
        assert Task(id=1, is_closed=True).closed is True
        assert Task(id=1, close_date=datetime.now()).closed is True
        assert Task(id=1).closed is False

    def test_get_field_by_name(self):
        f = FormField(id=1, name="Status", type=FieldType.text, value="Open")
        t = Task(id=1, fields=[f])
        assert t.get_field("Status") is f

    def test_get_field_by_id(self):
        f = FormField(id=42, name="Status", type=FieldType.text)
        t = Task(id=1, fields=[f])
        assert t.get_field(42) is f

    def test_get_field_by_code(self):
        f = FormField(id=1, name="Status", code="u_status", type=FieldType.text)
        t = Task(id=1, fields=[f])
        assert t.get_field("u_status") is f

    def test_get_field_not_found(self):
        t = Task(id=1, fields=[])
        assert t.get_field("Missing") is None

    def test_form_id_none_from_register(self):
        """Task from register has form_id=None — mutable for backfill."""
        t = Task(id=1, current_step=6)
        assert t.form_id is None
        t.form_id = 321
        assert t.form_id == 321


class TestFieldType:
    def test_person_responsible(self):
        """FieldType.person_responsible should be a valid enum value."""
        assert FieldType("person_responsible") is FieldType.person_responsible

    def test_all_common_types(self):
        """Smoke test: common field types are parseable."""
        for name in (
            "text",
            "money",
            "number",
            "date",
            "due_date",
            "person",
            "catalog",
            "multiple_choice",
            "form_link",
            "step",
            "project",
            "person_responsible",
        ):
            ft = FieldType(name)
            assert ft.value == name

    def test_get_field_in_title(self):
        """Fields nested inside a title section are found recursively."""
        inner = FormField(id=10, name="Inner", type=FieldType.text, value="val")
        title = FormField(
            id=1,
            name="Section",
            type=FieldType.title,
            value={"fields": [inner.model_dump()]},
        )
        t = Task(id=1, fields=[title])
        found = t.get_field("Inner")
        assert found is not None
        assert found.id == 10

    def test_latest_comment(self):
        c = Comment(id=1, text="Hello")
        t = Task(id=1, comments=[c])
        assert t.latest_comment is c
        assert Task(id=1).latest_comment is None

    def test_find_fields(self):
        f1 = FormField(id=1, name="Request Type", type=FieldType.text, value="Bug")
        f2 = FormField(id=2, name="Description", type=FieldType.text, value="Details")
        t = Task(id=1, fields=[f1, f2])
        results = t.find_fields(name="type")
        assert len(results) == 1
        assert results[0].id == 1

    def test_repr(self):
        t = Task(id=42, form_id=321, current_step=2)
        assert "42" in repr(t)
        assert "321" in repr(t)


class TestPerson:
    def test_full_name(self):
        p = Person(id=1, first_name="Ivan", last_name="Ivanov")
        assert p.full_name == "Ivan Ivanov"

    def test_full_name_partial(self):
        p = Person(id=1, first_name="Ivan")
        assert p.full_name == "Ivan"

    def test_person_type(self):
        p = Person(id=1, type=PersonType.role)
        assert p.type == PersonType.role


class TestFormField:
    def test_as_person(self):
        f = FormField(
            id=1,
            type=FieldType.person,
            value={"id": 42, "first_name": "Ivan", "last_name": "Ivanov"},
        )
        p = f.as_person()
        assert p is not None
        assert p.id == 42

    def test_as_multiple_choice(self):
        f = FormField(
            id=1,
            type=FieldType.multiple_choice,
            value={"choice_ids": [1], "choice_names": ["Open"]},
        )
        mc = f.as_multiple_choice()
        assert mc is not None
        assert mc.choice_names == ["Open"]

    def test_as_catalog(self):
        f = FormField(
            id=1,
            type=FieldType.catalog,
            value={"item_id": 42, "values": ["Moscow"]},
        )
        cat = f.as_catalog()
        assert cat is not None
        assert cat.item_id == 42

    def test_as_title(self):
        f = FormField(
            id=1,
            type=FieldType.title,
            value={"checkmark": "checked", "fields": []},
        )
        title = f.as_title()
        assert title is not None
        assert title.checkmark == "checked"

    def test_as_files(self):
        f = FormField(
            id=1,
            type=FieldType.file,
            value=[{"id": 1, "name": "doc.pdf"}],
        )
        files = f.as_files()
        assert len(files) == 1


class TestWebhookPayload:
    def test_parse(self):
        p = WebhookPayload(
            event="task_received",
            access_token="tok",
            task_id=1,
            task=Task(id=1),
        )
        assert p.is_task_created is False
        assert p.event == "task_received"

    def test_is_task_created(self):
        p = WebhookPayload(
            event="task_created",
            task_id=1,
            task=Task(id=1),
        )
        assert p.is_task_created is True


class TestBotResponse:
    def test_dump_clean(self):
        r = BotResponse(text="OK")
        d = r.model_dump_clean()
        assert d == {"text": "OK"}
        assert "action" not in d

    def test_empty(self):
        r = BotResponse()
        assert r.model_dump_clean() == {}


class TestComment:
    def test_is_approval(self):
        c = Comment(id=1, approval_choice=ApprovalChoice.approved)
        assert c.is_approval is True
        assert c.is_approved is True

    def test_is_finished(self):
        c = Comment(id=1, action=TaskAction.finished)
        assert c.is_finished is True


class TestApprovalEntry:
    def test_is_waiting(self):
        e = ApprovalEntry(person=Person(id=1), approval_choice=ApprovalChoice.waiting)
        assert e.is_waiting is True

    def test_is_waiting_none(self):
        e = ApprovalEntry(person=Person(id=1), approval_choice=None)
        assert e.is_waiting is True

    def test_is_approved(self):
        e = ApprovalEntry(person=Person(id=1), approval_choice=ApprovalChoice.approved)
        assert e.is_approved is True
        assert e.is_rejected is False
