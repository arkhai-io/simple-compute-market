"""Fixtures of the VM buyer watchdog's delivered-deal cases.

The purchase and its cleanup are the VM recurring purchase's
(``test_vm_recurring_purchase.py``) over the module's own resource, host, pool
and GPU model, with the lane's buyer run in the harness's process
(``helpers/in_process_buyer.py``), its ``buy`` opting into the watchdog.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from arkhai_vms_buyer import buy_cli
from market_arkhai_payments import ArkhaiPaymentsConfig

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.in_process_buyer import InProcessBuyer, in_process_buyer
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.helpers.rate_watchdog_stages import RateWatchdogState, require_watchdog_lane
from tests.e2e.roles.helpers.recurring_purchase_stages import recurring_purchase_cleanup
from tests.e2e.roles.scenarios.vms.conftest import capacity_site_id
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_RATE_WATCHDOG_GPU_MODEL,
    E2E_RATE_WATCHDOG_HOST,
    E2E_RATE_WATCHDOG_POOL_ID,
    E2E_RATE_WATCHDOG_RESOURCE_ID,
)
from tests.e2e.roles.scenarios.vms.purchase_driver import VmRateWatchdogDriver, vm_purchase_cli


@dataclass
class VmRateWatchdogState(RateWatchdogState):
    """The VM watchdog cases' state, under VM's domain identity."""

    domain_identity: str = "vms.compute"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory,
                 lane_time) -> Iterator[InProcessBuyer]:
    """The lane's buyer, profiled with no wallet and no waivers, buying through
    Arkhai payments alone, run in the harness's process for the module."""
    require_watchdog_lane(lane_time)
    cli = vm_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("vm_rate_watchdog_buyer"),
        lane_time_file=False,
    )
    with in_process_buyer(cli, command_module=buy_cli) as buyer:
        yield buyer


@pytest.fixture(scope="module")
def deal_state() -> VmRateWatchdogState:
    return VmRateWatchdogState()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, provisioning_client, provisioning_test_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client,
    site_capacity, registry_client,
) -> VmRateWatchdogDriver:
    """VM's part of the purchase, over the module's own resource, host, pool and
    GPU model. The buyer has no wallet, so of the lane buyer's configuration it
    takes only the SSH public key its provision terms carry."""
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return VmRateWatchdogDriver(
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": ssh_public_key},
        site_id=capacity_site_id(),
        reserved_resource_id=E2E_RATE_WATCHDOG_RESOURCE_ID,
        host=E2E_RATE_WATCHDOG_HOST,
        pool_id=E2E_RATE_WATCHDOG_POOL_ID,
        gpu_model=E2E_RATE_WATCHDOG_GPU_MODEL,
        purchase_registry=registry_client,
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: VmRateWatchdogDriver,
                     deal_state: VmRateWatchdogState, provisioning_test_client):
    """Resume a job the purchase's gates still hold, end an in-process command
    still running at the harness's gate, end an approved deal the watchdog did
    not stop, by the buyer's own stop, then remove the gates' rules; the lane's
    cleanup releases the module's holds and its reserved resources.

    The gates are opened before their rules are removed, since a removed rule
    leaves a job it holds waiting.
    """
    yield
    rules = provisioning_test_client.vm_rules
    run_cleanup([
        ("open the purchase's mock gates", deal_driver.open_gates),
        ("end the in-process command still running", purchase_cli.stop),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        ("remove the create mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the teardown mock rule", lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
    ])
