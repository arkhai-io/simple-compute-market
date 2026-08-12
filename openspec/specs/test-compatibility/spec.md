# Testing and Compatibility Specification

## Purpose

Define test-level ownership, shared contract fixtures, deterministic e2e staging, and client rollout behavior.

## Requirements

### Requirement: Layered behavioral verification
Unit, integration, smoke, and end-to-end tests MUST each defend the narrowest observable contract appropriate to their level and MUST NOT rely on e2e alone for component behavior.

#### Scenario: Service API behavior changes
- **WHEN** a route contract changes
- **THEN** focused unit/integration coverage pins the route behavior and e2e verifies only the cross-service flow

### Requirement: Shared contract fixtures
Cross-language or cross-package implementations of the same protocol MUST consume canonical fixtures that encode observable requests, responses, and state transitions.

#### Scenario: API-credit middleware port changes
- **WHEN** Python, TypeScript, or Rust middleware behavior is updated
- **THEN** each implementation reproduces the shared conformance session

### Requirement: Dependency-aware e2e stages
The end-to-end stage that violates an observable contract MUST fail; downstream stages MUST explicitly declare consumed prior state and skip with the exact missing state field rather than failing for an unrelated symptom.

#### Scenario: Required deal state is absent
- **WHEN** a downstream stage lacks a prerequisite produced by an earlier stage
- **THEN** the skip reason names the missing `DealState` field

### Requirement: Exact e2e state dependencies
Every staged e2e state field MUST use one exact producer/consumer name, and every field introduced for downstream behavior MUST have at least one explicit `require_state` consumer.

#### Scenario: Test author adds staged state
- **WHEN** a test adds a field to `DealState`
- **THEN** a downstream stage consumes that exact attribute name and coverage verifies the transition

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

## Evidence

- Layer ownership: package unit/integration suites and role-level e2e scenarios.
- Lifecycle-driven scenarios: the VM storefront's `/api/v1/admin/lifecycle` pause, resume,
  and per-loop advance routes, and the scenario helpers that call them.
- Cross-language API-credit protocol behavior: `middleware/conformance/session.json` and the Python, TypeScript, and Rust conformance runners.
- Explicit staged dependencies: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`, scenario `require_state` calls, and `e2e-tests/tests/e2e/roles/README.md`.

Additive/optional client coexistence during a staged rollout is not established as a general baseline contract; registry rollout work remains proposed in `migrate-registry-to-postgres`.
