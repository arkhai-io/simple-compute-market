"""Storefront composition root for the API-credits market domain runtime."""

from __future__ import annotations

from core_storefront.domain_runtime import StorefrontDomainRuntime


def get_storefront_domain_runtime() -> StorefrontDomainRuntime:
    """Return the API-credits domain runtime injected into this storefront."""
    from domains.apicredits.domain_runtime import storefront_runtime

    return storefront_runtime()
