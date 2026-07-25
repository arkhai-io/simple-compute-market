"""The `fulfillment.result.v1` versioned envelope.

A caller-facing fulfillment result is a read-time projection over the durable
`SettlementRecord` aggregate and its `ProvisionedResource` rows -- there is no
persisted result object (see
`openspec/specs/fulfillment/spec.md#durable-settlement-persistence`). This
module defines the wire shape of that projection once, as a real versioned
envelope, so `get_fulfillment_result` and any future caller that reads the
same projection (a push-delivery transport, for example) agree on one schema
rather than each inventing their own dict shape.

`credentials` is always empty in this envelope today: no `FulfillmentProvider`
method exists yet to populate it from a live provider fetch. The field is
part of the schema now so a later change that adds that fetch does not have
to widen an already-shipped envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .envelopes import VersionedEnvelope

FULFILLMENT_RESULT_KIND = "fulfillment.result.v1"
FULFILLMENT_RESULT_SCHEMA_VERSION = 1


class ProvisionedResourceOutput(BaseModel):
    """One provider-created output, as exposed to a result caller.

    Mirrors the durable `ProvisionedResource` row's caller-relevant fields;
    `provisioned_resource_id` is opaque and internal but included for
    idempotent client-side reconciliation across repeated reads.
    """

    provisioned_resource_id: str
    domain_resource_ref: str | None = None
    status: str

    model_config = {"frozen": True}


class FulfillmentCredential(BaseModel):
    """One role's live-fetched access credential.

    Never persisted -- constructed fresh for each `get_fulfillment_result`
    response from a provider's live fetch, once that fetch exists.
    """

    role: str
    password: str | None = None
    ssh_commands: dict[str, Any] | None = None

    model_config = {"frozen": True}


class FulfillmentResultPayload(BaseModel):
    """Caller-facing read-time projection over one settlement aggregate.

    Not a persisted model -- constructed fresh on every
    `get_fulfillment_result` call. `provisioned_resources` and `credentials`
    are populated only when `state` is `active`; every other lifecycle state
    reports the aggregate's identity, state, and failure detail with both
    left empty, since a fulfillment that hasn't produced a resource yet, or
    has already torn one down, has nothing a provider call could
    meaningfully return.
    """

    fulfillment_id: str
    capacity_reservation_id: str
    state: str
    failure_reason: str | None = None
    failure_message: str | None = None
    provisioned_resources: tuple[ProvisionedResourceOutput, ...] = ()
    credentials: tuple[FulfillmentCredential, ...] = ()

    model_config = {"frozen": True}


def build_fulfillment_result_envelope(
    payload: FulfillmentResultPayload,
) -> VersionedEnvelope[Any]:
    """Wrap a result payload in the current `fulfillment.result.v1` envelope."""

    return VersionedEnvelope(
        kind=FULFILLMENT_RESULT_KIND,
        schema_version=FULFILLMENT_RESULT_SCHEMA_VERSION,
        payload=payload.model_dump(mode="json"),
    )
