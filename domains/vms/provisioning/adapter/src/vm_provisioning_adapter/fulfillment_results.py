"""Versioned VM-domain fulfillment result payloads."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from market_fulfillment import ProvisionedResourceDescriptor, VersionedEnvelope

VM_FULFILLMENT_RESULT_KIND = "vm.fulfillment.result.v1"
VM_FULFILLMENT_RESULT_SCHEMA_VERSION = 1


class VmProvisionedResource(BaseModel):
    provisioned_resource_id: str
    status: str

    model_config = {"frozen": True}


class VmFulfillmentCredential(BaseModel):
    """One VM credential and the fulfillment outputs it grants access to."""

    credential_id: str | None = None
    role: str
    password: str | None = None
    ssh_commands: dict[str, Any] | None = None
    provisioned_resource_ids: tuple[str, ...]

    model_config = {"frozen": True}


class VmFulfillmentResultPayload(BaseModel):
    provisioned_resources: tuple[VmProvisionedResource, ...]
    credentials: tuple[VmFulfillmentCredential, ...]

    model_config = {"frozen": True}


def build_vm_fulfillment_result(
    provisioned_resources: tuple[ProvisionedResourceDescriptor, ...],
    credentials: tuple[VmFulfillmentCredential, ...],
) -> VersionedEnvelope[Any]:
    payload = VmFulfillmentResultPayload(
        provisioned_resources=tuple(
            VmProvisionedResource(
                provisioned_resource_id=resource.provisioned_resource_id,
                status=resource.status,
            )
            for resource in provisioned_resources
        ),
        credentials=credentials,
    )
    return VersionedEnvelope(
        kind=VM_FULFILLMENT_RESULT_KIND,
        schema_version=VM_FULFILLMENT_RESULT_SCHEMA_VERSION,
        payload=payload.model_dump(mode="json"),
    )
