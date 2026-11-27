"""System diagnostics routes for the registry service.

  ``GET /health``                   Kubernetes liveness/readiness probe.
                                    Returns 200 (ok) or 503 (degraded).
  ``GET /api/v1/system/stats``      DB population counts (publishers + listings).

``/health`` is the only endpoint that returns 503; ``/stats`` is diagnostic
and always 200.

Two routers are exported::

    make_health_router()   → registers GET /health (no prefix)
    make_system_router()   → registers GET /api/v1/system/*
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from core_registry.api.system_model import (
    HealthResponse,
    OrderStatusCounts,
    StatsResponse,
)
from market_authenticated_requests import Admitted, RouteAdmission
from market_identity import ExactRetry

from core_registry.api.admission import READ_ROLES, registry_core
from core_registry.api.api_key_auth import require_read_access
from core_registry.db.database import get_db
from core_registry.db.models import Publisher, Listing, OrderStatusEnum

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
async def health_check(
    db: Session = Depends(get_db),
):
    """Public lightweight probe; marketplace clients use the signed diagnostic."""
    checks: dict[str, str] = {"api": "ok"}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    all_ok = all(value == "ok" for value in checks.values())
    return JSONResponse(
        content={
            "status": "ok" if all_ok else "degraded",
            "checks": checks,
        },
        status_code=200 if all_ok else 503,
    )


@_system_router.get("/health", response_model=HealthResponse)
async def authenticated_health_check(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(registry_core, operation="health.read", roles=READ_ROLES, exact_retry=ExactRetry.RERUN)
    ),
    db: Session = Depends(get_db),
):
    require_read_access(request, db)
    checks: dict[str, str] = {"api": "ok"}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    all_ok = all(value == "ok" for value in checks.values())
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )


# ---------------------------------------------------------------------------
# /api/v1/system/stats  — DB population counts
# ---------------------------------------------------------------------------


@_system_router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Database population counts",
    description=(
        "Returns publisher count and per-status listing counts. "
        "Intended for quick operator diagnosis and smoke-test assertions "
        "without parsing paginated list responses."
    ),
)
def system_stats(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(registry_core, operation="system.stats.read", roles=READ_ROLES, exact_retry=ExactRetry.RERUN)
    ),
    db: Session = Depends(get_db),
):
    require_read_access(request, db)
    publisher_count: int = db.query(func.count(Publisher.publisher_id)).scalar() or 0

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
        publisher_count=publisher_count,
        order_count=total_orders,
        orders_by_status=OrderStatusCounts(**order_counts),
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Router factories
# ---------------------------------------------------------------------------


def make_health_router() -> APIRouter:
    """Returns the bare ``/health`` router (registered without prefix)."""
    return _health_router


def make_system_router() -> APIRouter:
    """Returns the ``/api/v1/system`` router."""
    return _system_router
