"""End service refuses to commit a deal it could not service once delivered."""

from unittest.mock import AsyncMock

from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.delivery import DeliveryAuthorization, DeliveryEvidence, DeliveryPhase
from market_deal_servicing import (
    Classification, DeliveryRecord, EndSession, FinalRequest, SellerDeal, SellerSession,
)
from market_deal_servicing.evidence import transaction


def register(rig, negotiation_id, *, once_only=None):
    """A committed deal; ``once_only=None`` registers no seller projection at all."""
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id=negotiation_id, commitment_ref=f"{negotiation_id}-commitment",
            seller=rig["seller"].identity, start_at=100, term_end=1000, committed_at=100,
            delivery_deadline_seconds=500,
        ))
        if once_only is not None:
            fields = {} if not once_only else {"once_only": True}
            SellerSession(conn).register(SellerDeal(
                negotiation_id=negotiation_id, commitment_ref=f"{negotiation_id}-commitment",
                domain="fixture", buyer=rig["buyer"].identity,
                payment=PaymentSelector("fixture.payment.v1"), **fields,
            ))


def evidence(negotiation_id):
    return DeliveryEvidence(negotiation_id=negotiation_id, commitment_ref=f"{negotiation_id}-commitment")


def journaled(rig, negotiation_id):
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        return session.intents(negotiation_id), session.read(negotiation_id).revision


def spy_adapter():
    adapter = AsyncMock()
    adapter.authorize.return_value = DeliveryAuthorization(
        status="allow", reason="verified", operation_id="adapter", evidence_refs=["commitment"],
    )
    return adapter


async def test_a_rate_deal_s_commit_is_refused_with_its_code_and_journaled_without_asking_the_adapter(rig):
    # A projection that never stated ``once_only`` reads as a rate deal.
    register(rig, "rate", once_only=False)
    adapter = spy_adapter()
    _, revision = journaled(rig, "rate")

    refusal = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("rate"), adapter=adapter, expected_revision=revision,
    )

    assert refusal.status == "refuse" and refusal.code == "rate_servicing_unavailable"
    assert refusal.reason == "rate servicing is not composed in this storefront"
    adapter.authorize.assert_not_called()
    intents, revision = journaled(rig, "rate")
    [authorization] = intents
    assert authorization.kind == "authorization" and authorization.state == "done"
    assert authorization.intent_ref == refusal.operation_id
    assert DeliveryAuthorization.model_validate(authorization.result).code == "rate_servicing_unavailable"
    # Nothing but the refusal is journaled: no billing intent, no end, no filing.
    assert {item.kind for item in intents} == {"authorization"}

    again = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("rate"), adapter=adapter, expected_revision=revision,
    )
    assert again == refusal
    adapter.authorize.assert_not_called()


async def test_a_once_only_deal_s_commit_reaches_the_adapter_and_its_answer_carries_no_code(rig):
    register(rig, "once", once_only=True)
    adapter = spy_adapter()
    _, revision = journaled(rig, "once")

    answer = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("once"), adapter=adapter, expected_revision=revision,
    )

    assert answer.status == "allow" and answer.code is None
    adapter.authorize.assert_awaited_once()
    [authorization], _ = journaled(rig, "once")
    assert "code" not in authorization.result


async def test_a_deal_with_no_seller_projection_is_refused_without_the_code(rig):
    register(rig, "unregistered")
    adapter = spy_adapter()
    _, revision = journaled(rig, "unregistered")

    refusal = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("unregistered"), adapter=adapter, expected_revision=revision,
    )

    assert refusal.status == "refuse" and refusal.code is None
    adapter.authorize.assert_not_called()
    [authorization], _ = journaled(rig, "unregistered")
    assert authorization.state == "done" and "code" not in authorization.result


async def test_a_due_end_replaces_the_refusal_and_its_code(rig):
    register(rig, "rate", once_only=False)
    with transaction(rig["path"]) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="rate", source_ref="buyer-end", ended_at=140, observed_at=140,
            actor=rig["buyer"].identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=150, classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))
    adapter = spy_adapter()
    _, revision = journaled(rig, "rate")

    answer = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("rate"), adapter=adapter, expected_revision=revision,
    )

    assert answer.status == "refuse" and answer.reason == "delivery ended" and answer.code is None
    adapter.authorize.assert_not_called()


async def test_a_stale_revision_makes_the_refusal_pending_without_its_code(rig):
    register(rig, "rate", once_only=False)
    _, revision = journaled(rig, "rate")

    answer = await rig["end"].authorize_delivery(
        DeliveryPhase.COMMIT, evidence("rate"), adapter=spy_adapter(), expected_revision=revision + 1,
    )

    assert answer.status == "pending" and answer.code is None


async def test_only_the_commit_is_refused_at_the_door(rig):
    register(rig, "rate", once_only=False)
    adapter = spy_adapter()
    _, revision = journaled(rig, "rate")

    answer = await rig["end"].authorize_delivery(
        DeliveryPhase.DISPATCH, evidence("rate"), adapter=adapter, expected_revision=revision,
    )

    assert answer.status == "allow"
    adapter.authorize.assert_awaited_once()
