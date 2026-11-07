"""VM fulfillment domain models for storefront settlement flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arkhai_vms import VmProvisionTerms


@dataclass(frozen=True)
class VmFulfillmentPlan:
    order_dict: dict[str, Any] | None
    order_id: str | None
    order_bytes: bytes
    required_attributes: dict[str, Any]
    provision_terms: VmProvisionTerms
    duration_seconds: int
    start_utc: str
    lease_end_utc: str
    funding_expiration_unix: int | None
    condition_anchor: str | None
