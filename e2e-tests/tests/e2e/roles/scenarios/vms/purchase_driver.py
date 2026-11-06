"""VM's part of a buyer purchase: what the purchase stages ask of it.

The stages in ``helpers/buyer_purchase_stages.py`` hold the purchase's control
flow and every assertion that is not VM's. This driver adds VM's to the
canonical deal's (``VmComputeDealDriver``): the listing's resource and its one
``arkhai.payments.v1`` settlement, and the option the listing states;
``market buy``, which selects its listing by discovery and polls its settlement
until delivery; the deal's fulfillment and delivery as the seller reports them
to the buyer, by its negotiation; and what the command records as it ends. The
lease view is the canonical deal's, which finds a VM hold by its negotiation
whatever the settlement mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from market_core.schemas import SettlementOption, compute_rate_total

from tests.e2e.roles.helpers.compute_deal import wait_for_stage_event
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.scenarios.vms.compute_deal_driver import (
    E2E_DEAL_GPU_COUNT,
    VmComputeDealDriver,
)

#: The listed price of an hour of the purchase's VM, in USD/6 base units.
HOURLY_GROSS = 1_000_000
#: Compute dispute coverage: the authority's minimum filing window plus the
#: delivery latency the seller allows for.
DISPUTE_WINDOW_SECONDS = 15 * 86400
DELIVERY_DEADLINE_SECONDS = 300
#: How long ``market buy`` waits for delivery, from its approval.
SETTLEMENT_TIMEOUT_SECONDS = 300
#: How often it reads its settlement meanwhile.
SETTLEMENT_POLL_SECONDS = 1.0


@dataclass(kw_only=True)
class VmPurchaseDriver(VmComputeDealDriver):
    """VM's ``PurchaseDriver`` and ``MockGates``, for the lane's purchase of
    one hour of a VM through ``market buy``."""

    #: The registry, read as the buyer discovers.
    purchase_registry: Any
    seller_account: str
    #: The payments option's dispute window, as the lane's seller states it.
    dispute_window: str

    buy_command = "market buy (arkhai.payments.v1)"
    teardown_command = "market end"
    buy_timeout_seconds = SETTLEMENT_TIMEOUT_SECONDS + 30.0
    # ``market buy`` goes on polling its settlement after the seller has
    # accepted its commit, which it records as submitting the settlement.
    committed_event = "settlement_submitted"

    @property
    def declared_host_id(self) -> str:
        # The one host this purchase registered enabled for its resource.
        return self.host

    def listing_resource(self) -> dict[str, Any]:
        """The resource the purchase's listing sells: what ``seed_supply``
        declares at the site, which the seller's inventory guard compares by
        equality."""
        return {
            "offering_mode": "vm",
            "resource_id": self.reserved_resource_id,
            "gpu_model": self.gpu_model,
            "gpu_count": E2E_DEAL_GPU_COUNT,
            "sla": 90.0,
            "region": "California, US",
        }

    def listing_settlement(self) -> dict[str, Any]:
        """The listing's one settlement: an hour of the VM in USD/6, paid
        through Arkhai payments to the lane's seller account."""
        return {
            "mechanism": "arkhai.payments.v1", "asset": "USD/6", "rate": "1.00", "per": "hour",
            "mechanism_input": {
                "payee_account": self.seller_account, "asset": "USD/6",
                "window": self.dispute_window,
                "delivery_deadline_seconds": DELIVERY_DEADLINE_SECONDS,
                "dispute_window_seconds": DISPUTE_WINDOW_SECONDS,
            },
        }

    def open_gates(self) -> None:
        """Resume this deal's gates that still hold, so no job stays parked."""
        rules = self.provisioning_test_client.vm_rules
        ours = {self.create_rule_id, self.teardown_rule_id}
        for rule in rules.list_rules():
            if rule.rule_id in ours and rule.paused:
                rules.resume_rule(rule.rule_id)

    def discover(self, listing_id: str) -> Any:
        return self.purchase_registry.get_listing(listing_id)

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        assert listing.listing_resource["gpu_model"] == self.gpu_model, listing
        # The listing states the payments settlement alone.
        assert len(listing.settlement_options) == 1, listing.settlement_options
        assert option.settlement_params["window"] == self.dispute_window, option
        adjudication = option.lifecycle["adjudication"]
        assert adjudication["dispute_window_seconds"] == DISPUTE_WINDOW_SECONDS, option
        assert option.lifecycle["delivery_deadline_seconds"] == DELIVERY_DEADLINE_SECONDS
        assert option.price_asset == "USD/6", option
        assert option.price_rates[0].per == "hour", option
        assert compute_rate_total(option.price_rates[0], 3600) == HOURLY_GROSS, option

    def buy_arguments(self, listing_id: str, option_id: str) -> list[str]:
        # ``market buy`` takes no listing: it selects one by discovery, so the
        # query names the GPU model only this purchase's resource declares,
        # and ``Purchase04`` checks that the Agreement names the listing and
        # option discovered. The hourly price is both the opening and the
        # ceiling, in the option's base units, so the buyer takes the listed
        # price.
        return [
            "buy",
            "--resource", f'gpu_model="{self.gpu_model}"',
            "--settlement", "mechanism=arkhai.payments.v1",
            "--initial-price", str(HOURLY_GROSS),
            "--max-price", str(HOURLY_GROSS),
            "--duration-hours", str(DURATION_HOURS),
            "--max-matches", "1",
            "--poll-interval", str(SETTLEMENT_POLL_SECONDS),
            "--settlement-timeout", str(SETTLEMENT_TIMEOUT_SECONDS),
            "--ssh-public-key", self.buyer_config["ssh_public_key"],
            "--yes",
        ]

    def teardown_arguments(self, run_id: str) -> list[str]:
        return ["end", "--from", run_id]

    def purchase_fulfillment(self, negotiation_id: str) -> dict[str, Any]:
        # The seller dispatches the fulfillment once it accepts the commit,
        # and records its job submitted once the dispatch is durable. The
        # purchase's buyer is the lane's buyer, whom this client signs as.
        wait_for_stage_event(
            self.storefront_admin_client, "provision", "job_submitted",
            negotiation_id=negotiation_id, timeout=15.0,
        )
        return self.storefront_client.get_settle_status(negotiation_id).model_dump(mode="json")

    def assert_delivery(self, deal_state: Any) -> None:
        """VM delivers through the settlement status the buyer reads, by the
        purchase's negotiation, naming the fulfillment its commit began."""
        status = self.storefront_client.get_settle_status(deal_state.negotiation_id)
        assert status.status == "ready", status
        assert status.tenant_credentials, f"tenant_credentials missing from settlement status: {status}"
        assert status.fulfillment_id == deal_state.fulfillment_id, status

    def check_run_ended(self, ended: dict[str, Any], deal_state: Any) -> None:
        """The run ended with its settlement ready, which it polled by the
        purchase's negotiation."""
        assert ended["status"] == "ready", ended
        assert ended["escrow_uid"] == deal_state.negotiation_id, ended
