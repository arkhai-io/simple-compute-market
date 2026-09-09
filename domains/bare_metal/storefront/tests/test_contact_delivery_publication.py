"""Versioned publication preflight and historical seller-dispatch exclusion."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from arkhai_bare_metal_storefront.contact_offers import (
    NOTICE,
    ContactDeliveryOffers,
    ContactOffers,
    ContactPublicationError,
    _check_existing,
    prepare_contact_offers,
)
from arkhai_bare_metal_storefront.delivery import redeliver_introduction
from arkhai_bare_metal_storefront.introduction_routes import legacy_delivery_allowed
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from fastapi.testclient import TestClient
from market_contact_exchange import IntroductionAgreement
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY
from market_settlement_runtime import derive_obligation_ref
from test_contact_only_runtime import BUYER, CONFIG, SELLER
from test_contact_only_runtime import environment as environment
from test_http_introductions import _app, _headers, _opening


def document(version=2):
    value = json.loads(
        (Path(__file__).parents[1] / "examples/contact-offers.json").read_text()
    )
    if version == 2:
        value["schema_version"] = 2
        value["delivery_policy"] = POLICY
        for offer in value["offers"]:
            offer["listing_id"] = offer["listing_id"].replace(
                "synthetic-contact-", "synthetic-contact-delivery-"
            )
        return ContactDeliveryOffers.model_validate(value)
    return ContactOffers.model_validate(value)


def configure(monkeypatch, version=2):
    raw = copy.deepcopy(CONFIG)
    for offer in document(version).offers:
        raw["contact"]["profiles"][offer.profile] = {
            "channel": "email",
            "terms": NOTICE,
        }
        if version == 2:
            raw["contact"]["profiles"][offer.profile]["delivery_policy"] = POLICY
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(raw))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_DELIVERY", json.dumps(DELIVERY_CONFIG))
    return raw


async def store(runtime, item):
    await runtime.db.upsert_bare_metal_listing(
        listing_id=item.offer.listing_id,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        listing=item.offer.listing(),
        accepted_escrows=[],
        settlement_options=item.request.settlement_options,
        site_id=None,
        pool_id=None,
        physical_resource_id=None,
        publication_intent=item.intent,
    )


async def test_v2_whole_file_config_policy_privacy_and_immutable_intent(
    environment, monkeypatch
):
    raw = configure(monkeypatch)
    runtime = build_runtime_from_environment()
    entries = await prepare_contact_offers(runtime, document())
    assert len(entries) == 5
    assert all(item.intent["schema_version"] == 2 for item in entries)
    item = entries[0]
    await store(runtime, item)
    assert await _check_existing(runtime, item)
    # An actual old shape lacks inner schema_version; it is never upgraded.
    old = replace(
        item,
        intent={
            k: v
            for k, v in item.intent.items()
            if k not in {"schema_version", "delivery_policy"}
        },
    )
    with pytest.raises(ContactPublicationError):
        await _check_existing(runtime, old)
    contaminated = document().model_dump()
    contaminated["offers"][-1]["name"] = (
        "SYNTHETIC TEST " + DELIVERY_CONFIG["seller_route"]["address"]
    )
    with pytest.raises(ContactPublicationError) as error:
        await prepare_contact_offers(
            runtime, ContactDeliveryOffers.model_validate(contaminated)
        )
    assert error.value.listing_id is None
    assert DELIVERY_CONFIG["seller_route"]["address"] not in str(error.value)
    object.__setattr__(runtime, "contact_delivery_config", None)
    with pytest.raises(ContactPublicationError):
        await prepare_contact_offers(runtime, document())
    for profile in raw["contact"]["profiles"].values():
        profile.pop("delivery_policy", None)
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(raw))
    with pytest.raises(ContactPublicationError):
        await prepare_contact_offers(build_runtime_from_environment(), document())


async def test_historical_publication_blocks_first_dispatch_and_redelivery_without_changing_reveal(
    environment, monkeypatch
):
    configure(monkeypatch, version=1)
    runtime = build_runtime_from_environment()
    item = (await prepare_contact_offers(runtime, document(1)))[0]
    assert set(item.intent) == {"offer", "settlement_options"}
    await store(runtime, item)
    delivered = []
    object.__setattr__(
        runtime, "introduction_delivery", lambda *args: delivered.append(args)
    )
    # Use the real accepted-party authority and the actual old immutable intent.
    with TestClient(_app(runtime)) as client:
        opening = _opening(item.request.settlement_options[0])
        opening["listing_id"] = item.offer.listing_id
        opening["buyer_principal"] = BUYER.identity.model_dump(mode="json")
        response = client.post(
            "/api/v1/negotiate/new",
            json=opening,
            headers=_headers(
                BUYER, "buyer", "negotiate_new", item.offer.listing_id, opening
            ),
        )
        assert response.status_code == 200, response.text
        accepted = response.json()
        ref = derive_obligation_ref(
            accepted["negotiation_id"], 0, accepted["settlement_plan"]["obligations"][0]
        )
        body = {
            "negotiation_id": accepted["negotiation_id"],
            "obligation_ref": ref,
            "contact_payload": {"name": "Synthetic buyer"},
        }
        response = client.post(
            "/api/v1/introductions",
            json=body,
            headers=_headers(BUYER, "buyer", "introduction_start", ref, body),
        )
        assert response.status_code == 200, response.text
    assert delivered == []
    restarted = build_runtime_from_environment()
    with pytest.raises(ValueError, match="not authorized"):
        await redeliver_introduction(restarted.db, ref, ())
    record = await restarted.db.load_contact_introduction(obligation_ref=ref)
    assert record is not None and record.buyer_contact == body["contact_payload"]
    agreement = IntroductionAgreement(
        agreement_ref=accepted["negotiation_id"],
        obligation_ref=ref,
        buyer_principal=BUYER.identity,
        seller_principal=SELLER.identity,
        introduction_package=record.introduction_package,
    )
    assert not await legacy_delivery_allowed(restarted.db, agreement)
    assert not await legacy_delivery_allowed(
        restarted.db,
        replace(
            agreement,
            introduction_package={
                **record.introduction_package,
                "listing_id": "unrelated",
            },
        ),
    )
    assert not await legacy_delivery_allowed(
        restarted.db,
        replace(
            agreement,
            introduction_package={
                **record.introduction_package,
                "delivery_policy": {"kind": "unknown"},
            },
        ),
    )
