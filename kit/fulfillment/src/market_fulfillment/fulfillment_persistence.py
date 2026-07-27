"""Persistence boundaries for durable fulfillment acceptance and acknowledgement."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Protocol

from sqlalchemy.orm import Session

from market_resource_pools import ResourcePoolService

from .db import SettlementRecordState
from .envelopes import VersionedEnvelope
from .provider import FulfillmentConflictError
from .settlement_repository import SettlementRepository, begin_sqlite_write_transaction


@dataclass(frozen=True)
class FulfillmentAcceptanceDecision:
    record: Any
    newly_accepted: bool
    dispatch_required: bool


class FulfillmentTransaction(Protocol):
    db: Session

    def accept(
        self,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
    ) -> FulfillmentAcceptanceDecision: ...

    def get_pool(self, pool_id: str) -> Any | None: ...

    def persist_prepared_create(
        self,
        capacity_reservation_id: str,
        prepared: VersionedEnvelope[Any],
    ) -> Any: ...

    def acknowledge_create(
        self,
        capacity_reservation_id: str,
        provider_metadata: dict[str, Any],
    ) -> Any: ...

    def get_by_fulfillment_id(self, fulfillment_id: str) -> Any | None: ...

    def list_provisioned_resources(self, capacity_reservation_id: str) -> list[Any]: ...


class FulfillmentUnitOfWork(Protocol):
    @contextmanager
    def transaction(self) -> Iterator[FulfillmentTransaction]: ...

    @contextmanager
    def read_transaction(self) -> Iterator[FulfillmentTransaction]: ...


class SqlAlchemyFulfillmentTransaction:
    def __init__(
        self,
        db: Session,
        pool_service: ResourcePoolService,
        repository: SettlementRepository,
    ) -> None:
        self.db = db
        self._pool_service = pool_service
        self._repository = repository

    def accept(
        self,
        *,
        capacity_reservation_id: str,
        market: str,
        fulfillment_request: VersionedEnvelope[Any],
    ) -> FulfillmentAcceptanceDecision:
        before = self._repository.get(self.db, capacity_reservation_id)
        was_accepted = bool(before and before.fulfillment_id)
        record = self._repository.accept_fulfillment(
            self.db,
            capacity_reservation_id=capacity_reservation_id,
            market=market,
            fulfillment_request=fulfillment_request,
        )
        dispatch_required = (
            record.state == SettlementRecordState.dispatch_pending.value
            and not dict(record.provider_metadata or {})
        )
        return FulfillmentAcceptanceDecision(
            record=record,
            newly_accepted=not was_accepted,
            dispatch_required=dispatch_required,
        )

    def get_pool(self, pool_id: str) -> Any | None:
        return self._pool_service.get_pool_in_session(self.db, pool_id)

    def persist_prepared_create(
        self,
        capacity_reservation_id: str,
        prepared: VersionedEnvelope[Any],
    ) -> Any:
        record = self._repository.get(self.db, capacity_reservation_id)
        if record is None:
            raise LookupError(capacity_reservation_id)

        value = prepared.model_dump(mode="json")
        if (
            record.prepared_create_operation is not None
            and record.prepared_create_operation != value
        ):
            raise FulfillmentConflictError(
                "accepted fulfillment already has a different prepared create operation"
            )

        record.prepared_create_operation = value
        self.db.flush()
        return record

    def acknowledge_create(
        self,
        capacity_reservation_id: str,
        provider_metadata: dict[str, Any],
    ) -> Any:
        record = self._repository.get(self.db, capacity_reservation_id)
        if record is None:
            raise LookupError(capacity_reservation_id)

        existing = dict(record.provider_metadata or {})
        incoming = dict(provider_metadata)
        if existing and existing != incoming:
            raise FulfillmentConflictError(
                "provider submission was already acknowledged with different metadata"
            )
        if existing == incoming and record.state == SettlementRecordState.dispatching.value:
            return record

        return self._repository.transition(
            self.db,
            capacity_reservation_id,
            SettlementRecordState.dispatching.value,
            provider_metadata=incoming,
        )

    def get_by_fulfillment_id(self, fulfillment_id: str) -> Any | None:
        return self._repository.get_by_fulfillment_id(self.db, fulfillment_id)

    def list_provisioned_resources(self, capacity_reservation_id: str) -> list[Any]:
        return self._repository.list_provisioned_resources(self.db, capacity_reservation_id)


class SqlAlchemyFulfillmentUnitOfWork:
    def __init__(
        self,
        session_factory: Any,
        pool_service: ResourcePoolService,
        repository: SettlementRepository | None = None,
        transaction_type: type[SqlAlchemyFulfillmentTransaction] = (
            SqlAlchemyFulfillmentTransaction
        ),
    ) -> None:
        self.session_factory = session_factory
        self.pool_service = pool_service
        self.repository = repository or SettlementRepository()
        self.transaction_type = transaction_type

    @contextmanager
    def transaction(self) -> Iterator[FulfillmentTransaction]:
        """Open a write-capable session without reserving the writer slot here.

        ``tx.accept()`` (``SettlementRepository.accept_fulfillment``) already
        calls ``begin_sqlite_write_transaction`` as its own first operation --
        it is also a tested, standalone entry point used directly outside
        any unit of work, so it must keep that guarantee. Every real
        ``transaction()`` usage in this codebase calls ``tx.accept()`` first,
        so reserving the writer slot again here would issue a second
        ``BEGIN IMMEDIATE`` on the same session, which SQLite rejects.
        """
        with self.session_factory() as db:
            tx = self.transaction_type(db, self.pool_service, self.repository)
            try:
                yield tx
                db.commit()
            except Exception:
                db.rollback()
                raise

    @contextmanager
    def read_transaction(self) -> Iterator[FulfillmentTransaction]:
        """Provide consistent reads without reserving SQLite's writer slot."""
        with self.session_factory() as db:
            tx = self.transaction_type(db, self.pool_service, self.repository)
            try:
                yield tx
            finally:
                db.rollback()
