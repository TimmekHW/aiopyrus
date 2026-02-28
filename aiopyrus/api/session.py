from __future__ import annotations

import asyncio
import base64
import json as _json
import logging
import re
import time
from collections.abc import AsyncIterator
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


def _jwt_exp(token: str) -> float | None:
    """Extract ``exp`` (Unix timestamp) from a JWT without verifying signature.

    Returns ``None`` for opaque or malformed tokens — caller falls back to
    the regular 401-based refresh.
    """
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
        return float(payload["exp"])
    except Exception:  # noqa: BLE001
        return None


def _web_base_from_api_url(api_url: str) -> str:
    """Derive the browser-facing base URL from the API URL.

    ``https://api.pyrus.com/v4/``          → ``https://pyrus.com``
    ``https://pyrus.corp.ru/api/v4/``      → ``https://pyrus.corp.ru``
    """
    base = re.sub(r"(/api)?/v\d+/?$", "", api_url.rstrip("/"))
    base = re.sub(r"^(https?://)api\.", r"\1", base)
    return base


def _derive_urls(base_url: str, api_version: str) -> tuple[str, str]:
    """Derive ``(api_url, auth_url)`` from a single *base_url*.

    Accepts both short and full forms::

        "https://pyrus.mycompany.com"
        "https://pyrus.mycompany.com/api/v4"

    On-premise Pyrus uses ``/api/v4/`` for both auth and API calls
    (unlike cloud where API is on a separate subdomain ``api.pyrus.com/v4/``).

    Returns ``(api_url, auth_url)`` with correct trailing slashes.
    """
    base = base_url.rstrip("/")
    # Strip existing version suffix so we can rebuild with api_version
    host_base = re.sub(r"(/api)?/v\d+$", "", base)
    api_url = f"{host_base}/api/{api_version}/"
    auth_url = f"{host_base}/api/{api_version}/auth"
    return api_url, auth_url


class PyrusSession:
    """Low-level async HTTPX session for Pyrus API.

    Handles authentication, token refresh, and raw HTTP calls.

    For corporate / self-hosted Pyrus instances supply ``base_url``::

        session = PyrusSession(
            login="user@example.com",
            security_key="KEY",
            base_url="https://pyrus.mycompany.com",
            ssl_verify=False,
        )
    """

    def __init__(
        self,
        login: str,
        security_key: str,
        person_id: int | None = None,
        *,
        timeout: float = 30.0,
        base_url: str | None = None,
        api_version: str = "v4",
        auth_url: str | None = None,
        api_url: str | None = None,
        files_url: str | None = None,
        proxy: str | None = None,
        ssl_verify: bool = True,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
    ) -> None:
        self._login = login
        self._security_key = security_key
        self._person_id = person_id
        self._timeout = timeout
        self._proxy = proxy
        self._ssl_verify = ssl_verify
        self._rate_limiter = RateLimiter(
            requests_per_second=requests_per_second,
            requests_per_minute=requests_per_minute,
            requests_per_10min=requests_per_10min,
        )

        # URL resolution priority: base_url > explicit api_url/auth_url > defaults
        if base_url is not None:
            derived_api, derived_auth = _derive_urls(base_url, api_version)
            self._api_url: str = api_url or derived_api
            self._auth_url: str = auth_url or derived_auth
            self._api_url_explicit = True
        else:
            self._auth_url = auth_url or _DEFAULT_AUTH_URL
            self._api_url = api_url or _DEFAULT_API_URL
            self._api_url_explicit = api_url is not None

        self._access_token: str | None = None
        self._token_expires_at: float | None = None
        self._files_url: str = files_url or _DEFAULT_FILES_URL
        self._client: httpx.AsyncClient | None = None
        self._auth_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self._timeout,
            "follow_redirects": True,
            "verify": self._ssl_verify,
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
        self._token_expires_at = _jwt_exp(token)

        # Update api_url / files_url from auth response (cloud Pyrus returns these)
        if not self._api_url_explicit and "api_url" in data:
            self._api_url = data["api_url"]
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

    @property
    def web_base(self) -> str:
        """Browser-facing base URL (e.g. ``https://pyrus.com``)."""
        return _web_base_from_api_url(self._api_url)

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

        # Lazy auth / proactive refresh — serialised so concurrent coroutines
        # don't all race to call auth() at the same time.
        async with self._auth_lock:
            if not self._access_token:
                await self.auth()
            elif self._token_expires_at is not None and time.time() > self._token_expires_at - 60:
                log.debug("Token expiring soon, refreshing proactively")
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
        try:
            response = await _do_request()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as exc:
            log.warning("Network error (%s), retrying in 5s …", exc)
            await asyncio.sleep(5.0)
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
                async with self._auth_lock:
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

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        use_files_url: bool = False,
    ) -> httpx.Response:
        """Аутентифицированный запрос, возвращающий сырой httpx.Response.

        Make an authenticated API request and return the raw httpx.Response.
        Used for endpoints that return non-JSON content (PDF, CSV).
        """
        base = self._files_url if use_files_url else self._api_url
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
        client = await self._get_client()
        async with self._auth_lock:
            if not self._access_token:
                await self.auth()
        await self._rate_limiter.acquire()
        headers = self._auth_headers()
        response = await client.request(method, url, params=params, headers=headers)
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def stream_get(
        self,
        path: str,
        *,
        params: dict | None = None,
    ) -> AsyncIterator[str]:
        """Authenticated streaming GET, yields text chunks.

        Аутентифицированный потоковый GET, выдаёт текстовые чанки.
        """
        url = f"{self._api_url.rstrip('/')}/{path.lstrip('/')}"
        client = await self._get_client()
        async with self._auth_lock:
            if not self._access_token or (
                self._token_expires_at is not None and time.time() > self._token_expires_at - 60
            ):
                await self.auth()
        await self._rate_limiter.acquire()
        headers = self._auth_headers()
        async with client.stream("GET", url, params=params, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_text():
                yield chunk

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> PyrusSession:
        await self._get_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
