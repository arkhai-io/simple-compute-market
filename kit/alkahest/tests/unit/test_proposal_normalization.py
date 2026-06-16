from __future__ import annotations

from market_alkahest.schemas import (
    EscrowProposal,
    match_accepted_escrow,
    normalize_proposal_against_accepted_escrows,
)


_ESCROW = "0x" + "11" * 20
_OTHER_ESCROW = "0x" + "22" * 20
_TOKEN = "0x" + "aa" * 20


def _proposal(**overrides) -> EscrowProposal:
    data = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"amount": 100},
        "expiration_unix": 1_800_000_000,
    }
    data.update(overrides)
    return EscrowProposal(**data)


def test_match_accepted_escrow_matches_chain_and_address_case_insensitively() -> None:
    accepted = [
        {"chain_name": "base", "escrow_address": _ESCROW},
        {"chain_name": "anvil", "escrow_address": _ESCROW.upper()},
    ]

    assert match_accepted_escrow(accepted, _proposal()) is accepted[1]


def test_match_accepted_escrow_returns_none_when_no_shape_matches() -> None:
    accepted = [{"chain_name": "anvil", "escrow_address": _OTHER_ESCROW}]

    assert match_accepted_escrow(accepted, _proposal()) is None


def test_normalize_merges_listing_literals_and_rates() -> None:
    accepted = [{
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN, "recipient": "0xSeller"},
        "rates": [{"field": "amount", "per": "hour", "value": "500"}],
    }]
    proposal = _proposal(literal_fields={"recipient": "0xOverride"})

    normalized = normalize_proposal_against_accepted_escrows(
        proposal=proposal,
        accepted_escrows=accepted,
    )

    assert normalized is not None
    assert normalized.literal_fields == {
        "token": _TOKEN,
        "recipient": "0xOverride",
    }
    assert [rate.model_dump() for rate in normalized.rates or []] == [
        {"field": "amount", "per": "hour", "value": "500"}
    ]


def test_normalize_preserves_proposal_rates_when_present() -> None:
    accepted = [{
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": "500"}],
    }]
    proposal = _proposal(rates=[{"field": "amount", "per": "hour", "value": "100"}])

    normalized = normalize_proposal_against_accepted_escrows(
        proposal=proposal,
        accepted_escrows=accepted,
    )

    assert normalized is not None
    assert [rate.model_dump() for rate in normalized.rates or []] == [
        {"field": "amount", "per": "hour", "value": "100"}
    ]


def test_normalize_returns_original_proposal_when_no_match() -> None:
    proposal = _proposal()

    assert normalize_proposal_against_accepted_escrows(
        proposal=proposal,
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": _OTHER_ESCROW}],
    ) is proposal
