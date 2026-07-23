from __future__ import annotations

from fastapi.testclient import TestClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


def _runtime(path: str) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_id="seller-1",
        admin_key="admin-secret",
    )


async def _insert_listing(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller="seller-1",
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
        assert client.post("/api/v1/admin/pause").status_code == 403
        paused = client.post(
            "/api/v1/admin/pause",
            headers={"X-Admin-Key": "admin-secret"},
        )
        assert paused.json() == {"paused": True, "message": "storefront paused"}

    second_runtime = _runtime(path)
    second_app = build_bare_metal_storefront_app(runtime=second_runtime)
    with TestClient(second_app) as client:
        status = client.get(
            "/api/v1/system/status",
            headers={"X-Admin-Key": "admin-secret"},
        )
        resumed = client.post(
            "/api/v1/admin/resume",
            headers={"X-Admin-Key": "admin-secret"},
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
            "site_configuration": "unavailable",
            "site_projection": "unavailable",
            "fulfillment": "unavailable",
        },
        "paused": False,
        "agent_id": "seller-1",
        "chain_id": None,
        "resource_count": 0,
    }
