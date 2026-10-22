"""Unit tests for the arbiter codec abstraction.

The codec layer is the swap point for adding new arbiter kinds — today
only RecipientArbiterCodec exists; tomorrow's TrustedOracleArbiterCodec
plugs into the same registry. These tests pin down:

- The registry: RecipientArbiterCodec is the only kind registered by
  default; lookup by string key returns it; unknown kinds raise.
- Extensibility: register_arbiter_codec adds new codecs without
  touching the existing flow.
- RecipientArbiterCodec encoding: SDK RecipientArbiterDemandData bytes
  round-trips through eth_abi.decode back to the same address.
"""

from dataclasses import dataclass

import pytest
from eth_abi import decode as abi_decode

from market_alkahest.alkahest import (
    AgreementContext,
    ArbiterCodec,
    RecipientArbiterCodec,
    encode_recipient_demand,
    get_arbiter_codec,
    known_arbiter_kinds,
    register_arbiter_codec,
)


_SELLER_WALLET = "0x" + "ab" * 20
_ARBITER_ADDR = "0x" + "ef" * 20


@pytest.fixture
def restore_registry():
    """Snapshot the codec registry, restore after each test that mutates it."""
    from market_alkahest import alkahest

    snapshot = dict(alkahest._ARBITER_CODECS)
    yield
    alkahest._ARBITER_CODECS.clear()
    alkahest._ARBITER_CODECS.update(snapshot)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_recipient_is_registered_by_default():
    assert "recipient_arbiter" in known_arbiter_kinds()


def test_get_arbiter_codec_returns_recipient_impl():
    codec = get_arbiter_codec("recipient_arbiter")
    assert isinstance(codec, RecipientArbiterCodec)
    assert codec.kind == "recipient_arbiter"


def test_get_arbiter_codec_raises_for_unknown_kind():
    with pytest.raises(ValueError) as exc:
        get_arbiter_codec("nonexistent_arbiter")
    msg = str(exc.value)
    assert "nonexistent_arbiter" in msg
    # Diagnostic includes the registered kinds so the operator can spot typos.
    assert "recipient_arbiter" in msg


def test_register_arbiter_codec_adds_new_kind(restore_registry):
    @dataclass
    class _StubCodec:
        kind: str = "stub_oracle"

        def resolve_address(self, chain_name, *, config_path):
            return _ARBITER_ADDR

        def encode_demand(self, agreement):
            return b"\xde\xad\xbe\xef"

    codec = _StubCodec()
    register_arbiter_codec(codec)
    assert "stub_oracle" in known_arbiter_kinds()
    assert get_arbiter_codec("stub_oracle") is codec


def test_register_arbiter_codec_replaces_existing(restore_registry):
    """Re-registering under the same kind overwrites — useful for mocks
    in test setup."""

    class _MockRecipient:
        kind = "recipient_arbiter"

        def resolve_address(self, chain_name, *, config_path):
            return _ARBITER_ADDR

        def encode_demand(self, agreement):
            return b"\x00" * 32

    register_arbiter_codec(_MockRecipient())
    codec = get_arbiter_codec("recipient_arbiter")
    assert isinstance(codec, _MockRecipient)


# ---------------------------------------------------------------------------
# RecipientArbiterCodec
# ---------------------------------------------------------------------------


def test_recipient_codec_satisfies_protocol():
    codec = RecipientArbiterCodec()
    assert isinstance(codec, ArbiterCodec)


def test_recipient_codec_encode_demand_is_abi_encoded_address():
    """The codec's demand bytes round-trip through eth_abi.decode
    back to the seller's wallet."""
    codec = RecipientArbiterCodec()
    agreement = AgreementContext(
        seller_wallet=_SELLER_WALLET,
        agreed_amount=1000,
        duration_seconds=3600,
    )
    demand = codec.encode_demand(agreement)
    (decoded_address,) = abi_decode(["address"], demand)
    assert decoded_address.lower() == _SELLER_WALLET.lower()


def test_recipient_codec_encode_matches_legacy_helper():
    """The codec and shared helper both delegate to the SDK demand codec."""
    codec = RecipientArbiterCodec()
    agreement = AgreementContext(
        seller_wallet=_SELLER_WALLET,
        agreed_amount=999,
        duration_seconds=1800,
    )
    assert codec.encode_demand(agreement) == encode_recipient_demand(_SELLER_WALLET)


def test_recipient_codec_ignores_price_and_duration():
    """RecipientArbiter binds none of the negotiated provision details
    into the demand — only the seller's wallet. Same wallet → same
    demand regardless of amount or duration."""
    codec = RecipientArbiterCodec()
    a = codec.encode_demand(AgreementContext(_SELLER_WALLET, 100, 60))
    b = codec.encode_demand(AgreementContext(_SELLER_WALLET, 999999, 3600 * 24 * 30))
    assert a == b
