"""Fixtures every VM live verification module takes; each module names its own row.

A module supplies ``rate_row``, the rate servicing rows' ``RateRow``: the
resource, executor, pool and GPU model its deal is sold on, which no other
scenario on the stack lists, whether its option is spot, and whether it pays
from the rate payer. The run's ``LIVE`` settings give the option's period, the
spot seller's notice and the Agreement's term
(``helpers/live_verification.py``). The purchase and its cleanup are the VM
recurring purchase's, against the run's external payments target, which a
lane's own double never is (``payments.live_payments``).

A module takes its prerequisites first among its fixtures — ``payments_config``,
``live_provenance``, ``mock_provisioning``, and the payer its deal pays from,
``funded_buyer`` or, for funds running out, ``funded_rate_payer`` — so a
topology that does not meet a requirement is a blocked skip naming it, and a
run missing a setting it owes fails naming the setting, before the module's
holds and anything it buys. Only the session's fixtures (lane time, the buyer
binary) and the VM lane's autouse, idempotent host registration set up before
them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers import live_verification
from tests.e2e.roles.helpers.live_verification import LiveSettings, Provenance
from tests.e2e.roles.helpers.payments import live_payments, payment_setting
from tests.e2e.roles.helpers.rate_servicing_stages import FUNDED_PERIODS
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    ASSET,
    payer_available,
    recurring_purchase_cleanup,
)
from tests.e2e.roles.scenarios.vms.conftest import capacity_site_id
from tests.e2e.roles.scenarios.vms.live.stages import LiveRateState
from tests.e2e.roles.scenarios.vms.purchase_driver import VmLiveRatePurchaseDriver, vm_purchase_cli
from tests.e2e.roles.scenarios.vms.rate_servicing.conftest import RateRow


@dataclass
class VmLiveRateState(LiveRateState):
    """A VM live module's state, under VM's domain identity."""

    domain_identity: str = "vms.compute"


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    """The run's external payments target in test mode, or a blocked skip
    naming why there is none to give live evidence: none, a lane's own
    double, or a target the run states is in live mode, which the topology
    requirements exclude."""
    config = live_payments()
    if config.livemode:
        pytest.skip("blocked: a live verification scenario runs against Arkhai payments in "
                    "test mode, and the run states PAYMENTS.LIVEMODE true")
    assert payment_setting("SELLER_ACCOUNT"), "PAYMENTS.SELLER_ACCOUNT is required for the listing"
    return config


@pytest.fixture(scope="module")
def mock_provisioning(provisioning_client) -> None:
    """Provisioning in its mock mode, as the topology requirements state: these
    scenarios prove the payments authority, not delivery. Real provisioning is
    the topology's unmet requirement, a blocked skip naming it before the
    module's holds; ``Stage00e`` then asserts the same mode as a lane does."""
    if not provisioning_client.get_system_status().execution.mocked:
        pytest.skip("blocked: a live verification scenario runs with provisioning in its mock "
                    "mode, and the provisioning service reports real execution")


@pytest.fixture(scope="module")
def funded_buyer(payments_config, live_settings: LiveSettings) -> str:
    """The run's buyer account, holding at least one term's price at the
    run's period, which a deal bought for the whole term may reserve; the
    scenario funds nothing. Less is the topology's unmet requirement, a
    blocked skip naming it before anything is bought, so a funding stop
    cannot stand in for the stop the module observes."""
    buyer = str(payment_setting("BUYER_ACCOUNT"))
    terms = live_settings.rate_terms
    required = (math.ceil(live_settings.maximum_term_seconds / terms.period_seconds)
                * terms.period_gross)
    held = payer_available(payments_config, buyer).get(ASSET, 0)
    if held < required:
        pytest.skip(f"blocked: the buyer {buyer} holds {held} {ASSET}, less than the "
                    f"{required} a term at the run's period costs")
    return buyer


@pytest.fixture(scope="module")
def live_settings() -> LiveSettings:
    return live_verification.live_settings()


@pytest.fixture(scope="module")
def live_provenance() -> Provenance:
    """The provenance the run's evidence is labelled with, or a blocked skip
    naming what it lacks. A module takes it among its first fixtures, so a run
    that could not label its evidence buys nothing at the live target."""
    return live_verification.live_provenance()


@pytest.fixture(scope="module")
def funded_rate_payer(payments_config, live_settings: LiveSettings) -> str:
    """The rate payer funds running out pays from, holding exactly
    ``FUNDED_PERIODS`` periods' price at the run's period, as the lane row's
    funding control gives it; the scenario funds nothing.

    The account and its key are configuration the run owes, so a missing one
    fails naming it. A balance other than the requirement is the topology's
    unmet requirement, a blocked skip naming it, taken before the module's
    holds and purchase so no deal is bought from a payer that cannot show the
    observation.
    """
    payer = str(payment_setting("RATE_PAYER_ACCOUNT"))
    missing = [f"PAYMENTS.{name}" for name in ("RATE_PAYER_ACCOUNT", "RATE_PAYER_API_KEY")
               if not payment_setting(name)]
    if missing:
        pytest.fail(f"funds running out pays from a rate payer, and the run states no "
                    f"{', '.join(missing)}")
    # A term of at most the funded periods ends by its terms at the
    # Agreement's end first, which the same assertion would take for funds
    # running out.
    funded_seconds = FUNDED_PERIODS * live_settings.period_seconds
    if live_settings.maximum_term_seconds <= funded_seconds:
        pytest.fail(f"LIVE.MAXIMUM_TERM_SECONDS is {live_settings.maximum_term_seconds}; funds "
                    f"running out needs a term longer than its {FUNDED_PERIODS} periods, "
                    f"{funded_seconds} seconds")
    required = FUNDED_PERIODS * live_settings.rate_terms.period_gross
    held = payer_available(payments_config, payer).get(ASSET, 0)
    if held != required:
        pytest.skip(f"blocked: funds running out needs the rate payer {payer} funded with "
                    f"exactly {required} {ASSET}, {FUNDED_PERIODS} periods at the run's "
                    f"period, and it holds {held}")
    return payer


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory,
                 rate_row: RateRow) -> BuyerCli:
    """The run's buyer, profiled with no wallet and no waivers, buying through
    Arkhai payments alone from the row's payer."""
    payer = str(payment_setting("RATE_PAYER_ACCOUNT")) if rate_row.rate_payer else None
    return vm_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("vm_live_rate_buyer"),
        payer=payer,
    )


@pytest.fixture(scope="module")
def deal_state() -> VmLiveRateState:
    return VmLiveRateState()


@pytest.fixture(scope="module")
def deal_driver(
    payments_config, provisioning_client, provisioning_test_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client,
    site_capacity, registry_client, rate_row: RateRow, live_settings: LiveSettings,
) -> VmLiveRatePurchaseDriver:
    """VM's part of the row's purchase, over the row's own resource, host, pool
    and GPU model, under the run's period, notice and term. The buyer has no
    wallet, so of the run buyer's configuration it takes only the SSH public
    key its provision terms carry."""
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return VmLiveRatePurchaseDriver(
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
        payee_notice_seconds=(live_settings.payee_notice_seconds
                              if rate_row.payee_notice_seconds is not None else None),
        rate_terms=live_settings.rate_terms,
        term_seconds=live_settings.maximum_term_seconds,
    )


@pytest.fixture(scope="module")
def purchase_cleanup(purchase_cli, deal_driver: VmLiveRatePurchaseDriver,
                     deal_state: VmLiveRateState, provisioning_test_client):
    """Resume a job the row's gates still hold, stop a ``market buy`` still
    running, end an approved deal no input began to end, by the buyer's own
    stop, then remove the gates' rules; the lane's cleanup releases the
    module's holds and its reserved resources. A deal the module stopped, or
    whose stop it is waiting for, is the payments authority's to end; the
    balance reset and anything else between runs are the caller's.

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
