"""A bare-metal storefront whose payments section is removed starts and reports its open payment deals.

Application integration: the running bare-metal app, its typed clients and
SQLite persistence (``recurring_world``). A storefront configured for payments
settles a deal, one kind per case; the app then restarts over the same
database with no payments section, so its composition builds no payments stage.
"""

import logging

import pytest
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle_client import SellerLifecycleClient

from integration.test_lifecycle_ends import accepted_once_deal
from integration.test_rate_delivery import accepted_recurring_deal, approve
from recurring_world import PAYMENTS_SERVICE, recurring_world

REASON = (
    "repair required: arkhai.payments.v1 has no lifecycle adapter; "
    "configure [Settlement].arkhai_payments service_url and service_identity"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["rate", "once"])
async def test_a_storefront_without_payments_servicing_starts_and_reports_its_open_payment_deals(
    tmp_path, caplog, kind,
):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await (accepted_recurring_deal if kind == "rate" else accepted_once_deal)(world)
        approve(payments, data)
        # Nothing is placed, so the deal stays open: its commit is allowed and
        # registered, and the site never answers.
        world.capacity.unreachable = True
        await world.buyer.settle_agreement(negotiation_id)

    caplog.set_level(logging.WARNING, logger="arkhai_bare_metal_storefront.server")
    async with recurring_world(tmp_path, payments=payments, payments_section=False) as world:
        status = await world.admin.get_system_status()
        seller = SellerLifecycleClient(world.admin)
        listed = await seller.list()
        read = await seller.read(negotiation_id)

    # It starts, reports the deal at startup in its log and its status ...
    assert f"Deal {negotiation_id} cannot be serviced: {REASON}" in caplog.text
    assert status.extra["unserviceable_deals"] == [{"negotiation_id": negotiation_id, "reason": REASON}]
    # ... and lists it repair required, its read naming the missing section.
    [deal] = listed.deals
    assert (deal.negotiation_id, deal.state) == (negotiation_id, "repair_required")
    assert read.authority.outcome.reason == REASON
