from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol

from market_storefront.models.domain_models import (
    ComputeResource,
    ERC20TokenMetadata,
    GpuInterconnect,
    TokenResource,
    VirtualizationType,
)
from service.clients.token import TOKEN_REGISTRY


# Slice fields stored directly on the resource row's ``attributes`` JSON.
# These are per-listing values the seller sets when publishing a slice.
# Items are (field_name, coercer-or-None). Coercer maps raw attribute value
# back into the typed field on read; None means pass-through string.
_COMPUTE_SLICE_FIELDS: tuple[tuple[str, Any], ...] = (
    ("vcpu_count", int),
    ("ram_gb", int),
    ("disk_gb", int),
    ("virtualization_type", VirtualizationType),
)

# Host context fields denormalized onto the wire-format ComputeResource at
# read time via a join against the hosts table. Stored on hosts rows, not on
# resources rows. Coercer applied when populating the joined ComputeResource.
_COMPUTE_HOST_CONTEXT_FIELDS: tuple[tuple[str, Any], ...] = (
    ("cpu_type", None),
    ("host_cpu_cores", int),
    ("host_ram_gb", int),
    ("host_disk_gb", int),
    ("host_disk_type", None),
    ("motherboard", None),
    ("total_gpu_count", int),
    ("gpu_interconnect", GpuInterconnect),
    ("nic_speed_gbps", int),
    ("internet_download_mbps", int),
    ("internet_upload_mbps", int),
    ("static_ip", bool),
    ("open_ports_count", int),
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

    def to_domain_resource(
        self,
        db_resource: dict[str, Any],
        host_row: dict[str, Any] | None = None,
    ) -> ComputeResource:
        """Convert a DB resource dict to a ComputeResource domain instance.

        Slice fields are read from ``db_resource.attributes``. Host context
        fields are read from ``host_row`` (a row from the ``hosts`` table)
        when provided — callers that have already loaded the seller's host
        inventory pass it here to denormalize host fields onto the returned
        ComputeResource. Without ``host_row``, host context fields fall back
        to whatever happens to be in ``attributes`` (legacy/wire payloads).
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

        slice_kwargs: dict[str, Any] = {}
        for field_name, coerce in _COMPUTE_SLICE_FIELDS:
            raw = attrs.get(field_name)
            if raw is None:
                continue
            slice_kwargs[field_name] = coerce(raw) if coerce is not None else raw

        host_kwargs: dict[str, Any] = {}
        host_source = host_row if host_row is not None else attrs
        for field_name, coerce in _COMPUTE_HOST_CONTEXT_FIELDS:
            raw = host_source.get(field_name)
            if raw is None:
                continue
            host_kwargs[field_name] = coerce(raw) if coerce is not None else raw

        return ComputeResource(
            resource_id=str(db_resource.get("resource_id")) if db_resource.get("resource_id") is not None else None,
            gpu_model=gpu_model,
            gpu_count=int(gpu_count),
            sla=float(sla),
            region=region,
            vm_host=str(vm_host) if vm_host is not None else None,
            **slice_kwargs,
            **host_kwargs,
        )

    def from_domain_resource(
        self,
        resource: ComputeResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Convert a ComputeResource domain instance to a DB resource dict.

        Only slice fields + the ``vm_host`` FK + the canonical
        gpu_model/sla/region triple are written to ``attributes``. Host
        context fields belong on the hosts table and are not written here.
        """
        attributes: dict[str, Any] = {
            "gpu_model": resource.gpu_model,
            "sla": resource.sla,
            "region": resource.region,
            "vm_host": resource.vm_host,
        }
        for field_name, _ in _COMPUTE_SLICE_FIELDS:
            v = getattr(resource, field_name)
            if v is None:
                continue
            attributes[field_name] = v.value if isinstance(v, Enum) else v
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.gpu_model.lower(),
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
        """Convert a DB resource dict to a TokenResource domain instance.

        Strict mode: ``resource_subtype`` is a contract address; metadata
        is materialized from the ``attributes`` JSON column when present,
        else looked up by address through ``TOKEN_REGISTRY`` for display
        fields (symbol). Failing that, falls back to an "address-only"
        metadata with ``symbol=""`` so downstream callers can still
        identify the token by its on-chain address.

        ``value`` of None means "hidden reserve" — the listing was
        published with no advertised price. Round-trips as
        ``amount=None``.
        """
        attrs = _ensure_dict(db_resource.get("attributes"))
        subtype = db_resource.get("resource_subtype")
        value = db_resource.get("value")
        if value is None:
            value = attrs.get("amount") if "amount" in attrs else None

        # Canonical identity is the address. Attributes carry it when the
        # row was written through from_domain_resource; legacy rows may
        # have only ``resource_subtype`` set, in which case we treat that
        # as the address (post-cutover; symbol-keyed legacy rows would
        # need a migration which is intentionally not in scope here).
        address = attrs.get("contract_address") or subtype
        if not address or not isinstance(address, str):
            raise ValueError(
                "token.erc20 db_resource needs an address in attributes.contract_address "
                "or resource_subtype"
            )

        if all(k in attrs for k in ("contract_address", "decimals")):
            token_meta = ERC20TokenMetadata(
                symbol=str(attrs.get("symbol", "")),
                contract_address=str(attrs["contract_address"]),
                decimals=int(attrs["decimals"]),
            )
        else:
            looked_up = TOKEN_REGISTRY.get_by_address(address)
            if looked_up is not None:
                token_meta = looked_up
            else:
                token_meta = ERC20TokenMetadata(
                    symbol="",
                    contract_address=address,
                    decimals=int(attrs.get("decimals", 0) or 0),
                )

        amount = None if value is None else int(value)
        return TokenResource(token=token_meta, amount=amount)

    def from_domain_resource(
        self,
        resource: TokenResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Convert a TokenResource domain instance to a DB resource dict.

        ``resource_subtype`` carries the lowercase contract address — the
        canonical identity. Symbol stays in ``attributes`` for display
        rendering but is never load-bearing.
        """
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.token.contract_address.lower(),
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
        """Convert a network dict to a TokenResource — strict address-only.

        Accepted shapes for ``data["token"]``:
          * ``"0x..."`` — bare contract address; metadata enriched via
            ``TOKEN_REGISTRY.get_by_address`` if known, otherwise the
            address-only stub (decimals must then be supplied on the
            wire or inferred from ``data["decimals"]``).
          * ``{"contract_address": "0x...", "decimals": N, "symbol"?: ...}``
            — full metadata; ``decimals`` is required since amount math
            depends on it.
          * ``ERC20TokenMetadata`` instance — pass-through.

        Bare symbol strings (``"USDC"``) are NOT accepted. Clients that
        want symbol convenience resolve to an address locally before
        calling this layer — keeps the on-the-wire format chain-agnostic
        and the server's TokenRegistry strictly a presentation cache.
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
                # Last-resort enrichment from the local registry — keeps
                # the dict shape minimal for callers that know they're
                # talking about a registered token.
                looked_up = TOKEN_REGISTRY.get_by_address(address)
                if looked_up is None:
                    raise ValueError(
                        f"token dict for {address} must include 'decimals' "
                        f"(token not in local registry)"
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
                    f"token string must be a 0x-prefixed address, got {token_value!r} "
                    f"(symbol-based identity is a client-side convenience; resolve "
                    f"to an address before calling)"
                )
            looked_up = TOKEN_REGISTRY.get_by_address(token_value)
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
