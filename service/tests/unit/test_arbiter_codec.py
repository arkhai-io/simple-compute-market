"""Unit tests for the arbiter codec abstraction.

The codec layer is the swap point for adding new arbiter kinds — today
only RecipientArbiterCodec exists; tomorrow's TrustedOracleArbiterCodec
plugs into the same registry. These tests pin down:

- The registry: RecipientArbiterCodec is the only kind registered by
  default; lookup by string key returns it; unknown kinds raise.
- Extensibility: register_arbiter_codec adds new codecs without
  touching the existing flow.
- RecipientArbiterCodec encoding: abi.encode("address", seller_wallet)
  round-trips through eth_abi.decode back to the same address.
- build_payment_obligation_data dispatches through the codec: the
  produced demand bytes match what the codec returns directly.
"""

from dataclasses import dataclass

import pytest
from eth_abi import decode as abi_decode

from service.clients.alkahest import (
    AgreementContext,
    ArbiterCodec,
    RecipientArbiterCodec,
    build_payment_obligation_data,
    encode_recipient_demand,
    get_arbiter_codec,
    known_arbiter_kinds,
    register_arbiter_codec,
)


_SELLER_WALLET = "0x" + "ab" * 20
_TOKEN = "0x" + "cd" * 20
_ARBITER_ADDR = "0x" + "ef" * 20


@pytest.fixture
def restore_registry():
    """Snapshot the codec registry, restore after each test that mutates it."""
    from service.clients import alkahest

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
        get_arbiter_codec("trusted_oracle_arbiter")
    msg = str(exc.value)
    assert "trusted_oracle_arbiter" in msg
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
        agreed_price=1000,
        duration_seconds=3600,
    )
    demand = codec.encode_demand(agreement)
    (decoded_address,) = abi_decode(["address"], demand)
    assert decoded_address.lower() == _SELLER_WALLET.lower()


def test_recipient_codec_encode_matches_legacy_helper():
    """The codec must produce identical bytes to the legacy free
    function so existing on-chain escrows stay valid."""
    codec = RecipientArbiterCodec()
    agreement = AgreementContext(
        seller_wallet=_SELLER_WALLET,
        agreed_price=999,
        duration_seconds=1800,
    )
    assert codec.encode_demand(agreement) == encode_recipient_demand(_SELLER_WALLET)


def test_recipient_codec_ignores_price_and_duration():
    """RecipientArbiter binds none of the negotiated provision details
    into the demand — only the seller's wallet. Same wallet → same
    demand regardless of price or duration."""
    codec = RecipientArbiterCodec()
    a = codec.encode_demand(AgreementContext(_SELLER_WALLET, 100, 60))
    b = codec.encode_demand(AgreementContext(_SELLER_WALLET, 999999, 3600 * 24 * 30))
    assert a == b


# ---------------------------------------------------------------------------
# build_payment_obligation_data dispatch
# ---------------------------------------------------------------------------


def test_build_payment_obligation_data_dispatches_through_codec(restore_registry):
    """Replace the recipient codec with a sentinel and verify the
    builder calls it (rather than reaching past the registry into
    legacy helpers)."""
    captured: dict = {}

    class _CapturingCodec:
        kind = "recipient_arbiter"

        def resolve_address(self, chain_name, *, config_path):
            captured["resolve"] = (chain_name, config_path)
            return _ARBITER_ADDR

        def encode_demand(self, agreement):
            captured["agreement"] = agreement
            return b"\xca\xfe\xba\xbe"

    register_arbiter_codec(_CapturingCodec())

    obligation_data = build_payment_obligation_data(
        seller_wallet=_SELLER_WALLET,
        agreed_price=500,
        duration_seconds=7200,
        token_contract_address=_TOKEN,
        chain_name="some_chain",
        addr_config_path="/tmp/addrs.json",
    )

    # Dispatch happened.
    assert captured["resolve"] == ("some_chain", "/tmp/addrs.json")
    assert captured["agreement"].seller_wallet == _SELLER_WALLET
    assert captured["agreement"].agreed_price == 500
    assert captured["agreement"].duration_seconds == 7200

    # Codec's outputs landed in the obligation_data dict.
    assert obligation_data["arbiter"] == _ARBITER_ADDR
    assert obligation_data["demand"] == "0xcafebabe"
    # Non-codec fields still come from the builder.
    assert obligation_data["token"] == _TOKEN
    assert obligation_data["amount"] == 500 * 7200 // 3600


def test_build_payment_obligation_data_raises_for_unknown_arbiter_kind():
    with pytest.raises(ValueError, match="trusted_oracle_arbiter"):
        build_payment_obligation_data(
            seller_wallet=_SELLER_WALLET,
            agreed_price=1000,
            duration_seconds=3600,
            token_contract_address=_TOKEN,
            chain_name="some_chain",
            arbiter_kind="trusted_oracle_arbiter",  # not registered
        )


def test_build_payment_obligation_data_amount_unchanged_by_codec_swap(restore_registry):
    """The amount formula (price × duration / 3600) lives outside the
    codec — swapping arbiters doesn't change it."""
    class _NoopCodec:
        kind = "recipient_arbiter"

        def resolve_address(self, chain_name, *, config_path):
            return _ARBITER_ADDR

        def encode_demand(self, agreement):
            return b""

    register_arbiter_codec(_NoopCodec())
    result = build_payment_obligation_data(
        seller_wallet=_SELLER_WALLET,
        agreed_price=1000,
        duration_seconds=1800,
        token_contract_address=_TOKEN,
        chain_name="some_chain",
    )
    # 1000 × 1800 / 3600 = 500
    assert result["amount"] == 500
