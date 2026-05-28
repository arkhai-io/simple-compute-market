"""API key issuance, verification, and revocation for private registries.

Access is gated independently per direction. When
``settings.require_read_api_key`` is True, read routes (discovery,
lookups, system diagnostics) require ``Authorization: Bearer <key>``
matching a non-revoked row. When ``settings.require_write_api_key`` is
True, write routes (publish / update / delete listings, heartbeat)
require such a key carrying ``write`` scope. A write key satisfies read
routes too. Operators mint and revoke keys via the ``/admin/api-keys``
routes, themselves gated by the ``REGISTRY_ADMIN_API_KEY`` env var (a
single shared secret distinct from the api_keys table).

Storage model: only ``sha256(raw_key)`` is persisted; the raw key is
returned to the operator exactly once at mint time. A DB leak
exposes hashes, not live credentials. Revocation sets ``revoked_at``
rather than deleting the row, preserving audit history.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.config import settings
from src.db.database import get_db
from src.db.models import ApiKey

logger = logging.getLogger(__name__)

Scope = Literal["read", "write"]


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_api_key(db: Session, *, name: str, scope: Scope = "read") -> tuple[str, ApiKey]:
    """Generate a fresh secret, store its hash, return both raw value
    and persisted row. The raw value is the operator's only chance to
    capture the key — emit it to the API response and never log it.

    ``scope`` defaults to ``read`` (least privilege); pass ``write`` for
    seller credentials that publish/update/delete listings.
    """
    raw = secrets.token_urlsafe(32)  # ~256 bits of entropy
    row = ApiKey(
        name=name,
        key_hash=_hash_key(raw),
        scope=scope,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("[API_KEY] minted key id=%s name=%s scope=%s", row.id, name, scope)
    return raw, row


def revoke_api_key(db: Session, *, key_id: int) -> bool:
    """Mark a key revoked. Idempotent — already-revoked keys are
    left unchanged. Returns True iff the key existed."""
    row = db.query(ApiKey).filter(ApiKey.id == key_id).one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("[API_KEY] revoked key id=%s name=%s", row.id, row.name)
    return True


def verify_api_key(db: Session, raw: str) -> ApiKey | None:
    """Look up a key by its hash. Returns the row when active and
    not revoked, ``None`` otherwise. Constant-time hash comparison
    is provided implicitly by indexing the unique hash column."""
    row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == _hash_key(raw))
        .filter(ApiKey.revoked_at.is_(None))
        .one_or_none()
    )
    return row


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_admin_api_key(request: Request) -> None:
    """Dependency for /admin/* routes. 401s when ``REGISTRY_ADMIN_API_KEY``
    isn't set on the server, OR when the request's
    ``Authorization: Bearer <key>`` doesn't match it.

    The admin key is a single shared secret deliberately — operators
    are expected to store it out-of-band (env var, secret manager).
    No DB row, no minting flow.
    """
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=401,
            detail="Admin endpoints disabled — REGISTRY_ADMIN_API_KEY not set",
        )
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin bearer token required")
    candidate = auth.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(candidate, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _verify_bearer(request: Request, db: Session) -> ApiKey:
    """Pull ``Authorization: Bearer <key>`` and resolve it to an active
    row, or 401. Shared by the read and write gates."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="API key required")
    raw = auth.removeprefix("Bearer ").strip()
    row = verify_api_key(db, raw) if raw else None
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return row


def require_read_access(
    request: Request, db: Session = Depends(get_db),
) -> None:
    """Dependency for read routes. No-op when
    ``settings.require_read_api_key`` is False (public discovery);
    otherwise any active key (read or write scope) is accepted."""
    if not settings.require_read_api_key:
        return
    _verify_bearer(request, db)


def require_write_access(
    request: Request, db: Session = Depends(get_db),
) -> None:
    """Dependency for write routes. No-op when
    ``settings.require_write_api_key`` is False (open publishing);
    otherwise requires an active key carrying ``write`` scope. Note the
    per-write signature checks still apply on top of this gate."""
    if not settings.require_write_api_key:
        return
    row = _verify_bearer(request, db)
    if row.scope != "write":
        raise HTTPException(
            status_code=403, detail="Write access requires a write-scoped API key"
        )
