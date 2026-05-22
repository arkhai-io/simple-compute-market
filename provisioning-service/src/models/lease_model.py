"""Pydantic models for the VM lease API.

LeaseCreate  — request body for POST /api/v1/leases
LeaseUpdate  — request body for PATCH /api/v1/leases/{id}
LeaseResponse — serialised view returned by all lease endpoints
LeaseListResponse — wraps a list of LeaseResponse for list queries

The storefront calls POST /api/v1/leases after a VM has been provisioned and
the lease window is known (i.e., after _do_shutdown succeeds in
action_executor.py). The provisioning service's LeaseWatchdog then polls the
vm_leases table, submits a check Ansible job to confirm VM cleanup, and calls
back to the storefront's PATCH /api/v1/admin/portfolio/resources/{resource_id}
endpoint when the lease is confirmed released.

The storefront_url and storefront_admin_key are global settings on the
provisioning service (settings.toml: storefront_url, storefront_admin_key)
rather than per-lease fields. One provisioning service instance serves one
storefront. In production these are injected via the provisioning-secrets
config profile.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LeaseCreate(BaseModel):
    """Body accepted by ``POST /api/v1/leases``."""

    resource_id: str = Field(
        description=(
            "Storefront-assigned resource identifier (e.g. 'compute-ww1-001'). "
            "Treated as an opaque string; the provisioning service does not "
            "validate it against any local table."
        )
    )
    escrow_uid: str = Field(
        description="On-chain escrow UID from the deal. Unique per lease."
    )
    vm_host: str = Field(
        description="KVM host alias (Ansible inventory name, e.g. 'ww1')."
    )
    vm_target: str = Field(
        description="Libvirt domain name of the provisioned VM (e.g. 'tenant-a3f2')."
    )
    lease_start_utc: Optional[datetime] = Field(
        default=None,
        description=(
            "UTC datetime when the lease becomes active. "
            "None means the lease is active immediately on creation."
        ),
    )
    lease_end_utc: datetime = Field(
        description="UTC datetime when the lease expires and the VM should be torn down."
    )
    create_job_id: Optional[str] = Field(
        default=None,
        description=(
            "Provisioning job_id of the VM creation job. "
            "Allows tracing from lease back to the original create job."
        ),
    )


class LeaseUpdate(BaseModel):
    """Body accepted by ``PATCH /api/v1/leases/{lease_id}``.

    All fields are optional; only supplied (non-None) fields are written.
    Primarily used by operators and tests; normal lifecycle transitions happen
    internally via LeaseService methods called by the watchdog.
    """

    status: Optional[str] = Field(
        default=None,
        description="New lease status. See LeaseStatus for valid values.",
    )
    check_job_id: Optional[str] = Field(
        default=None,
        description="Provisioning job_id for the most recent watchdog check job.",
    )
    lease_end_utc: Optional[datetime] = Field(
        default=None,
        description="Override the lease expiry time (e.g. to extend or shorten a lease).",
    )


class LeaseResponse(BaseModel):
    """Serialised lease row returned by all lease endpoints."""

    id: str
    resource_id: str
    escrow_uid: str
    vm_host: str
    vm_target: str
    lease_start_utc: Optional[datetime] = None
    lease_end_utc: datetime
    status: str
    create_job_id: Optional[str] = None
    check_job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeaseListResponse(BaseModel):
    """Response body for ``GET /api/v1/leases``."""

    leases: list[LeaseResponse]
    total: int
