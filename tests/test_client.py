"""Tests for UserClient API calls (mocked with respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from aiopyrus.exceptions import (
    PyrusAuthError,
    PyrusNotFoundError,
    PyrusPermissionError,
    PyrusRateLimitError,
)
from aiopyrus.user.client import UserClient

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"
FILES_BASE = "https://files.pyrus.com/"


def _mock_auth(token: str = "test-token"):
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


# ── Auth ─────────────────────────────────────────────────────


class TestAuth:
    @respx.mock
    async def test_successful_auth(self, client):
        _mock_auth("my-token")
        token = await client.auth()
        assert token == "my-token"

    @respx.mock
    async def test_auth_failure(self, client):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                401, json={"error": "Invalid credentials", "error_code": "invalid_credentials"}
            )
        )
        with pytest.raises(PyrusAuthError):
            await client.auth()

    @respx.mock
    async def test_lazy_auth_on_first_call(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(
                200,
                json={
                    "person_id": 100500,
                    "first_name": "Ivan",
                    "last_name": "Ivanov",
                },
            )
        )
        profile = await client.get_profile()
        assert profile.person_id == 100500
        await client.close()


# ── Profile ──────────────────────────────────────────────────


class TestProfile:
    @respx.mock
    async def test_get_profile(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(
                200,
                json={
                    "person_id": 100500,
                    "first_name": "Ivan",
                    "last_name": "Ivanov",
                    "email": "user@example.com",
                },
            )
        )
        await client.auth()
        profile = await client.get_profile()
        assert profile.first_name == "Ivan"
        assert profile.email == "user@example.com"
        await client.close()


# ── Tasks ────────────────────────────────────────────────────


class TestTasks:
    @respx.mock
    async def test_get_task(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/12345678").mock(
            return_value=httpx.Response(
                200,
                json={"task": {"id": 12345678, "text": "Test", "form_id": 321}},
            )
        )
        await client.auth()
        task = await client.get_task(12345678)
        assert task.id == 12345678
        assert task.form_id == 321
        await client.close()

    @respx.mock
    async def test_get_task_not_found(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/99999999").mock(
            return_value=httpx.Response(
                404, json={"error": "Task not found", "error_code": "not_found"}
            )
        )
        await client.auth()
        with pytest.raises(PyrusNotFoundError):
            await client.get_task(99999999)
        await client.close()

    @respx.mock
    async def test_comment_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/12345678/comments").mock(
            return_value=httpx.Response(
                200,
                json={"task": {"id": 12345678, "text": "Test"}},
            )
        )
        await client.auth()
        task = await client.comment_task(12345678, text="Hello")
        assert task.id == 12345678
        await client.close()


# ── Forms & Register ─────────────────────────────────────────


class TestForms:
    @respx.mock
    async def test_get_forms(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms").mock(
            return_value=httpx.Response(
                200,
                json={"forms": [{"id": 321, "name": "Requests", "fields": []}]},
            )
        )
        await client.auth()
        forms = await client.get_forms()
        assert len(forms) == 1
        assert forms[0].id == 321
        await client.close()

    @respx.mock
    async def test_get_register(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tasks": [
                        {"id": 1, "form_id": 321},
                        {"id": 2, "form_id": 321},
                    ]
                },
            )
        )
        await client.auth()
        tasks = await client.get_register(321)
        assert len(tasks) == 2
        await client.close()


# ── Members ──────────────────────────────────────────────────


class TestMembers:
    @respx.mock
    async def test_get_members(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 1, "first_name": "Ivan", "last_name": "Ivanov"},
                        {"id": 2, "first_name": "Petr", "last_name": "Petrov"},
                    ]
                },
            )
        )
        await client.auth()
        members = await client.get_members()
        assert len(members) == 2
        assert members[0].first_name == "Ivan"
        await client.close()

    @respx.mock
    async def test_find_member(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 1, "first_name": "Ivan", "last_name": "Ivanov"},
                        {"id": 2, "first_name": "Petr", "last_name": "Petrov"},
                    ]
                },
            )
        )
        await client.auth()
        person = await client.find_member("Ivan Ivanov")
        assert person is not None
        assert person.id == 1
        await client.close()

    @respx.mock
    async def test_find_member_not_found(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200, json={"members": [{"id": 1, "first_name": "Ivan", "last_name": "Ivanov"}]}
            )
        )
        await client.auth()
        person = await client.find_member("Nobody")
        assert person is None
        await client.close()


# ── Error codes ──────────────────────────────────────────────


class TestErrors:
    @respx.mock
    async def test_403(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(
                403, json={"error": "Forbidden", "error_code": "access_denied"}
            )
        )
        await client.auth()
        with pytest.raises(PyrusPermissionError):
            await client.get_task(1)
        await client.close()

    @respx.mock
    async def test_429(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(
                429,
                json={"error": "Rate limit", "error_code": "too_many_requests"},
                headers={"Retry-After": "0"},
            )
        )
        await client.auth()
        with pytest.raises(PyrusRateLimitError):
            await client.get_task(1)
        await client.close()


# ── Catalogs ─────────────────────────────────────────────────


class TestCatalogs:
    @respx.mock
    async def test_get_catalogs(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}catalogs").mock(
            return_value=httpx.Response(
                200,
                json={"catalogs": [{"catalog_id": 1, "name": "Cities"}]},
            )
        )
        await client.auth()
        catalogs = await client.get_catalogs()
        assert len(catalogs) == 1
        assert catalogs[0].name == "Cities"
        await client.close()


# ── Roles ────────────────────────────────────────────────────


class TestRoles:
    @respx.mock
    async def test_get_roles(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}roles").mock(
            return_value=httpx.Response(
                200,
                json={"roles": [{"id": 42, "name": "Admins"}]},
            )
        )
        await client.auth()
        roles = await client.get_roles()
        assert len(roles) == 1
        assert roles[0].name == "Admins"
        await client.close()


# ── Announcements ────────────────────────────────────────────


class TestAnnouncements:
    @respx.mock
    async def test_get_announcements(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}announcements").mock(
            return_value=httpx.Response(
                200,
                json={"announcements": [{"id": 1, "text": "Hello"}]},
            )
        )
        await client.auth()
        ann = await client.get_announcements()
        assert len(ann) == 1
        assert ann[0].text == "Hello"
        await client.close()


# ── Context manager ──────────────────────────────────────────


class TestContextManager:
    @respx.mock
    async def test_async_with(self):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(
                200, json={"person_id": 1, "first_name": "Test", "last_name": "User"}
            )
        )
        async with UserClient(login="test@example.com", security_key="SECRET") as c:
            profile = await c.get_profile()
            assert profile.first_name == "Test"
