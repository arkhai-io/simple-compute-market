"""Who a job acts for, and how a repeated submission is recognized.

A fulfillment provider submits each job it dispatches with a ``JobActionRequest``:
the capacity reservation the job serves, the caller's opaque deal reference, the
offering mode and action, the idempotency key that makes a retried submission
return the job already recorded, and the job's parameters. It is the job
authority's own record, never a request any route accepts; the job engine
persists its correlation fields, and a job with them recorded is one fulfillment
submitted.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning_contracts import VersionedContractModel
from pydantic import Field


class JobActionRequest(VersionedContractModel):
    capacity_reservation_id: str = Field(min_length=1)
    deal_ref: dict[str, Any]
    offering_mode: str = Field(min_length=1)
    action_kind: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    parameters: dict[str, Any]


__all__ = ["JobActionRequest"]
