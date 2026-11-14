"""One payments transaction adapter serves once-only and mixed mandates by composition."""

import asyncio

import pytest
from market_deal_lifecycle.delivery import ActivatedDeliveryRef, DeliveryEvidence
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand

from market_arkhai_payments.adapter import PaymentAdapter, pinned_snapshot_verifier
from market_arkhai_payments.agreement import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.models import StoredEvent

from payment_terms import SERVICE, agreement, config
from rate_terms import NOW, MemoryOperations, approved


def command(adapter, kind, key="operation", **payload):
    return LifecycleCommand(negotiation_id=adapter.negotiation_id, kind=kind, operation_key=key, payload=payload)


def once_only():
    terms, settings = agreement(), config()
    data = PaymentSettlementData.for_agreement(terms, settings)
    peer = FakePaymentsClient(signer=SERVICE)
    receipt = peer.approve(data.mandate)
    peer.observed_at = receipt.receipt.approvedAt
    adapter = PaymentAdapter(
        terms, data, account=data.mandate.to.root, client_for_owner=peer,
        verify_snapshot=pinned_snapshot_verifier(terms, data, settings),
    )
    return peer, adapter


def test_a_mixed_mandate_reverses_its_setup_and_stops_its_rate_in_one_adapter():
    async def drive():
        _, data, fake, adapter, _ = approved()
        assert [part.root.kind for part in data.mandate.parts] == ["once", "rate"]
        assert adapter.supported_commands == {"start", "stop", "notice", "reverse"}
        store = MemoryOperations()
        reverse = command(adapter, "reverse", "refund-setup", part="0", amount="5")
        assert (await adapter.submit(reverse, OperationKeys(adapter.negotiation_id, "refund-setup", store))).status == "accepted"
        stop = command(adapter, "stop", "stop-rate", part="1")
        assert (await adapter.submit(stop, OperationKeys(adapter.negotiation_id, "stop-rate", store))).status == "accepted"
        view = await adapter.read()
        # Only the rate part carries rate observations; the setup part's
        # reverse is an ordinary once movement with its amount.
        assert [part.part for part in view.parts] == ["1"]
        assert view.parts[0].pending_stop.at == NOW + 30 and view.state == "ending"
        kinds = {(event.part, event.kind, event.amount) for event in view.events}
        assert ("0", "reverse", "5") in kinds and ("1", "stop_request", None) in kinds
        assert fake.count("reverse") == 1 and fake.count("submit_event") == 1
    asyncio.run(drive())


def test_a_once_only_mandates_billing_start_is_a_no_op():
    async def drive():
        peer, adapter = once_only()
        evidence = DeliveryEvidence(negotiation_id=adapter.negotiation_id, commitment_ref=adapter.commitment_ref)
        activated = evidence.model_copy(update={
            "activated_delivery": ActivatedDeliveryRef(record_ref="site-activation", activated_at=1),
        })
        keys = OperationKeys(adapter.negotiation_id, "billing")
        started = await adapter.start_billing(keys, activated)
        assert isinstance(started.outcome, Accepted) and started.no_op
        assert (await adapter.start_billing(keys, evidence)).outcome.status == "rejected"
        assert peer.count("submit_event") == 0 and peer.count("reverse") == 0
        assert adapter.billing_operations(keys, activated) == ()
    asyncio.run(drive())


@pytest.mark.parametrize("kind,payload", [("start", {"part": "0"}), ("stop", {"part": "0"}), ("notice", {}), ("stop", {})])
def test_a_once_only_mandate_refuses_every_rate_command(kind, payload):
    _, adapter = once_only()
    assert adapter.supported_commands == {"reverse"}
    refusal = adapter.validate(command(adapter, kind, **payload))
    assert refusal is not None and "voluntary reverse only" in refusal.reason


def test_a_changed_stop_retry_is_refused_before_any_authority_call():
    async def drive():
        _, _, fake, adapter, _ = approved()
        store = MemoryOperations()
        keys = OperationKeys(adapter.negotiation_id, "stop", store)
        first = command(adapter, "stop", "stop", part="1")
        assert (await adapter.submit(first, keys)).status == "accepted"
        sent, reads = fake.count("submit_event"), fake.count("get_transaction")
        changed = first.model_copy(update={"at": NOW + 600})
        refused = await adapter.submit(changed, keys)
        assert refused.status == "rejected" and "changes content" in refused.reason
        assert (fake.count("submit_event"), fake.count("get_transaction")) == (sent, reads)
        # The identical retry is sent again under its one request identity,
        # and the authority answers with the event it already recorded.
        replay = await adapter.submit(first, keys)
        assert replay.status == "accepted"
        stops = [event.root for event in fake.get_transaction(adapter.commitment_ref).snapshot.events
                 if isinstance(event.root, StoredEvent) and event.root.event.kind.value == "stop"]
        assert len(stops) == 1 and stops[0].requestId.root == keys.part_event("1", "stop")
    asyncio.run(drive())


def test_a_stop_answered_by_an_earlier_winning_stop_is_satisfied_by_it():
    async def drive():
        raw, data, fake, payee, _ = approved(payer_notice=0)
        payer = PaymentAdapter(raw, data, account=data.mandate.from_.root, client_for_owner=fake,
                               verify_snapshot=payee.snapshots.verify, clock=lambda: fake.observed_at)
        stopped = await payer.submit(command(payer, "stop", "buyer-stop", part="1"),
                                     OperationKeys(payer.negotiation_id, "buyer-stop", MemoryOperations()))
        assert stopped.status == "accepted"
        fake.observed_at += 1
        # The authority answers the seller's later notice with the payer's
        # winning stop, which is effective no later, so it satisfies the notice.
        notice = await payee.submit(command(payee, "stop", "notice", part="1"),
                                    OperationKeys(payee.negotiation_id, "notice", MemoryOperations()))
        assert notice.status == "accepted"
        assert [(record.actor, record.kind, record.at) for record in notice.records] == [
            (data.mandate.from_.root, "stop", NOW),
        ]
    asyncio.run(drive())


def test_a_once_only_reverse_without_a_store_falls_back_to_the_authoritys_refusal():
    async def drive():
        peer, adapter = once_only()
        keys = OperationKeys(adapter.negotiation_id, "refund")
        assert (await adapter.submit(command(adapter, "reverse", "refund", part="0", amount="10"), keys)).status == "accepted"
        changed = await adapter.submit(command(adapter, "reverse", "refund", part="0", amount="20"), keys)
        assert changed.status == "rejected" and "request_id_reused" in changed.reason
    asyncio.run(drive())
