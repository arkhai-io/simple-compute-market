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

from market_storefront.services.system_service import (
    EvalResult,
    PolicyInfo,
    PolicyStatusResult,
    SeedResult,
    SystemService,
)
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
DEMAND = {
    "token": {
        "symbol": "MOCK",
        "contract_address": "0x0000000000000000000000000000000000000001",
        "decimals": 18,
    },
    "amount": 10_000,
}


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

        assert isinstance(result, PolicyStatusResult)
        assert result.callable_count == 0
        assert result.callable_registry == []
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
# evaluate_order_create — pre-flight checks
# ---------------------------------------------------------------------------

class TestEvaluateOrderCreatePreFlight:
    async def test_no_policies_seeded_returns_no_action(self, db):
        svc = _make_service(db)
        result = await svc.evaluate_order_create(offer_raw=OFFER, demand_raw=DEMAND)

        assert result.action == "no_action"
        assert result.resolvable is False
        assert result.policy_used is None
        assert "seed" in (result.reason or "").lower()

    async def test_unresolvable_components_returns_no_action_with_missing_names(self, db):
        """Policy seeded but callable not in registry → names the missing callable."""
        svc = _make_service(db, {})  # empty registry — component unresolvable

        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.evaluate_order_create(offer_raw=OFFER, demand_raw=DEMAND)

        assert result.action == "no_action"
        assert result.resolvable is False
        assert "oc.action.make_offer_from_order_create" in str(result.reason)

    async def test_invalid_offer_raises_value_error(self, db):
        svc = _make_service(db)
        with pytest.raises((ValueError, Exception)):
            await svc.evaluate_order_create(
                offer_raw={"not_a_valid_resource": True},
                demand_raw=DEMAND,
            )


# ---------------------------------------------------------------------------
# evaluate_order_create — happy path (policy engine wired and callable)
# ---------------------------------------------------------------------------

class TestEvaluateOrderCreateHappyPath:
    async def test_returns_make_offer_when_callable_fires(self, db):
        """End-to-end: seeded policy + registered callable → action=make_offer."""
        from market_storefront.models.domain_models import ActionType, ListingCreatedEvent
        from service.schemas import DomainAction

        # Register a fake callable that always returns MAKE_OFFER
        def _fake_make_offer(context):
            if not isinstance(context.event, ListingCreatedEvent):
                return None
            return DomainAction(
                action_type=ActionType.MAKE_OFFER,
                parameters={"offer": {}, "demand": {}, "duration_hours": 1},
            )

        registry = {"oc.action.make_offer_from_order_create": _fake_make_offer}
        svc = _make_service(db, registry)

        # Seed policies so the pre-flight check passes
        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.evaluate_order_create(offer_raw=OFFER, demand_raw=DEMAND)

        assert result.action == "make_offer"
        assert result.resolvable is True
        assert result.reason is None
        assert result.policy_used is not None

    async def test_evaluate_uses_wired_policy_store(self, db):
        """Verifies evaluate_order_create creates a wired PolicyStore, not a bare one.

        A bare PolicyStore (no register_callables) always returns None even when
        the callable exists in the registry.  This test fails if the wiring is absent.
        """
        from market_storefront.models.domain_models import ActionType, ListingCreatedEvent
        from service.schemas import DomainAction

        fired = []

        def _callable(context):
            fired.append(True)
            if isinstance(context.event, ListingCreatedEvent):
                return DomainAction(action_type=ActionType.MAKE_OFFER, parameters={})
            return None

        registry = {"oc.action.make_offer_from_order_create": _callable}
        svc = _make_service(db, registry)

        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.evaluate_order_create(offer_raw=OFFER, demand_raw=DEMAND)

        assert fired, "Callable was never invoked — PolicyStore was not wired with callables"
        assert result.action == "make_offer"

    async def test_none_from_policy_engine_returns_no_action_with_count(self, db):
        """A callable that returns None → no_action with registry count in reason."""
        registry = {"oc.action.make_offer_from_order_create": lambda ctx: None}
        svc = _make_service(db, registry)

        from market_policy.store import PolicyStore
        from market_storefront.policy.seeding import ComputePolicySeeder
        ps = PolicyStore(db)
        seeder = ComputePolicySeeder(policy_store=ps, sqlite_client=db, agent_id="test-agent")
        await seeder.ensure_default_policies()

        result = await svc.evaluate_order_create(offer_raw=OFFER, demand_raw=DEMAND)

        assert result.action == "no_action"
        assert result.resolvable is True  # registry has 1 entry
        assert "CALLABLE_REGISTRY has 1" in (result.reason or "")


# ---------------------------------------------------------------------------
# seed_policies
# ---------------------------------------------------------------------------

class TestSeedPolicies:
    async def test_seed_populates_seeded_policies_in_db(self, db):
        """After seed_policies(), the DB must contain the default policy rows."""
        svc = _make_service(db, {})

        # Patch the package walk to be a no-op (we don't want to touch real modules)
        with patch.object(SystemService, "POLICY_PACKAGE", "market_storefront.policy"):
            result = await svc.seed_policies()

        assert isinstance(result, SeedResult)
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
