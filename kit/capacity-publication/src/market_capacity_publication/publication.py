"""Schema-opaque listing publication and capacity reconciliation mechanics."""

from __future__ import annotations
from contextlib import asynccontextmanager

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from core_storefront.registry_publication import (
    close_listing_in_registries,
    publish_listing_to_registries,
)

from .capacity import CapacityBinding, CapacityBindingError

logger = logging.getLogger(__name__)

PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True, slots=True)
class PublicationCandidate(Generic[PayloadT]):
    """One domain-derived listing with its exact capacity authority."""

    listing_id: str
    binding: CapacityBinding
    payload: PayloadT

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, str) or not self.listing_id.strip():
            raise ValueError("publication listing_id must be non-empty")
        object.__setattr__(self, "listing_id", self.listing_id.strip())


@dataclass(frozen=True, slots=True)
class BoundListing:
    listing_id: str
    binding: CapacityBinding

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, str) or not self.listing_id.strip():
            raise ValueError("bound listing_id must be non-empty")
        object.__setattr__(self, "listing_id", self.listing_id.strip())


@dataclass(frozen=True, slots=True)
class ReconciliationPlan(Generic[PayloadT]):
    """Domain decisions executed by the kit-owned close/reopen lifecycle."""

    close: tuple[BoundListing, ...] = ()
    reopen: tuple[PublicationCandidate[PayloadT], ...] = ()


class PublicationRepository(Protocol):
    async def update_listing(self, *, listing_id: str, status: str) -> Any: ...
    async def load_publications(self, *, listing_id: str) -> list[dict[str, Any]]: ...
    async def upsert_publication(
        self,
        *,
        listing_id: str,
        registry_url: str,
        payload: Any,
        status: str,
        registry_assigned_id: str | None,
        last_error: str | None,
    ) -> Any: ...


class PublicationDomainHooks(Protocol[PayloadT]):
    """Schema and persistence hooks retained by a composing domain."""

    def validate_candidate(self, candidate: PublicationCandidate[PayloadT]) -> None: ...

    async def binding_for_listing(self, listing_id: str) -> CapacityBinding | None: ...


RegistryClientFactory = Callable[[], Any]
RequestFactory = Callable[..., Any]
PublishedEvent = Callable[..., Any]


class PublicationRuntime(Generic[PayloadT]):
    """Registry fan-out, durable result recording, and close/reopen execution."""

    def __init__(
        self,
        *,
        repository: PublicationRepository,
        hooks: PublicationDomainHooks[PayloadT],
        enabled: bool,
        registry_urls: Sequence[str],
        registry_client_factory: RegistryClientFactory,
        listing_request_factory: RequestFactory,
        update_listing_request_factory: RequestFactory,
        storefront_url: str,
        on_published: PublishedEvent | None = None,
    ) -> None:
        self._repository = repository
        self._hooks = hooks
        self._enabled = bool(enabled)
        self._registry_urls = tuple(registry_urls)
        self._registry_client_factory = registry_client_factory
        self._listing_request_factory = listing_request_factory
        self._update_listing_request_factory = update_listing_request_factory
        self._storefront_url = storefront_url
        self._on_published = on_published
        if self._enabled and not self._registry_urls:
            raise ValueError("enabled publication requires at least one registry URL")
        if not isinstance(storefront_url, str) or not storefront_url.strip():
            raise ValueError("publication storefront_url must be non-empty")

    async def publish(
        self, candidate: PublicationCandidate[PayloadT]
    ) -> dict[str, Any]:
        """Publish only a candidate whose durable binding matches exactly."""
        await self._require_persisted_binding(candidate.listing_id, candidate.binding)
        self._hooks.validate_candidate(candidate)
        return await publish_listing_to_registries(
            candidate.payload,
            enabled=self._enabled,
            registry_client_factory=self._open_registry_client,
            listing_request_factory=self._listing_request_factory,
            storefront_url=self._storefront_url,
            record_publications=self._record_publications,
            on_published=self._on_published,
        )

    async def close(self, listing: BoundListing) -> dict[str, Any]:
        """Close locally and at every registry that still records publication."""
        await self._require_persisted_binding(listing.listing_id, listing.binding)
        try:
            await self._repository.update_listing(
                listing_id=listing.listing_id,
                status="closed",
            )
        except Exception as exc:
            logger.warning(
                "[LOCAL DB] Failed to close listing %s: %s",
                listing.listing_id,
                exc,
            )
        return await close_listing_in_registries(
            listing.listing_id,
            enabled=self._enabled,
            registry_client_factory=self._open_registry_client,
            update_listing_request_factory=self._update_listing_request_factory,
            select_target_registries=self._registries_to_target,
            record_publications=self._record_closures,
        )

    async def reopen(
        self, candidate: PublicationCandidate[PayloadT]
    ) -> dict[str, Any]:
        """Reopen the exact persisted candidate, then republish it."""
        await self._require_persisted_binding(candidate.listing_id, candidate.binding)
        self._hooks.validate_candidate(candidate)
        await self._repository.update_listing(
            listing_id=candidate.listing_id,
            status="open",
        )
        return await self.publish(candidate)

    async def reconcile(
        self, plan: ReconciliationPlan[PayloadT]
    ) -> dict[str, tuple[str, ...]]:
        """Execute a domain-produced plan with deterministic close-before-reopen order."""
        closed: list[str] = []
        reopened: list[str] = []
        seen: set[str] = set()
        for listing in plan.close:
            if listing.listing_id in seen:
                raise ValueError(
                    f"duplicate listing {listing.listing_id!r} in reconciliation plan"
                )
            seen.add(listing.listing_id)
            result = await self.close(listing)
            if str(result.get("status", "?")) in {"closed", "skipped", "queued"}:
                closed.append(listing.listing_id)
        for candidate in plan.reopen:
            if candidate.listing_id in seen:
                raise ValueError(
                    f"listing {candidate.listing_id!r} cannot close and reopen in one plan"
                )
            seen.add(candidate.listing_id)
            result = await self.reopen(candidate)
            if str(result.get("status", "?")) in {
                "published",
                "disabled",
                "skipped",
                "queued",
            }:
                reopened.append(candidate.listing_id)
        return {"closed": tuple(closed), "reopened": tuple(reopened)}

    async def _require_persisted_binding(
        self, listing_id: str, supplied: CapacityBinding
    ) -> None:
        persisted = await self._hooks.binding_for_listing(listing_id)
        if persisted is None:
            raise CapacityBindingError(
                f"listing {listing_id!r} has no durable capacity binding"
            )
        if persisted != supplied:
            raise CapacityBindingError(
                f"listing {listing_id!r} capacity binding does not match durable state"
            )

    @asynccontextmanager
    async def _open_registry_client(self):
        async with self._registry_client_factory() as client:
            active_urls = tuple(client.urls)
            if active_urls != self._registry_urls:
                raise ValueError(
                    "registry publication client URLs do not match the exact "
                    "configured fanout"
                )
            yield client

    async def _registries_to_target(
        self, listing_id: str, fallback_urls: list[str]
    ) -> list[str]:
        try:
            publications = await self._repository.load_publications(
                listing_id=listing_id
            )
        except Exception:
            return list(fallback_urls)
        active = [
            row["registry_url"]
            for row in publications
            if row.get("status") != "unpublished"
        ]
        return active if active else list(fallback_urls)

    async def _record_closures(
        self, listing_id: str, results: list[dict[str, Any]]
    ) -> None:
        await self._record_results(
            listing_id,
            results,
            success_status="unpublished",
        )

    async def _record_publications(
        self, listing_id: str, results: list[dict[str, Any]]
    ) -> None:
        await self._record_results(
            listing_id,
            results,
            success_status="published",
        )

    async def _record_results(
        self,
        listing_id: str,
        results: list[dict[str, Any]],
        *,
        success_status: str,
    ) -> None:
        for result in results:
            try:
                await self._repository.upsert_publication(
                    listing_id=listing_id,
                    registry_url=result["registry_url"],
                    payload=result.get("payload") or {},
                    status=success_status if result.get("success") else "failed",
                    registry_assigned_id=result.get("registry_assigned_id"),
                    last_error=result.get("error"),
                )
            except Exception as exc:
                logger.warning(
                    "[PUBLICATIONS] Failed to record registry result for %s @ %s: %s",
                    listing_id,
                    result.get("registry_url"),
                    exc,
                )
