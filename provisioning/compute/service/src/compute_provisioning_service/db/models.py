import enum
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func


Base = declarative_base()


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class CredentialRole(str, enum.Enum):
    root = "root"
    tenant = "tenant"


class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"
    __table_args__ = (
        UniqueConstraint(
            "capacity_reservation_id",
            "action_kind",
            "idempotency_key",
            name="uq_ansible_jobs_contract_idempotency",
        ),
    )

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    params = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    process_id = Column(String, nullable=True)  # PID of running ansible process for cancellation
    retry_count = Column(Integer, default=0, nullable=False)  # Number of retry attempts made
    max_retries = Column(Integer, default=3, nullable=False)  # Maximum retry attempts allowed
    next_retry_at = Column(DateTime(timezone=True), nullable=True)  # Scheduled time for next retry
    escrow_uid = Column(String, nullable=True, index=True)  # On-chain escrow UID linking this job to a deal
    contract_version = Column(String, nullable=True)
    capacity_reservation_id = Column(String, nullable=True, index=True)
    deal_ref = Column(JSON, nullable=True)
    executor_kind = Column(String, nullable=True)
    action_kind = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True)
    credentials_private = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credentials = relationship("Credential", back_populates="job", cascade="all, delete-orphan")


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("ansible_jobs.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "root" or "tenant"
    password = Column(String, nullable=True)
    ssh_commands = Column(JSON, nullable=True)
    ssh_key_path_host = Column(String, nullable=True)
    key_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("AnsibleJob", back_populates="credentials")


# Provider-neutral resource-pool identity now lives in the shared
# market_resource_pools package (kit); re-exported here because the
# service's modules and tests reach all persistence models through
# db.models. The table rides market_resource_pools' own metadata —
# init_db creates it alongside this service's own Base and market_site's.
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool  # noqa: F401


class AnsiblePoolConfig(Base):
    """Ansible-provider-specific config for a resource pool.

    Provider-specific data lives in its own side table rather than as
    generic columns on ``resource_pools`` — see ARCHITECTURE.md § Physical
    Settlement Scheduler and FulfillmentProvider Architecture, "Settlement
    record metadata envelope" for the same principle applied to settlement
    records. Only the "ansible" provider is implemented; other providers
    (kubernetes, gcp, ...) would get their own side table, not new columns
    here.

    No ORM ``relationship()`` back to ``ResourcePool``: that model now lives
    in a different declarative registry (``market_resource_pools``), so
    navigation is by explicit ``pool_id`` lookup — which is how
    ``PoolConfigHandler`` implementations already read/write this table.
    """

    __tablename__ = "ansible_pool_configs"

    pool_id = Column(String, ForeignKey(ResourcePool.__table__.c.id), primary_key=True)
    playbook_path = Column(String, nullable=False)
    inventory_group = Column(String, nullable=False)
    extra_vars = Column(JSON, nullable=False, default=dict)


class Host(Base):
    """Registered provisioning host.

    This is the single source of truth for host inventory. The Ansible INI
    file is an input format only (via ``POST /hosts/import`` or the
    ``PROVISIONING_INVENTORY_INI`` env var at startup); at runtime, all host
    lookups and inventory rendering use this table. Rows may represent KVM
    hypervisors, bare-metal nodes, or future executor hosts; the row name is
    the Ansible alias used by executor jobs.

    ssh_key_type:
        "path"     — ssh_key_value is a filesystem path (e.g. a mounted
                     Kubernetes Secret at /home/appuser/.ssh/id_ed25519).
        "embedded" — ssh_key_value is a Fernet-encrypted PEM string stored
                     in the DB. Requires SSH_DECRYPTION_KEY to be set.

    enabled:
        False hosts are excluded from list queries and inventory rendering.
        Hosts are never hard-deleted (append-only) so that job history FKs
        (vm_host name references) remain resolvable.

    pool_id:
        Resource pool this host belongs to. Every host has a pool — there is
        no "unassigned" state. New rows default to the system-created
        "default" pool (DEFAULT_POOL_ID) at both the ORM layer (for
        freshly-created schemas) and the DB layer (for the migration that
        backfills pre-existing rows) so the column can be NOT NULL from the
        start rather than carrying a nullable transitional state.
    """

    __tablename__ = "hosts"

    name = Column(String, primary_key=True)  # Ansible alias, e.g. "kvm1"
    kvm_host = Column(String, nullable=False)  # IP/hostname the provisioner SSHes to
    # Address tenants use to reach this host's VM port-forwards (public IP,
    # DNS, or overlay IP). Distinct from kvm_host: the provisioner may reach
    # the host over a different network than buyers do. NULL → fall back to
    # kvm_host in tenant-facing connection info.
    public_host = Column(String, nullable=True)
    ssh_user = Column(String, nullable=False)  # SSH login user on the KVM host
    ssh_key_type = Column(String, nullable=False, default="path")  # "path" | "embedded"
    ssh_key_value = Column(String, nullable=False)  # path string or encrypted PEM
    gpu_count = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    pool_id = Column(
        String,
        ForeignKey(ResourcePool.__table__.c.id),
        nullable=False,
        default=DEFAULT_POOL_ID,
        server_default=DEFAULT_POOL_ID,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# The site-authority ledger models live in the shared market_site
# package; re-exported here because the service's modules and tests
# reach all persistence models through db.models. The tables ride
# market_site's own metadata — init_db creates both.
from market_site.db import (  # noqa: F401
    HELD_RESERVATION_STATES,
    ReservationState,
    CapacityEvent,
    CapacityReservation,
)

# The settlement/fulfillment aggregate lives in the shared
# market_fulfillment package; re-exported here for the same reason. The
# tables ride market_fulfillment's own metadata — init_db creates it
# alongside this service's own Base, market_site's, and
# market_resource_pools'.
from market_fulfillment.db import (  # noqa: F401
    ProvisionedResource,
    SettlementRecord,
    SettlementRecordState,
)
