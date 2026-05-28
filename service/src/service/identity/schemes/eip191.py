"""EIP-191 personal-sign identity scheme.

The default and (after the ERC-8004 removal in Phase 4) only built-in
scheme. ``identity.identifier`` is the lowercase 0x hex wallet address;
``proof`` is the 65-byte EIP-191 signature; ``message`` is the UTF-8
encoding of the canonical signed text.
"""

from __future__ import annotations

import logging

from service.identity.registry import register_identity_scheme
from service.schemas import Identity

logger = logging.getLogger(__name__)

SCHEME_NAME = "eip191"


class Eip191Verifier:
    """EIP-191 ``personal_sign`` verifier.

    Recovers the signer via :func:`eth_account.Account.recover_message`
    over an :func:`eth_account.messages.encode_defunct` envelope, then
    compares (case-insensitively) against ``identity.identifier``.
    Returns False on any recovery failure or malformed proof.
    """

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
        except Exception as exc:  # noqa: BLE001 — eth_account raises many shapes
            logger.error("[identity:eip191] signature recovery failed: %s", exc)
            return False

        return recovered.lower() == identity.identifier.lower()


register_identity_scheme(Eip191Verifier())
