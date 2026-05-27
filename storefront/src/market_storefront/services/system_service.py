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
from market_storefront.utils.config import CHAINS, settings, AGENT_ID

logger = logging.getLogger(__name__)


# Per-chain registry-auth states that mean "still in flight" — the wait
# loop retries past these. Definitive states (``ok``, ``owner_mismatch``,
# ``owner_unknown``, ``wallet_unconfigured``, ``unconfigured``, ``http_*``,
# ``error: ...``) end the wait.
_REGISTRY_AUTH_PENDING: frozenset[str] = frozenset({
    "agent_not_found",
    "agent_not_resolved",
    "timeout",
    "unreachable",
})


def _aggregate_registry_auth(per_chain: dict[str, str]) -> str:
    """Collapse per-chain auth states into a single status string.

    ``"ok"`` iff every chain reports ``"ok"``. Empty dict (no chains
    configured) → ``"unconfigured"`` to preserve the pre-multi-chain
    surface. Otherwise returns ``"<chain>:<status>"`` for the first
    non-ok chain in dict iteration order — operators get a deterministic,
    actionable hint pointing at the chain that needs attention.
    """
    if not per_chain:
        return "unconfigured"
    for name, status in per_chain.items():
        if status != "ok":
            return f"{name}:{status}"
    return "ok"


def _per_chain_has_pending(per_chain: dict[str, str]) -> bool:
    """True iff any chain is in a transient (retry-worthy) state.

    Empty dict (no chains configured) is treated as definitive — there is
    nothing to wait on, so the caller exits immediately with whatever
    aggregate string the empty dict produces (``"unconfigured"``).
    """
    return any(s in _REGISTRY_AUTH_PENDING for s in per_chain.values())


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

        per_chain_auth: dict[str, str] = {}
        if include_registry:
            checks["registry"] = await self.registry_check()
            per_chain_auth = await self._registry_auth_per_chain()
            checks["registry_auth"] = _aggregate_registry_auth(per_chain_auth)
            checks["negotiation_strategy"] = self.negotiation_strategy_check()

        # agent_not_found is a transient post-registration state (registry indexing lag)
        # and is not a service degradation. Only hard errors cause degraded status.
        # alkahest configured?
        configured = _container.configured_chain_names()
        if configured:
            checks["alkahest"] = ",".join(sorted(configured))
        else:
            checks["alkahest"] = "unconfigured"

        def _check_is_healthy(key: str, value: str) -> bool:
            """Return True if this check value does not indicate a service degradation.

            The ``negotiation_strategy`` check returns a human-readable strategy
            name (e.g. ``"bisection"``) on success rather than the literal ``"ok"``,
            so it gets its own rule. The ``alkahest`` check returns the
            comma-joined list of configured chain names (e.g.
            ``"base_sepolia,ethereum_sepolia"``) when at least one chain is
            up — also handled with its own rule. ``registry_auth`` may carry
            a ``"<chain>:<status>"`` aggregate from the multi-chain probe;
            we strip the chain prefix before checking literal-ness so
            transient states (``agent_not_found``, ``agent_not_resolved``)
            still report as healthy regardless of which chain raised them.
            """
            _ok_literals = {
                "ok", "unconfigured", "agent_not_found", "agent_not_resolved", "indexing",
            }
            literal = value
            if key == "registry_auth" and ":" in value:
                literal = value.split(":", 1)[1]
            if literal in _ok_literals:
                return True
            if key == "negotiation_strategy":
                return "exit_on_probe" not in value and not value.startswith(
                    ("unknown:", "error:")
                )
            if key == "alkahest":
                return bool(value) and not value.startswith(("unknown:", "error:"))
            return False

        all_ok = all(_check_is_healthy(k, v) for k, v in checks.items())

        result: dict = {"status": "ok" if all_ok else "degraded", "checks": checks}

        if include_registry:
            # Populate top-level diagnostic fields — not checks, just facts.
            # Per-chain: emit one (chain_name -> canonical_id + auth_status)
            # entry per configured chain. The single-chain shape
            # (top-level ``agent_id`` / ``chain_id``) is replaced because
            # there is no single canonical truth in a multi-chain world.
            try:
                from market_storefront.agent import _AGENT_IDS
                from service.clients.erc8004.blockchain import build_erc8004_canonical_id
                identities: dict[str, dict[str, Any]] = {}
                for name, chain in CHAINS.items():
                    aid = _AGENT_IDS.get(name)
                    auth_status = per_chain_auth.get(name, "unconfigured")
                    if aid is None or not chain.identity_registry_address:
                        identities[name] = {
                            "chain_id": chain.chain_id,
                            "agent_id": None,
                            "canonical_id": None,
                            "auth_status": auth_status,
                        }
                        continue
                    identities[name] = {
                        "chain_id": chain.chain_id,
                        "agent_id": aid,
                        "canonical_id": build_erc8004_canonical_id(
                            chain_id=chain.chain_id,
                            identity_registry=chain.identity_registry_address,
                            agent_id=aid,
                        ),
                        "auth_status": auth_status,
                    }
                result["identities"] = identities
            except Exception:
                result["identities"] = {}
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
        """Aggregate registry-auth verdict across every configured chain.

        Returns ``"ok"`` iff every configured chain has a resolved agent
        ID and at least one registry confirms the owner matches our
        wallet for that chain. Otherwise returns ``"<chain>:<status>"``
        for the first non-ok chain (deterministic by TOML order). When
        no chains are configured at all, returns ``"unconfigured"`` for
        symmetry with the pre-multi-chain shape.

        ``wait_for_registry_agent`` consumes the same per-chain dict
        directly via :meth:`_registry_auth_per_chain` so it can wait for
        every chain rather than parsing this aggregate.
        """
        per_chain = await self._registry_auth_per_chain()
        return _aggregate_registry_auth(per_chain)

    async def _registry_auth_per_chain(self) -> dict[str, str]:
        """Probe registry-auth for every configured chain, concurrently.

        For each chain in ``CHAINS``:

        - If the chain has no resolved agent ID yet (startup task still
          running) → ``"agent_not_resolved"`` (pending state).
        - If the chain has no ``identity_registry_address`` → ``"unconfigured"``.
        - Otherwise probe every configured registry URL concurrently and
          pick the best result for that chain: ``"ok"`` wins; then
          definitive non-ok beats ``"agent_not_found"``; otherwise
          ``"agent_not_found"``.

        Wallet missing → ``"wallet_unconfigured"`` for every chain. No
        configured chains → empty dict (callers aggregate to
        ``"unconfigured"``).
        """
        if not CHAINS:
            return {}
        from market_storefront.agent import _AGENT_IDS
        from service.clients.erc8004.blockchain import build_erc8004_canonical_id

        urls = [u.rstrip("/") for u in (settings.registry.urls or []) if u]
        auth = settings.registry.auth or {}
        wallet = (settings.wallet.address or "").lower()

        async def _probe_one(url: str, canonical: str) -> str:
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

        async def _check_chain(name: str) -> tuple[str, str]:
            chain = CHAINS[name]
            aid = _AGENT_IDS.get(name)
            if aid is None:
                return name, "agent_not_resolved"
            if not chain.identity_registry_address:
                return name, "unconfigured"
            if not urls:
                return name, "unconfigured"
            canonical = build_erc8004_canonical_id(
                chain_id=chain.chain_id,
                identity_registry=chain.identity_registry_address,
                agent_id=aid,
            )
            results = await asyncio.gather(*[_probe_one(u, canonical) for u in urls])
            if "ok" in results:
                return name, "ok"
            for r in results:
                if r != "agent_not_found":
                    return name, r
            return name, "agent_not_found"

        pairs = await asyncio.gather(*[_check_chain(n) for n in CHAINS.keys()])
        return dict(pairs)

    async def wait_for_registry_agent(self, timeout: float) -> dict:
        """Block until every configured chain has a definitive auth result.

        Polls every second until no chain remains in a pending state
        (``agent_not_found``, ``agent_not_resolved``, ``timeout``, or
        ``unreachable`` — all transient: the registry's EventSync still
        catching up, or the per-chain identity startup task still
        registering), or until *timeout* seconds elapse.

        Returns a dict with keys:
          ready             — True if every chain reached a definitive state
                              before timeout
          registry_auth     — the aggregate string (``"ok"`` iff every chain is
                              ok, else ``"<chain>:<status>"`` for the first
                              non-ok chain)
          auth_per_chain    — the full per-chain dict (chain_name → status)
          elapsed_ms        — approximate wall-clock wait time in ms

        'ready=True' does not imply 'registry_auth="ok"' — callers must check
        registry_auth or auth_per_chain to distinguish ``"ok"`` from
        ``"owner_mismatch"``, etc.

        Intended consumers:
          - GET /api/v1/system/wait-for-registry-agent
          - Storefront startup sequence (agent.py) — wait before starting the
            heartbeat loop so the first heartbeat is not guaranteed to 404.

        Drives off :meth:`_registry_auth_per_chain` directly so the wait
        sees per-chain state without needing to round-trip through the
        aggregate string. Tests that want a synthetic transient state can
        patch ``_registry_auth_per_chain``.
        """
        poll_interval = 1.0
        start = time.monotonic()
        deadline = start + timeout
        registry_auth = "unknown"
        per_chain: dict[str, str] = {}

        while True:
            per_chain = await self._registry_auth_per_chain()
            registry_auth = _aggregate_registry_auth(per_chain)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if not _per_chain_has_pending(per_chain):
                return {
                    "ready": True,
                    "registry_auth": registry_auth,
                    "auth_per_chain": per_chain,
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
            "auth_per_chain": per_chain,
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
        """Probe the configured negotiation chain. Returns a viability string.

        Runs the chain against a synthetic round-0 input (buyer matching
        seller price exactly, no listing context) and reports whether the
        terminal middleware would accept/counter (viable) or exit (broken
        config). Guard middlewares fire first; their veto produces
        ``exit_on_probe`` with the guard's reason — operator can read the
        reason to see whether the chain is misconfigured for their setup.

        Possible values:
          '<chain> (count=N)'            — chain produced a non-exit decision
          '<chain> (exit_on_probe: <r>)' — chain returned an exit/reject
          'error: <msg>'                 — load or run failed
        """
        try:
            from market_policy.negotiation_middleware import (
                NegotiationContext,
                NegotiationRound,
                run_negotiation_chain,
            )
            from market_storefront.utils.sync_negotiation import _load_storefront_chain

            chain = _load_storefront_chain()
            label = f"chain[{len(chain)}]"
            history = [NegotiationRound(
                round_number=0, sender="them", action="initial",
                proposal={"fields": {"amount": 10_000}},
            )]
            context = NegotiationContext(
                direction="maximize",
                our_reference_amount=10_000.0,
            )
            probe = run_negotiation_chain(chain, history, context)
            if probe.action in ("exit", "reject"):
                return f"{label} (exit_on_probe: {probe.reason})"
            return f"{label} (count={len(chain)})"
        except KeyError as exc:
            return f"unknown: {exc}"
        except Exception as exc:
            return f"error: {exc}"
