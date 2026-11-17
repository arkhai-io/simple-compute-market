"""VM's own stages of a rate servicing row, which each row module subclasses.

The listing stage and the capacity-event step are the VM recurring purchase's
(``test_vm_recurring_purchase.py``), over the row's own resource and settlement,
which its driver states.
"""

from __future__ import annotations

import logging

from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.rate_servicing_stages import RateServicingState
from tests.e2e.roles.scenarios.vms.conftest import (
    capacity_source_for,
    step_listing_reconciliation,
)
from tests.e2e.roles.scenarios.vms.purchase_driver import VmRecurringPurchaseDriver

log = logging.getLogger(__name__)


class VmRateListingCreated:
    def test_03_the_rows_listing_is_created_and_published(
        self, storefront_seller_client, storefront_admin_client, registry_client,
        deal_driver: VmRecurringPurchaseDriver, deal_state: RateServicingState,
    ):
        """The seller lists the row's resource with its one recurring payments
        settlement; creating it open publishes it to the registry, which the
        lane's servicing declaration lets publication do."""
        require_state(deal_state, "_registry_reachable", "_supply_seeded")
        resource = deal_driver.listing_resource()
        listing_id = storefront_seller_client.create_listing(
            listing_resource=resource,
            capacity_source=capacity_source_for(resource),
            max_duration_seconds=DURATION_HOURS * 3600,
            settlements=[deal_driver.listing_settlement()],
        ).listing_id
        assert listing_id, "listing creation returned no listing id"
        listing = storefront_admin_client.get_listing(listing_id)
        assert listing.status == "open" and listing.paused is False, listing
        published = registry_client.get_listing(listing_id)
        assert str(published.id) == listing_id, published
        deal_state.seller_listing_id = listing_id
        deal_state.listing_published = True
        log.info("[03] Rate listing %s created for resource %s and published",
                 listing_id, deal_driver.reserved_resource_id)


class VmRateCapacityEventCycle:
    def test_09a2_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: RateServicingState,
    ):
        """Step the held capacity-event loop, which closes the listing the
        row's reservation leaves unsatisfiable (``step_listing_reconciliation``)."""
        require_state(deal_state, "seller_listing_id", "provisioning_result_injected")
        pending, applied = step_listing_reconciliation(storefront_admin_client)
        deal_state._listing_reconciled = True
        log.info("[09a2] Capacity events for listing %s stepped: %s pending, %s applied",
                 deal_state.seller_listing_id, pending, applied)
