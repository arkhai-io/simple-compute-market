"""The hosted VM deal in Arkhai payments, committed once and read back.

Every VM scenario that runs a hosted once-only deal in ``arkhai.payments.v1``
commits it with ``commit_hosted_deal``, so its body is defined once: a listing
of the scenario's own resource with one Arkhai payments settlement, the
negotiation, the buyer's approval at the lane's payments double, the commit, and
delivery stepped to ``active`` through the mock create gate. It writes what
later stages read: the deal it returns, ``deal_state.lifecycle_purchase`` for the
end and release stages of ``lifecycle_deal.py``, and the handoff the shared
lease-expiry stages of ``compute_deal_stages.py`` read, keyed on the deal's
negotiation as every VM lease is.

The reads beside it are the storefront's lifecycle read as the buyer, through
``LifecycleClient``, and the transaction's payments snapshot, through the
payments kit with the buyer's own token.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import PaymentApproval, PaymentSettlementData
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage, LifecycleRead, SubmitResponse

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import (
    DealLease, advance_fulfillment_to, wait_for_stage_event,
)
from tests.e2e.roles.helpers.payments import buyer_payments_client, payment_setting
from tests.e2e.roles.scenarios.vms.composed_listing import payments_settlement
from tests.e2e.roles.scenarios.vms.conftest import (
    _publisher_trust, _signer, capacity_source_for,
)
from tests.e2e.roles.scenarios.vms.lifecycle_deal import LifecyclePurchase
from tests.e2e.roles.scenarios.vms.test_full_deal import OFFER_RESOURCE as _DEAL_RESOURCE


@dataclass(frozen=True)
class HostedDeal:
    """A committed hosted deal, delivering."""

    negotiation_id: str
    transaction: str
    listing_id: str
    fulfillment_id: str
    #: The accepted Agreement, as the buyer approved it.
    agreement: dict[str, Any]
    purchase: LifecyclePurchase
    ready: Any


def _peer() -> LifecycleClient:
    return LifecycleClient(
        str(settings.SELLER.API_URL),
        _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"),
        _publisher_trust(),
    )


def lifecycle_read(negotiation_id: str) -> LifecycleRead:
    """The storefront's lifecycle read of the deal, as the buyer reads it."""
    async def read():
        async with _peer() as peer:
            return await peer.read(negotiation_id)
    return asyncio.run(read())


def commit(negotiation_id: str, transaction: str) -> SubmitResponse:
    """The buyer's commit of the approved transaction, under its stable key."""
    async def send():
        async with _peer() as peer:
            return await peer.commit(CommitMessage(
                negotiation_id=negotiation_id, commitment_ref=transaction,
                operation_key="commit:" + transaction,
            ))
    return asyncio.run(send())


def payment_snapshot(config, transaction: str):
    """The transaction's signed snapshot, read with the buyer's own token."""
    with buyer_payments_client(config, str(payment_setting("BUYER_ACCOUNT"))) as client:
        return client.get_transaction(transaction).snapshot


def commit_hosted_deal(
    payments_config, deal_driver, deal_state, *, resource_id: str, storefront_seller_client,
    storefront_client, storefront_admin_client, registry_client, provisioning_client,
    provisioning_test_client, site_capacity,
) -> HostedDeal:
    """List ``resource_id`` in Arkhai payments, negotiate, approve, commit and
    deliver it to ``active``; the committed deal, its one part held whole.

    ``deal_driver`` is the VM driver over the scenario's own executor, pool and
    resource.
    """
    resource = {**_DEAL_RESOURCE, "resource_id": resource_id}
    deal_driver.seed_supply()
    listing_id = storefront_seller_client.create_listing(
        listing_resource=resource, capacity_source=capacity_source_for(resource),
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
    committed = commit(negotiation_id, data.transaction_id)
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
    # The handoff the shared lease-expiry stages read: a VM lease is keyed on
    # its negotiation, whatever settled it.
    deal_state.seller_listing_id = listing_id
    deal_state.negotiation_id = negotiation_id
    deal_state.settlement_ref = negotiation_id
    deal_state.fulfillment_id = status.fulfillment_id
    deal_state.deal_lease = lease
    deal_state.lease_id = lease.lease_id
    deal_state.reserved_resource_id = resource_id
    snapshot = payment_snapshot(payments_config, data.transaction_id)
    assert len(snapshot.parts) == 1
    assert all(part.held.root == part.gross.root and part.reversed.root == "0"
               for part in snapshot.parts)
    return HostedDeal(
        negotiation_id=negotiation_id, transaction=data.transaction_id, listing_id=listing_id,
        fulfillment_id=status.fulfillment_id, agreement=json.loads(raw), purchase=purchase,
        ready=ready,
    )
