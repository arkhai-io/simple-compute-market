"""SystemService — business logic for storefront health and connectivity checks.

Extracted from SystemController so that the logic is independently testable
without an HTTP request/response cycle.
"""

from __future__ import annotations

import asyncio
import httpx
import logging
import os
import time
from typing import Any

import market_storefront.container as _container
from market_storefront.utils.config import settings, chain_id, AGENT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SystemService:
    """Business logic for storefront health and connectivity checks."""

    def __init__(
        self,
        *,
        sqlite_client,
        agent_id: str | None = None,
    ) -> None:
        self._db = sqlite_client
        self._agent_id = agent_id or AGENT_ID or "agent"

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
                onchain_id = _live_agent_id or settings.onchain_agent_id
                if onchain_id:
                    from market_storefront.utils.action_executor import _canonical_agent_id
                    result["agent_id"] = _canonical_agent_id()
                else:
                    result["agent_id"] = None
            except Exception:
                result["agent_id"] = None
            try:
                result["chain_id"] = chain_id()
            except Exception:
                result["chain_id"] = None
            try:
                resources = await self._db.list_resources()
                result["resource_count"] = len(resources)
            except Exception:
                result["resource_count"] = None

        return result

    async def registry_check(self) -> str:
        """Probe every configured registry URL concurrently. Returns
        'ok' if at least one responded successfully; otherwise returns
        the last error string (so the operator at least gets *some*
        signal about what's wrong).

        Uses a 2-second timeout per registry so the status endpoint
        stays fast even with several configured. Only called from
        /api/v1/system/status — never from /health.
        """
        urls = [u.rstrip("/") for u in (settings.registry.urls or []) if u]
        if not urls:
            return "unconfigured"
        auth = settings.registry.auth or {}

        async def _probe(url: str) -> str:
            # /health is unauthenticated by design (so liveness probes
            # don't need credentials), so the auth header is optional
            # here; we attach it anyway to be consistent with
            # registry_auth_check and so private registries that ever
            # gate /health treat us identically to non-health requests.
            headers = {}
            token = auth.get(url) or auth.get(url + "/")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{url}/health", headers=headers)
                return "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
            except httpx.ConnectError:
                return "unreachable"
            except httpx.TimeoutException:
                return "timeout"
            except Exception as exc:
                return f"error: {exc}"

        import asyncio
        results = await asyncio.gather(*[_probe(u) for u in urls])
        if any(r == "ok" for r in results):
            return "ok"
        # Surface the most recent non-ok result (all are non-ok here).
        return results[-1]

    async def registry_auth_check(self) -> str:
        """Verify this agent's wallet owns its configured on-chain agent ID.

        Probes every configured registry concurrently. Returns 'ok' if
        at least one registry confirms the agent's owner matches our
        wallet. ``agent_not_found`` only when *every* registry reports
        404 (none have indexed us yet). Other definitive non-ok
        results win over agent_not_found because they're more
        actionable for the operator.
        """
        urls = [u.rstrip("/") for u in (settings.registry.urls or []) if u]
        if not urls:
            return "unconfigured"
        auth = settings.registry.auth or {}
        # Read the live runtime ID (set by _ensure_agent_identity at startup),
        # not the config-file value (which may be stale or absent when auto_register=True).
        from market_storefront.agent import _AGENT_ID as _live_agent_id
        onchain_id = _live_agent_id or settings.onchain_agent_id
        if not onchain_id:
            return "unconfigured"
        resolved_chain_id = chain_id()
        identity_addr = (settings.registry.identity_registry_address or "").lower()
        canonical = f"eip155:{resolved_chain_id}:{identity_addr}:{onchain_id}"
        wallet = (settings.wallet.address or "").lower()

        async def _probe(url: str) -> str:
            headers = {}
            token = auth.get(url) or auth.get(url + "/")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(
                        f"{url}/agents/{canonical}", headers=headers,
                    )
                if resp.status_code == 404:
                    return "agent_not_found"
                if resp.status_code >= 400:
                    return f"http_{resp.status_code}"
                data = resp.json()
                owner = (data.get("owner") or "").lower()
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

        import asyncio
        results = await asyncio.gather(*[_probe(u) for u in urls])
        if "ok" in results:
            return "ok"
        # Prefer a definitive non-ok result over agent_not_found, since
        # the latter is the transient "registry hasn't EventSynced yet"
        # state that wait_for_registry_agent retries past.
        for r in results:
            if r not in ("agent_not_found",):
                return r
        return "agent_not_found"

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
        _pending = {"agent_not_found", "timeout", "unreachable"}
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

    # Canonical bind-mount target for the inventory CSV inside a container.
    # When neither csv_inline nor csv_path is set explicitly,
    # ``seed_resources_if_empty`` auto-discovers a file at this path. Lets
    # the canonical compose deploy work with no resources_csv_path setting
    # in the TOML.
    _DEFAULT_CSV_PATH = "/app/resources.csv"

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
          3. Auto-discovery of ``/app/resources.csv`` — the canonical
             container bind-mount target. Skipped silently when the file
             doesn't exist, so local-dev outside a container is unaffected.

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
        elif os.path.exists(self._DEFAULT_CSV_PATH):
            report = await self._db.upsert_resources_from_csv(csv_path=self._DEFAULT_CSV_PATH)
            source = f"{self._DEFAULT_CSV_PATH} (auto-discovered)"
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
