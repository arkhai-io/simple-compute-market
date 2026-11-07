"""Reading how to reach a delivered host from provisioning's fulfillment result.

An active fulfillment's result carries the compute family's ``AccessDelivery``.
Bare metal delivers SSH access to the whole host, so its delivery names one SSH
endpoint with the tenant account; the buyer connects with the key it already
holds, so no credential is expected. A result in any other shape is refused
rather than read for whatever fields it happens to share.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    AccessDelivery,
    AccessEndpoint,
)
from market_core import VersionedEnvelope
from pydantic import ValidationError

_FULFILLMENT_RESULT_KIND = "fulfillment.result.v1"


def active_access_delivery(result: VersionedEnvelope[Any]) -> AccessDelivery:
    """The delivery an active fulfillment's result carries.

    Raises ``ValueError`` for a result that is not an active fulfillment's, or
    whose delivery is not the family's access delivery.
    """
    payload = result.payload
    if (
        result.kind != _FULFILLMENT_RESULT_KIND
        or result.schema_version != 1
        or not isinstance(payload, dict)
        or payload.get("state") != "active"
    ):
        raise ValueError("provisioning returned no active fulfillment result")
    try:
        domain = VersionedEnvelope.model_validate(payload.get("domain_result"))
    except ValidationError as exc:
        raise ValueError("the active fulfillment carries no delivery") from exc
    if domain.kind != ACCESS_DELIVERY_KIND or domain.schema_version != ACCESS_DELIVERY_SCHEMA_VERSION:
        raise ValueError(
            f"provisioning returned an unsupported delivery {domain.kind!r} "
            f"v{domain.schema_version}"
        )
    try:
        return AccessDelivery.model_validate(domain.payload)
    except ValidationError as exc:
        raise ValueError(f"provisioning returned an invalid delivery: {exc}") from exc


def ssh_endpoint(delivery: AccessDelivery) -> AccessEndpoint:
    """The SSH endpoint and tenant account a bare-metal delivery names."""
    for endpoint in delivery.endpoints:
        if endpoint.protocol == "ssh" and endpoint.user:
            return endpoint
    raise ValueError("the delivery names no SSH endpoint with a tenant account")


__all__ = ["active_access_delivery", "ssh_endpoint"]
