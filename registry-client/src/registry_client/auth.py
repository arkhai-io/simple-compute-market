"""EIP-191 signing helpers and shared error type for the registry client.

The registry API uses signed ``X-Signature`` / ``X-Timestamp`` headers on
mutation endpoints (heartbeat, publish_listing, delete_listing). The
message format is::

    "<operation>:<resource_id>:<timestamp>"

where ``resource_id`` is typically the canonical agent ID.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EIP-191 signing
# ---------------------------------------------------------------------------


def sign_eip191(private_key: str, message: str) -> str:
    """Sign *message* with *private_key* using EIP-191 personal_sign.

    Returns the hex signature string (with 0x prefix).
    """
    from eth_account import Account
    from eth_account.messages import encode_defunct

    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=private_key)
    return signed.signature.hex()


def build_auth_headers(private_key: str, operation: str, resource_id: str) -> dict[str, str]:
    """Build the auth headers expected by the Registry service.

    Header layout::

        X-Timestamp : unix timestamp (seconds, as a string)
        X-Signature : EIP-191 signature of  "<operation>:<resource_id>:<timestamp>"
        Content-Type: application/json
    """
    timestamp = str(int(time.time()))
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = sign_eip191(private_key, message)
    return {
        "Content-Type": "application/json",
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class RegistryClientError(Exception):
    """Raised when the Registry API returns a non-2xx status code."""

    def __init__(self, method: str, url: str, status_code: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} → HTTP {status_code}\n{body}")
