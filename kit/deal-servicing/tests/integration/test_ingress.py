import asyncio

import pytest
from market_deal_servicing import Classification, DeliveryIngress, EndSession, FinalRequest, PhysicalResult, VerifiedSiteEnd
from market_deal_servicing.evidence import transaction


async def test_duplicate_earlier_site_report_preserves_bytes_and_does_not_restart_teardown(rig):
    rig["physical"].apply_end.return_value = PhysicalResult(done=True, progress="tearing_down")
    event = [VerifiedSiteEnd(
        event_id="site", capacity_reservation_id="reservation", ended_at=140,
        actor=rig["authority_signer"].identity, cause="failure",
    )]
    ingress = DeliveryIngress(
        rig["path"], clock=lambda: rig["clock"][0], verify_site=lambda *_: event[0],
        classify_site=lambda *_: Classification(kind="provisioning_failure", evidence_refs=["site"]),
    )
    body = b'{"site":"exact signed fixture bytes", "proof": "development-only"}'
    first = await asyncio.to_thread(ingress.site_report, "deal", body=body, headers={"proof": "original"})
    await rig["end"].drive_physical("deal")
    rig["clock"][0] += 10
    second = await asyncio.to_thread(ingress.site_report, "deal", body=body, headers={"proof": "refreshed"})
    await rig["end"].drive_physical("deal")
    assert first.recorded_end == second.recorded_end
    event[0] = event[0].model_copy(update={"event_id": "earlier-site", "ended_at": 130})
    await asyncio.to_thread(ingress.site_report, "deal", body=b'{"earlier":true}', headers={})
    await rig["end"].drive_physical("deal")
    assert rig["physical"].apply_end.await_count == 1
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert len(end.requests("deal")) == 2
        assert end.view("deal").recorded_end.ended_at == 130
        assert end.view("deal").site_reports[0].body == body
        assert end.view("deal").site_reports[0].headers == {"proof": "original"}
        assert len([item for item in end.intents("deal") if item.kind == "filing"]) == 2
    rig["payment"].submit.assert_not_called()


def test_end_and_filing_roll_back_together_and_equal_time_selection_is_stable(rig):
    with pytest.raises(RuntimeError, match="crash"):
        with transaction(rig["path"]) as conn:
            end = EndSession(conn)
            request = FinalRequest(
                negotiation_id="deal", source_ref="failure", ended_at=150, observed_at=150,
                actor=rig["seller"].identity, cause="seller_failure", source="local",
            )
            end.record_end(
                request, now=150, classification=Classification(kind="provisioning_failure", evidence_refs=["failure"]),
                filing_intent=end.failure_filing(request, now=150, delivered=False),
            )
            raise RuntimeError("crash")
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert end.requests("deal") == [] and end.intents("deal") == []
        for ref in ("z", "a"):
            end.record_end(request.model_copy(update={"source_ref": ref}), now=150,
                           classification=Classification(kind="ruling", evidence_refs=["ruling"]))
        chosen = end.selected_end("deal")
    with transaction(rig["path"]) as conn:
        assert EndSession(conn).selected_end("deal") == chosen
        assert len(EndSession(conn).requests("deal")) == 2


async def test_future_start_failure_defers_exact_filing_across_restart(rig):
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        record = end.read("deal").model_copy(update={"start_at": 200})
        conn.execute("UPDATE servicing_delivery SET record=? WHERE negotiation_id='deal'", (record.model_dump_json(),))
    ingress = DeliveryIngress(
        rig["path"], clock=lambda: 150, verify_site=lambda *_: VerifiedSiteEnd(
            event_id="before-start", capacity_reservation_id="reservation", ended_at=140,
            actor=rig["authority_signer"].identity, cause="failure",
        ), classify_site=lambda *_: Classification(kind="provisioning_failure", evidence_refs=["site"]),
    )
    await asyncio.to_thread(ingress.site_report, "deal", body=b'{"failure":true}', headers={})
    with transaction(rig["path"]) as conn:
        intent = next(item for item in EndSession(conn).intents("deal") if item.kind == "filing")
        assert intent.not_before == intent.payload["payload"]["ended_at"] == 200
    result = await rig["service"]().dispatch_filings("deal")
    assert [(item.intent_ref, item.outcome.status) for item in result] == [(intent.intent_ref, "pending")]
    rig["dispute"].submit.assert_not_called()
