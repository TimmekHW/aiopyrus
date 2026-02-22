from __future__ import annotations

import hashlib
import hmac


def verify_webhook_signature(body: bytes, signature: str, security_key: str) -> bool:
    """Verify the HMAC-SHA1 signature that Pyrus sends with each webhook call.

    Pyrus computes:
        HMAC-SHA1(key=security_key, msg=body)

    and sends the hex-digest in the ``X-Pyrus-Sig`` header.
    """
    expected = hmac.new(
        security_key.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha1,
    ).hexdigest()
    return hmac.compare_digest(expected.lower(), signature.lower())
