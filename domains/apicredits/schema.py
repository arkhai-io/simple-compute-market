"""API-credits market schema and public domain vocabulary."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from domains.apicredits.listings.models import (
    API_CREDITS_KIND,
    ApiCreditsResource,
)
from domains.apicredits.negotiation.terms import (
    API_CREDITS_PROVISION_KIND,
    ApiCreditsProvisionTerms,
)

API_CREDITS_SCHEMA_KIND = API_CREDITS_KIND


class ApiCreditsListing(BaseModel):
    """API-credits domain payload carried by a registry listing."""

    kind: Literal["api_credits.v1"] = API_CREDITS_SCHEMA_KIND
    offer_resource: ApiCreditsResource = Field(
        description="Quota-backed API service offered by the seller.",
    )
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    demands: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_offer_resource_payload(cls, value: Any) -> Any:
        # Domain models can cross a source/wheel import boundary in the
        # storefront image. Structurally identical Pydantic classes loaded
        # from those two locations do not pass isinstance validation, so
        # normalize models back to their wire representation first.
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            return value
        if "offer_resource" in value:
            offer_resource = value["offer_resource"]
            if isinstance(offer_resource, BaseModel):
                offer_resource = offer_resource.model_dump(mode="json")
            elif isinstance(offer_resource, str):
                try:
                    offer_resource = json.loads(offer_resource)
                except (TypeError, ValueError):
                    return value
            return {**value, "offer_resource": offer_resource}
        return {"offer_resource": value}

    @model_validator(mode="after")
    def _validate_listing(self) -> "ApiCreditsListing":
        if not self.offer_resource.service_name.strip():
            raise ValueError("offer_resource.service_name must be non-empty")
        if (
            self.offer_resource.resource_id is not None
            and not self.offer_resource.resource_id.strip()
        ):
            raise ValueError("offer_resource.resource_id must be non-empty")
        return self


class ApiCreditsMessage(ApiCreditsProvisionTerms):
    """API-credits negotiation message payload."""

    kind: Literal["api_credits.v1"] = API_CREDITS_PROVISION_KIND

    @model_validator(mode="after")
    def _validate_message(self) -> "ApiCreditsMessage":
        if self.quantity is None or self.quantity < 1:
            raise ValueError("payload.quantity must be >= 1")
        if self.key_mode not in {"new", "existing"}:
            raise ValueError("payload.key.mode must be 'new' or 'existing'")
        if self.key_mode == "existing" and not self.key_id:
            raise ValueError("payload.key.key_id is required for existing keys")
        return self


class ApiCreditsTerms(ApiCreditsMessage):
    """Canonical agreed API-credits terms produced by negotiation."""

    listing_ref: str | None = None


class ApiCreditsMaterialization(BaseModel):
    """Settlement-to-fulfillment handoff for an API-credits agreement."""

    kind: Literal["api_credits.v1"] = API_CREDITS_SCHEMA_KIND
    escrow_uid: str
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"] = "new"
    key_id: str | None = None
    offer_resource: ApiCreditsResource | None = None
    settlement_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_materialization(self) -> "ApiCreditsMaterialization":
        if not self.escrow_uid.strip():
            raise ValueError("escrow_uid must be non-empty")
        if self.key_mode == "existing" and not self.key_id:
            raise ValueError("key_id is required for existing keys")
        return self


class ApiCreditsReceipt(BaseModel):
    """Domain receipt for API-credit issuance/fulfillment state."""

    kind: Literal["api_credits.v1"] = API_CREDITS_SCHEMA_KIND
    status: str
    escrow_uid: str | None = None
    capacity_reservation_id: str | None = None
    key_id: str | None = None
    fulfillment_uid: str | None = None
    credentials_ref: dict[str, Any] | None = None
    result_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_receipt(self) -> "ApiCreditsReceipt":
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        return self


class ApiCreditsResult(BaseModel):
    """Result shape for API-credit issuance/fulfillment slots."""

    kind: Literal["api_credits.v1"] = API_CREDITS_SCHEMA_KIND
    action: str
    status: str = "success"
    fulfillment_uid: str | None = None
    credentials_ref: dict[str, Any] | None = None
    details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> "ApiCreditsResult":
        if not self.action.strip():
            raise ValueError("action must be non-empty")
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        return self
