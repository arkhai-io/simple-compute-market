"""Provider-neutral caller-facing fulfillment result envelopes.

A result is a read-time projection over durable fulfillment state. The outer
``fulfillment.result.v1`` envelope owns lifecycle identity and failure detail;
provider/domain-specific output and credential data is carried in a nested
versioned envelope and is never persisted by the fulfillment kit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .envelopes import VersionedEnvelope

FULFILLMENT_RESULT_KIND = "fulfillment.result.v1"
FULFILLMENT_RESULT_SCHEMA_VERSION = 1


class ProvisionedResourceOutput(BaseModel):
    """Fulfillment-owned identity and current status for one produced output."""

    provisioned_resource_id: str
    status: str

    model_config = {"frozen": True}


class FulfillmentResultPayload(BaseModel):
    """Provider-neutral lifecycle projection for one fulfillment."""

    fulfillment_id: str
    capacity_reservation_id: str
    state: str
    failure_reason: str | None = None
    failure_message: str | None = None
    provisioned_resources: tuple[ProvisionedResourceOutput, ...] = ()
    domain_result: VersionedEnvelope[Any] | None = None

    model_config = {"frozen": True}


def build_fulfillment_result_envelope(
    payload: FulfillmentResultPayload,
) -> VersionedEnvelope[Any]:
    return VersionedEnvelope(
        kind=FULFILLMENT_RESULT_KIND,
        schema_version=FULFILLMENT_RESULT_SCHEMA_VERSION,
        payload=payload.model_dump(mode="json"),
    )
