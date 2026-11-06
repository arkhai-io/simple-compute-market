"""Commit holds the Agreement window under the deal's one reservation.

Library integration: the path over the real servicing journal on SQLite, with
port fakes and a fake site whose acknowledgements can be lost after their
effect.
"""

import json

import pytest
from market_deal_lifecycle.delivery import DeliveryPhase
from market_deal_servicing import Classification, EndSession, EvidenceSession, FinalRequest
from market_identity import Ed25519Signer
from market_site_client import SiteCapacityClientError, SiteCapacityUnauthenticatedResponseError

from compute_delivery import AcceptedHold, HoldPlacement, OutcomeKind, RepairReason
from compute_delivery.window import utc_seconds, utc_text

# Public deterministic development seed; never use on a public network.
BUYER = Ed25519Signer(bytes([1]) * 32)


def window_of(rig, reservation_id):
    row = rig.site.rows[reservation_id]
    return utc_seconds(row["lease_start_utc"]), utc_seconds(row["lease_end_utc"])


def record_buyer_end(rig):
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0], observed_at=rig.clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))


def end_requests(rig):
    with rig.session() as conn:
        session = EndSession(conn)
        return session.requests("deal"), session.intents("deal")


async def place_hold(rig, *, keyed=True, ttl=600):
    claim = dict(rig.domain.claim.claim)
    placement = HoldPlacement(claim=claim, ttl_seconds=ttl, lease_duration_seconds=7200)
    deal_ref = {"negotiation_id": "deal"}
    if keyed:
        deal_ref["placement_key"] = "deal:hold"
    held = await rig.site.reserve(claim=claim, deal_ref=deal_ref, ttl_seconds=ttl, lease_duration_seconds=7200)
    rig.site.calls.clear()
    rig.domain.hold = AcceptedHold(
        capacity_reservation_id=held["capacity_reservation_id"],
        placement=placement if keyed else None,
        expires_at=None if keyed else rig.clock[0] + ttl,
    )
    return held["capacity_reservation_id"]


async def test_late_settlement_commits_the_agreement_window_on_the_first_attempt_and_every_retry(rig):
    rig.clock[0] = rig.start + 1800
    rig.site.lose["commit"] = 1
    first = await rig.drive()
    assert first.kind is OutcomeKind.PENDING and first.capacity_reservation_id == "res-1"
    assert window_of(rig, "res-1") == (rig.start, rig.start + 7200)
    second = await rig.drive()
    assert second.kind is OutcomeKind.CONVERGED and second.fulfillment_id == "ful-1"
    assert window_of(rig, "res-1") == (rig.start, rig.start + 7200)
    assert len(rig.site.rows) == 1
    # Every attempt asked for the Agreement window, not the time it was made.
    assert len(rig.site.commits) == 2
    assert {(utc_seconds(start), utc_seconds(end)) for _, start, end in rig.site.commits} == {
        (rig.start, rig.start + 7200),
    }
    payload = rig.fulfillment.begins[0].fulfillment_request.payload
    assert (utc_seconds(payload["lease_start_utc"]), utc_seconds(payload["lease_end_utc"])) == (
        rig.start, rig.start + 7200,
    )


async def test_a_forward_reservation_commits_at_settlement_and_waits_for_its_start(rig):
    rig.clock[0] = rig.start - 7200
    waiting = await rig.drive()
    assert waiting.kind is OutcomeKind.WAITING and waiting.wake_at == rig.start
    assert waiting.capacity_reservation_id == "res-1"
    assert rig.site.rows["res-1"]["state"] == "leased"
    assert window_of(rig, "res-1") == (rig.start, rig.start + 7200)
    assert rig.fulfillment.begins == []
    assert rig.progress.row(rig.path, "deal")["claim_owner"] is None
    again = await rig.drive()
    assert again.kind is OutcomeKind.WAITING and rig.fulfillment.begins == []
    rig.clock[0] = rig.start
    started = await rig.drive()
    assert started.kind is OutcomeKind.CONVERGED and len(rig.fulfillment.begins) == 1
    assert len(rig.site.rows) == 1


async def test_an_end_recorded_while_a_deal_waits_stops_it_before_dispatch(rig):
    rig.clock[0] = rig.start - 7200
    assert (await rig.drive()).kind is OutcomeKind.WAITING
    rig.clock[0] = rig.start - 3600
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0], observed_at=rig.clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))
    rig.clock[0] = rig.start
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert ended.hook_disposition == "failed"
    assert rig.fulfillment.begins == []
    assert rig.site.rows["res-1"]["state"] == "released"


async def test_a_lost_reserve_acknowledgement_replays_the_same_reservation(rig):
    rig.site.lose["reserve"] = 1
    lost = await rig.drive()
    assert lost.kind is OutcomeKind.PENDING and lost.capacity_reservation_id is None
    assert rig.progress.row(rig.path, "deal")["reservation"] is None
    recovered = await rig.drive()
    assert recovered.capacity_reservation_id == "res-1" and recovered.fulfillment_id == "ful-1"
    assert len(rig.site.rows) == 1
    assert rig.site.rows["res-1"]["deal_ref"]["placement_key"] == "deal:settlement"


async def test_a_recovered_reservation_that_was_released_is_never_replaced(rig):
    rig.site.lose["reserve"] = 1
    assert (await rig.drive()).kind is OutcomeKind.PENDING
    rig.site.rows["res-1"]["state"] = "released"
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.capacity_reservation_id == "res-1"
    assert len(rig.site.rows) == 1 and rig.fulfillment.begins == []
    requests, intents = end_requests(rig)
    assert [request.source_ref for request in requests] == ["delivery:reservation-released:res-1"]
    assert [intent.kind for intent in intents if intent.kind == "filing"] == ["filing"]


async def test_a_live_hold_is_committed_and_no_second_reservation_is_placed(rig):
    hold = await place_hold(rig)
    outcome = await rig.drive()
    assert outcome.capacity_reservation_id == hold and outcome.fulfillment_id == "ful-1"
    assert "reserve" not in rig.site.calls and len(rig.site.rows) == 1
    assert window_of(rig, hold) == (rig.start, rig.start + 7200)
    assert rig.progress.row(rig.path, "deal")["reservation"] == hold


async def test_a_hold_commit_whose_answer_is_lost_is_retried_never_replaced(rig):
    hold = await place_hold(rig)
    rig.site.lose["commit"] = 1
    lost = await rig.drive()
    assert lost.kind is OutcomeKind.PENDING and lost.capacity_reservation_id == hold
    assert rig.progress.row(rig.path, "deal")["reservation"] is None
    adopted = await rig.drive()
    assert adopted.capacity_reservation_id == hold
    assert "reserve" not in rig.site.calls and len(rig.site.rows) == 1


async def test_a_hold_verified_lapsed_by_its_replay_is_replaced_under_settlement(rig):
    hold = await place_hold(rig)
    rig.site.expire(hold)
    outcome = await rig.drive()
    assert outcome.capacity_reservation_id == "res-2" and outcome.fulfillment_id == "ful-1"
    assert rig.site.rows["res-2"]["deal_ref"]["placement_key"] == "deal:settlement"
    assert rig.site.rows[hold]["state"] == "released"


async def test_a_keyless_hold_past_its_recorded_expiry_is_replaced_under_settlement(rig):
    hold = await place_hold(rig, keyed=False, ttl=60)
    rig.site.expire(hold)
    rig.clock[0] += 120
    outcome = await rig.drive()
    assert outcome.capacity_reservation_id == "res-2"


@pytest.mark.parametrize("recorded_expiry", [True, False])
async def test_a_refused_commit_of_a_live_hold_is_a_seller_failure(rig, recorded_expiry):
    hold = await place_hold(rig, keyed=False, ttl=600)
    if not recorded_expiry:
        # A hold placed with no key and no recorded expiry is never verified lapsed.
        rig.domain.hold = AcceptedHold(capacity_reservation_id=hold)
    rig.site.refuse_commit.add(hold)
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.capacity_reservation_id == hold
    assert ended.evidence_ref == f"delivery:commit-refused:{hold}"
    assert len(rig.site.rows) == 1 and rig.site.rows[hold]["state"] == "released"
    assert rig.fulfillment.begins == []


async def test_a_commit_refused_after_reservation_is_a_seller_failure_released_without_dispatch(rig):
    rig.clock[0] = rig.start - 7200
    rig.site.refuse_commit.add("res-1")
    rig.site.lose["release"] = 1
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.capacity_reservation_id == "res-1"
    assert ended.evidence_ref == "delivery:commit-refused:res-1"
    requests, intents = end_requests(rig)
    with rig.session() as conn:
        classification = conn.execute(
            "SELECT classification FROM servicing_final_requests WHERE source_ref=?",
            ("delivery:commit-refused:res-1",),
        ).fetchone()[0]
    assert Classification.model_validate_json(classification).kind == "start_failure"
    with rig.session() as conn:
        [item] = [
            item for item in EvidenceSession(conn).read("deal").items
            if item.evidence_id == "delivery:commit-refused:res-1"
        ]
    assert item.classification == "seller_assertion" and item.kind == "delivery_commit_refused"
    assert json.loads(item.body)["status_code"] == 409
    filing = next(intent for intent in intents if intent.kind == "filing")
    # Journaled now; it acts no earlier than the Agreement start.
    assert filing.not_before == rig.start
    assert filing.payload["payload"] == {"kind": "delivery_end", "ended_at": rig.start,
                                         "delivered": False, "cause": "payee"}
    terminate = next(intent for intent in intents if intent.kind == "terminate")
    assert terminate.state == "pending"
    assert rig.site.rows["res-1"]["state"] == "released"
    # A restart before the release acknowledgement retries the same release.
    again = await rig.drive()
    assert again.kind is OutcomeKind.ENDED
    assert len(rig.site.rows) == 1 and rig.fulfillment.begins == []
    assert [key for _, key in rig.site.releases] == [terminate.intent_ref, terminate.intent_ref]
    _, intents = end_requests(rig)
    assert next(intent for intent in intents if intent.kind == "terminate").state == "done"


async def test_a_settlement_placement_that_finds_no_capacity_is_a_seller_failure(rig):
    rig.site.capacity = False
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.capacity_reservation_id is None
    assert ended.evidence_ref == "delivery:no-capacity:deal"
    assert rig.site.rows == {}


@pytest.mark.parametrize("answer", [
    SiteCapacityUnauthenticatedResponseError("unsigned", status_code=404),
    SiteCapacityClientError("site error", status_code=500),
])
async def test_an_unsigned_or_failed_commit_answer_is_retried_on_the_same_reservation(rig, answer):
    rig.site.refuse_first["commit"] = answer
    unanswered = await rig.drive()
    assert unanswered.kind is OutcomeKind.PENDING and unanswered.capacity_reservation_id == "res-1"
    retried = await rig.drive()
    assert retried.fulfillment_id == "ful-1" and len(rig.site.rows) == 1
    assert [reservation for reservation, _, _ in rig.site.commits] == ["res-1", "res-1"]


@pytest.mark.parametrize("status", [404, 409])
async def test_a_refused_settlement_placement_is_a_seller_failure_with_nothing_held(rig, status):
    rig.site.refuse_first["reserve"] = SiteCapacityClientError("refused", status_code=status)
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.capacity_reservation_id is None
    assert ended.evidence_ref == "delivery:reserve-refused:deal"
    assert rig.site.rows == {} and rig.fulfillment.begins == []


async def test_a_reserve_answer_naming_no_reservation_is_site_unanswered(rig):
    rig.site.rewrite["reserve"] = {"capacity_reservation_id": None}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.evidence_ref == "reserve_claim:deal"
    assert rig.progress.row(rig.path, "deal")["reservation"] is None


async def test_a_commit_answer_naming_another_reservation_is_site_unanswered(rig):
    rig.site.rewrite["commit"] = {"capacity_reservation_id": "res-other"}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.SITE_UNANSWERED)
    assert outcome.capacity_reservation_id == "res-1" and outcome.evidence_ref == "reservation:res-1"
    assert rig.fulfillment.begins == []


async def test_a_lease_committed_under_other_timing_is_timing_invalid_and_kept(rig):
    rig.site.rewrite["commit"] = {"lease_start_utc": utc_text(rig.clock[0])}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.TIMING_INVALID)
    assert outcome.capacity_reservation_id == "res-1" and outcome.evidence_ref == "reservation:res-1"
    assert rig.fulfillment.begins == [] and len(rig.site.rows) == 1


async def test_a_hold_whose_recorded_placement_the_site_refuses_is_domain_result_invalid(rig):
    hold = await place_hold(rig)
    rig.site.expire(hold)
    placement = rig.domain.hold.placement
    rig.domain.hold = AcceptedHold(
        capacity_reservation_id=hold,
        placement=HoldPlacement(claim=placement.claim, ttl_seconds=600, lease_duration_seconds=3600),
    )
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert outcome.evidence_ref == "accepted_hold:deal"
    assert len(rig.site.rows) == 1 and rig.progress.row(rig.path, "deal")["reservation"] is None


async def test_a_hold_replay_answering_another_reservation_releases_nothing(rig):
    hold = await place_hold(rig, keyed=False)
    rig.site.expire(hold)
    rig.domain.hold = AcceptedHold(
        capacity_reservation_id=hold,
        placement=HoldPlacement(claim=dict(rig.domain.claim.claim), ttl_seconds=600, lease_duration_seconds=7200),
    )
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert "'res-2'" in outcome.detail
    # Whatever the replay answered may be the deal's live hold; it keeps its TTL.
    assert rig.site.rows["res-2"]["state"] == "reserved"
    assert rig.site.rows["res-2"]["hold_expires_at"] is not None
    assert "release" not in rig.site.calls
    assert rig.progress.row(rig.path, "deal")["reservation"] is None


async def test_a_reservation_is_recorded_even_when_an_end_wins_while_it_is_placed(rig):
    rig.site.on_arrival["reserve"] = lambda: record_buyer_end(rig)
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    assert rig.progress.row(rig.path, "deal")["reservation"] == "res-1"
    assert rig.site.rows["res-1"]["state"] == "released" and rig.fulfillment.begins == []


async def test_an_earlier_lawful_end_controls_a_commit_refusal_and_no_self_penalty_is_filed(rig):
    rig.site.on_arrival["commit"] = lambda: record_buyer_end(rig)
    rig.site.refuse_commit.add("res-1")
    ended = await rig.drive()
    assert ended.kind is OutcomeKind.ENDED and ended.evidence_ref == "buyer-end"
    requests, intents = end_requests(rig)
    refused = next(request for request in requests if request.source_ref == "delivery:commit-refused:res-1")
    assert refused.controlling_source_ref == "buyer-end"
    with rig.session() as conn:
        classification = conn.execute(
            "SELECT classification FROM servicing_final_requests WHERE source_ref=?",
            ("delivery:commit-refused:res-1",),
        ).fetchone()[0]
    assert Classification.model_validate_json(classification).kind == "buyer_surrender"
    assert [intent for intent in intents if intent.kind == "filing"] == []
    assert rig.site.rows["res-1"]["state"] == "released"


async def test_commit_is_authorized_before_any_reservation(rig):
    rig.adapter.answers["commit"] = ["pending"]
    pending = await rig.drive()
    assert pending.kind is OutcomeKind.PENDING and rig.site.calls == []
    assert rig.adapter.authorized == [DeliveryPhase.COMMIT.value]
