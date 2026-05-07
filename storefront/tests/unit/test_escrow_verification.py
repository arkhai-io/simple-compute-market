"""Unit tests for storefront.utils.escrow_verification.

Covers each rejection case (missing chain config, missing rpc, chain
read failure, decode error, revoked, expired, wrong arbiter, wrong
demand recipient, wrong token, insufficient amount) and the happy path.

The on-chain ``read_attestation`` reader is injected via a test seam so
tests are fully offline — no web3, no eth-abi setup beyond what
``encode_recipient_demand`` already needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    _decode_recipient_from_demand,
    _expected_amount_raw,
    _extract_token_contract_from_listing,
    verify_escrow_for_settlement,
)


SELLER = "0x1111111111111111111111111111111111111111"
SELLER_LOWER = SELLER.lower()
BUYER = "0x2222222222222222222222222222222222222222"
TOKEN = "0xaaaa000000000000000000000000000000000000"
TOKEN_LOWER = TOKEN.lower()
ARBITER = "0xbbbb000000000000000000000000000000000000"
ARBITER_LOWER = ARBITER.lower()
EAS = "0xcccc000000000000000000000000000000000000"
_DUMMY_CLIENT = object()
CHAIN = "anvil"
CONFIG_PATH = "/tmp/addresses.json"


def _encode_recipient(address: str) -> bytes:
    """Real ABI-encode of a single address — matches the buyer's
    encode_recipient_demand exactly."""
    from eth_abi import encode as abi_encode
    return abi_encode(["address"], [address])


@dataclass
class FakeAttestation:
    arbiter: str | None = ARBITER
    demand: bytes | None = None
    token: str | None = TOKEN
    amount: int | None = 1_000_000
    revocation_time: int = 0
    expiration_time: int = 0
    decode_error: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revocation_time != 0


def _good_attestation(**overrides: Any) -> FakeAttestation:
    base = FakeAttestation(demand=_encode_recipient(SELLER))
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_seams(attestation: FakeAttestation) -> dict[str, Any]:
    async def _read(client, uid):
        return attestation

    return {
        "read_attestation_fn": _read,
        "get_recipient_arbiter_fn": lambda chain, *, config_path=None: ARBITER,
    }


def _good_listing() -> dict:
    return {
        "demand_resource": {
            "token": {"contract_address": TOKEN, "decimals": 6, "symbol": "USDT"},
            "amount": 100,
        },
        "offer_resource": {"gpu_model": "H200", "gpu_count": 1},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestExpectedAmountRaw:
    def test_per_hour_times_duration(self):
        # 1000 per hour for 7200s = 2000
        assert _expected_amount_raw(1000, 7200) == 2000

    def test_truncates_partial_hour(self):
        # 1000 per hour for 1800s = 500 (integer truncation)
        assert _expected_amount_raw(1000, 1800) == 500

    def test_zero_duration_clamps_to_one_second(self):
        # max(0, 1) = 1; 1000 * 1 // 3600 = 0
        assert _expected_amount_raw(1000, 0) == 0


class TestExtractTokenContractFromListing:
    def test_demand_resource_with_token_dict(self):
        assert _extract_token_contract_from_listing(_good_listing()) == TOKEN

    def test_offer_resource_token_fallback(self):
        listing = {
            "demand_resource": {"gpu_model": "H200"},
            "offer_resource": {"token": {"contract_address": TOKEN}, "amount": 1},
        }
        assert _extract_token_contract_from_listing(listing) == TOKEN

    def test_serialized_json_string_demand(self):
        import json
        listing = {
            "demand_resource": json.dumps(
                {"token": {"contract_address": TOKEN}, "amount": 1}
            ),
            "offer_resource": {"gpu_model": "H200"},
        }
        assert _extract_token_contract_from_listing(listing) == TOKEN

    def test_no_token_field_raises(self):
        listing = {
            "demand_resource": {"amount": 1},
            "offer_resource": {"gpu_model": "H200"},
        }
        with pytest.raises(EscrowVerificationError, match="Cannot extract token"):
            _extract_token_contract_from_listing(listing)


class TestDecodeRecipientFromDemand:
    def test_round_trips(self):
        encoded = _encode_recipient(SELLER)
        decoded = _decode_recipient_from_demand(encoded)
        assert decoded == SELLER_LOWER

    def test_garbage_returns_none(self):
        assert _decode_recipient_from_demand(b"") is None
        assert _decode_recipient_from_demand(b"abc") is None


# ---------------------------------------------------------------------------
# verify_escrow_for_settlement — happy path
# ---------------------------------------------------------------------------

class TestVerifyHappyPath:
    @pytest.mark.asyncio
    async def test_passes_when_everything_matches(self):
        att = _good_attestation()
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
    async def test_passes_when_amount_exceeds_minimum(self):
        att = _good_attestation(amount=10_000)  # buyer overpaid
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,  # min = 1000
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            **_make_seams(att),
        )

    @pytest.mark.asyncio
    async def test_passes_when_no_expiration(self):
        att = _good_attestation(expiration_time=0)
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            now_unix=10**12,
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
                **_make_seams(_good_attestation()),
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
                **_make_seams(_good_attestation()),
            )

    # The EAS-address-unresolvable case is gone: alkahest_client carries
    # the EAS address inside its address_config — by the time we reach
    # the verifier, EAS is already resolved (or AlkahestClient
    # construction would have failed).

    @pytest.mark.asyncio
    async def test_rejects_when_arbiter_unresolvable(self):
        def _broken(*a, **k):
            raise ValueError("no arbiter for this chain")

        seams = _make_seams(_good_attestation())
        seams["get_recipient_arbiter_fn"] = _broken
        with pytest.raises(EscrowVerificationError, match="Cannot resolve RecipientArbiter"):
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

        seams = _make_seams(_good_attestation())
        seams["read_attestation_fn"] = _broken_read
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
    async def test_rejects_when_decode_error(self):
        att = _good_attestation(decode_error="not an erc20 escrow obligation")
        with pytest.raises(EscrowVerificationError, match="not an ERC-20 escrow obligation"):
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
    async def test_rejects_when_revoked(self):
        att = _good_attestation(revocation_time=10**12)
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
        att = _good_attestation(expiration_time=1000)
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
    async def test_rejects_when_arbiter_mismatch(self):
        att = _good_attestation(arbiter="0xdeadbeef00000000000000000000000000000000")
        with pytest.raises(EscrowVerificationError, match="arbiter mismatch"):
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
    async def test_rejects_when_demand_recipient_is_someone_else(self):
        # Buyer encoded a DIFFERENT seller's address into the demand.
        att = _good_attestation(demand=_encode_recipient(BUYER))
        with pytest.raises(EscrowVerificationError, match="recipient mismatch"):
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
    async def test_rejects_when_token_mismatch(self):
        att = _good_attestation(token="0xdeadbeef00000000000000000000000000000000")
        with pytest.raises(EscrowVerificationError, match="token mismatch"):
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
    async def test_rejects_when_amount_insufficient(self):
        # Need >= 1000 (price=1000, duration=3600). Provide 999.
        att = _good_attestation(amount=999)
        with pytest.raises(EscrowVerificationError, match="amount insufficient"):
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
    async def test_rejects_when_amount_is_none(self):
        att = _good_attestation(amount=None)
        with pytest.raises(EscrowVerificationError, match="amount insufficient"):
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
