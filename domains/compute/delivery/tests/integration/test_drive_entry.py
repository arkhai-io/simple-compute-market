"""``drive`` fails closed on what it cannot read, writing nothing and placing nothing.

Library integration: the path over the real servicing journal on SQLite, with
port fakes and a fake site and provisioning service.
"""

import pytest
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

from compute_delivery import AcceptedDeal, OutcomeKind, RepairReason


async def test_a_deal_that_was_never_accepted_is_repair_required_and_nothing_is_written(rig):
    outcome = await rig.delivery.drive("never-accepted")
    assert outcome.kind is OutcomeKind.REPAIR_REQUIRED
    assert outcome.reason is RepairReason.NO_ACCEPTED_DEAL
    assert outcome.evidence_ref == "servicing_delivery:never-accepted"
    assert rig.progress.row(rig.path, "never-accepted") is None
    assert rig.site.calls == [] and rig.fulfillment.begins == []


async def test_a_deal_without_verified_settlement_is_repair_required_and_nothing_is_written(rig):
    rig.domain.accepted = None
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    assert outcome.evidence_ref == "settlement:deal"
    assert rig.progress.row(rig.path, "deal") is None and rig.site.calls == []
    with rig.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM servicing_intents").fetchone()[0] == 0


async def test_settlement_naming_another_commitment_is_not_this_deal(rig):
    rig.domain.accepted = AcceptedDeal(
        commitment_ref="another", binding=rig.domain.accepted.binding, payment=rig.domain.accepted.payment,
    )
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    assert rig.progress.row(rig.path, "deal") is None


async def test_a_domain_answer_of_the_wrong_kind_is_repair_required(rig):
    rig.domain.accepted = {"commitment_ref": "commitment"}
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert rig.progress.row(rig.path, "deal") is None


async def test_recovery_lacking_timing_keeps_its_resource_and_guesses_nothing(rig):
    rig.progress.write(rig.path, "deal", step="commit", reservation="res-9")
    with transaction(rig.path) as conn:
        conn.execute("UPDATE servicing_delivery SET record=json_remove(record, '$.start_at')")
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.TIMING_INVALID)
    assert outcome.capacity_reservation_id == "res-9"
    assert outcome.evidence_ref == "servicing_delivery:deal" and "start_at field required" in outcome.detail
    assert rig.site.calls == [] and rig.fulfillment.begins == []
    assert rig.progress.row(rig.path, "deal")["reservation"] == "res-9"


async def test_an_empty_accepted_term_is_timing_invalid(rig):
    with transaction(rig.path) as conn:
        conn.execute(
            "UPDATE servicing_delivery SET record=json_set(record, '$.term_end', json_extract(record, '$.start_at'))"
        )
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.TIMING_INVALID)
    assert rig.site.calls == []


async def test_a_progress_row_with_an_unknown_step_begins_nothing(rig):
    rig.progress.write(rig.path, "deal", step="provisioning", reservation="res-1")
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.PROGRESS_UNREADABLE)
    assert outcome.capacity_reservation_id == "res-1"
    assert outcome.evidence_ref == "delivery_progress:deal"
    assert rig.site.calls == [] and rig.fulfillment.begins == []


async def test_a_progress_row_disagreeing_with_itself_begins_nothing(rig):
    rig.progress.write(rig.path, "deal", step="fulfillment", reservation="res-1")
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.PROGRESS_UNREADABLE)
    assert rig.site.calls == [] and rig.fulfillment.begins == []


@pytest.mark.parametrize("port", ["claim", "hold"])
async def test_a_reserve_claim_or_hold_of_the_wrong_kind_places_nothing(rig, port):
    setattr(rig.domain, port, {"capacity_reservation_id": "res-1"})
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.DOMAIN_RESULT_INVALID)
    assert "reserve" not in rig.site.calls and "commit" not in rig.site.calls


async def test_a_servicing_record_unreadable_beyond_its_timing_is_no_accepted_deal(rig):
    with transaction(rig.path) as conn:
        conn.execute("UPDATE servicing_delivery SET record=json_remove(record, '$.seller')")
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    assert rig.site.calls == []


async def test_a_commitment_the_payment_adapter_refuses_is_not_an_accepted_deal(rig):
    rig.commitment_valid[0] = False
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    assert outcome.detail == "invalid commitment evidence"
    with rig.session() as conn:
        [authorization] = [
            intent for intent in EndSession(conn).intents("deal") if intent.kind == "authorization"
        ]
    assert outcome.evidence_ref == authorization.intent_ref
    assert rig.site.calls == []


async def test_a_mechanism_with_no_adapter_is_never_allowed(rig):
    rig.domain.accepted = AcceptedDeal(
        commitment_ref="commitment", binding=rig.domain.accepted.binding, payment=None,
    )
    outcome = await rig.drive()
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REPAIR_REQUIRED, RepairReason.NO_ACCEPTED_DEAL)
    assert "no delivery adapter" in outcome.detail
    assert rig.site.calls == []
