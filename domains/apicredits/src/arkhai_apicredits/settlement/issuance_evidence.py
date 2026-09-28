"""Canonical, signed, secret-free API-credit issuance evidence."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal, Self

from market_identity import (
    Identity,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_json,
    get_identity_verifier,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

EVIDENCE_PROTOCOL = "arkhai.api-credits.issuance-evidence.v1"
EVIDENCE_CAPABILITY = "api-credits.issuance.v1"
PORTABLE_FULFILLMENT_REF_SCHEMA = "arkhai.api-credits.portable-fulfillment-ref.v1"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_EVIDENCE_BYTES = 32_768


class IssuanceEvidenceError(ValueError):
    """Signed evidence is malformed, untrusted, stale, or semantically different."""


class _EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApiCreditsIssuanceEvidenceBodyV1(_EvidenceContract):
    """Public issuance fact signed by the API-credit storefront authority."""

    protocol: Literal["arkhai.api-credits.issuance-evidence.v1"] = EVIDENCE_PROTOCOL
    schema_version: Literal["1"] = "1"
    capability: Literal["api-credits.issuance.v1"] = EVIDENCE_CAPABILITY
    domain: Literal["api-credits"] = "api-credits"
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
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        for field_name in ("condition_anchor", "obligation_ref", "fulfillment_id"):
            if not _SAFE_REF.fullmatch(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a safe opaque reference")
        if self.grant_id != self.fulfillment_id:
            raise ValueError("grant_id must equal fulfillment_id")
        if self.owner != self.buyer:
            raise ValueError("key owner must equal the accepted canonical buyer")
        return self


class SignedApiCreditsIssuanceEvidenceV1(_EvidenceContract):
    """Evidence body plus one scheme-matched marketplace signature."""

    body: ApiCreditsIssuanceEvidenceBodyV1
    proof: SignatureProof

    @model_validator(mode="after")
    def proof_matches_issuer(self) -> Self:
        if self.proof.scheme != self.body.issuer.scheme:
            raise ValueError("evidence proof scheme does not match issuer")
        return self


class ExpectedApiCreditsIssuanceEvidenceV1(_EvidenceContract):
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
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    funding_expiration_unix: int = Field(ge=0)


class PortableApiCreditsFulfillmentRefV1(_EvidenceContract):
    """Safe common-runtime reference to digest-only hosted publication."""

    schema: Literal[
        "arkhai.api-credits.portable-fulfillment-ref.v1"
    ] = PORTABLE_FULFILLMENT_REF_SCHEMA
    resolver_id: str = Field(min_length=1, max_length=255)
    attestation_uid: str = Field(min_length=1, max_length=512)
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_safe_refs(self) -> Self:
        if not _SAFE_REF.fullmatch(self.resolver_id):
            raise ValueError("resolver_id must be a safe opaque reference")
        if not _SAFE_REF.fullmatch(self.attestation_uid):
            raise ValueError("attestation_uid must be a safe opaque reference")
        return self


def _evidence_signing_bytes(body: ApiCreditsIssuanceEvidenceBodyV1) -> bytes:
    return EVIDENCE_PROTOCOL.encode() + b"\0" + canonical_json(
        body.model_dump(mode="json")
    )


def sign_api_credits_issuance_evidence(
    body: ApiCreditsIssuanceEvidenceBodyV1,
    signer: Signer,
) -> SignedApiCreditsIssuanceEvidenceV1:
    """Sign one canonical evidence body with its declared issuer."""

    if signer.identity != body.issuer:
        raise IssuanceEvidenceError("evidence signer does not match issuer")
    proof = SignatureProof.from_bytes(
        signer.identity.scheme,
        signer.sign(_evidence_signing_bytes(body)),
    )
    return SignedApiCreditsIssuanceEvidenceV1(body=body, proof=proof)


def canonical_signed_issuance_evidence(
    evidence: SignedApiCreditsIssuanceEvidenceV1,
) -> str:
    """Encode the signed object in the only admitted JSON representation."""

    return canonical_json(evidence.model_dump(mode="json")).decode("utf-8")


def issuance_evidence_digest(
    evidence: SignedApiCreditsIssuanceEvidenceV1,
) -> str:
    """Return the digest published to the hosted conditional authority."""

    encoded = canonical_signed_issuance_evidence(evidence).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def decode_signed_issuance_evidence(
    value: str | bytes,
) -> SignedApiCreditsIssuanceEvidenceV1:
    """Decode bounded canonical evidence and reject alternate JSON encodings."""

    raw = value.encode("utf-8") if isinstance(value, str) else value
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise IssuanceEvidenceError("issuance evidence exceeds size limit")
    try:
        decoded = json.loads(raw)
        evidence = SignedApiCreditsIssuanceEvidenceV1.model_validate(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IssuanceEvidenceError("invalid signed issuance evidence") from exc
    if canonical_signed_issuance_evidence(evidence).encode("utf-8") != raw:
        raise IssuanceEvidenceError("issuance evidence must use canonical JSON")
    return evidence


def verify_api_credits_issuance_evidence(
    evidence: SignedApiCreditsIssuanceEvidenceV1,
    *,
    expected: ExpectedApiCreditsIssuanceEvidenceV1,
    trusted_issuers: TrustedIdentitySet,
    now_unix: int,
    max_future_skew_seconds: int = 30,
) -> ApiCreditsIssuanceEvidenceBodyV1:
    """Verify signature, trust, timeliness, digest, and every accepted field."""

    body = evidence.body
    if body.issuer not in trusted_issuers or body.issuer != expected.issuer:
        raise IssuanceEvidenceError("issuance evidence issuer is not trusted")
    verifier = get_identity_verifier(body.issuer.scheme)
    if not verifier.verify_signature(
        body.issuer,
        _evidence_signing_bytes(body),
        evidence.proof.to_bytes(),
    ):
        raise IssuanceEvidenceError("issuance evidence signature is invalid")
    if body.committed_at_unix > expected.funding_expiration_unix:
        raise IssuanceEvidenceError("credit grant committed after funding expiry")
    if body.committed_at_unix > now_unix + max_future_skew_seconds:
        raise IssuanceEvidenceError("credit grant commitment time is in the future")

    fields = (
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
    )
    for field_name in fields:
        if getattr(body, field_name) != getattr(expected, field_name):
            raise IssuanceEvidenceError(
                f"issuance evidence {field_name} does not match accepted obligation"
            )
    return body


def encode_portable_issuance_fulfillment_ref(
    *,
    resolver_id: str,
    attestation_uid: str,
    evidence_digest: str,
) -> str:
    ref = PortableApiCreditsFulfillmentRefV1(
        resolver_id=resolver_id,
        attestation_uid=attestation_uid,
        evidence_digest=evidence_digest,
    )
    return canonical_json(ref.model_dump(mode="json")).decode("utf-8")


def decode_portable_issuance_fulfillment_ref(
    value: str,
) -> PortableApiCreditsFulfillmentRefV1:
    try:
        decoded = json.loads(value)
        ref = PortableApiCreditsFulfillmentRefV1.model_validate(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise IssuanceEvidenceError("invalid portable issuance fulfillment reference") from exc
    if canonical_json(ref.model_dump(mode="json")).decode("utf-8") != value:
        raise IssuanceEvidenceError(
            "portable issuance fulfillment reference must use canonical JSON"
        )
    return ref
