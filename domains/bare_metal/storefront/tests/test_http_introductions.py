"""End-to-end introduction reveal on the bare-metal storefront surface."""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
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
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from core_buyer.introductions import IntroductionTransport
from loopback import serving
from source_sites import SourceSites
from storefront_client import StorefrontClient

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
        # Openings recheck each listing against the site that published it.
        capacity_client=SourceSites(),
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
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
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
            "kind": "bare_metal.v2",
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


def _introductions(base_url: str, signer=BUYER_SIGNER) -> IntroductionTransport:
    """The production buyer's introduction client, pointed at ``base_url``."""
    return IntroductionTransport(
        seller_url=base_url,
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(SELLER_SIGNER.identity,)
        ),
    )


async def _accept_and_start(base_url: str, option: dict) -> tuple[str, str, dict]:
    """Accept the contact listing and reveal, through the buyer's typed clients."""
    opening = _opening(option)
    async with StorefrontClient(
        base_url,
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    ) as storefront:
        payload = await storefront.negotiate_new(
            listing_id=opening["listing_id"],
            initial_amount=None,
            provision_terms=opening["provision_terms"],
            proposal_fields=opening["proposal"]["fields"],
            settlement_selection=opening["proposal"]["settlement_selection"],
            selection_only=True,
            buyer_agent_url=opening["buyer_agent_url"],
        )
    assert payload["action"] == "accept"
    negotiation_id = payload["negotiation_id"]
    plan = payload["settlement_plan"]
    obligation_ref = derive_obligation_ref(
        negotiation_id, 0, plan["obligations"][0]
    )
    started = _introductions(base_url).start(
        negotiation_id=negotiation_id,
        obligation_ref=obligation_ref,
        contact_payload=dict(_BUYER_CONTACT),
    )
    return negotiation_id, obligation_ref, started


async def test_contact_options_publish_through_the_composition() -> None:
    from datetime import datetime, timedelta, timezone

    from market_settlement_runtime import SettlementPublicationClause

    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
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
        },
        resources={
            "claimant_principal": SELLER_SIGNER.identity,
        },
    )
    now = datetime.now(timezone.utc)
    payload = await composition.publication_payload(
        candidate={"host_id": "machine-1"},
        clauses=[
            SettlementPublicationClause(
                mechanism=CONTACT_MECHANISM,
                asset="introduction",
                mechanism_input={"profile": "default"},
            )
        ],
        option_expires_at=now + timedelta(hours=2),
        funding_deadlines={},
        fulfillment_deadline=now + timedelta(hours=3),
    )
    assert payload.accepted_escrows == ()
    (option,) = payload.settlement_options
    assert option["mechanism"] == CONTACT_MECHANISM
    assert option["rates"] == []
    assert "@capacity_broker" not in str(payload.settlement_options)


async def test_introduction_start_reveals_and_completes(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    app = _app(runtime)
    with serving(app) as base_url:
        negotiation_id, obligation_ref, projection = await _accept_and_start(
            base_url, option
        )
        read = _introductions(base_url).read(obligation_ref=obligation_ref)
    assert projection["revealed"] is True
    assert projection["counterparty_contact"] == _SELLER_CONTACT
    assert projection["introduction"]["channel"] == "telegram"
    assert read["counterparty_contact"] == _SELLER_CONTACT

    # Deferred debt, not an exemption: no typed client reads an introduction as
    # the seller, so the seller's read is hand-built until one exists.
    with TestClient(app) as client:
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
    with serving(_app(runtime)) as base_url:
        _, obligation_ref, _ = await _accept_and_start(base_url, option)

    with serving(_app(_runtime(path))) as base_url:
        read = _introductions(base_url).read(obligation_ref=obligation_ref)
    assert read["counterparty_contact"] == _SELLER_CONTACT


async def test_reveal_refusals(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        with pytest.raises(RuntimeError, match="404"):
            _introductions(base_url).read(obligation_ref="ee" * 32)

        _, obligation_ref, _ = await _accept_and_start(base_url, option)
        with pytest.raises(RuntimeError, match="403"):
            _introductions(base_url, OUTSIDER_SIGNER).read(obligation_ref=obligation_ref)
