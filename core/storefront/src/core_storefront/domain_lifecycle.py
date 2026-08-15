"""Mechanism-neutral invocation contracts for selected storefront domains.

The persisted :mod:`core_storefront.domain_registry` binding remains the routing
authority.  These runtime-only carriers pass already-resolved public identities
and caller-owned ports to the exact registered domain hook; they never contain
provider URLs, credentials, or a fallback selector.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from market_core import MarketDomainContract
from market_identity import Identity

from .domain_registry import StorefrontDomainBinding, StorefrontThreadBinding


class StorefrontDomainLifecycleError(RuntimeError):
    """A selected domain returned a malformed lifecycle artifact."""


@dataclass(frozen=True)
class StorefrontSettlementBuildContext:
    """Canonical accepted inputs supplied to one domain settlement builder."""

    binding: StorefrontDomainBinding
    negotiation_id: str
    listing_id: str
    site_id: str
    proposal: Any = field(repr=False)
    agreed_amount: int
    duration_seconds: int
    buyer_principal: Identity
    seller_principal: Identity
    seller_wallet_address: str | None = None
    chain_config_paths: Mapping[str, str | None] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )

    def __post_init__(self) -> None:
        if not self.negotiation_id or not self.listing_id or not self.site_id:
            raise ValueError("settlement context identities must be non-empty")
        if self.agreed_amount < 0 or self.duration_seconds <= 0:
            raise ValueError("settlement amount/duration are invalid")
        object.__setattr__(
            self,
            "chain_config_paths",
            MappingProxyType(dict(self.chain_config_paths)),
        )


@dataclass(frozen=True)
class StorefrontSettlementArtifacts:
    """Validated canonical plan plus domain-owned safe supplemental artifacts."""

    settlement_plan: Mapping[str, Any]
    supplemental: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        plan = dict(self.settlement_plan)
        obligations = plan.get("obligations")
        if not isinstance(obligations, list) or not obligations:
            raise StorefrontDomainLifecycleError(
                "selected domain returned no canonical settlement obligations"
            )
        if any(not isinstance(item, dict) for item in obligations):
            raise StorefrontDomainLifecycleError(
                "selected domain returned a malformed settlement obligation"
            )
        object.__setattr__(self, "settlement_plan", MappingProxyType(plan))
        object.__setattr__(self, "supplemental", MappingProxyType(dict(self.supplemental)))

    @classmethod
    def from_hook_result(cls, result: Any) -> "StorefrontSettlementArtifacts":
        if not isinstance(result, Mapping):
            raise StorefrontDomainLifecycleError(
                "selected domain settlement builder must return a mapping"
            )
        raw_plan = result.get("settlement_plan")
        if not isinstance(raw_plan, Mapping):
            raise StorefrontDomainLifecycleError(
                "selected domain settlement builder omitted settlement_plan"
            )
        return cls(
            settlement_plan=raw_plan,
            supplemental={key: value for key, value in result.items() if key != "settlement_plan"},
        )


@dataclass(frozen=True)
class StorefrontFulfillmentPorts:
    """Caller-owned authority ports; no routing or provider configuration."""

    repository: Any = field(repr=False)
    capacity_client: Any = field(repr=False)
    fulfillment_client: Any = field(repr=False)




@dataclass(frozen=True)
class StorefrontSettlementFulfillmentInput:
    """Domain-neutral transient input retained by one prepared settlement."""

    thread_binding: StorefrontThreadBinding
    buyer_principal: Identity
    domain_input: Mapping[str, Any] = field(repr=False)
    fulfillment_anchor: str | None = None
    evidence_client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "domain_input",
            MappingProxyType(dict(self.domain_input)),
        )

    @property
    def negotiation_id(self) -> str:
        return self.thread_binding.negotiation_id

    @property
    def site_id(self) -> str:
        return self.thread_binding.site_id


@dataclass(frozen=True)
class StorefrontFulfillmentContext:
    """Exact accepted binding and public operation identities for fulfillment."""

    thread_binding: StorefrontThreadBinding
    escrow_uid: str
    buyer_principal: Identity
    ports: StorefrontFulfillmentPorts = field(repr=False)
    domain_input: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.escrow_uid:
            raise ValueError("escrow_uid must be non-empty")

    @property
    def negotiation_id(self) -> str:
        return self.thread_binding.negotiation_id

    @property
    def site_id(self) -> str:
        return self.thread_binding.site_id


@dataclass(frozen=True)
class StorefrontFulfillmentLifecycle:
    """Safe durable lifecycle projection returned by a domain fulfillment hook."""

    negotiation_id: str
    escrow_uid: str
    site_id: str
    state: str
    physical_resource_id: str | None = None
    capacity_reservation_id: str | None = None
    settlement_resource_id: str | None = None
    fulfillment_id: str | None = None
    failure_reason: str | None = None
    domain_result: Any = field(default=None, repr=False)
    fulfillment_ref: str | None = None
    public_result: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_hook_result(cls, result: Any) -> "StorefrontFulfillmentLifecycle":
        if not isinstance(result, Mapping):
            raise StorefrontDomainLifecycleError(
                "selected domain fulfillment hook must return a mapping"
            )
        required = ("negotiation_id", "escrow_uid", "site_id", "state")
        missing = tuple(key for key in required if not result.get(key))
        if missing:
            raise StorefrontDomainLifecycleError(
                "selected domain fulfillment result is missing " + ", ".join(missing)
            )
        return cls(
            negotiation_id=str(result["negotiation_id"]),
            escrow_uid=str(result["escrow_uid"]),
            site_id=str(result["site_id"]),
            state=str(result["state"]),
            physical_resource_id=_optional_text(result.get("physical_resource_id")),
            capacity_reservation_id=_optional_text(result.get("capacity_reservation_id")),
            settlement_resource_id=_optional_text(result.get("settlement_resource_id")),
            fulfillment_id=_optional_text(result.get("fulfillment_id")),
            fulfillment_ref=_optional_text(result.get("fulfillment_ref")),
            public_result=MappingProxyType(dict(result.get("public_result") or {})),
            failure_reason=_optional_text(result.get("failure_reason")),
            domain_result=result.get("domain_result"),
        )


def build_domain_settlement_artifacts(
    domain: MarketDomainContract,
    context: StorefrontSettlementBuildContext,
) -> StorefrontSettlementArtifacts:
    """Invoke only the already-resolved domain settlement builder."""

    if context.binding.domain_identity != domain.identity:
        raise StorefrontDomainLifecycleError(
            "settlement context binding disagrees with selected domain"
        )
    settlement = domain.settlement
    if settlement is None:
        raise StorefrontDomainLifecycleError(
            f"domain {domain.identity!s} has no settlement capability"
        )
    return StorefrontSettlementArtifacts.from_hook_result(
        settlement.build_plan(context=context)
    )


async def fulfill_domain(
    domain: MarketDomainContract,
    context: StorefrontFulfillmentContext,
) -> StorefrontFulfillmentLifecycle:
    """Invoke the selected domain hook and validate exact binding continuity."""

    if context.thread_binding.binding.domain_identity != domain.identity:
        raise StorefrontDomainLifecycleError(
            "fulfillment context binding disagrees with selected domain"
        )
    fulfillment = domain.fulfillment
    if fulfillment is None:
        raise StorefrontDomainLifecycleError(
            f"domain {domain.identity!s} has no fulfillment capability"
        )
    result = StorefrontFulfillmentLifecycle.from_hook_result(
        await fulfillment.fulfill(context=context)
    )
    if (
        result.negotiation_id != context.negotiation_id
        or result.escrow_uid != context.escrow_uid
        or result.site_id != context.site_id
    ):
        raise StorefrontDomainLifecycleError(
            "selected domain fulfillment result changed its accepted binding"
        )
    return result


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None
