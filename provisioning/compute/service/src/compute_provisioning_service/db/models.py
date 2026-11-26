import injected_time
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func


Base = declarative_base()


# The job authority's models live in compute_provisioning; re-exported here
# because the service's modules and tests reach all persistence models through
# db.models. Their tables are created by the job authority's own baseline in
# this service's migration chain (db/migrations.py), as every table here is.
from compute_provisioning.jobs.db import (  # noqa: E402,F401
    TERMINAL_JOB_STATUSES,
    JobCredential,
    JobRecord,
    JobStatus,
)


class ProvisioningReplayReservation(Base):
    """Durable principal-scoped request reservation and recorded outcome."""

    __tablename__ = "provisioning_replay_reservations"

    principal_scheme = Column(String, primary_key=True)
    principal_identifier = Column(String, primary_key=True)
    request_id = Column(String, primary_key=True)
    request_hash = Column(String, nullable=False)
    dispatch_lease_expires_at = Column(DateTime(timezone=True), nullable=False)
    dispatch_attempt_count = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    response_body_empty = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    response_media_type = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

class LeaseEndReport(Base):
    """One lease end's signed statement, as the site signed it when the end was
    recorded: the authenticated lease read serves it, and the storefront peer's
    consumer delivers it. Kept under its own retention, independent of the
    event it was recorded with."""

    __tablename__ = "lease_end_reports"

    event_id = Column(String, primary_key=True)
    capacity_reservation_id = Column(String, nullable=False, index=True)
    report = Column(Text, nullable=False)
    # Reports are read in creation order and retained by age, so creation is
    # stamped from the process's time source rather than the database's clock.
    created_at = Column(
        DateTime(timezone=True),
        default=injected_time.now_datetime,
        nullable=False,
        index=True,
    )


class ProvisioningTrustedPrincipal(Base):
    """Versioned role binding retained through bounded rotation overlap."""

    __tablename__ = "provisioning_trusted_principals"

    role = Column(String, primary_key=True)
    principal_scheme = Column(String, primary_key=True)
    principal_identifier = Column(String, primary_key=True)
    generation = Column(Integer, nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ProvisioningIdentityRotationAudit(Base):
    """Immutable accepted rotation intent for audit and nonce replay rejection."""

    __tablename__ = "provisioning_identity_rotation_audit"

    nonce = Column(String, primary_key=True)
    role = Column(String, nullable=False)
    current_scheme = Column(String, nullable=False)
    current_identifier = Column(String, nullable=False)
    replacement_scheme = Column(String, nullable=False)
    replacement_identifier = Column(String, nullable=False)
    overlap_seconds = Column(Integer, nullable=False)
    intent_expires_at = Column(Integer, nullable=False)
    applied_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )



# Provider-neutral resource-pool identity lives in the shared
# market_resource_pools package (kit); re-exported here because the
# service's modules and tests reach all persistence models through
# db.models.
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool  # noqa: F401


class DefinitionDocumentImport(Base):
    """Digest of the definition document last reconciled, per document kind.

    Import treats a document as authoritative: it overwrites entries that
    differ from it. What it does with an entry the document does not name
    depends on the kind: a pool is disabled, because the document declares
    what the deployment offers; a capacity declaration, or what a contributed
    kind declares, may be retained. That authority, in any form, belongs to the act of submitting a document. A process start is not a submission, and
    re-applying a document nobody submitted reverts whatever else changed the
    database — silently, on eviction, drain, and crash recovery.

    So a startup reconciles only when the mounted document differs from the
    digest recorded here. The digest is written in the same transaction that
    applies the reconciliation, so a failed apply does not record a document
    that was never applied and suppress the next attempt.
    """

    __tablename__ = "definition_document_imports"

    document_kind = Column(String, primary_key=True)
    digest = Column(String, nullable=False)
    imported_at = Column(DateTime, nullable=False, server_default=func.now())


# The host registry's model lives with the host authority in
# compute_provisioning; re-exported here because the service's modules and
# tests reach all persistence models through db.models.
from compute_provisioning.hosts.db import Host  # noqa: E402,F401


# The site-authority ledger models live in the shared market_site
# package; re-exported here because the service's modules and tests
# reach all persistence models through db.models.
from market_site.db import (  # noqa: F401
    HELD_RESERVATION_STATES,
    ReservationState,
    CapacityEvent,
    CapacityReservation,
)

# The settlement/fulfillment aggregate lives in the shared
# market_fulfillment package; re-exported here for the same reason.
from market_fulfillment.db import (  # noqa: F401
    ProvisionedResource,
    SettlementRecord,
    SettlementRecordState,
)
