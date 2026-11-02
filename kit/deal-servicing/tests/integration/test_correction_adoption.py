"""End ordering and delayed classification share one immutable correction journal."""

import pytest

from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import Classification, EndSession, FinalRequest
from test_review_fix_a import BUYER, SELLER, failure, service


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("lawful", [False, True])
def test_pending_echo_adopts_verified_controlling_source_after_restart(tmp_path, delivered, lawful):
    path = tmp_path / "servicing.sqlite"
    service(path, delivered=delivered)
    echo = FinalRequest(
        negotiation_id="deal", source_ref="site:event", observed_at=120, ended_at=120,
        actor=SELLER.identity, cause="termination", source="lease_ended", evidence_refs=["site:event"],
    )
    with transaction(path) as conn:
        EndSession(conn).record_end(echo, now=120, pending_classification=True)
    kind = "buyer_surrender" if lawful else "unentitled_withdrawal"
    with transaction(path) as conn:
        end = EndSession(conn)
        controlling = FinalRequest(
            negotiation_id="deal", source_ref="operator:first", observed_at=120, ended_at=120,
            actor=BUYER.identity if lawful else SELLER.identity,
            cause="buyer_surrender" if lawful else "operator_end",
            source="end_delivery" if lawful else "administrator", evidence_refs=["operator:first"],
        )
        end.record_end(
            controlling, now=120, classification=Classification(kind=kind, evidence_refs=controlling.evidence_refs),
            filing_intent=None if lawful else end.failure_filing(controlling, now=120, delivered=delivered),
        )
    classification = Classification(kind=kind, evidence_refs=["site:event", controlling.source_ref])
    for _ in range(2):
        with transaction(path) as conn:
            end = EndSession(conn)
            assert end.resolve_correction(
                "deal", echo.source_ref, end.read("deal").revision,
                evidence=classification.evidence_refs, classification=classification,
                controlling_source_ref=controlling.source_ref,
            ).status == "admitted"
            assert next(r for r in end.requests("deal") if r.source_ref == echo.source_ref) == echo
            assert len([i for i in end.intents("deal") if i.kind == "filing"]) == (0 if lawful else 1)


def test_correction_cannot_adopt_an_unverified_or_conflicting_source(tmp_path):
    path = tmp_path / "servicing.sqlite"
    service(path)
    with transaction(path) as conn:
        end = EndSession(conn)
        original = failure(end)
        echo = original.model_copy(update={"source_ref": "site:event", "source": "lease_ended"})
        end.record_end(echo, now=120, pending_classification=True)
        for source, kind in [("missing", "unentitled_withdrawal"), (original.source_ref, "terms")]:
            with pytest.raises(ValueError, match="controlling"):
                end.resolve_correction(
                    "deal", echo.source_ref, end.read("deal").revision,
                    evidence=["site:event", source],
                    classification=Classification(kind=kind, evidence_refs=["site:event", source]),
                    controlling_source_ref=source,
                )
        assert conn.execute(
            "SELECT classification FROM servicing_final_requests WHERE source_ref='site:event'",
        ).fetchone()[0] is None


@pytest.mark.parametrize("later", [True, False])
def test_only_a_new_selected_failure_journals_a_filing(tmp_path, later):
    path = tmp_path / "servicing.sqlite"
    service(path)
    with transaction(path) as conn:
        end = EndSession(conn)
        first = failure(end)
    second = first.model_copy(update={"source_ref": "operator:second", "ended_at": 130 if later else 110})
    for _ in range(2):
        with transaction(path) as conn:
            end = EndSession(conn)
            end.record_end(
                second, now=130,
                classification=Classification(kind="unentitled_withdrawal", evidence_refs=second.evidence_refs),
                filing_intent=end.failure_filing(second, now=130, delivered=True),
            )
            assert len(end.requests("deal")) == 2
            assert len([i for i in end.intents("deal") if i.kind == "filing"]) == (1 if later else 2)
            assert end.selected_end("deal").source_ref == (first if later else second).source_ref
