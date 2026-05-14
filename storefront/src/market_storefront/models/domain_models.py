from enum import Enum
from datetime import datetime
from typing import Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator
import uuid

from service.schemas import (
    AcceptedEscrow,
    ActionType,
    Attestation as CoreAttestation,
    Decision as CoreDecision,
    DecisionContext as CoreDecisionContext,
    DomainAction as CoreDomainAction,
    DomainEvent as CoreDomainEvent,
    Resource as CoreResource,
    TokenResource as CoreTokenResource,
)

from service.clients.token import ERC20TokenMetadata

# =============================================================================
# Domain Model Class Hierarchy
# =============================================================================
#
# service.schemas (external wheel — canonical base types)
# ├── CoreResource                  Base resource model
# │   └── ComputeDomainResource     Parse/coerce helper; extends CoreResource
# │       ├── ComputeResource       A compute slice (GPU, CPU, RAM, region, ...)
# │       └── TokenResource         ERC-20 token payment (= CoreTokenResource alias)
# ├── CoreDomainEvent               Base event model
# │   ├── DomainEvent               (alias for CoreDomainEvent)
# │   ├── ListingCreatedEvent       order_create pipeline trigger
# │   ├── ListingClosedEvent        order_close pipeline trigger
# │   └── ResourceImbalanceEvent    alert pipeline trigger
# └── (other core types re-aliased below)
#     ├── Action                    = CoreDomainAction
#     ├── DecisionContext           = CoreDecisionContext
#     └── Decision                  = CoreDecision
#
# Marketplace-layer types (defined here)
# ├── Listing                       A published marketplace listing
# │   ├── offer_resource: ComputeResource | TokenResource
# │   └── accepted_escrows: list[AcceptedEscrow] | None
# ├── Host                          Physical host metadata (capacity, hardware)
# ├── ComputeResourcePortfolio      Collection of ComputeResource slices
# └── ResourceAlertRequest          HTTP input for POST /alerts/resource
#         └── .to_resource_imbalance_event() → ResourceImbalanceEvent
#
# Enumerations
# ├── GPUModel          H200 | Tesla V100 | RTX 5080 | RTX A5000 | RTX 4090
# ├── Region            California, US | New York, US | Tokyo, JP
# ├── GpuInterconnect   nvlink | nvswitch | pcie_only | infiniband
# ├── VirtualizationType bare_metal | vm | container
# └── EventType         order_create | order_close | resource_imbalance | ...
# =============================================================================


class GPUModel(str, Enum):
    """GPU hardware models available in the marketplace"""

    H200 = "H200"
    TESLA_V100 = "Tesla V100"
    RTX_5080 = "RTX 5080"
    RTX_A5000 = "RTX A5000"
    RTX_4090 = "RTX 4090"


class Region(str, Enum):
    """Geographic regions for compute resources"""

    CALIFORNIA_US = "California, US"
    NEW_YORK_US = "New York, US"
    TOKYO_JP = "Tokyo, JP"


class GpuInterconnect(str, Enum):
    """GPU-to-GPU interconnect topology."""

    NVLINK = "nvlink"
    NVSWITCH = "nvswitch"
    PCIE_ONLY = "pcie_only"
    INFINIBAND = "infiniband"


class VirtualizationType(str, Enum):
    """How the host exposes the resource to the buyer.

    Per-slice (resource-level) — the seller picks the deployment mode for
    each listing. Two listings on the same host can differ (e.g., one as a
    GPU-passthrough VM, another as a Docker container) provided the host's
    deployment configuration supports both.
    """

    BARE_METAL = "bare_metal"
    VM = "vm"
    CONTAINER = "container"


class Host(BaseModel):
    """A physical host the seller owns. Source of truth for host hardware.

    Mirrors provisioning-service's host inventory and adds marketing metadata
    that the provisioning-service doesn't track (cpu_type, motherboard,
    capacity totals, network specs, datacenter grade, etc.). Compute slice
    resources reference a host by ``name`` via ``ComputeResource.vm_host``.

    Capacity invariants enforced at publish time:
      ``SUM(active_slices.gpu_count)  ≤ total_gpu_count``
      ``SUM(active_slices.vcpu_count) ≤ host_cpu_cores``
      ``SUM(active_slices.ram_gb)     ≤ host_ram_gb``
      ``SUM(active_slices.disk_gb)    ≤ host_disk_gb``

    Free-form provider-specific tags belong in ``attributes`` under the
    ``tag.*`` namespace (e.g. ``attributes["tag.datacenter_tier"]``).
    """

    name: str = Field(description="Host alias (matches provisioning-service host alias, e.g. 'ww1').")
    cpu_type: str | None = Field(default=None, description="Host CPU model string, e.g. 'AMD EPYC 9654'")
    host_cpu_cores: int | None = Field(default=None, description="Total physical CPU cores on host")
    host_ram_gb: int | None = Field(default=None, description="Host total RAM in GB")
    host_disk_gb: int | None = Field(default=None, description="Host total disk capacity in GB")
    host_disk_type: str | None = Field(
        default=None,
        description="Disk model string of the host's storage, e.g. 'Samsung MZTL3T8HEFK'",
    )
    motherboard: str | None = Field(default=None, description="Motherboard model string")
    total_gpu_count: int | None = Field(default=None, description="Total GPUs on the host")
    gpu_model: GPUModel | None = Field(default=None, description="GPU model (assumes homogeneous GPUs per host in v1)")
    gpu_interconnect: GpuInterconnect | None = Field(
        default=None,
        description="Host GPU-to-GPU interconnect (set by BIOS/NVSwitch domain; uniform across slices)",
    )
    nic_speed_gbps: int | None = Field(default=None, description="Host NIC link speed in Gbps")
    internet_download_mbps: int | None = Field(default=None, description="Host internet downlink in Mbps")
    internet_upload_mbps: int | None = Field(default=None, description="Host internet uplink in Mbps")
    static_ip: bool | None = Field(default=None, description="Whether the host has a static public IP")
    open_ports_count: int | None = Field(
        default=None,
        description="Number of externally-routable TCP ports the host exposes",
    )
    region: Region | None = Field(default=None, description="Geographic region of the host")
    datacenter_grade: bool | None = Field(
        default=None,
        description="True for commercial datacenter hosting (vs home/colo)",
    )
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="Free-form provider tags under the 'tag.*' namespace.",
    )
    enabled: bool = Field(default=True, description="Whether the host is active")


Attestation = CoreAttestation


class ComputeDomainResource(CoreResource):
    """Compute-domain resource parser extension on top of core Resource."""

    @staticmethod
    def _resolve_token_metadata(token_value: Any) -> ERC20TokenMetadata:
        """Convert token identifiers into ERC20TokenMetadata."""
        if isinstance(token_value, ERC20TokenMetadata):
            return token_value
        if isinstance(token_value, dict):
            return ERC20TokenMetadata(**token_value)
        if isinstance(token_value, str):
            from service.clients.token import TOKEN_REGISTRY

            return TOKEN_REGISTRY.require(token_value)
        raise ValueError(
            "Token value must be a symbol string, ERC20TokenMetadata dict, or ERC20TokenMetadata instance"
        )
    
    @classmethod
    def parse_from_dict(cls, data: Any) -> CoreResource:
        """Parse a resource from a dictionary or return existing Resource instance.
        
        Converts dictionary payloads into the appropriate Resource subclass:
        - If data is already a Resource instance → returns it unchanged
        - If data is a JSON string → deserializes it first, then dispatches
        - If dict contains 'token' key → returns TokenResource (takes precedence)
        - If dict contains 'gpu_model' key → returns ComputeResource
        - If dict contains both keys → returns TokenResource (token takes precedence)
        - If dict contains neither key → raises ValueError
        - If data is not a dict and not a Resource → returns data unchanged
        
        Args:
            data: Dictionary with resource data, JSON string, existing Resource
                  instance, or other value
            
        Returns:
            Resource instance (TokenResource, ComputeResource, or existing Resource)
            
        Raises:
            ValueError: If data is a dict but doesn't contain required keys for
                        any resource type
        """
        # If already a Resource instance, return it unchanged
        if isinstance(data, CoreResource):
            return data

        # Deserialize JSON strings — SQLite stores resources as JSON text
        if isinstance(data, str):
            import json as _json
            try:
                data = _json.loads(data)
            except (ValueError, TypeError):
                return data  # not valid JSON; pass through unchanged

        # If not a dict after attempted deserialization, return as-is
        if not isinstance(data, dict):
            return data
        
        # TokenResource takes precedence if both keys are present
        if "token" in data:
            data = dict(data)  # copy to avoid mutating caller input
            data["token"] = cls._resolve_token_metadata(data["token"])
            return TokenResource(**data)
        elif "gpu_model" in data:
            return ComputeResource(**data)
        raise ValueError(
            "Resource dict must have either 'token' (TokenResource) "
            "or 'gpu_model' (ComputeResource) key"
        )


TokenResource = CoreTokenResource

class ComputeResource(ComputeDomainResource):
    """Describes a compute slice — a sliceable allocation from a host that
    may be put on the market. The seller decides the slice configuration
    (gpu_count + vcpu_count + ram_gb + disk_gb) when publishing; one host
    can be split into multiple concurrent slices.

    Wire format is denormalized: host context fields (cpu_type, motherboard,
    host_cpu_cores, host_ram_gb, etc.) are populated from a join against the
    seller's ``hosts`` table at publish time so buyers see one flat record
    per listing. Stored-row form keeps only slice fields + the ``vm_host``
    FK; the storefront's ``ComputeGpuResourceAdapter`` handles the join.

    Configuration-only — values derivable from another field (VRAM from
    gpu_model, PCIe lanes/generation from motherboard, AVX from cpu_type)
    are intentionally omitted; consumers compute them from vendor lookup
    tables. All optional spec fields default to ``None`` so sparse payloads
    keep parsing.

    Free-form provider tags belong in ``attributes`` under the ``tag.*``
    namespace (e.g. ``attributes["tag.datacenter_tier"]``). Tags are opaque
    to the negotiation policy and matched by exact equality only.
    """

    resource_id: str | None = Field(
        default=None,
        description="Canonical DB resource identifier for this compute slice",
    )

    # ---- Slice fields (per-listing; the seller's split of the host) ----
    gpu_model: GPUModel = Field(
        description="The model of the GPU (H200, Tesla V100, RTX 5080, RTX A5000, RTX 4090)"
    )
    gpu_count: int = Field(description="Number of GPUs in this slice")
    sla: float = Field(description="The SLA of this slice")
    region: Region = Field(
        description="The region of the slice (matches host region)"
    )
    vm_host: str | None = Field(
        default=None,
        description="FK to hosts.name — which host this slice is allocated from",
    )
    vcpu_count: int | None = Field(default=None, description="vCPUs allocated to this slice")
    ram_gb: int | None = Field(default=None, description="RAM allocated to this slice in GB")
    disk_gb: int | None = Field(default=None, description="Disk allocated to this slice in GB")
    virtualization_type: VirtualizationType | None = Field(
        default=None,
        description="How this slice is exposed: bare_metal | vm | container",
    )

    # ---- Host context (denormalized at publish; sourced from hosts table) ----
    cpu_type: str | None = Field(default=None, description="Host CPU model string, e.g. 'AMD EPYC 9654'")
    host_cpu_cores: int | None = Field(default=None, description="Total physical cores on host")
    host_ram_gb: int | None = Field(default=None, description="Host total RAM in GB")
    host_disk_gb: int | None = Field(default=None, description="Host total disk capacity in GB")
    host_disk_type: str | None = Field(
        default=None,
        description="Host disk model string, e.g. 'Samsung MZTL3T8HEFK'",
    )
    motherboard: str | None = Field(default=None, description="Host motherboard model string")
    total_gpu_count: int | None = Field(default=None, description="Total GPUs on host (slice fraction = gpu_count / total_gpu_count)")
    gpu_interconnect: GpuInterconnect | None = Field(
        default=None,
        description="Host GPU-to-GPU interconnect topology",
    )
    nic_speed_gbps: int | None = Field(default=None, description="Host primary NIC link speed in Gbps")
    internet_download_mbps: int | None = Field(default=None, description="Host internet downlink in Mbps")
    internet_upload_mbps: int | None = Field(default=None, description="Host internet uplink in Mbps")
    static_ip: bool | None = Field(default=None, description="Whether the host has a static public IP")
    open_ports_count: int | None = Field(
        default=None,
        description="Number of externally-routable TCP ports the host exposes",
    )
    datacenter_grade: bool | None = Field(
        default=None,
        description="True for commercial datacenter hosting (vs home/colo)",
    )


class ComputeResourcePortfolio(BaseModel):
    """Describes the resource portfolio of an Agent."""

    resources: list[ComputeResource] = Field(description="The resources in the portfolio")

    def total_gpu_count(self, gpu_model: GPUModel | None = None) -> int:
        """Calculate total GPU gpu_count, optionally filtered by model"""
        if gpu_model:
            return sum(r.gpu_count for r in self.resources if r.gpu_model == gpu_model)
        return sum(r.gpu_count for r in self.resources)

    def has_capacity(self, required: ComputeResource) -> bool:
        """Check if portfolio has sufficient capacity for a required resource.

        Mandatory match: gpu_model, region, gpu_count (>=), sla (>=).

        Optional spec fields are enforced only when the demand side specifies
        them (i.e., is not None). Numeric fields use >=; enum/string/bool
        fields use exact equality. If the demand specifies a constraint and
        the offered resource has the field as None, the resource is rejected
        — an unknown spec can't be assumed to satisfy a stated requirement.
        """
        numeric_min_fields = (
            "vcpu_count",
            "ram_gb",
            "disk_gb",
            "host_cpu_cores",
            "host_ram_gb",
            "host_disk_gb",
            "total_gpu_count",
            "nic_speed_gbps",
            "internet_download_mbps",
            "internet_upload_mbps",
            "open_ports_count",
        )
        equality_fields = (
            "cpu_type",
            "host_disk_type",
            "motherboard",
            "gpu_interconnect",
            "virtualization_type",
            "static_ip",
            "datacenter_grade",
        )
        for resource in self.resources:
            if not (
                resource.gpu_model == required.gpu_model
                and resource.region == required.region
                and resource.gpu_count >= required.gpu_count
                and resource.sla >= required.sla
            ):
                continue
            ok = True
            for field in numeric_min_fields:
                req_v = getattr(required, field)
                if req_v is None:
                    continue
                res_v = getattr(resource, field)
                if res_v is None or res_v < req_v:
                    ok = False
                    break
            if not ok:
                continue
            for field in equality_fields:
                req_v = getattr(required, field)
                if req_v is None:
                    continue
                if getattr(resource, field) != req_v:
                    ok = False
                    break
            if ok:
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
                existing.gpu_count += resource.gpu_count
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
                if existing.gpu_count >= resource.gpu_count:
                    existing.gpu_count -= resource.gpu_count
                    if existing.gpu_count == 0:
                        self.resources.remove(existing)
                    return True
        return False


class Listing(BaseModel):
    """Marketplace listing for trading compute resources and tokens."""

    listing_id: str = Field(description="The id of the listing")
    seller: str = Field(description="The card URL of the agent that posted the listing")
    buyer: str | None = Field(
        default="",
        description="The card URL of the agent that took the listing",
    )
    offer_resource: Union[ComputeResource, TokenResource] = Field(
        description="The resource being offered, which may be a token or compute resource."
    )
    accepted_escrows: list[AcceptedEscrow] | None = Field(
        default=None,
        description=(
            "Per-listing list of accepted on-chain escrow shapes (chain + "
            "escrow address + advertised partial fields + per-hour price). "
            "Canonical pricing+escrow advertisement; the buyer's escrow "
            "proposal must pick one of these entries by (chain_name, "
            "escrow_address)."
        ),
    )
    max_duration_seconds: int | None = Field(
        default=None,
        description=(
            "Optional ceiling on lease duration in seconds. None = unlimited. "
            "accepted_escrows[i].price_per_hour is the advertised per-hour "
            "rate; total payment is computed at agreement time as "
            "price_per_hour * agreed_duration_seconds / 3600."
        ),
    )
    seller_attestation: str | None = Field(
        default=None,
        description="The seller's fulfillment attestation UID (None until fulfillment lands).",
    )
    buyer_attestation: str | None = Field(
        default=None,
        description="The buyer's escrow attestation UID (None until escrow is locked).",
    )
    oracle_address: str | None = Field(
        default=None,
        description="The oracle wallet address used for arbitration and escrow workflows",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_resources(cls, data: Any) -> Any:
        """Parse resources from dicts to Resource types."""
        if not isinstance(data, dict):
            return data

        if "offer_resource" in data:
            data["offer_resource"] = ComputeDomainResource.parse_from_dict(data["offer_resource"])

        return data

    def is_open(self) -> bool:
        """Check if this is an open listing (escrow or fulfillment missing)."""
        return self.seller_attestation is None or self.buyer_attestation is None

    def is_closed(self) -> bool:
        """Check if this listing is fully attested (both escrow and fulfillment)."""
        return self.seller_attestation is not None and self.buyer_attestation is not None


# =============================
# Event models for A2A workflow
# =============================


class EventType(str, Enum):
    """Events that can be handled by the Agent"""

    ORDER_CREATE = "order_create"
    ORDER_CLOSE = "order_close"
    RESOURCE_IMBALANCE = "resource_imbalance"
    # Pre-thread guard hook: fires from /negotiate/new before any state
    # mutation. The seeded policy composite runs guards (e.g. inventory
    # match) and emits REJECT_OFFER with a reason on veto, mapped to
    # HTTP 409 (OfferUnfulfillableError) by the negotiate flow. Operators
    # who want to support non-immediate deals (futures, off-chain matched)
    # swap the composite's components for an empty list or an alternative
    # guard set.
    NEGOTIATION_REQUESTED = "negotiation_requested"
DomainEvent = CoreDomainEvent


class ListingCreatedEvent(DomainEvent):
    """Event triggered when a local client requests order creation."""

    event_type: EventType = Field(default=EventType.ORDER_CREATE)
    offer: Union[ComputeResource, TokenResource] = Field(
        description="Offered resource (compute or token)"
    )
    demand: Union[ComputeResource, TokenResource] = Field(
        description="Demanded resource (compute or token)"
    )
    max_duration_seconds: int | None = Field(
        default=None,
        description=(
            "Optional max lease duration in seconds (None = unlimited). "
            "Buyer asks for an actual duration at negotiation init."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def parse_resources(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "offer" in data:
            data["offer"] = ComputeDomainResource.parse_from_dict(data["offer"])
        if "demand" in data:
            data["demand"] = ComputeDomainResource.parse_from_dict(data["demand"])
        return data


class ListingClosedEvent(DomainEvent):
    """Event triggered when a local client requests listing closure."""

    event_type: EventType = Field(default=EventType.ORDER_CLOSE)
    listing_id: str = Field(description="Listing ID to close")


class NegotiationRequestedEvent(DomainEvent):
    """Event triggered when a buyer asks to start a negotiation thread.

    Fires from ``sync_negotiation.start_negotiation_for_remote_request``
    before any thread state is written. The seeded guard composite runs
    against this event; if any guard returns ``REJECT_OFFER``, the flow
    short-circuits with HTTP 409 and the reason in the action's
    ``parameters["reason"]``.

    Carries the listing dict (so guards can read ``offer_resource``,
    ``accepted_escrows``, ``status``, etc.) plus the buyer's proposed
    price, duration, and escrow proposal so escrow- and price-aware
    guards can run against the request before any thread state is
    written.
    """

    event_type: EventType = Field(default=EventType.NEGOTIATION_REQUESTED)
    listing_id: str = Field(description="Listing the buyer wants to negotiate against")
    listing: dict[str, Any] = Field(
        default_factory=dict,
        description="Full listing row from sqlite (offer_resource, accepted_escrows, status, ...)",
    )
    proposed_price: int | None = Field(
        default=None,
        description="Buyer's initial price proposal (None if not provided)",
    )
    requested_duration_seconds: int | None = Field(
        default=None,
        description="Buyer's requested lease duration in seconds (None if not provided)",
    )
    escrow_proposal: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Buyer's EscrowProposal as a dict (chain_name, escrow_address, "
            "fields, expiration_unix). None for legacy clients."
        ),
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
        description="Resource details with required fields: gpu_model, gpu_count, sla, region"
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
        required_fields = ["gpu_model", "gpu_count", "sla", "region"]
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
        gpu_count = int(self.resource["gpu_count"])
        sla = float(self.resource["sla"])
        region = Region(self.resource["region"])
        
        # Create ComputeResource
        compute_resource = ComputeResource(
            gpu_model=gpu_model,
            gpu_count=gpu_count,
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
                "gpu_count": gpu_count,
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
                    required_fields = ["gpu_model", "gpu_count", "sla", "region"]
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
            required_fields = ["gpu_model", "gpu_count", "sla", "region"]
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
                "gpu_count": resource.gpu_count,
                "region": resource.region.value,
                "imbalance_type": imbalance_type,
                "severity": severity,
            },
        )


# =============================
# Decision and Action domain models for reactive agents
# =============================
# ActionType moved to service.schemas (imported at module top).


Action = CoreDomainAction
DecisionContext = CoreDecisionContext
Decision = CoreDecision
