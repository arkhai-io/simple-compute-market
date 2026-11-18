"""Bare metal's own stage of a delivered rate deal's module, which each rate
servicing row and the watchdog cases' module subclass.

The publication stage is the bare-metal recurring purchase's
(``test_bare_metal_recurring_purchase.py``), over the module's own machine and
the pool override stating its one recurring option, which its driver seeds.
"""

from __future__ import annotations

import logging

from tests.e2e.roles.helpers.compute_deal import advance_storefront, dry_run_storefront
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.recurring_purchase_stages import RecurringPurchaseState
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import WHOLE_HOST_CAPACITY
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import BareMetalRecurringPurchaseDriver

PUBLICATION = "publication"

log = logging.getLogger(__name__)


class BareMetalRateListingPublished:
    def test_03_one_publication_pass_publishes_the_rows_listing(
        self, storefront_admin_client, deal_driver: BareMetalRecurringPurchaseDriver,
        deal_state: RecurringPurchaseState,
    ):
        """The dry run would publish the module's machine, and one pass publishes
        it, which the lane's servicing declaration lets publication do for its
        recurring option."""
        require_state(deal_state, "_supply_seeded")
        resource_id = deal_driver.reserved_resource_id
        preview = dry_run_storefront(storefront_admin_client, PUBLICATION)
        assert any(
            item.get("action") == "publish"
            and item.get("source", {}).get("physical_resource_id") == resource_id
            for item in preview["actions"]
        ), preview
        report = advance_storefront(storefront_admin_client, PUBLICATION)
        listings = [
            str(item["listing_id"]) for item in report["actions"]
            if item["action"] == "publish"
            and item["source"]["physical_resource_id"] == resource_id
        ]
        assert len(listings) == 1, report
        assert deal_driver.available_units() == WHOLE_HOST_CAPACITY["units"]
        deal_state.seller_listing_id = listings[0]
        deal_state.listing_published = True
        log.info("[03] Rate listing %s published for machine %s", listings[0], resource_id)
