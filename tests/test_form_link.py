"""Тесты полей-ссылок (form_link): чтение, linked_task, автодополнение, поиск по полю."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from aiopyrus.types.form import FormLinkValue
from aiopyrus.types.task import Task
from aiopyrus.user.client import UserClient
from aiopyrus.utils.context import TaskContext

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"

FORM_ID = 321  # форма текущей задачи
LINKED_FORM = 322  # форма, на которую ссылается поле
LINK_FIELD = 42  # поле-ссылка "Связанная заявка"
TICKET_FIELD = 7  # текстовое поле в связанной форме "Номер тикета"


def _mock_auth() -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "t", "api_url": API_BASE, "files_url": API_BASE}
        )
    )


@pytest.fixture
def client() -> UserClient:
    return UserClient(login="test@example.com", security_key="SECRET")


def _task_with_link(value: Any) -> Task:
    return Task.model_validate(
        {
            "id": 12345678,
            "form_id": FORM_ID,
            "fields": [
                {
                    "id": LINK_FIELD,
                    "type": "form_link",
                    "name": "Связанная заявка",
                    "value": value,
                }
            ],
        }
    )


def _mock_form_definition() -> None:
    """Определение формы: поле-ссылка указывает на LINKED_FORM."""
    respx.get(f"{API_BASE}forms/{FORM_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": FORM_ID,
                "name": "Основная форма",
                "fields": [
                    {
                        "id": LINK_FIELD,
                        "type": "form_link",
                        "name": "Связанная заявка",
                        "info": {"form_id": LINKED_FORM},
                    }
                ],
            },
        )
    )


# ── Модель FormLinkValue ────────────────────────────────────────────────────


class TestFormLinkValue:
    def test_task_id_singular_parsed(self):
        """Прод отдаёт task_id (singular) вместе с task_ids — раньше терялся."""
        fl = FormLinkValue.model_validate(
            {"task_id": 111, "task_ids": [111], "subject": "Заявка А | Высокий"}
        )
        assert fl.task_id == 111
        assert fl.task_ids == [111]
        assert fl.subject == "Заявка А | Высокий"

    def test_only_task_ids(self):
        fl = FormLinkValue.model_validate({"task_ids": [222, 333]})
        assert fl.task_id is None
        assert fl.task_ids == [222, 333]


# ── Чтение: ctx["Поле"] → subject ───────────────────────────────────────────


class TestReadFormLink:
    def test_read_returns_subject(self, client: UserClient):
        task = _task_with_link(
            {"task_id": 111, "task_ids": [111], "subject": "Заявка А | Высокий | 01.01.2026"}
        )
        ctx = TaskContext(task, client)
        assert ctx["Связанная заявка"] == "Заявка А | Высокий | 01.01.2026"

    def test_read_falls_back_to_task_id(self, client: UserClient):
        """Без subject возвращаем ID связанной задачи."""
        task = _task_with_link({"task_id": 111, "task_ids": [111]})
        ctx = TaskContext(task, client)
        assert ctx["Связанная заявка"] == 111

    def test_read_empty_link(self, client: UserClient):
        task = _task_with_link(None)
        ctx = TaskContext(task, client)
        assert ctx.get("Связанная заявка") is None

    def test_get_value_id_returns_int(self, client: UserClient):
        task = _task_with_link({"task_id": 111, "task_ids": [111], "subject": "X"})
        ctx = TaskContext(task, client)
        assert ctx.get_value_id("Связанная заявка") == 111

    def test_get_value_id_multiple(self, client: UserClient):
        task = _task_with_link({"task_ids": [111, 222]})
        ctx = TaskContext(task, client)
        assert ctx.get_value_id("Связанная заявка") == [111, 222]


# ── linked_task / linked_form_id ────────────────────────────────────────────


class TestLinkedTask:
    @respx.mock
    async def test_linked_task_loads_full_task(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/111").mock(
            return_value=httpx.Response(
                200, json={"task": {"id": 111, "form_id": LINKED_FORM, "text": "Заявка А"}}
            )
        )
        await client.auth()
        ctx = TaskContext(_task_with_link({"task_id": 111, "task_ids": [111]}), client)
        linked = await ctx.linked_task("Связанная заявка")
        assert linked is not None
        assert linked.id == 111
        assert linked.text == "Заявка А"
        await client.close()

    async def test_linked_task_none_when_empty(self, client: UserClient):
        ctx = TaskContext(_task_with_link(None), client)
        assert await ctx.linked_task("Связанная заявка") is None
        await client.close()

    async def test_linked_task_wrong_type_raises(self, client: UserClient):
        task = Task.model_validate(
            {
                "id": 1,
                "form_id": FORM_ID,
                "fields": [{"id": 9, "type": "text", "name": "Текст", "value": "x"}],
            }
        )
        ctx = TaskContext(task, client)
        with pytest.raises(TypeError, match="not 'form_link'"):
            await ctx.linked_task("Текст")
        await client.close()

    @respx.mock
    async def test_linked_form_id(self, client: UserClient):
        _mock_auth()
        _mock_form_definition()
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        assert await ctx.linked_form_id("Связанная заявка") == LINKED_FORM
        await client.close()


# ── client.find_tasks_by_field (фильтр реестра fld{id}=) ────────────────────


class TestFindTasksByField:
    @respx.mock
    async def test_search_by_field_id(self, client: UserClient):
        _mock_auth()
        route = respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 111, "text": "Заявка А"}]})
        )
        await client.auth()
        found = await client.find_tasks_by_field(LINKED_FORM, TICKET_FIELD, "ABC-001")
        assert [t.id for t in found] == [111]
        assert route.calls.last.request.url.params[f"fld{TICKET_FIELD}"] == "ABC-001"
        await client.close()

    @respx.mock
    async def test_search_by_field_name(self, client: UserClient):
        """Имя поля резолвится в ID через определение формы."""
        _mock_auth()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": LINKED_FORM,
                    "name": "Связанная форма",
                    "fields": [{"id": TICKET_FIELD, "type": "text", "name": "Номер тикета"}],
                },
            )
        )
        route = respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 111}]})
        )
        await client.auth()
        found = await client.find_tasks_by_field(LINKED_FORM, "Номер тикета", "ABC-001")
        assert [t.id for t in found] == [111]
        assert route.calls.last.request.url.params[f"fld{TICKET_FIELD}"] == "ABC-001"
        await client.close()

    @respx.mock
    async def test_unknown_field_name_raises(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}").mock(
            return_value=httpx.Response(200, json={"id": LINKED_FORM, "name": "F", "fields": []})
        )
        await client.auth()
        with pytest.raises(KeyError, match="not found in form"):
            await client.find_tasks_by_field(LINKED_FORM, "Нет такого", "X")
        await client.close()


# ── fill() — автодополнение по строке ───────────────────────────────────────


def _mock_linked_form_fields() -> None:
    """Связанная форма с текстовым полем «Номер тикета» (приоритетное для поиска)."""
    respx.get(f"{API_BASE}forms/{LINKED_FORM}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": LINKED_FORM,
                "name": "Связанная форма",
                "fields": [
                    {"id": TICKET_FIELD, "type": "text", "name": "Номер тикета"},
                    {"id": 8, "type": "text", "name": "Описание"},
                ],
            },
        )
    )


class TestFillFormLink:
    @respx.mock
    async def test_fill_with_int_task_id(self, client: UserClient):
        _mock_auth()
        route = respx.post(f"{API_BASE}tasks/12345678/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 12345678}})
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        ctx.fill("Связанная заявка", 111)
        await ctx.answer("привязал")
        import json as _json

        body = _json.loads(route.calls.last.request.content.decode())
        assert body["field_updates"] == [
            {"id": LINK_FIELD, "value": {"task_id": 111, "task_ids": [111]}}
        ]
        await client.close()

    @respx.mock
    async def test_fill_with_numeric_string(self, client: UserClient):
        """Числовая строка (из БД/CSV) = task_id, без похода в поиск."""
        _mock_auth()
        route = respx.post(f"{API_BASE}tasks/12345678/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 12345678}})
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        ctx.fill("Связанная заявка", "111")
        await ctx.answer()
        import json as _json

        body = _json.loads(route.calls.last.request.content.decode())
        assert body["field_updates"][0]["value"]["task_id"] == 111
        await client.close()

    @respx.mock
    async def test_fill_with_search_string(self, client: UserClient):
        """Строка → поиск в связанной форме → task_id (как автодополнение в UI)."""
        _mock_auth()
        _mock_form_definition()
        _mock_linked_form_fields()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 111, "text": "Заявка А"}]})
        )
        route = respx.post(f"{API_BASE}tasks/12345678/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 12345678}})
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        ctx.fill("Связанная заявка", "ABC-001")
        await ctx.answer()
        import json as _json

        body = _json.loads(route.calls.last.request.content.decode())
        assert body["field_updates"][0]["value"] == {"task_id": 111, "task_ids": [111]}
        await client.close()

    @respx.mock
    async def test_fill_not_found_raises_with_hint(self, client: UserClient):
        _mock_auth()
        _mock_form_definition()
        _mock_linked_form_fields()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(200, json={"tasks": []})
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        ctx.fill("Связанная заявка", "НЕТ-ТАКОГО")
        with pytest.raises(ValueError, match="not found"):
            await ctx.answer()
        await client.close()

    @respx.mock
    async def test_fill_ambiguous_raises(self, client: UserClient):
        """Несколько совпадений — явная ошибка, а не молчаливый выбор первого."""
        _mock_auth()
        _mock_form_definition()
        _mock_linked_form_fields()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(
                200, json={"tasks": [{"id": 111, "text": "А"}, {"id": 222, "text": "Б"}]}
            )
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        ctx.fill("Связанная заявка", "ABC")
        with pytest.raises(ValueError, match="Ambiguous"):
            await ctx.answer()
        await client.close()


# ── search_link — предпросмотр кандидатов ───────────────────────────────────


class TestSearchLink:
    @respx.mock
    async def test_search_link_returns_candidates(self, client: UserClient):
        _mock_auth()
        _mock_form_definition()
        _mock_linked_form_fields()
        respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(
                200, json={"tasks": [{"id": 111, "text": "Заявка А"}, {"id": 222, "text": "Б"}]}
            )
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        found = await ctx.search_link("Связанная заявка", "ABC")
        assert [t.id for t in found] == [111, 222]
        await client.close()

    @respx.mock
    async def test_search_link_explicit_field(self, client: UserClient):
        _mock_auth()
        _mock_form_definition()
        route = respx.get(f"{API_BASE}forms/{LINKED_FORM}/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 111}]})
        )
        await client.auth()
        ctx = TaskContext(_task_with_link(None), client)
        found = await ctx.search_link("Связанная заявка", "ABC", search_field=TICKET_FIELD)
        assert [t.id for t in found] == [111]
        assert route.calls.last.request.url.params[f"fld{TICKET_FIELD}"] == "ABC"
        await client.close()
