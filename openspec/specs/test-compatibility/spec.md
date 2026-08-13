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

### Requirement: Artifact-bound hosted settlement system evidence
Hosted settlement system tests MUST verify the exact signed production and
private E2E release identities, wheels, image digests, schemas, protocols, and
capabilities before composition. Marketplace-owned scenarios MUST drive the
ordinary discovery, negotiation, settlement, fulfillment, status, and reclaim
surfaces; simulator controls MUST remain confined to the private test runner
and reports MUST contain only allowlisted normalized effects.

#### Scenario: Hermetic hosted settlement lifecycle runs
- **WHEN** an operator selects the private hermetic hosted profile with compatible signed artifacts
- **THEN** the consumer scenario runs from those artifacts without sibling source, wallet, chain, RPC, EAS, or provider credentials and records the production and E2E manifest identities

#### Scenario: Real-provider evidence is unavailable
- **WHEN** Stripe test credentials, a ready connected account, reachable webhook forwarding, or an authorized protected workflow is unavailable
- **THEN** the missing external prerequisite is reported and simulator output MUST NOT be labeled as Stripe evidence

### Requirement: Public test entry points exclude private hosted fixtures
Ordinary public builds, test discovery, and fork workflows MUST NOT resolve
private hosted E2E packages, images, manifests, control credentials, or
provider credentials.

#### Scenario: Contributor runs the default test suite
- **WHEN** no private registry access or hosted E2E credential is present
- **THEN** collection and execution succeed without importing or skipping over private hosted controls

## Evidence

- Layer ownership: package unit/integration suites and role-level e2e scenarios.
- Cross-language API-credit protocol behavior: `middleware/conformance/session.json` and the Python, TypeScript, and Rust conformance runners.
- Explicit staged dependencies: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`, scenario `require_state` calls, and `e2e-tests/tests/e2e/roles/README.md`.

Additive/optional client coexistence during a staged rollout is not established as a general baseline contract; registry rollout work remains proposed in `migrate-registry-to-postgres`.
