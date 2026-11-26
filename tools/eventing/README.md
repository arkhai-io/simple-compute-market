# eventing

One eventing system per service: declared kinds of event, recorded in the
producer's own database transaction, and delivered in order to each destination of
each named consumer, each delivery retried until it succeeds or is abandoned. Every
outbox, notification or peer delivery a service runs is a consumer of it rather than a mechanism of its own.

The component (distribution `arkhai-eventing`, import `eventing`) depends on the
standard library, SQLAlchemy 2, pydantic 2 and sqlglot, and on nothing else. It
works through a service's own SQLAlchemy sessions, its DDL and statements written
for SQLite and PostgreSQL alike; its own suite runs on SQLite. This README is its
interface.

## The envelope

Every event carries one envelope, which a consumer reads without knowing the kind:

```json
{
  "envelope_version": 1,
  "id": "01JDX9R6Q7Z3K2W8P4M5N6B7C8",
  "kind": "orders.shipment_delayed",
  "kind_version": 1,
  "data_schema": "urn:event:orders.shipment_delayed:1",
  "source": {"service": "orders", "instance": "eu-1"},
  "sequence": 48213,
  "occurred_at": "2026-11-25T17:42:10Z",
  "severity": "action_required",
  "subject": {"type": "shipment", "id": "sh-9e0d"},
  "related": [{"type": "order", "id": "o-7f3a"}, {"type": "depot", "id": "d-02"}],
  "correlation_id": "o-7f3a",
  "causation_id": null,
  "attributes": {"carrier": "rail", "delay_minutes": 95},
  "summary": "Shipment sh-9e0d is 95 minutes late at depot d-02.",
  "details": {"reason": "missed connection"},
  "extensions": {}
}
```

- `id` is a ULID, the event's stable identity; every delivery of the event carries it.
- `sequence` orders the events of one store (see "Recording").
- `severity` is `info` < `warning` < `action_required`; `Severity.rank` and
  `severity_rank()` give 0, 1 and 2.
- `attributes` hold scalars only: strings, integers, floats, booleans and null.
- `details` hold what a reader of that kind wants, following its `kind_version`, and
  only what may leave the service: sinks receive the whole envelope.

The envelope evolves by addition: a field is only ever added, as optional; a reader
ignores fields it does not know and keeps `extensions` unchanged without
interpreting them; `envelope_version` changes only with an incompatible change. A
kind's `details` change incompatibly only with a new `kind_version`, and a reader
reads the version before the details: `Catalogue.decode_details` decodes them only
for the version declared, and a reader meeting another version routes and renders
the event from its envelope alone.

## Kinds and the catalogue

A kind is declared before any event of it is recorded:

```python
class Delay(BaseModel):
    reason: str

SHIPMENT_DELAYED = Kind(
    name="orders.shipment_delayed",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=Delay,
    attributes={"carrier": str, "delay_minutes": int},
    dedup_key=("subject", "attributes.delay_minutes"),
    summary=lambda draft, details: f"Shipment {draft.subject.id} is late: {details.reason}.",
)
catalogue = Catalogue([SHIPMENT_DELAYED], schema_prefix="urn:event")
```

- `attributes` declares each attribute's type: `str`, `int`, `float` or `bool`. An
  attribute may not share an envelope column's name, and two kinds declaring one
  attribute name declare it with one type, since a route reads it as one column.
- `dedup_key` names the fields identifying one occurrence: `subject`,
  `correlation_id`, `causation_id`, `attributes.<name>`, `details.<field>`, or
  `related.<type>` (the identifier of the related reference of that type). An empty
  key makes every event its own occurrence.
- `summary` renders the line a person reads, from the draft and its validated details.
- `hook`, a `RecordHook`, is optional work done in the recording transaction with the
  event as recorded; `RecordHook.tables` names each table it writes, the column its
  rows are pruned by, and optionally the column holding the `id` of the event that
  wrote each row (`PrunedTable(name, timestamp_column, event_column=...)`), which
  keeps a row while its event is.

`Catalogue.kinds()` lists every declared kind. The catalogue refuses a second kind
of one name, and a declaration whose attributes or key cannot be routed or resolved
(`KindRefused`).

## Recording

```python
recorder = Recorder(catalogue, source=Source(service="orders", instance="eu-1"), clock=now)
with sessions.begin() as session:
    ...  # the state change the event reports
    recorder.record(session, SHIPMENT_DELAYED.draft(
        subject=Reference(type="shipment", id="sh-9e0d"),
        details={"reason": "missed connection"},
        attributes={"carrier": "rail", "delay_minutes": 95},
        related=[Reference(type="order", id="o-7f3a")],
    ))
```

`record` writes through the producer's session, so the event commits or rolls back
with the state change it reports, and runs the kind's hook in the same transaction;
a hook that raises rolls the transaction back. A draft (`EventDraft`) can be
prepared by one component and recorded by another that does not know its kind.

The recorder refuses, writing nothing, a draft of an undeclared kind
(`EventRefused`, code `undeclared_kind`), an attribute undeclared or of another type
(`invalid_attributes`), or details failing the kind's model (`invalid_details`). An
occurrence already recorded is not written again: `record` returns the existing
event and runs no hook.

`sequence` is allocated from one counter row updated in the producer's transaction,
whose lock is held until that transaction ends, so no event commits with a lower
sequence than one already visible, and a consumer that has read every event up to a
sequence has missed none below it. A repeated occurrence leaves a gap, which no
reader depends on. On PostgreSQL, transactions recording events queue on the row
from their record call to their commit.

`clock` is the process's source of the time of the world, returning an aware
datetime: it stamps `occurred_at` when a draft gives none, and the recording time
retention counts from.

## Consumers

```python
consumer = Consumer(
    "notifications",
    session_factory=sessions,
    destinations={"ops-mail": mail, "ops-chat": chat},
    select=routes.select,            # (envelope, candidates); by default every candidate
    retry=RetryPolicy(max_age=timedelta(days=1)),
    finally_sink=LogFinallySink(),   # the default
    clock=now,
    runner="worker-0",               # unique to the instance by default
    hold=timedelta(minutes=5),       # the default
)
consumer.run_cycle()
```

A `Destination` has one method, `deliver(envelope)`: it returns once the event is
delivered, raises to fail the attempt, raises `AbandonDelivery(reason)` to refuse
this one delivery outright, and raises `ParkDestination(reason)` to park itself. A
selection (`Selection`) is called with the event and the candidate destinations —
those not retired and added before the event — and names the ones it goes to. A consumer holds a durable position and, for each destination, a state —
`active`, `parked` or `retired` — and a delivery per event selected for it,
`pending`, `delivered` or `abandoned`, with its attempts and last error.

`run_cycle()` registers the consumer and its destinations, reads every event past
the position into pending deliveries, then delivers what is due:

- Each destination receives its events in `sequence` order, at least once until a
  delivery is abandoned or pruned while its destination is parked (below), under the
  event's `id`: a delivery whose outcome was not recorded — the process stopped after
  delivering — is delivered again. A failed delivery is retried after the policy's
  backoff, doubling from `initial` to `maximum`, and the destination's later events
  wait behind it; another destination is not held up.
- A new consumer starts at the latest event. A consumer with no destination still
  reads each event, advancing its position, and the destinations it first has start
  at its position whenever they are added. Once a consumer has had destinations, a
  change to
  them takes effect at the latest committed event: the cycle first reads every
  committed event with the destinations as stored, then adds each new destination,
  which receives no event committed before it, and retires each departing one.
- A parked destination receives nothing until it is resumed (`Consumer.resume`, or
  `EventService.resume`); resuming delivers, in order, its pending events still
  retained. `Consumer.park` parks one explicitly.
- A stored destination absent from the consumer's configuration is retired: each event
  still pending to it, those just read for it included, is marked abandoned and
  handed to the finally sink, and nothing more is selected for it. A name configured
  again starts afresh at the position.
- A delivery its destination refuses with `AbandonDelivery` is abandoned at once,
  keeping the refusal as its last error, and the event goes to the finally sink; the
  destination's next delivery follows.
- With `RetryPolicy.max_age`, a delivery that fails once older than that is
  abandoned, keeping its last error, and the event goes to the finally sink. With
  none, a delivery is retried without limit.
- One runner holds a named consumer at a time. A cycle, and `register()`, `read()`
  and `deliver()` each run alone, first take the consumer's hold — its holder,
  `runner`, and an expiry `hold` ahead, stored on the consumer's row — or do nothing,
  reporting `held_elsewhere`, while another runner holds it unexpired. Every
  transaction of the cycle renews the hold and applies nothing once another runner has
  taken it, and the cycle releases the hold when it ends. A `Consumer` also runs one
  cycle at a time, a second started meanwhile doing nothing, so neither two processes
  nor a timer's cycle and a manual one deliver to a destination together. A runner that stops holding it leaves the hold to lapse: `hold` is longer than any
  delivery attempt, since a runner still inside a destination's call when its hold
  lapses loses the consumer once another runner takes it, records no outcome, and that
  runner delivers the event again under its `id`.
- Taking, renewing and releasing the hold are writes, so every cycle writes, an idle
  one included. On SQLite, whose writers wait for one another, a cycle waits behind an
  open producer transaction, up to the connection's busy timeout.
- Retries are scheduled, ages measured, and the hold's expiry kept in the time of the
  world `clock` reads, since the schedule and the hold are stored, outlive the process
  and are compared by other runners: where that time is held, a retry comes due, and a
  stopped runner's hold lapses, only when it is moved forward. A `runner` identity
  stable across restarts — the process's instance name — lets a restarted process take
  its own hold back at once; two processes given one identity are not kept apart.

The finally sink (`FinallySink.abandoned`) defaults to the log: a warning on the
`eventing.finally` logger carrying the event's envelope and last error.

## Routes

A route selects events with an SQL condition, which sqlglot parses and evaluates
with its own executor:

```python
routes = Routes(
    [Route("late-rail", "kind = 'orders.shipment_delayed' AND carrier = 'rail'", ("ops-chat",)),
     Route("depot-d02", "id IN (SELECT event_id FROM related WHERE type = 'depot' AND id = 'd-02')",
           ("ops-mail",))],
    catalogue,
    enabled={"ops-mail", "ops-chat"},
)
routes.select(envelope)  # the destinations of every route selecting the event
```

A condition reads one event as the one-row table `event` and its references as the
table `related` (`event_id`, `type`, `id`). The columns of `event` are the
envelope's scalar fields — `envelope_version`, `id`, `kind`, `kind_version`,
`data_schema`, `source_service`, `source_instance`, `sequence`, `occurred_at` (ISO
8601 UTC text), `severity`, `severity_rank`, `subject_type`, `subject_id`,
`correlation_id`, `causation_id`, `summary` — and every attribute a declared kind
declares, NULL where the event does not carry it.

Building `Routes` refuses a route (`RouteRefused`, naming it) whose condition holds
anything but comparisons, `AND`, `OR`, `NOT`, `IN`, `LIKE`, `IS NULL`, literals and
subqueries over `related`; that names a column neither the envelope nor a declared
kind has; or that names a destination not enabled. Correlated subqueries read the
event's columns qualified as `event.<column>`.

## Retention

```python
pruner = Pruner(catalogue, session_factory=sessions, clock=now, retention=Retention(
    events=timedelta(days=30), deliveries=timedelta(days=30),
    tables={"shipment_notices": None},  # a hook's table; None keeps every row
))
pruner.prune()
```

Each table is retained for its own time: `events` (the events and their
references), `deliveries` (finished deliveries, and retired destinations with none
left, though a consumer keeps its latest destination row), and each table a
record-time hook writes, by its name. A table whose retention is `None` keeps every
row. A hook's row whose table names
an event column is kept, whatever its own retention, while its event is, so no
retained event refers to a pruned row; one whose column is empty goes by time alone. An event is pruned only once it is past its retention, every consumer has
read past it, and each of its deliveries is delivered or abandoned, or its
destination is parked or retired. A parked destination does not hold an event back,
so one parked longer than the events' retention receives, on resume, only what is
still retained. A consumer that is not run holds the events past its position,
which it has not read. `Pruner` refuses a retention naming a table no declared
kind's hook writes.

## Reads and the status service

`EventReader.events` reads events by kind, severity, subject and related reference,
in sequence order, past a sequence. `EventReader.destinations` reads each consumer's
destinations: state, position, deliveries by state, and the earliest pending one.

`EventService` is the framework-free service a process binds behind its own
authentication; it answers JSON-ready dictionaries and refuses with
`EventServiceError` (status, code, detail):

| Method | Answers | Refuses |
|---|---|---|
| `list_events(kind, severity, subject, reference, after, limit)` | `{"events": [...], "next_after": n}`; `subject` and `reference` as `<type>:<id>` | 422 `invalid_query` |
| `deliveries()` | `{"destinations": [...]}` | — |
| `resume(destination, consumer=None)` | `{"consumer", "destination", "state": "active"}` | 404 `unknown_destination`, 409 `ambiguous_destination`, 409 `destination_retired` |

## Schema

The component owns no migration engine. `SCHEMA_STEPS` holds one `SchemaStep` per
schema version, fixed DDL a service's migration chain applies in order, each under
its `name` (`eventing_0001`, …) and through `apply(connection)`. A released step is
never edited; a later change to the tables is a further step. The tables are
`eventing_events`, `eventing_related`, `eventing_sequence`, `eventing_consumers`,
`eventing_destinations` and `eventing_deliveries`, described by `metadata`.

## Development

- `make test` type-checks the package and runs its unit tests, the structure test
  holding its boundary among them, and its library-integration tests over real SQLite
  files.
- `make build` builds its wheel into its own `dist/`, or into `DIST_DIR`.
