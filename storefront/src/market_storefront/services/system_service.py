"""SystemService — business logic for policy seeding, status, and dry-run evaluation.

Extracted from SystemController so that the logic is independently testable
without an HTTP request/response cycle.

Three responsibilities:
  seed_policies()          — discover @policy_callable decorators + seed DB rows
  get_policy_status()      — read callable registry + seeded policies with resolvability
None of these methods write to the registry or produce side-effects beyond SQLite
(seed_policies writes policy rows; all other methods are read-only).
"""

from __future__ import annotations

import asyncio
import httpx
import importlib
import logging
import os
import pkgutil
import sys
import time
from typing import Any

import market_storefront.container as _container
from market_policy.registry import CALLABLE_REGISTRY
from market_policy.store import PolicyStore
from market_storefront.policy.seeding import ComputePolicySeeder
from market_storefront.models.system_models import (
    ImportErrorResponse,
    PolicyStatusResponse,
    SeededPolicyInfo,
    SeedPoliciesResponse,
)
from market_storefront.utils.config import CONFIG, _resolve_chain_id

logger = logging.getLogger(__name__)


# Internal transfer object used only within _get_seeded_policies_detail
class _PolicyInfoInternal:
    __slots__ = ("policy_name", "trigger_type", "callable_ref", "components", "components_resolvable")
    def __init__(self, policy_name, trigger_type, callable_ref, components, components_resolvable):
        self.policy_name = policy_name
        self.trigger_type = trigger_type
        self.callable_ref = callable_ref
        self.components = components
        self.components_resolvable = components_resolvable


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

    async def _get_seeded_policies_detail(self) -> list[_PolicyInfoInternal]:
        """Load seeded policy rows from SQLite with per-policy resolvability."""
        try:
            rows = await self._db.list_seeded_policies()
        except Exception:
            return []
        result = []
        for row in rows:
            components: list[str] = row.get("components") or []
            resolvable = all(c in self._registry for c in components)
            result.append(_PolicyInfoInternal(
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

    async def seed_policies(self) -> SeedPoliciesResponse:
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

        import_errors: list[ImportErrorResponse] = []
        try:
            pkg = importlib.import_module(self.POLICY_PACKAGE)
            if hasattr(pkg, "__path__"):
                for mod_info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
                    try:
                        importlib.import_module(mod_info.name)
                    except Exception as mod_exc:
                        import_errors.append(ImportErrorResponse(
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

        result = SeedPoliciesResponse(
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

    async def get_policy_status(self) -> PolicyStatusResponse:
        """Return the callable registry contents and seeded policies with resolvability."""
        callables = sorted(self._registry.keys())
        seeded = await self._get_seeded_policies_detail()
        return PolicyStatusResponse(
            callable_count=len(callables),
            callable_registry={k: k for k in callables},
            seeded_policies=[
                SeededPolicyInfo(
                    policy_name=p.policy_name,
                    trigger_type=p.trigger_type or "",
                    components=p.components,
                    components_resolvable=p.components_resolvable,
                )
                for p in seeded
            ],
        )

    # ------------------------------------------------------------------
    # Health / connectivity checks
    # Moved from SystemController._health_impl / _registry_check etc.
    # ------------------------------------------------------------------

    async def get_health(self, *, include_registry: bool = False) -> dict:
        """Return a health dict: {status, checks}.

        Parameters
        ----------
        include_registry:
            When True, also probe the registry URL, verify agent ownership,
            and check negotiation strategy viability. Used by
            GET /api/v1/system/status. Omitted for the fast /health liveness probe.
        """
        import sqlite3

        checks: dict[str, str] = {"api": "ok"}
        try:
            conn = sqlite3.connect(self._db.db_path, timeout=2)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"

        if include_registry:
            checks["registry"] = await self.registry_check()
            checks["registry_auth"] = await self.registry_auth_check()
            checks["negotiation_strategy"] = self.negotiation_strategy_check()

        # agent_not_found is a transient post-registration state (registry indexing lag)
        # and is not a service degradation. Only hard errors cause degraded status.
        # alkahest configured?
        checks["alkahest"] = "ok" if _container.resolved_alkahest_configured else "unconfigured"

        def _check_is_healthy(key: str, value: str) -> bool:
            """Return True if this check value does not indicate a service degradation.

            The ``negotiation_strategy`` check returns a human-readable strategy
            name (e.g. ``"bisection"``) on success rather than the literal ``"ok"``,
            so it gets its own rule: healthy unless the value contains the
            ``exit_on_probe`` marker or starts with a known error prefix.
            """
            _ok_literals = {"ok", "unconfigured", "agent_not_found", "indexing"}
            if value in _ok_literals:
                return True
            if key == "negotiation_strategy":
                return "exit_on_probe" not in value and not value.startswith(
                    ("unknown:", "error:")
                )
            return False

        all_ok = all(_check_is_healthy(k, v) for k, v in checks.items())

        result: dict = {"status": "ok" if all_ok else "degraded", "checks": checks}

        if include_registry:
            # Populate top-level diagnostic fields — not checks, just facts.
            try:
                from market_storefront.agent import _AGENT_ID as _live_agent_id
                onchain_id = _live_agent_id or CONFIG.onchain_agent_id
                if onchain_id:
                    from market_storefront.utils.action_executor import _canonical_agent_id
                    result["agent_id"] = _canonical_agent_id()
                else:
                    result["agent_id"] = None
            except Exception:
                result["agent_id"] = None
            try:
                result["chain_id"] = _resolve_chain_id()
            except Exception:
                result["chain_id"] = None
            try:
                resources = await self._db.list_resources()
                result["resource_count"] = len(resources)
            except Exception:
                result["resource_count"] = None

        return result

    async def registry_check(self) -> str:
        """Probe the configured registry URL. Returns 'ok' or an error string.

        Uses a 2-second timeout so the status endpoint stays fast.
        Only called from /api/v1/system/status — never from /health.
        """
        url = (CONFIG.indexer_url or "").rstrip("/")
        if not url:
            return "unconfigured"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/health")
            return "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
        except httpx.ConnectError:
            return "unreachable"
        except httpx.TimeoutException:
            return "timeout"
        except Exception as exc:
            return f"error: {exc}"

    async def registry_auth_check(self) -> str:
        """Verify this agent's wallet owns its configured on-chain agent ID.

        Returns 'ok', 'unconfigured', 'agent_not_found', 'owner_mismatch',
        or an error string.
        """
        url = (CONFIG.indexer_url or "").rstrip("/")
        if not url:
            return "unconfigured"
        # Read the live runtime ID (set by _ensure_agent_identity at startup),
        # not the config-file value (which may be stale or absent when auto_register=True).
        from market_storefront.agent import _AGENT_ID as _live_agent_id
        onchain_id = _live_agent_id or CONFIG.onchain_agent_id
        if not onchain_id:
            return "unconfigured"
        chain_id = _resolve_chain_id()
        identity_addr = (CONFIG.identity_registry_address or "").lower()
        canonical = f"eip155:{chain_id}:{identity_addr}:{onchain_id}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{url}/agents/{canonical}")
            if resp.status_code == 404:
                return "agent_not_found"
            if resp.status_code >= 400:
                return f"http_{resp.status_code}"
            data = resp.json()
            owner = (data.get("owner") or "").lower()
            wallet = (CONFIG.agent_wallet_address or "").lower()
            if not owner:
                return "owner_unknown"
            if not wallet:
                return "wallet_unconfigured"
            return "ok" if owner == wallet else "owner_mismatch"
        except httpx.ConnectError:
            return "unreachable"
        except httpx.TimeoutException:
            return "timeout"
        except Exception as exc:
            return f"error: {exc}"

    async def wait_for_registry_agent(self, timeout: float) -> dict:
        """Block until registry_auth_check() returns a definitive result.

        Polls registry_auth_check() every second until the result is anything
        other than 'agent_not_found' (the transient state while the registry's
        EventSync is catching up after a fresh on-chain registration), or until
        *timeout* seconds elapse.

        Returns a dict with keys:
          ready       — True if a definitive result was reached before timeout
          registry_auth — the raw registry_auth_check() value
          elapsed_ms  — approximate wall-clock wait time in milliseconds

        'ready=True' does not imply 'registry_auth="ok"' — callers must check
        registry_auth independently.  Definitive non-ok values include
        'owner_mismatch', 'unconfigured', 'unreachable', and error strings.

        Intended consumers:
          - GET /api/v1/system/wait-for-registry-agent (thin controller wrapper)
          - Storefront startup sequence (agent.py) — wait before starting the
            heartbeat loop so the first heartbeat is not guaranteed to 404.
        """
        _pending = {"agent_not_found"}
        poll_interval = 1.0
        start = time.monotonic()
        deadline = start + timeout
        registry_auth = "unknown"

        while True:
            registry_auth = await self.registry_auth_check()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if registry_auth not in _pending:
                return {
                    "ready": True,
                    "registry_auth": registry_auth,
                    "elapsed_ms": elapsed_ms,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "ready": False,
            "registry_auth": registry_auth,
            "elapsed_ms": elapsed_ms,
        }

    async def seed_resources_if_empty(
        self,
        *,
        csv_inline: str | None = None,
        csv_path: str | None = None,
    ) -> dict:
        """Seed the resources table on startup if it is empty.

        Source priority (matches provisioning service pattern):
          1. ``csv_inline`` — raw CSV content delivered via config injection
             (Helm Secret ``resources_csv_inline``). Used when the CSV must not
             be baked into the container image.
          2. ``csv_path`` — path to a CSV file on disk (compose / local dev).

        Seeding is skipped when the resources table already has rows, so that
        operator changes made via the import API are not overwritten on pod
        restart. To force a clobber regardless of table state, use
        ``POST /api/v1/admin/portfolio/resources/import``.

        Returns a dict with keys:
          seeded         — True if the CSV was imported, False if skipped.
          imported_count — number of rows written (0 when seeded=False).
          source         — human-readable description of the data source used.
        """
        existing = await self._db.list_resources()
        if existing:
            logger.info(
                "[RESOURCE SEED] Skipping — %d resource(s) already in DB",
                len(existing),
            )
            return {"seeded": False, "imported_count": len(existing), "source": "already_populated"}

        if csv_inline:
            report = await self._db.upsert_resources_from_csv_content(
                csv_content=csv_inline,
                source_label="resources_csv_inline (config)",
            )
            source = "resources_csv_inline (config)"
        elif csv_path:
            report = await self._db.upsert_resources_from_csv(csv_path=csv_path)
            source = csv_path
        else:
            logger.info("[RESOURCE SEED] No resource source configured — starting with empty inventory")
            return {"seeded": False, "imported_count": 0, "source": None}

        imported = report.get("imported_count", 0)
        failed = report.get("failed_count", 0)
        if failed:
            logger.warning(
                "[RESOURCE SEED] %d row(s) failed to import from %s",
                failed, source,
            )
        logger.info("[RESOURCE SEED] Imported %d resource(s) from %s", imported, source)
        return {"seeded": True, "imported_count": imported, "source": source}

    def negotiation_strategy_check(self) -> str:
        """Probe the configured negotiation strategy. Returns a viability string.

        Possible values:
          'bisection'                    — BisectionStrategy loaded; always viable
          'rl (viable)'                  — RL strategy loaded; torch is available
          '<name> (exit_on_probe: <r>)'  — strategy exits every round; will fail
          'unknown: <msg>'               — load_strategy raised
        """
        try:
            from market_policy.negotiation_strategy import NegotiationRoundInput
            from market_storefront.utils.sync_negotiation import _load_storefront_strategy

            strategy = _load_storefront_strategy()
            name = type(strategy).__name__
            probe = strategy.decide(NegotiationRoundInput(
                direction="maximize",
                our_reference_price=10_000,
                their_proposed_price=10_000,
                history=[],
            ))
            if probe.action == "exit":
                return f"{name} (exit_on_probe: {probe.reason})"
            return name.lower().replace("strategy", "").strip() or name
        except KeyError as exc:
            return f"unknown: {exc}"
        except Exception as exc:
            return f"error: {exc}"
