"""The authority's persistence for keys, immutable grants, and consumption.

Bearer secrets are hashed on key rows. Issuance grants snapshot every
mutation-relevant public input under a unique fulfillment identity and digest;
operator adjustments remain distinguishable by a null fulfillment identity. A
grant issued with accepted terms has one ``grant_terms`` row beside it, so the
grant table's columns stay those every authority image checks.
"""

from __future__ import annotations

import injected_time
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Every time here is stamped by the application from the process's time source
# (``injected_time.now_datetime``), never by the database's clock.
_utcnow = injected_time.now_datetime


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
    negotiation_id = Column(String, nullable=True, unique=True)
    service = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    key_mode = Column(String, nullable=True)
    key_target_id = Column(String, nullable=True)
    owner_scheme = Column(String, nullable=True)
    owner_id = Column(String, nullable=True)
    request_digest = Column(String, nullable=True)
    capacity_reservation_id = Column(String, nullable=True)
    result_balance = Column(Integer, nullable=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(
        String, nullable=False, default="issuance"
    )  # issuance | admin_adjustment
    granted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class GrantTerms(Base):
    """The accepted terms a grant was issued under; a key pins its first grant's row."""

    __tablename__ = "grant_terms"

    grant_id = Column(Integer, ForeignKey("credit_grants.id"), primary_key=True)
    accepted_terms = Column(Text, nullable=False)
    terms_digest = Column(String, nullable=False)
    request_charge = Column(Integer, nullable=False)


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
