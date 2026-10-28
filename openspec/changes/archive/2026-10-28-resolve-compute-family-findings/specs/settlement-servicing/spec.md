## MODIFIED Requirements

### Requirement: A fulfillment attempt may be deferred to its domain's convergence

A fulfillment attempt MUST report one of three outcomes: fulfilled, failed, or deferred.
Deferred means work remains that the domain's own convergence will finish: the workload
exists, but a step after it did not complete. A deferred outcome MUST be persisted through
the domain, so the domain can leave its deal open; no fulfillment MAY be bound for it, and
servicing MUST NOT be woken for it. A deferred outcome is distinct from a ready step
awaiting delivery, whose fulfillment has not started and which servicing rechecks every
cycle.

#### Scenario: A domain defers a fulfillment

- **WHEN** a domain's fulfillment reports deferred
- **THEN** the outcome is persisted, no fulfillment reference is bound to the obligation,
  and servicing is not woken

## ADDED Requirements

### Requirement: A ready step awaiting delivery is rechecked every cycle

A servicing worker's ready step that finds its domain's delivery not yet active, and
leaves the obligation awaiting delivery, MUST NOT count that as a failed attempt: the
obligation MUST be due again on the worker's next servicing cycle, and the error backoff
MUST NOT lengthen. A failed ready step keeps the error backoff.

The settlement operation journal MUST record the wait: a ready step leaves its obligation
awaiting delivery through the runtime's operation for it, which in one write releases the
fulfillment lease, returns the attempt its reservation counted, marks the operation
awaiting delivery while it stays pending, and makes it due at once. The worker MUST read
the operation after the ready step returns and MUST NOT apply the error backoff to an
operation awaiting delivery; an operation still pending and not awaiting delivery keeps
the error backoff. A release that does not know the mark MUST still find the operation
pending and due.

#### Scenario: Delivery takes several cycles

- **WHEN** a ready step leaves an obligation awaiting delivery because its delivery is not
  yet active, on several consecutive cycles
- **THEN** each time the obligation is due on the next cycle, and its attempts are not
  counted toward the backoff

#### Scenario: The process stops just after the mark is written

- **WHEN** a ready step's awaiting-delivery mark is written and the process stops before
  the worker schedules anything
- **THEN** the restarted worker finds the obligation due, its lease free, and the
  attempt not counted

#### Scenario: A ready step returns without starting or awaiting delivery

- **WHEN** a ready step returns, has not marked its obligation awaiting delivery, and has
  bound no fulfillment
- **THEN** the obligation takes the error backoff

#### Scenario: A release without the mark services the obligation

- **WHEN** a release that predates the awaiting-delivery mark runs against a journal
  holding an operation awaiting delivery
- **THEN** it finds the operation pending and due, and retries it on the error backoff

#### Scenario: A ready step fails

- **WHEN** a ready step raises
- **THEN** the obligation is retried after the error backoff, as before

### Requirement: Every failing servicing step is reported

A servicing worker MUST log every step it schedules for retry, naming the obligation, the
operation, and the error, whether or not an event callback is composed. Each storefront
that composes the worker MUST compose its event callback.

#### Scenario: A step fails without a callback

- **WHEN** a servicing step fails in a worker composed with no event callback
- **THEN** the worker logs the retry with the obligation, operation, and error

### Requirement: The settle wait polls through a failed status read

An administrator's settle wait MUST treat a failed read of a settlement's status as a
poll that did not reach a terminal state, keep polling until its deadline, and on reaching
the deadline report `ready: false` with the last error.

#### Scenario: The site is briefly unreachable

- **WHEN** one status read during a settle wait fails and a later one reports the
  settlement terminal
- **THEN** the wait reports ready

#### Scenario: Every read fails

- **WHEN** every status read until the deadline fails
- **THEN** the wait reports `ready: false` with the last error, rather than failing
