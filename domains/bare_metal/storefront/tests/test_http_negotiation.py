from __future__ import annotations

import time
import base64
from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_settlement_runtime import derive_obligation_ref
from market_identity import (
    AuthenticatedResponse,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

from arkhai_bare_metal import (
    BareMetalHostedOptionFacts,
    decode_bare_metal_hosted_option_facts,
    CanonicalPrincipal,
    bind_bare_metal_hosted_option,
)
from arkhai_bare_metal_storefront.hosted_lifecycle import (
    BareMetalHostedLifecycleCallbacks,
)
from arkhai_bare_metal_storefront.hosted_routes import lifecycle_domain_callbacks
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )


PRIVATE_KEY = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
BUYER_SIGNER = Eip191Signer(PRIVATE_KEY)
BUYER = BUYER_SIGNER.identity.identifier
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
ESCROW = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"


def _headers(
    operation: str,
    resource_id: str,
    body: dict,
    *,
    method: str = "POST",
) -> dict[str, str]:
    timestamp = int(time.time())
    request_id = f"test-{uuid.uuid4().hex}"
    signed = sign_request(
        signer=BUYER_SIGNER,
        envelope=RequestEnvelope(
            role="buyer",
            principal=BUYER_SIGNER.identity,
            method=method,
            operation=operation,
            resource=resource_id,
            request_id=request_id,
            timestamp=timestamp,
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


def _runtime(path: str) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(
            identities=(ADMIN_SIGNER.identity,),
        ),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address="0x3333333333333333333333333333333333333333",
        plan_builder=lambda **kwargs: {
            "settlement_plan": {
                "buyer_principal": kwargs["buyer_principal"].model_dump(mode="json"),
                "seller_principal": kwargs["seller_principal"].model_dump(mode="json"),
                "obligations": [],
            },
            "accepted_escrow_terms": [],
        },
    )


async def _insert_listing(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id="listing-1",
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
            "min_duration_seconds": 60,
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": ESCROW,
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            },
        ],
    )


def _hosted_option() -> SettlementOption:
    now = datetime.now(timezone.utc)
    claimant = CanonicalPrincipal(
        scheme=SELLER_SIGNER.identity.scheme.value,
        identifier=SELLER_SIGNER.identity.identifier,
    )
    params = {
        "account_ref": "seller-main",
        "authority_id": "authority-main",
        "country": "US",
        "environment": "test",
        "claimant_principal": claimant.model_dump(mode="json"),
        "condition": {
            "condition_id": "bare-metal-lease-ready",
            "evaluator": {
                "kind": "builtin.v1",
                "version": "trivial.v1",
                "params": {"kind": "trivial"},
            },
            "demand": {"encoding": "application/jcs+json", "value": {}},
        },
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "funds_flow": "separate_charges_transfers",
        "contract_fingerprint": "sha256:" + "ab" * 32,
    }
    rates = [RateValue(field="amount", per="hour", value=120)]
    base = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )
    facts = BareMetalHostedOptionFacts(
        derivation_key="site-a:resource-1",
        projection_digest="sha256:" + "cd" * 32,
        site_id="site-a",
        executor_kind="bare_metal",
        resource_selection="specific",
        physical_resource_id="resource-1",
        physical_host_id="physical-host-1",
        pool_id="pool-a",
        offer_expires_at=now + timedelta(hours=2),
        funding_deadline=now + timedelta(hours=1),
        fulfillment_deadline=now + timedelta(hours=1, minutes=30),
    )
    return bind_bare_metal_hosted_option(base, facts=facts).option


async def _insert_hosted_listing(
    runtime: BareMetalStorefrontRuntime,
    *,
    options: list[SettlementOption] | None = None,
) -> SettlementOption:
    selected = _hosted_option()
    advertised = options if options is not None else [selected]
    await runtime.db.upsert_bare_metal_listing(
        listing_id="hosted-listing",
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
            "min_duration_seconds": 60,
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[],
        settlement_options=[option.model_dump(mode="json") for option in advertised],
    )
    return advertised[0]


def _hosted_opening(
    option: SettlementOption,
    *,
    selection: SettlementSelection | None = None,
) -> dict:
    facts = decode_bare_metal_hosted_option_facts(option.params.get("bare_metal"))
    selected = selection or SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=int(facts.funding_deadline.timestamp()),
    )
    ssh_key = "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()
    return {
        "listing_id": "hosted-listing",
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": {
                "duration_seconds": 5400,
                "access_method": "ssh",
                "ssh_public_key": ssh_key,
            },
        },
        "proposal": {
            "settlement_selection": selected.model_dump(mode="json"),
            "fields": {"amount": "180"},
        },
    }


def _opening(*, payload: dict | None = None) -> dict:
    return {
        "listing_id": "listing-1",
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": payload
            or {
                "duration_seconds": 3600,
                "access_method": "ssh",
                "ssh_public_key": "ssh-ed25519 buyer-key",
            },
        },
        "proposal": {
            "chain_name": "anvil",
            "escrow_address": ESCROW,
            "fields": {"amount": "100", "token": TOKEN},
            "literal_fields": {"token": TOKEN},
            "expiration_unix": int(time.time()) + 3600,
        },
    }


async def test_signed_opening_accepts_and_persists_domain_artifacts(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    opening = _opening()
    opening.pop("buyer_agent_url")
    app = _app(runtime)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/negotiate/new",
            json=opening,
            headers=_headers("negotiate_new", "listing-1", opening),
        )
        negotiation_id = response.json()["negotiation_id"]
        listing_threads = client.get(
            "/api/v1/listings/listing-1/negotiations",
        )
        detail = client.get(
            f"/api/v1/listings/listing-1/negotiations/{negotiation_id}",
        )

    assert response.status_code == 200
    assert response.json()["action"] == "accept"
    assert response.json()["accepted_provision_terms"] == _opening()["provision_terms"]
    assert response.json()["settlement_plan"] == {
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "seller_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "obligations": [],
        "service_terms": {},
    }
    assert listing_threads.json()["count"] == 1
    assert detail.json()["terminal_state"] == "success"
    assert detail.json()["round_count"] == 2
    assert (
        await runtime.db.load_bare_metal_message(
            negotiation_id=negotiation_id,
        )
    ).ssh_public_key == "ssh-ed25519 buyer-key"
    assert (
        await runtime.db.load_bare_metal_terms(
            negotiation_id=negotiation_id,
        )
    ).machine_id == "machine-1"
    binding = await runtime.db.load_thread_binding(
        negotiation_id=negotiation_id,
    )
    assert binding.site_id == "site-a"
    assert binding.listing_id == "listing-1"
    assert binding.binding.offering_mode == "bare_metal"
    assert str(binding.binding.domain_identity) == "bare_metal.v1"


async def test_hosted_only_opening_derives_exact_plan_and_first_binding(
    tmp_path,
) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_hosted_listing(runtime)
    opening = _hosted_opening(option)

    with TestClient(_app(runtime)) as client:
        response = client.post(
            "/api/v1/negotiate/new",
            json=opening,
            headers=_headers("negotiate_new", "hosted-listing", opening),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "accept"
    assert payload["accepted_escrow_proposal"] is None
    assert (
        payload["settlement_selection"] == opening["proposal"]["settlement_selection"]
    )
    plan = SettlementPlan.model_validate(payload["settlement_plan"])
    obligation = plan.obligations[0]
    assert obligation.amount == 180
    assert obligation.params.get("funding_profile") == "card.v1"
    assert "bare_metal" not in obligation.params
    assert plan.service_terms["bare_metal.v1"]["listing_id"] == "hosted-listing"
    assert plan.service_terms["bare_metal.v1"]["option_id"] == option.option_id
    obligation_ref = derive_obligation_ref(
        payload["negotiation_id"],
        0,
        obligation.model_dump(mode="json"),
    )

    lifecycle = BareMetalHostedLifecycleCallbacks(
        db=runtime.db,
        runtime=None,
        local_principal=SELLER_SIGNER.identity,
        capacity_client=None,
        fulfillment_client=None,
        publish_evidence=None,
    )
    accepted = await lifecycle_domain_callbacks(
        db=runtime.db,
        lifecycle=lifecycle,
    ).prepare(payload["negotiation_id"], obligation_ref, None)
    persisted = await runtime.db.load_bare_metal_hosted_lifecycle(
        obligation_ref=obligation_ref
    )

    assert accepted.obligation.amount == 180
    assert persisted is not None
    assert persisted.accepted_binding.option.option.option_id == option.option_id
    assert persisted.capacity_reservation_id is None


async def test_hosted_opening_rejects_mutated_and_ambiguous_selection(
    tmp_path,
) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_hosted_listing(runtime)
    facts = decode_bare_metal_hosted_option_facts(option.params.get("bare_metal"))
    mutated = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=int(facts.funding_deadline.timestamp()) + 1,
    )
    mutated_opening = _hosted_opening(option, selection=mutated)
    ambiguous_opening = _hosted_opening(option)
    ambiguous_opening["settlement_selection"] = mutated.model_dump(mode="json")

    with TestClient(_app(runtime)) as client:
        mutated_response = client.post(
            "/api/v1/negotiate/new",
            json=mutated_opening,
            headers=_headers(
                "negotiate_new",
                "hosted-listing",
                mutated_opening,
            ),
        )
        ambiguous_response = client.post(
            "/api/v1/negotiate/new",
            json=ambiguous_opening,
            headers=_headers(
                "negotiate_new",
                "hosted-listing",
                ambiguous_opening,
            ),
        )

    assert mutated_response.status_code == 400
    assert ambiguous_response.status_code == 400


async def test_auth_and_domain_failures_write_no_thread(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = _app(runtime)
    invalid = _opening(
        payload={
            "duration_seconds": 3600,
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer-key",
            "access_ref": {"url": "https://buyer.invalid"},
        },
    )

    with TestClient(app) as client:
        unsigned = client.post("/api/v1/negotiate/new", json=_opening())
        rejected = client.post(
            "/api/v1/negotiate/new",
            json=invalid,
            headers=_headers("negotiate_new", "listing-1", invalid),
        )
        threads = client.get("/api/v1/listings/listing-1/negotiations")

    assert unsigned.status_code == 401
    assert rejected.status_code == 400
    assert threads.json()["count"] == 0


async def test_durable_pause_blocks_new_negotiation(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    await runtime.db.set_global_paused(paused=True)
    app = _app(runtime)

    with TestClient(app) as client:
        opening = _opening()
        response = client.post(
            "/api/v1/negotiate/new",
            json=opening,
            headers=_headers("negotiate_new", "listing-1", opening),
        )

    assert response.status_code == 503


async def test_a_refused_caller_can_verify_the_refusal(tmp_path) -> None:
    """An unsigned refusal is discarded by a caller that pins the storefront.

    The caller then knows only that the answer was unreadable, which is the one
    thing that does not help it. Binding the route's own operation and resource
    plus the caller's request identity costs nothing that depends on trust.
    """

    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    opening = _opening()
    # A resource the route did not derive: authentication refuses this before
    # any handler runs, which is exactly where the signing state was missing.
    headers = _headers("negotiate_new", "listing-not-this-one", opening)

    with TestClient(_app(runtime)) as client:
        refused = client.post("/api/v1/negotiate/new", json=opening, headers=headers)

    assert refused.status_code == 403
    payload = refused.json()
    signed = AuthenticatedResponse.model_validate(
        {
            "protocol": refused.headers["X-Market-Signature-Version"],
            "role": refused.headers["X-Market-Role"],
            "principal": {
                "scheme": refused.headers["X-Market-Identity-Scheme"],
                "identifier": refused.headers["X-Market-Identity-Identifier"],
            },
            "method": "POST",
            "operation": "negotiate_new",
            "resource": "listing-1",
            "request_id": refused.headers["X-Market-Request-ID"],
            "timestamp": int(refused.headers["X-Market-Timestamp"]),
            "status": refused.status_code,
            "body_hash": canonical_body_hash(payload),
            "proof": {
                "scheme": refused.headers["X-Market-Identity-Scheme"],
                "value": refused.headers["X-Market-Signature"],
            },
        }
    )
    verification = verify_response(
        signed,
        body=payload,
        now=int(time.time()),
        max_skew=300,
        expected_role="seller",
        expected_principals=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        expected_method="POST",
        expected_operation="negotiate_new",
        expected_resource="listing-1",
        expected_request_id=headers["X-Market-Request-ID"],
    )
    assert verification.verified, verification.code
    assert refused.headers["X-Market-Request-ID"] == headers["X-Market-Request-ID"]


async def test_a_caller_with_no_request_identity_is_refused_unsigned(tmp_path) -> None:
    """Nothing to bind: a proof over an invented identity verifies against nothing."""

    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)

    with TestClient(_app(runtime)) as client:
        refused = client.post("/api/v1/negotiate/new", json=_opening())

    assert refused.status_code == 401
    assert "X-Market-Signature" not in refused.headers
