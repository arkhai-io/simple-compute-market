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
    agent_id = Column(String, nullable=True, index=True)  # ERC-8004 agent ID that submitted this job
    process_id = Column(String, nullable=True)  # PID of running ansible process for cancellation
    retry_count = Column(Integer, default=0, nullable=False)  # Number of retry attempts made
    max_retries = Column(Integer, default=3, nullable=False)  # Maximum retry attempts allowed
    next_retry_at = Column(DateTime(timezone=True), nullable=True)  # Scheduled time for next retry
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProvisionedVM(Base):
    __tablename__ = "provisioned_vm_access"

    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False, index=True)
    vm_name = Column(String, nullable=False, index=True)
    vm_host = Column(String, nullable=False)
    vm_ip_internal = Column(String, nullable=True)
    vm_state = Column(String, nullable=True)

    # Marketplace context
    seller_order_id = Column(String, nullable=True, index=True)
    buyer_order_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=False, index=True)  # 'seller' or 'buyer'
    seller_agent_id = Column(String, nullable=True, index=True)
    buyer_agent_id = Column(String, nullable=True, index=True)
    negotiation_id = Column(String, nullable=True, index=True)
    escrow_uid = Column(String, nullable=True, index=True)

    # Root credentials (seller-only visibility)
    root_password = Column(String, nullable=True)
    root_ssh_key_path = Column(String, nullable=True)
    root_ssh_commands = Column(JSON, nullable=True)

    # Tenant credentials (buyer-only visibility)
    tenant_user = Column(String, nullable=True)
    tenant_password = Column(String, nullable=True)
    tenant_ssh_commands = Column(JSON, nullable=True)

    # Network/access
    external_ssh_port = Column(String, nullable=True)
    frp_domain = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
