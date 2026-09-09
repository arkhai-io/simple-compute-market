"""Concrete publication wiring for the bare-metal storefront."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from arkhai_bare_metal.projections import TrustedBareMetalProjection
from arkhai_bare_metal.storefront_publication import (
    commit_derived_bare_metal_listing,
    load_derived_bare_metal_listing_by_id,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
    run_storefront_publication_command,
)
from core_storefront.publication_composition import (
    build_storefront_publication_selection,
)
from core_storefront.domain_registry import StorefrontDomainRegistry
from core_storefront.publication_runner import (
    PublicationCommandResult,
    PublicationSourceSelection,
)
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
    DisabledPublicationPolicy,
    PublicationCandidate,
    PublicationRuntime,
    PublicationTransition,
)

ProjectionSnapshot = Callable[
    [],
    Iterable[TrustedBareMetalProjection] | None,
]
CloseListing = Callable[[str, str, str | None], dict[str, Any]]
PublishExistingListing = Callable[..., dict[str, Any]]


class BareMetalPublicationHooks:
    """Bare-metal validation and atomic local lifecycle commit adapter."""

    def __init__(self, repository: Any, available_keys: frozenset[str]) -> None:
        self._repository = repository
        self._available_keys = available_keys

    def validate_candidate(
        self,
        candidate: PublicationCandidate[dict[str, Any]],
    ) -> None:
        payload = candidate.payload
        source = payload.get("bare_metal_candidate")
        offer = payload.get("offer_resource")
        if not isinstance(source, dict) or not isinstance(offer, dict):
            raise CapacityBindingError("bare-metal publication candidate is incomplete")
        if (
            str(source.get("site_id") or "") != candidate.binding.site_id
            or str(source.get("physical_resource_id") or "")
            != candidate.binding.source_id
            or str(offer.get("virtualization_type") or "")
            != candidate.binding.offering_mode
        ):
            raise CapacityBindingError(
                "bare-metal publication candidate does not match its binding"
            )
        if str(source.get("derivation_key") or "") not in self._available_keys:
            raise CapacityBindingError(
                "bare-metal publication candidate is not currently available"
            )

    async def binding_for_listing(self, listing_id: str) -> CapacityBinding | None:
        durable = await self._repository.load_listing_binding(listing_id=listing_id)
        if durable is None or durable.physical_resource_id is None:
            return None
        return CapacityBinding(
            durable.site_id,
            durable.binding.offering_mode,
            durable.physical_resource_id,
        )

    async def validate_lifecycle(
        self,
        candidate: PublicationCandidate[dict[str, Any]],
        transition: PublicationTransition,
        *,
        previous_local_committed: bool,
    ) -> None:
        row = await asyncio.to_thread(
            load_derived_bare_metal_listing_by_id,
            self._repository.db_path,
            listing_id=candidate.listing_id,
        )
        if row is None:
            raise CapacityBindingError(
                "bare-metal lifecycle target is not durably tracked"
            )
        source = candidate.payload["bare_metal_candidate"]
        if row.get("derivation_key") != source.get("derivation_key"):
            raise CapacityBindingError(
                "bare-metal lifecycle target has a different derivation"
            )
        locally_open = (
            row.get("status") == "open" and row.get("listing_status") == "open"
        )
        if transition is PublicationTransition.REFRESH and not locally_open:
            raise CapacityBindingError(
                "bare-metal refresh target is not locally open"
            )
        if transition is PublicationTransition.REOPEN:
            if previous_local_committed and not locally_open:
                raise CapacityBindingError(
                    "bare-metal reopen recovery target is no longer locally open"
                )
            if not previous_local_committed and locally_open:
                raise CapacityBindingError(
                    "bare-metal reopen target is already locally open"
                )

    def disabled_publication_policy(
        self,
        transition: PublicationTransition,
    ) -> DisabledPublicationPolicy:
        del transition
        return DisabledPublicationPolicy.SKIP_LOCAL

    async def commit_candidate(
        self,
        candidate: PublicationCandidate[dict[str, Any]],
        transition: PublicationTransition,
    ) -> None:
        payload = candidate.payload
        await asyncio.to_thread(
            commit_derived_bare_metal_listing,
            self._repository.db_path,
            listing_id=candidate.listing_id,
            base_url=str(payload["storefront_url"]),
            candidate=payload["bare_metal_candidate"],
            offer=payload["offer_resource"],
            accepted_escrows=payload["accepted_escrows"],
            demands=payload["demands"],
            max_duration_seconds=payload.get("max_duration_seconds"),
            settlement_options=payload.get("settlement_options"),
            publication_clauses=payload.get("publication_clauses"),
            reopen=transition is PublicationTransition.REOPEN,
        )


def build_bare_metal_lifecycle_runtime(
    *,
    repository: Any,
    available_keys: frozenset[str],
    enabled: bool,
    registry_urls: tuple[str, ...],
    registry_client_factory: Callable[[], Any],
    listing_request_factory: Callable[..., Any],
    update_listing_request_factory: Callable[..., Any],
    storefront_url: str,
) -> PublicationRuntime[dict[str, Any]]:
    """Compose the shared lifecycle engine with bare-metal policy."""
    return PublicationRuntime(
        repository=repository,
        hooks=BareMetalPublicationHooks(repository, available_keys),
        enabled=enabled,
        registry_urls=registry_urls,
        registry_client_factory=registry_client_factory,
        listing_request_factory=listing_request_factory,
        update_listing_request_factory=update_listing_request_factory,
        storefront_url=storefront_url,
    )


def build_bare_metal_publication_selection(
    registry: StorefrontDomainRegistry,
    *,
    projection_snapshot: ProjectionSnapshot,
    close_listing: CloseListing,
    publish_existing_listing: PublishExistingListing,
    refresh_listing_ids: frozenset[str] = frozenset(),
) -> PublicationSourceSelection:
    """Select the exact registered bare-metal publication capability.

    ``refresh_listing_ids`` names the open listings an operator asked to
    republish under their existing identifiers. It is empty for the routine
    round, which leaves open listings untouched.
    """
    registration = registry.resolve_mode("bare_metal")
    selection = build_storefront_publication_selection(
        registry,
        source_kwargs_by_contribution={
            registration.contribution_id: {
                "projection_snapshot": projection_snapshot,
                "close_listing": close_listing,
                "publish_existing_listing": publish_existing_listing,
                "refresh_listing_ids": refresh_listing_ids,
            },
        },
    )
    (source,) = selection.sources
    if source.name != registration.contribution_id:
        raise ValueError(
            "bare-metal publication source must match its registered contribution"
        )

    def offer_resource(candidate: dict[str, Any]) -> dict[str, Any]:
        offer = source.offer_resource(candidate)
        offer["virtualization_type"] = registration.binding.offering_mode
        return offer

    return PublicationSourceSelection(
        sources=(replace(source, offer_resource=offer_resource),),
    )


def run_bare_metal_publication(
    selection: PublicationSourceSelection,
    *,
    config: StorefrontPublicationCommandConfig,
    callbacks: StorefrontPublicationCommandCallbacks,
    skip_ids: set[str] | None = None,
) -> PublicationCommandResult:
    """Run one schema-opaque core publication round."""
    return run_storefront_publication_command(
        selection,
        config=config,
        callbacks=callbacks,
        skip_ids=skip_ids,
    )
