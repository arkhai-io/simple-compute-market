"""Bare-metal domain contract models.

These models describe the storefront-facing bare-metal provisioning contract.
Provisioner implementations can adapt them onto their local site-authority,
inventory, and access-control internals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

BARE_METAL_EXECUTOR_KIND = "bare_metal"
NODE_GRANT_ACCESS_ACTION = "node_grant_access"
NODE_RECLAIM_ACCESS_ACTION = "node_reclaim_access"
BARE_METAL_ACCESS_ACTIONS = (
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
EXCLUSIVE_ALLOCATION_MODE = "exclusive"
PHYSICAL_HOST_ID_REF_KEY = "physical_host_id"


def bare_metal_executor_ref(
    physical_host_id: str,
    *,
    access_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build executor_ref for a bare-metal lease allocation."""
    ref = dict(access_ref or {})
    ref[PHYSICAL_HOST_ID_REF_KEY] = physical_host_id
    return ref


class BareMetalLeaseCreate(BaseModel):
    """Request to attach a bare-metal lease tail to a live allocation."""

    allocation_id: str | None = Field(
        default=None,
        description=(
            "Site allocation identifier. If omitted, the provisioner may look "
            "up the live allocation by escrow_uid."
        ),
    )
    escrow_uid: str = Field(description="On-chain escrow UID from the deal.")
    machine_id: str = Field(
        description=(
            "Bare-metal executor-local machine identity. This is not a global "
            "physical-host namespace."
        ),
    )
    physical_host_id: str = Field(
        description=(
            "Stable physical host identity used for cross-mode accounting "
            "against VM slices and other whole-host claims."
        ),
    )
    lease_start_utc: datetime | None = Field(
        default=None,
        description="UTC datetime when the lease starts; omitted means active now.",
    )
    lease_end_utc: datetime = Field(
        description="UTC datetime when the bare-metal access lease expires.",
    )
    access_ref: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Provisioner-specific access metadata, such as ssh_user or key id. "
            "Secrets should be references, not raw private material."
        ),
    )
    create_job_id: str | None = Field(
        default=None,
        description="Optional access-grant job id for audit/tracing.",
    )

    @model_validator(mode="after")
    def _validate_non_empty_ids(self) -> "BareMetalLeaseCreate":
        for field_name in ("escrow_uid", "machine_id", "physical_host_id"):
            value = getattr(self, field_name)
            if not str(value).strip():
                raise ValueError(f"{field_name} must be non-empty")
        return self


class BareMetalLeaseView(BaseModel):
    """Minimal allocation-backed bare-metal lease view."""

    allocation_id: str
    escrow_uid: str | None = None
    machine_id: str
    physical_host_id: str
    lease_start_utc: str | None = None
    lease_end_utc: str | None = None
    state: str
    release_job_id: str | None = None
    access_ref: dict[str, Any] | None = None


class BareMetalAccessResult(BaseModel):
    """Result shape for bare-metal grant/reclaim executor slots."""

    action: str = Field(
        description="Bare-metal executor lifecycle action that completed.",
    )
    machine_id: str = Field(
        description="Executor-local bare-metal machine identity.",
    )
    physical_host_id: str | None = Field(
        default=None,
        description="Stable cross-mode physical host identity when available.",
    )
    ssh_user: str | None = Field(
        default=None,
        description="Tenant SSH account touched by the access operation.",
    )
    escrow_uid: str | None = Field(
        default=None,
        description="On-chain escrow UID associated with the lease.",
    )
    timestamp: str | None = Field(
        default=None,
        description="Executor-reported completion timestamp.",
    )
    status: str = Field(
        default="success",
        description="Executor-reported terminal status.",
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Implementation-specific result details.",
    )

    @model_validator(mode="after")
    def _validate_action(self) -> "BareMetalAccessResult":
        if self.action not in BARE_METAL_ACCESS_ACTIONS:
            raise ValueError(
                "action must be one of "
                f"{', '.join(BARE_METAL_ACCESS_ACTIONS)}"
            )
        if not self.machine_id.strip():
            raise ValueError("machine_id must be non-empty")
        return self
