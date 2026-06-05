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
from unittest.mock import AsyncMock, MagicMock

import pytest

from service.clients.alkahest import (
    Erc20NonTierableEscrowCodec,
    Erc20TierableEscrowCodec,
    Erc1155NonTierableEscrowCodec,
    Erc1155TierableEscrowCodec,
    Erc721NonTierableEscrowCodec,
    Erc721TierableEscrowCodec,
    EscrowKindCodec,
    NativeTokenNonTierableEscrowCodec,
    NativeTokenTierableEscrowCodec,
    _normalize_demand_bytes,
    get_escrow_kind_codec,
    get_escrow_kind_codec_by_address,
    known_escrow_kinds,
    register_escrow_kind_codec,
)


_ARBITER = "0x" + "ab" * 20
_TOKEN = "0x" + "cd" * 20
_TOKEN_ID = 42
_TOKEN_AMOUNT = 7
_DEMAND_HEX = "0x" + "11" * 32
_DEMAND_BYTES = bytes.fromhex("11" * 32)


@pytest.fixture
def restore_registry():
    """Snapshot the codec registry, restore after each test that mutates it."""
    from service.clients import alkahest

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
    from service.clients import alkahest
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

    from service.clients import alkahest
    alkahest._ESCROW_KIND_CODECS.clear()
    register_escrow_kind_codec(_BrokenOnThisChain())
    register_escrow_kind_codec(_WorkingCodec())

    assert get_escrow_kind_codec_by_address(target_address, "any_chain").kind == "working"


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
