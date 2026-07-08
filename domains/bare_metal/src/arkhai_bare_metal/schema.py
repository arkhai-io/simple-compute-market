"""Bare-metal market schema and public domain vocabulary.

The domain package specifies the shared market vocabulary. Runtime choices such
as seller policies, provisioning implementations, host inventory backends, and
provider integrations live in separate packages that depend on this package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BARE_METAL_SCHEMA_KIND = "bare_metal.v1"
BARE_METAL_EXECUTOR_KIND = "bare_metal"
SSH_ACCESS_METHOD = "ssh"
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


class BareMetalListing(BaseModel):
    """Bare-metal domain payload carried by a registry listing."""

    kind: Literal["bare_metal.v1"] = BARE_METAL_SCHEMA_KIND
    machine_id: str = Field(
        description="Bare-metal executor-local machine identity.",
    )
    physical_host_id: str = Field(
        description="Stable physical host identity for cross-mode accounting.",
    )
    access_methods: list[str] = Field(
        default_factory=lambda: [SSH_ACCESS_METHOD],
        description="Buyer-visible access methods supported by this listing.",
    )
    min_duration_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Shortest lease duration the seller advertises.",
    )
    max_duration_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Longest lease duration the seller advertises.",
    )
    site: dict[str, str] | None = Field(
        default=None,
        description="Optional site/region/zone labels for discovery.",
    )
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific hardware capabilities for discovery.",
    )

    @model_validator(mode="after")
    def _validate_listing(self) -> "BareMetalListing":
        for field_name in ("machine_id", "physical_host_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not self.access_methods:
            raise ValueError("access_methods must contain at least one method")
        if any(not str(method).strip() for method in self.access_methods):
            raise ValueError("access_methods must not contain blank values")
        if (
            self.min_duration_seconds is not None
            and self.max_duration_seconds is not None
            and self.min_duration_seconds > self.max_duration_seconds
        ):
            raise ValueError(
                "min_duration_seconds must be <= max_duration_seconds"
            )
        return self


class BareMetalMessage(BaseModel):
    """Bare-metal negotiation message payload."""

    kind: Literal["bare_metal.v1"] = BARE_METAL_SCHEMA_KIND
    duration_seconds: int = Field(
        ge=1,
        description="Requested bare-metal lease duration.",
    )
    access_method: str = Field(
        default=SSH_ACCESS_METHOD,
        description="Requested access method.",
    )
    ssh_public_key: str | None = Field(
        default=None,
        description="Buyer SSH public key when SSH access is requested.",
    )
    access_ref: dict[str, Any] | None = Field(
        default=None,
        description="Optional access metadata/reference agreed by policy.",
    )

    @model_validator(mode="after")
    def _validate_message(self) -> "BareMetalMessage":
        if not self.access_method.strip():
            raise ValueError("access_method must be non-empty")
        if self.access_method == SSH_ACCESS_METHOD and not (
            self.ssh_public_key or self.access_ref
        ):
            raise ValueError(
                "ssh_public_key or access_ref is required for SSH access"
            )
        return self


class BareMetalTerms(BaseModel):
    """Canonical agreed bare-metal terms produced by negotiation."""

    kind: Literal["bare_metal.v1"] = BARE_METAL_SCHEMA_KIND
    machine_id: str = Field(
        description="Bare-metal executor-local machine identity.",
    )
    physical_host_id: str = Field(
        description="Stable physical host identity for cross-mode accounting.",
    )
    duration_seconds: int = Field(
        ge=1,
        description="Agreed bare-metal lease duration.",
    )
    access_method: str = Field(
        default=SSH_ACCESS_METHOD,
        description="Agreed access method.",
    )
    ssh_public_key: str | None = Field(
        default=None,
        description="Buyer SSH public key when SSH access is requested.",
    )
    access_ref: dict[str, Any] | None = Field(
        default=None,
        description="Access metadata/reference consumed by provisioning.",
    )
    listing_ref: str | None = Field(
        default=None,
        description="Optional registry/storefront listing reference.",
    )

    @model_validator(mode="after")
    def _validate_terms(self) -> "BareMetalTerms":
        for field_name in ("machine_id", "physical_host_id", "access_method"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.access_method == SSH_ACCESS_METHOD and not (
            self.ssh_public_key or self.access_ref
        ):
            raise ValueError(
                "ssh_public_key or access_ref is required for SSH access"
            )
        return self


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
