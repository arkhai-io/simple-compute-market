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


class AnsibleJob(Base):
    __tablename__ = "ansible_jobs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    params = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    agent_id = Column(String, nullable=True, index=True)  # ERC-8004 agent ID (seller) that submitted this job
    buyer_agent_id = Column(String, nullable=True, index=True)  # ERC-8004 agent ID of the buyer
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
    granted_to = Column(String, nullable=False, index=True)  # agent_id this credential is visible to
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

    name = Column(String, primary_key=True)  # Ansible alias, e.g. "ww1"
    kvm_host = Column(String, nullable=False)  # IP or hostname for SSH
    ssh_user = Column(String, nullable=False)  # SSH login user on the KVM host
    ssh_key_type = Column(String, nullable=False, default="path")  # "path" | "embedded"
    ssh_key_value = Column(String, nullable=False)  # path string or encrypted PEM
    gpu_count = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
