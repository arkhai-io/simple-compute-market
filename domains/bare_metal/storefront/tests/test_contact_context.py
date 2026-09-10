"""Real acceptance capture and review fences over disposable SQLite."""

import copy
import json
import sqlite3
from collections import UserDict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from arkhai_bare_metal.contact_contract import ContactDeclaration
from arkhai_bare_metal_storefront.contact_context import (
    context_digest,
    declaration_listing,
    validate_accepted_contact_context,
)
from arkhai_bare_metal_storefront.introduction_routes import _accepted_introduction
from arkhai_bare_metal_storefront.negotiation_service import NegotiationRequestError
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from core_storefront.models.negotiation_models import NegotiateNewRequest
from market_contact_exchange import delivery_state
from market_contact_exchange.delivery_contract import (
    ContactText, EmailRoute, IntroductionFinalize, IntroductionReview,
)
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY
from market_core.schemas import SettlementPlan
from market_settlement_runtime import SettlementPublicationClause, derive_obligation_ref
from test_contact_only_runtime import BUYER, CONFIG, SELLER
from test_contact_only_runtime import environment as environment

DECLARATION = {
    "schema_version": 1, "listing_id": "declared-contact-example",
    "declaration_id": "declaration-example", "name": "Disposable example machine",
    "machine_details": {
        "gpu_model": "Example GPU", "gpu_count": 2, "vcpu_count": 8,
        "ram_gb": 32, "disk_gb": 256, "region": "Example region",
    },
}


@pytest.fixture
def context_environment(environment, monkeypatch):
    config = copy.deepcopy(CONFIG)
    config["contact"]["profiles"]["default"].update(
        delivery_policy=POLICY, context_contract="accepted-listing.v1",
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    monkeypatch.setenv("BARE_METAL_STOREFRONT_DELIVERY", json.dumps(DELIVERY_CONFIG))
    return environment


async def admitted(runtime, *, declaration=DECLARATION, overrides=None):
    value = ContactDeclaration.model_validate(declaration)
    listing = declaration_listing(value)
    now = datetime.now(timezone.utc)
    published = await runtime.settlement_composition.publication_payload(
        candidate=listing.model_dump(mode="json"),
        clauses=[SettlementPublicationClause(
            mechanism="contact-exchange.v1", asset="introduction",
            mechanism_input={"profile": "default"},
        )],
        offer_expires_at=now + timedelta(hours=1), funding_deadlines={},
        fulfillment_deadline=now + timedelta(hours=1),
    )
    intent = {
        "schema_version": 3, "declaration": declaration,
        "settlement_options": list(published.settlement_options),
    }
    kwargs = dict(
        listing_id=value.listing_id, status="open", created_at=now.isoformat(),
        updated_at=now.isoformat(), seller_principal=SELLER.identity,
        storefront_url=runtime.storefront_url, listing=listing,
        accepted_escrows=[], settlement_options=list(published.settlement_options),
        site_id=None, pool_id=None, physical_resource_id=None, publication_intent=intent,
    )
    kwargs.update(overrides or {})
    await runtime.db.upsert_bare_metal_listing(**kwargs)
    return published.settlement_options[0]


def request(option):
    return NegotiateNewRequest(
        listing_id=DECLARATION["listing_id"], buyer_principal=BUYER.identity,
        provision_terms={"kind": "bare_metal.v1", "version": 1, "payload": {
            "duration_seconds": 3600, "access_method": "none",
        }},
        settlement_selection={
            "mechanism": "contact-exchange.v1", "option_id": option["option_id"],
            "expiration_unix": 4102444800,
        },
    )


async def accept(runtime, option):
    return await runtime.negotiation_service().open(request=request(option), buyer_principal=BUYER.identity)


def counts(runtime):
    with sqlite3.connect(runtime.db.db_path) as conn:
        return tuple(conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in (
            "contact_introductions", "contact_delivery_intents", "settlement_operations",
        ))


async def test_acceptance_captures_exact_declaration_and_survives_listing_drift(context_environment):
    runtime = build_runtime_from_environment()
    option = await admitted(runtime)
    result = await accept(runtime, option)
    plan = result.settlement_plan
    package = plan.service_terms["contact-exchange.v1"]
    context = package["accepted_context"]
    assert context["declaration"] == DECLARATION
    assert context["accepted_terms"] == {"duration_seconds": 3600, "access_method": "none"}
    assert context["option_id"] == option["option_id"]
    assert plan.obligations[0].params["accepted_context_digest"] == context_digest(context)
    assert counts(runtime) == (0, 0, 0)
    binding = await runtime.db.load_listing_binding(listing_id=DECLARATION["listing_id"])
    assert binding.site_id is binding.pool_id is binding.physical_resource_id is None
    assert "physical_host_id" not in binding.source_envelope_json
    assert "machine_id" not in binding.source_envelope_json
    ref = derive_obligation_ref(result.negotiation_id, 0, plan.obligations[0].model_dump(mode="json"))
    # Deliberate corruption setup: no public API may rewrite immutable provenance.
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute("UPDATE listings SET offer_resource='{}'")
    restarted = build_runtime_from_environment()
    agreement, _ = await _accepted_introduction(restarted.db, result.negotiation_id, ref)
    assert agreement.introduction_package == package
    assert counts(restarted) == (0, 0, 0)
    with sqlite3.connect(restarted.db.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM settlement_obligations").fetchone()[0] == 1


@pytest.mark.parametrize("overrides", [
    {"site_id": "example-site"}, {"pool_id": "example-pool"},
    {"physical_resource_id": "example-resource"}, {"publication_intent": None},
])
async def test_declaration_admission_never_manufactures_authority(context_environment, overrides):
    runtime = build_runtime_from_environment()
    with pytest.raises(ValueError):
        await admitted(runtime, overrides=overrides)
    assert await runtime.db.load_listing(listing_id=DECLARATION["listing_id"]) is None


@pytest.mark.parametrize("invalid", ["unknown", "bytes_identifier"])
async def test_invalid_declaration_mapping_admission_persists_nothing(context_environment, invalid):
    runtime = build_runtime_from_environment()
    listing = declaration_listing(ContactDeclaration.model_validate(DECLARATION)).model_dump(mode="json")
    if invalid == "unknown":
        listing["unrecognized"] = "example"
    else:
        listing["declaration_id"] = b"declaration-example"
    with pytest.raises(ValueError):
        await admitted(runtime, overrides={"listing": UserDict(listing)})
    with sqlite3.connect(runtime.db.db_path) as conn:
        for table in ("listings", "storefront_listing_bindings", "negotiation_threads", "settlement_obligations"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert counts(runtime) == (0, 0, 0)


@pytest.mark.parametrize("projection", [
    '{"PRIVATE-PROJECTION-CANARY":',
    json.dumps({"declaration_id": "PRIVATE-PROJECTION-CANARY"}),
    json.dumps(["PRIVATE-PROJECTION-CANARY"]),
])
async def test_acceptance_safely_refuses_invalid_projection(context_environment, projection):
    runtime = build_runtime_from_environment()
    option = await admitted(runtime)
    # Corrupt storage is not reachable through the listing admission API.
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute("UPDATE listings SET offer_resource=?", (projection,))
    with pytest.raises(NegotiationRequestError) as error:
        await accept(runtime, option)
    assert error.value.detail == "invalid_contact_provenance"
    assert str(error.value) == "invalid_contact_provenance"
    assert error.value.status_code == 409
    assert error.value.__suppress_context__
    assert counts(runtime) == (0, 0, 0)
    with sqlite3.connect(runtime.db.db_path) as conn:
        for table in ("negotiation_threads", "settlement_obligations"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


async def test_projection_database_outage_is_not_a_provenance_rejection(context_environment):
    runtime = build_runtime_from_environment()
    option = await admitted(runtime)

    class ProjectionOutageDatabase:
        def __getattr__(self, name):
            return getattr(runtime.db, name)

        async def load_bare_metal_listing_payload(self, *, listing_id):
            raise sqlite3.OperationalError("disposable projection database unavailable")

    service = replace(runtime.negotiation_service(), db=ProjectionOutageDatabase())
    with pytest.raises(sqlite3.OperationalError, match="disposable projection database unavailable"):
        await service.open(request=request(option), buyer_principal=BUYER.identity)
    assert counts(runtime) == (0, 0, 0)
    with sqlite3.connect(runtime.db.db_path) as conn:
        for table in ("negotiation_threads", "settlement_obligations"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("corruption", ["missing", "declaration", "option", "listing"])
async def test_acceptance_refuses_inconsistent_authoritative_provenance(context_environment, corruption):
    runtime = build_runtime_from_environment()
    option = await admitted(runtime)
    binding = await runtime.db.load_listing_binding(listing_id=DECLARATION["listing_id"])
    source = json.loads(binding.source_envelope_json)
    if corruption == "missing":
        source.pop("publication_intent")
    elif corruption == "declaration":
        source["publication_intent"]["declaration"]["machine_details"]["ram_gb"] = 64
    elif corruption == "option":
        source["publication_intent"]["settlement_options"][0]["params"]["terms"] = "Changed terms"
    # Deliberate corruption setup at an otherwise immutable storage boundary.
    with sqlite3.connect(runtime.db.db_path) as conn:
        if corruption == "listing":
            row = conn.execute("SELECT offer_resource FROM listings").fetchone()[0]
            listing = json.loads(row)
            listing["capabilities"]["gpu_count"] = 99
            conn.execute("UPDATE listings SET offer_resource=?", (json.dumps(listing),))
        else:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute("UPDATE storefront_listing_bindings SET source_envelope_json='{}'")
            # A corrupt-storage fixture cannot be produced through the public API.
            conn.execute("DROP TRIGGER storefront_listing_binding_immutable")
            conn.execute("UPDATE storefront_listing_bindings SET source_envelope_json=?", (
                json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            ))
    with pytest.raises(NegotiationRequestError, match="invalid_contact_provenance"):
        await accept(runtime, option)
    assert counts(runtime) == (0, 0, 0)
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM negotiation_threads").fetchone()[0] == 0


async def test_new_context_rejects_private_configured_literal(context_environment, monkeypatch):
    config = copy.deepcopy(CONFIG)
    config["contact"]["profiles"]["default"].update(
        delivery_policy=POLICY, context_contract="accepted-listing.v1",
    )
    config["contact"]["contact_payload"] = {"text": "PRIVATE-CONTACT-CANARY"}
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    runtime = build_runtime_from_environment()
    declaration = {**DECLARATION, "name": "PRIVATE-CONTACT-CANARY"}
    option = await admitted(runtime, declaration=declaration)
    with pytest.raises(NegotiationRequestError) as error:
        await accept(runtime, option)
    assert "PRIVATE-CONTACT-CANARY" not in str(error.value)
    assert counts(runtime) == (0, 0, 0)


@pytest.mark.parametrize("changed", [
    "text", "route", "buyer", "seller", "option", "machine", "terms", "seller_text", "seller_route",
])
async def test_review_cannot_finalize_changed_text_parties_context_or_seller(context_environment, changed):
    runtime = build_runtime_from_environment()
    result = await accept(runtime, await admitted(runtime))
    plan = result.settlement_plan
    ref = derive_obligation_ref(result.negotiation_id, 0, plan.obligations[0].model_dump(mode="json"))
    agreement, _ = await _accepted_introduction(runtime.db, result.negotiation_id, ref)
    buyer_text = ContactText(text='  Whole blurb 😀 e\u0301\n"quoted"  ').model_dump()
    seller_text = ContactText(text="Seller's whole blurb").model_dump()
    seller_route = EmailRoute(kind="email", address="seller@example.invalid")
    body = dict(
        schema_version=2, negotiation_id=result.negotiation_id, obligation_ref=ref,
        finalization_id="12345678-1234-4234-8234-123456789abc",
        contact_payload=buyer_text, delivery_route={"kind": "email", "address": "buyer@example.invalid"},
    )
    review = await runtime.db.contact_transaction(lambda conn: delivery_state.review(
        conn, IntroductionReview.model_validate(body), agreement, seller_text, seller_route, 100,
    ))
    body.update(review_token=review["review_token"], consent="exchange-contacts-and-deliver.v1")
    if changed == "text":
        body["contact_payload"] = {"text": buyer_text["text"] + " "}
    elif changed == "route":
        body["delivery_route"]["address"] = "changed@example.invalid"
    elif changed in {"buyer", "seller"}:
        agreement = replace(agreement, **{f"{changed}_principal": BUYER.identity if changed == "seller" else SELLER.identity})
    elif changed == "seller_text":
        seller_text = {"text": "changed"}
    elif changed == "seller_route":
        seller_route = EmailRoute(kind="email", address="changed@example.invalid")
    else:
        package = copy.deepcopy(agreement.introduction_package)
        if changed == "option":
            package["option_id"] = "a" * 64
        elif changed == "machine":
            package["accepted_context"]["declaration"]["machine_details"]["ram_gb"] = 64
        else:
            package["accepted_context"]["accepted_terms"]["duration_seconds"] = 7200
        agreement = replace(agreement, introduction_package=package)
        corrupt_plan = plan.model_dump(mode="json")
        corrupt_plan["service_terms"]["contact-exchange.v1"] = package
        with pytest.raises(ValueError, match="invalid_contact_provenance"):
            validate_accepted_contact_context(SettlementPlan.model_validate(corrupt_plan))
    outcome = await runtime.db.contact_transaction(lambda conn: delivery_state.finalize(
        conn, IntroductionFinalize.model_validate(body), agreement, seller_text, seller_route, 101,
    ))
    assert outcome.detail == {"code": "review_changed" if changed.startswith("seller_") else "finalization_conflict"}
    assert counts(runtime) == (0, 0, 0)


async def test_whole_text_finalization_preserves_reviewed_scalars(context_environment):
    runtime = build_runtime_from_environment()
    result = await accept(runtime, await admitted(runtime))
    ref = derive_obligation_ref(result.negotiation_id, 0, result.settlement_plan.obligations[0].model_dump(mode="json"))
    agreement, _ = await _accepted_introduction(runtime.db, result.negotiation_id, ref)
    buyer_text = ContactText(text='  One blurb 😀 e\u0301\n"quoted" \\  ').model_dump()
    seller_text = ContactText(text="Seller blurb 😀").model_dump()
    seller_route = EmailRoute(kind="email", address="seller@example.invalid")
    body = dict(
        schema_version=2, negotiation_id=result.negotiation_id, obligation_ref=ref,
        finalization_id="12345678-1234-4234-8234-123456789abc",
        contact_payload=buyer_text, delivery_route={"kind": "email", "address": "buyer@example.invalid"},
    )
    review = await runtime.db.contact_transaction(lambda conn: delivery_state.review(
        conn, IntroductionReview.model_validate(body), agreement, seller_text, seller_route, 100,
    ))
    assert review["introduction"] == agreement.introduction_package
    finalized = IntroductionFinalize.model_validate({
        **body, "review_token": review["review_token"], "consent": "exchange-contacts-and-deliver.v1",
    })
    record = await runtime.db.contact_transaction(lambda conn: delivery_state.finalize(
        conn, finalized, agreement, seller_text, seller_route, 101,
    ))
    assert record.buyer_contact == buyer_text
    assert record.seller_contact == seller_text
    assert record.introduction_package == review["introduction"]
    restarted = build_runtime_from_environment()
    stored = await restarted.db.load_contact_introduction(obligation_ref=ref)
    assert stored == record
    assert counts(restarted) == (1, 2, 0)


async def test_protected_accepted_lookup_refuses_corrupt_package(context_environment):
    runtime = build_runtime_from_environment()
    result = await accept(runtime, await admitted(runtime))
    plan = result.settlement_plan.model_dump(mode="json")
    ref = derive_obligation_ref(result.negotiation_id, 0, plan["obligations"][0])
    plan["service_terms"]["contact-exchange.v1"]["accepted_context"]["declaration"]["name"] = "Changed name"
    # Deliberate storage corruption, bypassing the immutable plan commit API.
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute("UPDATE negotiation_threads SET settlement_plan=? WHERE negotiation_id=?", (
            json.dumps(plan), result.negotiation_id,
        ))
    with pytest.raises(ValueError, match="invalid_contact_provenance"):
        await _accepted_introduction(runtime.db, result.negotiation_id, ref)
    assert counts(runtime) == (0, 0, 0)
