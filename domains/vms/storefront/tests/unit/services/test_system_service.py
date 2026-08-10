"""Unit tests for SystemService.

SQLite is a real in-process temp database (no mocking needed — it's fast
and avoids mock complexity for DB reads).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "system_service_test.db"))


def _make_service(
    db: SQLiteClient,
    registry: dict | None = None,
    *,
    projection_status_provider=None,
    listing_mode_explanation_provider=None,
) -> SystemService:
    """``registry`` arg kept for compat with older test invocations; ignored."""
    return SystemService(
        sqlite_client=db,
        agent_id="test-agent",
        projection_status_provider=projection_status_provider,
        listing_mode_explanation_provider=listing_mode_explanation_provider,
    )


OFFER = {"gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US"}


# ---------------------------------------------------------------------------
# seed_resources_if_empty
# ---------------------------------------------------------------------------

class TestSeedResourcesIfEmpty:
    async def test_skips_when_resources_already_present(self, db, tmp_path):
        """When the resources table is non-empty, seeding is skipped.

        The CSV path exists (a minimal valid file) but must never be read
        because the early-exit guard fires first.
        """
        # Pre-populate the resources table with one row so the guard fires.
        await db.upsert_resource(
            resource_id="existing-001",
            resource_type="compute.gpu",
            state="available",
        )

        # Create a minimal CSV that would be valid if imported.
        csv_file = tmp_path / "dummy.csv"
        csv_file.write_text(
            "resource_id,resource_type,state\n"
            "new-001,compute.gpu,available\n"
        )

        svc = _make_service(db)
        result = await svc.seed_resources_if_empty(csv_path=str(csv_file))

        assert result["seeded"] is False
        # imported_count reflects what was already there, not a new import.
        assert result["imported_count"] == 1
        # The new row from the CSV must not have been inserted.
        resources = await db.list_resources()
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "existing-001"

    async def test_seeds_when_table_is_empty(self, tmp_path):
        """When the resources table is empty, the CSV is imported."""
        from market_storefront.utils.sqlite_client import SQLiteClient

        db = SQLiteClient(db_path=str(tmp_path / "seed_test.db"))

        # Minimal valid kvm1-style CSV row.
        csv_file = tmp_path / "resources.csv"
        csv_file.write_text(
            "resource_id,resource_type,resource_subtype,unit,value,state,"
            "min_price,token,max_duration_seconds,"
            "attribute.gpu_model,attribute.sla,attribute.region,"
            "attribute.vm_host,attribute.vcpu_count,attribute.ram_gb,"
            "attribute.disk_gb,attribute.virtualization_type\n"
            "compute-test-001,compute.gpu,rtx5080,count,1,available,"
            "150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,"
            'RTX 5080,90.0,"California, US",'
            "kvm1,16,256,4000,bare_metal\n"
        )

        svc = _make_service(db)
        result = await svc.seed_resources_if_empty(csv_path=str(csv_file))

        assert result["seeded"] is True
        assert result["imported_count"] == 1

        resources = await db.list_resources(resource_type="compute.gpu", state="available")
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "compute-test-001"

    async def test_seeds_from_inline_content(self, db):
        """When csv_inline is provided, it is imported without touching the filesystem."""
        csv_content = (
            "resource_id,resource_type,resource_subtype,unit,value,state,"
            "min_price,token,max_duration_seconds,"
            "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
            'compute-inline-001,compute.gpu,rtx5080,count,1,available,'
            '150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
            'RTX 5080,90.0,"California, US",kvm1\n'
        )
        svc = _make_service(db)
        result = await svc.seed_resources_if_empty(csv_inline=csv_content)

        assert result["seeded"] is True
        assert result["imported_count"] == 1
        resources = await db.list_resources()
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "compute-inline-001"

    async def test_inline_takes_priority_over_path(self, db, tmp_path):
        """csv_inline is used when both inline and path are provided."""
        csv_file = tmp_path / "resources.csv"
        csv_file.write_text(
            "resource_id,resource_type,state\n"
            "compute-path-001,compute.gpu,available\n"
        )
        csv_content = (
            "resource_id,resource_type,resource_subtype,unit,value,state,"
            "min_price,token,max_duration_seconds,"
            "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
            'compute-inline-001,compute.gpu,rtx5080,count,1,available,'
            '150,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
            'RTX 5080,90.0,"California, US",kvm1\n'
        )
        svc = _make_service(db)
        result = await svc.seed_resources_if_empty(
            csv_inline=csv_content, csv_path=str(csv_file)
        )
        assert result["seeded"] is True
        resources = await db.list_resources()
        # Only the inline row should be present.
        assert len(resources) == 1
        assert resources[0]["resource_id"] == "compute-inline-001"

    async def test_empty_csv_path_returns_not_seeded(self, db):
        """Neither source configured skips seeding and returns seeded=False."""
        svc = _make_service(db)
        result = await svc.seed_resources_if_empty()
        assert result["seeded"] is False
        assert result["imported_count"] == 0

    async def test_missing_csv_raises(self, db):
        """A configured but missing CSV path raises FileNotFoundError."""
        svc = _make_service(db)
        with pytest.raises(FileNotFoundError):
            await svc.seed_resources_if_empty(csv_path="/nonexistent/path/resources.csv")


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


class TestGetHealthListingModeExplanations:
    async def test_reports_per_site_per_pool_explanation(self, db):
        """get_health copies the injected provider's explanations through
        verbatim, mirroring TestGetHealthSiteProjections' own pattern."""
        explanations = {
            "site-a": {"gpu-pool": "unrecognized listing_mode 'bogus', using 'fungible'"},
        }
        svc = _make_service(db, listing_mode_explanation_provider=lambda: explanations)
        result = await svc.get_health(include_registry=True)

        assert result["listing_mode_explanations"] == explanations

    async def test_omitted_from_fast_health_probe(self, db):
        svc = _make_service(db, listing_mode_explanation_provider=lambda: {"site-a": {}})
        result = await svc.get_health(include_registry=False)
        assert "listing_mode_explanations" not in result

    async def test_default_provider_is_the_real_listing_mode_explanations(self, db):
        """With no provider injected, get_health falls back to the real
        production source rather than silently returning nothing."""
        svc = _make_service(db)  # no listing_mode_explanation_provider injected
        result = await svc.get_health(include_registry=True)
        # No sites are configured/loaded in this process, so the real
        # function returns an empty dict, not None -- proving the default
        # path actually ran rather than swallowing an exception.
        assert result["listing_mode_explanations"] == {}

    async def test_reporting_failure_does_not_add_a_checks_entry(self, db):
        def _boom():
            raise RuntimeError("no event loop for pollers in this process")

        svc = _make_service(db, listing_mode_explanation_provider=_boom)
        result = await svc.get_health(include_registry=True)

        assert result["listing_mode_explanations"] is None
        assert "listing_mode_explanations" not in result["checks"]

    async def test_does_not_change_all_ok_status(self, db):
        """A populated explanations dict (implying some pool fell back to
        a structural default) is informational only -- it must not gate
        overall health status."""
        explanations = {"site-a": {"gpu-pool": "unrecognized listing_mode 'bogus'"}}
        svc = _make_service(db, listing_mode_explanation_provider=lambda: explanations)
        result = await svc.get_health(include_registry=True)
        assert "listing_mode_explanations" not in result["checks"]
