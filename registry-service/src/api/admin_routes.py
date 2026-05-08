"""Admin endpoints for issuing and revoking API keys.

Every endpoint here is gated by ``require_admin_api_key`` — operators
authenticate with the single shared ``REGISTRY_ADMIN_API_KEY`` env
var rather than a key from the ``api_keys`` table. This keeps the
mint-flow bootstrappable: there is no chicken-and-egg with key #1.

Issuance returns the raw secret exactly once at creation time. The
DB only stores the sha256 hash; the registry cannot recover the raw
value if the operator loses it. Lost key → revoke + mint a fresh one.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.api_key_auth import (
    mint_api_key, revoke_api_key, require_admin_api_key,
)
from src.db.database import get_db
from src.db.models import ApiKey

router = APIRouter(
    prefix="/admin/api-keys",
    tags=["admin"],
    dependencies=[Depends(require_admin_api_key)],
)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable label")


class CreateApiKeyResponse(BaseModel):
    id: int
    name: str
    key: str = Field(..., description="Raw bearer token — store this now; the registry retains only its hash")
    created_at: str


class ApiKeyListItem(BaseModel):
    id: int
    name: str
    created_at: str
    revoked_at: Optional[str] = None


@router.post("", response_model=CreateApiKeyResponse, status_code=201)
def create_api_key(
    body: CreateApiKeyRequest, db: Session = Depends(get_db),
) -> CreateApiKeyResponse:
    """Mint a new key. The response includes the raw token; the
    operator must capture it now — the registry never returns it
    again."""
    raw, row = mint_api_key(db, name=body.name.strip())
    return CreateApiKeyResponse(
        id=row.id, name=row.name, key=raw,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=List[ApiKeyListItem])
def list_api_keys(db: Session = Depends(get_db)) -> List[ApiKeyListItem]:
    """List every key (including revoked) for audit. Raw values are
    not stored and therefore not returned."""
    rows = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [
        ApiKeyListItem(
            id=r.id, name=r.name,
            created_at=r.created_at.isoformat(),
            revoked_at=r.revoked_at.isoformat() if r.revoked_at else None,
        )
        for r in rows
    ]


@router.delete("/{key_id}", status_code=204)
def revoke(key_id: int, db: Session = Depends(get_db)) -> None:
    """Mark a key revoked. Idempotent on already-revoked keys; 404
    when the id is unknown."""
    if not revoke_api_key(db, key_id=key_id):
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
