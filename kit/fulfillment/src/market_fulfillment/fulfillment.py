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
from .settlement_types import SettlementResource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FulfillmentAcceptance:
    fulfillment_id: str
    capacity_reservation_id: str
    state: str


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
