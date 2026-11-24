"""VM storefront construction and validation for its market-domain contract."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from arkhai_vms.domain_runtime import market_domain
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontSettlementBuildContext,
)
from core_storefront.domain_plugins import StorefrontDomainContribution
from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
)
from arkhai_vms_negotiation.storefront_round import default_seller_round_hook
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

from compute_delivery import OutcomeKind

from market_storefront.delivery_ports import drive_vm_delivery, vm_delivery_path
from market_storefront.negotiation_runtime import build_vm_accepted_artifacts
from market_storefront.settlement_stages import vm_seller_stages
from market_storefront.utils.config import settings

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
    listing: Mapping[str, Any],
):
    """Adapt the VM plan builder to the common selected-domain context.

    ``listing`` is the listing the deal was negotiated against, whose release
    conditions authorize the escrow's; the seller stage binds it.
    """

    return build_vm_accepted_artifacts(
        proposal=context.proposal,
        listing=listing,
        agreed_amount=context.agreed_amount,
        duration_seconds=context.duration_seconds,
        buyer_principal=context.buyer_principal,
        seller_principal=context.seller_principal,
        uses_scalar_amount=context.uses_scalar_amount,
        chain_config_paths=context.chain_config_paths,
    )


def build_vm_seller_stages():
    """Bind the VM seller declaration without reconstructing a domain contract."""
    return vm_seller_stages(_build_vm_settlement_plan)


async def _fulfill_vm_context(
    *,
    context: StorefrontFulfillmentContext,
) -> dict[str, Any]:
    """Drive the VM deal through the compute delivery path, once.

    ``ports`` may carry the capacity effects and fulfillment client the path
    uses; each is built from the storefront's runtime when absent.
    ``domain_input`` may carry the seller's ``failure_policy``. The path's
    outcome maps to the hook's state: available or converged is fulfilled,
    ended is failed once the end is durable, and anything else, including a
    drive stopped by an exception, is deferred for the resume pass.
    """

    raw = context.domain_input if context.domain_input is not None else {}
    if not isinstance(raw, Mapping):
        raise TypeError("VM fulfillment requires a domain_input mapping")
    db = context.ports.repository
    nid = context.negotiation_id
    path = vm_delivery_path(
        db, capacity=context.ports.capacity_client, fulfillment=context.ports.fulfillment_client,
    )
    failure_policy = raw.get("failure_policy")
    outcome = await drive_vm_delivery(path, db, nid, failure_policy=failure_policy)
    # The settle task carries a dispatched VM until provisioning settles, as
    # far as the provisioning timeout, polling at its interval; past that, or
    # for any other outcome, the resume pass carries it on.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(settings.provisioning.timeout)
    while (
        outcome is not None
        and outcome.kind is OutcomeKind.PENDING
        and outcome.fulfillment_id is not None
        and loop.time() < deadline
    ):
        await asyncio.sleep(float(settings.provisioning.poll_interval))
        outcome = await drive_vm_delivery(path, db, nid, failure_policy=failure_policy)
    row = await db.load_vm_delivery(negotiation_id=nid) or {}
    state = outcome.hook_disposition if outcome is not None else "deferred"
    order = context.settlement_evidence.evidence["delivery"]["payload"]["order"]
    listing_resource = order.get("listing_resource")
    if not isinstance(listing_resource, Mapping):
        listing_resource = {}
    detail = (
        outcome.detail or outcome.kind.value
        if outcome is not None
        else "delivery stopped before it could report; the next drive resumes it"
    )
    return {
        "negotiation_id": nid,
        "settlement_ref": context.settlement_ref,
        "site_id": context.site_id,
        "state": state,
        "physical_resource_id": listing_resource.get("resource_id"),
        "capacity_reservation_id": row.get("capacity_reservation_id"),
        "fulfillment_id": row.get("fulfillment_id"),
        "failure_reason": None if state == "fulfilled" else detail,
        "domain_result": {
            "outcome": outcome.kind.value if outcome is not None else None,
            "reason": outcome.reason.value if outcome is not None and outcome.reason else None,
            "message": detail,
            "fulfillment_uid": row.get("fulfillment_uid"),
            "connection_details": row.get("connection_details"),
        },
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
                seller_stages=build_vm_seller_stages(),
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
    missing = _REQUIRED_VM_STOREFRONT_CAPABILITIES - validated.declared_capabilities
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
    chain_probe=None,
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
        chain_probe=chain_probe,
    )
