"""EIP-191 personal-sign identity scheme."""

from __future__ import annotations

import logging

from market_identity.models import Identity
from market_identity.registry import register_identity_scheme

logger = logging.getLogger(__name__)

SCHEME_NAME = "eip191"


class Eip191Verifier:
    """EIP-191 ``personal_sign`` verifier."""

    name = SCHEME_NAME

    def verify_signature(
        self,
        identity: Identity,
        message: bytes,
        proof: bytes,
    ) -> bool:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
        except ImportError:
            logger.warning("[identity:eip191] eth_account not available")
            return False

        if identity.scheme != self.name:
            return False

        try:
            text = message.decode("utf-8")
        except UnicodeDecodeError:
            logger.error("[identity:eip191] message is not valid UTF-8")
            return False

        try:
            envelope = encode_defunct(text=text)
            recovered = Account.recover_message(envelope, signature=proof)
        except Exception as exc:  # noqa: BLE001
            logger.error("[identity:eip191] signature recovery failed: %s", exc)
            return False

        return recovered.lower() == identity.identifier.lower()


register_identity_scheme(Eip191Verifier())
