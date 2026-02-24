from __future__ import annotations

from enum import Enum
from typing import Any

from .base import PyrusModel
from .file import Attachment
from .user import Person


class FieldType(str, Enum):
    text = "text"
    money = "money"
    number = "number"
    date = "date"
    time = "time"
    email = "email"
    phone = "phone"
    flag = "flag"
    status = "status"
    creation_date = "creation_date"
    note = "note"
    checkmark = "checkmark"
    due_date = "due_date"
    due_date_time = "due_date_time"
    catalog = "catalog"
    file = "file"
    person = "person"
    author = "author"
    table = "table"
    title = "title"  # type: ignore[reportAssignmentType]
    multiple_choice = "multiple_choice"
    form_link = "form_link"
    step = "step"
    project = "project"  # deprecated, read-only
    person_responsible = "person_responsible"
    task_approval_date = "task_approval_date"
    task_approval_user = "task_approval_user"


# ---------------------------------------------------------------------------
# Typed value models for complex fields
# ---------------------------------------------------------------------------


class CatalogFieldValue(PyrusModel):
    """Value structure for ``catalog`` fields.

    Read response contains ``headers``/``values``/``rows`` with display data.
    Write uses only ``item_id`` (single) or ``item_ids`` (multiple),
    or ``item_name`` (lookup by first-column name).
    """

    # Single selection (also present in multi as the first id for compat)
    item_id: int | None = None
    # Multi-selection
    item_ids: list[int] | None = None
    # Write by name instead of id
    item_name: str | None = None
    # Read-only display data
    headers: list[str] | None = None
    values: list[str] | None = None  # first selected row values
    rows: list[list[str]] | None = None  # all selected rows values


class MultipleChoiceValue(PyrusModel):
    """Value structure for ``multiple_choice`` fields."""

    choice_id: int | None = None  # singular selection shortcut (API compat)
    choice_ids: list[int] | None = None
    choice_names: list[str] | None = None
    fields: list[FormField] | None = None  # sub-fields tied to the choice


class TitleValue(PyrusModel):
    """Value structure for ``title`` (section header) fields."""

    checkmark: str | None = None  # "checked" | "unchecked" | None
    fields: list[FormField] | None = None


class FormLinkValue(PyrusModel):
    """Value structure for ``form_link`` fields."""

    task_ids: list[int] | None = None
    subject: str | None = None


class TableRow(PyrusModel):
    """One row inside a ``table`` field value."""

    row_id: int
    position: int | None = None
    cells: list[FormField] = []
    # Write-only: set to True to delete this row
    delete: bool | None = None


# ---------------------------------------------------------------------------
# FormField
# ---------------------------------------------------------------------------


class FormField(PyrusModel):
    """A single field in a form task (both definition and value)."""

    id: int
    type: FieldType | None = None
    name: str | None = None
    code: str | None = None

    # Raw value — type depends on ``type``:
    #   text/money/number/date/time/email/phone/note/step/status/creation_date → str | int | float
    #   checkmark/flag   → "checked" | "unchecked" | "none"
    #   due_date         → "YYYY-MM-DD"          (+ separate ``duration`` field)
    #   due_date_time    → "YYYY-MM-DDThh:mm:ssZ" (+ separate ``duration`` field)
    #   person/author    → dict (use as_person())
    #   file             → list[dict] (use as_files())
    #   catalog          → dict (use as_catalog())
    #   multiple_choice  → dict (use as_multiple_choice())
    #   title            → dict (use as_title())
    #   form_link        → dict (use as_form_link())
    #   table            → list[dict] (use as_table_rows())
    value: Any | None = None

    # Present on due_date / due_date_time fields
    duration: int | str | None = None

    # Present on cells inside a table row
    parent_id: int | None = None
    row_id: int | None = None

    # Catalog reference (from form definition)
    catalog_id: int | None = None

    # Form definition metadata (returned in GET /forms/{id})
    info: dict | None = None
    required_step: int | None = None
    immutable_step: int | None = None

    # UI hint shown on hover in the Pyrus interface
    tooltip: str | None = None

    # Default value pre-filled by Pyrus (common on multiple_choice / catalog)
    default_value: str | None = None

    # Present on address composite subfields — points to the parent composite field
    related_field_id: int | None = None

    # Conditional visibility rule (complex nested structure — kept as raw dict)
    visibility_condition: dict | None = None

    # -----------------------------------------------------------------------
    # Typed accessors
    # -----------------------------------------------------------------------

    def as_person(self) -> Person | None:
        """Interpret value as a Person (for ``person`` / ``author`` fields)."""
        if isinstance(self.value, dict):
            return Person.model_validate(self.value)
        return None

    def as_files(self) -> list[Attachment]:
        """Interpret value as a list of Attachments (for ``file`` fields)."""
        if isinstance(self.value, list):
            return [Attachment.model_validate(f) for f in self.value if isinstance(f, dict)]
        return []

    def as_catalog(self) -> CatalogFieldValue | None:
        """Interpret value as a CatalogFieldValue (for ``catalog`` fields)."""
        if isinstance(self.value, dict):
            return CatalogFieldValue.model_validate(self.value)
        return None

    def as_multiple_choice(self) -> MultipleChoiceValue | None:
        """Interpret value as a MultipleChoiceValue (for ``multiple_choice`` fields)."""
        if isinstance(self.value, dict):
            return MultipleChoiceValue.model_validate(self.value)
        return None

    def as_title(self) -> TitleValue | None:
        """Interpret value as a TitleValue (for ``title`` fields)."""
        if isinstance(self.value, dict):
            return TitleValue.model_validate(self.value)
        return None

    def as_form_link(self) -> FormLinkValue | None:
        """Interpret value as a FormLinkValue (for ``form_link`` fields)."""
        if isinstance(self.value, dict):
            return FormLinkValue.model_validate(self.value)
        return None

    def as_table_rows(self) -> list[TableRow]:
        """Interpret value as table rows (for ``table`` fields)."""
        if isinstance(self.value, list):
            return [TableRow.model_validate(r) for r in self.value if isinstance(r, dict)]
        return []

    def __repr__(self) -> str:
        return f"<FormField id={self.id} type={self.type} name={self.name!r} value={self.value!r}>"


# Rebuild models that have forward references to FormField
MultipleChoiceValue.model_rebuild()
TitleValue.model_rebuild()
TableRow.model_rebuild()


# ---------------------------------------------------------------------------
# Form definition models
# ---------------------------------------------------------------------------


class FormStep(PyrusModel):
    """A workflow step in a form."""

    step: int
    name: str
    approvals: list[list[Person]] | None = None


class PrintTemplate(PyrusModel):
    """A print form (print template) attached to a form."""

    print_form_id: int | None = None
    print_form_name: str


class FormFolder(PyrusModel):
    """One element of the folder hierarchy path for a form."""

    id: int
    name: str


class Form(PyrusModel):
    """Pyrus form template (business process schema)."""

    id: int
    name: str
    steps: dict[str, str] = {}
    fields: list[FormField] = []
    print_forms: list[PrintTemplate] = []
    # API returns "deleted_or_closed" (form is archived/disabled)
    deleted_or_closed: bool | None = None
    # Система где folder то dict, то string, то хуй знает.
    # cloud: list[FormFolder] ({id, name}), corp: list[str].
    folder: list[Any] | None = None

    def get_field(self, field_id: int) -> FormField | None:
        """Найти поле по id — включая вложенные в title секции через info['fields']."""
        return self._find_field(self.fields, field_id)

    @staticmethod
    def _find_field(fields: list, field_id: int) -> FormField | None:
        for field in fields:
            if field.id == field_id:
                return field
            # Form definition nests sub-fields inside info["fields"] (as raw dicts)
            if field.info:
                sub = field.info.get("fields")
                if sub:
                    found = Form._find_in_dicts(sub, field_id)
                    if found is not None:
                        return found
        return None

    @staticmethod
    def _find_in_dicts(items: list, field_id: int) -> FormField | None:
        """Рекурсивный поиск в списке raw dict-ов из info['fields']."""
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("id") == field_id:
                return FormField.model_validate(item)
            # Recurse further if this item also has nested info.fields
            sub_info = item.get("info") or {}
            sub = sub_info.get("fields") if isinstance(sub_info, dict) else None
            if sub:
                found = Form._find_in_dicts(sub, field_id)
                if found is not None:
                    return found
        return None


class FormPermissions(PyrusModel):
    members: list[Any] | None = None
