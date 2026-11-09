"""Hosted VM commit, servicing, operator end/case and separate physical release.

The commit and servicing stages need a payments target, which the VM lane runs
as its payments double (PAYMENTS). The operator-end and refund stages also need
the dispute authority the registries recommend, MEDIATION.SERVICE_URL, which the
lane runs as its mediation double: with no rule installed it accepts the
seller's filing and holds each part by an extension at the payments double, and
rules nothing, so the seller's refund reverses the held money. Where no target
is named they report a blocked skip naming it; an unready lane-owned target
fails them by name. Provisioning uses the VM lane's mock executor, not a real
guest or SSH proof. Its commit is the hosted deal every such VM scenario commits
(``payment_deal.py``).
"""

from __future__ import annotations

import dataclasses

import pytest

from tests.e2e.roles.helpers.compute_deal import advance_storefront
from tests.e2e.roles.helpers.mediation import configured_mediation
from tests.e2e.roles.helpers.payments import configured_payments
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_PAYMENT_DEAL_HOST, E2E_PAYMENT_DEAL_POOL_ID,
)
from tests.e2e.roles.scenarios.vms.lifecycle_deal import (
    Stage12c_CapacityReleasedOnce, TypedLifecycleBuyer,
)
from tests.e2e.roles.scenarios.vms.payment_deal import (
    commit, commit_hosted_deal, lifecycle_read, payment_snapshot,
)

#: This scenario's own resource, the canonical deal's shape under another id. A
#: listing's binding to its resource outlives the listing, so whichever scenario on a
#: shared stack lists a resource second is refused.
PAYMENT_RESOURCE_ID = "compute-e2e-payment-deal-001"


pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
        "lane_doubles_evidence",
    ),
    pytest.mark.e2e_vm_payment_deal,
]


@pytest.fixture(scope="module")
def payments_config():
    return configured_payments()


@pytest.fixture(scope="module")
def mediation_target():
    """The case stages' dispute authority: a blocked skip when none is
    configured, a failure when the lane's own is not ready."""
    return configured_mediation()


@pytest.fixture(scope="module")
def deal_driver(deal_driver):
    """The VM deal driver over this scenario's own executor, pool, and resource."""
    return dataclasses.replace(
        deal_driver, reserved_resource_id=PAYMENT_RESOURCE_ID,
        host=E2E_PAYMENT_DEAL_HOST, pool_id=E2E_PAYMENT_DEAL_POOL_ID,
    )


@pytest.fixture(scope="module")
def hosted():
    return {}


@pytest.fixture(scope="module")
def vm_lifecycle_buyer(storefront_client, storefront_admin_client, registry_client,
                       deal_driver, buyer_config, seller_wallet, site_capacity):
    return TypedLifecycleBuyer(storefront_client, storefront_admin_client, registry_client,
                               deal_driver, buyer_config, seller_wallet, site_capacity)


def test_hosted_commit_delivers_after_a_verified_receipt(
    payments_config, hosted, deal_driver, deal_state, storefront_seller_client,
    storefront_client, storefront_admin_client, registry_client, provisioning_client,
    provisioning_test_client, site_capacity,
):
    deal = commit_hosted_deal(
        payments_config, deal_driver, deal_state, resource_id=PAYMENT_RESOURCE_ID,
        storefront_seller_client=storefront_seller_client, storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client, registry_client=registry_client,
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client, site_capacity=site_capacity,
    )
    hosted.update(transaction=deal.transaction, negotiation_id=deal.negotiation_id,
                  fulfillment_id=deal.fulfillment_id, ready=deal.ready, purchase=deal.purchase)


def test_commit_replay_and_servicing_keep_the_same_hosted_deal(
    hosted, storefront_admin_client, storefront_client,
):
    assert hosted.get("transaction"), "hosted commit did not complete"
    transaction, negotiation_id = hosted["transaction"], hosted["negotiation_id"]
    assert commit(negotiation_id, transaction).outcome.status == "accepted"
    advance_storefront(storefront_admin_client, "settlement-servicing")
    view = lifecycle_read(negotiation_id)
    assert view.commitment_ref == transaction
    # The authority does not know this Agreement until its first case is filed.
    # Its absent record is not a verified empty case history.
    assert view.authority.state == "running", view
    assert view.delivery.progress == "active", view
    assert storefront_client.get_settle_status(negotiation_id).fulfillment_id == hosted["fulfillment_id"]


def test_operator_end_files_one_case_without_a_local_payment_remedy(
    mediation_target, hosted, payments_config, storefront_admin_client, deal_driver,
):
    assert hosted.get("transaction"), "hosted commit did not complete"
    deal_driver.arm_teardown_gate()
    negotiation_id = hosted["negotiation_id"]
    first = storefront_admin_client.admin_interrupt_deal(
        negotiation_id, reason="development hosted VM reclaim",
    )
    assert first["settlement_action"] == "delivery_end_filing", first
    assert first["lifecycle_outcome"]["status"] == "accepted", first
    # With no rule installed the authority accepts the filing and holds every
    # part by an extension of its own, ruling nothing.
    filing = first["lifecycle_outcome"]["filing"]
    assert filing and filing["parts"], first
    assert all(part["status"] == "held" and part["extension_ref"] for part in filing["parts"]), filing
    assert first["delivery"]["progress"] == "tearing_down", first
    again = storefront_admin_client.admin_interrupt_deal(
        negotiation_id, reason="development hosted VM reclaim",
    )
    assert again["delivery"]["recorded_end"] == first["delivery"]["recorded_end"]
    advance_storefront(storefront_admin_client, "settlement-servicing")
    view = lifecycle_read(negotiation_id)
    assert view.authority.outcome.status == "accepted", view
    assert len(view.authority.cases) == 1, view
    (case,) = view.authority.cases
    assert any(event.kind == "filed" for event in view.authority.disputes), view
    assert not any(event.kind == "ruled" for event in view.authority.disputes), view
    assert len(view.delivery.site_reports) == 1, view
    assert view.delivery.progress == "tearing_down", view
    # Each part is held at the payments double by the case's own extension.
    snapshot = payment_snapshot(payments_config, hosted["transaction"])
    assert all(part.reversed.root == "0" and part.held.root == part.gross.root
               for part in snapshot.parts)
    assert sorted(extension.part for extension in view.authority.extensions) == sorted(
        str(part.part) for part in snapshot.parts), view
    assert all(extension.case_ref == case.case_ref for extension in view.authority.extensions), view
    hosted["case_ref"] = case.case_ref
    purchase = hosted["purchase"]
    purchase.receipt = {"selected_end": view.delivery.recorded_end.model_dump(mode="json")}
    purchase.reports = [item.model_dump(mode="json") for item in view.delivery.site_reports]


def test_seller_refund_is_financial_and_release_waits_for_the_callback(
    mediation_target, hosted, payments_config, storefront_seller_client, provisioning_client,
    provisioning_test_client, storefront_admin_client, vm_lifecycle_buyer, deal_state,
):
    assert hosted.get("case_ref"), "operator end did not produce its authority case"
    refunded = storefront_seller_client.refund_settlement(hosted["negotiation_id"])
    assert refunded.status == "refunded", refunded
    assert refunded.settlement_ref == hosted["transaction"]
    snapshot = payment_snapshot(payments_config, hosted["transaction"])
    assert snapshot.parts and all(
        part.reversed.root == part.gross.root and part.held.root == "0" and part.released.root == "0"
        for part in snapshot.parts
    )
    assert lifecycle_read(hosted["negotiation_id"]).delivery.progress == "tearing_down"
    Stage12c_CapacityReleasedOnce().test_12c_only_provider_completion_and_callback_prove_capacity_return(
        provisioning_client, provisioning_test_client, storefront_admin_client,
        vm_lifecycle_buyer, deal_state,
    )
