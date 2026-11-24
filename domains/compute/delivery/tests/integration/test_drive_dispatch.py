"""Dispatch is authorized, recorded before it begins, and recovered without a second fulfillment.

Library integration: the path over the real servicing journal on SQLite, with
port fakes and a fake site and provisioning service.
"""

import pytest
from market_deal_servicing import Classification, EndSession, FinalRequest
from market_identity import Ed25519Signer

from compute_delivery import OutcomeKind, RepairReason

# Public deterministic development seed; never use on a public network.
BUYER = Ed25519Signer(bytes([1]) * 32)


def record_buyer_end(rig):
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0], observed_at=rig.clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))


def authorizations(rig, phase):
    with rig.session() as conn:
        return [
            intent for intent in EndSession(conn).intents("deal")
            if intent.kind == "authorization" and intent.payload["phase"] == phase
        ]


async def test_an_end_recorded_after_the_dispatch_authorization_was_read_stops_dispatch(rig):
    def end_during(phase):
        if phase.value == "dispatch":
            record_buyer_end(rig)

    rig.adapter.on_authorize = end_during
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert rig.fulfillment.begins == []
    # The dispatch record shares the stale admission's transaction, so it was not written.
    assert rig.progress.row(rig.path, "deal")["step"] == "commit"
    assert rig.site.rows["res-1"]["state"] == "released"


async def test_an_unknown_authorization_outcome_stays_pending_and_resolves_the_same_authorization(rig):
    rig.adapter.answers["dispatch"] = ["pending"]
    pending = await rig.drive()
    assert pending.kind is OutcomeKind.PENDING and rig.fulfillment.begins == []
    [unresolved] = authorizations(rig, "dispatch")
    assert unresolved.state == "pending"
    resumed = await rig.drive()
    assert resumed.fulfillment_id == "ful-1"
    [resolved] = authorizations(rig, "dispatch")
    assert resolved.intent_ref == unresolved.intent_ref and resolved.state == "done"


async def test_dispatch_is_recorded_before_fulfillment_begins(rig):
    seen = []
    begin = rig.fulfillment.begin_fulfillment

    async def observe(body, *, site_id):
        seen.append(rig.progress.row(rig.path, "deal")["step"])
        return await begin(body, site_id=site_id)

    rig.fulfillment.begin_fulfillment = observe
    await rig.drive()
    assert seen == ["dispatch"]
    assert rig.progress.row(rig.path, "deal")["fulfillment"] == "ful-1"


async def test_a_lost_dispatch_acknowledgement_repeats_the_same_request_for_the_same_fulfillment(rig):
    rig.fulfillment.lose_begin = 1
    with pytest.raises(ConnectionError):
        await rig.drive()
    assert rig.progress.row(rig.path, "deal")["step"] == "dispatch"
    recovered = await rig.drive()
    assert recovered.fulfillment_id == "ful-1"
    assert len(rig.fulfillment.begins) == 2 and len(rig.fulfillment.by_reservation) == 1
    assert rig.fulfillment.begins[0] == rig.fulfillment.begins[1]


async def test_a_worker_resuming_after_dispatch_polls_the_recorded_fulfillment(rig):
    rig.fulfillment.state = "dispatching"
    first = await rig.drive()
    assert first.kind is OutcomeKind.PENDING and first.fulfillment_id == "ful-1"
    resumed = await rig.drive()
    assert resumed.kind is OutcomeKind.PENDING and resumed.fulfillment_id == "ful-1"
    assert len(rig.fulfillment.begins) == 1
    assert rig.site.calls.count("reserve") == 1


async def test_a_fulfillment_request_for_another_reservation_is_refused_before_dispatch(rig):
    rig.domain.request_reservation = "res-other"
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert rig.fulfillment.begins == [] and rig.progress.row(rig.path, "deal")["step"] == "commit"


async def test_a_dispatch_acknowledged_for_another_reservation_is_site_unanswered(rig):
    begin = rig.fulfillment.begin_fulfillment

    async def misrouted(body, *, site_id):
        accepted = await begin(body, site_id=site_id)
        return accepted.model_copy(update={"capacity_reservation_id": "res-other"})

    rig.fulfillment.begin_fulfillment = misrouted
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.evidence_ref == "reservation:res-1"
    assert rig.progress.row(rig.path, "deal")["step"] == "dispatch"
    assert rig.progress.row(rig.path, "deal")["fulfillment"] is None


async def test_an_empty_fulfillment_result_is_repair_required_and_nothing_replaces_it(rig):
    rig.fulfillment.state = "dispatching"
    await rig.drive()
    rig.fulfillment.state = "active"
    rig.fulfillment.result = {}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert outcome.fulfillment_id == "ful-1" and outcome.evidence_ref == "fulfillment:ful-1"
    assert len(rig.fulfillment.begins) == 1
    assert rig.record().available_at is None


async def test_a_result_showing_no_ready_evidence_is_repair_required(rig):
    rig.domain.ready = None
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert len(rig.fulfillment.begins) == 1
