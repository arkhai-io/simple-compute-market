"""VM-owned request models for listing settlement composition."""

from __future__ import annotations

from core_storefront.models.listing_models import CreateListingRequest
from market_settlement_runtime import SettlementPublicationClause
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HostedFiatSettlementConfig(BaseModel):
    """Hosted-fiat listing input interpreted only by the VM composition."""

    model_config = ConfigDict(extra="forbid")

    account_ref: str = Field(strict=True, min_length=1, max_length=256)
    currency: str = Field(strict=True, pattern=r"^[a-z]{3}$")
    rate_minor_units: int = Field(strict=True, gt=0)
    condition_profile: str = Field(strict=True, min_length=1, max_length=128)
    resolver_id: str | None = Field(
        default=None,
        strict=True,
        min_length=1,
        max_length=128,
    )

    @field_validator("account_ref", "condition_profile", "resolver_id")
    @classmethod
    def require_trimmed_value(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("hosted settlement identifiers must be trimmed")
        return value


class VmCreateListingRequest(CreateListingRequest):
    """VM listing request with hosted-fiat composition validation."""

    settlements: list[SettlementPublicationClause] = Field(
        default_factory=list,
        description="Typed settlement clauses compiled into public options.",
    )
    settlement_config: HostedFiatSettlementConfig | None = Field(
        default=None,
        description=(
            "Hosted-fiat settlement configuration resolved against "
            "operator-owned profiles before publication."
        ),
    )

    @model_validator(mode="after")
    def require_settlement_choice(self) -> VmCreateListingRequest:
        if (
            not self.accepted_escrows
            and not self.settlements
            and not self.settlement_options
            and self.settlement_config is None
        ):
            raise ValueError("at least one settlement choice is required")
        return self
