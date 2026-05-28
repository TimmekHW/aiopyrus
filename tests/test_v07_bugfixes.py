"""Regression tests for v0.7.2 hotfixes.

Bug #1: ``Channel.type`` rejected unknown values (e.g. ``delay_escalation``
from corp / on-premise Pyrus), crashing the entire ``Task`` parse.

Bug #2: ``find_member()`` couldn't resolve a numeric string (``"100500"``) —
those typically come from databases/CSV where ``person_id`` is stored as text.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from aiopyrus.types.task import Channel, ChannelType, Comment, Task
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
def client() -> UserClient:
    return UserClient(login="test@example.com", security_key="SECRET")


# ── Bug #1: unknown Channel.type does not crash Task parsing ────────────────


class TestChannelTypeForwardCompat:
    def test_unknown_channel_type_parses(self):
        """Pyrus on-premise sends server-internal channel types not in our enum
        (observed: ``delay_escalation``). Reading must not fail."""
        ch = Channel.model_validate({"type": "delay_escalation"})
        assert ch.type == "delay_escalation"

    def test_known_channel_type_still_parses_as_string(self):
        ch = Channel.model_validate({"type": "email"})
        assert ch.type == "email"

    def test_channel_type_none(self):
        ch = Channel.model_validate({"type": None})
        assert ch.type is None

    def test_task_with_unknown_channel_in_comment_parses(self):
        """Full Task with ``delay_escalation`` channel in a comment must parse."""
        task = Task.model_validate(
            {
                "id": 84307477,
                "comments": [
                    {"id": 1, "text": "hi"},
                    {"id": 9, "channel": {"type": "delay_escalation"}},
                ],
            }
        )
        assert task.id == 84307477
        assert len(task.comments) == 2
        assert task.comments[1].channel is not None
        assert task.comments[1].channel.type == "delay_escalation"

    def test_channel_type_enum_constants_still_usable_for_sending(self):
        """Backwards compat: ``ChannelType.email`` is still a usable string."""
        assert ChannelType.email.value == "email"
        assert ChannelType.email == "email"  # str-Enum equality

    def test_comment_with_unknown_channel(self):
        c = Comment.model_validate({"id": 1, "channel": {"type": "future_channel_we_dont_know"}})
        assert c.channel is not None
        assert c.channel.type == "future_channel_we_dont_know"


# ── Bug #2: find_member accepts numeric strings as person_id ────────────────


class TestFindMemberNumeric:
    @respx.mock
    async def test_find_member_int(self, client: UserClient):
        """``find_member(100500)`` -> direct ``GET /members/{id}``."""
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": 100500,
                    "first_name": "Данил",
                    "last_name": "Колбасенко",
                    "email": "user@example.com",
                },
            )
        )
        await client.auth()
        person = await client.find_member(100500)
        assert person is not None
        assert person.id == 100500
        assert person.first_name == "Данил"
        await client.close()

    @respx.mock
    async def test_find_member_numeric_string(self, client: UserClient):
        """Bug #2: ``find_member("100500")`` (e.g. from DB) must resolve as ID."""
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"},
            )
        )
        await client.auth()
        person = await client.find_member("100500")
        assert person is not None
        assert person.id == 100500
        await client.close()

    @respx.mock
    async def test_find_member_numeric_string_with_whitespace(self, client: UserClient):
        """Whitespace around a numeric ID still resolves as ID."""
        _mock_auth()
        respx.get(f"{API_BASE}members/42").mock(
            return_value=httpx.Response(200, json={"id": 42, "first_name": "X"})
        )
        await client.auth()
        person = await client.find_member("  42 ")
        assert person is not None
        assert person.id == 42
        await client.close()

    @respx.mock
    async def test_find_member_int_not_found_returns_none(self, client: UserClient):
        """Numeric ID not in Pyrus → ``None`` (not exception)."""
        _mock_auth()
        respx.get(f"{API_BASE}members/999999").mock(
            return_value=httpx.Response(404, json={"error": "not found", "error_code": "not_found"})
        )
        await client.auth()
        person = await client.find_member("999999")
        assert person is None
        await client.close()

    @respx.mock
    async def test_find_member_int_permission_denied_returns_none(self, client: UserClient):
        """Numeric ID forbidden (403) → ``None`` (not exception)."""
        _mock_auth()
        respx.get(f"{API_BASE}members/12345").mock(
            return_value=httpx.Response(403, json={"error": "no rights"})
        )
        await client.auth()
        person = await client.find_member("12345")
        assert person is None
        await client.close()

    @respx.mock
    async def test_find_member_non_numeric_still_searches_by_name(self, client: UserClient):
        """Regression: name-based search still works for non-numeric input."""
        _mock_auth()
        respx.get(f"{API_BASE}members").mock(
            return_value=httpx.Response(
                200,
                json={
                    "members": [
                        {"id": 1, "first_name": "Алиса", "last_name": "Тестова"},
                        {"id": 2, "first_name": "Данил", "last_name": "Колбасенко"},
                    ]
                },
            )
        )
        await client.auth()
        person = await client.find_member("Колбасенко")
        assert person is not None
        assert person.id == 2
        await client.close()

    @respx.mock
    async def test_find_member_negative_id_string_treated_as_id(self, client: UserClient):
        """``"-5"`` is still digit-like — treated as ID lookup (and returns None)."""
        _mock_auth()
        respx.get(f"{API_BASE}members/-5").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        await client.auth()
        person = await client.find_member("-5")
        assert person is None
        await client.close()


# ── New: explicit unambiguous lookup ────────────────────────────────────────


class TestFindMemberById:
    """Explicit ``find_member_by_id`` — для случаев когда в компании 3 тёзки
    и нужен строгий поиск по ID без auto-эвристик."""

    @respx.mock
    async def test_by_id_int(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(
                200,
                json={"id": 100500, "first_name": "Данил", "last_name": "Колбасенко"},
            )
        )
        await client.auth()
        person = await client.find_member_by_id(100500)
        assert person is not None
        assert person.id == 100500
        await client.close()

    @respx.mock
    async def test_by_id_numeric_string(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}members/100500").mock(
            return_value=httpx.Response(200, json={"id": 100500, "first_name": "X"})
        )
        await client.auth()
        person = await client.find_member_by_id("100500")
        assert person is not None
        assert person.id == 100500
        await client.close()

    @respx.mock
    async def test_by_id_not_found_returns_none(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}members/999999").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        await client.auth()
        person = await client.find_member_by_id(999999)
        assert person is None
        await client.close()

    @respx.mock
    async def test_by_id_forbidden_returns_none(self, client: UserClient):
        _mock_auth()
        respx.get(f"{API_BASE}members/777").mock(
            return_value=httpx.Response(403, json={"error": "no rights"})
        )
        await client.auth()
        person = await client.find_member_by_id(777)
        assert person is None
        await client.close()

    async def test_by_id_rejects_non_numeric_string(self, client: UserClient):
        """A non-numeric string is a usage error, not a 'not found' case."""
        import pytest

        with pytest.raises(ValueError, match="numeric"):
            await client.find_member_by_id("Колбасенко")
        await client.close()
