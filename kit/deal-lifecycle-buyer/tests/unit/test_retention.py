"""Retention is conservative over incomplete or unavailable fresh authority reads."""

import base64
from dataclasses import replace

import pytest
from market_deal_lifecycle.terms import Adjudication
from market_deal_lifecycle_contracts.models import EvidenceItem
from market_deal_lifecycle_buyer import FileEvidenceStore, RetentionObservation, prune_command


TERMS = Adjudication.model_validate({
    "version": 1, "dispute": {"interface": "example.v1", "origin": "https://authority.example",
    "account": "authority", "record_key": "key", "params": {}},
    "dispute_window_seconds": 100, "case_hold_max_seconds": None,
})
ENDED = RetentionObservation(
    adjudication=TERMS, has_adapter=True, committed=True, delivery_ended_at=100,
    physical_recovered_at=120, parts_complete=True, cases_complete=True,
    payouts={"one": 130, "two": 150}, case_closes={"case": 200},
)
ITEM = EvidenceItem(evidence_id="item", kind="signed_response", classification="seller_assertion",
                    recorded_at=10, body=base64.b64encode(b"exact bytes"))


@pytest.mark.asyncio
@pytest.mark.parametrize(("observed", "now", "delete"), [
    (ENDED, 299, False), (ENDED, 300, True),
    (replace(ENDED, delivery_ended_at=None), 10000, False),
    (replace(ENDED, physical_recovered_at=None), 10000, False),
    (replace(ENDED, payouts={"one": 130, "two": None}), 10000, False),
    (replace(ENDED, payouts={}), 10000, False),
    (replace(ENDED, case_closes={"case": None}), 10000, False),
    (replace(ENDED, cases_complete=False), 10000, False),
    (replace(ENDED, parts_complete=False), 10000, False),
    (replace(ENDED, adjudication=None), 10000, False),
    (replace(ENDED, has_adapter=False), 10000, False),
    (replace(ENDED, committed=None), 10000, False),
    (replace(ENDED, committed=False, acceptance_expires_at=500), 599, False),
    (replace(ENDED, committed=False, acceptance_expires_at=500), 600, True),
    (replace(ENDED, committed=False, acceptance_expires_at=None), 10000, False),
])
async def test_only_a_complete_expired_boundary_prunes(tmp_path, observed, now, delete):
    store = FileEvidenceStore(tmp_path)
    await store.put("neg-1", ITEM)
    reads = []
    async def read(negotiation_id):
        reads.append(negotiation_id)
        assert (await store.read(negotiation_id)).items == [ITEM]
        return observed
    result = await prune_command(store, read, now=now)
    assert reads == ["neg-1"]
    assert result.deleted == (("neg-1",) if delete else ())
    assert (await store.negotiations()) == (() if delete else ("neg-1",))


@pytest.mark.asyncio
async def test_unavailable_read_and_new_evidence_keep_records(tmp_path):
    store = FileEvidenceStore(tmp_path)
    await store.put("neg-1", ITEM)
    async def unavailable(_):
        raise ConnectionError("offline")
    result = await prune_command(store, unavailable, now=10000)
    assert result.kept == {"neg-1": "read_unavailable"}
    async def changed(negotiation_id):
        await store.put(negotiation_id, ITEM.model_copy(update={"evidence_id": "new"}))
        return ENDED
    result = await prune_command(store, changed, now=10000)
    assert result.kept == {"neg-1": "evidence_changed"}
    assert len((await store.read("neg-1")).items) == 2
