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
End-to-end stages MUST fail at the stage that violates a required contract and MUST explicitly declare consumed prior state so missing setup does not silently become an unrelated skip.

#### Scenario: Required deal state is absent
- **WHEN** a downstream stage cannot obtain a prerequisite produced by an earlier stage
- **THEN** the suite identifies the missing prerequisite and originating failure deterministically

### Requirement: Exact e2e state dependencies
Every staged e2e state field MUST use one exact producer/consumer name, and every field introduced for downstream behavior MUST have at least one explicit `require_state` consumer.

#### Scenario: Test author adds staged state
- **WHEN** a test adds a field to `DealState`
- **THEN** a downstream stage consumes that exact attribute name and coverage verifies the transition

### Requirement: Compatible client rollout
Clients MUST tolerate additive response fields and, during a staged rollout, tolerate absence of newly introduced optional fields until all servers are upgraded.

#### Scenario: Old client reads new server response
- **WHEN** the server adds an optional field
- **THEN** the old client ignores it and continues processing known fields

<!-- Provenance: ARCHITECTURE.md “Testing Strategy”, registry compatibility sections; evidence: package tests, e2e staged scenarios, middleware/conformance/session.json -->
