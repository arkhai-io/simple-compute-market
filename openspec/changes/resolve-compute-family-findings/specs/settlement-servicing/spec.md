## ADDED Requirements

### Requirement: A ready step whose delivery is pending is rechecked every cycle

A servicing worker's ready step that finds its domain's delivery still pending, and defers
the obligation for it, MUST NOT count that deferral as a failed attempt: the obligation
MUST be due again on the worker's next servicing cycle, and the error backoff MUST NOT
lengthen. A failed ready step keeps the error backoff.

The settlement operation journal MUST record the deferral: a ready step defers through the
runtime's deferral operation, which in one write releases the fulfillment lease, returns
the attempt its reservation counted, marks the operation deferred, and makes it due at
once. The worker MUST read the operation after the ready step returns and MUST NOT apply
the error backoff to a deferred operation; an operation still pending and not deferred
keeps the error backoff.

#### Scenario: Delivery takes several cycles

- **WHEN** a ready step defers an obligation because its delivery is not yet active, on
  several consecutive cycles
- **THEN** each deferral leaves the obligation due on the next cycle, and its attempts are
  not counted toward the backoff

#### Scenario: The process stops just after a deferral

- **WHEN** a ready step's deferral is written and the process stops before the worker
  schedules anything
- **THEN** the restarted worker finds the obligation due, its lease free, and the
  deferral's attempt not counted

#### Scenario: A ready step returns without deferring or starting

- **WHEN** a ready step returns, has not deferred, and has bound no fulfillment
- **THEN** the obligation takes the error backoff

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
