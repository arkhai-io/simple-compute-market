"""Narrow persistence boundary for atomic settlement scheduling.

The scheduler depends on this use-case-specific interface rather than on raw
sessions or broad repositories. Implementations may compose several DALs, but
all operations exposed by one transaction share the same database session and
commit/rollback boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from sqlalchemy.orm import Session

from market_resource_pools import ResourcePoolService
from market_site.ledger import CapacityLedgerService

from .repository import SettlementRepository, begin_sqlite_write_transaction


class SchedulingTransaction(Protocol):
    """Persistence operations that are safe inside one scheduling transaction."""

    def lock_reservation(self, capacity_reservation_id: str) -> Any | None: ...
    def reservation_payload(self, reservation: Any) -> dict[str, Any]: ...
    def get_assignment(self, capacity_reservation_id: str) -> Any | None: ...
    def schedule_assignment(self, **kwargs: Any) -> Any: ...
    def list_candidates(self, *, resource_kind: str, exclude_reservation_id: str) -> list[Any]: ...
    def list_enabled_pools(self) -> list[Any]: ...
    def load_cursor(self, resource_kind: str) -> Any: ...
    def save_cursor(self, resource_kind: str, *, last_pool_id: str | None, last_resource_by_pool: dict[str, str]) -> Any: ...
    def rebind_capacity(self, *, capacity_reservation_id: str, settlement_resource_id: str) -> None: ...


class SchedulingUnitOfWork(Protocol):
    @contextmanager
    def transaction(self) -> Iterator[SchedulingTransaction]: ...


class SqlAlchemySchedulingTransaction:
    def __init__(self, db: Session, pool_service: ResourcePoolService,
                 capacity_ledger: CapacityLedgerService,
                 repository: SettlementRepository) -> None:
        self.db = db
        self._pool_service = pool_service
        self._capacity_ledger = capacity_ledger
        self._repository = repository

    def lock_reservation(self, capacity_reservation_id: str) -> Any | None:
        return self._capacity_ledger.lock_reservation(self.db, capacity_reservation_id)

    def reservation_payload(self, reservation: Any) -> dict[str, Any]:
        return self._capacity_ledger.reservation_payload_in_session(reservation)

    def get_assignment(self, capacity_reservation_id: str) -> Any | None:
        return self._repository.get(self.db, capacity_reservation_id)

    def schedule_assignment(self, **kwargs: Any) -> Any:
        return self._repository.schedule(self.db, **kwargs)

    def list_candidates(self, *, resource_kind: str, exclude_reservation_id: str) -> list[Any]:
        return self._capacity_ledger.iter_scheduling_candidates_in_session(
            self.db, resource_kind=resource_kind,
            exclude_reservation_id=exclude_reservation_id,
        )

    def list_enabled_pools(self) -> list[Any]:
        return self._pool_service.list_pools_in_session(self.db, enabled_only=True)

    def load_cursor(self, resource_kind: str) -> Any:
        return self._repository.get_cursor_in_session(self.db, resource_kind)

    def save_cursor(self, resource_kind: str, *, last_pool_id: str | None,
                    last_resource_by_pool: dict[str, str]) -> Any:
        return self._repository.save_cursor_in_session(
            self.db, resource_kind, last_pool_id=last_pool_id,
            last_resource_by_pool=last_resource_by_pool,
        )

    def rebind_capacity(self, *, capacity_reservation_id: str,
                        settlement_resource_id: str) -> None:
        self._capacity_ledger.assign_settlement_resource_in_session(
            self.db, capacity_reservation_id=capacity_reservation_id,
            settlement_resource_id=settlement_resource_id,
        )


class SqlAlchemySchedulingUnitOfWork:
    """Open one SQLite writer transaction for the complete scheduling use case."""

    def __init__(self, session_factory: Any, pool_service: ResourcePoolService,
                 capacity_ledger: CapacityLedgerService,
                 repository: SettlementRepository | None = None,
                 transaction_type: type[SqlAlchemySchedulingTransaction] = SqlAlchemySchedulingTransaction) -> None:
        self.session_factory = session_factory
        self.pool_service = pool_service
        self.capacity_ledger = capacity_ledger
        self.repository = repository or SettlementRepository()
        self.transaction_type = transaction_type

    @contextmanager
    def transaction(self) -> Iterator[SchedulingTransaction]:
        with self.session_factory() as db:
            begin_sqlite_write_transaction(db)
            tx = self.transaction_type(db, self.pool_service, self.capacity_ledger, self.repository)
            try:
                yield tx
                db.commit()
            except Exception:
                db.rollback()
                raise
