"""Versioned negotiation envelope for bare-metal provision inputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BARE_METAL_PROVISION_KIND = "bare_metal.v1"
BARE_METAL_PROVISION_VERSION = 1
SSH_ACCESS_METHOD = "ssh"


class BareMetalProvisionPayload(BaseModel):
    """Domain-owned payload schema for bare-metal provision envelope v1."""

    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(ge=1)
    # "none" is the non-provisioning shape: a settlement that completes with
    # no machine access (an introduction deal). Every provisioning path
    # re-requires SSH credentials at its own admission arm.
    access_method: Literal["ssh", "none"] = SSH_ACCESS_METHOD
    ssh_public_key: str | None = Field(default=None, min_length=1)

    @field_validator("ssh_public_key")
    @classmethod
    def _validate_ssh_public_key(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ssh_public_key must be non-empty when supplied")
        return value

    @model_validator(mode="after")
    def _validate_access(self) -> "BareMetalProvisionPayload":
        if self.access_method == SSH_ACCESS_METHOD and self.ssh_public_key is None:
            raise ValueError("ssh_public_key is required for SSH access")
        if self.access_method != SSH_ACCESS_METHOD and self.ssh_public_key:
            raise ValueError("ssh_public_key applies only to SSH access")
        return self


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
