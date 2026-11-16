"""Admin endpoints: API keys, the registry's status, and its time.

Every endpoint here is gated by ``require_admin_api_key`` — operators
authenticate with the single shared ``REGISTRY_ADMIN_API_KEY`` env
var rather than a key from the ``api_keys`` table. This keeps the
mint-flow bootstrappable: there is no chicken-and-egg with key #1.

Issuance returns the raw secret exactly once at creation time. The
DB only stores the sha256 hash; the registry cannot recover the raw
value if the operator loses it. Lost key → revoke + mint a fresh one.
"""
from __future__ import annotations

from typing import List, Literal, Optional

import injected_time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from injected_time import TimeRouteError, TimeRouteService
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core_registry.api.api_key_auth import (
    mint_api_key, revoke_api_key, require_admin_api_key,
)
from core_registry.db.database import get_db
from core_registry.db.models import ApiKey

router = APIRouter(
    prefix="/admin/api-keys",
    tags=["admin"],
    dependencies=[Depends(require_admin_api_key)],
)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable label")
    scope: Literal["read", "write"] = Field(
        "read",
        description="'read' (discovery/lookups) or 'write' (publish/update/delete + heartbeat). Write implies read. Defaults to read (least privilege).",
    )


class CreateApiKeyResponse(BaseModel):
    id: int
    name: str
    scope: str
    key: str = Field(..., description="Raw bearer token — store this now; the registry retains only its hash")
    created_at: str


class ApiKeyListItem(BaseModel):
    id: int
    name: str
    scope: str
    created_at: str
    revoked_at: Optional[str] = None


@router.post("", response_model=CreateApiKeyResponse, status_code=201)
def create_api_key(
    body: CreateApiKeyRequest, db: Session = Depends(get_db),
) -> CreateApiKeyResponse:
    """Mint a new key. The response includes the raw token; the
    operator must capture it now — the registry never returns it
    again."""
    raw, row = mint_api_key(db, name=body.name.strip(), scope=body.scope)
    return CreateApiKeyResponse(
        id=row.id, name=row.name, scope=row.scope, key=raw,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=List[ApiKeyListItem])
def list_api_keys(db: Session = Depends(get_db)) -> List[ApiKeyListItem]:
    """List every key (including revoked) for audit. Raw values are
    not stored and therefore not returned."""
    # Whole-second times tie; the key id is insertion order.
    rows = db.query(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).all()
    return [
        ApiKeyListItem(
            id=r.id, name=r.name, scope=r.scope,
            created_at=r.created_at.isoformat(),
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
        )
        for r in rows
    ]


@router.delete("/{key_id}", status_code=204, response_model=None)
def revoke(key_id: int, db: Session = Depends(get_db)) -> None:
    """Mark a key revoked. Idempotent on already-revoked keys; 404
    when the id is unknown."""
    if not revoke_api_key(db, key_id=key_id):
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")


class AdminStatusResponse(BaseModel):
    """``GET /admin/status``: the registry's time source, ``{"source": "wall"}``
    or ``{"source": "injected", "now": <Unix seconds>}``."""

    time: dict[str, object]


class TimeSettingResponse(BaseModel):
    """``POST /admin/time``: the instant an injected registry is set to."""

    source: Literal["injected"]
    now: int


status_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_api_key)],
)


@status_router.get("/status", response_model=AdminStatusResponse)
def admin_status() -> AdminStatusResponse:
    """The registry's time source, in either mode."""
    return AdminStatusResponse(
        time=TimeRouteService(injected_time.installed()).status()
    )


def make_time_router() -> APIRouter:
    """The ``POST /admin/time`` router, which the registry mounts only while its
    source is injected, so a wall-time registry serves no such route.

    Behind the administrator bearer key, as every ``/admin`` route is, and
    answered unsigned as they are: a bearer request carries no timestamp, so no
    freshness stands between a lane's advance and this route. A body other than
    ``{"now": <Unix seconds>}`` is 422 ``invalid_time``, an earlier instant 409
    ``time_moves_forward``, and neither changes anything. Should the router be
    mounted over a source that cannot be set, it answers 404.
    """
    time_router = APIRouter(
        prefix="/admin",
        tags=["admin"],
        dependencies=[Depends(require_admin_api_key)],
    )

    @time_router.post("/time", response_model=TimeSettingResponse)
    async def set_time(request: Request) -> JSONResponse:
        routes = TimeRouteService(injected_time.installed())
        if not routes.settable:
            raise HTTPException(status_code=404, detail="Not Found")
        try:
            answer = routes.set_time(await request.body())
        except TimeRouteError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={"code": error.code, "detail": error.detail},
            )
        return JSONResponse(content=answer)

    return time_router
