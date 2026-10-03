"""Settlement by introduction on the VM storefront, over the signed wire.

The router is mounted behind the middleware a buyer really meets, so a passing
test means a buyer signing as ``core_buyer`` does, and holding only the
seller's pinned principal, can start and re-read an introduction. Contact
exchange is composed exactly as the lifespan composes it, over a real SQLite
database; only negotiation acceptance and the settlement runtime are stood in.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_contact_exchange import contact_accepted_obligation_builder
from market_core.schemas import SettlementPlan, derive_settlement_option_id
from market_settlement_runtime import SettlementObligationRecord, derive_obligation_ref

import market_storefront.container as _container
from market_storefront.contact_exchange import build_vm_contact_exchange
from market_storefront.controllers.introductions_controller import router
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.settlement_composition import build_storefront_settlement_registry
from market_storefront.utils.sqlite_client import SQLiteClient

# The buyer-signed transport and the seller-signature check the hosted wire
# test already pins to core_buyer's behaviour.
from .test_hosted_settlement_wire import (
    BUYER_SIGNER,
    INTRUDER_SIGNER,
    SELLER,
    SELLER_SIGNER,
    _assert_seller_signed,
    _call,
    _Repository,
)

NEGOTIATION_ID = "negotiation-introduction-1"
BUYER_CONTACT = {"email": "buyer@example.com"}
CONTACTS = {
    "dc-west": {"email": "ops@west.example"},
    "dc-east": {"email": "sales@east.example"},
}


class _Runtime:
    """The settlement-runtime operations an introduction drives, recorded."""

    def __init__(self) -> None:
        self.records: dict[str, SettlementObligationRecord] = {}
        self.calls: list[str] = []

    async def register_plan(self, *, agreement_ref: str, obligations: list[Any]):
        for index, obligation in enumerate(obligations):
            record = SettlementObligationRecord.from_obligation(
                agreement_ref=agreement_ref, obligation_index=index, obligation=obligation
            )
            self.records.setdefault(record.obligation_ref, record)
        self.calls.append("register")

    async def materialize(self, **_: Any) -> None:
        self.calls.append("materialize")

    async def bind_fulfillment(self, *_: Any, **__: Any) -> None:
        self.calls.append("bind")

    async def check(self, **_: Any) -> None:
        self.calls.append("check")

    async def collect(self, **_: Any) -> None:
        self.calls.append("collect")


def _settlement_config():
    raw = {
        "priority": ["contact-exchange.v1"],
        "contact": {
            "enabled": True,
            "origins": {
                origin: {"contact_payload": contact} for origin, contact in CONTACTS.items()
            },
            "profiles": {"default": {"channel": "email", "terms": "Quoted per engagement."}},
        },
    }
    return build_storefront_settlement_registry().resolve(raw, role="seller")


def _accepted_thread() -> tuple[dict[str, Any], str]:
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
    config = _settlement_config().mechanism_config("contact")
    artifacts = contact_accepted_obligation_builder(
        config,
        option,
        {
            "buyer_principal": BUYER_SIGNER.identity,
            "seller_principal": SELLER,
            "expiration_unix": 2_000_000_000,
        },
    )
    plan = SettlementPlan.model_validate(
        {
            "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
            "seller_principal": SELLER.model_dump(mode="json"),
            "obligations": [artifacts.obligation],
            "service_terms": dict(artifacts.service_terms),
        }
    )
    obligation = plan.obligations[0].model_dump(mode="json")
    thread = {"terminal_state": "success", "settlement_plan": plan.model_dump(mode="json")}
    return thread, derive_obligation_ref(NEGOTIATION_ID, 0, obligation)


@pytest_asyncio.fixture
async def wired(tmp_path, monkeypatch):
    thread, obligation_ref = _accepted_thread()
    origin = {"value": "dc-west"}
    db = SQLiteClient(
        db_path=str(tmp_path / "introductions.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )
    db.load_negotiation_thread_row = AsyncMock(return_value=thread)  # type: ignore[method-assign]
    db.load_thread_binding = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda **_: SimpleNamespace(site_id=origin["value"])
    )
    runtime = _Runtime()
    settlement = SimpleNamespace(
        settlement_config=_settlement_config(),
        repository=_Repository(runtime),
        runtime=runtime,
    )
    delivered: list[tuple[Any, Any]] = []
    composition = build_vm_contact_exchange(
        sqlite_client=db,
        settlement_composition=settlement,
        known_origins=tuple(CONTACTS),
        delivery=lambda projection, agreement: delivered.append((projection, agreement)),
    )
    monkeypatch.setattr(_container, "resolved_sqlite_client", db)
    monkeypatch.setattr(_container, "resolved_marketplace_signer", SELLER_SIGNER)
    monkeypatch.setattr(_container, "resolved_contact_exchange", composition)

    app = FastAPI()
    app.middleware("http")(listing_lifecycle_middleware)
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            obligation_ref=obligation_ref,
            runtime=runtime,
            composition=composition,
            delivered=delivered,
            origin=origin,
        )


async def _start(wired, *, obligation_ref=None, signer=BUYER_SIGNER, request_id=None):
    ref = obligation_ref or wired.obligation_ref
    return await _call(
        wired.client,
        method="POST",
        path="/api/v1/introductions",
        operation="introduction_start",
        resource=ref,
        body={
            "negotiation_id": NEGOTIATION_ID,
            "obligation_ref": ref,
            "contact_payload": BUYER_CONTACT,
        },
        signer=signer,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_an_accepted_introduction_reveals_signed_and_collects(wired) -> None:
    status, payload, headers, request_id = await _start(wired)

    assert status == 200, payload
    _assert_seller_signed(
        status=status,
        payload=payload,
        headers=headers,
        method="POST",
        operation="introduction_start",
        resource=wired.obligation_ref,
        request_id=request_id,
    )
    assert payload["counterparty_contact"] == CONTACTS["dc-west"]
    record = wired.runtime.records[wired.obligation_ref]
    assert record.agreement_ref == NEGOTIATION_ID
    # Collected through the settlement runtime; nothing reached VM fulfillment.
    assert wired.runtime.calls == ["register", "materialize", "bind", "check", "collect"]
    ((projection, agreement),) = wired.delivered
    assert agreement.origin == "dc-west"
    assert projection["counterparty_contact"] == BUYER_CONTACT


@pytest.mark.asyncio
async def test_the_reveal_is_re_readable_and_an_exact_retry_replays(wired) -> None:
    status, first, _headers, request_id = await _start(wired)
    assert status == 200, first
    status, again, _headers, _ = await _start(wired, request_id=request_id)
    assert status == 200, again
    assert again == first

    status, payload, headers, request_id = await _call(
        wired.client,
        method="GET",
        path=f"/api/v1/introductions/{wired.obligation_ref}",
        operation="introduction_read",
        resource=wired.obligation_ref,
    )
    assert status == 200, payload
    _assert_seller_signed(
        status=status,
        payload=payload,
        headers=headers,
        method="GET",
        operation="introduction_read",
        resource=wired.obligation_ref,
        request_id=request_id,
    )
    assert payload["counterparty_contact"] == CONTACTS["dc-west"]


@pytest.mark.asyncio
async def test_a_mismatched_obligation_is_refused_with_no_payload(wired) -> None:
    status, payload, _headers, _ = await _start(wired, obligation_ref="0" * 64)
    assert status == 404, payload
    assert "ops@west.example" not in str(payload)
    assert wired.runtime.records == {}


@pytest.mark.asyncio
async def test_an_outsider_cannot_start_the_introduction(wired) -> None:
    status, payload, _headers, _ = await _start(wired, signer=INTRUDER_SIGNER)
    assert status in {401, 403}, payload
    assert "ops@west.example" not in str(payload)


@pytest.mark.asyncio
async def test_each_origin_reveals_its_own_seller(wired) -> None:
    wired.origin["value"] = "dc-east"
    status, payload, _headers, _ = await _start(wired)
    assert status == 200, payload
    assert payload["counterparty_contact"] == CONTACTS["dc-east"]
    assert "west.example" not in str(payload)


@pytest.mark.asyncio
async def test_an_origin_without_a_contact_is_refused_before_anything_happens(wired) -> None:
    wired.origin["value"] = "dc-north"
    status, payload, _headers, _ = await _start(wired)
    assert status == 503, payload
    assert payload["detail"]["code"] == "seller_contact_unavailable"
    assert await wired.composition.store.load(wired.obligation_ref) is None
    assert wired.runtime.records == {}
    assert wired.delivered == []


@pytest.mark.asyncio
async def test_retention_disclosure_and_deleted_outcome(wired) -> None:
    status, _payload, _headers, _ = await _start(wired)
    assert status == 200
    disclosure = wired.composition.disclosures()["introduction_retention"]
    assert disclosure["scope"] == "introduction_record"

    deleted = await wired.composition.retention().delete_one(wired.obligation_ref)
    assert deleted["payloads_deleted_at"]
    status, payload, _headers, _ = await _call(
        wired.client,
        method="GET",
        path=f"/api/v1/introductions/{wired.obligation_ref}",
        operation="introduction_read",
        resource=wired.obligation_ref,
    )
    assert status == 410, payload
    assert payload["detail"]["code"] == "introduction_payloads_deleted"
    # The obligation itself is untouched by deleting its payloads.
    assert wired.obligation_ref in wired.runtime.records

