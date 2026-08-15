"""VM-owned request models for listing settlement composition."""

from __future__ import annotations

from core_storefront.models.listing_models import CreateListingRequest
from market_settlement_runtime import SettlementPublicationClause
from pydantic import Field, model_validator




class VmCreateListingRequest(CreateListingRequest):
    """VM listing request with hosted-fiat composition validation."""

    settlements: list[SettlementPublicationClause] = Field(
        default_factory=list,
        description="Typed settlement clauses compiled into public options.",
    )

    @model_validator(mode="after")
    def require_settlement_choice(self) -> VmCreateListingRequest:
        if not self.accepted_escrows and not self.settlements and not self.settlement_options:
            raise ValueError("at least one settlement choice is required")
        return self
