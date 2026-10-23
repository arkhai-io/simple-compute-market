"""Canonical, signed, secret-free issuance evidence, and the portable reference to its digest."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Self

from market_identity import (
    Identity,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_json,
    get_identity_verifier,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from arkhai_api.labels import IssuanceLabel

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_MAX_EVIDENCE_BYTES = 32_768
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class IssuanceEvidenceError(ValueError):
    """Signed evidence is malformed, untrusted, stale, under another label, or semantically different."""


class _EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class IssuanceEvidenceBodyV1(_EvidenceContract):
    """The public issuance fact a storefront signs; ``domain`` is the issuing label's name."""

    protocol: str = Field(pattern=r"^arkhai\.[a-z0-9-]+\.issuance-evidence\.v1$")
    schema_version: Literal["1"] = "1"
    capability: str = Field(pattern=r"^[a-z0-9-]+\.issuance\.v1$")
    domain: str
    condition_anchor: str = Field(min_length=1, max_length=512)
    obligation_ref: str = Field(min_length=1, max_length=255)
    fulfillment_id: str = Field(min_length=1, max_length=320)
    grant_id: str = Field(min_length=1, max_length=320)
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"]
    key_id: str = Field(min_length=1, max_length=255)
    owner: Identity
    buyer: Identity
    claimant: Identity
    issuer: Identity
    status: Literal["committed"] = "committed"
    committed_at_unix: int = Field(ge=0)
    request_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="before")
    @classmethod
    def _spell_protocol_and_capability(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        try:
            label = IssuanceLabel(value.get("domain"))
        except (TypeError, ValueError):
            return value
        return {"protocol": label.evidence_protocol, "capability": label.evidence_capability, **value}

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        label = IssuanceLabel(self.domain)
        if (self.protocol, self.capability) != (label.evidence_protocol, label.evidence_capability):
            raise ValueError("protocol and capability must spell the evidence domain")
        for field_name in ("condition_anchor", "obligation_ref", "fulfillment_id"):
            if not _SAFE_REF.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a safe opaque reference")
        if self.grant_id != self.fulfillment_id:
            raise ValueError("grant_id must equal fulfillment_id")
        if self.owner != self.buyer:
            raise ValueError("key owner must equal the accepted canonical buyer")
        return self


class SignedIssuanceEvidenceV1(_EvidenceContract):
    """Evidence body plus one scheme-matched marketplace signature."""

    body: IssuanceEvidenceBodyV1
    proof: SignatureProof

    @model_validator(mode="after")
    def proof_matches_issuer(self) -> Self:
        if self.proof.scheme != self.body.issuer.scheme:
            raise ValueError("evidence proof scheme does not match issuer")
        return self


class ExpectedIssuanceEvidenceV1(_EvidenceContract):
    """Exact accepted facts a condition resolver must match."""

    condition_anchor: str
    obligation_ref: str
    fulfillment_id: str
    grant_id: str
    service: str
    resource_id: str
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"]
    key_id: str
    owner: Identity
    buyer: Identity
    claimant: Identity
    issuer: Identity
    request_digest: str = Field(pattern=DIGEST_PATTERN)
    funding_expiration_unix: int = Field(ge=0)


class PortableFulfillmentRefV1(_EvidenceContract):
    """Safe common-runtime reference to digest-only issuance publication."""

    schema: str = Field(pattern=r"^arkhai\.[a-z0-9-]+\.portable-fulfillment-ref\.v1$")
    resolver_id: str = Field(min_length=1, max_length=255)
    attestation_uid: str = Field(min_length=1, max_length=512)
    evidence_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_safe_refs(self) -> Self:
        if not _SAFE_REF.fullmatch(self.resolver_id):
            raise ValueError("resolver_id must be a safe opaque reference")
        if not _SAFE_REF.fullmatch(self.attestation_uid):
            raise ValueError("attestation_uid must be a safe opaque reference")
        return self


def _under_label(label: IssuanceLabel, body: IssuanceEvidenceBodyV1) -> None:
    if body.domain != label.name:
        raise IssuanceEvidenceError("issuance evidence is under another label")


def _signing_bytes(body: IssuanceEvidenceBodyV1) -> bytes:
    return body.protocol.encode() + b"\0" + canonical_json(body.model_dump(mode="json"))


def sign_issuance_evidence(
    label: IssuanceLabel,
    body: IssuanceEvidenceBodyV1,
    signer: Signer,
) -> SignedIssuanceEvidenceV1:
    """Sign one canonical evidence body under its label with its declared issuer."""

    _under_label(label, body)
    if signer.identity != body.issuer:
        raise IssuanceEvidenceError("evidence signer does not match issuer")
    proof = SignatureProof.from_bytes(signer.identity.scheme, signer.sign(_signing_bytes(body)))
    return SignedIssuanceEvidenceV1(body=body, proof=proof)


def canonical_signed_issuance_evidence(evidence: SignedIssuanceEvidenceV1) -> str:
    """The signed object in the only admitted JSON representation."""

    return canonical_json(evidence.model_dump(mode="json")).decode("utf-8")


def issuance_evidence_digest(label: IssuanceLabel, evidence: SignedIssuanceEvidenceV1) -> str:
    _under_label(label, evidence.body)
    encoded = canonical_signed_issuance_evidence(evidence).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def decode_signed_issuance_evidence(
    label: IssuanceLabel,
    value: str | bytes,
) -> SignedIssuanceEvidenceV1:
    """Decode bounded canonical evidence under ``label``, rejecting alternate JSON encodings."""

    raw = value.encode("utf-8") if isinstance(value, str) else value
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise IssuanceEvidenceError("issuance evidence exceeds size limit")
    try:
        evidence = SignedIssuanceEvidenceV1.model_validate(json.loads(raw))
    except (TypeError, ValueError) as exc:
        raise IssuanceEvidenceError("invalid signed issuance evidence") from exc
    _under_label(label, evidence.body)
    if canonical_signed_issuance_evidence(evidence).encode("utf-8") != raw:
        raise IssuanceEvidenceError("issuance evidence must use canonical JSON")
    return evidence


def verify_issuance_evidence(
    label: IssuanceLabel,
    evidence: SignedIssuanceEvidenceV1,
    *,
    expected: ExpectedIssuanceEvidenceV1,
    trusted_issuers: TrustedIdentitySet,
    now_unix: int,
    max_future_skew_seconds: int = 30,
) -> IssuanceEvidenceBodyV1:
    """Verify label, signature, trust, timeliness, and every accepted field."""

    body = evidence.body
    _under_label(label, body)
    if body.issuer not in trusted_issuers or body.issuer != expected.issuer:
        raise IssuanceEvidenceError("issuance evidence issuer is not trusted")
    verifier = get_identity_verifier(body.issuer.scheme)
    if not verifier.verify_signature(body.issuer, _signing_bytes(body), evidence.proof.to_bytes()):
        raise IssuanceEvidenceError("issuance evidence signature is invalid")
    if body.committed_at_unix > expected.funding_expiration_unix:
        raise IssuanceEvidenceError("credit grant committed after funding expiry")
    if body.committed_at_unix > now_unix + max_future_skew_seconds:
        raise IssuanceEvidenceError("credit grant commitment time is in the future")
    for field_name in (
        "condition_anchor",
        "obligation_ref",
        "fulfillment_id",
        "grant_id",
        "service",
        "resource_id",
        "quantity",
        "key_mode",
        "key_id",
        "owner",
        "buyer",
        "claimant",
        "request_digest",
    ):
        if getattr(body, field_name) != getattr(expected, field_name):
            raise IssuanceEvidenceError(
                f"issuance evidence {field_name} does not match accepted obligation"
            )
    return body


def encode_portable_fulfillment_ref(
    label: IssuanceLabel,
    *,
    resolver_id: str,
    attestation_uid: str,
    evidence_digest: str,
) -> str:
    ref = PortableFulfillmentRefV1(
        schema=label.portable_fulfillment_ref_schema,
        resolver_id=resolver_id,
        attestation_uid=attestation_uid,
        evidence_digest=evidence_digest,
    )
    return canonical_json(ref.model_dump(mode="json")).decode("utf-8")


def decode_portable_fulfillment_ref(label: IssuanceLabel, value: str) -> PortableFulfillmentRefV1:
    try:
        ref = PortableFulfillmentRefV1.model_validate(json.loads(value))
    except (TypeError, ValueError) as exc:
        raise IssuanceEvidenceError("invalid portable issuance fulfillment reference") from exc
    if ref.schema != label.portable_fulfillment_ref_schema:
        raise IssuanceEvidenceError("portable issuance fulfillment reference is under another label")
    if canonical_json(ref.model_dump(mode="json")).decode("utf-8") != value:
        raise IssuanceEvidenceError("portable issuance fulfillment reference must use canonical JSON")
    return ref
