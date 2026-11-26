## ADDED Requirements

### Requirement: An event carries an envelope every consumer reads without knowing its kind

An event MUST carry an envelope of `envelope_version`, `id`, `kind`, `kind_version`, `data_schema`, `source`, `sequence`, `occurred_at`, `severity`, `subject`, `related`, `correlation_id`, `causation_id`, `attributes`, `summary`, `details` and `extensions`. Severity MUST be one of `info`, `warning` and `action_required`, in that order. `attributes` MUST hold scalars only. A reader MUST ignore an envelope field it does not know and MUST preserve `extensions` without interpreting them. An envelope field MUST only ever be added, as optional; `envelope_version` MUST change only with an incompatible envelope change, and a kind's `details` MUST follow its `kind_version`.

#### Scenario: A reader meets a newer kind version

- **WHEN** a consumer built for a kind's version 1 reads an event of that kind at `kind_version` 2
- **THEN** it routes and renders the event from its envelope and does not decode its `details` with its version-1 model

#### Scenario: An event carries an extension its reader does not know

- **WHEN** an event carries an `extensions` entry no reader interprets
- **THEN** every consumer keeps it unchanged in what it stores and delivers

### Requirement: A kind is declared before it is recorded

A kind MUST be declared before any event of it is recorded: its name, version, default severity, declared attributes and their types, dedup key, details model and summary renderer. The recorder MUST refuse an event whose kind is not declared, or whose attributes or `details` do not match its declaration. The declared kinds MUST be listable as a catalogue.

#### Scenario: A producer records an undeclared kind

- **WHEN** a producer records an event whose kind no declaration names
- **THEN** the recorder refuses it and nothing is written

#### Scenario: An event's details do not match its kind

- **WHEN** a producer records an event whose `details` fail its kind's details model
- **THEN** the recorder refuses it and nothing is written

### Requirement: An event is recorded in its producer's transaction

The recorder MUST write an event through the producer's own database session, so that the event commits or rolls back with the state change it reports. A kind MAY declare a record-time hook, which MUST run in the same transaction and whose failure MUST roll the transaction back.

#### Scenario: The producer's transaction rolls back

- **WHEN** a producer records an event and its transaction then rolls back
- **THEN** no event exists and no consumer receives one

#### Scenario: A record-time hook fails

- **WHEN** a kind's record-time hook raises while an event of that kind is recorded
- **THEN** the producer's transaction rolls back, its state change included

### Requirement: An occurrence is recorded once per its dedup key

The recorder MUST write at most one event per kind and dedup-key value, and MUST return the existing event when the same occurrence is recorded again.

#### Scenario: A state change is observed twice

- **WHEN** a producer records an event whose kind and dedup-key value match an event already recorded
- **THEN** no second event is written and the producer receives the existing event

### Requirement: A consumer receives each event at least once per destination, in order

A named consumer MUST hold a durable position and, for each destination, a delivery state of pending, delivered, parked or abandoned, with its attempt count and last error. It MUST deliver events to each destination in `sequence` order and at least once, under the event's stable `id`, and a failing destination MUST NOT hold up another. The recorder MUST allocate `sequence` so that no event commits with a lower sequence than an event already visible to a consumer — from a single counter updated in the producer's transaction, whose lock is held until that transaction ends — so that a consumer advancing its position past every event it has read skips none. One runner MUST hold a named consumer at a time: a runner MUST take the consumer's hold — its identity and an expiry, stored with the consumer — before it registers, reads or delivers, MUST do nothing while another runner holds it unexpired, and MUST record no outcome once another runner has taken it, so two runners never deliver to a destination together.

#### Scenario: Two producers record events concurrently

- **WHEN** a transaction records an event while another transaction that recorded one first has not yet ended, and a consumer reads between the two commits
- **THEN** the second cannot allocate its sequence until the first ends, its event's sequence is the higher of the two, and the consumer delivers both in sequence order

#### Scenario: Two runners of one consumer overlap

- **WHEN** a second runner runs a cycle of a consumer while a first runner holds it, and later the first runner's hold lapses while it is still delivering an event
- **THEN** the second runner delivers nothing while the first holds the consumer, then takes it once the hold has lapsed, and the first runner records no outcome after the second has taken it

#### Scenario: A destination fails

- **WHEN** one of a consumer's destinations fails a delivery and another succeeds
- **THEN** the succeeding destination's state is delivered, the failing one's stays pending with its attempt count and last error, and it is retried

#### Scenario: The process stops after delivering and before recording it

- **WHEN** a delivery succeeds and the process stops before recording the outcome
- **THEN** the event is delivered again under the same `id`

### Requirement: A destination is parked and resumed explicitly, and a destination added to a consumer that has had destinations receives no earlier event

A consumer MUST be able to park a destination, after which nothing is delivered to it until it is resumed, and resuming MUST deliver, in order, the events it missed that are still retained. The destinations a consumer first has MUST start at its position, whenever they are added: a consumer is registered at the latest committed event, or where its service registers it, and a running consumer with no destination still reads each event, keeping its position at the last event it read. Once a consumer has had destinations, a change to them MUST take effect at the latest committed event: each event committed before it MUST go to the destinations as they were, whether or not the consumer had read it, and a destination added MUST NOT receive any event committed before it was added. A destination its consumer no longer has configured MUST be retired: each event still undelivered to it, read or not, MUST be marked abandoned and handed to the consumer's finally sink, and nothing more is delivered to it. A consumer that can no longer tell which of its unread events a retired destination would have received MUST hand every one of them to the finally sink for it, rather than lose one.

#### Scenario: A destination is parked and resumed

- **WHEN** a destination is parked, events are recorded, and the destination is resumed while those events are retained
- **THEN** the events recorded while it was parked are delivered to it in order

#### Scenario: A destination is parked past the events' retention

- **WHEN** a destination stays parked until events recorded meanwhile are past their table's retention and pruned, and is then resumed
- **THEN** it receives, in order, only the events still retained

#### Scenario: A destination is removed from its consumer's configuration

- **WHEN** a destination has undelivered events and its consumer starts without it configured
- **THEN** each of those deliveries is abandoned and the event written to the finally sink, and none is delivered to it

#### Scenario: A destination is added

- **WHEN** a destination is added to a consumer that has events recorded before it
- **THEN** none of those events is delivered to it

#### Scenario: A destination is replaced before the consumer reads an event

- **WHEN** an event commits, and before the consumer reads it the consumer starts with one destination replaced by another
- **THEN** the event is not delivered to the new destination, and is abandoned to the finally sink for the replaced one

#### Scenario: A first destination is added to a consumer that had none

- **WHEN** a consumer has read events with no destination, another event commits, and the consumer then starts with a destination configured
- **THEN** none of the events it read is delivered to the destination, and the event committed since its last read is

### Requirement: A route selects events with an SQL condition validated against the catalogue

A route MUST select events with an SQL condition over the event's envelope scalar fields and declared attributes as columns and its `related` references as a table, evaluated by sqlglot. At startup, a route MUST be refused if its condition holds anything but comparisons, `AND`, `OR`, `NOT`, `IN`, `LIKE`, `IS NULL`, literals and subqueries over `related`, or names a column neither the envelope nor a declared kind has, or names a destination that is not enabled.

#### Scenario: A route selects long jobs

- **WHEN** a route's condition is `kind = 'provisioning.job_finished' AND duration_seconds >= 1800` and a job of that kind finishes after 2832 seconds
- **THEN** the event is delivered to the route's destinations, and a job finishing after 40 seconds is not

#### Scenario: A route selects events about a host

- **WHEN** a route's condition is `id IN (SELECT event_id FROM related WHERE type = 'host' AND id = 'bm-02')`
- **THEN** every event naming host `bm-02` among its `related` references is selected, whatever its kind

#### Scenario: A route names an unknown column

- **WHEN** a route's condition names a column no declared kind has
- **THEN** startup is refused naming the route and the column

#### Scenario: A route holds a statement

- **WHEN** a route's condition holds a statement such as `DROP TABLE events`
- **THEN** startup is refused naming the route

### Requirement: An abandoned delivery goes to the finally sink

A consumer MUST be able to bound a destination's retries by a maximum age, after which that event's delivery to that destination is marked abandoned, keeping its last error, and the event is handed to the consumer's finally sink. A destination MUST be able to refuse one delivery outright, which is then abandoned the same way at once, keeping the refusal as its last error, while the destination's later deliveries follow it in order. The finally sink MUST default to the log.

#### Scenario: A destination keeps failing

- **WHEN** a destination fails every delivery of an event past its consumer's maximum age
- **THEN** that delivery is abandoned with its last error and the event is written to the finally sink

#### Scenario: A destination refuses one delivery

- **WHEN** a destination refuses the delivery at the head of its queue outright
- **THEN** that delivery is abandoned with the refusal as its last error, the event is written to the finally sink, and the destination's next delivery is attempted

### Requirement: Stored events are pruned by time per table, never ahead of a pending destination

Each table the component writes, and each table a record-time hook writes, MUST be retained for a time configured per table, where no limit keeps every row. An event MUST be pruned only once it is past its table's retention and, for each consumer's destination, it is delivered or abandoned, or the destination is parked or retired. A parked destination MUST NOT hold back the pruning of an event past its retention. Pruning MUST leave no retained row referring to a pruned one: an event's references and deliveries go with it, and a row a record-time hook wrote that names its event MUST be kept, whatever its own retention, while that event is.

#### Scenario: An old event is still pending

- **WHEN** an event is past its table's retention and one consumer's destination is still pending it
- **THEN** the event is kept until that destination's state is no longer pending

#### Scenario: A hook's row is past its retention while its event is pending

- **WHEN** a row a record-time hook wrote is past its table's retention and the event it names is still kept for a pending destination
- **THEN** the row is kept, and is pruned once its event is

### Requirement: The component depends on no internal package and names no market concept

The eventing component MUST depend only on the standard library and third-party distributions, MUST name no market concept, and MUST hold that boundary with a structure test of its own. It MUST supply its table definitions and one schema step per version for a service's own migration chain to apply.

#### Scenario: The component imports an internal package

- **WHEN** a module of the component imports a package of this repository
- **THEN** its structure test fails naming the import
