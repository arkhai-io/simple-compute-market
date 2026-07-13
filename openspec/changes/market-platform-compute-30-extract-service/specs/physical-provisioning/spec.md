## ADDED Requirements

### Requirement: Compute-owned provisioning service

Cross-domain compute orchestration MUST run from a deployable service owned by `provisioning/compute`, while VM and bare-metal packages retain their concrete executor semantics and register them through explicit adapter bundles.

#### Scenario: Extracted service starts with current adapters

- **WHEN** the compute provisioner starts with VM and bare-metal adapters configured
- **THEN** it mounts generic job, lease, capacity, health, and watchdog surfaces plus each adapter's declared executor/operator surfaces

#### Scenario: Generic service is inspected for dependencies

- **WHEN** package and import boundaries are checked
- **THEN** generic compute service modules do not import concrete VM or bare-metal request, action, result, playbook, or access models

### Requirement: Validated executor registration

Service composition MUST reject duplicate executor/action kinds and incomplete adapter bundles before accepting traffic.

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for an executor/action kind
- **THEN** startup fails with both registrations identified and no server begins serving

### Requirement: Clean ownership cutover

After callers and deployments migrate, generic provisioning service and client paths under the VM domain MUST be removed rather than retained as aliases or compatibility distributions.

#### Scenario: Extraction completes

- **WHEN** repository package, import, image, and manifest references are reconciled
- **THEN** generic compute provisioning resolves only from the top-level provisioning category and domain packages contain only their concrete adapters and assets
