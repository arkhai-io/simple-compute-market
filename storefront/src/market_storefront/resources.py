from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol

from market_storefront.schema.pydantic_models import (
    ComputeResource,
    ERC20TokenMetadata,
    GpuInterconnect,
    TokenResource,
    VirtualizationType,
)
from service.clients.token import TOKEN_REGISTRY


# Optional spec fields on ComputeResource that round-trip through the DB
# resource ``attributes`` dict. The attribute key matches the model field.
# Items are (field_name, coercer-or-None). Coercer maps the raw attribute
# value back into the typed field on read; None means pass-through.
_COMPUTE_OPTIONAL_SPEC_FIELDS: tuple[tuple[str, Any], ...] = (
    ("cpu_type", None),
    ("cpu_count", int),
    ("ram_gb", int),
    ("disk_gb", int),
    ("disk_type", None),
    ("disk_count", int),
    ("motherboard", None),
    ("gpu_interconnect", GpuInterconnect),
    ("nic_speed_gbps", int),
    ("internet_download_mbps", int),
    ("internet_upload_mbps", int),
    ("static_ip", bool),
    ("open_ports_count", int),
    ("virtualization_type", VirtualizationType),
    ("datacenter_grade", bool),
)


class ResourceAdapter(Protocol):
    """Adapter interface for mapping between DB rows, network dicts, and domain schemas."""

    resource_type: Final[str]
    domain_type: Final[type]
    discriminator_key: Final[str]

    def to_domain_resource(self, db_resource: dict[str, Any]) -> Any:
        """DB row -> Python schema."""
        ...

    def from_domain_resource(
        self,
        resource: Any,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Python schema -> DB row."""
        ...

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Network dict (A2A) -> Python schema."""
        ...

    def to_dict(self, resource: Any) -> dict[str, Any]:
        """Python schema -> network dict (A2A)."""
        ...


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class ComputeGpuResourceAdapter:
    resource_type: str = "compute.gpu"
    domain_type: type = ComputeResource
    discriminator_key: str = "gpu_model"

    def to_domain_resource(self, db_resource: dict[str, Any]) -> ComputeResource:
        """
        Convert a DB resource dict to a ComputeResource domain instance.
        """
        attrs = _ensure_dict(db_resource.get("attributes"))

        gpu_model = attrs.get("gpu_model") or db_resource.get("resource_subtype")
        gpu_count = db_resource.get("value")
        if gpu_count is None:
            gpu_count = attrs.get("gpu_count", 0)
        sla = attrs.get("sla")
        region = attrs.get("region")
        vm_host = attrs.get("vm_host")

        if gpu_model is None or sla is None or region is None:
            raise ValueError(
                "compute.gpu db_resource requires attributes.gpu_model/resource_subtype, attributes.sla, and attributes.region"
            )

        optional_kwargs: dict[str, Any] = {}
        for field_name, coerce in _COMPUTE_OPTIONAL_SPEC_FIELDS:
            raw = attrs.get(field_name)
            if raw is None:
                continue
            optional_kwargs[field_name] = coerce(raw) if coerce is not None else raw

        return ComputeResource(
            resource_id=str(db_resource.get("resource_id")) if db_resource.get("resource_id") is not None else None,
            gpu_model=gpu_model,
            gpu_count=int(gpu_count),
            sla=float(sla),
            region=region,
            vm_host=str(vm_host) if vm_host is not None else None,
            **optional_kwargs,
        )

    def from_domain_resource(
        self,
        resource: ComputeResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert a ComputeResource domain instance to a DB resource dict."""
        attributes: dict[str, Any] = {
            "gpu_model": resource.gpu_model.value,
            "sla": resource.sla,
            "region": resource.region.value,
            "vm_host": resource.vm_host,
        }
        for field_name, _ in _COMPUTE_OPTIONAL_SPEC_FIELDS:
            v = getattr(resource, field_name)
            if v is None:
                continue
            attributes[field_name] = v.value if isinstance(v, Enum) else v
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.gpu_model.value.lower(),
            "unit": "count",
            "value": resource.gpu_count,
            "state": state,
            "attributes": attributes,
        }

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

    def to_domain_resource(self, db_resource: dict[str, Any]) -> TokenResource:
        """
        Convert a DB resource dict to a TokenResource domain instance.
        """
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
        """
        Convert a TokenResource domain instance to a DB resource dict.
        """
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

    def from_dict(self, data: dict[str, Any]) -> TokenResource:
        """
        Convert a network dict (A2A payload) to a TokenResource domain instance.
        """
        token_value = data.get("token")
        if isinstance(token_value, ERC20TokenMetadata):
            token_meta = token_value
        elif isinstance(token_value, dict):
            if all(k in token_value for k in ("symbol", "contract_address", "decimals")):
                token_meta = ERC20TokenMetadata(**token_value)
            elif "symbol" in token_value:
                token_meta = TOKEN_REGISTRY.require(token_value["symbol"])
            elif "contract_address" in token_value:
                token_meta = TOKEN_REGISTRY.require(token_value["contract_address"])
            else:
                raise ValueError("Token dict must include symbol, contract_address, or decimals")
        elif isinstance(token_value, str):
            token_meta = TOKEN_REGISTRY.require(token_value)
        else:
            raise ValueError(f"Unsupported token value type: {type(token_value).__name__}")
        return TokenResource(token=token_meta, amount=int(data["amount"]))

    def to_dict(self, resource: TokenResource) -> dict[str, Any]:
        """
        Convert a TokenResource domain instance to a network dict (A2A payload).
        """
        return {"resource_type": self.resource_type, **resource.model_dump()}


_RESOURCE_TYPE_TO_ADAPTER: dict[str, ResourceAdapter] = {}
_DOMAIN_TYPE_TO_ADAPTER: dict[type, ResourceAdapter] = {}


def register_resource_adapter(adapter: ResourceAdapter) -> None:
    """
    Register a ResourceAdapter for mapping between DB rows, network dicts, and domain schemas.
    """
    _RESOURCE_TYPE_TO_ADAPTER[adapter.resource_type] = adapter
    _DOMAIN_TYPE_TO_ADAPTER[adapter.domain_type] = adapter


def get_resource_adapter(resource_type: str) -> ResourceAdapter | None:
    """
    Get the registered ResourceAdapter for a given resource_type, or None if not found.
    """
    return _RESOURCE_TYPE_TO_ADAPTER.get(resource_type)


def get_supported_resource_types() -> set[str]:
    """Return resource types that have registered domain adapters."""
    return set(_RESOURCE_TYPE_TO_ADAPTER)


def adapt_db_resource_to_domain_resource(db_resource: dict[str, Any]) -> Any:
    """
    Adapt a DB resource dict to the appropriate domain resource instance using the registered adapter.
     - If no adapter is found for the resource_type, returns the original db_resource dict.
     - Raises ValueError if resource_type is missing or if the adapter fails to convert.
    """
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
    """
    Adapt a domain resource instance to a DB resource dict using the registered adapter.
    Raises ValueError if no adapter is found for the resource's type or if the adapter fails to convert.
    """
    adapter = _DOMAIN_TYPE_TO_ADAPTER.get(type(resource))
    if adapter is None:
        raise ValueError(f"Unsupported domain resource type: {type(resource).__name__}")
    return adapter.from_domain_resource(resource, resource_id=resource_id, state=state)


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
