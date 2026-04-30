"""System controller — health, liveness, and policy diagnostic endpoints.

Exposes:
  ``GET  /health``                        Kubernetes liveness/readiness probe.
  ``GET  /api/v1/system/health``          Versioned alias, same handler.
  ``GET  /api/v1/system/status``          Richer diagnostic (DB reachability, pause state).
  ``POST /admin/policy/seed``             Idempotent: discover callables + seed default policies.
  ``GET  /api/v1/system/policy``          Callable registry + seeded policy diagnostic.
  ``POST /api/v1/system/policy/evaluate`` Dry-run an order event against the policy engine.

``/health`` is kept at the root to match the Kubernetes probe convention
used by the provisioning and registry services.

Policy endpoints
----------------
``POST /admin/policy/seed`` (admin key required) ensures the in-process
``CALLABLE_REGISTRY`` is populated and the default policies are written to
SQLite.  Safe to call repeatedly — all operations are idempotent.  Useful
after a startup where ``discover_and_register`` silently failed (e.g. because
``gymnasium`` was not installed, causing the package walk to abort before
importing ``store.py``).

``GET /api/v1/system/policy`` returns the current callable registry contents
and seeded policies with a ``components_resolvable`` flag so operators can
diagnose mismatches between the DB policy rows and the in-memory callable
registry without reading logs.

``POST /api/v1/system/policy/evaluate`` accepts a synthetic order event and
returns what action the policy engine would produce, without writing anything
to SQLite or calling the registry.  Use it after seeding to confirm the
pipeline is wired end-to-end before submitting a real order.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import pkgutil
import sqlite3
import sys
import uuid
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from market_policy.registry import CALLABLE_REGISTRY
from market_policy.store import PolicyStore
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.schema.pydantic_models import (
    ListingCreatedEvent, EventType, ComputeResource, TokenResource,
)
from market_storefront.utils.action_executor import parse_resource_from_dict
from market_storefront.utils.config import CONFIG
from service.schemas import DecisionContext

logger = logging.getLogger(__name__)


class SystemController:
    """Stateless handler class — all methods are ``@staticmethod`` or use
    module-level singletons injected at mount time."""

    def __init__(self, *, sqlite_client, globally_paused_fn) -> None:
        """
        Parameters
        ----------
        sqlite_client:
            The storefront's ``SQLiteClient`` instance (used for DB ping and
            policy row reads).
        globally_paused_fn:
            Zero-arg callable that returns ``bool`` — the current global pause
            state.  Passed as a callable so the controller always reads the
            live value rather than a snapshot taken at construction time.
        """
        self._sqlite_client = sqlite_client
        self._globally_paused_fn = globally_paused_fn

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def _health_impl(self) -> JSONResponse:
        checks: dict[str, str] = {"api": "ok"}

        # DB ping — open a read connection and SELECT 1.
        try:
            conn = sqlite3.connect(self._sqlite_client.db_path, timeout=2)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if all_ok else "degraded", "checks": checks},
            status_code=200 if all_ok else 503,
        )

    async def health_bare(self, request: Request) -> JSONResponse:
        """``GET /health`` — Kubernetes liveness probe."""
        return await self._health_impl()

    async def health_versioned(self, request: Request) -> JSONResponse:
        """``GET /api/v1/system/health`` — versioned alias."""
        return await self._health_impl()

    async def system_status(self, request: Request) -> JSONResponse:
        """``GET /api/v1/system/status`` — diagnostic snapshot.

        Returns the global pause flag alongside the health checks so callers
        can distinguish "healthy but paused" from "degraded".
        """
        health_response = await self._health_impl()
        body = json.loads(health_response.body)
        body["paused"] = self._globally_paused_fn()
        return JSONResponse(body, status_code=health_response.status_code)

    # ------------------------------------------------------------------
    # Policy seed (admin key required — enforced by AdminAuthMiddleware)
    # ------------------------------------------------------------------

    async def policy_seed(self, request: Request) -> JSONResponse:
        """``POST /admin/policy/seed`` — idempotent callable discovery + policy seeding.

        Step 1: Re-runs ``discover_and_register("domain.compute.agent.app.policy")``
                to populate the in-process ``CALLABLE_REGISTRY``.
        Step 2: Calls ``ComputePolicySeeder.ensure_default_policies()`` to write
                the default policy rows to SQLite if absent.

        Returns the post-seed callable count and the list of seeded policy names.
        """
        # Step 1 — repopulate CALLABLE_REGISTRY
        # Walk the package manually so we can collect per-module import errors
        # and surface them in the response — the stock discover_and_register
        # swallows errors silently into WARNING logs which aren't visible to callers.

        # domain/ lives at /app/domain in the container (WORKDIR=/app).
        # Console-script entry points don't add CWD to sys.path, so we
        # add the app root explicitly if it's missing. PYTHONPATH="/app" in
        # the Dockerfile is the primary fix; this is defence-in-depth.
        _app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Walk up from controllers/ to find the repo root containing domain/
        for _candidate in ["/app", os.getcwd(), os.path.dirname(_app_root)]:
            if os.path.isdir(os.path.join(_candidate, "domain")) and _candidate not in sys.path:
                sys.path.insert(0, _candidate)
                logger.info("[POLICY SEED] Added %s to sys.path for domain import", _candidate)
                break

        import_errors: list[dict] = []
        pkg_name = "domain.compute.agent.app.policy"
        try:
            pkg = importlib.import_module(pkg_name)
            if hasattr(pkg, "__path__"):
                for mod_info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                    try:
                        importlib.import_module(mod_info.name)
                    except Exception as mod_exc:
                        import_errors.append({"module": mod_info.name, "error": str(mod_exc)})
                        logger.warning("[POLICY SEED] Failed to import %s: %s", mod_info.name, mod_exc)
        except Exception as exc:
            logger.error("[POLICY SEED] Failed to import package %s: %s", pkg_name, exc)
            return JSONResponse(
                {"error": f"Failed to import {pkg_name}", "detail": str(exc)},
                status_code=500,
            )

        callable_count = len(CALLABLE_REGISTRY)
        callables = sorted(CALLABLE_REGISTRY.keys())

        # Step 2 — seed default policies into SQLite

        try:
            policy_store = PolicyStore(self._sqlite_client)
            seeder = ComputePolicySeeder(
                policy_store=policy_store,
                sqlite_client=self._sqlite_client,
                agent_id=CONFIG.agent_id or "agent",
            )
            await seeder.ensure_default_policies()
        except Exception as exc:
            logger.error("[POLICY SEED] ensure_default_policies failed: %s", exc)
            return JSONResponse(
                {"error": "policy seeding failed", "detail": str(exc)},
                status_code=500,
            )

        # Collect seeded policy names from SQLite for the response
        seeded_policies = await self._get_seeded_policy_names()

        logger.info(
            "[POLICY SEED] callable_count=%d seeded_policies=%s import_errors=%d",
            callable_count, seeded_policies, len(import_errors),
        )
        return JSONResponse({
            "callable_registry_count": callable_count,
            "callables": callables,
            "seeded_policies": seeded_policies,
            "import_errors": import_errors,   # empty list on full success
        })

    # ------------------------------------------------------------------
    # Policy diagnostic (no auth required — read-only)
    # ------------------------------------------------------------------

    async def policy_status(self, request: Request) -> JSONResponse:
        """``GET /api/v1/system/policy`` — callable registry + seeded policy diagnostic.

        Returns the current contents of the in-process CALLABLE_REGISTRY and
        the policies stored in SQLite, with a ``components_resolvable`` flag on
        each policy that is ``true`` only when every component name is present
        in the registry.  Use this to diagnose mismatches between DB rows and
        the live callable registry without reading container logs.
        """

        callables = sorted(CALLABLE_REGISTRY.keys())

        # Read seeded policies from SQLite
        seeded = await self._get_seeded_policies_detail(CALLABLE_REGISTRY)

        return JSONResponse({
            "callable_count": len(callables),
            "callable_registry": callables,
            "seeded_policies": seeded,
        })

    # ------------------------------------------------------------------
    # Policy dry-run (no auth required — read-only, no side effects)
    # ------------------------------------------------------------------

    async def policy_evaluate(self, request: Request) -> JSONResponse:
        """``POST /api/v1/system/policy/evaluate`` — dry-run an order event.

        Accepts a synthetic ``order_create`` event payload and runs it through
        the policy engine exactly as ``POST /orders/create`` would, but without
        writing anything to SQLite or calling the registry.  Returns the action
        the policy engine would produce.

        Request body::

            {
                "event_type": "order_create",           // only supported value for now
                "offer":  { "gpu_model": "H200", "quantity": 1, "sla": 99.0,
                            "region": "California, US" },
                "demand": { "token": {...}, "amount": 10000 }
            }

        Response::

            {
                "action":    "make_offer",   // or "no_action"
                "policy_used":  "order_create_default_v1",
                "components":   ["oc.action.make_offer_from_order_create"],
                "resolvable":   true,
                "reason":       null         // populated when action == "no_action"
            }
        """
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        event_type = body.get("event_type", "order_create")
        if event_type != "order_create":
            return JSONResponse(
                {"error": f"Unsupported event_type: {event_type!r}. Only 'order_create' is supported."},
                status_code=400,
            )

        offer_raw = body.get("offer")
        demand_raw = body.get("demand")
        if not offer_raw or not demand_raw:
            return JSONResponse(
                {"error": "Request body must include 'offer' and 'demand' fields."},
                status_code=400,
            )

        # Parse resources through the same path as the real endpoint

        try:
            offer_resource = parse_resource_from_dict(offer_raw)
            demand_resource = parse_resource_from_dict(demand_raw)
        except Exception as exc:
            return JSONResponse(
                {"error": "Invalid offer/demand resource", "detail": str(exc)},
                status_code=400,
            )

        synthetic_event = ListingCreatedEvent(
            event_id=f"dry_run_{uuid.uuid4().hex[:8]}",
            source="dry_run",
            offer=offer_resource,
            demand=demand_resource,
            duration_hours=body.get("duration_hours", 1),
            data={
                "offer": offer_raw,
                "demand": demand_raw,
                "duration_hours": body.get("duration_hours", 1),
                "paused": False,
            },
        )

        # Delegate to PolicyStore.evaluate_policy — the same path TraderAgent._consult_policy
        # uses.  Pure read: no SQLite writes, no registry calls.

        agent_id = CONFIG.agent_id or "agent"
        policy_store = PolicyStore(self._sqlite_client)

        # Quick pre-flight: are any policies seeded at all for this trigger?
        # We do this separately so we can give a clear error vs "callable missing".
        seeded_all = await self._get_seeded_policies_detail(CALLABLE_REGISTRY)
        oc_policies = [p for p in seeded_all if p.get("trigger_type") == EventType.ORDER_CREATE.value]
        if not oc_policies:
            return JSONResponse({
                "action": "no_action",
                "policy_used": None,
                "components": [],
                "resolvable": False,
                "reason": "No policies seeded for 'order_create' trigger. Call POST /admin/policy/seed first.",
            })

        # Surface unresolvable components only when we actually have components to check.
        # (Empty components means the JOIN found no composite rows — treat as resolvable
        # and let PolicyStore try the callable_ref directly in the registry.)
        has_components = any(p["components"] for p in oc_policies)
        if has_components:
            first_unresolvable = next(
                (p for p in oc_policies if p["components"] and not p["components_resolvable"]),
                None,
            )
            if first_unresolvable:
                unresolvable = [c for c in first_unresolvable["components"] if c not in CALLABLE_REGISTRY]
                return JSONResponse({
                    "action": "no_action",
                    "policy_used": first_unresolvable["policy_name"],
                    "components": first_unresolvable["components"],
                    "resolvable": False,
                    "reason": f"Components not in callable registry: {unresolvable}. Call POST /admin/policy/seed.",
                })

        ctx = DecisionContext(
            agent_id=agent_id,
            event=synthetic_event,
            market_state={},
            available_resources={},
            past_experiences=[],
            negotiation_history=[],
        )

        try:
            action = await policy_store.evaluate_policy(agent_id=agent_id, context=ctx)
        except Exception as exc:
            logger.warning("[POLICY EVAL] evaluate_policy raised: %s", exc)
            return JSONResponse(
                {"error": "Policy evaluation error", "detail": str(exc)},
                status_code=500,
            )

        if action is None:
            # Callable registry is likely empty — report it clearly.
            callable_count = len(CALLABLE_REGISTRY)
            return JSONResponse({
                "action": "no_action",
                "policy_used": oc_policies[0]["policy_name"],
                "components": oc_policies[0]["components"],
                "resolvable": callable_count > 0,
                "reason": (
                    "Policy evaluated but returned no action. "
                    f"CALLABLE_REGISTRY has {callable_count} entries. "
                    "If 0, call POST /admin/policy/seed first."
                ),
            })

        action_type = action.action_type.value if hasattr(action.action_type, "value") else str(action.action_type)
        return JSONResponse({
            "action": action_type.lower(),
            "policy_used": oc_policies[0]["policy_name"],
            "components": oc_policies[0]["components"],
            "resolvable": True,
            "reason": None,
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_seeded_policy_names(self) -> list[str]:
        """Return all policy_name values stored in SQLite."""
        try:
            rows = await self._sqlite_client.list_seeded_policies()
            return [r.get("policy_name", "") for r in rows if r.get("policy_name")]
        except Exception:
            return []

    async def _get_seeded_policies_detail(self, callable_registry: dict) -> list[dict]:
        """Return seeded policies with components and resolvability flag."""
        try:
            rows = await self._sqlite_client.list_seeded_policies()
        except Exception:
            return []
        result = []
        for row in rows:
            components = row.get("components") or []
            if isinstance(components, str):
                try:
                    components = json.loads(components)
                except Exception:
                    components = [components]
            resolvable = all(c in callable_registry for c in components)
            result.append({
                "policy_name": row.get("policy_name"),
                "trigger_type": row.get("trigger_type"),
                "components": components,
                "components_resolvable": resolvable,
            })
        return result

    # ------------------------------------------------------------------
    # Route factory
    # ------------------------------------------------------------------

    def routes(self) -> list[Route]:
        """Return all routes for this controller."""
        return [
            Route("/health",                            self.health_bare,      methods=["GET"]),
            Route("/api/v1/system/health",              self.health_versioned,  methods=["GET"]),
            Route("/api/v1/system/status",              self.system_status,     methods=["GET"]),
            Route("/admin/policy/seed",                 self.policy_seed,       methods=["POST"]),
            Route("/api/v1/system/policy",              self.policy_status,     methods=["GET"]),
            Route("/api/v1/system/policy/evaluate",     self.policy_evaluate,   methods=["POST"]),
        ]
