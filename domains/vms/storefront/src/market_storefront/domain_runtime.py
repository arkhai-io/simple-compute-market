"""Storefront composition root for the VM market domain runtime."""

from __future__ import annotations

from core_storefront.domain_runtime import StorefrontDomainRuntime


def get_storefront_domain_runtime() -> StorefrontDomainRuntime:
    """Return the VM domain runtime injected into this storefront."""
    from arkhai_vms.domain_runtime import storefront_runtime

    return storefront_runtime()

