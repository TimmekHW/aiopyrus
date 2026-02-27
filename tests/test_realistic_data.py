"""Tests with realistic Pyrus API data — responses from docs, edge cases, boundary values.

Uses real JSON shapes from https://pyrus.com/ru/help/api/ documentation.
Validates that Pydantic models correctly parse production-like data with
Unicode, nulls, nested structures, and all field types.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx

from aiopyrus.types.catalog import Catalog, CatalogItem, CatalogSyncResult
from aiopyrus.types.form import (
    FieldType,
    Form,
    FormField,
)
from aiopyrus.types.task import (
    Announcement,
    ApprovalChoice,
    ApprovalEntry,
    Channel,
    ChannelType,
    Comment,
    RegisterResponse,
    SubscriberEntry,
    Task,
    TaskAction,
    TaskList,
)
from aiopyrus.types.user import (
    ContactsResponse,
    Person,
    PersonType,
    Profile,
)
from aiopyrus.types.webhook import BotResponse, WebhookPayload
from aiopyrus.user.client import UserClient
from aiopyrus.utils.fields import (
    FieldUpdate,
    format_mention,
    get_flat_fields,
    select_fields,
)

# ══════════════════════════════════════════════════════════════
# Test data from Pyrus API docs (https://pyrus.com/ru/help/api/)
# ══════════════════════════════════════════════════════════════

# Real task JSON from GET /tasks/{id} docs
REAL_TASK_JSON = {
    "id": 11613,
    "text": "Payments",
    "create_date": "2017-08-17T14:31:18Z",
    "last_modified_date": "2017-08-18T10:00:11Z",
    "author": {
        "id": 1731,
        "first_name": "Bob",
        "last_name": "Smith",
        "email": "Bob.Smith@gmail.com",
        "type": "user",
    },
    "form_id": 1345,
    "responsible": {
        "id": 1733,
        "first_name": "John",
        "last_name": "Snow",
        "email": "John.Snow@gmail.com",
        "type": "user",
    },
    "approvals": [
        [
            {
                "person": {
                    "id": 1733,
                    "first_name": "John",
                    "last_name": "Snow",
                    "email": "John.Snow@gmail.com",
                    "type": "user",
                },
                "approval_choice": "waiting",
            }
        ]
    ],
    "fields": [
        {"id": 1, "type": "text", "name": "Purpose", "value": "IT conference in Amsterdam"},
        {"id": 2, "type": "money", "name": "Amount", "value": 10306.25},
    ],
    "comments": [
        {
            "id": 13767,
            "create_date": "2017-08-17T14:31:18Z",
            "author": {
                "id": 1731,
                "first_name": "Bob",
                "last_name": "Smith",
                "email": "Bob.Smith@gmail.com",
                "type": "user",
            },
            "reassigned_to": {
                "id": 1730,
                "first_name": "John",
                "last_name": "Snow",
                "email": "John.Snow@gmail.com",
                "type": "user",
            },
        }
    ],
}

# Real contacts JSON from GET /contacts docs
REAL_CONTACTS_JSON = {
    "organizations": [
        {
            "organization_id": 2181,
            "name": "My Organization",
            "department_catalog_id": 1234,
            "persons": [
                {
                    "id": 1731,
                    "first_name": "\u0418\u0432\u0430\u043d",
                    "last_name": "\u041a\u043e\u0442\u043e\u0432",
                    "mobile_phone": "79031234567",
                    "email": "iv.kotov@gmail.com",
                    "type": "user",
                    "department_id": 13836,
                    "department_name": "Marketing",
                },
                {
                    "id": 1733,
                    "first_name": "\u0421\u0442\u0430\u043d\u0438\u0441\u043b\u0430\u0432",
                    "last_name": "\u041b\u043e\u043c\u043e\u0432",
                    "email": "stas.lomov@gmail.com",
                    "type": "user",
                },
                {
                    "id": 1725,
                    "first_name": "\u041b\u043e\u0440\u0430",
                    "last_name": "\u041b\u044c\u0432\u043e\u0432\u0430",
                    "email": "l.lvova.gmail.com",
                    "type": "user",
                },
            ],
            "roles": [
                {
                    "id": 1743,
                    "name": "SomeRole",
                    "member_ids": [1725, 1733],
                    "type": "role",
                }
            ],
        }
    ]
}

# Real member JSON from GET /members/{id} docs — fired + banned + emoji status
REAL_MEMBER_FULL_JSON = {
    "id": 664768,
    "first_name": "mna",
    "last_name": "nas",
    "email": "test.pyrus.account@gmail.com",
    "type": "user",
    "external_id": "",
    "status": "\U0001f637\u0417\u0430\u0431\u043e\u043b\u0435\u043b",
    "banned": True,
    "fired": True,
    "position": "",
    "mobile_phone": "79091234567",
    "phone": "71234567890",
}

# Real catalog JSON from GET /catalogs/{id} docs
REAL_CATALOG_JSON = {
    "catalog_id": 6625,
    "name": "Clients",
    "catalog_headers": [
        {"name": "Name", "type": "text"},
        {"name": "Company", "type": "text"},
    ],
    "items": [
        {"item_id": 15200, "values": ["Reatha Middendorf", "Acme, inc."]},
        {"item_id": 15201, "values": ["Daedra Ullrich", "Widget Corp"]},
        {"item_id": 15202, "values": ["Andy Mahn", "123 Warehousing"]},
    ],
}

# Real announcement JSON from GET /announcements/{id} docs
REAL_ANNOUNCEMENT_JSON = {
    "id": 14786,
    "text": "New announcement",
    "formatted_text": "New announcement",
    "create_date": "2022-04-27T10:51:50Z",
    "author": {
        "id": 1731,
        "first_name": "Bob",
        "last_name": "Smith",
        "email": "Bob.Smith@gmail.com",
        "type": "user",
        "external_id": "",
        "department_id": 13836,
        "banned": False,
    },
    "comments": [
        {
            "id": 29662,
            "text": "Comment",
            "formatted_text": "Comment",
            "create_date": "2022-04-27T10:51:50Z",
            "author": {
                "id": 1731,
                "first_name": "Bob",
                "last_name": "Smith",
                "email": "Bob.Smith@gmail.com",
                "type": "user",
                "external_id": "",
                "department_id": 13836,
                "banned": False,
            },
        }
    ],
}

# Real lists JSON from GET /lists docs
REAL_LISTS_JSON = {
    "lists": [
        {
            "id": 1352,
            "name": "Branch offices",
            "children": [
                {"id": 1465, "name": "Moscow"},
                {"id": 3763, "name": "San Francisco"},
            ],
        },
        {"id": 2144, "name": "Personal"},
    ]
}


# ══════════════════════════════════════════════════════════════
# 1. Parsing real API responses into Pydantic models
# ══════════════════════════════════════════════════════════════


class TestParseRealTaskResponse:
    """Parse the exact JSON from Pyrus docs into our Task model."""

    def test_basic_fields(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert task.id == 11613
        assert task.text == "Payments"
        assert task.form_id == 1345
        assert isinstance(task.create_date, datetime)
        assert isinstance(task.last_modified_date, datetime)

    def test_author_person(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert task.author is not None
        assert task.author.id == 1731
        assert task.author.first_name == "Bob"
        assert task.author.last_name == "Smith"
        assert task.author.email == "Bob.Smith@gmail.com"
        assert task.author.type == PersonType.user

    def test_responsible(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert task.responsible is not None
        assert task.responsible.full_name == "John Snow"

    def test_approvals_nested(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert task.approvals is not None
        assert len(task.approvals) == 1
        step = task.approvals[0]
        assert len(step) == 1
        entry = step[0]
        assert entry.person.id == 1733
        assert entry.approval_choice == ApprovalChoice.waiting
        assert entry.is_waiting is True
        assert entry.is_approved is False

    def test_form_fields(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert len(task.fields) == 2
        purpose = task.get_field("Purpose")
        assert purpose is not None
        assert purpose.value == "IT conference in Amsterdam"
        assert purpose.type == FieldType.text

        amount = task.get_field("Amount")
        assert amount is not None
        assert amount.value == 10306.25
        assert amount.type == FieldType.money

    def test_comments_with_reassign(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert len(task.comments) == 1
        c = task.comments[0]
        assert c.id == 13767
        assert c.reassigned_to is not None
        assert c.reassigned_to.first_name == "John"

    def test_is_form_task(self):
        task = Task.model_validate(REAL_TASK_JSON)
        assert task.is_form_task is True


class TestParseRealContacts:
    """Parse contacts JSON with Russian names and roles."""

    def test_organizations(self):
        resp = ContactsResponse.model_validate(REAL_CONTACTS_JSON)
        assert len(resp.organizations) == 1
        org = resp.organizations[0]
        assert org.organization_id == 2181
        assert org.department_catalog_id == 1234

    def test_russian_names(self):
        resp = ContactsResponse.model_validate(REAL_CONTACTS_JSON)
        persons = resp.organizations[0].persons
        assert len(persons) == 3
        assert persons[0].first_name == "\u0418\u0432\u0430\u043d"
        assert persons[0].last_name == "\u041a\u043e\u0442\u043e\u0432"
        assert persons[0].department_name == "Marketing"
        assert persons[0].mobile_phone == "79031234567"

    def test_roles_in_org(self):
        resp = ContactsResponse.model_validate(REAL_CONTACTS_JSON)
        roles = resp.organizations[0].roles
        assert len(roles) == 1
        assert roles[0].name == "SomeRole"
        assert roles[0].member_ids == [1725, 1733]


class TestParseRealMember:
    """Parse member with fired/banned/emoji status."""

    def test_fired_banned_member(self):
        person = Person.model_validate(REAL_MEMBER_FULL_JSON)
        assert person.id == 664768
        assert person.fired is True
        assert person.banned is True
        assert person.position == ""
        assert "\u0417\u0430\u0431\u043e\u043b\u0435\u043b" in (person.status or "")

    def test_empty_external_id(self):
        """Pyrus returns external_id as empty string, not null — validator coerces to None."""
        person = Person.model_validate(REAL_MEMBER_FULL_JSON)
        assert person.id == 664768
        assert person.external_id is None


class TestParseRealCatalog:
    """Parse catalog with multi-column items."""

    def test_catalog_structure(self):
        cat = Catalog.model_validate(REAL_CATALOG_JSON)
        assert cat.catalog_id == 6625
        assert cat.name == "Clients"
        assert len(cat.catalog_headers) == 2
        assert cat.catalog_headers[0].name == "Name"
        assert cat.catalog_headers[1].name == "Company"

    def test_catalog_items(self):
        cat = Catalog.model_validate(REAL_CATALOG_JSON)
        assert len(cat.items) == 3
        assert cat.items[0].item_id == 15200
        assert cat.items[0].values == ["Reatha Middendorf", "Acme, inc."]

    def test_find_item_searches_first_column_only(self):
        """find_item searches by the first column value only — not second."""
        cat = Catalog.model_validate(REAL_CATALOG_JSON)
        # First column match works
        item = cat.find_item("Reatha Middendorf")
        assert item is not None
        assert item.item_id == 15200
        # Second column does NOT match (by design — find_item uses values[0])
        assert cat.find_item("Acme, inc.") is None

    def test_find_item_first_column(self):
        cat = Catalog.model_validate(REAL_CATALOG_JSON)
        item = cat.find_item("Andy Mahn")
        assert item is not None
        assert item.item_id == 15202


class TestParseRealAnnouncement:
    """Parse announcement with comments (from docs)."""

    def test_announcement_fields(self):
        ann = Announcement.model_validate(REAL_ANNOUNCEMENT_JSON)
        assert ann.id == 14786
        assert ann.text == "New announcement"
        assert isinstance(ann.create_date, datetime)

    def test_announcement_author_extra_fields(self):
        """Author has extra fields (external_id, department_id, banned) — model ignores extras."""
        ann = Announcement.model_validate(REAL_ANNOUNCEMENT_JSON)
        assert ann.author is not None
        assert ann.author.id == 1731

    def test_announcement_comments(self):
        ann = Announcement.model_validate(REAL_ANNOUNCEMENT_JSON)
        assert len(ann.comments) == 1
        comment = ann.comments[0]
        assert comment.id == 29662
        assert comment.text == "Comment"


class TestParseRealLists:
    """Parse task lists with children."""

    def test_lists_hierarchy(self):
        lists = [TaskList.model_validate(item) for item in REAL_LISTS_JSON["lists"]]
        assert len(lists) == 2
        assert lists[0].name == "Branch offices"
        assert len(lists[0].children) == 2
        assert lists[0].children[0].name == "Moscow"
        assert lists[0].children[1].name == "San Francisco"
        assert lists[1].name == "Personal"
        assert lists[1].children == []


# ══════════════════════════════════════════════════════════════
# 2. All field types — realistic values from docs
# ══════════════════════════════════════════════════════════════


class TestAllFieldTypes:
    """Parse every field type Pyrus supports with realistic values."""

    def test_text_field(self):
        f = FormField.model_validate(
            {"id": 1, "type": "text", "name": "Purpose", "value": "IT conference in Amsterdam"}
        )
        assert f.value == "IT conference in Amsterdam"
        assert f.type == FieldType.text

    def test_money_field(self):
        f = FormField.model_validate({"id": 2, "type": "money", "name": "Amount", "value": 1365.27})
        assert f.value == 1365.27

    def test_number_field(self):
        f = FormField.model_validate(
            {"id": 3, "type": "number", "name": "Quantity", "value": 157.2134}
        )
        assert f.value == 157.2134

    def test_date_field(self):
        f = FormField.model_validate(
            {"id": 4, "type": "date", "name": "Start Date", "value": "2017-03-16"}
        )
        assert f.value == "2017-03-16"

    def test_time_field(self):
        f = FormField.model_validate(
            {"id": 5, "type": "time", "name": "Meeting Time", "value": "17:26"}
        )
        assert f.value == "17:26"

    def test_email_field(self):
        f = FormField.model_validate(
            {"id": 6, "type": "email", "name": "Contact", "value": "consumer@mycompany.com"}
        )
        assert f.value == "consumer@mycompany.com"

    def test_phone_field(self):
        f = FormField.model_validate(
            {"id": 7, "type": "phone", "name": "Phone", "value": "+7 800 555 3565"}
        )
        assert f.value == "+7 800 555 3565"

    def test_checkmark_field(self):
        f = FormField.model_validate(
            {"id": 8, "type": "checkmark", "name": "Confirmed", "value": "checked"}
        )
        assert f.value == "checked"

    def test_flag_field(self):
        f = FormField.model_validate(
            {"id": 9, "type": "flag", "name": "Important", "value": "unchecked"}
        )
        assert f.value == "unchecked"

    def test_status_field(self):
        f = FormField.model_validate(
            {"id": 10, "type": "status", "name": "Task Status", "value": "open"}
        )
        assert f.value == "open"

    def test_due_date_field_with_duration(self):
        f = FormField.model_validate(
            {
                "id": 11,
                "type": "due_date",
                "name": "Deadline",
                "value": "2017-03-16",
                "duration": "140",
            }
        )
        assert f.value == "2017-03-16"
        assert f.duration == "140"

    def test_due_date_time_field(self):
        f = FormField.model_validate(
            {
                "id": 12,
                "type": "due_date_time",
                "name": "Exact Deadline",
                "value": "2017-03-16T14:53:23Z",
                "duration": "140",
            }
        )
        assert "2017-03-16" in str(f.value)

    def test_catalog_single_select(self):
        f = FormField.model_validate(
            {
                "id": 13,
                "type": "catalog",
                "name": "Payment type",
                "catalog_id": 277,
                "value": {
                    "item_id": 80797460,
                    "item_ids": [80797460],
                    "headers": ["Vendor Name", "Vendor Code"],
                    "values": ["GE", "123"],
                    "rows": [["GE", "123"]],
                },
            }
        )
        cat = f.as_catalog()
        assert cat is not None
        assert cat.item_id == 80797460
        assert cat.item_ids == [80797460]
        assert cat.headers == ["Vendor Name", "Vendor Code"]
        assert cat.values == ["GE", "123"]
        assert cat.rows == [["GE", "123"]]

    def test_catalog_multi_select(self):
        f = FormField.model_validate(
            {
                "id": 14,
                "type": "catalog",
                "name": "Vendors",
                "value": {
                    "item_ids": [80797460, 80797461],
                    "headers": ["Vendor Name", "Vendor Code"],
                    "rows": [["GE", "123"], ["VN", "321"]],
                },
            }
        )
        cat = f.as_catalog()
        assert cat is not None
        assert cat.item_id is None
        assert cat.item_ids == [80797460, 80797461]
        assert cat.rows is not None
        assert len(cat.rows) == 2

    def test_person_field(self):
        f = FormField.model_validate(
            {
                "id": 15,
                "type": "person",
                "name": "Executor",
                "value": {
                    "id": 1730,
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "email": "Jane.Doe@gmail.com",
                    "type": "user",
                },
            }
        )
        p = f.as_person()
        assert p is not None
        assert p.id == 1730
        assert p.full_name == "Jane Doe"

    def test_multiple_choice_with_sub_fields(self):
        """Multiple choice where selecting an option reveals sub-fields."""
        f = FormField.model_validate(
            {
                "id": 16,
                "type": "multiple_choice",
                "name": "Decision",
                "value": {
                    "choice_ids": [5],
                    "choice_names": ["Yes"],
                    "fields": [
                        {
                            "id": 6,
                            "type": "text",
                            "name": "Comment",
                            "value": "Additional info",
                            "parent_id": 4,
                        },
                        {
                            "id": 9,
                            "type": "number",
                            "name": "Quantity",
                            "value": 15,
                            "parent_id": 4,
                        },
                    ],
                },
            }
        )
        mc = f.as_multiple_choice()
        assert mc is not None
        assert mc.choice_ids == [5]
        assert mc.choice_names == ["Yes"]
        assert mc.fields is not None
        assert len(mc.fields) == 2
        assert mc.fields[0].name == "Comment"
        assert mc.fields[1].value == 15

    def test_table_field_with_rows(self):
        """Table field from the docs — rows with position and cells."""
        f = FormField.model_validate(
            {
                "id": 5,
                "type": "table",
                "name": "Payment Schedule",
                "value": [
                    {
                        "row_id": 0,
                        "position": 1,
                        "cells": [
                            {
                                "id": 6,
                                "type": "date",
                                "name": "Date",
                                "value": "2017-08-26",
                                "parent_id": 5,
                                "row_id": 0,
                            },
                            {
                                "id": 9,
                                "type": "money",
                                "name": "Amount",
                                "value": 10000,
                                "parent_id": 5,
                                "row_id": 0,
                            },
                        ],
                    },
                    {
                        "row_id": 1,
                        "position": 1,
                        "cells": [
                            {
                                "id": 6,
                                "type": "date",
                                "name": "Date",
                                "value": "2017-08-27",
                                "parent_id": 5,
                                "row_id": 1,
                            },
                            {
                                "id": 9,
                                "type": "money",
                                "name": "Amount",
                                "value": 306.25,
                                "parent_id": 5,
                                "row_id": 1,
                            },
                        ],
                    },
                ],
            }
        )
        rows = f.as_table_rows()
        assert len(rows) == 2
        assert rows[0].row_id == 0
        assert rows[0].position == 1
        assert len(rows[0].cells) == 2
        assert rows[0].cells[0].value == "2017-08-26"
        assert rows[0].cells[1].value == 10000
        assert rows[1].cells[1].value == 306.25

    def test_title_with_checkmark_and_nested(self):
        """Title section with checkmark and nested fields (from docs)."""
        f = FormField.model_validate(
            {
                "id": 2,
                "type": "title",
                "name": "Issue Details",
                "value": {
                    "checkmark": "checked",
                    "fields": [
                        {
                            "id": 3,
                            "type": "date",
                            "name": "Date",
                            "value": "2017-08-19",
                            "parent_id": 2,
                        },
                        {
                            "id": 4,
                            "type": "text",
                            "name": "Description",
                            "value": "My issue",
                            "parent_id": 2,
                        },
                    ],
                },
            }
        )
        title = f.as_title()
        assert title is not None
        assert title.checkmark == "checked"
        assert title.fields is not None
        assert len(title.fields) == 2
        assert title.fields[0].value == "2017-08-19"
        assert title.fields[1].value == "My issue"

    def test_form_link_field(self):
        f = FormField.model_validate(
            {
                "id": 17,
                "type": "form_link",
                "name": "Linked Expense",
                "value": {"task_ids": [1573], "subject": "Expense report"},
            }
        )
        link = f.as_form_link()
        assert link is not None
        assert link.task_ids == [1573]
        assert link.subject == "Expense report"

    def test_file_field_with_version(self):
        """File field with versioning (root_id + version)."""
        f = FormField.model_validate(
            {
                "id": 18,
                "type": "file",
                "name": "Documents",
                "value": [
                    {
                        "id": 17563,
                        "name": "S15294-16.pdf",
                        "size": 541512,
                        "md5": "202cb962ac59075b964b07152d234b70",
                        "url": "https://api.pyrus.com/files/17563",
                        "version": 2,
                        "root_id": 17562,
                    }
                ],
            }
        )
        files = f.as_files()
        assert len(files) == 1
        assert files[0].id == 17563
        assert files[0].name == "S15294-16.pdf"
        assert files[0].size == 541512
        assert files[0].md5 == "202cb962ac59075b964b07152d234b70"
        assert files[0].version == 2
        assert files[0].root_id == 17562

    def test_creation_date_field(self):
        f = FormField.model_validate(
            {"id": 19, "type": "creation_date", "name": "Created", "value": "2017-08-17T14:31:18Z"}
        )
        assert f.type == FieldType.creation_date

    def test_note_field(self):
        f = FormField.model_validate(
            {
                "id": 20,
                "type": "note",
                "name": "Instructions",
                "value": "Fill all fields before submitting",
            }
        )
        assert f.type == FieldType.note

    def test_step_field(self):
        f = FormField.model_validate(
            {"id": 21, "type": "step", "name": "Current Step", "value": "3"}
        )
        assert f.type == FieldType.step

    def test_person_responsible_field(self):
        f = FormField.model_validate(
            {
                "id": 22,
                "type": "person_responsible",
                "name": "Responsible",
                "value": {"id": 1733, "first_name": "John", "last_name": "Snow"},
            }
        )
        assert f.type == FieldType.person_responsible


# ══════════════════════════════════════════════════════════════
# 3. Edge cases and boundary values
# ══════════════════════════════════════════════════════════════


class TestEdgeCaseTasks:
    """Tasks with unusual or boundary data."""

    def test_task_minimal(self):
        """Task with only required field (id)."""
        task = Task(id=1)
        assert task.text is None
        assert task.form_id is None
        assert task.fields == []
        assert task.comments == []
        assert task.participants == []
        assert task.approvals is None
        assert task.closed is False

    def test_task_all_optional_fields(self):
        """Task with every optional field populated."""
        task = Task.model_validate(
            {
                "id": 99999999,
                "text": "\u0417\u0430\u0434\u0430\u0447\u0430 \u0441 \u044e\u043d\u0438\u043a\u043e\u0434\u043e\u043c \ud83d\ude80",
                "formatted_text": "<b>\u0412\u0430\u0436\u043d\u043e</b>",
                "subject": "\u0422\u0435\u043c\u0430 \u0437\u0430\u0434\u0430\u0447\u0438",
                "create_date": "2026-01-15T08:00:00Z",
                "last_modified_date": "2026-02-20T14:30:00Z",
                "close_date": "2026-02-25T18:00:00Z",
                "due_date": "2026-03-01",
                "due": "2026-03-01T10:00:00Z",
                "duration": 60,
                "scheduled_date": "2026-02-28",
                "scheduled_datetime_utc": "2026-02-28T09:00:00Z",
                "author": {
                    "id": 100500,
                    "first_name": "\u0414\u0430\u043d\u0438\u043b",
                    "last_name": "\u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
                },
                "responsible": {
                    "id": 100501,
                    "first_name": "\u0410\u043d\u043d\u0430",
                    "last_name": "\u041f\u0435\u0442\u0440\u043e\u0432\u0430",
                },
                "form_id": 321,
                "current_step": 3,
                "parent_task_id": 88888888,
                "linked_task_ids": [11111111, 22222222],
                "list_ids": [1, 2, 3],
                "flat": True,
                "deleted": False,
                "is_closed": True,
                "close_comment": "\u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e",
                "participants": [
                    {"id": 100502, "first_name": "\u0418\u0432\u0430\u043d"},
                    {
                        "id": 100503,
                        "first_name": "\u041f\u0451\u0442\u0440",
                        "last_name": "\u041f\u0435\u0442\u0440\u043e\u0432",
                    },
                ],
                "subscribers": [
                    {"person": {"id": 100504, "first_name": "\u041e\u043b\u044c\u0433\u0430"}},
                ],
                "fields": [],
                "comments": [],
                "attachments": [
                    {
                        "id": 555,
                        "name": "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442.pdf",
                        "size": 1024000,
                    }
                ],
            }
        )
        assert task.id == 99999999
        assert task.closed is True
        assert task.is_form_task is True
        assert task.parent_task_id == 88888888
        assert len(task.linked_task_ids) == 2
        assert len(task.participants) == 2
        assert len(task.subscribers) == 1
        assert task.duration == 60
        assert task.author is not None
        assert (
            task.author.full_name
            == "\u0414\u0430\u043d\u0438\u043b \u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e"
        )

    def test_task_from_inbox_sparse(self):
        """Inbox returns sparse task — no fields, no form_id, no approvals."""
        task = Task.model_validate(
            {
                "id": 12345,
                "text": "Inbox task",
                "create_date": "2026-01-01T00:00:00Z",
                "last_modified_date": "2026-01-02T00:00:00Z",
                "author": {"id": 1, "first_name": "A"},
                "responsible": {"id": 2, "first_name": "B"},
            }
        )
        assert task.form_id is None
        assert task.current_step is None
        assert task.fields == []
        assert task.approvals is None
        assert task.is_form_task is False

    def test_task_from_register_no_form_id(self):
        """Register returns task with current_step but no form_id — we backfill it."""
        task = Task.model_validate(
            {
                "id": 42,
                "current_step": 2,
                "fields": [{"id": 1, "type": "text", "name": "Name", "value": "Test"}],
            }
        )
        assert task.form_id is None
        task.form_id = 321
        assert task.form_id == 321

    def test_zero_money_field(self):
        """Money value can be 0 or 0.0 — shouldn't be treated as None."""
        f = FormField(id=1, type=FieldType.money, name="Amount", value=0)
        assert f.value == 0
        f2 = FormField(id=2, type=FieldType.money, name="Amount", value=0.0)
        assert f2.value == 0.0

    def test_large_task_id(self):
        """Pyrus task IDs can be very large integers."""
        task = Task(id=999999999)
        assert task.id == 999999999

    def test_empty_string_values(self):
        """Fields with empty string values should not be treated as None."""
        f = FormField(id=1, type=FieldType.text, name="Notes", value="")
        assert f.value == ""


class TestEdgeCasePersons:
    """Person model edge cases."""

    def test_person_no_names(self):
        """Person with only id — full_name should be empty."""
        p = Person(id=1)
        assert p.full_name == ""

    def test_person_all_types(self):
        for t in (PersonType.person, PersonType.role, PersonType.bot):
            p = Person(id=1, type=t)
            assert p.type is not None

    def test_person_with_task_receiver(self):
        """Fired employee who delegates tasks to another."""
        p = Person(
            id=100,
            first_name="\u0418\u0432\u0430\u043d",
            last_name="\u0418\u0432\u0430\u043d\u043e\u0432",
            fired=True,
            task_receiver=200,
        )
        assert p.fired is True
        assert p.task_receiver == 200

    def test_person_native_names(self):
        """Non-Latin native names (Japanese, Chinese, etc.)."""
        p = Person(
            id=1,
            first_name="Takeshi",
            last_name="Yamamoto",
            native_first_name="\u5c71\u672c",
            native_last_name="\u6b66\u53f2",
        )
        assert p.native_first_name == "\u5c71\u672c"
        assert p.full_name == "Takeshi Yamamoto"

    def test_person_repr(self):
        p = Person(
            id=100500,
            first_name="\u0414\u0430\u043d\u0438\u043b",
            last_name="\u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
        )
        r = repr(p)
        assert "100500" in r


class TestEdgeCaseComments:
    """Comment model with various action types."""

    def test_approval_comment(self):
        c = Comment.model_validate(
            {
                "id": 100,
                "create_date": "2026-01-15T10:00:00Z",
                "author": {"id": 1731, "first_name": "Bob"},
                "approval_choice": "approved",
                "approval_step": 2,
            }
        )
        assert c.is_approval is True
        assert c.is_approved is True
        assert c.approval_step == 2

    def test_rejection_comment(self):
        c = Comment(id=101, approval_choice=ApprovalChoice.rejected)
        assert c.is_rejected is True
        assert c.is_approved is False

    def test_finished_comment(self):
        c = Comment.model_validate(
            {
                "id": 102,
                "text": "It's done.",
                "action": "finished",
                "create_date": "2017-08-18T10:02:23Z",
                "author": {"id": 1731, "first_name": "Bob", "last_name": "Smith"},
            }
        )
        assert c.is_finished is True
        assert c.action == TaskAction.finished

    def test_comment_with_field_updates(self):
        c = Comment.model_validate(
            {
                "id": 103,
                "field_updates": [
                    {"id": 1, "type": "text", "name": "Status", "value": "Closed"},
                    {"id": 2, "type": "money", "name": "Amount", "value": 5000},
                ],
            }
        )
        assert c.field_updates is not None
        assert len(c.field_updates) == 2
        assert c.field_updates[0].name == "Status"

    def test_comment_with_channel(self):
        c = Comment.model_validate(
            {
                "id": 104,
                "text": "Email reply",
                "channel": {
                    "type": "email",
                    "to": {"email": "client@example.com", "name": "Client"},
                    "from": {"email": "bot@pyrus.com"},
                },
            }
        )
        assert c.channel is not None
        assert c.channel.type == ChannelType.email

    def test_comment_with_spent_minutes(self):
        c = Comment(id=105, spent_minutes=90, text="Worked 1.5 hours")
        assert c.spent_minutes == 90

    def test_comment_with_mentions(self):
        c = Comment(id=106, text="Hey @Ivan", mentions=[100500, 100501])
        assert c.mentions == [100500, 100501]

    def test_comment_with_attachments(self):
        c = Comment.model_validate(
            {
                "id": 107,
                "attachments": [
                    {"id": 555, "name": "report.xlsx", "size": 2048000, "md5": "abc123"},
                ],
            }
        )
        assert c.attachments is not None
        assert len(c.attachments) == 1
        assert c.attachments[0].name == "report.xlsx"

    def test_comment_with_list_changes(self):
        c = Comment(id=108, added_list_ids=[1, 2], removed_list_ids=[3])
        assert c.added_list_ids == [1, 2]
        assert c.removed_list_ids == [3]


class TestEdgeCaseApprovalWorkflow:
    """Multi-step approval workflows."""

    def test_multi_step_approval(self):
        """Task with 3 approval steps — mixed statuses."""
        task = Task.model_validate(
            {
                "id": 42,
                "approvals": [
                    # Step 1: approved by both
                    [
                        {"person": {"id": 1, "first_name": "A"}, "approval_choice": "approved"},
                        {"person": {"id": 2, "first_name": "B"}, "approval_choice": "approved"},
                    ],
                    # Step 2: one approved, one rejected
                    [
                        {"person": {"id": 3, "first_name": "C"}, "approval_choice": "approved"},
                        {"person": {"id": 4, "first_name": "D"}, "approval_choice": "rejected"},
                    ],
                    # Step 3: still waiting
                    [
                        {"person": {"id": 5, "first_name": "E"}, "approval_choice": "waiting"},
                    ],
                ],
            }
        )
        assert task.approvals is not None
        assert len(task.approvals) == 3
        assert task.approvals[0][0].is_approved is True
        assert task.approvals[1][1].is_rejected is True
        assert task.approvals[2][0].is_waiting is True

    def test_acknowledged_approval(self):
        entry = ApprovalEntry(
            person=Person(id=1, first_name="\u0414\u0430\u043d\u0438\u043b"),
            approval_choice=ApprovalChoice.acknowledged,
        )
        assert entry.is_waiting is False
        assert entry.is_approved is False
        assert entry.is_rejected is False

    def test_revoked_approval(self):
        entry = ApprovalEntry(
            person=Person(id=1),
            approval_choice=ApprovalChoice.revoked,
        )
        assert entry.is_waiting is False
        assert entry.is_approved is False


class TestEdgeCaseCatalogs:
    """Catalog edge cases."""

    def test_empty_catalog(self):
        cat = Catalog(catalog_id=1, name="Empty")
        assert cat.items == []
        assert cat.find_item("anything") is None

    def test_catalog_with_deleted_items(self):
        cat = Catalog(
            catalog_id=1,
            name="Cities",
            items=[
                CatalogItem(item_id=1, values=["Moscow", "MSK"]),
                CatalogItem(item_id=2, values=["London", "LDN"], deleted=True),
            ],
        )
        assert cat.items[1].deleted is True
        # find_item still finds deleted items (it's a local search)
        assert cat.find_item("London") is not None

    def test_catalog_sync_result(self):
        result = CatalogSyncResult.model_validate(
            {
                "catalog_id": 999,
                "applied": True,
                "added": [{"item_id": 15205, "values": ["Jean Overturf", "Demo Company"]}],
                "deleted": [{"item_id": 15202, "values": ["Andy Mahn", "123 Warehousing"]}],
                "updated": [{"item_id": 15200, "values": ["Reatha Middendorf", "Acme"]}],
            }
        )
        assert result.applied is True
        assert len(result.added) == 1
        assert len(result.deleted) == 1
        assert len(result.updated) == 1

    def test_catalog_single_value(self):
        """Catalog with single-column items."""
        cat = Catalog(
            catalog_id=1,
            name="Statuses",
            items=[
                CatalogItem(item_id=1, values=["Open"]),
                CatalogItem(item_id=2, values=["Closed"]),
            ],
        )
        found = cat.find_item("Open")
        assert found is not None
        assert found.item_id == 1


class TestEdgeCaseForm:
    """Form model with nested fields in info."""

    def test_form_with_table_columns(self):
        """Form definition with table field containing column definitions in info."""
        form = Form.model_validate(
            {
                "id": 36120,
                "name": "Payments",
                "steps": {"1": "Draft", "2": "Manager approval", "3": "Accounting"},
                "fields": [
                    {"id": 1, "type": "text", "name": "Purpose"},
                    {"id": 2, "type": "money", "name": "Amount"},
                    {
                        "id": 3,
                        "type": "catalog",
                        "name": "Payment type",
                        "info": {"catalog_id": 277},
                    },
                    {
                        "id": 4,
                        "type": "table",
                        "name": "Payment Schedule",
                        "info": {
                            "columns": [
                                {"id": 5, "type": "date", "name": "Date", "parent_id": 4},
                                {"id": 6, "type": "money", "name": "Amount", "parent_id": 4},
                            ]
                        },
                    },
                ],
                "print_forms": [{"print_form_id": 1, "print_form_name": "Invoice"}],
            }
        )
        assert form.name == "Payments"
        assert form.steps == {"1": "Draft", "2": "Manager approval", "3": "Accounting"}
        assert len(form.fields) == 4
        assert len(form.print_forms) == 1
        assert form.print_forms[0].print_form_name == "Invoice"

        # get_field doesn't search info.columns (table column definitions) — by design
        # Table columns are in info["columns"], but get_field only searches info["fields"]
        assert form.get_field(5) is None
        # But top-level and nested title/info fields are found:
        purpose = form.get_field(1)
        assert purpose is not None
        assert purpose.name == "Purpose"

    def test_form_with_deeply_nested_titles(self):
        """Title inside title inside title."""
        form = Form.model_validate(
            {
                "id": 1,
                "name": "Deep",
                "fields": [
                    {
                        "id": 100,
                        "type": "title",
                        "name": "L1",
                        "info": {
                            "fields": [
                                {
                                    "id": 200,
                                    "type": "title",
                                    "name": "L2",
                                    "info": {
                                        "fields": [
                                            {
                                                "id": 300,
                                                "type": "title",
                                                "name": "L3",
                                                "info": {
                                                    "fields": [
                                                        {
                                                            "id": 400,
                                                            "type": "text",
                                                            "name": "Deep Field",
                                                        },
                                                    ]
                                                },
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        )
        deep = form.get_field(400)
        assert deep is not None
        assert deep.name == "Deep Field"


class TestEdgeCaseWebhookPayload:
    """Webhook payloads with various event types and task data."""

    def test_task_created_event(self):
        payload = WebhookPayload(
            event="task_created",
            access_token="secret-token",
            task_id=42,
            user_id=100500,
            task=Task(id=42, form_id=321),
        )
        assert payload.is_task_created is True
        assert payload.is_comment is False

    def test_comment_event(self):
        payload = WebhookPayload(
            event="comment",
            task_id=42,
            task=Task(id=42),
        )
        assert payload.is_comment is True
        assert payload.is_task_created is False

    def test_task_received_with_rich_task(self):
        """Webhook with full task data including fields and approvals."""
        payload = WebhookPayload.model_validate(
            {
                "event": "task_received",
                "access_token": "tok",
                "task_id": 11613,
                "task": REAL_TASK_JSON,
            }
        )
        assert payload.task.id == 11613
        assert payload.task.form_id == 1345
        assert len(payload.task.fields) == 2


class TestBotResponseEdgeCases:
    """BotResponse for various actions."""

    def test_full_response(self):
        resp = BotResponse(
            text="Approved and reassigned",
            approval_choice="approved",
            reassign_to={"id": 100500},
            field_updates=[{"id": 1, "value": "Done"}],
            spent_minutes=30,
            due_date="2026-03-01",
        )
        d = resp.model_dump_clean()
        assert d["approval_choice"] == "approved"
        assert d["reassign_to"] == {"id": 100500}
        assert d["spent_minutes"] == 30

    def test_response_with_participant_changes(self):
        resp = BotResponse(
            participants_added=[{"id": 1}],
            participants_removed=[{"id": 2}],
            approvals_added=[[{"id": 3}]],
            approvals_removed=[{"id": 4}],
        )
        d = resp.model_dump_clean()
        assert d["participants_added"] == [{"id": 1}]
        assert d["approvals_removed"] == [{"id": 4}]


# ══════════════════════════════════════════════════════════════
# 4. Utilities with realistic data
# ══════════════════════════════════════════════════════════════


class TestGetFlatFieldsRealistic:
    """get_flat_fields with real nested structures."""

    def test_flat_fields_with_title_sections(self):
        """Title → nested fields → flatten to leaf fields."""
        fields = [
            FormField(
                id=1,
                type=FieldType.title,
                name="Section A",
                value={
                    "checkmark": "checked",
                    "fields": [
                        {"id": 2, "type": "text", "name": "Field A1", "value": "Hello"},
                        {"id": 3, "type": "money", "name": "Field A2", "value": 100.50},
                    ],
                },
            ),
            FormField(id=4, type=FieldType.text, name="Top Level", value="Direct"),
        ]
        flat = get_flat_fields(fields)
        assert len(flat) == 3
        names = [f.name for f in flat]
        assert "Field A1" in names
        assert "Field A2" in names
        assert "Top Level" in names

    def test_flat_fields_with_table(self):
        """Table → rows → cells → flatten."""
        fields = [
            FormField(
                id=5,
                type=FieldType.table,
                name="Payment Schedule",
                value=[
                    {
                        "row_id": 0,
                        "cells": [
                            {"id": 6, "type": "date", "name": "Date", "value": "2017-08-26"},
                            {"id": 7, "type": "money", "name": "Amount", "value": 10000},
                        ],
                    },
                    {
                        "row_id": 1,
                        "cells": [
                            {"id": 6, "type": "date", "name": "Date", "value": "2017-08-27"},
                            {"id": 7, "type": "money", "name": "Amount", "value": 306.25},
                        ],
                    },
                ],
            ),
        ]
        flat = get_flat_fields(fields)
        assert len(flat) == 4  # 2 rows x 2 cells
        values = [f.value for f in flat]
        assert "2017-08-26" in values
        assert 10000 in values

    def test_flat_fields_empty_title(self):
        """Title with no sub-fields — stays in the list."""
        fields = [
            FormField(id=1, type=FieldType.title, name="Empty Section", value=None),
        ]
        flat = get_flat_fields(fields)
        assert len(flat) == 1
        assert flat[0].name == "Empty Section"

    def test_flat_fields_mixed(self):
        """Mix of title, table, and plain fields."""
        fields = [
            FormField(id=1, type=FieldType.text, name="Name", value="Test"),
            FormField(
                id=2,
                type=FieldType.title,
                name="Details",
                value={
                    "fields": [
                        {"id": 3, "type": "email", "name": "Email", "value": "a@b.com"},
                    ]
                },
            ),
            FormField(
                id=4,
                type=FieldType.table,
                name="Items",
                value=[
                    {
                        "row_id": 0,
                        "cells": [{"id": 5, "type": "text", "name": "Item", "value": "Pen"}],
                    }
                ],
            ),
        ]
        flat = get_flat_fields(fields)
        assert len(flat) == 3
        names = [f.name for f in flat]
        assert "Name" in names
        assert "Email" in names
        assert "Item" in names

    def test_flat_fields_empty_list(self):
        assert get_flat_fields([]) == []


class TestFormatMentionRealistic:
    def test_mention_russian(self):
        html = format_mention(
            100500,
            header="\u0414\u0430\u043d\u0438\u043b \u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
        )
        assert 'data-personid="100500"' in html
        assert (
            "\u0414\u0430\u043d\u0438\u043b \u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e"
            in html
        )

    def test_mention_with_text(self):
        html = format_mention(1733, header="John Snow", text="please review")
        assert "John Snow" in html
        assert "please review" in html
        assert html.endswith("please review")

    def test_mention_empty_header(self):
        html = format_mention(42)
        assert 'data-personid="42"' in html


class TestSelectFieldsRealistic:
    def test_select_from_tasks(self):
        tasks = [
            Task(id=1, form_id=321, current_step=2, text="A"),
            Task(id=2, form_id=322, current_step=3, text="B"),
        ]
        slim = select_fields(tasks, {"id", "form_id"})
        assert len(slim) == 2
        assert slim[0] == {"id": 1, "form_id": 321}
        assert slim[1] == {"id": 2, "form_id": 322}
        assert "text" not in slim[0]
        assert "current_step" not in slim[0]

    def test_select_nonexistent_field(self):
        """Requesting a field that doesn't exist — just omitted."""
        tasks = [Task(id=1)]
        slim = select_fields(tasks, {"id", "nonexistent_field"})
        assert slim[0] == {"id": 1}

    def test_select_from_persons(self):
        persons = [
            Person(
                id=1,
                first_name="\u0418\u0432\u0430\u043d",
                last_name="\u0418\u0432\u0430\u043d\u043e\u0432",
                email="ivan@test.com",
            ),
            Person(
                id=2,
                first_name="\u041f\u0451\u0442\u0440",
                last_name="\u041f\u0435\u0442\u0440\u043e\u0432",
            ),
        ]
        slim = select_fields(persons, {"id", "email"})
        assert slim[0]["email"] == "ivan@test.com"
        assert slim[1]["email"] is None


class TestFieldUpdateRealistic:
    """FieldUpdate with realistic Pyrus field data."""

    def test_from_field_money_as_string(self):
        """Money field → from_field converts to string."""
        f = FormField(id=2, type=FieldType.money, name="Amount")
        result = FieldUpdate.from_field(f, 10306.25)
        assert result == {"id": 2, "value": "10306.25"}

    def test_from_field_date(self):
        f = FormField(id=4, type=FieldType.date, name="Start Date")
        result = FieldUpdate.from_field(f, "2026-03-01")
        assert result == {"id": 4, "value": "2026-03-01"}

    def test_from_field_checkmark_russian(self):
        """Russian 'da' should map to checked."""
        f = FormField(id=8, type=FieldType.checkmark, name="Confirmed")
        result = FieldUpdate.from_field(f, "\u0434\u0430")
        assert result == {"id": 8, "value": "checked"}

    def test_from_field_multiple_choice_list(self):
        """Multiple selection — list of choice_ids."""
        f = FormField(id=16, type=FieldType.multiple_choice, name="Tags")
        result = FieldUpdate.from_field(f, [1, 2, 3])
        assert result == {"id": 16, "value": {"choice_ids": [1, 2, 3]}}


# ══════════════════════════════════════════════════════════════
# 5. Client methods with realistic API responses
# ══════════════════════════════════════════════════════════════

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"
FILES_BASE = "https://files.pyrus.com/"


def _mock_auth(token: str = "test-token") -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": token,
                "api_url": API_BASE,
                "files_url": FILES_BASE,
            },
        )
    )


@pytest.fixture
def client():
    return UserClient(login="test@example.com", security_key="SECRET")


class TestClientWithRealData:
    """Client methods returning realistic Pyrus responses."""

    @respx.mock
    async def test_get_task_rich_response(self, client):
        """Parse full task response from docs."""
        _mock_auth()
        respx.get(f"{API_BASE}tasks/11613").mock(
            return_value=httpx.Response(200, json={"task": REAL_TASK_JSON})
        )
        await client.auth()
        task = await client.get_task(11613)
        assert task.id == 11613
        assert task.form_id == 1345
        assert task.author is not None
        assert task.author.full_name == "Bob Smith"
        assert len(task.fields) == 2
        purpose = task.get_field("Purpose")
        assert purpose is not None
        assert purpose.value == "IT conference in Amsterdam"
        amount = task.get_field("Amount")
        assert amount is not None
        assert amount.value == 10306.25
        assert task.approvals is not None
        assert len(task.approvals) == 1
        assert task.approvals[0][0].is_waiting is True
        await client.close()

    @respx.mock
    async def test_get_contacts_russian(self, client):
        """Parse contacts with Russian names."""
        _mock_auth()
        respx.get(f"{API_BASE}contacts").mock(
            return_value=httpx.Response(200, json=REAL_CONTACTS_JSON)
        )
        await client.auth()
        contacts = await client.get_contacts()
        org = contacts.organizations[0]
        assert org.name == "My Organization"
        assert org.persons[0].first_name == "\u0418\u0432\u0430\u043d"
        assert org.persons[0].department_name == "Marketing"
        assert len(org.roles) == 1
        assert org.roles[0].member_ids == [1725, 1733]
        await client.close()

    @respx.mock
    async def test_get_catalog_real(self, client):
        """Parse catalog from docs."""
        _mock_auth()
        respx.get(f"{API_BASE}catalogs/6625").mock(
            return_value=httpx.Response(200, json=REAL_CATALOG_JSON)
        )
        await client.auth()
        cat = await client.get_catalog(6625)
        assert cat.name == "Clients"
        assert len(cat.items) == 3
        # find_item searches first column only
        item = cat.find_item("Reatha Middendorf")
        assert item is not None
        assert item.item_id == 15200
        await client.close()

    @respx.mock
    async def test_get_announcement_real(self, client):
        """Parse announcement from docs."""
        _mock_auth()
        respx.get(f"{API_BASE}announcements/14786").mock(
            return_value=httpx.Response(200, json={"announcement": REAL_ANNOUNCEMENT_JSON})
        )
        await client.auth()
        ann = await client.get_announcement(14786)
        assert ann.text == "New announcement"
        assert len(ann.comments) == 1
        assert ann.comments[0].text == "Comment"
        await client.close()

    @respx.mock
    async def test_get_lists_real(self, client):
        """Parse lists hierarchy from docs."""
        _mock_auth()
        respx.get(f"{API_BASE}lists").mock(return_value=httpx.Response(200, json=REAL_LISTS_JSON))
        await client.auth()
        lists = await client.get_lists()
        assert len(lists) == 2
        assert lists[0].name == "Branch offices"
        assert lists[0].children[0].name == "Moscow"
        assert lists[1].children == []
        await client.close()

    @respx.mock
    async def test_get_register_with_pagination(self, client):
        """Register response with has_more and total_count."""
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tasks": [
                        {
                            "id": 1,
                            "current_step": 2,
                            "fields": [{"id": 1, "type": "text", "name": "Name", "value": "A"}],
                        },
                        {
                            "id": 2,
                            "current_step": 3,
                            "fields": [{"id": 1, "type": "text", "name": "Name", "value": "B"}],
                        },
                    ],
                    "has_more": True,
                },
            )
        )
        await client.auth()
        tasks = await client.get_register(321)
        assert len(tasks) == 2
        assert tasks[0].get_field("Name").value == "A"
        await client.close()

    @respx.mock
    async def test_get_inbox_empty(self, client):
        """Empty inbox."""
        _mock_auth()
        respx.get(f"{API_BASE}inbox").mock(return_value=httpx.Response(200, json={"tasks": []}))
        await client.auth()
        tasks = await client.get_inbox()
        assert tasks == []
        await client.close()

    @respx.mock
    async def test_get_members_russian_with_departments(self, client):
        """Members with Russian names and department info."""
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {
                            "id": 123456,
                            "first_name": "\u0418\u0432\u0430\u043d",
                            "last_name": "\u0418\u0432\u0430\u043d\u043e\u0432",
                            "email": "ivan.ivanov@company.com",
                            "type": "user",
                            "status": "\U0001f637\u0417\u0430\u0431\u043e\u043b\u0435\u043b",
                            "banned": False,
                            "position": "developer",
                            "mobile_phone": "79091234567",
                            "phone": "71234567890",
                        },
                        {
                            "id": 789012,
                            "first_name": "\u0414\u0430\u043d\u0438\u043b",
                            "last_name": "\u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
                            "email": "danil@company.com",
                            "type": "user",
                            "position": "lead",
                        },
                    ]
                },
            )
        )
        await client.auth()
        members = await client.get_members()
        assert len(members) == 2
        assert members[0].first_name == "\u0418\u0432\u0430\u043d"
        assert members[0].position == "developer"
        assert (
            members[1].full_name
            == "\u0414\u0430\u043d\u0438\u043b \u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e"
        )
        await client.close()

    @respx.mock
    async def test_batch_get_tasks_all_fail(self, client):
        """All tasks in batch fail — returns empty list."""
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(404, json={"error": "not found", "error_code": "not_found"})
        )
        respx.get(f"{API_BASE}tasks/2").mock(
            return_value=httpx.Response(
                403, json={"error": "forbidden", "error_code": "access_denied"}
            )
        )
        await client.auth()
        tasks = await client.get_tasks([1, 2])
        assert tasks == []
        await client.close()

    @respx.mock
    async def test_batch_get_tasks_single_item(self, client):
        """Batch with single task — should work."""
        _mock_auth()
        respx.get(f"{API_BASE}tasks/11613").mock(
            return_value=httpx.Response(200, json={"task": REAL_TASK_JSON})
        )
        await client.auth()
        tasks = await client.get_tasks([11613])
        assert len(tasks) == 1
        assert tasks[0].author is not None
        assert tasks[0].author.full_name == "Bob Smith"
        await client.close()

    @respx.mock
    async def test_batch_get_tasks_empty_list(self, client):
        """Batch with empty list — should return empty."""
        _mock_auth()
        await client.auth()
        tasks = await client.get_tasks([])
        assert tasks == []
        await client.close()


class TestChannelTypes:
    """All channel types parse correctly."""

    @pytest.mark.parametrize(
        "channel_type",
        ["email", "telegram", "sms", "facebook", "vk", "viber", "mobile_app", "web_widget"],
    )
    def test_channel_type_enum(self, channel_type):
        ct = ChannelType(channel_type)
        assert ct.value == channel_type

    def test_channel_with_contacts(self):
        ch = Channel.model_validate(
            {
                "type": "email",
                "to": {"email": "client@example.com", "name": "Client Name"},
                "from": {"email": "support@pyrus.com"},
            }
        )
        assert ch.type == ChannelType.email
        assert ch.to is not None
        assert ch.to.email == "client@example.com"
        assert ch.to.name == "Client Name"
        assert ch.from_ is not None
        assert ch.from_.email == "support@pyrus.com"


class TestRegisterResponse:
    """RegisterResponse model."""

    def test_with_pagination(self):
        resp = RegisterResponse.model_validate(
            {
                "tasks": [{"id": 1}, {"id": 2}],
                "has_more": True,
                "total_count": 150,
            }
        )
        assert len(resp.tasks) == 2
        assert resp.has_more is True
        assert resp.total_count == 150

    def test_empty(self):
        resp = RegisterResponse.model_validate({"tasks": []})
        assert resp.tasks == []
        assert resp.has_more is None


class TestTaskListDeepNesting:
    """TaskList with deep nesting and colors."""

    def test_three_level_nesting(self):
        data = {
            "id": 1,
            "name": "Root",
            "color": "#4CAF50",
            "children": [
                {
                    "id": 2,
                    "name": "Level 1",
                    "children": [
                        {
                            "id": 3,
                            "name": "Level 2",
                            "children": [{"id": 4, "name": "Level 3"}],
                        }
                    ],
                }
            ],
        }
        tl = TaskList.model_validate(data)
        assert tl.color == "#4CAF50"
        assert tl.children[0].children[0].children[0].name == "Level 3"

    def test_list_with_color(self):
        """Lists from POST /lists/{id} response with color."""
        tl = TaskList.model_validate(
            {
                "id": 43082,
                "name": "api spisok",
                "color": "#4CAF50",
            }
        )
        assert tl.color == "#4CAF50"
        assert tl.name == "api spisok"


class TestSubscriberEntry:
    """SubscriberEntry with approval_choice."""

    def test_subscriber_with_approval(self):
        entry = SubscriberEntry.model_validate(
            {
                "person": {
                    "id": 100500,
                    "first_name": "\u0414\u0430\u043d\u0438\u043b",
                    "last_name": "\u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
                },
                "approval_choice": "approved",
            }
        )
        assert entry.person.id == 100500
        assert entry.approval_choice == ApprovalChoice.approved

    def test_subscriber_minimal(self):
        entry = SubscriberEntry.model_validate({"person": {"id": 1, "first_name": "A"}})
        assert entry.person.id == 1
        assert entry.approval_choice is None


class TestProfileModel:
    """Profile model."""

    def test_profile_with_org(self):
        profile = Profile.model_validate(
            {
                "person_id": 100500,
                "first_name": "\u0414\u0430\u043d\u0438\u043b",
                "last_name": "\u041a\u043e\u043b\u0431\u0430\u0441\u0435\u043d\u043a\u043e",
                "email": "danil@company.com",
                "locale": "ru",
                "timezone_offset": 180,
                "organization_id": 2181,
            }
        )
        assert profile.person_id == 100500
        assert profile.locale == "ru"
        assert profile.timezone_offset == 180


class TestExtraFieldsIgnored:
    """Pydantic models with extra="ignore" — unknown fields don't break parsing."""

    def test_person_with_unknown_fields(self):
        """Real API may return fields not in our model (location, personality, etc.)."""
        p = Person.model_validate(
            {
                "id": 123,
                "first_name": "\u0418\u0432\u0430\u043d",
                "last_name": "\u041a\u043e\u0442\u043e\u0432",
                "location": "\u041c\u043e\u0441\u043a\u0432\u0430, UTC+3",
                "personality": "\u041b\u044e\u0431\u043b\u044e \u043f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432\u043e\u0432\u0430\u0442\u044c",
                "personnel_number": "0000-000001",
                "vacation_days": "2",
                "web_session_settings": {"life_span_hours": 8760},
                "rights": 0,
            }
        )
        assert p.id == 123
        assert p.first_name == "\u0418\u0432\u0430\u043d"

    def test_task_with_unknown_fields(self):
        """Task with extra fields from newer API version."""
        t = Task.model_validate(
            {
                "id": 42,
                "text": "Test",
                "some_new_field": "value",
                "another_unknown": 123,
            }
        )
        assert t.id == 42

    def test_catalog_with_extra_fields(self):
        """Catalog from GET /catalogs includes supervisors, external_version."""
        cat_list_item = {
            "catalog_id": 31816,
            "name": "Catalog1",
            "version": 151199,
            "deleted": False,
            "supervisors": [1731],
            "external_version": 0,
        }
        cat = Catalog.model_validate(cat_list_item)
        assert cat.catalog_id == 31816
        assert cat.version == 151199
        assert cat.deleted is False
