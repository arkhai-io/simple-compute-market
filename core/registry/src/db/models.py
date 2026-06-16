from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Enum as SQLEnum, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum


Base = declarative_base()


class Publisher(Base):
    """A principal that owns listings.

    Identified by one or more :class:`PublisherIdentity` rows — today a
    single ``eip191`` wallet. Created lazily on the first signed publish;
    nothing is registered ahead of time. ``publisher_id`` is local to this
    indexer — correlating a publisher across registries goes through the
    shared ``(scheme, identifier)`` claims, not this surrogate id.
    """
    __tablename__ = "publishers"

    publisher_id = Column(Integer, primary_key=True, autoincrement=True)
    # Where buyers reach this publisher's storefront to negotiate. Set from
    # the publish payload on first sighting.
    storefront_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    identities = relationship("PublisherIdentity", back_populates="publisher", cascade="all, delete-orphan")
    listings = relationship("Listing", back_populates="publisher", cascade="all, delete-orphan")


class PublisherIdentity(Base):
    """A verified signing identity belonging to a publisher.

    ``(scheme, identifier)`` is globally unique; ``eip191`` identifiers are
    lowercased wallet addresses. One row per publisher today; the seam for
    linking additional identities (other chains/schemes) later.
    """
    __tablename__ = "identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    publisher_id = Column(Integer, ForeignKey("publishers.publisher_id", ondelete="CASCADE"), nullable=False)
    scheme = Column(String, nullable=False)
    identifier = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    publisher = relationship("Publisher", back_populates="identities")

    __table_args__ = (
        Index("ux_identities_scheme_identifier", "scheme", "identifier", unique=True),
        Index("idx_identities_publisher_id", "publisher_id"),
    )


class OrderStatusEnum(str, enum.Enum):
    open = "open"
    closed = "closed"
    expired = "expired"


class Listing(Base):
    __tablename__ = "listings"

    listing_id = Column(String, primary_key=True)
    publisher_id = Column(Integer, ForeignKey("publishers.publisher_id", ondelete="CASCADE"), nullable=False)
    offer_resource = Column(JSON, nullable=False)  # registry-specific shape (e.g. ComputeResource)
    accepted_escrows = Column(JSON, nullable=True)  # settlement-schema blob; opaque to the indexer
    demands = Column(JSON, nullable=True)  # listing-level arbiter demand blob; opaque to the indexer
    # Optional ceiling on lease duration (seconds). NULL = unlimited.
    # Buyers supply the actual duration at negotiation init.
    max_duration_seconds = Column(Integer, nullable=True)
    oracle_address = Column(Text, nullable=True)
    status = Column(SQLEnum(OrderStatusEnum, name="liststatusenum"), nullable=False, default=OrderStatusEnum.open)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_api_keys_revoked_at", "revoked_at"),
    )
