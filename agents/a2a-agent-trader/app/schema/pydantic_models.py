from enum import Enum
from pydantic import BaseModel, Field


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
    The attestation is a signed message from the buyer to the seller,
    and a signed message from the seller to the buyer.
    """

    buyer_attestation: str = Field(description="The attestation of the buyer")
    seller_attestation: str = Field(description="The attestation of the seller")


class ComputeResource(BaseModel):
    """Describes the resources that are available to each Agent,
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
    An open order is one with blank attestations (buyer_attestation and seller_attestation).
    A closed order is one with filled out buyer_attestation and seller_attestation.
    """

    order_id: str = Field(description="The id of the order")
    tag: Tag = Field(description="The tag of the order (buy or sell)")
    order_maker: str = Field(description="The card URL of the agent who made the order")
    order_taker: str = Field(
        default="",
        description="The card URL of the agent who took the order",
    )
    compute_resource: ComputeResource = Field(
        description="The compute resource being offered or sought"
    )
    quantity: int = Field(
        description="The quantity of the compute resource being offered or sought"
    )
    duration: int = Field(description="The duration of the order in days")
    attestation: Attestation | None = Field(
        default=None,
        description="The attestation of the order (None for open orders)",
    )

    def is_open(self) -> bool:
        """Check if this is an open order (no attestation)"""
        return self.attestation is None

    def is_closed(self) -> bool:
        """Check if this is a closed order (has attestation)"""
        return self.attestation is not None


