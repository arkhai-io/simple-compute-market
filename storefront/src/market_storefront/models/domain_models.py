from enum import Enum
from datetime import datetime
from typing import Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator
import uuid

from service.schemas import (
    AcceptedEscrow,
    ActionType,
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
# └── ComputeResourcePortfolio      Collection of ComputeResource slices
#
# Enumerations
# ├── GPUModel          Advisory string-enum of common NVIDIA models.
# │                       Field types are plain `str`; the indexer's
# │                       filter-spec.yaml is the authoritative vocabulary.
# ├── Region            Advisory string-enum. Field types are plain `str`;
# │                       region vocabularies are indexer-local.
# ├── GpuInterconnect   nvlink | nvswitch | pcie_only | infiniband
# └── VirtualizationType bare_metal | vm | container
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

    name: str = Field(description="Host alias (matches provisioning-service host alias, e.g. 'kvm1').")
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
    gpu_model: str | None = Field(default=None, description="GPU model (assumes homogeneous GPUs per host in v1)")
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
    region: str | None = Field(default=None, description="Geographic region of the host")
    datacenter_grade: bool | None = Field(
        default=None,
        description="True for commercial datacenter hosting (vs home/colo)",
    )
    attributes: dict[str, Any] | None = Field(
        default=None,
        description="Free-form provider tags under the 'tag.*' namespace.",
    )
    enabled: bool = Field(default=True, description="Whether the host is active")


class ComputeDomainResource(CoreResource):
    """Compute-domain resource parser extension on top of core Resource."""

    @staticmethod
    def _resolve_token_metadata(token_value: Any) -> ERC20TokenMetadata:
        """Materialize ``ERC20TokenMetadata`` from a wire payload.

        Strict address-only on the wire: bare strings must be 0x-prefixed
        addresses; bare symbols are rejected. Addresses are enriched with
        symbol/decimals from the chain-resolved cache when present;
        addresses not yet cached yield an address-only stub
        (``symbol=""``, ``decimals=0``). For dicts, ``contract_address``
        is required.
        """
        if isinstance(token_value, ERC20TokenMetadata):
            return token_value
        if isinstance(token_value, dict):
            if not token_value.get("contract_address"):
                raise ValueError(
                    "Token dict must include 'contract_address' (0x...)"
                )
            return ERC20TokenMetadata(**token_value)
        if isinstance(token_value, str):
            if not token_value.startswith("0x"):
                raise ValueError(
                    f"Token string must be a 0x-prefixed address, got "
                    f"{token_value!r}"
                )
            from service.clients.token import resolve_token_cached

            looked_up = resolve_token_cached(token_value)
            if looked_up is not None:
                return looked_up
            return ERC20TokenMetadata(
                symbol="",
                contract_address=token_value,
                decimals=0,
            )
        raise ValueError(
            "Token value must be a 0x-address string, ERC20TokenMetadata "
            "dict (with contract_address), or ERC20TokenMetadata instance"
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
    gpu_model: str = Field(
        description="GPU model identifier. The indexer's filter-spec.yaml "
                    "is the authoritative vocabulary; the storefront accepts "
                    "any string."
    )
    gpu_count: int = Field(description="Number of GPUs in this slice")
    sla: float = Field(description="The SLA of this slice")
    region: str = Field(
        description="Geographic region of the slice (matches host region)"
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

    def total_gpu_count(self, gpu_model: str | None = None) -> int:
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


# =============================
# =============================
# Decision and Action domain models — re-exported from service.schemas
# for back-compat with callers that import via this module. Direct
# producers/consumers are migrating off these; phase 4 deletes them.
# =============================


DomainEvent = CoreDomainEvent
Action = CoreDomainAction
DecisionContext = CoreDecisionContext
Decision = CoreDecision
