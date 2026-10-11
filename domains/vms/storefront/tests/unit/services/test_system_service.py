"""Unit tests for SystemService.

SQLite is a real in-process temp database (no mocking needed — it's fast
and avoids mock complexity for DB reads).
"""

from __future__ import annotations

import sqlite3

import pytest
from compute_provisioning_contracts import COMPUTE_PROVISIONING_CONTRACT_VERSION
from market_identity import Ed25519Signer

from market_storefront.services.system_service import SystemService
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient

MARKETPLACE_SIGNER = Ed25519Signer(b"\x41" * 32)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "system_service_test.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


def _make_service(
    db: SQLiteClient,
    *,
    projection_status_provider=None,
    listing_cardinality_mode_explanation_provider=None,
) -> SystemService:
    return SystemService(
        sqlite_client=db,
        marketplace_signer=MARKETPLACE_SIGNER,
        agent_id="test-agent",
        projection_status_provider=projection_status_provider,
        listing_cardinality_mode_explanation_provider=listing_cardinality_mode_explanation_provider,
    )


# ---------------------------------------------------------------------------
# get_health: no local inventory
# ---------------------------------------------------------------------------

class TestGetHealthReadsNoLocalInventory:
    async def test_status_needs_no_local_resource_table(self, db):
        """Status reports no resource count and reads no local inventory, so
        a database without a ``resources`` table is still healthy."""
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("DROP TABLE IF EXISTS resources")

        result = await _make_service(db).get_health(include_registry=True)

        assert "resource_count" not in result
        assert result["checks"]["database"] == "ok"


# ---------------------------------------------------------------------------
# get_health: per-site projection load-state reporting
# ---------------------------------------------------------------------------

class TestGetHealthSiteProjections:
    async def test_reports_per_site_per_family_state(self, db):
        """get_health copies the injected provider's summary through verbatim."""
        summary = {
            "site-a": {
                "resource_pool": {
                    "state": "loaded", "revision": 3, "digest": "abc",
                    "last_error": None, "fetched_at": "2026-08-03T12:00:00+00:00",
                },
                "capacity_bucket": {
                    "state": "stale", "revision": 2, "digest": "def",
                    "last_error": "boom", "fetched_at": "2026-08-03T11:55:00+00:00",
                },
            },
        }
        svc = _make_service(db, projection_status_provider=lambda: summary)
        result = await svc.get_health(include_registry=True)

        assert result["site_projections"] == summary

    async def test_omitted_from_fast_health_probe(self, db):
        """The liveness probe (include_registry=False) does not compute this."""
        svc = _make_service(db, projection_status_provider=lambda: {"site-a": {}})
        result = await svc.get_health(include_registry=False)
        assert "site_projections" not in result

    async def test_default_provider_is_the_real_projection_status_summary(self, db):
        """With no provider injected, get_health falls back to the real
        production source rather than silently returning nothing."""
        svc = _make_service(db)  # no projection_status_provider -- exercises the default
        result = await svc.get_health(include_registry=True)
        # No sites are configured/loaded in this process, so the real
        # summary is an empty dict, not None -- proving the default path
        # actually ran rather than swallowing an exception.
        assert result["site_projections"] == {}

    async def test_one_site_unavailable_is_reported_outside_the_health_gate(self, db):
        """An unavailable/invalid site must be reported, not gated on.

        Asserted directly against `checks` (the dict `all_ok` actually
        gates on) rather than the top-level `status`, so this test does
        not depend on unrelated checks (registry/alkahest/negotiation
        strategy) also being healthy in whatever environment runs it.
        """
        summary = {
            "site-a": {
                "resource_pool": {
                    "state": "unavailable", "revision": None, "digest": None,
                    "last_error": "connection refused", "fetched_at": None,
                },
                "capacity_bucket": {
                    "state": "not_loaded", "revision": None, "digest": None,
                    "last_error": None, "fetched_at": None,
                },
            },
        }
        svc = _make_service(db, projection_status_provider=lambda: summary)
        result = await svc.get_health(include_registry=True)

        assert result["site_projections"]["site-a"]["resource_pool"]["state"] == "unavailable"
        assert "site_projections" not in result["checks"]

    async def test_reporting_failure_does_not_add_a_checks_entry(self, db):
        """A raise while computing the summary yields None, not a crashed
        health check or a new gated `checks` entry."""
        def _boom():
            raise RuntimeError("no event loop for pollers in this process")

        svc = _make_service(db, projection_status_provider=_boom)
        result = await svc.get_health(include_registry=True)

        assert result["site_projections"] is None
        assert "site_projections" not in result["checks"]


class TestGetHealthProvisioningContractPin:
    """The pin has to survive the response model, not just the service dict.

    The status route returns `HealthResponse(**body)`, so a key the service
    puts in its dict and the model does not declare never reaches a caller.
    That is how this pin first shipped invisible -- on this service and,
    separately, on the provisioning service, both times passing a check that
    only looked at the service method.
    """

    async def test_reports_the_major_this_storefront_speaks(self, db):
        svc = _make_service(db)
        result = await svc.get_health(include_registry=True)

        assert (
            result["provisioning_contract_version"]
            == COMPUTE_PROVISIONING_CONTRACT_VERSION
        )

    async def test_survives_the_response_model(self, db):
        """Constructing the model is the assertion the route performs."""
        from core_storefront.models.system_models import HealthResponse

        svc = _make_service(db)
        body = await svc.get_health(include_registry=True)

        model = HealthResponse(**body)

        assert (
            model.provisioning_contract_version
            == COMPUTE_PROVISIONING_CONTRACT_VERSION
        ), (
            "the status route returns HealthResponse(**body); a pin the "
            "service reports but the model drops is invisible to every caller"
        )

    async def test_omitted_from_fast_health_probe(self, db):
        """The liveness probe does not owe a cutover diagnostic."""
        svc = _make_service(db)
        result = await svc.get_health()

        assert "provisioning_contract_version" not in result


class TestGetHealthListingModeExplanations:
    async def test_reports_per_site_per_pool_explanation(self, db):
        """get_health copies the injected provider's explanations through
        verbatim, mirroring TestGetHealthSiteProjections' own pattern."""
        explanations = {
            "site-a": {"gpu-pool": "unrecognized listing_cardinality_mode 'bogus', using 'fungible'"},
        }
        svc = _make_service(db, listing_cardinality_mode_explanation_provider=lambda: explanations)
        result = await svc.get_health(include_registry=True)

        assert result["listing_cardinality_mode_explanations"] == explanations

    async def test_omitted_from_fast_health_probe(self, db):
        svc = _make_service(db, listing_cardinality_mode_explanation_provider=lambda: {"site-a": {}})
        result = await svc.get_health(include_registry=False)
        assert "listing_cardinality_mode_explanations" not in result

    async def test_default_provider_is_the_real_listing_cardinality_mode_explanations(self, db):
        """With no provider injected, get_health falls back to the real
        production source rather than silently returning nothing."""
        svc = _make_service(db)  # no listing_cardinality_mode_explanation_provider injected
        result = await svc.get_health(include_registry=True)
        # No sites are configured/loaded in this process, so the real
        # function returns an empty dict, not None -- proving the default
        # path actually ran rather than swallowing an exception.
        assert result["listing_cardinality_mode_explanations"] == {}

    async def test_reporting_failure_does_not_add_a_checks_entry(self, db):
        def _boom():
            raise RuntimeError("no event loop for pollers in this process")

        svc = _make_service(db, listing_cardinality_mode_explanation_provider=_boom)
        result = await svc.get_health(include_registry=True)

        assert result["listing_cardinality_mode_explanations"] is None
        assert "listing_cardinality_mode_explanations" not in result["checks"]

    async def test_does_not_change_all_ok_status(self, db):
        """A populated explanations dict (implying some pool fell back to
        a structural default) is informational only -- it must not gate
        overall health status."""
        explanations = {"site-a": {"gpu-pool": "unrecognized listing_cardinality_mode 'bogus'"}}
        svc = _make_service(db, listing_cardinality_mode_explanation_provider=lambda: explanations)
        result = await svc.get_health(include_registry=True)
        assert "listing_cardinality_mode_explanations" not in result["checks"]
