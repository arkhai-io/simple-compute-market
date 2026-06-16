"""Compatibility shim — the registry fan-in/fan-out client moved to
``core_storefront.multi_registry_client`` when the API-tokens domain
became the second storefront composition root."""

from core_storefront.multi_registry_client import (  # noqa: F401
    MultiRegistryClient,
    PublishResult,
)
