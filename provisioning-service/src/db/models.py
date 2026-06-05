import enum
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
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


class LeaseStatus(str, enum.Enum):
    """Lifecycle states for a VM lease tracked in the vm_leases table.

    pending   — lease_start_utc is in the future; VM may not yet be running.
    active    — lease is running; lease_end_utc is in the future.
    releasing — lease_end_utc has passed; watchdog submitted a check job to
                confirm VM cleanup and is waiting for it to complete before
                releasing the storefront resource.
    released  — storefront PATCH /resources/{id} called successfully; resource
                is available again.
    forced    — grace period elapsed without VM confirmation; storefront
                patched regardless. Resource is available; VM state unknown.
    cancelled — lease cancelled before expiry (e.g. early termination by deal).
    """

    pending   = "pending"
    active    = "active"
    releasing = "releasing"
    released  = "released"
    forced    = "forced"
    cancelled = "cancelled"


class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"

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


class Host(Base):
    """Registered KVM hypervisor host.

    This is the single source of truth for host inventory. The Ansible INI
    file is an input format only (via ``POST /hosts/import`` or the
    ``PROVISIONING_INVENTORY_INI`` env var at startup); at runtime, all host
    lookups and inventory rendering use this table.

    ssh_key_type:
        "path"     — ssh_key_value is a filesystem path (e.g. a mounted
                     Kubernetes Secret at /home/appuser/.ssh/id_ed25519).
        "embedded" — ssh_key_value is a Fernet-encrypted PEM string stored
                     in the DB. Requires SSH_DECRYPTION_KEY to be set.

    enabled:
        False hosts are excluded from list queries and inventory rendering.
        Hosts are never hard-deleted (append-only) so that job history FKs
        (vm_host name references) remain resolvable.
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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class VmLease(Base):
    """Tracks active VM leases so the LeaseWatchdog can release storefront
    resources when leases expire — replacing the storefront's polling pattern.

    resource_id:
        The storefront-assigned resource identifier (e.g. 'compute-kvm1-001').
        Stored as unvalidated TEXT; the provisioning service has no resources
        table, so no FK constraint is possible. Application-level FK enforced
        by the storefront (caller).

    escrow_uid:
        On-chain escrow UID from the deal. Unique per lease — one deal produces
        exactly one lease. Used for recovery queries and idempotency.

    vm_host / vm_target:
        KVM host alias and libvirt domain name. Used when submitting check jobs.

    lease_start_utc / lease_end_utc:
        Lease window boundaries in UTC. lease_start_utc is nullable (None means
        "starts immediately on creation"). The watchdog acts when
        lease_end_utc < now AND status IN (active, pending).

    status:
        LeaseStatus enum value. Transitions:
          pending  → active    (when lease_start_utc passes or is None at creation)
          active   → releasing (when lease_end_utc passes, watchdog submits check job)
          releasing→ released  (check job confirms VM gone, storefront patched)
          releasing→ forced    (grace period elapsed, storefront patched anyway)
          *        → cancelled (explicit cancellation before expiry)

    create_job_id:
        Provisioning job_id of the VM creation job. Allows tracing from lease
        back to the original job that produced the VM.

    check_job_id:
        Provisioning job_id for the most recent check Ansible job submitted by
        the watchdog. Nullable — only set during the 'releasing' phase. Allows
        operators to query ``GET /api/v1/jobs/{check_job_id}`` for details.
    """

    __tablename__ = "vm_leases"

    id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    resource_id = Column(String, nullable=False, index=True)
    allocation_id = Column(String, nullable=True, index=True)
    escrow_uid = Column(String, nullable=False, unique=True, index=True)
    vm_host = Column(String, nullable=False)
    vm_target = Column(String, nullable=False)
    lease_start_utc = Column(DateTime(timezone=True), nullable=True)
    lease_end_utc = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(
        String, nullable=False, default=LeaseStatus.pending.value, index=True
    )
    create_job_id = Column(String, nullable=True)
    check_job_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
