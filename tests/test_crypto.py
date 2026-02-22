"""Tests for webhook HMAC-SHA1 signature verification."""

from __future__ import annotations

import hashlib
import hmac

from aiopyrus.utils.crypto import verify_webhook_signature


class TestWebhookSignature:
    def _sign(self, body: bytes, key: str) -> str:
        return hmac.new(key.encode(), msg=body, digestmod=hashlib.sha1).hexdigest()

    def test_valid_signature(self):
        body = b'{"task_id": 12345}'
        key = "my-secret-key"
        sig = self._sign(body, key)
        assert verify_webhook_signature(body, sig, key) is True

    def test_invalid_signature(self):
        body = b'{"task_id": 12345}'
        assert verify_webhook_signature(body, "bad-signature", "my-secret-key") is False

    def test_case_insensitive(self):
        body = b"test"
        key = "secret"
        sig = self._sign(body, key).upper()
        assert verify_webhook_signature(body, sig, key) is True

    def test_different_body(self):
        key = "secret"
        sig = self._sign(b"original", key)
        assert verify_webhook_signature(b"tampered", sig, key) is False

    def test_empty_body(self):
        key = "secret"
        sig = self._sign(b"", key)
        assert verify_webhook_signature(b"", sig, key) is True

    def test_unicode_key(self):
        body = b"data"
        key = "unicode-key"
        sig = self._sign(body, key)
        assert verify_webhook_signature(body, sig, key) is True
