"""SystemService — business logic for policy seeding, status, and dry-run evaluation.

Extracted from SystemController so that the logic is independently testable
without an HTTP request/response cycle.

Three responsibilities:
  seed_policies()          — discover @policy_callable decorators + seed DB rows
  get_policy_status()      — read callable registry + seeded policies with resolvability
  evaluate_order_create()  — dry-run a synthetic order_create event through the policy engine

None of these methods write to the registry or produce side-effects beyond SQLite
(seed_policies writes policy rows; evaluate_order_create is fully read-only).
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from market_policy.registry import CALLABLE_REGISTRY
from market_policy.store import PolicyStore
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.schema.pydantic_models import (
    EventType,
    ListingCreatedEvent,
)
from market_storefront.utils.action_executor import parse_resource_from_dict
from market_storefront.utils.config import CONFIG
from service.schemas import DecisionContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses — typed return values instead of raw dicts
# ---------------------------------------------------------------------------

@dataclass
class ModuleImportError:
    module: str
    error: str


@dataclass
class SeedResult:
    callable_registry_count: int
    callables: list[str]
    seeded_policies: list[str]
    import_errors: list[ModuleImportError]


@dataclass
class PolicyInfo:
    policy_name: str
    trigger_type: str | None
    callable_ref: str | None
    components: list[str]
    components_resolvable: bool


@dataclass
class PolicyStatusResult:
    callable_count: int
    callable_registry: list[str]
    seeded_policies: list[PolicyInfo]


@dataclass
class EvalResult:
    action: str                   # "make_offer", "no_action", etc.
    policy_used: str | None
    components: list[str] = field(default_factory=list)
    resolvable: bool = True
    reason: str | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SystemService:
    """Business logic for system-level policy operations.

    Parameters
    ----------
    sqlite_client:
        The storefront SQLiteClient instance — used for policy row reads/writes.
    agent_id:
        Agent identifier used as the key for policy DB rows.
    callable_registry:
        Override for the module-level CALLABLE_REGISTRY.  Inject a plain dict
        in unit tests to avoid touching the real global singleton.
    """

    # Package walked during seed.  Named here so tests can patch it.
    POLICY_PACKAGE = "domain.compute.agent.app.policy"

    def __init__(
        self,
        *,
        sqlite_client,
        agent_id: str | None = None,
        callable_registry: dict | None = None,
    ) -> None:
        self._db = sqlite_client
        self._agent_id = agent_id or CONFIG.agent_id or "agent"
        # Injected registry lets tests work without touching the global singleton.
        self._registry: dict = callable_registry if callable_registry is not None else CALLABLE_REGISTRY

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_policy_store(self) -> PolicyStore:
        """Create a PolicyStore wired with the current callable registry.

        PolicyStore.__init__ starts with an empty self._registry.  Callers
        that use evaluate_policy must first call register_callables — this is
        what PolicyManager.initialize() does at startup.
        """
        store = PolicyStore(self._db)
        store.register_callables(self._registry)
        return store

    async def _get_seeded_policies_detail(self) -> list[PolicyInfo]:
        """Load seeded policy rows from SQLite with per-policy resolvability."""
        try:
            rows = await self._db.list_seeded_policies()
        except Exception:
            return []
        result = []
        for row in rows:
            components: list[str] = row.get("components") or []
            resolvable = all(c in self._registry for c in components)
            result.append(PolicyInfo(
                policy_name=row.get("policy_name", ""),
                trigger_type=row.get("trigger_type"),
                callable_ref=row.get("callable_ref"),
                components=components,
                components_resolvable=resolvable,
            ))
        return result

    @staticmethod
    def _ensure_domain_on_sys_path() -> None:
        """Add the app root to sys.path if domain/ is not yet importable.

        Primary fix is ENV PYTHONPATH=/app in the Dockerfile.  This is
        defence-in-depth for environments where that env var is absent.
        """
        controllers_dir = os.path.dirname(os.path.abspath(__file__))
        # services/ → market_storefront/ → src/ → (app root)
        app_root_candidate = os.path.dirname(  # src/
            os.path.dirname(  # market_storefront/
                os.path.dirname(controllers_dir)  # services/
            )
        )
        for candidate in ["/app", os.getcwd(), app_root_candidate]:
            if os.path.isdir(os.path.join(candidate, "domain")) and candidate not in sys.path:
                sys.path.insert(0, candidate)
                logger.info("[POLICY SEED] Added %s to sys.path for domain import", candidate)
                return

    # ------------------------------------------------------------------
    # seed_policies
    # ------------------------------------------------------------------

    async def seed_policies(self) -> SeedResult:
        """Discover @policy_callable decorators and seed default policies to SQLite.

        Step 1: Ensure domain/ is on sys.path, then walk
                ``domain.compute.agent.app.policy`` submodules so every
                @policy_callable decorator fires and populates CALLABLE_REGISTRY.
                Per-module import failures are collected (not raised) so one bad
                optional dependency like ``gymnasium`` doesn't block the rest.

        Step 2: Run ComputePolicySeeder.ensure_default_policies() to write the
                policy DB rows if absent.  Idempotent — safe to call repeatedly.

        Returns
        -------
        SeedResult
            Includes any per-module import errors so callers can surface them
            without reading container logs.
        """
        self._ensure_domain_on_sys_path()

        import_errors: list[ModuleImportError] = []
        try:
            pkg = importlib.import_module(self.POLICY_PACKAGE)
            if hasattr(pkg, "__path__"):
                for mod_info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                    try:
                        importlib.import_module(mod_info.name)
                    except Exception as mod_exc:
                        import_errors.append(ModuleImportError(
                            module=mod_info.name, error=str(mod_exc)
                        ))
                        logger.warning(
                            "[POLICY SEED] Failed to import %s: %s", mod_info.name, mod_exc
                        )
        except Exception as exc:
            logger.error("[POLICY SEED] Failed to import package %s: %s", self.POLICY_PACKAGE, exc)
            raise RuntimeError(f"Failed to import {self.POLICY_PACKAGE}: {exc}") from exc

        seeder = ComputePolicySeeder(
            policy_store=PolicyStore(self._db),
            sqlite_client=self._db,
            agent_id=self._agent_id,
        )
        await seeder.ensure_default_policies()

        seeded_names = [
            p.policy_name for p in await self._get_seeded_policies_detail()
        ]

        result = SeedResult(
            callable_registry_count=len(self._registry),
            callables=sorted(self._registry.keys()),
            seeded_policies=seeded_names,
            import_errors=import_errors,
        )
        logger.info(
            "[POLICY SEED] callable_count=%d seeded=%s import_errors=%d",
            result.callable_registry_count, seeded_names, len(import_errors),
        )
        return result

    # ------------------------------------------------------------------
    # get_policy_status
    # ------------------------------------------------------------------

    async def get_policy_status(self) -> PolicyStatusResult:
        """Return the callable registry contents and seeded policies with resolvability."""
        callables = sorted(self._registry.keys())
        seeded = await self._get_seeded_policies_detail()
        return PolicyStatusResult(
            callable_count=len(callables),
            callable_registry=callables,
            seeded_policies=seeded,
        )

    # ------------------------------------------------------------------
    # evaluate_order_create
    # ------------------------------------------------------------------

    async def evaluate_order_create(
        self,
        *,
        offer_raw: dict[str, Any],
        demand_raw: dict[str, Any],
        max_duration_seconds: int | None = None,
    ) -> EvalResult:
        """Dry-run a synthetic order_create event through the policy engine.

        Parses ``offer_raw`` and ``demand_raw`` through the same resource
        coercion path as ``POST /listings/create``, constructs a
        ListingCreatedEvent, and calls PolicyStore.evaluate_policy with a
        wired PolicyStore instance.

        No SQLite writes.  No registry API calls.

        Raises
        ------
        ValueError
            If offer_raw or demand_raw cannot be parsed into valid resource models.

        Returns
        -------
        EvalResult
            ``action`` is the lower-cased ActionType value (e.g. ``"make_offer"``)
            on success, or ``"no_action"`` with a populated ``reason`` when the
            pipeline can't produce an action.
        """
        offer_resource = parse_resource_from_dict(offer_raw)
        demand_resource = parse_resource_from_dict(demand_raw)

        synthetic_event = ListingCreatedEvent(
            event_id=f"dry_run_{uuid.uuid4().hex[:8]}",
            source="dry_run",
            offer=offer_resource,
            demand=demand_resource,
            max_duration_seconds=max_duration_seconds,
            data={
                "offer": offer_raw,
                "demand": demand_raw,
                "max_duration_seconds": max_duration_seconds,
                "paused": False,
            },
        )

        # Pre-flight: are there any policies seeded for this trigger?
        seeded_all = await self._get_seeded_policies_detail()
        oc_policies = [
            p for p in seeded_all
            if p.trigger_type == EventType.ORDER_CREATE.value
        ]
        if not oc_policies:
            return EvalResult(
                action="no_action",
                policy_used=None,
                components=[],
                resolvable=False,
                reason=(
                    "No policies seeded for 'order_create' trigger. "
                    "Call POST /admin/policy/seed first."
                ),
            )

        # Surface unresolvable components before running evaluation so the error
        # message names the missing callable(s) rather than silently returning None.
        first_unresolvable = next(
            (p for p in oc_policies if p.components and not p.components_resolvable),
            None,
        )
        if first_unresolvable:
            missing = [c for c in first_unresolvable.components if c not in self._registry]
            return EvalResult(
                action="no_action",
                policy_used=first_unresolvable.policy_name,
                components=first_unresolvable.components,
                resolvable=False,
                reason=(
                    f"Components not in callable registry: {missing}. "
                    "Call POST /admin/policy/seed."
                ),
            )

        policy_store = self._make_policy_store()
        ctx = DecisionContext(
            agent_id=self._agent_id,
            event=synthetic_event,
            market_state={},
            available_resources={},
            past_experiences=[],
            negotiation_history=[],
        )

        action = await policy_store.evaluate_policy(agent_id=self._agent_id, context=ctx)

        first_policy = oc_policies[0]
        if action is None:
            return EvalResult(
                action="no_action",
                policy_used=first_policy.policy_name,
                components=first_policy.components,
                resolvable=len(self._registry) > 0,
                reason=(
                    "Policy evaluated but returned no action. "
                    f"CALLABLE_REGISTRY has {len(self._registry)} entries. "
                    "If 0, call POST /admin/policy/seed first."
                ),
            )

        action_type = (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )
        return EvalResult(
            action=action_type.lower(),
            policy_used=first_policy.policy_name,
            components=first_policy.components,
            resolvable=True,
            reason=None,
        )
