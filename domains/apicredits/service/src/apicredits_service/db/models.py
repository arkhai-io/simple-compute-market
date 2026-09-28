"""Credits authority persistence for keys, immutable grants, and consumption.

Bearer secrets are hashed on key rows. Issuance grants snapshot every
mutation-relevant public input under a unique fulfillment identity and digest;
operator adjustments remain distinguishable by a null fulfillment identity.
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
    owner_scheme = Column(String, nullable=True)  # "eip191" | "ed25519" | None
    owner_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")  # active | revoked
    balance = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class CreditGrant(Base):
    __tablename__ = "credit_grants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_id = Column(String, ForeignKey("api_keys.key_id"), nullable=False, index=True)
    fulfillment_id = Column(String, nullable=True, unique=True)
    obligation_ref = Column(String, nullable=True)
    mechanism = Column(String, nullable=True)
    service = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    key_mode = Column(String, nullable=True)
    key_target_id = Column(String, nullable=True)
    owner_scheme = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    request_digest = Column(String, nullable=True)
    capacity_reservation_id = Column(String, nullable=True)
    result_balance = Column(Integer, nullable=True)
    escrow_uid = Column(String, nullable=True, unique=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(
        String, nullable=False, default="issuance"
    )  # issuance | admin_adjustment
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
