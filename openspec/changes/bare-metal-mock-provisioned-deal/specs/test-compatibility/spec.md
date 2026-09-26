## ADDED Requirements

### Requirement: A deployable domain's deal runs on every end-to-end run

Every market domain intended for deployment MUST have a complete-deal scenario that runs
on every run of the end-to-end pipeline, against running services with provisioning in
its mock profile. That scenario proves the services compose into a working deal. It
MUST NOT be reported as evidence of real delivery: where a domain's release acceptance
requires a real access target, that remains a separate protected lane.

#### Scenario: Bare metal runs its deal in the pipeline

- **WHEN** the bare-metal end-to-end lane runs
- **THEN** a whole-host deal completes through discovery, negotiation, settlement,
  mock-provisioned delivery, and teardown, observed through typed clients
- **AND** the site reports the Physical Resource's capacity returned after teardown

#### Scenario: Real access is required

- **WHEN** release acceptance requires observing real access and its revocation
- **THEN** the mock-provisioned deal does not satisfy it, and the protected lane's
  requirement stands

### Requirement: A bare-metal deal survives restart at its durable boundaries

The pipeline's bare-metal deal MUST restart the storefront after settlement commit and
after teardown acceptance and prove that the buyer, on resume, retrieves the same
operation without a second obligation, mechanism selection, or physical teardown, and
that duplicate polling and result reads are idempotent. An authenticated operator pause
MUST survive a storefront restart, refusing new negotiations until an authenticated
resume.

#### Scenario: Process stops after settlement commit

- **WHEN** the settlement authority committed the recorded operation but the buyer did not receive its response
- **THEN** resume retrieves the same operation and continues without a second obligation or mechanism selection

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** recovery observes or resumes the same teardown, and the site reports capacity released once

#### Scenario: Storefront is paused and restarted

- **WHEN** an authenticated operator pauses the storefront and its process restarts
- **THEN** the paused state remains active and new negotiations are refused until an authenticated resume operation
