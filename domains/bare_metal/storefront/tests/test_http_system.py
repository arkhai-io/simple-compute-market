from __future__ import annotations

import time
import uuid
from fastapi.testclient import TestClient
from market_identity import (
    EMPTY_BODY,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

SELLER_SECRET_HEX = "11" * 32
SELLER_SIGNER = Eip191Signer(bytes.fromhex(SELLER_SECRET_HEX))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))

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
    )


def _admin_headers(operation: str, resource: str, *, method: str) -> dict[str, str]:
    signed = sign_request(
        signer=ADMIN_SIGNER,
        envelope=RequestEnvelope(
            role="admin",
            principal=ADMIN_SIGNER.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=f"admin-{uuid.uuid4().hex}",
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(EMPTY_BODY),
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

def test_runtime_repr_does_not_serialize_signer_secret(tmp_path) -> None:
    rendered = repr(_runtime(str(tmp_path / "storefront.db")))
    assert SELLER_SECRET_HEX not in rendered
    assert "marketplace_signer" not in rendered


async def _insert_listing(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[],
    )


async def test_listing_routes_return_exact_validated_domain_payload(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.get("/api/v1/listings/listing-1")
        listing_list = client.get("/api/v1/listings")
        missing = client.get("/api/v1/listings/missing")

    assert response.status_code == 200
    assert response.json()["offer_resource"] == {
        "kind": "bare_metal.v1",
        "machine_id": "machine-1",
        "physical_host_id": "physical-host-1",
        "access_methods": ["ssh"],
        "max_duration_seconds": 7200,
        "capabilities": {},
    }
    assert listing_list.status_code == 200
    assert listing_list.json()["count"] == 1
    assert listing_list.json()["listings"][0]["listing_id"] == "listing-1"
    assert missing.status_code == 404


async def test_pause_is_admin_authenticated_and_survives_app_restart(tmp_path) -> None:
    path = str(tmp_path / "storefront.db")
    first_runtime = _runtime(path)
    first_app = build_bare_metal_storefront_app(runtime=first_runtime)

    with TestClient(first_app) as client:
        assert client.post("/api/v1/admin/pause").status_code == 401
        paused = client.post(
            "/api/v1/admin/pause",
            headers=_admin_headers(
                "pause",
                "/api/v1/admin/pause",
                method="POST",
            ),
        )
        assert paused.json() == {"paused": True, "message": "storefront paused"}

    second_runtime = _runtime(path)
    second_app = build_bare_metal_storefront_app(runtime=second_runtime)
    with TestClient(second_app) as client:
        status = client.get(
            "/api/v1/system/status",
            headers=_admin_headers(
                "system_status",
                "/api/v1/system/status",
                method="GET",
            ),
        )
        resumed = client.post(
            "/api/v1/admin/resume",
            headers=_admin_headers(
                "resume",
                "/api/v1/admin/resume",
                method="POST",
            ),
        )

    assert status.status_code == 200
    assert status.json()["paused"] is True
    assert resumed.json()["paused"] is False


async def test_health_is_truthful_about_uncomposed_authorities(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "api": "ok",
            "database": "ok",
            "commercial_settlement": "unavailable",
            "site_projection": "unavailable",
            "fulfillment": "unavailable",
        },
        "paused": False,
        "principal": SELLER_SIGNER.identity.model_dump(mode="json"),
        "sites": [],
        "resource_count": 0,
    }
