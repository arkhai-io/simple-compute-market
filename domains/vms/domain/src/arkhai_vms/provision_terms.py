"""VM provision-term construction."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


VM_PROVISION_KIND = "compute.v1"
VM_PROVISION_VERSION = 1


class VmProvisionPayload(BaseModel):
    """Domain-owned payload schema for VM provision envelope version 1."""

    model_config = ConfigDict(extra="forbid")

    duration_seconds: int = Field(gt=0)
    ssh_public_key: str = ""
    start_utc: str | None = None
    compute_resource: dict[str, Any] | None = None


class VmProvisionTerms(BaseModel):
    """VM provision envelope with independently versioned payload."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["compute.v1"] = VM_PROVISION_KIND
    version: Literal[1] = VM_PROVISION_VERSION
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return VmProvisionPayload.model_validate(value).model_dump(
            exclude_none=True,
        )

    @property
    def duration_seconds(self) -> int | None:
        raw = self.payload.get("duration_seconds")
        return int(raw) if raw is not None else None

    @property
    def start_utc(self) -> str | None:
        raw = self.payload.get("start_utc")
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    @property
    def ssh_public_key(self) -> str:
        raw = self.payload.get("ssh_public_key")
        return raw if isinstance(raw, str) else ""

    @property
    def compute_resource(self) -> dict[str, Any] | None:
        raw = self.payload.get("compute_resource")
        return raw if isinstance(raw, dict) else None


def make_vm_provision_terms(
    *,
    duration_seconds: int,
    ssh_public_key: str,
    start_utc: str | None = None,
    compute_resource: dict[str, Any] | None = None,
) -> VmProvisionTerms:
    payload: dict[str, Any] = {
        "duration_seconds": int(duration_seconds),
        "ssh_public_key": ssh_public_key,
    }
    if start_utc is not None:
        payload["start_utc"] = str(start_utc)
    if compute_resource is not None:
        payload["compute_resource"] = compute_resource
    return VmProvisionTerms(payload=payload)

def normalize_vm_provision_terms(terms: Any) -> VmProvisionTerms:
    """Validate either a wire envelope or its durably decoded VM payload."""

    if isinstance(terms, dict) and "payload" in terms:
        return VmProvisionTerms.model_validate(terms)
    payload = VmProvisionPayload.model_validate(terms).model_dump(exclude_none=True)
    return VmProvisionTerms(payload=payload)


# ---------------------------------------------------------------------------
# compute.v1 payload accessors
# ---------------------------------------------------------------------------
# Wire-received provision terms arrive as the core opaque carrier
# (market_core.schemas.ProvisionTerms) or a plain dict; the core model
# does not interpret the payload. These functions are the VM domain's
# interpretation of the compute.v1 payload shape, accepting any carrier
# with a ``payload`` attribute or key.


def provision_payload(terms: Any) -> dict[str, Any]:
    if isinstance(terms, dict):
        raw = terms.get("payload")
    else:
        raw = getattr(terms, "payload", None)
    return raw if isinstance(raw, dict) else {}


def provision_duration_seconds(terms: Any) -> int | None:
    raw = provision_payload(terms).get("duration_seconds")
    return int(raw) if raw is not None else None


def provision_start_utc(terms: Any) -> str | None:
    raw = provision_payload(terms).get("start_utc")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def provision_ssh_public_key(terms: Any) -> str:
    raw = provision_payload(terms).get("ssh_public_key")
    return raw if isinstance(raw, str) else ""


def provision_compute_resource(terms: Any) -> dict[str, Any] | None:
    raw = provision_payload(terms).get("compute_resource")
    return raw if isinstance(raw, dict) else None
