"""Bare-metal domain callback composition for common hosted settlement routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_identity import Identity
from market_settlement_runtime import (
    AuthorizedSettlementRequest,
    HostedAcceptedAgreement,
    HostedSettlementRouteCallbacks,
    HostedSettlementRouteService,
    SettlementObligationRecord,
)

from .hosted_binding import ensure_accepted_hosted_binding
from .hosted_lifecycle import BareMetalHostedLifecycleCallbacks
from .sqlite_client import SQLiteClient


@dataclass(frozen=True, slots=True)
class BareMetalHostedDomainCallbacks:
    """Bare-owned accepted-state hooks; common mechanics remain in the kit."""

    prepare: Callable[
        [str, str, SettlementObligationRecord | None],
        Awaitable[HostedAcceptedAgreement],
    ]
    reserve: Callable[
        [HostedAcceptedAgreement, str], Awaitable[SettlementObligationRecord]
    ]
    fulfill: Callable[
        [SettlementObligationRecord, str], Awaitable[SettlementObligationRecord]
    ]
    project: Callable[
        [SettlementObligationRecord, Any | None, Mapping[str, Any] | None],
        Awaitable[Mapping[str, Any]],
    ]
    cleanup: Callable[[str, str], Awaitable[None]]
    before_reclaim: (
        Callable[
            [SettlementObligationRecord, str], Awaitable[SettlementObligationRecord]
        ]
        | None
    ) = None


def lifecycle_domain_callbacks(
    *,
    db: SQLiteClient,
    lifecycle: BareMetalHostedLifecycleCallbacks,
) -> BareMetalHostedDomainCallbacks:
    """Bind accepted-state persistence and physical reclaim guards once."""

    async def prepare(
        agreement_ref: str,
        obligation_ref: str,
        record: SettlementObligationRecord | None,
    ) -> HostedAcceptedAgreement:
        await ensure_accepted_hosted_binding(
            db=db,
            negotiation_id=agreement_ref,
            obligation_ref=obligation_ref,
        )
        return await lifecycle.prepare(agreement_ref, obligation_ref, record)

    async def before_reclaim(
        record: SettlementObligationRecord,
        worker_id: str,
    ) -> SettlementObligationRecord:
        del worker_id
        await lifecycle.assert_reclaim_safe(record)
        return record

    return BareMetalHostedDomainCallbacks(
        prepare=prepare,
        reserve=lifecycle.reserve,
        fulfill=lifecycle.fulfill,
        project=lifecycle.project,
        cleanup=lifecycle.cleanup,
        before_reclaim=before_reclaim,
    )


def build_bare_metal_hosted_route_service(
    *,
    repository: Any,
    runtime: Any,
    domain_callbacks: BareMetalHostedDomainCallbacks,
    authorize_request: Callable[
        [Any, str, str, Identity, Mapping[str, Any] | None],
        Awaitable[Any],
    ],
) -> HostedSettlementRouteService:
    """Install bare interpretation into the one common route service."""

    async def authorize(
        request_context: Any,
        operation: str,
        resource_id: str,
        expected_principal: Identity,
        body: Mapping[str, Any] | None,
    ) -> AuthorizedSettlementRequest:
        authenticated = await authorize_request(
            request_context,
            operation,
            resource_id,
            expected_principal,
            body,
        )
        return AuthorizedSettlementRequest(
            exact_retry=bool(authenticated.exact_retry),
            recorded_outcome=authenticated.recorded_outcome,
        )

    async def wake(obligation_ref: str) -> None:
        await repository.wake_settlement_obligation(obligation_ref)

    return HostedSettlementRouteService(
        repository=repository,
        runtime=runtime,
        callbacks=HostedSettlementRouteCallbacks(
            prepare=domain_callbacks.prepare,
            authorize=authorize,
            reserve=domain_callbacks.reserve,
            fulfill=domain_callbacks.fulfill,
            project=domain_callbacks.project,
            cleanup=domain_callbacks.cleanup,
            before_reclaim=domain_callbacks.before_reclaim,
        ),
        mechanism_id="fiat.stripe.v1",
        wake=wake,
    )


__all__ = [
    "BareMetalHostedDomainCallbacks",
    "build_bare_metal_hosted_route_service",
    "lifecycle_domain_callbacks",
]
