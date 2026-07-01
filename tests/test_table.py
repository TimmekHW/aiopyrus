"""Тесты DataFrame-подобного API для полей-таблиц (ctx.table)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from aiopyrus.types.form import FieldType, FormField
from aiopyrus.types.task import Task
from aiopyrus.user.client import UserClient
from aiopyrus.utils.table import Column, TableProxy, build_columns

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"

# ── Реальная структура таблицы «План работ» (task 12345678) ───────────
# Колонки: 36 text «Что сделать», 110 person «Ответственный», 39 checkmark «Выполнено»
TABLE_ID = 35
COL_PLAN, COL_RESP, COL_DONE = 36, 110, 39


def _make_table_field(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Построить raw dict table-поля с заданными строками."""
    return {
        "id": TABLE_ID,
        "type": "table",
        "name": "План работ",
        "value": rows,
    }


def _cell(col_id: int, ctype: str, name: str, value: Any) -> dict[str, Any]:
    return {"id": col_id, "type": ctype, "name": name, "value": value, "parent_id": TABLE_ID}


def _sample_task() -> Task:
    rows = [
        {
            "row_id": 0,
            "cells": [
                _cell(COL_PLAN, "text", "Что сделать", "Задача А"),
                _cell(
                    COL_RESP,
                    "person",
                    "Ответственный",
                    {"id": 100501, "first_name": "Иван", "last_name": "Петров"},
                ),
                _cell(COL_DONE, "checkmark", "Выполнено", "unchecked"),
            ],
        },
        {
            "row_id": 1,
            "cells": [
                _cell(COL_PLAN, "text", "Что сделать", "Задача В"),
                _cell(
                    COL_RESP,
                    "person",
                    "Ответственный",
                    {"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"},
                ),
                _cell(COL_DONE, "checkmark", "Выполнено", "checked"),
            ],
        },
    ]
    return Task.model_validate(
        {"id": 12345678, "form_id": 321, "fields": [_make_table_field(rows)]}
    )


# ── build_columns / build_rows (pure, без сети) ─────────────────────────────


class TestBuild:
    def test_columns_from_rows(self):
        task = _sample_task()
        field = task.get_field("План работ")
        assert field is not None
        cols = build_columns(field, None)  # без form definition
        by_id = {c.id: c for c in cols}
        assert set(by_id) == {COL_PLAN, COL_RESP, COL_DONE}
        assert by_id[COL_RESP].type == "person"
        assert by_id[COL_DONE].type == "checkmark"

    def test_columns_from_form_definition(self):
        """Колонки берутся из info['fields'] — включая пустые во всех строках."""
        field = FormField(id=TABLE_ID, type=FieldType.table, name="T", value=None)
        form_field = FormField(
            id=TABLE_ID,
            type=FieldType.table,
            name="T",
            info={
                "fields": [
                    {"id": COL_PLAN, "type": "text", "name": "Что сделать"},
                    {"id": COL_RESP, "type": "person", "name": "Ответственный"},
                    {"id": COL_DONE, "type": "checkmark", "name": "Выполнено"},
                ]
            },
        )
        cols = build_columns(field, form_field)
        assert [c.name for c in cols] == ["Что сделать", "Ответственный", "Выполнено"]


# ── Через TaskContext (полный флоу) ─────────────────────────────────────────


def _mock_auth() -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "t", "api_url": API_BASE, "files_url": API_BASE}
        )
    )


@pytest.fixture
def client() -> UserClient:
    return UserClient(login="test@example.com", security_key="SECRET")


def _ctx(client: UserClient):
    from aiopyrus.utils.context import TaskContext

    return TaskContext(_sample_task(), client)


class TestReadTable:
    async def test_open_and_read(self, client: UserClient):
        ctx = _ctx(client)
        # form definition недоступен в этом тесте — колонки из строк
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        assert isinstance(tbl, TableProxy)
        assert set(tbl.columns) == {"Что сделать", "Ответственный", "Выполнено"}
        assert len(tbl) == 2
        assert tbl[0]["Что сделать"] == "Задача А"
        assert tbl[0]["Ответственный"] == "Иван Петров"
        assert tbl[0]["Выполнено"] is False
        assert tbl[1]["Выполнено"] is True

    async def test_not_a_table_raises(self, client: UserClient):
        from aiopyrus.utils.context import TaskContext

        task = Task.model_validate(
            {
                "id": 1,
                "form_id": 1,
                "fields": [{"id": 9, "type": "text", "name": "Текст", "value": "x"}],
            }
        )
        ctx = TaskContext(task, client)
        with pytest.raises(TypeError, match="not 'table'"):
            await ctx.table("Текст")

    async def test_missing_field_raises(self, client: UserClient):
        ctx = _ctx(client)
        with pytest.raises(KeyError, match="not found"):
            await ctx.table("Нет такой")


class TestFilter:
    async def test_where_bool(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        done = tbl.where(**{"Выполнено": True})
        assert len(done) == 1
        assert done[0]["Что сделать"] == "Задача В"

    async def test_where_substring(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        rows = tbl.where(**{"Ответственный": "петров"})  # частичное, регистронезависимо
        assert len(rows) == 1
        assert rows[0].row_id == 0

    async def test_find_returns_first(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        row = tbl.find(**{"Что сделать": "Задача В"})
        assert row is not None
        assert row.row_id == 1

    async def test_find_none(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        assert tbl.find(**{"Что сделать": "нет такого"}) is None

    async def test_missing_checkmark_cell_reads_false(self, client: UserClient):
        """Pyrus не присылает ячейку у непроставленной галочки — читаем как False."""
        from aiopyrus.utils.context import TaskContext

        # строка вообще без ячейки Выполнено
        task = Task.model_validate(
            {
                "id": 1,
                "form_id": 1,
                "fields": [
                    _make_table_field(
                        [
                            {
                                "row_id": 0,
                                "cells": [_cell(COL_PLAN, "text", "Что сделать", "X")],
                            }
                        ]
                    )
                ],
            }
        )
        ctx = TaskContext(task, client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        # колонка Выполнено известна из первой (единственной) строки? нет — её там нет.
        # добавим её вручную как колонку через form definition-эмуляцию:
        from aiopyrus.utils.table import Column

        tbl._columns.append(Column(COL_DONE, "Выполнено", "checkmark"))
        tbl._by_name["выполнено"] = tbl._columns[-1]
        tbl._by_id[COL_DONE] = tbl._columns[-1]
        assert tbl[0]["Выполнено"] is False
        assert tbl.where(**{"Выполнено": False})  # теперь матчит


class TestEditPayload:
    async def test_update_cell_builds_payload(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl[0]["Выполнено"] = True
        assert ctx.pending_count() == 1
        update = await tbl._build_update()
        assert update == {
            "id": TABLE_ID,
            "value": [{"row_id": 0, "cells": [{"id": COL_DONE, "value": "checked"}]}],
        }

    async def test_delete_row_builds_payload(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl.find(**{"Что сделать": "Задача В"}).delete()
        update = await tbl._build_update()
        assert update == {"id": TABLE_ID, "value": [{"row_id": 1, "delete": True}]}
        # удалённая строка исчезает из live-выборки
        assert len(tbl) == 1

    async def test_add_row_with_int_person(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl.add(**{"Что сделать": "Новая", "Ответственный": 100500, "Выполнено": False})
        assert len(tbl) == 3
        update = await tbl._build_update()
        assert update["id"] == TABLE_ID
        (entry,) = update["value"]
        assert "row_id" not in entry  # новая строка
        cells = {c["id"]: c["value"] for c in entry["cells"]}
        assert cells[COL_PLAN] == "Новая"
        assert cells[COL_RESP] == {"id": 100500}  # int person → {"id": ...}
        assert cells[COL_DONE] == "unchecked"  # False → unchecked

    @respx.mock
    async def test_add_row_resolves_person_name(self, client: UserClient):
        """Имя человека в ячейке резолвится в person_id через find_member."""
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"},
                    ]
                },
            )
        )
        await client.auth()
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl.add(**{"Что сделать": "X", "Ответственный": "Колбасенко"})
        update = await tbl._build_update()
        (entry,) = update["value"]
        cells = {c["id"]: c["value"] for c in entry["cells"]}
        assert cells[COL_RESP] == {"id": 100500}
        await client.close()

    @respx.mock
    async def test_person_cell_by_email(self, client: UserClient):
        """Ячейку person можно заполнить email — резолвится в person_id."""
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {
                            "id": 100500,
                            "first_name": "Данил",
                            "last_name": "Колбасенко",
                            "email": "user@example.com",
                        },
                    ]
                },
            )
        )
        await client.auth()
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl.add(**{"Что сделать": "X", "Ответственный": "user@example.com"})
        update = await tbl._build_update()
        (entry,) = update["value"]
        cells = {c["id"]: c["value"] for c in entry["cells"]}
        assert cells[COL_RESP] == {"id": 100500}
        await client.close()

    @respx.mock
    async def test_person_cell_by_numeric_string(self, client: UserClient):
        """Ячейку person можно заполнить числовой строкой person_id (напр. из БД/CSV)."""
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200, json={"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"}
            )
        )
        await client.auth()
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl.add(**{"Что сделать": "X", "Ответственный": "100500"})
        update = await tbl._build_update()
        (entry,) = update["value"]
        cells = {c["id"]: c["value"] for c in entry["cells"]}
        assert cells[COL_RESP] == {"id": 100500}
        await client.close()

    async def test_no_changes_no_payload(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        assert await tbl._build_update() is None

    async def test_discard_clears_tables(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl[0]["Выполнено"] = True
        assert ctx.pending_count() == 1
        ctx.discard()
        assert ctx.pending_count() == 0


class TestFlushIntegration:
    @respx.mock
    async def test_answer_sends_table_update(self, client: UserClient):
        """ctx.answer() отправляет table-правки в field_updates одним запросом."""
        _mock_auth()
        route = respx.post(f"{API_BASE}tasks/12345678/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 12345678}})
        )
        await client.auth()
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        tbl[0]["Выполнено"] = True
        tbl.add(**{"Что сделать": "Новая строка", "Выполнено": False})
        await ctx.answer("Обновил план")

        sent = route.calls.last.request.content.decode()
        import json

        body = json.loads(sent)
        assert body["text"] == "Обновил план"
        fu = body["field_updates"]
        assert len(fu) == 1
        assert fu[0]["id"] == TABLE_ID
        # одна правка + одна новая строка
        assert len(fu[0]["value"]) == 2
        await client.close()


class TestRender:
    async def test_repr_is_ascii_table(self, client: UserClient):
        ctx = _ctx(client)
        client.get_form = None  # type: ignore[assignment]
        tbl = await ctx.table("План работ")
        s = repr(tbl)
        assert "План работ" in s
        assert "Ответственный" in s
        assert "Петров" in s
        assert "✓" in s or "·" in s  # checkmark рендер


class TestColumnRepr:
    def test_column_repr(self):
        c = Column(id=5, name="X", type="text")
        assert "id=5" in repr(c)
