"""Strict public contracts for marketplace identity and signed envelopes."""

from __future__ import annotations

import base64
import binascii
import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

REQUEST_PROTOCOL = "arkhai.market-request-signature.v2"
RESPONSE_PROTOCOL = "arkhai.market-response-signature.v2"
ROTATION_PROTOCOL = "arkhai.market-identity-rotation.v1"

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ED25519_PUBLIC_KEY_BYTES = 32
_ED25519_SIGNATURE_BYTES = 64
_EIP191_SIGNATURE_BYTES = 65


class IdentityScheme(str, Enum):
    """Identity schemes supported by the marketplace wire contract."""

    EIP191 = "eip191"
    ED25519 = "ed25519"


SchemeField = Annotated[IdentityScheme, Field(strict=False)]


class ContractModel(BaseModel):
    """Base for immutable, strict, closed public identity contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Identity(ContractModel):
    """A canonical scheme-tagged marketplace principal."""

    scheme: SchemeField
    identifier: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str, info: ValidationInfo) -> str:
        scheme = info.data.get("scheme")
        if scheme == IdentityScheme.EIP191:
            if not _ADDRESS.fullmatch(value):
                raise ValueError("eip191 identifier must be a 20-byte hexadecimal address")
            return value.lower()
        if scheme == IdentityScheme.ED25519:
            raw = _decode_base64url(value, field="ed25519 identifier")
            if len(raw) != _ED25519_PUBLIC_KEY_BYTES:
                raise ValueError("ed25519 identifier must encode a 32-byte public key")
            if value != _encode_base64url(raw):
                raise ValueError("ed25519 identifier must use canonical unpadded base64url")
            return value
        raise ValueError("unsupported identity scheme")


class TrustedIdentitySet(ContractModel):
    """One exact trust pin plus at most one overlapping rotation identity."""

    identities: tuple[Identity, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def identities_are_unique(self) -> TrustedIdentitySet:
        if len(set(self.identities)) != len(self.identities):
            raise ValueError("trusted identities must be unique")
        return self

    def allows(self, identity: Identity) -> bool:
        """Return whether the complete scheme-tagged identity is trusted."""

        return identity in self.identities

    def __contains__(self, identity: object) -> bool:
        return identity in self.identities


class SignatureProof(ContractModel):
    """A canonical, bounded, scheme-tagged signature encoding."""

    scheme: SchemeField
    value: str = Field(min_length=1, max_length=132)

    @model_validator(mode="after")
    def validate_value(self) -> SignatureProof:
        if self.scheme == IdentityScheme.EIP191:
            if not self.value.startswith("0x"):
                raise ValueError("eip191 proof must be 0x-prefixed hexadecimal")
            try:
                raw = bytes.fromhex(self.value[2:])
            except ValueError as exc:
                raise ValueError("eip191 proof must contain hexadecimal bytes") from exc
            if len(raw) != _EIP191_SIGNATURE_BYTES:
                raise ValueError("eip191 proof must contain a 65-byte signature")
            if self.value != "0x" + raw.hex():
                raise ValueError("eip191 proof must use canonical lowercase hexadecimal")
            return self

        raw = _decode_base64url(self.value, field="ed25519 proof")
        if len(raw) != _ED25519_SIGNATURE_BYTES:
            raise ValueError("ed25519 proof must encode a 64-byte signature")
        if self.value != _encode_base64url(raw):
            raise ValueError("ed25519 proof must use canonical unpadded base64url")
        return self

    @classmethod
    def from_bytes(cls, scheme: IdentityScheme, signature: bytes) -> SignatureProof:
        """Encode one raw signature using its scheme's canonical wire form."""

        if not isinstance(signature, bytes):
            raise TypeError("signature must be bytes")
        if scheme == IdentityScheme.EIP191:
            return cls(scheme=scheme, value="0x" + signature.hex())
        if scheme == IdentityScheme.ED25519:
            return cls(scheme=scheme, value=_encode_base64url(signature))
        raise ValueError("unsupported identity scheme")

    def to_bytes(self) -> bytes:
        """Decode the already-validated signature with a fixed upper bound."""

        if self.scheme == IdentityScheme.EIP191:
            return bytes.fromhex(self.value[2:])
        return _decode_base64url(self.value, field="ed25519 proof")


class RequestEnvelope(ContractModel):
    """Unsigned canonical marketplace request fields."""

    protocol: Literal[REQUEST_PROTOCOL] = REQUEST_PROTOCOL
    role: str = Field(min_length=1, max_length=64)
    principal: Identity
    method: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    resource: str = Field(max_length=1024)
    request_id: str = Field(min_length=1, max_length=128)
    timestamp: int = Field(ge=0, le=9_223_372_036_854_775_807)
    body_hash: str

    @field_validator("role", "operation")
    @classmethod
    def validate_token(cls, value: str, info: ValidationInfo) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a bounded ASCII token")
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        if not _REQUEST_ID.fullmatch(value):
            raise ValueError("request_id must be a bounded ASCII token")
        return value

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        if not value.isascii() or not value.isalpha():
            raise ValueError("method must contain only ASCII letters")
        return value.upper()

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("resource must not contain NUL")
        return value

    @field_validator("body_hash")
    @classmethod
    def validate_body_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("body_hash must be a lowercase SHA-256 hexadecimal digest")
        return value


class AuthenticatedRequest(RequestEnvelope):
    """A request envelope carrying a proof by its declared principal."""

    proof: SignatureProof

    @model_validator(mode="after")
    def proof_matches_principal(self) -> AuthenticatedRequest:
        if self.proof.scheme != self.principal.scheme:
            raise ValueError("proof scheme must match principal scheme")
        return self


class ResponseEnvelope(ContractModel):
    """Unsigned canonical marketplace response fields."""

    protocol: Literal[RESPONSE_PROTOCOL] = RESPONSE_PROTOCOL
    role: str = Field(min_length=1, max_length=64)
    principal: Identity
    method: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    resource: str = Field(max_length=1024)
    request_id: str = Field(min_length=1, max_length=128)
    timestamp: int = Field(ge=0, le=9_223_372_036_854_775_807)
    status: int = Field(ge=100, le=599)
    body_hash: str

    @field_validator("role", "operation")
    @classmethod
    def validate_token(cls, value: str, info: ValidationInfo) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a bounded ASCII token")
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        if not _REQUEST_ID.fullmatch(value):
            raise ValueError("request_id must be a bounded ASCII token")
        return value

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        if not value.isascii() or not value.isalpha():
            raise ValueError("method must contain only ASCII letters")
        return value.upper()

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("resource must not contain NUL")
        return value

    @field_validator("body_hash")
    @classmethod
    def validate_body_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("body_hash must be a lowercase SHA-256 hexadecimal digest")
        return value


class AuthenticatedResponse(ResponseEnvelope):
    """A response envelope carrying a proof by its declared principal."""

    proof: SignatureProof

    @model_validator(mode="after")
    def proof_matches_principal(self) -> AuthenticatedResponse:
        if self.proof.scheme != self.principal.scheme:
            raise ValueError("proof scheme must match principal scheme")
        return self


class ReplayIdentity(ContractModel):
    """The complete namespace used by an authority's replay store."""

    principal: Identity
    request_id: str = Field(min_length=1, max_length=128)

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        if not _REQUEST_ID.fullmatch(value):
            raise ValueError("request_id must be a bounded ASCII token")
        return value


class ReplayReservation(ContractModel):
    """Persistence-neutral replay value for one authenticated request."""

    identity: ReplayIdentity
    request_hash: str

    @field_validator("request_hash")
    @classmethod
    def validate_request_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("request_hash must be a lowercase SHA-256 digest")
        return value


class RotationIntent(ContractModel):
    """One canonical ownership intent signed by current and replacement keys."""

    protocol: Literal[ROTATION_PROTOCOL] = ROTATION_PROTOCOL
    current: Identity
    replacement: Identity
    subject: str = Field(min_length=1, max_length=256)
    authority: str = Field(min_length=1, max_length=256)
    nonce: str = Field(min_length=1, max_length=128)
    overlap_seconds: int = Field(ge=0, le=2_592_000)
    expires_at: int = Field(gt=0, le=9_223_372_036_854_775_807)

    @field_validator("subject", "authority", "nonce")
    @classmethod
    def validate_text(cls, value: str, info: ValidationInfo) -> str:
        if "\x00" in value:
            raise ValueError(f"{info.field_name} must not contain NUL")
        return value

    @model_validator(mode="after")
    def identities_differ(self) -> RotationIntent:
        if self.current == self.replacement:
            raise ValueError("replacement identity must differ from current identity")
        return self


class RotationRequest(ContractModel):
    """A rotation intent with independent possession proofs from both identities."""

    intent: RotationIntent
    current_proof: SignatureProof
    replacement_proof: SignatureProof

    @model_validator(mode="after")
    def proofs_match_identities(self) -> RotationRequest:
        if self.current_proof.scheme != self.intent.current.scheme:
            raise ValueError("current proof scheme must match current identity")
        if self.replacement_proof.scheme != self.intent.replacement.scheme:
            raise ValueError("replacement proof scheme must match replacement identity")
        return self


def _decode_base64url(value: str, *, field: str) -> bytes:
    if not _BASE64URL.fullmatch(value):
        raise ValueError(f"{field} must contain only base64url characters")
    if len(value) > 342:
        raise ValueError(f"{field} exceeds the decoding bound")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{field} is not valid base64url") from exc


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
