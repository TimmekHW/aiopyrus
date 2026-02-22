"""Shared fixtures for aiopyrus test suite."""

from __future__ import annotations

from typing import Any

import pytest

from aiopyrus.types.form import FieldType, FormField
from aiopyrus.types.task import Task
from aiopyrus.types.user import Person
from aiopyrus.types.webhook import WebhookPayload


def make_task(**overrides: Any) -> Task:
    """Build a Task with sensible defaults, overridable by kwargs."""
    defaults: dict[str, Any] = dict(
        id=12345678,
        text="Test task",
        form_id=321,
        current_step=2,
        fields=[],
    )
    defaults.update(overrides)
    return Task(**defaults)


def make_payload(**task_overrides: Any) -> WebhookPayload:
    """Build a WebhookPayload wrapping a default task."""
    task = make_task(**task_overrides)
    return WebhookPayload(
        event="task_received",
        access_token="test-token",
        task_id=task.id,
        task=task,
    )


def make_field(
    id: int = 1,
    name: str = "Field",
    type: str = "text",
    value: Any = None,
    **extra: Any,
) -> FormField:
    """Build a FormField with given params."""
    return FormField(id=id, name=name, type=FieldType(type), value=value, **extra)


def make_person(id: int = 100500, first_name: str = "Ivan", last_name: str = "Ivanov") -> Person:
    return Person(id=id, first_name=first_name, last_name=last_name)


# Re-export for convenience
@pytest.fixture
def payload():
    return make_payload()


@pytest.fixture
def task():
    return make_task()
