"""Bare metal's part of a buyer purchase: what the purchase stages ask of it.

The stages in ``helpers/buyer_purchase_stages.py`` hold the purchase's control
flow and every assertion that is not bare metal's. ``BareMetalPurchaseParts``
is what every bare-metal purchase adds to its canonical deal's driver, mock or
real: the listing as the buyer's purchase profile reads it and the payments
option it states; ``market bare-metal buy`` and ``market bare-metal teardown``
with the buyer's configuration; the deal's fulfillment as the seller reports it
to the buyer; and the lease view, which finds the purchase's hold by its
negotiation. ``BareMetalPurchaseDriver`` is the lane's, over
``BareMetalComputeDealDriver``: a storefront pool override offering the lane's
whole host in ``arkhai.payments.v1`` alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from core_buyer.profile_service import BuyerProfileService
from core_buyer.run_log import read_run_identity
from market_core.schemas import SettlementOption, compute_rate_total
from market_identity import IdentityScheme, ProfileRepository, TrustedIdentitySet, create_signer
from registry_client import SyncRegistryClient
from storefront_client import SyncStorefrontClient

from tests.e2e.roles.buyer_cli import BuyerCli, _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.payments import (
    buyer_payments_environment,
    dispute_window_seconds,
    payment_config_toml,
    payment_setting,
)
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import (
    BARE_METAL,
    MACHINE_ADDRESS,
    BareMetalComputeDealDriver,
    BareMetalDealLease,
)

#: The listed price of an hour of the whole host, in USD/6 base units.
HOURLY_GROSS = 1_000_000
#: The delivery latency the seller allows for, which the dispute coverage
#: (``dispute_window_seconds``) covers.
DELIVERY_DEADLINE_SECONDS = 300
#: How long the buyer waits for its payment's receipt before giving up.
PAYMENT_TIMEOUT_SECONDS = 300


def bare_metal_purchase_cli(payments_config: Any, binary: Any, base: Path) -> BuyerCli:
    """A profiled Ed25519 buyer with no wallet (``PAYMENTS``'s buyer), under
    ``base``, buying through Arkhai payments. Each profile keeps its own run
    logs, so a purchase's compensation finds that purchase alone."""
    url = lane_setting("registry_url")
    scheme = lane_setting("registry_scheme")
    identifier = lane_setting("registry_identifier")
    authority = lane_setting("registry_authority_id")
    sections = (
        "[bare_metal]",
        f"registry_url = {_toml_quote(url)}",
        f"registry_authority = {_toml_quote(authority)}",
        "registry_principals = [{ scheme = " + _toml_quote(scheme)
        + ", identifier = " + _toml_quote(identifier) + " }]",
        f"payer_account = {_toml_quote(str(payment_setting('BUYER_ACCOUNT')))}",
        "",
        *payment_config_toml(payments_config, table="bare_metal.arkhai_payments"),
    )
    return create_profiled_buyer_cli(
        binary=binary,
        base=base,
        domain_identity="bare_metal.v1",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential=str(payment_setting("BUYER_MARKETPLACE_CREDENTIAL")),
        registries=(url,),
        registry_authorities={url: {"authority": authority,
                                   "identities": [{"scheme": scheme, "identifier": identifier}]}},
        credential_environment=buyer_payments_environment(payments_config),
        toml_sections=sections,
    )


def purchase_signer(cli: BuyerCli, run_id: str | None = None) -> Any:
    """The purchase profile's signer, or, for ``run_id``, the one its run
    recorded."""
    service = BuyerProfileService(
        repository=ProfileRepository(cli.data_dir / "arkhai/buyer/profiles.json"),
        environ=cli.credential_env,
        run_logs_directory=cli.run_dir,
    )
    if run_id is None:
        return service.resolve_fresh_signer()[1]
    recorded = read_run_identity(run_id, directory=cli.run_dir)
    return service.resolve_recovery_signer(
        profile_id=recorded.profile_id, principal=recorded.principal,
    )[1]


def purchase_fulfillment_transport(cli: BuyerCli) -> BareMetalFulfillmentTransport:
    """The purchase profile's own fulfillment transport."""
    signer = purchase_signer(cli)
    return BareMetalFulfillmentTransport(
        seller_url=lane_setting("storefront_url"),
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: _pinned("storefront"),
    )


def purchase_registry_client(cli: BuyerCli) -> SyncRegistryClient:
    """The registry, signed as the purchase profile rather than the lane buyer."""
    return SyncRegistryClient(
        lane_setting("registry_url"), signer=purchase_signer(cli), caller_role="buyer",
        expected_registries=_pinned("registry"),
        registry_authority=lane_setting("registry_authority_id"),
    )


def seller_refund(negotiation_id: str) -> Any:
    """Refund the purchase as the storefront's pinned seller; a repeat returns
    the same result."""
    seller = create_signer(
        lane_setting("storefront_scheme"), str(payment_setting("SELLER_MARKETPLACE_CREDENTIAL")),
    )
    assert seller.identity in _pinned("storefront").identities
    with SyncStorefrontClient(
        lane_setting("storefront_url"), signer=seller, caller_role="seller",
        expected_publishers=_pinned("storefront"),
    ) as storefront:
        return storefront.refund_settlement(negotiation_id)


class BareMetalPurchaseParts:
    """The ``PurchaseDriver`` parts every bare-metal purchase supplies the same way.

    Mixed into a bare-metal canonical deal's driver, whose ``fulfillment`` is
    the purchase profile's transport; the driver supplies
    ``purchase_registry``, ``storefront_pins``, ``config_path`` and
    ``buyer_config``.
    """

    buy_command = "market bare-metal buy (arkhai.payments.v1)"
    teardown_command = "market bare-metal teardown"
    buy_timeout_seconds = PAYMENT_TIMEOUT_SECONDS + 30.0
    # After its approval, ``market bare-metal buy`` records its end only once
    # the seller has accepted its commit; a failed commit ends it unrecorded.
    committed_event = "run_ended"

    def discover(self, listing_id: str) -> Any:
        return self.purchase_registry.get_listing(listing_id)

    def check_payments_listing(self, listing: Any, option: SettlementOption) -> None:
        """What any backed whole-host listing and its payments option state: a
        backed machine the pinned storefront publishes, priced by the hour in
        USD/6. The terms themselves are the seller's."""
        assert listing.listing_resource["capacity_backing"] == "backed", listing
        assert listing.publisher_principals == self.storefront_pins, listing
        assert option.price_asset == "USD/6", option
        assert option.price_rates[0].per == "hour", option

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
        # The command ended after the seller accepted its commit, which
        # dispatches the fulfillment.
        return self.fulfillment.status(negotiation_id)

    def check_run_ended(self, ended: dict[str, Any], deal_state: Any) -> None:
        """The run ended agreed, naming the transaction and the fulfillment its
        commit began."""
        assert ended["status"] == "agreed", ended
        assert ended["transaction_id"] == deal_state.settlement_id, ended
        assert ended["fulfillment"]["settlement_ref"] == deal_state.settlement_id, ended
        assert ended["fulfillment"]["negotiation_id"] == deal_state.negotiation_id, ended

    def lease_view(self, deal_state: Any) -> BareMetalDealLease:
        # A payments fulfillment's hold names the deal's negotiation.
        return BareMetalDealLease(
            self.provisioning_client,
            self.site_capacity,
            negotiation_id=deal_state.negotiation_id,
        )


@dataclass(kw_only=True)
class BareMetalPurchaseDriver(BareMetalPurchaseParts, BareMetalComputeDealDriver):
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
                    "dispute_window_seconds": dispute_window_seconds(
                        delivery_deadline_seconds=DELIVERY_DEADLINE_SECONDS,
                    ),
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

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        """The listing and option, with the terms the lane's pool override
        states: an hour at ``HOURLY_GROSS``, with the seller's dispute window
        and the run's dispute coverage."""
        # The pool override offers the payments option alone.
        assert len(listing.settlement_options) == 1, listing.settlement_options
        self.check_payments_listing(listing, option)
        assert option.settlement_params["window"] == self.dispute_window, option
        adjudication = option.lifecycle["adjudication"]
        assert adjudication["dispute_window_seconds"] == dispute_window_seconds(
            delivery_deadline_seconds=DELIVERY_DEADLINE_SECONDS,
        ), option
        assert adjudication["case_hold_max_seconds"] is None, option
        assert option.lifecycle["delivery_deadline_seconds"] == DELIVERY_DEADLINE_SECONDS
        assert compute_rate_total(option.price_rates[0], 3600) == HOURLY_GROSS, option

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
