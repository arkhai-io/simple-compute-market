from enum import Enum
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from pydantic import ConfigDict


class GPUModel(str, Enum):
    """GPU hardware models available in the marketplace"""

    H200 = "H200"
    TESLA_V100 = "Tesla V100"
    RTX_5080 = "RTX 5080"


class Region(str, Enum):
    """Geographic regions for compute resources"""

    CALIFORNIA_US = "California, US"
    NEW_YORK_US = "New York, US"
    TOKYO_JP = "Tokyo, JP"


class Tag(str, Enum):
    """Order type tags"""

    BUY = "buy"
    SELL = "sell"


class Attestation(BaseModel):
    """Describes the attestation of an agent with respect to a compute resource.

    Who bought and who sold the compute resource.
    The attestation is a signed message from the maker to the taker,
    and a signed message from the taker to the maker.
    """

    maker_attestation: str = Field(description="The attestation of the maker")
    taker_attestation: str = Field(description="The attestation of the taker")


class Resource(BaseModel):
    """Generic resource.
    """


class TokenResource(Resource):
    """Describes a given value and amount of a token used for trade.

    Note that while USDT and USDC are precise to 6 decimal places, ERC-20 uses 18 as standard.
    Thus, we use 18 decimal places.
    """
    token: str = Field(description="Token or currency")
    amount: int = Field(description=
        "Integer amount for the token, up to 18 decimal places (e.g. 10 units = 10 * 10**18)"
    )

class ComputeResource(Resource):
    """Describes the compute resources that are available to each Agent,
    and may be put on the market. This is before any valuation.
    Not all resources in the resource portfolio are on sale
    """

    gpu_model: GPUModel = Field(
        description="The model of the GPU (H200, Tesla V100, RTX 5080)"
    )
    quantity: int = Field(description="The quantity of the GPU")
    sla: float = Field(description="The SLA of the GPU")
    region: Region = Field(
        description="The region of the GPU (California, US, Tokyo, JP, etc.)"
    )


class ComputeResourcePortfolio(BaseModel):
    """Describes the resource portfolio of an Agent."""

    resources: list[ComputeResource] = Field(description="The resources in the portfolio")

    def total_quantity(self, gpu_model: GPUModel | None = None) -> int:
        """Calculate total GPU quantity, optionally filtered by model"""
        if gpu_model:
            return sum(r.quantity for r in self.resources if r.gpu_model == gpu_model)
        return sum(r.quantity for r in self.resources)

    def has_capacity(self, required: ComputeResource) -> bool:
        """Check if portfolio has sufficient capacity for a required resource"""
        for resource in self.resources:
            if (
                resource.gpu_model == required.gpu_model
                and resource.region == required.region
                and resource.quantity >= required.quantity
                and resource.sla >= required.sla
            ):
                return True
        return False

    def add_resource(self, resource: ComputeResource) -> None:
        """Add a resource to the portfolio"""
        for existing in self.resources:
            if (
                existing.gpu_model == resource.gpu_model
                and existing.region == resource.region
                and existing.sla == resource.sla
            ):
                existing.quantity += resource.quantity
                return
        self.resources.append(resource)

    def remove_resource(self, resource: ComputeResource) -> bool:
        """Remove a resource from the portfolio. Returns True if successful."""
        for existing in self.resources:
            if (
                existing.gpu_model == resource.gpu_model
                and existing.region == resource.region
                and existing.sla == resource.sla
            ):
                if existing.quantity >= resource.quantity:
                    existing.quantity -= resource.quantity
                    if existing.quantity == 0:
                        self.resources.remove(existing)
                    return True
        return False


class MarketOrder(BaseModel):
    """Describes an open order on the market, which contains information about
    the resources being offered or sought, and parameters are used for matching
    agents before the negotiation begins.
    An open order is one with blank attestations (maker_attestation and taker_attestation).
    A closed order is one with filled out maker_attestation and taker_attestation.
    """

    order_id: str = Field(description="The id of the order")
    tag: Tag = Field(description="The tag of the order (buy or sell)")
    order_maker: str = Field(description="The card URL of the agent who made the order")
    order_taker: str = Field(
        default="",
        description="The card URL of the agent who took the order",
    )
    offer_resource: Resource = Field(
        description="The resource being offered, which may be a token or compute resource."
    )
    demand_resource: Resource = Field(
        description="The resource being demanded, which may be a token or compute resource."
    )
    quantity: int = Field(
        description="The quantity of the compute resource being offered or sought"
    )
    duration: int = Field(description="The duration of the order in days")
    maker_attestation: Attestation | None = Field(
        default=None,
        description="The attestation for the offer in escrow (None for open orders)",
    )
    taker_attestation: Attestation | None = Field(
        default=None,
        description="The attestation of the satisfied demand in escrow (None for open orders)",
    )

    def is_open(self) -> bool:
        """Check if this is an open order (no attestation)"""
        return self.attestation is None

    def is_closed(self) -> bool:
        """Check if this is a closed order (has attestation)"""
        return self.attestation is not None


# =============================
# Event models for A2A workflow
# =============================


class EventType(str, Enum):
    """Events that can be handled by the Agent"""

    MAKE_OFFER = "make_offer"
    RESOURCE_IMBALANCE = "resource_imbalance"
    CRON_JOB = "cron_job"
    ARBITRAGE_OPPORTUNITY = "arbitrage_opportunity"
    MARKET_ORDER = "market_order"
    NEGOTIATION = "negotiation"


class DomainEvent(BaseModel):
    """Base event model"""

    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(description="Unique event identifier")
    event_type: EventType = Field(description="Type of event")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the event occurred",
    )
    source: str = Field(description="Source of the event (agent_id, system, etc.)")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data payload",
    )


class MarketOrderEvent(DomainEvent):
    """Event triggered when a market order is broadcast"""

    event_type: EventType = Field(default=EventType.MARKET_ORDER)
    order: MarketOrder = Field(description="The market order that was broadcast")

    @classmethod
    def from_order(cls, order: MarketOrder) -> "MarketOrderEvent":
        """Create event from a market order"""
        return cls(
            event_id=f"evt_{order.order_id}",
            source=order.order_maker,
            order=order,
            data={
                "order_id": order.order_id,
                "tag": order.tag.value,
                "gpu_model": order.compute_resource.gpu_model.value,
                "quantity": order.quantity,
                "duration": order.duration,
            },
        )


class ResourceImbalanceEvent(DomainEvent):
    """Event triggered when resource imbalance is detected"""

    event_type: EventType = Field(default=EventType.RESOURCE_IMBALANCE)
    resource: ComputeResource = Field(description="The imbalanced resource")
    imbalance_type: str = Field(description="Type of imbalance: surplus or deficit")
    severity: float = Field(description="Severity of imbalance (0.0-1.0)")

    @classmethod
    def create(
        cls,
        event_id: str,
        source: str,
        resource: ComputeResource,
        imbalance_type: str,
        severity: float,
    ) -> "ResourceImbalanceEvent":
        """Create a resource imbalance event"""
        return cls(
            event_id=event_id,
            source=source,
            resource=resource,
            imbalance_type=imbalance_type,
            severity=severity,
            data={
                "gpu_model": resource.gpu_model.value,
                "quantity": resource.quantity,
                "region": resource.region.value,
                "imbalance_type": imbalance_type,
                "severity": severity,
            },
        )


class NegotiationEvent(DomainEvent):
    """Event triggered when a negotiation message is received"""

    event_type: EventType = Field(default=EventType.NEGOTIATION)
    negotiation_id: str = Field(description="ID of the negotiation thread")
    message_type: str = Field(description="Type of negotiation message")
    sender: str = Field(description="Agent who sent the message")

    @classmethod
    def create(
        cls,
        event_id: str,
        negotiation_id: str,
        message_type: str,
        sender: str,
        data: dict[str, Any],
    ) -> "NegotiationEvent":
        """Create a negotiation event"""
        return cls(
            event_id=event_id,
            source=sender,
            negotiation_id=negotiation_id,
            message_type=message_type,
            sender=sender,
            data=data,
        )


# =============================
# Decision and Action domain models for reactive agents
# =============================


class ActionType(str, Enum):
    """Types of actions an agent can take."""

    # Market entry actions
    RESPOND_TO_ORDER = "respond_to_order"
    IGNORE_ORDER = "ignore_order"
    MAKE_OFFER = "make_offer"

    # Negotiation actions
    ACCEPT_OFFER = "accept_offer"
    REJECT_OFFER = "reject_offer"
    COUNTER_OFFER = "counter_offer"
    EXIT_NEGOTIATION = "exit_negotiation"

    # Resource management actions
    RESOLVE_INTERNALLY = "resolve_internally"
    OUTSOURCE = "outsource"

    # No-op
    NOOP = "noop"


class Action(BaseModel):
    """An action to be taken by an agent."""

    action_type: ActionType = Field(description="Type of action")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the action was created",
    )


class DecisionContext(BaseModel):
    """Context information for making a reactive decision."""

    # Trigger information
    event: DomainEvent = Field(description="The triggering event")

    # Agent state
    agent_id: str = Field(description="Agent making the decision")
    available_resources: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent's current resource state",
    )

    # Historical context
    past_experiences: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Relevant past experiences",
    )

    # Market context
    market_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Current market conditions",
    )

    # Negotiation context (if applicable)
    negotiation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="History of current negotiation thread",
    )

    def get_event_type(self) -> EventType:
        """Get the type of triggering event."""
        return self.event.event_type

    def has_negotiation_context(self) -> bool:
        """Check if this context includes negotiation history."""
        return len(self.negotiation_history) > 0


class Decision(BaseModel):
    """A decision made by a reactive agent."""

    decision_id: str = Field(description="Unique decision identifier")
    agent_id: str = Field(description="Agent who made the decision")
    context: DecisionContext = Field(description="Context that led to the decision")
    action: Action = Field(description="The chosen action")
    policy_used: str = Field(description="Policy that produced this decision")
    confidence: float = Field(
        default=1.0,
        description="Confidence in the decision (0.0-1.0)",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the decision was made",
    )

    # Outcome tracking (filled in later)
    outcome: dict[str, Any] | None = Field(
        default=None,
        description="Outcome of executing this decision",
    )
    utility: float | None = Field(
        default=None,
        description="Utility gained from this decision",
    )

    def record_outcome(self, outcome: dict[str, Any], utility: float) -> None:
        """Record the outcome and utility of this decision."""
        self.outcome = outcome
        self.utility = utility


