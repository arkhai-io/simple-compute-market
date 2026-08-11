## ADDED Requirements

### Requirement: System-integration scenarios drive lifecycle rather than wait for it

An end-to-end scenario MUST drive timer-driven work through operator lifecycle
controls rather than waiting for a loop to run. A scenario pauses the services whose
loops it depends on, asserts what an action did before anything else can react,
advances one cycle deliberately, and asserts again.

A scenario MUST NOT wait for a system to settle in place of this, whether by sleeping
or by polling until an expected state appears. Waiting cannot establish ordering even
when it succeeds, and it converts a defect that reorders two writes into an
intermittent failure rather than a reproducible one.

Resuming a paused service is itself a state change. A scenario MUST NOT resume
between assertions; resumption belongs to teardown.

Scenarios established under this requirement do not detect race conditions and are
not a substitute for concurrency testing at lower levels.

#### Scenario: An action's effect is observed before any loop reacts

- **WHEN** a scenario performs an action against a paused service and asserts
  immediately
- **THEN** the observed state reflects that action alone, because no timer-driven
  work can have run between the action and the assertion

#### Scenario: One advance, one observable step

- **WHEN** a scenario advances a lifecycle loop by one cycle and asserts
- **THEN** the observed change is attributable to that cycle, and a subsequent
  assertion failure identifies which cycle produced it

#### Scenario: A scenario that cannot pause a service states what it does not control

- **WHEN** a scenario depends on a service that exposes no lifecycle controls
- **THEN** the scenario records that its timing depends on that service's own loops,
  rather than presenting its assertions as deterministic
