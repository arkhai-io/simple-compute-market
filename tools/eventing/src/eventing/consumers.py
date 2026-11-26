"""Consumers: each event delivered at least once to each of a consumer's destinations.

A named consumer holds a durable position — the highest sequence it has read — and,
for each of its destinations, a state (`active`, `parked` or `retired`) and one
delivery row per event selected for it: `pending`, `delivered` or `abandoned`, with
its attempt count and last error. A cycle does three things, each in its own
transactions:

1. **Registers** the consumer and its configured destinations. A new consumer starts
   at the latest event, and the destinations it is first registered with at its
   position. Once a consumer has had destinations, a change to them takes effect at
   the latest committed event: the cycle first reads every committed event with the
   destinations as stored, then adds each new destination there — so it receives no
   event recorded before it — and retires each stored destination absent from the
   configuration: each delivery still pending to it, those just read included, is
   abandoned to the finally sink, and nothing more is selected for it.
2. **Reads** every event past the position, in sequence order, writes a pending
   delivery for each destination its selection names among those not retired and
   added before the event, and advances the position. The recorder's sequence
   allocation means no event can later commit below the position.
3. **Delivers**, destination by destination, each pending delivery in sequence order,
   outside any transaction, then records the outcome. A delivery that fails is retried
   after a backoff, and the destination's later events wait behind it; another
   destination is not held up. A delivery whose outcome was never recorded — the
   process stopped after delivering — is delivered again under the same event `id`,
   so a destination sees each event at least once.

One runner holds a named consumer at a time. A cycle — and each of the three phases
run on its own — first takes the consumer's hold, a holder and an expiry stored on
the consumer's row, or does nothing when another runner holds it unexpired; every
transaction of the cycle renews the hold, and applies nothing once another runner
has taken it, so a delivery's outcome is recorded only by the runner still holding
the consumer. A `Consumer` runs one cycle at a time: a cycle started while another of
the same instance runs does nothing. Two processes, or two cycles of one instance,
therefore never deliver to a destination together; a runner identity names one
process, and two instances given one identity are not kept apart. A runner that
stops holding it leaves the hold to lapse, so the hold is longer than any delivery
attempt: a holder still inside a destination's call when its hold lapses loses the
consumer once another runner takes it, records no outcome, and that runner delivers
the event again under the same `id`.

A destination parks itself by raising `ParkDestination`, or is parked explicitly;
nothing is delivered to it until it is resumed, and resuming delivers, in order, the
pending events still retained. A destination that can never take one delivery — a
receiver refusing that event outright, say — raises `AbandonDelivery`: that delivery
is abandoned to the finally sink and the destination's next one follows. A
consumer's retry policy may bound a delivery's retries by a maximum age: a delivery
that fails once older than that is abandoned, keeping its last error, and the event
is handed to the finally sink.

Retries are scheduled, a delivery's age measured, and the hold's expiry kept in the
time of the world the consumer's clock reads, not on the monotonic clock: the
schedule and the hold are stored, outlive the process and are compared by other
runners. Where that time is held, a retry comes due, and a stopped runner's hold
lapses, only when it is moved forward; a runner identity stable across restarts lets
a restarted process take its own hold back at once.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import ColumnElement, CursorResult, and_, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from eventing import schema
from eventing.envelope import Envelope

ACTIVE = "active"
PARKED = "parked"
RETIRED = "retired"

PENDING = "pending"
DELIVERED = "delivered"
ABANDONED = "abandoned"

RETIRED_ERROR = "destination retired: not configured"

logger = logging.getLogger(__name__)

DEFAULT_HOLD = timedelta(minutes=5)
"""How long a runner holds a consumer past its latest transaction."""


class _HoldLost(Exception):
    """Another runner took the consumer: the transaction raising it rolls back."""


class ParkDestination(Exception):
    """Raised by a destination that must receive nothing more until it is resumed —
    a receiver answering that it does not support the delivery, say. The message is
    the reason, kept as the delivery's last error and the destination's state reason."""


class AbandonDelivery(Exception):
    """Raised by a destination that can never take this one delivery — a receiver
    refusing the event itself rather than failing for the moment. The delivery is
    abandoned, the message kept as its last error, and the event handed to the
    finally sink; the destination's next delivery follows."""


class Destination(Protocol):
    """Where a consumer delivers. `deliver` returns once the event is delivered, and
    raises to fail the attempt, `AbandonDelivery` to abandon this delivery, or
    `ParkDestination` to park the destination."""

    def deliver(self, envelope: Envelope) -> None: ...


class FinallySink(Protocol):
    """Where an abandoned delivery's event goes."""

    def abandoned(
        self, *, consumer: str, destination: str, envelope: Envelope, last_error: str | None
    ) -> None: ...


class LogFinallySink:
    """The default finally sink: the event and its last error, logged as a warning."""

    def __init__(self, log: logging.Logger | None = None) -> None:
        self._log = log or logging.getLogger("eventing.finally")

    def abandoned(
        self, *, consumer: str, destination: str, envelope: Envelope, last_error: str | None
    ) -> None:
        self._log.warning(
            "delivery abandoned: consumer=%s destination=%s event=%s last_error=%s envelope=%s",
            consumer, destination, envelope.id, last_error, envelope.to_json(),
        )


@dataclass(frozen=True)
class RetryPolicy:
    """How a consumer retries a failed delivery: a backoff doubling from `initial`
    to at most `maximum`, and an optional `max_age` past which a failing delivery is
    abandoned. With no `max_age`, a delivery is retried without limit."""

    initial: timedelta = timedelta(seconds=10)
    maximum: timedelta = timedelta(hours=1)
    max_age: timedelta | None = None

    def delay(self, attempts: int) -> timedelta:
        """The wait before the attempt after `attempts` failed ones."""
        delay: timedelta = min(self.initial * (2 ** max(attempts - 1, 0)), self.maximum)
        return delay


@dataclass
class CycleReport:
    """What one consumer cycle did."""

    read: int = 0
    selected: int = 0
    delivered: int = 0
    failed: int = 0
    parked: list[str] = field(default_factory=list)
    abandoned: int = 0
    retired: list[str] = field(default_factory=list)
    held_elsewhere: bool = False
    """Another runner held the consumer, or another cycle of this instance was
    running, so the cycle did nothing; or another runner took the consumer during
    the cycle, which then stopped without applying its pending outcome."""


Selection = Callable[[Envelope, frozenset[str]], Collection[str]]
"""Names the destinations an event goes to, among the candidates given: those not
retired and added before the event, which may include a stored destination the
configuration no longer names while a change to the destinations takes effect."""


def _all(envelope: Envelope, candidates: frozenset[str]) -> Collection[str]:
    return candidates


class Consumer:
    """One named consumer over one store.

    `select` names the destinations an event goes to among the candidates it is
    given; by default, every candidate. `clock` reads the time of the world as an
    aware datetime, against which retries are scheduled, a delivery's age is
    measured and the hold kept.
    `runner` names this runner as the hold's holder, unique to the instance by
    default; a name given is one process's, stable across its restarts. `hold` is how
    long it holds the consumer past each transaction, longer than any delivery
    attempt.
    """

    def __init__(
        self,
        name: str,
        *,
        session_factory: sessionmaker[Session],
        destinations: Mapping[str, Destination],
        clock: Callable[[], datetime],
        retry: RetryPolicy | None = None,
        select: Selection | None = None,
        finally_sink: FinallySink | None = None,
        batch_size: int = 100,
        runner: str | None = None,
        hold: timedelta = DEFAULT_HOLD,
    ) -> None:
        self.name = name
        self._sessions = session_factory
        self._destinations = dict(destinations)
        self._clock = clock
        self._retry = retry or RetryPolicy()
        self._select = select or _all
        self._finally = finally_sink or LogFinallySink()
        self._batch_size = batch_size
        self.runner = runner or uuid4().hex
        self._hold = hold
        self._running = threading.Lock()

    def run_cycle(self) -> CycleReport:
        """Register, read past the position, and deliver what is due, holding the
        consumer's hold throughout."""
        return self._held(self._register, self._read, self._deliver)

    def register(self, report: CycleReport | None = None) -> CycleReport:
        """Record the consumer and its configured destinations, retiring each stored
        destination absent from the configuration, under the consumer's hold. A
        change to destinations a consumer already has first reads every committed
        event past the position, as a cycle's read does, so the change takes effect
        at the latest committed event."""
        return self._held(self._register, report=report)

    def read(self, report: CycleReport | None = None) -> CycleReport:
        """Write a pending delivery of each event past the position for each
        destination selected for it, advancing the position past every event read,
        under the consumer's hold."""
        return self._held(self._read, report=report)

    def deliver(self, report: CycleReport | None = None) -> CycleReport:
        """Attempt each active destination's due deliveries, in sequence order, under
        the consumer's hold."""
        return self._held(self._deliver, report=report)

    def _held(
        self, *phases: Callable[[CycleReport], None], report: CycleReport | None = None
    ) -> CycleReport:
        """Run `phases` in order while this runner holds the consumer, releasing it
        after; with another runner holding it, or another cycle of this instance
        running, run nothing."""
        report = report if report is not None else CycleReport()
        if not self._running.acquire(blocking=False):
            report.held_elsewhere = True
            return report
        try:
            if not self._acquire():
                report.held_elsewhere = True
                return report
            try:
                for phase in phases:
                    phase(report)
            except _HoldLost:
                report.held_elsewhere = True
            except BaseException:
                self._release_quietly()
                raise
            self._release()
            return report
        finally:
            self._running.release()

    def _acquire(self) -> bool:
        """Take the consumer's hold if it is free, lapsed or already this runner's,
        registering a new consumer at the latest event."""
        now = self._clock()
        values = {"held_by": self.runner,
                  "held_until": schema.to_stored(now + self._hold)}
        try:
            with self._sessions.begin() as session:
                known = session.execute(
                    select(schema.consumers.c.name).where(schema.consumers.c.name == self.name)
                ).first()
                if known is None:
                    latest: int | None = session.execute(
                        select(func.max(schema.events.c.sequence))
                    ).scalar_one()
                    session.execute(
                        insert(schema.consumers).values(
                            name=self.name, position=int(latest or 0),
                            created_at=schema.to_stored(now), **values,
                        )
                    )
                    return True
                taken: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
                    update(schema.consumers)
                    .where(
                        schema.consumers.c.name == self.name,
                        or_(schema.consumers.c.held_by.is_(None),
                            schema.consumers.c.held_by == self.runner,
                            schema.consumers.c.held_until <= schema.to_stored(now)),
                    )
                    .values(**values)
                )
                return taken.rowcount == 1
        except IntegrityError:
            # Another runner registered the consumer first; this cycle leaves it to
            # that runner.
            return False

    def _renew(self, session: Session, now: datetime) -> None:
        """Extend this runner's hold in `session`'s transaction, or raise
        `_HoldLost` when another runner has taken the consumer."""
        renewed: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
            update(schema.consumers)
            .where(schema.consumers.c.name == self.name,
                   schema.consumers.c.held_by == self.runner)
            .values(held_until=schema.to_stored(now + self._hold))
        )
        if renewed.rowcount == 0:
            raise _HoldLost

    def _release_quietly(self) -> None:
        """Release the hold while another error propagates, logging a failure to
        release rather than replacing that error; the hold then lapses."""
        try:
            self._release()
        except Exception:
            logger.exception("consumer %s: could not release its hold", self.name)

    def _release(self) -> None:
        with self._sessions.begin() as session:
            session.execute(
                update(schema.consumers)
                .where(schema.consumers.c.name == self.name,
                       schema.consumers.c.held_by == self.runner)
                .values(held_by=None, held_until=None)
            )

    def _register(self, report: CycleReport) -> None:
        while True:
            clock_now = self._clock()
            now = schema.to_stored(clock_now)
            with self._sessions.begin() as session:
                self._renew(session, clock_now)
                position = self._position(session)
                stored: dict[str, str] = {
                    row.name: row.state
                    for row in session.execute(
                        select(schema.destinations.c.name, schema.destinations.c.state).where(
                            schema.destinations.c.consumer == self.name
                        )
                    )
                }
                receiving = {name for name, state in stored.items() if state != RETIRED}
                if stored and receiving != set(self._destinations):
                    latest = int(session.execute(
                        select(func.coalesce(func.max(schema.events.c.sequence), 0))
                    ).scalar_one())
                    if latest > position:
                        # The change takes effect at the latest committed event: the
                        # events before it go to the destinations as stored.
                        unread = True
                    else:
                        unread = False
                        self._apply_destinations(session, stored, position, now, report)
                else:
                    unread = False
                    self._apply_destinations(session, stored, position, now, report)
            if not unread:
                return
            self._read(report)

    def _apply_destinations(
        self,
        session: Session,
        stored: Mapping[str, str],
        position: int,
        now: datetime,
        report: CycleReport,
    ) -> None:
        """Add each configured destination not stored, or retired, at `position`, and
        retire each stored destination the configuration does not name."""
        for name in sorted(self._destinations):
            if name not in stored:
                session.execute(
                    insert(schema.destinations).values(
                        consumer=self.name, name=name, state=ACTIVE,
                        added_at_position=position, added_at=now, state_changed_at=now,
                    )
                )
            elif stored[name] == RETIRED:
                # Configured again after retirement: a new destination, starting
                # at the current position.
                session.execute(
                    update(schema.destinations)
                    .where(self._destination(name))
                    .values(state=ACTIVE, added_at_position=position,
                            added_at=now, state_changed_at=now, state_reason=None)
                )
        for name in sorted(set(stored) - set(self._destinations)):
            if stored[name] != RETIRED:
                report.abandoned += self._retire(session, name, now)
                report.retired.append(name)

    def _read(self, report: CycleReport) -> None:
        while True:
            with self._sessions.begin() as session:
                clock_now = self._clock()
                self._renew(session, clock_now)
                now = schema.to_stored(clock_now)
                position = self._position(session)
                receiving: dict[str, int] = {
                    row.name: int(row.added_at_position)
                    for row in session.execute(
                        select(schema.destinations.c.name,
                               schema.destinations.c.added_at_position).where(
                            schema.destinations.c.consumer == self.name,
                            schema.destinations.c.state != RETIRED,
                        )
                    )
                }
                rows = session.execute(
                    select(schema.events.c.sequence, schema.events.c.envelope)
                    .where(schema.events.c.sequence > position)
                    .order_by(schema.events.c.sequence)
                    .limit(self._batch_size)
                ).all()
                if not rows:
                    return
                for row in rows:
                    sequence: int = row.sequence
                    raw = row.envelope
                    candidates = frozenset(
                        name for name, added in receiving.items() if added < sequence)
                    chosen = candidates & set(
                        self._select(Envelope.from_json(str(raw)), candidates))
                    for destination in sorted(chosen):
                        session.execute(
                            insert(schema.deliveries).values(
                                consumer=self.name, destination=destination,
                                event_sequence=sequence, state=PENDING, attempts=0,
                                created_at=now, next_attempt_at=now,
                            )
                        )
                    report.selected += len(chosen)
                report.read += len(rows)
                session.execute(
                    update(schema.consumers)
                    .where(schema.consumers.c.name == self.name)
                    .values(position=rows[-1][0])
                )

    def _deliver(self, report: CycleReport) -> None:
        for name in sorted(self._destinations):
            self._deliver_to(name, report)

    def park(self, destination: str, reason: str) -> None:
        """Park `destination`: nothing is delivered to it until it is resumed."""
        with self._sessions.begin() as session:
            park_destination(session, self.name, destination, reason, self._clock())

    def resume(self, destination: str) -> None:
        """Resume `destination`, delivering, in order, its pending events still retained."""
        with self._sessions.begin() as session:
            resume_destination(session, self.name, destination, self._clock())

    def _deliver_to(self, name: str, report: CycleReport) -> None:
        destination = self._destinations[name]
        while True:
            now = self._clock()
            with self._sessions.begin() as session:
                self._renew(session, now)
                state: str = session.execute(
                    select(schema.destinations.c.state).where(self._destination(name))
                ).scalar_one()
                if state != ACTIVE:
                    return
                due = session.execute(
                    select(
                        schema.deliveries.c.event_sequence,
                        schema.deliveries.c.attempts,
                        schema.deliveries.c.created_at,
                        schema.deliveries.c.next_attempt_at,
                        schema.events.c.envelope,
                    )
                    .join(schema.events,
                          schema.events.c.sequence == schema.deliveries.c.event_sequence)
                    .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
                    .order_by(schema.deliveries.c.event_sequence)
                    .limit(1)
                ).first()
            # The head of the destination's queue holds the rest back until it is
            # delivered or abandoned, so the destination receives events in order.
            if due is None or schema.from_stored(due.next_attempt_at) > now:
                return
            envelope = Envelope.from_json(due.envelope)
            attempts = due.attempts + 1
            try:
                destination.deliver(envelope)
            except ParkDestination as parked:
                with self._sessions.begin() as session:
                    self._renew(session, self._clock())
                    self._attempted(session, name, due.event_sequence, attempts, now,
                                    last_error=str(parked))
                    park_destination(session, self.name, name, str(parked), now)
                report.parked.append(name)
                return
            except AbandonDelivery as refused:
                with self._sessions.begin() as session:
                    self._renew(session, self._clock())
                    self._attempted(session, name, due.event_sequence, attempts, now,
                                    last_error=str(refused), state=ABANDONED)
                    self._finally.abandoned(consumer=self.name, destination=name,
                                            envelope=envelope, last_error=str(refused))
                report.abandoned += 1
                continue
            except Exception as error:  # a destination's failure is any exception
                last_error = f"{type(error).__name__}: {error}"
                age = now - schema.from_stored(due.created_at)
                with self._sessions.begin() as session:
                    self._renew(session, self._clock())
                    if self._retry.max_age is not None and age >= self._retry.max_age:
                        self._attempted(session, name, due.event_sequence, attempts, now,
                                        last_error=last_error, state=ABANDONED)
                        self._finally.abandoned(consumer=self.name, destination=name,
                                                envelope=envelope, last_error=last_error)
                        report.abandoned += 1
                        continue
                    self._attempted(session, name, due.event_sequence, attempts, now,
                                    last_error=last_error,
                                    next_attempt_at=now + self._retry.delay(attempts))
                report.failed += 1
                return
            with self._sessions.begin() as session:
                self._renew(session, self._clock())
                self._attempted(session, name, due.event_sequence, attempts, now,
                                state=DELIVERED)
            report.delivered += 1

    def _attempted(
        self,
        session: Session,
        destination: str,
        sequence: int,
        attempts: int,
        now: datetime,
        *,
        last_error: str | None = None,
        state: str = PENDING,
        next_attempt_at: datetime | None = None,
    ) -> None:
        values: dict[str, object] = {
            "attempts": attempts,
            "last_attempted_at": schema.to_stored(now),
            "state": state,
        }
        if last_error is not None:
            values["last_error"] = last_error
        if state != PENDING:
            values["finished_at"] = schema.to_stored(now)
        if next_attempt_at is not None:
            values["next_attempt_at"] = schema.to_stored(next_attempt_at)
        session.execute(
            update(schema.deliveries)
            .where(self._deliveries(destination),
                   schema.deliveries.c.event_sequence == sequence)
            .values(**values)
        )

    def _position(self, session: Session) -> int:
        """The consumer's position, registered when this runner took its hold."""
        position: int = session.execute(
            select(schema.consumers.c.position).where(schema.consumers.c.name == self.name)
        ).scalar_one()
        return int(position)

    def _retire(self, session: Session, name: str, now: datetime) -> int:
        pending = session.execute(
            select(schema.deliveries.c.event_sequence, schema.deliveries.c.last_error,
                   schema.events.c.envelope)
            .join(schema.events, schema.events.c.sequence == schema.deliveries.c.event_sequence)
            .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
            .order_by(schema.deliveries.c.event_sequence)
        ).all()
        session.execute(
            update(schema.deliveries)
            .where(self._deliveries(name), schema.deliveries.c.state == PENDING)
            .values(state=ABANDONED, finished_at=now,
                    last_error=func.coalesce(schema.deliveries.c.last_error, RETIRED_ERROR))
        )
        session.execute(
            update(schema.destinations)
            .where(self._destination(name))
            .values(state=RETIRED, state_changed_at=now, state_reason=RETIRED_ERROR)
        )
        # Handed over inside the transaction: if the finally sink fails, the
        # retirement rolls back and is attempted again, so no event is lost.
        for row in pending:
            self._finally.abandoned(
                consumer=self.name, destination=name,
                envelope=Envelope.from_json(row.envelope),
                last_error=row.last_error or RETIRED_ERROR,
            )
        return len(pending)

    def _destination(self, name: str) -> ColumnElement[bool]:
        return and_(schema.destinations.c.consumer == self.name, schema.destinations.c.name == name)

    def _deliveries(self, destination: str) -> ColumnElement[bool]:
        return and_(schema.deliveries.c.consumer == self.name,
                    schema.deliveries.c.destination == destination)


class UnknownDestination(LookupError):
    """No destination of that name is registered for the consumer."""


def park_destination(session: Session, consumer: str, destination: str, reason: str,
                     now: datetime) -> None:
    """Park `consumer`'s `destination` in `session`'s transaction."""
    result: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
        update(schema.destinations)
        .where(schema.destinations.c.consumer == consumer,
               schema.destinations.c.name == destination,
               schema.destinations.c.state != RETIRED)
        .values(state=PARKED, state_changed_at=schema.to_stored(now), state_reason=reason)
    )
    if result.rowcount == 0:
        raise UnknownDestination(f"consumer {consumer} has no destination {destination}")


def resume_destination(session: Session, consumer: str, destination: str, now: datetime) -> None:
    """Resume `consumer`'s parked `destination` in `session`'s transaction: its
    pending deliveries become due at once. Resuming an active destination changes
    nothing."""
    stored = schema.to_stored(now)
    result: CursorResult[tuple[()]] = session.execute(  # type: ignore[assignment]
        update(schema.destinations)
        .where(schema.destinations.c.consumer == consumer,
               schema.destinations.c.name == destination,
               schema.destinations.c.state == PARKED)
        .values(state=ACTIVE, state_changed_at=stored, state_reason=None)
    )
    if result.rowcount:
        session.execute(
            update(schema.deliveries)
            .where(schema.deliveries.c.consumer == consumer,
                   schema.deliveries.c.destination == destination,
                   schema.deliveries.c.state == PENDING)
            .values(next_attempt_at=stored)
        )
