"""End-to-end introduction reveal on the bare-metal storefront surface."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi.testclient import TestClient
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_core.schemas import derive_settlement_option_id
from market_identity import (
    EMPTY_BODY,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)
from market_settlement_runtime import derive_obligation_ref

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
OUTSIDER_SIGNER = Eip191Signer(bytes.fromhex("44" * 32))

_SELLER_CONTACT = {"telegram": "@capacity_broker"}
_BUYER_CONTACT = {"email": "buyer@example.com"}


def _headers(
    signer: Eip191Signer,
    role: str,
    operation: str,
    resource_id: str,
    body: Any,
    *,
    method: str = "POST",
) -> dict[str, str]:
    signed = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource_id,
            request_id=f"test-{uuid.uuid4().hex}",
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }


def _contact_option() -> dict[str, Any]:
    params = {
        "profile": "default",
        "channel": "telegram",
        "terms": "Net-30, prose contract on request.",
        "claimant_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
    }
    return {
        "option_id": derive_settlement_option_id(
            mechanism=CONTACT_MECHANISM,
            asset="introduction",
            rates=[],
            params=params,
        ),
        "mechanism": CONTACT_MECHANISM,
        "asset": "introduction",
        "rates": [],
        "params": params,
    }


def _runtime(path: str) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        settlement_composition=(
            BareMetalStorefrontSettlementComposition.from_raw_config(
                {
                    "priority": [CONTACT_MECHANISM],
                    "contact": {
                        "enabled": True,
                        "contact_payload": dict(_SELLER_CONTACT),
                        "profiles": {
                            "default": {
                                "channel": "telegram",
                                "terms": "Net-30, prose contract on request.",
                            }
                        },
                    },
                }
            )
        ),
    )


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )


async def _insert_contact_listing(runtime: BareMetalStorefrontRuntime) -> dict:
    option = _contact_option()
    await runtime.db.upsert_bare_metal_listing(
        listing_id="intro-listing",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option],
    )
    return option


def _opening(option: dict) -> dict:
    return {
        "listing_id": "intro-listing",
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": {"duration_seconds": 3600, "access_method": "none"},
        },
        "proposal": {
            "settlement_selection": {
                "mechanism": CONTACT_MECHANISM,
                "option_id": option["option_id"],
                "expiration_unix": 1_900_000_000,
            },
            "fields": {},
        },
    }


def _accept_and_start(client: TestClient, option: dict) -> tuple[str, str, dict]:
    opening = _opening(option)
    response = client.post(
        "/api/v1/negotiate/new",
        json=opening,
        headers=_headers(
            BUYER_SIGNER, "buyer", "negotiate_new", "intro-listing", opening
        ),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action"] == "accept"
    negotiation_id = payload["negotiation_id"]
    plan = payload["settlement_plan"]
    obligation_ref = derive_obligation_ref(
        negotiation_id, 0, plan["obligations"][0]
    )
    start_body = {
        "negotiation_id": negotiation_id,
        "obligation_ref": obligation_ref,
        "contact_payload": dict(_BUYER_CONTACT),
    }
    started = client.post(
        "/api/v1/introductions",
        json=start_body,
        headers=_headers(
            BUYER_SIGNER, "buyer", "introduction_start", obligation_ref, start_body
        ),
    )
    assert started.status_code == 200, started.text
    return negotiation_id, obligation_ref, started.json()


async def test_introduction_start_reveals_and_completes(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with TestClient(_app(runtime)) as client:
        negotiation_id, obligation_ref, projection = _accept_and_start(client, option)
        assert projection["revealed"] is True
        assert projection["counterparty_contact"] == _SELLER_CONTACT
        assert projection["introduction"]["channel"] == "telegram"

        read = client.get(
            f"/api/v1/introductions/{obligation_ref}",
            headers=_headers(
                BUYER_SIGNER,
                "buyer",
                "introduction_read",
                obligation_ref,
                EMPTY_BODY,
                method="GET",
            ),
        )
        assert read.status_code == 200
        assert read.json()["counterparty_contact"] == _SELLER_CONTACT

        seller_read = client.get(
            f"/api/v1/introductions/{obligation_ref}",
            headers=_headers(
                SELLER_SIGNER,
                "seller",
                "introduction_read",
                obligation_ref,
                EMPTY_BODY,
                method="GET",
            ),
        )
        assert seller_read.status_code == 200
        assert seller_read.json()["counterparty_contact"] == _BUYER_CONTACT
    status = await runtime.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"


async def test_introduction_survives_a_storefront_restart(tmp_path) -> None:
    path = str(tmp_path / "storefront.db")
    runtime = _runtime(path)
    option = await _insert_contact_listing(runtime)
    with TestClient(_app(runtime)) as client:
        _, obligation_ref, _ = _accept_and_start(client, option)

    restarted = _runtime(path)
    with TestClient(_app(restarted)) as client:
        read = client.get(
            f"/api/v1/introductions/{obligation_ref}",
            headers=_headers(
                BUYER_SIGNER,
                "buyer",
                "introduction_read",
                obligation_ref,
                EMPTY_BODY,
                method="GET",
            ),
        )
        assert read.status_code == 200
        assert read.json()["counterparty_contact"] == _SELLER_CONTACT


async def test_reveal_refusals(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with TestClient(_app(runtime)) as client:
        unknown = "ee" * 32
        premature = client.get(
            f"/api/v1/introductions/{unknown}",
            headers=_headers(
                BUYER_SIGNER,
                "buyer",
                "introduction_read",
                unknown,
                EMPTY_BODY,
                method="GET",
            ),
        )
        assert premature.status_code == 404

        _, obligation_ref, _ = _accept_and_start(client, option)
        outsider = client.get(
            f"/api/v1/introductions/{obligation_ref}",
            headers=_headers(
                OUTSIDER_SIGNER,
                "buyer",
                "introduction_read",
                obligation_ref,
                EMPTY_BODY,
                method="GET",
            ),
        )
        assert outsider.status_code == 403
