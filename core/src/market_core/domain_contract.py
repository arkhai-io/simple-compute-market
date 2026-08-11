"""Versioned, domain-neutral market plugin contract.

The carrier package owns only immutable protocol shapes and startup validation.
Concrete domains own every payload model and hook implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeVar, cast, runtime_checkable


class DomainIdentity(str):
    """Stable identifier for a market domain, independent of plugin API version."""

    def __new__(cls, value: str) -> "DomainIdentity":
        normalized = value.strip()
        if not normalized or normalized != value:
            raise ValueError("domain identity must be a non-empty, trimmed string")
        return cast("DomainIdentity", super().__new__(cls, normalized))


@dataclass(frozen=True, order=True)
class ContractVersion:
    """Version of the core-owned plugin API, not a domain payload schema."""

    major: int
    minor: int = 0

    def __post_init__(self) -> None:
        if self.major < 1 or self.minor < 0:
            raise ValueError("contract version components must be non-negative and major >= 1")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


MARKET_DOMAIN_CONTRACT_VERSION = ContractVersion(1, 0)
SUPPORTED_MARKET_DOMAIN_CONTRACT_VERSIONS = frozenset({MARKET_DOMAIN_CONTRACT_VERSION})

DomainCallable = Callable[..., Any]


@runtime_checkable
class CodecCapability(Protocol):
    """Deterministic codecs for the six universal market-domain artifacts."""

    def listing(self, value: Any) -> Any: ...
    def message(self, value: Any) -> Any: ...
    def terms(self, value: Any) -> Any: ...
    def materialization(self, value: Any) -> Any: ...
    def receipt(self, value: Any) -> Any: ...
    def result(self, value: Any) -> Any: ...


@dataclass(frozen=True)
class ImmutableCodecCapability:
    """Immutable callable-backed implementation of :class:`CodecCapability`."""

    normalize_listing: DomainCallable
    normalize_message: DomainCallable
    normalize_terms: DomainCallable
    normalize_materialization: DomainCallable
    normalize_receipt: DomainCallable
    normalize_result: DomainCallable

    def listing(self, value: Any) -> Any:
        return self.normalize_listing(value)

    def message(self, value: Any) -> Any:
        return self.normalize_message(value)

    def terms(self, value: Any) -> Any:
        return self.normalize_terms(value)

    def materialization(self, value: Any) -> Any:
        return self.normalize_materialization(value)

    def receipt(self, value: Any) -> Any:
        return self.normalize_receipt(value)

    def result(self, value: Any) -> Any:
        return self.normalize_result(value)


@runtime_checkable
class BuyerCapability(Protocol):
    """Buyer command and schema-specific orchestration hooks."""

    register_commands: DomainCallable
    build_provision_terms: DomainCallable
    select_policy: DomainCallable
    decode_result: DomainCallable


@dataclass(frozen=True)
class ImmutableBuyerCapability:
    register_commands: DomainCallable
    build_provision_terms: DomainCallable
    select_policy: DomainCallable
    decode_result: DomainCallable


@runtime_checkable
class StorefrontCapability(Protocol):
    """Domain storefront policy hook used after envelope validation."""

    run_negotiation_policy: DomainCallable


@dataclass(frozen=True)
class ImmutableStorefrontCapability:
    run_negotiation_policy: DomainCallable


@runtime_checkable
class PublicationCapability(Protocol):
    """Domain publication source and/or direct publication hook."""

    source_factory: DomainCallable | None
    publish: DomainCallable | None


@dataclass(frozen=True)
class ImmutablePublicationCapability:
    source_factory: DomainCallable | None = None
    publish: DomainCallable | None = None


@runtime_checkable
class SettlementCapability(Protocol):
    """Domain settlement verification and plan construction hooks."""

    verify: DomainCallable
    build_plan: DomainCallable


@dataclass(frozen=True)
class ImmutableSettlementCapability:
    verify: DomainCallable
    build_plan: DomainCallable


@runtime_checkable
class FulfillmentCapability(Protocol):
    """Domain fulfillment hook."""

    fulfill: DomainCallable


@dataclass(frozen=True)
class ImmutableFulfillmentCapability:
    fulfill: DomainCallable


@runtime_checkable
class ComputeProvisioningCapability(Protocol):
    """Optional compute-domain provisioning hook.

    This is deliberately not a lease/release lifecycle interface; lifecycle
    authority belongs to the separately composed compute service.
    """

    provision: DomainCallable


@dataclass(frozen=True)
class ImmutableComputeProvisioningCapability:
    provision: DomainCallable


class DomainCapability(str, Enum):
    BUYER = "buyer"
    STOREFRONT = "storefront"
    PUBLICATION = "publication"
    SETTLEMENT = "settlement"
    FULFILLMENT = "fulfillment"
    COMPUTE_PROVISIONING = "compute_provisioning"


_CAPABILITY_ATTRIBUTES: dict[DomainCapability, str] = {
    DomainCapability.BUYER: "buyer",
    DomainCapability.STOREFRONT: "storefront",
    DomainCapability.PUBLICATION: "publication",
    DomainCapability.SETTLEMENT: "settlement",
    DomainCapability.FULFILLMENT: "fulfillment",
    DomainCapability.COMPUTE_PROVISIONING: "compute_provisioning",
}

_CAPABILITY_HOOKS: dict[DomainCapability, tuple[str, ...]] = {
    DomainCapability.BUYER: (
        "register_commands",
        "build_provision_terms",
        "select_policy",
        "decode_result",
    ),
    DomainCapability.STOREFRONT: ("run_negotiation_policy",),
    DomainCapability.PUBLICATION: (),
    DomainCapability.SETTLEMENT: ("verify", "build_plan"),
    DomainCapability.FULFILLMENT: ("fulfill",),
    DomainCapability.COMPUTE_PROVISIONING: ("provision",),
}


@dataclass(frozen=True)
class MarketDomainContract:
    """Immutable root contract supplied by one concrete market domain."""

    identity: DomainIdentity
    contract_version: ContractVersion
    codecs: CodecCapability
    declared_capabilities: frozenset[DomainCapability] = frozenset()
    buyer: BuyerCapability | None = None
    storefront: StorefrontCapability | None = None
    publication: PublicationCapability | None = None
    settlement: SettlementCapability | None = None
    fulfillment: FulfillmentCapability | None = None
    compute_provisioning: ComputeProvisioningCapability | None = None

    def has_capability(self, capability: DomainCapability) -> bool:
        return capability in self.declared_capabilities

    def capability(self, capability: DomainCapability) -> object | None:
        return cast(object | None, getattr(self, _CAPABILITY_ATTRIBUTES[capability]))


class DomainContractValidationError(ValueError):
    """Raised before role startup when an installed domain is incompatible."""


C = TypeVar("C", bound=MarketDomainContract)


def validate_domain_contract(
    contract: C,
    *,
    supported_versions: frozenset[ContractVersion] = SUPPORTED_MARKET_DOMAIN_CONTRACT_VERSIONS,
) -> C:
    """Validate one contract and return it for composition chaining."""

    if not isinstance(contract.identity, DomainIdentity):
        raise DomainContractValidationError(
            f"domain identity must be DomainIdentity, got {type(contract.identity).__name__}"
        )
    if contract.contract_version not in supported_versions:
        supported = ", ".join(str(version) for version in sorted(supported_versions)) or "(none)"
        raise DomainContractValidationError(
            f"domain {contract.identity!s} uses unsupported market contract version "
            f"{contract.contract_version}; supported versions: {supported}"
        )
    if not isinstance(contract.codecs, CodecCapability):
        raise DomainContractValidationError(
            f"domain {contract.identity!s} has an incomplete codec capability"
        )

    for capability, attribute in _CAPABILITY_ATTRIBUTES.items():
        implementation = getattr(contract, attribute)
        declared = capability in contract.declared_capabilities
        if declared and implementation is None:
            raise DomainContractValidationError(
                f"domain {contract.identity!s} declares {capability.value!r} "
                "but provides no implementation"
            )
        if implementation is not None and not declared:
            raise DomainContractValidationError(
                f"domain {contract.identity!s} provides undeclared capability "
                f"{capability.value!r}"
            )
        if implementation is None:
            continue
        missing = [
            hook for hook in _CAPABILITY_HOOKS[capability]
            if not callable(getattr(implementation, hook, None))
        ]
        if capability is DomainCapability.PUBLICATION and not any(
            callable(getattr(implementation, hook, None))
            for hook in ("source_factory", "publish")
        ):
            missing.append("source_factory or publish")
        if missing:
            raise DomainContractValidationError(
                f"domain {contract.identity!s} capability {capability.value!r} "
                f"is incomplete; missing callable hooks: {', '.join(missing)}"
            )
    return contract


def validate_domain_contracts(
    contracts: Iterable[C],
    *,
    supported_versions: frozenset[ContractVersion] = SUPPORTED_MARKET_DOMAIN_CONTRACT_VERSIONS,
) -> tuple[C, ...]:
    """Validate installed contracts and reject duplicate stable identities."""

    validated: list[C] = []
    seen: set[DomainIdentity] = set()
    for contract in contracts:
        validate_domain_contract(contract, supported_versions=supported_versions)
        if contract.identity in seen:
            raise DomainContractValidationError(
                f"duplicate market domain identity: {contract.identity!s}"
            )
        seen.add(contract.identity)
        validated.append(contract)
    return tuple(validated)
