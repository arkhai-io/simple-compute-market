"""How one bare-metal publication cycle is composed from a running storefront.

The publication loop's timer and its step, which the publication command runs
through the administrator API, compose their cycle here, so neither can run a
different cycle. The held site projections
and every configured registry come from the storefront runtime; terms of sale
come from its configuration, replaced for one site's pool by the storefront's
stored override. A cycle that cannot be composed raises
``BareMetalPublicationError`` naming what is missing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core_storefront.publication_runner import PublicationPayload
from market_resource_pools_contracts.backing import capacity_backing

from .pool_overrides import compile_publication_clauses
from .publication import BareMetalPublicationCycle, BareMetalPublicationError
from .publication_service import BareMetalRegistryConfiguration
from .runtime import BareMetalStorefrontRuntime
from .storefront_registry import build_bare_metal_storefront_registry

logger = logging.getLogger(__name__)


def publication_payload_builder(
    runtime: BareMetalStorefrontRuntime,
) -> Callable[[dict[str, Any]], Any]:
    """Build each candidate's payload from the configured publication terms.

    A candidate reaches the builder only with a positive lease bound: the cycle
    holds a pool whose override and configuration state none.
    """
    composition = runtime.settlement_composition
    if composition is None:
        raise BareMetalPublicationError(
            "shared settlement configuration is required for publication"
        )
    clauses = runtime.publication_clauses
    default_max_duration = runtime.default_max_duration_seconds

    def fulfils_through_capacity(mechanism: str) -> bool:
        return composition.seller_stages[mechanism].fulfils_through_capacity

    async def build(candidate: dict[str, Any]) -> PublicationPayload:
        # A pool's storefront override replaces the configured clauses and
        # bound for that pool's listings only.
        override_clauses = candidate.get("override_clauses")
        configured = (
            compile_publication_clauses(override_clauses)
            if override_clauses is not None
            else clauses
        )
        # The candidate's backing decides which clauses it may publish: a
        # mechanism that delivers through capacity reaches a reservation only
        # an admission authority can make.
        backing = capacity_backing(candidate["listing_resource"]["capacity_backing"])
        admissible, dropped = backing.admissible_settlement(
            configured,
            mechanism=lambda clause: clause.mechanism,
            fulfils_through_capacity=fulfils_through_capacity,
        )
        if dropped:
            logger.warning(
                "bare-metal pool %s: dropped settlement mechanisms %s, which bare "
                "metal fulfils through capacity",
                candidate.get("pool_id"),
                list(dropped),
            )
            if not admissible:
                raise ValueError(
                    f"pool {candidate.get('pool_id')!r} has no settlement option its "
                    f"{backing.label} listings may publish"
                )
        return await composition.publication_payload(
            candidate=candidate,
            clauses=admissible,
            max_duration_seconds=candidate.get(
                "override_max_duration_seconds", default_max_duration
            ),
        )

    return build


def build_publication_cycle(
    runtime: BareMetalStorefrontRuntime,
    *,
    registry_configuration: BareMetalRegistryConfiguration,
    cycle_factory: Callable[..., BareMetalPublicationCycle] = BareMetalPublicationCycle,
) -> BareMetalPublicationCycle:
    """Compose one cycle over the runtime's held projection of every configured site."""
    if runtime.site_projections is None:
        raise BareMetalPublicationError("site projection state is unavailable")
    return cycle_factory(
        sqlite_client=runtime.db,
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        site_projections=runtime.site_projections,
        site_ids=[binding.site_id for binding in runtime.site_bindings],
        registry_client_factory=registry_configuration.client_factory(
            runtime.marketplace_signer
        ),
        registry_urls=registry_configuration.urls,
        storefront_url=runtime.storefront_url,
        seller_principal=runtime.seller_principal,
        build_payload=publication_payload_builder(runtime),
        default_max_duration_seconds=runtime.default_max_duration_seconds,
        enter_stage=runtime.loops.enter_stage,
        derivation=runtime.publication_derivation,
    )


def compose_publication_cycle(
    runtime: BareMetalStorefrontRuntime,
    *,
    cycle_factory: Callable[..., BareMetalPublicationCycle] = BareMetalPublicationCycle,
) -> BareMetalPublicationCycle:
    """Compose one cycle from the runtime and every registry it configures."""
    if runtime.registry_configuration is None:
        raise BareMetalPublicationError("no registry is configured for publication")
    return build_publication_cycle(
        runtime,
        registry_configuration=runtime.registry_configuration,
        cycle_factory=cycle_factory,
    )


__all__ = [
    "build_publication_cycle",
    "compose_publication_cycle",
    "publication_payload_builder",
]
