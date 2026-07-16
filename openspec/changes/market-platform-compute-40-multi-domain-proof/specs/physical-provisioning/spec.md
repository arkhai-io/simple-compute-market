## ADDED Requirements

### Requirement: Concurrent VM and bare-metal adapters

One extracted compute provisioner MUST load VM and bare-metal adapter bundles concurrently and dispatch action and release behavior from the committed allocation's executor identity. Registered fulfillment-provider identities MUST remain orthogonal infrastructure-mechanism choices and MUST NOT participate in, infer, or override executor-adapter selection; this proof does not require provider-backed fulfillment for both domains.

#### Scenario: VM and bare-metal jobs run

- **WHEN** valid committed allocations submit their respective create/grant actions
- **THEN** each action is validated and executed by its registered adapter and both expose the common durable job lifecycle

#### Scenario: Request attempts executor substitution

- **WHEN** a caller submits an executor kind that differs from the committed allocation
- **THEN** the provisioner rejects the request before infrastructure work and preserves the recorded allocation identity

#### Scenario: Provider cannot substitute an executor

- **WHEN** a provider identity is registered or available for a settlement resource
- **THEN** action and release dispatch still select the adapter only from the committed allocation's executor identity and do not route another executor kind merely because that mechanism is available

#### Scenario: Both allocation types release

- **WHEN** VM teardown and bare-metal reclaim complete for their leases
- **THEN** release dispatch selects the corresponding adapters and each site allocation becomes available exactly once

### Requirement: Generic provisioning dependency proof

Generic site and compute-provisioning modules MUST remain importable and testable without concrete VM or bare-metal implementation imports.

#### Scenario: Architecture boundary tests run

- **WHEN** dependencies of generic site and compute packages are inspected
- **THEN** concrete domain models, actions, playbooks, and result types appear only behind registered adapter packages
