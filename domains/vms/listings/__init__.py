"""VM listing schema helpers."""

from domains.vms.listings.buyer_cli import (
    build_vm_filter_params,
    format_accepted_escrows,
    format_demands,
    format_resource,
    short_ts,
    shorten,
)
from domains.vms.listings.models import (
    ComputeDomainResource,
    ComputeResource,
    ComputeResourcePortfolio,
    ERC20TokenMetadata,
    GPUModel,
    GpuInterconnect,
    Host,
    Listing,
    Region,
    TokenResource,
    VirtualizationType,
)
from domains.vms.listings.pricing import (
    extract_compute_from_order,
    extract_initial_price_from_order,
    resource_is_compute,
)
from domains.vms.listings.resources import (
    ComputeGpuResourceAdapter,
    ResourceAdapter,
    TokenErc20ResourceAdapter,
    adapt_db_resource_to_domain_resource,
    adapt_domain_resource_to_db_resource,
    get_resource_adapter,
    get_supported_resource_types,
    parse_resource_from_dict,
    register_resource_adapter,
)
from domains.vms.listings.strategy import (
    determine_strategy_from_order,
    determine_strategy_from_resources,
)

__all__ = [
    "build_vm_filter_params",
    "adapt_db_resource_to_domain_resource",
    "adapt_domain_resource_to_db_resource",
    "ComputeDomainResource",
    "ComputeGpuResourceAdapter",
    "ComputeResource",
    "ComputeResourcePortfolio",
    "determine_strategy_from_order",
    "determine_strategy_from_resources",
    "ERC20TokenMetadata",
    "extract_compute_from_order",
    "extract_initial_price_from_order",
    "format_accepted_escrows",
    "format_demands",
    "format_resource",
    "GPUModel",
    "GpuInterconnect",
    "get_resource_adapter",
    "get_supported_resource_types",
    "Host",
    "Listing",
    "parse_resource_from_dict",
    "Region",
    "register_resource_adapter",
    "ResourceAdapter",
    "resource_is_compute",
    "short_ts",
    "shorten",
    "TokenErc20ResourceAdapter",
    "TokenResource",
    "VirtualizationType",
]
