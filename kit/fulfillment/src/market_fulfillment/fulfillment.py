"""Durable fulfillment acceptance and provider dispatch orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from market_resource_pools import pool_delivers_offering_mode

from .db import SettlementRecord, SettlementRecordState
from .envelopes import VersionedEnvelope
from .fulfillment_persistence import FulfillmentTransaction, FulfillmentUnitOfWork
from .provider import (
    CredentialFetchFailedError,
    FulfillmentConflictError,
    FulfillmentCreateFailedError,
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    ProviderRegistry,
    ProvisionedResourceDescriptor,
    SettlementResult,
)
from .results import (
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    build_fulfillment_result_envelope,
)
from .settlement_types import SettlementEntityNotFoundError, SettlementResource

logger = logging.getLogger(__name__)

# States a fulfillment reaches only after begin_fulfillment_teardown has
# already run once. A repeat call in any of these states is an idempotent
# no-op return, not a re-preparation or a conflict -- including terminal
# torn_down and the retryable teardown_failed, which recovery may still
# resolve by calling this same entrypoint again.
_TEARDOWN_INITIATED_STATES = frozenset(
    {
        SettlementRecordState.teardown_dispatch_pending.value,
        SettlementRecordState.tearing_down.value,
        SettlementRecordState.torn_down.value,
        SettlementRecordState.teardown_failed.value,
    }
)


@dataclass(frozen=True)
class FulfillmentAcceptance:
    fulfillment_id: str
    capacity_reservation_id: str
    state: str


@dataclass(frozen=True)
class FulfillmentStatus:
    """The cheap, provider-free read `get_fulfillment_status` returns.

    A direct projection of the durable aggregate's identity, state, and
    failure fields -- no provisioned-resource outputs or credentials, which
    belong to the heavier `get_fulfillment_result` read.
    """

    fulfillment_id: str
    capacity_reservation_id: str
    state: str
    failure_reason: str | None
    failure_message: str | None


@dataclass(frozen=True)
class PreparedFulfillment:
    record: Any
    provider: Any
    prepared: VersionedEnvelope[Any]


class _NoCode:
    co_varnames: tuple[str, ...] = ()


_NO_CODE = _NoCode()


class FulfillmentOrchestrator:
    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        unit_of_work: FulfillmentUnitOfWork,
    ) -> None:
        self._providers = provider_registry
        self._uow = unit_of_work

    @staticmethod
    def _resource(record: Any) -> SettlementResource:
        return SettlementResource(
            settlement_resource_id=record.settlement_resource_id,
            pool_id=record.pool_id,
            executor_kind=(record.scheduling_requirements or {}).get(
                "executor_kind"
            ),
            resource_kind=(record.scheduling_requirements or {}).get(
                "resource_kind", "unknown"
            ),
            provider=record.provider,
            attributes=dict(record.resource_attributes or {}),
            dimensions=dict(
                (record.scheduling_requirements or {}).get("dimensions") or {}
            ),
        )

    @staticmethod
    def _view(record: Any) -> FulfillmentAcceptance:
        return FulfillmentAcceptance(
            fulfillment_id=record.fulfillment_id,
            capacity_reservation_id=record.capacity_reservation_id,
            state=record.state,
        )

    @staticmethod
    def _require_pool_delivers_mode(tx: FulfillmentTransaction, record: Any) -> Any:
        pool = tx.get_pool(record.pool_id)
        if pool is None:
            raise LookupError(f"pool {record.pool_id!r} not found")
        executor_kind = (record.scheduling_requirements or {}).get("executor_kind")
        if not executor_kind:
            raise FulfillmentConflictError(
                "scheduled settlement has no explicit executor_kind"
            )
        if not pool_delivers_offering_mode(pool.policy_tags, executor_kind):
            raise FulfillmentConflictError(
                f"pool {record.pool_id!r} does not declare offering mode "
                f"{executor_kind!r}"
            )
        return pool

    def _prepare_fulfillment(
        self,
        tx: FulfillmentTransaction,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
        record: Any | None = None,
        acquire: bool = True,
    ) -> PreparedFulfillment:
        """Resolve and validate a fulfillment into a provider operation.

        ``acquire=False`` asks the provider to prepare without taking anything
        it would have to give back — the validation path, which answers a
        question rather than making a commitment. Every rejection still runs.
        """
        record = record or tx.db.get(SettlementRecord, capacity_reservation_id)
        if record is None:
            raise LookupError(f"no scheduled settlement for {capacity_reservation_id!r}")
        if record.market != market:
            raise ValueError(
                f"settlement was scheduled for market={record.market!r}"
            )

        pool = self._require_pool_delivers_mode(tx, record)
        provider = self._providers.require(record.provider)
        prepare = provider.prepare_create
        kwargs: dict[str, Any] = {
            "capacity_reservation_id": capacity_reservation_id,
            "request": fulfillment_request,
            "resource": self._resource(record),
            "pool_config": dict(pool.provider_config or {}),
        }
        # Providers that acquire nothing during preparation need no say in
        # this, and are not required to grow a parameter to keep working.
        if not acquire and "allocate" in getattr(prepare, "__code__", _NO_CODE).co_varnames:
            kwargs["allocate"] = False
        prepared = prepare(**kwargs)
        return PreparedFulfillment(record=record, provider=provider, prepared=prepared)

    def validate_fulfillment(
        self,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
    ) -> FulfillmentValidationResult:
        try:
            with self._uow.read_transaction() as tx:
                # Validation answers whether this request would be accepted. It
                # must not acquire anything on the way to the answer, or a
                # caller checking repeatedly consumes resources it never asked
                # for and never receives.
                self._prepare_fulfillment(
                    tx,
                    capacity_reservation_id=capacity_reservation_id,
                    market=market,
                    fulfillment_request=fulfillment_request,
                    acquire=False,
                )
            return FulfillmentValidationResult()
        except Exception as exc:
            return FulfillmentValidationResult(
                (
                    FulfillmentValidationIssue(
                        code="request_invalid",
                        message=str(exc),
                    ),
                )
            )

    async def begin_fulfillment(
        self,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
    ) -> FulfillmentAcceptance:
        with self._uow.transaction() as tx:
            decision = tx.accept(
                capacity_reservation_id=capacity_reservation_id,
                market=market,
                fulfillment_request=fulfillment_request,
            )
            record = decision.record
            if not decision.dispatch_required:
                return self._view(record)

            provider = self._providers.require(record.provider)
            if record.prepared_create_operation:
                # A snapshotted provider request preserves accepted inputs, but
                # it cannot preserve permission to deliver a mode the operator
                # has since withdrawn from the pool.
                self._require_pool_delivers_mode(tx, record)
            if record.prepared_create_operation:
                prepared = VersionedEnvelope.model_validate(
                    record.prepared_create_operation
                )
            else:
                preparation = self._prepare_fulfillment(
                    tx,
                    capacity_reservation_id=capacity_reservation_id,
                    market=market,
                    fulfillment_request=fulfillment_request,
                    record=record,
                )
                provider = preparation.provider
                prepared = preparation.prepared
                tx.persist_prepared_create(capacity_reservation_id, prepared)
            accepted = self._view(record)

        try:
            result = await provider.dispatch_create(prepared)
        except FulfillmentCreateFailedError:
            logger.exception(
                "Fulfillment dispatch failed after durable acceptance",
                extra={"capacity_reservation_id": capacity_reservation_id},
            )
            return FulfillmentAcceptance(
                fulfillment_id=accepted.fulfillment_id,
                capacity_reservation_id=accepted.capacity_reservation_id,
                state=SettlementRecordState.dispatch_pending.value,
            )

        with self._uow.transaction() as tx:
            acknowledged = tx.acknowledge_create(
                capacity_reservation_id,
                result.provider_metadata,
            )
            return self._view(acknowledged)

    async def begin_fulfillment_teardown(self, fulfillment_id: str) -> FulfillmentAcceptance:
        """Durably initiate whole-fulfillment teardown.

        Performs no provider I/O itself: prepares the teardown envelope --
        reusing one already captured on the row (backfilled rows, or a
        retried call after a prior preparation) rather than re-preparing --
        and transitions the aggregate to `teardown_dispatch_pending`.
        `FulfillmentConvergenceWatchdog`'s dispatch and status-convergence
        passes own everything downstream of that transition; there is no
        synchronous dispatch attempt here, unlike `begin_fulfillment`,
        because nothing depends on teardown completing before this call
        returns.

        Idempotent: a fulfillment already at or past
        `teardown_dispatch_pending` (including terminal `torn_down` and the
        retryable `teardown_failed`) returns its current view rather than
        raising or re-preparing, so a caller does not need to track whether
        it already asked for teardown before asking again.
        """

        with self._uow.transaction() as tx:
            record = tx.get_by_fulfillment_id(fulfillment_id)
            if record is None:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment {fulfillment_id!r}"
                )
            if record.state in _TEARDOWN_INITIATED_STATES:
                return self._view(record)
            if record.state != SettlementRecordState.active.value:
                raise FulfillmentConflictError(
                    f"fulfillment {fulfillment_id!r} is {record.state!r}; "
                    "only an active fulfillment can begin teardown"
                )

            if record.prepared_teardown_operation:
                prepared = VersionedEnvelope.model_validate(
                    record.prepared_teardown_operation
                )
            else:
                pool = tx.get_pool(record.pool_id)
                if pool is None:
                    raise LookupError(f"pool {record.pool_id!r} not found")
                provider = self._providers.require(record.provider)
                prepared = provider.prepare_teardown(
                    self._settlement_result(tx, record),
                    dict(pool.provider_config or {}),
                )

            updated = tx.begin_teardown(fulfillment_id, prepared)
            return self._view(updated)

    @staticmethod
    def _settlement_result(tx: FulfillmentTransaction, record: Any) -> SettlementResult:
        provisioned = tx.list_provisioned_resources(record.capacity_reservation_id)
        return SettlementResult(
            capacity_reservation_id=record.capacity_reservation_id,
            fulfillment_id=record.fulfillment_id,
            resource=FulfillmentOrchestrator._resource(record),
            provisioned_resources=tuple(
                {
                    "provisioned_resource_id": resource.provisioned_resource_id,
                    "status": resource.status,
                }
                for resource in provisioned
            ),
            provider_metadata=dict(record.provider_metadata or {}),
        )

    def get_fulfillment_status(self, fulfillment_id: str) -> FulfillmentStatus:
        """Read current aggregate state -- no provider or Ansible call.

        A read reflects current durable state on demand; there is no
        separate outbox or delivery-acknowledgement state to consult. Uses
        the read-only transaction (no SQLite writer-slot reservation), the
        same primitive `validate_fulfillment` already uses.
        """

        with self._uow.read_transaction() as tx:
            record = tx.get_by_fulfillment_id(fulfillment_id)
            if record is None:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment {fulfillment_id!r}"
                )
            return FulfillmentStatus(
                fulfillment_id=record.fulfillment_id,
                capacity_reservation_id=record.capacity_reservation_id,
                state=record.state,
                failure_reason=record.failure_reason,
                failure_message=record.failure_message,
            )

    async def get_fulfillment_result(self, fulfillment_id: str) -> VersionedEnvelope[Any]:
        """Read the caller-facing result projection as a `fulfillment.result.v1` envelope.

        Provisioned-resource outputs and credentials are populated only when
        the aggregate is `active`; every other state returns both empty
        rather than an error, since the aggregate's identity, state, and
        failure detail are still meaningful before or after `active`. The
        read transaction is closed before the live credential fetch, which
        performs provider I/O and must not run with a database transaction
        open, matching the "no DB transaction open during provider I/O"
        principle the convergence worker already establishes.
        """

        with self._uow.read_transaction() as tx:
            record = tx.get_by_fulfillment_id(fulfillment_id)
            if record is None:
                raise SettlementEntityNotFoundError(
                    f"no fulfillment {fulfillment_id!r}"
                )

            is_active = record.state == SettlementRecordState.active.value
            outputs: tuple[ProvisionedResourceOutput, ...] = ()
            if is_active:
                outputs = tuple(
                    ProvisionedResourceOutput(
                        provisioned_resource_id=resource.provisioned_resource_id,
                        status=resource.status,
                    )
                    for resource in tx.list_provisioned_resources(
                        record.capacity_reservation_id
                    )
                )

            fulfillment_id_value = record.fulfillment_id
            capacity_reservation_id = record.capacity_reservation_id
            state = record.state
            failure_reason = record.failure_reason
            failure_message = record.failure_message
            provider_name = record.provider
            provider_metadata = dict(record.provider_metadata or {})

        domain_result: VersionedEnvelope[Any] | None = None
        if is_active:
            provider = self._providers.require(provider_name)
            descriptors = tuple(
                ProvisionedResourceDescriptor(
                    provisioned_resource_id=output.provisioned_resource_id,
                    status=output.status,
                )
                for output in outputs
            )
            try:
                domain_result = await provider.fetch_credentials(
                    provider_metadata,
                    descriptors,
                )
            except Exception as exc:
                if isinstance(exc, CredentialFetchFailedError):
                    raise
                logger.exception(
                    "Unexpected credential fetch failure",
                    extra={
                        "fulfillment_id": fulfillment_id_value,
                        "provider": provider_name,
                    },
                )
                raise CredentialFetchFailedError(
                    "the fulfillment provider could not produce its result"
                ) from exc

        payload = FulfillmentResultPayload(
            fulfillment_id=fulfillment_id_value,
            capacity_reservation_id=capacity_reservation_id,
            state=state,
            failure_reason=failure_reason,
            failure_message=failure_message,
            provisioned_resources=outputs,
            domain_result=domain_result,
        )
        return build_fulfillment_result_envelope(payload)
