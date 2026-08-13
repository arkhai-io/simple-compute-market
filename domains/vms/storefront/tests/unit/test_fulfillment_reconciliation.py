from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.settlement.fulfillment import (
    FulfillmentReconciliationUnavailable,
    reconcile_or_submit_compute_fulfillment,
)


@pytest.mark.asyncio
async def test_reconciliation_adopts_matching_attestation_without_submission():
    obligation = SimpleNamespace(do_obligation=AsyncMock())
    client = SimpleNamespace(string_obligation=obligation)
    uid = await reconcile_or_submit_compute_fulfillment(
        client=client,
        escrow_uid="escrow-1",
        connection_details="details",
        allow_submit=False,
        query_fulfillments=AsyncMock(return_value=["att-1"]),
    )
    assert uid == "att-1"
    obligation.do_obligation.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_without_query_surface_refuses_blind_submission():
    client = SimpleNamespace(
        string_obligation=SimpleNamespace(do_obligation=AsyncMock())
    )
    with pytest.raises(FulfillmentReconciliationUnavailable):
        await reconcile_or_submit_compute_fulfillment(
            client=client,
            escrow_uid="escrow-1",
            connection_details="details",
            allow_submit=False,
        )
    client.string_obligation.do_obligation.assert_not_awaited()
