"""The job authority's persistence: one row per job, one per credential it produced.

The tables keep their names, ``ansible_jobs`` and ``credentials``. A job row
holds its identity, state, route key (``offering_mode`` and ``executor_action``),
``host_id``, its opaque parameters, retry bookkeeping, the contract identity it
was submitted under if any, the opaque cancellation handle its executor
reported, its logs, and its result as a ``ResultEnvelope``. A credential row
holds one ``CredentialEnvelope``. Nothing here interprets a parameter, a
handle, a result, or a credential.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.cancelled.value}
)


class JobRecord(Base):
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
    host_id = Column(String, nullable=True, index=True)
    # A ResultEnvelope, as the job's executor reported it.
    result = Column(JSON, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    # The opaque cancellation handle the executor reported, returned to it as is.
    execution_handle = Column(JSON, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    escrow_uid = Column(String, nullable=True, index=True)
    capacity_reservation_id = Column(String, nullable=True, index=True)
    deal_ref = Column(JSON, nullable=True)
    offering_mode = Column(String, nullable=True)
    # The contract action this job was submitted under, part of its contract
    # identity; for a job submitted without a contract, the action it runs.
    action_kind = Column(String, nullable=True)
    # The action the job's executor runs, which the job is routed by. A
    # contract action may run as a different executor action (a VM teardown
    # runs ``destroy``).
    executor_action = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    credentials = relationship(
        "JobCredential", back_populates="job", cascade="all, delete-orphan"
    )


class JobCredential(Base):
    __tablename__ = "credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("ansible_jobs.id"), nullable=False, index=True)
    # A CredentialEnvelope, as the job's executor reported it.
    envelope = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    job = relationship("JobRecord", back_populates="credentials")


__all__ = ["Base", "JobCredential", "JobRecord", "JobStatus", "TERMINAL_JOB_STATUSES"]
