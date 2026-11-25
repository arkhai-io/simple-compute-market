"""Fixtures every VM rate-dispute row takes; each module names its own row.

A row module supplies ``rate_row``: the resource, executor, pool and GPU model
its deal is sold on, which no other scenario on the stack lists. The purchase,
its driver and its cleanup are the VM recurring purchase's
(``test_vm_recurring_purchase.py``) over that row, paid by the lane's buyer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.mediation import MediationTarget, configured_mediation
from tests.e2e.roles.helpers.payments import configured_payments, payment_setting
from tests.e2e.roles.helpers.recurring_purchase_stages import recurring_purchase_cleanup
from tests.e2e.roles.scenarios.vms.conftest import capacity_site_id
from tests.e2e.roles.scenarios.vms.purchase_driver import (
    VmRecurringPurchaseDriver,
    vm_purchase_cli,
)
from tests.e2e.roles.scenarios.vms.rate_dispute.stages import RateDisputeState
from tests.e2e.roles.scenarios.vms.rate_servicing.conftest import RateRow


@dataclass
class VmRateDisputeState(RateDisputeState):
    """A VM rate-dispute row's state, under VM's domain identity."""

    domain_identity: str = "vms.compute"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    config = configured_payments()
    assert config.livemode is False
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def mediation_target() -> MediationTarget:
    """The lane's mediation target: a blocked skip when none is configured, a
    failure when the lane's own is not ready."""
    return configured_mediation()


@pytest.fixture(scope="module")
def buyer_evidence(tmp_path_factory) -> Path:
    """The directory of the buyer's evidence store, which the harness's filing
    keeps its operation keys in, as the buyer's lifecycle does."""
    return tmp_path_factory.mktemp("rate_dispute_buyer_evidence")


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    """The lane's buyer, profiled with no wallet and no waivers, buying through
    Arkhai payments alone."""
    return vm_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("vm_rate_dispute_buyer"),
    )


@pytest.fixture(scope="module")
def deal_state() -> VmRateDisputeState:
    return VmRateDisputeState()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, provisioning_client, provisioning_test_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client,
    site_capacity, registry_client, rate_row: RateRow,
) -> VmRecurringPurchaseDriver:
    """VM's part of the row's purchase, over the row's own resource, host, pool
    and GPU model. The buyer has no wallet, so of the lane buyer's
    configuration it takes only the SSH public key its provision terms carry."""
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return VmRecurringPurchaseDriver(
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client,
        site_capacity=site_capacity,
        buyer_config={"ssh_public_key": ssh_public_key},
        site_id=capacity_site_id(),
        reserved_resource_id=rate_row.resource_id,
        host=rate_row.host,
        pool_id=rate_row.pool_id,
        gpu_model=rate_row.gpu_model,
        purchase_registry=registry_client,
        seller_account=str(payment_setting("SELLER_ACCOUNT")),
        dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: VmRecurringPurchaseDriver,
                     deal_state: VmRateDisputeState, provisioning_test_client):
    """Resume a job the row's gates still hold, stop a ``market buy`` still
    running, end an approved deal no ruling began to end, by the buyer's own
    stop, then remove the gates' rules; the lane's cleanup releases the
    module's holds and its reserved resources, and ``lane_double_rules`` the
    rules the row installed on the doubles.

    The gates are opened before their rules are removed, since a removed rule
    leaves a job it holds waiting.
    """
    yield
    rules = provisioning_test_client.vm_rules
    run_cleanup([
        ("open the row's mock gates", deal_driver.open_gates),
        *recurring_purchase_cleanup(purchase_cli, deal_driver, deal_state),
        ("remove the create mock rule", lambda: rules.delete_rule(deal_driver.create_rule_id)),
        ("remove the teardown mock rule", lambda: rules.delete_rule(deal_driver.teardown_rule_id)),
    ])
