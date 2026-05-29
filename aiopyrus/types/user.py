from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import field_validator

from .base import PyrusModel


class PersonType(str, Enum):
    person = "person"
    user = "user"  # corp instance который живёт по своим правилам
    role = "role"
    bot = "bot"


class Messenger(PyrusModel):
    """Messenger contact embedded in a Person record.

    Контакт мессенджера, встроенный в карточку сотрудника. Возвращается
    Pyrus как ``{"type": "...", "nickname": "..."}``.  Это узкая типизация
    того, что раньше было ``dict[str, Any]`` — IDE-автокомплит, при этом
    ``extra="ignore"`` (на ``PyrusModel``) сохраняет forward-compat
    для будущих ключей.
    """

    type: str | None = None
    nickname: str | None = None


class SessionPolicy(PyrusModel):
    """Admin session-policy block returned on every ``Person`` on corp/on-premise.

    Политика админ-сессий, прикреплённая к карточке сотрудника на корп /
    on-premise. На облаке отсутствует.  Все шесть полей ``Person`` —
    ``mobile_session_settings``, ``mobile_session_inactive_settings``,
    ``mobile_session_restriction_settings``, ``web_session_settings``,
    ``web_session_inactive_settings``, ``web_session_restriction_settings``
    — используют этот класс.

    Поля свободны (``str | int | None``) — серверная схема разнится
    между инстансами и со временем; ``extra="ignore"`` сохраняет
    forward-compat.
    """

    life_span_hours: int | None = None
    max_count: int | None = None


class Person(PyrusModel):
    """Represents a Pyrus user, role, or bot."""

    id: int
    first_name: str = ""
    last_name: str = ""
    # Name in the user's native language (e.g. Japanese / Chinese)
    native_first_name: str | None = None
    native_last_name: str | None = None
    email: str | None = None
    type: PersonType | None = PersonType.person
    department_id: int | None = None
    department_name: str | None = None
    position: str | None = None
    # Phones
    phone: str | None = None  # office phone
    mobile_phone: str | None = None
    # Status
    status: str | None = None
    locale: str | None = None
    # Employment / account state
    fired: bool | None = False  # terminated employee
    banned: bool | None = False  # account blocked by admin
    # Task delegation: tasks assigned to this person go to task_receiver instead
    task_receiver: int | None = None
    # External ID (corp / on-premise instances — maps to AD, 1C, etc.)
    external_id: int | None = None
    # Organisation ID (typically populated on synthetic system users in
    # comment.author and on corp instances; mirrors Profile.organization_id)
    organization_id: int | None = None
    # Avatar
    avatar_id: int | None = None
    external_avatar_id: int | None = None
    # Location / messenger
    location: str | None = None  # physical city / office (e.g. "Владивосток")
    skype: str | None = None
    messenger: Messenger | None = None
    # Date of birth — Pyrus returns ``{"day": int, "month": int}`` (year
    # optional on cloud).  Kept as loose ``dict[str, Any]`` to match the
    # house style for opaque sub-objects.
    birth_date: dict[str, Any] | None = None
    # ── Admin session policy (corp / on-premise only, omitted on cloud) ──
    mobile_session_settings: SessionPolicy | None = None
    mobile_session_inactive_settings: SessionPolicy | None = None
    mobile_session_restriction_settings: SessionPolicy | None = None
    web_session_settings: SessionPolicy | None = None
    web_session_inactive_settings: SessionPolicy | None = None
    web_session_restriction_settings: SessionPolicy | None = None

    @field_validator("external_id", mode="before")
    @classmethod
    def _coerce_external_id(cls, v: object) -> int | None:
        """Pyrus API returns external_id as empty string when unset."""
        if v is None or v == "":
            return None
        return int(v)  # type: ignore[arg-type]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:
        return f"<Person id={self.id} name={self.full_name!r}>"


class Role(PyrusModel):
    """Represents a Pyrus role (group of people).

    Note:
        ``fired`` and ``banned`` are populated only on Pyrus **cloud**.
        On-premise / corp instances omit these keys from the role payload,
        so the ``False`` default does **not** reflect the actual role state
        on a corp deployment — never rely on it there.
    """

    id: int
    name: str
    member_ids: list[int] = []
    fired: bool = False  # archived / deleted role (cloud only — see class docstring)
    banned: bool = False  # disabled role (cloud only — see class docstring)


class Organization(PyrusModel):
    """An organization returned in the contacts response."""

    organization_id: int | None = None
    name: str | None = None
    department_catalog_id: int | None = None
    persons: list[Person] = []
    roles: list[Role] = []


class ContactsResponse(PyrusModel):
    organizations: list[Organization] = []


class Profile(PyrusModel):
    """Current user profile (GET /profile)."""

    person_id: int
    first_name: str = ""
    last_name: str = ""
    email: str | None = None
    locale: str | None = None
    timezone_offset: int | None = None  # minutes offset from UTC (e.g. 180 = UTC+3)
    organization_id: int | None = None
    organization: Organization | None = None
