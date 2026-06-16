"""Pre-settlement on-chain escrow verification.

The seller's storefront calls ``verify_escrow_for_settlement`` before any
provisioning side-effect. It reads the EAS attestation by uid via
alkahest-py's ``client.erc20.escrow.non_tierable.get_obligation(uid)`` and
asserts the on-chain obligation_data dict-matches what the seller
expects, computed via ``build_payment_obligation_data`` from the same
negotiation inputs the buyer used.

Verification is two-phase:

1. Attestation envelope: the EAS attestation exists, is not revoked, and
   has a non-zero expirationTime in the future.

2. Obligation data: the chain's ObligationData (arbiter + demand + token
   + amount for ERC20EscrowObligation) dict-equals the expected
   obligation_data byte-for-byte (modulo address-case normalization and
   bytes/hex normalization). Single dict-compare replaces the per-field
   hard-coded checks; adding new arbiter / escrow kinds later only
   requires updating ``build_payment_obligation_data`` (or its successor
   codec lookup in step 5), not this verifier.

The expected ``expiration_unix`` doesn't participate in dict-compare —
it's buyer-clock-stamped at escrow creation and the seller can't
reproduce it without the buyer publishing the value. Step 7 makes the
buyer publish the full EscrowTerms via the negotiation protocol so this
check can become exact-equal.

On any mismatch raises ``EscrowVerificationError``. The caller maps that
to HTTP 400 — settlement aborts before any DB side effect or chain
write. ``get_obligation_fn`` and ``build_obligation_data_fn`` are
injectable test seams.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class EscrowVerificationError(ValueError):
    """Raised when an on-chain escrow does not match the negotiated terms."""


def _normalize_address(addr: Any) -> str | None:
    """Lowercase address for case-insensitive comparison.

    Returns None when the input isn't a usable address string — caller
    distinguishes missing-from-listing (raise) vs. missing-on-chain
    (also raise, but with a different message).
    """
    if not addr or not isinstance(addr, str):
        return None
    return addr.lower()


def _normalize_bytes(value: Any) -> str | None:
    """Canonicalize a demand-bytes-like value to a "0x"-prefixed hex string.

    Accepts:
      - bytes / bytearray → hex-encode
      - "0x..."-prefixed hex string → lowercase
      - bare hex string (no 0x) → lowercase + prepend 0x

    Returns None for anything else (which the caller treats as a
    verification failure — chain reads should always produce one of
    the accepted shapes).
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "0x" + bytes(value).hex()
    if isinstance(value, str):
        s = value.lower()
        if s.startswith("0x"):
            return s
        # tolerate bare hex (no leading 0x)
        try:
            bytes.fromhex(s)
            return "0x" + s
        except ValueError:
            return None
    return None


def _extract_token_contract_from_listing(listing: dict[str, Any]) -> str:
    """Pull the negotiated token contract address from the seller's
    listing's primary accepted-escrow entry.

    Used as the fallback when the buyer didn't include an
    ``escrow_proposal`` on the negotiation thread. With a proposal in
    hand the verifier reads ``proposal.literal_fields["token"]`` directly.
    """
    from market_core.schemas import accepted_token_address

    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        try:
            accepted = json.loads(accepted)
        except Exception:
            accepted = None
    if isinstance(accepted, list) and accepted:
        addr = accepted_token_address(accepted[0])
        if addr:
            return addr
    raise EscrowVerificationError(
        "Cannot extract token contract address from listing — "
        "no accepted_escrows[0] token literal"
    )


_ADDRESS_FIELDS = {
    "arbiter",
    "token",
    "recipient",
}
_ADDRESS_LIST_FIELDS = {
    "erc20Tokens",
    "erc721Tokens",
    "erc1155Tokens",
}
_BYTES_FIELDS = {
    "demand",
    "data",
    "schema",
    "ref_uid",
    "refUID",
    "attestationUid",
}
_INT_FIELDS = {
    "amount",
    "tokenId",
    "nativeAmount",
    "expiration_time",
    "expirationTime",
    "value",
}
_INT_LIST_FIELDS = {
    "erc20Amounts",
    "erc721TokenIds",
    "erc1155TokenIds",
    "erc1155Amounts",
}


def _normalize_obligation_value(key: str, val: Any) -> Any:
    if isinstance(val, dict):
        return _normalize_obligation_data(val)
    if key in _ADDRESS_FIELDS:
        return _normalize_address(val)
    if key in _ADDRESS_LIST_FIELDS:
        return [_normalize_address(item) for item in (val or [])]
    if key in _BYTES_FIELDS:
        return _normalize_bytes(val)
    if key in _INT_FIELDS:
        return int(val) if val is not None else None
    if key in _INT_LIST_FIELDS:
        return [int(item) for item in (val or [])]
    if isinstance(val, list):
        return [_normalize_obligation_value(key, item) for item in val]
    return val


def _normalize_obligation_data(data: dict[str, Any]) -> dict[str, Any]:
    """Canonical form for dict-compare.

    Addresses → lowercase, bytes-like fields → "0x"-prefixed hex, integer
    fields → int. Keys outside the canonical set pass through unchanged so
    shape mismatches are still visible in the final diff.
    """
    return {key: _normalize_obligation_value(key, val) for key, val in data.items()}


def _plain_attestation_request(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    schema = getattr(value, "schema", None)
    request_data = getattr(value, "data", None)
    if schema is None and request_data is None:
        return None
    if isinstance(request_data, dict):
        data_dict = request_data
    else:
        data_dict = {
            "recipient": getattr(request_data, "recipient", None),
            "expiration_time": getattr(request_data, "expiration_time", None),
            "revocable": getattr(request_data, "revocable", None),
            "ref_uid": getattr(request_data, "ref_uid", None),
            "data": getattr(request_data, "data", None),
            "value": getattr(request_data, "value", None),
        }
    return {"schema": schema, "data": data_dict}


def _read_chain_obligation_data(obligation: Any) -> dict[str, Any]:
    """Read fields off the alkahest-py decoded ObligationData object.

    The SDK returns a typed struct (not a dict). Pull every known escrow
    ObligationData field into a normalized dict so one comparison covers
    ERC20, native token, NFT, token bundle, and attestation escrows.
    """
    raw: dict[str, Any] = {}
    field_aliases = {
        "arbiter": "arbiter",
        "demand": "demand",
        "token": "token",
        "amount": "amount",
        "token_id": "tokenId",
        "native_amount": "nativeAmount",
        "erc20_tokens": "erc20Tokens",
        "erc20_amounts": "erc20Amounts",
        "erc721_tokens": "erc721Tokens",
        "erc721_token_ids": "erc721TokenIds",
        "erc1155_tokens": "erc1155Tokens",
        "erc1155_token_ids": "erc1155TokenIds",
        "erc1155_amounts": "erc1155Amounts",
        "attestation_uid": "attestationUid",
    }
    for sdk_attr, canonical_key in field_aliases.items():
        value = getattr(obligation, sdk_attr, None)
        if value is not None:
            raw[canonical_key] = bytes(value) if sdk_attr == "demand" else value
    attestation = _plain_attestation_request(getattr(obligation, "attestation", None))
    if attestation is not None:
        raw["attestation"] = attestation
    return _normalize_obligation_data(raw)


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
    escrow_proposal: Any = None,
    escrow_kind: str = "erc20_escrow_obligation_nontierable",
    now_unix: int | None = None,
    get_obligation_fn: Any = None,
    build_obligation_data_fn: Any = None,
) -> None:
    """Read the on-chain escrow and assert it matches the negotiated terms.

    Parameters
    ----------
    escrow_uid:
        The 0x-prefixed 32-byte attestation uid handed to us by the buyer.
    seller_wallet:
        Our wallet address; participates in the expected obligation_data
        via the RecipientArbiter demand encoding.
    agreed_price, agreed_duration_seconds:
        From the negotiation thread; ``agreed_price`` is the absolute
        payment amount in base units (the DB column name is retained
        from before the per-hour → absolute refactor — semantically it
        is now the amount, not a rate). Together with the proposal's
        token + arbiter and the chain config they determine the entire
        expected obligation_data dict.
    listing:
        The seller's listing row (after ``load_listing``); used as the
        fallback source for the payment token when no proposal is
        available (legacy threads).
    alkahest_client:
        An ``AlkahestClient`` already bound to the right chain.
    chain_name, alkahest_address_config_path:
        Used to resolve the canonical arbiter + escrow contract
        addresses for the chain (a static config lookup, not an RPC call).
    escrow_proposal:
        The buyer's ``EscrowProposal``, persisted on the negotiation
        thread at /negotiate/new. When present, the verifier materializes
        the same concrete ``EscrowTerms`` shape the buyer used and compares
        its ``obligation_data`` with the chain-read obligation. None for
        legacy threads — verifier falls back to the listing-derived token
        and the ``escrow_kind`` default.
    escrow_kind:
        Fallback escrow slot name when ``escrow_proposal`` is None.
        Today only ``"erc20_escrow_obligation_nontierable"`` is
        registered.
    now_unix:
        Override for ``time.time()`` (test seam).
    get_obligation_fn / build_obligation_data_fn:
        Test seams. ``get_obligation_fn`` defaults to the registered
        escrow-kind codec's ``get_obligation`` (returns the decoded
        ``{"attestation", "data"}`` shape). ``build_obligation_data_fn``
        defaults to the canonical helper that constructs the expected
        obligation_data dict.

    Raises
    ------
    EscrowVerificationError
        On any mismatch. Caller should map to HTTP 400.
    """
    if alkahest_client is None:
        raise EscrowVerificationError(
            "AlkahestClient not configured — cannot verify escrow on chain"
        )

    # The proposal (when present) is the source of truth: its
    # (chain_name, escrow_address) identifies the escrow contract and
    # its literal_fields / fields supply the buyer-committed values.
    # Legacy threads with no proposal fall back to the kwarg defaults
    # + a listing-derived token.
    from market_core.schemas import accepted_recipient_address, accepted_token_address

    effective_recipient = seller_wallet
    _codec = None
    expected_obligation_raw: dict[str, Any] | None = None
    if escrow_proposal is not None:
        from market_alkahest.alkahest import get_escrow_codec_for
        _addr = (escrow_proposal.escrow_address or "").lower()
        # The buyer may leave the escrow contract unpinned — a zero-address
        # placeholder — so negotiation gates on field equality rather than a
        # specific (chain, address). An unpinned proposal escrows against the
        # chain's default kind, so resolve the codec from ``escrow_kind``
        # rather than the placeholder address (which matches no codec).
        _unpinned = (not _addr) or set(_addr.removeprefix("0x")) <= {"0"}
        if _unpinned:
            effective_escrow_kind = escrow_kind
        else:
            try:
                _codec = get_escrow_codec_for(
                    escrow_proposal.chain_name,
                    escrow_proposal.escrow_address,
                    config_path=alkahest_address_config_path,
                )
            except ValueError as exc:
                raise EscrowVerificationError(
                    f"Cannot resolve escrow codec for proposal "
                    f"(chain={escrow_proposal.chain_name!r}, "
                    f"address={escrow_proposal.escrow_address!r}): {exc}"
                ) from exc
            effective_escrow_kind = _codec.kind
        proposal_recipient = accepted_recipient_address(escrow_proposal)
        if proposal_recipient:
            effective_recipient = proposal_recipient
        if build_obligation_data_fn is not None:
            proposal_token = accepted_token_address(escrow_proposal)
            if not isinstance(proposal_token, str) or not proposal_token:
                raise EscrowVerificationError(
                    f"escrow proposal for {escrow_uid} omitted token "
                    f"(literal_fields['token'] missing); cannot verify "
                    f"against chain"
                )
            effective_token = proposal_token
        if build_obligation_data_fn is None:
            from market_alkahest.alkahest import materialize_escrow_terms_from_proposal

            try:
                expected_terms = materialize_escrow_terms_from_proposal(
                    proposal=escrow_proposal,
                    seller_wallet_address=effective_recipient,
                    agreed_amount=int(agreed_price),
                    duration_seconds=int(agreed_duration_seconds),
                    addr_config_path=alkahest_address_config_path,
                )
            except Exception as exc:
                raise EscrowVerificationError(
                    f"Cannot construct expected obligation_data for "
                    f"chain={chain_name!r}: {exc}"
                ) from exc
            expected_obligation_raw = expected_terms[0].obligation_data
    else:
        effective_escrow_kind = escrow_kind
        effective_token = _extract_token_contract_from_listing(listing)

    if get_obligation_fn is None:
        from market_alkahest.alkahest import get_escrow_kind_codec
        if _codec is None:
            try:
                _codec = get_escrow_kind_codec(effective_escrow_kind)
            except ValueError as exc:
                raise EscrowVerificationError(
                    f"Cannot read escrow {escrow_uid}: {exc}"
                ) from exc

        async def get_obligation_fn(client, uid):  # type: ignore[no-redef]
            return await _codec.get_obligation(client, uid)

    if expected_obligation_raw is None and not effective_recipient:
        raise EscrowVerificationError(
            "Escrow recipient is not configured — cannot verify escrow demand"
        )

    if expected_obligation_raw is None:
        # Legacy thread with no concrete proposal; keep the old ERC20 path.
        if build_obligation_data_fn is None:
            from market_alkahest.alkahest import (
                build_payment_obligation_data as build_obligation_data_fn,
            )
        try:
            expected_obligation_raw = build_obligation_data_fn(
                demands=None,
                recipient=effective_recipient,
                agreed_amount=int(agreed_price),
                duration_seconds=int(agreed_duration_seconds),
                token_contract_address=effective_token,
                chain_name=chain_name,
                addr_config_path=alkahest_address_config_path,
                arbiter_kind="recipient_arbiter",
            )
        except Exception as exc:
            raise EscrowVerificationError(
                f"Cannot construct expected obligation_data for chain={chain_name!r}: {exc}"
            ) from exc
    expected = _normalize_obligation_data(expected_obligation_raw)

    # Read the on-chain attestation + obligation.
    try:
        decoded = await get_obligation_fn(alkahest_client, escrow_uid)
    except Exception as exc:
        raise EscrowVerificationError(
            f"Failed to read escrow {escrow_uid} from chain: {exc}"
        ) from exc

    att = decoded["attestation"]
    obligation = decoded["data"]

    # Attestation envelope checks (independent of obligation_data shape).
    if att.revocation_time:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} is revoked (revocation_time="
            f"{att.revocation_time})"
        )

    now = int(now_unix) if now_unix is not None else int(time.time())
    if att.expiration_time and int(att.expiration_time) <= now:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} expired at {att.expiration_time} "
            f"(now={now})"
        )
    if not att.expiration_time:
        # The EAS contract treats expiration_time=0 as "never expires";
        # for escrow obligations we always want a deadline so a stale
        # escrow can be reclaimed. Reject the no-expiry shape.
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} has no expirationTime — refusing to settle"
        )

    # Dict-compare the canonical ObligationData. One check covers every
    # field the contract enforces at collection time (arbiter, demand,
    # token, amount) and adds nothing arbiter-specific to this verifier.
    actual = _read_chain_obligation_data(obligation)
    if actual != expected:
        # Build a focused diff so the operator sees exactly which fields
        # diverged. Stringify byte-y / large-int values for the message.
        diffs = []
        for key in sorted(set(actual) | set(expected)):
            if actual.get(key) != expected.get(key):
                diffs.append(
                    f"{key}: chain={actual.get(key)!r} expected={expected.get(key)!r}"
                )
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} obligation_data mismatch: " + "; ".join(diffs)
        )

    logger.info(
        "[ESCROW_VERIFY] escrow=%s ok: fields=%s arbiter=%s exp=%s",
        escrow_uid, sorted(actual), actual.get("arbiter"), att.expiration_time,
    )
