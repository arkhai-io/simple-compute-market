"""Module-level IdentityRegistryClient initialized lazily on first use.

Provides a single shared client to the routes that JIT-index agents
(`_ensure_agent_indexed` in api/utils.py). Centralizes the read path so
ownerOf/tokenURI calls don't spin up a fresh web3 connection per request.
"""

from __future__ import annotations

from src.config import settings
from src.contracts.identity_registry import IdentityRegistryClient
from src.types import NetworkConfig

_client: IdentityRegistryClient | None = None


def get_identity_registry() -> IdentityRegistryClient:
    global _client
    if _client is None:
        _client = IdentityRegistryClient(
            NetworkConfig(
                chain_id=settings.chain_id,
                rpc_url=settings.rpc_url,
                identity_registry=settings.identity_registry_address,
                reputation_registry=settings.reputation_registry_address,
                validation_registry=settings.validation_registry_address,
            )
        )
    return _client


def reset() -> None:
    """Drop the cached client. Test-only — production never calls this."""
    global _client
    _client = None
