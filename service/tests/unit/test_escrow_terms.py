"""Unit tests for service.schemas.EscrowTerms.

The type is a flat mirror of an alkahest escrow obligation's
doObligation call shape: it stores `obligation_data` as a literal
ObligationData dict and the rest is metadata (maker + escrow contract
address + absolute expiration). These tests pin down:

- Construction with an ERC20-shaped obligation_data.
- Universal-field access (arbiter, demand) regardless of escrow kind.
- Round-trip serialization (model_dump → model_validate).
- maker discrimination accepts buyer/seller and rejects others.
- expiration_unix must be positive (gt=0 constraint).

These don't test on-chain behavior — the model is pure data; on-chain
verification happens against `obligation_data` byte-by-byte at
settlement time.
"""

import pytest
from pydantic import ValidationError

from service.schemas import EscrowTerms


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _erc20_obligation_data(
    arbiter="0x" + "aa" * 20,
    demand="0x" + "11" * 32,
    token="0x" + "bb" * 20,
    amount=1_000_000,
):
    """ERC20EscrowObligation.ObligationData shape:
        (address arbiter, bytes demand, address token, uint256 amount)
    """
    return {"arbiter": arbiter, "demand": demand, "token": token, "amount": amount}


def test_construct_with_erc20_obligation_data():
    terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(),
        expiration_unix=1_800_000_000,
    )
    assert terms.maker == "buyer"
    assert terms.escrow_contract == "0x" + "ee" * 20
    assert terms.expiration_unix == 1_800_000_000


def test_universal_arbiter_and_demand_extraction():
    """Every escrow obligation starts with (address arbiter, bytes demand, …)
    so consumers can grab those two without knowing the escrow kind."""
    arbiter_addr = "0x" + "cd" * 20
    demand_bytes = "0x" + "42" * 32
    terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(arbiter=arbiter_addr, demand=demand_bytes),
        expiration_unix=1_800_000_000,
    )
    assert terms.obligation_data["arbiter"] == arbiter_addr
    assert terms.obligation_data["demand"] == demand_bytes


def test_obligation_data_carries_payment_fields():
    """Payment fields (token+amount for ERC20) come through unchanged.
    The contract decides their shape; EscrowTerms doesn't reinterpret."""
    terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(token="0x" + "f1" * 20, amount=42),
        expiration_unix=1_800_000_000,
    )
    assert terms.obligation_data["token"] == "0x" + "f1" * 20
    assert terms.obligation_data["amount"] == 42


def test_native_token_obligation_data_shape():
    """NativeTokenEscrowObligation.ObligationData has no `token` field —
    just (arbiter, demand, amount). The model accepts any shape that
    matches the contract."""
    terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data={
            "arbiter": "0x" + "aa" * 20,
            "demand": "0x" + "11" * 32,
            "amount": 5_000_000_000_000_000_000,  # 5 ETH in wei
        },
        expiration_unix=1_800_000_000,
    )
    assert "token" not in terms.obligation_data
    assert terms.obligation_data["amount"] == 5_000_000_000_000_000_000


# ---------------------------------------------------------------------------
# Roundtrip / serialization
# ---------------------------------------------------------------------------


def test_roundtrip_via_model_dump_and_validate():
    original = EscrowTerms(
        maker="seller",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(),
        expiration_unix=1_800_000_000,
    )
    dumped = original.model_dump()
    restored = EscrowTerms.model_validate(dumped)
    assert restored == original


def test_obligation_data_dict_preserves_int_values():
    """Pydantic shouldn't coerce uint256 amounts through JSON-style
    serialization in model_dump — the dict round-trip stays as ints."""
    terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(amount=2**200),
        expiration_unix=1_800_000_000,
    )
    dumped = terms.model_dump()
    assert dumped["obligation_data"]["amount"] == 2**200
    assert isinstance(dumped["obligation_data"]["amount"], int)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_maker_rejects_arbitrary_string():
    with pytest.raises(ValidationError) as exc:
        EscrowTerms(
            maker="oracle",  # type: ignore[arg-type]
            escrow_contract="0x" + "ee" * 20,
            obligation_data=_erc20_obligation_data(),
            expiration_unix=1_800_000_000,
        )
    assert "maker" in str(exc.value).lower()


def test_maker_accepts_both_sides():
    """A negotiation can produce buyer-made AND seller-made escrows
    (e.g. payment + seller penalty deposit). Both values are valid."""
    buyer_terms = EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(),
        expiration_unix=1_800_000_000,
    )
    seller_terms = EscrowTerms(
        maker="seller",
        escrow_contract="0x" + "ee" * 20,
        obligation_data=_erc20_obligation_data(),
        expiration_unix=1_800_000_000,
    )
    assert buyer_terms.maker == "buyer"
    assert seller_terms.maker == "seller"


def test_expiration_unix_must_be_positive():
    """The gt=0 constraint catches zero (which the EAS contracts use as
    a sentinel for 'never expires') and negative values."""
    for bad_value in (0, -1, -1_700_000_000):
        with pytest.raises(ValidationError):
            EscrowTerms(
                maker="buyer",
                escrow_contract="0x" + "ee" * 20,
                obligation_data=_erc20_obligation_data(),
                expiration_unix=bad_value,
            )


def test_negotiation_outcome_is_a_list_of_terms():
    """The convention is `list[EscrowTerms]` (not a wrapper type) so a
    single escrow today and a multi-escrow future (payment + bond, or
    block-by-block) use the same outer shape."""
    escrows: list[EscrowTerms] = [
        EscrowTerms(
            maker="buyer",
            escrow_contract="0x" + "ee" * 20,
            obligation_data=_erc20_obligation_data(amount=100),
            expiration_unix=1_800_000_000,
        ),
        EscrowTerms(
            maker="seller",
            escrow_contract="0x" + "ee" * 20,
            obligation_data=_erc20_obligation_data(amount=10),
            expiration_unix=1_800_000_000,
        ),
    ]
    assert [e.maker for e in escrows] == ["buyer", "seller"]
    assert sum(e.obligation_data["amount"] for e in escrows) == 110
