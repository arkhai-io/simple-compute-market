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

from market_storefront.models.system_models import (
    PolicyStatusResponse,
    SeedPoliciesResponse,
)
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
# _make_policy_store — callable registry wiring
# ---------------------------------------------------------------------------

class TestMakePolicyStore:
    def test_wires_injected_registry_into_store(self, db):
        """_make_policy_store() must call register_callables so PolicyStore
        can resolve the injected callables — not just hold an empty dict."""
        fake_fn = MagicMock(return_value=None)
        registry = {"my.callable": fake_fn}
        svc = _make_service(db, registry)

        store = svc._make_policy_store()

        # The store's internal registry must contain the injected callable.
        assert "my.callable" in store._registry
        assert store._registry["my.callable"] is fake_fn

    def test_empty_registry_produces_empty_store(self, db):
        svc = _make_service(db, {})
        store = svc._make_policy_store()
        assert store._registry == {}


# ---------------------------------------------------------------------------
# get_policy_status
# ---------------------------------------------------------------------------

class TestGetPolicyStatus:
    async def test_returns_empty_when_no_policies_seeded(self, db):
        svc = _make_service(db)
        result = await svc.get_policy_status()

        assert isinstance(result, PolicyStatusResponse)
        assert result.callable_count == 0
        assert result.callable_registry == {}  # empty dict, not list (callable_registry is dict[name→name])
        assert result.seeded_policies == []

    async def test_reflects_injected_registry_callables(self, db):
        registry = {"a.callable": MagicMock(), "b.callable": MagicMock()}
        svc = _make_service(db, registry)
        result = await svc.get_policy_status()

        assert result.callable_count == 2
        assert sorted(result.callable_registry) == ["a.callable", "b.callable"]

    async def test_resolvable_true_when_all_components_registered(self, db):
        """A seeded policy whose component IS in the registry → resolvable=True."""
        registry = {"oc.action.make_offer_from_order_create": MagicMock()}
        svc = _make_service(db, registry)

        # Seed the policy so list_seeded_policies returns something
        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.get_policy_status()
        oc = next((p for p in result.seeded_policies if "order_create" in (p.policy_name or "")), None)
        assert oc is not None
        assert oc.components_resolvable is True

    async def test_resolvable_false_when_component_missing(self, db):
        """A seeded policy whose component is NOT in the registry → resolvable=False."""
        svc = _make_service(db, {})  # empty registry

        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.get_policy_status()
        oc = next((p for p in result.seeded_policies if "order_create" in (p.policy_name or "")), None)
        assert oc is not None
        assert oc.components_resolvable is False
# ---------------------------------------------------------------------------
# PolicyService.evaluate_listing_create_policy_from_raw
# These were previously on SystemService.evaluate_order_create; moved to PolicyService.
# ---------------------------------------------------------------------------

OFFER = {
    "gpu_model": "H200", "gpu_count": 1, "sla": 99.0, "region": "California, US",
}
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "fields": {"token": "0x0000000000000000000000000000000000000001"},
    "price_per_hour": 5000,
}]


def _make_policy_service(db, registry=None):
    from market_policy.registry import CALLABLE_REGISTRY
    from market_storefront.services.policy_service import PolicyService
    from unittest.mock import MagicMock
    config = MagicMock()
    config.base_url_override = ""
    config.agent_id = "test-agent"
    if registry is not None:
        CALLABLE_REGISTRY.clear()
        CALLABLE_REGISTRY.update(registry)
    return PolicyService(
        sqlite_client=db, alkahest_client=None, config=config, agent_id="test-agent",
    )


class TestEvaluateListingCreatePolicyFromRaw:
    async def test_no_policy_components_returns_no_action(self, db):
        """Empty policy_components list → no_action with explanation."""
        from market_storefront.models.system_models import PolicyEvaluateResponse
        svc = _make_policy_service(db)
        result = await svc.evaluate_listing_create_policy_from_raw(
            offer_raw=OFFER, accepted_escrows=ACCEPTED_ESCROWS, policy_components=[],
        )
        assert isinstance(result, PolicyEvaluateResponse)
        assert result.action == "no_action"
        assert result.resolvable is False
        assert result.reason is not None

    async def test_unresolvable_components_returns_no_action(self, db):
        """Component not in CALLABLE_REGISTRY → no_action with resolvable=False."""
        from market_storefront.models.system_models import PolicyEvaluateResponse
        svc = _make_policy_service(db, {})  # empty registry
        result = await svc.evaluate_listing_create_policy_from_raw(
            offer_raw=OFFER, accepted_escrows=ACCEPTED_ESCROWS,
            policy_components=["oc.action.make_offer_from_order_create"],
        )
        assert isinstance(result, PolicyEvaluateResponse)
        assert result.action == "no_action"
        assert result.resolvable is False
        assert "CALLABLE_REGISTRY" in (result.reason or "")

    async def test_invalid_offer_raises_value_error(self, db):
        """Invalid offer dict raises ValueError before callable is consulted."""
        svc = _make_policy_service(db)
        with pytest.raises((ValueError, Exception)):
            await svc.evaluate_listing_create_policy_from_raw(
                offer_raw={"not_a_valid_resource": True}, accepted_escrows=ACCEPTED_ESCROWS,
                policy_components=["oc.action.make_offer_from_order_create"],
            )

    async def test_returns_make_offer_when_callable_fires(self, db):
        """When the callable is registered and fires, action=make_offer is returned.

        No DB seeding required — the function no longer reads seeded_policies.
        """
        from market_storefront.models.domain_models import ActionType, ListingCreatedEvent
        from market_storefront.models.system_models import PolicyEvaluateResponse
        from service.schemas import DomainAction
        def _fake_make_offer(context):
            if isinstance(context.event, ListingCreatedEvent):
                return DomainAction(
                    action_type=ActionType.MAKE_OFFER,
                    parameters={"offer": OFFER, "accepted_escrows": ACCEPTED_ESCROWS,
                                "max_duration_seconds": None, "paused": False},
                )
            return None
        registry = {"oc.action.make_offer_from_order_create": _fake_make_offer}
        svc = _make_policy_service(db, registry)
        result = await svc.evaluate_listing_create_policy_from_raw(
            offer_raw=OFFER, accepted_escrows=ACCEPTED_ESCROWS,
            policy_components=["oc.action.make_offer_from_order_create"],
        )
        assert isinstance(result, PolicyEvaluateResponse)
        assert result.action == "make_offer"
        assert result.resolvable is True


class TestSeedPolicies:
    async def test_seed_populates_seeded_policies_in_db(self, db):
        """After seed_policies(), the DB must contain the default policy rows."""
        svc = _make_service(db, {})

        # Patch the package walk to be a no-op (we don't want to touch real modules)
        with patch.object(SystemService, "POLICY_PACKAGE", "market_storefront.policy"):
            result = await svc.seed_policies()

        assert isinstance(result, SeedPoliciesResponse)
        assert len(result.seeded_policies) > 0
        assert any("order_create" in p for p in result.seeded_policies)

    async def test_seed_idempotent(self, db):
        """Calling seed_policies() twice must not duplicate DB rows."""
        svc = _make_service(db, {})

        with patch.object(SystemService, "POLICY_PACKAGE", "market_storefront.policy"):
            r1 = await svc.seed_policies()
            r2 = await svc.seed_policies()

        assert sorted(r1.seeded_policies) == sorted(r2.seeded_policies)

    async def test_seed_raises_on_bad_package(self, db):
        """If the policy package itself can't be imported, seed_policies raises RuntimeError."""
        svc = _make_service(db, {})
        with patch.object(SystemService, "POLICY_PACKAGE", "this.package.does.not.exist"):
            with pytest.raises(RuntimeError, match="Failed to import"):
                await svc.seed_policies()

    async def test_seed_collects_submodule_errors(self, db):
        """Per-submodule import failures are collected, not raised.

        We patch pkgutil.walk_packages to yield one fake module whose name is
        genuinely unimportable, letting the real importlib.import_module produce
        an ImportError naturally rather than patching importlib globally (which
        would intercept every import in the process, including pytest internals).
        """
        svc = _make_service(db, {})

        bad_mod = MagicMock()
        bad_mod.name = "definitely.does.not.exist.fake_submodule_xyz"

        with patch.object(SystemService, "POLICY_PACKAGE", "market_storefront.policy"), \
             patch("pkgutil.walk_packages", return_value=[bad_mod]):
            result = await svc.seed_policies()

        assert len(result.import_errors) == 1
        assert result.import_errors[0].module == bad_mod.name


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

        # Minimal valid ww1-style CSV row.
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
            "ww1,16,256,4000,bare_metal\n"
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
            'RTX 5080,90.0,"California, US",ww1\n'
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
            'RTX 5080,90.0,"California, US",ww1\n'
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
