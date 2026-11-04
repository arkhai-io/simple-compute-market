import pytest
from market_deal_lifecycle.evidence import CommitmentAttempt
from market_deal_lifecycle.terms import LifecycleTerms
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DisputeEvent,
)
from market_deal_servicing import (
    Classification, EndSession, FinalRequest, SQLiteEvidenceStore, seller_retention,
)
from market_deal_servicing.evidence import EvidenceSession, RetentionObservation, transaction


@pytest.mark.parametrize("administrator", [False, True])
async def test_exact_opening_acceptance_and_author_survive_restart(rig, administrator):
    body = b'{"offer": "exact bytes including whitespace"}'
    author = rig["authority_signer"].identity if administrator else rig["seller"].identity
    terms = LifecycleTerms.model_validate({"adjudication": {
        "version": 1, "dispute": rig["authority"].model_dump(mode="json"),
        "dispute_window_seconds": 60, "case_hold_max_seconds": None,
    }})
    with transaction(rig["path"]) as conn:
        evidence = EvidenceSession(conn)
        evidence.capture("deal", evidence_id="opening", body=body, headers={"proof": "verified-fixture"},
                         context={"request_id": "opening"}, recorded_at=100)
        evidence.accept("deal", message_id="opening", accepted_by=author, expires_at=120, terms=terms)
    store = SQLiteEvidenceStore(rig["path"])
    kept = await store.read("deal")
    assert kept.items[0].body == body and kept.items[0].headers == {"proof": "verified-fixture"}
    with transaction(rig["path"]) as conn:
        row = conn.execute("SELECT accepted_by,lifecycle FROM servicing_evidence_deals WHERE negotiation_id='deal'").fetchone()
        assert row == (author.model_dump_json(), terms.model_dump_json()) or (
            row[0] == author.model_dump_json() and LifecycleTerms.model_validate_json(row[1]) == terms
        )
    await store.record_commitment("deal", CommitmentAttempt(commitment_ref="commitment"))
    await store.observe("deal", RetentionObservation(
        observed_at=300, delivery_ended_at=150, recovered_at=180,
        payouts={"once": None}, cases={}, open_extensions=[], complete=True,
    ))
    assert not await store.prune("deal", now=1000, has_adapter=True)
    await store.observe("deal", RetentionObservation(
        observed_at=301, delivery_ended_at=150, recovered_at=180,
        payouts={"once": 200}, cases={"case": None}, open_extensions=[], complete=True,
    ))
    assert not await store.prune("deal", now=1000, has_adapter=True)
    await store.observe("deal", RetentionObservation(
        observed_at=302, delivery_ended_at=150, recovered_at=180,
        payouts={"once": 200}, cases={"case": 260}, open_extensions=[], complete=True,
    ))
    assert not await store.prune("deal", now=319, has_adapter=True)
    assert await store.prune("deal", now=320, has_adapter=True)
    assert not (await store.read("deal")).items


async def test_seller_retention_observes_payment_and_cases_before_prune(rig):
    path = rig["path"]
    store = SQLiteEvidenceStore(path)
    terms = LifecycleTerms.model_validate({"adjudication": {
        "version": 1, "dispute": rig["authority"].model_dump(mode="json"),
        "dispute_window_seconds": 60, "case_hold_max_seconds": None,
    }})
    with transaction(path) as conn:
        evidence = EvidenceSession(conn)
        evidence.capture("deal", evidence_id="opening", body=b"{}", headers={}, context={}, recorded_at=100)
        evidence.accept("deal", message_id="opening", accepted_by=rig["seller"].identity, expires_at=120, terms=terms)
        evidence.record_commitment("deal", CommitmentAttempt(commitment_ref="commitment"))
        end = EndSession(conn)
        end.record_end(FinalRequest(
            negotiation_id="deal", source_ref="end", actor=rig["buyer"].identity, ended_at=140,
            observed_at=150, cause="buyer_surrender", source="end_delivery",
        ), now=150, classification=Classification(kind="buyer_surrender", evidence_refs=["end"]))
        end.physical_progress("deal", "released")
    observer = seller_retention(path, "deal", clock=lambda: rig["clock"][0])
    watch_factory = rig["watch"]

    def factory(deal, payment, dispute):
        watch = watch_factory(deal, payment, dispute)
        watch.observe_retention = observer
        return watch

    api = rig["service"]()
    api.watch_factory = factory
    # Unknown terminal financial state keeps evidence even with recovered capacity.
    assert not await api.prune("deal")
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), payouts={"once": None})
    assert not await api.prune("deal")
    rig["clock"][0] = 200
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), payouts={"once": 200})
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), cases=[
        CaseRecord(case_ref="case", state="filed", record_ref="filed"),
    ])
    assert not await api.prune("deal")
    rig["clock"][0] = 210
    rig["dispute"].read.return_value = AuthorityView(
        outcome=Accepted(), cases=[CaseRecord(case_ref="case", state="closed", record_ref="closed")],
        disputes=[DisputeEvent(negotiation_id="deal", commitment_ref="commitment", case_ref="case",
                              kind="closed", actor="authority", at=210, sequence=1, record_ref="closed")],
    )
    assert not await api.prune("deal")
    rig["clock"][0] = 270
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), payouts={"once": 270})
    assert await api.prune("deal")  # A refresh must not slide the first completion observation.
    assert not (await store.read("deal")).items


async def test_no_terms_or_missing_adapter_never_prunes(rig):
    store = SQLiteEvidenceStore(rig["path"])
    await store.observe("deal", RetentionObservation(
        observed_at=200, delivery_ended_at=100, recovered_at=100,
        payouts={"once": 100}, cases={}, open_extensions=[], complete=True,
    ))
    assert not await store.prune("deal", now=10000, has_adapter=False)
    assert not await store.prune("deal", now=10000, has_adapter=True)
