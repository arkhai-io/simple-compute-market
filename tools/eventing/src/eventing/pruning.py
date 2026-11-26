"""Pruning: stored state retained by time, per table, never ahead of a pending delivery.

Each table has its own retention, and a table with none keeps every row. The
component's tables are named for retention by `schema.TABLES`: `events` (the
events and their references) and `deliveries` (finished deliveries, and retired
destinations with none left); a table a record-time hook writes is named as its
kind declares it.

An event is pruned only once it is past its retention, every consumer has read past
it, and each delivery of it is delivered or abandoned, or its destination is parked
or retired. A parked destination therefore does not hold an event back: one parked
longer than the events' retention receives, when resumed, only what is still
retained. A delivery of a pruned event goes with it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import ColumnClause, CursorResult, Delete, column, delete, exists, func, select, table
from sqlalchemy.orm import Session, sessionmaker

from eventing import schema
from eventing.consumers import ABANDONED, ACTIVE, DELIVERED, PENDING, RETIRED
from eventing.kinds import Catalogue


@dataclass(frozen=True)
class Retention:
    """How long each table keeps its rows; None keeps every row.

    `tables` holds the retention of each table a record-time hook writes, by the
    table's name.
    """

    events: timedelta | None = None
    deliveries: timedelta | None = None
    tables: Mapping[str, timedelta | None] = field(default_factory=dict)


@dataclass
class PruneReport:
    """How many rows one pass removed, by retention name."""

    removed: dict[str, int] = field(default_factory=dict)


class Pruner:
    """Prunes one store by its retention. Refuses, when built, a retention naming a
    table no declared kind's hook writes."""

    def __init__(
        self,
        catalogue: Catalogue,
        *,
        session_factory: sessionmaker[Session],
        retention: Retention,
        clock: Callable[[], datetime],
    ) -> None:
        hooked = {
            pruned.name: pruned
            for kind in catalogue.kinds()
            if kind.hook is not None
            for pruned in kind.hook.tables
        }
        unknown = sorted(set(retention.tables) - set(hooked))
        if unknown:
            raise ValueError(
                f"retention names {', '.join(unknown)}, which no declared kind's hook writes"
            )
        self._hooked = hooked
        self._sessions = session_factory
        self._retention = retention
        self._clock = clock

    def prune(self) -> PruneReport:
        """Remove every row past its table's retention that may go, in one transaction."""
        report = PruneReport()
        now = self._clock()
        with self._sessions.begin() as session:
            if self._retention.events is not None:
                report.removed["events"] = self._prune_events(
                    session, schema.to_stored(now - self._retention.events))
            if self._retention.deliveries is not None:
                cutoff = schema.to_stored(now - self._retention.deliveries)
                report.removed["deliveries"] = _deleted(session, delete(schema.deliveries).where(
                    schema.deliveries.c.state.in_((DELIVERED, ABANDONED)),
                    schema.deliveries.c.finished_at < cutoff,
                ))
                report.removed["retired_destinations"] = self._prune_retired(session, cutoff)
            for name, retention in sorted(self._retention.tables.items()):
                if retention is None:
                    continue
                pruned = self._hooked[name]
                stamp: ColumnClause[datetime] = column(pruned.timestamp_column)
                report.removed[name] = _deleted(session, delete(table(name, stamp)).where(
                    stamp < schema.to_stored(now - retention)))
        return report

    def _prune_retired(self, session: Session, cutoff: datetime) -> int:
        d, ds = schema.deliveries, schema.destinations
        return _deleted(session, delete(ds).where(
            ds.c.state == RETIRED,
            ds.c.state_changed_at < cutoff,
            ~exists().where(d.c.consumer == ds.c.consumer, d.c.destination == ds.c.name),
        ))

    def _prune_events(self, session: Session, cutoff: datetime) -> int:
        d, ds = schema.deliveries, schema.destinations
        # A delivery still owed to an active destination holds its event.
        owed = exists().where(
            d.c.event_sequence == schema.events.c.sequence,
            d.c.state == PENDING,
            exists().where(ds.c.consumer == d.c.consumer, ds.c.name == d.c.destination,
                           ds.c.state == ACTIVE),
        )
        condition = [schema.events.c.recorded_at < cutoff, ~owed]
        # An event a consumer has not read yet has no delivery rows, but may still be
        # selected for one of its destinations, so it is pending to them.
        lowest: int | None = session.execute(select(func.min(schema.consumers.c.position))).scalar_one()
        if lowest is not None:
            condition.append(schema.events.c.sequence <= lowest)
        sequences: list[int] = list(
            session.execute(select(schema.events.c.sequence).where(*condition)).scalars()
        )
        for start in range(0, len(sequences), 500):
            chunk = sequences[start:start + 500]
            session.execute(delete(schema.related).where(schema.related.c.event_sequence.in_(chunk)))
            session.execute(delete(d).where(d.c.event_sequence.in_(chunk)))
            session.execute(delete(schema.events).where(schema.events.c.sequence.in_(chunk)))
        return len(sequences)


def _deleted(session: Session, statement: Delete) -> int:
    result: CursorResult[tuple[()]] = session.execute(statement)  # type: ignore[assignment]
    return result.rowcount
