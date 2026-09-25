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
