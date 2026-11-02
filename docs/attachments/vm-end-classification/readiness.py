"""Gate the VM lane on healthy authorities and signed dispute-bearing publication.

Run inside the configured E2E buyer image, from /app, before pytest. All seeded
principals and capacity are deterministic development fixtures, never public
network identities or real hardware.
"""

import json
import urllib.request
from contextlib import ExitStack, contextmanager

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import storefront_loops_held
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.scenarios.vms import conftest as lane
from tests.e2e.roles.scenarios.vms.host_registry import provision_e2e_executor, refresh_storefront_projections
from tests.e2e.roles.scenarios.vms.test_full_deal import ACCEPTED_ESCROWS, OFFER_RESOURCE


config = configured_payments()
mediation_url = str(settings.get("PAYMENTS.MEDIATION_URL", "")).rstrip("/")
assert mediation_url, "PAYMENTS.MEDIATION_URL is required for lifecycle qualification"
assert json.load(urllib.request.urlopen(mediation_url + "/health", timeout=5))["status"] == "ok"
description = json.load(urllib.request.urlopen(mediation_url + "/", timeout=5))
with ExitStack() as stack:
    def client(fixture):
        return stack.enter_context(contextmanager(fixture.__wrapped__)())

    admin = client(lane.storefront_admin_client)
    seller = client(lane.storefront_seller_client)
    registry = client(lane.registry_client)
    provisioning = client(lane.provisioning_client)
    capacity = lane.site_capacity_admin_client.__wrapped__()
    assert admin.get_health().status == "ok"
    assert provisioning.get_system_status().status == "ok"
    with storefront_loops_held(admin):
        resource_id = "compute-e2e-lifecycle-readiness"
        provision_e2e_executor(provisioning, capacity,
            host="lifecycle-readiness", pool_id="lifecycle-readiness", resource_id=resource_id,
            sellable_units=1, attributes={"gpu_model": "RTX 5080", "region": "California, US", "sla": "90.0"})
        refresh_storefront_projections(admin)
        resource = {**OFFER_RESOURCE, "resource_id": resource_id}
        listing = seller.create_listing(
            listing_resource=resource, capacity_source=lane.capacity_source_for(resource),
            accepted_escrows=ACCEPTED_ESCROWS, max_duration_seconds=3600,
            settlements=[{"mechanism": "arkhai.payments.v1", "asset": "USD/6", "rate": "1.00", "per": "hour",
                "mechanism_input": {"payee_account": str(payment_setting("SELLER_ACCOUNT")),
                    "asset": "USD/6", "window": "P7D", "delivery_deadline_seconds": 300,
                    "dispute_window_seconds": 1296000}}],
        )
        row = registry.get_listing(listing.listing_id)
        options = row.settlement_options
        hosted = [option for option in options if option["settlement"]["schema"] == "arkhai.payments.v1"]
        assert hosted, options
        for option in hosted:
            terms = option["lifecycle"]["adjudication"]
            assert terms["dispute"] == description["dispute"], terms
            assert terms["dispute_window_seconds"] >= description["minimum_dispute_window_seconds"]
            assert terms["case_hold_max_seconds"] is None
            assert option["lifecycle"]["delivery_deadline_seconds"] == 300
        print("VM_READY: signed registry publication has dispute-bearing hosted terms; payments and mediation healthy")
