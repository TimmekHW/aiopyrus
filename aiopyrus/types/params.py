"""Request-модели и тип-алиасы для клиентского API.

Typed request models and type aliases for client API.

Каждая модель зеркалит kwargs соответствующего одиночного метода клиента,
обеспечивая автокомплит и type-checking для батч-вызовов.

Example::

    from aiopyrus.types.params import NewTask, NewRole, PrintFormItem

    results = await client.create_tasks([
        NewTask(text="Simple task"),
        NewTask(form_id=321, fields=[FieldUpdate.text(1, "value")]),
    ])
"""

from __future__ import annotations

from typing import Any, TypeAlias

from pydantic import BaseModel

PersonRef: TypeAlias = int | dict[str, Any]
"""Ссылка на пользователя/роль: person_id (``int``) или полный dict ``{"id": ..., "type": ...}``.

A person/role reference: bare person_id or a full Pyrus person dict.
"""


class NewTask(BaseModel):
    """Параметры создания задачи — зеркало ``create_task()`` kwargs.

    Typed parameters for task creation — mirrors ``create_task()`` kwargs.

    Example::

        await client.create_tasks([
            NewTask(text="Простая задача"),
            NewTask(form_id=321, responsible=100500, fields=[...]),
        ])
    """

    # Simple task
    text: str | None = None
    formatted_text: str | None = None
    subject: str | None = None
    # Form task
    form_id: int | None = None
    fields: list[dict[str, Any]] | None = None
    fill_defaults: bool | None = None
    approvals: list[list[PersonRef]] | None = None
    # People
    responsible: PersonRef | None = None
    participants: list[PersonRef] | None = None
    subscribers: list[PersonRef] | None = None
    # Time
    due_date: str | None = None
    due: str | None = None
    duration: int | None = None
    scheduled_date: str | None = None
    scheduled_datetime_utc: str | None = None
    # Organisation
    parent_task_id: int | None = None
    list_ids: list[int] | None = None
    attachments: list[str] | None = None


class NewRole(BaseModel):
    """Параметры создания роли — зеркало ``create_role()`` kwargs.

    Typed parameters for role creation.

    Example::

        await client.create_roles([
            NewRole(name="Administrators", member_ids=[100500, 100501]),
            NewRole(name="Viewers"),
        ])
    """

    name: str
    member_ids: list[int] | None = None


class RoleUpdate(BaseModel):
    """Параметры обновления роли — зеркало ``update_role()`` kwargs.

    Typed parameters for role update.

    Example::

        await client.update_roles([
            RoleUpdate(role_id=42, name="Super Admins"),
            RoleUpdate(role_id=43, banned=True),
        ])
    """

    role_id: int
    name: str | None = None
    member_ids: list[int] | None = None
    banned: bool | None = None


class MemberUpdate(BaseModel):
    """Параметры обновления сотрудника — зеркало ``update_member()`` kwargs.

    Typed parameters for member update.

    Example::

        await client.update_members([
            MemberUpdate(member_id=100500, position="Lead Developer"),
            MemberUpdate(member_id=100501, status="В отпуске"),
        ])
    """

    member_id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    position: str | None = None
    phone: str | None = None
    mobile_phone: str | None = None
    status: str | None = None
    banned: bool | None = None


class PrintFormItem(BaseModel):
    """Пара (задача, печатная форма) для ``download_print_forms()``.

    A (task, print form) pair for ``download_print_forms()``.

    Example::

        await client.download_print_forms([
            PrintFormItem(task_id=12345678, print_form_id=1),
            PrintFormItem(task_id=12345679, print_form_id=2),
        ])
    """

    task_id: int
    print_form_id: int
