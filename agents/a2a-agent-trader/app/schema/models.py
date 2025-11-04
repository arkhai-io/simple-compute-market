from dataclasses import dataclass
from enum import Enum
from typing import Optional


class GPUModel(str, Enum):
    """Supported GPU SKUs for compute resources."""

    H200 = "H200"
    TESLA_V100 = "Tesla V100"
    RTX_5080 = "RTX 5080"


class Region(str, Enum):
    """Regions where compute resources can be provisioned."""

    CALIFORNIA_US = "California, US"
    NEW_YORK_US = "New York, US"
    TOKYO_JP = "Tokyo, JP"


class OrderTag(str, Enum):
    """Types of orders in the market. May be BUY or SELL."""

    BUY = "buy"
    SELL = "sell"


@dataclass
class ComputeResource:
    """Describes an allocatable compute resource node managed by the trader."""

    gpu_model: GPUModel
    quantity: int
    sla: float  # percentage value in the range [0, 100]
    region: Region


@dataclass
class Order:
    """Describes an order on the market."""

    order_id: str
    tag: OrderTag
    order_maker: str  # Card URL
    compute_resource: ComputeResource
    duration: int  # duration in days
    offer_token: str
    offer_value: float
    maker_attestation: Optional[str] = None  # To be filled after negotation
    taker_attestation: Optional[str] = None  # To be filled after negotation


