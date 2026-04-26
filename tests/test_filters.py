"""Tests for all filters — builtin, composition (&/|/~), magic F."""

from __future__ import annotations

from datetime import datetime, timezone

from aiopyrus.bot.filters.base import AndFilter, NotFilter, OrFilter
from aiopyrus.bot.filters.builtin import (
    CreatedAfterFilter,
    EventFilter,
    FieldValueFilter,
    FormFilter,
    ModifiedAfterFilter,
    ResponsibleFilter,
    StepFilter,
    TextFilter,
)
from aiopyrus.bot.filters.magic import F

from .conftest import make_field, make_payload, make_person

# ── FormFilter ────────────────────────────────────────────────


class TestFormFilter:
    async def test_match_single(self):
        p = make_payload(form_id=321)
        assert await FormFilter(321)(p) is True

    async def test_no_match_single(self):
        p = make_payload(form_id=999)
        assert await FormFilter(321)(p) is False

    async def test_match_list(self):
        p = make_payload(form_id=322)
        assert await FormFilter([321, 322, 323])(p) is True

    async def test_no_match_list(self):
        p = make_payload(form_id=999)
        assert await FormFilter([321, 322])(p) is False

    async def test_none_form_id_never_matches(self):
        """form_id=None (inbox/register data) → always False."""
        p = make_payload(form_id=None)
        assert await FormFilter(321)(p) is False
        assert await FormFilter([321, 322])(p) is False

    async def test_match_by_name_after_resolve(self):
        from aiopyrus.types.form import Form

        class FakeBot:
            async def get_forms(self):
                return [
                    Form(id=321, name="Заявки на доступ"),
                    Form(id=999, name="Согласование"),
                ]

        f = FormFilter("Заявки на доступ")
        await f.resolve(FakeBot())
        assert await f(make_payload(form_id=321)) is True
        assert await f(make_payload(form_id=999)) is False

    async def test_match_by_name_case_insensitive(self):
        from aiopyrus.types.form import Form

        class FakeBot:
            async def get_forms(self):
                return [Form(id=321, name="Заявки на Доступ")]

        f = FormFilter("заявки на доступ")
        await f.resolve(FakeBot())
        assert await f(make_payload(form_id=321)) is True

    async def test_mixed_id_and_name(self):
        from aiopyrus.types.form import Form

        class FakeBot:
            async def get_forms(self):
                return [Form(id=999, name="Согласование")]

        f = FormFilter([321, "Согласование"])
        await f.resolve(FakeBot())
        assert await f(make_payload(form_id=321)) is True
        assert await f(make_payload(form_id=999)) is True
        assert await f(make_payload(form_id=111)) is False

    async def test_unknown_name_raises(self):
        from aiopyrus.types.form import Form

        class FakeBot:
            async def get_forms(self):
                return [Form(id=321, name="Заявки")]

        f = FormFilter("Не существует")
        try:
            await f.resolve(FakeBot())
        except ValueError as exc:
            assert "Не существует" in str(exc)
        else:
            raise AssertionError("Expected ValueError for unknown form name")

    async def test_unresolved_name_returns_false_with_warning(self, caplog):
        f = FormFilter("Какая-то форма")
        result = await f(make_payload(form_id=321))
        assert result is False

    async def test_resolve_idempotent_skips_when_no_names(self):
        """resolve() with only ints does NOT call get_forms()."""

        class FakeBot:
            calls = 0

            async def get_forms(self):
                self.calls += 1
                return []

        bot = FakeBot()
        f = FormFilter([321, 322])
        await f.resolve(bot)
        assert bot.calls == 0

    async def test_resolve_propagates_through_composite(self):
        from aiopyrus.bot.filters.builtin import StepFilter
        from aiopyrus.types.form import Form

        class FakeBot:
            async def get_forms(self):
                return [Form(id=321, name="Заявки")]

        composite = FormFilter("Заявки") & StepFilter(2)
        await composite.resolve(FakeBot())
        # Inner FormFilter should now match by id
        p_match = make_payload(form_id=321, current_step=2)
        p_wrong_step = make_payload(form_id=321, current_step=3)
        assert await composite(p_match) is True
        assert await composite(p_wrong_step) is False


# ── StepFilter ────────────────────────────────────────────────


class TestStepFilter:
    async def test_match(self):
        p = make_payload(current_step=2)
        assert await StepFilter(2)(p) is True

    async def test_no_match(self):
        p = make_payload(current_step=3)
        assert await StepFilter(2)(p) is False

    async def test_match_list(self):
        p = make_payload(current_step=3)
        assert await StepFilter([2, 3])(p) is True

    async def test_none_step_never_matches(self):
        """current_step=None (inbox data) → always False."""
        p = make_payload(current_step=None)
        assert await StepFilter(2)(p) is False
        assert await StepFilter([2, 3])(p) is False


# ── ResponsibleFilter ────────────────────────────────────────


class TestResponsibleFilter:
    async def test_match(self):
        p = make_payload(responsible=make_person(id=42))
        assert await ResponsibleFilter(42)(p) is True

    async def test_no_match(self):
        p = make_payload(responsible=make_person(id=99))
        assert await ResponsibleFilter(42)(p) is False

    async def test_no_responsible(self):
        p = make_payload(responsible=None)
        assert await ResponsibleFilter(42)(p) is False

    async def test_match_list(self):
        p = make_payload(responsible=make_person(id=42))
        assert await ResponsibleFilter([42, 100])(p) is True


# ── TextFilter ────────────────────────────────────────────────


class TestTextFilter:
    async def test_match_case_insensitive(self):
        p = make_payload(text="Оплата по счёту")
        assert await TextFilter("оплата")(p) is True

    async def test_no_match(self):
        p = make_payload(text="Закрытие задачи")
        assert await TextFilter("оплата")(p) is False

    async def test_case_sensitive(self):
        p = make_payload(text="Оплата по счёту")
        assert await TextFilter("оплата", case_sensitive=True)(p) is False
        assert await TextFilter("Оплата", case_sensitive=True)(p) is True

    async def test_none_text(self):
        p = make_payload(text=None)
        assert await TextFilter("anything")(p) is False


# ── EventFilter ───────────────────────────────────────────────


class TestEventFilter:
    async def test_match(self):
        p = make_payload()
        p.event = "task_created"
        assert await EventFilter("task_created")(p) is True

    async def test_no_match(self):
        p = make_payload()
        p.event = "comment"
        assert await EventFilter("task_created")(p) is False

    async def test_multiple_events(self):
        p = make_payload()
        p.event = "comment"
        assert await EventFilter("task_created", "comment")(p) is True


# ── FieldValueFilter ─────────────────────────────────────────


class TestFieldValueFilter:
    async def test_match_text(self):
        f = make_field(id=1, name="Title", type="text", value="Hello")
        p = make_payload(fields=[f])
        assert await FieldValueFilter(field_name="Title", value="Hello")(p) is True

    async def test_case_insensitive(self):
        f = make_field(id=1, name="Title", type="text", value="Hello")
        p = make_payload(fields=[f])
        assert await FieldValueFilter(field_name="Title", value="hello")(p) is True

    async def test_match_none_value(self):
        f = make_field(id=1, name="Title", type="text", value=None)
        p = make_payload(fields=[f])
        assert await FieldValueFilter(field_name="Title", value=None)(p) is True

    async def test_match_multiple_choice(self):
        f = make_field(
            id=1,
            name="Status",
            type="multiple_choice",
            value={"choice_ids": [1], "choice_names": ["Open"]},
        )
        p = make_payload(fields=[f])
        assert await FieldValueFilter(field_name="Status", value="Open")(p) is True

    async def test_no_field(self):
        p = make_payload(fields=[])
        assert await FieldValueFilter(field_name="Missing", value="x")(p) is False

    async def test_no_key(self):
        p = make_payload()
        assert await FieldValueFilter(value="x")(p) is False

    async def test_match_by_field_id(self):
        f = make_field(id=42, name="Title", type="text", value="Hello")
        p = make_payload(fields=[f])
        assert await FieldValueFilter(field_id=42, value="Hello")(p) is True


# ── ModifiedAfterFilter / CreatedAfterFilter ─────────────────


class TestTimeFilters:
    async def test_modified_after_match(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        p = make_payload(last_modified_date=datetime(2026, 2, 1, tzinfo=timezone.utc))
        assert await ModifiedAfterFilter(since=since)(p) is True

    async def test_modified_after_no_match(self):
        since = datetime(2026, 3, 1, tzinfo=timezone.utc)
        p = make_payload(last_modified_date=datetime(2026, 2, 1, tzinfo=timezone.utc))
        assert await ModifiedAfterFilter(since=since)(p) is False

    async def test_modified_after_none(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        p = make_payload(last_modified_date=None)
        assert await ModifiedAfterFilter(since=since)(p) is False

    async def test_created_after_match(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        p = make_payload(create_date=datetime(2026, 2, 1, tzinfo=timezone.utc))
        assert await CreatedAfterFilter(since=since)(p) is True

    async def test_created_after_no_match(self):
        since = datetime(2026, 3, 1, tzinfo=timezone.utc)
        p = make_payload(create_date=datetime(2026, 2, 1, tzinfo=timezone.utc))
        assert await CreatedAfterFilter(since=since)(p) is False

    async def test_naive_datetime_handled(self):
        """Naive datetimes (no tzinfo) should be treated as UTC."""
        since = datetime(2026, 1, 1)  # naive
        p = make_payload(last_modified_date=datetime(2026, 2, 1))  # naive
        assert await ModifiedAfterFilter(since=since)(p) is True


# ── Composition (&, |, ~) ────────────────────────────────────


class TestComposition:
    async def test_and_both_true(self):
        p = make_payload(form_id=321, current_step=2)
        f = FormFilter(321) & StepFilter(2)
        assert isinstance(f, AndFilter)
        assert await f(p) is True

    async def test_and_one_false(self):
        p = make_payload(form_id=321, current_step=3)
        f = FormFilter(321) & StepFilter(2)
        assert await f(p) is False

    async def test_or_first_true(self):
        p = make_payload(form_id=321)
        f = FormFilter(321) | FormFilter(999)
        assert isinstance(f, OrFilter)
        assert await f(p) is True

    async def test_or_second_true(self):
        p = make_payload(form_id=999)
        f = FormFilter(321) | FormFilter(999)
        assert await f(p) is True

    async def test_or_both_false(self):
        p = make_payload(form_id=111)
        f = FormFilter(321) | FormFilter(999)
        assert await f(p) is False

    async def test_not(self):
        p = make_payload(form_id=321)
        f = ~FormFilter(321)
        assert isinstance(f, NotFilter)
        assert await f(p) is False

    async def test_not_inverts(self):
        p = make_payload(form_id=999)
        f = ~FormFilter(321)
        assert await f(p) is True

    async def test_complex_chain(self):
        p = make_payload(form_id=321, current_step=2, text="оплата")
        f = FormFilter(321) & StepFilter(2) & ~TextFilter("отклонено")
        assert await f(p) is True


# ── Magic F ───────────────────────────────────────────────────


class TestMagicF:
    async def test_eq(self):
        p = make_payload(form_id=321)
        assert await (F.form_id == 321)(p) is True
        assert await (F.form_id == 999)(p) is False

    async def test_ne(self):
        p = make_payload(form_id=321)
        assert await (F.form_id != 999)(p) is True

    async def test_in(self):
        p = make_payload(form_id=321)
        assert await F.form_id.in_([321, 322])(p) is True
        assert await F.form_id.in_([999])(p) is False

    async def test_contains(self):
        p = make_payload(text="Оплата по счёту 123")
        assert await F.text.contains("оплата")(p) is True
        assert await F.text.contains("нет")(p) is False

    async def test_contains_case_sensitive(self):
        p = make_payload(text="Оплата по счёту")
        assert await F.text.contains("оплата", case_sensitive=True)(p) is False
        assert await F.text.contains("Оплата", case_sensitive=True)(p) is True

    async def test_is_none(self):
        p = make_payload(responsible=None)
        assert await F.responsible.is_none()(p) is True

    async def test_is_not_none(self):
        p = make_payload(responsible=make_person())
        assert await F.responsible.is_not_none()(p) is True

    async def test_nested_attr(self):
        p = make_payload(responsible=make_person(id=42))
        assert await (F.responsible.id == 42)(p) is True

    async def test_comparison_gt(self):
        p = make_payload(current_step=5)
        assert await (F.current_step > 3)(p) is True
        assert await (F.current_step > 10)(p) is False

    async def test_exception_returns_false(self):
        """If accessor raises, the filter returns False (not an exception)."""
        p = make_payload()
        # Accessing a non-existent deep chain attribute
        f = F.nonexistent_attr.deep.chain == "x"
        assert await f(p) is False

    async def test_composition_with_magic(self):
        p = make_payload(form_id=321, current_step=2)
        f = (F.form_id == 321) & (F.current_step == 2)
        assert await f(p) is True

    async def test_callable_accessor(self):
        p = make_payload()
        p.event = "comment"
        f = F(lambda p: p.event) == "comment"
        assert await f(p) is True
