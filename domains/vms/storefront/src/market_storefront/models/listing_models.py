"""VM-owned request models for listing settlement composition."""

from __future__ import annotations

from typing import Any

from core_storefront.models.listing_models import CreateListingRequest
from market_settlement_runtime import SettlementPublicationClause
from pydantic import BaseModel, ConfigDict, Field, model_validator


class VmCapacitySource(BaseModel):
    """Trusted capacity provenance bound atomically to a VM listing."""

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(min_length=1)
    pool_id: str | None = Field(default=None, min_length=1)
    resource_id: str | None = Field(default=None, min_length=1)
    gpu_count: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def require_capacity_identity(self) -> VmCapacitySource:
        if self.pool_id is None and self.resource_id is None:
            raise ValueError("capacity source requires pool_id or resource_id")
        return self




class VmCreateListingRequest(CreateListingRequest):
    """VM listing request with hosted-fiat composition validation."""

    settlements: list[SettlementPublicationClause] = Field(
        default_factory=list,
        description="Typed settlement clauses compiled into public options.",
    )
    capacity_source: VmCapacitySource = Field(
        description=(
            "Trusted site and pool or Physical Resource provenance persisted "
            "with the listing before publication."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def reject_removed_settlement_config(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("settlement_config") is not None:
            raise ValueError(
                "settlement_config is removed; use complete settlements clauses"
            )
        return value

    @model_validator(mode="after")
    def require_settlement_choice(self) -> VmCreateListingRequest:
        if not self.accepted_escrows and not self.settlements and not self.settlement_options:
            raise ValueError("at least one settlement choice is required")
        return self
