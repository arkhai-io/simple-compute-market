"""The watch records a part's final stop once, by authority record, outside its cursor."""

from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent, PaymentPartObservation

from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction


def stop(kind="stop", at=140, sequence=1):
    return PaymentEvent(
        negotiation_id="deal", commitment_ref="commitment", part="1", kind=kind, actor="payer-account",
        at=at, cause="payer", sequence=sequence, authority_record_ref="commitment:events:1:part:1",
        settles_through="started_period",
    )


def view(*, pending=None, final=None, events=()):
    return AuthorityView(outcome=Accepted(), state="ended" if final else "ending", events=list(events), parts=[
        PaymentPartObservation(part="1", pending_stop=pending, final_stop=final, evidence_ref="snapshot"),
    ])


def requests(rig):
    with transaction(rig["path"]) as conn:
        return EndSession(conn).requests("deal")


async def test_a_pending_stop_request_never_records_an_end(rig):
    request = stop(kind="stop_request")
    rig["payment"].read.return_value = view(pending=request, events=[request])
    await rig["watch"]().poll()
    assert requests(rig) == []


async def test_a_stop_maturing_without_a_new_sequence_is_recorded_once(rig):
    # The request's event was consumed by an earlier poll; the maturity carries
    # no new sequence, so only the part's final stop shows the end.
    request = stop(kind="stop_request")
    rig["payment"].read.return_value = view(pending=request, events=[request])
    await rig["watch"]().poll()
    rig["payment"].read.return_value = view(final=stop(), events=[request])
    await rig["watch"]().poll()
    await rig["watch"]().poll()
    recorded = requests(rig)
    assert len(recorded) == 1
    assert (recorded[0].ended_at, recorded[0].source) == (140, "commitment:events:1:part:1")


async def test_a_replay_changing_the_recorded_stop_is_refused(rig):
    rig["payment"].read.return_value = view(final=stop())
    await rig["watch"]().poll()
    rig["payment"].read.return_value = view(final=stop(at=145))
    views, _ = await rig["watch"]().poll()
    assert views[0].outcome.status == "rejected" and "changes its recorded end" in views[0].outcome.reason
    assert [item.ended_at for item in requests(rig)] == [140]
