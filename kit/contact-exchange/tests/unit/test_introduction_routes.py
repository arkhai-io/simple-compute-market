"""Reveal authorization, idempotency, and refusal mechanics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from market_contact_exchange import (
    AuthorizedIntroductionRequest,
    IntroductionAgreement,
    IntroductionRecord,
    IntroductionRouteCallbacks,
    IntroductionRouteError,
    IntroductionRouteService,
    IntroductionStart,
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

    def service(self, deliver=None) -> IntroductionRouteService:
        return IntroductionRouteService(
            callbacks=IntroductionRouteCallbacks(
                prepare=self.prepare,
                authorize=self.authorize,
                persist=self.persist,
                load=self.load,
                complete=self.complete,
            ),
            seller_contact=dict(_SELLER_CONTACT),
            deliver=deliver,
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


def test_service_requires_a_seller_contact_payload() -> None:
    harness = Harness()
    with pytest.raises(ValueError, match="requires a seller contact payload"):
        IntroductionRouteService(
            callbacks=IntroductionRouteCallbacks(
                prepare=harness.prepare,
                authorize=harness.authorize,
                persist=harness.persist,
                load=harness.load,
                complete=harness.complete,
            ),
            seller_contact={},
        )


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
