"""Unit tests for the escrow-kind codec abstraction.

The codec layer is the SDK-dispatch swap point for escrow obligation
contracts. Tests cover:

- Registry: default alkahest escrow kinds are registered.
- Lookup by kind (direct) and by address (reverse, used at submission
  time when the buyer's EscrowTerms carries only the contract address).
- Extensibility: register_escrow_kind_codec adds new entries.
- Functional: codecs translate flat obligation_data dicts into the SDK's
  (price_data, arbiter_data, expiration) shape and propagate returned uids.
- Demand normalization: accepts hex string ("0x..." or bare) and bytes.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_alkahest.alkahest import (
    Attestation2NonTierableEscrowCodec,
    Attestation2TierableEscrowCodec,
    AttestationNonTierableEscrowCodec,
    AttestationTierableEscrowCodec,
    Erc20NonTierableEscrowCodec,
    Erc20TierableEscrowCodec,
    Erc1155NonTierableEscrowCodec,
    Erc1155TierableEscrowCodec,
    Erc721NonTierableEscrowCodec,
    Erc721TierableEscrowCodec,
    EscrowKindCodec,
    NativeTokenNonTierableEscrowCodec,
    NativeTokenTierableEscrowCodec,
    TokenBundleNonTierableEscrowCodec,
    TokenBundleTierableEscrowCodec,
    materialize_escrow_terms_from_proposal,
    materialize_escrow_terms_payload_from_proposal,
    _normalize_demand_bytes,
    get_escrow_kind_codec,
    get_escrow_kind_codec_by_address,
    get_escrow_obligation_with_codec,
    known_escrow_kinds,
    reclaim_expired_escrow_with_codec,
    register_escrow_kind_codec,
)


_ARBITER = "0x" + "ab" * 20
_TOKEN = "0x" + "cd" * 20
_TOKEN_ID = 42
_TOKEN_AMOUNT = 7
_DEMAND_HEX = "0x" + "11" * 32
_DEMAND_BYTES = bytes.fromhex("11" * 32)
_UID = "0x" + "22" * 32


@pytest.fixture
def restore_registry():
    """Snapshot the codec registry, restore after each test that mutates it."""
    from market_alkahest import alkahest

    snapshot = dict(alkahest._ESCROW_KIND_CODECS)
    yield
    alkahest._ESCROW_KIND_CODECS.clear()
    alkahest._ESCROW_KIND_CODECS.update(snapshot)


# ---------------------------------------------------------------------------
# _normalize_demand_bytes
# ---------------------------------------------------------------------------


class TestNormalizeDemandBytes:
    def test_accepts_0x_prefixed_hex(self):
        assert _normalize_demand_bytes("0xab12cd") == bytes([0xab, 0x12, 0xcd])

    def test_accepts_bare_hex(self):
        assert _normalize_demand_bytes("ab12cd") == bytes([0xab, 0x12, 0xcd])

    def test_accepts_bytes(self):
        assert _normalize_demand_bytes(b"\xab\x12") == b"\xab\x12"

    def test_accepts_bytearray(self):
        assert _normalize_demand_bytes(bytearray([0xab, 0x12])) == b"\xab\x12"

    def test_rejects_non_bytes_non_string(self):
        with pytest.raises(TypeError):
            _normalize_demand_bytes(12345)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_erc20_non_tierable_registered_by_default():
    assert "erc20_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "erc20_escrow_obligation_tierable" in known_escrow_kinds()
    assert "erc721_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "erc721_escrow_obligation_tierable" in known_escrow_kinds()
    assert "erc1155_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "erc1155_escrow_obligation_tierable" in known_escrow_kinds()
    assert "native_token_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "native_token_escrow_obligation_tierable" in known_escrow_kinds()
    assert "token_bundle_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "token_bundle_escrow_obligation_tierable" in known_escrow_kinds()
    assert "attestation_escrow_obligation_nontierable" in known_escrow_kinds()
    assert "attestation_escrow_obligation_tierable" in known_escrow_kinds()
    assert "attestation_escrow_obligation_2_nontierable" in known_escrow_kinds()
    assert "attestation_escrow_obligation_2_tierable" in known_escrow_kinds()


def test_get_escrow_kind_codec_returns_erc20_impl():
    non_tierable = get_escrow_kind_codec("erc20_escrow_obligation_nontierable")
    tierable = get_escrow_kind_codec("erc20_escrow_obligation_tierable")
    assert isinstance(non_tierable, Erc20NonTierableEscrowCodec)
    assert isinstance(tierable, Erc20TierableEscrowCodec)
    assert non_tierable.kind == "erc20_escrow_obligation_nontierable"
    assert tierable.kind == "erc20_escrow_obligation_tierable"


def test_get_escrow_kind_codec_returns_erc721_impls():
    non_tierable = get_escrow_kind_codec("erc721_escrow_obligation_nontierable")
    tierable = get_escrow_kind_codec("erc721_escrow_obligation_tierable")
    assert isinstance(non_tierable, Erc721NonTierableEscrowCodec)
    assert isinstance(tierable, Erc721TierableEscrowCodec)


def test_get_escrow_kind_codec_returns_erc1155_impls():
    non_tierable = get_escrow_kind_codec("erc1155_escrow_obligation_nontierable")
    tierable = get_escrow_kind_codec("erc1155_escrow_obligation_tierable")
    assert isinstance(non_tierable, Erc1155NonTierableEscrowCodec)
    assert isinstance(tierable, Erc1155TierableEscrowCodec)


def test_get_escrow_kind_codec_returns_native_token_impls():
    non_tierable = get_escrow_kind_codec("native_token_escrow_obligation_nontierable")
    tierable = get_escrow_kind_codec("native_token_escrow_obligation_tierable")
    assert isinstance(non_tierable, NativeTokenNonTierableEscrowCodec)
    assert isinstance(tierable, NativeTokenTierableEscrowCodec)


def test_get_escrow_kind_codec_returns_token_bundle_impls():
    non_tierable = get_escrow_kind_codec("token_bundle_escrow_obligation_nontierable")
    tierable = get_escrow_kind_codec("token_bundle_escrow_obligation_tierable")
    assert isinstance(non_tierable, TokenBundleNonTierableEscrowCodec)
    assert isinstance(tierable, TokenBundleTierableEscrowCodec)


def test_get_escrow_kind_codec_returns_attestation_impls():
    v1_non = get_escrow_kind_codec("attestation_escrow_obligation_nontierable")
    v1_tier = get_escrow_kind_codec("attestation_escrow_obligation_tierable")
    v2_non = get_escrow_kind_codec("attestation_escrow_obligation_2_nontierable")
    v2_tier = get_escrow_kind_codec("attestation_escrow_obligation_2_tierable")
    assert isinstance(v1_non, AttestationNonTierableEscrowCodec)
    assert isinstance(v1_tier, AttestationTierableEscrowCodec)
    assert isinstance(v2_non, Attestation2NonTierableEscrowCodec)
    assert isinstance(v2_tier, Attestation2TierableEscrowCodec)


def test_get_escrow_kind_codec_unknown_kind_raises():
    with pytest.raises(ValueError) as exc:
        get_escrow_kind_codec("unknown_native_token_kind")
    msg = str(exc.value)
    assert "unknown_native_token_kind" in msg
    assert "erc20_escrow_obligation_nontierable" in msg


def test_register_escrow_kind_codec_adds_new_kind(restore_registry):
    class _StubCodec:
        kind = "native_token"

        def resolve_address(self, chain_name, *, config_path):
            return "0x" + "ff" * 20

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "0xstub_uid"

        async def get_obligation(self, client, uid):
            return {"stub": True}

    codec = _StubCodec()
    register_escrow_kind_codec(codec)
    assert "native_token" in known_escrow_kinds()
    assert get_escrow_kind_codec("native_token") is codec


def test_register_escrow_kind_codec_replaces_existing(restore_registry):
    class _MockErc20:
        kind = "erc20_escrow_obligation_nontierable"

        def resolve_address(self, chain_name, *, config_path):
            return "0x" + "00" * 20

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "0xmock"

        async def get_obligation(self, client, uid):
            return None

    register_escrow_kind_codec(_MockErc20())
    assert isinstance(get_escrow_kind_codec("erc20_escrow_obligation_nontierable"), _MockErc20)


# ---------------------------------------------------------------------------
# Lookup by address
# ---------------------------------------------------------------------------


def test_get_escrow_kind_codec_by_address_matches_resolved_address(restore_registry):
    """The address-based lookup resolves through each codec's
    resolve_address() — exact-match (case-insensitive) on the
    target address."""
    target_address = "0x" + "ab" * 20

    class _CodecA:
        kind = "kind_a"

        def resolve_address(self, chain_name, *, config_path):
            return target_address

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "uid_a"

        async def get_obligation(self, client, uid):
            return {}

    class _CodecB:
        kind = "kind_b"

        def resolve_address(self, chain_name, *, config_path):
            return "0x" + "cd" * 20

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "uid_b"

        async def get_obligation(self, client, uid):
            return {}

    # Wipe and re-register so only our test codecs are searched.
    from market_alkahest import alkahest
    alkahest._ESCROW_KIND_CODECS.clear()
    register_escrow_kind_codec(_CodecA())
    register_escrow_kind_codec(_CodecB())

    # Found by exact match.
    assert get_escrow_kind_codec_by_address(target_address, "some_chain").kind == "kind_a"
    # Case-insensitive.
    assert get_escrow_kind_codec_by_address(target_address.upper(), "some_chain").kind == "kind_a"
    # Misses raise.
    with pytest.raises(ValueError, match="No escrow-kind codec found"):
        get_escrow_kind_codec_by_address("0x" + "ef" * 20, "some_chain")


def test_get_escrow_kind_codec_by_address_skips_codecs_that_dont_resolve(restore_registry):
    """A codec that can't resolve on this chain (e.g. anvil without
    override JSON) shouldn't break the lookup — it's just skipped."""
    target_address = "0x" + "ab" * 20

    class _BrokenOnThisChain:
        kind = "broken"

        def resolve_address(self, chain_name, *, config_path):
            raise ValueError("not deployed on this chain")

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return ""

        async def get_obligation(self, client, uid):
            return {}

    class _WorkingCodec:
        kind = "working"

        def resolve_address(self, chain_name, *, config_path):
            return target_address

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "ok"

        async def get_obligation(self, client, uid):
            return {}

    from market_alkahest import alkahest
    alkahest._ESCROW_KIND_CODECS.clear()
    register_escrow_kind_codec(_BrokenOnThisChain())
    register_escrow_kind_codec(_WorkingCodec())

    assert get_escrow_kind_codec_by_address(target_address, "any_chain").kind == "working"


def test_get_escrow_obligation_with_codec_uses_exact_address(restore_registry):
    target_address = "0x" + "aa" * 20

    class _Codec:
        kind = "exact"

        def resolve_address(self, chain_name, *, config_path):
            return target_address

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "0xuid"

        async def get_obligation(self, client, uid):
            return {"uid": uid}

        async def collect(self, client, uid, fulfillment_uid):
            return None

        async def reclaim_expired(self, client, uid):
            return None

        async def refund_claimed(self, **kwargs):
            return {}

    register_escrow_kind_codec(_Codec())

    codec, decoded = asyncio.run(
        get_escrow_obligation_with_codec(
            MagicMock(),
            "0xescrow",
            chain_name="anvil",
            escrow_address=target_address,
        )
    )

    assert codec.kind == "exact"
    assert decoded == {"uid": "0xescrow"}


def test_reclaim_expired_with_codec_discovers_working_codec(restore_registry):
    class _FailingCodec:
        kind = "failing"

        def resolve_address(self, chain_name, *, config_path):
            return "0x" + "01" * 20

        async def create_obligation(self, client, obligation_data, expiration_unix):
            return "0xuid"

        async def get_obligation(self, client, uid):
            raise RuntimeError("wrong codec")

        async def collect(self, client, uid, fulfillment_uid):
            return None

        async def reclaim_expired(self, client, uid):
            raise RuntimeError("wrong codec")

        async def refund_claimed(self, **kwargs):
            return {}

    class _WorkingCodec(_FailingCodec):
        kind = "working"

        def resolve_address(self, chain_name, *, config_path):
            return "0x" + "02" * 20

        async def reclaim_expired(self, client, uid):
            return {"uid": uid, "status": "reclaimed"}

    from market_alkahest import alkahest

    alkahest._ESCROW_KIND_CODECS.clear()
    register_escrow_kind_codec(_FailingCodec())
    register_escrow_kind_codec(_WorkingCodec())

    codec, receipt = asyncio.run(
        reclaim_expired_escrow_with_codec(
            MagicMock(),
            "0xescrow",
            chain_name="anvil",
        )
    )

    assert codec.kind == "working"
    assert receipt == {"uid": "0xescrow", "status": "reclaimed"}


# ---------------------------------------------------------------------------
# Erc20NonTierableEscrowCodec functional
# ---------------------------------------------------------------------------


def test_erc20_codec_satisfies_protocol():
    assert isinstance(Erc20NonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(Erc20TierableEscrowCodec(), EscrowKindCodec)


def test_erc20_create_obligation_translates_to_sdk_shape():
    """The codec splits the flat obligation_data dict into the SDK's
    expected (price_data, arbiter_data, expiration) call shape."""
    codec = Erc20NonTierableEscrowCodec()

    # Build a mock alkahest client. The SDK call shape is
    # client.erc20.util.approve(price_data, "escrow")
    # then client.erc20.escrow.non_tierable.create(price_data, arbiter_data, expiration).
    mock_client = MagicMock()
    mock_client.erc20.util.approve = AsyncMock(return_value=None)
    mock_client.erc20.escrow.non_tierable.create = AsyncMock(
        return_value={"log": {"uid": "0xdeadbeef"}},
    )

    obligation_data = {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "token": _TOKEN,
        "amount": 1000,
    }
    uid = asyncio.run(
        codec.create_obligation(mock_client, obligation_data, expiration_unix=1_800_000_000)
    )

    assert uid == "0xdeadbeef"

    # approve was called with price_data.
    mock_client.erc20.util.approve.assert_awaited_once()
    approve_args = mock_client.erc20.util.approve.await_args
    assert approve_args.args[0] == {"address": _TOKEN, "value": 1000}
    assert approve_args.args[1] == "escrow"

    # create was called with the split shape + expiration.
    mock_client.erc20.escrow.non_tierable.create.assert_awaited_once()
    create_args = mock_client.erc20.escrow.non_tierable.create.await_args
    price_data, arbiter_data, expiration = create_args.args
    assert price_data == {"address": _TOKEN, "value": 1000}
    assert arbiter_data["arbiter"] == _ARBITER
    assert arbiter_data["demand"] == _DEMAND_BYTES  # hex → bytes conversion
    assert expiration == 1_800_000_000


def test_erc20_create_obligation_accepts_bytes_demand():
    """obligation_data["demand"] can already be bytes — codec doesn't double-encode."""
    codec = Erc20NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.util.approve = AsyncMock()
    mock_client.erc20.escrow.non_tierable.create = AsyncMock(
        return_value={"log": {"uid": "0xok"}},
    )
    asyncio.run(codec.create_obligation(
        mock_client,
        {"arbiter": _ARBITER, "demand": _DEMAND_BYTES, "token": _TOKEN, "amount": 1},
        expiration_unix=1_800_000_000,
    ))
    assert mock_client.erc20.escrow.non_tierable.create.await_args.args[1]["demand"] == _DEMAND_BYTES


def test_erc20_create_obligation_missing_uid_raises():
    codec = Erc20NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.util.approve = AsyncMock()
    mock_client.erc20.escrow.non_tierable.create = AsyncMock(
        return_value={"log": {}},  # no uid key
    )
    with pytest.raises(RuntimeError, match="did not return a uid"):
        asyncio.run(codec.create_obligation(
            mock_client,
            {"arbiter": _ARBITER, "demand": _DEMAND_HEX, "token": _TOKEN, "amount": 1},
            expiration_unix=1_800_000_000,
        ))


def test_erc20_get_obligation_dispatches_to_sdk():
    """get_obligation delegates to client.erc20.escrow.non_tierable.get_obligation."""
    codec = Erc20NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.escrow.non_tierable.get_obligation = AsyncMock(
        return_value={"attestation": "att", "data": "data"},
    )
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"attestation": "att", "data": "data"}
    mock_client.erc20.escrow.non_tierable.get_obligation.assert_awaited_once_with("0xescrow")


def test_erc20_collect_and_reclaim_dispatch_to_sdk():
    codec = Erc20NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.escrow.non_tierable.collect = AsyncMock(return_value="collected")
    mock_client.erc20.escrow.non_tierable.reclaim_expired = AsyncMock(return_value="reclaimed")

    collect = asyncio.run(codec.collect(mock_client, "0xescrow", "0xfulfillment"))
    reclaim = asyncio.run(codec.reclaim_expired(mock_client, "0xescrow"))

    assert collect == "collected"
    assert reclaim == "reclaimed"
    mock_client.erc20.escrow.non_tierable.collect.assert_awaited_once_with(
        "0xescrow", "0xfulfillment",
    )
    mock_client.erc20.escrow.non_tierable.reclaim_expired.assert_awaited_once_with(
        "0xescrow",
    )


def test_erc20_tierable_create_obligation_dispatches_to_sdk():
    codec = Erc20TierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.util.approve = AsyncMock(return_value=None)
    mock_client.erc20.escrow.tierable.create = AsyncMock(
        return_value={"log": {"uid": "0xtier"}},
    )

    uid = asyncio.run(
        codec.create_obligation(
            mock_client,
            {"arbiter": _ARBITER, "demand": _DEMAND_HEX, "token": _TOKEN, "amount": 9},
            expiration_unix=1_800_000_000,
        )
    )

    assert uid == "0xtier"
    mock_client.erc20.util.approve.assert_awaited_once_with(
        {"address": _TOKEN, "value": 9},
        "escrow",
    )
    mock_client.erc20.escrow.tierable.create.assert_awaited_once()
    price_data, arbiter_data, expiration = mock_client.erc20.escrow.tierable.create.await_args.args
    assert price_data == {"address": _TOKEN, "value": 9}
    assert arbiter_data == {"arbiter": _ARBITER, "demand": _DEMAND_BYTES}
    assert expiration == 1_800_000_000


def test_erc20_tierable_get_obligation_dispatches_to_sdk():
    codec = Erc20TierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc20.escrow.tierable.get_obligation = AsyncMock(
        return_value={"kind": "erc20_tierable"},
    )
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": "erc20_tierable"}
    mock_client.erc20.escrow.tierable.get_obligation.assert_awaited_once_with("0xescrow")


def test_materialize_escrow_terms_uses_final_agreed_amount_over_proposal_amount():
    proposal = SimpleNamespace(
        chain_name="anvil",
        escrow_address="0x" + "00" * 20,
        fields={
            "arbiter": _ARBITER,
            "demand": _DEMAND_HEX,
            "token": _TOKEN,
            "amount": 7000,
        },
        expiration_unix=1_800_000_000,
    )

    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        seller_wallet_address="0x" + "12" * 20,
        agreed_amount=9500,
        duration_seconds=3600,
    )[0]

    assert terms.obligation_data["amount"] == 9500


def test_materialize_escrow_terms_payload_matches_model_dump():
    proposal = SimpleNamespace(
        chain_name="anvil",
        escrow_address="0x" + "00" * 20,
        fields={
            "arbiter": _ARBITER,
            "demand": _DEMAND_HEX,
            "token": _TOKEN,
            "amount": 7000,
        },
        expiration_unix=1_800_000_000,
    )

    expected = [
        term.model_dump()
        for term in materialize_escrow_terms_from_proposal(
            proposal=proposal,
            seller_wallet_address="0x" + "12" * 20,
            agreed_amount=9500,
            duration_seconds=3600,
        )
    ]

    assert materialize_escrow_terms_payload_from_proposal(
        proposal=proposal,
        seller_wallet_address="0x" + "12" * 20,
        agreed_amount=9500,
        duration_seconds=3600,
    ) == expected


def test_materialize_escrow_terms_assigns_indexed_bundle_rate_fields():
    proposal = SimpleNamespace(
        chain_name="anvil",
        escrow_address="0x" + "00" * 20,
        literal_fields={
            "arbiter": _ARBITER,
            "demand": _DEMAND_HEX,
            "erc20Tokens": [_TOKEN, "0x" + "ef" * 20],
        },
        rates=[
            {"field": "erc20Amounts[0]", "per": "hour", "value": 100},
            {"field": "erc20Amounts[1]", "per": "hour", "value": 200},
            {"field": "nativeAmount", "per": "hour", "value": 3},
        ],
        expiration_unix=1_800_000_000,
    )

    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        seller_wallet_address="0x" + "12" * 20,
        agreed_amount=999,
        duration_seconds=7200,
    )[0]

    assert terms.obligation_data["erc20Amounts"] == [200, 400]
    assert terms.obligation_data["nativeAmount"] == 6
    assert "amount" not in terms.obligation_data


def test_materialize_escrow_terms_does_not_add_amount_for_amountless_escrow():
    proposal = SimpleNamespace(
        chain_name="anvil",
        escrow_address="0x" + "00" * 20,
        literal_fields={
            "arbiter": _ARBITER,
            "demand": _DEMAND_HEX,
            "attestationUid": "0x" + "12" * 32,
        },
        rates=[],
        expiration_unix=1_800_000_000,
    )

    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        seller_wallet_address="0x" + "12" * 20,
        agreed_amount=999,
        duration_seconds=7200,
    )[0]

    assert terms.obligation_data["attestationUid"] == "0x" + "12" * 32
    assert "amount" not in terms.obligation_data


def test_erc20_refund_claimed_transfers_claimed_token(monkeypatch):
    refund = AsyncMock(return_value={"tx_hash": "0xrefund", "asset_kind": "erc20"})
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc20_claimed", refund)

    result = asyncio.run(
        Erc20NonTierableEscrowCodec().refund_claimed(
            private_key="pk",
            rpc_url="http://rpc",
            obligation_data={"token": _TOKEN, "amount": "17"},
            to_address=_ARBITER,
        )
    )

    assert result == {"tx_hash": "0xrefund", "asset_kind": "erc20"}
    refund.assert_awaited_once_with(
        private_key="pk",
        rpc_url="http://rpc",
        token_address=_TOKEN,
        to_address=_ARBITER,
        amount_raw=17,
    )


# ---------------------------------------------------------------------------
# Native token escrow codecs functional
# ---------------------------------------------------------------------------


def test_native_token_codecs_satisfy_protocol():
    assert isinstance(NativeTokenNonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(NativeTokenTierableEscrowCodec(), EscrowKindCodec)


def _native_token_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "amount": 1234,
    }


def _mock_native_token_client(tier_attr: str):
    mock_client = MagicMock()
    tier_client = getattr(mock_client.native_token.escrow, tier_attr)
    tier_client.create = AsyncMock(return_value={"log": {"uid": "0xnative"}})
    tier_client.get_obligation = AsyncMock(return_value={"kind": tier_attr})
    return mock_client, tier_client


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (NativeTokenNonTierableEscrowCodec(), "non_tierable"),
        (NativeTokenTierableEscrowCodec(), "tierable"),
    ],
)
def test_native_token_create_obligation_translates_to_sdk_shape(codec, tier_attr):
    mock_client, tier_client = _mock_native_token_client(tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client, _native_token_obligation_data(), expiration_unix=1_800_000_000
        )
    )

    assert uid == "0xnative"
    tier_client.create.assert_awaited_once()
    price_data, arbiter_data, expiration = tier_client.create.await_args.args
    assert price_data == {"value": 1234}
    assert arbiter_data == {"arbiter": _ARBITER, "demand": _DEMAND_BYTES}
    assert expiration == 1_800_000_000


def test_native_token_create_obligation_missing_uid_raises():
    codec = NativeTokenNonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.native_token.escrow.non_tierable.create = AsyncMock(return_value={"log": {}})
    with pytest.raises(RuntimeError, match="did not return a uid"):
        asyncio.run(
            codec.create_obligation(
                mock_client, _native_token_obligation_data(), expiration_unix=1_800_000_000
            )
        )


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (NativeTokenNonTierableEscrowCodec(), "non_tierable"),
        (NativeTokenTierableEscrowCodec(), "tierable"),
    ],
)
def test_native_token_get_obligation_dispatches_to_sdk(codec, tier_attr):
    mock_client, tier_client = _mock_native_token_client(tier_attr)
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": tier_attr}
    tier_client.get_obligation.assert_awaited_once_with("0xescrow")


def test_native_token_refund_claimed_transfers_claimed_native_value(monkeypatch):
    refund = AsyncMock(return_value={"tx_hash": "0xnative", "asset_kind": "native_token"})
    monkeypatch.setattr("market_alkahest.alkahest._refund_native_claimed", refund)

    result = asyncio.run(
        NativeTokenNonTierableEscrowCodec().refund_claimed(
            private_key="pk",
            rpc_url="http://rpc",
            obligation_data={"amount": "23"},
            to_address=_ARBITER,
        )
    )

    assert result == {"tx_hash": "0xnative", "asset_kind": "native_token"}
    refund.assert_awaited_once_with(
        private_key="pk",
        rpc_url="http://rpc",
        to_address=_ARBITER,
        amount_raw=23,
    )


# ---------------------------------------------------------------------------
# Token bundle escrow codecs functional
# ---------------------------------------------------------------------------


def test_token_bundle_codecs_satisfy_protocol():
    assert isinstance(TokenBundleNonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(TokenBundleTierableEscrowCodec(), EscrowKindCodec)


def _token_bundle_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "nativeAmount": 5,
        "erc20Tokens": [_TOKEN],
        "erc20Amounts": [11],
        "erc721Tokens": [_TOKEN],
        "erc721TokenIds": [_TOKEN_ID],
        "erc1155Tokens": [_TOKEN],
        "erc1155TokenIds": [3],
        "erc1155Amounts": [_TOKEN_AMOUNT],
    }


def _mock_token_bundle_client(tier_attr: str):
    mock_client = MagicMock()
    mock_client.token_bundle.util.approve = AsyncMock(return_value=None)
    tier_client = getattr(mock_client.token_bundle.escrow, tier_attr)
    tier_client.create = AsyncMock(return_value={"log": {"uid": "0xbundle"}})
    tier_client.get_obligation = AsyncMock(return_value={"kind": tier_attr})
    return mock_client, tier_client


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (TokenBundleNonTierableEscrowCodec(), "non_tierable"),
        (TokenBundleTierableEscrowCodec(), "tierable"),
    ],
)
def test_token_bundle_create_obligation_translates_to_sdk_shape(codec, tier_attr):
    mock_client, tier_client = _mock_token_bundle_client(tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client,
            _token_bundle_obligation_data(),
            expiration_unix=1_800_000_000,
        )
    )

    assert uid == "0xbundle"
    expected_bundle = {
        "native_amount": 5,
        "erc20s": [{"address": _TOKEN, "value": 11}],
        "erc721s": [{"address": _TOKEN, "id": _TOKEN_ID}],
        "erc1155s": [{"address": _TOKEN, "id": 3, "value": _TOKEN_AMOUNT}],
    }
    mock_client.token_bundle.util.approve.assert_awaited_once_with(
        expected_bundle, "escrow",
    )
    tier_client.create.assert_awaited_once()
    bundle_data, arbiter_data, expiration = tier_client.create.await_args.args
    assert bundle_data == expected_bundle
    assert arbiter_data == {"arbiter": _ARBITER, "demand": _DEMAND_BYTES}
    assert expiration == 1_800_000_000


def test_token_bundle_create_obligation_rejects_mismatched_arrays():
    codec = TokenBundleNonTierableEscrowCodec()
    mock_client, _tier_client = _mock_token_bundle_client("non_tierable")
    data = _token_bundle_obligation_data()
    data["erc20Amounts"] = []
    with pytest.raises(ValueError, match="length mismatch"):
        asyncio.run(
            codec.create_obligation(
                mock_client, data, expiration_unix=1_800_000_000
            )
        )


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (TokenBundleNonTierableEscrowCodec(), "non_tierable"),
        (TokenBundleTierableEscrowCodec(), "tierable"),
    ],
)
def test_token_bundle_get_obligation_dispatches_to_sdk(codec, tier_attr):
    mock_client, tier_client = _mock_token_bundle_client(tier_attr)
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": tier_attr}
    tier_client.get_obligation.assert_awaited_once_with("0xescrow")


def test_token_bundle_refund_claimed_fans_out_to_token_transfers(monkeypatch):
    native = AsyncMock(return_value={"asset_kind": "native_token", "tx_hash": "0xn"})
    erc20 = AsyncMock(return_value={"asset_kind": "erc20", "tx_hash": "0x20"})
    erc721 = AsyncMock(return_value={"asset_kind": "erc721", "tx_hash": "0x721"})
    erc1155 = AsyncMock(return_value={"asset_kind": "erc1155", "tx_hash": "0x1155"})
    monkeypatch.setattr("market_alkahest.alkahest._refund_native_claimed", native)
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc20_claimed", erc20)
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc721_claimed", erc721)
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc1155_claimed", erc1155)

    result = asyncio.run(
        TokenBundleNonTierableEscrowCodec().refund_claimed(
            private_key="pk",
            rpc_url="http://rpc",
            obligation_data=_token_bundle_obligation_data(),
            to_address=_ARBITER,
        )
    )

    assert result == {
        "asset_kind": "token_bundle",
        "transfers": [
            {"asset_kind": "native_token", "tx_hash": "0xn"},
            {"asset_kind": "erc20", "tx_hash": "0x20"},
            {"asset_kind": "erc721", "tx_hash": "0x721"},
            {"asset_kind": "erc1155", "tx_hash": "0x1155"},
        ],
    }
    native.assert_awaited_once_with(
        private_key="pk", rpc_url="http://rpc", to_address=_ARBITER, amount_raw=5
    )
    erc20.assert_awaited_once_with(
        private_key="pk", rpc_url="http://rpc", token_address=_TOKEN,
        to_address=_ARBITER, amount_raw=11,
    )
    erc721.assert_awaited_once_with(
        private_key="pk", rpc_url="http://rpc", token_address=_TOKEN,
        to_address=_ARBITER, token_id=_TOKEN_ID,
    )
    erc1155.assert_awaited_once_with(
        private_key="pk", rpc_url="http://rpc", token_address=_TOKEN,
        to_address=_ARBITER, token_id=3, amount_raw=_TOKEN_AMOUNT,
    )


# ---------------------------------------------------------------------------
# Attestation escrow codecs functional
# ---------------------------------------------------------------------------


def test_attestation_codecs_satisfy_protocol():
    assert isinstance(AttestationNonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(AttestationTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(Attestation2NonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(Attestation2TierableEscrowCodec(), EscrowKindCodec)


def _attestation_request():
    return {
        "schema": _UID,
        "data": {
            "recipient": _TOKEN,
            "expiration_time": 0,
            "revocable": False,
            "ref_uid": _UID,
            "data": "0x1234",
            "value": 0,
        },
    }


def _attestation_v1_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "attestation": _attestation_request(),
    }


def _attestation_v2_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "attestationUid": _UID,
    }


def _mock_attestation_client(version_attr: str, tier_attr: str):
    mock_client = MagicMock()
    version_client = getattr(mock_client.attestation.escrow, version_attr)
    tier_client = getattr(version_client, tier_attr)
    tier_client.create = AsyncMock(return_value={"log": {"uid": "0xatt"}})
    tier_client.get_obligation = AsyncMock(return_value={"kind": f"{version_attr}:{tier_attr}"})
    return mock_client, tier_client


@pytest.mark.parametrize(
    ("codec", "version_attr", "tier_attr"),
    [
        (AttestationNonTierableEscrowCodec(), "v1", "non_tierable"),
        (AttestationTierableEscrowCodec(), "v1", "tierable"),
    ],
)
def test_attestation_v1_create_obligation_translates_to_sdk_shape(
    codec, version_attr, tier_attr,
):
    mock_client, tier_client = _mock_attestation_client(version_attr, tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client,
            _attestation_v1_obligation_data(),
            expiration_unix=1_800_000_000,
        )
    )

    assert uid == "0xatt"
    attestation, arbiter_data, expiration = tier_client.create.await_args.args
    assert attestation.schema == _UID
    assert attestation.data.data == bytes.fromhex("1234")
    assert arbiter_data == {"arbiter": _ARBITER, "demand": _DEMAND_BYTES}
    assert expiration == 1_800_000_000


@pytest.mark.parametrize(
    ("codec", "version_attr", "tier_attr"),
    [
        (Attestation2NonTierableEscrowCodec(), "v2", "non_tierable"),
        (Attestation2TierableEscrowCodec(), "v2", "tierable"),
    ],
)
def test_attestation_v2_create_obligation_translates_to_sdk_shape(
    codec, version_attr, tier_attr,
):
    mock_client, tier_client = _mock_attestation_client(version_attr, tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client,
            _attestation_v2_obligation_data(),
            expiration_unix=1_800_000_000,
        )
    )

    assert uid == "0xatt"
    attestation_uid, arbiter_data, expiration = tier_client.create.await_args.args
    assert attestation_uid == _UID
    assert arbiter_data == {"arbiter": _ARBITER, "demand": _DEMAND_BYTES}
    assert expiration == 1_800_000_000


def test_attestation_v2_create_obligation_missing_uid_raises():
    codec = Attestation2NonTierableEscrowCodec()
    mock_client, _tier_client = _mock_attestation_client("v2", "non_tierable")
    data = _attestation_v2_obligation_data()
    data.pop("attestationUid")
    with pytest.raises(ValueError, match="attestationUid is required"):
        asyncio.run(
            codec.create_obligation(
                mock_client, data, expiration_unix=1_800_000_000
            )
        )


@pytest.mark.parametrize(
    ("codec", "version_attr", "tier_attr"),
    [
        (AttestationNonTierableEscrowCodec(), "v1", "non_tierable"),
        (AttestationTierableEscrowCodec(), "v1", "tierable"),
        (Attestation2NonTierableEscrowCodec(), "v2", "non_tierable"),
        (Attestation2TierableEscrowCodec(), "v2", "tierable"),
    ],
)
def test_attestation_get_obligation_dispatches_to_sdk(codec, version_attr, tier_attr):
    mock_client, tier_client = _mock_attestation_client(version_attr, tier_attr)
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": f"{version_attr}:{tier_attr}"}
    tier_client.get_obligation.assert_awaited_once_with("0xescrow")


def test_attestation_refund_claimed_is_unsupported():
    with pytest.raises(NotImplementedError, match="do not carry a token refund asset"):
        asyncio.run(
            AttestationNonTierableEscrowCodec().refund_claimed(
                private_key="pk",
                rpc_url="http://rpc",
                obligation_data=_attestation_v1_obligation_data(),
                to_address=_ARBITER,
            )
        )


# ---------------------------------------------------------------------------
# ERC721 escrow codecs functional
# ---------------------------------------------------------------------------


def test_erc721_codecs_satisfy_protocol():
    assert isinstance(Erc721NonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(Erc721TierableEscrowCodec(), EscrowKindCodec)


def _erc721_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "token": _TOKEN,
        "tokenId": _TOKEN_ID,
    }


def _mock_erc721_client(tier_attr: str):
    mock_client = MagicMock()
    mock_client.erc721.util.approve = AsyncMock(return_value=None)
    tier_client = getattr(mock_client.erc721.escrow, tier_attr)
    tier_client.create = AsyncMock(return_value={"log": {"uid": "0x721"}})
    tier_client.get_obligation = AsyncMock(return_value={"kind": tier_attr})
    return mock_client, tier_client


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (Erc721NonTierableEscrowCodec(), "non_tierable"),
        (Erc721TierableEscrowCodec(), "tierable"),
    ],
)
def test_erc721_create_obligation_translates_to_sdk_shape(codec, tier_attr):
    mock_client, tier_client = _mock_erc721_client(tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client, _erc721_obligation_data(), expiration_unix=1_800_000_000
        )
    )

    assert uid == "0x721"

    if tier_attr == "non_tierable":
        mock_client.erc721.util.approve.assert_awaited_once()
        approve_args = mock_client.erc721.util.approve.await_args
        assert approve_args.args[0] == {"address": _TOKEN, "id": _TOKEN_ID}
        assert approve_args.args[1] == "escrow"
    else:
        mock_client.erc721.util.approve.assert_not_awaited()

    tier_client.create.assert_awaited_once()
    price_data, arbiter_data, expiration = tier_client.create.await_args.args
    assert price_data == {"address": _TOKEN, "id": _TOKEN_ID}
    assert arbiter_data["arbiter"] == _ARBITER
    assert arbiter_data["demand"] == _DEMAND_BYTES
    assert expiration == 1_800_000_000


def test_erc721_create_obligation_missing_uid_raises():
    codec = Erc721NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc721.util.approve = AsyncMock()
    mock_client.erc721.escrow.non_tierable.create = AsyncMock(return_value={"log": {}})
    with pytest.raises(RuntimeError, match="did not return a uid"):
        asyncio.run(
            codec.create_obligation(
                mock_client, _erc721_obligation_data(), expiration_unix=1_800_000_000
            )
        )


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (Erc721NonTierableEscrowCodec(), "non_tierable"),
        (Erc721TierableEscrowCodec(), "tierable"),
    ],
)
def test_erc721_get_obligation_dispatches_to_sdk(codec, tier_attr):
    mock_client, tier_client = _mock_erc721_client(tier_attr)
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": tier_attr}
    tier_client.get_obligation.assert_awaited_once_with("0xescrow")


def test_erc721_refund_claimed_transfers_claimed_nft(monkeypatch):
    refund = AsyncMock(return_value={"tx_hash": "0x721", "asset_kind": "erc721"})
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc721_claimed", refund)

    result = asyncio.run(
        Erc721NonTierableEscrowCodec().refund_claimed(
            private_key="pk",
            rpc_url="http://rpc",
            obligation_data={"token": _TOKEN, "tokenId": "42"},
            to_address=_ARBITER,
        )
    )

    assert result == {"tx_hash": "0x721", "asset_kind": "erc721"}
    refund.assert_awaited_once_with(
        private_key="pk",
        rpc_url="http://rpc",
        token_address=_TOKEN,
        to_address=_ARBITER,
        token_id=42,
    )


# ---------------------------------------------------------------------------
# ERC1155 escrow codecs functional
# ---------------------------------------------------------------------------


def test_erc1155_codecs_satisfy_protocol():
    assert isinstance(Erc1155NonTierableEscrowCodec(), EscrowKindCodec)
    assert isinstance(Erc1155TierableEscrowCodec(), EscrowKindCodec)


def _erc1155_obligation_data():
    return {
        "arbiter": _ARBITER,
        "demand": _DEMAND_HEX,
        "token": _TOKEN,
        "tokenId": _TOKEN_ID,
        "amount": _TOKEN_AMOUNT,
    }


def _mock_erc1155_client(tier_attr: str):
    mock_client = MagicMock()
    mock_client.erc1155.util.approve_all = AsyncMock(return_value=None)
    tier_client = getattr(mock_client.erc1155.escrow, tier_attr)
    tier_client.create = AsyncMock(return_value={"log": {"uid": "0x1155"}})
    tier_client.get_obligation = AsyncMock(return_value={"kind": tier_attr})
    return mock_client, tier_client


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (Erc1155NonTierableEscrowCodec(), "non_tierable"),
        (Erc1155TierableEscrowCodec(), "tierable"),
    ],
)
def test_erc1155_create_obligation_translates_to_sdk_shape(codec, tier_attr):
    mock_client, tier_client = _mock_erc1155_client(tier_attr)

    uid = asyncio.run(
        codec.create_obligation(
            mock_client, _erc1155_obligation_data(), expiration_unix=1_800_000_000
        )
    )

    assert uid == "0x1155"

    mock_client.erc1155.util.approve_all.assert_awaited_once()
    approve_args = mock_client.erc1155.util.approve_all.await_args
    assert approve_args.args[0] == _TOKEN
    assert approve_args.args[1] == "escrow"

    tier_client.create.assert_awaited_once()
    price_data, arbiter_data, expiration = tier_client.create.await_args.args
    assert price_data == {"address": _TOKEN, "id": _TOKEN_ID, "value": _TOKEN_AMOUNT}
    assert arbiter_data["arbiter"] == _ARBITER
    assert arbiter_data["demand"] == _DEMAND_BYTES
    assert expiration == 1_800_000_000


def test_erc1155_create_obligation_missing_uid_raises():
    codec = Erc1155NonTierableEscrowCodec()
    mock_client = MagicMock()
    mock_client.erc1155.util.approve_all = AsyncMock()
    mock_client.erc1155.escrow.non_tierable.create = AsyncMock(return_value={"log": {}})
    with pytest.raises(RuntimeError, match="did not return a uid"):
        asyncio.run(
            codec.create_obligation(
                mock_client, _erc1155_obligation_data(), expiration_unix=1_800_000_000
            )
        )


@pytest.mark.parametrize(
    ("codec", "tier_attr"),
    [
        (Erc1155NonTierableEscrowCodec(), "non_tierable"),
        (Erc1155TierableEscrowCodec(), "tierable"),
    ],
)
def test_erc1155_get_obligation_dispatches_to_sdk(codec, tier_attr):
    mock_client, tier_client = _mock_erc1155_client(tier_attr)
    result = asyncio.run(codec.get_obligation(mock_client, "0xescrow"))
    assert result == {"kind": tier_attr}
    tier_client.get_obligation.assert_awaited_once_with("0xescrow")


def test_erc1155_refund_claimed_transfers_claimed_token_amount(monkeypatch):
    refund = AsyncMock(return_value={"tx_hash": "0x1155", "asset_kind": "erc1155"})
    monkeypatch.setattr("market_alkahest.alkahest._refund_erc1155_claimed", refund)

    result = asyncio.run(
        Erc1155NonTierableEscrowCodec().refund_claimed(
            private_key="pk",
            rpc_url="http://rpc",
            obligation_data={"token": _TOKEN, "tokenId": "42", "amount": "7"},
            to_address=_ARBITER,
        )
    )

    assert result == {"tx_hash": "0x1155", "asset_kind": "erc1155"}
    refund.assert_awaited_once_with(
        private_key="pk",
        rpc_url="http://rpc",
        token_address=_TOKEN,
        to_address=_ARBITER,
        token_id=42,
        amount_raw=7,
    )
