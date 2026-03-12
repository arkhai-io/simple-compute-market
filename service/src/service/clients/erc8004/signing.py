"""Shared EIP-191 signing utilities for order and heartbeat auth."""

import time
import logging
from typing import Optional

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    HAS_ETH_ACCOUNT = True
except ImportError:
    HAS_ETH_ACCOUNT = False

logger = logging.getLogger(__name__)


def sign_eip191(private_key: str, message: str) -> Optional[str]:
    """Sign a message with EIP-191 personal sign. Returns hex signature or None."""
    if not HAS_ETH_ACCOUNT:
        logger.warning("[SIGNING] eth_account not available, cannot sign message")
        return None
    try:
        message_hash = encode_defunct(text=message)
        signed = Account.sign_message(message_hash, private_key)
        return signed.signature.hex()
    except Exception as e:
        logger.error(f"[SIGNING] Failed to sign message: {e}")
        return None


def verify_eip191(message: str, signature: str, expected_address: str) -> bool:
    """Verify an EIP-191 signature. Returns True if the signer matches expected_address."""
    if not HAS_ETH_ACCOUNT:
        return False
    try:
        message_hash = encode_defunct(text=message)
        recovered = Account.recover_message(message_hash, signature=signature)
        return recovered.lower() == expected_address.lower()
    except Exception as e:
        logger.error(f"[SIGNING] Failed to verify signature: {e}")
        return False


def build_order_auth(private_key: str, operation: str, resource_id: str) -> dict:
    """Build auth fields for an order mutation request.

    Args:
        private_key: Hex private key of the signer
        operation: One of 'create_order', 'update_order', 'delete_order'
        resource_id: agent_id for create_order, order_id for update/delete

    Returns:
        Dict with 'signature' and 'timestamp' to merge into the request body/params.
        Empty dict if signing is unavailable.
    """
    timestamp = int(time.time())
    message = f"{operation}:{resource_id}:{timestamp}"
    sig = sign_eip191(private_key, message)
    if sig is None:
        return {}
    return {"signature": sig, "timestamp": timestamp}
