"""Claims-side arbiter codecs: encode/decode round-trips + registration."""

from __future__ import annotations

import pytest

from market_alkahest.claims import (
    AllArbiterCodec,
    ERC20SplitterArbiterCodec,
    NativeTokenSplitterArbiterCodec,
    TrustedOracleArbiterCodec,
)
from market_alkahest.alkahest import get_arbiter_codec, known_arbiter_kinds

_ORACLE = "0x" + "11" * 20
_ARB_A = "0x" + "22" * 20
_ARB_B = "0x" + "33" * 20


def test_claims_codecs_are_registered() -> None:
    kinds = known_arbiter_kinds()
    assert "trusted_oracle_arbiter" in kinds
    assert "all_arbiter" in kinds
    assert "erc20_splitter" in kinds
    assert "native_token_splitter" in kinds
    assert isinstance(
        get_arbiter_codec("trusted_oracle_arbiter"), TrustedOracleArbiterCodec
    )
    assert isinstance(get_arbiter_codec("all_arbiter"), AllArbiterCodec)
    assert isinstance(get_arbiter_codec("erc20_splitter"), ERC20SplitterArbiterCodec)
    assert isinstance(
        get_arbiter_codec("native_token_splitter"), NativeTokenSplitterArbiterCodec
    )


def test_trusted_oracle_demand_round_trip() -> None:
    codec = TrustedOracleArbiterCodec()
    encoded = codec.encode_demand_data({"oracle": _ORACLE, "data": b"\x01\x02"})
    decoded = codec.decode_demand_data(encoded)
    assert decoded["oracle"].lower() == _ORACLE
    assert decoded["data"] == b"\x01\x02"


def test_trusted_oracle_demand_accepts_hex_data_and_empty() -> None:
    codec = TrustedOracleArbiterCodec()
    encoded = codec.encode_demand_data({"oracle": _ORACLE, "data": "0x0102"})
    assert codec.decode_demand_data(encoded)["data"] == b"\x01\x02"
    empty = codec.encode_demand_data({"oracle": _ORACLE})
    assert codec.decode_demand_data(empty)["data"] == b""


def test_trusted_oracle_demand_requires_oracle() -> None:
    with pytest.raises(ValueError, match="oracle"):
        TrustedOracleArbiterCodec().encode_demand_data({"data": b""})


@pytest.mark.parametrize(
    "codec",
    [ERC20SplitterArbiterCodec(), NativeTokenSplitterArbiterCodec()],
)
def test_splitter_demand_round_trip(codec) -> None:
    encoded = codec.encode_demand_data({"oracle": _ORACLE, "data": "0x0102"})
    decoded = codec.decode_demand_data(encoded)
    assert decoded["oracle"].lower() == _ORACLE
    assert decoded["data"] == b"\x01\x02"


def test_splitter_demand_requires_oracle() -> None:
    with pytest.raises(ValueError, match="oracle"):
        ERC20SplitterArbiterCodec().encode_demand_data({"data": b""})


def test_all_arbiter_demand_round_trip() -> None:
    codec = AllArbiterCodec()
    child_a = b"\xaa" * 32
    child_b = TrustedOracleArbiterCodec().encode_demand_data(
        {"oracle": _ORACLE, "data": b"\x05"}
    )
    encoded = codec.encode_demand_data(
        {"arbiters": [_ARB_A, _ARB_B], "demands": [child_a, child_b]}
    )
    decoded = codec.decode_demand_data(encoded)
    assert [a.lower() for a in decoded["arbiters"]] == [_ARB_A, _ARB_B]
    assert decoded["demands"] == [child_a, child_b]


def test_all_arbiter_demand_validates_shape() -> None:
    codec = AllArbiterCodec()
    with pytest.raises(ValueError, match="mismatch"):
        codec.encode_demand_data({"arbiters": [_ARB_A], "demands": []})
    with pytest.raises(ValueError, match="at least one"):
        codec.encode_demand_data({"arbiters": [], "demands": []})


def test_agreement_context_encoding_is_refused() -> None:
    from market_alkahest.alkahest import AgreementContext

    ctx = AgreementContext(recipient=_ORACLE)
    with pytest.raises(ValueError, match="demand_data"):
        TrustedOracleArbiterCodec().encode_demand(ctx)
    with pytest.raises(ValueError, match="demand_data"):
        AllArbiterCodec().encode_demand(ctx)
    with pytest.raises(ValueError, match="demand_data"):
        ERC20SplitterArbiterCodec().encode_demand(ctx)
