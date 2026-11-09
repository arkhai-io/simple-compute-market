"""VM's part of a buyer purchase: what the purchase stages ask of it.

The stages in ``helpers/buyer_purchase_stages.py`` hold the purchase's control
flow and every assertion that is not VM's. ``VmPurchaseParts`` is what every VM
purchase adds to its canonical deal's driver, mock or real: ``market buy``,
which selects its listing by discovery and polls its settlement until delivery;
the option a payments listing states; the deal's fulfillment and delivery as
the seller reports them to the buyer, by its negotiation; and what the command
records as it ends. ``VmPurchaseDriver`` is the lane's, over
``VmComputeDealDriver``: its listing's resource and its one
``arkhai.payments.v1`` settlement. The lease view is the canonical deal's,
which finds a VM hold by its negotiation whatever the settlement mechanism.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from market_core.schemas import SettlementOption, compute_rate_total

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli, _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.compute_deal import wait_for_stage_event
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.payments import (
    buyer_payments_environment,
    dispute_window_seconds,
    payment_config_toml,
    payment_setting,
)
from tests.e2e.roles.scenarios.vms.compute_deal_driver import (
    E2E_DEAL_GPU_COUNT,
    VmComputeDealDriver,
)
from tests.e2e.roles.scenarios.vms.composed_listing import (
    delivery_deadline_seconds,
    payments_settlement,
)

#: The listed price of an hour of the purchase's VM, in USD/6 base units:
#: ``payments_settlement``'s rate of 1.00 USD an hour.
HOURLY_GROSS = 1_000_000
#: The minimum wait; a longer declared VM delivery allowance takes precedence.
SETTLEMENT_TIMEOUT_SECONDS = 300
#: How often it reads its settlement meanwhile.
SETTLEMENT_POLL_SECONDS = 1.0


def vm_purchase_cli(payments_config: Any, binary: Any, base: Path) -> BuyerCli:
    """The run's VM buyer (``BUYER``), profiled under ``base`` with no wallet,
    buying through Arkhai payments alone. Each profile keeps its own run
    logs, so a purchase's compensation finds that purchase alone."""
    registry_url = str(settings.REGISTRY.API_URL or "").rstrip("/")
    assert registry_url, "REGISTRY.API_URL is required for the purchase's discovery"
    scheme = str(settings.BUYER.get("marketplace_scheme", "eip191") or "eip191")
    credential = str(settings.BUYER.get("marketplace_credential", "") or "")
    assert credential, "BUYER.MARKETPLACE_CREDENTIAL is required for the purchase's buyer"
    sections = (
        "[vms]",
        f"payer_account = {_toml_quote(str(payment_setting('BUYER_ACCOUNT')))}",
        "",
        # Only the configured, enabled mechanism is selectable, so the buyer
        # can settle this purchase no other way.
        "[Settlement]",
        "schema_version = 1",
        'priority = ["arkhai.payments.v1"]',
        "",
        *payment_config_toml(payments_config),
    )
    return create_profiled_buyer_cli(
        binary=binary,
        base=base,
        domain_identity="vms.compute",
        marketplace_scheme=scheme,
        marketplace_credential=credential,
        registries=(registry_url,),
        registry_authorities={registry_url: {
            "authority": str(settings.REGISTRY.get("authority_id", "") or ""),
            "identities": [{
                "scheme": str(settings.REGISTRY.get("authority_scheme", "eip191") or "eip191"),
                "identifier": str(settings.REGISTRY.get("identifier", "") or ""),
            }],
        }},
        credential_environment=buyer_payments_environment(payments_config),
        toml_sections=sections,
    )


class VmPurchaseParts:
    """The ``PurchaseDriver`` parts every VM purchase supplies the same way.

    Mixed into a VM canonical deal's driver, whose ``storefront_client`` (the
    purchase's buyer) and ``storefront_admin_client`` it reads; the driver
    supplies ``purchase_registry``, ``dispute_window``, ``buyer_config`` and
    the discovery query its listing alone answers (``resource_query``).
    """

    buy_command = "market buy (arkhai.payments.v1)"
    teardown_command = "market end"
    buy_timeout_seconds = SETTLEMENT_TIMEOUT_SECONDS + 30.0
    # ``market buy`` goes on polling its settlement after the seller has
    # accepted its commit, which it records as submitting the settlement.
    committed_event = "settlement_submitted"

    def resource_query(self) -> str:
        """The typed discovery query only the purchase's listing answers."""
        raise NotImplementedError

    def discover(self, listing_id: str) -> Any:
        return self.purchase_registry.get_listing(listing_id)

    def check_payments_option(self, option: SettlementOption) -> None:
        """What a VM listing's payments option states: an hour in USD/6 at
        ``HOURLY_GROSS``, with the seller's dispute window and the run's
        dispute coverage, which the listing's settlement stated."""
        assert option.settlement_params["window"] == self.dispute_window, option
        deadline = delivery_deadline_seconds()
        adjudication = option.lifecycle["adjudication"]
        assert adjudication["dispute_window_seconds"] == dispute_window_seconds(
            delivery_deadline_seconds=deadline,
        ), option
        assert option.lifecycle["delivery_deadline_seconds"] == deadline
        assert option.price_asset == "USD/6", option
        assert option.price_rates[0].per == "hour", option
        assert compute_rate_total(option.price_rates[0], 3600) == HOURLY_GROSS, option

    def buy_arguments(self, listing_id: str, option_id: str) -> list[str]:
        # ``market buy`` takes no listing: it selects one by discovery, so the
        # query names what only this purchase's listing states, and
        # ``Purchase04`` checks that the Agreement names the listing and
        # option discovered. The hourly price is both the opening and the
        # ceiling, in the option's base units, so the buyer takes the listed
        # price.
        return [
            "buy",
            "--resource", self.resource_query(),
            "--settlement", "mechanism=arkhai.payments.v1",
            "--initial-price", str(HOURLY_GROSS),
            "--max-price", str(HOURLY_GROSS),
            "--duration-hours", str(DURATION_HOURS),
            "--max-matches", "1",
            "--poll-interval", str(SETTLEMENT_POLL_SECONDS),
            "--settlement-timeout", str(max(SETTLEMENT_TIMEOUT_SECONDS, delivery_deadline_seconds())),
            "--ssh-public-key", self.buyer_config["ssh_public_key"],
            "--yes",
        ]

    def teardown_arguments(self, run_id: str) -> list[str]:
        return ["end", "--from", run_id]

    def purchase_fulfillment(self, negotiation_id: str) -> dict[str, Any]:
        # The seller dispatches the fulfillment once it accepts the commit,
        # and records its job submitted once the dispatch is durable. The
        # purchase's buyer is the one this storefront client signs as.
        wait_for_stage_event(
            self.storefront_admin_client, "provision", "job_submitted",
            negotiation_id=negotiation_id, timeout=15.0,
        )
        # The typed client's settle status is a dataclass, not a pydantic model.
        return asdict(self.storefront_client.get_settle_status(negotiation_id))

    def check_run_ended(self, ended: dict[str, Any], deal_state: Any) -> None:
        """The run ended with its settlement ready, which it polled by the
        purchase's negotiation."""
        assert ended["status"] == "ready", ended
        assert ended["escrow_uid"] == deal_state.negotiation_id, ended


@dataclass(kw_only=True)
class VmPurchaseDriver(VmPurchaseParts, VmComputeDealDriver):
    """VM's ``PurchaseDriver`` and ``MockGates``, for the lane's purchase of
    one hour of a VM through ``market buy``."""

    #: The registry, read as the buyer discovers.
    purchase_registry: Any
    seller_account: str
    #: The payments option's dispute window, as the lane's seller states it.
    dispute_window: str

    @property
    def declared_host_id(self) -> str:
        # The one host this purchase registered enabled for its resource.
        return self.host

    def resource_query(self) -> str:
        # The GPU model only this purchase's resource declares.
        return f'gpu_model="{self.gpu_model}"'

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
        return payments_settlement(
            seller_account=self.seller_account, dispute_window=self.dispute_window,
        )

    def open_gates(self) -> None:
        """Resume this deal's gates that still hold, so no job stays parked."""
        rules = self.provisioning_test_client.vm_rules
        ours = {self.create_rule_id, self.teardown_rule_id}
        for rule in rules.list_rules():
            if rule.rule_id in ours and rule.paused:
                rules.resume_rule(rule.rule_id)

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        assert listing.listing_resource["gpu_model"] == self.gpu_model, listing
        # The listing states the payments settlement alone.
        assert len(listing.settlement_options) == 1, listing.settlement_options
        self.check_payments_option(option)

    def assert_delivery(self, deal_state: Any) -> None:
        """VM delivers through the settlement status the buyer reads, by the
        purchase's negotiation, naming the fulfillment its commit began."""
        status = self.storefront_client.get_settle_status(deal_state.negotiation_id)
        assert status.status == "ready", status
        assert status.tenant_credentials, f"tenant_credentials missing from settlement status: {status}"
        assert status.fulfillment_id == deal_state.fulfillment_id, status
