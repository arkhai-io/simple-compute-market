"""Unit tests for SystemService.

All tests inject a fake callable_registry so the global CALLABLE_REGISTRY
singleton is never touched.  SQLite is a real in-process temp database
(no mocking needed — it's fast and avoids mock complexity for DB reads).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_storefront.services.system_service import SystemService
from market_storefront.utils.sqlite_client import SQLiteClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "system_service_test.db"))


def _make_service(db: SQLiteClient, registry: dict | None = None) -> SystemService:
    return SystemService(
        sqlite_client=db,
        agent_id="test-agent",
        callable_registry=registry if registry is not None else {},
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
# wait_for_registry_agent — transient retry behaviour
# ---------------------------------------------------------------------------

class TestWaitForRegistryAgent:
    """Verify that wait_for_registry_agent retries past transient states
    and exits immediately on definitive states.

    Regression guard: 'timeout' and 'unreachable' were previously treated
    as definitive, causing the e2e stage 03c to fail with registry_auth='timeout'
    after a single 2-second HTTP probe that hit a slow registry at startup.
    """

    def _make_svc(self, db) -> SystemService:
        return SystemService(
            sqlite_client=db,
            agent_id="test-agent",
            callable_registry={},
        )

    @pytest.mark.asyncio
    async def test_returns_ok_immediately_when_check_succeeds(self, db):
        svc = self._make_svc(db)
        with patch.object(svc, "registry_auth_check", new=AsyncMock(return_value="ok")):
            result = await svc.wait_for_registry_agent(timeout=5.0)
        assert result["ready"] is True
        assert result["registry_auth"] == "ok"

    @pytest.mark.asyncio
    async def test_retries_past_agent_not_found(self, db):
        """agent_not_found is the normal indexing-lag state — must be retried."""
        svc = self._make_svc(db)
        call_count = 0

        async def _probe():
            nonlocal call_count
            call_count += 1
            return "ok" if call_count >= 2 else "agent_not_found"

        with patch.object(svc, "registry_auth_check", new=_probe):
            result = await svc.wait_for_registry_agent(timeout=5.0)
        assert result["ready"] is True
        assert result["registry_auth"] == "ok"
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_retries_past_timeout(self, db):
        """timeout is a transient network condition — must be retried, not treated as definitive."""
        svc = self._make_svc(db)
        call_count = 0

        async def _probe():
            nonlocal call_count
            call_count += 1
            return "ok" if call_count >= 2 else "timeout"

        with patch.object(svc, "registry_auth_check", new=_probe):
            result = await svc.wait_for_registry_agent(timeout=5.0)
        assert result["ready"] is True
        assert result["registry_auth"] == "ok"
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_retries_past_unreachable(self, db):
        """unreachable is a transient connectivity state — must be retried."""
        svc = self._make_svc(db)
        call_count = 0

        async def _probe():
            nonlocal call_count
            call_count += 1
            return "ok" if call_count >= 2 else "unreachable"

        with patch.object(svc, "registry_auth_check", new=_probe):
            result = await svc.wait_for_registry_agent(timeout=5.0)
        assert result["ready"] is True
        assert result["registry_auth"] == "ok"
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_exits_immediately_on_owner_mismatch(self, db):
        """owner_mismatch is definitive — exit without retrying."""
        svc = self._make_svc(db)
        call_count = 0

        async def _probe():
            nonlocal call_count
            call_count += 1
            return "owner_mismatch"

        with patch.object(svc, "registry_auth_check", new=_probe):
            result = await svc.wait_for_registry_agent(timeout=5.0)
        assert result["ready"] is True
        assert result["registry_auth"] == "owner_mismatch"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_returns_ready_false_on_timeout(self, db):
        """All pending states until timeout → ready=False with last seen value."""
        svc = self._make_svc(db)
        with patch.object(svc, "registry_auth_check", new=AsyncMock(return_value="agent_not_found")):
            result = await svc.wait_for_registry_agent(timeout=0.1)
        assert result["ready"] is False
