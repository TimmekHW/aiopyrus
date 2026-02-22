"""FieldUpdate — умный строитель payload для обновления полей формы.

Избавляет от необходимости знать формат значения для каждого типа поля.

Пример::

    from aiopyrus.utils.fields import FieldUpdate

    updates = [
        FieldUpdate.from_field(task.get_field(2460), "1020"),          # text
        FieldUpdate.from_field(task.get_field("u_status_zadachi12"), 3),  # choice_id
        FieldUpdate.from_field(task.get_field("Executor1028"), 100500),   # person_id
    ]
    await client.comment_task(task.id, field_updates=updates)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiopyrus.types.form import FormField


# Типы полей которые принимают строковое значение напрямую
_TEXT_TYPES = {"text", "email", "phone", "note", "number", "money",
               "date", "time", "due_date", "due_date_time", "step", "status",
               "creation_date"}


class FieldUpdate:
    """Статические фабрики для словарей field_updates.

    Каждый метод возвращает dict, который можно передать в
    ``client.comment_task(task_id, field_updates=[...])``.
    """

    # ------------------------------------------------------------------
    # Typed factories
    # ------------------------------------------------------------------

    @staticmethod
    def text(field_id: int, value: str | None) -> dict:
        """Текстовое поле (text, email, phone, note, number, money, date…)."""
        return {"id": field_id, "value": value}

    @staticmethod
    def choice(field_id: int, choice_id: int) -> dict:
        """Multiple-choice поле — по ID варианта."""
        return {"id": field_id, "value": {"choice_ids": [choice_id]}}

    @staticmethod
    def choices(field_id: int, choice_ids: list[int]) -> dict:
        """Multiple-choice поле — несколько вариантов сразу."""
        return {"id": field_id, "value": {"choice_ids": choice_ids}}

    @staticmethod
    def person(field_id: int, person_id: int) -> dict:
        """Person-поле — по ID пользователя/роли."""
        return {"id": field_id, "value": {"id": person_id}}

    @staticmethod
    def clear_person(field_id: int) -> dict:
        """Очистить person-поле."""
        return {"id": field_id, "value": None}

    @staticmethod
    def catalog(field_id: int, item_id: int) -> dict:
        """Catalog-поле — по ID записи в каталоге."""
        return {"id": field_id, "value": {"item_id": item_id}}

    @staticmethod
    def checkmark(field_id: int, checked: bool) -> dict:
        """Checkmark / flag поле."""
        return {"id": field_id, "value": "checked" if checked else "unchecked"}

    @staticmethod
    def clear(field_id: int) -> dict:
        """Очистить любое поле (установить value=None)."""
        return {"id": field_id, "value": None}

    # ------------------------------------------------------------------
    # Smart auto-detect factory
    # ------------------------------------------------------------------

    @staticmethod
    def from_field(field: "FormField", value: Any) -> dict:
        """Автоматически определить формат по типу поля.

        Args:
            field:  Объект поля из ``task.get_field(...)`` — нужен чтобы знать тип.
            value:  Значение в «человеческом» формате:

                    - ``text/email/phone/note/number/money/date`` →
                      строка или число, будет преобразовано в str.
                    - ``checkmark/flag`` → bool (``True`` = «checked»).
                    - ``multiple_choice`` → **int** (choice_id).
                      Чтобы узнать choice_id по названию, используй
                      ``await client.get_form_choices(form_id, field.id)``.
                    - ``person/author`` → **int** (person_id) или объект
                      ``Person``. Для поиска по имени —
                      ``await client.find_member("Ivanov")``.
                    - ``catalog`` → **int** (item_id).
                    - ``None`` → очищает поле.

        Raises:
            ValueError: если тип поля не поддерживается или передан
                        несовместимый тип значения.

        Example::

            status = task.get_field("u_status_zadachi12")   # multiple_choice
            executor = task.get_field("Executor1028")        # person
            keis = task.get_field(2460)                      # text

            updates = [
                FieldUpdate.from_field(keis, "1020"),
                FieldUpdate.from_field(status, 3),           # choice_id=3
                FieldUpdate.from_field(executor, 100500),    # person_id
            ]
        """
        if value is None:
            return FieldUpdate.clear(field.id)

        ftype = field.type.value if field.type else None

        if ftype is None or ftype in _TEXT_TYPES:
            return FieldUpdate.text(field.id, str(value))

        if ftype in ("checkmark", "flag"):
            if isinstance(value, bool):
                return FieldUpdate.checkmark(field.id, value)
            if isinstance(value, str):
                return FieldUpdate.checkmark(field.id, value.lower() in ("checked", "true", "1", "да", "yes"))
            raise ValueError(
                f"Field {field.id!r} ({field.name!r}) is a checkmark — "
                f"pass True/False or 'checked'/'unchecked', got {value!r}"
            )

        if ftype == "multiple_choice":
            if isinstance(value, int):
                return FieldUpdate.choice(field.id, value)
            if isinstance(value, list) and all(isinstance(v, int) for v in value):
                return FieldUpdate.choices(field.id, value)
            raise ValueError(
                f"Field {field.id!r} ({field.name!r}) is multiple_choice — "
                f"pass choice_id as int.\n"
                f"To look up choice_id by name use:\n"
                f"    choices = await client.get_form_choices(task.form_id, {field.id})\n"
                f"    # e.g. choices == {{'Открыта': 1, 'В работе': 2, 'Закрыта': 3}}"
            )

        if ftype in ("person", "author"):
            # Accept int (person_id), Person object, or dict with 'id'
            if isinstance(value, int):
                return FieldUpdate.person(field.id, value)
            if hasattr(value, "id"):          # Person object
                return FieldUpdate.person(field.id, value.id)
            if isinstance(value, dict) and "id" in value:
                return FieldUpdate.person(field.id, value["id"])
            raise ValueError(
                f"Field {field.id!r} ({field.name!r}) is a person field — "
                f"pass person_id as int or a Person object.\n"
                f"To find a person by name use:\n"
                f"    person = await client.find_member('Ivanov')"
            )

        if ftype == "catalog":
            if isinstance(value, int):
                return FieldUpdate.catalog(field.id, value)
            raise ValueError(
                f"Field {field.id!r} ({field.name!r}) is a catalog field — "
                f"pass item_id as int."
            )

        # Fallback for unknown / unsupported types
        raise ValueError(
            f"Field {field.id!r} ({field.name!r}) has unsupported type {ftype!r}. "
            f"Build the update dict manually."
        )
