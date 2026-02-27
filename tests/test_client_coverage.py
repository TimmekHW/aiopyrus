"""Tests for UserClient endpoints not yet covered — get_register params, get_calendar,
get_form, get_catalog, get_contacts, get_member, get_announcement, task_context,
find_members, form_permissions, upload_file (path), comment_task extended params.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

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


# ── get_register with parameters ─────────────────────────────


class TestGetRegisterParams:
    @respx.mock
    async def test_with_steps_and_filters(self, client):
        _mock_auth()
        route = respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1}]})
        )
        await client.auth()
        tasks = await client.get_register(
            321,
            steps=[1, 2],
            include_archived=True,
            field_ids=[10, 20],
            sort="id",
            item_count=50,
            created_after="2026-01-01",
            modified_before="2026-12-31",
            due_filter="overdue",
            field_filters={"fld5": "Moscow"},
        )
        assert len(tasks) == 1
        # Check query params were passed
        request = route.calls.last.request
        url_str = str(request.url)
        assert "steps=1%2C2" in url_str or "steps=1,2" in url_str
        assert "include_archived=y" in url_str
        await client.close()

    @respx.mock
    async def test_with_task_ids_and_dates(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": []})
        )
        await client.auth()
        tasks = await client.get_register(
            321,
            task_ids=[100, 200],
            created_before="2026-06-01",
            modified_after="2026-01-01",
            closed_before="2026-12-31",
            closed_after="2026-01-01",
            id_filter="gt1000",
        )
        assert tasks == []
        await client.close()


# ── get_register_post ─────────────────────────────────────────


class TestGetRegisterPost:
    @respx.mock
    async def test_basic(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}forms/321/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1}]})
        )
        await client.auth()
        tasks = await client.get_register_post(321, {"fld5": "Moscow", "steps": "1,2"})
        assert len(tasks) == 1
        body = json.loads(respx.calls.last.request.content)
        assert body["fld5"] == "Moscow"
        await client.close()


# ── get_calendar ──────────────────────────────────────────────


class TestGetCalendar:
    @respx.mock
    async def test_get_calendar(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}calendar").mock(
            return_value=httpx.Response(
                200,
                json={"tasks": [{"id": 1}, {"id": 2}]},
            )
        )
        await client.auth()
        tasks = await client.get_calendar(from_date="2026-01-01", to_date="2026-12-31")
        assert len(tasks) == 2
        await client.close()

    @respx.mock
    async def test_get_calendar_no_params(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}calendar").mock(return_value=httpx.Response(200, json={"tasks": []}))
        await client.auth()
        tasks = await client.get_calendar()
        assert tasks == []
        await client.close()


# ── get_form ──────────────────────────────────────────────────


class TestGetForm:
    @respx.mock
    async def test_get_form(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321").mock(
            return_value=httpx.Response(
                200,
                json={"id": 321, "name": "Requests", "fields": []},
            )
        )
        await client.auth()
        form = await client.get_form(321)
        assert form.id == 321
        assert form.name == "Requests"
        await client.close()


# ── get_catalog ───────────────────────────────────────────────


class TestGetCatalog:
    @respx.mock
    async def test_get_catalog(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}catalogs/999").mock(
            return_value=httpx.Response(
                200,
                json={
                    "catalog_id": 999,
                    "name": "Cities",
                    "items": [{"item_id": 1, "values": ["Moscow"]}],
                },
            )
        )
        await client.auth()
        cat = await client.get_catalog(999)
        assert cat.catalog_id == 999
        assert len(cat.items) == 1
        await client.close()


# ── get_contacts ──────────────────────────────────────────────


class TestGetContacts:
    @respx.mock
    async def test_get_contacts(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}contacts").mock(
            return_value=httpx.Response(
                200,
                json={"organizations": [{"organization_id": 1, "persons": []}]},
            )
        )
        await client.auth()
        contacts = await client.get_contacts()
        assert len(contacts.organizations) == 1
        await client.close()

    @respx.mock
    async def test_get_contacts_inactive(self, client):
        _mock_auth()
        route = respx.get(f"{API_BASE}contacts").mock(
            return_value=httpx.Response(
                200,
                json={"organizations": []},
            )
        )
        await client.auth()
        await client.get_contacts(include_inactive=True)
        url_str = str(route.calls.last.request.url)
        assert "include_inactive=true" in url_str
        await client.close()


# ── get_member ────────────────────────────────────────────────


class TestGetMember:
    @respx.mock
    async def test_get_member(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100500, "first_name": "Ivan", "last_name": "Ivanov"},
            )
        )
        await client.auth()
        person = await client.get_member(100500)
        assert person.id == 100500
        await client.close()


# ── get_announcement / get_announcements ──────────────────────


class TestGetAnnouncement:
    @respx.mock
    async def test_get_announcement(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}announcements/1").mock(
            return_value=httpx.Response(
                200,
                json={"announcement": {"id": 1, "text": "Hello"}},
            )
        )
        await client.auth()
        ann = await client.get_announcement(1)
        assert ann.id == 1
        assert ann.text == "Hello"
        await client.close()


# ── task_context ──────────────────────────────────────────────


class TestTaskContext:
    @respx.mock
    async def test_task_context(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "task": {
                        "id": 42,
                        "text": "Test",
                        "fields": [{"id": 1, "name": "Status", "type": "text", "value": "Open"}],
                    }
                },
            )
        )
        await client.auth()
        ctx = await client.task_context(42)
        assert ctx.id == 42
        assert ctx["Status"] == "Open"
        await client.close()


# ── find_members ──────────────────────────────────────────────


class TestFindMembers:
    @respx.mock
    async def test_find_members_multiple(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 1, "first_name": "Ivan", "last_name": "Ivanov"},
                        {"id": 2, "first_name": "Ivana", "last_name": "Petrova"},
                        {"id": 3, "first_name": "Petr", "last_name": "Petrov"},
                    ]
                },
            )
        )
        await client.auth()
        result = await client.find_members("Ivan")
        assert len(result) == 2  # Ivan Ivanov + Ivana
        await client.close()

    @respx.mock
    async def test_find_member_by_email(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {
                            "id": 1,
                            "first_name": "Ivan",
                            "last_name": "Ivanov",
                            "email": "ivan@example.com",
                        },
                    ]
                },
            )
        )
        await client.auth()
        person = await client.find_member("ivan@example")
        assert person is not None
        assert person.id == 1
        await client.close()


# ── Form permissions ──────────────────────────────────────────


class TestFormPermissions:
    @respx.mock
    async def test_get_form_permissions(self, client):
        _mock_auth()
        respx.get(f"{API_BASE}forms/321/permissions").mock(
            return_value=httpx.Response(200, json={"permissions": []})
        )
        await client.auth()
        result = await client.get_form_permissions(321)
        assert "permissions" in result
        await client.close()

    @respx.mock
    async def test_set_form_permissions(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}forms/321/permissions").mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        await client.auth()
        result = await client.set_form_permissions(321, {"user_id": 1, "level": "admin"})
        assert result["success"] is True
        await client.close()


# ── upload_file from path ─────────────────────────────────────


class TestUploadFilePath:
    @respx.mock
    async def test_upload_from_path(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}files/upload").mock(
            return_value=httpx.Response(200, json={"guid": "xyz-789", "md5_hash": "abc"})
        )
        await client.auth()
        # Create a temp file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"hello world")
            tmp_path = tmp.name
        result = await client.upload_file(tmp_path)
        assert result.guid == "xyz-789"
        Path(tmp_path).unlink(missing_ok=True)
        await client.close()

    @respx.mock
    async def test_upload_from_pathlib(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}files/upload").mock(
            return_value=httpx.Response(200, json={"guid": "xyz-789", "md5_hash": "abc"})
        )
        await client.auth()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"content")
            tmp_path = Path(tmp.name)
        result = await client.upload_file(tmp_path)
        assert result.guid == "xyz-789"
        tmp_path.unlink(missing_ok=True)
        await client.close()

    @respx.mock
    async def test_upload_from_file_object(self, client):
        """Test BinaryIO upload path."""
        _mock_auth()
        respx.post(f"{API_BASE}files/upload").mock(
            return_value=httpx.Response(200, json={"guid": "file-obj", "md5_hash": "abc"})
        )
        await client.auth()
        import io

        buf = io.BytesIO(b"file content from io")
        result = await client.upload_file(buf, filename="data.bin")
        assert result.guid == "file-obj"
        await client.close()


# ── comment_task extended parameters ──────────────────────────


class TestCommentTaskExtended:
    @respx.mock
    async def test_with_approvals_added(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, approvals_added=[[100500, 100501]])
        body = json.loads(respx.calls.last.request.content)
        assert body["approvals_added"] == [[{"id": 100500}, {"id": 100501}]]
        await client.close()

    @respx.mock
    async def test_with_scheduling(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(
            42,
            scheduled_date="2026-03-01",
            scheduled_datetime_utc="2026-03-01T10:00:00Z",
            due_date="2026-03-15",
            spent_minutes=60,
            skip_notification=True,
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["scheduled_date"] == "2026-03-01"
        assert body["spent_minutes"] == 60
        assert body["skip_notification"] is True
        await client.close()

    @respx.mock
    async def test_with_channel(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, text="Via email", channel="email")
        body = json.loads(respx.calls.last.request.content)
        assert body["channel"] == {"type": "email"}
        await client.close()

    @respx.mock
    async def test_with_participants_and_subscribers(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(
            42,
            participants_added=[100500],
            participants_removed=[100501],
            subscribers_added=[200],
            subscribers_removed=[201],
            comment_as_roles=[42],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["participants_added"] == [{"id": 100500}]
        assert body["subscribers_removed"] == [{"id": 201}]
        assert body["comment_as_roles"] == [{"id": 42}]
        await client.close()

    @respx.mock
    async def test_with_list_ids(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(
            42,
            added_list_ids=[1, 2],
            removed_list_ids=[3],
            cancel_due=True,
            cancel_schedule=True,
            skip_satisfaction=True,
            skip_auto_reopen=True,
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["added_list_ids"] == [1, 2]
        assert body["cancel_due"] is True
        assert body["cancel_schedule"] is True
        await client.close()

    @respx.mock
    async def test_edit_comment(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, edit_comment_id=555, text="Edited")
        body = json.loads(respx.calls.last.request.content)
        assert body["edit_comment_id"] == 555
        await client.close()

    @respx.mock
    async def test_reply_to_comment(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(42, reply_to_comment_id=555, text="Reply")
        body = json.loads(respx.calls.last.request.content)
        assert body["reply_note_id"] == 555
        await client.close()

    @respx.mock
    async def test_approvals_removed_and_rerequested(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.comment_task(
            42,
            approvals_removed=[100500],
            approvals_rerequested=[100501],
            subscribers_rerequested=[200],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["approvals_removed"] == [{"id": 100500}]
        assert body["approvals_rerequested"] == [{"id": 100501}]
        assert body["subscribers_rerequested"] == [{"id": 200}]
        await client.close()


# ── create_task extended parameters ───────────────────────────


class TestCreateTaskExtended:
    @respx.mock
    async def test_all_params(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1}})
        )
        await client.auth()
        await client.create_task(
            text="Task",
            formatted_text="<b>Task</b>",
            subject="Subject",
            fill_defaults=True,
            participants=[100500],
            subscribers=[200],
            due_date="2026-03-01",
            due="2026-03-01T10:00",
            duration=60,
            scheduled_date="2026-03-01",
            scheduled_datetime_utc="2026-03-01T10:00:00Z",
            parent_task_id=9999,
            list_ids=[1, 2],
            attachments=["guid1"],
        )
        body = json.loads(respx.calls.last.request.content)
        assert body["formatted_text"] == "<b>Task</b>"
        assert body["subject"] == "Subject"
        assert body["fill_defaults"] is True
        assert body["participants"] == [{"id": 100500}]
        assert body["subscribers"] == [{"id": 200}]
        assert body["due_date"] == "2026-03-01"
        assert body["duration"] == 60
        assert body["parent_task_id"] == 9999
        assert body["list_ids"] == [1, 2]
        assert body["attachments"] == [{"guid": "guid1"}]
        await client.close()


# ── Shortcut methods ──────────────────────────────────────────


class TestShortcutMethods:
    @respx.mock
    async def test_reopen_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.reopen_task(42, text="Reopening")
        body = json.loads(respx.calls.last.request.content)
        assert body["action"] == "reopened"
        await client.close()

    @respx.mock
    async def test_approve_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.approve_task(42, text="Approved")
        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == "approved"
        await client.close()

    @respx.mock
    async def test_reject_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.reject_task(42)
        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == "rejected"
        await client.close()

    @respx.mock
    async def test_acknowledge_task(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}tasks/42/comments").mock(
            return_value=httpx.Response(200, json={"task": {"id": 42}})
        )
        await client.auth()
        await client.acknowledge_task(42)
        body = json.loads(respx.calls.last.request.content)
        assert body["approval_choice"] == "acknowledged"
        await client.close()


# ── Announcements with attachments ────────────────────────────


class TestAnnouncementsExtended:
    @respx.mock
    async def test_create_with_attachments(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}announcements").mock(
            return_value=httpx.Response(200, json={"announcement": {"id": 1, "text": "News"}})
        )
        await client.auth()
        await client.create_announcement(text="News", attachments=["guid1"])
        body = json.loads(respx.calls.last.request.content)
        assert body["attachments"] == [{"guid": "guid1"}]
        await client.close()

    @respx.mock
    async def test_comment_with_attachments(self, client):
        _mock_auth()
        respx.post(f"{API_BASE}announcements/1/comments").mock(
            return_value=httpx.Response(200, json={"announcement": {"id": 1, "text": "News"}})
        )
        await client.auth()
        await client.comment_announcement(1, text="Reply", attachments=["guid2"])
        body = json.loads(respx.calls.last.request.content)
        assert body["attachments"] == [{"guid": "guid2"}]
        await client.close()
