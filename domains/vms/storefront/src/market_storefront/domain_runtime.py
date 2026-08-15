"""VM storefront construction and validation for its market-domain contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from arkhai_vms.domain_runtime import market_domain
from core_storefront.domain_plugins import StorefrontDomainContribution
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontSettlementBuildContext,
)
from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
)
from core_storefront.escrow_verification import verify_escrow_for_settlement
from domains.vms.negotiation.storefront_round import default_seller_round_hook
from market_core import (
    DomainCapability,
    DomainContractValidationError,
    DomainIdentity,
    ImmutableComputeProvisioningCapability,
    ImmutableFulfillmentCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)

from market_storefront.negotiation_runtime import build_vm_accepted_artifacts
from market_storefront.services.fulfillment_service import fulfill_compute_obligation

VM_STOREFRONT_DOMAIN_IDENTITY = DomainIdentity("compute.v1")
_REQUIRED_VM_STOREFRONT_CAPABILITIES = frozenset(
    {
        DomainCapability.PUBLICATION,
        DomainCapability.STOREFRONT,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
        DomainCapability.COMPUTE_PROVISIONING,
    }
)


def _build_vm_settlement_plan(
    *,
    context: StorefrontSettlementBuildContext,
):
    """Adapt the VM plan builder to the common selected-domain context."""

    return build_vm_accepted_artifacts(
        proposal=context.proposal,
        agreed_amount=context.agreed_amount,
        duration_seconds=context.duration_seconds,
        buyer_principal=context.buyer_principal,
        seller_principal=context.seller_principal,
    )


async def _fulfill_vm_context(
    *,
    context: StorefrontFulfillmentContext,
) -> dict[str, Any]:
    """Adapt the common frozen-binding carrier to VM fulfillment inputs."""

    raw = context.domain_input
    if not isinstance(raw, Mapping):
        raise TypeError("VM fulfillment requires a domain_input mapping")
    required = (
        "ssh_public_key",
        "order",
        "duration_seconds",
        "listing_id",
        "settlement_mechanism",
    )
    missing = tuple(key for key in required if raw.get(key) is None)
    if missing:
        raise ValueError("VM fulfillment input is missing " + ", ".join(missing))
    result = await fulfill_compute_obligation(
        sqlite_client=context.ports.repository,
        client=context.ports.fulfillment_client,
        escrow_uid=context.escrow_uid,
        ssh_public_key=str(raw["ssh_public_key"]),
        order=raw["order"],
        duration_seconds=int(raw["duration_seconds"]),
        start_utc=raw.get("start_utc"),
        listing_id=str(raw["listing_id"]),
        negotiation_id=context.negotiation_id,
        site_id=context.site_id,
        settlement_mechanism=str(raw["settlement_mechanism"]),
    )
    result = dict(result or {})
    order = raw["order"] if isinstance(raw["order"], Mapping) else {}
    offer_resource = order.get("offer_resource")
    if not isinstance(offer_resource, Mapping):
        offer_resource = {}
    physical_resource_id = result.get("physical_resource_id")
    if physical_resource_id is None:
        physical_resource_id = offer_resource.get("resource_id")
    return {
        "negotiation_id": context.negotiation_id,
        "escrow_uid": context.escrow_uid,
        "site_id": context.site_id,
        "state": str(result.get("status") or "failed"),
        "physical_resource_id": physical_resource_id,
        "capacity_reservation_id": result.get("capacity_reservation_id"),
        "settlement_resource_id": result.get("settlement_resource_id"),
        "fulfillment_id": result.get("fulfillment_uid")
        or result.get("fulfillment_id"),
        "failure_reason": result.get("message")
        if result.get("status") != "fulfilled"
        else None,
        "domain_result": result,
    }

def build_vm_storefront_domain() -> MarketDomainContract:
    """Construct the ordinary VM contract used by the storefront executable."""
    base = market_domain()
    role_capabilities = _REQUIRED_VM_STOREFRONT_CAPABILITIES - {
        DomainCapability.PUBLICATION
    }
    return validate_vm_storefront_domain(
        replace(
            base,
            declared_capabilities=base.declared_capabilities | role_capabilities,
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=default_seller_round_hook,
            ),
            settlement=ImmutableSettlementCapability(
                verify=verify_escrow_for_settlement,
                build_plan=_build_vm_settlement_plan,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=_fulfill_vm_context,
            ),
            compute_provisioning=ImmutableComputeProvisioningCapability(
                provision=_fulfill_vm_context,
            ),
        )
    )


VM_STOREFRONT_CONTRIBUTION = StorefrontDomainContribution(
    contribution_id="vms",
    build_contract=build_vm_storefront_domain,
)


def build_vm_storefront_registry(
    domain: MarketDomainContract | None = None,
) -> StorefrontDomainRegistry:
    """Build an explicit one-registration VM registry for focused composition."""

    contract = (
        build_vm_storefront_domain()
        if domain is None
        else validate_vm_storefront_domain(domain)
    )
    return StorefrontDomainRegistry(
        (
            StorefrontDomainRegistration(
                offering_mode="vm",
                contract=contract,
                contribution_id="vms",
            ),
        )
    )


def validate_vm_storefront_domain(domain: object) -> MarketDomainContract:
    """Validate the exact contract profile supported by the VM executable."""
    if not isinstance(domain, MarketDomainContract):
        raise DomainContractValidationError(
            "VM storefront requires a MarketDomainContract, "
            f"got {type(domain).__name__}"
        )
    validated = validate_domain_contract(domain)
    if validated.identity != VM_STOREFRONT_DOMAIN_IDENTITY:
        raise DomainContractValidationError(
            "VM storefront requires domain "
            f"{VM_STOREFRONT_DOMAIN_IDENTITY!s}, got {validated.identity!s}"
        )
    missing = (
        _REQUIRED_VM_STOREFRONT_CAPABILITIES - validated.declared_capabilities
    )
    if missing:
        names = ", ".join(sorted(capability.value for capability in missing))
        raise DomainContractValidationError(
            f"domain {validated.identity!s} is missing required VM storefront "
            f"capabilities: {names}"
        )
    return validated


def build_settlement_runtime(
    *,
    domain: MarketDomainContract,
    sqlite_client,
    alkahest_clients,
    marketplace_signer,
):
    """Compose VM policy and explicit settlement mechanisms."""
    from market_storefront.settlement_composition import (
        build_vm_settlement_composition,
    )

    return build_vm_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
    )
