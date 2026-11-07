"""The API-credit opening guard admits a selection's mechanism parameters."""

from __future__ import annotations

from arkhai_apicredits.negotiation.policies import api_credits_round_zero_guard
from market_policy.negotiation_middleware import NegotiationContext, NegotiationRound

_OPTION_ID = "cd" * 32


def _round(selection: dict) -> list[NegotiationRound]:
    return [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal={"fields": {}, "settlement_selection": selection},
        )
    ]


def _context() -> NegotiationContext:
    context = NegotiationContext(
        direction="maximize",
        our_reference_amount=1000,
        listing={
            "listing_id": "L-credits",
            "settlement_options": [
                {
                    "option_id": _OPTION_ID,
                    "price": {"asset": "USD/2", "rates": []},
                    "settlement": {"schema": "arkhai.payments.v1"},
                }
            ],
        },
    )
    context.intermediate["requested_quantity"] = 10
    return context


def _selection(**extra) -> dict:
    return {
        "option_id": _OPTION_ID,
        "settlement": {"schema": "arkhai.payments.v1"},
        "expiration_unix": 1_900_000_000,
        **extra,
    }


def _rejection(decision) -> str | None:
    return decision.reason if decision is not None and decision.action == "reject" else None


def test_selection_with_payer_params_is_not_refused_as_malformed():
    params = {"payer_account": "11111111-1111-4111-8111-111111111111"}
    decision, _context_out = api_credits_round_zero_guard(
        _round(_selection(settlement={"schema": "arkhai.payments.v1", **params})),
        _context(),
    )
    assert "selection has invalid fields" not in (_rejection(decision) or "")


def test_selection_with_empty_params_is_not_refused_as_malformed():
    decision, _context_out = api_credits_round_zero_guard(
        _round(_selection()), _context()
    )
    assert "selection has invalid fields" not in (_rejection(decision) or "")


def test_selection_with_unknown_fields_or_non_mapping_params_is_refused():
    for selection in (_selection(amount="5"), _selection(settlement=["payer"])):
        decision, _context_out = api_credits_round_zero_guard(_round(selection), _context())
        assert _rejection(decision) == "invalid_settlement_selection:selection has invalid fields"
