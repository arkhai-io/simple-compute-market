"""Schema-opaque listing publication and capacity reconciliation mechanics."""

from __future__ import annotations
from contextlib import asynccontextmanager

import json
import inspect
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from core_storefront.multi_registry_client import RegistryTargetIdentity
from core_storefront.registry_publication import (
    close_listing_in_registries,
    ensure_json_obj,
    publish_listing_with_client,
    publish_listing_to_registries,
)
from market_identity import Identity
from registry_client import RegistryClientError

from .capacity import CapacityBinding, CapacityBindingError

logger = logging.getLogger(__name__)

PayloadT = TypeVar("PayloadT")


class PublicationTransition(str, Enum):
    """Lifecycle transition applied to an existing publication candidate."""

    REFRESH = "refresh"
    REOPEN = "reopen"


class DisabledPublicationPolicy(str, Enum):
    """Domain-owned local behavior when registry publication is disabled."""

    SKIP_LOCAL = "skip_local"
    COMMIT_LOCAL = "commit_local"


class PublicationTargetState(str, Enum):
    """One target's confirmed or safely recoverable lifecycle outcome."""

    CONFIRMED = "confirmed"
    PREFLIGHT_UNKNOWN = "preflight_unknown"
    WRITE_UNCONFIRMED = "write_unconfirmed"
    WRITE_FAILED = "write_failed"
    WRITE_UNKNOWN = "write_unknown"
    CONFIRMATION_MISMATCH = "confirmation_mismatch"


@dataclass(frozen=True, slots=True)
class PublicationTargetResult:
    registry_url: str
    state: PublicationTargetState
    wrote: bool
    error_type: str | None = None
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    """Immutable identity of one explicit lifecycle operation."""

    listing_id: str
    binding: CapacityBinding
    transition: PublicationTransition
    canonical_request: str
    publisher_identity: Identity
    targets: tuple[RegistryTargetIdentity, ...]
    expected_statuses: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PublicationLifecycleResult:
    """Stable result of one refresh, reopen, or explicit recovery operation."""

    status: str
    listing_id: str
    transition: PublicationTransition
    local_committed: bool
    partial: bool = False
    target_results: tuple[PublicationTargetResult, ...] = ()
    failure_stage: str | None = None
    error_type: str | None = None
    intent: PublicationIntent | None = None
    receipts_persisted: bool = False
    event_emitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the credential-free command projection of this result."""
        outcomes = ", ".join(
            f"{target.registry_url}={target.state.value}"
            for target in self.target_results
        )
        result: dict[str, Any] = {
            "status": self.status,
            "listing_id": self.listing_id,
            "transition": self.transition.value,
            "local_committed": self.local_committed,
            "partial": self.partial,
            "registry_results": [
                {
                    "registry_url": target.registry_url,
                    "state": target.state.value,
                    "wrote": target.wrote,
                    "error_type": target.error_type,
                    "status_code": target.status_code,
                }
                for target in self.target_results
            ],
        }
        if self.failure_stage is not None:
            result["failure_stage"] = self.failure_stage
            result["message"] = (
                f"registry publication {self.failure_stage} failed"
                + (f": {outcomes}" if outcomes else "")
            )
        if self.error_type is not None:
            result["error_type"] = self.error_type
        if self.partial and self.failure_stage is None:
            result["message"] = (
                "registry publication is only partially confirmed"
                + (f": {outcomes}" if outcomes else "")
            )
        return result


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

    async def validate_lifecycle(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
        *,
        previous_local_committed: bool,
    ) -> None: ...

    def disabled_publication_policy(
        self,
        transition: PublicationTransition,
    ) -> DisabledPublicationPolicy: ...

    async def commit_candidate(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
    ) -> None: ...


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
    ) -> PublicationLifecycleResult:
        """Reopen the exact persisted candidate under explicit domain policy."""
        return await self._start_lifecycle(candidate, PublicationTransition.REOPEN)

    async def refresh(
        self,
        candidate: PublicationCandidate[PayloadT],
    ) -> PublicationLifecycleResult:
        """Refresh terms without changing a locally or remotely open status."""
        return await self._start_lifecycle(candidate, PublicationTransition.REFRESH)

    async def _start_lifecycle(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
    ) -> PublicationLifecycleResult:
        try:
            canonical_request = _canonical_request(
                candidate,
                transition,
                self._listing_request_factory,
            )
        except Exception as exc:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=transition,
                local_committed=False,
                failure_stage="setup",
                error_type=type(exc).__name__,
            )
        await self._require_persisted_binding(candidate.listing_id, candidate.binding)
        self._hooks.validate_candidate(candidate)
        await self._hooks.validate_lifecycle(
            candidate,
            transition,
            previous_local_committed=False,
        )
        if not self._enabled:
            commit = (
                self._hooks.disabled_publication_policy(transition)
                is DisabledPublicationPolicy.COMMIT_LOCAL
            )
            if commit:
                await self._hooks.commit_candidate(candidate, transition)
            return PublicationLifecycleResult(
                status="disabled",
                listing_id=candidate.listing_id,
                transition=transition,
                local_committed=commit,
            )
        return await self._execute_lifecycle(
            candidate,
            transition,
            canonical_request,
        )

    async def _execute_lifecycle(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
        canonical_request: str,
    ) -> PublicationLifecycleResult:
        target_results: tuple[PublicationTargetResult, ...] = ()
        intent: PublicationIntent | None = None
        failure_stage = "setup"
        publication_failure_stage: str | None = None
        publication_error_type: str | None = None
        receipts_persisted = False
        event_emitted = False
        try:
            async with self._open_registry_client() as registry_client:
                failure_stage = "preflight"
                target_results, write_targets, expected_statuses = (
                    await self._preflight_targets(
                        registry_client,
                        candidate,
                        transition,
                        canonical_request,
                    )
                )
                intent = PublicationIntent(
                    listing_id=candidate.listing_id,
                    binding=candidate.binding,
                    transition=transition,
                    canonical_request=canonical_request,
                    publisher_identity=registry_client.publisher_identity,
                    targets=tuple(registry_client.registry_targets),
                    expected_statuses=tuple(expected_statuses.items()),
                )
                if write_targets:
                    failure_stage = "fanout"
                    publication = await publish_listing_with_client(
                        json.loads(canonical_request),
                        registry_client=registry_client,
                        listing_request_factory=self._listing_request_factory,
                        storefront_url=self._storefront_url,
                        target_registry_urls=write_targets,
                        status=(
                            "open"
                            if transition is PublicationTransition.REOPEN
                            else None
                        ),
                        record_publications=None,
                        on_published=None,
                    )
                    target_results = await self._confirm_write_results(
                        registry_client,
                        candidate,
                        target_results,
                        publication,
                        expected_statuses,
                        canonical_request,
                    )
                    if publication.get("failure_stage") is not None:
                        publication_failure_stage = str(publication["failure_stage"])
                        publication_error_type = publication.get("error_type")
                side_effect_failure = await self._complete_lifecycle_side_effects(
                    candidate,
                    transition,
                    target_results,
                    intent,
                    local_committed=False,
                    receipts_persisted=False,
                    event_emitted=False,
                )
                if side_effect_failure is not None:
                    return side_effect_failure
                receipts_persisted = True
                event_emitted = self._on_published is None or any(
                    result.state is PublicationTargetState.CONFIRMED
                    for result in target_results
                )
                failure_stage = "context"
        except Exception as exc:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=transition,
                local_committed=False,
                partial=_target_results_partial(target_results),
                target_results=target_results,
                failure_stage=failure_stage,
                error_type=type(exc).__name__,
                intent=intent,
                receipts_persisted=receipts_persisted,
                event_emitted=event_emitted,
            )

        assert intent is not None
        if publication_failure_stage is not None:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=transition,
                local_committed=False,
                partial=_target_results_partial(target_results),
                target_results=target_results,
                failure_stage=publication_failure_stage,
                error_type=publication_error_type,
                intent=intent,
                receipts_persisted=receipts_persisted,
                event_emitted=event_emitted,
            )
        return await self._finish_lifecycle(
            candidate,
            transition,
            target_results,
            intent,
            already_committed=False,
            receipts_persisted=receipts_persisted,
            event_emitted=event_emitted,
        )

    async def recover(
        self,
        candidate: PublicationCandidate[PayloadT],
        previous: PublicationLifecycleResult,
    ) -> PublicationLifecycleResult:
        """Recover one explicit immutable operation without blind rewrites."""
        intent = previous.intent
        if intent is None:
            raise ValueError("publication result has no recoverable intent")
        try:
            canonical_request = _canonical_request(
                candidate,
                previous.transition,
                self._listing_request_factory,
            )
        except Exception as exc:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=previous.transition,
                local_committed=previous.local_committed,
                partial=_target_results_partial(previous.target_results),
                target_results=previous.target_results,
                failure_stage="recovery",
                error_type=type(exc).__name__,
                intent=intent,
                receipts_persisted=previous.receipts_persisted,
                event_emitted=previous.event_emitted,
            )
        await self._require_persisted_binding(candidate.listing_id, candidate.binding)
        self._hooks.validate_candidate(candidate)
        await self._hooks.validate_lifecycle(
            candidate,
            previous.transition,
            previous_local_committed=previous.local_committed,
        )
        if (
            intent.listing_id != candidate.listing_id
            or intent.binding != candidate.binding
            or intent.transition is not previous.transition
            or intent.canonical_request != canonical_request
        ):
            raise ValueError("publication recovery candidate does not match intent")

        expected_statuses = dict(intent.expected_statuses)
        retained: list[PublicationTargetResult] = []
        retry_targets: list[str] = []
        retained_tuple = previous.target_results
        outcomes_changed = False
        receipts_persisted = previous.receipts_persisted
        event_emitted = previous.event_emitted
        publication_failure_stage: str | None = None
        publication_error_type: str | None = None
        try:
            async with self._open_registry_client() as registry_client:
                if (
                    registry_client.publisher_identity != intent.publisher_identity
                    or tuple(registry_client.registry_targets) != intent.targets
                ):
                    raise ValueError(
                        "publication recovery identity does not match intent"
                    )
                for result in previous.target_results:
                    if result.state is PublicationTargetState.CONFIRMED:
                        retained.append(result)
                        continue
                    if result.state is PublicationTargetState.WRITE_FAILED:
                        retry_targets.append(result.registry_url)
                        outcomes_changed = True
                        continue
                    outcomes_changed = True
                    try:
                        summary = await registry_client.get_listing_from_registry(
                            registry_url=result.registry_url,
                            listing_id=candidate.listing_id,
                        )
                    except Exception as exc:
                        retained.append(
                            PublicationTargetResult(
                                registry_url=result.registry_url,
                                state=result.state,
                                wrote=result.wrote,
                                error_type=type(exc).__name__,
                                status_code=getattr(exc, "status_code", None),
                            )
                        )
                        continue
                    retained.append(
                        PublicationTargetResult(
                            registry_url=result.registry_url,
                            state=(
                                PublicationTargetState.CONFIRMED
                                if self._summary_matches(
                                    summary,
                                    intent.canonical_request,
                                    registry_client.publisher_identity,
                                    expected_statuses[result.registry_url],
                                )
                                else PublicationTargetState.CONFIRMATION_MISMATCH
                            ),
                            wrote=result.wrote,
                        )
                    )
                if retry_targets:
                    publication = await publish_listing_with_client(
                        json.loads(intent.canonical_request),
                        registry_client=registry_client,
                        listing_request_factory=self._listing_request_factory,
                        storefront_url=self._storefront_url,
                        target_registry_urls=retry_targets,
                        status=(
                            "open"
                            if previous.transition is PublicationTransition.REOPEN
                            else None
                        ),
                        record_publications=None,
                        on_published=None,
                    )
                    retained_tuple = await self._confirm_write_results(
                        registry_client,
                        candidate,
                        tuple(retained),
                        publication,
                        expected_statuses,
                        intent.canonical_request,
                    )
                    if publication.get("failure_stage") is not None:
                        publication_failure_stage = str(publication["failure_stage"])
                        publication_error_type = publication.get("error_type")
                else:
                    by_url = {result.registry_url: result for result in retained}
                    retained_tuple = tuple(
                        by_url[target.configured_url]
                        for target in registry_client.registry_targets
                    )
                receipts_persisted = (
                    previous.receipts_persisted and not outcomes_changed
                )
                side_effect_failure = await self._complete_lifecycle_side_effects(
                    candidate,
                    previous.transition,
                    retained_tuple,
                    intent,
                    local_committed=previous.local_committed,
                    receipts_persisted=receipts_persisted,
                    event_emitted=previous.event_emitted,
                )
                if side_effect_failure is not None:
                    return side_effect_failure
                receipts_persisted = True
                event_emitted = previous.event_emitted or (
                    self._on_published is None
                    or any(
                        result.state is PublicationTargetState.CONFIRMED
                        for result in retained_tuple
                    )
                )
        except Exception as exc:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=previous.transition,
                local_committed=previous.local_committed,
                partial=_target_results_partial(retained_tuple),
                target_results=retained_tuple,
                failure_stage="recovery",
                error_type=type(exc).__name__,
                intent=intent,
                receipts_persisted=receipts_persisted,
                event_emitted=event_emitted,
            )
        if publication_failure_stage is not None:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=previous.transition,
                local_committed=previous.local_committed,
                partial=_target_results_partial(retained_tuple),
                target_results=retained_tuple,
                failure_stage=publication_failure_stage,
                error_type=publication_error_type,
                intent=intent,
                receipts_persisted=receipts_persisted,
                event_emitted=event_emitted,
            )
        return await self._finish_lifecycle(
            candidate,
            previous.transition,
            retained_tuple,
            intent,
            already_committed=previous.local_committed,
            receipts_persisted=receipts_persisted,
            event_emitted=event_emitted,
        )

    async def _complete_lifecycle_side_effects(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
        target_results: tuple[PublicationTargetResult, ...],
        intent: PublicationIntent,
        *,
        local_committed: bool,
        receipts_persisted: bool,
        event_emitted: bool,
    ) -> PublicationLifecycleResult | None:
        if not receipts_persisted:
            try:
                await self._record_lifecycle_results(intent, target_results)
            except Exception as exc:
                return PublicationLifecycleResult(
                    status="error",
                    listing_id=candidate.listing_id,
                    transition=transition,
                    local_committed=local_committed,
                    partial=_target_results_partial(target_results),
                    target_results=target_results,
                    failure_stage="persistence",
                    error_type=type(exc).__name__,
                    intent=intent,
                    receipts_persisted=False,
                    event_emitted=event_emitted,
                )
            receipts_persisted = True

        confirmed = any(
            result.state is PublicationTargetState.CONFIRMED
            for result in target_results
        )
        if self._on_published is not None and confirmed and not event_emitted:
            payload = _listing_payload(candidate.payload)
            canonical = json.loads(intent.canonical_request)
            try:
                event_result = self._on_published(
                    listing_id=candidate.listing_id,
                    storefront_url=canonical["storefront_url"],
                    seller_principal=payload.get("seller_principal"),
                    offer_resource=canonical["offer_resource"],
                    accepted_escrows=canonical["accepted_escrows"],
                    settlement_options=canonical["settlement_options"],
                    demands=canonical["demands"],
                    max_duration_seconds=canonical.get("max_duration_seconds"),
                )
                if inspect.isawaitable(event_result):
                    await event_result
            except Exception as exc:
                return PublicationLifecycleResult(
                    status="error",
                    listing_id=candidate.listing_id,
                    transition=transition,
                    local_committed=local_committed,
                    partial=_target_results_partial(target_results),
                    target_results=target_results,
                    failure_stage="event",
                    error_type=type(exc).__name__,
                    intent=intent,
                    receipts_persisted=receipts_persisted,
                    event_emitted=False,
                )
        return None

    async def _finish_lifecycle(
        self,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
        target_results: tuple[PublicationTargetResult, ...],
        intent: PublicationIntent,
        *,
        already_committed: bool,
        receipts_persisted: bool,
        event_emitted: bool,
    ) -> PublicationLifecycleResult:
        confirmed = sum(
            result.state is PublicationTargetState.CONFIRMED
            for result in target_results
        )
        if not confirmed:
            return PublicationLifecycleResult(
                status="error",
                listing_id=candidate.listing_id,
                transition=transition,
                local_committed=False,
                partial=False,
                target_results=target_results,
                failure_stage="confirmation",
                intent=intent,
                receipts_persisted=receipts_persisted,
                event_emitted=event_emitted,
            )
        if not already_committed:
            try:
                await self._hooks.commit_candidate(candidate, transition)
            except Exception as exc:
                return PublicationLifecycleResult(
                    status="error",
                    listing_id=candidate.listing_id,
                    transition=transition,
                    local_committed=False,
                    partial=_target_results_partial(target_results),
                    target_results=target_results,
                    failure_stage="local_commit",
                    error_type=type(exc).__name__,
                    intent=intent,
                    receipts_persisted=receipts_persisted,
                    event_emitted=event_emitted,
                )
        partial = confirmed != len(target_results)
        return PublicationLifecycleResult(
            status="partial" if partial else "published",
            listing_id=candidate.listing_id,
            transition=transition,
            local_committed=True,
            partial=partial,
            target_results=target_results,
            intent=intent,
            receipts_persisted=receipts_persisted,
            event_emitted=event_emitted,
        )

    async def _preflight_targets(
        self,
        registry_client: Any,
        candidate: PublicationCandidate[PayloadT],
        transition: PublicationTransition,
        canonical_request: str,
    ) -> tuple[
        tuple[PublicationTargetResult, ...],
        tuple[str, ...],
        dict[str, str],
    ]:
        results: list[PublicationTargetResult] = []
        write_targets: list[str] = []
        expected_statuses: dict[str, str] = {
            target.configured_url: "open"
            for target in registry_client.registry_targets
        }
        for target in registry_client.registry_targets:
            url = target.configured_url
            try:
                summary = await registry_client.get_listing_from_registry(
                    registry_url=url,
                    listing_id=candidate.listing_id,
                )
            except RegistryClientError as exc:
                if exc.status_code == 404:
                    write_targets.append(url)
                    continue
                results.append(
                    PublicationTargetResult(
                        registry_url=url,
                        state=PublicationTargetState.PREFLIGHT_UNKNOWN,
                        wrote=False,
                        error_type=type(exc).__name__,
                        status_code=exc.status_code,
                    )
                )
                continue
            except Exception as exc:
                results.append(
                    PublicationTargetResult(
                        registry_url=url,
                        state=PublicationTargetState.PREFLIGHT_UNKNOWN,
                        wrote=False,
                        error_type=type(exc).__name__,
                    )
                )
                continue

            current_status = str(summary.status or "").lower()
            if (
                str(summary.id or "") != candidate.listing_id
                or summary.publisher_principals is None
                or registry_client.publisher_identity
                not in summary.publisher_principals
            ):
                results.append(
                    PublicationTargetResult(
                        registry_url=url,
                        state=PublicationTargetState.CONFIRMATION_MISMATCH,
                        wrote=False,
                    )
                )
                continue
            if transition is PublicationTransition.REFRESH and current_status != "open":
                results.append(
                    PublicationTargetResult(
                        registry_url=url,
                        state=PublicationTargetState.CONFIRMATION_MISMATCH,
                        wrote=False,
                    )
                )
                continue
            expected_statuses[url] = (
                "open"
                if transition is PublicationTransition.REOPEN
                else current_status
            )
            if self._summary_matches(
                summary,
                canonical_request,
                registry_client.publisher_identity,
                expected_statuses[url],
            ):
                results.append(
                    PublicationTargetResult(
                        registry_url=url,
                        state=PublicationTargetState.CONFIRMED,
                        wrote=False,
                    )
                )
            else:
                write_targets.append(url)
        return tuple(results), tuple(write_targets), expected_statuses

    async def _confirm_write_results(
        self,
        registry_client: Any,
        candidate: PublicationCandidate[PayloadT],
        preflight_results: tuple[PublicationTargetResult, ...],
        publication: dict[str, Any],
        expected_statuses: dict[str, str],
        canonical_request: str,
    ) -> tuple[PublicationTargetResult, ...]:
        by_url = {result.registry_url: result for result in preflight_results}
        for result in publication.get("registry_results") or ():
            url = str(result["registry_url"])
            if not result.get("success"):
                status_code = result.get("status_code")
                by_url[url] = PublicationTargetResult(
                    registry_url=url,
                    state=(
                        PublicationTargetState.WRITE_FAILED
                        if _is_confirmed_rejection(status_code)
                        else PublicationTargetState.WRITE_UNKNOWN
                    ),
                    wrote=True,
                    error_type=result.get("error_type"),
                    status_code=status_code,
                )
                continue
            try:
                summary = await registry_client.get_listing_from_registry(
                    registry_url=url,
                    listing_id=candidate.listing_id,
                )
            except Exception as exc:
                state = (
                    PublicationTargetState.CONFIRMATION_MISMATCH
                    if isinstance(exc, RegistryClientError)
                    and exc.status_code == 404
                    else PublicationTargetState.WRITE_UNCONFIRMED
                )
                by_url[url] = PublicationTargetResult(
                    registry_url=url,
                    state=state,
                    wrote=True,
                    error_type=type(exc).__name__,
                    status_code=getattr(exc, "status_code", None),
                )
                continue
            by_url[url] = PublicationTargetResult(
                registry_url=url,
                state=(
                    PublicationTargetState.CONFIRMED
                    if self._summary_matches(
                        summary,
                        canonical_request,
                        registry_client.publisher_identity,
                        expected_statuses[url],
                    )
                    else PublicationTargetState.CONFIRMATION_MISMATCH
                ),
                wrote=True,
            )
        for url in expected_statuses:
            if url not in by_url:
                by_url[url] = PublicationTargetResult(
                    registry_url=url,
                    state=PublicationTargetState.WRITE_UNKNOWN,
                    wrote=True,
                    error_type=publication.get("error_type"),
                )
        return tuple(
            by_url[target.configured_url]
            for target in registry_client.registry_targets
        )

    def _summary_matches(
        self,
        summary: Any,
        canonical_request: str,
        publisher_identity: Identity,
        expected_status: str,
    ) -> bool:
        payload = json.loads(canonical_request)
        return (
            str(summary.id or "") == str(payload["listing_id"])
            and summary.publisher_principals is not None
            and publisher_identity in summary.publisher_principals
            and summary.storefront_url == payload.get("storefront_url")
            and summary.offer
            == ensure_json_obj(payload.get("offer_resource"), {})
            and summary.accepted_escrows
            == ensure_json_obj(payload.get("accepted_escrows"), [])
            and summary.settlement_options
            == ensure_json_obj(payload.get("settlement_options"), [])
            and summary.demands == ensure_json_obj(payload.get("demands"), [])
            and summary.max_duration_seconds == payload.get("max_duration_seconds")
            and str(summary.status or "").lower() == expected_status
        )

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
            close_result = await self.close(listing)
            if str(close_result.get("status", "?")) in {
                "closed",
                "skipped",
                "queued",
            }:
                closed.append(listing.listing_id)
        for candidate in plan.reopen:
            if candidate.listing_id in seen:
                raise ValueError(
                    f"listing {candidate.listing_id!r} cannot close and reopen in one plan"
                )
            seen.add(candidate.listing_id)
            reopen_result = await self.reopen(candidate)
            if reopen_result.local_committed:
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

    async def _record_lifecycle_results(
        self,
        intent: PublicationIntent,
        results: tuple[PublicationTargetResult, ...],
    ) -> None:
        payload = json.loads(intent.canonical_request)
        safe_results: list[dict[str, Any]] = []
        for result in results:
            if (
                result.state is not PublicationTargetState.CONFIRMED
                and not result.wrote
            ):
                continue
            success = result.state is PublicationTargetState.CONFIRMED
            last_error = None
            if not success:
                last_error = (
                    "registry write failed"
                    if result.state is PublicationTargetState.WRITE_FAILED
                    else f"registry lifecycle {result.state.value}"
                )
                if result.error_type:
                    last_error += f": {result.error_type}"
                if result.status_code is not None:
                    last_error += f" HTTP {result.status_code}"
            safe_results.append(
                {
                    "registry_url": result.registry_url,
                    "success": success,
                    "payload": payload,
                    "registry_assigned_id": intent.listing_id if success else None,
                    "error": last_error,
                }
            )
        await self._record_results(
            intent.listing_id,
            safe_results,
            success_status="published",
            strict=True,
        )

    async def _record_results(
        self,
        listing_id: str,
        results: list[dict[str, Any]],
        *,
        success_status: str,
        strict: bool = False,
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
                if strict:
                    raise
                logger.warning(
                    "[PUBLICATIONS] Failed to record registry result for %s @ %s: %s",
                    listing_id,
                    result.get("registry_url"),
                    exc,
                )


def _listing_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"unsupported listing payload: {type(value).__name__}")


def _canonical_request(
    candidate: PublicationCandidate[Any],
    transition: PublicationTransition,
    listing_request_factory: RequestFactory,
) -> str:
    payload = _listing_payload(candidate.payload)
    if payload.get("listing_id") != candidate.listing_id:
        raise ValueError(
            "publication payload listing_id does not match its bound candidate"
        )
    kwargs = {
        "listing_id": candidate.listing_id,
        "offer": ensure_json_obj(payload.get("offer_resource"), {}),
        "accepted_escrows": ensure_json_obj(payload.get("accepted_escrows"), []),
        "settlement_options": ensure_json_obj(payload.get("settlement_options"), []),
        "demands": ensure_json_obj(payload.get("demands"), []),
        "max_duration_seconds": payload.get("max_duration_seconds"),
        "storefront_url": payload.get("storefront_url"),
    }
    if transition is PublicationTransition.REOPEN:
        kwargs["status"] = "open"
    request = listing_request_factory(**kwargs)
    to_dict = getattr(request, "to_dict", None)
    if callable(to_dict):
        request = to_dict()
    else:
        model_dump = getattr(request, "model_dump", None)
        if callable(model_dump):
            request = model_dump(mode="json", exclude_none=True)
    if not isinstance(request, dict):
        raise TypeError("listing request must serialize to an object")
    return json.dumps(request, sort_keys=True, separators=(",", ":"))


def _is_confirmed_rejection(status_code: Any) -> bool:
    return (
        isinstance(status_code, int)
        and 400 <= status_code < 500
        and status_code != 408
    )


def _target_results_partial(
    results: tuple[PublicationTargetResult, ...],
) -> bool:
    confirmed = sum(
        result.state is PublicationTargetState.CONFIRMED for result in results
    )
    return 0 < confirmed < len(results)
