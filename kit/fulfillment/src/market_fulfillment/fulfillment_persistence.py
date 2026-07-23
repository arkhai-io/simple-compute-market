"""Persistence boundary for durable fulfillment acceptance and acknowledgement."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Protocol
from sqlalchemy.orm import Session
from market_resource_pools import ResourcePoolService
from .db import SettlementRecordState
from .envelopes import VersionedEnvelope
from .provider import FulfillmentConflictError
from .repository import SettlementRepository, begin_sqlite_write_transaction

@dataclass(frozen=True)
class FulfillmentAcceptanceDecision:
    record: Any
    newly_accepted: bool
    dispatch_required: bool

class FulfillmentTransaction(Protocol):
    db: Session
    def accept(self, *, capacity_reservation_id:str, market:str, fulfillment_request:VersionedEnvelope[Any]) -> FulfillmentAcceptanceDecision: ...
    def get_pool(self, pool_id:str) -> Any | None: ...
    def persist_prepared_create(self, capacity_reservation_id:str, prepared:VersionedEnvelope[Any]) -> Any: ...
    def acknowledge_create(self, capacity_reservation_id:str, provider_metadata:dict[str,Any]) -> Any: ...

class FulfillmentUnitOfWork(Protocol):
    @contextmanager
    def transaction(self) -> Iterator[FulfillmentTransaction]: ...

class SqlAlchemyFulfillmentTransaction:
    def __init__(self, db:Session, pool_service:ResourcePoolService, repository:SettlementRepository) -> None:
        self.db=db; self._pool_service=pool_service; self._repository=repository
    def accept(self, *, capacity_reservation_id:str, market:str, fulfillment_request:VersionedEnvelope[Any]) -> FulfillmentAcceptanceDecision:
        before=self._repository.get(self.db, capacity_reservation_id)
        was_accepted=bool(before and before.fulfillment_id)
        record=self._repository.accept_fulfillment(self.db, capacity_reservation_id=capacity_reservation_id, market=market, fulfillment_request=fulfillment_request)
        dispatch_required=(record.state == SettlementRecordState.dispatch_pending.value and not dict(record.provider_metadata or {}))
        return FulfillmentAcceptanceDecision(record, not was_accepted, dispatch_required)
    def get_pool(self, pool_id:str) -> Any | None:
        return self._pool_service.get_pool_in_session(self.db, pool_id)
    def persist_prepared_create(self, capacity_reservation_id:str, prepared:VersionedEnvelope[Any]) -> Any:
        record=self._repository.get(self.db, capacity_reservation_id)
        value=prepared.model_dump(mode='json')
        if record is None: raise LookupError(capacity_reservation_id)
        if record.prepared_create_operation is not None and record.prepared_create_operation != value:
            raise FulfillmentConflictError('accepted fulfillment already has a different prepared create operation')
        record.prepared_create_operation=value; self.db.flush(); return record
    def acknowledge_create(self, capacity_reservation_id:str, provider_metadata:dict[str,Any]) -> Any:
        record=self._repository.get(self.db, capacity_reservation_id)
        if record is None: raise LookupError(capacity_reservation_id)
        existing=dict(record.provider_metadata or {})
        incoming=dict(provider_metadata)
        if existing and existing != incoming:
            raise FulfillmentConflictError('provider submission was already acknowledged with different metadata')
        return self._repository.transition(self.db, capacity_reservation_id, SettlementRecordState.dispatching.value, provider_metadata=incoming)

class SqlAlchemyFulfillmentUnitOfWork:
    def __init__(self, session_factory:Any, pool_service:ResourcePoolService, repository:SettlementRepository|None=None, transaction_type:type[SqlAlchemyFulfillmentTransaction]=SqlAlchemyFulfillmentTransaction) -> None:
        self.session_factory=session_factory; self.pool_service=pool_service; self.repository=repository or SettlementRepository(); self.transaction_type=transaction_type
    @contextmanager
    def transaction(self) -> Iterator[FulfillmentTransaction]:
        with self.session_factory() as db:
            begin_sqlite_write_transaction(db)
            tx=self.transaction_type(db,self.pool_service,self.repository)
            try:
                yield tx; db.commit()
            except Exception:
                db.rollback(); raise
