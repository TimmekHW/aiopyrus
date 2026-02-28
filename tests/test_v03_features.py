"""Tests for v0.3.0 features: JWT refresh, URL helpers, SyncClient,
batch registers, streaming register."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
import respx

from aiopyrus.api.session import _jwt_exp, _web_base_from_api_url
from aiopyrus.sync import SyncClient
from aiopyrus.user.client import UserClient, _iter_json_array

AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
API_BASE = "https://api.pyrus.com/v4/"
FILES_BASE = "https://files.pyrus.com/"


def _make_jwt(exp: float, sub: str = "bot@example") -> str:
    """Build a minimal JWT with the given exp claim (no real signature)."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    payload_dict = {"sub": sub, "exp": exp}
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{sig.decode()}"


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
# 1. JWT preemptive refresh
# -----------------------------------------------------------------------


class TestJwtExp:
    def test_valid_jwt(self):
        exp = time.time() + 3600
        token = _make_jwt(exp)
        assert _jwt_exp(token) == pytest.approx(exp, abs=1)

    def test_opaque_token(self):
        assert _jwt_exp("opaque-string-no-dots") is None

    def test_malformed_base64(self):
        assert _jwt_exp("a.!!!invalid!!!.c") is None

    def test_no_exp_claim(self):
        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(b'{"sub":"bot"}').rstrip(b"=")
        sig = base64.urlsafe_b64encode(b"sig").rstrip(b"=")
        token = f"{header.decode()}.{payload.decode()}.{sig.decode()}"
        assert _jwt_exp(token) is None


class TestProactiveRefresh:
    @respx.mock
    async def test_refresh_before_expiry(self, client):
        # Token that expires in 30 seconds (< 60s threshold)
        exp_soon = time.time() + 30
        jwt_token = _make_jwt(exp_soon)
        _mock_auth(jwt_token)
        await client.auth()

        # Second auth call for the proactive refresh
        fresh_token = _make_jwt(time.time() + 3600)
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": fresh_token, "api_url": API_BASE, "files_url": FILES_BASE},
            )
        )
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(200, json={"person_id": 1})
        )
        await client.get_profile()
        # Token should have been refreshed
        assert client._session._access_token == fresh_token

    @respx.mock
    async def test_no_refresh_when_token_valid(self, client):
        # Token that expires in 2 hours (well above threshold)
        exp_later = time.time() + 7200
        jwt_token = _make_jwt(exp_later)
        _mock_auth(jwt_token)
        await client.auth()

        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(200, json={"person_id": 1})
        )
        await client.get_profile()
        # Token should NOT have been refreshed
        assert client._session._access_token == jwt_token


# -----------------------------------------------------------------------
# 2. URL helpers
# -----------------------------------------------------------------------


class TestWebBase:
    def test_cloud_api(self):
        assert _web_base_from_api_url("https://api.pyrus.com/v4/") == "https://pyrus.com"

    def test_onpremise(self):
        assert _web_base_from_api_url("https://pyrus.corp.ru/api/v4/") == "https://pyrus.corp.ru"

    def test_onpremise_no_trailing_slash(self):
        assert _web_base_from_api_url("https://pyrus.corp.ru/api/v4") == "https://pyrus.corp.ru"


class TestUrlHelpers:
    def test_task_url_cloud(self):
        c = UserClient(login="u@ex.com", security_key="K")
        assert c.get_task_url(12345678) == "https://pyrus.com/t#id12345678"

    def test_form_url_cloud(self):
        c = UserClient(login="u@ex.com", security_key="K")
        assert c.get_form_url(321) == "https://pyrus.com/form/321"

    def test_task_url_onpremise(self):
        c = UserClient(login="u@ex.com", security_key="K", base_url="https://pyrus.corp.ru")
        assert c.get_task_url(999) == "https://pyrus.corp.ru/t#id999"

    def test_form_url_onpremise(self):
        c = UserClient(login="u@ex.com", security_key="K", base_url="https://pyrus.corp.ru")
        assert c.get_form_url(42) == "https://pyrus.corp.ru/form/42"


# -----------------------------------------------------------------------
# 3. SyncClient
# -----------------------------------------------------------------------


class TestSyncClient:
    @respx.mock
    def test_sync_get_profile(self):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(
                200, json={"person_id": 1, "first_name": "Test", "last_name": "User"}
            )
        )
        with SyncClient(login="u@ex.com", security_key="K") as sc:
            profile = sc.get_profile()
            assert profile.person_id == 1

    @respx.mock
    def test_sync_url_helpers(self):
        """Non-async methods are proxied as-is."""
        with SyncClient(login="u@ex.com", security_key="K") as sc:
            assert "t#id42" in sc.get_task_url(42)

    @respx.mock
    def test_sync_auth(self):
        _mock_auth("tok-123")
        with SyncClient(login="u@ex.com", security_key="K") as sc:
            token = sc.auth()
            assert token == "tok-123"


# -----------------------------------------------------------------------
# 4. Batch get_registers
# -----------------------------------------------------------------------


class TestGetRegisters:
    @respx.mock
    async def test_two_forms(self, client):
        _mock_auth()
        await client.auth()
        for fid, tid in [(100, 1), (200, 2)]:
            respx.get(f"{API_BASE}forms/{fid}/register").mock(
                return_value=httpx.Response(
                    200,
                    json={"tasks": [{"id": tid, "text": f"task-{tid}"}]},
                )
            )
        regs = await client.get_registers([100, 200])
        assert set(regs.keys()) == {100, 200}
        assert regs[100][0].id == 1
        assert regs[200][0].id == 2

    @respx.mock
    async def test_partial_failure(self, client):
        _mock_auth()
        await client.auth()
        respx.get(f"{API_BASE}forms/100/register").mock(
            return_value=httpx.Response(200, json={"tasks": [{"id": 1}]})
        )
        respx.get(f"{API_BASE}forms/999/register").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        regs = await client.get_registers([100, 999])
        assert 100 in regs
        assert 999 not in regs


# -----------------------------------------------------------------------
# 5. Streaming register
# -----------------------------------------------------------------------


class TestIterJsonArray:
    async def test_single_chunk(self):
        data = json.dumps({"tasks": [{"id": 1}, {"id": 2}, {"id": 3}]})

        async def _chunks():
            yield data

        items = [obj async for obj in _iter_json_array(_chunks(), "tasks")]
        assert [i["id"] for i in items] == [1, 2, 3]

    async def test_split_across_chunks(self):
        full = json.dumps({"tasks": [{"id": 10, "text": "hello"}, {"id": 20, "text": "world"}]})
        mid = len(full) // 2

        async def _chunks():
            yield full[:mid]
            yield full[mid:]

        items = [obj async for obj in _iter_json_array(_chunks(), "tasks")]
        assert len(items) == 2
        assert items[0]["id"] == 10
        assert items[1]["id"] == 20

    async def test_empty_array(self):
        async def _chunks():
            yield '{"tasks": [], "count": 0}'

        items = [obj async for obj in _iter_json_array(_chunks(), "tasks")]
        assert items == []

    async def test_key_split_across_chunks(self):
        """The 'tasks' key itself is split between two chunks."""

        async def _chunks():
            yield '{"tas'
            yield 'ks": [{"id": 7}]}'

        items = [obj async for obj in _iter_json_array(_chunks(), "tasks")]
        assert len(items) == 1
        assert items[0]["id"] == 7

    async def test_many_small_chunks(self):
        data = json.dumps({"tasks": [{"id": i} for i in range(5)]})

        async def _chunks():
            for ch in data:
                yield ch

        items = [obj async for obj in _iter_json_array(_chunks(), "tasks")]
        assert [i["id"] for i in items] == [0, 1, 2, 3, 4]


class TestStreamRegister:
    @respx.mock
    async def test_stream_yields_tasks(self, client):
        _mock_auth()
        await client.auth()
        body = json.dumps({"tasks": [{"id": 1, "text": "A"}, {"id": 2, "text": "B"}]})
        respx.get(f"{API_BASE}forms/321/register").mock(return_value=httpx.Response(200, text=body))
        tasks = [t async for t in client.stream_register(321)]
        assert len(tasks) == 2
        assert tasks[0].id == 1
        assert tasks[1].id == 2
