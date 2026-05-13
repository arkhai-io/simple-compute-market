"""Unit tests for service.schemas.EscrowTermsProposal.

Lightweight: the type is data-only (no behavior). These pin construction,
roundtrip, and the gt=0 expiration constraint.
"""

import pytest
from pydantic import ValidationError

from service.schemas import EscrowTermsProposal


def test_construct_canonical_proposal():
    p = EscrowTermsProposal(
        escrow_kind="erc20_non_tierable",
        arbiter_kind="recipient",
        payment_token="0x" + "ab" * 20,
        expiration_unix=1_800_000_000,
    )
    assert p.escrow_kind == "erc20_non_tierable"
    assert p.arbiter_kind == "recipient"
    assert p.expiration_unix == 1_800_000_000


def test_roundtrip_via_model_dump():
    original = EscrowTermsProposal(
        escrow_kind="erc20_non_tierable",
        arbiter_kind="recipient",
        payment_token="0x" + "cd" * 20,
        expiration_unix=1_800_000_000,
    )
    restored = EscrowTermsProposal.model_validate(original.model_dump())
    assert restored == original


def test_expiration_unix_must_be_positive():
    for bad in (0, -1, -1_700_000_000):
        with pytest.raises(ValidationError):
            EscrowTermsProposal(
                escrow_kind="erc20_non_tierable",
                arbiter_kind="recipient",
                payment_token="0x" + "ab" * 20,
                expiration_unix=bad,
            )


def test_proposal_carries_no_amount():
    """The amount intentionally lives on EscrowTerms (post-agreement),
    not on the proposal — it depends on the agreed price + duration
    which aren't known at round 0."""
    fields = EscrowTermsProposal.model_fields
    assert "amount" not in fields
    assert "agreed_price" not in fields
    assert "duration_seconds" not in fields
