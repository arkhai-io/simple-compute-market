"""System diagnostics routes for the registry service.

Exposes four endpoint groups:

  ``GET /health``                   Kubernetes liveness/readiness probe.
                                    Returns 200 (ok) or 503 (degraded) — never
                                    masks failures with a 200 that lies to k8s.
  ``GET /api/v1/system/config``     Active chain and contract configuration.
  ``GET /api/v1/system/sync``       Background service liveness (event sync,
                                    health check service).
  ``GET /api/v1/system/stats``      DB population counts by entity type and
                                    order status.

All ``/api/v1/system/*`` endpoints return 200 regardless of the values they
report — they are diagnostic, not probes.  Only ``/health`` uses 503.

Registration in ``routes.py``
------------------------------
Two routers are exported::

    make_health_router()   → registers GET /health (no prefix)
    make_system_router()   → registers GET /api/v1/system/*
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.api.system_model import (
    AgentIndexedResponse,
    AttestationStatsResponse,
    ConfigResponse,
    EventSyncStatus,
    HealthCheckServiceStatus,
    HealthChecks,
    HealthResponse,
    OrderStatusCounts,
    StatsResponse,
    SyncResponse,
)
from src.config import settings
from src.db.database import get_db
from src.db.models import Agent, Listing, OrderStatusEnum
_health_router = APIRouter(tags=["system"])
_system_router = APIRouter(prefix="/api/v1/system", tags=["system"])


# ---------------------------------------------------------------------------
# /health  — liveness / readiness probe
# ---------------------------------------------------------------------------


@_health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check (liveness/readiness probe)",
    description=(
        "Checks API reachability and database connectivity via SELECT 1. "
        "Returns HTTP 200 with status='ok' when all checks pass, "
        "HTTP 503 with status='degraded' on any failure."
    ),
)
async def health_check(db: Session = Depends(get_db)) -> JSONResponse:
    checks: dict[str, str] = {"api": "ok"}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    payload = {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
    return JSONResponse(content=payload, status_code=200 if all_ok else 503)


# ---------------------------------------------------------------------------
# /api/v1/system/config  — active chain and contract configuration
# ---------------------------------------------------------------------------


@_system_router.get(
    "/config",
    response_model=ConfigResponse,
    summary="Active chain and contract configuration",
    description=(
        "Returns the chain ID, RPC URL, and contract addresses currently "
        "loaded from environment variables. Useful for confirming that a "
        "deployment is pointed at the correct chain without inspecting pod "
        "env vars directly."
    ),
)
def system_config() -> ConfigResponse:
    return ConfigResponse(
        chain_id=settings.chain_id,
        rpc_url=settings.rpc_url,
        identity_registry_address=settings.identity_registry_address,
        reputation_registry_address=settings.reputation_registry_address,
        validation_registry_address=settings.validation_registry_address,
        enable_health_checks=settings.enable_health_checks,
        heartbeat_ttl_secs=settings.heartbeat_ttl_secs,
    )


# ---------------------------------------------------------------------------
# /api/v1/system/sync  — background service liveness
# ---------------------------------------------------------------------------


@_system_router.get(
    "/sync",
    response_model=SyncResponse,
    summary="Background service liveness",
    description=(
        "Reports whether the event sync and health check background services "
        "started during application lifespan are still running. "
        "A stopped event_sync means on-chain agent registration events are "
        "no longer being indexed."
    ),
)
def system_sync() -> SyncResponse:
    # Import here to avoid a circular import at module load time — main.py
    # imports from src.api.routes which imports this module.
    import src.main as _main

    event_sync = _main.event_sync
    health_check_svc = _main.health_check

    return SyncResponse(
        event_sync=EventSyncStatus(
            running=event_sync.is_running if event_sync is not None else False,
            last_synced_block=(
                event_sync.last_synced_block if event_sync is not None else 0
            ),
        ),
        health_check=HealthCheckServiceStatus(
            running=(
                health_check_svc.is_running if health_check_svc is not None else False
            ),
            enabled=settings.enable_health_checks,
        ),
    )


# ---------------------------------------------------------------------------
# /api/v1/system/sync/wait-for-agent  — long-poll until agent is indexed
# ---------------------------------------------------------------------------


@_system_router.get(
    "/sync/wait-for-agent",
    response_model=AgentIndexedResponse,
    summary="Long-poll until an agent is indexed (test/admin helper)",
    description=(
        "Blocks (server-side) until the specified canonical agent ID appears "
        "in the registry DB, or until *timeout* seconds elapse.  Returns "
        "``indexed=True`` as soon as the row exists; ``indexed=False`` on "
        "timeout.  Intended for e2e test suites that need to wait for the "
        "EventSync background service to index a freshly registered agent "
        "before proceeding with heartbeat and listing-publish calls.  "
        "Poll interval is 500 ms — callers should set timeout >= 60 s to "
        "cover a normal sync cycle."
    ),
)
async def wait_for_agent_indexed(
    agent_id: str,
    timeout: float = 60.0,
    db: Session = Depends(get_db),
) -> AgentIndexedResponse:
    import asyncio
    import time as _time

    if timeout > 120.0:
        timeout = 120.0  # hard cap — protect the server from indefinite holds

    poll_interval = 0.5
    start = _time.monotonic()
    deadline = start + timeout

    while True:
        db.expire_all()
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
        if agent is not None:
            elapsed_ms = int((_time.monotonic() - start) * 1000)
            return AgentIndexedResponse(
                indexed=True,
                agent_id=agent_id,
                elapsed_ms=elapsed_ms,
            )
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(poll_interval, remaining))

    elapsed_ms = int((_time.monotonic() - start) * 1000)
    return AgentIndexedResponse(indexed=False, agent_id=agent_id, elapsed_ms=elapsed_ms)


# ---------------------------------------------------------------------------
# /api/v1/system/stats  — DB population counts
# ---------------------------------------------------------------------------


@_system_router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Database population counts",
    description=(
        "Returns agent count and per-status order counts. "
        "Intended for quick operator diagnosis and smoke-test assertions "
        "without needing to parse paginated list responses."
    ),
)
def system_stats(db: Session = Depends(get_db)) -> StatsResponse:
    agent_count: int = db.query(func.count(Agent.id)).scalar() or 0

    order_counts: dict[str, int] = {s.value: 0 for s in OrderStatusEnum}
    rows = (
        db.query(Listing.status, func.count(Listing.listing_id))
        .group_by(Listing.status)
        .all()
    )
    for status, count in rows:
        order_counts[status.value if hasattr(status, "value") else status] = count

    total_orders = sum(order_counts.values())

    return StatsResponse(
        agent_count=agent_count,
        order_count=total_orders,
        orders_by_status=OrderStatusCounts(**order_counts),
    )


# ---------------------------------------------------------------------------
# /api/v1/system/stats/attestations  — settlement activity counts
# ---------------------------------------------------------------------------


@_system_router.get(
    "/stats/attestations",
    response_model=AttestationStatsResponse,
    summary="Settlement activity counts",
    description=(
        "Returns counts of listings with Alkahest attestation UIDs written back "
        "by agents after on-chain settlement. A non-zero settled_listing_count "
        "confirms that at least one full deal cycle has completed: escrow locked "
        "by the buyer (buyer_attestation) and compute obligation fulfilled by the "
        "seller (seller_attestation). Intended as a smoke-test signal that the "
        "market is functioning end-to-end, not just deployed."
    ),
)
def attestation_stats(db: Session = Depends(get_db)) -> AttestationStatsResponse:
    seller_count: int = (
        db.query(func.count(Listing.listing_id))
        .filter(Listing.seller_attestation.isnot(None))
        .scalar()
        or 0
    )
    buyer_count: int = (
        db.query(func.count(Listing.listing_id))
        .filter(Listing.buyer_attestation.isnot(None))
        .scalar()
        or 0
    )
    settled_count: int = (
        db.query(func.count(Listing.listing_id))
        .filter(
            Listing.seller_attestation.isnot(None),
            Listing.buyer_attestation.isnot(None),
        )
        .scalar()
        or 0
    )
    return AttestationStatsResponse(
        settled_listing_count=settled_count,
        seller_attestation_count=seller_count,
        buyer_attestation_count=buyer_count,
    )


# ---------------------------------------------------------------------------
# Router factories
# ---------------------------------------------------------------------------


def make_health_router() -> APIRouter:
    """Returns the bare ``/health`` router (registered without prefix)."""
    return _health_router


def make_system_router() -> APIRouter:
    """Returns the ``/api/v1/system`` router."""
    return _system_router
