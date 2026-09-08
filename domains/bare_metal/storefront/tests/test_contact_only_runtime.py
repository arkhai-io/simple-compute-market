"""Contact-only environment composition over real signed loopback HTTP."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import sqlite3
import uuid
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import uvicorn
from arkhai_bare_metal import BareMetalProvisionTerms
from core_storefront.models.negotiation_models import NegotiateNewRequest
from core_storefront.auth import AuthError, verify_authenticated_response
from core_buyer.introductions import IntroductionTransport
from core_buyer.negotiation_client import load_buyer_chain, negotiate_with_seller
from market_contact_exchange import MECHANISM
from market_core.schemas import SettlementSelection, derive_settlement_option_id
from market_identity import (
    EMPTY_BODY, Ed25519Signer, TrustedIdentitySet, RequestEnvelope,
    canonical_body_hash, sign_request,
)
from market_settlement_runtime import (
    SettlementPublicationClause, SettlementObligationRecord,
    SettlementSQLiteRepository, derive_obligation_ref,
)

from arkhai_bare_metal_storefront import runtime as runtime_module
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.negotiation_service import NegotiationRequestError
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)

# Deterministic synthetic test-only seeds. NEVER deploy these keys live.
SELLER_SEED = bytes([17]) * 32
SELLER = Ed25519Signer(SELLER_SEED)
BUYER = Ed25519Signer(bytes([34]) * 32)
ADMIN = Ed25519Signer(bytes([51]) * 32)
OUTSIDER = Ed25519Signer(bytes([68]) * 32)
SELLER_CONTACT = {"email": "synthetic-seller@example.invalid"}
BUYER_CONTACT = {"email": "synthetic-buyer@example.invalid"}
CONFIG = {
    "priority": [MECHANISM],
    "contact": {
        "enabled": True,
        "contact_payload": SELLER_CONTACT,
        "profiles": {
            "default": {
                "channel": "email",
                "terms": "SYNTHETIC TEST introduction only. No payment or machine access.",
            }
        },
    },
}


@pytest.fixture
def environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("BARE_METAL_") or name == "ARKHAI_IDENTITY_CREDENTIAL":
            monkeypatch.delenv(name)
    values = {
        "BARE_METAL_STOREFRONT_DB_PATH": str(tmp_path / "storefront.db"),
        "BARE_METAL_STOREFRONT_PUBLIC_URL": "http://127.0.0.1:8000",
        "BARE_METAL_STOREFRONT_IDENTITY_SCHEME": "ed25519",
        "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER": SELLER.identity.identifier,
        "ARKHAI_IDENTITY_CREDENTIAL": base64.urlsafe_b64encode(SELLER_SEED).rstrip(b"=").decode(),
        "BARE_METAL_STOREFRONT_ADMIN_IDENTITIES": json.dumps([ADMIN.identity.model_dump(mode="json")]),
        "BARE_METAL_STOREFRONT_SETTLEMENT": json.dumps(CONFIG),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


async def _listing(runtime, *, listing_id="synthetic-introduction", **overrides):
    now = datetime.now(timezone.utc)
    payload = await runtime.settlement_composition.publication_payload(
        candidate={"machine_id": "synthetic-machine"},
        clauses=[SettlementPublicationClause(
            mechanism=MECHANISM, asset="introduction",
            mechanism_input={"profile": "default"},
        )],
        offer_expires_at=now + timedelta(hours=1),
        funding_deadlines={},
        fulfillment_deadline=now + timedelta(hours=2),
    )
    values = dict(
        listing_id=listing_id, status="open", created_at=now.isoformat(),
        updated_at=now.isoformat(), seller_principal=SELLER.identity,
        storefront_url=runtime.storefront_url,
        site_id=None, pool_id=None, physical_resource_id=None,
        listing={
            "kind": "bare_metal.v1", "machine_id": "synthetic-machine",
            "physical_host_id": "synthetic-host", "access_methods": ["none"],
        },
        accepted_escrows=[], settlement_options=list(payload.settlement_options),
    )
    values.update(overrides)
    await runtime.db.upsert_bare_metal_listing(**values)
    return payload.settlement_options[0]


async def test_environment_omits_physical_and_financial_authorities(environment, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("contact-only startup constructed a physical or chain authority")

    # Composition-boundary guards: fail before any external client can be built.
    monkeypatch.setattr(runtime_module, "build_trusted_site_clients", forbidden)
    monkeypatch.setattr(runtime_module, "_build_chain_clients_from_environment", forbidden)
    monkeypatch.setattr(runtime_module, "parse_site_bindings", forbidden)
    runtime = build_runtime_from_environment()
    assert runtime.site_bindings == ()
    assert runtime.capacity_client is runtime.fulfillment_client is None
    assert runtime.seller_evm_address is None
    assert runtime.chain_clients == {}
    assert set(runtime.settlement_clients) == {MECHANISM}
    assert runtime.hosted_domain_callbacks is runtime.settlement_worker is None
    assert runtime.introduction_delivery is None
    with pytest.raises(RuntimeError, match="not configured"):
        runtime.settlement_service()
    with pytest.raises(RuntimeError, match="unavailable"):
        runtime.fulfillment_service()
    option = await _listing(runtime)
    assert SELLER_CONTACT["email"] not in json.dumps(option)
    health = await runtime.health()
    assert health["status"] == "ok"
    assert health["checks"]["site_projection"] == "not_applicable"
    assert health["checks"]["fulfillment"] == "not_applicable"
    assert health["resource_count"] == 1
    assert health["sites"] == []
    assert "example.invalid" not in json.dumps(health)


async def test_incomplete_contact_config_is_not_healthy(environment, monkeypatch):
    config = json.loads(json.dumps(CONFIG))
    config["contact"]["contact_payload"] = {}
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    health = await build_runtime_from_environment().health()
    assert health["status"] == "degraded"
    assert health["checks"]["commercial_settlement"] == "unavailable"


def test_financial_composition_still_requires_sites(environment, monkeypatch):
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps({
        "priority": ["alkahest.v1", MECHANISM],
        "alkahest": {"enabled": True}, "contact": CONFIG["contact"],
    }))
    # Public deterministic test-only EVM address, not a signing credential.
    monkeypatch.setenv("BARE_METAL_STOREFRONT_EVM_ADDRESS", "0x" + "11" * 20)
    with pytest.raises(RuntimeError, match="trusted site bindings"):
        build_runtime_from_environment()
    assert not os.path.exists(environment["BARE_METAL_STOREFRONT_DB_PATH"])


@pytest.mark.parametrize("overrides", [
    {"pool_id": "pool-without-site"},
    {"physical_resource_id": "resource-without-site"},
    {"accepted_escrows": [{"chain_name": "unavailable"}]},
    {"settlement_options": []},
    {"listing": {"machine_id": "synthetic-machine", "physical_host_id": "synthetic-host", "access_methods": ["ssh"]}},
    {"settlement_options": [{"option_id": derive_settlement_option_id(mechanism="fiat.stripe.v1", asset="usd", rates=[], params={}), "mechanism": "fiat.stripe.v1", "asset": "usd", "rates": [], "params": {}}]},
])
async def test_unbacked_admission_refuses_partial_authority(environment, overrides):
    runtime = build_runtime_from_environment()
    with pytest.raises(ValueError):
        await _listing(runtime, **overrides)
    assert await runtime.db.load_listing(listing_id="synthetic-introduction") is None


@contextmanager
def _server(monkeypatch):
    ready = threading.Event()
    runtimes = []
    domain = get_market_domain_contract()

    def runtime_factory():
        runtime = build_runtime_from_environment(domain=domain)
        runtimes.append(runtime)
        return runtime

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)
        app = build_bare_metal_storefront_app(
            registry=build_bare_metal_storefront_registry(domain=domain),
            runtime_factory=runtime_factory,
        )
        server = ReadyServer(uvicorn.Config(app, log_level="error", lifespan="on"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            assert ready.wait(10), "storefront startup did not complete"
            assert server.started
            yield url, runtimes[0]
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), "storefront did not shut down"


def _transport(url, signer):
    return IntroductionTransport(
        seller_url=url, principal=signer.identity, signer=signer,
        resolve_seller_principals=lambda: TrustedIdentitySet(identities=(SELLER.identity,)),
        request_timeout=5,
    )


def _accept_contact(url, runtime):
    option = asyncio.run(_listing(runtime))
    outcome = negotiate_with_seller(
        seller_url=url, principal=BUYER.identity, signer=BUYER,
        listing_id="synthetic-introduction",
        resolve_seller_principals=lambda: TrustedIdentitySet(identities=(SELLER.identity,)),
        initial_price=None, max_price=None, unit_count=1,
        policy_params={"_selected_settlement_option": option},
        provision_terms=BareMetalProvisionTerms(payload={"duration_seconds": 3600, "access_method": "none"}),
        settlement_selection=SettlementSelection(
            mechanism=MECHANISM, option_id=option["option_id"],
            expiration_unix=int(time.time()) + 3600,
        ),
        chain=load_buyer_chain(policy_mode="listed_price"),
    )
    return outcome


def test_signed_environment_negotiation_consent_reveal_and_restart(environment, monkeypatch):
    with _server(monkeypatch) as (url, runtime):
        outcome = _accept_contact(url, runtime)
        assert outcome.status == "agreed"
        negotiation_id = outcome.negotiation_id
        plan = outcome.settlement_plan.model_dump(mode="json")
        obligation_ref = derive_obligation_ref(negotiation_id, 0, plan["obligations"][0])
        assert plan["obligations"][0].get("amount") is None
        assert asyncio.run(runtime.db.load_contact_introduction(obligation_ref=obligation_ref)) is None
        buyer = _transport(url, BUYER)
        outsider = _transport(url, OUTSIDER)
        with pytest.raises(RuntimeError, match="authenticated HTTP 409"):
            buyer.read(obligation_ref=obligation_ref)
        _assert_pending_wire(url, obligation_ref, negotiation_id)
        _assert_pending_bookkeeping(runtime, negotiation_id, obligation_ref)

    # A new process over the same database must resolve pending before consent.
    with _server(monkeypatch) as (url, runtime):
        _assert_pending_wire(url, obligation_ref, negotiation_id)
        _assert_pending_bookkeeping(runtime, negotiation_id, obligation_ref)
        buyer = _transport(url, BUYER)
        outsider = _transport(url, OUTSIDER)
        with pytest.raises(RuntimeError, match="HTTP 403"):
            outsider.start(negotiation_id=negotiation_id, obligation_ref=obligation_ref, contact_payload=BUYER_CONTACT)
        revealed = buyer.start(negotiation_id=negotiation_id, obligation_ref=obligation_ref, contact_payload=BUYER_CONTACT)
        assert revealed["counterparty_contact"] == SELLER_CONTACT
        assert buyer.read(obligation_ref=obligation_ref) == revealed
        assert _transport(url, SELLER).read(obligation_ref=obligation_ref)["counterparty_contact"] == BUYER_CONTACT
        assert buyer.start(negotiation_id=negotiation_id, obligation_ref=obligation_ref, contact_payload=BUYER_CONTACT) == revealed
        record = asyncio.run(runtime.db.load_contact_introduction(obligation_ref=obligation_ref))
        assert record.buyer_contact == BUYER_CONTACT
        assert record.seller_contact == SELLER_CONTACT
        assert record.introduction_package == plan["service_terms"][MECHANISM]
        assert asyncio.run(runtime.settlement_runtime.get_status(negotiation_id)).status == "complete"
        before = asyncio.run(runtime.settlement_repository.load_settlement_obligation(obligation_ref))
        pending_record = SettlementObligationRecord.from_obligation(
            agreement_ref=negotiation_id, obligation_index=0, obligation=plan["obligations"][0],
        )
        asyncio.run(runtime.db.commit_settlement_plan(
            negotiation_id=negotiation_id, settlement_plan=plan,
            buyer_principal=BUYER.identity, seller_principal=SELLER.identity,
            register_bookkeeping=lambda conn: SettlementSQLiteRepository.upsert_settlement_obligation_in_transaction(
                conn, pending_record.model_dump(),
            ),
        ))
        assert asyncio.run(runtime.settlement_repository.load_settlement_obligation(obligation_ref)) == before
        binding = asyncio.run(runtime.db.load_thread_binding(negotiation_id=negotiation_id))
        assert binding.site_id is None
        with pytest.raises(RuntimeError, match="HTTP 403"):
            outsider.read(obligation_ref=obligation_ref)

    # Mutable configuration cannot change an already revealed introduction.
    config = json.loads(json.dumps(CONFIG))
    config["contact"]["contact_payload"] = {"email": "changed@example.invalid"}
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    with _server(monkeypatch) as (url, restarted):
        assert _transport(url, BUYER).read(obligation_ref=obligation_ref) == revealed
        assert asyncio.run(restarted.db.load_thread_binding(negotiation_id=negotiation_id)) == binding
        assert asyncio.run(restarted.settlement_runtime.get_status(negotiation_id)).status == "complete"
        assert restarted.capacity_client is restarted.fulfillment_client is None


@pytest.mark.parametrize("terms", [
    {"duration_seconds": 3600, "access_method": "ssh", "ssh_public_key": "ssh-ed25519 synthetic"},
])
def test_contact_negotiation_refuses_physical_terms(environment, monkeypatch, terms):
    with _server(monkeypatch) as (url, runtime):
        option = asyncio.run(_listing(runtime))
        with pytest.raises(RuntimeError, match="HTTP 409"):
            negotiate_with_seller(
                seller_url=url, principal=BUYER.identity, signer=BUYER,
                listing_id="synthetic-introduction",
                resolve_seller_principals=lambda: TrustedIdentitySet(identities=(SELLER.identity,)),
                initial_price=None, max_price=None, unit_count=1,
                policy_params={"_selected_settlement_option": option},
                provision_terms=BareMetalProvisionTerms(payload=terms),
                settlement_selection=SettlementSelection(
                    mechanism=MECHANISM, option_id=option["option_id"],
                    expiration_unix=int(time.time()) + 3600,
                ),
                chain=load_buyer_chain(policy_mode="listed_price"),
            )


async def test_contact_runtime_refuses_legacy_financial_negotiation(environment):
    runtime = build_runtime_from_environment()
    await _listing(runtime)
    request = NegotiateNewRequest(
        listing_id="synthetic-introduction", buyer_principal=BUYER.identity,
        provision_terms={
            "kind": "bare_metal.v1", "version": 1,
            "payload": {"duration_seconds": 3600, "access_method": "none"},
        },
        proposal={
            "chain_name": "synthetic", "escrow_address": "0x" + "11" * 20,
            "fields": {"amount": "1"}, "expiration_unix": int(time.time()) + 3600,
        },
    )
    with pytest.raises(NegotiationRequestError, match="financial settlement is unavailable"):
        await runtime.negotiation_service().open(request=request, buyer_principal=BUYER.identity)


def _signed_headers(signer, operation, ref, *, method="GET", body=EMPTY_BODY):
    signed = sign_request(signer=signer, envelope=RequestEnvelope(
        role="buyer", principal=signer.identity, method=method,
        operation=operation, resource=ref, request_id=str(uuid.uuid4()),
        timestamp=int(time.time()), body_hash=canonical_body_hash(body),
    ))
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }


def _assert_pending_wire(url, ref, negotiation_id):
    # Raw HTTP is limited to wire mutation/verification; the lifecycle uses the
    # canonical typed buyer clients, which cannot construct malformed envelopes.
    with httpx.Client(base_url=url, trust_env=False) as client:
        for signer in (BUYER, SELLER):
            headers = _signed_headers(signer, "introduction_read", ref)
            response = client.get(f"/api/v1/introductions/{ref}", headers=headers)
            assert response.status_code == 409
            assert response.json() == {"detail": "introduction has not been started"}
            context = dict(
                headers=response.headers,
                expected_principals=TrustedIdentitySet(identities=(SELLER.identity,)),
                expected_role="seller", method="GET", operation="introduction_read",
                resource=ref, request_id=headers["X-Market-Request-ID"],
                status=409, body=response.json(),
            )
            verify_authenticated_response(**context)
            changed_signature = dict(response.headers)
            changed_signature["x-market-signature"] = "invalid"
            for mutation in (
                {"headers": changed_signature},
                {"body": {"detail": "revealed"}}, {"status": 200},
                {"resource": "another-obligation"}, {"operation": "introduction_start"},
                {"method": "POST"}, {"request_id": "another-request"},
                {"expected_principals": TrustedIdentitySet(identities=(OUTSIDER.identity,))},
            ):
                with pytest.raises(AuthError):
                    verify_authenticated_response(**{**context, **mutation})
        headers = _signed_headers(OUTSIDER, "introduction_read", ref)
        assert client.get(f"/api/v1/introductions/{ref}", headers=headers).status_code == 403
        unsigned = client.get(f"/api/v1/introductions/{ref}")
        assert unsigned.status_code in (401, 403)
        assert unsigned.json()["detail"]
        assert "x-market-signature" not in unsigned.headers
        for operation, resource in (("introduction_start", ref), ("introduction_read", "wrong-ref")):
            headers = _signed_headers(BUYER, operation, resource)
            assert client.get(f"/api/v1/introductions/{ref}", headers=headers).status_code in (400, 401, 403)
        headers = _signed_headers(BUYER, "introduction_read", ref)
        headers["X-Market-Signature"] = "invalid"
        assert client.get(f"/api/v1/introductions/{ref}", headers=headers).status_code in (400, 401, 403)
        unknown = client.get("/api/v1/introductions/unknown", headers=_signed_headers(BUYER, "introduction_read", "unknown"))
        assert unknown.status_code == 404
        assert "x-market-signature" not in unknown.headers
        start = {"negotiation_id": "unknown", "obligation_ref": ref, "contact_payload": BUYER_CONTACT}
        # An unknown agreement must not gain party authentication from its ref.
        response = client.post("/api/v1/introductions", json=start, headers=_signed_headers(
            BUYER, "introduction_start", ref, method="POST", body=start,
        ))
        assert response.status_code == 404
        start["negotiation_id"] = negotiation_id
        headers = _signed_headers(BUYER, "introduction_start", ref, method="POST", body=start)
        changed_body = {**start, "contact_payload": {"email": "tampered@example.invalid"}}
        assert client.post("/api/v1/introductions", json=changed_body, headers=headers).status_code in (400, 401, 403)


def _assert_pending_bookkeeping(runtime, negotiation_id, ref):
    row = asyncio.run(runtime.settlement_repository.load_settlement_obligation(ref))
    assert row["agreement_ref"] == negotiation_id
    for field in ("materialization_state", "condition_state", "collection_state", "reclaim_state"):
        assert row[field] == "pending"
    for field in ("mechanism_ref", "fulfillment_ref", "materialization_receipt", "collection_receipt"):
        assert row[field] is None
    assert row["version"] == 0
    assert asyncio.run(runtime.settlement_repository.list_due_settlement_obligations(now_unix=time.time() + 7200)) == []
    assert asyncio.run(runtime.db.load_contact_introduction(obligation_ref=ref)) is None
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM settlement_operations").fetchone()[0] == 0
        dump = "\n".join(conn.iterdump())
        assert BUYER_CONTACT["email"] not in dump
        assert SELLER_CONTACT["email"] not in dump


async def test_contact_acceptance_bookkeeping_rollback(environment):
    runtime = build_runtime_from_environment()
    option = await _listing(runtime)
    request = NegotiateNewRequest(
        listing_id="synthetic-introduction", buyer_principal=BUYER.identity,
        provision_terms=BareMetalProvisionTerms(payload={"duration_seconds": 3600, "access_method": "none"}).model_dump(mode="json"),
        settlement_selection=SettlementSelection(
            mechanism=MECHANISM, option_id=option["option_id"], expiration_unix=int(time.time()) + 3600,
        ),
    )
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute("CREATE TRIGGER reject_bookkeeping AFTER INSERT ON settlement_obligations BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic rollback"):
        await runtime.negotiation_service().open(request=request, buyer_principal=BUYER.identity)
    with sqlite3.connect(runtime.db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM settlement_obligations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM negotiation_threads WHERE settlement_plan IS NOT NULL").fetchone()[0] == 0
        conn.execute("DROP TRIGGER reject_bookkeeping")
    restarted = build_runtime_from_environment()
    outcome = await restarted.negotiation_service().open(request=request, buyer_principal=BUYER.identity)
    plan = outcome.settlement_plan.model_dump(mode="json")
    # The earlier failed opening is durable but has no accepted plan. Exercise
    # rollback after the callback itself successfully inserted a new obligation.
    with sqlite3.connect(runtime.db.db_path) as conn:
        failed_id = conn.execute("SELECT negotiation_id FROM negotiation_threads WHERE settlement_plan IS NULL").fetchone()[0]
    failed_record = SettlementObligationRecord.from_obligation(
        agreement_ref=failed_id, obligation_index=0, obligation=plan["obligations"][0],
    )
    def abort_new_registration(conn):
        SettlementSQLiteRepository.upsert_settlement_obligation_in_transaction(conn, failed_record.model_dump())
        raise RuntimeError("abort after bookkeeping")
    with pytest.raises(RuntimeError, match="abort after bookkeeping"):
        await restarted.db.commit_settlement_plan(
            negotiation_id=failed_id, settlement_plan=plan,
            buyer_principal=BUYER.identity, seller_principal=SELLER.identity,
            register_bookkeeping=abort_new_registration,
        )
    assert (await restarted.db.load_negotiation_thread_row(negotiation_id=failed_id))["settlement_plan"] is None
    assert await restarted.settlement_repository.load_settlement_obligation(failed_record.obligation_ref) is None


def test_legacy_accepted_unregistered_read_remains_unknown(environment, monkeypatch):
    with _server(monkeypatch) as (url, runtime):
        outcome = _accept_contact(url, runtime)
        plan = outcome.settlement_plan.model_dump(mode="json")
        ref = derive_obligation_ref(outcome.negotiation_id, 0, plan["obligations"][0])
        # Model the old persisted format: accepted plan but no bookkeeping.
        # Only this disposable test database is modified, before any start.
        with sqlite3.connect(runtime.db.db_path) as conn:
            conn.execute("DELETE FROM settlement_obligations WHERE obligation_ref=?", (ref,))
    with _server(monkeypatch) as (url, restarted):
        with httpx.Client(base_url=url, trust_env=False) as client:
            response = client.get(f"/api/v1/introductions/{ref}", headers=_signed_headers(BUYER, "introduction_read", ref))
        assert response.status_code == 404
        assert response.json() == {"detail": "introduction not found"}
        assert "x-market-signature" not in response.headers
        assert asyncio.run(restarted.settlement_repository.load_settlement_obligation(ref)) is None
        assert asyncio.run(restarted.db.load_contact_introduction(obligation_ref=ref)) is None
        # The existing explicit start carries the missing agreement identity.
        revealed = _transport(url, BUYER).start(
            negotiation_id=outcome.negotiation_id, obligation_ref=ref, contact_payload=BUYER_CONTACT,
        )
        assert revealed["counterparty_contact"] == SELLER_CONTACT
