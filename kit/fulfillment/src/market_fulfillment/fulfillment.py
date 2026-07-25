"""Durable fulfillment acceptance and provider dispatch orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .db import SettlementRecord, SettlementRecordState
from .envelopes import VersionedEnvelope
from .fulfillment_persistence import FulfillmentTransaction, FulfillmentUnitOfWork
from .provider import (
    FulfillmentCreateFailedError,
    FulfillmentValidationIssue,
    FulfillmentValidationResult,
    ProviderRegistry,
)
from .results import (
    FulfillmentCredential,
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    build_fulfillment_result_envelope,
)
from .settlement_types import SettlementEntityNotFoundError, SettlementResource

logger = logging.getLogger(__name__)


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
            resource_kind=(record.scheduling_requirements or {}).get(
                "resource_kind", "unknown"
            ),
            provider=record.provider,
            attributes=dict(record.resource_attributes or {}),
        )

    @staticmethod
    def _view(record: Any) -> FulfillmentAcceptance:
        return FulfillmentAcceptance(
            fulfillment_id=record.fulfillment_id,
            capacity_reservation_id=record.capacity_reservation_id,
            state=record.state,
        )

    def _prepare_fulfillment(
        self,
        tx: FulfillmentTransaction,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
        record: Any | None = None,
    ) -> PreparedFulfillment:
        record = record or tx.db.get(SettlementRecord, capacity_reservation_id)
        if record is None:
            raise LookupError(f"no scheduled settlement for {capacity_reservation_id!r}")
        if record.market != market:
            raise ValueError(
                f"settlement was scheduled for market={record.market!r}"
            )

        pool = tx.get_pool(record.pool_id)
        if pool is None:
            raise LookupError(f"pool {record.pool_id!r} not found")

        provider = self._providers.require(record.provider)
        prepared = provider.prepare_create(
            capacity_reservation_id=capacity_reservation_id,
            request=fulfillment_request,
            resource=self._resource(record),
            pool_config=dict(pool.provider_config or {}),
        )
        return PreparedFulfillment(record=record, provider=provider, prepared=prepared)

    def validate_fulfillment(
        self,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
    ) -> FulfillmentValidationResult:
        try:
            with self._uow.read_transaction() as tx:
                self._prepare_fulfillment(
                    tx,
                    capacity_reservation_id=capacity_reservation_id,
                    market=market,
                    fulfillment_request=fulfillment_request,
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
                        domain_resource_ref=resource.domain_resource_ref,
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

        credentials: tuple[FulfillmentCredential, ...] = ()
        if is_active:
            provider = self._providers.require(provider_name)
            credential_set = await provider.fetch_credentials(provider_metadata)
            credentials = tuple(
                FulfillmentCredential(
                    role=credential.role,
                    password=credential.password,
                    ssh_commands=credential.ssh_commands,
                )
                for credential in credential_set.credentials
            )

        payload = FulfillmentResultPayload(
            fulfillment_id=fulfillment_id_value,
            capacity_reservation_id=capacity_reservation_id,
            state=state,
            failure_reason=failure_reason,
            failure_message=failure_message,
            provisioned_resources=outputs,
            credentials=credentials,
        )
        return build_fulfillment_result_envelope(payload)
