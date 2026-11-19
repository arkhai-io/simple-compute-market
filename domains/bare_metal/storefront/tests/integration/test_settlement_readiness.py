"""Settlement readiness follows durable delivery, beyond physical provisioning."""

from dataclasses import replace
from sys import float_info

from held_loops import held_loop_controller
from market_arkhai_payments.fixtures import build_signed_receipt
from market_site_client import SiteCapacityClientError
from test_deal_controls import _client
from test_http_settlement import ADMIN_SIGNER, _app, _CapacityClient, _payment_deal


async def test_wait_retries_failed_activation_before_reporting_a_paid_deal_ready(tmp_path):
    class Capacity(_CapacityClient):
        refuse_activation = True

        async def activate_lease(self, **request):
            if self.refuse_activation:
                raise SiteCapacityClientError("activation temporarily unavailable", status_code=503)
            return await super().activate_lease(**request)

    deal = await _payment_deal(tmp_path)
    capacity = Capacity()
    runtime = replace(
        deal.runtime,
        capacity_client=capacity,
        loop_controller_factory=held_loop_controller,
    )
    deal.payments.serve(
        build_signed_receipt(signer=deal.receipt_signer, mandate=deal.data.mandate)
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with (
            _client(app, ADMIN_SIGNER, "admin", seller=deal.seller.identity) as admin,
            _client(app, deal.buyer, "buyer", seller=deal.seller.identity) as buyer,
        ):
            await admin.admin_pause_lifecycle_loops()
            await buyer.settle_agreement(deal.negotiation_id)
            # The API requires a positive timeout. Adding the smallest normal
            # float to its monotonic clock leaves a deadline of now, so this
            # exercises one read without spending a polling interval.
            pending = await admin.wait_for_settlement(
                deal.negotiation_id, timeout=float_info.min
            )
            row = await runtime.db.load_bare_metal_fulfillment_lifecycle(
                negotiation_id=deal.negotiation_id
            )
            assert row["state"] == "active"
            assert capacity.activated_at is None
            assert not await runtime.lifecycle.delivery_available(deal.negotiation_id)
            assert pending.ready is False
            assert pending.status == "settlement_verified"

            capacity.refuse_activation = False
            ready = await admin.wait_for_settlement(deal.data.transaction_id, timeout=1.0)

    assert ready.ready is True and ready.status == "ready"
    assert capacity.activated_at is not None
    assert await runtime.lifecycle.delivery_available(deal.negotiation_id)
    assert len(capacity.reserve_calls) == len(deal.provisioning.begin_calls) == 1
