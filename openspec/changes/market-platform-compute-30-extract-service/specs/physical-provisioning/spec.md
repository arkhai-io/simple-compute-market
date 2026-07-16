## ADDED Requirements

### Requirement: Compute-owned provisioning service

Cross-domain compute orchestration, including mechanism-neutral fulfillment coordination, MUST run from a deployable service owned by `provisioning/compute`, while VM and bare-metal packages retain their concrete executor and fulfillment-provider semantics and register them through explicit adapter bundles.

#### Scenario: Extracted service starts with current adapters

- **WHEN** the compute provisioner starts with VM and bare-metal adapters configured
- **THEN** it mounts generic job, lease, capacity, fulfillment, health, and watchdog surfaces plus each adapter's declared executor, provider, and operator surfaces

#### Scenario: Generic service is inspected for dependencies

- **WHEN** package and import boundaries are checked
- **THEN** generic compute service modules do not import concrete VM or bare-metal request, action, result, playbook, provider, fulfillment-requirement, or access models

### Requirement: Validated executor registration

Service composition MUST reject duplicate executor/action kinds, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor kind. This extraction does not join POOLS-3's provider-only fulfillment path to executor dispatch.

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for an executor/action kind
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers executor adapters and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace an executor adapter

### Requirement: Clean ownership cutover

After callers and deployments migrate, generic provisioning service and client paths under the VM domain MUST be removed rather than retained as aliases or compatibility distributions.

#### Scenario: Extraction completes

- **WHEN** repository package, import, image, and manifest references are reconciled
- **THEN** generic compute provisioning resolves only from the top-level provisioning category and domain packages contain only their concrete adapters and assets
