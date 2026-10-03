"""The promoted accepted-state interpretation against a real introduction table."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from market_contact_exchange import (
    CONTACT_EXCHANGE_MIGRATIONS,
    AuthorizedIntroductionRequest,
    ContactExchangeComposition,
    ContactSettlementConfig,
    IntroductionAgreement,
    IntroductionPayloadsDeletedError,
    IntroductionRouteError,
    IntroductionStart,
    SQLiteIntroductionStore,
    contact_accepted_obligation_builder,
)
from market_core.schemas import SettlementPlan, derive_settlement_option_id
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import derive_obligation_ref

BUYER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "11" * 20)
SELLER = Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "22" * 20)
NEGOTIATION = "neg-1"


def _config(**overrides: Any) -> ContactSettlementConfig:
    section: dict[str, Any] = {
        "enabled": True,
        "origins": {
            "dc-west": {"contact_payload": {"email": "ops@west.example"}},
            "dc-east": {"contact_payload": {"email": "sales@east.example"}},
        },
        "profiles": {"default": {"channel": "email", "terms": "Quoted per engagement."}},
    }
    section.update(overrides)
    return ContactSettlementConfig.model_validate(section)


def _plan() -> tuple[dict[str, Any], str]:
    params = {
        "profile": "default",
        "channel": "email",
        "terms": "Quoted per engagement.",
        "claimant_principal": SELLER.model_dump(mode="json"),
    }
    option = {
        "option_id": derive_settlement_option_id(
            mechanism="contact-exchange.v1", asset="introduction", rates=[], params=params
        ),
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": params,
    }
    artifacts = contact_accepted_obligation_builder(
        _config(),
        option,
        {
            "buyer_principal": BUYER,
            "seller_principal": SELLER,
            "expiration_unix": 4_000_000_000,
        },
    )
    obligation = artifacts.obligation
    plan = {
        "obligations": [obligation],
        "service_terms": dict(artifacts.service_terms),
    }
    validated = SettlementPlan.model_validate(plan)
    ref = derive_obligation_ref(
        NEGOTIATION, 0, validated.obligations[0].model_dump(mode="json")
    )
    return validated.model_dump(mode="json"), ref


class Runtime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def register_plan(self, *, agreement_ref: str, obligations: list[Any]) -> None:
        self.calls.append("register")

    async def materialize(self, **_: Any) -> None:
        self.calls.append("materialize")

    async def bind_fulfillment(self, *_: Any, **__: Any) -> None:
        self.calls.append("bind")

    async def check(self, **_: Any) -> None:
        self.calls.append("check")

    async def collect(self, **_: Any) -> None:
        self.calls.append("collect")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteIntroductionStore:
    path = tmp_path / "storefront.db"
    conn = sqlite3.connect(path)
    try:
        for migration in CONTACT_EXCHANGE_MIGRATIONS:
            migration.apply(conn)
        conn.commit()
    finally:
        conn.close()
    return SQLiteIntroductionStore(path)


def _composition(
    store: SQLiteIntroductionStore,
    *,
    origin: str | None = "dc-west",
    config: ContactSettlementConfig | None = None,
    terminal_state: str = "success",
    known_origins: tuple[str, ...] = ("dc-west", "dc-east"),
    delivered: list[tuple[Mapping[str, Any], IntroductionAgreement]] | None = None,
) -> tuple[ContactExchangeComposition, Runtime, str]:
    plan, ref = _plan()
    runtime = Runtime()
    section = config or _config()

    async def load_thread(*, negotiation_id: str) -> Mapping[str, Any] | None:
        if negotiation_id != NEGOTIATION:
            return None
        return {"terminal_state": terminal_state, "settlement_plan": plan}

    async def load_obligation(obligation_ref: str) -> Mapping[str, Any] | None:
        return None

    async def load_origin(negotiation_id: str) -> str | None:
        return origin

    composition = ContactExchangeComposition(
        config=lambda: section,
        store=store,
        load_thread=load_thread,
        load_obligation=load_obligation,
        load_origin=load_origin,
        settlement_runtime=runtime,
        known_origins=known_origins,
        deliver=(
            (lambda projection, agreement: delivered.append((projection, agreement)))
            if delivered is not None
            else None
        ),
    )
    return composition, runtime, ref


async def _authorize(
    request_context: Any,
    operation: str,
    resource_id: str,
    allowed: tuple[Identity, ...],
    body: Mapping[str, Any] | None,
) -> AuthorizedIntroductionRequest:
    return AuthorizedIntroductionRequest(principal=request_context)


def _start(ref: str) -> IntroductionStart:
    return IntroductionStart(
        negotiation_id=NEGOTIATION,
        obligation_ref=ref,
        contact_payload={"email": "buyer@example.com"},
    )


@pytest.mark.parametrize(
    ("origin", "expected"),
    [("dc-west", "ops@west.example"), ("dc-east", "sales@east.example")],
)
async def test_a_reveal_carries_the_contact_of_its_own_origin(
    store, origin: str, expected: str
) -> None:
    composition, runtime, ref = _composition(store, origin=origin)
    projection = await composition.reveal_service(_authorize).start(BUYER, _start(ref))
    stored = await store.load(ref)
    assert stored is not None
    assert stored.seller_contact == {"email": expected}
    assert projection["counterparty_contact"] == {"email": expected}
    assert runtime.calls == ["register", "materialize", "bind", "check", "collect"]


async def test_an_origin_without_a_contact_refuses_before_persisting(store) -> None:
    delivered: list[Any] = []
    composition, runtime, ref = _composition(store, origin="dc-north", delivered=delivered)
    service = composition.reveal_service(_authorize)
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start(BUYER, _start(ref))
    assert caught.value.status_code == 503
    assert await store.load(ref) is None
    assert runtime.calls == []
    assert delivered == []


async def test_a_mismatched_obligation_ref_is_refused_without_a_payload(store) -> None:
    composition, _, ref = _composition(store)
    service = composition.reveal_service(_authorize)
    with pytest.raises(IntroductionRouteError) as caught:
        await service.start(BUYER, _start("0" * 64))
    assert caught.value.status_code == 404
    assert "does not match" in str(caught.value.detail)
    assert await store.load(ref) is None


async def test_an_unaccepted_deal_is_not_found(store) -> None:
    composition, _, ref = _composition(store, terminal_state="failure")
    with pytest.raises(IntroductionRouteError) as caught:
        await composition.reveal_service(_authorize).start(BUYER, _start(ref))
    assert caught.value.status_code == 404


async def test_the_seller_dispatch_sees_the_agreement_origin(store) -> None:
    delivered: list[tuple[Mapping[str, Any], IntroductionAgreement]] = []
    composition, _, ref = _composition(store, origin="dc-east", delivered=delivered)
    await composition.reveal_service(_authorize).start(BUYER, _start(ref))
    ((projection, agreement),) = delivered
    assert agreement.origin == "dc-east"
    assert projection["counterparty_contact"] == {"email": "buyer@example.com"}


async def test_redelivery_reads_the_durable_reveal_and_stops_after_deletion(store) -> None:
    composition, _, ref = _composition(store)
    await composition.reveal_service(_authorize).start(BUYER, _start(ref))
    record, agreement = await composition.load_revealed(ref)
    assert record.buyer_contact == {"email": "buyer@example.com"}
    assert agreement.origin == "dc-west"

    retention = composition.retention()
    assert retention is not None
    await retention.delete_one(ref)
    with pytest.raises(IntroductionPayloadsDeletedError):
        await composition.load_revealed(ref)


def test_construction_refuses_contacts_that_do_not_fit_the_origins(store) -> None:
    with pytest.raises(ValueError, match="dc-east"):
        _composition(store, known_origins=("dc-west",))
    single = ContactSettlementConfig.model_validate(
        {"enabled": True, "contact_payload": {"email": "one@x.example"}}
    )
    with pytest.raises(ValueError, match="one origin"):
        _composition(store, config=single)


def test_disabled_contact_exchange_offers_nothing(store) -> None:
    composition = ContactExchangeComposition(
        config=lambda: None,
        store=store,
        load_thread=None,  # type: ignore[arg-type]
        load_obligation=None,  # type: ignore[arg-type]
        load_origin=None,  # type: ignore[arg-type]
        settlement_runtime=Runtime(),
        known_origins=(),
    )
    assert composition.reveal_service(_authorize) is None
    assert composition.retention() is None
    assert composition.disclosures() == {}


def test_disclosures_state_the_retention_window(store) -> None:
    composition, _, _ = _composition(store, config=_config(retention_seconds=3600))
    assert composition.disclosures()["introduction_retention"]["window_seconds"] == 3600
