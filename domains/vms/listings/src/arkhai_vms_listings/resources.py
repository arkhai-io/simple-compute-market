from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

from arkhai_vms_listings.models import (
    ComputeResource,
    ERC20TokenMetadata,
    TokenResource,
)
from market_alkahest.token import resolve_token_cached


class ResourceAdapter(Protocol):
    """Adapter interface for mapping between network dicts and domain schemas."""

    resource_type: Final[str]
    domain_type: Final[type]
    discriminator_key: Final[str]

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Network dict (A2A) -> Python schema."""
        ...

    def to_dict(self, resource: Any) -> dict[str, Any]:
        """Python schema -> network dict (A2A)."""
        ...


@dataclass(frozen=True)
class ComputeGpuResourceAdapter:
    resource_type: str = "compute.gpu"
    domain_type: type = ComputeResource
    discriminator_key: str = "gpu_model"

    def from_dict(self, data: dict[str, Any]) -> ComputeResource:
        """
        Convert a network dict (A2A payload) to a ComputeResource domain instance.
        """
        return ComputeResource(**data)

    def to_dict(self, resource: ComputeResource) -> dict[str, Any]:
        """
        Convert a ComputeResource domain instance to a network dict (A2A payload).
        """
        return {"resource_type": self.resource_type, **resource.model_dump()}


@dataclass(frozen=True)
class TokenErc20ResourceAdapter:
    resource_type: str = "token.erc20"
    domain_type: type = TokenResource
    discriminator_key: str = "token"

    def from_dict(self, data: dict[str, Any]) -> TokenResource:
        """Convert a network dict to a TokenResource — strict address-only.

        Accepted shapes for ``data["token"]``:
          * ``"0x..."`` — bare contract address; metadata enriched via
            the chain-resolved cache if known, otherwise the address-only
            stub (decimals must then be supplied on the wire or inferred
            from ``data["decimals"]``).
          * ``{"contract_address": "0x...", "decimals": N, "symbol"?: ...}``
            — full metadata; ``decimals`` is required since amount math
            depends on it.
          * ``ERC20TokenMetadata`` instance — pass-through.

        Bare symbol strings (``"USDC"``) are NOT accepted. Addresses are
        the canonical token identity; symbols are derived view data
        resolved on-chain.
        """
        token_value = data.get("token")
        if isinstance(token_value, ERC20TokenMetadata):
            token_meta = token_value
        elif isinstance(token_value, dict):
            address = token_value.get("contract_address")
            if not address or not isinstance(address, str):
                raise ValueError(
                    "token dict must include 'contract_address' (0x...)"
                )
            decimals = token_value.get("decimals")
            if decimals is None:
                looked_up = resolve_token_cached(address)
                if looked_up is None:
                    raise ValueError(
                        f"token dict for {address} must include 'decimals' "
                        f"(no cached chain metadata for this address)"
                    )
                token_meta = looked_up
            else:
                token_meta = ERC20TokenMetadata(
                    symbol=str(token_value.get("symbol", "")),
                    contract_address=str(address),
                    decimals=int(decimals),
                )
        elif isinstance(token_value, str):
            if not token_value.startswith("0x"):
                raise ValueError(
                    f"token string must be a 0x-prefixed address, got {token_value!r}"
                )
            looked_up = resolve_token_cached(token_value)
            if looked_up is not None:
                token_meta = looked_up
            else:
                token_meta = ERC20TokenMetadata(
                    symbol="",
                    contract_address=token_value,
                    decimals=0,
                )
        else:
            raise ValueError(f"Unsupported token value type: {type(token_value).__name__}")
        amount_raw = data.get("amount")
        amount = None if amount_raw is None else int(amount_raw)
        return TokenResource(token=token_meta, amount=amount)

    def to_dict(self, resource: TokenResource) -> dict[str, Any]:
        """
        Convert a TokenResource domain instance to a network dict (A2A payload).
        """
        return {"resource_type": self.resource_type, **resource.model_dump()}


_RESOURCE_TYPE_TO_ADAPTER: dict[str, ResourceAdapter] = {}


def register_resource_adapter(adapter: ResourceAdapter) -> None:
    """
    Register a ResourceAdapter for mapping between network dicts and domain schemas.
    """
    _RESOURCE_TYPE_TO_ADAPTER[adapter.resource_type] = adapter


def get_resource_adapter(resource_type: str) -> ResourceAdapter | None:
    """
    Get the registered ResourceAdapter for a given resource_type, or None if not found.
    """
    return _RESOURCE_TYPE_TO_ADAPTER.get(resource_type)


def parse_resource_from_dict(data: Any) -> Any:
    """Parse a network dict (A2A payload) to a Python schema.

    - Non-dict values (including existing domain instances) are returned as-is.
    - Prefers explicit ``resource_type`` field; falls back to discriminator_key
      heuristics for backward compatibility.
    """
    if not isinstance(data, dict):
        return data

    resource_type = data.get("resource_type")
    if isinstance(resource_type, str):
        adapter = _RESOURCE_TYPE_TO_ADAPTER.get(resource_type)
        if adapter is not None:
            return adapter.from_dict(data)

    # Fallback: heuristic matching via discriminator_key
    for adapter in _RESOURCE_TYPE_TO_ADAPTER.values():
        if adapter.discriminator_key in data:
            return adapter.from_dict(data)

    raise ValueError(
        f"Cannot determine resource type from dict keys: {list(data.keys())}"
    )


# Register built-in adapters.
register_resource_adapter(ComputeGpuResourceAdapter())
register_resource_adapter(TokenErc20ResourceAdapter())
