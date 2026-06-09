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

from market_core.schemas import EscrowProposal

from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    _extract_token_contract_from_listing,
    _normalize_address,
    _normalize_bytes,
    _normalize_obligation_data,
    _read_chain_obligation_data,
    verify_escrow_for_settlement,
)


SELLER = "0x1111111111111111111111111111111111111111"
SELLER_LOWER = SELLER.lower()
BUYER = "0x2222222222222222222222222222222222222222"
RECIPIENT = "0x3333333333333333333333333333333333333333"
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


@dataclass
class _FakeTokenBundleObligationData:
    arbiter: str = ARBITER
    demand: bytes = b"\x11\x22"
    native_amount: str = "5"
    erc20_tokens: list[str] | None = None
    erc20_amounts: list[str] | None = None
    erc721_tokens: list[str] | None = None
    erc721_token_ids: list[str] | None = None
    erc1155_tokens: list[str] | None = None
    erc1155_token_ids: list[str] | None = None
    erc1155_amounts: list[str] | None = None


@dataclass
class _FakeAttestationRequestData:
    recipient: str = RECIPIENT
    expiration_time: int = 0
    revocable: bool = False
    ref_uid: str = "0x" + "22" * 32
    data: bytes = b"\x12\x34"
    value: int = 0


@dataclass
class _FakeAttestationRequest:
    schema: str = "0x" + "33" * 32
    data: _FakeAttestationRequestData = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = _FakeAttestationRequestData()


@dataclass
class _FakeAttestationV1ObligationData:
    arbiter: str = ARBITER
    demand: bytes = b"\x11\x22"
    attestation: _FakeAttestationRequest = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.attestation is None:
            self.attestation = _FakeAttestationRequest()


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


async def _async_value(value: Any) -> Any:
    return value


def _canonical_obligation_data(
    *,
    seller_wallet: str = SELLER,
    agreed_amount: int = 1000,
    duration_seconds: int = 3600,
    token_contract_address: str = TOKEN,
    arbiter_address: str = ARBITER,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Same shape ``build_payment_obligation_data`` produces. Test seam
    feeds this back to the verifier so we don't need the real alkahest
    chain config lookups. ``agreed_amount`` is the absolute payment in
    base units of the payment token (already multiplied out from any
    per-hour rate during negotiation)."""
    return {
        "arbiter": arbiter_address,
        "demand": "0x" + _encode_recipient(seller_wallet).hex(),
        "token": token_contract_address,
        "amount": int(agreed_amount),
    }


def _make_seams(decoded: dict[str, Any]) -> dict[str, Any]:
    async def _get_obligation(client, uid):
        return decoded

    def _build(*, demands=None, recipient=None, seller_wallet=None, agreed_amount, duration_seconds,
               token_contract_address, chain_name, addr_config_path=None,
               arbiter_kind="recipient"):
        effective_recipient = recipient or seller_wallet
        return _canonical_obligation_data(
            seller_wallet=effective_recipient,
            agreed_amount=agreed_amount,
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
            "literal_fields": {"token": TOKEN},
            "rates": [{"field": "amount", "per": "hour", "value": "100"}],
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


class TestReadChainObligationData:
    def test_reads_token_bundle_shape(self):
        obligation = _FakeTokenBundleObligationData(
            erc20_tokens=[TOKEN],
            erc20_amounts=["11"],
            erc721_tokens=[TOKEN],
            erc721_token_ids=["42"],
            erc1155_tokens=[TOKEN],
            erc1155_token_ids=["3"],
            erc1155_amounts=["7"],
        )
        assert _read_chain_obligation_data(obligation) == {
            "arbiter": ARBITER_LOWER,
            "demand": "0x1122",
            "nativeAmount": 5,
            "erc20Tokens": [TOKEN_LOWER],
            "erc20Amounts": [11],
            "erc721Tokens": [TOKEN_LOWER],
            "erc721TokenIds": [42],
            "erc1155Tokens": [TOKEN_LOWER],
            "erc1155TokenIds": [3],
            "erc1155Amounts": [7],
        }

    def test_reads_attestation_v1_shape(self):
        assert _read_chain_obligation_data(_FakeAttestationV1ObligationData()) == {
            "arbiter": ARBITER_LOWER,
            "demand": "0x1122",
            "attestation": {
                "schema": "0x" + "33" * 32,
                "data": {
                    "recipient": RECIPIENT.lower(),
                    "expiration_time": 0,
                    "revocable": False,
                    "ref_uid": "0x" + "22" * 32,
                    "data": "0x1234",
                    "value": 0,
                },
            },
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
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "1"}],
            }]),
            "offer_resource": {"gpu_model": "H200"},
        }
        assert _extract_token_contract_from_listing(listing) == TOKEN

    def test_no_token_raises(self):
        listing = {
            "accepted_escrows": [{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {},
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
        with pytest.raises(EscrowVerificationError, match="Escrow recipient"):
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


# ---------------------------------------------------------------------------
# Phase 6 — proposal-path codec dispatch + literal_fields token reader
# ---------------------------------------------------------------------------


_ERC20_ESCROW_ADDR = "0x" + "11" * 20
_NATIVE_ESCROW_ADDR = "0x" + "22" * 20
_TOKEN_LEGACY = "0x" + "BB" * 20


@pytest.fixture
def patched_codec_lookup(monkeypatch):
    """Stub ``get_escrow_codec_for`` + ``address_to_slot`` so proposal-path
    verifies don't need a real chain config. Returns a capture dict the
    tests inspect."""
    from market_alkahest import alkahest as alkahest_mod

    captured: dict = {}

    class _StubErc20Codec:
        kind = "erc20_escrow_obligation_nontierable"

        def resolve_address(self, chain_name, *, config_path):
            return _ERC20_ESCROW_ADDR

    class _StubNativeCodec:
        kind = "native_token_escrow_obligation_nontierable"

        def resolve_address(self, chain_name, *, config_path):
            return _NATIVE_ESCROW_ADDR

    def _stub_codec_for(chain_name, escrow_address, *, config_path=None):
        captured.setdefault("codec_lookups", []).append(
            (chain_name, escrow_address, config_path)
        )
        if escrow_address.lower() == _ERC20_ESCROW_ADDR.lower():
            return _StubErc20Codec()
        if escrow_address.lower() == _NATIVE_ESCROW_ADDR.lower():
            return _StubNativeCodec()
        raise ValueError(f"no stub codec for address {escrow_address!r}")

    def _stub_address_to_slot(chain_name, address, *, config_path=None):
        if address.lower() == ARBITER.lower():
            return "recipient_arbiter"
        return None

    monkeypatch.setattr(
        alkahest_mod, "get_escrow_codec_for", _stub_codec_for,
    )
    monkeypatch.setattr(
        alkahest_mod, "address_to_slot", _stub_address_to_slot,
    )
    return captured


def _build_seams_capturing_token():
    """Variant of _make_seams that captures the token actually passed to
    the obligation builder, so tests can assert which token the verifier
    sourced."""
    captured: dict = {}

    async def _get_obligation(client, uid):
        return _good_obligation()

    def _build(*, demands=None, recipient=None, seller_wallet=None, agreed_amount, duration_seconds,
               token_contract_address, chain_name, addr_config_path=None,
               arbiter_kind="recipient_arbiter"):
        effective_recipient = recipient or seller_wallet
        captured["token"] = token_contract_address
        captured["arbiter_kind"] = arbiter_kind
        captured["demands"] = demands
        captured["recipient"] = effective_recipient
        return _canonical_obligation_data(
            seller_wallet=effective_recipient,
            agreed_amount=agreed_amount,
            duration_seconds=duration_seconds,
            token_contract_address=token_contract_address,
        )

    return {
        "get_obligation_fn": _get_obligation,
        "build_obligation_data_fn": _build,
    }, captured


def _erc20_proposal(*, fields=None, literal_fields=None):
    return EscrowProposal(
        chain_name=CHAIN,
        escrow_address=_ERC20_ESCROW_ADDR,
        fields=fields or {},
        literal_fields=literal_fields,
        expiration_unix=1_800_000_000,
    )


class TestVerifyProposalDispatch:
    @pytest.mark.asyncio
    async def test_reads_token_from_literal_fields(self, patched_codec_lookup):
        seams, captured = _build_seams_capturing_token()
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            escrow_proposal=_erc20_proposal(literal_fields={"token": TOKEN}),
            now_unix=1_700_000_000,
            **seams,
        )
        assert captured["token"] == TOKEN

    @pytest.mark.asyncio
    async def test_reads_recipient_from_literal_fields(self, patched_codec_lookup):
        seams, captured = _build_seams_capturing_token()
        seams["get_obligation_fn"] = (
            lambda client, uid: _async_value(
                _good_obligation(demand=_encode_recipient(RECIPIENT))
            )
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
            escrow_proposal=_erc20_proposal(
                literal_fields={"token": TOKEN, "recipient": RECIPIENT},
            ),
            now_unix=1_700_000_000,
            **seams,
        )
        assert captured["recipient"] == RECIPIENT

    @pytest.mark.asyncio
    async def test_unpinned_zero_address_falls_back_to_default_kind(self, patched_codec_lookup):
        """A zero-address proposal (escrow contract unpinned during
        negotiation) resolves the codec from the default escrow_kind rather
        than erroring — the buyer escrows against the chain's default kind."""
        seams, captured = _build_seams_capturing_token()
        proposal = EscrowProposal(
            chain_name=CHAIN,
            escrow_address="0x" + "00" * 20,
            fields={},
            literal_fields={"token": TOKEN},
            expiration_unix=1_800_000_000,
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
            escrow_proposal=proposal,
            now_unix=1_700_000_000,
            **seams,
        )
        assert captured["token"] == TOKEN

    @pytest.mark.asyncio
    async def test_ignores_legacy_fields_token(self, patched_codec_lookup):
        """``fields`` is the negotiation-amount carrier; verifier reads
        the token from ``literal_fields`` exclusively."""
        seams, captured = _build_seams_capturing_token()
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            escrow_proposal=_erc20_proposal(
                fields={"token": _TOKEN_LEGACY},
                literal_fields={"token": TOKEN},
            ),
            now_unix=1_700_000_000,
            **seams,
        )
        assert captured["token"] == TOKEN

    @pytest.mark.asyncio
    async def test_raises_when_proposal_has_no_literal_token(self, patched_codec_lookup):
        seams, _captured = _build_seams_capturing_token()
        with pytest.raises(EscrowVerificationError, match="omitted token"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                escrow_proposal=_erc20_proposal(
                    fields={"token": _TOKEN_LEGACY}, literal_fields={},
                ),
                now_unix=1_700_000_000,
                **seams,
            )

    @pytest.mark.asyncio
    async def test_verifies_non_erc20_with_generic_terms(self, patched_codec_lookup):
        """Non-ERC20 proposal verification uses the generic materialized
        obligation shape instead of an ERC20-only dispatch gate."""
        seams, _captured = _build_seams_capturing_token()
        seams.pop("build_obligation_data_fn")
        proposal = EscrowProposal(
            chain_name=CHAIN,
            escrow_address=_NATIVE_ESCROW_ADDR,
            fields={},
            literal_fields={"token": TOKEN},
            demands=[{"arbiter": ARBITER, "demand_data": {"recipient": SELLER}}],
            expiration_unix=1_800_000_000,
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
            escrow_proposal=proposal,
            now_unix=1_700_000_000,
            **seams,
        )

    @pytest.mark.asyncio
    async def test_injected_legacy_builder_still_requires_token(self, patched_codec_lookup):
        """The legacy injected builder seam is still ERC20-shaped and
        therefore requires a token."""
        seams, _captured = _build_seams_capturing_token()
        proposal = EscrowProposal(
            chain_name=CHAIN,
            escrow_address=_NATIVE_ESCROW_ADDR,
            fields={},
            expiration_unix=1_800_000_000,
        )
        with pytest.raises(EscrowVerificationError, match="omitted token"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                escrow_proposal=proposal,
                now_unix=1_700_000_000,
                **seams,
            )

    @pytest.mark.asyncio
    async def test_raises_verification_error_when_codec_lookup_fails(self, patched_codec_lookup):
        """If the address isn't registered on any codec (misconfigured
        chain config or stale tag), surface an EscrowVerificationError —
        the seller would have to abort and reconcile config off-chain."""
        seams, _captured = _build_seams_capturing_token()
        bogus = "0x" + "ff" * 20
        proposal = EscrowProposal(
            chain_name=CHAIN,
            escrow_address=bogus,
            fields={},
            literal_fields={"token": TOKEN},
            expiration_unix=1_800_000_000,
        )
        with pytest.raises(EscrowVerificationError, match="Cannot resolve escrow codec"):
            await verify_escrow_for_settlement(
                escrow_uid="0xdead",
                seller_wallet=SELLER,
                agreed_price=1000,
                agreed_duration_seconds=3600,
                listing=_good_listing(),
                alkahest_client=_DUMMY_CLIENT,
                chain_name=CHAIN,
                alkahest_address_config_path=CONFIG_PATH,
                escrow_proposal=proposal,
                now_unix=1_700_000_000,
                **seams,
            )

    @pytest.mark.asyncio
    async def test_arbiter_override_via_literal_fields(self, patched_codec_lookup):
        """Arbiter override on the proposal participates regardless of
        which sibling it lives on. The stub address_to_slot recognizes
        ARBITER → "recipient_arbiter"."""
        seams, captured = _build_seams_capturing_token()
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            escrow_proposal=_erc20_proposal(
                literal_fields={"token": TOKEN, "arbiter": ARBITER},
            ),
            now_unix=1_700_000_000,
            **seams,
        )
        assert captured["arbiter_kind"] == "recipient_arbiter"

    @pytest.mark.asyncio
    async def test_codec_lookup_uses_proposal_chain_and_address(self, patched_codec_lookup):
        """Sanity check: the codec-resolve call gets the proposal's
        (chain, address, config_path) — not the listing's or kwarg's."""
        seams, _captured = _build_seams_capturing_token()
        await verify_escrow_for_settlement(
            escrow_uid="0xdead",
            seller_wallet=SELLER,
            agreed_price=1000,
            agreed_duration_seconds=3600,
            listing=_good_listing(),
            alkahest_client=_DUMMY_CLIENT,
            chain_name=CHAIN,
            alkahest_address_config_path=CONFIG_PATH,
            escrow_proposal=_erc20_proposal(literal_fields={"token": TOKEN}),
            now_unix=1_700_000_000,
            **seams,
        )
        lookups = patched_codec_lookup["codec_lookups"]
        assert lookups == [(CHAIN, _ERC20_ESCROW_ADDR, CONFIG_PATH)]
