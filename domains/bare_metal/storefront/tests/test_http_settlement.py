from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import json
import sqlite3
import time
import uuid

from fastapi.testclient import TestClient
from market_core.schemas import SettlementPlan
from market_fulfillment import VersionedEnvelope
from market_settlement_runtime import derive_obligation_ref
from market_identity import (
    EMPTY_BODY,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)

from arkhai_bare_metal import BareMetalMessage, BareMetalTerms
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
ESCROW_ADDRESS = "0x1111111111111111111111111111111111111111"
ESCROW_UID = "0x" + "ab" * 32
OTHER_ESCROW_UID = "0x" + "cd" * 32


def _settle_body(negotiation_id: str) -> dict:
    return {
        "negotiation_id": negotiation_id,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_evm_address": BUYER,
    }


def _headers(
    operation: str,
    resource_id: str,
    body: dict | None = None,
    *,
    method: str = "POST",
) -> dict[str, str]:
    timestamp = int(time.time())
    signed = sign_request(
        signer=BUYER_SIGNER,
        envelope=RequestEnvelope(
            role="buyer",
            principal=BUYER_SIGNER.identity,
            method=method,
            operation=operation,
            resource=resource_id,
            request_id=f"test-{uuid.uuid4().hex}",
            timestamp=timestamp,
            body_hash=canonical_body_hash(EMPTY_BODY if body is None else body),
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


def _plan(**kwargs):
    expiration_unix = (
        kwargs["proposal"]["expiration_unix"]
        if isinstance(kwargs["proposal"], dict)
        else kwargs["proposal"].expiration_unix
    )
    return {
        "settlement_plan": {
            "buyer_principal": kwargs["buyer_principal"].model_dump(mode="json"),
            "seller_principal": kwargs["seller_principal"].model_dump(mode="json"),
            "obligations": [
                {
                    "payer": "seller",
                    "claimant": "buyer",
                    "amount": 25,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "payer_principal": kwargs["seller_principal"].model_dump(
                        mode="json"
                    ),
                    "claimant_principal": kwargs["buyer_principal"].model_dump(
                        mode="json"
                    ),
                    "params": {"chain_name": "anvil", "kind": "seller-bond"},
                },
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": 100,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "params": {"chain_name": "anvil", "kind": "primary-payment"},
                    "payer_principal": kwargs["buyer_principal"].model_dump(
                        mode="json"
                    ),
                    "claimant_principal": kwargs["seller_principal"].model_dump(
                        mode="json"
                    ),
                },
            ],
            "service_terms": {},
        }
    }


async def _accepted_runtime(
    path: str, verifier
) -> tuple[BareMetalStorefrontRuntime, str]:
    domain = get_market_domain_contract()
    db = SQLiteClient(path, domain=domain)
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(
            identities=(ADMIN_SIGNER.identity,),
        ),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address="0x3333333333333333333333333333333333333333",
        plan_builder=_plan,
        chain_clients={"anvil": object()},
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    await db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="now",
        updated_at="now",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
    )
    negotiation_id = "neg-accepted"
    await db.persist_bare_metal_opening(
        negotiation_id=negotiation_id,
        listing_id="listing-1",
        seller_principal=runtime.seller_principal,
        buyer_agent_id="https://buyer.example",
        buyer_principal=BUYER_SIGNER.identity,
        seller_reference_amount=100,
        strategy="listed",
        message=BareMetalMessage(
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 persisted-key",
        ),
        proposal={
            "chain_name": "anvil",
            "escrow_address": ESCROW_ADDRESS,
            "fields": {"amount": "100"},
            "expiration_unix": int(time.time()) + 3600,
        },
        buyer_amount=100,
        seller_action="accept",
        seller_amount=100,
        terms=BareMetalTerms(
            machine_id="machine-1",
            physical_host_id="host-1",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 persisted-key",
            listing_ref="listing-1",
        ),
        agreed_amount=100,
    )
    return runtime, negotiation_id


async def test_settlement_is_verified_idempotently_without_fulfillment_claims(
    tmp_path,
) -> None:
    calls = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    app = _app(runtime)
    body = _settle_body(negotiation_id)

    with TestClient(app) as client:
        first = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID, body),
        )
        retry = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID, body),
        )
        conflict = client.post(
            f"/api/v1/settle/{OTHER_ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", OTHER_ESCROW_UID, body),
        )

    restarted_domain = get_market_domain_contract()
    restarted = BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=restarted_domain),
        domain=restarted_domain,
        seller_principal=runtime.seller_principal,
        admin_principals=runtime.admin_principals,
        storefront_url=runtime.storefront_url,
        marketplace_signer=runtime.marketplace_signer,
        seller_evm_address=runtime.seller_evm_address,
        plan_builder=_plan,
        chain_clients={},
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    with TestClient(_app(restarted)) as client:
        restart_retry = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID, body),
        )
        status = client.get(
            f"/api/v1/settle/{ESCROW_UID}/status",
            headers=_headers(
                "settle_status",
                ESCROW_UID,
                method="GET",
            ),
        )

    obligation_ref = first.json().get("obligation_ref")
    assert isinstance(obligation_ref, str) and len(obligation_ref) == 64
    expected = {
        "escrow_uid": ESCROW_UID,
        "negotiation_id": negotiation_id,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "seller_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "status": "settlement_verified",
        "fulfillment_available": True,
        "obligation_ref": obligation_ref,
    }
    assert first.status_code == 200
    assert first.json() == expected
    assert retry.json() == expected
    assert status.json() == expected
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "negotiation already has a primary escrow"
    assert len(calls) == 1
    assert calls[0]["agreed_duration_seconds"] == 3600
    assert calls[0]["agreed_price"] == 100
    assert "ssh_public_key" not in body
    assert not (
        {"provisioning_job_id", "tenant_credentials", "receipt", "result"}
        & first.json().keys()
    )
    assert restart_retry.json() == expected
    assert restarted.settlement_runtime._clients == {}
    aggregate = await restarted.settlement_runtime.get_status(negotiation_id)
    expiration_unix = aggregate.obligations[1].obligation["expiration_unix"]
    obligations = SettlementPlan.model_validate(
        _plan(
            proposal={"expiration_unix": expiration_unix},
            buyer_principal=BUYER_SIGNER.identity,
            seller_principal=SELLER_SIGNER.identity,
        )["settlement_plan"]
    ).model_dump(mode="json")["obligations"]
    assert aggregate.status == "active"
    assert len(aggregate.obligations) == 2
    assert aggregate.obligations[0].mechanism_ref is None
    verified = aggregate.obligations[1]
    assert verified.obligation_ref == derive_obligation_ref(
        negotiation_id,
        1,
        obligations[1],
    )
    assert verified.mechanism_ref == ESCROW_UID
    assert verified.materialization_state == "materialized"
    assert verified.mechanism_status == "ready"
    assert verified.mechanism_state == {}
    assert verified.condition_anchor is None
    assert verified.fulfillment_ref is None
    assert verified.condition_state == "pending"
    assert verified.collection_state == "pending"
    assert all(item.fulfillment_ref is None for item in aggregate.obligations)

    conn = sqlite3.connect(path)
    try:
        operations = conn.execute(
            "SELECT operation, state FROM settlement_operations "
            "ORDER BY obligation_ref, operation"
        ).fetchall()
        legacy_claim_table = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'settlement_claims'"
        ).fetchone()
        legacy_claims = (
            conn.execute("SELECT COUNT(*) FROM settlement_claims").fetchone()[0]
            if legacy_claim_table is not None
            else 0
        )
    finally:
        conn.close()
    assert operations == [("materialize", "succeeded")]
    assert legacy_claims == 0


async def test_settlement_rejects_replacement_access_input_and_failed_verification(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise ValueError("chain mismatch")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    app = _app(runtime)

    with TestClient(app) as client:
        replacement_body = {
            **_settle_body(negotiation_id),
            "ssh_public_key": "attacker-key",
        }
        replacement = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=replacement_body,
            headers=_headers("settle_escrow", ESCROW_UID, replacement_body),
        )
        body = _settle_body(negotiation_id)
        failed = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID, body),
        )

    assert replacement.status_code == 422
    assert failed.status_code == 400
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None


async def test_settlement_rejects_unmatched_obligation_without_registering_claims(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        return 2

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    with TestClient(_app(runtime)) as client:
        body = _settle_body(negotiation_id)
        response = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID, body),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "settlement verification returned no exact obligation"
    )
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None
    aggregate = await runtime.settlement_runtime.get_status(negotiation_id)
    assert aggregate.obligations == []


async def test_status_fails_closed_without_canonical_verified_adoption(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise AssertionError("status must not call a settlement provider")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    inserted = await runtime.db.insert_escrow(
        escrow_uid=ESCROW_UID,
        negotiation_id=negotiation_id,
        chain_name="anvil",
        escrow_address=ESCROW_ADDRESS,
        is_primary=True,
        status="settlement_verified",
    )
    assert inserted

    with TestClient(_app(runtime)) as client:
        response = client.get(
            f"/api/v1/settle/{ESCROW_UID}/status",
            headers=_headers("settle_status", ESCROW_UID, method="GET"),
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "verified settlement lifecycle is inconsistent"
    )


class _FulfillmentSite:
    def __init__(self) -> None:
        self.releases = []

    async def list_reservations(self):
        return []

    async def release(self, **request):
        self.releases.append(request)
        return {"state": "released"}


class _CapacityClient:
    def __init__(self) -> None:
        self.site_client = _FulfillmentSite()
        self.reservation_sites = {}
        self.reserve_calls = []

    def site(self, site_id):
        assert site_id == "site-a"
        return self.site_client

    async def reserve(self, **request):
        self.reserve_calls.append(request)
        self.reservation_sites["reservation-a"] = request["site"]
        return {
            "capacity_reservation_id": "reservation-a",
            "site": request["site"],
        }


class _ProvisioningClient:
    def __init__(self, *, torn_down: bool = False) -> None:
        self.begin_calls = []
        self.teardown_calls = []
        self.torn_down = torn_down

    async def schedule_resource(self, request):
        return SimpleNamespace(
            settlement_resource_id="settlement-resource-a",
            pool_id="pool-a",
            resource_kind="compute.bare-metal",
            provider="bare_metal.ansible",
            attributes={
                "bare_metal_publication": {
                    "enabled": True,
                    "machine_id": "machine-1",
                    "physical_host_id": "host-1",
                }
            },
        )

    async def begin_fulfillment(self, body):
        self.begin_calls.append(body)
        return SimpleNamespace(
            fulfillment_id="fulfillment-a",
            capacity_reservation_id="reservation-a",
            state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id, **request):
        assert fulfillment_id == "fulfillment-a"
        return SimpleNamespace(
            state="torn_down" if self.torn_down else "active",
            failure_reason=None,
            failure_message=None,
        )

    async def get_fulfillment_result(self, fulfillment_id, **request):
        return VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={
                "fulfillment_id": fulfillment_id,
                "capacity_reservation_id": "reservation-a",
                "state": "active",
                "provisioned_resources": [],
                "domain_result": {
                    "kind": "bare_metal.fulfillment.result.v1",
                    "schema_version": 1,
                    "payload": {
                        "kind": "bare_metal.v1",
                        "action": "node_grant_access",
                        "machine_id": "machine-1",
                        "physical_host_id": "host-1",
                        "ssh_user": "tenant-a",
                        "host": "203.0.113.25",
                        "port": 2222,
                        "status": "success",
                        "details": {"private_key": "must-not-cross-storefront"},
                    },
                },
            },
        )

    async def begin_fulfillment_teardown(self, fulfillment_id, **request):
        self.teardown_calls.append((fulfillment_id, request))
        self.torn_down = True
        return SimpleNamespace(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="reservation-a",
            state="teardown_dispatch_pending",
        )


async def test_http_fulfillment_restarts_on_recorded_site_and_redacts_result(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    capacity = _CapacityClient()
    provisioning = _ProvisioningClient()
    runtime = replace(
        runtime,
        capacity_client=capacity,
        fulfillment_client=provisioning,
    )
    settle_body = _settle_body(negotiation_id)
    begin_body = {
        "negotiation_id": negotiation_id,
        "escrow_uid": ESCROW_UID,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
    }

    with TestClient(_app(runtime)) as client:
        settled = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=settle_body,
            headers=_headers("settle_escrow", ESCROW_UID, settle_body),
        )
        begun = client.post(
            "/api/v1/fulfillments/begin",
            json=begin_body,
            headers=_headers(
                "bare_metal_fulfillment_begin",
                negotiation_id,
                begin_body,
            ),
        )
        ready = client.get(
            f"/api/v1/fulfillments/{negotiation_id}/status",
            headers=_headers(
                "bare_metal_fulfillment_status",
                negotiation_id,
                method="GET",
            ),
        )
        result = client.get(
            f"/api/v1/fulfillments/{negotiation_id}/result",
            headers=_headers(
                "bare_metal_fulfillment_result",
                negotiation_id,
                method="GET",
            ),
        )
        access = client.get(
            f"/api/v1/fulfillments/{negotiation_id}/access",
            headers=_headers(
                "bare_metal_fulfillment_access",
                negotiation_id,
                method="GET",
            ),
        )
        tearing_down = client.post(
            f"/api/v1/fulfillments/{negotiation_id}/teardown",
            headers=_headers(
                "bare_metal_fulfillment_teardown",
                negotiation_id,
            ),
        )

    restarted_capacity = _CapacityClient()
    restarted = replace(
        runtime,
        db=SQLiteClient(path, domain=runtime.domain),
        capacity_client=restarted_capacity,
        fulfillment_client=_ProvisioningClient(torn_down=True),
    )
    with TestClient(_app(restarted)) as client:
        released = client.get(
            f"/api/v1/fulfillments/{negotiation_id}/status",
            headers=_headers(
                "bare_metal_fulfillment_status",
                negotiation_id,
                method="GET",
            ),
        )
        repeated = client.get(
            f"/api/v1/fulfillments/{negotiation_id}/status",
            headers=_headers(
                "bare_metal_fulfillment_status",
                negotiation_id,
                method="GET",
            ),
        )

    assert settled.status_code == 200
    assert begun.status_code == 200
    assert ready.json()["state"] == "active"
    assert tearing_down.json()["state"] == "teardown_dispatch_pending"
    assert released.json()["state"] == "released"
    assert repeated.json() == released.json()
    assert capacity.reserve_calls[0]["site"] == "site-a"
    assert capacity.reserve_calls[0]["claim"]["resource_id"] == "resource-1"
    assert len(provisioning.begin_calls) == 1
    assert len(provisioning.teardown_calls) == 1
    assert len(restarted_capacity.site_client.releases) == 1
    public_result = result.json()
    assert public_result["receipt"]["status"] == "ready"
    assert public_result["result"]["ssh_user"] == "tenant-a"
    assert public_result["result"]["host"] is None
    assert public_result["result"]["port"] is None
    assert access.json() == {
        "negotiation_id": negotiation_id,
        "method": "ssh",
        "host": "203.0.113.25",
        "port": 2222,
        "username": "tenant-a",
        "expires_at": None,
    }
    serialized_result = json.dumps(public_result, sort_keys=True)
    for forbidden in (
        "authority_url",
        "credential",
        "private_key",
        "provider",
        "provider_metadata",
    ):
        assert forbidden not in serialized_result
