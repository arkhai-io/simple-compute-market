"""Credential-free lease-ready result and portable evidence codecs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema

ResourceSelection = Literal["specific", "fungible"]
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def canonical_bare_metal_json(value: Any) -> str:
    """Serialize a public domain value for stable identity derivation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def bare_metal_digest(value: Any) -> str:
    """Return a canonical lower-case SHA-256 reference."""

    return (
        "sha256:"
        + hashlib.sha256(canonical_bare_metal_json(value).encode()).hexdigest()
    )


class CanonicalPrincipal(BaseModel):
    """Canonical marketplace principal for the parties bound by the evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scheme: str = Field(min_length=1)
    identifier: str = Field(min_length=1)

    @field_validator("scheme", "identifier")
    @classmethod
    def _validate_component(cls, value: str) -> str:
        if value != value.strip() or _TOKEN.fullmatch(value) is None:
            raise ValueError("principal components must be trimmed public tokens")
        return value


BARE_METAL_LEASE_READY_RESULT_KIND = "bare_metal.lease-ready-result.v1"
BARE_METAL_LEASE_READY_EVIDENCE_KIND = "bare_metal.lease-ready-evidence.v1"
BARE_METAL_ACCEPTED_ALKAHEST_BINDING_KIND = "bare_metal.accepted-alkahest-binding.v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_V1_TIMESTAMP = TypeAdapter(datetime)


class BareMetalLeaseReadyResult(BaseModel):
    """Allowlisted public result derived from authoritative physical state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.lease-ready-result.v1"] = (
        BARE_METAL_LEASE_READY_RESULT_KIND
    )
    site_id: str = Field(min_length=1, max_length=256)
    offering_mode: Literal["bare_metal"] = "bare_metal"
    resource_selection: ResourceSelection
    physical_resource_id: str | None = Field(default=None, max_length=256)
    capacity_reservation_ref: str = Field(min_length=1, max_length=256)
    settlement_resource_ref: str = Field(min_length=1, max_length=256)
    fulfillment_ref: str = Field(min_length=1, max_length=256)
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
        return bare_metal_digest(_result_v1(self))


class BareMetalAcceptedAlkahestBinding(BaseModel):
    """What an accepted Alkahest deal binds its lease-ready evidence to.

    Physical facts come from the listing binding copied by the accepted thread,
    beside the digest of the settlement plan committed at acceptance and the
    escrow it was funded by.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.accepted-alkahest-binding.v1"] = (
        BARE_METAL_ACCEPTED_ALKAHEST_BINDING_KIND
    )
    agreement_ref: str = Field(min_length=1)
    negotiation_id: str = Field(min_length=1)
    listing_id: str = Field(min_length=1)
    obligation_ref: str = Field(min_length=1)
    escrow_uid: str = Field(min_length=1, max_length=256)
    accepted_plan_digest: str
    buyer_principal: CanonicalPrincipal
    seller_principal: CanonicalPrincipal
    claimant_principal: CanonicalPrincipal
    site_id: str = Field(min_length=1)
    offering_mode: Literal["bare_metal"] = "bare_metal"
    resource_selection: ResourceSelection
    physical_resource_id: str | None = None
    pool_id: str | None = None
    access_method: Literal["ssh"] = "ssh"

    @field_validator("accepted_plan_digest")
    @classmethod
    def _validate_plan_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError(
                "accepted_plan_digest must be a lower-case SHA-256 reference"
            )
        return value

    @field_validator("escrow_uid")
    @classmethod
    def _validate_escrow(cls, value: str) -> str:
        if _OPAQUE_REF.fullmatch(value) is None:
            raise ValueError("escrow_uid must be a trimmed opaque token")
        return value

    @model_validator(mode="after")
    def _validate_selection(self) -> "BareMetalAcceptedAlkahestBinding":
        if (self.resource_selection == "specific") != (
            self.physical_resource_id is not None
        ):
            raise ValueError(
                "a specific-resource binding names its Physical Resource, "
                "and a fungible one does not"
            )
        return self

    @property
    def facts(self) -> "BareMetalAcceptedAlkahestBinding":
        """The physical facts, which this binding states itself."""
        return self

    @property
    def binding_digest(self) -> str:
        return bare_metal_digest(_binding_v1(self))


BareMetalAcceptedBinding = BareMetalAcceptedAlkahestBinding


class BareMetalLeaseReadyEvidence(BaseModel):
    """Portable condition evidence with no access or provider capability data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.lease-ready-evidence.v1"] = (
        BARE_METAL_LEASE_READY_EVIDENCE_KIND
    )
    accepted_binding_kind: Literal["bare_metal.accepted-alkahest-binding.v1"] = (
        BARE_METAL_ACCEPTED_ALKAHEST_BINDING_KIND
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

    @model_validator(mode="before")
    @classmethod
    def _validate_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict) and "result" in data and "result_digest" in data:
            result = data["result"]
            if isinstance(result, dict) and any(
                isinstance(result.get(name), datetime)
                for name in ("access_ready_at", "expires_at")
            ):
                result = BareMetalLeaseReadyResult.model_validate(result)
                data = {**data, "result": result}
            if isinstance(result, BareMetalLeaseReadyResult):
                result = _result_v1(result)
            if data["result_digest"] != bare_metal_digest(result):
                raise ValueError(
                    "evidence result digest does not match its public result"
                )
            if isinstance(data["result"], dict):
                data = {
                    **data,
                    "result": BareMetalLeaseReadyResult.model_validate_json(
                        json.dumps(data["result"])
                    ),
                }
        return data

    @property
    def evidence_digest(self) -> str:
        return bare_metal_digest(self)

    def canonical_json(self) -> str:
        return canonical_bare_metal_json(self)


def _principal_v1(value: CanonicalPrincipal) -> dict[str, str]:
    return {"scheme": value.scheme, "identifier": value.identifier}


def _timestamp_v1(value: datetime) -> str:
    return _V1_TIMESTAMP.dump_python(value, mode="json")


def _result_v1(value: BareMetalLeaseReadyResult) -> dict[str, Any]:
    """The fixed v1 wire grammar, independent of application-view defaults."""
    wire = {
        "kind": BARE_METAL_LEASE_READY_RESULT_KIND,
        "site_id": value.site_id,
        "offering_mode": value.offering_mode,
        "resource_selection": value.resource_selection,
        "capacity_reservation_ref": value.capacity_reservation_ref,
        "settlement_resource_ref": value.settlement_resource_ref,
        "fulfillment_ref": value.fulfillment_ref,
        "access_method": value.access_method,
        "access_ready": value.access_ready,
        "access_ready_at": _timestamp_v1(value.access_ready_at),
        "expires_at": _timestamp_v1(value.expires_at),
    }
    if value.physical_resource_id is not None:
        wire["physical_resource_id"] = value.physical_resource_id
    return wire


def _binding_v1(value: BareMetalAcceptedAlkahestBinding) -> dict[str, Any]:
    wire = {
        name: getattr(value, name)
        for name in (
            "kind",
            "agreement_ref",
            "negotiation_id",
            "listing_id",
            "obligation_ref",
            "escrow_uid",
            "accepted_plan_digest",
            "site_id",
            "offering_mode",
            "resource_selection",
            "physical_resource_id",
            "pool_id",
            "access_method",
        )
        if getattr(value, name) is not None
    }
    for name in ("buyer_principal", "seller_principal", "claimant_principal"):
        wire[name] = _principal_v1(getattr(value, name))
    return wire


def _verified_json(canonical_bytes: bytes, expected_digest: str) -> dict[str, Any]:
    if not isinstance(canonical_bytes, bytes):
        raise ValueError("canonical evidence must be UTF-8 bytes")
    if (
        not isinstance(expected_digest, str)
        or _SHA256.fullmatch(expected_digest) is None
    ):
        raise ValueError("expected digest must be a lower-case SHA-256 reference")
    actual = "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()
    if actual != expected_digest:
        raise ValueError("canonical document does not match expected digest")
    wire = json.loads(canonical_bytes.decode("utf-8"))
    if not isinstance(wire, dict):
        raise ValueError("canonical document must be a JSON object")
    if canonical_bare_metal_json(wire).encode("utf-8") != canonical_bytes:
        raise ValueError("document must use canonical bare-metal JSON")
    return wire


@dataclass(frozen=True, slots=True)
class BareMetalLeaseReadyResultDocument:
    """A verified public result representation and its separate application view."""

    canonical_bytes: bytes
    result_digest: str
    value: BareMetalLeaseReadyResult = field(init=False, compare=False)

    def __post_init__(self) -> None:
        wire = _verified_json(self.canonical_bytes, self.result_digest)
        # Literal validation normalizes numeric 1 to True; the retained v1 wire
        # permits only JSON true, or omission of its defaulted field.
        if "access_ready" in wire and wire["access_ready"] is not True:
            raise ValueError("lease-ready access_ready must be JSON true")
        value = BareMetalLeaseReadyResult.model_validate_json(json.dumps(wire))
        object.__setattr__(self, "value", value)

    def canonical_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    def to_wire(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)

    @property
    def kind(self) -> Literal["bare_metal.lease-ready-result.v1"]:
        return self.value.kind

    @property
    def site_id(self) -> str:
        return self.value.site_id

    @property
    def offering_mode(self) -> Literal["bare_metal"]:
        return self.value.offering_mode

    @property
    def resource_selection(self) -> ResourceSelection:
        return self.value.resource_selection

    @property
    def physical_resource_id(self) -> str | None:
        return self.value.physical_resource_id

    @property
    def capacity_reservation_ref(self) -> str:
        return self.value.capacity_reservation_ref

    @property
    def settlement_resource_ref(self) -> str:
        return self.value.settlement_resource_ref

    @property
    def fulfillment_ref(self) -> str:
        return self.value.fulfillment_ref

    @property
    def access_method(self) -> Literal["ssh"]:
        return self.value.access_method

    @property
    def access_ready(self) -> Literal[True]:
        return self.value.access_ready

    @property
    def access_ready_at(self) -> datetime:
        return self.value.access_ready_at

    @property
    def expires_at(self) -> datetime:
        return self.value.expires_at


@dataclass(frozen=True, slots=True)
class BareMetalLeaseReadyEvidenceDocument:
    """Retained proof bytes are authoritative; the validated view is for reads."""

    canonical_bytes: bytes
    evidence_digest: str
    value: BareMetalLeaseReadyEvidence = field(init=False, compare=False)
    result: BareMetalLeaseReadyResultDocument = field(init=False)

    def __post_init__(self) -> None:
        wire = _verified_json(self.canonical_bytes, self.evidence_digest)
        if "result" not in wire or "result_digest" not in wire:
            raise ValueError("evidence requires a result and its digest")
        # Verify the original nested representation before decoding either view.
        result = BareMetalLeaseReadyResultDocument(
            canonical_bare_metal_json(wire["result"]).encode("utf-8"),
            wire["result_digest"],
        )
        value = BareMetalLeaseReadyEvidence.model_validate_json(json.dumps(wire))
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "value", value)

    def canonical_json(self) -> str:
        return self.canonical_bytes.decode("utf-8")

    def to_wire(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)

    @classmethod
    def from_wire(cls, wire: Any) -> "BareMetalLeaseReadyEvidenceDocument":
        canonical_bytes = canonical_bare_metal_json(wire).encode("utf-8")
        return cls(canonical_bytes, bare_metal_digest(wire))

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        def validate(value: Any) -> "BareMetalLeaseReadyEvidenceDocument":
            if isinstance(value, cls):
                return value
            return cls.from_wire(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            json_schema_input_schema=handler.generate_schema(
                BareMetalLeaseReadyEvidence
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda document: document.to_wire(),
                when_used="always",
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> Any:
        return handler(schema["json_schema_input_schema"])

    @property
    def kind(self) -> Literal["bare_metal.lease-ready-evidence.v1"]:
        return self.value.kind

    @property
    def accepted_binding_kind(
        self,
    ) -> Literal["bare_metal.accepted-alkahest-binding.v1"]:
        return self.value.accepted_binding_kind

    @property
    def agreement_ref(self) -> str:
        return self.value.agreement_ref

    @property
    def obligation_ref(self) -> str:
        return self.value.obligation_ref

    @property
    def accepted_binding_digest(self) -> str:
        return self.value.accepted_binding_digest

    @property
    def fulfillment_identity(self) -> str:
        return self.value.fulfillment_identity

    @property
    def buyer_principal(self) -> CanonicalPrincipal:
        return self.value.buyer_principal

    @property
    def seller_principal(self) -> CanonicalPrincipal:
        return self.value.seller_principal

    @property
    def claimant_principal(self) -> CanonicalPrincipal:
        return self.value.claimant_principal

    @property
    def condition_anchor(self) -> str:
        return self.value.condition_anchor

    @property
    def result_digest(self) -> str:
        return self.value.result_digest


def derive_bare_metal_fulfillment_identity(
    binding: BareMetalAcceptedBinding,
) -> str:
    """Derive the stable physical fulfillment identity from accepted authority."""

    facts = binding.facts
    return bare_metal_digest(
        {
            "kind": "bare_metal.fulfillment-identity.v1",
            "agreement_ref": binding.agreement_ref,
            "obligation_ref": binding.obligation_ref,
            "accepted_binding_digest": binding.binding_digest,
            "buyer_principal": _principal_v1(binding.buyer_principal),
            "claimant_principal": _principal_v1(binding.claimant_principal),
            "site_id": facts.site_id,
            "offering_mode": facts.offering_mode,
            "resource_selection": facts.resource_selection,
            "physical_resource_id": facts.physical_resource_id,
            "pool_id": facts.pool_id,
        }
    )


def build_bare_metal_lease_ready_evidence(
    *,
    binding: BareMetalAcceptedBinding,
    condition_anchor: str,
    result: BareMetalLeaseReadyResult,
) -> BareMetalLeaseReadyEvidenceDocument:
    """Bind an authoritative public result to the exact accepted obligation."""

    facts = binding.facts
    if result.site_id != facts.site_id or result.offering_mode != facts.offering_mode:
        raise ValueError("lease-ready result conflicts with accepted site/executor")
    if result.resource_selection != facts.resource_selection:
        raise ValueError("lease-ready result changes accepted resource selection")
    if result.physical_resource_id != facts.physical_resource_id:
        raise ValueError("lease-ready result changes accepted Physical Resource")
    if result.access_method != facts.access_method:
        raise ValueError("lease-ready result changes accepted access method")
    wire = {
        "kind": BARE_METAL_LEASE_READY_EVIDENCE_KIND,
        "accepted_binding_kind": binding.kind,
        "agreement_ref": binding.agreement_ref,
        "obligation_ref": binding.obligation_ref,
        "accepted_binding_digest": binding.binding_digest,
        "fulfillment_identity": derive_bare_metal_fulfillment_identity(binding),
        "buyer_principal": _principal_v1(binding.buyer_principal),
        "seller_principal": _principal_v1(binding.seller_principal),
        "claimant_principal": _principal_v1(binding.claimant_principal),
        "condition_anchor": condition_anchor,
        "result": _result_v1(result),
        "result_digest": bare_metal_digest(_result_v1(result)),
    }
    return BareMetalLeaseReadyEvidenceDocument.from_wire(wire)


__all__ = [
    "BARE_METAL_ACCEPTED_ALKAHEST_BINDING_KIND",
    "BARE_METAL_LEASE_READY_EVIDENCE_KIND",
    "BARE_METAL_LEASE_READY_RESULT_KIND",
    "BareMetalAcceptedAlkahestBinding",
    "BareMetalAcceptedBinding",
    "BareMetalLeaseReadyEvidence",
    "BareMetalLeaseReadyEvidenceDocument",
    "BareMetalLeaseReadyResultDocument",
    "BareMetalLeaseReadyResult",
    "build_bare_metal_lease_ready_evidence",
    "derive_bare_metal_fulfillment_identity",
]
