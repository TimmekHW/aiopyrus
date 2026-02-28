"""Tests for v0.4.0 features: find_by_email, approval helpers,
file size validation, filtered streaming."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from aiopyrus.exceptions import PyrusFileSizeError
from aiopyrus.types.task import ApprovalChoice, ApprovalEntry, Task
from aiopyrus.types.user import Person
from aiopyrus.user.client import _MAX_UPLOAD_SIZE, UserClient

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


# -----------------------------------------------------------------------
# 1. find_member_by_email / find_members_by_emails
# -----------------------------------------------------------------------

MEMBERS_RESPONSE = {
    "members": [
        {"id": 1, "first_name": "Alice", "last_name": "Smith", "email": "alice@corp.com"},
        {"id": 2, "first_name": "Bob", "last_name": "Jones", "email": "bob@corp.com"},
        {"id": 3, "first_name": "Carol", "last_name": "White", "email": "carol@corp.com"},
        {"id": 4, "first_name": "Dave", "last_name": "Brown"},  # no email
    ]
}


class TestFindMemberByEmail:
    @respx.mock
    async def test_exact_match(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        person = await client.find_member_by_email("alice@corp.com")
        assert person is not None
        assert person.id == 1
        assert person.first_name == "Alice"

    @respx.mock
    async def test_case_insensitive(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        person = await client.find_member_by_email("BOB@CORP.COM")
        assert person is not None
        assert person.id == 2

    @respx.mock
    async def test_not_found(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        person = await client.find_member_by_email("nobody@corp.com")
        assert person is None


class TestFindMembersByEmails:
    @respx.mock
    async def test_multiple_emails(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        found = await client.find_members_by_emails(["alice@corp.com", "carol@corp.com"])
        assert len(found) == 2
        assert found["alice@corp.com"].id == 1
        assert found["carol@corp.com"].id == 3

    @respx.mock
    async def test_partial_match(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        found = await client.find_members_by_emails(["alice@corp.com", "nobody@x.com"])
        assert len(found) == 1
        assert "alice@corp.com" in found

    @respx.mock
    async def test_empty_result(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(200, json=MEMBERS_RESPONSE)
        )
        found = await client.find_members_by_emails(["x@x.com", "y@y.com"])
        assert found == {}


# -----------------------------------------------------------------------
# 2. Approval helpers on Task
# -----------------------------------------------------------------------


def _make_task_with_approvals() -> Task:
    return Task(
        id=12345678,
        approvals=[
            # Step 1: two approvers
            [
                ApprovalEntry(
                    person=Person(id=1, first_name="Alice", last_name="Smith", email="a@x.com"),
                    approval_choice=ApprovalChoice.approved,
                ),
                ApprovalEntry(
                    person=Person(id=2, first_name="Bob", last_name="Jones", email="b@x.com"),
                    approval_choice=ApprovalChoice.waiting,
                ),
            ],
            # Step 2: one approver
            [
                ApprovalEntry(
                    person=Person(id=3, first_name="Carol", last_name="White", email="c@x.com"),
                    approval_choice=ApprovalChoice.rejected,
                ),
            ],
        ],
    )


class TestGetApprovals:
    def test_all_on_step(self):
        task = _make_task_with_approvals()
        approvals = task.get_approvals(1)
        assert len(approvals) == 2
        assert approvals[0].person.id == 1
        assert approvals[1].person.id == 2

    def test_filter_by_choice_string(self):
        task = _make_task_with_approvals()
        approved = task.get_approvals(1, choice="approved")
        assert len(approved) == 1
        assert approved[0].person.id == 1

    def test_filter_by_choice_enum(self):
        task = _make_task_with_approvals()
        waiting = task.get_approvals(1, choice=ApprovalChoice.waiting)
        assert len(waiting) == 1
        assert waiting[0].person.id == 2

    def test_filter_rejected(self):
        task = _make_task_with_approvals()
        rejected = task.get_approvals(2, choice="rejected")
        assert len(rejected) == 1
        assert rejected[0].person.id == 3

    def test_empty_approvals(self):
        task = Task(id=1)
        assert task.get_approvals(1) == []

    def test_invalid_step(self):
        task = _make_task_with_approvals()
        assert task.get_approvals(0) == []
        assert task.get_approvals(99) == []

    def test_waiting_includes_none_choice(self):
        """ApprovalEntry with approval_choice=None should match 'waiting'."""
        task = Task(
            id=1,
            approvals=[
                [
                    ApprovalEntry(
                        person=Person(id=10, first_name="X", last_name="Y"),
                        approval_choice=None,
                    ),
                ]
            ],
        )
        waiting = task.get_approvals(1, choice="waiting")
        assert len(waiting) == 1
        assert waiting[0].person.id == 10


class TestApprovalsByStep:
    def test_dict_structure(self):
        task = _make_task_with_approvals()
        by_step = task.approvals_by_step
        assert set(by_step.keys()) == {1, 2}
        assert len(by_step[1]) == 2
        assert len(by_step[2]) == 1

    def test_empty(self):
        task = Task(id=1)
        assert task.approvals_by_step == {}


class TestApproverConvenience:
    def test_names(self):
        task = _make_task_with_approvals()
        names = task.get_approver_names(1)
        assert names == ["Alice Smith", "Bob Jones"]

    def test_names_filtered(self):
        task = _make_task_with_approvals()
        names = task.get_approver_names(1, choice="approved")
        assert names == ["Alice Smith"]

    def test_emails(self):
        task = _make_task_with_approvals()
        emails = task.get_approver_emails(1)
        assert emails == ["a@x.com", "b@x.com"]

    def test_emails_skips_none(self):
        task = Task(
            id=1,
            approvals=[
                [
                    ApprovalEntry(
                        person=Person(id=1, first_name="X", last_name="Y"),
                        approval_choice=ApprovalChoice.approved,
                    ),
                ]
            ],
        )
        # Person has no email
        emails = task.get_approver_emails(1)
        assert emails == []

    def test_ids(self):
        task = _make_task_with_approvals()
        ids = task.get_approver_ids(2)
        assert ids == [3]


# -----------------------------------------------------------------------
# 3. File size validation
# -----------------------------------------------------------------------


class TestFileSizeValidation:
    @respx.mock
    async def test_raises_on_oversized_file(self, client):
        _mock_auth()
        await client.auth()
        # Create a fake "file" that is over 250 MB
        oversized = b"x" * (_MAX_UPLOAD_SIZE + 1)
        with pytest.raises(PyrusFileSizeError, match="250 MB"):
            await client.upload_file(oversized, filename="big.bin")

    @respx.mock
    async def test_ok_under_limit(self, client):
        _mock_auth()
        await client.auth()
        small = b"hello"
        respx.post(f"{API_BASE}files/upload").mock(
            return_value=httpx.Response(
                200, json={"guid": "abc-123", "md5_hash": "x", "content_length": 5}
            )
        )
        result = await client.upload_file(small, filename="small.txt")
        assert result.guid == "abc-123"


# -----------------------------------------------------------------------
# 4. Filtered streaming (predicate)
# -----------------------------------------------------------------------


class TestStreamRegisterPredicate:
    @respx.mock
    async def test_predicate_filters(self, client):
        _mock_auth()
        await client.auth()
        body = json.dumps(
            {
                "tasks": [
                    {"id": 1, "current_step": 1},
                    {"id": 2, "current_step": 2},
                    {"id": 3, "current_step": 2},
                    {"id": 4, "current_step": 3},
                ]
            }
        )
        respx.get(f"{API_BASE}forms/321/register").mock(return_value=httpx.Response(200, text=body))
        tasks = [
            t async for t in client.stream_register(321, predicate=lambda t: t.current_step == 2)
        ]
        assert len(tasks) == 2
        assert tasks[0].id == 2
        assert tasks[1].id == 3

    @respx.mock
    async def test_no_predicate_yields_all(self, client):
        _mock_auth()
        await client.auth()
        body = json.dumps({"tasks": [{"id": 1}, {"id": 2}]})
        respx.get(f"{API_BASE}forms/321/register").mock(return_value=httpx.Response(200, text=body))
        tasks = [t async for t in client.stream_register(321)]
        assert len(tasks) == 2

    @respx.mock
    async def test_predicate_all_filtered_out(self, client):
        _mock_auth()
        await client.auth()
        body = json.dumps({"tasks": [{"id": 1}, {"id": 2}]})
        respx.get(f"{API_BASE}forms/321/register").mock(return_value=httpx.Response(200, text=body))
        tasks = [t async for t in client.stream_register(321, predicate=lambda t: False)]
        assert tasks == []
