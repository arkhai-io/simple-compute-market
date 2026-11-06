"""Bare metal's part of a buyer purchase: what the purchase stages ask of it.

The stages in ``helpers/buyer_purchase_stages.py`` hold the purchase's control
flow and every assertion that is not bare metal's. This driver adds bare
metal's to the canonical deal's (``BareMetalComputeDealDriver``): a storefront
pool override offering the lane's whole host in ``arkhai.payments.v1`` alone;
the listing as the buyer's purchase profile reads it and the option it states;
``market bare-metal buy`` and ``market bare-metal teardown`` with the buyer's
configuration; the deal's fulfillment as the seller reports it to the buyer; and
the lease view, which finds the purchase's hold by its negotiation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from market_core.schemas import SettlementOption, compute_rate_total
from market_identity import TrustedIdentitySet

from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import (
    BARE_METAL,
    MACHINE_ADDRESS,
    BareMetalComputeDealDriver,
    BareMetalDealLease,
)

#: The listed price of an hour of the whole host, in USD/6 base units.
HOURLY_GROSS = 1_000_000
#: Compute dispute coverage: the authority's minimum filing window plus the
#: delivery latency the seller allows for.
DISPUTE_WINDOW_SECONDS = 15 * 86400
DELIVERY_DEADLINE_SECONDS = 300
#: How long the buyer waits for its payment's receipt before giving up.
PAYMENT_TIMEOUT_SECONDS = 300


@dataclass(kw_only=True)
class BareMetalPurchaseDriver(BareMetalComputeDealDriver):
    """Bare metal's ``PurchaseDriver`` and ``MockGates``, for the lane's
    whole-host purchase through ``market bare-metal buy``."""

    #: The registry, signed as the buyer's purchase profile.
    purchase_registry: Any
    #: The storefront's pool overrides, as its administrator.
    pool_overrides: Any
    #: The storefront principal every listing and response is pinned to.
    storefront_pins: TrustedIdentitySet
    #: The purchase profile's buyer configuration file.
    config_path: str
    seller_account: str
    #: The payments option's dispute window, as the lane's seller states it.
    dispute_window: str

    buy_command = "market bare-metal buy (arkhai.payments.v1)"
    teardown_command = "market bare-metal teardown"
    buy_timeout_seconds = PAYMENT_TIMEOUT_SECONDS + 30.0

    @property
    def declared_host_id(self) -> str:
        # The one host this purchase registered enabled for its machine.
        return self.host_id

    def seed_supply(self) -> None:
        """The canonical deal's supply, offered in ``arkhai.payments.v1`` alone."""
        super().seed_supply()
        self.pool_overrides.put_pool_override({
            "site_id": self.site_id, "pool_id": self.pool_id,
            "offering_mode": BARE_METAL,
            "settlements": [{
                "mechanism": "arkhai.payments.v1", "asset": "USD/6",
                "rate": "1.00", "per": "hour",
                "mechanism_input": {
                    "payee_account": self.seller_account,
                    "asset": "USD/6", "window": self.dispute_window,
                    "dispute_window_seconds": DISPUTE_WINDOW_SECONDS,
                    "case_hold_max_seconds": None,
                    "delivery_deadline_seconds": DELIVERY_DEADLINE_SECONDS,
                },
            }],
        })

    def remove_pool_override(self) -> None:
        self.pool_overrides.delete_pool_override(self.site_id, self.pool_id, BARE_METAL)

    def open_gates(self) -> None:
        """Resume this deal's gates that still hold, so no job stays parked."""
        rules = self.provisioning_test_client.bare_metal_rules
        ours = {self.create_rule_id, self.teardown_rule_id}
        for rule in rules.list_rules():
            if rule.rule_id in ours and rule.paused:
                rules.resume_rule(rule.rule_id)

    def discover(self, listing_id: str) -> Any:
        return self.purchase_registry.get_listing(listing_id)

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        assert listing.listing_resource["capacity_backing"] == "backed", listing
        assert listing.publisher_principals == self.storefront_pins, listing
        # The pool override offers the payments option alone.
        assert len(listing.settlement_options) == 1, listing.settlement_options
        assert option.settlement_params["window"] == self.dispute_window, option
        adjudication = option.lifecycle["adjudication"]
        assert adjudication["dispute_window_seconds"] == DISPUTE_WINDOW_SECONDS, option
        assert adjudication["case_hold_max_seconds"] is None, option
        assert option.lifecycle["delivery_deadline_seconds"] == DELIVERY_DEADLINE_SECONDS
        assert option.price_asset == "USD/6", option
        assert option.price_rates[0].per == "hour", option
        assert compute_rate_total(option.price_rates[0], 3600) == HOURLY_GROSS, option

    def buy_arguments(self, listing_id: str, option_id: str) -> list[str]:
        return [
            "bare-metal", "buy", listing_id,
            "--option-id", option_id,
            "--ssh-public-key", self.buyer_config["ssh_public_key"],
            "--duration-seconds", str(DURATION_HOURS * 3600),
            "--payment-timeout-seconds", str(PAYMENT_TIMEOUT_SECONDS),
            "--config", self.config_path,
        ]

    def teardown_arguments(self, run_id: str) -> list[str]:
        return ["bare-metal", "teardown", "--run-id", run_id, "--config", self.config_path]

    def purchase_fulfillment(self, negotiation_id: str) -> dict[str, Any]:
        return self.fulfillment.status(negotiation_id)

    def lease_view(self, deal_state: Any) -> BareMetalDealLease:
        # A payments fulfillment's hold names the deal's negotiation.
        return BareMetalDealLease(
            self.provisioning_client,
            self.site_capacity,
            negotiation_id=deal_state.negotiation_id,
        )

    def assert_delivery(self, deal_state: Any) -> None:
        """The canonical deal's delivery, its receipt naming the purchase's
        fulfillment and host, and the whole machine held."""
        super().assert_delivery(deal_state)
        receipt = self.fulfillment.result(deal_state.negotiation_id)["receipt"]
        assert receipt["access_ref"]["fulfillment_id"] == deal_state.fulfillment_id, receipt
        assert receipt["host_id"] == self.host_id, receipt
        assert self.fulfillment.access(deal_state.negotiation_id)["host"] == MACHINE_ADDRESS
        assert self.available_units() == 0

    def available_units(self) -> int:
        """The whole machine's units the site reports available."""
        row = next(row for row in self.site_capacity.snapshot()
                   if row["resource_id"] == self.reserved_resource_id)
        return int(row["available"]["units"])
