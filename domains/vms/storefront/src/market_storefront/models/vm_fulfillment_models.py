"""VM fulfillment domain models for storefront settlement flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VmFulfillmentPlan:
    order_dict: dict[str, Any] | None
    order_id: str | None
    order_bytes: bytes
    required_attributes: dict[str, Any]
