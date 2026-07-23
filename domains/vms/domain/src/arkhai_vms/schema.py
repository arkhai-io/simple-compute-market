"""VM market schema names used by core role runtimes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .provision_terms import VM_PROVISION_KIND, VmProvisionTerms


class VmListing(BaseModel):
    """VM-domain listing payload carried by a storefront/registry listing."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    offer_resource: dict[str, Any] = Field(
        description="Compute slice payload offered by the seller.",
    )
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    demands: list[dict[str, Any]] = Field(default_factory=list)
    max_duration_seconds: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _accept_offer_resource_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "offer_resource" in value:
            return value
        return {"offer_resource": value}

    @model_validator(mode="after")
    def _validate_listing(self) -> "VmListing":
        if not self.offer_resource:
            raise ValueError("offer_resource must be non-empty")
        if "gpu_model" not in self.offer_resource:
            raise ValueError("offer_resource must include gpu_model")
        if "gpu_count" not in self.offer_resource:
            raise ValueError("offer_resource must include gpu_count")
        return self


class VmMessage(BaseModel):
    """VM-domain negotiation message payload."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    duration_seconds: int
    ssh_public_key: str = Field(default="")
    start_utc: str | None = None
    compute_resource: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_provision_terms(cls, value: Any) -> Any:
        if isinstance(value, VmProvisionTerms):
            envelope = value
        elif isinstance(value, dict) and "payload" in value:
            envelope = VmProvisionTerms.model_validate(value)
        else:
            return value
        payload = dict(envelope.payload)
        payload["kind"] = envelope.kind
        return payload


class VmTerms(BaseModel):
    """Canonical agreed VM terms produced by negotiation."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    duration_seconds: int = Field(ge=1)
    ssh_public_key: str
    start_utc: str | None = None
    compute_resource: dict[str, Any] | None = None
    listing_ref: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_provision_terms(cls, value: Any) -> Any:
        if isinstance(value, VmProvisionTerms):
            envelope = value
        elif isinstance(value, dict) and "payload" in value:
            envelope = VmProvisionTerms.model_validate(value)
        else:
            return value
        payload = dict(envelope.payload)
        payload["kind"] = envelope.kind
        return payload

    @model_validator(mode="after")
    def _validate_terms(self) -> "VmTerms":
        if not self.ssh_public_key.strip():
            raise ValueError("ssh_public_key must be non-empty")
        return self


class VmMaterialization(BaseModel):
    """Settlement-to-fulfillment handoff for a VM agreement."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    escrow_uid: str
    duration_seconds: int = Field(ge=1)
    ssh_public_key: str
    compute_resource: dict[str, Any] | None = None
    lease_start_utc: datetime | None = None
    lease_end_utc: datetime | None = None
    listing_ref: str | None = None
    settlement_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_materialization(self) -> "VmMaterialization":
        if not self.escrow_uid.strip():
            raise ValueError("escrow_uid must be non-empty")
        if not self.ssh_public_key.strip():
            raise ValueError("ssh_public_key must be non-empty")
        if (
            self.lease_start_utc is not None
            and self.lease_end_utc is not None
            and self.lease_start_utc >= self.lease_end_utc
        ):
            raise ValueError("lease_start_utc must be before lease_end_utc")
        return self


class VmReceipt(BaseModel):
    """Domain receipt for VM fulfillment/servicing state."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    escrow_uid: str | None = None
    vm_name: str | None = None
    status: str
    lease_start_utc: datetime | None = None
    lease_end_utc: datetime | None = None
    access_ref: dict[str, Any] | None = None
    result_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_receipt(self) -> "VmReceipt":
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        if (
            self.lease_start_utc is not None
            and self.lease_end_utc is not None
            and self.lease_start_utc >= self.lease_end_utc
        ):
            raise ValueError("lease_start_utc must be before lease_end_utc")
        return self


class VmResult(BaseModel):
    """Result shape for VM provisioning/release executor slots."""

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    action: str
    status: str = "success"
    vm_name: str | None = None
    escrow_uid: str | None = None
    details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> "VmResult":
        if not self.action.strip():
            raise ValueError("action must be non-empty")
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        return self
