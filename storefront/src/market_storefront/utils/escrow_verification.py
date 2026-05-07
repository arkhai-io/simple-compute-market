"""Pre-settlement on-chain escrow verification.

The seller's storefront calls ``verify_escrow_for_settlement`` before any
provisioning side-effect. It reads the EAS attestation by uid and asserts
that each escrow property matches the negotiated terms:

  - attestation exists and decodes as ERC-20 escrow
  - not revoked
  - not expired (``expiration_time == 0`` is the "no expiry" sentinel)
  - arbiter == canonical RecipientArbiter for this chain
  - decoded demand recipient == seller's wallet
  - token contract == negotiated token contract
  - amount >= ``agreed_price * agreed_duration_seconds // 3600``

On any mismatch raises ``EscrowVerificationError``. The caller maps that to
HTTP 400 — settlement aborts before any DB side effect or chain write.

The ``read_attestation`` reader and ``encode_recipient_demand`` /
``get_recipient_arbiter`` helpers are imported lazily to keep this module
testable without web3 or the alkahest address config.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from eth_abi import decode as abi_decode

logger = logging.getLogger(__name__)


class EscrowVerificationError(ValueError):
    """Raised when an on-chain escrow does not match the negotiated terms."""


def _normalize_address(addr: str | None) -> str | None:
    if not addr or not isinstance(addr, str):
        return None
    return addr.lower()


def _extract_token_contract_from_listing(listing: dict[str, Any]) -> str:
    """Pull the negotiated token contract address from the seller's listing.

    The listing's token side is whichever of offer/demand is the
    ``TokenResource`` — the other is the compute resource.
    """
    for field in ("demand_resource", "offer_resource"):
        raw = listing.get(field)
        parsed = raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
        if isinstance(parsed, dict) and "token" in parsed:
            token = parsed.get("token")
            if isinstance(token, dict):
                addr = token.get("contract_address")
                if isinstance(addr, str):
                    return addr
            # token can also be just a symbol string in legacy listings; that
            # has no contract address and cannot be verified — the caller
            # should fall back to bypassing the token check, but we want to
            # surface that explicitly rather than silently skipping.
    raise EscrowVerificationError(
        "Cannot extract token contract address from listing — "
        "no demand/offer resource with token.contract_address"
    )


def _decode_recipient_from_demand(demand: bytes) -> str | None:
    """Decode ``RecipientArbiter.DemandData{address recipient}`` -> address.

    Mirrors the buyer's ``encode_recipient_demand`` (which abi-encodes a
    single ``address``). Returns the recipient address (lowercase) or None
    if decoding fails.
    """
    try:
        (recipient,) = abi_decode(["address"], demand)
        return str(recipient).lower()
    except Exception as exc:
        logger.debug("[ESCROW_VERIFY] could not decode demand: %s", exc)
        return None


def _expected_amount_raw(agreed_price: int, agreed_duration_seconds: int) -> int:
    """Mirror buyer's ``escrow_client._create.amount_raw`` formula.

    ``agreed_price`` is per-hour in raw token units; ``agreed_duration_seconds``
    is the buyer's lease ask echoed by the seller. Integer math truncates
    the same way the buyer's encoder does.
    """
    return int(agreed_price) * int(max(agreed_duration_seconds, 1)) // 3600


async def verify_escrow_for_settlement(
    *,
    escrow_uid: str,
    seller_wallet: str,
    agreed_price: int,
    agreed_duration_seconds: int,
    listing: dict[str, Any],
    alkahest_client: Any,
    chain_name: str,
    alkahest_address_config_path: str | None,
    now_unix: int | None = None,
    read_attestation_fn: Any = None,
    get_recipient_arbiter_fn: Any = None,
) -> None:
    """Read the on-chain escrow and assert it matches the negotiated terms.

    Parameters
    ----------
    escrow_uid:
        The 0x-prefixed 32-byte attestation uid handed to us by the buyer.
    seller_wallet:
        Our wallet address; the escrow's decoded demand recipient must match.
    agreed_price, agreed_duration_seconds:
        From the negotiation thread; together they reconstruct the buyer's
        ``amount_raw`` floor.
    listing:
        The seller's listing row (after ``load_listing``); used to extract
        the negotiated token contract address.
    alkahest_client:
        An ``AlkahestClient`` already bound to the right chain; we read the
        escrow attestation through its ``erc20.escrow.non_tierable.get_obligation``
        path. The client knows its own RPC URL + EAS address, so we no longer
        thread those through.
    chain_name, alkahest_address_config_path:
        Used only to look up the canonical ``RecipientArbiter`` address —
        a static config lookup, not an RPC call.
    now_unix:
        Override for ``time.time()`` (test seam).
    read_attestation_fn / get_recipient_arbiter_fn:
        Test seams. Default to the real helpers.

    Raises
    ------
    EscrowVerificationError
        On any mismatch. Caller should map to HTTP 400.
    """
    if read_attestation_fn is None:
        from service.clients.eas import read_attestation as read_attestation_fn  # type: ignore[no-redef]
    if get_recipient_arbiter_fn is None:
        from service.clients.alkahest import get_recipient_arbiter as get_recipient_arbiter_fn  # type: ignore[no-redef]

    if alkahest_client is None:
        raise EscrowVerificationError(
            "AlkahestClient not configured — cannot verify escrow on chain"
        )

    expected_token = _normalize_address(_extract_token_contract_from_listing(listing))
    expected_amount_min = _expected_amount_raw(agreed_price, agreed_duration_seconds)
    expected_seller = _normalize_address(seller_wallet)
    if not expected_seller:
        raise EscrowVerificationError(
            "Seller wallet address is not configured — cannot verify escrow recipient"
        )

    try:
        expected_arbiter = _normalize_address(
            get_recipient_arbiter_fn(
                chain_name, config_path=alkahest_address_config_path
            )
        )
    except Exception as exc:
        raise EscrowVerificationError(
            f"Cannot resolve RecipientArbiter address for chain={chain_name!r}: {exc}"
        ) from exc

    try:
        attestation = await read_attestation_fn(alkahest_client, escrow_uid)
    except Exception as exc:
        raise EscrowVerificationError(
            f"Failed to read escrow {escrow_uid} from chain: {exc}"
        ) from exc

    if attestation is None:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} not found on chain"
        )

    if attestation.decode_error:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} is not an ERC-20 escrow obligation: "
            f"{attestation.decode_error}"
        )

    if attestation.is_revoked:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} is revoked (revocation_time="
            f"{attestation.revocation_time})"
        )

    now = int(now_unix) if now_unix is not None else int(time.time())
    if attestation.expiration_time and attestation.expiration_time <= now:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} expired at {attestation.expiration_time} "
            f"(now={now})"
        )

    actual_arbiter = _normalize_address(attestation.arbiter)
    if actual_arbiter != expected_arbiter:
        raise EscrowVerificationError(
            f"Escrow arbiter mismatch: chain={actual_arbiter} "
            f"expected RecipientArbiter={expected_arbiter}"
        )

    decoded_recipient = _decode_recipient_from_demand(attestation.demand or b"")
    if decoded_recipient != expected_seller:
        raise EscrowVerificationError(
            f"Escrow demand recipient mismatch: chain={decoded_recipient} "
            f"expected seller={expected_seller}"
        )

    actual_token = _normalize_address(attestation.token)
    if actual_token != expected_token:
        raise EscrowVerificationError(
            f"Escrow token mismatch: chain={actual_token} "
            f"expected={expected_token}"
        )

    if attestation.amount is None or attestation.amount < expected_amount_min:
        raise EscrowVerificationError(
            f"Escrow amount insufficient: chain={attestation.amount} "
            f"expected>={expected_amount_min} "
            f"(agreed_price={agreed_price}/hour × duration="
            f"{agreed_duration_seconds}s)"
        )

    logger.info(
        "[ESCROW_VERIFY] escrow=%s ok: amount=%s token=%s arbiter=%s "
        "recipient=%s exp=%s",
        escrow_uid, attestation.amount, actual_token, actual_arbiter,
        decoded_recipient, attestation.expiration_time,
    )
