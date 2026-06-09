"""VM provision-term construction."""

from typing import Any

from pydantic import BaseModel, Field


VM_PROVISION_KIND = "compute.v1"


class VmProvisionTerms(BaseModel):
    """VM-domain provision terms matching the compute.v1 wire shape."""

    kind: str = Field(default=VM_PROVISION_KIND)
    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_seconds(self) -> int | None:
        raw = self.payload.get("duration_seconds")
        return int(raw) if raw is not None else None

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
) -> VmProvisionTerms:
    return VmProvisionTerms(
        payload={
            "duration_seconds": int(duration_seconds),
            "ssh_public_key": ssh_public_key,
        },
    )
