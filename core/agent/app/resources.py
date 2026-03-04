from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.agent.app.schema.pydantic_models import (
    ComputeResource,
    ERC20TokenMetadata,
    TokenResource,
)
from core.agent.app.utils.token_registry import TOKEN_REGISTRY


class ResourceAdapter(Protocol):
    """Adapter interface for mapping generic DB resources to domain resources."""

    resource_type: str

    def to_domain_resource(self, db_resource: dict[str, Any]) -> Any:
        ...

    def from_domain_resource(
        self,
        resource: Any,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        ...


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class ComputeGpuResourceAdapter:
    resource_type: str = "compute.gpu"

    def to_domain_resource(self, db_resource: dict[str, Any]) -> ComputeResource:
        attrs = _ensure_dict(db_resource.get("attributes"))

        gpu_model = attrs.get("gpu_model") or db_resource.get("resource_subtype")
        quantity = db_resource.get("value")
        if quantity is None:
            quantity = attrs.get("quantity", 0)
        sla = attrs.get("sla")
        region = attrs.get("region")

        if gpu_model is None or sla is None or region is None:
            raise ValueError(
                "compute.gpu db_resource requires attributes.gpu_model/resource_subtype, attributes.sla, and attributes.region"
            )

        return ComputeResource(
            gpu_model=gpu_model,
            quantity=int(quantity),
            sla=float(sla),
            region=region,
        )

    def from_domain_resource(
        self,
        resource: ComputeResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.gpu_model.value.lower(),
            "unit": "count",
            "value": resource.quantity,
            "state": state,
            "attributes": {
                "gpu_model": resource.gpu_model.value,
                "sla": resource.sla,
                "region": resource.region.value,
            },
        }


@dataclass(frozen=True)
class TokenErc20ResourceAdapter:
    resource_type: str = "token.erc20"

    def to_domain_resource(self, db_resource: dict[str, Any]) -> TokenResource:
        attrs = _ensure_dict(db_resource.get("attributes"))
        subtype = db_resource.get("resource_subtype")
        value = db_resource.get("value")
        if value is None:
            value = attrs.get("amount", 0)

        token_meta: ERC20TokenMetadata
        if all(k in attrs for k in ("symbol", "contract_address", "decimals")):
            token_meta = ERC20TokenMetadata(
                symbol=str(attrs["symbol"]),
                contract_address=str(attrs["contract_address"]),
                decimals=int(attrs["decimals"]),
            )
        elif subtype:
            token_meta = TOKEN_REGISTRY.require(str(subtype))
        else:
            raise ValueError(
                "token.erc20 db_resource requires token metadata in attributes or resource_subtype resolvable by token registry"
            )

        return TokenResource(token=token_meta, amount=int(value))

    def from_domain_resource(
        self,
        resource: TokenResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.token.symbol.lower(),
            "unit": "base_units",
            "value": resource.amount,
            "state": state,
            "attributes": {
                "symbol": resource.token.symbol,
                "contract_address": resource.token.contract_address,
                "decimals": resource.token.decimals,
            },
        }


RESOURCE_ADAPTERS: dict[str, ResourceAdapter] = {}


def register_resource_adapter(adapter: ResourceAdapter) -> None:
    RESOURCE_ADAPTERS[adapter.resource_type] = adapter


def get_resource_adapter(resource_type: str) -> ResourceAdapter | None:
    return RESOURCE_ADAPTERS.get(resource_type)


def adapt_db_resource_to_domain_resource(db_resource: dict[str, Any]) -> Any:
    resource_type = db_resource.get("resource_type")
    if not isinstance(resource_type, str):
        raise ValueError("DB resource missing resource_type")
    adapter = get_resource_adapter(resource_type)
    if adapter is None:
        return db_resource
    return adapter.to_domain_resource(db_resource)


def adapt_domain_resource_to_db_resource(
    resource: Any,
    *,
    resource_id: str,
    state: str | None = None,
) -> dict[str, Any]:
    if isinstance(resource, ComputeResource):
        adapter = get_resource_adapter("compute.gpu")
        if adapter is None:
            raise ValueError("Adapter not registered for compute.gpu")
        return adapter.from_domain_resource(
            resource, resource_id=resource_id, state=state
        )
    if isinstance(resource, TokenResource):
        adapter = get_resource_adapter("token.erc20")
        if adapter is None:
            raise ValueError("Adapter not registered for token.erc20")
        return adapter.from_domain_resource(
            resource, resource_id=resource_id, state=state
        )
    raise ValueError(f"Unsupported domain resource type: {type(resource).__name__}")


# Register built-in adapters.
register_resource_adapter(ComputeGpuResourceAdapter())
register_resource_adapter(TokenErc20ResourceAdapter())
