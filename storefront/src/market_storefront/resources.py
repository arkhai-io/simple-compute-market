"""Compatibility re-exports for VM resource adapters."""

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

__all__ = [
    "ComputeGpuResourceAdapter",
    "ResourceAdapter",
    "TokenErc20ResourceAdapter",
    "adapt_db_resource_to_domain_resource",
    "adapt_domain_resource_to_db_resource",
    "get_resource_adapter",
    "get_supported_resource_types",
    "parse_resource_from_dict",
    "register_resource_adapter",
]
