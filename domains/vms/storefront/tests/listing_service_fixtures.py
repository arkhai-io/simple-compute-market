from __future__ import annotations

from dataclasses import dataclass

from core_storefront.aggregation import fill_first
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainRegistry,
)
from market_capacity_publication import CapacityRuntime, CapacitySite
from market_core import MarketDomainContract
from market_identity import Signer, TrustedIdentitySet


async def _noop_reconcile(_context: object) -> None:
    return None


class _EmptyCapacitySiteClient:
    async def snapshot(self) -> list[dict]:
        return []


def build_test_capacity_runtime(
    *,
    signer: Signer,
    authorities: TrustedIdentitySet,
) -> CapacityRuntime:
    """Build the smallest real capacity composition accepted by VM services."""

    return CapacityRuntime(
        sites=(
            CapacitySite(
                "site-test",
                "http://capacity.test",
                authorities,
            ),
        ),
        signer=signer,
        placement=fill_first,
        reconcile=_noop_reconcile,
        site_client_factory=lambda _site, _signer: _EmptyCapacitySiteClient(),
    )


@dataclass(frozen=True)
class VmListingCollaborators:
    """Exact registry-owned VM collaborators for a ListingService fixture."""

    registry: StorefrontDomainRegistry
    binding: StorefrontDomainBinding
    domain: MarketDomainContract
    capacity_runtime: CapacityRuntime


def vm_listing_collaborators(
    registry: StorefrontDomainRegistry,
    *,
    signer: Signer,
    authorities: TrustedIdentitySet,
) -> VmListingCollaborators:
    registration = registry.resolve_mode("vm")
    return VmListingCollaborators(
        registry=registry,
        binding=registration.binding,
        domain=registration.contract,
        capacity_runtime=build_test_capacity_runtime(
            signer=signer,
            authorities=authorities,
        ),
    )
