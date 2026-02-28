from __future__ import annotations


class PyrusError(Exception):
    """Base exception for all aiopyrus errors."""


class PyrusAPIError(PyrusError):
    """Raised when the Pyrus API returns an error response."""

    def __init__(
        self, error: str, error_code: str | None = None, status_code: int | None = None
    ) -> None:
        self.error = error
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(f"[{error_code or status_code}] {error}")


class PyrusAuthError(PyrusAPIError):
    """Raised when authentication fails or the token is invalid."""


class PyrusNotFoundError(PyrusAPIError):
    """Raised when a requested resource does not exist (404)."""


class PyrusPermissionError(PyrusAPIError):
    """Raised when the current user lacks permission for the action (403)."""


class PyrusRateLimitError(PyrusAPIError):
    """Raised when the API rate limit is exceeded (429)."""


class PyrusWebhookSignatureError(PyrusError):
    """Raised when webhook HMAC-SHA1 signature verification fails."""


class PyrusWebhookTimeoutError(PyrusError):
    """Raised when the webhook handler exceeds the 60-second response limit."""


class PyrusFileSizeError(PyrusError):
    """Raised when a file exceeds the maximum upload size (250 MB)."""
