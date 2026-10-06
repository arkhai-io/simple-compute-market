"""What a job-backed fulfillment delivers, and the evidence a create job reports.

A domain's codec reports a successful create job's result as
``DeliveryEvidence``: the endpoints to connect to and when access became
ready, stored by the job authority as the job's ``ResultEnvelope`` under
``DELIVERY_EVIDENCE_RESULT_KIND``. The family's job-backed provider accepts a
create as succeeded only when that evidence validates, so a fulfillment never
becomes active with a delivery nobody can read.

``AccessDelivery`` is what the fulfillment result carries for an active
fulfillment: the evidence's endpoints and ``ready_at``, and each credential the
create job issued, reduced to ``DeliveredCredential``'s fields. It says only how
to reach what was provisioned. It carries no provisioned-resource list (the
fulfillment result already does, and a job-backed fulfillment produces one), no
deal reference, no lease window, and no provisioner-side path or host-internal
address: a credential field outside ``DeliveredCredential`` never crosses.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The ``ResultEnvelope.result_kind`` under which a create job reports its evidence.
DELIVERY_EVIDENCE_RESULT_KIND = "compute.delivery-evidence.v1"

#: The kind and schema version of the delivery a fulfillment result carries.
ACCESS_DELIVERY_KIND = "compute.access-delivery"
ACCESS_DELIVERY_SCHEMA_VERSION = 1


class AccessEndpoint(BaseModel):
    """Where to connect to what was provisioned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    user: str | None = Field(default=None, min_length=1)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("ready_at must be timezone-aware")
    return value


class DeliveryEvidence(BaseModel):
    """A successful create job's result: how to connect, and since when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoints: tuple[AccessEndpoint, ...] = Field(min_length=1)
    ready_at: datetime

    _ready_at_is_aware = field_validator("ready_at")(_aware)


class DeliveredCredential(BaseModel):
    """One credential a create job issued, by role, reduced to its delivered fields.

    The fields are an allowlist. A stored credential may carry more, such as
    where a key file lives on a provisioner host; none of that is delivered.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    password: str | None = None
    key_type: str | None = None


class AccessDelivery(BaseModel):
    """How to reach what an active job-backed fulfillment provisioned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoints: tuple[AccessEndpoint, ...] = Field(min_length=1)
    credentials: tuple[DeliveredCredential, ...] = ()
    ready_at: datetime

    _ready_at_is_aware = field_validator("ready_at")(_aware)


__all__ = [
    "ACCESS_DELIVERY_KIND",
    "ACCESS_DELIVERY_SCHEMA_VERSION",
    "AccessDelivery",
    "AccessEndpoint",
    "DELIVERY_EVIDENCE_RESULT_KIND",
    "DeliveredCredential",
    "DeliveryEvidence",
]
