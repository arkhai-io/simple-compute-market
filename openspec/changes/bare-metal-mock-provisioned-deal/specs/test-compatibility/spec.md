## ADDED Requirements

### Requirement: A deployable domain's deal runs on every end-to-end run

Every market domain intended for deployment MUST have a complete-deal scenario that runs
on every run of the end-to-end pipeline, against running services using that domain's
ordinary local or test authorities. A domain whose delivery crosses compute provisioning
MUST run provisioning in its mock profile. The scenario MUST hold every storefront loop
it depends on, preview each transition it advances through that loop's or route's dry
run where one exists, and advance it explicitly. That scenario proves the services
compose into a working deal. Mocked delivery MUST NOT be reported as evidence of real
delivery: where a domain's release acceptance requires a real external resource, that
remains a separate protected lane.

#### Scenario: Bare metal runs its deal in the pipeline

- **WHEN** the bare-metal end-to-end lane runs
- **THEN** a whole-host deal completes through discovery, negotiation, Alkahest
  settlement, mock-provisioned delivery, lease expiry, and teardown, observed through
  typed clients, with every dry-run stage VM's deal runs
- **AND** the site releases the Physical Resource's reservation, the storefront receives
  the capacity-released callback, and the next publication pass reopens the listing

#### Scenario: Buyer teardown is repeated

- **WHEN** the bare-metal lane's second deal requests teardown twice
- **THEN** both requests return the same lease release operation and the site releases
  the reservation once

#### Scenario: Real access is required

- **WHEN** release acceptance requires observing real access and its revocation
- **THEN** the mock-provisioned deal does not satisfy it, and the protected lane's
  requirement stands

### Requirement: Compute-family deal stages are defined once

Every compute-family domain's complete-deal scenario MUST declare its stages from one
shared set of compute deal stage definitions, supplying what differs through a
per-domain driver: supply seeding, provision terms, the mock rules matched, the lease
view, settlement-preview expectations, and result and access assertions. A domain MAY
override or insert a stage; it MUST NOT copy a stage's body. Domains outside the compute
family keep their own deal flows.

#### Scenario: A stage changes

- **WHEN** a shared compute deal stage's preview, advance, or assertion changes
- **THEN** every compute-family lane runs the changed stage without a per-domain edit

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

### Requirement: Each domain runs in its own lane on images built once

The end-to-end pipeline MUST run each market domain's scenarios in a lane of its own, as
a pipeline job separate from every other domain's lane, so a failure in one domain's
lane cannot hide or stand in for another's evidence. A pipeline run MUST build each image
once and every lane MUST run on those images; a lane MUST NOT rebuild them. Local lane
targets MAY build before they run.

#### Scenario: The pipeline runs

- **WHEN** the end-to-end pipeline runs
- **THEN** one job builds the images, and the VM, bare-metal, and API-credit lanes each
  load them and run their own stack and scenarios
- **AND** the VM lane's stack does not include the API-credit services

### Requirement: Bare-metal storefront restart recovery is proven at integration level

Bare-metal storefront restart recovery MUST be proven by integration tests that rebuild
the production application over the same database. After a rebuild following settlement
commit or teardown acceptance, the buyer MUST retrieve the same operation without a
second obligation, mechanism selection, or physical teardown, and duplicate polling and
result reads MUST be idempotent. The end-to-end lane starts from empty state and does
not restart services.

#### Scenario: Process stops after settlement commit

- **WHEN** the settlement authority committed the recorded operation but the buyer did not receive its response
- **THEN** after the rebuild, resume retrieves the same operation and continues without a second obligation or mechanism selection

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** after the rebuild, recovery observes the same lease release operation and the site releases capacity once
