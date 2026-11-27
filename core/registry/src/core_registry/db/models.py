from datetime import datetime

import injected_time
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    Text,
    JSON,
    Enum as SQLEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum


Base = declarative_base()


def utcnow() -> datetime:
    """The process time source's instant as the model defaults and the stored
    deadlines take it: UTC with no zone. Stored times are compared later — a
    replay lease's expiry, a rotation's overlap deadline — and listings are
    ordered by them. An API key's times are written aware by its store."""
    return injected_time.now_datetime().replace(tzinfo=None)


class Publisher(Base):
    """A stable subject that owns listings through principal bindings."""

    __tablename__ = "publishers"

    publisher_id = Column(Integer, primary_key=True, autoincrement=True)
    # Where buyers reach this publisher's storefront to negotiate. Set from
    # the publish payload on first sighting.
    storefront_url = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
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
        DateTime(timezone=True), nullable=False, default=utcnow
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
        DateTime(timezone=True), nullable=False, default=utcnow
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


class RfqReplayReservation(Base):
    """An account-scoped request binding with at most a mutation receipt."""

    __tablename__ = "rfq_replay_reservations"

    namespace = Column(String(128), primary_key=True)
    subject = Column(String(255), primary_key=True)
    request_id = Column(String(128), primary_key=True)
    key_id = Column(String(128), nullable=False)
    input_digest = Column(String(64), nullable=False)
    receipt = Column(JSON(none_as_null=True), nullable=True)


class RfqRequest(Base):
    """The buyer's current request and optimistic write version."""

    __tablename__ = "rfq_requests"

    rfq_id = Column(String(128), primary_key=True)
    kind = Column(String(128), nullable=False)
    buyer_namespace = Column(String(128), nullable=False)
    buyer_subject = Column(String(255), nullable=False)
    requirements = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False)
    terms_revision = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)
    respond_by = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_rfq_requests_discovery", "kind", "closed_at", "created_at", "rfq_id"),
    )


class RfqTermsRevision(Base):
    """Original requirements for a consent-bearing terms revision."""

    __tablename__ = "rfq_terms_revisions"

    rfq_id = Column(
        String(128), ForeignKey("rfq_requests.rfq_id", ondelete="CASCADE"), primary_key=True,
    )
    revision = Column(Integer, primary_key=True)
    requirements = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


class RfqPartyReference(Base):
    """A stable, opaque reference visible only in the projections of one RFQ."""

    __tablename__ = "rfq_party_references"

    rfq_id = Column(
        String(128), ForeignKey("rfq_requests.rfq_id", ondelete="CASCADE"), primary_key=True,
    )
    namespace = Column(String(128), primary_key=True)
    subject = Column(String(255), primary_key=True)
    reference = Column(String(128), nullable=False)

    __table_args__ = (UniqueConstraint("rfq_id", "reference", name="uq_rfq_party_reference"),)


class RfqResponse(Base):
    """One respondent's versioned consent for an RFQ terms revision."""

    __tablename__ = "rfq_responses"

    response_id = Column(String(128), primary_key=True)
    rfq_id = Column(String(128), nullable=False)
    respondent_namespace = Column(String(128), nullable=False)
    respondent_subject = Column(String(255), nullable=False)
    terms_revision = Column(Integer, nullable=False)
    offered_quantity = Column(JSON(none_as_null=True), nullable=True)
    state = Column(String(16), nullable=False)
    version = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ("rfq_id", "terms_revision"),
            ("rfq_terms_revisions.rfq_id", "rfq_terms_revisions.revision"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("rfq_id", "respondent_namespace", "respondent_subject"),
            ("rfq_party_references.rfq_id", "rfq_party_references.namespace", "rfq_party_references.subject"),
            ondelete="CASCADE",
        ),
        Index("idx_rfq_responses_inbox", "rfq_id", "created_at", "response_id"),
        Index(
            "uq_rfq_response_pending", "rfq_id", "respondent_namespace", "respondent_subject",
            "terms_revision", unique=True, sqlite_where=text("state = 'pending'"),
            postgresql_where=text("state = 'pending'"),
        ),
    )


class RfqIntroduction(Base):
    """A single consenting pair with its own contact retrieval cutoff."""

    __tablename__ = "rfq_introductions"

    introduction_id = Column(String(128), primary_key=True)
    response_id = Column(
        String(128), ForeignKey("rfq_responses.response_id", ondelete="CASCADE"), nullable=False,
    )
    completed_at = Column(DateTime, nullable=False)
    contact_until = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    version = Column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("response_id", name="uq_rfq_introduction_response"),)


class RfqContactPayload(Base):
    """Only authenticated ciphertext and its envelope reach database custody."""

    __tablename__ = "rfq_contact_payloads"

    response_id = Column(
        String(128), ForeignKey("rfq_responses.response_id", ondelete="CASCADE"), primary_key=True,
    )
    purpose = Column(String(32), primary_key=True)
    format_version = Column(Integer, nullable=False)
    key_id = Column(String(128), nullable=False)
    nonce = Column(LargeBinary, nullable=False)
    ciphertext = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    __table_args__ = (Index("idx_rfq_contacts_expiry", "expires_at", "response_id", "purpose"),)


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
        DateTime(timezone=True), nullable=False, default=utcnow
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
    # The document and seller evidence share the publication transaction.
    published_document = Column(JSON, nullable=True)
    publisher_publication = Column(JSON, nullable=True)
    publisher_updates = Column(JSON, nullable=True)
    listing_resource = Column(
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
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
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
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_api_keys_revoked_at", "revoked_at"),)
