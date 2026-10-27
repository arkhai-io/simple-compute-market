"""Unit tests for storefront.utils.escrow_verification.

Covers the obligation-data normalization helpers, and verification against the
plan committed at acceptance: each rejection case (no client, chain read
failure, revoked, expired, no expiration, and each field of obligation_data
diverging) and the happy path.

The alkahest ``get_obligation`` call is injected via a test seam so tests are
fully offline — no web3, no eth-abi setup beyond what's needed to round-trip
an ABI-encoded address.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from market_alkahest.plans import (
    SettlementPlan,
    escrow_terms_to_settlement_obligation,
)
from market_alkahest.schemas import EscrowTerms

from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    _normalize_address,
    _normalize_bytes,
    _normalize_obligation_data,
    _read_chain_obligation_data,
    verify_escrow_against_plan,
)

SELLER = "0x1111111111111111111111111111111111111111"
BUYER = "0x2222222222222222222222222222222222222222"
RECIPIENT = "0x3333333333333333333333333333333333333333"
TOKEN = "0xAAAA000000000000000000000000000000000000"
TOKEN_LOWER = TOKEN.lower()
ARBITER = "0xBBBB000000000000000000000000000000000000"
ARBITER_LOWER = ARBITER.lower()
_DUMMY_CLIENT = object()
CHAIN = "anvil"
CONFIG_PATH = "/tmp/addresses.json"
_ESCROW_ADDR = "0x" + "11" * 20
_EXPIRATION = 1_800_000_000


def _encode_recipient(address: str) -> bytes:
    """Real ABI-encode of a single address — matches the buyer's encoding."""
    from eth_abi import encode as abi_encode

    return abi_encode(["address"], [address])


@dataclass
class _FakeAttestationEnvelope:
    """Mirrors the fields the verifier reads off alkahest's
    ``decoded["attestation"]`` (the EAS envelope)."""

    revocation_time: int = 0
    expiration_time: int = _EXPIRATION


@dataclass
class _FakeObligationData:
    """Mirrors alkahest's ``decoded["data"]`` typed
    ``ERC20EscrowObligation.ObligationData`` payload."""

    arbiter: str | None = ARBITER
    demand: bytes | None = None
    token: str | None = TOKEN
    amount: int | None = 1_000_000


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


@dataclass
class _FakeAttestationReferenceObligationData:
    arbiter: str = ARBITER
    demand: bytes = b"\x11\x22"
    referenced_attestation_uid: bytes = b"\x44" * 32


def _good_obligation(**overrides: Any) -> dict[str, Any]:
    """Build the ``{'attestation': ..., 'data': ...}`` dict alkahest's
    get_obligation returns, applying overrides to whichever sub-record
    carries each field. The default ``data`` funds ``_plan()``."""
    att = _FakeAttestationEnvelope()
    data = _FakeObligationData(demand=_encode_recipient(SELLER), amount=1000)
    for k, v in overrides.items():
        if hasattr(att, k):
            setattr(att, k, v)
        elif hasattr(data, k):
            setattr(data, k, v)
        else:
            raise AttributeError(f"unknown override: {k}")
    return {"attestation": att, "data": data}


def _obligation_data(*, agreed_amount: int = 1000) -> dict[str, Any]:
    """The ERC-20 escrow paying the seller's recipient condition."""
    return {
        "arbiter": ARBITER,
        "demand": "0x" + _encode_recipient(SELLER).hex(),
        "token": TOKEN,
        "amount": int(agreed_amount),
    }


def _plan(*terms: EscrowTerms) -> dict[str, Any]:
    """The plan committed at acceptance, one obligation per ``terms``."""
    terms = terms or (
        EscrowTerms(
            maker="buyer",
            chain_name=CHAIN,
            escrow_contract=_ESCROW_ADDR,
            obligation_data=_obligation_data(),
            expiration_unix=_EXPIRATION,
        ),
    )
    return SettlementPlan(
        obligations=[escrow_terms_to_settlement_obligation(t) for t in terms]
    ).model_dump(mode="json")


async def _verify(decoded: Any, *, plan=None, client=_DUMMY_CLIENT, now_unix=1_700_000_000):
    async def _get_obligation(_client, _uid):
        if isinstance(decoded, Exception):
            raise decoded
        return decoded

    return await verify_escrow_against_plan(
        escrow_uid="0xdead",
        settlement_plan=plan or _plan(),
        alkahest_client=client,
        chain_name=CHAIN,
        escrow_address=_ESCROW_ADDR,
        alkahest_address_config_path=CONFIG_PATH,
        now_unix=now_unix,
        get_obligation_fn=_get_obligation,
    )


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


class TestNormalizeAddress:
    def test_lowercases(self):
        assert (
            _normalize_address("0xABCdef0000000000000000000000000000000000")
            == "0xabcdef0000000000000000000000000000000000"
        )

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
        normalized = _normalize_obligation_data(
            {
                "arbiter": "0xABCDEF0000000000000000000000000000000000",
                "demand": b"\xab\xcd",
                "token": "0x1234000000000000000000000000000000000000",
                "amount": 999,
            }
        )
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

    def test_reads_attestation_reference_shape(self):
        assert _read_chain_obligation_data(
            _FakeAttestationReferenceObligationData()
        ) == {
            "arbiter": ARBITER_LOWER,
            "demand": "0x1122",
            "attestationUid": "0x" + "44" * 32,
        }


# ---------------------------------------------------------------------------
# verify_escrow_against_plan
# ---------------------------------------------------------------------------


class TestVerifyAgainstThePlan:
    @pytest.mark.asyncio
    async def test_passes_when_the_escrow_funds_the_plan(self):
        assert await _verify(_good_obligation()) == 0

    @pytest.mark.asyncio
    async def test_passes_with_case_insensitive_address_match(self):
        """Chain might return checksummed addresses; the plan might hold them
        lowercased (or vice versa) — normalization handles it."""
        assert await _verify(_good_obligation(arbiter=ARBITER.upper(), token=TOKEN.upper())) == 0

    @pytest.mark.asyncio
    async def test_matches_a_non_first_plan_obligation(self):
        first, second = (
            EscrowTerms(
                maker="buyer",
                chain_name=CHAIN,
                escrow_contract=_ESCROW_ADDR,
                obligation_data=_obligation_data(agreed_amount=amount),
                expiration_unix=expiration,
            )
            for amount, expiration in ((500, _EXPIRATION), (1000, _EXPIRATION + 1))
        )

        matched = await _verify(
            _good_obligation(amount=1000, expiration_time=_EXPIRATION + 1),
            plan=_plan(first, second),
        )

        assert matched == 1


class TestVerifyRejections:
    @pytest.mark.asyncio
    async def test_rejects_when_no_alkahest_client(self):
        with pytest.raises(EscrowVerificationError, match="AlkahestClient not configured"):
            await _verify(_good_obligation(), client=None)

    @pytest.mark.asyncio
    async def test_rejects_when_chain_read_fails(self):
        with pytest.raises(EscrowVerificationError, match="Failed to read escrow"):
            await _verify(RuntimeError("rpc unreachable"))

    @pytest.mark.asyncio
    async def test_rejects_when_revoked(self):
        with pytest.raises(EscrowVerificationError, match="is revoked"):
            await _verify(_good_obligation(revocation_time=10**12))

    @pytest.mark.asyncio
    async def test_rejects_when_expired(self):
        with pytest.raises(EscrowVerificationError, match="expired"):
            await _verify(_good_obligation(), now_unix=_EXPIRATION + 1)

    @pytest.mark.asyncio
    async def test_rejects_when_no_expiration_set(self):
        """The EAS contract treats expiration_time=0 as 'never expires'.
        For our escrows we always want a reclaim deadline, so refuse it."""
        with pytest.raises(EscrowVerificationError, match="no expirationTime"):
            await _verify(_good_obligation(expiration_time=0))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("override", "field"),
        [
            ({"arbiter": "0xdeadbeef00000000000000000000000000000000"}, "arbiter:"),
            # The buyer encoded a different party as the recipient.
            ({"demand": _encode_recipient(BUYER)}, "demand:"),
            ({"token": "0xdeadbeef00000000000000000000000000000000"}, "token:"),
            # Strict equality: under- and overpayment both diverge from the plan.
            ({"amount": 999}, "amount:"),
            ({"amount": 2000}, "amount:"),
        ],
        ids=["arbiter", "recipient", "token", "underpaid", "overpaid"],
    )
    async def test_rejects_an_obligation_diverging_from_the_plan(self, override, field):
        with pytest.raises(EscrowVerificationError, match="obligation_data mismatch") as exc:
            await _verify(_good_obligation(**override))
        # The diff names the diverging field.
        assert field in str(exc.value)

    @pytest.mark.asyncio
    async def test_rejects_a_plan_with_no_obligation_on_the_escrow(self):
        other = EscrowTerms(
            maker="buyer",
            chain_name=CHAIN,
            escrow_contract="0x" + "99" * 20,
            obligation_data=_obligation_data(),
            expiration_unix=_EXPIRATION,
        )
        with pytest.raises(EscrowVerificationError, match="holds no obligation"):
            await _verify(_good_obligation(), plan=_plan(other))
