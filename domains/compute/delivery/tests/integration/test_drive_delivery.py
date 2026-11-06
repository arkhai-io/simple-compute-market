"""Activation precedes billing start and availability; undelivered deals end with evidence.

Library integration: the path over the real servicing journal and end service
on SQLite, with the once-only adapters (Alkahest's, and the hosted payments
adapter over the kit's fake payments service), port fakes and a fake site and
provisioning service.
"""

import pytest
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsConfig
from market_arkhai_payments.adapter import PaymentAdapter, pinned_snapshot_verifier
from market_arkhai_payments.agreement import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle
from market_capacity_publication import CapacityEffects
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_deal_servicing import Classification, DeliveryRecord, EndSession, FinalRequest
from market_deal_lifecycle_contracts.models import Rejected, Unknown
from market_identity import Ed25519Signer
from market_site_client import SiteCapacityClientError

from compute_delivery import (
    AcceptedDeal,
    ComputeDeliveryPath,
    ContinuationState,
    OutcomeKind,
    RepairReason,
)
from compute_delivery.window import utc_seconds, utc_text

# Public deterministic development seeds; never use on a public network.
BUYER = Ed25519Signer(bytes([1]) * 32)
SELLER = Ed25519Signer(bytes([2]) * 32)
PAYMENTS = Ed25519Signer(bytes([7]) * 32)
#: Fixture payment accounts; never real accounts.
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"


def intents(rig, negotiation_id="deal"):
    with rig.session() as conn:
        return EndSession(conn).intents(negotiation_id)


def requests(rig, negotiation_id="deal"):
    with rig.session() as conn:
        return EndSession(conn).requests(negotiation_id)


def classification(rig, source_ref):
    with rig.session() as conn:
        row = conn.execute(
            "SELECT classification FROM servicing_final_requests WHERE source_ref=?", (source_ref,),
        ).fetchone()
    return Classification.model_validate_json(row[0]).kind


def record_buyer_end(rig, *, at):
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=at, observed_at=rig.clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))


async def dispatched(rig):
    """Drive the deal to a recorded fulfillment that has not become active."""
    rig.fulfillment.state = "dispatching"
    outcome = await rig.drive()
    assert outcome.kind is OutcomeKind.PENDING and outcome.fulfillment_id == "ful-1"
    rig.fulfillment.state = "active"


async def test_a_buyer_who_never_reads_is_still_recorded_available(rig):
    activated_when_billing_started = []
    start_billing = rig.adapter.start_billing

    async def observed(key, evidence):
        activated_when_billing_started.append(rig.site.rows["res-1"]["activated_at_utc"] is not None)
        return await start_billing(key, evidence)

    rig.adapter.start_billing = observed
    outcome = await rig.drive()
    assert activated_when_billing_started == [True]
    assert outcome.kind is OutcomeKind.CONVERGED and outcome.hook_disposition == "fulfilled"
    record = rig.record()
    assert record.available_at == rig.clock[0] and record.progress == "active"
    row = rig.progress.row(rig.path, "deal")
    assert row["step"] == "activated" and row["activated_at"] == rig.clock[0]
    assert utc_seconds(rig.site.rows["res-1"]["activated_at_utc"]) == rig.clock[0]
    [billing] = [intent for intent in intents(rig) if intent.kind == "billing"]
    assert billing.operation_key == "deal:billing-start" and billing.state == "done"
    assert billing.payload["activated_delivery"] == {"version": 1, "record_ref": "res-1",
                                                     "activated_at": rig.clock[0]}
    assert billing.payload["ready"]["digest"] == "a" * 64
    assert billing.result["no_op"] is True


async def test_a_once_only_alkahest_deal_starts_billing_as_a_no_op(rig):
    await rig.drive()
    [billing] = [intent for intent in intents(rig) if intent.kind == "billing"]
    assert billing.result["outcome"]["status"] == "accepted" and billing.result["no_op"] is True
    assert rig.adapter.billing_keys == ["deal:billing-start"]


async def test_pending_evidence_publication_is_available_not_converged_and_retried(rig):
    rig.domain.continuation_state = ContinuationState.PENDING
    available = await rig.drive()
    assert available.kind is OutcomeKind.AVAILABLE and available.hook_disposition == "fulfilled"
    rig.domain.continuation_state = ContinuationState.ACKNOWLEDGED
    reads = len(rig.fulfillment.reads)
    converged = await rig.drive()
    assert converged.kind is OutcomeKind.CONVERGED
    assert rig.domain.continuations == 2
    assert len(rig.fulfillment.begins) == 1 and rig.site.calls.count("activate") == 1
    # Once available, a drive goes straight to the continuation.
    assert len(rig.fulfillment.reads) == reads


async def test_an_end_after_availability_lets_a_pending_continuation_land_and_then_ends(rig):
    rig.domain.continuation_state = ContinuationState.PENDING
    assert (await rig.drive()).kind is OutcomeKind.AVAILABLE
    rig.clock[0] += 60
    record_buyer_end(rig, at=rig.clock[0])
    rig.clock[0] += 60
    pending = await rig.drive()
    assert pending.kind is OutcomeKind.PENDING and "ended" in pending.detail
    assert rig.domain.continuations == 2 and rig.end_port.calls == []
    rig.domain.continuation_state = ContinuationState.ACKNOWLEDGED
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert rig.domain.continuations == 3
    assert rig.end_port.calls and rig.end_port.calls[0][0] is True
    # The end is the buyer's, after delivery: no delivery failure is recorded beside it.
    assert [request.source_ref for request in requests(rig)] == ["buyer-end"]
    assert len(rig.fulfillment.begins) == 1


async def test_an_end_after_availability_ends_a_deal_with_no_continuation(rig):
    assert (await rig.drive()).kind is OutcomeKind.CONVERGED
    record_buyer_end(rig, at=rig.clock[0])
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert rig.domain.continuations == 2
    assert [request.source_ref for request in requests(rig)] == ["buyer-end"]


async def test_an_available_deal_past_its_term_is_ended_without_a_delivery_failure(rig):
    assert (await rig.drive()).kind is OutcomeKind.CONVERGED
    rig.clock[0] = rig.start + 7200
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "servicing_delivery:deal"
    assert requests(rig) == []


async def test_an_end_recorded_for_later_leaves_an_available_deal_converged(rig):
    assert (await rig.drive()).kind is OutcomeKind.CONVERGED
    record_buyer_end(rig, at=rig.clock[0] + 600)
    assert (await rig.drive()).kind is OutcomeKind.CONVERGED


async def test_a_continuation_answer_of_the_wrong_kind_is_domain_result_invalid(rig):
    rig.domain.continuation_state = "acknowledged"
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert outcome.evidence_ref == "continuation:deal"


async def test_a_truncation_before_activation_is_kept_and_activation_records_the_sites_instant(rig):
    await dispatched(rig)
    record_buyer_end(rig, at=rig.start + 3600)
    await rig.end.drive_physical("deal")
    assert utc_seconds(rig.site.rows["res-1"]["lease_end_utc"]) == rig.start + 3600
    outcome = await rig.drive()
    assert outcome.kind is OutcomeKind.CONVERGED
    row = rig.site.rows["res-1"]
    assert utc_seconds(row["activated_at_utc"]) == rig.clock[0]
    assert utc_seconds(row["lease_end_utc"]) == rig.start + 3600
    assert rig.progress.row(rig.path, "deal")["activated_at"] == rig.clock[0]


@pytest.mark.parametrize("state", ["releasing", "released"])
async def test_expiry_claiming_the_lease_first_ends_the_deal_without_billing(rig, state):
    await dispatched(rig)
    rig.site.rows["res-1"]["state"] = state
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "delivery:activation-lapsed:res-1"
    assert classification(rig, "delivery:activation-lapsed:res-1") == "activation_lapse"
    assert [intent.kind for intent in intents(rig) if intent.kind in ("billing", "filing")] == ["filing"]
    assert rig.record().available_at is None
    assert rig.progress.row(rig.path, "deal")["activated_at"] is None


async def test_a_refused_activation_of_a_lease_still_running_is_unexplained(rig):
    await dispatched(rig)
    rig.site.refuse_first["activate"] = SiteCapacityClientError("refused", status_code=409)
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.ACTIVATION_UNEXPLAINED)
    assert outcome.evidence_ref == "lease:res-1" and "active" in outcome.detail
    assert outcome.capacity_reservation_id == "res-1" and outcome.fulfillment_id == "ful-1"
    assert [intent for intent in intents(rig) if intent.kind == "billing"] == []


@pytest.mark.parametrize("answer", ["unsigned", "unreachable", "unknown"])
async def test_a_site_that_cannot_activate_has_not_activated_and_is_retried(rig, answer):
    await dispatched(rig)
    rig.site.activation = answer
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.evidence_ref == "reservation:res-1"
    assert rig.progress.row(rig.path, "deal")["activated_at"] is None
    assert [intent for intent in intents(rig) if intent.kind == "billing"] == []
    assert rig.record().available_at is None
    rig.site.activation = "answer"
    retried = await rig.drive()
    assert retried.kind is OutcomeKind.CONVERGED
    assert rig.progress.row(rig.path, "deal")["activated_at"] == rig.clock[0]


async def test_a_lost_billing_start_acknowledgement_repeats_the_same_key(rig):
    rig.adapter.lose_billing = 1
    with pytest.raises(ConnectionError):
        await rig.drive()
    [pending] = [intent for intent in intents(rig) if intent.kind == "billing"]
    assert pending.state == "pending" and rig.record().available_at is None
    recovered = await rig.drive()
    assert recovered.kind is OutcomeKind.CONVERGED
    [billing] = [intent for intent in intents(rig) if intent.kind == "billing"]
    assert billing.intent_ref == pending.intent_ref and billing.state == "done"
    assert rig.adapter.billing_keys == ["deal:billing-start", "deal:billing-start"]
    assert rig.site.calls.count("activate") == 1


async def test_a_lawful_end_before_availability_files_no_self_penalty(rig):
    await dispatched(rig)
    record_buyer_end(rig, at=rig.clock[0])
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert [intent for intent in intents(rig) if intent.kind in ("filing", "billing")] == []
    assert [request.source_ref for request in requests(rig)] == ["buyer-end"]
    assert rig.end_port.calls and rig.end_port.calls[0][0] is True
    assert rig.record().available_at is None


async def test_settlement_after_the_window_dispatches_nothing_and_supplies_never_delivered_evidence(rig):
    rig.clock[0] = rig.start + 7200 + 60
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "delivery:window-elapsed:deal"
    assert rig.site.calls == [] and rig.fulfillment.begins == []
    assert classification(rig, "delivery:window-elapsed:deal") == "non_delivery"
    [filing] = [intent for intent in intents(rig) if intent.kind == "filing"]
    assert filing.payload["payload"] == {"kind": "delivery_end", "ended_at": rig.start,
                                         "delivered": False, "cause": "payee"}
    again = await rig.drive()
    assert again.kind is OutcomeKind.ENDED and len(requests(rig)) == 1


@pytest.mark.parametrize("state", ["failed", "abandoned", "tearing_down", "torn_down"])
async def test_a_failed_provisioning_is_handed_to_the_end_operation_and_adopted(rig, state):
    await dispatched(rig)
    rig.fulfillment.state = state
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "delivery:fulfillment-failed:ful-1"
    assert classification(rig, "delivery:fulfillment-failed:ful-1") == "provisioning_failure"
    assert len(rig.fulfillment.begins) == 1
    # The dispatched work is ended through the domain's end port, never replaced.
    assert rig.end_port.calls[0][0] is True and rig.site.rows["res-1"]["state"] == "leased"


@pytest.mark.parametrize(("rewrite", "state"), [
    # Acted on, the first would activate the deal and the second end it.
    ({"fulfillment_id": "ful-other"}, "active"),
    ({"capacity_reservation_id": "res-other"}, "failed"),
])
async def test_a_status_naming_another_fulfillment_or_reservation_is_site_unanswered(rig, rewrite, state):
    await dispatched(rig)
    rig.fulfillment.state = state
    rig.fulfillment.rewrite["status"] = rewrite
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.evidence_ref == "fulfillment:ful-1"
    assert outcome.capacity_reservation_id == "res-1" and outcome.fulfillment_id == "ful-1"
    assert rig.site.calls.count("activate") == 0 and rig.end_port.calls == []
    assert requests(rig) == [] and rig.record().available_at is None


async def test_a_status_answer_of_the_wrong_kind_is_site_unanswered(rig):
    await dispatched(rig)

    async def untyped(fulfillment_id, *, capacity_reservation_id, site_id):
        return {"fulfillment_id": fulfillment_id, "capacity_reservation_id": capacity_reservation_id,
                "state": "active"}

    rig.fulfillment.get_fulfillment_status = untyped
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert rig.site.calls.count("activate") == 0


async def test_a_refused_activation_explained_by_another_leases_view_is_unexplained(rig):
    await dispatched(rig)
    rig.site.rows["res-1"]["state"] = "released"
    rig.fulfillment.rewrite["lease"] = {"capacity_reservation_id": "res-other"}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.ACTIVATION_UNEXPLAINED)
    assert outcome.evidence_ref == "lease:res-1"
    assert outcome.capacity_reservation_id == "res-1" and outcome.fulfillment_id == "ful-1"
    assert requests(rig) == [] and rig.end_port.calls == []
    assert [intent for intent in intents(rig) if intent.kind in ("billing", "filing")] == []


async def test_a_refused_activation_with_a_lease_answer_of_the_wrong_kind_is_unexplained(rig):
    await dispatched(rig)
    rig.site.rows["res-1"]["state"] = "released"

    async def untyped(capacity_reservation_id, *, site_id):
        return {"capacity_reservation_id": capacity_reservation_id, "status": "released"}

    rig.fulfillment.get_lease = untyped
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.ACTIVATION_UNEXPLAINED)
    assert requests(rig) == [] and rig.end_port.calls == []


async def test_a_fulfillment_in_an_unknown_state_is_site_unanswered(rig):
    await dispatched(rig)
    rig.fulfillment.state = "provisioning"
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.evidence_ref == "fulfillment:ful-1"


async def test_a_create_that_never_settles_does_not_outlast_the_window(rig):
    await dispatched(rig)
    rig.fulfillment.state = "dispatching"
    rig.clock[0] = rig.start + 7200
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "delivery:window-elapsed:deal"
    assert classification(rig, "delivery:window-elapsed:deal") == "non_delivery"


async def test_an_end_due_when_provisioning_fails_takes_the_end_without_another_failure(rig):
    await dispatched(rig)
    record_buyer_end(rig, at=rig.clock[0])
    rig.fulfillment.state = "failed"
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert [request.source_ref for request in requests(rig)] == ["buyer-end"]


@pytest.mark.parametrize("rewrite", [{"capacity_reservation_id": "res-other"}, {"activated_at_utc": None}])
async def test_an_activation_answer_naming_no_activated_reservation_is_site_unanswered(rig, rewrite):
    await dispatched(rig)
    rig.site.rewrite["activate"] = rewrite
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert rig.progress.row(rig.path, "deal")["activated_at"] is None


async def test_billing_waits_for_this_clock_to_reach_the_sites_activation_instant(rig):
    await dispatched(rig)
    rig.site.rewrite["activate"] = {"activated_at_utc": utc_text(rig.clock[0] + 5)}
    waiting = await rig.drive()
    assert waiting.kind is OutcomeKind.PENDING
    assert [intent for intent in intents(rig) if intent.kind == "billing"] == []
    rig.clock[0] += 5
    assert (await rig.drive()).kind is OutcomeKind.CONVERGED


async def test_a_refused_billing_start_is_the_payment_authoritys_refusal(rig):
    rig.adapter.billing_outcome = Rejected(reason="the authority refuses the start")
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    [billing] = [intent for intent in intents(rig) if intent.kind == "billing"]
    assert outcome.evidence_ref == billing.intent_ref and outcome.detail == "the authority refuses the start"
    assert rig.record().available_at is None


async def test_a_billing_start_refused_because_an_end_is_due_ends_the_deal(rig):
    def end_then_refuse():
        record_buyer_end(rig, at=rig.clock[0])
        return Rejected(reason="delivery ended")

    start_billing = rig.adapter.start_billing

    async def refusing(key, evidence):
        rig.adapter.billing_outcome = end_then_refuse()
        return await start_billing(key, evidence)

    rig.adapter.start_billing = refusing
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"


async def test_an_unknown_billing_start_leaves_the_deal_pending(rig):
    rig.adapter.billing_outcome = Unknown(reason="the authority did not answer")
    outcome = await rig.drive()
    assert outcome.kind is OutcomeKind.PENDING and outcome.detail == "billing start is unknown"
    assert rig.record().available_at is None


async def test_ready_evidence_changed_after_billing_journaled_it_is_domain_result_invalid(rig):
    rig.adapter.lose_billing = 1
    with pytest.raises(ConnectionError):
        await rig.drive()
    rig.domain.ready = rig.domain.ready.model_copy(update={"digest": "b" * 64})
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert rig.adapter.billing_keys == ["deal:billing-start"]


async def test_a_hosted_once_only_payment_deal_starts_billing_as_a_no_op(rig):
    settings = ArkhaiPaymentsConfig(
        enabled=True, service_url="http://127.0.0.1:9", service_identity=PAYMENTS.identity,
        fee_bps=250, development_auth=True,
    )
    params = {"payee_account": PAYEE, "window": "P7D", "deposit_agreement": False}
    price = {"asset": "USD/2", "rates": []}
    settlement = {"schema": ARKHAI_PAYMENTS_MECHANISM, **params}
    lifecycle = dispute_lifecycle(DISPUTE)
    terms = Agreement(
        negotiation_id="paid", listing_id="listing-1", listing_hash="a" * 64,
        buyer=BUYER.identity.model_dump(mode="json"), seller=SELLER.identity.model_dump(mode="json"),
        settlement=SettlementOption(
            option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
            price=price, settlement=settlement, lifecycle=lifecycle,
        ),
        settlement_params={"payer_account": PAYER}, amount="10000", asset="USD/2",
        duration_seconds=7200, start_utc=utc_text(rig.start).replace("+00:00", "Z"),
        provision_terms={"kind": "test.v1", "version": 1, "payload": {}},
        accepted_at=utc_text(rig.start - 900).replace("+00:00", "Z"),
    ).model_dump(mode="json", exclude_none=True)
    data = PaymentSettlementData.for_agreement(terms, settings)
    peer = FakePaymentsClient(signer=PAYMENTS)
    receipt = peer.approve(data.mandate)
    peer.observed_at = receipt.receipt.approvedAt
    adapter = PaymentAdapter(
        terms, data, account=data.mandate.to.root, client_for_owner=peer,
        verify_snapshot=pinned_snapshot_verifier(terms, data, settings),
    )
    with rig.session() as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="paid", seller=SELLER.identity, commitment_ref=data.transaction_id,
            start_at=rig.start, term_end=rig.start + 7200, committed_at=rig.start - 600,
        ))
    domain = type(rig.domain)(AcceptedDeal(
        commitment_ref=data.transaction_id, binding=rig.domain.accepted.binding, payment=adapter,
    ))
    delivery = ComputeDeliveryPath(
        end=rig.end, progress=rig.progress, domain=domain, capacity=CapacityEffects(rig.site),
        fulfillment=rig.fulfillment,
    )
    outcome = await delivery.drive("paid")
    assert outcome.kind is OutcomeKind.CONVERGED
    [billing] = [intent for intent in intents(rig, "paid") if intent.kind == "billing"]
    assert billing.result["outcome"]["status"] == "accepted" and billing.result["no_op"] is True
    # Each authorized phase was checked against the hosted authority's signed snapshot.
    assert peer.count("get_transaction") >= 4
