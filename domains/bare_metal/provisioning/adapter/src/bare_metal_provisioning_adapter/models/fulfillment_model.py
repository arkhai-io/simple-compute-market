"""Bare-metal fulfillment provider carriers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class BareMetalAnsibleJobParams:
    """Domain-owned Ansible command understood by the shared job boundary."""

    vm_host: str
    vm_action: str
    vm_target: str
    executor_kind: str
    executor_action: str
    executor_target: str
    executor_ref: dict[str, Any]
    escrow_uid: str
    physical_host_id: str
    ssh_public_key: str | None
    access_ref: dict[str, Any] | None
    playbook_path: str
    provider_extra_vars: dict[str, Any] = field(default_factory=dict)
    max_retries: int | None = None


class BareMetalFulfillmentMetadata(BaseModel):
    """Opaque operational state retained by generic fulfillment."""

    model_config = ConfigDict(extra="forbid")

    create_job_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
    machine_id: str = Field(min_length=1)
    physical_host_id: str = Field(min_length=1)
    operation: Literal["create", "teardown"]
    teardown_job_id: str | None = None
