from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Text,
    JSON,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum


Base = declarative_base()


class Publisher(Base):
    """A stable subject that owns listings through principal bindings."""

    __tablename__ = "publishers"

    publisher_id = Column(Integer, primary_key=True, autoincrement=True)
    # Where buyers reach this publisher's storefront to negotiate. Set from
    # the publish payload on first sighting.
    storefront_url = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    identities = relationship(
        "PublisherIdentity", back_populates="publisher", cascade="all, delete-orphan"
    )
    listings = relationship(
        "Listing", back_populates="publisher", cascade="all, delete-orphan"
    )
    rotations = relationship(
        "PublisherIdentityRotation",
        back_populates="publisher",
        cascade="all, delete-orphan",
    )


class PublisherIdentity(Base):
    """A canonical principal binding retained through its full lifecycle."""

    __tablename__ = "identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    publisher_id = Column(
        Integer,
        ForeignKey("publishers.publisher_id", ondelete="CASCADE"),
        nullable=False,
    )
    scheme = Column(String, nullable=False)
    identifier = Column(String, nullable=False)
    status = Column(String, nullable=False, default="primary", server_default="primary")
    active_until = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    publisher = relationship("Publisher", back_populates="identities")

    __table_args__ = (
        Index("ux_identities_scheme_identifier", "scheme", "identifier", unique=True),
        Index("idx_identities_publisher_id", "publisher_id"),
        Index(
            "ux_identities_one_primary_per_publisher",
            "publisher_id",
            unique=True,
            sqlite_where=text("status = 'primary'"),
            postgresql_where=text("status = 'primary'"),
        ),
    )


class PublisherReplayReservation(Base):
    """A durable principal-scoped request reservation and cached outcome."""

    __tablename__ = "publisher_replay_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    principal_scheme = Column(String, nullable=False)
    principal_identifier = Column(String, nullable=False)
    request_id = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    lease_owner = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "principal_scheme",
            "principal_identifier",
            "request_id",
            name="uq_publisher_replay_principal_request",
        ),
        Index("idx_publisher_replay_created_at", "created_at"),
        Index("idx_publisher_replay_lease_expires_at", "lease_expires_at"),
    )


class PublisherIdentityRotation(Base):
    """Idempotent two-proof transition between publisher principals."""

    __tablename__ = "publisher_identity_rotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    publisher_id = Column(
        Integer,
        ForeignKey("publishers.publisher_id", ondelete="CASCADE"),
        nullable=False,
    )
    nonce = Column(String, nullable=False)
    intent_hash = Column(String, nullable=False)
    current_scheme = Column(String, nullable=False)
    current_identifier = Column(String, nullable=False)
    replacement_scheme = Column(String, nullable=False)
    replacement_identifier = Column(String, nullable=False)
    overlap_seconds = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    applied_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    retire_at = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)

    publisher = relationship("Publisher", back_populates="rotations")

    __table_args__ = (
        UniqueConstraint(
            "publisher_id",
            "nonce",
            name="uq_publisher_rotation_nonce",
        ),
        Index("idx_publisher_rotations_publisher_id", "publisher_id"),
    )


class OrderStatusEnum(str, enum.Enum):
    open = "open"
    closed = "closed"
    expired = "expired"


class Listing(Base):
    __tablename__ = "listings"

    listing_id = Column(String, primary_key=True)
    publisher_id = Column(
        Integer,
        ForeignKey("publishers.publisher_id", ondelete="CASCADE"),
        nullable=False,
    )
    offer_resource = Column(
        JSON, nullable=False
    )  # registry-specific shape (e.g. ComputeResource)
    accepted_escrows = Column(
        JSON, nullable=True
    )  # settlement-schema blob; opaque to the indexer
    settlement_options = Column(
        JSON, nullable=True
    )  # mechanism-neutral settlement choices
    demands = Column(
        JSON, nullable=True
    )  # listing-level arbiter demand blob; opaque to the indexer
    # Optional ceiling on lease duration (seconds). NULL = unlimited.
    # Buyers supply the actual duration at negotiation init.
    max_duration_seconds = Column(Integer, nullable=True)
    oracle_address = Column(Text, nullable=True)
    status = Column(
        SQLEnum(OrderStatusEnum, name="liststatusenum"),
        nullable=False,
        default=OrderStatusEnum.open,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    publisher = relationship("Publisher", back_populates="listings")

    __table_args__ = (
        Index("idx_listings_publisher_id", "publisher_id"),
        Index("idx_listings_status", "status"),
        Index("idx_listings_created_at", "created_at"),
    )


class ApiKey(Base):
    """Bearer-token credential for accessing a private registry.

    Operators mint a key via ``POST /admin/api-keys`` (gated by the
    ``REGISTRY_ADMIN_API_KEY`` env var). The raw secret is shown to
    the operator exactly once at creation time; only its sha256 hash
    is stored, so a DB leak does not expose live tokens. Revocation
    sets ``revoked_at`` rather than deleting the row, preserving the
    audit trail.

    ``scope`` is ``read`` or ``write``; a write key implies read. Read
    routes (discovery, lookups) accept any active key; write routes
    (publish / update / delete listings) require a write key. New keys
    default to ``read`` (least privilege).

    Auth gating is opt-in per direction: when
    ``settings.require_read_api_key`` / ``require_write_api_key`` are
    False (the default) that direction is open and the table goes
    unconsulted for it. When set, the matching route dependency requires
    ``Authorization: Bearer <raw-key>`` and verifies via hash lookup.
    """

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)  # human label e.g. "alice-buyer"
    key_hash = Column(String, nullable=False, unique=True)  # sha256(raw_key)
    scope = Column(String, nullable=False, server_default="read")  # "read" | "write"
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_api_keys_revoked_at", "revoked_at"),)
