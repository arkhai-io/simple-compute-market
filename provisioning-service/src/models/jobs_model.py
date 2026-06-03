"""Internal and HTTP-layer data models for the Ansible job system.

Naming conventions:
  - ``AnsibleJobParams``  — internal DTO built from any typed request and passed
    to ``AnsibleService``.  Not exposed in the OpenAPI schema.
  - ``Job*``              — HTTP response models (JobSubmitResponse, JobStatusResponse, …).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Internal DTO — replaces ProvisionRequest + ProvisioningParams
# ---------------------------------------------------------------------------


@dataclass
class AnsibleJobParams:
    """Structured representation of any Ansible job request for internal use.

    This is the single internal type that flows from ``AnsibleJobService``
    through to ``AnsibleService``.  Typed HTTP request models (in
    ``vm_request_model.py``) each expose a ``to_ansible_job_params()`` method
    that produces one of these.

    Never serialised directly into the OpenAPI schema.
    """

    vm_host: str
    vm_action: str
    vm_target: Optional[str] = None

    # VM sizing (create only)
    image_setup_type: str = "scratch"
    vm_ram: Optional[int] = None
    vm_vcpus: Optional[int] = None
    vm_disk_size: Optional[str] = None
    vm_os_variant: Optional[str] = None

    # Tenant access
    ssh_pubkey: Optional[str] = None

    # GPU (create only)
    gpu_provisioned: Optional[bool] = None
    vm_gpu_count: Optional[int] = None
    vm_gpu_device: Optional[str] = None
    vm_gpu_devices: Optional[list[str]] = field(default=None)
    vm_gpu_partition_size: Optional[str] = None

    # FRP tunnelling (create only)
    frp_server_addr: Optional[str] = None
    frp_domain: Optional[str] = None
    frp_dashboard_password: Optional[str] = None

    # Golden image (create + golden mode)
    golden_image_name: Optional[str] = None
    gcs_bucket_url: Optional[str] = None
    gcs_image_path: Optional[str] = None

    # Lease scheduling
    vm_expiry_at: Optional[str] = None

    # Deal linkage — on-chain escrow UID for recovery queries
    escrow_uid: Optional[str] = None

    # Retry policy (per-job override)
    max_retries: Optional[int] = None


# ---------------------------------------------------------------------------
# Parsed result returned to AnsibleJobService after a playbook completes.
# Replaces ProvisioningResult.
# ---------------------------------------------------------------------------


@dataclass
class AnsibleRunResult:
    """Parsed result returned to AnsibleJobService after a playbook completes."""

    stdout: str
    stderr: str
    ssh_port: Optional[str]
    tenant_user: Optional[str]
    vm_host_ip: Optional[str]
    ssh_command: Optional[str]
    ansible_result: Optional[dict] = None
    process_id: Optional[int] = None


# ---------------------------------------------------------------------------
# HTTP response models — all prefixed Job*
# ---------------------------------------------------------------------------


class JobSubmitResponse(BaseModel):
    """Returned immediately when a job is accepted into the queue.

    Poll ``GET /api/v1/jobs/{job_id}`` for status updates.
    The job_id is stable across retries; use it for credentials and logs too.
    """

    job_id: str = Field(description="Stable unique identifier for the queued job")
    status: str = Field(description="Initial job status (always 'queued')")


class JobStatusResponse(BaseModel):
    """Full job status including parameters, result, and retry metadata."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(
        description="Current status: queued, running, succeeded, failed, or cancelled"
    )
    params: dict[str, Any] = Field(
        description="Original request parameters submitted with the job"
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Structured result from Ansible on success (SSH info, VM state, etc.)",
    )
    error: Optional[str] = Field(default=None, description="Error message if the job failed")
    retry_count: int = Field(default=0, description="Number of retries attempted so far")
    max_retries: int = Field(default=3, description="Maximum retries allowed for this job")
    next_retry_at: Optional[datetime] = Field(
        default=None,
        description="Scheduled time for the next retry attempt (UTC)",
    )
    escrow_uid: Optional[str] = Field(
        default=None,
        description="On-chain escrow UID linking this job to a deal (set at submission time)",
    )


class JobLogsResponse(BaseModel):
    """Raw Ansible playbook output for a job."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Current job status")
    logs: Optional[str] = Field(
        default=None, description="Raw Ansible stdout/stderr captured during execution"
    )


class JobListResponse(BaseModel):
    """Paginated list of Ansible jobs."""

    jobs: list[JobStatusResponse] = Field(description="Jobs on the current page")
    total: int = Field(description="Total number of jobs matching the query")
    offset: int = Field(description="Number of jobs skipped (pagination offset)")
    limit: int = Field(description="Maximum jobs returned per page")


# ---------------------------------------------------------------------------
# Credential response models
# ---------------------------------------------------------------------------


class CredentialResponse(BaseModel):
    """A single credential (one role) for a job."""

    role: str = Field(description="Credential role: 'root' or 'tenant'")
    password: Optional[str] = Field(default=None, description="Login password")
    ssh_commands: Optional[dict] = Field(
        default=None, description="SSH connection commands (external/internal)"
    )
    ssh_key_path_host: Optional[str] = Field(
        default=None, description="Path to SSH key on the host"
    )
    key_type: Optional[str] = Field(
        default=None, description="SSH key type (e.g. 'provided')"
    )


class CredentialListResponse(BaseModel):
    """All credentials for a job, one entry per role."""

    job_id: str = Field(description="Unique job identifier")
    credentials: list[CredentialResponse] = Field(
        description="Every role's credentials for the job"
    )
