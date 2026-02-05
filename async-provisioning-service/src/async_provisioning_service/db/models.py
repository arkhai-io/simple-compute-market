import enum

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func


Base = declarative_base()


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ProvisioningJob(Base):
    __tablename__ = "provisioning_jobs"

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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
