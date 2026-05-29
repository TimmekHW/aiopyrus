"""Telephony API — модели интеграции с телефонией / колл-центром.

Pyrus поддерживает регистрацию звонков и прикрепление аудио-записей
к задачам через ``POST /integrations/call`` и
``POST /integrations/attachcallrecord``.

Use case: интеграции Zadarma, asterisk-ботов, корпоративных АТС.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import field_serializer, field_validator

from .base import PyrusModel


class TelephonyMappingCode(str, Enum):
    """Известные коды CallMapping — на какое поле формы маппится значение."""

    call_start_time = "CallStartTime"
    call_end_time = "CallEndTime"
    call_duration = "CallDuration"
    phone_number_from = "PhoneNumberFrom"
    phone_number_to = "PhoneNumberTo"
    rating = "Rating"
    rating_comment = "RatingComment"
    rating_date = "RatingDate"


class CallMapping(PyrusModel):
    """Один маппинг ``code → value`` для регистрируемого звонка.

    Значения сериализуются как JSON-скаляры: строки/числа как есть,
    datetime — в ISO 8601 ``YYYY-MM-DDTHH:MM:SSZ``.
    """

    code: TelephonyMappingCode | str
    value: str | int | float | datetime

    @field_serializer("value")
    def _ser_value(self, v: Any) -> Any:
        if isinstance(v, datetime):
            tz_aware = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            return tz_aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return v


class TelephonyPersonRef(PyrusModel):
    """Ссылка на сотрудника-ответственного в ответе телефонии.

    Pyrus возвращает ``user_id`` как строку (``"34231"``) — валидатор
    приводит к ``int``.
    """

    user_id: int
    first_name: str = ""
    last_name: str = ""
    work_phone: str | None = None

    @field_validator("user_id", mode="before")
    @classmethod
    def _coerce_user_id(cls, v: object) -> int:
        if isinstance(v, str) and v:
            return int(v)
        return int(v)  # type: ignore[arg-type]


class RegisterCallResponse(PyrusModel):
    """Ответ на ``POST /integrations/call``.

    Возвращает ID созданной/найденной задачи (если форма звонков
    настроена), флаг новой задачи и ответственного. Может содержать
    ``error_code`` + ``error`` при логической ошибке (например,
    если в аккаунте не задан ``account_id``).
    """

    task_id: int | None = None
    is_new_task: bool | None = None
    responsible_person: TelephonyPersonRef | None = None
    error_code: str | None = None
    error: str | None = None


class AttachCallRecordResponse(PyrusModel):
    """Ответ на ``POST /integrations/attachcallrecord``.

    На успех — пустой объект. На логическую ошибку — ``error_code`` + ``error``.
    """

    error_code: str | None = None
    error: str | None = None


# ── Meeting (для /calendar в 2026 — отдельный массив рядом с tasks) ──


class MeetingJoinParameters(PyrusModel):
    """Параметры подключения к онлайн-встрече."""

    url: str | None = None
    external_id: str | None = None
    password: str | None = None


class Meeting(PyrusModel):
    """Календарная встреча из ответа ``GET /calendar``.

    В 2026 Pyrus стал возвращать встречи отдельным массивом
    ``meetings`` рядом с ``tasks`` — встречи теперь отделены от
    задач с deadline.
    """

    id: int
    type: str = ""  # "offline" / "online" / ...
    start_time: datetime | None = None
    duration: int | None = None  # минуты
    join_parameters: MeetingJoinParameters | None = None
    creator_id: int | None = None
    task_id: int | None = None
    shared_calendar_event_id: str | None = None
    shared_to_email: bool | None = None


class CalendarResponse(PyrusModel):
    """Ответ ``GET /calendar`` в новом формате 2026.

    Old shape: ``{tasks: [...]}``. New shape:
    ``{has_more, tasks: [...], meetings: [...]}``.
    """

    has_more: bool = False
    tasks: list[Any] = []  # list[Task] — но Task в другом модуле, чтобы избежать circular import
    meetings: list[Meeting] | None = None
