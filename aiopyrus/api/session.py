from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from aiopyrus.exceptions import (
    PyrusAPIError,
    PyrusAuthError,
    PyrusNotFoundError,
    PyrusPermissionError,
    PyrusRateLimitError,
)
from aiopyrus.utils.rate_limiter import RateLimiter

log = logging.getLogger("aiopyrus.session")

_DEFAULT_AUTH_URL = "https://accounts.pyrus.com/api/v4/auth"
_DEFAULT_API_URL = "https://api.pyrus.com/v4/"
_DEFAULT_FILES_URL = "https://files.pyrus.com/"

# 401 codes that mean the token is permanently invalid — re-auth won't help
_PERMANENT_AUTH_ERRORS = frozenset({"revoked_token", "account_blocked"})

# Proxy / server errors that are transient and worth a single retry
_TRANSIENT_STATUS = frozenset({502, 503, 504})


def _retry_wait(response: httpx.Response, default: float) -> float:
    """Return how many seconds to wait before retrying.

    Checks ``Retry-After`` (standard) and ``X-RateLimit-Reset`` (Pyrus)
    headers; falls back to *default* if neither is present or parseable.
    """
    for header in ("Retry-After", "X-RateLimit-Reset"):
        value = response.headers.get(header)
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                pass
    return default


class PyrusSession:
    """Low-level async HTTPX session for Pyrus API.

    Handles authentication, token refresh, and raw HTTP calls.

    For corporate / self-hosted Pyrus instances supply ``api_url`` and
    ``auth_url`` explicitly, e.g.::

        session = PyrusSession(
            login="user@example.com",
            security_key="KEY",
            auth_url="https://pyrus.example.com/api/v4/auth",
            api_url="https://pyrus.example.com/v4/",
        )
    """

    def __init__(
        self,
        login: str,
        security_key: str,
        person_id: int | None = None,
        *,
        timeout: float = 30.0,
        auth_url: str | None = None,
        api_url: str | None = None,
        files_url: str | None = None,
        proxy: str | None = None,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
    ) -> None:
        self._login = login
        self._security_key = security_key
        self._person_id = person_id
        self._timeout = timeout
        self._proxy = proxy
        self._rate_limiter = RateLimiter(
            requests_per_second=requests_per_second,
            requests_per_minute=requests_per_minute,
            requests_per_10min=requests_per_10min,
        )

        # Custom URLs override defaults; api_url is also updated from auth response
        self._auth_url: str = auth_url or _DEFAULT_AUTH_URL
        self._access_token: str | None = None
        self._api_url: str = api_url or _DEFAULT_API_URL
        self._files_url: str = files_url or _DEFAULT_FILES_URL
        # Track whether api_url was explicitly set (don't override with auth response then)
        self._api_url_explicit: bool = api_url is not None

        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
        }
        if self._proxy:
            kwargs["proxy"] = self._proxy
            log.debug("Using proxy: %s", self._proxy)
        return httpx.AsyncClient(**kwargs)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._build_client()
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTPX client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def auth(self) -> str:
        """Authenticate with the Pyrus API and store the access token.

        Returns the access_token string.
        """
        payload: dict[str, Any] = {
            "login": self._login,
            "security_key": self._security_key,
        }
        if self._person_id is not None:
            payload["person_id"] = self._person_id

        client = await self._get_client()
        response = await client.post(self._auth_url, json=payload)

        data = response.json()

        if response.status_code != 200 or "access_token" not in data:
            error = data.get("error", "Authentication failed")
            error_code = data.get("error_code")
            raise PyrusAuthError(error, error_code, response.status_code)

        token: str = data["access_token"]
        self._access_token = token

        # Only update api_url / files_url from the response if not explicitly set
        # and if the server returns them (standard cloud Pyrus does; corp instances may not).
        if not self._api_url_explicit:
            if "api_url" in data:
                self._api_url = data["api_url"]
            elif "api_url" not in data:
                # Corp instance: derive api_url from auth_url (strip /auth suffix)
                base = self._auth_url
                if base.endswith("/auth"):
                    self._api_url = base[: -len("auth")]  # keep trailing slash
        if "files_url" in data:
            self._files_url = data["files_url"]

        log.debug("Authenticated as %s (api_url=%s)", self._login, self._api_url)
        return token

    def set_token(self, token: str, api_url: str | None = None) -> None:
        """Manually set the access token (e.g. from a webhook payload)."""
        self._access_token = token
        if api_url:
            self._api_url = api_url

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise PyrusAuthError("Not authenticated. Call auth() first.", status_code=401)
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse the response and raise appropriate exceptions on errors."""
        try:
            data: dict = response.json()
        except Exception:
            data = {}

        remaining = response.headers.get("X-RateLimit-Remaining")
        log.debug(
            "   status=%d  keys=%s  rl_remaining=%s",
            response.status_code,
            list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            remaining,
        )

        if response.status_code == 200:
            return data

        error = data.get("error", response.text or "Unknown error")
        error_code = data.get("error_code")

        if response.status_code == 401:
            raise PyrusAuthError(error, error_code, 401)
        if response.status_code == 403:
            raise PyrusPermissionError(error, error_code, 403)
        if response.status_code == 404:
            raise PyrusNotFoundError(error, error_code, 404)
        if response.status_code == 429:
            raise PyrusRateLimitError(error, error_code, 429)

        raise PyrusAPIError(error, error_code, response.status_code)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict | None = None,
        data: Any = None,
        files: Any = None,
        headers: dict | None = None,
        use_files_url: bool = False,
    ) -> dict[str, Any]:
        """Make an authenticated API request.

        Auto-retries once on 401 by re-authenticating.
        Blocks if the configured rate limit is reached.
        """
        base = self._files_url if use_files_url else self._api_url
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"

        client = await self._get_client()

        # Lazy auth: authenticate on first API call if no token yet
        if not self._access_token:
            await self.auth()

        # Rate limiting: block here if needed (counted once per logical request)
        await self._rate_limiter.acquire()

        req_headers = {**self._auth_headers()}
        if headers:
            req_headers.update(headers)

        log.debug(
            "→ %s %s  body=%s", method, url, list(json.keys()) if isinstance(json, dict) else json
        )

        async def _do_request() -> httpx.Response:
            return await client.request(
                method,
                url,
                json=json,
                params=params,
                data=data,
                files=files,
                headers=req_headers,
            )

        t0 = time.perf_counter()
        response = await _do_request()

        # --- 401: token expired → re-auth and retry once (skip if permanently revoked)
        if response.status_code == 401 and self._login:
            try:
                err_code = response.json().get("error_code", "")
            except Exception:
                err_code = ""
            if err_code not in _PERMANENT_AUTH_ERRORS:
                log.debug("Token expired (%s), re-authenticating …", err_code or "unknown")
                await self.auth()
                req_headers.update(self._auth_headers())
                t0 = time.perf_counter()
                response = await _do_request()

        # --- 429: server-side rate limit → honour Retry-After and retry once
        elif response.status_code == 429:
            wait = _retry_wait(response, default=60.0)
            log.warning("Server rate limit (429), waiting %.0fs before retry …", wait)
            await asyncio.sleep(wait)
            t0 = time.perf_counter()
            response = await _do_request()

        # --- 502 / 503 / 504: transient proxy error (Angie / NGINX) → retry once
        elif response.status_code in _TRANSIENT_STATUS:
            wait = _retry_wait(response, default=5.0)
            log.warning(
                "Transient proxy error %d, retrying in %.0fs …",
                response.status_code,
                wait,
            )
            await asyncio.sleep(wait)
            t0 = time.perf_counter()
            response = await _do_request()

        elapsed = time.perf_counter() - t0
        log.debug("← %s %s  %.0fms", method, path, elapsed * 1000)
        return await self._handle_response(response)

    # Convenience shorthands
    async def get(self, path: str, *, params: dict | None = None) -> dict:
        return await self.request("GET", path, params=params)

    async def post(
        self, path: str, *, json: Any = None, files: Any = None, data: Any = None
    ) -> dict:
        return await self.request("POST", path, json=json, files=files, data=data)

    async def put(self, path: str, *, json: Any = None) -> dict:
        return await self.request("PUT", path, json=json)

    async def delete(self, path: str) -> dict:
        return await self.request("DELETE", path)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> PyrusSession:
        await self._get_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
