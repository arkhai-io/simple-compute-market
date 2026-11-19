"""The VM Alkahest stage's continuation after availability, with its collaborators mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_alkahest import RELEASE_MODELS

from market_storefront.settlement_stages import VmAlkahestSellerStage
from tests.fulfillment_fixtures import vm_delivery_evidence


@pytest.mark.asyncio
async def test_ambiguous_onchain_recovery_never_blindly_resubmits():
    db = SimpleNamespace(update_vm_delivery=AsyncMock(), update_escrow=AsyncMock())
    submit = AsyncMock(side_effect=RuntimeError("query unavailable"))
    stage = VmAlkahestSellerStage(
        None, fulfils_through_capacity=True, completes_outside_settlement=False,
        release_models=RELEASE_MODELS,
    )
    with pytest.raises(RuntimeError, match="query unavailable"):
        await stage.continue_delivery(
            evidence=vm_delivery_evidence(), db=db,
            delivery={"negotiation_id": "neg-1", "fulfillment_phase": "onchain_submission_started"},
            connection_json="{}", submit=submit, client=object(),
        )
    assert submit.await_args.kwargs["allow_submit"] is False
