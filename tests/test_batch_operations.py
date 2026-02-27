"""Tests for batch operations: get_tasks, create_tasks, delete_tasks,
task_contexts, create_roles, update_roles, update_members."""

from __future__ import annotations

import httpx
import pytest
import respx

from aiopyrus.types.params import MemberUpdate, NewRole, NewTask, RoleUpdate
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


# -- get_tasks --


class TestGetTasks:
    @respx.mock
    async def test_parallel_fetch(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1, "text": "A"}})
        )
        respx.get(f"{API_BASE}tasks/2").mock(
            return_value=httpx.Response(200, json={"task": {"id": 2, "text": "B"}})
        )
        await client.auth()
        tasks = await client.get_tasks([1, 2])
        assert len(tasks) == 2
        assert tasks[0].id == 1
        assert tasks[1].id == 2
        await client.close()

    @respx.mock
    async def test_skips_errors(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1}})
        )
        respx.get(f"{API_BASE}tasks/2").mock(
            return_value=httpx.Response(404, json={"error": "not found", "error_code": "not_found"})
        )
        await client.auth()
        tasks = await client.get_tasks([1, 2])
        assert len(tasks) == 1
        assert tasks[0].id == 1
        await client.close()


# -- create_tasks --


class TestCreateTasks:
    @respx.mock
    async def test_batch_create(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            side_effect=[
                httpx.Response(200, json={"task": {"id": 101}}),
                httpx.Response(200, json={"task": {"id": 102}}),
            ]
        )
        await client.auth()
        results = await client.create_tasks(
            [
                NewTask(text="Task A"),
                NewTask(text="Task B"),
            ]
        )
        assert len(results) == 2
        assert results[0].id == 101
        assert results[1].id == 102
        await client.close()

    @respx.mock
    async def test_batch_create_with_error(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            side_effect=[
                httpx.Response(200, json={"task": {"id": 101}}),
                httpx.Response(403, json={"error": "no access", "error_code": "forbidden"}),
            ]
        )
        await client.auth()
        results = await client.create_tasks(
            [
                NewTask(text="Task A"),
                NewTask(text="Task B"),
            ]
        )
        assert len(results) == 2
        assert results[0].id == 101
        assert isinstance(results[1], BaseException)
        await client.close()

    @respx.mock
    async def test_batch_create_form_task(self, client):
        """NewTask with form_id, responsible, fields."""
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            return_value=httpx.Response(200, json={"task": {"id": 201, "form_id": 321}})
        )
        await client.auth()
        results = await client.create_tasks(
            [
                NewTask(
                    form_id=321,
                    responsible=100500,
                    fields=[{"id": 1, "value": "test"}],
                ),
            ]
        )
        assert len(results) == 1
        assert results[0].id == 201
        await client.close()


# -- delete_tasks --


class TestDeleteTasks:
    @respx.mock
    async def test_batch_delete(self, client):
        _mock_auth()
        respx.delete(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        respx.delete(f"{API_BASE}tasks/2").mock(
            return_value=httpx.Response(200, json={"deleted": True})
        )
        await client.auth()
        results = await client.delete_tasks([1, 2])
        assert results == [True, True]
        await client.close()


# -- task_contexts --


class TestTaskContexts:
    @respx.mock
    async def test_batch_fetch_contexts(self, client):
        """task_contexts() returns list of TaskContext objects."""
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 1001,
                        "form_id": 321,
                        "fields": [{"id": 1, "type": "text", "name": "Name", "value": "A"}],
                    }
                },
            )
        )
        respx.get(f"{API_BASE}tasks/1002").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 1002,
                        "form_id": 321,
                        "fields": [{"id": 1, "type": "text", "name": "Name", "value": "B"}],
                    }
                },
            )
        )
        await client.auth()
        ctxs = await client.task_contexts([1001, 1002])
        assert len(ctxs) == 2
        assert ctxs[0].id == 1001
        assert ctxs[1].id == 1002
        assert ctxs[0]["Name"] == "A"
        assert ctxs[1]["Name"] == "B"
        await client.close()

    @respx.mock
    async def test_skips_failed_tasks(self, client):
        """task_contexts() skips tasks that fail to load (404, 403)."""
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1}})
        )
        respx.get(f"{API_BASE}tasks/2").mock(
            return_value=httpx.Response(404, json={"error": "not found", "error_code": "not_found"})
        )
        await client.auth()
        ctxs = await client.task_contexts([1, 2])
        assert len(ctxs) == 1
        assert ctxs[0].id == 1
        await client.close()

    @respx.mock
    async def test_empty_list(self, client):
        _mock_auth()
        await client.auth()
        ctxs = await client.task_contexts([])
        assert ctxs == []
        await client.close()


# -- create_roles --


class TestCreateRoles:
    @respx.mock
    async def test_batch_create_roles(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}roles").mock(
            side_effect=[
                httpx.Response(200, json={"id": 10, "name": "Admins"}),
                httpx.Response(200, json={"id": 11, "name": "Users"}),
            ]
        )
        await client.auth()
        results = await client.create_roles(
            [
                NewRole(name="Admins", member_ids=[1, 2]),
                NewRole(name="Users"),
            ]
        )
        assert len(results) == 2
        assert results[0].id == 10
        assert results[1].id == 11
        await client.close()


# -- update_roles --


class TestUpdateRoles:
    @respx.mock
    async def test_batch_update_roles(self, client):
        _mock_auth()
        respx.put(f"{API_BASE}roles/10").mock(
            return_value=httpx.Response(200, json={"id": 10, "name": "SuperAdmins"})
        )
        respx.put(f"{API_BASE}roles/11").mock(
            return_value=httpx.Response(200, json={"id": 11, "name": "Viewers"})
        )
        await client.auth()
        results = await client.update_roles(
            [
                RoleUpdate(role_id=10, name="SuperAdmins"),
                RoleUpdate(role_id=11, name="Viewers"),
            ]
        )
        assert len(results) == 2
        assert results[0].name == "SuperAdmins"
        assert results[1].name == "Viewers"
        await client.close()


# -- update_members --


class TestUpdateMembers:
    @respx.mock
    async def test_batch_update_members(self, client):
        _mock_auth()
        respx.put(f"{API_BASE}members/100").mock(
            return_value=httpx.Response(
                200, json={"id": 100, "first_name": "New", "last_name": "Name"}
            )
        )
        respx.put(f"{API_BASE}members/200").mock(
            return_value=httpx.Response(
                200, json={"id": 200, "first_name": "Other", "last_name": "Person"}
            )
        )
        await client.auth()
        results = await client.update_members(
            [
                MemberUpdate(member_id=100, first_name="New"),
                MemberUpdate(member_id=200, first_name="Other"),
            ]
        )
        assert len(results) == 2
        assert results[0].first_name == "New"
        assert results[1].first_name == "Other"
        await client.close()
