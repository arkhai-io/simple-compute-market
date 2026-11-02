"""Unchanged delivery admission is a read, without bypassing end/deadline checks."""

from market_deal_lifecycle.delivery import DeliveryPhase
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import EndSession
from test_review_fix_a import service


def test_repeated_admission_preserves_revision_but_still_checks_term(tmp_path):
    path = tmp_path / "servicing.sqlite"
    service(path)
    with transaction(path) as conn:
        end = EndSession(conn)
        record = end.read("deal")
        first = end.admit("deal", DeliveryPhase.COMMIT, record.revision, now=120)
        replay = end.admit("deal", DeliveryPhase.COMMIT, first.revision, now=120)
        assert replay.status == "admitted" and replay.revision == first.revision
        expired = end.admit("deal", DeliveryPhase.COMMIT, replay.revision, now=1000)
        assert expired.status == "ended" and expired.ended_at == 1000
