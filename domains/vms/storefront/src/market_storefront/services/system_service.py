"""SystemService — business logic for storefront health and connectivity checks.

Extracted from SystemController so that the logic is independently testable
without an HTTP request/response cycle.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import httpx
from compute_provisioning_contracts import COMPUTE_PROVISIONING_CONTRACT_VERSION
from market_capacity_publication import SiteProjectionState
from market_identity import Signer
from market_policy.listing_source import ListingSourceVerdict

import market_storefront.container as _container
from market_storefront import lifecycle
from market_storefront.services.capacity_client import site_projection_status
from market_storefront.services.listing_cardinality_explanations import (
    listing_cardinality_mode_explanations,
)
from market_storefront.services.listing_identity_carryover import carryover_report
from market_storefront.negotiation_runtime import load_storefront_chain
from market_storefront.utils.config import (
    AGENT_ID,
    CHAINS,
    get_evm_wallet_address,
    settings,
)

logger = logging.getLogger(__name__)

# The negotiation-strategy probe's synthetic listing: placeholder values that
# name no real contract or party. The shape guard refuses an escrow naming no
# contract, one its listing does not accept, and a condition its listing does
# not advertise, so the probe's opening names this listing's escrow and
# condition.
_PROBE_ESCROW = {"chain_name": "probe", "escrow_address": "0x" + "11" * 20}
_PROBE_CONDITION = {
    "chain_name": "probe",
    "arbiter": "0x" + "22" * 20,
    "demand_data": {"recipient": "0x" + "33" * 20},
}
_PROBE_LISTING = {"accepted_escrows": [_PROBE_ESCROW], "demands": [_PROBE_CONDITION]}


def _default_publication_derivation_provider() -> dict[str, dict[str, Any]]:
    """Each site's holds, refusals, and reports from the latest publication
    cycle that derived it, from the process's site-derivation log; empty
    before any cycle has run."""
    log = _container.resolved_site_derivation_log
    return log.latest() if log is not None else {}


async def _default_pool_override_status_provider() -> list[dict[str, Any]] | None:
    """Every stored storefront pool override and the one state it is in, or
    ``None`` when no override service is composed."""
    service = _container.resolved_pool_override_service
    if service is None:
        return None
    return await service.statuses()


def _default_lifecycle_provider() -> dict[str, dict[str, Any]]:
    """Every lifecycle loop's controller state and the outcome of its last
    cycle, by loop name, from the process's one loop controller."""
    return {name: loop.to_dict() for name, loop in lifecycle.snapshot().items()}


async def _default_settlement_provider() -> list[dict[str, Any]] | None:
    """Each composed mechanism's readiness, as its registration projects it.

    Readiness reads the Alkahest chain probe's last results and calls no chain,
    so a status read never waits on one. Status names nothing being published,
    so Alkahest's readiness answers for every configured chain.
    """
    composition = _container.resolved_settlement_composition
    if composition is None:
        return None
    return [status.safe_projection() for status in await composition.readiness()]


def _default_listing_identity_carryover_provider() -> dict[str, Any]:
    """Which pre-shape listings carried a seller's close or pause, and to which
    shape-bearing successor: the listing a seller should reopen or resume."""
    return carryover_report()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SystemService:
    """Business logic for storefront health and connectivity checks."""

    def __init__(
        self,
        *,
        sqlite_client,
        marketplace_signer: Signer,
        site_projections: SiteProjectionState,
        agent_id: str | None = None,
        projection_status_provider: Callable[[], dict[str, Any]] | None = None,
        listing_cardinality_mode_explanation_provider: (
            Callable[[], dict[str, dict[str, str]]] | None
        ) = None,
        publication_derivation_provider: (
            Callable[[], dict[str, dict[str, Any]]] | None
        ) = None,
        listing_identity_carryover_provider: Callable[[], dict[str, Any]] | None = None,
        pool_override_status_provider: (
            Callable[[], Awaitable[list[dict[str, Any]] | None]] | None
        ) = None,
        lifecycle_provider: Callable[[], dict[str, dict[str, Any]]] | None = None,
        settlement_provider: (
            Callable[[], Awaitable[list[dict[str, Any]] | None]] | None
        ) = None,
        registry_probe_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._db = sqlite_client
        # The transport the registry health probes are sent over; the network's
        # unless a caller answers them itself.
        self._registry_probe_transport = registry_probe_transport
        self._marketplace_signer = marketplace_signer
        self._agent_id = agent_id or AGENT_ID or "agent"
        # Both read the storefront's one projection state unless a caller
        # supplies its own report.
        self._projection_status_provider = projection_status_provider or partial(
            site_projection_status, site_projections
        )
        self._listing_cardinality_mode_explanation_provider = (
            listing_cardinality_mode_explanation_provider
            or partial(listing_cardinality_mode_explanations, site_projections)
        )
        self._publication_derivation_provider = (
            publication_derivation_provider or _default_publication_derivation_provider
        )
        self._listing_identity_carryover_provider = (
            listing_identity_carryover_provider
            or _default_listing_identity_carryover_provider
        )
        self._pool_override_status_provider = (
            pool_override_status_provider or _default_pool_override_status_provider
        )
        self._lifecycle_provider = lifecycle_provider or _default_lifecycle_provider
        self._settlement_provider = settlement_provider or _default_settlement_provider

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
        # Public on both routes: a buyer reads these before handing over any
        # data, so they cannot wait for an authenticated status call.
        contact_exchange = _container.resolved_contact_exchange
        disclosures = (
            contact_exchange.disclosures() if contact_exchange is not None else {}
        )
        if disclosures:
            result["disclosures"] = disclosures

        if include_registry:
            principal = self._marketplace_signer.identity
            result["agent_id"] = self._agent_id
            result["marketplace_principal"] = principal.model_dump(mode="json")
            result["storefront_domains"] = tuple(
                {
                    "contribution_id": item.contribution_id,
                    "offering_mode": item.offering_mode,
                    "domain_identity": item.domain_identity,
                    "contract_version": item.contract_version,
                }
                for item in self._db.domain_registry.projection()
            )
            # The provisioning contract major this storefront *speaks*, taken
            # from its own installed `compute_provisioning` wheel rather than
            # from anything the peer reports. Two deployments can disagree
            # only if their wheels differ, which is exactly the skew a
            # cutover has to rule out before mutations resume -- and until
            # both sides reported this there was no way to check it against a
            # live fleet.
            #
            # Distinct from `storefront_domains[].contract_version` above,
            # which is a domain contribution's own version and a different
            # axis entirely.
            result["provisioning_contract_version"] = (
                COMPUTE_PROVISIONING_CONTRACT_VERSION
            )
            wallet = get_evm_wallet_address().lower() if CHAINS else ""
            result["evm_mechanisms"] = {
                name: {
                    "chain_id": chain.chain_id,
                    "address": wallet or None,
                }
                for name, chain in CHAINS.items()
            }
            try:
                result["site_projections"] = self._projection_status_provider()
            except Exception:
                result["site_projections"] = None
            try:
                result["listing_cardinality_mode_explanations"] = (
                    self._listing_cardinality_mode_explanation_provider()
                )
            except Exception:
                result["listing_cardinality_mode_explanations"] = None
            try:
                result["publication_derivation"] = (
                    self._publication_derivation_provider()
                )
            except Exception:
                result["publication_derivation"] = None
            try:
                result["listing_identity_carryover"] = (
                    self._listing_identity_carryover_provider()
                )
            except Exception:
                result["listing_identity_carryover"] = None
            try:
                result["pool_overrides"] = await self._pool_override_status_provider()
            except Exception:
                result["pool_overrides"] = None
            try:
                result["lifecycle"] = self._lifecycle_provider()
            except Exception:
                result["lifecycle"] = None
            try:
                result["settlement"] = await self._settlement_provider()
            except Exception:
                result["settlement"] = None

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
                async with httpx.AsyncClient(
                    timeout=2.0, transport=self._registry_probe_transport
                ) as client:
                    resp = await client.get(f"{url}/health", headers=headers)
                return "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
            except httpx.ConnectError:
                return "unreachable"
            except httpx.TimeoutException:
                return "timeout"
            except Exception as exc:
                return f"error: {exc}"

        results = await asyncio.gather(*[_probe(u) for u in urls])
        if any(r == "ok" for r in results):
            return "ok"
        # Surface the most recent non-ok result (all are non-ok here).
        return results[-1]

    def negotiation_strategy_check(self) -> str:
        """Probe the configured negotiation chain. Returns a viability string.

        Runs the chain against a synthetic round-0 input (buyer matching
        seller price exactly, on a synthetic listing accepting the probe's
        escrow and condition) and reports whether the
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

            chain = load_storefront_chain()
            label = f"chain[{len(chain)}]"
            history = [
                NegotiationRound(
                    round_number=0,
                    sender="them",
                    action="initial",
                    # Minimal structurally-valid opening proposal: the VM
                    # opening guard validates the full EscrowProposal shape
                    # (chain_name/escrow_address/expiration_unix required).
                    proposal={
                        **_PROBE_ESCROW,
                        "fields": {"amount": 10_000},
                        "demand": _PROBE_CONDITION,
                        "expiration_unix": 4_102_444_800,  # 2100-01-01
                    },
                )
            ]
            context = NegotiationContext(
                direction="maximize",
                our_reference_amount=10_000,
                listing=_PROBE_LISTING,
                # The probe exercises the strategy, not a listing: no source is
                # checked, so the inventory guard is given a matching verdict.
                listing_source=ListingSourceVerdict("matches"),
            )
            probe = run_negotiation_chain(chain, history, context)
            if probe.action in ("exit", "reject"):
                return f"{label} (exit_on_probe: {probe.reason})"
            return f"{label} (count={len(chain)})"
        except KeyError as exc:
            return f"unknown: {exc}"
        except Exception as exc:
            return f"error: {exc}"
