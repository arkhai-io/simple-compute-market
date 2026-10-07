from __future__ import annotations

import time
import base64
from datetime import datetime, timedelta, timezone
import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from storefront_client import StorefrontClient, StorefrontClientError
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
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from source_sites import SourceSite, SourceSites, listing_source_projection


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
        # Openings recheck each listing against the site that published it.
        capacity_client=SourceSites(),
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
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
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
        offering_mode="bare_metal",
        resource_selection="specific",
        physical_resource_id="resource-1",
        physical_host_id="physical-host-1",
        pool_id="pool-a",
        option_expires_at=now + timedelta(hours=2),
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
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
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
            "kind": "bare_metal.v2",
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
            "kind": "bare_metal.v2",
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


def _typed(app, signer, role: str) -> StorefrontClient:
    """The canonical storefront client over the in-process app.

    Responses are verified against the storefront's own marketplace signer.
    """
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _negotiate(client: StorefrontClient, *, payload: dict | None = None) -> dict:
    """Open on the seeded Alkahest listing through the typed client."""
    opening = _opening(payload=payload)
    return await client.negotiate_new(
        listing_id=opening["listing_id"],
        initial_amount=100,
        provision_terms=opening["provision_terms"],
        token=TOKEN,
        chain_name="anvil",
        escrow_address=ESCROW,
        proposal_fields={"token": TOKEN},
    )


async def _negotiate_hosted(client: StorefrontClient, opening: dict) -> dict:
    """Open on the seeded hosted listing with an exact selection and no escrow."""
    return await client.negotiate_new(
        listing_id=opening["listing_id"],
        initial_amount=None,
        provision_terms=opening["provision_terms"],
        proposal_fields=opening["proposal"]["fields"],
        settlement_selection=opening["proposal"]["settlement_selection"],
        selection_only=True,
    )


async def test_signed_opening_accepts_and_persists_domain_artifacts(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            payload = await _negotiate(buyer)
        negotiation_id = payload["negotiation_id"]
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            listing_threads = await admin.list_negotiations("listing-1")
            detail = await admin.get_negotiation("listing-1", negotiation_id)

    assert payload["action"] == "accept"
    assert payload["accepted_provision_terms"] == _opening()["provision_terms"]
    assert payload["settlement_plan"] == {
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "seller_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "obligations": [],
        "service_terms": {},
    }
    assert listing_threads.count == 1
    assert detail.terminal_state == "success"
    assert detail.round_count == 2
    assert (
        await runtime.db.load_bare_metal_message(
            negotiation_id=negotiation_id,
        )
    ).ssh_public_key == "ssh-ed25519 buyer-key"
    assert (
        await runtime.db.load_bare_metal_terms(
            negotiation_id=negotiation_id,
        )
    ).host_id == "machine-1"
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

    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            payload = await _negotiate_hosted(buyer, opening)

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
    assert plan.service_terms["bare_metal.v2"]["listing_id"] == "hosted-listing"
    assert plan.service_terms["bare_metal.v2"]["option_id"] == option.option_id
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
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate_hosted(buyer, _hosted_opening(option, selection=mutated))
    assert refused.value.status_code == 400

    # Rejection path: a selection stated both inside the proposal and beside it
    # is one the typed client cannot construct, so the server's refusal of it is
    # checked with a hand-built request, on its status only.
    ambiguous_opening = _hosted_opening(option)
    ambiguous_opening["settlement_selection"] = mutated.model_dump(mode="json")
    with TestClient(app) as client:
        ambiguous_response = client.post(
            "/api/v1/negotiate/new",
            json=ambiguous_opening,
            headers=_headers("negotiate_new", "hosted-listing", ambiguous_opening),
        )
    assert ambiguous_response.status_code == 400


async def test_auth_and_domain_failures_write_no_thread(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = _app(runtime)

    # Rejection path: an unsigned request is one the typed client never sends.
    with TestClient(app) as client:
        unsigned = client.post("/api/v1/negotiate/new", json=_opening())
    assert unsigned.status_code == 401

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as rejected:
                await _negotiate(
                    buyer,
                    payload={
                        "duration_seconds": 3600,
                        "access_method": "ssh",
                        "ssh_public_key": "ssh-ed25519 buyer-key",
                        "access_ref": {"url": "https://buyer.invalid"},
                    },
                )
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            threads = await admin.list_negotiations("listing-1")

    assert rejected.value.status_code == 400
    assert threads.count == 0


async def test_a_trading_pause_blocks_new_negotiation(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    runtime.trading_pause.pause()
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate(buyer)

    assert refused.value.status_code == 503


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


async def _open_against(tmp_path, site: SourceSite):
    """Open a negotiation on the seeded listing, its site answering ``site``.

    Returns the refusal the typed client raised, the thread count the
    administrator then reads, and the site double.
    """
    runtime = replace(
        _runtime(str(tmp_path / "storefront.db")), capacity_client=SourceSites(site)
    )
    await _insert_listing(runtime)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate(buyer)
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            threads = await admin.list_negotiations("listing-1")
    return refused.value, threads.count, site


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param(
            listing_source_projection(capacity={"units": 1, "gpu_count": 4, "ram_gb": 2048}),
            id="fewer GPUs declared",
        ),
        pytest.param(listing_source_projection(gpu_model="B200"), id="model changed"),
        pytest.param(listing_source_projection(region="eu-central"), id="region moved"),
        pytest.param(listing_source_projection(resource_id="resource-2"), id="resource gone"),
    ],
)
async def test_an_opening_on_a_listing_its_source_no_longer_supports_is_refused(
    tmp_path, projection
) -> None:
    refused, threads, site = await _open_against(tmp_path, SourceSite(projection))

    assert refused.status_code == 409
    assert "no_matching_declaration" in str(refused)
    assert threads == 0
    assert site.calls == 1


async def test_an_opening_whose_site_cannot_answer_is_refused_as_retryable(tmp_path) -> None:
    refused, threads, _ = await _open_against(
        tmp_path, SourceSite(error=ConnectionError("site unreachable"))
    )

    assert refused.status_code == 503
    # The refusal names no source detail; the seller's log carries it.
    assert "listing_source_unverifiable" in str(refused)
    assert threads == 0


async def test_an_opening_with_no_site_authority_is_refused_as_retryable(tmp_path) -> None:
    runtime = replace(_runtime(str(tmp_path / "storefront.db")), capacity_client=None)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate(buyer)

    assert refused.value.status_code == 503


async def test_a_hosted_opening_on_a_listing_its_source_no_longer_supports_is_refused(
    tmp_path,
) -> None:
    """The guard runs before the Alkahest and hosted paths branch."""
    runtime = replace(
        _runtime(str(tmp_path / "storefront.db")),
        capacity_client=SourceSites(SourceSite(listing_source_projection(gpu_model="B200"))),
    )
    option = await _insert_hosted_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate_hosted(buyer, _hosted_opening(option))

    assert refused.value.status_code == 409
    assert "no_matching_declaration" in str(refused.value)


# ---------------------------------------------------------------------------
# Rounds, acceptance, and the listing's source after the opening
# ---------------------------------------------------------------------------

_COUNTERING_CHAIN = ["escrow_shape_guard", "bisection"]


def _countering_runtime(path: str, site: SourceSite) -> BareMetalStorefrontRuntime:
    """A storefront whose seller counters below the listed rate, as the lane's does."""
    return replace(
        _runtime(path),
        negotiation_policies=_COUNTERING_CHAIN,
        capacity_client=SourceSites(site),
    )


def _escrow_proposal(amount: int) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": ESCROW,
        "fields": {"amount": str(amount), "token": TOKEN},
        "literal_fields": {"token": TOKEN},
        "expiration_unix": int(time.time()) + 3600,
    }


async def _open_countered(buyer: StorefrontClient) -> dict:
    """Open below the listed rate (100 for the hour), which the seller counters."""
    opened = await buyer.negotiate_new(
        listing_id="listing-1",
        initial_amount=80,
        provision_terms=_opening()["provision_terms"],
        token=TOKEN,
        chain_name="anvil",
        escrow_address=ESCROW,
        proposal_fields={"token": TOKEN},
    )
    assert opened["action"] == "counter"
    return opened


async def _accepted_records(runtime: BareMetalStorefrontRuntime, negotiation_id: str):
    thread = await runtime.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    terms = await runtime.db.load_bare_metal_terms(negotiation_id=negotiation_id)
    return thread, terms


async def test_a_countering_seller_negotiates_over_rounds_to_acceptance(tmp_path) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            countered = int(opened["proposal"]["fields"]["amount"])
            accepted = await buyer.negotiate_continue(
                opened["negotiation_id"], action="accept"
            )

    assert accepted["action"] == "accept"
    thread, terms = await _accepted_records(runtime, opened["negotiation_id"])
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == countered
    assert terms is not None and terms.host_id == "machine-1"
    assert thread["settlement_plan"] is not None
    # One recheck at the opening, one before the buyer's accept.
    assert site.calls == 2


async def test_force_accept_records_terms_and_plan_and_reserves_nothing(tmp_path) -> None:
    site = SourceSite()
    sites = SourceSites(site)
    runtime = replace(_countering_runtime(str(tmp_path / "storefront.db"), site), capacity_client=sites)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            forced = await admin.force_accept_negotiation(
                "listing-1", opened["negotiation_id"], amount=95
            )

    assert (forced.action, forced.amount) == ("accept", 95)
    thread, terms = await _accepted_records(runtime, opened["negotiation_id"])
    assert thread["terminal_state"] == "success"
    assert terms is not None
    assert thread["settlement_plan"] is not None
    # Bare metal holds nothing at negotiation: capacity is reserved when
    # settlement starts fulfillment.
    assert sites.reservation_sites == {}
    assert await runtime.db.load_capacity_hold(negotiation_id=opened["negotiation_id"]) is None


async def test_evaluate_negotiate_reports_what_negotiate_new_refuses(tmp_path) -> None:
    site = SourceSite(listing_source_projection(gpu_model="B200"))
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            preview = await admin.evaluate_negotiate(
                "listing-1",
                proposal=_escrow_proposal(80),
                buyer_principal=BUYER_SIGNER.identity,
                provision_terms=_opening()["provision_terms"],
            )
            threads = await admin.list_negotiations("listing-1")

    assert preview.refused is True
    assert "no_matching_declaration" in (preview.decision_reason or "")
    assert threads.count == 0


_SOURCE_CHANGES = [
    pytest.param(
        {"projection": listing_source_projection(gpu_model="B200")},
        409,
        "no_matching_declaration",
        id="declaration changed",
    ),
    pytest.param(
        {"projection": listing_source_projection(available=False)},
        409,
        "no_matching_inventory",
        id="machine taken",
    ),
    pytest.param(
        {"error": ConnectionError("site unreachable")},
        503,
        "listing_source_unverifiable",
        id="site unreachable",
    ),
]


def _change_source(site: SourceSite, change: dict) -> None:
    if "projection" in change:
        site.projection = change["projection"]
    else:
        site.error = change["error"]


@pytest.mark.parametrize(("change", "status", "reason"), _SOURCE_CHANGES)
async def test_a_counter_rechecks_the_source(tmp_path, change, status, reason) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            _change_source(site, change)
            if status == 503:
                with pytest.raises(StorefrontClientError) as refused:
                    await buyer.negotiate_continue(
                        opened["negotiation_id"],
                        action="counter",
                        proposal=_escrow_proposal(85),
                    )
                assert refused.value.status_code == 503
                assert reason in str(refused.value)
                result = None
            else:
                result = await buyer.negotiate_continue(
                    opened["negotiation_id"],
                    action="counter",
                    proposal=_escrow_proposal(85),
                )

    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=opened["negotiation_id"]
    )
    if result is None:
        # Retryable: nothing was recorded, so the buyer may try again.
        assert thread["terminal_state"] is None
    else:
        # The seller rejects the round, as its inventory guard would.
        assert (result["action"], result["reason"]) == ("reject", reason)
        assert thread["terminal_state"] == "failure"


@pytest.mark.parametrize(("change", "status", "reason"), _SOURCE_CHANGES)
async def test_a_buyer_accept_rechecks_the_source(tmp_path, change, status, reason) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            _change_source(site, change)
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.negotiate_continue(opened["negotiation_id"], action="accept")

    assert refused.value.status_code == status
    assert reason in str(refused.value)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=opened["negotiation_id"]
    )
    assert (thread["terminal_state"], thread["agreed_at"]) == (None, None)


@pytest.mark.parametrize(("change", "status", "reason"), _SOURCE_CHANGES)
async def test_a_force_accept_rechecks_the_source(tmp_path, change, status, reason) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
        _change_source(site, change)
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.force_accept_negotiation(
                    "listing-1", opened["negotiation_id"], amount=95
                )

    assert refused.value.status_code == status
    assert reason in str(refused.value)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=opened["negotiation_id"]
    )
    assert (thread["terminal_state"], thread["agreed_at"]) == (None, None)


async def test_a_buyer_exits_whatever_the_source(tmp_path) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            site.error = ConnectionError("site unreachable")
            calls = site.calls
            exited = await buyer.negotiate_continue(opened["negotiation_id"], action="exit")

    assert exited["action"] == "exit"
    assert site.calls == calls


async def test_force_accept_answers_a_domain_refusal_with_its_status(tmp_path) -> None:
    """A refusal the domain owns answers force-accept as it answers negotiate/{id}."""
    from arkhai_bare_metal_storefront.settlement import BareMetalSettlementPlanError

    def failing_builder(**_kwargs):
        raise BareMetalSettlementPlanError("accepted escrow could not be materialized")

    site = SourceSite()
    runtime = replace(
        _countering_runtime(str(tmp_path / "storefront.db"), site),
        plan_builder=failing_builder,
    )
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            # A counter builds no plan, so the opening succeeds.
            opened = await _open_countered(buyer)
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.force_accept_negotiation(
                    "listing-1", opened["negotiation_id"], amount=95
                )

    assert refused.value.status_code == 409
    assert "could not be materialized" in str(refused.value)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=opened["negotiation_id"]
    )
    assert thread["terminal_state"] is None


async def test_a_thread_without_its_opening_message_is_not_resumed(tmp_path) -> None:
    import sqlite3

    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            conn = sqlite3.connect(runtime.db.db_path)
            try:
                conn.execute(
                    "DELETE FROM storefront_domain_artifacts "
                    "WHERE negotiation_id = ? AND artifact_slot = 'message'",
                    (opened["negotiation_id"],),
                )
                conn.commit()
            finally:
                conn.close()
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.negotiate_continue(opened["negotiation_id"], action="accept")

    assert refused.value.status_code == 409
    assert "opening message" in str(refused.value)
