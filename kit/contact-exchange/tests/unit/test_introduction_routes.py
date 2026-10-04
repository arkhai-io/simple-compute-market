"""Reveal authorization, idempotency, and refusal mechanics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from market_contact_exchange import (
    AuthorizedIntroductionRequest,
    IntroductionAgreement,
    IntroductionPayloadsDeletedError,
    IntroductionRecord,
    IntroductionRouteCallbacks,
    IntroductionRouteError,
    IntroductionRouteService,
    IntroductionStart,
    introduction_projection,
)
from market_identity import Identity, IdentityScheme

BUYER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "11" * 20)
SELLER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "22" * 20)
OUTSIDER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "33" * 20)

_OBLIGATION_REF = "ab" * 32
_PACKAGE = {"channel": "telegram", "terms": "Net-30 prose."}
_SELLER_CONTACT = {"telegram": "@capacity_broker"}


class Harness:
    """Accepted-deal domain callbacks over in-memory persistence."""

    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.records: dict[str, IntroductionRecord] = {}
        self.completions: list[str] = []
        self.agreement = IntroductionAgreement(
            agreement_ref="neg-1",
            obligation_ref=_OBLIGATION_REF,
            buyer_principal=BUYER,
            seller_principal=SELLER,
            introduction_package=dict(_PACKAGE),
        )

    async def prepare(
        self, negotiation_id: str | None, obligation_ref: str
    ) -> IntroductionAgreement:
        if not self.accepted or obligation_ref != _OBLIGATION_REF:
            raise ValueError("introduction deal is not accepted")
        return self.agreement

    async def authorize(
        self,
        request_context: Any,
        operation: str,
        resource_id: str,
        allowed_principals: tuple[Identity, ...],
        body: Mapping[str, Any] | None,
    ) -> AuthorizedIntroductionRequest:
        caller = request_context["principal"]
        if caller not in allowed_principals:
            raise IntroductionRouteError(403, "caller is not an introduction party")
        return AuthorizedIntroductionRequest(principal=caller)

    async def persist(
        self,
        agreement: IntroductionAgreement,
        buyer_contact: Mapping[str, str],
        seller_contact: Mapping[str, str],
    ) -> IntroductionRecord:
        record = IntroductionRecord(
            obligation_ref=agreement.obligation_ref,
            agreement_ref=agreement.agreement_ref,
            buyer_contact=dict(buyer_contact),
            seller_contact=dict(seller_contact),
            introduction_package=dict(agreement.introduction_package),
        )
        existing = self.records.get(agreement.obligation_ref)
        if existing is not None:
            if existing.payloads_deleted_at is not None:
                raise IntroductionPayloadsDeletedError(existing.payloads_deleted_at)
            if existing != record:
                raise ValueError(
                    "introduction already revealed with different contact payloads"
                )
            return existing
        self.records[agreement.obligation_ref] = record
        return record

    async def load(self, obligation_ref: str) -> IntroductionRecord | None:
        return self.records.get(obligation_ref)

    async def complete(self, agreement: IntroductionAgreement) -> None:
        self.completions.append(agreement.obligation_ref)

    def redact(self, deleted_at: str = "2026-10-01T12:00:00Z") -> None:
        record = self.records[_OBLIGATION_REF]
        self.records[_OBLIGATION_REF] = record.model_copy(
            update={
                "buyer_contact": {},
                "seller_contact": {},
                "payloads_deleted_at": deleted_at,
            }
        )

    def service(
        self, deliver=None, disclosure=None, seller_contact=_SELLER_CONTACT
    ) -> IntroductionRouteService:
        self.resolved: list[IntroductionAgreement] = []

        def resolve(agreement: IntroductionAgreement) -> Mapping[str, str] | None:
            self.resolved.append(agreement)
            return dict(seller_contact) if seller_contact is not None else None

        return IntroductionRouteService(
            callbacks=IntroductionRouteCallbacks(
                prepare=self.prepare,
                authorize=self.authorize,
                persist=self.persist,
                load=self.load,
                complete=self.complete,
            ),
            resolve_seller_contact=resolve,
            deliver=deliver,
            disclosure=disclosure,
        )


def _start() -> IntroductionStart:
    return IntroductionStart(
        negotiation_id="neg-1",
        obligation_ref=_OBLIGATION_REF,
        contact_payload={"email": "buyer@example.com"},
    )


async def test_start_reveals_the_seller_contact_to_the_buyer() -> None:
    harness = Harness()
    projection = await harness.service().start({"principal": BUYER}, _start())
    assert projection["revealed"] is True
    assert projection["counterparty_contact"] == _SELLER_CONTACT
    assert projection["introduction"] == _PACKAGE
    assert harness.completions == [_OBLIGATION_REF]


async def test_start_is_idempotent_and_conflicts_on_changed_payload() -> None:
    harness = Harness()
    service = harness.service()
    first = await service.start({"principal": BUYER}, _start())
    again = await service.start({"principal": BUYER}, _start())
    assert first == again
    changed = IntroductionStart(
        negotiation_id="neg-1",
        obligation_ref=_OBLIGATION_REF,
        contact_payload={"email": "other@example.com"},
    )
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start({"principal": BUYER}, changed)
    assert caught.value.status_code == 409


async def test_each_party_reads_the_counterparty_payload() -> None:
    harness = Harness()
    service = harness.service()
    await service.start({"principal": BUYER}, _start())
    buyer_view = await service.read({"principal": BUYER}, _OBLIGATION_REF)
    seller_view = await service.read({"principal": SELLER}, _OBLIGATION_REF)
    assert buyer_view["counterparty_contact"] == _SELLER_CONTACT
    assert seller_view["counterparty_contact"] == {"email": "buyer@example.com"}
    assert buyer_view["introduction"] == seller_view["introduction"] == _PACKAGE


async def test_read_before_start_is_refused() -> None:
    harness = Harness()
    with pytest.raises(IntroductionRouteError) as caught:
        await harness.service().read({"principal": BUYER}, _OBLIGATION_REF)
    assert caught.value.status_code == 409


async def test_unaccepted_deal_is_not_found() -> None:
    harness = Harness(accepted=False)
    with pytest.raises(IntroductionRouteError) as caught:
        await harness.service().start({"principal": BUYER}, _start())
    assert caught.value.status_code == 404


async def test_non_party_is_refused() -> None:
    harness = Harness()
    service = harness.service()
    await service.start({"principal": BUYER}, _start())
    with pytest.raises(IntroductionRouteError) as caught:
        await service.read({"principal": OUTSIDER}, _OBLIGATION_REF)
    assert caught.value.status_code == 403


async def test_only_the_buyer_may_start() -> None:
    harness = Harness()
    with pytest.raises(IntroductionRouteError) as caught:
        await harness.service().start({"principal": SELLER}, _start())
    assert caught.value.status_code == 403


async def test_a_start_whose_origin_has_no_contact_is_refused_before_anything_happens() -> None:
    harness = Harness()
    delivered: list[tuple] = []
    service = harness.service(
        deliver=lambda projection, agreement: delivered.append((projection, agreement)),
        seller_contact=None,
    )
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start({"principal": BUYER}, _start())
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "seller_contact_unavailable"
    assert harness.records == {}
    assert harness.completions == []
    assert delivered == []


async def test_the_contact_is_resolved_for_the_agreement_being_revealed() -> None:
    harness = Harness()
    service = harness.service()
    await service.start({"principal": BUYER}, _start())
    assert [agreement.obligation_ref for agreement in harness.resolved] == [
        _OBLIGATION_REF
    ]


async def test_the_seller_side_is_told_its_own_half_of_the_reveal() -> None:
    harness = Harness()
    delivered: list[tuple] = []
    service = harness.service(
        deliver=lambda projection, agreement: delivered.append((projection, agreement))
    )

    await service.start({"principal": BUYER}, _start())

    (projection, agreement) = delivered[0]
    assert len(delivered) == 1
    assert projection["counterparty_contact"] == {"email": "buyer@example.com"}
    assert projection["obligation_ref"] == _OBLIGATION_REF
    assert agreement.agreement_ref == "neg-1"
    assert agreement.seller_principal == SELLER


async def test_a_repeat_start_announces_one_introduction_once() -> None:
    harness = Harness()
    delivered: list[tuple] = []
    service = harness.service(deliver=lambda projection, agreement: delivered.append(1))

    await service.start({"principal": BUYER}, _start())
    await service.start({"principal": BUYER}, _start())

    assert len(delivered) == 1


async def test_reading_the_durable_reveal_delivers_nothing() -> None:
    harness = Harness()
    delivered: list[tuple] = []
    service = harness.service(deliver=lambda projection, agreement: delivered.append(1))
    await service.start({"principal": BUYER}, _start())
    delivered.clear()

    await service.read({"principal": SELLER}, _OBLIGATION_REF)
    await service.read({"principal": BUYER}, _OBLIGATION_REF)

    assert delivered == []


async def test_a_failing_delivery_leaves_the_reveal_and_the_deal_intact() -> None:
    harness = Harness()

    def explode(projection, agreement):
        raise RuntimeError("the operator's mail server is down")

    projection = await harness.service(deliver=explode).start(
        {"principal": BUYER}, _start()
    )

    assert projection["revealed"] is True
    assert projection["counterparty_contact"] == _SELLER_CONTACT
    assert harness.completions == [_OBLIGATION_REF]


async def test_no_delivery_configured_reads_no_record_and_changes_nothing() -> None:
    harness = Harness()

    projection = await harness.service().start({"principal": BUYER}, _start())

    assert projection["revealed"] is True
    assert harness.completions == [_OBLIGATION_REF]


_DISCLOSURE = {
    "window_seconds": 2592000,
    "basis": "current_policy",
    "scope": "introduction_record",
}
_DELETED = {
    "code": "introduction_payloads_deleted",
    "payloads_deleted_at": "2026-10-01T12:00:00Z",
}


def test_the_projection_refuses_a_redacted_record() -> None:
    record = IntroductionRecord(
        obligation_ref=_OBLIGATION_REF,
        agreement_ref="neg-1",
        buyer_contact={},
        seller_contact={},
        payloads_deleted_at="2026-10-01T12:00:00Z",
    )
    with pytest.raises(IntroductionPayloadsDeletedError):
        introduction_projection(record, for_role="seller")


async def test_the_reveal_carries_the_disclosure_when_one_is_provided() -> None:
    harness = Harness()
    calls: list[int] = []

    def disclosure() -> dict[str, Any]:
        calls.append(1)
        return dict(_DISCLOSURE)

    service = harness.service(disclosure=disclosure)
    started = await service.start({"principal": BUYER}, _start())
    read = await service.read({"principal": SELLER}, _OBLIGATION_REF)
    assert started["retention"] == _DISCLOSURE
    assert read["retention"] == _DISCLOSURE
    # Read from the provider at each reveal, never captured once.
    assert len(calls) == 2


async def test_the_reveal_omits_the_disclosure_without_a_provider() -> None:
    projection = await Harness().service().start({"principal": BUYER}, _start())
    assert "retention" not in projection


async def test_a_read_after_deletion_answers_the_deleted_outcome() -> None:
    harness = Harness()
    service = harness.service()
    await service.start({"principal": BUYER}, _start())
    harness.redact()
    for party in (BUYER, SELLER):
        with pytest.raises(IntroductionRouteError) as caught:
            await service.read({"principal": party}, _OBLIGATION_REF)
        assert caught.value.status_code == 410
        assert caught.value.detail == _DELETED


async def test_a_start_after_deletion_completes_but_persists_and_delivers_nothing() -> None:
    harness = Harness()
    delivered: list[Any] = []
    service = harness.service(deliver=lambda projection, agreement: delivered.append(1))
    await service.start({"principal": BUYER}, _start())
    harness.redact()
    harness.completions.clear()
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start({"principal": BUYER}, _start())
    assert caught.value.status_code == 410
    assert caught.value.detail == _DELETED
    assert harness.completions == [_OBLIGATION_REF]
    assert harness.records[_OBLIGATION_REF].buyer_contact == {}
    assert delivered == [1]


async def test_a_start_after_deletion_reports_unavailable_completion() -> None:
    harness = Harness()
    service = harness.service()
    await service.start({"principal": BUYER}, _start())
    harness.redact()

    async def failing(agreement: IntroductionAgreement) -> None:
        raise RuntimeError("settlement store unavailable")

    harness.complete = failing  # type: ignore[method-assign]
    with pytest.raises(IntroductionRouteError) as caught:
        await harness.service().start({"principal": BUYER}, _start())
    assert caught.value.status_code == 503


async def test_a_redaction_racing_a_start_answers_the_deleted_outcome() -> None:
    harness = Harness()
    await harness.service().start({"principal": BUYER}, _start())
    delivered: list[Any] = []
    original_load = harness.load

    async def stale_load(obligation_ref: str) -> IntroductionRecord | None:
        # The start reads the record, then the sweep redacts it before persist.
        record = await original_load(obligation_ref)
        harness.redact()
        return record

    harness.load = stale_load  # type: ignore[method-assign]
    harness.completions.clear()
    service = harness.service(deliver=lambda projection, agreement: delivered.append(1))
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start({"principal": BUYER}, _start())
    assert caught.value.status_code == 410
    assert harness.completions == [_OBLIGATION_REF]
    assert delivered == []


async def test_a_deletion_committing_during_a_first_reveal_does_not_recall_it() -> None:
    """A reveal is ordered by its persist; deletion bounds only what follows.

    The start persists, then waits on completion while a deletion commits. The
    start finishes answering and delivering the reveal it made before the
    deletion; every later read and start answers the deleted outcome.
    """
    harness = Harness()
    delivered: list[str] = []
    completing = asyncio.Event()
    release = asyncio.Event()
    original_complete = harness.complete

    async def held_complete(agreement: IntroductionAgreement) -> None:
        completing.set()
        await release.wait()
        await original_complete(agreement)

    harness.complete = held_complete  # type: ignore[method-assign]
    service = harness.service(
        deliver=lambda projection, agreement: delivered.append(
            projection["obligation_ref"]
        )
    )

    start = asyncio.create_task(service.start({"principal": BUYER}, _start()))
    await asyncio.wait_for(completing.wait(), timeout=5)
    harness.redact()
    release.set()
    revealed = await start

    assert revealed["revealed"] is True
    assert revealed["counterparty_contact"] == _SELLER_CONTACT
    assert delivered == [_OBLIGATION_REF]

    harness.complete = original_complete  # type: ignore[method-assign]
    for attempt in (
        service.read({"principal": BUYER}, _OBLIGATION_REF),
        service.start({"principal": BUYER}, _start()),
    ):
        with pytest.raises(IntroductionRouteError) as caught:
            await attempt
        assert caught.value.status_code == 410
    assert delivered == [_OBLIGATION_REF]
