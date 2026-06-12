"""Tokens-service tables: keys, credit grants, and the consumption log.

The schema is the credit model from
docs/development/design-api-tokens-domain.md: a key carries a balance
(grants − consumption, maintained transactionally as a column for O(1)
consume checks), grants are one-per-deal (``escrow_uid`` UNIQUE makes
issuance idempotent under job retry; NULL for admin adjustments, which
SQLite's UNIQUE treats as distinct), and consumption is an append-only
log with per-key idempotency so middleware batch flushes never
double-count.

Bearer secrets are hashed at rest (`secret_hash`); ``owner_scheme`` /
``owner_id`` is the scheme-tagged ownership claim ("wallet" in v1) that
the negotiation guards consult and issuance re-checks authoritatively.

The site-authority quota ledger tables ride ``core_site``'s own
metadata — ``init_db`` creates both.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApiKey(Base):
    __tablename__ = "api_keys"

    key_id = Column(String, primary_key=True)
    secret_hash = Column(String, nullable=False)
    owner_scheme = Column(String, nullable=True)   # "wallet" | "ed25519" | None (open top-up)
    owner_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")  # active | revoked
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )


class CreditGrant(Base):
    __tablename__ = "credit_grants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String, ForeignKey("api_keys.key_id"), nullable=False, index=True)
    escrow_uid = Column(String, nullable=True, unique=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(String, nullable=False, default="issuance")  # issuance | admin_adjustment
    granted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ConsumptionEvent(Base):
    __tablename__ = "consumption_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String, ForeignKey("api_keys.key_id"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("key_id", "idempotency_key", name="uq_consumption_idem"),
    )
