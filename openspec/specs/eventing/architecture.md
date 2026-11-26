# Eventing Architecture

The [normative contract](spec.md) states what the eventing component guarantees: the
envelope, declared kinds, recording in the producer's transaction, one occurrence
per key, delivery to each destination in order and at least once until a delivery is
delivered or abandoned, park and resume, the finally sink, routes, and retention. This document explains the component's model —
how an event travels from the transaction that records it to each destination of
each consumer — why each part works as it does, and why the component is built here
and stands alone. Its [README](../../../tools/eventing/README.md) is its interface;
the rules a service follows when it reports its state changes are
[`eventing.md`](../../../docs/guidance/engineering/eventing.md).

## One eventing system per service

A service has one eventing system: its producers record events, and every outbox,
notification or peer delivery it runs is a consumer of that system rather than a
mechanism of its own per event type
([`eventing.md`, "A service has one eventing system"](../../../docs/guidance/engineering/eventing.md#a-service-has-one-eventing-system)).
The component, `tools/eventing` (distribution `arkhai-eventing`, import `eventing`),
is that system's core: the envelope, kind declarations and the catalogue, the
recorder, the tables and their schema steps, consumers with per-destination state,
routes, retention, and a read and status service. Anything that knows what an event
means — which kinds exist, what a destination does with one — is the composing
service's.

The compute provisioning service, `provisioning/compute/service`, composes it. It
builds one catalogue of the site's kinds (declared in `kit/site`'s
`market_site.events`) and compute provisioning's (`compute_provisioning.operator_events`),
one recorder injected into the site ledger, the job engine and, through the site's
failing transition, the lease lifecycle, and the component's schema steps in its own
migration chain. Three consumers read its events: the signed lease-end report's
delivery to the storefront peer, the capacity-released callback, and `kit/delivery`'s
event-sink consumer (`market_delivery.event_sinks`), which hands each event its routes
select to the operator's sinks. Which kinds the service records, and what each
consumer does, are
[physical provisioning's](../physical-provisioning/spec.md),
[site capacity's](../site-capacity/spec.md) and
[introduction delivery's](../introduction-delivery/spec.md) contracts.

```text
producer's transaction ── Recorder.record ──▶ eventing_events (sequence, envelope)
   (the state change)        └─ hook rows                │
                                                         │ each consumer reads past its position
                                                         ▼
                                        eventing_deliveries, one per selected destination
                                         pending ──▶ delivered | abandoned ──▶ finally sink
                                                         │ in sequence order, per destination
                                                         ▼
                                              Destination.deliver(envelope)
```

## The envelope

Every event carries one envelope, which a consumer reads without knowing the kind.
Anything a consumer acts on without knowing the kind — routing, filtering,
deduplicating, ordering, correlating — is a first-class field of it
([`eventing.md`, "What a consumer acts on without knowing the kind is an envelope field"](../../../docs/guidance/engineering/eventing.md#what-a-consumer-acts-on-without-knowing-the-kind-is-an-envelope-field)):

- `id`, a ULID, is the event's stable identity, carried by every delivery of it, on
  which a receiver deduplicates; it sorts by the time the event occurred.
- `kind`, `kind_version` and `data_schema` (`<prefix>:<kind>:<version>`, the prefix
  the catalogue's) say what the event is and which version its `details` follow.
- `source` names the recording service and its instance, and `sequence` orders the
  events of one store.
- `occurred_at`, `severity` (`info` < `warning` < `action_required`, with a rank for
  comparison), `subject` and `related` references, `correlation_id` and
  `causation_id` place the event for a reader.
- `attributes` are the kind's declared scalars, which routes read as columns;
  `summary` is the line a person reads.
- `details` hold only what a reader of that kind wants, redacted before recording,
  since destinations receive the whole envelope; `extensions` are carried unchanged.

The envelope evolves by addition, a kind's `details` follow its `kind_version`, and
a reader meeting a version it does not know routes and renders the event from its
envelope alone
([`eventing.md`, "The envelope only gains optional fields"](../../../docs/guidance/engineering/eventing.md#the-envelope-only-gains-optional-fields)).

A minimal envelope with everything else in `details` was rejected: every router,
filter and cursor would have to learn each kind. CloudEvents 1.0 as the stored form
was rejected too: its extensions must be flat scalars, which pushes `related`,
`attributes` and `source` back into its `data`. No CloudEvents rendering exists; one
at a destination's edge needs no change to the stored form.

## Kinds and the catalogue

A kind is declared before any event of it is recorded: its name, version, default
severity, attributes and their types, dedup key, details model, summary renderer,
and optionally a record-time hook. The catalogue holds a service's declarations and
lists them. It refuses a second kind of one name, an attribute named as an envelope
column, and one attribute name declared with two types, since a route reads every
attribute as a column of one table, and refuses a dedup key naming no field the kind
has. The declaration never travels: an event carries its envelope alone, so a reader
that has never seen the declaration still routes, stores and renders it.

A producer hands the recorder an `EventDraft`. One component can prepare a draft and
another record it without knowing its kind: the lease lifecycle prepares its
release-failure event, and the site ledger, which owns the transaction of the failing
transition, records it there only if it accepts the transition.

## Recording and the sequence

The recorder writes an event through the producer's own session, so it commits or
rolls back with the state change it reports
([`eventing.md`, "An event is recorded in the transaction of the state change it reports"](../../../docs/guidance/engineering/eventing.md#an-event-is-recorded-in-the-transaction-of-the-state-change-it-reports)).
It refuses, writing nothing, an undeclared kind, attributes not as declared, and
details failing the kind's model.

`sequence` is allocated from a single counter row, `eventing_sequence`, which the
recorder updates in the producer's transaction (`UPDATE … SET value = value + 1
RETURNING value`). The row's lock is held until that transaction ends, so a second
transaction recording an event waits until the first commits or rolls back. No event
therefore commits with a lower sequence than one already visible, and a consumer may
always advance its position past every event it has read without skipping one that
commits later. A repeated occurrence leaves a gap in the sequence, on which no reader
depends.

On SQLite, which serializes writers anyway, the lock costs nothing. On PostgreSQL,
transactions that record events queue on the row from their record call to their
commit, negligible at the volumes of this repository's services; a service recording
events at rates where that queue is measurable revisits the allocation. A
free-running sequence was rejected: its consumers would stop at a gap until it is
proven unused, which needs PostgreSQL's transaction snapshots in a component meant
to be portable, or, judged by a time horizon, still loses an event whose transaction
outlives the horizon.

## Dedup keys

A kind's dedup key names the envelope fields that identify one occurrence:
`subject`, `correlation_id`, `causation_id`, `attributes.<name>`, `details.<field>`,
or `related.<type>`. The recorder writes at most one event per kind and key value,
held by a unique constraint, and on a repeat returns the event already recorded and
runs no hook. A kind with an empty key makes every event its own occurrence.
Producers observe one state change more than once — a retried transition, a second
pass of a reconciling loop — and the recorder, not each producer, keeps the
occurrence single
([`eventing.md`, "An occurrence is recorded once per its declared key"](../../../docs/guidance/engineering/eventing.md#an-occurrence-is-recorded-once-per-its-declared-key)).

## Record-time hooks

A kind's record-time hook runs in the recording transaction with the event as
recorded, and its failure rolls the producer's transaction back. It is where state
that must exist exactly when the event does is written: the site's lease-end kind's
hook signs the lease-end statement and writes it to `lease_end_reports`, from which
the authenticated lease read serves it, whatever happens to its delivery. Evidence
stays domain state the hook writes, not part of the event stream, so it keeps a
retention of its own.

A hook declares each table it writes as a `PrunedTable`: the table's name, the column
its rows are pruned by, and optionally the column holding the `id` of the event that
wrote each row. The declaration is what lets pruning treat the table as the
component's own ("Retention" below), and a retention naming a table no declared hook
writes is refused.

## Consumers, destinations and delivery states

A named consumer holds a durable position, the highest sequence it has read, and for
each destination a state — `active`, `parked` or `retired` — and the position it
joined at. Each event selected for a destination becomes a delivery, `pending`,
`delivered` or `abandoned`, with its attempt count, last error and next attempt.
A consumer's cycle runs three phases, each in its own transactions:

1. **Register** the consumer and its configured destinations ("A change of
   destinations" below).
2. **Read** every event past the position, in sequence order, writing a pending
   delivery for each destination its selection names among the candidates — those
   not retired and joined before the event — and advance the position.
3. **Deliver**, destination by destination, each due delivery in sequence order,
   outside any transaction, then record its outcome. A destination's head delivery
   holds its later ones back; another destination is not held up.

A delivery's outcome is recorded after the destination's call returns, so a process
that stops between the two delivers the event again under the same `id`: delivery is
at least once
([`eventing.md`, "Delivery is at least once per destination, under a stable identity"](../../../docs/guidance/engineering/eventing.md#delivery-is-at-least-once-per-destination-under-a-stable-identity)).

## One runner per consumer

A named consumer is held by one runner at a time. A cycle — and registering, reading
or delivering run on its own — first takes the consumer's hold, a holder and an
expiry on the consumer's row, or does nothing, reporting `held_elsewhere`, while
another runner holds it unexpired. Each of its transactions renews the hold and
applies nothing once another runner has taken it, and the cycle releases the hold at
its end. A `Consumer` instance also runs one cycle at a time, so a timer's cycle and
one run by hand on the same instance are kept apart too. Without the hold, two runs
of one consumer read the same head delivery and both call the destination, and the
slower one's outcome overwrites the faster one's after the faster has delivered the
next event: out of order, and a delivered event shown pending.

The hold's expiry is kept in the consumer's clock, the time of the world, as the retry
schedule is, since both are stored and other runners compare them; where that time is
held, a stopped runner's hold lapses only when the time is moved. The hold is longer
than any delivery attempt — five minutes by default — so only a runner stuck past it
inside a destination's call can be superseded, and then the event is delivered again
under its `id`, as at-least-once delivery allows. Taking, renewing and releasing the
hold are writes, so every cycle writes, an idle one included; on SQLite a cycle waits
behind an open producer transaction, up to the connection's busy timeout.

A runner identity names one live process. An identity stable across the process's
restarts lets a restarted process take its own hold back at once, rather than waiting
for the hold to lapse; two processes given one identity are not kept apart. A service
running replicas therefore gives each replica its own identity. The provisioning
service names its runner for its site (`compute-provisioning:<site>`), on the
assumption that one process serves a site's database at a time; a deployment running
two provisioning processes against one site's database would break that assumption,
and its processes would need distinct identities for the hold to keep them apart.

One mechanism covers registering and reading as well as delivering, at a throughput of
one runner per consumer, ample at these volumes. A claim per destination was rejected:
it lets several runners serve one consumer's destinations at once, but leaves
concurrent registering and reading to fail on their keys. Leaving the rule to each
deployment — one replica, a process-local lock — was rejected because a second
process, or a cycle run by hand, breaks it silently.

## Routes

A route selects events with an SQL condition over one event: the envelope's scalar
fields and every declared attribute as the columns of a one-row table `event`, NULL
where the event does not carry the attribute, and its references as the table
`related` (`event_id`, `type`, `id`). Severity is compared through `severity_rank`.
sqlglot parses the condition, and the route is validated over sqlglot's own syntax
tree when it is built, at the service's startup: only comparisons, `AND`, `OR`,
`NOT`, `IN`, `LIKE`, `IS NULL`, literals and subqueries over `related`; every column
one the envelope has or a declared kind declares; every destination enabled. Anything
else is refused naming the route. sqlglot's executor then evaluates the condition
over the event's rows in the process, with no database involved.

SQL because an operator selects events by anything the envelope carries — a job that
ran longer than half an hour, every event naming one host among its references —
which routes by kind and severity alone cannot express, and SQL is a language
operators already read, with subqueries for the references. Predicates of the
component's own, an expression language of its own, and an adopted language that is
not SQL (CEL) were rejected for that. sqlglot because it parses into a tree whose
node types can be checked, so a statement such as `DROP` is refused by what it is
rather than by matching text; it executes over Python rows without a database; and it
transpiles the same condition into a database's dialect. No routing at all was
rejected, which floods every sink, and so were throttling and digests, which nothing
yet needs.

sqlglot's executor is not built for speed: a route costs about 4 ms per event, and
every route is evaluated for every event. At the provisioning service's volumes that
is ample. A deployment needing more evaluates its routes in the database instead, by
transpiling each condition, which needs no change to the routes an operator writes.

## A change of destinations

The destinations a consumer first has start at its position, whenever they are
configured. A consumer is registered at the latest committed event when it first
runs, or where its service's migration registers it, and a running consumer with no
destination still reads each event, keeping its position at the last one it read. The
provisioning service's migration registers its storefront consumers past the events
its data migration writes, so the first report and callback after an upgrade or an
install reach the destinations the consumers' first cycle configures.

After that, a change to a consumer's destinations takes effect at the latest
committed event. A cycle first reads every committed event with the destinations as
stored — the selection is given the candidate destinations, so it can choose for one
the configuration does not name — then adds each configured destination there and
retires each departing one: every delivery still pending to it, those just read
included, is abandoned to the finally sink, and nothing more is selected for it. An
event committed before a restart with another peer therefore never reaches the peer
that takes its place. A retired name configured again starts afresh at the position,
and the pruner keeps a consumer's latest destination row, so a consumer whose
destinations were all retired and pruned is not taken for one registering its first.

A routed consumer cannot judge a departing sink by the routes that named it, since
the configuration it runs with holds none of them. `kit/delivery`'s event-sink
consumer therefore chooses every unread event for a departing sink, and the sink's
retirement hands each to the finally sink: within the few events unread at a restart
that removes a sink, the finally sink may record one the former route would not have
selected, but none it would have is lost.

A first destination does receive what was recorded since the consumer's last read —
the events of a restart's window, from one cycle to the next. A lease-end report from
that window sent to a first storefront peer that does not own its reservation can
park that peer until an administrator resumes it. Starting a first destination at the
latest committed event instead would drop the first report after an upgrade, which
the migration's registration exists to deliver.

Four alternatives were rejected. Binding each report to its peer when it is recorded
puts domain state in the report table and still leaves the departing peer's unread
work. Storing the route set at registration, so a departing sink is judged by its
former routes, is exact but adds selection state the generic consumer keeps without
understanding it, and an interface to carry it. Recording each event's chosen sinks
when it is recorded couples recording to the delivery configuration. Marking whether
a consumer has been registered with a configuration, so a first destination of one
that ran empty starts at the latest committed event, is exact for the restart window
but keeps state in the generic component for that window alone.

## Failed delivery

A destination's `deliver` returns once the event is delivered, raises to fail the
attempt, raises `AbandonDelivery` to refuse this one delivery outright, or raises
`ParkDestination` to park itself. Each consumer has a retry policy: a backoff doubling
from an initial delay to a maximum, and optionally a maximum age.

- A failed attempt is retried after the backoff, the destination's later events
  waiting behind it.
- A parked destination receives nothing until it is resumed, explicitly; resuming
  delivers, in order, its pending events still retained.
- A destination refusing one delivery has it abandoned at once, keeping the refusal
  as its last error, and the event goes to the finally sink; the destination's next
  delivery follows, so a receiver's permanent refusal of one event costs that event
  alone.
- With a maximum age, a delivery that fails once older than that is abandoned with its
  last error to the finally sink; without one, a delivery is retried without limit.

The finally sink defaults to the log, a warning on the `eventing.finally` logger
carrying the envelope and the last error. The provisioning service's peer consumers
retry without limit, park on a peer's "unsupported", and abandon a capacity-released
callback the storefront refuses; its event-sink consumer retries each sink up to a
maximum age, then hands the event to the finally sink, the log or a sink instance named
for it. Parking on a permanent refusal was rejected, since resuming sends the same head
again and stalls on it; so was a maximum age for the peers, which would block every
later delivery until it passed; and so was retrying operator sinks forever, which
leaves a dead sink silent.

No event is recorded when a delivery is abandoned: the finally sink is its only
report, so an abandonment is seen only where the finally sink is watched.

## Retention

Each table is retained by time, configured per table, and a table given no limit
keeps every row
([`persistence.md`, "State kept for notification or audit is retained by time"](../../../docs/guidance/engineering/persistence.md#state-kept-for-notification-or-audit-is-retained-by-time)).
The tables are `events` (the events and their references), `deliveries` (finished
deliveries, and retired destinations with none left, though a consumer keeps its
latest destination row), and each table a record-time hook writes, by its name.
Retention by kind or by severity is not offered: every event of the store shares the
events' retention.

Pruning never runs ahead of a pending destination. An event is pruned only once it is
past its retention, every consumer has read past it, and each of its deliveries is
delivered or abandoned, or its destination is parked or retired. A consumer that is
not run holds every event past its position, which it has not read. A retired
destination holds nothing back, so a removed peer's pending deliveries do not keep
events forever.

A parked destination does not hold an event back either. This is an accepted risk and
a current limitation: a destination parked longer than the events' retention receives,
on resume, only the events still retained, and those pruned meanwhile are lost to it.
For the signed lease-end report, what a resumed peer misses stays readable through the
authenticated lease read. A parked destination holding back every event it would
receive, until resumed or abandoned, was rejected: it keeps the resume guarantee whole
but lets a long park grow the events table without bound.

Pruning leaves no reference dangling. An event's references and deliveries go with
it, and a row a record-time hook wrote that names its event is kept, whatever its own
table's retention, while that event is, so a retained event's delivery always finds
it; a hook's row naming no event goes by time alone. Expiring a delivery together with
its hook row was rejected, as it would narrow what a delivery promises to recover.

## Schema steps

The component owns no migration engine, and cannot use the repository's,
`kit/schema-migrations`, since it depends on no internal package. It supplies its
tables' definitions as SQLAlchemy `metadata` and `SCHEMA_STEPS`, one `SchemaStep` of
fixed DDL per schema version, each with a `name` (`eventing_0001`, …) and an
`apply(connection)`. A service's own migration chain applies the steps in order, each
under its name as a migration's identity; the provisioning service's chain applies
them among its own migrations, before the data migration that writes events into the
store. A released step is never edited, and a later change to the
tables is a further step. The DDL holds to types SQLite and PostgreSQL both accept,
times stored as UTC without a zone.

A service's data migration that writes events other than through the recorder
allocates each `sequence` by incrementing the counter row, stores a whole valid
envelope, and writes the consumer positions and delivery rows its events need
explicitly, since a consumer first run starts at the latest committed event and a
destination at its consumer's position.

## Reads and the status service

`EventReader` reads events by kind, severity, subject and related reference, in
sequence order, and each consumer's destinations with their state, position,
deliveries by state and earliest pending delivery. `EventService` is framework-free:
it validates and performs those reads and the resume of a parked destination,
answering JSON-ready dictionaries and refusing with a status, a code and a detail.
Its HTTP binding — paths, administrator authentication, turning a refusal into a
response — is each process's own, as `tools/injected-time`'s route service is
([injected time, "The component"](../injected-time/architecture.md#the-component)).
The provisioning service binds it under its administrator routes `GET
/api/v1/events`, `GET /api/v1/events/deliveries` and `POST
/api/v1/events/destinations/{name}/resume`.

## Built rather than adopted

No library found covers per-destination delivery state, record-time hooks and SQLite
together. `eventsourcing` has a notification log and atomic tracking records on
SQLite and PostgreSQL, but its events are those of event-sourced aggregates, it shares
sessions through a process-global setting rather than the producer's own session, it
keeps no state per destination, and its append-only design works against pruning.
Adopting it and building around it keeps more than half the work and a model that
does not fit. The outbox libraries found — `outboxed`, `outbox-core`, `python-cqrs`,
`outbox-streaming` and `factbus` — are each PostgreSQL-only or bound to a message
broker, and none supports SQLite, on which this repository's services run. An
external broker adds infrastructure and still needs an outbox to publish to it
atomically with the state change.

So the component is built, and kept small: it depends on the standard library,
SQLAlchemy, pydantic and sqlglot, and adopts sqlglot rather than writing a condition
language ("Routes" above)
([`implementation.md`, "Prefer an existing library"](../../../docs/guidance/engineering/implementation.md#prefer-an-existing-library)).

## Standalone

The component is generic infrastructure, so it is a standalone component under
`tools/` rather than a kit
([`package-layers.md`, "Kind"](../../../docs/guidance/repository/package-layers.md#kind)):
it depends on no internal package, names no market concept, and is ready to lift into
a repository of its own. Because `make check-architecture` does not read `tools/`, its
structure test, `tools/eventing/tests/unit/test_structure.py`, holds that boundary: it
fails on an import of any package of this repository, on a market term in its source,
and on a runtime dependency beyond its three distributions. The market's kinds, the
signed lease-end consumer, the capacity-released consumer and `kit/delivery`'s
event-sink consumer stay on the market side, depending on the component; the
component knows no sink, and `kit/delivery`'s sinks are the destinations the event-sink
consumer hands events to.

## Related contracts

- [Physical provisioning](../physical-provisioning/spec.md): the provisioning kinds, the event reads and resume, the lease-end report's and capacity-released callback's consumers
- [Site capacity](../site-capacity/spec.md): the site's kinds, and a failing transition recording a caller's prepared event
- [Introduction delivery](../introduction-delivery/spec.md): the sinks and the event-sink consumer
- [Injected time](../injected-time/spec.md): the clock a recorder and a consumer read
