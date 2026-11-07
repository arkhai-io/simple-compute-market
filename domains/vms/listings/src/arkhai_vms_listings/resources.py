from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

from arkhai_vms_listings.models import (
    COMPUTE_RESOURCE_TYPE,
    TOKEN_RESOURCE_TYPE,
    ComputeResource,
    ERC20TokenMetadata,
    TokenResource,
)
from market_alkahest.token import resolve_token_cached


class ResourceAdapter(Protocol):
    """Adapter interface for mapping between network dicts and domain schemas.

    ``discriminator_key`` is a key whose presence selects the adapter for a
    payload naming no registered ``resource_type``; the compute adapter has
    none, because it takes every payload no other adapter selects.
    """

    resource_type: Final[str]
    domain_type: Final[type]
    discriminator_key: Final[str | None]

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Network dict (A2A) -> Python schema."""
        ...

    def to_dict(self, resource: Any) -> dict[str, Any]:
        """Python schema -> network dict (A2A)."""
        ...


@dataclass(frozen=True)
class ComputeGpuResourceAdapter:
    resource_type: str = COMPUTE_RESOURCE_TYPE
    domain_type: type = ComputeResource
    # No key recognises compute: a slice without GPUs carries no GPU field.
    discriminator_key: str | None = None

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
    resource_type: str = TOKEN_RESOURCE_TYPE
    domain_type: type = TokenResource
    discriminator_key: str | None = "token"

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
    - An explicit, registered ``resource_type`` selects its adapter.
    - Otherwise an adapter whose ``discriminator_key`` the payload carries
      selects itself, as ``token`` selects the token adapter.
    - Any other mapping is compute, whose validation refuses one whose fields
      state no shape. Over the built-in adapters this is
      ``payload_resource_type``'s rule.
    """
    if not isinstance(data, dict):
        return data

    resource_type = data.get("resource_type")
    if isinstance(resource_type, str):
        adapter = _RESOURCE_TYPE_TO_ADAPTER.get(resource_type)
        if adapter is not None:
            return adapter.from_dict(data)

    for adapter in _RESOURCE_TYPE_TO_ADAPTER.values():
        if adapter.discriminator_key is not None and adapter.discriminator_key in data:
            return adapter.from_dict(data)

    return _RESOURCE_TYPE_TO_ADAPTER[COMPUTE_RESOURCE_TYPE].from_dict(data)


# Register built-in adapters.
register_resource_adapter(ComputeGpuResourceAdapter())
register_resource_adapter(TokenErc20ResourceAdapter())
