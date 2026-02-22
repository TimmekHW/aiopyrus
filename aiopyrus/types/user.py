from __future__ import annotations

from enum import Enum
from typing import Optional

from .base import PyrusModel


class PersonType(str, Enum):
    person = "person"
    user = "user"       # corp instance который живёт по своим правилам
    role = "role"
    bot = "bot"


class Person(PyrusModel):
    """Represents a Pyrus user, role, or bot."""

    id: int
    first_name: str = ""
    last_name: str = ""
    # Name in the user's native language (e.g. Japanese / Chinese)
    native_first_name: Optional[str] = None
    native_last_name: Optional[str] = None
    email: Optional[str] = None
    type: Optional[PersonType] = PersonType.person
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    position: Optional[str] = None
    # Phones
    phone: Optional[str] = None          # office phone
    mobile_phone: Optional[str] = None
    # Status
    status: Optional[str] = None
    locale: Optional[str] = None
    # Employment / account state
    fired: Optional[bool] = False        # terminated employee
    banned: Optional[bool] = False       # account blocked by admin
    # Task delegation: tasks assigned to this person go to task_receiver instead
    task_receiver: Optional[int] = None

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
    fired: bool = False    # archived / deleted role
    banned: bool = False   # disabled role


class Organization(PyrusModel):
    """An organization returned in the contacts response."""

    organization_id: Optional[int] = None
    name: Optional[str] = None
    department_catalog_id: Optional[int] = None
    persons: list[Person] = []
    roles: list[Role] = []


class ContactsResponse(PyrusModel):
    organizations: list[Organization] = []


class Profile(PyrusModel):
    """Current user profile (GET /profile)."""

    person_id: int
    first_name: str = ""
    last_name: str = ""
    email: Optional[str] = None
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    organization_id: Optional[int] = None
    organization: Optional[Organization] = None
