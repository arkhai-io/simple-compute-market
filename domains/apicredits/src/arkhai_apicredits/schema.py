"""The API-credits listing, and the family's carriers bound to its kind literal."""

from __future__ import annotations

import json
from typing import Any, Literal

from arkhai_api_contracts.carriers import (
    materialization_model,
    message_model,
    receipt_model,
    result_model,
    terms_model,
)
from market_core.schemas import SettlementOption
from pydantic import BaseModel, ConfigDict, Field, model_validator

from arkhai_apicredits.listings.models import (
    API_CREDITS_KIND,
    ApiCreditsResource,
)
from arkhai_apicredits.negotiation.terms import API_CREDITS_PROVISION_KIND

API_CREDITS_SCHEMA_KIND = API_CREDITS_KIND


class ApiCreditsListing(BaseModel):
    """API-credits domain payload carried by a registry listing."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["api_credits.v1"] = API_CREDITS_SCHEMA_KIND
    listing_resource: ApiCreditsResource = Field(
        description="Quota-backed API service offered by the seller.",
    )
    accepted_escrows: list[dict[str, Any]] = Field(default_factory=list)
    settlement_options: list[SettlementOption] = Field(default_factory=list)
    demands: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_listing_resource_payload(cls, value: Any) -> Any:
        # Domain models can cross a source/wheel import boundary in the
        # storefront image. Structurally identical Pydantic classes loaded
        # from those two locations do not pass isinstance validation, so
        # normalize models back to their wire representation first.
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            return value
        if "listing_resource" in value:
            listing_resource = value["listing_resource"]
            if isinstance(listing_resource, BaseModel):
                listing_resource = listing_resource.model_dump(mode="json")
            elif isinstance(listing_resource, str):
                try:
                    listing_resource = json.loads(listing_resource)
                except (TypeError, ValueError):
                    return value
            return {**value, "listing_resource": listing_resource}
        return {"listing_resource": value}

    @model_validator(mode="after")
    def _validate_listing(self) -> "ApiCreditsListing":
        if not self.listing_resource.service_name.strip():
            raise ValueError("listing_resource.service_name must be non-empty")
        if (
            self.listing_resource.resource_id is not None
            and not self.listing_resource.resource_id.strip()
        ):
            raise ValueError("listing_resource.resource_id must be non-empty")
        option_ids = [option.option_id for option in self.settlement_options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("settlement_options contains duplicate option identities")
        return self


ApiCreditsMessage = message_model(API_CREDITS_PROVISION_KIND)
ApiCreditsTerms = terms_model(API_CREDITS_PROVISION_KIND)
ApiCreditsMaterialization = materialization_model(API_CREDITS_SCHEMA_KIND, ApiCreditsResource)
ApiCreditsReceipt = receipt_model(API_CREDITS_SCHEMA_KIND)
ApiCreditsResult = result_model(API_CREDITS_SCHEMA_KIND)
