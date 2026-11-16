"""The watch records a part's final stop once, by authority record, outside its cursor."""

import json

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


#: Names a journal would use for money the neutral loop must never keep.
MONEY = ("amount", "balance", "funded", "owed", "gross", "reserved")


def keys(value):
    """Every key anywhere in a decoded JSON value."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


async def test_the_journal_holds_the_stop_and_the_selected_end_and_no_money(rig):
    # The authority's view carries money: a collection and a funded boundary.
    collect = PaymentEvent(
        negotiation_id="deal", commitment_ref="commitment", part="1", kind="collect", actor="payee-account",
        at=120, amount="250000", cause="period", sequence=1, authority_record_ref="commitment:events:0:part:1",
    )
    final = stop(sequence=2)
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), state="ended", events=[collect, final], parts=[
        PaymentPartObservation(part="1", started_at=100, funded_through=200, final_stop=final, evidence_ref="snapshot"),
    ])
    await rig["watch"]().poll()

    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        [recorded] = end.requests("deal")
        assert (recorded.source_ref, recorded.ended_at) == ("payment-stop:commitment:events:1:part:1", 140)
        assert end.selected_end("deal") == recorded
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'servicing_%'")]
        columns = {column[1] for table in tables for column in conn.execute(f"PRAGMA table_info({table})")}
        journaled = [json.loads(row[0]) for row in conn.execute(
            "SELECT request FROM servicing_final_requests UNION ALL SELECT intent FROM servicing_intents "
            "UNION ALL SELECT record FROM servicing_delivery")]
    assert not [name for name in columns if any(word in name for word in MONEY)], columns
    assert not [key for key in set().union(*map(keys, journaled)) if any(word in key for word in MONEY)]


async def test_a_replay_changing_the_recorded_stop_is_refused(rig):
    rig["payment"].read.return_value = view(final=stop())
    await rig["watch"]().poll()
    rig["payment"].read.return_value = view(final=stop(at=145))
    views, _ = await rig["watch"]().poll()
    assert views[0].outcome.status == "rejected" and "changes its recorded end" in views[0].outcome.reason
    assert [item.ended_at for item in requests(rig)] == [140]
