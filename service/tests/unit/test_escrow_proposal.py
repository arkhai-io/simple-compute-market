"""Unit tests for service.schemas.AcceptedEscrow + EscrowProposal.

Lightweight: both types are data-only (no behavior). These pin
construction, roundtrip, and the gt=0 expiration constraint on the
proposal.
"""

import pytest
from pydantic import ValidationError

from service.schemas import AcceptedEscrow, EscrowProposal


_ESCROW = "0x" + "11" * 20
_ARBITER = "0x" + "22" * 20
_TOKEN = "0x" + "33" * 20


def test_construct_canonical_proposal():
    p = EscrowProposal(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"arbiter": _ARBITER, "token": _TOKEN},
        expiration_unix=1_800_000_000,
    )
    assert p.chain_name == "base_sepolia"
    assert p.escrow_address == _ESCROW
    assert p.fields["token"] == _TOKEN
    assert p.expiration_unix == 1_800_000_000


def test_roundtrip_via_model_dump():
    original = EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"arbiter": _ARBITER, "token": _TOKEN},
        expiration_unix=1_800_000_000,
    )
    restored = EscrowProposal.model_validate(original.model_dump())
    assert restored == original


def test_expiration_unix_must_be_positive():
    for bad in (0, -1, -1_700_000_000):
        with pytest.raises(ValidationError):
            EscrowProposal(
                chain_name="anvil",
                escrow_address=_ESCROW,
                fields={"token": _TOKEN},
                expiration_unix=bad,
            )


def test_proposal_carries_no_amount():
    """``amount`` belongs to the on-chain ObligationData at settlement,
    not the proposal — it depends on the agreed price + duration which
    aren't known at round 0."""
    fields = EscrowProposal.model_fields
    assert "amount" not in fields
    assert "agreed_price" not in fields
    assert "duration_seconds" not in fields


def test_accepted_escrow_default_empty_fields():
    a = AcceptedEscrow(chain_name="anvil", escrow_address=_ESCROW)
    assert a.fields == {}
    assert a.price_per_hour is None


def test_accepted_escrow_with_advertisement():
    a = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"arbiter": _ARBITER, "token": _TOKEN},
        price_per_hour=1_000_000,
    )
    assert a.fields["token"] == _TOKEN
    assert a.price_per_hour == 1_000_000


def test_accepted_escrow_roundtrip():
    original = AcceptedEscrow(
        chain_name="base_sepolia",
        escrow_address=_ESCROW,
        fields={"arbiter": _ARBITER, "token": _TOKEN},
        price_per_hour=1_500_000,
    )
    restored = AcceptedEscrow.model_validate(original.model_dump())
    assert restored == original
