"""A receipt-gated, fixed-term whole-host purchase on the mock bare-metal lane.

The bare-metal lane's buyer purchase: a profiled Ed25519 buyer with no wallet
buys one whole host through ``market bare-metal buy`` in ``arkhai.payments.v1``
against the lane's payments double. It runs the shared buyer-purchase stages
(``helpers/buyer_purchase_stages.py``) and the canonical deal's stages from
fulfillment onwards, ``BareMetalPurchaseDriver`` supplying bare metal's part,
and inserts bare metal's publication close (09a2, shared with the canonical
deal's bare-metal lanes) and its own:

  03   Publication:   one pass publishes the purchase's machine
  09d  Re-drive:      the run's commit, repeated from its retained identity,
                      keeps the transaction, fulfillment and durable result
  11   Seller refund: after the buyer's teardown, the seller refunds the
                      still-held payment, every part reversed
  12   Ended:         the deal reads released and the whole host is available

Financial reversal and physical release are separate operations: the buyer's
teardown ends delivery, not the payment. Mock access is never evidence of real
SSH.

The storefront's loops, fulfillment convergence, and the lease watchdog are held
for the whole module, so publication, delivery, and release are each the step a
stage asks for, and the purchase's cleanup runs before the holds are released.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from core_buyer.run_log import read_run
from market_arkhai_payments import ArkhaiPaymentsConfig, agreement_from_bytes
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage
from market_identity import Ed25519Signer
from market_pool_overrides import SyncPoolOverrideClient

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.buyer_purchase_stages import (
    Purchase01_PayerBalanceBefore,
    Purchase02_ListingDiscovered,
    Purchase03_Bought,
    Purchase04_PurchaseCorrelated,
    Purchase05_PaymentRecordsChecked,
    Purchase09_PurchaseRunEnded,
    Purchase10_BuyerTeardown,
    PurchaseState,
)
from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    advance_storefront,
    dry_run_storefront,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.compute_deal_stages import (
    Stage00_LifecycleHeld,
    Stage00a_StorefrontHealth,
    Stage00b_RegistryReachable,
    Stage00c2_ProvisioningContractPins,
    Stage00c_ProvisioningHealth,
    Stage00e_ProvisioningMockMode,
    Stage00f1_ExecutorHostRegistry,
    Stage00h_ProvisioningStorefrontLink,
    Stage07a_ArmCreateGate,
    Stage08b2_ReleaseCreateGateAndDrain,
    Stage09a_FulfillmentConvergesToActive,
    Stage09b_SettlementReadyAndCredentials,
    Stage09c2_ArmTeardownGate,
    Stage09c_LeaseRecorded,
    Stage11a2_ReleaseTeardownGateAndDrain,
    Stage11b_TeardownCompletion,
)
from tests.e2e.roles.helpers.domain_deal import ordered_events, require_state
from tests.e2e.roles.helpers.payment_compensation import (
    PurchaseCompensation,
    fulfillment_or_none,
    refund_may_clear,
)
from tests.e2e.roles.helpers.payments import (
    buyer_payments_client,
    configured_payments,
    payment_setting,
)
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import WHOLE_HOST_CAPACITY
from tests.e2e.roles.scenarios.bare_metal.conftest import _pinned, lane_setting
from tests.e2e.roles.scenarios.bare_metal.publication_stages import (
    BareMetalPublicationClosesListing,
)
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    HOURLY_GROSS,
    BareMetalPurchaseDriver,
    bare_metal_purchase_cli,
    purchase_fulfillment_transport,
    purchase_registry_client,
    purchase_signer,
    seller_refund,
)

pytestmark = [
    # Listed first, so the holds are taken before, and released after, every
    # other fixture of the module; the purchase's cleanup is listed after them.
    pytest.mark.usefixtures(
        "storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held",
        "purchase_cleanup", "lane_doubles_evidence",
    ),
    pytest.mark.e2e_bare_metal_payment_deal,
]

PUBLICATION = "publication"

log = logging.getLogger(__name__)


@dataclass
class BareMetalPurchaseState(PurchaseState):
    """The bare-metal purchase's own observations over the purchase's state."""

    domain_identity: str = "bare_metal.v1"
    #: The seller's refund of the held payment (``RefundResult``).
    refund: Optional[Any] = None


@pytest.fixture(scope="module")
def payments_config() -> ArkhaiPaymentsConfig:
    lane_setting("registry_url")
    lane_setting("storefront_url")
    config = configured_payments()
    assert config.livemode is False
    for key in ("SELLER_ACCOUNT", "COMPUTE_HOURLY_GROSS", "DISPUTE_WINDOW"):
        assert payment_setting(key), f"PAYMENTS.{key} is required for the whole-host fixture"
    assert str(payment_setting("COMPUTE_HOURLY_GROSS")) == str(HOURLY_GROSS)
    assert str(payment_setting("DISPUTE_WINDOW")) == "P7D"
    return config


@pytest.fixture(scope="module")
def purchase_cli(payments_config, buyer_cli_binary, tmp_path_factory) -> BuyerCli:
    return bare_metal_purchase_cli(
        payments_config, buyer_cli_binary, tmp_path_factory.mktemp("bare_metal_payment_buyer"),
    )


@pytest.fixture(scope="module")
def deal_state() -> BareMetalPurchaseState:
    return BareMetalPurchaseState()


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
) -> BareMetalPurchaseDriver:
    # Only the public SSH key leaves this fixture's memory.
    public = Ed25519Signer(os.urandom(32)).identity.identifier
    public_bytes = base64.urlsafe_b64decode(public + "=" * (-len(public) % 4))
    ssh_blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + public_bytes
    return BareMetalPurchaseDriver(
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
        dispute_window=str(payment_setting("DISPUTE_WINDOW")),
    )


def _release(transport, negotiation_id, fulfillment_id, provisioning_client, admin) -> dict:
    teardown = transport.teardown(negotiation_id)
    assert teardown["delivery"]["progress"] in {"tearing_down", "released"}, teardown
    assert transport.status(negotiation_id)["fulfillment_id"] == fulfillment_id
    advance_fulfillment_to(provisioning_client, fulfillment_id, "torn_down", max_advances=8)
    provisioning_client.check_leases()
    wait_for_stage_event(
        admin, "fulfillment", "capacity_released",
        negotiation_id=negotiation_id, timeout=15.0,
    )
    released = transport.status(negotiation_id)
    assert released["state"] == "released"
    return released


@pytest.fixture(scope="module")
def purchase_cleanup(
    purchase_cli, purchase_fulfillment, deal_driver: BareMetalPurchaseDriver,
    deal_state: BareMetalPurchaseState, provisioning_client, provisioning_test_client,
    storefront_admin_client,
):
    """Whatever the stages left: a held job, an unrefunded payment, a held host.

    A deal stage 12 did not record ended is still outstanding at the payments
    service and the site. Its gates are opened first, since a removed rule
    leaves a job it holds waiting and a held teardown would stall the release.
    """
    yield
    compensation = PurchaseCompensation(
        run_dir=purchase_cli.run_dir,
        status=lambda negotiation_id: fulfillment_or_none(
            purchase_fulfillment.status, negotiation_id,
        ),
        refund=seller_refund,
        release=lambda negotiation_id, status: _release(
            purchase_fulfillment, negotiation_id, str(status["fulfillment_id"]),
            provisioning_client, storefront_admin_client,
        ),
        retryable=refund_may_clear,
    )
    run_cleanup(
        [
            ("open the purchase's mock gates", deal_driver.open_gates),
            *compensation.steps(settled=deal_state.teardown is not None),
            # Deleting a rule that is already gone reports it not deleted;
            # only a real failure raises, and it is reported like any step's.
            ("remove the access-grant mock rule", lambda: provisioning_test_client
             .bare_metal_rules.delete_rule(deal_driver.create_rule_id)),
            ("remove the access-reclaim mock rule", lambda: provisioning_test_client
             .bare_metal_rules.delete_rule(deal_driver.teardown_rule_id)),
            ("drain provisioning", lambda: provisioning_test_client.drain(timeout=30)),
            ("remove the pool override", deal_driver.remove_pool_override),
        ],
    )


# ===========================================================================
# Readiness and supply
# ===========================================================================

class TestStage00_LifecycleHeld(Stage00_LifecycleHeld):
    pass


class TestStage00a_StorefrontHealth(Stage00a_StorefrontHealth):
    pass


class TestStage00b_RegistryReachable(Stage00b_RegistryReachable):
    pass


class TestStage00c_ProvisioningHealth(Stage00c_ProvisioningHealth):
    pass


class TestStage00c2_ProvisioningContractPins(Stage00c2_ProvisioningContractPins):
    pass


class TestStage00e_ProvisioningMockMode(Stage00e_ProvisioningMockMode):
    pass


class TestStage00f1_ExecutorHostRegistry(Stage00f1_ExecutorHostRegistry):
    pass


class TestStage00h_ProvisioningStorefrontLink(Stage00h_ProvisioningStorefrontLink):
    pass


class TestStage03_PublicationPublishesTheMachine:
    def test_03_one_publication_pass_publishes_the_purchase_listing(
        self, storefront_admin_client, deal_driver: BareMetalPurchaseDriver,
        deal_state: BareMetalPurchaseState,
    ):
        """The dry run would publish the machine, and one pass publishes it."""
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
        log.info("[03] Listing %s published for machine %s", listings[0], resource_id)


# ===========================================================================
# The purchase
# ===========================================================================

class TestPurchase01_PayerBalanceBefore(Purchase01_PayerBalanceBefore):
    pass


class TestPurchase02_ListingDiscovered(Purchase02_ListingDiscovered):
    pass


class TestStage07a_ArmCreateGate(Stage07a_ArmCreateGate):
    pass


class TestPurchase03_Bought(Purchase03_Bought):
    pass


class TestPurchase04_PurchaseCorrelated(Purchase04_PurchaseCorrelated):
    pass


class TestStage08b2_ReleaseCreateGateAndDrain(Stage08b2_ReleaseCreateGateAndDrain):
    pass


class TestPurchase05_PaymentRecordsChecked(Purchase05_PaymentRecordsChecked):
    pass


# ===========================================================================
# Delivery
# ===========================================================================

class TestStage09a_FulfillmentConvergesToActive(Stage09a_FulfillmentConvergesToActive):
    pass


class TestStage09a2_PublicationClosesTheListing(BareMetalPublicationClosesListing):
    pass


class TestStage09b_SettlementReadyAndCredentials(Stage09b_SettlementReadyAndCredentials):
    pass


class TestStage09c_LeaseRecorded(Stage09c_LeaseRecorded):
    pass


class TestPurchase09_PurchaseRunEnded(Purchase09_PurchaseRunEnded):
    pass


class TestStage09d_SettlementReDriven:
    def test_09d_the_runs_commit_re_driven_is_the_same_settlement(
        self, purchase_cli: BuyerCli, purchase_fulfillment, deal_state: BareMetalPurchaseState,
    ):
        """The original run's commit, repeated under its retained identity.

        Recovery reads the signed run, resolves its recorded profile and
        principal, and commits the same negotiation and transaction again; the
        transaction, the fulfillment and the durable result are unchanged.
        """
        require_state(deal_state, "purchase_run", "negotiation_id", "settlement_id",
                      "fulfillment_id", "agreement", "settlement_status")
        run_id = deal_state.purchase_run.run_id
        signer = purchase_signer(purchase_cli, run_id)
        assert signer.identity == purchase_fulfillment.principal
        _, accepted, approved, ended = ordered_events(
            read_run(run_id, signer=signer, directory=purchase_cli.run_dir),
            "run_started", "negotiation_completed", "payment_approved", "run_ended",
        )
        assert accepted["negotiation_id"] == deal_state.negotiation_id
        assert approved["transaction_id"] == ended["transaction_id"] == deal_state.settlement_id
        assert agreement_from_bytes(
            base64.b64decode(accepted["agreement_bytes"], validate=True)
        ) == deal_state.agreement
        delivered = purchase_fulfillment.result(deal_state.negotiation_id)

        async def commit():
            async with LifecycleClient(lane_setting("storefront_url"), signer, _pinned("storefront")) as buyer:
                again = await buyer.commit(CommitMessage(
                    negotiation_id=deal_state.negotiation_id,
                    commitment_ref=deal_state.settlement_id,
                    operation_key="commit:" + deal_state.settlement_id,
                ))
                assert again.outcome.status == "accepted", again
                read = await buyer.read(deal_state.negotiation_id)
                assert read.commitment_ref == deal_state.settlement_id, read

        asyncio.run(commit())
        status = purchase_fulfillment.status(deal_state.negotiation_id)
        assert status["fulfillment_id"] == deal_state.fulfillment_id, status
        assert purchase_fulfillment.result(deal_state.negotiation_id) == delivered
        log.info("[09d] Run %s re-committed Agreement %s under transaction %s; fulfillment %s "
                 "unchanged", run_id, deal_state.negotiation_id, deal_state.settlement_id,
                 deal_state.fulfillment_id)


# ===========================================================================
# The buyer's teardown, then the seller's refund
# ===========================================================================

class TestStage09c2_ArmTeardownGate(Stage09c2_ArmTeardownGate):
    pass


class TestPurchase10_BuyerTeardown(Purchase10_BuyerTeardown):
    pass


class TestStage11a2_ReleaseTeardownGateAndDrain(Stage11a2_ReleaseTeardownGateAndDrain):
    pass


class TestStage11_SellerRefundsTheHeldPayment:
    def test_11_the_seller_refunds_the_payment_the_teardown_left_held(
        self, payments_config: ArkhaiPaymentsConfig, deal_state: BareMetalPurchaseState,
    ):
        """After the buyer's teardown, the seller reverses every part of the payment.

        The teardown ended delivery, not the payment, so the payment is still
        held and its reverse takes every part.
        """
        require_state(deal_state, "negotiation_id", "settlement_id", "teardown_fulfillment_id")
        refunded = seller_refund(deal_state.negotiation_id)
        assert refunded.status == "refunded", refunded
        assert refunded.settlement_ref == deal_state.settlement_id, refunded
        with buyer_payments_client(payments_config, str(payment_setting("BUYER_ACCOUNT"))) as client:
            snapshot = client.get_transaction(str(deal_state.settlement_id)).snapshot
        assert snapshot.parts and {part.status.value for part in snapshot.parts} == {"reversed"}
        assert all(part.rate is None and part.reversed.root == part.gross.root
                   and part.released.root == "0" and part.held.root == "0"
                   for part in snapshot.parts), snapshot.parts
        deal_state.refund = refunded
        log.info("[11] Seller refunded Agreement %s: transaction %s reversed",
                 deal_state.negotiation_id, deal_state.settlement_id)


class TestStage11b_TeardownCompletion(Stage11b_TeardownCompletion):
    pass


class TestStage12_PurchaseEnded:
    def test_12_the_deal_is_released_and_the_whole_host_available(
        self, purchase_fulfillment, deal_driver: BareMetalPurchaseDriver,
        deal_state: BareMetalPurchaseState,
    ):
        """The buyer reads the deal released, and the site the whole machine free."""
        require_state(deal_state, "refund", "teardown_fulfillment_id")
        released = purchase_fulfillment.status(deal_state.negotiation_id)
        assert released["state"] == "released", released
        assert deal_driver.available_units() == WHOLE_HOST_CAPACITY["units"]
        deal_state.teardown = {
            "transaction": deal_state.refund.settlement_ref, "physical": released,
        }
        log.info("[12] Agreement %s released; fulfillment %s; machine %s available",
                 deal_state.negotiation_id, deal_state.teardown_fulfillment_id,
                 deal_driver.reserved_resource_id)
