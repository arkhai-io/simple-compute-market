"""Credential-free lease-ready result and portable evidence codecs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .hosted_contract import (
    BARE_METAL_ACCEPTED_BINDING_KIND,
    BareMetalAcceptedHostedBinding,
    CanonicalPrincipal,
    ResourceSelection,
    bare_metal_digest,
    canonical_bare_metal_json,
)

BARE_METAL_LEASE_READY_RESULT_KIND = "bare_metal.lease-ready-result.v1"
BARE_METAL_LEASE_READY_EVIDENCE_KIND = "bare_metal.lease-ready-evidence.v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class BareMetalLeaseReadyResult(BaseModel):
    """Allowlisted public result derived from authoritative physical state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.lease-ready-result.v1"] = (
        BARE_METAL_LEASE_READY_RESULT_KIND
    )
    site_id: str = Field(min_length=1, max_length=256)
    executor_kind: Literal["bare_metal"] = "bare_metal"
    resource_selection: ResourceSelection
    physical_resource_id: str | None = Field(default=None, max_length=256)
    capacity_reservation_ref: str = Field(min_length=1, max_length=256)
    settlement_resource_ref: str = Field(min_length=1, max_length=256)
    fulfillment_ref: str = Field(min_length=1, max_length=256)
    access_grant_ref: str = Field(min_length=1, max_length=256)
    access_method: Literal["ssh"] = "ssh"
    access_ready: Literal[True] = True
    access_ready_at: datetime
    expires_at: datetime

    @field_validator(
        "site_id",
        "physical_resource_id",
        "capacity_reservation_ref",
        "settlement_resource_ref",
        "fulfillment_ref",
        "access_grant_ref",
    )
    @classmethod
    def _validate_public_ref(cls, value: str | None) -> str | None:
        if value is not None and _OPAQUE_REF.fullmatch(value) is None:
            raise ValueError("lease-ready references must be trimmed opaque tokens")
        return value

    @model_validator(mode="after")
    def _validate_result(self) -> "BareMetalLeaseReadyResult":
        if self.resource_selection == "specific":
            if self.physical_resource_id is None:
                raise ValueError(
                    "specific-resource result requires Physical Resource identity"
                )
        elif self.physical_resource_id is not None:
            raise ValueError(
                "fungible result must keep assigned Physical Resource internal"
            )
        if self.access_ready_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("lease-ready timestamps must be timezone-aware")
        if self.access_ready_at >= self.expires_at:
            raise ValueError("access readiness must precede lease expiry")
        return self

    @property
    def result_digest(self) -> str:
        return bare_metal_digest(self)


class BareMetalLeaseReadyEvidence(BaseModel):
    """Portable condition evidence with no access or provider capability data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.lease-ready-evidence.v1"] = (
        BARE_METAL_LEASE_READY_EVIDENCE_KIND
    )
    accepted_binding_kind: Literal["bare_metal.accepted-hosted-binding.v1"] = (
        BARE_METAL_ACCEPTED_BINDING_KIND
    )
    agreement_ref: str = Field(min_length=1, max_length=256)
    obligation_ref: str = Field(min_length=1, max_length=256)
    accepted_binding_digest: str
    fulfillment_identity: str
    buyer_principal: CanonicalPrincipal
    seller_principal: CanonicalPrincipal
    claimant_principal: CanonicalPrincipal
    condition_anchor: str = Field(min_length=1, max_length=256)
    result: BareMetalLeaseReadyResult
    result_digest: str

    @field_validator("agreement_ref", "obligation_ref", "condition_anchor")
    @classmethod
    def _validate_opaque_ref(cls, value: str) -> str:
        if _OPAQUE_REF.fullmatch(value) is None:
            raise ValueError("evidence references must be trimmed opaque tokens")
        return value

    @field_validator(
        "accepted_binding_digest",
        "fulfillment_identity",
        "result_digest",
    )
    @classmethod
    def _validate_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("evidence digests must be lower-case SHA-256 references")
        return value

    @model_validator(mode="after")
    def _validate_evidence(self) -> "BareMetalLeaseReadyEvidence":
        if self.result_digest != self.result.result_digest:
            raise ValueError("evidence result digest does not match its public result")
        return self

    @property
    def evidence_digest(self) -> str:
        return bare_metal_digest(self)

    def canonical_json(self) -> str:
        return canonical_bare_metal_json(self)


def derive_bare_metal_fulfillment_identity(
    binding: BareMetalAcceptedHostedBinding,
) -> str:
    """Derive the stable physical fulfillment identity from accepted authority."""

    facts = binding.option.facts
    return bare_metal_digest(
        {
            "kind": "bare_metal.fulfillment-identity.v1",
            "agreement_ref": binding.agreement_ref,
            "obligation_ref": binding.obligation_ref,
            "accepted_binding_digest": binding.binding_digest,
            "buyer_principal": binding.buyer_principal.model_dump(mode="json"),
            "claimant_principal": binding.claimant_principal.model_dump(mode="json"),
            "site_id": facts.site_id,
            "executor_kind": facts.executor_kind,
            "resource_selection": facts.resource_selection,
            "physical_resource_id": facts.physical_resource_id,
            "pool_id": facts.pool_id,
        }
    )


def build_bare_metal_lease_ready_evidence(
    *,
    binding: BareMetalAcceptedHostedBinding,
    condition_anchor: str,
    result: BareMetalLeaseReadyResult,
) -> BareMetalLeaseReadyEvidence:
    """Bind an authoritative public result to the exact accepted obligation."""

    facts = binding.option.facts
    if result.site_id != facts.site_id or result.executor_kind != facts.executor_kind:
        raise ValueError("lease-ready result conflicts with accepted site/executor")
    if result.resource_selection != facts.resource_selection:
        raise ValueError("lease-ready result changes accepted resource selection")
    if result.physical_resource_id != facts.physical_resource_id:
        raise ValueError("lease-ready result changes accepted Physical Resource")
    if result.access_method != facts.access_method:
        raise ValueError("lease-ready result changes accepted access method")
    return BareMetalLeaseReadyEvidence(
        agreement_ref=binding.agreement_ref,
        obligation_ref=binding.obligation_ref,
        accepted_binding_digest=binding.binding_digest,
        fulfillment_identity=derive_bare_metal_fulfillment_identity(binding),
        buyer_principal=binding.buyer_principal,
        seller_principal=binding.seller_principal,
        claimant_principal=binding.claimant_principal,
        condition_anchor=condition_anchor,
        result=result,
        result_digest=result.result_digest,
    )


__all__ = [
    "BARE_METAL_LEASE_READY_EVIDENCE_KIND",
    "BARE_METAL_LEASE_READY_RESULT_KIND",
    "BareMetalLeaseReadyEvidence",
    "BareMetalLeaseReadyResult",
    "build_bare_metal_lease_ready_evidence",
    "derive_bare_metal_fulfillment_identity",
]
