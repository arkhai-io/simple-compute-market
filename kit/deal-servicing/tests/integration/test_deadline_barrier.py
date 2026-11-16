"""A missed delivery deadline waits for a payment observation made at or after it.

Library integration: real SQLite, the payment watch and end service over it, and
a stand-in payment adapter whose reads the tests choose. The rig's deal is
once-only; ``rate`` is registered beside it with a projection that is not.
Both have the Agreement start 100, commitment 100 and a 500-second delivery
deadline, so the deadline is 600.
"""

from unittest.mock import AsyncMock

from market_deal_lifecycle.adapters import PaymentSelector
from market_deal_lifecycle.delivery import DeliveryAuthorization, DeliveryEvidence, DeliveryPhase
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, PaymentEvent, PaymentPartObservation, Unknown,
)

from market_deal_servicing import DealWatch, DeliveryRecord, EndSession, SellerDeal, SellerSession
from market_deal_servicing.evidence import transaction

DEADLINE = 600


def register(rig, negotiation_id, *, once_only=None):
    """A committed deal; ``once_only=None`` registers no seller projection at all."""
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id=negotiation_id, commitment_ref=f"{negotiation_id}-commitment",
            seller=rig["seller"].identity, start_at=100, term_end=1000, committed_at=100,
            delivery_deadline_seconds=500,
        ))
        if once_only is not None:
            SellerSession(conn).register(SellerDeal(
                negotiation_id=negotiation_id, commitment_ref=f"{negotiation_id}-commitment",
                domain="fixture", buyer=rig["buyer"].identity,
                payment=PaymentSelector("fixture.payment.v1"), once_only=once_only,
            ))


def payer_stop(at):
    return PaymentEvent(
        negotiation_id="rate", commitment_ref="rate-commitment", part="0", kind="stop",
        actor="payer-account", at=at, cause="payer", sequence=1,
        authority_record_ref="rate-commitment:events:1:part:0", settles_through="started_period",
    )


def view(*, stop=None):
    return AuthorityView(outcome=Accepted(), state="ended" if stop else "unstarted", parts=[
        PaymentPartObservation(part="0", final_stop=stop, evidence_ref="snapshot"),
    ])


def rate_watch(rig, payment):
    return DealWatch(
        rig["path"], negotiation_id="rate", commitment_ref="rate-commitment",
        payment=payment, dispute=None, dispute_binding=None, seller_account="seller-account",
        actor=lambda _: rig["buyer"].identity, clock=lambda: rig["clock"][0],
    )


async def poll_at(rig, at, read):
    """One payment poll begun at ``at``, the authority answering ``read``."""
    rig["clock"][0] = at
    payment = AsyncMock()
    payment.read.return_value = read
    await rate_watch(rig, payment).poll()


def admit_at(rig, negotiation_id, at):
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        record = session.read(negotiation_id)
        return session.admit(negotiation_id, record.phase, record.revision, now=at)


def journal(rig, negotiation_id):
    """The deal's recorded ends, journaled intents, revision and observation instant."""
    with transaction(rig["path"]) as conn:
        session = EndSession(conn)
        record = session.read(negotiation_id)
        return (
            session.requests(negotiation_id), session.intents(negotiation_id), record.revision,
            session.payment_observed_at(negotiation_id, record.commitment_ref),
        )


async def test_a_successful_poll_records_the_instant_it_began_with_the_stop_it_carried(rig):
    register(rig, "rate", once_only=False)
    payment = AsyncMock()

    async def read():
        # The authority answers after the poll began; the instant is the earlier one.
        rig["clock"][0] = 700
        return view(stop=payer_stop(400))

    payment.read.side_effect = read
    rig["clock"][0] = 650
    await rate_watch(rig, payment).poll()

    requests, _, _, observed_at = journal(rig, "rate")
    assert observed_at == 650
    assert [(item.source_ref, item.ended_at) for item in requests] == [
        ("payment-stop:rate-commitment:events:1:part:0", 400),
    ]


async def test_a_failed_or_refused_read_leaves_the_earlier_instant(rig):
    register(rig, "rate", once_only=False)
    await poll_at(rig, 300, view())
    await poll_at(rig, 650, AuthorityView(outcome=Unknown(reason="payment authority unreachable")))
    assert journal(rig, "rate")[3] == 300

    # A view the watch refuses, here one changing a recorded stop, records
    # nothing it carried, its instant included.
    await poll_at(rig, 660, view(stop=payer_stop(400)))
    await poll_at(rig, 700, view(stop=payer_stop(450)))
    requests, _, _, observed_at = journal(rig, "rate")
    assert observed_at == 660 and [item.ended_at for item in requests] == [400]


async def test_a_deadline_admitted_after_a_post_deadline_observation_files_seller_non_delivery(rig):
    register(rig, "rate", once_only=False)
    await poll_at(rig, 650, view())

    admission = admit_at(rig, "rate", 650)

    assert admission.status == "ended" and admission.ended_at == DEADLINE
    requests, intents, _, _ = journal(rig, "rate")
    assert [(item.source_ref, item.cause) for item in requests] == [("delivery-deadline", "non_delivery")]
    [filing] = [intent for intent in intents if intent.kind == "filing"]
    assert filing.payload["kind"] == "delivery_end"
    assert filing.payload["payload"]["cause"] == "payee" and filing.payload["payload"]["delivered"] is False


async def test_a_payer_stop_before_the_deadline_recorded_after_it_wins_with_no_filing(rig):
    register(rig, "rate", once_only=False)
    await poll_at(rig, 650, view(stop=payer_stop(400)))

    admission = admit_at(rig, "rate", 650)

    assert admission.status == "ended" and admission.ended_at == 400
    requests, intents, _, _ = journal(rig, "rate")
    assert [item.cause for item in requests] == ["payer"]
    assert not [intent for intent in intents if intent.kind == "filing"]


async def test_without_a_post_deadline_observation_nothing_is_recorded_until_a_successful_read(rig):
    register(rig, "rate", once_only=False)
    await poll_at(rig, 500, view())
    _, _, revision, _ = journal(rig, "rate")

    # Only a pre-deadline observation: nothing is admitted, recorded or filed.
    admission = admit_at(rig, "rate", 650)
    assert admission.status == "awaiting_observation" and admission.revision == revision
    assert journal(rig, "rate")[:3] == ([], [], revision)

    # The authority cannot be read: still nothing.
    await poll_at(rig, 660, AuthorityView(outcome=Unknown(reason="payment authority unreachable")))
    assert admit_at(rig, "rate", 660).status == "awaiting_observation"
    assert journal(rig, "rate")[:3] == ([], [], revision)

    # A successful read made after the deadline admits it.
    await poll_at(rig, 670, view())
    admission = admit_at(rig, "rate", 670)
    assert admission.status == "ended" and admission.ended_at == DEADLINE
    requests, intents, _, _ = journal(rig, "rate")
    assert [item.source_ref for item in requests] == ["delivery-deadline"]
    assert [intent.kind for intent in intents if intent.kind != "terminate"] == ["filing"]


def test_a_once_only_deal_past_its_deadline_files_as_before(rig):
    # The rig's deal is once-only and no payment observation was ever recorded.
    admission = admit_at(rig, "deal", 650)

    assert admission.status == "ended" and admission.ended_at == DEADLINE
    requests, intents, _, observed_at = journal(rig, "deal")
    assert observed_at is None
    assert [item.source_ref for item in requests] == ["delivery-deadline"]
    assert [intent.kind for intent in intents if intent.kind != "terminate"] == ["filing"]


def test_a_deal_with_no_seller_projection_keeps_the_deadline_rule(rig):
    register(rig, "unregistered")

    admission = admit_at(rig, "unregistered", 650)

    assert admission.status == "ended" and admission.ended_at == DEADLINE
    assert [item.source_ref for item in journal(rig, "unregistered")[0]] == ["delivery-deadline"]


async def test_an_allow_is_pending_while_the_deadline_awaits_an_observation(rig):
    # The door refuses only the commit, so a dispatch reaches the adapter,
    # whose allow admission does not admit past the deadline.
    register(rig, "rate", once_only=False)
    adapter = AsyncMock()
    adapter.authorize.return_value = DeliveryAuthorization(
        status="allow", reason="verified", operation_id="adapter", evidence_refs=["rate-commitment"],
    )
    _, _, revision, _ = journal(rig, "rate")
    rig["clock"][0] = 650

    answer = await rig["end"].authorize_delivery(
        DeliveryPhase.DISPATCH, DeliveryEvidence(negotiation_id="rate", commitment_ref="rate-commitment"),
        adapter=adapter, expected_revision=revision,
    )

    assert answer.status == "pending"
    assert answer.reason == "the missed delivery deadline awaits a payment observation"
    requests, intents, after, _ = journal(rig, "rate")
    assert requests == [] and after == revision
    assert [(intent.kind, intent.state) for intent in intents] == [("authorization", "pending")]


async def test_the_coded_commit_refusal_stands_while_the_deadline_awaits_an_observation(rig):
    register(rig, "rate", once_only=False)
    evidence = DeliveryEvidence(negotiation_id="rate", commitment_ref="rate-commitment")
    adapter = AsyncMock()

    async def commit():
        _, _, revision, _ = journal(rig, "rate")
        return await rig["end"].authorize_delivery(
            DeliveryPhase.COMMIT, evidence, adapter=adapter, expected_revision=revision,
        )

    rig["clock"][0] = 150
    refusal = await commit()
    assert refusal.code == "rate_servicing_unavailable"

    # Past the deadline with no observation since: the same journaled answer,
    # since a changed one at the same revision would be refused.
    rig["clock"][0] = 650
    assert await commit() == refusal

    await poll_at(rig, 660, view())
    rig["clock"][0] = 660
    ended = await commit()
    assert (ended.status, ended.reason, ended.code) == ("refuse", "delivery ended", None)
    adapter.authorize.assert_not_called()
    [*_, latest] = [intent for intent in journal(rig, "rate")[1] if intent.kind == "authorization"]
    assert DeliveryAuthorization.model_validate(latest.result).reason == "delivery ended"
