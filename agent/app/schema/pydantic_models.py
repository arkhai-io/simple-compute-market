from enum import Enum
from datetime import datetime
from typing import Any, Literal, Union
from pydantic import BaseModel, Field, SerializeAsAny, field_validator, model_validator
from pydantic import ConfigDict
import uuid


class ERC20TokenMetadata(BaseModel):
    """Describes registry metadata for an ERC-20 token."""

    symbol: str = Field(description="Ticker symbol, e.g. USDC")
    contract_address: str = Field(description="Checksummed ERC-20 contract address")
    decimals: int = Field(
        description="Number of decimal places the token uses", ge=0, le=30
    )


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
    
    @staticmethod
    def _resolve_token_metadata(token_value: Any) -> ERC20TokenMetadata:
        """Convert token identifiers into ERC20TokenMetadata."""
        if isinstance(token_value, ERC20TokenMetadata):
            return token_value
        if isinstance(token_value, dict):
            return ERC20TokenMetadata(**token_value)
        if isinstance(token_value, str):
            from app.utils.token_registry import TOKEN_REGISTRY

            return TOKEN_REGISTRY.require(token_value)
        raise ValueError(
            "Token value must be a symbol string, ERC20TokenMetadata dict, or ERC20TokenMetadata instance"
        )
    
    @classmethod
    def parse_from_dict(cls, data: Any) -> "Resource":
        """Parse a resource from a dictionary or return existing Resource instance.
        
        Converts dictionary payloads into the appropriate Resource subclass:
        - If data is already a Resource instance → returns it unchanged
        - If dict contains 'token' key → returns TokenResource (takes precedence)
        - If dict contains 'gpu_model' key → returns ComputeResource
        - If dict contains both keys → returns TokenResource (token takes precedence)
        - If dict contains neither key → raises ValueError
        - If data is not a dict and not a Resource → returns data unchanged
        
        Args:
            data: Dictionary with resource data, existing Resource instance, or other value
            
        Returns:
            Resource instance (TokenResource, ComputeResource, or existing Resource)
            
        Raises:
            ValueError: If data is a dict but doesn't contain required keys for any resource type
        """
        # If already a Resource instance, return it unchanged
        if isinstance(data, Resource):
            return data
        
        # If not a dict, return as-is (pass through)
        if not isinstance(data, dict):
            return data
        
        # TokenResource takes precedence if both keys are present
        if "token" in data:
            data = dict(data)  # copy to avoid mutating caller input
            data["token"] = cls._resolve_token_metadata(data["token"])
            return TokenResource(**data)
        elif "gpu_model" in data:
            return ComputeResource(**data)
        else:
            raise ValueError(
                "Resource dict must have either 'token' (TokenResource) "
                "or 'gpu_model' (ComputeResource) key"
            )


class TokenResource(Resource):
    """Describes a given value and amount of a token used for trade."""

    token: SerializeAsAny[ERC20TokenMetadata] = Field(
        description="Token metadata resolved from registry"
    )
    amount: int = Field(
        description="Integer amount in base units (token amount * 10**decimals)"
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
    """Market order for trading compute resources and tokens."""

    order_id: str = Field(description="The id of the order")
    order_maker: str = Field(description="The card URL of the agent who made the order")
    order_taker: str | None = Field(
        default="",
        description="The card URL of the agent who took the order",
    )
    offer_resource: Union[ComputeResource, TokenResource] = Field(
        description="The resource being offered, which may be a token or compute resource."
    )
    demand_resource: Union[ComputeResource, TokenResource] = Field(
        description="The resource being demanded, which may be a token or compute resource."
    )
    duration_hours: int = Field(description="The duration of the order in hours")
    maker_attestation: str | None = Field(
        default=None,
        description="The attestation for the offer in escrow (None for open orders)",
    )
    taker_attestation: str | None = Field(
        default=None,
        description="The attestation of the satisfied demand in escrow (None for open orders)",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_resources(cls, data: Any) -> Any:
        """Parse resources from dicts to Resource types."""
        if not isinstance(data, dict):
            return data
        
        # Parse offer_resource using Resource helper
        if "offer_resource" in data:
            data["offer_resource"] = Resource.parse_from_dict(data["offer_resource"])
        
        # Parse demand_resource using Resource helper
        if "demand_resource" in data:
            data["demand_resource"] = Resource.parse_from_dict(data["demand_resource"])
        
        return data

    def is_open(self) -> bool:
        """Check if this is an open order (no attestation)"""
        return self.maker_attestation is None or self.taker_attestation is None

    def is_closed(self) -> bool:
        """Check if this is a closed order (has attestation)"""
        return self.maker_attestation is not None and self.taker_attestation is not None


# =============================
# Event models for A2A workflow
# =============================


class EventType(str, Enum):
    """Events that can be handled by the Agent"""

    ORDER_CREATE = "order_create"
    ORDER_CLOSE = "order_close"
    MAKE_OFFER = "make_offer"
    ACCEPT_OFFER = "accept_offer"
    RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT = "receive_compute_obligation_fulfillment"
    ARBITRATION_COMPLETE = "arbitration_complete"
    RESOURCE_IMBALANCE = "resource_imbalance"
    CRON_JOB = "cron_job"
    ARBITRAGE_OPPORTUNITY = "arbitrage_opportunity"
    NEGOTIATION = "negotiation"


class DomainEvent(BaseModel):
    """Base event model"""

    model_config = ConfigDict(use_enum_values=False)

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


class OrderCreateEvent(DomainEvent):
    """Event triggered when a local client requests order creation."""

    event_type: EventType = Field(default=EventType.ORDER_CREATE)
    offer: Resource = Field(description="Offered resource (compute or token)")
    demand: Resource = Field(description="Demanded resource (compute or token)")
    duration_hours: int = Field(default=1, description="Duration of the order in hours")

    @model_validator(mode="before")
    @classmethod
    def parse_resources(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "offer" in data:
            data["offer"] = Resource.parse_from_dict(data["offer"])
        if "demand" in data:
            data["demand"] = Resource.parse_from_dict(data["demand"])
        return data


class OrderCloseEvent(DomainEvent):
    """Event triggered when a local client requests order closure."""

    event_type: EventType = Field(default=EventType.ORDER_CLOSE)
    order_id: str = Field(description="Order ID to close")


class MakeOfferEvent(DomainEvent):
    """Event triggered when a market order is broadcast"""

    event_type: EventType = Field(default=EventType.MAKE_OFFER)
    order: MarketOrder = Field(description="The market order that was broadcast")

    @classmethod
    def from_order(cls, order: MarketOrder) -> "MakeOfferEvent":
        """Create event from a market order"""
        return cls(
            event_id=f"evt_{order.order_id}",
            source=order.order_maker,
            order=order,
            data={
                "order_id": order.order_id,
                "offer_resource": order.offer_resource.model_dump(mode="json"),
                "demand_resource": order.demand_resource.model_dump(mode="json"),
                "duration_hours": order.duration_hours,
            },
        )


class AcceptOfferEvent(DomainEvent):
    """Event triggered when a taker accepts a market offer."""

    event_type: EventType = Field(default=EventType.ACCEPT_OFFER)
    order: MarketOrder = Field(description="The accepted market order with taker info")
    escrow_uid: str | None = Field(
        default=None,
        description="Escrow receipt UID supplied by the taker",
    )
    ssh_public_key: str | None = Field(
        default=None,
        description="Buyer-provided SSH public key for provisioning access",
    )

    @classmethod
    def from_order(
        cls,
        order: MarketOrder,
        escrow_uid: str | None = None,
        ssh_public_key: str | None = None,
    ) -> "AcceptOfferEvent":
        """Create an accept-offer event from a market order and optional escrow UID."""
        return cls(
            event_id=f"acc_{order.order_id}",
            source=order.order_taker or order.order_maker,
            order=order,
            escrow_uid=escrow_uid,
            ssh_public_key=ssh_public_key,
            data={
                "order_id": order.order_id,
                "offer_resource": order.offer_resource.model_dump(mode="json"),
                "demand_resource": order.demand_resource.model_dump(mode="json"),
                "duration_hours": order.duration_hours,
                "escrow_uid": escrow_uid,
                "ssh_public_key": ssh_public_key,
            },
        )


class ReceiveComputeObligationFulfillmentEvent(DomainEvent):
    """Event triggered when the buyer receives compute fulfillment details."""

    event_type: EventType = Field(default=EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT)
    escrow_uid: str = Field(description="Escrow UID tied to the fulfillment")
    fulfillment_uid: str | None = Field(
        default=None,
        description="UID of the fulfillment (may be provided by seller/chain)",
    )
    connection_details: str | dict | None = Field(
        default=None,
        description="Connection string/details for the provisioned compute",
    )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReceiveComputeObligationFulfillmentEvent":
        escrow_uid = payload.get("escrow_uid")
        if not escrow_uid:
            raise ValueError("ReceiveComputeObligationFulfillmentEvent requires escrow_uid")
        return cls(
            event_id=payload.get("event_id", f"rcf_{uuid.uuid4()}"),
            source=payload.get("source", "unknown"),
            escrow_uid=escrow_uid,
            fulfillment_uid=payload.get("fulfillment_uid"),
            connection_details=payload.get("connection_details"),
            data=payload,
        )

class ArbitrationCompleteEvent(DomainEvent):
    """Event triggered when arbitration over fulfillment has completed."""

    event_type: EventType = Field(default=EventType.ARBITRATION_COMPLETE)
    decisions: list[Any] | None = Field(
        default=None,
        description="Arbiter decisions returned for the fulfillment",
    )
    fulfillment_uid: str | None = Field(
        default=None,
        description="UID of the fulfillment that was arbitrated",
    )
    escrow_uid: str | None = Field(
        default=None,
        description="Escrow UID tied to the fulfillment (may be required to collect)",
    )
    oracle_address: str | None = Field(
        default=None,
        description="Oracle contract/address used for arbitration",
    )
    status: str | None = Field(
        default=None,
        description="Status string reported by the arbiter or workflow",
    )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ArbitrationCompleteEvent":
        """Create an arbitration-complete event from a payload dict."""
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            raise ValueError("ArbitrationCompleteEvent payload must be a dictionary")

        fulfillment_uid = data.get("fulfillment_uid")
        if not fulfillment_uid:
            raise ValueError("ArbitrationCompleteEvent requires fulfillment_uid")

        return cls(
            event_id=data.get("event_id") or payload.get("event_id", f"arb_{uuid.uuid4()}"),
            source=data.get("source") or payload.get("source", "unknown"),
            decisions=data.get("decisions"),
            fulfillment_uid=fulfillment_uid,
            escrow_uid=data.get("escrow_uid"),
            oracle_address=data.get("oracle_address"),
            status=data.get("status"),
            data=data,
        )

class ResourceAlertRequest(BaseModel):
    """Request model for resource imbalance alerts from monitoring systems.
    
    Validates incoming alert structure and provides conversion to ResourceImbalanceEvent.
    All fields are required - strict validation with no defaults.
    """
    
    event_type: Literal["resource_imbalance"] = Field(
        description="Type of event (must be resource_imbalance)"
    )
    resource: dict[str, Any] = Field(
        description="Resource details with required fields: gpu_model, quantity, sla, region"
    )
    value: float = Field(
        ge=0.0,
        le=1.0,
        description="Utilization value (0.0-1.0) that maps to severity"
    )
    label: str = Field(description="Alert label (e.g., 'LOW UTILIZATION')")
    threshold: str = Field(description="Threshold string (e.g., '<=0.30')")
    
    @field_validator("resource")
    @classmethod
    def validate_resource(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Validate resource dict has all required fields."""
        required_fields = ["gpu_model", "quantity", "sla", "region"]
        missing = [field for field in required_fields if field not in v]
        if missing:
            raise ValueError(f"Resource dict missing required fields: {missing}")
        return v
    
    def to_resource_imbalance_event(
        self,
        event_id: str | None = None,
        source: str | None = None,
    ) -> "ResourceImbalanceEvent":
        """Convert alert to ResourceImbalanceEvent.
        
        Maps value -> severity, extracts resource fields, stores label/threshold in data.
        """
        # Extract and validate resource fields
        gpu_model = GPUModel(self.resource["gpu_model"])
        quantity = int(self.resource["quantity"])
        sla = float(self.resource["sla"])
        region = Region(self.resource["region"])
        
        # Create ComputeResource
        compute_resource = ComputeResource(
            gpu_model=gpu_model,
            quantity=quantity,
            sla=sla,
            region=region,
        )
        
        # Map value to severity
        severity = self.value
        
        # Determine imbalance_type from label/value (policy can override)
        # Default to 'surplus' for low utilization, 'deficit' for high
        imbalance_type = "surplus" if "LOW" in self.label.upper() else "deficit"
        
        # Create event with label and threshold in data for policy access
        return ResourceImbalanceEvent(
            event_id=event_id or f"alert_{uuid.uuid4()}",
            source=source or "resource-monitor",
            resource=compute_resource,
            imbalance_type=imbalance_type,
            severity=severity,
            data={
                "gpu_model": gpu_model.value,
                "quantity": quantity,
                "region": region.value,
                "sla": sla,
                "imbalance_type": imbalance_type,
                "severity": severity,
                "label": self.label,
                "threshold": self.threshold,
                "value": self.value,
            },
        )


class ResourceImbalanceEvent(DomainEvent):
    """Event triggered when resource imbalance is detected"""

    event_type: EventType = Field(default=EventType.RESOURCE_IMBALANCE)
    resource: ComputeResource = Field(description="The imbalanced resource")
    imbalance_type: str = Field(description="Type of imbalance: surplus or deficit")
    severity: float = Field(description="Severity of imbalance (0.0-1.0)")

    @model_validator(mode="before")
    @classmethod
    def parse_resource(cls, data: Any) -> Any:
        """Parse resource from dict to ComputeResource if needed.
        
        Also extracts imbalance_type and severity from nested data dict if present.
        """
        if not isinstance(data, dict):
            return data
        
        # Handle nested data structure - extract fields from data dict
        if "data" in data and isinstance(data["data"], dict):
            nested_data = data["data"]
            
            # Extract resource from nested data
            if "resource" in nested_data:
                resource_dict = nested_data["resource"]
                if isinstance(resource_dict, dict):
                    # Validate required fields
                    required_fields = ["gpu_model", "quantity", "sla", "region"]
                    missing = [f for f in required_fields if f not in resource_dict]
                    if missing:
                        raise ValueError(f"Resource missing required fields: {missing}")
                    # Convert to ComputeResource
                    data["resource"] = ComputeResource.model_validate(resource_dict)
            
            # Extract imbalance_type and severity from nested data if not at top level
            if "imbalance_type" in nested_data and "imbalance_type" not in data:
                data["imbalance_type"] = nested_data["imbalance_type"]
            if "severity" in nested_data and "severity" not in data:
                data["severity"] = nested_data["severity"]
        
        # If resource is at top level as dict, convert it
        elif "resource" in data and isinstance(data["resource"], dict):
            resource_dict = data["resource"]
            required_fields = ["gpu_model", "quantity", "sla", "region"]
            missing = [f for f in required_fields if f not in resource_dict]
            if missing:
                raise ValueError(f"Resource missing required fields: {missing}")
            data["resource"] = ComputeResource.model_validate(resource_dict)
        
        return data

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
    CLOSE_ORDER = "close_order"

    # Resource management actions
    RESOLVE_INTERNALLY = "resolve_internally"
    OUTSOURCE = "outsource"
    FULFILL_COMPUTE_OBLIGATION = "fulfill_compute_obligation"
    TRUST_COMPUTE_OBLIGATION_FULFILLMENT = "trust_compute_obligation_fulfillment"
    COLLECT_ESCROW = "collect_escrow"
    VERIFY_COMPUTE_OBLIGATION_FULFILLMENT = "verify_compute_obligation_fulfillment"
    GET_AVAILABLE_RESOURCES = "get_available_resources"

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
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the decision was made",
    )

    # Outcome tracking (filled in later)
    outcome: dict[str, Any] | None = Field(
        default=None,
        description="Outcome of executing this decision",
    )

    def record_outcome(self, outcome: dict[str, Any]) -> None:
        """Record the outcome of this decision."""
        self.outcome = outcome
