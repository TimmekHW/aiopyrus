"""Tests for FieldUpdate factory methods."""

from __future__ import annotations

import pytest

from aiopyrus.utils.fields import FieldUpdate

from .conftest import make_field, make_person


class TestFieldUpdateFactories:
    def test_text(self):
        assert FieldUpdate.text(1, "hello") == {"id": 1, "value": "hello"}

    def test_text_none(self):
        assert FieldUpdate.text(1, None) == {"id": 1, "value": None}

    def test_choice(self):
        assert FieldUpdate.choice(1, 42) == {"id": 1, "value": {"choice_ids": [42]}}

    def test_choices(self):
        assert FieldUpdate.choices(1, [42, 43]) == {"id": 1, "value": {"choice_ids": [42, 43]}}

    def test_person(self):
        assert FieldUpdate.person(1, 100500) == {"id": 1, "value": {"id": 100500}}

    def test_clear_person(self):
        assert FieldUpdate.clear_person(1) == {"id": 1, "value": None}

    def test_catalog(self):
        assert FieldUpdate.catalog(1, 999) == {"id": 1, "value": {"item_id": 999}}

    def test_checkmark_true(self):
        assert FieldUpdate.checkmark(1, True) == {"id": 1, "value": "checked"}

    def test_checkmark_false(self):
        assert FieldUpdate.checkmark(1, False) == {"id": 1, "value": "unchecked"}

    def test_clear(self):
        assert FieldUpdate.clear(1) == {"id": 1, "value": None}


class TestFromField:
    def test_none_value_clears(self):
        f = make_field(id=1, type="text")
        assert FieldUpdate.from_field(f, None) == {"id": 1, "value": None}

    def test_text_type(self):
        f = make_field(id=1, type="text")
        assert FieldUpdate.from_field(f, "hello") == {"id": 1, "value": "hello"}

    def test_number_as_str(self):
        f = make_field(id=1, type="number")
        assert FieldUpdate.from_field(f, 42) == {"id": 1, "value": "42"}

    def test_email(self):
        f = make_field(id=1, type="email")
        assert FieldUpdate.from_field(f, "a@b.com") == {"id": 1, "value": "a@b.com"}

    def test_checkmark_bool(self):
        f = make_field(id=1, type="checkmark")
        assert FieldUpdate.from_field(f, True) == {"id": 1, "value": "checked"}
        assert FieldUpdate.from_field(f, False) == {"id": 1, "value": "unchecked"}

    def test_checkmark_string(self):
        f = make_field(id=1, type="checkmark")
        assert FieldUpdate.from_field(f, "yes") == {"id": 1, "value": "checked"}
        assert FieldUpdate.from_field(f, "no") == {"id": 1, "value": "unchecked"}
        assert FieldUpdate.from_field(f, "true") == {"id": 1, "value": "checked"}

    def test_checkmark_invalid(self):
        f = make_field(id=1, type="checkmark")
        with pytest.raises(ValueError, match="checkmark"):
            FieldUpdate.from_field(f, 123)

    def test_flag(self):
        f = make_field(id=1, type="flag")
        assert FieldUpdate.from_field(f, True) == {"id": 1, "value": "checked"}

    def test_multiple_choice_int(self):
        f = make_field(id=1, type="multiple_choice")
        assert FieldUpdate.from_field(f, 42) == {"id": 1, "value": {"choice_ids": [42]}}

    def test_multiple_choice_list_int(self):
        f = make_field(id=1, type="multiple_choice")
        assert FieldUpdate.from_field(f, [1, 2]) == {"id": 1, "value": {"choice_ids": [1, 2]}}

    def test_multiple_choice_string_raises(self):
        f = make_field(id=1, name="Status", type="multiple_choice")
        with pytest.raises(ValueError, match="multiple_choice"):
            FieldUpdate.from_field(f, "Open")

    def test_person_int(self):
        f = make_field(id=1, type="person")
        assert FieldUpdate.from_field(f, 100500) == {"id": 1, "value": {"id": 100500}}

    def test_person_object(self):
        f = make_field(id=1, type="person")
        p = make_person(id=42)
        assert FieldUpdate.from_field(f, p) == {"id": 1, "value": {"id": 42}}

    def test_person_dict(self):
        f = make_field(id=1, type="person")
        assert FieldUpdate.from_field(f, {"id": 42}) == {"id": 1, "value": {"id": 42}}

    def test_person_string_raises(self):
        f = make_field(id=1, name="Executor", type="person")
        with pytest.raises(ValueError, match="person"):
            FieldUpdate.from_field(f, "Ivan Ivanov")

    def test_author(self):
        f = make_field(id=1, type="author")
        assert FieldUpdate.from_field(f, 100500) == {"id": 1, "value": {"id": 100500}}

    def test_catalog_int(self):
        f = make_field(id=1, type="catalog")
        assert FieldUpdate.from_field(f, 999) == {"id": 1, "value": {"item_id": 999}}

    def test_catalog_string_raises(self):
        f = make_field(id=1, name="City", type="catalog")
        with pytest.raises(ValueError, match="catalog"):
            FieldUpdate.from_field(f, "Moscow")

    def test_unsupported_type_raises(self):
        f = make_field(id=1, name="Table", type="table")
        with pytest.raises(ValueError, match="unsupported"):
            FieldUpdate.from_field(f, [])
