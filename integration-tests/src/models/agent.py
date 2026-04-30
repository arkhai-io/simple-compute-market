"""
arkhai_e2e_tests/models/agent.py
---------------------------------
Typed dataclasses for the storefront REST API request and response shapes.

Derived from:
  - pydantic_models.py  (ListingCreatedEvent, ListingClosedEvent, ResourceAlertRequest)
  - agent.py            (_run_create_order_flow, _run_close_order_flow response dicts,
                         serve_erc8004_registration_file response shape)

Auth note: the storefront validates X-Signature / X-Timestamp headers using
EIP-191 where the message is  "<operation>:<resource_id>:<timestamp>".
The resource_id for create_listing is the storefront's BASE_URL_OVERRIDE string;
for close_listing it is the listing_id string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ERC-8004 registration file and listing response models
#
# These classes have moved to the ``arkhai-storefront-client`` package
# (``storefront_client.models``).  They are re-exported here so that existing
# imports from ``src.models.agent`` continue to work without changes.
# ---------------------------------------------------------------------------

from storefront_client.models import (  # noqa: F401 — re-exported for backward compat
    StorefrontEndpoint,
    StorefrontListingCloseResponse,
    StorefrontListingCreateResponse,
    ERC8004RegistrationFile,
    RegistrationRecord,
)


# ---------------------------------------------------------------------------
# (Remaining classes below are request builders — not yet migrated.)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Listing create  (POST /listings/create)
# ---------------------------------------------------------------------------

@dataclass
class ComputeResourcePayload:
    gpu_model: str
    quantity: int
    sla: float
    region: str

    def to_dict(self) -> dict:
        return {
            "gpu_model": self.gpu_model,
            "quantity": self.quantity,
            "sla": self.sla,
            "region": self.region,
        }


@dataclass
class TokenResourcePayload:
    token: str
    amount: float

    def to_dict(self) -> dict:
        return {"token": self.token, "amount": self.amount}


@dataclass
class AgentOrderCreateRequest:
    """
    Request body for POST /listings/create.

    One of offer/demand must be a ComputeResourcePayload; the other a
    TokenResourcePayload.  The storefront will reject if both are the same type.
    """
    offer: dict[str, Any]
    demand: dict[str, Any]
    duration_hours: int = 1

    def to_dict(self) -> dict:
        return {
            "offer": self.offer,
            "demand": self.demand,
            "duration_hours": self.duration_hours,
        }

    @classmethod
    def compute_offer(
        cls,
        *,
        gpu_model: str,
        quantity: int,
        sla: float,
        region: str,
        token: str,
        amount: float,
        duration_hours: int = 1,
    ) -> "AgentOrderCreateRequest":
        """Seller-side convenience: offering compute, demanding tokens."""
        return cls(
            offer=ComputeResourcePayload(gpu_model, quantity, sla, region).to_dict(),
            demand=TokenResourcePayload(token, amount).to_dict(),
            duration_hours=duration_hours,
        )

    @classmethod
    def token_offer(
        cls,
        *,
        token: str,
        amount: float,
        gpu_model: str,
        quantity: int,
        sla: float,
        region: str,
        duration_hours: int = 1,
    ) -> "AgentOrderCreateRequest":
        """Buyer-side convenience: offering tokens, demanding compute."""
        return cls(
            offer=TokenResourcePayload(token, amount).to_dict(),
            demand=ComputeResourcePayload(gpu_model, quantity, sla, region).to_dict(),
            duration_hours=duration_hours,
        )


# ---------------------------------------------------------------------------
# Listing close  (POST /listings/close)
# ---------------------------------------------------------------------------

@dataclass
class AgentOrderCloseRequest:
    """Request body for POST /listings/close."""
    listing_id: str

    def to_dict(self) -> dict:
        return {"listing_id": self.listing_id}


# ---------------------------------------------------------------------------
# Resource alert  (POST /alerts/resource)
# ---------------------------------------------------------------------------

@dataclass
class ResourceAlertRequest:
    """
    Request body for POST /alerts/resource.

    Maps to ResourceAlertRequest in pydantic_models.py.
    event_type must be "resource_imbalance".
    value is a float 0.0-1.0; label / threshold describe the condition.
    """
    event_type: str
    resource: dict[str, Any]   # keys: gpu_model, quantity, sla, region
    value: float
    label: str
    threshold: str

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "resource": self.resource,
            "value": self.value,
            "label": self.label,
            "threshold": self.threshold,
        }

    @classmethod
    def surplus(
        cls,
        *,
        gpu_model: str,
        quantity: int,
        sla: float,
        region: str,
        value: float = 0.1,
    ) -> "ResourceAlertRequest":
        """Convenience factory for a low-utilization (surplus) alert."""
        return cls(
            event_type="resource_imbalance",
            resource={"gpu_model": gpu_model, "quantity": quantity, "sla": sla, "region": region},
            value=value,
            label="LOW UTILIZATION",
            threshold="<=0.30",
        )
