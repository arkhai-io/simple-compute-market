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

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.api.system_model import (
    HealthResponse,
    OrderStatusCounts,
    StatsResponse,
)
from src.db.database import get_db
from src.db.models import Publisher, Listing, OrderStatusEnum

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
def system_stats(db: Session = Depends(get_db)) -> StatsResponse:
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
