"""Access material is disclosed only through a live, admitted read.

Library integration: ``read_access`` over the real servicing journal on SQLite,
after the path delivered the deal through port fakes.
"""

import pytest
from market_deal_servicing import Classification, EndSession, FinalRequest
from market_identity import Ed25519Signer

from compute_delivery import AccessRefused, OutcomeKind

# Public deterministic development seed; never use on a public network.
BUYER = Ed25519Signer(bytes([1]) * 32)


def record_buyer_end(rig):
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0], observed_at=rig.clock[0],
            actor=BUYER.identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))


class Fetch:
    def __init__(self, during=None):
        self.calls = []
        self.during = during

    async def __call__(self, fulfillment_id, capacity_reservation_id):
        self.calls.append((fulfillment_id, capacity_reservation_id))
        if self.during is not None:
            self.during()
        return {"host": "vm-1.example", "port": 22, "user": "tenant"}


async def delivered(rig):
    outcome = await rig.drive()
    assert outcome.kind is OutcomeKind.CONVERGED
    rig.adapter.calls.clear()
    rig.validations.clear()


async def test_an_available_deal_reads_its_access_live_without_a_payment_snapshot(rig):
    await delivered(rig)
    fetch = Fetch()
    material = await rig.delivery.read_access("deal", fetch)
    assert material == {"host": "vm-1.example", "port": 22, "user": "tenant"}
    assert fetch.calls == [("ful-1", "res-1")]
    assert rig.adapter.calls == [] and rig.validations == []


async def test_a_future_truncation_recorded_during_the_fetch_still_discloses(rig):
    await delivered(rig)

    def truncate():
        with rig.session() as conn:
            EndSession(conn).record_end(FinalRequest(
                negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0] + 600,
                observed_at=rig.clock[0], actor=BUYER.identity, cause="buyer_surrender", source="buyer",
                evidence_refs=["buyer-end"],
            ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))

    material = await rig.delivery.read_access("deal", Fetch(during=truncate))
    assert material["host"] == "vm-1.example"


async def test_an_end_recorded_earlier_falling_due_during_the_fetch_discards_what_was_fetched(rig):
    await delivered(rig)
    with rig.session() as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="buyer-end", ended_at=rig.clock[0] + 10,
            observed_at=rig.clock[0], actor=BUYER.identity, cause="buyer_surrender", source="buyer",
            evidence_refs=["buyer-end"],
        ), now=rig.clock[0], classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))

    def time_passes():
        rig.clock[0] += 20

    fetch = Fetch(during=time_passes)
    with pytest.raises(AccessRefused) as refused:
        await rig.delivery.read_access("deal", fetch)
    assert refused.value.reason == "ended" and len(fetch.calls) == 1


async def test_a_deal_not_yet_available_discloses_nothing(rig):
    rig.fulfillment.state = "dispatching"
    await rig.drive()
    fetch = Fetch()
    with pytest.raises(AccessRefused) as refused:
        await rig.delivery.read_access("deal", fetch)
    assert refused.value.reason == "not_available" and fetch.calls == []


async def test_a_deal_before_its_agreement_start_discloses_nothing(rig):
    await delivered(rig)
    rig.clock[0] = rig.start - 1
    fetch = Fetch()
    with pytest.raises(AccessRefused) as refused:
        await rig.delivery.read_access("deal", fetch)
    assert refused.value.reason == "not_started" and fetch.calls == []


async def test_an_end_admitted_during_the_fetch_discards_what_was_fetched(rig):
    await delivered(rig)
    fetch = Fetch(during=lambda: record_buyer_end(rig))
    with pytest.raises(AccessRefused) as refused:
        await rig.delivery.read_access("deal", fetch)
    assert refused.value.reason == "ended" and len(fetch.calls) == 1


async def test_a_read_repeated_after_an_end_runs_again_and_is_refused(rig):
    await delivered(rig)
    first = await rig.delivery.read_access("deal", Fetch())
    assert first["host"] == "vm-1.example"
    record_buyer_end(rig)
    fetch = Fetch()
    with pytest.raises(AccessRefused) as refused:
        await rig.delivery.read_access("deal", fetch)
    assert refused.value.reason == "ended" and fetch.calls == []
