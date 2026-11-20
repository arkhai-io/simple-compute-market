"""Fixtures of the bare-metal buyer watchdog's delivered-deal cases.

The purchase and its cleanup are the bare-metal recurring purchase's
(``test_bare_metal_recurring_purchase.py``), its driver seeding a pool and
machine of its own, with the buyer run in the harness's process
(``helpers/in_process_buyer.py``), its ``buy`` opting into the watchdog.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from arkhai_bare_metal_buyer import cli as bare_metal_cli
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Ed25519Signer
from market_pool_overrides import SyncPoolOverrideClient

from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.in_process_buyer import InProcessBuyer, in_process_buyer
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.helpers.rate_watchdog_stages import RateWatchdogState, require_watchdog_lane
from tests.e2e.roles.helpers.recurring_purchase_stages import recurring_purchase_cleanup
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    BareMetalRateWatchdogDriver,
    bare_metal_purchase_cli,
    purchase_fulfillment_transport,
    purchase_registry_client,
)


@dataclass
class BareMetalRateWatchdogState(RateWatchdogState):
    """The bare-metal watchdog cases' state, under bare metal's domain identity."""

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
                 lane_time) -> Iterator[InProcessBuyer]:
    """The purchase profile's buyer, run in the harness's process for the module."""
    require_watchdog_lane(lane_time)
    cli = bare_metal_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("bare_metal_rate_watchdog_buyer"),
        lane_time_file=False,
    )
    with in_process_buyer(cli, command_module=bare_metal_cli) as buyer:
        yield buyer


@pytest.fixture(scope="module")
def deal_state() -> BareMetalRateWatchdogState:
    return BareMetalRateWatchdogState()


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
    provisioning_test_client, storefront_admin_client, site_capacity,
) -> BareMetalRateWatchdogDriver:
    # Only the public SSH key leaves this fixture's memory.
    public = Ed25519Signer(os.urandom(32)).identity.identifier
    public_bytes = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    ssh_blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + public_bytes
    return BareMetalRateWatchdogDriver(
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
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: BareMetalRateWatchdogDriver,
                     deal_state: BareMetalRateWatchdogState, provisioning_test_client):
    """Whatever the stages left: a held job, an in-process command still running
    at the harness's gate, an approved deal the watchdog did not stop, ended by
    the buyer's own stop, the gates' rules, a provisioning job still running,
    and the pool override.

    The gates are opened first, since a removed rule leaves a job it holds
    waiting.
    """
    yield
    rules = provisioning_test_client.bare_metal_rules
    run_cleanup([
        ("open the purchase's mock gates", deal_driver.open_gates),
        ("end the in-process command still running", purchase_cli.stop),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        ("remove the access-grant mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the access-reclaim mock rule",
         lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
        ("drain provisioning", lambda: provisioning_test_client.drain(timeout=30)),
        ("remove the pool override", deal_driver.remove_pool_override),
    ])
