"""Extended tests for magic filter — lt, le, gt, ge, _F.__call__, contains None."""

from __future__ import annotations

from aiopyrus.bot.filters.magic import F

from .conftest import make_payload, make_person


class TestMagicComparisons:
    async def test_lt(self):
        p = make_payload(current_step=2)
        assert await (F.current_step < 5)(p) is True
        assert await (F.current_step < 1)(p) is False

    async def test_le(self):
        p = make_payload(current_step=2)
        assert await (F.current_step <= 2)(p) is True
        assert await (F.current_step <= 1)(p) is False

    async def test_gt(self):
        p = make_payload(current_step=5)
        assert await (F.current_step > 3)(p) is True
        assert await (F.current_step > 10)(p) is False

    async def test_ge(self):
        p = make_payload(current_step=5)
        assert await (F.current_step >= 5)(p) is True
        assert await (F.current_step >= 6)(p) is False

    async def test_contains_none_value(self):
        """F.text.contains() on None text returns False, not an exception."""
        p = make_payload(text=None)
        assert await F.text.contains("anything")(p) is False

    async def test_ne(self):
        p = make_payload(form_id=321)
        assert await (F.form_id != 321)(p) is False
        assert await (F.form_id != 999)(p) is True


class TestMagicCallable:
    async def test_f_callable_accessor(self):
        """F(lambda p: p.event) works as an entrypoint."""
        p = make_payload()
        p.event = "task_polled"
        filt = F(lambda p: p.event)
        assert await (filt == "task_polled")(p) is True
        assert await (filt == "other")(p) is False


class TestMagicAttributeNavigation:
    async def test_deep_nested_attr(self):
        p = make_payload(responsible=make_person(id=42))
        # F.responsible.id navigates into task.responsible.id
        assert await (F.responsible.id == 42)(p) is True

    async def test_missing_attr_returns_false(self):
        p = make_payload()
        # Accessing nonexistent attr chain → accessor returns None → bool(None) = False
        filt = F.nonexistent.deep == "something"
        assert await filt(p) is False

    async def test_in_with_none(self):
        """in_() with None accessor → should not crash."""
        p = make_payload(responsible=None)
        filt = F.responsible.in_([None])
        assert await filt(p) is True

    async def test_is_none_on_present(self):
        p = make_payload(form_id=321)
        assert await F.form_id.is_none()(p) is False

    async def test_is_not_none_on_none(self):
        p = make_payload(responsible=None)
        assert await F.responsible.is_not_none()(p) is False
