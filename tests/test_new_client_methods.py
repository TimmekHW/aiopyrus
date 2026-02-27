"""Tests for new client methods: task lists, print forms, avatar,
calendar enrichment, CSV export, external_id resolution."""

from __future__ import annotations

import httpx
import pytest
import respx

from aiopyrus.types.params import PrintFormItem
from aiopyrus.user.client import UserClient

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"
FILES_BASE = "https://files.pyrus.com/"


def _mock_auth(token: str = "test-token") -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": token,
                "api_url": API_BASE,
                "files_url": FILES_BASE,
            },
        )
    )


@pytest.fixture
def client():
    return UserClient(login="test@example.com", security_key="SECRET")


# -- Task Lists --


class TestGetLists:
    @respx.mock
    async def test_get_lists(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}lists").mock(
            return_value=httpx.Response(
                200,
                json={
                    "lists": [
                        {
                            "id": 1,
                            "name": "Project A",
                            "children": [{"id": 2, "name": "Sub-project"}],
                        },
                        {"id": 3, "name": "Project B"},
                    ]
                },
            )
        )
        await client.auth()
        lists = await client.get_lists()
        assert len(lists) == 2
        assert lists[0].name == "Project A"
        assert len(lists[0].children) == 1
        assert lists[0].children[0].name == "Sub-project"
        await client.close()

    @respx.mock
    async def test_get_task_list(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}lists/1/tasks").mock(
            return_value=httpx.Response(
                200,
                json={"tasks": [{"id": 100}, {"id": 200}]},
            )
        )
        await client.auth()
        tasks = await client.get_task_list(1, item_count=50)
        assert len(tasks) == 2
        assert tasks[0].id == 100
        await client.close()


# -- Print Forms --


class TestPrintForms:
    @respx.mock
    async def test_download_print_form(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1/print_forms/5").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 fake content")
        )
        await client.auth()
        pdf_bytes = await client.download_print_form(1, 5)
        assert pdf_bytes.startswith(b"%PDF")
        await client.close()

    @respx.mock
    async def test_download_print_forms_batch(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1/print_forms/5").mock(
            return_value=httpx.Response(200, content=b"%PDF-1")
        )
        respx.get(f"{API_BASE}tasks/2/print_forms/6").mock(
            return_value=httpx.Response(200, content=b"%PDF-2")
        )
        await client.auth()
        results = await client.download_print_forms(
            [
                PrintFormItem(task_id=1, print_form_id=5),
                PrintFormItem(task_id=2, print_form_id=6),
            ]
        )
        assert len(results) == 2
        assert results[0] == b"%PDF-1"
        assert results[1] == b"%PDF-2"
        await client.close()


# -- Avatar --


class TestSetAvatar:
    @respx.mock
    async def test_set_avatar(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}members/100500/avatar").mock(
            return_value=httpx.Response(
                200, json={"id": 100500, "first_name": "Ivan", "last_name": "Ivanov"}
            )
        )
        await client.auth()
        person = await client.set_avatar(100500, "abc-def-guid")
        assert person.id == 100500
        assert person.first_name == "Ivan"
        await client.close()


# -- Calendar enrichment --


class TestCalendar:
    @respx.mock
    async def test_calendar_with_params(self, client):
        _mock_auth()
        route = respx.get(f"{API_BASE}calendar").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1}]})
        )
        await client.auth()
        tasks = await client.get_calendar(
            from_date="2026-01-01",
            to_date="2026-01-31",
            filter_mask=5,
            all_accessed_tasks=True,
            item_count=50,
        )
        assert len(tasks) == 1

        # Verify params were sent correctly
        request = route.calls.last.request
        assert "filter_mask=5" in str(request.url)
        assert "all_accessed_tasks=y" in str(request.url)
        assert "item_count=50" in str(request.url)
        await client.close()


# -- CSV export --


class TestCSVExport:
    @respx.mock
    async def test_get_register_csv(self, client):
        _mock_auth()
        csv_content = "id,name,status\n1,Test,Open\n2,Other,Closed\n"
        respx.get(url__regex=r".*/forms/321/register.*").mock(
            return_value=httpx.Response(200, text=csv_content)
        )
        await client.auth()
        csv_text = await client.get_register_csv(321, steps=[1, 2])
        assert "id,name,status" in csv_text
        assert "Test" in csv_text
        await client.close()


# -- External ID --


class TestExternalId:
    @respx.mock
    async def test_get_member_external_id(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members/100").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100, "first_name": "A", "last_name": "B", "external_id": 42},
            )
        )
        await client.auth()
        ext_id = await client.get_member_external_id(100)
        assert ext_id == 42
        await client.close()

    @respx.mock
    async def test_get_member_external_id_none(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members/100").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100, "first_name": "A", "last_name": "B"},
            )
        )
        await client.auth()
        ext_id = await client.get_member_external_id(100)
        assert ext_id is None
        await client.close()

    @respx.mock
    async def test_get_members_external_ids_parallel(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members/100").mock(
            return_value=httpx.Response(
                200, json={"id": 100, "first_name": "A", "last_name": "B", "external_id": 42}
            )
        )
        respx.get(f"{API_BASE}members/200").mock(
            return_value=httpx.Response(200, json={"id": 200, "first_name": "C", "last_name": "D"})
        )
        await client.auth()
        ext_ids = await client.get_members_external_ids([100, 200])
        assert ext_ids == [42, None]
        await client.close()

    @respx.mock
    async def test_external_ids_with_error(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members/100").mock(
            return_value=httpx.Response(
                200, json={"id": 100, "first_name": "A", "last_name": "B", "external_id": 42}
            )
        )
        respx.get(f"{API_BASE}members/999").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        await client.auth()
        ext_ids = await client.get_members_external_ids([100, 999])
        assert ext_ids[0] == 42
        assert ext_ids[1] is None  # error → None
        await client.close()
