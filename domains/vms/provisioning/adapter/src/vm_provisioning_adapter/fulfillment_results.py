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
    ssh_key_path_host: str | None = None
    key_type: str | None = None
    provisioned_resource_ids: tuple[str, ...]

    model_config = {"frozen": True}


class VmConnectionInfo(BaseModel):
    """Structured VM identity/connection metadata, known only after the
    provider's job completes.

    Paired with ``VmConnectivitySettings`` (``fulfillment_model.py``) but
    the other direction: that's buyer/storefront-supplied *input* (what
    relay to use); this is provider-reported *output* (what the VM turned
    out to be reachable as). ``ssh_commands`` on each credential already
    carries a ready-to-use connection string (host, port, and user baked
    in), so none of this is required to connect -- it exists for callers
    that want the pieces separately rather than parsing a command string.
    """

    vm_name: str | None = None
    host: str | None = None
    timestamp: str | None = None
    tenant_user: str | None = None
    vm_ip_internal: str | None = None
    ssh_port: str | None = None

    model_config = {"frozen": True}


class VmFulfillmentResultPayload(BaseModel):
    provisioned_resources: tuple[VmProvisionedResource, ...]
    credentials: tuple[VmFulfillmentCredential, ...]
    connection_info: VmConnectionInfo | None = None

    model_config = {"frozen": True}


def build_vm_fulfillment_result(
    provisioned_resources: tuple[ProvisionedResourceDescriptor, ...],
    credentials: tuple[VmFulfillmentCredential, ...],
    *,
    connection_info: VmConnectionInfo | None = None,
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
        connection_info=connection_info,
    )
    return VersionedEnvelope(
        kind=VM_FULFILLMENT_RESULT_KIND,
        schema_version=VM_FULFILLMENT_RESULT_SCHEMA_VERSION,
        payload=payload.model_dump(mode="json"),
    )
