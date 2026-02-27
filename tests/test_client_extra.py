"""Tests for UserClient endpoints not covered by test_client.py.

Covers: create_task, delete_task, comment_task params, get_inbox,
search_tasks, get_form_choices, create_catalog, sync_catalog,
update_catalog, create_member, upload_file, download_file,
create_role, update_role, create_announcement, comment_announcement.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

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


# ── Task creation ───────────────────────────────────────────


class TestCreateTask:
    @respx.mock
    async def test_create_simple_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            return_value=httpx.Response(200, json={"task": {"id": 999, "text": "New"}})
        )
        await client.auth()
        task = await client.create_task(text="New task")
        assert task.id == 999
        body = json.loads(respx.calls.last.request.content)
        assert body["text"] == "New task"
        await client.close()

    @respx.mock
    async def test_create_form_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1000, "form_id": 321}})
        )
        await client.auth()
        await client.create_task(
            form_id=321,
            fields=[{"id": 1, "value": "test"}],
            responsible=100500,
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["form_id"] == 321
        assert body["responsible"] == {"id": 100500}
        await client.close()

    @respx.mock
    async def test_create_task_with_approvals(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1001}})
        )
        await client.auth()
        await client.create_task(
            text="Approval task",
            approvals=[[100500, 100501]],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["approvals"] == [[{"id": 100500}, {"id": 100501}]]
        await client.close()


# ── Task deletion ───────────────────────────────────────────


class TestDeleteTask:
    @respx.mock
    async def test_delete_task(self, client):
        _mock_auth()
        respx.delete(f"{API_BASE}tasks/42").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        await client.auth()
        result = await client.delete_task(42)
        assert result is True
        await client.close()


# ── Comment task extended ───────────────────────────────────


class TestCommentTask:
    @respx.mock
    async def test_private_comment(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, text="Secret", private=True)
        body = json.loads(respx.calls.last.request.content)
        assert body["channel"] == {"type": "private_channel"}
        await client.close()

    @respx.mock
    async def test_comment_with_attachments(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, attachments=["guid1", "guid2"])
        body = json.loads(respx.calls.last.request.content)
        assert body["attachments"] == [{"guid": "guid1"}, {"guid": "guid2"}]
        await client.close()

    @respx.mock
    async def test_comment_task_shortcut_methods(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.finish_task(42, text="Done")
        body = json.loads(respx.calls.last.request.content)
        assert body["action"] == "finished"
        await client.close()


# ── Inbox ───────────────────────────────────────────────────


class TestInbox:
    @respx.mock
    async def test_get_inbox(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}inbox").mock(
            return_value=httpx.Response(
                200,
                json={"tasks": [{"id": 1}, {"id": 2}]},
            )
        )
        await client.auth()
        tasks = await client.get_inbox()
        assert len(tasks) == 2
        await client.close()


# ── Search tasks ────────────────────────────────────────────


class TestSearchTasks:
    @respx.mock
    async def test_search_across_forms(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1, "form_id": 321}]})
        )
        respx.get(f"{API_BASE}forms/322/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 2, "form_id": 322}]})
        )
        await client.auth()
        tasks = await client.search_tasks({321: [1], 322: None})
        assert len(tasks) == 2
        await client.close()

    @respx.mock
    async def test_search_partial_failure(self, client):
        """One form fails, the other succeeds — results from success are returned."""
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1}]})
        )
        respx.get(f"{API_BASE}forms/999/register").mock(
            return_value=httpx.Response(404, json={"error": "not found", "error_code": "not_found"})
        )
        await client.auth()
        tasks = await client.search_tasks({321: [1], 999: None})
        assert len(tasks) == 1
        assert tasks[0].id == 1
        await client.close()


# ── Form choices ────────────────────────────────────────────


class TestFormChoices:
    @respx.mock
    async def test_get_form_choices(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 321,
                    "name": "Test",
                    "fields": [
                        {
                            "id": 10,
                            "type": "multiple_choice",
                            "name": "Status",
                            "info": {
                                "options": [
                                    {"choice_id": 1, "choice_value": "Open"},
                                    {"choice_id": 2, "choice_value": "Closed"},
                                ]
                            },
                        }
                    ],
                },
            )
        )
        await client.auth()
        choices = await client.get_form_choices(321, 10)
        assert choices == {"Open": 1, "Closed": 2}
        await client.close()

    @respx.mock
    async def test_get_form_choices_no_info(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 321,
                    "name": "Test",
                    "fields": [{"id": 10, "type": "text", "name": "Name"}],
                },
            )
        )
        await client.auth()
        choices = await client.get_form_choices(321, 10)
        assert choices == {}
        await client.close()


# ── Catalog operations ──────────────────────────────────────


class TestCatalogOps:
    @respx.mock
    async def test_create_catalog(self, client):
        _mock_auth()
        respx.put(f"{API_BASE}catalogs").mock(
            return_value=httpx.Response(
                200,
                json={"catalog_id": 999, "name": "Cities", "items": []},
            )
        )
        await client.auth()
        cat = await client.create_catalog(
            "Cities",
            headers=["Name", "Code"],
            items=[["Moscow", "MSK"]],
        )
        assert cat.catalog_id == 999
        body = json.loads(respx.calls.last.request.content)
        assert body["catalog_headers"] == [{"name": "Name"}, {"name": "Code"}]
        await client.close()

    @respx.mock
    async def test_sync_catalog(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}catalogs/999").mock(
            return_value=httpx.Response(
                200,
                json={"catalog_id": 999, "applied": True},
            )
        )
        await client.auth()
        result = await client.sync_catalog(999, headers=["Name"], items=[["Moscow"]])
        assert result.applied is True
        await client.close()

    @respx.mock
    async def test_update_catalog(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}catalogs/999/diff").mock(
            return_value=httpx.Response(
                200,
                json={"catalog_id": 999, "applied": True},
            )
        )
        await client.auth()
        result = await client.update_catalog(999, upsert=[["NewCity"]], delete=["OldCity"])
        assert result.catalog_id == 999
        body = json.loads(respx.calls.last.request.content)
        assert body["upsert"] == [{"values": ["NewCity"]}]
        assert body["delete"] == ["OldCity"]
        await client.close()


# ── Member operations ───────────────────────────────────────


class TestMemberOps:
    @respx.mock
    async def test_create_member(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100501, "first_name": "Test", "last_name": "User"},
            )
        )
        await client.auth()
        person = await client.create_member(
            first_name="Test", last_name="User", email="test@example.com"
        )
        assert person.id == 100501
        await client.close()

    @respx.mock
    async def test_update_member(self, client):
        _mock_auth()
        respx.put(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100500, "first_name": "Updated", "last_name": "User"},
            )
        )
        await client.auth()
        person = await client.update_member(100500, first_name="Updated")
        assert person.first_name == "Updated"
        await client.close()

    @respx.mock
    async def test_block_member(self, client):
        _mock_auth()
        respx.delete(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(200, json={"banned": True})
        )
        await client.auth()
        result = await client.block_member(100500)
        assert result is True
        await client.close()

    @respx.mock
    async def test_find_members_all(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 1, "first_name": "Ivan", "last_name": "Ivanov"},
                        {"id": 2, "first_name": "Ivana", "last_name": "Petrovna"},
                    ]
                },
            )
        )
        await client.auth()
        result = await client.find_members("Ivan")
        assert len(result) == 2
        await client.close()


# ── Role operations ─────────────────────────────────────────


class TestRoleOps:
    @respx.mock
    async def test_create_role(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}roles").mock(
            return_value=httpx.Response(200, json={"id": 42, "name": "Admins"})
        )
        await client.auth()
        role = await client.create_role("Admins", member_ids=[100500])
        assert role.name == "Admins"
        await client.close()

    @respx.mock
    async def test_update_role(self, client):
        _mock_auth()
        respx.put(f"{API_BASE}roles/42").mock(
            return_value=httpx.Response(200, json={"id": 42, "name": "SuperAdmins"})
        )
        await client.auth()
        role = await client.update_role(42, name="SuperAdmins")
        assert role.name == "SuperAdmins"
        await client.close()


# ── Announcement operations ─────────────────────────────────


class TestAnnouncementOps:
    @respx.mock
    async def test_create_announcement(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}announcements").mock(
            return_value=httpx.Response(
                200,
                json={"announcement": {"id": 1, "text": "Hello"}},
            )
        )
        await client.auth()
        ann = await client.create_announcement(text="Hello")
        assert ann.text == "Hello"
        await client.close()

    @respx.mock
    async def test_comment_announcement(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}announcements/1/comments").mock(
            return_value=httpx.Response(
                200,
                json={"announcement": {"id": 1, "text": "Hello"}},
            )
        )
        await client.auth()
        ann = await client.comment_announcement(1, text="Reply")
        assert ann.id == 1
        await client.close()


# ── File operations ─────────────────────────────────────────


class TestFileOps:
    @respx.mock
    async def test_upload_file_bytes(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}files/upload").mock(
            return_value=httpx.Response(200, json={"guid": "abc-123", "md5_hash": "deadbeef"})
        )
        await client.auth()
        result = await client.upload_file(b"file content", filename="test.txt")
        assert result.guid == "abc-123"
        await client.close()

    @respx.mock
    async def test_download_file(self, client):
        _mock_auth()
        respx.get(f"{FILES_BASE}files/download/abc-123").mock(
            return_value=httpx.Response(200, content=b"file data")
        )
        await client.auth()
        data = await client.download_file("abc-123")
        assert data == b"file data"
        await client.close()
