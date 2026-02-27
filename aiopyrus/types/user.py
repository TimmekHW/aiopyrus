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
    # Avatar
    avatar_id: int | None = None
    external_avatar_id: int | None = None
    # Location / messenger
    location: str | None = None  # physical city / office (e.g. "Владивосток")
    skype: str | None = None
    messenger: dict[str, Any] | None = None  # {"type": "Internet", "nickname": "..."}

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
    """Represents a Pyrus role (group of people)."""

    id: int
    name: str
    member_ids: list[int] = []
    fired: bool = False  # archived / deleted role
    banned: bool = False  # disabled role


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
