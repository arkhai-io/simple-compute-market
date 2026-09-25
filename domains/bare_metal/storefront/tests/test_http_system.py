from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient
from market_identity import Eip191Signer, TrustedIdentitySet

from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError
from storefront_client.models import HealthResponse

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )

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
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[],
    )


async def test_listing_routes_return_exact_validated_domain_payload(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = _app(runtime)

    with TestClient(app) as client:
        response = client.get("/api/v1/listings/listing-1")
        listing_list = client.get("/api/v1/listings")
        missing = client.get("/api/v1/listings/missing")

    assert response.status_code == 200
    assert response.json()["listing_resource"] == {
        "capacity_backing": "backed",
        "kind": "bare_metal.v2",
        "offering_mode": "bare_metal",
        "host_id": "machine-1",
        "physical_host_id": "physical-host-1",
        "access_methods": ["ssh"],
        "max_duration_seconds": 7200,
        "capabilities": {},
    }
    assert listing_list.status_code == 200
    assert listing_list.json()["count"] == 1
    assert listing_list.json()["listings"][0]["listing_id"] == "listing-1"
    assert missing.status_code == 404


def _admin_client(app) -> StorefrontClient:
    """The canonical storefront client as the configured administrator.

    Responses are verified against the storefront's own marketplace signer.
    """
    return StorefrontClient(
        "http://seller",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def test_pause_is_admin_authenticated_and_survives_app_restart(tmp_path) -> None:
    path = str(tmp_path / "storefront.db")
    first_app = _app(_runtime(path))

    # Rejection path: an unsigned request is refused before any state changes.
    with TestClient(first_app) as client:
        assert client.post("/api/v1/admin/pause").status_code == 401
    async with first_app.router.lifespan_context(first_app):
        async with _admin_client(first_app) as admin:
            paused = await admin.admin_pause()
    assert (paused.paused, paused.message) == (True, "storefront paused")

    second_app = _app(_runtime(path))
    async with second_app.router.lifespan_context(second_app):
        async with _admin_client(second_app) as admin:
            status = await admin.get_system_status()
            resumed = await admin.admin_resume()

    assert status.paused is True
    assert resumed.paused is False


async def _health(runtime: BareMetalStorefrontRuntime) -> HealthResponse:
    """Read ``/health`` through the canonical storefront client.

    The app runs its own lifespan, which composes the runtime into the request
    container, and the client talks to it over the in-process transport.
    """
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as client:
            return await client.get_health()


async def test_health_is_truthful_about_uncomposed_authorities(tmp_path) -> None:
    health = await _health(_runtime(str(tmp_path / "storefront.db")))

    assert health.status == "degraded"
    assert health.checks == {
        "api": "ok",
        "database": "ok",
        "commercial_settlement": "unavailable",
        "fulfillment": "unavailable",
    }
    assert health.paused is False
    assert health.resource_count == 0
    assert health.site_projections == {}


class _Site:
    """A site authority's typed client, answering the projection version."""

    def __init__(self, *, revision: int = 0, error: Exception | None = None) -> None:
        self._revision = revision
        self._error = error

    async def resource_pool_projection_version(self) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        return {"revision": self._revision, "digest": f"digest-{self._revision}"}

    async def snapshot(self) -> list[dict[str, object]]:
        raise AssertionError("health must not read the aggregate capacity projection")


class _Sites:
    def __init__(self, sites: dict[str, _Site]) -> None:
        self._sites = sites

    def site(self, site_id: str) -> _Site:
        return self._sites[site_id]

    async def snapshot(self) -> list[dict[str, object]]:
        raise AssertionError("health must not read the aggregate capacity projection")


def _sited_runtime(path: str, sites: dict[str, _Site]) -> BareMetalStorefrontRuntime:
    runtime = _runtime(path)
    return BareMetalStorefrontRuntime(
        db=runtime.db,
        domain=runtime.domain,
        seller_principal=runtime.seller_principal,
        admin_principals=runtime.admin_principals,
        storefront_url=runtime.storefront_url,
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address=runtime.seller_evm_address,
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                # A development identity; never used on any public network.
                authority_principal=ADMIN_SIGNER.identity,
                authority_url=f"http://{site_id}:8000",
            )
            for site_id in sites
        ),
        capacity_client=_Sites(sites),
        fulfillment_client=object(),
    )


async def test_every_answering_site_is_reported_loaded(tmp_path) -> None:
    runtime = _sited_runtime(
        str(tmp_path / "storefront.db"),
        {"site-a": _Site(revision=3), "site-b": _Site(revision=5)},
    )

    health = await _health(runtime)

    projections = health.site_projections
    assert set(projections) == {"site-a", "site-b"}
    site_a = projections["site-a"]["resource_pool"]
    assert (site_a["state"], site_a["revision"], site_a["digest"]) == (
        "loaded",
        3,
        "digest-3",
    )
    assert site_a["fetched_at"] is not None
    assert projections["site-b"]["resource_pool"]["revision"] == 5
    assert "site_projection" not in health.checks
    assert health.checks["fulfillment"] == "ok"


async def test_one_site_unavailable_is_reported_outside_the_health_gate(
    tmp_path,
) -> None:
    """One site being down is reported for that site and changes no gated check.

    Asserted against ``checks`` directly, the dict the status gates on, so the
    test does not depend on unrelated checks being healthy.
    """
    healthy = await _health(
        _sited_runtime(
            str(tmp_path / "healthy.db"),
            {"site-a": _Site(revision=3), "site-b": _Site(revision=5)},
        )
    )
    one_down = await _health(
        _sited_runtime(
            str(tmp_path / "one-down.db"),
            {
                "site-a": _Site(revision=3),
                "site-b": _Site(error=ConnectionError("connection refused")),
            },
        )
    )

    site_b = one_down.site_projections["site-b"]["resource_pool"]
    assert site_b["state"] == "unavailable"
    assert "connection refused" in site_b["last_error"]
    assert one_down.site_projections["site-a"]["resource_pool"]["state"] == "loaded"
    assert one_down.checks == healthy.checks
    assert one_down.status == healthy.status
    assert "site_projections" not in one_down.checks


class _RecordingCycle:
    """Stands in for one publication pass, recording when it runs."""

    def __init__(self, log: list[str], name: str, gate: asyncio.Event | None) -> None:
        self._log = log
        self._name = name
        self._gate = gate

    async def run(self) -> dict[str, object]:
        self._log.append(f"start {self._name}")
        if self._gate is not None:
            await self._gate.wait()
        self._log.append(f"end {self._name}")
        return {"dry_run": False, "actions": [{"action": "publish"}], "counts": {"publish": 1}}


def _stepped_runtime(path: str, log: list[str], gate: asyncio.Event | None = None):
    runtime = _runtime(path)
    names = iter(("first", "second", "third"))
    return dataclasses.replace(
        runtime,
        publication_cycle_factory=lambda _runtime: _RecordingCycle(
            log, next(names), gate
        ),
    )


async def test_the_publication_step_runs_one_pass_and_returns_its_report(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            report = await admin.admin_run_lifecycle_cycle("publication")

    assert report == {
        "dry_run": False,
        "actions": [{"action": "publish"}],
        "counts": {"publish": 1},
    }
    assert log == ["start first", "end first"]


async def test_the_publication_step_refuses_an_unsigned_request(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    # Rejection path: an unsigned request is refused before any pass runs.
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/lifecycle/publication/run-cycle")

    assert response.status_code == 401
    assert log == []


async def test_a_loop_the_storefront_does_not_run_is_not_found(tmp_path) -> None:
    log: list[str] = []
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await admin.admin_run_lifecycle_cycle("capacity-events")

    assert refused.value.status_code == 404
    assert log == []


async def test_concurrent_publication_steps_run_one_after_the_other(tmp_path) -> None:
    log: list[str] = []
    gate = asyncio.Event()
    app = _app(_stepped_runtime(str(tmp_path / "storefront.db"), log, gate))

    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            first = asyncio.create_task(admin.admin_run_lifecycle_cycle("publication"))
            second = asyncio.create_task(admin.admin_run_lifecycle_cycle("publication"))
            while not log:
                await asyncio.sleep(0)
            # Give the second request every chance to start a pass of its own.
            for _ in range(50):
                await asyncio.sleep(0)
            assert log == ["start first"]
            gate.set()
            await asyncio.gather(first, second)

    assert log == ["start first", "end first", "start second", "end second"]
