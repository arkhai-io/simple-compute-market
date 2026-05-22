"""API key issuance, verification, and revocation for private registries.

When ``settings.require_api_key`` is True, every request to a non-
admin / non-health route is gated by ``Authorization: Bearer <key>``
matching a non-revoked row in the ``api_keys`` table. Operators mint
and revoke keys via the ``/admin/api-keys`` routes, which are
themselves gated by the ``REGISTRY_ADMIN_API_KEY`` env var (a single
shared secret distinct from the api_keys table).

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

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.config import settings
from src.db.database import get_db
from src.db.models import ApiKey

logger = logging.getLogger(__name__)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_api_key(db: Session, *, name: str) -> tuple[str, ApiKey]:
    """Generate a fresh secret, store its hash, return both raw value
    and persisted row. The raw value is the operator's only chance to
    capture the key — emit it to the API response and never log it.
    """
    raw = secrets.token_urlsafe(32)  # ~256 bits of entropy
    row = ApiKey(name=name, key_hash=_hash_key(raw), created_at=datetime.now(timezone.utc))
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("[API_KEY] minted key id=%s name=%s", row.id, name)
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


def require_valid_api_key(
    request: Request, db: Session = Depends(get_db),
) -> None:
    """Dependency for non-admin routes. No-op when
    ``settings.require_api_key`` is False (back-compat / public
    registry); otherwise verifies the bearer header against the
    api_keys table."""
    if not settings.require_api_key:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="API key required")
    raw = auth.removeprefix("Bearer ").strip()
    if not raw or verify_api_key(db, raw) is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
