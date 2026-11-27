"""Authenticated encryption for registry-owned RFQ contact payloads."""

from dataclasses import dataclass, field
from datetime import datetime
from os import urandom
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from market_core.rfq import RfqContact, RfqReference
from market_identity import canonical_json
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError, model_validator

ContactPurpose = Literal["pending-respondent", "introduction-respondent", "introduction-buyer"]
PENDING_CONTACT: ContactPurpose = "pending-respondent"
RESPONDENT_CONTACT: ContactPurpose = "introduction-respondent"
BUYER_CONTACT: ContactPurpose = "introduction-buyer"
_FORMAT_VERSION = 1
_NONCE_BYTES = 12
_contact: TypeAdapter[dict[str, str]] = TypeAdapter(RfqContact)


class RfqContactUnavailable(Exception):
    """A configured key or authenticated contact payload could not be used."""


@dataclass(frozen=True)
class ContactBinding:
    registry: str
    rfq_id: str
    record_id: str
    party_namespace: str
    party_subject: str = field(repr=False)
    purpose: ContactPurpose
    expires_at: datetime

    def associated_data(self) -> bytes:
        return canonical_json({
            "protocol": "arkhai.rfq-contact.v1",
            "registry": self.registry,
            "rfq_id": self.rfq_id,
            "record_id": self.record_id,
            "party_namespace": self.party_namespace,
            "party_subject": self.party_subject,
            "purpose": self.purpose,
            "expires_at": self.expires_at.isoformat(),
        })


@dataclass(frozen=True)
class EncryptedContact:
    format_version: int
    key_id: str
    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)


class RfqContactKeys(BaseModel):
    """A keyring whose current writer and retained readers live outside the database."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True, frozen=True)

    current: RfqReference
    keys: dict[RfqReference, SecretStr] = Field(repr=False)

    @model_validator(mode="after")
    def validate_keys(self) -> "RfqContactKeys":
        if self.current not in self.keys:
            raise ValueError("the current RFQ contact key is missing")
        for key in self.keys.values():
            value = key.get_secret_value()
            if len(value) != 64 or len(bytes.fromhex(value)) != 32:
                raise ValueError("RFQ contact keys require 32 bytes")
        return self

    @classmethod
    def load(cls, path: str) -> "RfqContactKeys":
        try:
            return cls.model_validate_json(Path(path).read_bytes())
        except (OSError, ValueError):
            raise RuntimeError("cannot load REGISTRY_RFQ_CONTACT_KEYS_FILE") from None

    def _cipher(self, key_id: str) -> AESGCM:
        key = self.keys.get(key_id)
        if key is None:
            raise RfqContactUnavailable("RFQ contact key unavailable")
        return AESGCM(bytes.fromhex(key.get_secret_value()))

    def encrypt(self, contact: dict[str, str], binding: ContactBinding) -> EncryptedContact:
        nonce = urandom(_NONCE_BYTES)
        ciphertext = self._cipher(self.current).encrypt(
            nonce, canonical_json(contact), binding.associated_data(),
        )
        return EncryptedContact(_FORMAT_VERSION, self.current, nonce, ciphertext)

    def decrypt(self, encrypted: EncryptedContact, binding: ContactBinding) -> dict[str, str]:
        if encrypted.format_version != _FORMAT_VERSION or len(encrypted.nonce) != _NONCE_BYTES:
            raise RfqContactUnavailable("RFQ contact format unavailable")
        try:
            raw = self._cipher(encrypted.key_id).decrypt(
                encrypted.nonce, encrypted.ciphertext, binding.associated_data(),
            )
            return _contact.validate_json(raw, strict=True)
        except (InvalidTag, ValidationError, ValueError):
            raise RfqContactUnavailable("RFQ contact could not be authenticated") from None
