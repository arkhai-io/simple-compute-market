"""Domain-agnostic core schemas.

These models are intentionally minimal and stable so current agent code can
map in/out without immediate domain extraction.
"""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny


class ERC20TokenMetadata(BaseModel):
    """Describes metadata for an ERC-20 token."""

    symbol: str = Field(description="Ticker symbol, e.g. USDC")
    contract_address: str = Field(description="Checksummed ERC-20 contract address")
    decimals: int = Field(
        description="Number of decimal places the token uses", ge=0, le=30
    )


class Resource(BaseModel):
    """Domain-agnostic base resource model."""

    @classmethod
    def parse_from_dict(cls, data: Any) -> "Resource":
        """Parse core-known resource shapes.

        Core only understands universally valid resources. Domain-specific
        resources should be parsed by domain adapters that extend this method.
        """
        if isinstance(data, Resource):
            return data
        if not isinstance(data, dict):
            return data
        if "token" in data:
            return TokenResource(**data)
        raise ValueError("Unsupported resource payload for core Resource parser")


class TokenResource(Resource):
    """Describes a given value and amount of a token used for trade/payment."""

    token: SerializeAsAny[ERC20TokenMetadata] = Field(
        description="Token metadata resolved from registry"
    )
    amount: int = Field(
        description="Integer amount in base units (token amount * 10**decimals)"
    )


class Attestation(BaseModel):
    """Mutual attestations exchanged between maker and taker."""

    maker_attestation: str = Field(description="The attestation of the maker")
    taker_attestation: str = Field(description="The attestation of the taker")


class DomainEvent(BaseModel):
    """Generic domain event transported through core orchestration."""

    model_config = ConfigDict(use_enum_values=False)

    event_id: str = Field(description="Unique event identifier")
    event_type: Any = Field(description="Event type identifier")
    source: str = Field(description="Source identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class DomainAction(BaseModel):
    """Generic domain action selected by policy and executed by action handlers."""

    action_type: Any = Field(description="Action type identifier")
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Decision(BaseModel):
    """A policy decision and its execution outcome."""

    decision_id: str = Field(description="Unique decision identifier")
    agent_id: str = Field(description="Agent who made the decision")
    context: "DecisionContext" = Field(description="Context that led to the decision")
    action: DomainAction = Field(description="Chosen action")
    policy_used: str = Field(description="Policy that produced the decision")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the decision was made",
    )
    outcome: dict[str, Any] | None = Field(
        default=None,
        description="Outcome of executing this decision",
    )

    def record_outcome(self, outcome: dict[str, Any]) -> None:
        self.outcome = outcome


class DecisionContext(BaseModel):
    """Domain-neutral policy evaluation context."""

    event: DomainEvent
    agent_id: str
    available_resources: dict[str, Any] = Field(default_factory=dict)
    past_experiences: list[dict[str, Any]] = Field(default_factory=list)
    market_state: dict[str, Any] = Field(default_factory=dict)
    negotiation_history: list[dict[str, Any]] = Field(default_factory=list)

    def get_event_type(self) -> str:
        et = self.event.event_type
        return et.value if hasattr(et, "value") else str(et)

    def has_negotiation_context(self) -> bool:
        return len(self.negotiation_history) > 0
