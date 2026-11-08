import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle.delivery import (
    ActivatedDeliveryRef, BillingStartResult, DeliveryAuthorization, DeliveryEvidence, DeliveryPhase,
)
from market_deal_lifecycle_contracts.models import Accepted, Unknown
from market_deal_servicing import (
    Classification, EndService, EndSession, FinalRequest, PhysicalResult,
)
from market_deal_servicing.evidence import transaction


def end_request(rig, *, at=150, ref="ruling"):
    return FinalRequest(
        negotiation_id="deal", source_ref=ref, actor=rig["authority_signer"].identity,
        cause="ruling", source="dispute-record", ended_at=at, observed_at=150,
        evidence_refs=["verified-ruling"],
    )


def record_end(rig, request=None):
    with transaction(rig["path"]) as conn:
        request = request or end_request(rig)
        EndSession(conn).record_end(request, now=150, classification=Classification(
            kind="ruling", evidence_refs=request.evidence_refs,
        ))


@pytest.mark.parametrize("dispatched", [False, True])
async def test_end_survives_restart_before_lease_or_overlapping_dispatch(rig, dispatched):
    if dispatched:
        with transaction(rig["path"]) as conn:
            assert EndSession(conn).admit("deal", DeliveryPhase.DISPATCH, 0, now=150).status == "admitted"
    record_end(rig)
    rig["physical"].apply_end.return_value = PhysicalResult(
        done=True, progress="tearing_down" if dispatched else "released",
    )
    service = EndService(rig["path"], rig["physical"], clock=lambda: 150)
    await service.drive_physical("deal")
    await service.drive_physical("deal")
    record_end(rig, end_request(rig, at=140, ref="late-earlier-report"))
    await service.drive_physical("deal")
    assert rig["physical"].apply_end.await_count == 1
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        assert session.selected_end("deal").ended_at == 140
        assert session.admit("deal", DeliveryPhase.ACTIVATE, session.read("deal").revision, now=150).status == "ended"
        assert len(session.requests("deal")) == 2


async def test_authorization_holds_no_write_lock_and_rechecks_revision(rig):
    entered, release = asyncio.Event(), asyncio.Event()
    loop_thread = threading.get_ident()
    callback_threads = []

    async def authorize(*_):
        entered.set()
        await release.wait()
        return DeliveryAuthorization(status="allow", reason="verified", operation_id="authorize", evidence_refs=["commitment"])

    adapter = AsyncMock()
    adapter.authorize.side_effect = authorize
    task = asyncio.create_task(rig["end"].authorize_delivery(
        DeliveryPhase.DISPATCH, DeliveryEvidence(negotiation_id="deal", commitment_ref="commitment"),
        adapter=adapter, expected_revision=0,
        apply=lambda *_: callback_threads.append(threading.get_ident()),
    ))
    await entered.wait()
    # Independent session can write while financial I/O is deliberately suspended.
    await asyncio.wait_for(asyncio.to_thread(record_end, rig), timeout=2)
    release.set()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.status != "allow" and not callback_threads
    # With no concurrent end, the protected write itself is off-loop.
    with transaction(rig["path"]) as conn:
        conn.execute("DELETE FROM servicing_final_requests")
        revision = EndSession(conn).read("deal").revision
    result = await rig["end"].authorize_delivery(
        DeliveryPhase.DISPATCH, DeliveryEvidence(negotiation_id="deal", commitment_ref="commitment"),
        adapter=adapter, expected_revision=revision,
        apply=lambda *_: callback_threads.append(threading.get_ident()),
    )
    assert result.status == "allow" and callback_threads[0] != loop_thread


async def test_billing_intent_precedes_io_and_same_key_recovers_unknown(rig):
    evidence = DeliveryEvidence(
        negotiation_id="deal", commitment_ref="commitment",
        activated_delivery=ActivatedDeliveryRef(record_ref="activated", activated_at=140),
    )
    adapter = AsyncMock()
    keys = []

    async def start(key, received):
        assert received == evidence
        with transaction(rig["path"]) as conn:
            intents = [item for item in EndSession(conn).intents("deal") if item.kind == "billing"]
        assert len(intents) == 1 and intents[0].operation_key == key
        keys.append(key)
        return BillingStartResult(outcome=Unknown(reason="lost") if len(keys) == 1 else Accepted())

    adapter.start_billing.side_effect = start
    first = await rig["end"].begin_billing("start", evidence, adapter=adapter)
    record_end(rig)
    restarted = EndService(rig["path"], rig["physical"], clock=lambda: 150)
    recovered = await restarted.begin_billing("start", evidence, adapter=adapter)
    assert first.intent_ref == recovered.intent_ref and keys == ["start", "start"]
    assert isinstance(recovered.result.outcome, Accepted)
    refused = await restarted.begin_billing("changed", evidence, adapter=adapter)
    assert refused.result.outcome.status == "rejected"


async def test_billing_start_without_activation_evidence_is_refused_before_any_authority_call(rig):
    adapter = AsyncMock()
    refused = await rig["end"].begin_billing(
        "start", DeliveryEvidence(negotiation_id="deal", commitment_ref="commitment"), adapter=adapter,
    )
    assert refused.result.outcome.status == "rejected"
    adapter.start_billing.assert_not_called()
    with transaction(rig["path"]) as conn:
        assert [item for item in EndSession(conn).intents("deal") if item.kind == "billing"] == []


def test_deadline_failure_and_pending_correction_are_atomic(rig):
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        record = session.read("deal").model_copy(update={"delivery_deadline_seconds": 20})
        conn.execute("UPDATE servicing_delivery SET record=? WHERE negotiation_id='deal'", (record.model_dump_json(),))
        assert session.admit("deal", DeliveryPhase.ACTIVATE, 0, now=150).status == "ended"
        assert session.selected_end("deal").ended_at == 120
        assert next(item for item in session.intents("deal") if item.kind == "filing").payload["payload"]["ended_at"] == 100
        pending = end_request(rig, at=110, ref="unclassified-site")
        session.record_end(pending, now=150, pending_classification=True)
        revision = session.read("deal").revision
        filing = session.failure_filing(pending, now=150, delivered=False)
        assert session.resolve_correction(
            "deal", pending.source_ref, revision - 1, evidence=["site"],
            classification=Classification(kind="non_delivery", evidence_refs=["site"]), filing_intent=filing,
        ).status == "retry"
        assert session.resolve_correction(
            "deal", pending.source_ref, revision, evidence=["site"],
            classification=Classification(kind="non_delivery", evidence_refs=["site"]), filing_intent=filing,
        ).status == "admitted"
