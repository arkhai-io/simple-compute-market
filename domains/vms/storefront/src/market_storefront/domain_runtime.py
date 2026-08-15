"""VM storefront construction and validation for its market-domain contract."""

from __future__ import annotations

from dataclasses import replace

from arkhai_vms.domain_runtime import market_domain
from core_storefront.domain_plugins import StorefrontDomainContribution
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

from market_storefront.services.fulfillment_service import fulfill_compute_obligation
from market_storefront.utils.sync_negotiation import _accepted_escrow_artifacts

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
                build_plan=_accepted_escrow_artifacts,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=fulfill_compute_obligation,
            ),
            compute_provisioning=ImmutableComputeProvisioningCapability(
                provision=fulfill_compute_obligation,
            ),
        )
    )

VM_STOREFRONT_CONTRIBUTION = StorefrontDomainContribution(
    contribution_id="vms",
    build_contract=build_vm_storefront_domain,
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
