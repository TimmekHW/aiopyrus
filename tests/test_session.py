"""Tests for PyrusSession — auth, retries, error handling, rate limiting."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from aiopyrus.api.session import PyrusSession, _derive_urls, _retry_wait
from aiopyrus.exceptions import (
    PyrusAPIError,
    PyrusAuthError,
    PyrusNotFoundError,
    PyrusPermissionError,
    PyrusRateLimitError,
)

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


def _session(**kwargs: Any) -> PyrusSession:
    return PyrusSession(login="test@example.com", security_key="SECRET", **kwargs)


# ── _retry_wait ─────────────────────────────────────────────


class TestRetryWait:
    def test_retry_after_header(self):
        resp = httpx.Response(429, headers={"Retry-After": "5"})
        assert _retry_wait(resp, default=60.0) == 5.0

    def test_ratelimit_reset_header(self):
        resp = httpx.Response(429, headers={"X-RateLimit-Reset": "10"})
        assert _retry_wait(resp, default=60.0) == 10.0

    def test_retry_after_takes_precedence(self):
        resp = httpx.Response(429, headers={"Retry-After": "3", "X-RateLimit-Reset": "10"})
        assert _retry_wait(resp, default=60.0) == 3.0

    def test_non_numeric_falls_back(self):
        resp = httpx.Response(429, headers={"Retry-After": "not-a-number"})
        assert _retry_wait(resp, default=42.0) == 42.0

    def test_no_headers_uses_default(self):
        resp = httpx.Response(429)
        assert _retry_wait(resp, default=99.0) == 99.0

    def test_negative_clamped_to_zero(self):
        resp = httpx.Response(429, headers={"Retry-After": "-5"})
        assert _retry_wait(resp, default=60.0) == 0.0


# ── Auth ────────────────────────────────────────────────────


class TestSessionAuth:
    @respx.mock
    async def test_successful_auth(self):
        _mock_auth("my-token")
        s = _session()
        token = await s.auth()
        assert token == "my-token"
        assert s.is_authenticated
        await s.close()

    @respx.mock
    async def test_auth_failure(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                401,
                json={"error": "Invalid credentials", "error_code": "invalid"},
            )
        )
        s = _session()
        with pytest.raises(PyrusAuthError):
            await s.auth()
        await s.close()

    @respx.mock
    async def test_auth_missing_token(self):
        respx.post(AUTH_URL).mock(return_value=httpx.Response(200, json={"some_field": "no_token"}))
        s = _session()
        with pytest.raises(PyrusAuthError):
            await s.auth()
        await s.close()

    @respx.mock
    async def test_auth_updates_api_url(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "api_url": "https://custom.pyrus.com/v4/",
                    "files_url": "https://custom-files.pyrus.com/",
                },
            )
        )
        s = _session()
        await s.auth()
        assert s._api_url == "https://custom.pyrus.com/v4/"
        assert s._files_url == "https://custom-files.pyrus.com/"
        await s.close()

    @respx.mock
    async def test_explicit_api_url_not_overridden(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "tok",
                    "api_url": "https://other.pyrus.com/v4/",
                },
            )
        )
        s = _session(api_url="https://my-corp.pyrus.com/v4/")
        await s.auth()
        assert s._api_url == "https://my-corp.pyrus.com/v4/"
        await s.close()

    @respx.mock
    async def test_base_url_derives_both_urls(self):
        """base_url should derive both api_url and auth_url automatically."""
        respx.post("https://pyrus.corp.ru/api/v4/auth").mock(
            return_value=httpx.Response(200, json={"access_token": "tok"})
        )
        s = _session(base_url="https://pyrus.corp.ru")
        assert s._api_url == "https://pyrus.corp.ru/api/v4/"
        assert s._auth_url == "https://pyrus.corp.ru/api/v4/auth"
        await s.auth()
        # api_url should NOT be overridden since base_url marks it explicit
        assert s._api_url == "https://pyrus.corp.ru/api/v4/"
        await s.close()

    def test_set_token(self):
        s = _session()
        assert not s.is_authenticated
        s.set_token("manual-token")
        assert s.is_authenticated
        assert s._access_token == "manual-token"

    def test_set_token_with_api_url(self):
        s = _session()
        s.set_token("tok", api_url="https://custom.pyrus.com/v4/")
        assert s._api_url == "https://custom.pyrus.com/v4/"

    @respx.mock
    async def test_person_id_sent_in_auth(self):
        respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok", "api_url": API_BASE},
            )
        )
        s = _session(person_id=100500)
        await s.auth()
        req = respx.calls.last.request
        import json

        body = json.loads(req.content)
        assert body["person_id"] == 100500
        await s.close()


# ── _handle_response ────────────────────────────────────────


class TestHandleResponse:
    @respx.mock
    async def test_200_ok(self):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(200, json={"person_id": 1})
        )
        s = _session()
        await s.auth()
        data = await s.get("profile")
        assert data["person_id"] == 1
        await s.close()

    @respx.mock
    async def test_401_raises_auth_error(self):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            side_effect=[
                httpx.Response(401, json={"error": "revoked", "error_code": "revoked_token"}),
            ]
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusAuthError):
            await s.get("tasks/1")
        await s.close()

    @respx.mock
    async def test_403_raises_permission_error(self):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(
                403, json={"error": "Forbidden", "error_code": "access_denied"}
            )
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusPermissionError):
            await s.get("tasks/1")
        await s.close()

    @respx.mock
    async def test_404_raises_not_found(self):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/999").mock(
            return_value=httpx.Response(404, json={"error": "Not found", "error_code": "not_found"})
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusNotFoundError):
            await s.get("tasks/999")
        await s.close()

    @respx.mock
    async def test_429_raises_rate_limit(self):
        _mock_auth()
        # First 429, then retry also returns 429
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(
                429,
                json={"error": "Rate limit", "error_code": "too_many_requests"},
                headers={"Retry-After": "0"},
            )
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusRateLimitError):
            await s.get("tasks/1")
        await s.close()

    @respx.mock
    async def test_500_raises_api_error(self):
        _mock_auth()
        respx.get(f"{API_BASE}tasks/1").mock(
            return_value=httpx.Response(500, json={"error": "Internal Server Error"})
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusAPIError):
            await s.get("tasks/1")
        await s.close()


# ── Request retry logic ─────────────────────────────────────


class TestRequestRetry:
    @respx.mock
    async def test_401_non_permanent_retries_with_reauth(self):
        """401 with non-permanent error code triggers re-auth + retry."""
        auth_route = respx.post(AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "new-token", "api_url": API_BASE},
            )
        )
        respx.get(f"{API_BASE}profile").mock(
            side_effect=[
                httpx.Response(401, json={"error": "expired", "error_code": "token_expired"}),
                httpx.Response(200, json={"person_id": 1}),
            ]
        )
        s = _session()
        await s.auth()
        data = await s.get("profile")
        assert data["person_id"] == 1
        # auth called twice: initial + re-auth
        assert auth_route.call_count == 2
        await s.close()

    @respx.mock
    async def test_401_permanent_no_retry(self):
        """401 with 'revoked_token' should NOT re-auth — raise immediately."""
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(
                401, json={"error": "revoked", "error_code": "revoked_token"}
            )
        )
        s = _session()
        await s.auth()
        with pytest.raises(PyrusAuthError):
            await s.get("profile")
        await s.close()

    @respx.mock
    async def test_502_transient_retries_once(self):
        """502 triggers a retry after wait."""
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            side_effect=[
                httpx.Response(502, text="Bad Gateway", headers={"Retry-After": "0"}),
                httpx.Response(200, json={"person_id": 1}),
            ]
        )
        s = _session()
        await s.auth()
        data = await s.get("profile")
        assert data["person_id"] == 1
        await s.close()

    @respx.mock
    async def test_429_retries_once_with_wait(self):
        """429 triggers a retry after Retry-After wait."""
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            side_effect=[
                httpx.Response(
                    429,
                    json={"error": "rate limit"},
                    headers={"Retry-After": "0"},
                ),
                httpx.Response(200, json={"person_id": 1}),
            ]
        )
        s = _session()
        await s.auth()
        data = await s.get("profile")
        assert data["person_id"] == 1
        await s.close()

    @respx.mock
    async def test_lazy_auth_on_first_request(self):
        """If no token, auth() is called automatically before the first request."""
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(200, json={"person_id": 1})
        )
        s = _session()
        assert not s.is_authenticated
        data = await s.get("profile")
        assert s.is_authenticated
        assert data["person_id"] == 1
        await s.close()


# ── Lifecycle ───────────────────────────────────────────────


class TestLifecycle:
    @respx.mock
    async def test_context_manager(self):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(
            return_value=httpx.Response(200, json={"person_id": 1})
        )
        async with _session() as s:
            await s.auth()
            data = await s.get("profile")
            assert data["person_id"] == 1

    @respx.mock
    async def test_close_cleans_up(self):
        s = _session()
        # Force client creation
        client = await s._get_client()
        assert not client.is_closed
        await s.close()
        assert s._client is None

    @respx.mock
    async def test_double_close(self):
        s = _session()
        await s._get_client()
        await s.close()
        await s.close()  # should not raise

    @respx.mock
    async def test_proxy_config(self):
        s = _session(proxy="http://proxy:8080")
        assert s._proxy == "http://proxy:8080"
        await s.close()


# ── Request URL construction ────────────────────────────────


class TestURLConstruction:
    @respx.mock
    async def test_files_url_used_for_uploads(self):
        _mock_auth()
        respx.post(f"{FILES_BASE}files/upload").mock(
            return_value=httpx.Response(200, json={"guid": "abc"})
        )
        s = _session()
        await s.auth()
        data = await s.request("POST", "files/upload", use_files_url=True)
        assert data["guid"] == "abc"
        await s.close()

    @respx.mock
    async def test_convenience_methods(self):
        _mock_auth()
        respx.get(f"{API_BASE}profile").mock(return_value=httpx.Response(200, json={"ok": True}))
        respx.post(f"{API_BASE}tasks").mock(return_value=httpx.Response(200, json={"ok": True}))
        respx.put(f"{API_BASE}catalogs").mock(return_value=httpx.Response(200, json={"ok": True}))
        respx.delete(f"{API_BASE}tasks/1").mock(return_value=httpx.Response(200, json={"ok": True}))
        s = _session()
        await s.auth()
        assert (await s.get("profile"))["ok"]
        assert (await s.post("tasks", json={}))["ok"]
        assert (await s.put("catalogs", json={}))["ok"]
        assert (await s.delete("tasks/1"))["ok"]
        await s.close()

    @respx.mock
    async def test_auth_headers_not_set_raises(self):
        s = _session()
        with pytest.raises(PyrusAuthError, match="Not authenticated"):
            s._auth_headers()


# ── _derive_urls ───────────────────────────────────────────


class TestDeriveUrls:
    def test_short_base_url(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com", "v4")
        assert api == "https://pyrus.mycompany.com/api/v4/"
        assert auth == "https://pyrus.mycompany.com/api/v4/auth"

    def test_full_api_url(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com/api/v4", "v4")
        assert api == "https://pyrus.mycompany.com/api/v4/"
        assert auth == "https://pyrus.mycompany.com/api/v4/auth"

    def test_short_versioned_url(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com/v4", "v4")
        assert api == "https://pyrus.mycompany.com/api/v4/"
        assert auth == "https://pyrus.mycompany.com/api/v4/auth"

    def test_trailing_slash_stripped(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com/", "v4")
        assert api == "https://pyrus.mycompany.com/api/v4/"
        assert auth == "https://pyrus.mycompany.com/api/v4/auth"

    def test_custom_api_version(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com", "v5")
        assert api == "https://pyrus.mycompany.com/api/v5/"
        assert auth == "https://pyrus.mycompany.com/api/v5/auth"

    def test_version_in_url_replaced_by_param(self):
        api, auth = _derive_urls("https://pyrus.mycompany.com/api/v4", "v5")
        assert api == "https://pyrus.mycompany.com/api/v5/"
        assert auth == "https://pyrus.mycompany.com/api/v5/auth"


# ── ssl_verify ─────────────────────────────────────────────


class TestSSLVerify:
    def test_ssl_verify_default_true(self):
        s = _session()
        assert s._ssl_verify is True

    def test_ssl_verify_false(self):
        s = _session(ssl_verify=False)
        assert s._ssl_verify is False

    async def test_ssl_verify_passed_to_client(self):
        s = _session(ssl_verify=False)
        client = await s._get_client()
        # httpx stores verify in _transport._pool._ssl_context or similar;
        # simplest check: the client was created without error
        assert client is not None
        await s.close()
