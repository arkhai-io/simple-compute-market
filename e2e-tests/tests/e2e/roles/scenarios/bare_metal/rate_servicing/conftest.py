"""Fixtures every bare-metal rate servicing row takes; each module names its own row.

A row module supplies ``rate_row``: the seller's notice its option states, and
whether it pays from the lane's second payer. Each row's driver seeds a pool and
machine of its own. The purchase, its driver and its cleanup are the bare-metal
recurring purchase's (``test_bare_metal_recurring_purchase.py``) over that row.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

import pytest
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Ed25519Signer
from market_pool_overrides import SyncPoolOverrideClient

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.helpers.rate_servicing_stages import RateServicingState
from tests.e2e.roles.helpers.recurring_purchase_stages import recurring_purchase_cleanup
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    BareMetalRecurringPurchaseDriver,
    bare_metal_purchase_cli,
    purchase_fulfillment_transport,
    purchase_registry_client,
)


@dataclass(frozen=True)
class RateRow:
    """What one bare-metal rate servicing row's option states and pays from."""

    #: The seller's notice the row's option states: a spot option's; none for
    #: on-demand.
    payee_notice_seconds: int | None = None
    #: The row pays from the lane's second payer, which it funds itself.
    rate_payer: bool = False


@dataclass
class BareMetalRateServicingState(RateServicingState):
    """A bare-metal rate servicing row's state, under bare metal's domain identity."""

    domain_identity: str = "bare_metal.v1"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    lane_setting("registry_url")
    lane_setting("storefront_url")
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the pool override"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory,
                 rate_row: RateRow) -> BuyerCli:
    payer = str(payment_setting("RATE_PAYER_ACCOUNT")) if rate_row.rate_payer else None
    return bare_metal_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("bare_metal_rate_buyer"),
        payer=payer,
    )


@pytest.fixture(scope="module")
def deal_state() -> BareMetalRateServicingState:
    return BareMetalRateServicingState()


@pytest.fixture(scope="module")
def purchase_fulfillment(purchase_cli) -> BareMetalFulfillmentTransport:
    """The purchase profile's own fulfillment transport."""
    return purchase_fulfillment_transport(purchase_cli)


@pytest.fixture(scope="module")
def purchase_registry(purchase_cli):
    """The registry, signed as the purchase profile rather than the lane buyer."""
    client = purchase_registry_client(purchase_cli)
    yield client
    client.close()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, purchase_cli, purchase_fulfillment, purchase_registry,
    bare_metal_site_operator, bare_metal_site_capacity, provisioning_client,
    provisioning_test_client, storefront_admin_client, site_capacity, rate_row: RateRow,
) -> BareMetalRecurringPurchaseDriver:
    # Only the public SSH key leaves this fixture's memory.
    public = Ed25519Signer(os.urandom(32)).identity.identifier
    public_bytes = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    ssh_blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + public_bytes
    return BareMetalRecurringPurchaseDriver(
        site_operator=bare_metal_site_operator,
        site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_admin_client=storefront_admin_client,
        fulfillment=purchase_fulfillment,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": "ssh-ed25519 " + base64.b64encode(ssh_blob).decode("ascii")},
        site_id=lane_setting("site_id"),
        purchase_registry=purchase_registry,
        pool_overrides=SyncPoolOverrideClient(storefront_admin_client),
        storefront_pins=_pinned("storefront"),
        config_path=str(purchase_cli.config_path),
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
        payee_notice_seconds=rate_row.payee_notice_seconds,
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: BareMetalRecurringPurchaseDriver,
                     deal_state: BareMetalRateServicingState, provisioning_test_client):
    """Whatever the stages left: a held job, a purchase command still running,
    an approved deal no ending began to end, ended by the buyer's own stop, the
    gates' rules, a provisioning job still running, and the pool override.

    The gates are opened first, since a removed rule leaves a job it holds
    waiting.
    """
    yield
    rules = provisioning_test_client.bare_metal_rules
    run_cleanup([
        ("open the row's mock gates", deal_driver.open_gates),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        ("remove the access-grant mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the access-reclaim mock rule",
         lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
        ("drain provisioning", lambda: provisioning_test_client.drain(timeout=30)),
        ("remove the pool override", deal_driver.remove_pool_override),
    ])
