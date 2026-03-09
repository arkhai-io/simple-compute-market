import enum
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
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


class ProvisioningJob(Base):
    __tablename__ = "provisioning_jobs"

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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credentials = relationship("Credential", back_populates="job", cascade="all, delete-orphan")


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("provisioning_jobs.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "root" or "tenant"
    granted_to = Column(String, nullable=False, index=True)  # agent_id this credential is visible to
    password = Column(String, nullable=True)
    ssh_commands = Column(JSON, nullable=True)
    ssh_key_path_host = Column(String, nullable=True)
    key_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("ProvisioningJob", back_populates="credentials")
