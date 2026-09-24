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
    reopen_listing_in_registries,
)
from core_storefront.sqlite_client import SellerClosedListingError

from .capacity import CapacityBindingError, PublicationBinding

logger = logging.getLogger(__name__)

PayloadT = TypeVar("PayloadT")

_CLOSED_BY_VALUES = frozenset({"seller", "reconciliation"})


@dataclass(frozen=True, slots=True)
class PublicationCandidate(Generic[PayloadT]):
    """One domain-derived listing with its exact durable binding.

    The binding may be capacity-backed or unbacked; publication treats it as an
    identity token and never asks it an availability question.
    """

    listing_id: str
    binding: PublicationBinding
    payload: PayloadT

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, str) or not self.listing_id.strip():
            raise ValueError("publication listing_id must be non-empty")
        object.__setattr__(self, "listing_id", self.listing_id.strip())


@dataclass(frozen=True, slots=True)
class BoundListing:
    listing_id: str
    binding: PublicationBinding

    def __post_init__(self) -> None:
        if not isinstance(self.listing_id, str) or not self.listing_id.strip():
            raise ValueError("bound listing_id must be non-empty")
        object.__setattr__(self, "listing_id", self.listing_id.strip())


@dataclass(frozen=True, slots=True)
class ReconciliationPlan(Generic[PayloadT]):
    """Domain decisions executed by the kit-owned close/reopen lifecycle.

    Every close in a plan is a reconciliation close.
    """

    close: tuple[BoundListing, ...] = ()
    reopen: tuple[PublicationCandidate[PayloadT], ...] = ()


class PublicationRepository(Protocol):
    async def update_listing(
        self,
        *,
        listing_id: str,
        status: str,
        closed_by: str | None = None,
        reopened_by: str | None = None,
    ) -> Any: ...
    async def load_publications(self, *, listing_id: str) -> list[dict[str, Any]]: ...
    async def load_listing(self, *, listing_id: str) -> dict[str, Any] | None: ...
    async def list_publication_divergence(
        self, *, registry_urls: Sequence[str]
    ) -> list[dict[str, Any]]: ...
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

    async def binding_for_listing(
        self, listing_id: str
    ) -> PublicationBinding | None: ...


@dataclass(frozen=True, slots=True)
class RegistryDivergence:
    """A listing whose local status some configured registries do not hold."""

    listing_id: str
    listing_status: str
    registry_urls: tuple[str, ...]


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

    async def close(
        self, listing: BoundListing, *, closed_by: str
    ) -> dict[str, Any]:
        """Close locally, then at every registry that still records publication.

        ``closed_by`` names who closed the listing, ``seller`` or
        ``reconciliation``. Reconciliation reopens only what reconciliation
        closed, so there is no default: a close that did not say would either
        let a capacity event undo a seller's decision or stop reconciliation
        restoring a listing it withdrew.

        The local close is the durable decision, so a failure there propagates
        before any registry is told: a registry saying closed while the
        storefront still says open is a state neither side can reconcile from.
        A registry that misses the close is recorded as failed and repaired by
        :meth:`converge`, which every publication pass runs.
        """
        if closed_by not in _CLOSED_BY_VALUES:
            raise ValueError(
                f"closed_by must be one of {sorted(_CLOSED_BY_VALUES)}, "
                f"not {closed_by!r}"
            )
        await self._require_persisted_binding(listing.listing_id, listing.binding)
        await self._repository.update_listing(
            listing_id=listing.listing_id,
            status="closed",
            closed_by=closed_by,
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
        self, candidate: PublicationCandidate[PayloadT], *, reopened_by: str
    ) -> dict[str, Any]:
        """Reopen the exact persisted candidate, then republish it.

        ``reopened_by`` names who is reopening, ``seller`` or
        ``reconciliation``. The repository refuses a reconciliation reopen of a
        listing its seller closed with ``SellerClosedListingError``, before any
        registry is told.
        """
        if reopened_by not in _CLOSED_BY_VALUES:
            raise ValueError(
                f"reopened_by must be one of {sorted(_CLOSED_BY_VALUES)}, "
                f"not {reopened_by!r}"
            )
        await self._require_persisted_binding(candidate.listing_id, candidate.binding)
        self._hooks.validate_candidate(candidate)
        await self._repository.update_listing(
            listing_id=candidate.listing_id,
            status="open",
            reopened_by=reopened_by,
        )
        published = await self.publish(candidate)
        if published.get("status") != "published":
            return published
        # Publishing refreshes the payload a registry holds but not its status,
        # so a listing a registry recorded as closed is reopened explicitly. The
        # result is recorded so a registry that stays closed is seen as diverged.
        reopened = await reopen_listing_in_registries(
            candidate.listing_id,
            enabled=self._enabled,
            registry_client_factory=self._open_registry_client,
            update_listing_request_factory=self._update_listing_request_factory,
            select_target_registries=self._registries_to_target,
            record_publications=self._record_publications,
        )
        if reopened.get("status") == "error":
            return reopened
        return published

    async def reconcile(
        self, plan: ReconciliationPlan[PayloadT]
    ) -> dict[str, tuple[str, ...]]:
        """Execute a domain-produced plan with deterministic close-before-reopen order.

        Every close is a reconciliation close and every reopen a reconciliation
        reopen. A listing whose local close fails is reported under
        ``failed_closes`` and the rest of the plan continues; a candidate its
        seller closed is reported under ``seller_closed`` and left closed, so a
        plan built from a stale view cannot undo a seller's close.
        """
        closed: list[str] = []
        failed_closes: list[str] = []
        reopened: list[str] = []
        seller_closed: list[str] = []
        seen: set[str] = set()
        for listing in plan.close:
            if listing.listing_id in seen:
                raise ValueError(
                    f"duplicate listing {listing.listing_id!r} in reconciliation plan"
                )
            seen.add(listing.listing_id)
            try:
                result = await self.close(listing, closed_by="reconciliation")
            except CapacityBindingError:
                # A binding that disagrees with durable state is a defect in
                # the plan, not a close that failed; it stops the plan.
                raise
            except Exception as exc:
                logger.warning(
                    "[LOCAL DB] reconciliation could not close listing %s: %s",
                    listing.listing_id,
                    exc,
                )
                failed_closes.append(listing.listing_id)
                continue
            if str(result.get("status", "?")) in {"closed", "skipped", "queued"}:
                closed.append(listing.listing_id)
        for candidate in plan.reopen:
            if candidate.listing_id in seen:
                raise ValueError(
                    f"listing {candidate.listing_id!r} cannot close and reopen in one plan"
                )
            seen.add(candidate.listing_id)
            try:
                result = await self.reopen(candidate, reopened_by="reconciliation")
            except SellerClosedListingError:
                logger.info(
                    "[RECONCILE] listing %s was closed by its seller; not reopening it",
                    candidate.listing_id,
                )
                seller_closed.append(candidate.listing_id)
                continue
            if str(result.get("status", "?")) in {
                "published",
                "disabled",
                "skipped",
                "queued",
            }:
                reopened.append(candidate.listing_id)
        return {
            "closed": tuple(closed),
            "failed_closes": tuple(failed_closes),
            "reopened": tuple(reopened),
            "seller_closed": tuple(seller_closed),
        }

    async def _require_persisted_binding(
        self, listing_id: str, supplied: PublicationBinding
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

    async def publication_divergence(self) -> tuple[RegistryDivergence, ...]:
        """Listings some configured registry has not converged on.

        Read from the durable per-registry records: a registry that missed a
        publish, close, or reopen recorded it as failed, and disagrees with the
        listing's local status until repaired.
        """
        if not self._enabled:
            return ()
        rows = await self._repository.list_publication_divergence(
            registry_urls=self._registry_urls
        )
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            key = (str(row["listing_id"]), str(row["listing_status"]))
            grouped.setdefault(key, []).append(str(row["registry_url"]))
        return tuple(
            RegistryDivergence(listing_id, status, tuple(urls))
            for (listing_id, status), urls in grouped.items()
        )

    async def converge(
        self, divergences: Sequence[RegistryDivergence] | None = None
    ) -> dict[str, tuple[str, ...]]:
        """Bring each diverged registry to its listing's local status.

        The local listing is the durable decision, so the repair resends only
        what it implies, and only to the registries that diverged: a close for a
        closed listing; for an open one, the stored listing republished and then
        reopened. Results are recorded as every publication records them, so a
        registry still unreachable stays diverged for the next pass. Returns the
        listings ``repaired`` and those still ``unrepaired``.
        """
        if divergences is None:
            divergences = await self.publication_divergence()
        for divergence in divergences:
            try:
                await self._converge_one(divergence)
            except Exception as exc:
                logger.warning(
                    "[REGISTRY] could not converge listing %s at %s: %s",
                    divergence.listing_id,
                    ", ".join(divergence.registry_urls),
                    exc,
                )
        remaining = {
            divergence.listing_id for divergence in await self.publication_divergence()
        }
        return {
            "repaired": tuple(
                d.listing_id for d in divergences if d.listing_id not in remaining
            ),
            "unrepaired": tuple(
                d.listing_id for d in divergences if d.listing_id in remaining
            ),
        }

    async def _converge_one(self, divergence: RegistryDivergence) -> None:
        targets = frozenset(divergence.registry_urls)

        async def diverged(_listing_id: str, urls: list[str]) -> list[str]:
            return [url for url in urls if url in targets]

        if divergence.listing_status == "closed":
            await close_listing_in_registries(
                divergence.listing_id,
                enabled=self._enabled,
                registry_client_factory=self._open_registry_client,
                update_listing_request_factory=self._update_listing_request_factory,
                select_target_registries=diverged,
                record_publications=self._record_closures,
            )
            return
        listing = await self._repository.load_listing(listing_id=divergence.listing_id)
        if listing is None:
            return
        published = await publish_listing_to_registries(
            listing,
            enabled=self._enabled,
            registry_client_factory=self._open_registry_client,
            listing_request_factory=self._listing_request_factory,
            storefront_url=self._storefront_url,
            record_publications=self._record_publications,
            registry_urls=divergence.registry_urls,
        )
        if published.get("status") != "published":
            return
        await reopen_listing_in_registries(
            divergence.listing_id,
            enabled=self._enabled,
            registry_client_factory=self._open_registry_client,
            update_listing_request_factory=self._update_listing_request_factory,
            select_target_registries=diverged,
            record_publications=self._record_publications,
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
