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
from market_storefront.utils.config import (
    CHAINS,
    ESCROW_TEMPLATES,
    settings,
    AGENT_ID,
)

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
            checks["negotiation_strategy"] = self.negotiation_strategy_check()

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
            comma-joined list of configured chain names when at least one chain
            is up — also handled with its own rule.
            """
            if value in ("ok", "unconfigured"):
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
            # Top-level diagnostic facts. Identity is the wallet (eip191),
            # not a per-chain ERC-8004 NFT — a single chain-agnostic value.
            # ``agent_id`` is the identity the storefront presents to the
            # provisioning service (X-Agent-ID); consumers read it here to
            # address jobs the storefront owns. ``identities`` keeps the
            # per-chain breakdown for multi-chain operators.
            wallet = (settings.wallet.address or "").lower() or None
            result["agent_id"] = wallet
            identities: dict[str, dict[str, Any]] = {}
            for name, chain in CHAINS.items():
                identities[name] = {
                    "chain_id": chain.chain_id,
                    "identity": wallet,
                    "scheme": "eip191" if wallet else None,
                }
            result["identities"] = identities
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
            # here; we attach it anyway so private registries that ever
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
                templates=ESCROW_TEMPLATES,
            )
            source = "resources_csv_inline (config)"
        elif csv_path:
            report = await self._db.upsert_resources_from_csv(
                csv_path=csv_path, templates=ESCROW_TEMPLATES,
            )
            source = csv_path
        elif os.path.exists(self._DEFAULT_CSV_PATH):
            report = await self._db.upsert_resources_from_csv(
                csv_path=self._DEFAULT_CSV_PATH, templates=ESCROW_TEMPLATES,
            )
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
                # Minimal structurally-valid opening proposal: the VM
                # opening guard validates the full EscrowProposal shape
                # (chain_name/escrow_address/expiration_unix required).
                # The zero escrow address keeps the shape guard's legacy
                # carve-out applicable, so the probe needs no
                # accepted-escrows context on a listing.
                proposal={
                    "chain_name": "probe",
                    "escrow_address": "0x" + "00" * 20,
                    "fields": {"amount": 10_000},
                    "expiration_unix": 4_102_444_800,  # 2100-01-01
                },
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
