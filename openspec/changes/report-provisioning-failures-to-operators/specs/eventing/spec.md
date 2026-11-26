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

A named consumer MUST hold a durable position and, for each destination, a delivery state of pending, delivered, parked or abandoned, with its attempt count and last error. It MUST deliver events to each destination in `sequence` order and at least once, under the event's stable `id`, and a failing destination MUST NOT hold up another.

#### Scenario: A destination fails

- **WHEN** one of a consumer's destinations fails a delivery and another succeeds
- **THEN** the succeeding destination's state is delivered, the failing one's stays pending with its attempt count and last error, and it is retried

#### Scenario: The process stops after delivering and before recording it

- **WHEN** a delivery succeeds and the process stops before recording the outcome
- **THEN** the event is delivered again under the same `id`

### Requirement: A destination is parked and resumed explicitly, and a new destination starts at the current position

A consumer MUST be able to park a destination, after which nothing is delivered to it until it is resumed, and resuming MUST deliver what it missed in order. A destination added to a consumer MUST start at the consumer's current position and MUST NOT receive events recorded before it was added.

#### Scenario: A destination is parked and resumed

- **WHEN** a destination is parked, events are recorded, and the destination is resumed
- **THEN** the events recorded while it was parked are delivered to it in order

#### Scenario: A destination is added

- **WHEN** a destination is added to a consumer that has events recorded before it
- **THEN** none of those events is delivered to it

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

A consumer MUST be able to bound a destination's retries by a maximum age, after which that event's delivery to that destination is marked abandoned, keeping its last error, and the event is handed to the consumer's finally sink. The finally sink MUST default to the log.

#### Scenario: A destination keeps failing

- **WHEN** a destination fails every delivery of an event past its consumer's maximum age
- **THEN** that delivery is abandoned with its last error and the event is written to the finally sink

### Requirement: Stored events are pruned by time per table, never ahead of a consumer

Each table the component writes, and each table a record-time hook writes, MUST be retained for a time configured per table, where no limit keeps every row. An event MUST be pruned only once it is past its table's retention and every consumer has delivered, parked past or abandoned it for each destination.

#### Scenario: An old event is still pending

- **WHEN** an event is past its table's retention and one consumer's destination is still pending it
- **THEN** the event is kept until that destination's state is no longer pending

### Requirement: The component depends on no internal package and names no market concept

The eventing component MUST depend only on the standard library and third-party distributions, MUST name no market concept, and MUST hold that boundary with a structure test of its own. It MUST supply its table definitions and one schema step per version for a service's own migration chain to apply.

#### Scenario: The component imports an internal package

- **WHEN** a module of the component imports a package of this repository
- **THEN** its structure test fails naming the import
