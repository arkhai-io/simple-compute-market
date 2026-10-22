"""Pre-settlement on-chain escrow verification.

The seller's storefront calls ``verify_escrow_against_plan`` before any
provisioning side-effect. It reads the EAS attestation by uid through the
escrow contract's codec and asserts the on-chain obligation_data dict-matches
one obligation of the settlement plan committed when the deal was accepted.
The plan, not the listing as it stands now, is what the buyer funded: a seller
who changes release policy, wallet, or address book afterwards cannot make a
correctly funded escrow fail verification. The address book is read only to
find the escrow contract's codec, so an address book that stops naming the
contract a deal funded leaves that deal unverifiable; the buyer's escrow stays
reclaimable at expiry.

Verification is two-phase:

1. Attestation envelope: the EAS attestation exists, is not revoked, and
   has a non-zero expirationTime in the future.

2. Obligation data: the chain's ObligationData (arbiter + demand + token
   + amount for ERC20EscrowObligation) dict-equals the expected
   obligation_data byte-for-byte (modulo address-case normalization and
   bytes/hex normalization). Single dict-compare replaces the per-field
   hard-coded checks; adding new arbiter / escrow kinds only requires
   registering their codecs, not changing this verifier.

Every plan obligation carries an ``expiration_unix``, which must also match
the attestation's expiration time exactly.

On any mismatch raises ``EscrowVerificationError``. The caller maps that
to HTTP 400 — settlement aborts before any DB side effect or chain
write. ``get_obligation_fn`` is an injectable test seam; no production
caller passes it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from market_alkahest import alkahest as _codecs
from market_alkahest.plans import (
    ALKAHEST_MECHANISM,
    SettlementPlan,
    settlement_obligation_to_escrow_terms,
)

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


# A key present on only one side is a mismatch even when the other side's value
# is None; a diff that read both through ``dict.get`` would report nothing.
_ABSENT = object()


def _shown(value: Any) -> str:
    return "<absent>" if value is _ABSENT else repr(value)


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
        "referenced_attestation_uid": "attestationUid",
    }
    for sdk_attr, canonical_key in field_aliases.items():
        value = getattr(obligation, sdk_attr, None)
        if value is not None:
            raw[canonical_key] = bytes(value) if sdk_attr == "demand" else value
    attestation_value = getattr(obligation, "attestation", None)
    attestation = _plain_attestation_request(attestation_value)
    if attestation is not None:
        raw["attestation"] = attestation
    elif attestation_value is not None:
        raw["attestationUid"] = attestation_value
    return _normalize_obligation_data(raw)


def _escrow_codec(
    chain_name: str, escrow_address: str, config_path: str | None
) -> Any:
    """The codec of the escrow contract at ``escrow_address`` on ``chain_name``."""
    try:
        return _codecs.get_escrow_codec_for(
            chain_name, escrow_address, config_path=config_path
        )
    except ValueError as exc:
        raise EscrowVerificationError(
            f"Cannot resolve escrow codec for proposal "
            f"(chain={chain_name!r}, address={escrow_address!r}): {exc}"
        ) from exc


async def _match_on_chain(
    *,
    escrow_uid: str,
    alkahest_client: Any,
    get_obligation_fn: Any,
    candidates: list[tuple[int, dict[str, Any], int | None]],
    now_unix: int | None,
) -> int:
    """Read the escrow and return the index of the one candidate it matches.

    Each candidate is ``(index, normalized obligation_data, expiration_unix)``;
    an expiration of ``None`` is not compared. Raises
    ``EscrowVerificationError`` naming the first candidate's differences when
    none matches.
    """
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
            f"Escrow {escrow_uid} is revoked (revocation_time={att.revocation_time})"
        )

    now = int(now_unix) if now_unix is not None else int(time.time())
    if att.expiration_time and int(att.expiration_time) <= now:
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} expired at {att.expiration_time} (now={now})"
        )
    if not att.expiration_time:
        # The EAS contract treats expiration_time=0 as "never expires";
        # for escrow obligations we always want a deadline so a stale
        # escrow can be reclaimed. Reject the no-expiry shape.
        raise EscrowVerificationError(
            f"Escrow {escrow_uid} has no expirationTime — refusing to settle"
        )
    actual = _read_chain_obligation_data(obligation)

    # Match the decoded escrow to one exact expected obligation, so no
    # position is assumed when a plan holds several.
    for index, candidate, candidate_expiration in candidates:
        expiration_matches = (
            candidate_expiration is None
            or int(att.expiration_time) == candidate_expiration
        )
        if actual == candidate and expiration_matches:
            logger.info(
                "[ESCROW_VERIFY] escrow=%s ok: fields=%s arbiter=%s exp=%s",
                escrow_uid,
                sorted(actual),
                actual.get("arbiter"),
                att.expiration_time,
            )
            return index

    _, expected, expected_expiration = candidates[0]
    diffs = []
    for key in sorted(set(actual) | set(expected)):
        chain_value = actual.get(key, _ABSENT)
        expected_value = expected.get(key, _ABSENT)
        if chain_value != expected_value:
            diffs.append(
                f"{key}: chain={_shown(chain_value)} "
                f"expected={_shown(expected_value)}"
            )
    if (
        expected_expiration is not None
        and int(att.expiration_time) != expected_expiration
    ):
        diffs.append(
            "expiration_time: "
            f"chain={att.expiration_time!r} expected={expected_expiration!r}"
        )
    raise EscrowVerificationError(
        f"Escrow {escrow_uid} obligation_data mismatch: " + "; ".join(diffs)
    )


def _codec_reader(codec: Any) -> Any:
    async def read(client: Any, uid: str) -> Any:
        return await codec.get_obligation(client, uid)

    return read


async def verify_escrow_against_plan(
    *,
    escrow_uid: str,
    settlement_plan: Any,
    alkahest_client: Any,
    chain_name: str,
    escrow_address: str,
    alkahest_address_config_path: str | None,
    now_unix: int | None = None,
    get_obligation_fn: Any = None,
) -> int:
    """Read the on-chain escrow and assert it is one obligation of the plan.

    ``settlement_plan`` is the plan committed when the deal was accepted, as
    the negotiation thread stores it. The escrow is read through the codec of
    its contract, ``escrow_address`` on ``chain_name`` (the accepted
    proposal's), and must equal, obligation data and expiry, one of the plan's
    Alkahest obligations on that contract. Returns that obligation's index in
    the plan, which identifies it to the settlement runtime.

    Nothing is re-derived from the listing, the seller's wallet, or the release
    policy: those may have changed since acceptance, and the buyer funded the
    plan. The address configuration is read only to find the escrow
    contract's codec.

    Raises ``EscrowVerificationError`` on any mismatch, or when the plan holds
    no Alkahest obligation on that contract.
    """
    if alkahest_client is None:
        raise EscrowVerificationError(
            "AlkahestClient not configured — cannot verify escrow on chain"
        )
    try:
        plan = SettlementPlan.model_validate(settlement_plan)
    except Exception as exc:
        raise EscrowVerificationError(
            f"the accepted settlement plan cannot be read: {exc}"
        ) from exc
    target = escrow_address.lower()
    candidates: list[tuple[int, dict[str, Any], int | None]] = []
    for index, obligation in enumerate(plan.obligations):
        if obligation.mechanism != ALKAHEST_MECHANISM:
            continue
        terms = settlement_obligation_to_escrow_terms(obligation)
        if terms.chain_name != chain_name or terms.escrow_contract.lower() != target:
            continue
        candidates.append(
            (
                index,
                _normalize_obligation_data(terms.obligation_data),
                int(terms.expiration_unix),
            )
        )
    if not candidates:
        raise EscrowVerificationError(
            "the accepted settlement plan holds no obligation on escrow "
            f"{escrow_address!r} of chain {chain_name!r}"
        )
    if get_obligation_fn is None:
        get_obligation_fn = _codec_reader(
            _escrow_codec(chain_name, escrow_address, alkahest_address_config_path)
        )
    return await _match_on_chain(
        escrow_uid=escrow_uid,
        alkahest_client=alkahest_client,
        get_obligation_fn=get_obligation_fn,
        candidates=candidates,
        now_unix=now_unix,
    )
