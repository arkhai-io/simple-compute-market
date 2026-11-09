"""Hosted VM commit, servicing, operator end/case and separate physical release.

The commit and servicing stages need a payments target, which the VM lane runs
as its payments double (PAYMENTS). The operator-end and refund stages also need
a dispute authority that accepts a filed case, MEDIATION.SERVICE_URL, and report
a blocked skip naming it where none is configured, as in the lane, whose
registries recommend an authority that can never answer. Servicing still reads
the deal running then, because the storefront holds a dispute credential for that
authority. Provisioning uses the VM lane's mock executor, not a real guest or SSH
proof.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import time

import pytest
from market_arkhai_payments import PaymentApproval, PaymentSettlementData
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import (
    DealLease, advance_fulfillment_to, advance_storefront, wait_for_stage_event,
)
from tests.e2e.roles.helpers.mediation import configured_mediation
from tests.e2e.roles.helpers.payments import (
    buyer_payments_client,
    configured_payments,
    payment_setting,
)
from tests.e2e.roles.scenarios.vms.composed_listing import payments_settlement
from tests.e2e.roles.scenarios.vms.conftest import (
    _publisher_trust, _signer, capacity_source_for,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_PAYMENT_DEAL_HOST, E2E_PAYMENT_DEAL_POOL_ID,
)
from tests.e2e.roles.scenarios.vms.lifecycle_deal import (
    LifecyclePurchase, Stage12c_CapacityReleasedOnce, TypedLifecycleBuyer,
)
from tests.e2e.roles.scenarios.vms.test_full_deal import OFFER_RESOURCE as _DEAL_RESOURCE

#: This scenario's own resource, the canonical deal's shape under another id. A
#: listing's binding to its resource outlives the listing, so whichever scenario on a
#: shared stack lists a resource second is refused.
PAYMENT_RESOURCE_ID = "compute-e2e-payment-deal-001"
OFFER_RESOURCE = {**_DEAL_RESOURCE, "resource_id": PAYMENT_RESOURCE_ID}


pytestmark = [
    pytest.mark.usefixtures(
        "payments_config", "storefront_loops_held", "alice_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held",
        "ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources",
    ),
    pytest.mark.e2e_vm_payment_deal,
]


@pytest.fixture(scope="module")
def payments_config():
    return configured_payments()


@pytest.fixture(scope="module")
def mediation_target():
    """The case stages' dispute authority; a blocked skip when none is configured."""
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


def _peer():
    return LifecycleClient(
        str(settings.SELLER.API_URL),
        _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"),
        _publisher_trust(),
    )


def _read(negotiation_id):
    async def read():
        async with _peer() as peer:
            return await peer.read(negotiation_id)
    return asyncio.run(read())


def _commit(negotiation_id, transaction):
    async def commit():
        async with _peer() as peer:
            return await peer.commit(CommitMessage(
                negotiation_id=negotiation_id, commitment_ref=transaction,
                operation_key="commit:" + transaction,
            ))
    return asyncio.run(commit())


def _snapshot(config, transaction):
    with buyer_payments_client(config, str(payment_setting("BUYER_ACCOUNT"))) as client:
        return client.get_transaction(transaction).snapshot


def test_hosted_commit_delivers_after_a_verified_receipt(
    payments_config, hosted, deal_driver, deal_state, storefront_seller_client,
    storefront_client, storefront_admin_client, registry_client, provisioning_client,
    provisioning_test_client, site_capacity,
):
    deal_driver.seed_supply()
    listing_id = storefront_seller_client.create_listing(
        listing_resource=OFFER_RESOURCE, capacity_source=capacity_source_for(OFFER_RESOURCE),
        max_duration_seconds=3600,
        settlements=[payments_settlement(
            seller_account=str(payment_setting("SELLER_ACCOUNT")),
            dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
        )],
    ).listing_id
    published = registry_client.get_listing(listing_id)
    assert len(published.settlement_options) == 1
    option = published.settlement_options[0]
    assert option["settlement"]["schema"] == "arkhai.payments.v1"
    assert option["lifecycle"]["adjudication"]["dispute"]["interface"] == "arkhai.mediation.v1"
    opened = storefront_client.negotiate_new(
        listing_id=listing_id, initial_amount=1000000, provision_terms=deal_driver.provision_terms(),
        selection_only=True, settlement_selection={
            "option_id": option["option_id"],
            "settlement": {"schema": "arkhai.payments.v1",
                           "payer_account": str(payment_setting("BUYER_ACCOUNT"))},
            "expiration_unix": int(time.time()) + 300,
        },
    )
    negotiation_id = opened["negotiation_id"]
    accepted = opened
    if opened["action"] == "counter":
        accepted = storefront_client.negotiate_continue(negotiation_id, action="accept")
    assert accepted["action"] == "accept", accepted
    raw = base64.b64decode(accepted["agreement_bytes"], validate=True)
    data = PaymentSettlementData.parse(accepted["settlement_data"])
    approval = PaymentApproval(
        payments_config, str(payment_setting("BUYER_ACCOUNT")),
        client_for_owner=lambda owner: buyer_payments_client(payments_config, owner),
    )
    assert storefront_client.settle_agreement(negotiation_id).status == "pending"
    assert approval.approve(raw, data.to_wire()) == data.transaction_id
    deal_driver.arm_create_gate()
    committed = _commit(negotiation_id, data.transaction_id)
    assert committed.outcome.status == "accepted", committed
    wait_for_stage_event(storefront_admin_client, "provision", "job_submitted",
                         negotiation_id=negotiation_id, timeout=30)
    status = storefront_client.get_settle_status(negotiation_id)
    assert status.fulfillment_id, status
    deal_driver.release_create_gate()
    provisioning_test_client.drain(timeout=30)
    advance_fulfillment_to(provisioning_client, status.fulfillment_id, "active")
    ready = storefront_admin_client.wait_for_settlement(negotiation_id, timeout=30)
    assert ready.ready and ready.status == "ready", ready
    assert storefront_client.get_settle_status(negotiation_id).tenant_credentials
    lease = DealLease(provisioning_client, site_capacity, negotiation_id=negotiation_id)
    assert lease.refresh()["status"] == "active"
    purchase = LifecyclePurchase(negotiation_id, status.fulfillment_id, lease.lease_id)
    deal_state.lifecycle_purchase = purchase
    hosted.update(transaction=data.transaction_id, negotiation_id=negotiation_id,
                  fulfillment_id=status.fulfillment_id, ready=ready, purchase=purchase)
    snapshot = _snapshot(payments_config, data.transaction_id)
    assert len(snapshot.parts) == 1
    assert all(part.held.root == part.gross.root and part.reversed.root == "0" for part in snapshot.parts)


def test_commit_replay_and_servicing_keep_the_same_hosted_deal(
    hosted, storefront_admin_client, storefront_client,
):
    assert hosted.get("transaction"), "hosted commit did not complete"
    transaction, negotiation_id = hosted["transaction"], hosted["negotiation_id"]
    assert _commit(negotiation_id, transaction).outcome.status == "accepted"
    advance_storefront(storefront_admin_client, "settlement-servicing")
    view = _read(negotiation_id)
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
    assert first["delivery"]["progress"] == "tearing_down", first
    again = storefront_admin_client.admin_interrupt_deal(
        negotiation_id, reason="development hosted VM reclaim",
    )
    assert again["delivery"]["recorded_end"] == first["delivery"]["recorded_end"]
    advance_storefront(storefront_admin_client, "settlement-servicing")
    view = _read(negotiation_id)
    assert view.authority.outcome.status == "accepted", view
    assert len(view.authority.cases) == 1, view
    assert any(event.kind == "filed" for event in view.authority.disputes), view
    assert len(view.delivery.site_reports) == 1, view
    assert view.delivery.progress == "tearing_down", view
    assert all(part.reversed.root == "0" and part.held.root == part.gross.root
               for part in _snapshot(payments_config, hosted["transaction"]).parts)
    hosted["case_ref"] = view.authority.cases[0].case_ref
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
    snapshot = _snapshot(payments_config, hosted["transaction"])
    assert snapshot.parts and all(
        part.reversed.root == part.gross.root and part.held.root == "0" and part.released.root == "0"
        for part in snapshot.parts
    )
    assert _read(hosted["negotiation_id"]).delivery.progress == "tearing_down"
    Stage12c_CapacityReleasedOnce().test_12c_only_provider_completion_and_callback_prove_capacity_return(
        provisioning_client, provisioning_test_client, storefront_admin_client,
        vm_lifecycle_buyer, deal_state,
    )
