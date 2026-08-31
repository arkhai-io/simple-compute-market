"""A mechanism that declines the scalar path reaches acceptance with no amount."""

from __future__ import annotations

from typing import Any

import pytest
from market_negotiation_runtime import RoundEvaluation, RoundRequest
from market_policy.negotiation_middleware import NegotiationDecision

from test_runtime import _BUYER, _SELLER, HookHarness, RecordingRepository, runtime_for

_SELECTION_PROPOSAL: dict[str, Any] = {
    "settlement_selection": {
        "mechanism": "contact-exchange.v1",
        "option_id": "bb" * 32,
        "expiration_unix": 1_900_000_000,
    },
    "fields": {},
}


class NonScalarHarness(HookHarness):
    """Take-it-or-leave-it seller: accepts the selection as proposed."""

    def __init__(self) -> None:
        super().__init__(proposal_key="amount")

    async def evaluate(self, request: RoundRequest) -> RoundEvaluation:
        self.policy_calls.append(request)
        latest = request.history[-1].proposal or {}
        return RoundEvaluation(
            our_amount=0,
            strategy_label="exact-accept",
            decision=NegotiationDecision(
                action="accept",
                proposal=dict(latest),
                reason="exact_listing",
            ),
            pinned_proposal=dict(request.history[0].proposal or {}),
            uses_scalar_amount=False,
            buyer_amount=None,
            domain_state={},
        )


@pytest.mark.asyncio
async def test_non_scalar_selection_reaches_acceptance_without_amount() -> None:
    repository = RecordingRepository()
    harness = NonScalarHarness()
    runtime = runtime_for(repository, harness)

    response = await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal=dict(_SELECTION_PROPOSAL),
        terms={"units": 2},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )

    assert response["accepted_artifact"]["amount"] == 0
    assert repository.agreements[0]["agreed_price"] == 0
    assert repository.threads["neg-fixed"]["terminal_state"] == "success"
    assert repository.effects[-1][0] == "artifacts"
