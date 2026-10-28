"""Integration tests for the Admin API.

Uses the async ``StorefrontClient`` via ``httpx.ASGITransport``,
matching the provisioning-service integration test pattern.
All assertions go through the canonical client.

Key fixture change from Starlette → FastAPI: the AdminController and
SystemController now import the global pause functions from server.py via
their defaults. For testing we need to control the pause state, so the
fixture wires the container and uses the module-level flag in server.py
directly (same as production).
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet
from core_storefront.models.system_models import STAGE_EVENT_PAGE_CAP
from core_storefront.service_peers import ServicePeerTrust

import market_storefront.container as _container
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
import market_storefront.lifecycle as _lifecycle
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.utils.sqlite_client import SQLiteClient

from market_storefront.services.system_service import SystemService
from storefront_client.client import StorefrontClient, StorefrontClientError
from tests.publication_app import recorded_registries
from tests.fake_site import (
    FakeProjectionSite,
    FakeSite,
    loaded_site_projection_state,
    site_capacity,
    site_projection_state,
)


def _no_projections():
    """A projection state over one site that has served nothing yet."""
    return site_projection_state({"default": FakeProjectionSite(resource_pools=[])})


_TEST_SELLER_PRINCIPAL = Identity(
    scheme="eip191",
    identifier="0x2222222222222222222222222222222222222222",
)

_MARKETPLACE_SIGNER = Ed25519Signer(b"\x61" * 32)
_ADMIN_SIGNER = Ed25519Signer(b"\x62" * 32)
_UNTRUSTED_ADMIN_SIGNER = Ed25519Signer(b"\x63" * 32)
_SERVICE_SIGNER = Ed25519Signer(b"\x64" * 32)
_MARKETPLACE_PUBLISHERS = TrustedIdentitySet(
    identities=(_MARKETPLACE_SIGNER.identity,)
)
_ADMIN_PRINCIPALS = TrustedIdentitySet(identities=(_ADMIN_SIGNER.identity,))
_SERVICE_PRINCIPALS = TrustedIdentitySet(identities=(_SERVICE_SIGNER.identity,))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path) -> SQLiteClient:
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    return SQLiteClient(
        db_path=str(tmp_path / "admin_test.db"),
        registry=registry,
    )


@pytest_asyncio.fixture(autouse=True)
def reset_pause_state():
    """Ensure the process's trading pause is reset between tests."""
    _lifecycle.trading_pause().resume()
    yield
    _lifecycle.trading_pause().resume()


@pytest_asyncio.fixture
async def admin_app(db) -> AsyncIterator[FastAPI]:
    _container.resolved_domain_registry = db.domain_registry
    _container.resolved_sqlite_client = db
    _container.resolved_marketplace_signer = _MARKETPLACE_SIGNER
    _container.resolved_system_service = SystemService(
        sqlite_client=db,
        marketplace_signer=_MARKETPLACE_SIGNER,
        site_projections=_no_projections(),
    )

    with (
        patch(
            "market_storefront.middleware.admin_identity.get_administrator_configs",
            return_value={"operator": _ADMIN_PRINCIPALS},
        ),
    ):
        initialize_administrator_identities(db.db_path)
        service_peer_trust = ServicePeerTrust(
            db.db_path,
            {"system-status": ("service", "default", _SERVICE_PRINCIPALS)},
        )
        service_peer_trust.seed()
        _container.resolved_service_peer_trust = service_peer_trust
        app = FastAPI()
        app.include_router(system_router)
        app.include_router(admin_router)
        app.middleware("http")(service_peer_callback_middleware)
        app.middleware("http")(administrator_identity_middleware)
        yield app

    _container.resolved_domain_registry = None
    _container.resolved_capacity_runtime = None
    _container.resolved_sqlite_client = None
    _container.resolved_marketplace_signer = None
    _container.resolved_system_service = None
    _container.resolved_service_peer_trust = None


@pytest_asyncio.fixture
async def client(
    admin_app, db
) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    transport = httpx.ASGITransport(app=admin_app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        signer=_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_MARKETPLACE_PUBLISHERS,
    ) as c:
        yield c, db


@pytest_asyncio.fixture
async def client_untrusted(admin_app) -> AsyncIterator[StorefrontClient]:
    transport = httpx.ASGITransport(app=admin_app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        signer=_UNTRUSTED_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_MARKETPLACE_PUBLISHERS,
    ) as c:
        yield c


@pytest_asyncio.fixture
async def unsigned_client(admin_app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_client(admin_app) -> AsyncIterator[StorefrontClient]:
    """Administrator-role client.

    System status is an administrator operation: the operation it binds is
    named for the administrator, and its sibling read on the same prefix
    (GET /api/v1/system/events) is an administrator contract too. The
    service-peer client below remains for the provisioning callbacks, which
    are genuinely service-to-service.
    """
    transport = httpx.ASGITransport(app=admin_app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        signer=_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_MARKETPLACE_PUBLISHERS,
    ) as c:
        yield c


@pytest_asyncio.fixture
async def service_client(admin_app) -> AsyncIterator[StorefrontClient]:
    transport = httpx.ASGITransport(app=admin_app)
    async with StorefrontClient(
        "http://test",
        transport=transport,
        signer=_SERVICE_SIGNER,
        caller_role="service",
        expected_publishers=_MARKETPLACE_PUBLISHERS,
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        c, _ = client
        result = await c.get_health()
        assert result.status == "ok"
        assert result.checks.get("database") == "ok"
        assert "registry" not in result.checks

    async def test_system_status_includes_paused(self, admin_client):
        result = await admin_client.get_system_status()
        assert result.paused is False

    async def test_system_status_reports_no_resource_count(self, admin_client):
        result = await admin_client.get_system_status()
        assert "resource_count" not in result.extra

    async def test_system_status_readable_by_service_peer(self, service_client):
        """A service peer reads status to confirm its own signing path works.

        This is the provisioning adapter's `storefront_auth` health check. It
        is the only side-effect-free service operation available — the other
        is the capacity-released callback, which mutates state — so if this
        route stops accepting the `service` role, provisioning loses its only
        way to verify the credential it uses for that callback.
        """
        result = await service_client.get_system_status()
        assert result.status in ("ok", "degraded")

    async def test_any_configured_sites_peer_reads_status(self, admin_app, db):
        """Two sites, each bound to its own peer: the read names no site, so the
        second site's peer reads status as the first's does, and a principal no
        configured peer holds is refused."""
        site_b = Ed25519Signer(b"\x65" * 32)
        stranger = Ed25519Signer(b"\x66" * 32)
        trust = ServicePeerTrust(
            db.db_path,
            {
                "system-status": ("service", "default", _SERVICE_PRINCIPALS),
                "site-b-peer": (
                    "service",
                    "site-b",
                    TrustedIdentitySet(identities=(site_b.identity,)),
                ),
            },
        )
        trust.seed()
        _container.resolved_service_peer_trust = trust
        transport = httpx.ASGITransport(app=admin_app)
        results = {}
        for name, signer in (("a", _SERVICE_SIGNER), ("b", site_b), ("stranger", stranger)):
            async with StorefrontClient(
                "http://test",
                transport=transport,
                signer=signer,
                caller_role="service",
                expected_publishers=_MARKETPLACE_PUBLISHERS,
            ) as service:
                try:
                    results[name] = (await service.get_system_status()).status
                except StorefrontClientError as exc:
                    # Refused before any handler: an unsigned 403 the client reports.
                    results[name] = str(exc)

        assert results["a"] in ("ok", "degraded")
        assert results["b"] in ("ok", "degraded")
        assert results["stranger"].startswith("HTTP 403"), results["stranger"]

    async def test_system_status_includes_registry_check(self, admin_client):
        result = await admin_client.get_system_status()
        registry_check = result.checks.get("registry")
        assert registry_check is not None
        assert isinstance(registry_check, str) and registry_check

    async def test_system_status_includes_negotiation_strategy_check(
        self, admin_client
    ):
        result = await admin_client.get_system_status()
        strat_check = result.checks.get("negotiation_strategy")
        assert strat_check is not None
        assert isinstance(strat_check, str) and strat_check
        assert "exit_on_probe" not in strat_check, (
            f"Negotiation strategy would exit on every round: {strat_check!r}"
        )

    async def test_system_status_surfaces_site_projection_state(
        self, db, admin_client
    ):
        """End-to-end: a populated projection status summary must survive
        SystemService -> HealthResponse (server, pydantic) -> HTTP JSON ->
        HealthResponse (client, dataclass) intact. Exercises the real route
        through the real StorefrontClient, not SystemService in isolation --
        this is exactly the layer a service-level unit test cannot prove.
        """
        summary = {
            "site-a": {
                "resource_pool": {
                    "state": "loaded",
                    "revision": 3,
                    "digest": "abc123",
                    "last_error": None,
                    "fetched_at": "2026-08-03T12:00:00+00:00",
                },
                "capacity_bucket": {
                    "state": "unavailable",
                    "revision": None,
                    "digest": None,
                    "last_error": "connection refused",
                    "fetched_at": None,
                },
            },
        }
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            marketplace_signer=_MARKETPLACE_SIGNER,
            site_projections=_no_projections(),
            projection_status_provider=lambda: summary,
        )
        result = await admin_client.get_system_status()

        assert result.site_projections == summary
        assert result.site_projections["site-a"]["resource_pool"]["state"] == "loaded"
        assert result.site_projections["site-a"]["capacity_bucket"]["state"] == "unavailable"

    async def test_health_omits_site_projections(self, db, service_client):
        """The fast liveness probe (/health) must not carry this field at all."""
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            marketplace_signer=_MARKETPLACE_SIGNER,
            site_projections=_no_projections(),
            projection_status_provider=lambda: {"site-a": {}},
        )
        result = await service_client.get_health()

        assert result.site_projections is None

    async def test_system_status_surfaces_listing_cardinality_mode_explanations(
        self, db, admin_client
    ):
        """Same real end-to-end round trip as
        test_system_status_surfaces_site_projection_state (above), for the
        sibling field -- this is exactly the layer that hid the original
        site_projections bug (Pydantic v2's default extra="ignore" silently
        dropping a field the server model hadn't declared), so the new
        field gets the same real-HTTP proof rather than only a
        SystemService-level unit test.
        """
        explanations = {
            "site-a": {"gpu-pool": "unrecognized listing_cardinality_mode 'bogus', using 'fungible'"},
        }
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            marketplace_signer=_MARKETPLACE_SIGNER,
            site_projections=_no_projections(),
            listing_cardinality_mode_explanation_provider=lambda: explanations,
        )
        result = await admin_client.get_system_status()

        assert result.listing_cardinality_mode_explanations == explanations

    async def test_health_omits_listing_cardinality_mode_explanations(
        self, db, service_client
    ):
        """The fast liveness probe (/health) must not carry this field either."""
        _container.resolved_system_service = SystemService(
            sqlite_client=db,
            marketplace_signer=_MARKETPLACE_SIGNER,
            site_projections=_no_projections(),
            listing_cardinality_mode_explanation_provider=lambda: {"site-a": {}},
        )
        result = await service_client.get_health()

        assert result.listing_cardinality_mode_explanations is None


# ---------------------------------------------------------------------------
# POST /admin/pause
# ---------------------------------------------------------------------------

class TestAdminPause:
    async def test_missing_auth_is_rejected(self, unsigned_client):
        response = await unsigned_client.post("/api/v1/admin/pause", json={})
        assert response.status_code == 401

    async def test_valid_untrusted_principal_is_rejected(self, client_untrusted):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_untrusted.admin_pause()
        assert exc_info.value.status_code == 403

    async def test_pause_sets_flag(self, client):
        c, _ = client
        result = await c.admin_pause()
        assert result.paused is True
        assert _lifecycle.trading_pause().paused is True

    async def test_pause_reflected_in_system_status(self, client, admin_client):
        c, _ = client
        await c.admin_pause()
        status = await admin_client.get_system_status()
        assert status.paused is True


# ---------------------------------------------------------------------------
# POST /admin/resume
# ---------------------------------------------------------------------------

class TestAdminResume:
    async def test_rejects_untrusted_principal(self, client_untrusted):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_untrusted.admin_resume()
        assert exc_info.value.status_code == 403

    async def test_resume_clears_flag(self, client):
        c, _ = client
        await c.admin_pause()
        assert _lifecycle.trading_pause().paused is True
        result = await c.admin_resume()
        assert result.paused is False
        assert _lifecycle.trading_pause().paused is False

    async def test_resume_reflected_in_system_status(self, client, admin_client):
        c, _ = client
        await c.admin_pause()
        await c.admin_resume()
        status = await admin_client.get_system_status()
        assert status.paused is False

async def _seed_dynamic_listing_pool_rows(
    db: SQLiteClient,
    *,
    site_id: str = "default",
) -> None:
    for gpu_count in range(1, 5):
        listing_id = f"listing-{gpu_count}x"
        await db.upsert_listing(
            listing_id=listing_id,
            status="open",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            listing_resource={
                "resource_id": "pool-h200-1",
                "gpu_model": "H200",
                "gpu_count": gpu_count,
                "region": "California, US",
                "sla": 99.0,
                "offering_mode": "vm",
            },
            accepted_escrows=[{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }],
            demands=[],
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://seller",
            seller_principal=_TEST_SELLER_PRINCIPAL,
        )
        await db.record_listing_binding(
            binding=prepare_vm_listing_binding(
                listing_id=listing_id,
                candidate={
                    "capacity_backing": "backed",
                    "site_id": site_id,
                    "pool_id": "pool-h200-1",
                    # The listing publishes this resource, so its binding names
                    # it: a stored key is read from the binding.
                    "resource_id": "pool-h200-1",
                    "listing_shape": {"gpu": {"count": gpu_count, "model": "H200"}},
                },
            )
        )


def _fake_pool_site():
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "pool-h200-1", 4,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "host-1",
            "offering_mode": "vm",
        },
    )
    return fake


async def _ledger_hold(capacity, *, gpu_count: int = 2) -> str:
    reserved = await capacity.reserve(
        claim={
            "offering_mode": "vm",
            "resource_id": "pool-h200-1",
            "gpu_count": gpu_count,
        },
        deal_ref={"listing_id": "listing-2x", "escrow_uid": "escrow-2x"},
    )
    assert reserved is not None
    return str(reserved["capacity_reservation_id"])


class TestFulfillmentEvents:
    """The admin reserve and the capacity-released callback over the
    site-authority ledger.

    The reservation rows live in the ledger; a reserve closes the derived
    listings its hold makes stale, and the capacity-released callback returns
    the units through the capacity client and reopens what they make
    available again.
    """

    async def test_admin_reserve_capacity_closes_oversized_listings(self, client):
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        async with site_capacity(_fake_pool_site(), project_pool_modes=True):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x",
                escrow_uid="manual-escrow-2x",
            )

        assert response.capacity_reservation_id
        # Pool membership, not physical identity: the capacity boundary
        # strips `resource_id` from every reservation response, so the
        # storefront reports the pool its own durable listing binding
        # recorded at publication.
        assert response.pool_id == "pool-h200-1"
        assert response.gpu_count == 2
        assert sorted(response.closed_listing_ids) == ["listing-3x", "listing-4x"]
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }

    async def test_admin_reserve_capacity_for_a_mapped_listing_pins_to_its_site(
        self, client,
    ):
        """A durably bound listing must reserve at its exact site rather than
        re-running placement for an already-derived candidate.
        """
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        async with site_capacity(_fake_pool_site(), project_pool_modes=True):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x",
                escrow_uid="manual-escrow-2x",
            )

        assert response.capacity_reservation_id
        # The site this listing is bound to, read back from the binding that
        # pinned it -- the response carries no physical resource identity to
        # assert on, by design of the capacity boundary.
        assert response.pool_id == "pool-h200-1"

    async def test_admin_reserve_capacity_honors_a_live_refusal_over_a_cached_projection(
        self, client,
    ):
        """A fresh, valid cached site_resource_pools projection showing
        abundant capacity must not override what the site's live
        reservations endpoint actually says. reserve() has no code path
        that reads the projection cache at all today (confirmed
        directly against aggregation.py -- zero references); this test
        proves the *observable* consequence of that fact, so it fails
        immediately if a future change ever adds such a shortcut.
        """
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        # The live site genuinely has zero capacity for this resource.
        fake = FakeSite(deliverable_modes={"vm"})
        fake.add_resource(
            "pool-h200-1", 0,
            attributes={
                "gpu_model": "H200",
                "vm_host": "host-1",
                "offering_mode": "vm",
            },
        )

        # A held projection of the same site, same pool, claiming abundant
        # capacity -- fresh, loaded, not stale.
        held = await loaded_site_projection_state({"default": FakeProjectionSite(
            resource_pools=[{
                "pool_id": "pool-h200-1",
                "resources": [{
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H200"},
                    "enabled": True,
                }],
            }],
        )})

        async with site_capacity(fake, project_pool_modes=True):
            with patch.object(_container, "resolved_site_projections", held):
                with pytest.raises(StorefrontClientError) as exc_info:
                    await c.admin_reserve_capacity(
                        required_attributes={
                            "resource_id": "pool-h200-1",
                            "gpu_count": 2,
                        },
                        listing_id="listing-2x",
                        escrow_uid="manual-escrow-refused",
                    )

        assert "409" in str(exc_info.value)

    async def test_admin_reserve_reports_listings_closed_by_delta_race(self, client):
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()
        original_handle = fake._handle

        def handle_with_delta_reconciliation(request):
            response = original_handle(request)
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/capacity/reservations"
            ):
                conn = sqlite3.connect(db.db_path)
                try:
                    conn.execute(
                        "UPDATE listings SET status = 'closed', "
                        "closed_by = 'reconciliation' WHERE listing_id = ?",
                        ("listing-3x",),
                    )
                    conn.commit()
                finally:
                    conn.close()
            return response

        fake._handle = handle_with_delta_reconciliation
        async with site_capacity(fake, project_pool_modes=True):
            response = await c.admin_reserve_capacity(
                required_attributes={
                    "resource_id": "pool-h200-1",
                    "gpu_count": 2,
                },
                listing_id="listing-2x",
                escrow_uid="manual-escrow-2x",
            )

        assert sorted(response.closed_listing_ids) == [
            "listing-3x",
            "listing-4x",
        ]

    async def test_admin_reserve_capacity_returns_409_when_no_capacity(self, client):
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        async with site_capacity(_fake_pool_site(), project_pool_modes=True) as capacity:
            await _ledger_hold(capacity, gpu_count=2)
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 3,
                    },
                    listing_id="listing-3x",
                    escrow_uid="manual-escrow-3x",
                )

        assert "409" in str(exc_info.value)

    async def test_admin_reserve_capacity_returns_500_for_a_stale_site_mapping(
        self, client,
    ):
        """A listing mapped to a site that isn't currently configured is
        a data-integrity problem, not a capacity answer -- must not be
        collapsed into the same 409 a genuine refusal returns."""
        c, db = client
        await _seed_dynamic_listing_pool_rows(db, site_id="ghost-site")

        async with site_capacity(_fake_pool_site(), project_pool_modes=True):
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-2x",
                    escrow_uid="manual-escrow-stale",
                )

        assert "500" in str(exc_info.value)

    async def test_a_refused_reservation_checks_both_families_once_and_is_not_retried(
        self, client,
    ):
        """A topology-sensitive refusal triggers one drift check of every
        projection family of the refusing site, through the site client the
        state installed its handler on; the reservation is not retried, and a
        resource-pool change the check finds wakes publication."""
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()
        fake.capacity_buckets = []
        original_dispatch = fake._dispatch

        def refuse_reservations(request):
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/capacity/reservations"
            ):
                # The pool changed beneath the claim the storefront sent.
                fake.pool_projection_revision += 1
                return httpx.Response(409, json={"detail": "resource pool changed"})
            return original_dispatch(request)

        fake._dispatch = refuse_reservations
        wakes: list[None] = []
        async with site_capacity(
            fake, project_pool_modes=True, on_resource_pool_change=lambda: wakes.append(None)
        ):
            refused_at, woken = len(fake.requests), len(wakes)
            with pytest.raises(StorefrontClientError):
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-2x",
                    escrow_uid="manual-escrow-drift",
                )

        after = fake.requests[refused_at:]
        assert after.count(("POST", "/api/v1/capacity/reservations")) == 1
        refusal = after.index(("POST", "/api/v1/capacity/reservations"))
        checked = after[refusal + 1:]
        assert checked.count(("GET", "/api/v1/capacity/site-resource-pools/version")) == 1
        assert checked.count(("GET", "/api/v1/capacity/site-capacity-buckets/version")) == 1
        # Only the family whose identity moved is fetched again.
        assert checked.count(("GET", "/api/v1/capacity/site-resource-pools")) == 1
        assert ("GET", "/api/v1/capacity/site-capacity-buckets") not in checked
        assert len(wakes) == woken + 1

    async def test_admin_reserve_capacity_returns_502_when_the_mapped_site_is_unreachable(
        self, client,
    ):
        """The mapped site itself failing to respond is also distinct
        from a genuine "no capacity" refusal -- must surface as an
        upstream-communication failure, not a 409."""
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()

        def handle_reservation_failure(request):
            if (
                request.method == "POST"
                and request.url.path == "/api/v1/capacity/reservations"
            ):
                raise ConnectionError("site unreachable")
            return original_handle(request)

        original_handle = fake._handle
        fake._handle = handle_reservation_failure

        async with site_capacity(fake, project_pool_modes=True):
            with pytest.raises(StorefrontClientError) as exc_info:
                await c.admin_reserve_capacity(
                    required_attributes={
                        "resource_id": "pool-h200-1",
                        "gpu_count": 2,
                    },
                    listing_id="listing-2x",
                    escrow_uid="manual-escrow-unreachable",
                )

        assert "502" in str(exc_info.value)

    async def test_capacity_released_releases_and_reopens(
        self, client, service_client
    ):
        c, db = client
        await _seed_dynamic_listing_pool_rows(db)
        fake = _fake_pool_site()

        async with site_capacity(fake, project_pool_modes=True):
            reserved = await c.admin_reserve_capacity(
                required_attributes={"resource_id": "pool-h200-1", "gpu_count": 2},
                listing_id="listing-2x",
                escrow_uid="escrow-2x",
            )
            capacity_reservation_id = reserved.capacity_reservation_id
            assert sorted(reserved.closed_listing_ids) == ["listing-3x", "listing-4x"]

            response = await service_client.notify_capacity_released(
                capacity_reservation_id,
                site_id="default",
            )

        assert response["capacity_reservation_id"] == capacity_reservation_id
        assert response["state"] == "released"
        assert sorted(response["reopened_listing_ids"]) == ["listing-3x", "listing-4x"]
        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "open",
            4: "open",
        }
        assert fake.reservations[capacity_reservation_id]["state"] == "released"
        assert fake._available("pool-h200-1") == 4

    async def test_release_of_unknown_reservation_is_idempotent(
        self, service_client
    ):
        """The watchdog usually released first; a second capacity-released
        for the same (or an unknown) reservation must land cleanly."""
        async with site_capacity(
            FakeSite(deliverable_modes={"vm"}),
            project_pool_modes=True,
        ):
            response = await service_client.notify_capacity_released(
                "ledger-only-alloc",
                site_id="default",
                resource_id="compute-kvm1-001",
                released_at="2026-06-10T00:00:00Z",
            )
        assert response["capacity_reservation_id"] == "ledger-only-alloc"
        assert response["state"] == "released"


# ---------------------------------------------------------------------------
# Real orchestration: a cached projection reaches the real reconciler and
# produces real storefront DB/listing state, using the real
# close_stale_compute_listings_after_capacity_change /
# reopen_available_compute_listings_after_capacity_change functions rather
# than a mocked reconciliation boundary.
# ---------------------------------------------------------------------------

class TestRealOrchestrationCacheToReconciliation:
    async def test_cached_projection_closes_real_oversized_listings(self, client):
        from core_storefront.aggregation import fill_first
        from core_storefront.capacity import CapacityDelta
        from market_capacity_publication import CapacityRuntime, CapacitySite
        from market_site_client import SiteCapacityClient
        from market_storefront.services.capacity_client import _capacity_reconciler
        from tests.fake_site import (
            TEST_MARKETPLACE_SIGNER,
            TEST_SITE_AUTHORITIES,
        )

        _c, db = client
        await _seed_dynamic_listing_pool_rows(db)

        # The projection's own "available" field takes precedence over the
        # live snapshot: 2 of the pool's 4 GPUs are authoritatively available.
        held = await loaded_site_projection_state({"default": FakeProjectionSite(
            resource_pools=[{
                "pool_id": "pool-h200-1",
                "pool_metadata": {
                    "policy_tags": {"deliverable_modes": ["vm"], "region": "California, US"},
                },
                "resources": [{
                    "physical_resource_id": "pool-h200-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 2},
                    # The listings claim this region; admission matches it here.
                    "attributes": {"gpu_model": "H200", "region": "California, US"},
                    "enabled": True,
                }],
            }],
        )})
        fake = _fake_pool_site()
        site = CapacitySite(
            "default",
            "http://fake-site:8081",
            TEST_SITE_AUTHORITIES,
        )
        runtime = CapacityRuntime(
            sites=(site,),
            signer=TEST_MARKETPLACE_SIGNER,
            placement=fill_first,
            reconcile=_capacity_reconciler(lambda: db, site_projections=lambda: held),
            site_client_factory=lambda configured, signer: SiteCapacityClient(
                configured.url,
                signer=signer,
                expected_authorities=configured.expected_authorities,
                transport=fake.transport(),
            ),
        )

        with recorded_registries():
            # Aggregate subscription is the public capacity-publication hook:
            # it carries this repository into the real VM reconciler.
            await runtime.client().emit_site_delta(
                "default",
                CapacityDelta(kind="reserved", version=1),
            )

        statuses = {
            gpu_count: (await db.load_listing(listing_id=f"listing-{gpu_count}x"))[
                "status"
            ]
            for gpu_count in range(1, 5)
        }
        assert statuses == {
            1: "open",
            2: "open",
            3: "closed",
            4: "closed",
        }


# ---------------------------------------------------------------------------
# GET /api/v1/system/events
# ---------------------------------------------------------------------------

class TestStreamEvents:
    async def test_rejects_untrusted_principal(self, client_untrusted):
        with pytest.raises(StorefrontClientError) as exc_info:
            await client_untrusted.get_events()
        assert exc_info.value.status_code == 403

    async def test_returns_empty_list_on_fresh_db(self, client):
        c, _ = client
        result = await c.get_events()
        assert result.count == 0
        assert result.events == []

    async def test_returns_seeded_events(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, listing_id, data) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2025-01-01T00:00:00Z", "discovery", "order_published", "listing-1",
                 _json.dumps({"listing_id": "listing-1"})),
            )
            conn.commit()
        finally:
            conn.close()

        result = await c.get_events()
        assert result.count == 1
        assert result.events[0].stage == "discovery"
        assert result.events[0].event == "order_published"
        assert result.events[0].listing_id == "listing-1"

    async def test_since_id_cursor(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            for i in range(3):
                conn.execute(
                    "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                    (f"2025-01-0{i+1}T00:00:00Z", "discovery", f"event_{i}",
                     _json.dumps({"seq": i})),
                )
            conn.commit()
        finally:
            conn.close()

        all_events = await c.get_events()
        assert all_events.count == 3

        first_id = all_events.events[0].id
        tail = await c.get_events(since_id=first_id)
        assert tail.count == 2
        assert all(ev.id > first_id for ev in tail.events)

    async def test_stage_filter(self, client):
        c, db = client
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                ("2025-01-01T00:00:00Z", "discovery", "published", _json.dumps({})),
            )
            conn.execute(
                "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                ("2025-01-01T00:00:01Z", "negotiation", "started", _json.dumps({})),
            )
            conn.commit()
        finally:
            conn.close()

        disc_events = await c.get_events(stage="discovery")
        assert all(ev.stage == "discovery" for ev in disc_events.events)
        assert disc_events.count == 1

        neg_events = await c.get_events(stage="negotiation")
        assert neg_events.count == 1
        assert neg_events.events[0].stage == "negotiation"

    @staticmethod
    def _seed_events(db, count: int, *, stage: str = "discovery") -> None:
        import json as _json
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        try:
            conn.executemany(
                "INSERT INTO stage_events (ts, stage, event, data) VALUES (?, ?, ?, ?)",
                [
                    ("2025-01-01T00:00:00Z", stage, f"event_{i}", _json.dumps({"seq": i}))
                    for i in range(count)
                ],
            )
            conn.commit()
        finally:
            conn.close()

    async def test_reports_not_truncated_when_the_log_fits(self, client):
        c, db = client
        self._seed_events(db, 3)

        result = await c.get_events(limit=10)
        assert result.count == 3
        assert result.truncated is False

    async def test_reports_truncated_when_rows_remain_beyond_the_page(self, client):
        c, db = client
        self._seed_events(db, 5)

        result = await c.get_events(limit=2)
        assert result.count == 2
        assert result.truncated is True

    async def test_not_truncated_when_the_log_ends_on_the_page_boundary(self, client):
        """A full page that exhausted the log is not truncated.

        The case a caller cannot work out for itself, and the reason the flag
        is served rather than derived: `count == limit` holds here and in the
        test above, so anything inferring truncation from that comparison
        reports this exact-fit log as incomplete and sends a reader looking
        for a second page that does not exist.
        """
        c, db = client
        self._seed_events(db, 2)

        result = await c.get_events(limit=2)
        assert result.count == 2
        assert result.truncated is False

    async def test_truncation_is_reported_at_the_page_cap(self, client):
        """The cap is the boundary the e2e claims stage actually reads at.

        `STAGE_EVENT_PAGE_CAP` is both the route's accepted maximum and the
        store's internal clamp, so a page requested at the cap is the one case
        where over-fetching from outside the store would be clamped back to
        the cap and read as complete. Asserted at the cap, not just at a small
        limit, because that is where a plausible implementation goes quiet.
        """
        c, db = client
        self._seed_events(db, STAGE_EVENT_PAGE_CAP + 1)

        result = await c.get_events(limit=STAGE_EVENT_PAGE_CAP)
        assert result.count == STAGE_EVENT_PAGE_CAP
        assert result.truncated is True

        # And the tail beyond it is reachable and complete.
        tail = await c.get_events(
            since_id=result.events[-1].id, limit=STAGE_EVENT_PAGE_CAP
        )
        assert tail.count == 1
        assert tail.truncated is False



class TestReleaseReservations:
    """POST /api/v1/admin/portfolio/release-reservations, through the typed client.

    The route releases held reservations in each configured site's ledger and
    touches no storefront table, including an allocation ledger an older
    database still holds.
    """

    async def test_releases_every_held_site_reservation(self, client):
        c, _db = client

        async with site_capacity(_fake_pool_site()) as capacity:
            first = await _ledger_hold(capacity, gpu_count=1)
            second = await _ledger_hold(capacity, gpu_count=2)

            result = await c.admin_release_reservations()

        assert sorted(result.resource_ids) == sorted(
            [f"ledger:default:{first}", f"ledger:default:{second}"]
        )
        assert result.released_count == 2

    async def test_a_second_call_releases_nothing_new(self, client):
        c, _db = client

        async with site_capacity(_fake_pool_site()) as capacity:
            await _ledger_hold(capacity)
            await c.admin_release_reservations()

            again = await c.admin_release_reservations()

        assert again.released_count == 0
        assert again.resource_ids == []

    async def test_leaves_an_existing_allocation_ledger_untouched(self, client):
        c, db = client
        with sqlite3.connect(db.db_path) as conn:
            conn.execute(
                "CREATE TABLE compute_allocations ("
                " allocation_id TEXT PRIMARY KEY, resource_id TEXT NOT NULL,"
                " gpu_count INTEGER NOT NULL, state TEXT NOT NULL,"
                " released_at TEXT)"
            )
            conn.execute(
                "INSERT INTO compute_allocations VALUES ('alloc-1', 'held', 1, 'leased', NULL)"
            )
        before = self._allocations(db)

        result = await c.admin_release_reservations()

        assert result.released_count == 0
        assert self._allocations(db) == before == [("alloc-1", "held", 1, "leased", None)]

    @staticmethod
    def _allocations(db: SQLiteClient) -> list[tuple]:
        with sqlite3.connect(db.db_path) as conn:
            return conn.execute("SELECT * FROM compute_allocations").fetchall()


# ---------------------------------------------------------------------------
# GET /api/v1/system/events: what the signature does not bind is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["limit=100&since_id=0&stream=false&after=1", "stream=true", "stage=a&stage=b"],
)
async def test_an_event_read_the_signature_does_not_bind_is_refused(admin_app, query):
    # Rejection path: the canonical client cannot send these, so the request is
    # raw, and only its status is asserted. The refusal precedes authentication,
    # since the signed resource cannot be built.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app), base_url="http://test"
    ) as raw:
        response = await raw.get(f"/api/v1/system/events?{query}")
    assert response.status_code == 400
