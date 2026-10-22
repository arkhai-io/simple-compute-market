from __future__ import annotations

import copy
import sqlite3
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement import (
    BareMetalSettlementPlanError,
    build_bare_metal_settlement_plan,
)
import httpx
import pytest
from fastapi.testclient import TestClient
from storefront_client import StorefrontClient, StorefrontClientError
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from market_alkahest.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_core.schemas import (
    RateValue,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import (
    AuthenticatedResponse,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from settlement_compositions import alkahest_composition
from held_loops import held_loop_controller
from source_sites import (
    SourceSite,
    SourceSites,
    listing_source_projection,
    source_projections,
)

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


def _sourced(site: SourceSite) -> dict:
    """The runtime fields that put the seeded listing's site behind ``site``.

    Openings recheck each listing against the projection the storefront holds
    for the site that published it, which startup loads with its first poll; a
    change the site makes reaches it at the next ``site-projections`` step. The
    loops start held, so no timer polls behind a test's back.
    """
    return {
        "capacity_client": SourceSites(site),
        "site_projections": source_projections(site),
        "loop_controller_factory": held_loop_controller,
    }


async def _poll_sites(app) -> None:
    """Step the held site-projection poller, as a scenario does after a site changes."""
    async with _typed(app, ADMIN_SIGNER, "admin") as admin:
        await admin.admin_run_lifecycle_cycle("site-projections")


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
        **_sourced(SourceSite()),
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address=SELLER_WALLET,
        settlement_composition=alkahest_composition(
            SELLER_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients={"anvil": object()},
        ),
        plan_builder=lambda **kwargs: {
            "settlement_plan": {
                "buyer_principal": kwargs["buyer_principal"].model_dump(mode="json"),
                "seller_principal": kwargs["seller_principal"].model_dump(mode="json"),
                "obligations": [],
            },
        },
    )


#: The seller wallet the listing's release condition pays.
SELLER_WALLET = "0x3333333333333333333333333333333333333333"
#: A recipient other than the seller wallet.
BUYER_RECIPIENT = "0x" + "77" * 20


def _recipient_condition(recipient: str) -> dict:
    return {
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter(
            "anvil", config_path=str(anvil_address_book_path())
        ),
        "demand_data": {"recipient": recipient},
    }


#: The release condition a seeded listing authorizes, which a buyer naming a
#: pinned escrow selects, as the buyer builds its proposal from the listing.
AUTHORIZED = [_recipient_condition(SELLER_WALLET)]


async def _insert_listing(
    runtime: BareMetalStorefrontRuntime,
    *,
    demands: list[dict] | None = AUTHORIZED,
    settlement_options: list[dict] | None = None,
) -> None:
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
        demands=demands,
        settlement_options=settlement_options,
    )


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
        demands=AUTHORIZED,
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
    administrator then reads, and how many calls the opening made to the site.
    """
    runtime = replace(_runtime(str(tmp_path / "storefront.db")), **_sourced(site))
    await _insert_listing(runtime)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        loaded = site.calls
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate(buyer)
        opening_calls = site.calls - loaded
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            threads = await admin.list_negotiations("listing-1")
    return refused.value, threads.count, opening_calls


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
    refused, threads, opening_calls = await _open_against(tmp_path, SourceSite(projection))

    assert refused.status_code == 409
    assert "no_matching_declaration" in str(refused)
    assert threads == 0
    # The recheck reads the held projection and calls no site.
    assert opening_calls == 0


async def test_an_opening_whose_site_cannot_answer_is_refused_as_retryable(tmp_path) -> None:
    """The site never answered a poll, so the storefront holds no projection of
    it. Spec scenario "The site's projection is not held"."""
    refused, threads, opening_calls = await _open_against(
        tmp_path, SourceSite(error=ConnectionError("site unreachable"))
    )

    assert refused.status_code == 503
    # The refusal names no source detail; the seller's log carries it.
    assert "listing_source_unverifiable" in str(refused)
    assert threads == 0
    assert opening_calls == 0


async def test_an_opening_with_no_site_authority_is_refused_as_retryable(tmp_path) -> None:
    runtime = replace(
        _runtime(str(tmp_path / "storefront.db")), capacity_client=None, site_projections=None
    )
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await _negotiate(buyer)

    assert refused.value.status_code == 503




def _refused_generation() -> dict:
    """The seeded listing's projection with its bare-metal view naming a pool
    other than the one containing it, a generation bare metal refuses whole."""
    projection = copy.deepcopy(listing_source_projection())
    resource = projection["resource_pools"][0]["resources"][0]
    resource["publication_views"]["bare_metal.v2"]["pool_id"] = "pool-elsewhere"
    return projection


async def test_an_opening_on_a_refused_generation_is_refused_as_retryable(tmp_path) -> None:
    """Spec scenario "The held generation is refused"."""
    refused, threads, opening_calls = await _open_against(
        tmp_path, SourceSite(_refused_generation())
    )

    assert refused.status_code == 503
    assert "listing_source_unverifiable" in str(refused)
    assert threads == 0
    assert opening_calls == 0


async def test_an_expired_confirmation_refuses_until_a_poll_confirms_the_site(
    tmp_path,
) -> None:
    """With the loops held and trading live, an opening more than the window
    after the site's last confirmed poll is refused as retryable, with no site
    call; once the operator steps the site-projection loop, an opening within
    the window of that poll proceeds. Spec scenarios "The held generation's
    confirmation has expired" and "The loops are held past the confirmation
    window"."""
    site = SourceSite()
    now: list[datetime] = []
    runtime = replace(
        _countering_runtime(str(tmp_path / "storefront.db"), site),
        source_confirmation_seconds=60,
        source_confirmation_clock=lambda: now[0],
    )
    await _insert_listing(runtime)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            loaded = _confirmed_at(await admin.get_system_status())
            now.append(loaded + timedelta(seconds=61))
            calls = site.calls
            async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
                with pytest.raises(StorefrontClientError) as expired:
                    await _open_countered(buyer)
            refused_calls = site.calls - calls

            await admin.admin_run_lifecycle_cycle("site-projections")
            polled = _confirmed_at(await admin.get_system_status())
            now[0] = polled + timedelta(seconds=1)
            async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
                opened = await _open_countered(buyer)
            held = runtime.loops.is_pause_requested()

    assert expired.value.status_code == 503
    assert "listing_source_unverifiable" in str(expired.value)
    assert refused_calls == 0
    assert polled > loaded
    assert opened["action"] == "counter"
    assert held, "stepping the poller must not resume the loops"


def _confirmed_at(status) -> datetime:
    """When the seeded listing's site was last confirmed, as status reports it."""
    return datetime.fromisoformat(
        status.site_projections["site-a"]["resource_pool"]["fetched_at"]
    )


# ---------------------------------------------------------------------------
# Rounds, acceptance, and the listing's source after the opening
# ---------------------------------------------------------------------------

_COUNTERING_CHAIN = ["escrow_shape_guard", "bisection"]


def _countering_runtime(path: str, site: SourceSite) -> BareMetalStorefrontRuntime:
    """A storefront whose seller counters below the listed rate, as the lane's does."""
    return replace(
        _runtime(path),
        negotiation_policies=_COUNTERING_CHAIN,
        **_sourced(site),
    )


def _escrow_proposal(amount: int) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": ESCROW,
        "fields": {"amount": str(amount), "token": TOKEN},
        "literal_fields": {"token": TOKEN},
        "demand": AUTHORIZED[0],
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
        demands=AUTHORIZED,
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
        loaded = site.calls
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            countered = int(opened["proposal"]["fields"]["amount"])
            accepted = await buyer.negotiate_continue(
                opened["negotiation_id"], action="accept"
            )
        negotiation_calls = site.calls - loaded

    assert accepted["action"] == "accept"
    thread, terms = await _accepted_records(runtime, opened["negotiation_id"])
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == countered
    assert terms is not None and terms.host_id == "machine-1"
    assert thread["settlement_plan"] is not None
    # A recheck at the opening and one before the buyer's accept, each reading
    # the held projection: neither calls the site.
    assert negotiation_calls == 0


@pytest.mark.parametrize("acceptance", ["buyer", "force_accept"])
async def test_acceptance_builds_its_plan_from_the_record_the_opening_authorized(
    tmp_path, acceptance
) -> None:
    """The listing is refreshed in place between the opening and acceptance,
    its release condition now paying another recipient; acceptance, by the
    buyer or forced by an administrator, builds the plan from the record the
    opening authorized, so the escrow the buyer funds is the one it opened on."""
    built: list[dict] = []

    def recording_builder(**kwargs):
        built.append(dict(kwargs["listing"]))
        return {
            "settlement_plan": {
                "buyer_principal": kwargs["buyer_principal"].model_dump(mode="json"),
                "seller_principal": kwargs["seller_principal"].model_dump(mode="json"),
                "obligations": [],
            },
        }

    site = SourceSite()
    runtime = replace(
        _countering_runtime(str(tmp_path / "storefront.db"), site),
        plan_builder=recording_builder,
    )
    await _insert_listing(runtime)
    opened_against = await runtime.db.load_listing(listing_id="listing-1")
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            opened = await _open_countered(buyer)
            await _insert_listing(
                runtime, demands=[_recipient_condition(BUYER_RECIPIENT)]
            )
            if acceptance == "buyer":
                accepted = await buyer.negotiate_continue(
                    opened["negotiation_id"], action="accept"
                )
                action = accepted["action"]
            else:
                async with _typed(app, ADMIN_SIGNER, "admin") as admin:
                    forced = await admin.force_accept_negotiation(
                        "listing-1", opened["negotiation_id"], amount=95
                    )
                action = forced.action

    refreshed = await runtime.db.load_listing(listing_id="listing-1")
    assert refreshed["demands"] != opened_against["demands"]
    assert action == "accept"
    (listing,) = built
    assert listing["demands"] == opened_against["demands"]
    assert listing["status"] == "open"


async def test_force_accept_records_terms_and_plan_and_reserves_nothing(tmp_path) -> None:
    site = SourceSite()
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), site)
    sites = runtime.capacity_client
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


#: The zero address, which names no escrow contract.
_UNPINNED = "0x" + "0" * 40


def _unpinned_proposal(amount: int) -> dict:
    return {**_escrow_proposal(amount), "escrow_address": _UNPINNED}


async def _open_unpinned(buyer: StorefrontClient, amount: int) -> dict:
    return await buyer.negotiate_new(
        listing_id="listing-1",
        initial_amount=amount,
        provision_terms=_opening()["provision_terms"],
        token=TOKEN,
        escrow_address=_UNPINNED,
        proposal_fields={"token": TOKEN},
    )


@pytest.mark.parametrize(
    "policies",
    [
        pytest.param(None, id="default chain"),
        pytest.param(["listed_price"], id="a chain without the shape guard"),
    ],
)
async def test_an_opening_naming_no_escrow_contract_is_refused(tmp_path, policies) -> None:
    """Refused by name whatever the seller's chain, even at the listed rate,
    which the seller would otherwise accept, and nothing is recorded."""
    amount = 100
    runtime = _materializing_runtime(str(tmp_path / "storefront.db"), policies=policies)
    await _insert_listing(runtime, demands=[_recipient_condition(SELLER_WALLET)])
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            preview = await admin.evaluate_negotiate(
                "listing-1",
                proposal=_unpinned_proposal(amount),
                buyer_principal=BUYER_SIGNER.identity,
                provision_terms=_opening()["provision_terms"],
            )
            async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
                with pytest.raises(StorefrontClientError) as refused:
                    await _open_unpinned(buyer, amount)
            threads = await admin.list_negotiations("listing-1")

    assert preview.refused is True
    assert "escrow_contract_unpinned" in (preview.decision_reason or "")
    assert refused.value.status_code == 409
    assert "escrow_contract_unpinned" in str(refused.value)
    assert threads.count == 0
    _nothing_accepted(runtime)


async def test_a_pinned_escrow_the_listing_does_not_accept_is_refused(tmp_path) -> None:
    runtime = _countering_runtime(str(tmp_path / "storefront.db"), SourceSite())
    await _insert_listing(runtime)
    app = _app(runtime)
    unlisted = "0x" + "33" * 20

    async with app.router.lifespan_context(app):
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            preview = await admin.evaluate_negotiate(
                "listing-1",
                proposal={**_escrow_proposal(80), "escrow_address": unlisted},
                buyer_principal=BUYER_SIGNER.identity,
                provision_terms=_opening()["provision_terms"],
            )
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.negotiate_new(
                    listing_id="listing-1",
                    initial_amount=80,
                    provision_terms=_opening()["provision_terms"],
                    token=TOKEN,
                    chain_name="anvil",
                    escrow_address=unlisted,
                    proposal_fields={"token": TOKEN},
                )

    # Nothing prices a contract the listing does not offer; it is refused, in
    # the preview and the opening.
    assert preview.refused is True
    assert "escrow_not_in_accepted_set" in (preview.decision_reason or "")
    assert refused.value.status_code == 409
    assert "escrow_not_in_accepted_set" in str(refused.value)


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
            await _poll_sites(app)
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
            await _poll_sites(app)
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
        await _poll_sites(app)
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


# ---------------------------------------------------------------------------
# The release condition an accepted plan uses
# ---------------------------------------------------------------------------

def _materializing_runtime(path: str, *, policies=None) -> BareMetalStorefrontRuntime:
    """A storefront that materializes accepted plans with its real plan builder."""
    return replace(
        _runtime(path),
        plan_builder=build_bare_metal_settlement_plan,
        chain_config_paths={"anvil": str(anvil_address_book_path())},
        seller_evm_address=SELLER_WALLET,
        negotiation_policies=policies,
        **_sourced(SourceSite()),
    )


async def _open_at_the_listed_rate(
    app, *, escrow_address: str = ESCROW, demands: list[dict] | None = None
) -> dict:
    async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
        return await buyer.negotiate_new(
            listing_id="listing-1",
            initial_amount=100,
            provision_terms=_opening()["provision_terms"],
            token=TOKEN,
            chain_name="anvil",
            escrow_address=escrow_address,
            proposal_fields={"token": TOKEN},
            demands=demands,
        )


def _nothing_accepted(runtime: BareMetalStorefrontRuntime) -> None:
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM negotiation_threads "
            "WHERE agreement_bytes IS NOT NULL OR settlement_plan IS NOT NULL"
        ).fetchone()[0] == 0


async def test_a_substituted_recipient_is_refused_without_the_shape_guard(
    tmp_path,
) -> None:
    runtime = _materializing_runtime(
        str(tmp_path / "storefront.db"), policies=["listed_price"]
    )
    await _insert_listing(runtime, demands=[_recipient_condition(SELLER_WALLET)])
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        with pytest.raises(StorefrontClientError) as refused:
            await _open_at_the_listed_rate(
                app, demands=[_recipient_condition(BUYER_RECIPIENT)]
            )

    assert refused.value.status_code == 409
    assert "release_condition" in str(refused.value)
    _nothing_accepted(runtime)


async def test_a_listing_authorizing_no_condition_accepts_none(tmp_path) -> None:
    runtime = _materializing_runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime, demands=None)
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        with pytest.raises(StorefrontClientError) as refused:
            await _open_at_the_listed_rate(
                app, demands=[_recipient_condition(BUYER_RECIPIENT)]
            )

    assert refused.value.status_code == 409
    assert "release_condition" in str(refused.value)
    _nothing_accepted(runtime)


async def test_an_opening_naming_no_condition_is_settled_under_the_listings(
    tmp_path,
) -> None:
    """Without the shape guard, which refuses a pinned escrow selecting no
    advertised condition, materialization settles one under the listing's."""
    runtime = _materializing_runtime(
        str(tmp_path / "storefront.db"), policies=["listed_price"]
    )
    authorized = _recipient_condition(SELLER_WALLET)
    await _insert_listing(runtime, demands=[authorized])
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        accepted = await _open_at_the_listed_rate(app)

    assert accepted["action"] == "accept"
    (obligation,) = accepted["settlement_plan"]["obligations"]
    data = obligation["params"]["obligation_data"]
    assert data["arbiter"].lower() == authorized["arbiter"].lower()
    assert data["demand"] == "0x" + encode_recipient_demand(SELLER_WALLET).hex()
    # The plan is the seller's committed copy; no escrow terms ride beside it.
    assert "accepted_escrow_terms" not in accepted


async def test_a_condition_no_escrow_can_be_settled_under_refuses_the_round(
    tmp_path,
) -> None:
    """A listing derived for an empty seller wallet authorizes a recipient
    condition paying no one; the plan cannot be materialized, so the round is
    refused as the listing's release condition, and nothing is accepted."""
    runtime = _materializing_runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime, demands=[_recipient_condition("")])
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        with pytest.raises(StorefrontClientError) as refused:
            await _open_at_the_listed_rate(app, demands=[_recipient_condition("")])

    assert refused.value.status_code == 409
    assert "release_condition_unreadable" in str(refused.value)
    _nothing_accepted(runtime)


# ---------------------------------------------------------------------------
# An exact selection of a mechanism settled only under a plan
# ---------------------------------------------------------------------------

#: The seeded listing's escrow as its Alkahest option publishes it.
_ACCEPTED_ESCROW = {
    "chain_name": "anvil",
    "escrow_address": ESCROW,
    "literal_fields": {"token": TOKEN},
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
}


def _alkahest_option() -> dict:
    params = {"accepted_escrow": dict(_ACCEPTED_ESCROW)}
    rates = [RateValue(field="amount", per="hour", value=100)]
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="alkahest.v1", asset=TOKEN, rates=rates, params=params
        ),
        mechanism="alkahest.v1",
        asset=TOKEN,
        rates=rates,
        params=params,
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    "demands", [AUTHORIZED, None], ids=["authorized condition", "no demands"]
)
async def test_an_exact_alkahest_selection_is_refused_with_nothing_accepted(
    tmp_path, demands
) -> None:
    """An Alkahest escrow is settled only under the plan an escrow proposal
    materializes against the listing's release condition; a selection builds
    none, so it is refused whatever the listing authorizes, and the buyer opens
    with an escrow proposal instead."""
    runtime = _materializing_runtime(str(tmp_path / "storefront.db"))
    option = _alkahest_option()
    await _insert_listing(runtime, demands=demands, settlement_options=[option])
    app = _app(runtime)

    async with app.router.lifespan_context(app):
        async with _typed(app, BUYER_SIGNER, "buyer") as buyer:
            with pytest.raises(StorefrontClientError) as refused:
                await buyer.negotiate_new(
                    listing_id="listing-1",
                    initial_amount=None,
                    provision_terms=_opening()["provision_terms"],
                    settlement_selection={
                        "mechanism": option["mechanism"],
                        "option_id": option["option_id"],
                        "expiration_unix": int(time.time()) + 3600,
                    },
                    selection_only=True,
                )
        async with _typed(app, ADMIN_SIGNER, "admin") as admin:
            threads = await admin.list_negotiations("listing-1")

    assert refused.value.status_code == 409
    assert "settlement_selection_requires_plan" in str(refused.value)
    assert threads.count == 0
    _nothing_accepted(runtime)

