"""Versioned negotiation envelope for bare-metal provision inputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BARE_METAL_PROVISION_KIND = "bare_metal.v1"
BARE_METAL_PROVISION_VERSION = 1
SSH_ACCESS_METHOD = "ssh"


class BareMetalProvisionPayload(BaseModel):
    """Domain-owned payload schema for bare-metal provision envelope v1."""

    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(ge=1)
    access_method: Literal["ssh"] = SSH_ACCESS_METHOD
    ssh_public_key: str = Field(min_length=1)

    @field_validator("ssh_public_key")
    @classmethod
    def _validate_ssh_public_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ssh_public_key must be non-empty")
        return value


class BareMetalProvisionTerms(BaseModel):
    """Bare-metal provision envelope with independently versioned payload."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bare_metal.v1"] = BARE_METAL_PROVISION_KIND
    version: Literal[1] = BARE_METAL_PROVISION_VERSION
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return BareMetalProvisionPayload.model_validate(value).model_dump(
            exclude_none=True,
        )


def make_bare_metal_provision_terms(
    *,
    duration_seconds: int,
    ssh_public_key: str,
) -> BareMetalProvisionTerms:
    """Build the canonical v1 envelope for buyer negotiation input."""
    return BareMetalProvisionTerms(
        payload={
            "duration_seconds": duration_seconds,
            "access_method": SSH_ACCESS_METHOD,
            "ssh_public_key": ssh_public_key,
        },
    )
