"""Portable registry self-description carriers."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ED25519_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]")
_EIP191_IDENTIFIER = re.compile(r"0x[0-9a-f]{40}")
_AUTHORITY_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*")
_SCHEMA_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")


class _StrictCarrier(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RegistryPrincipal(_StrictCarrier):
    """Canonical public principal carried by a registry descriptor."""

    scheme: Literal["ed25519", "eip191"]
    identifier: str

    @model_validator(mode="after")
    def validate_identifier(self) -> RegistryPrincipal:
        pattern = (
            _ED25519_IDENTIFIER if self.scheme == "ed25519" else _EIP191_IDENTIFIER
        )
        if pattern.fullmatch(self.identifier) is None:
            raise ValueError(f"invalid {self.scheme} registry principal")
        return self


class RegistryAuthorityDescriptor(_StrictCarrier):
    """Stable authority name and its ordered active trust pins."""

    name: str = Field(min_length=1, max_length=64, pattern=_AUTHORITY_NAME.pattern)
    principals: tuple[RegistryPrincipal, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_unique_principals(self) -> RegistryAuthorityDescriptor:
        identities = {(item.scheme, item.identifier) for item in self.principals}
        if len(identities) != len(self.principals):
            raise ValueError("registry authority principals must be unique")
        return self


class PublicRegistryAccess(_StrictCarrier):
    posture: Literal["public"] = "public"


class KeyGatedRegistryAccess(_StrictCarrier):
    posture: Literal["key-gated"] = "key-gated"
    acquisition_pointer: str = Field(alias="acquisitionPointer", max_length=2_048)

    @field_validator("acquisition_pointer")
    @classmethod
    def validate_acquisition_pointer(cls, value: str) -> str:
        return _http_url(value, "registry access acquisition pointer")


RegistryAccess = Annotated[
    PublicRegistryAccess | KeyGatedRegistryAccess,
    Field(discriminator="posture"),
]


class RegistrySchemaDescriptor(_StrictCarrier):
    id: str = Field(min_length=1, max_length=128, pattern=_SCHEMA_TOKEN.pattern)
    version: str = Field(min_length=1, max_length=64, pattern=_SCHEMA_TOKEN.pattern)


class RegistryDescriptor(_StrictCarrier):
    """One operator-authored registry description on the public wire."""

    access: RegistryAccess
    authority: RegistryAuthorityDescriptor
    base_url: str = Field(alias="baseUrl", max_length=2_048)
    display_name: str = Field(alias="displayName", min_length=1, max_length=256)
    operator_identity: str = Field(
        alias="operatorIdentity",
        min_length=1,
        max_length=256,
    )
    schema_identity: RegistrySchemaDescriptor = Field(alias="schema")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _http_url(value, "registry base URL").rstrip("/")

    @field_validator("display_name", "operator_identity")
    @classmethod
    def normalize_bounded_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("registry descriptor text must be nonempty")
        return normalized

    def to_wire(self) -> dict[str, object]:
        """Return the exact camel-case JSON object carried over HTTP."""

        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


def _http_url(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must use HTTP or HTTPS")
    return value
