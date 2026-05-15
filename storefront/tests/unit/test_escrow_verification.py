"""Unit tests for storefront.utils.escrow_verification.

Covers each rejection case (missing chain config, missing wallet, builder
failure, chain read failure, revoked, expired, no-expiration, and each
field of obligation_data diverging) and the happy path.

The alkahest ``get_obligation`` call and the canonical
``build_payment_obligation_data`` helper are injected via test seams so
tests are fully offline — no web3, no eth-abi setup beyond what's
needed to round-trip an ABI-encoded address.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    _extract_token_contract_from_listing,
    _normalize_address,
    _normalize_bytes,
    _normalize_obligation_data,
    verify_escrow_for_settlement,
)


SELLER = "0x1111111111111111111111111111111111111111"
SELLER_LOWER = SELLER.lower()
BUYER = "0x2222222222222222222222222222222222222222"
TOKEN = "0xAAAA000000000000000000000000000000000000"
TOKEN_LOWER = TOKEN.lower()
ARBITER = "0xBBBB000000000000000000000000000000000000"
ARBITER_LOWER = ARBITER.lower()
_DUMMY_CLIENT = object()
CHAIN = "anvil"
CONFIG_PATH = "/tmp/addresses.json"


def _encode_recipient(address: str) -> bytes:
    """Real ABI-encode of a single address — matches the buyer's encoding."""
    from eth_abi import encode as abi_encode
    return abi_encode(["address"], [address])


@dataclass
class _FakeAttestationEnvelope:
    """Mirrors the fields the verifier reads off alkahest's
    ``decoded["attestation"]`` (the EAS envelope)."""
    revocation_time: int = 0
    expiration_time: int = 1_800_000_000  # absolute UTC unix far enough out


@dataclass
class _FakeObligationData:
    """Mirrors alkahest's ``decoded["data"]`` typed
    ``ERC20EscrowObligation.ObligationData`` payload."""
    arbiter: str | None = ARBITER
    demand: bytes | None = None
    token: str | None = TOKEN
    amount: int | None = 1_000_000  # default; tests override to the expected 1000


def _good_obligation(**overrides: Any) -> dict[str, Any]:
    """Build the ``{'attestation': ..., 'data': ...}`` dict alkahest's
    get_obligation returns, applying overrides to whichever sub-record
    carries each field. The default ``data`` matches what the
    canonical builder produces for (SELLER, 1000, 3600, TOKEN)."""
    att = _FakeAttestationEnvelope()
    data = _FakeObligationData(
        demand=_encode_recipient(SELLER),
        amount=1000,  # 1000 per-hour × 3600s / 3600 = 1000
    )
    for k, v in overrides.items():
        if hasattr(att, k):
            setattr(att, k, v)
        elif hasattr(data, k):
            setattr(data, k, v)
        else:
            raise AttributeError(f"unknown override: {k}")
    return {"attestation": att, "data": data}


def _canonical_obligation_data(
    *,
    seller_wallet: str = SELLER,
    agreed_price: int = 1000,
    duration_seconds: int = 3600,
    token_contract_address: str = TOKEN,
    arbiter_address: str = ARBITER,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Same shape ``build_payment_obligation_data`` produces. Test seam
    feeds this back to the verifier so we don't need the real alkahest
    chain config lookups."""
    return {
        "arbiter": arbiter_address,
        "demand": "0x" + _encode_recipient(seller_wallet).hex(),
        "token": token_contract_address,
        "amount": int(agreed_price) * int(max(duration_seconds, 1)) // 3600,
    }


def _make_seams(decoded: dict[str, Any]) -> dict[str, Any]:
    async def _get_obligation(client, uid):
        return decoded

    def _build(*, seller_wallet, agreed_price, duration_seconds,
               token_contract_address, chain_name, addr_config_path=None,
               arbiter_kind="recipient"):
        return _canonical_obligation_data(
            seller_wallet=seller_wallet,
            agreed_price=agreed_price,
            duration_seconds=duration_seconds,
            token_contract_address=token_contract_address,
        )

    return {
        "get_obligation_fn": _get_obligation,
        "build_obligation_data_fn": _build,
    }


def _good_listing() -> dict:
    return {
        "accepted_escrows": [{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "fields": {"token": TOKEN},
            "price_per_hour": 100,
        }],
        "offer_resource": {"gpu_model": "H200", "gpu_count": 1},
    }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


class TestNormalizeAddress:
    def test_lowercases(self):
        assert _normalize_address("0xABCdef0000000000000000000000000000000000") == \
            "0xabcdef0000000000000000000000000000000000"

    def test_empty_returns_none(self):
        assert _normalize_address("") is None
        assert _normalize_address(None) is None

    def test_non_string_returns_none(self):
        assert _normalize_address(123) is None


class TestNormalizeBytes:
    def test_bytes_to_hex(self):
        assert _normalize_bytes(b"\xab\xcd") == "0xabcd"

    def test_hex_prefixed_lowercased(self):
        assert _normalize_bytes("0xABCD") == "0xabcd"

    def test_hex_without_prefix_gets_one(self):
        assert _normalize_bytes("ABCD") == "0xabcd"

    def test_none_returns_none(self):
        assert _normalize_bytes(None) is None

    def test_invalid_returns_none(self):
        assert _normalize_bytes("not hex at all") is None


class TestNormalizeObligationData:
    def test_round_trips_canonical_shape(self):
        normalized = _normalize_obligation_data({
            "arbiter": "0xABCDEF0000000000000000000000000000000000",
            "demand": b"\xab\xcd",
            "token": "0x1234000000000000000000000000000000000000",
            "amount": 999,
        })
        assert normalized == {
            "arbiter": "0xabcdef0000000000000000000000000000000000",
            "demand": "0xabcd",
            "token": "0x1234000000000000000000000000000000000000",
            "amount": 999,
        }


# ---------------------------------------------------------------------------
# _extract_token_contract_from_listing
# ---------------------------------------------------------------------------


class TestExtractTokenContractFromListing:
    def test_reads_accepted_escrows_token(self):
        assert _extract_token_contract_from_listing(_good_listing()) == TOKEN

    def test_serialized_json_string_accepted_escrows(self):
        import json
        listing = {
            "accepted_escrows": json.dumps([{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": TOKEN},
                "price_per_hour": 1,
            }]),
            "offer_resource": {"gpu_model": "H200"},
        }
        assert _extract_token_contract_from_listing(listing) == TOKEN

    def test_no_token_raises(self):
        listing = {
            "accepted_escrows": [{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {},
            }],
            "offer_resource": {"gpu_model": "H200"},
        }
        with pytest.raises(EscrowVerificationError, match="Cannot extract token"):
            _extract_token_contract_from_listing(listing)

    def test_empty_accepted_escrows_raises(self):
        listing = {"accepted_escrows": [], "offer_resource": {"gpu_model": "H200"}}
        with pytest.raises(EscrowVerificationError, match="Cannot extract token"):
            _extract_token_contract_from_listing(listing)


# ---------------------------------------------------------------------------
# verify_escrow_for_settlement — happy path
# ---------------------------------------------------------------------------


class TestVerifyHappyPath:
    @pytest.mark.asyncio
    async def test_passes_when_everything_matches(self):
        att = _good_obligation()
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            now_unix=1_700_000_000,
            **_make_seams(att),
        )

    @pytest.mark.asyncio
    async def test_passes_with_case_insensitive_address_match(self):
        """Chain might return checksummed addresses; expected might be
        lowercase (or vice versa) — normalization handles it."""
        att = _good_obligation(
            arbiter=ARBITER.upper(),  # all-caps from chain
            token=TOKEN.upper(),
        )
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            now_unix=1_700_000_000,
            **_make_seams(att),
        )


# ---------------------------------------------------------------------------
# verify_escrow_for_settlement — rejection cases
# ---------------------------------------------------------------------------


class TestVerifyRejections:
    @pytest.mark.asyncio
    async def test_rejects_when_no_alkahest_client(self):
        with pytest.raises(EscrowVerificationError, match="AlkahestClient not configured"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=None,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                **_make_seams(_good_obligation()),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_seller_wallet_blank(self):
        with pytest.raises(EscrowVerificationError, match="Seller wallet"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet="",
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                **_make_seams(_good_obligation()),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_obligation_data_builder_raises(self):
        """If chain config lookups fail (e.g. unknown chain, missing
        anvil addresses file), the verifier should refuse rather than
        try to compare against undefined expected values."""
        def _broken(**_kw):
            raise ValueError("no arbiter for this chain")

        seams = _make_seams(_good_obligation())
        seams["build_obligation_data_fn"] = _broken
        with pytest.raises(EscrowVerificationError, match="Cannot construct expected obligation_data"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                **seams,
            )

    @pytest.mark.asyncio
    async def test_rejects_when_chain_read_fails(self):
        async def _broken_read(*a, **k):
            raise RuntimeError("rpc unreachable")

        seams = _make_seams(_good_obligation())
        seams["get_obligation_fn"] = _broken_read
        with pytest.raises(EscrowVerificationError, match="Failed to read escrow"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                **seams,
            )

    @pytest.mark.asyncio
    async def test_rejects_when_revoked(self):
        att = _good_obligation(revocation_time=10**12)
        with pytest.raises(EscrowVerificationError, match="is revoked"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                **_make_seams(att),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_expired(self):
        att = _good_obligation(expiration_time=1000)
        with pytest.raises(EscrowVerificationError, match="expired"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=2000,  # > expiration_time
                **_make_seams(att),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_no_expiration_set(self):
        """The EAS contract treats expiration_time=0 as 'never expires'.
        For our escrows we always want a reclaim deadline, so refuse it."""
        att = _good_obligation(expiration_time=0)
        with pytest.raises(EscrowVerificationError, match="no expirationTime"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_arbiter_mismatch(self):
        att = _good_obligation(arbiter="0xdeadbeef00000000000000000000000000000000")
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )

    @pytest.mark.asyncio
    async def test_rejects_when_demand_recipient_is_someone_else(self):
        """Buyer encoded a DIFFERENT seller's address as the recipient."""
        att = _good_obligation(demand=_encode_recipient(BUYER))
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch") as exc:
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )
        # The diff should name the diverging field.
        assert "demand:" in str(exc.value)

    @pytest.mark.asyncio
    async def test_rejects_when_token_mismatch(self):
        att = _good_obligation(token="0xdeadbeef00000000000000000000000000000000")
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch") as exc:
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )
        assert "token:" in str(exc.value)

    @pytest.mark.asyncio
    async def test_rejects_when_amount_below(self):
        """Strict equality: underpayment now rejected (was previously
        only checked as floor)."""
        att = _good_obligation(amount=999)
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch") as exc:
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )
        assert "amount:" in str(exc.value)

    @pytest.mark.asyncio
    async def test_rejects_when_amount_above(self):
        """Strict equality also catches overpayment — a deviation worth
        investigating even if the chain contract would have accepted it
        (since `checkObligation` does `>=` not `==`)."""
        att = _good_obligation(amount=2000)
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                now_unix=1_700_000_000,
                **_make_seams(att),
            )
