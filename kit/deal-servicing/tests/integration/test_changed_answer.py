"""End service asks the payment adapter for every deal and holds a changed answer back.

Library integration: real SQLite, end service over it, and a stand-in payment
adapter whose answers the tests choose. ``rate`` is a committed deal whose seller
projection is not once-only: Agreement start 100, term end 1000, committed at 100,
with a 500-second delivery deadline; the clock reads 150.
"""

from unittest.mock import AsyncMock

from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.delivery import DeliveryAuthorization, DeliveryEvidence, DeliveryPhase
from market_deal_servicing import (
    Classification, DeliveryRecord, EndSession, FinalRequest, SellerDeal, SellerSession,
)
from market_deal_servicing.evidence import transaction

EVIDENCE = DeliveryEvidence(negotiation_id="rate", commitment_ref="rate-commitment")


def register(rig, *, delivery_deadline_seconds=500):
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="rate", commitment_ref="rate-commitment",
            seller=rig["seller"].identity, start_at=100, term_end=1000, committed_at=100,
            delivery_deadline_seconds=delivery_deadline_seconds,
        ))
        SellerSession(conn).register(SellerDeal(
            negotiation_id="rate", commitment_ref="rate-commitment", domain="fixture",
            buyer=rig["buyer"].identity, payment=PaymentSelector("fixture.payment.v1"), once_only=False,
        ))


def answer(status, reason, snapshot=1):
    # A rate adapter's answer names the fresh snapshot it read, so two answers
    # of one status differ in their evidence references.
    return DeliveryAuthorization(
        status=status, reason=reason, operation_id="rate:commit",
        evidence_refs=["rate-commitment", f"rate-commitment:snapshot:{snapshot}"],
    )


def journal(rig):
    """The deal's authorization intents and its revision."""
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        return [item for item in session.intents("rate") if item.kind == "authorization"], session.read("rate").revision


async def commit(rig, adapter):
    _, revision = journal(rig)
    return await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, EVIDENCE, adapter=adapter, expected_revision=revision,
    )


def adapter_answering(*answers):
    adapter = AsyncMock()
    adapter.authorize.side_effect = list(answers)
    return adapter


async def test_a_rate_deal_s_commit_asks_the_adapter_and_journals_its_allow(rig):
    register(rig)
    adapter = adapter_answering(answer("allow", "verified timely approved rate commitment"))

    allowed = await commit(rig, adapter)

    assert allowed.status == "allow"
    adapter.authorize.assert_awaited_once()
    [intent], _ = journal(rig)
    assert intent.state == "done" and intent.intent_ref == allowed.operation_id
    assert DeliveryAuthorization.model_validate(intent.result).status == "allow"


async def test_allow_then_pending_holds_the_commit_back_and_a_later_allow_proceeds(rig):
    register(rig)
    first = answer("allow", "verified timely approved rate commitment", snapshot=1)
    adapter = adapter_answering(
        first, answer("pending", "verified current authority state is unavailable"),
        answer("allow", "verified timely approved rate commitment", snapshot=3),
    )
    allowed = await commit(rig, adapter)
    before = journal(rig)

    held = await commit(rig, adapter)

    assert held.status == "pending" and held.operation_id == allowed.operation_id
    assert "changed from allow to pending" in held.reason
    assert "verified current authority state is unavailable" in held.reason
    assert journal(rig) == before
    # The next allow, though it read a newer snapshot, is the same answer: the
    # one journaled first stands and is returned.
    again = await commit(rig, adapter)
    assert again == allowed
    assert journal(rig) == before


async def test_allow_then_refuse_is_pending_with_nothing_journaled(rig):
    register(rig)
    adapter = adapter_answering(
        answer("allow", "verified timely approved rate commitment"),
        answer("refuse", "verified stop or maximum term is effective", snapshot=2),
    )
    allowed = await commit(rig, adapter)
    before = journal(rig)

    held = await commit(rig, adapter)

    assert held.status == "pending" and held.operation_id == allowed.operation_id
    assert "changed from allow to refuse" in held.reason
    assert journal(rig) == before


async def test_once_a_recorded_end_moves_the_revision_admission_answers_ended(rig):
    register(rig)
    adapter = adapter_answering(
        answer("allow", "verified timely approved rate commitment"),
        answer("refuse", "verified stop or maximum term is effective", snapshot=2),
        answer("refuse", "verified stop or maximum term is effective", snapshot=3),
    )
    await commit(rig, adapter)
    assert (await commit(rig, adapter)).status == "pending"
    # The watch records the buyer's stop, which moves the revision.
    with transaction(rig["path"]) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="rate", source_ref="payment-stop:rate-commitment:events:1:part:0",
            ended_at=140, observed_at=150, actor=rig["buyer"].identity, cause="payer",
            source="rate-commitment:events:1:part:0", evidence_refs=["rate-commitment:events:1:part:0"],
        ), now=150, pending_classification=True)

    ended = await commit(rig, adapter)

    assert (ended.status, ended.reason) == ("refuse", "delivery ended")
    intents, _ = journal(rig)
    assert [DeliveryAuthorization.model_validate(item.result).reason for item in intents] == [
        "verified timely approved rate commitment", "delivery ended",
    ]


async def test_an_end_due_at_the_same_revision_is_admission_s_answer_not_a_changed_one(rig):
    # No delivery deadline, so only the term end can end the deal.
    register(rig, delivery_deadline_seconds=None)
    adapter = adapter_answering(
        answer("allow", "verified timely approved rate commitment"),
        answer("allow", "verified timely approved rate commitment", snapshot=2),
    )
    allowed = await commit(rig, adapter)
    before = journal(rig)
    # The term end passes with no end recorded, so the revision stands still.
    rig["clock"][0] = 1000

    ended = await commit(rig, adapter)

    assert (ended.status, ended.reason) == ("refuse", "delivery ended")
    assert ended.operation_id == allowed.operation_id
    assert journal(rig) == before


async def test_a_once_only_deal_s_unchanged_answer_reads_the_journal_as_before(rig):
    adapter = AsyncMock()
    adapter.authorize.return_value = DeliveryAuthorization(
        status="allow", reason="validated once commitment", operation_id="deal:commit",
        evidence_refs=["commitment"],
    )
    evidence = DeliveryEvidence(negotiation_id="deal", commitment_ref="commitment")

    async def ask():
        with transaction(rig["path"]) as conn:
            revision = EndSession(conn).read("deal").revision
        return await rig["end"].authorize_delivery(
            DeliveryPhase.COMMIT, evidence, adapter=adapter, expected_revision=revision,
        )

    first = await ask()
    second = await ask()

    assert first == second and first.status == "allow"
    assert adapter.authorize.await_count == 2
