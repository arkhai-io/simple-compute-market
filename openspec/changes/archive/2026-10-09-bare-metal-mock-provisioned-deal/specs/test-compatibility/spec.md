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

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest and delivered
through the provisioning mock profile, MUST take each stage its domains run identically
from one shared definition. A domain MUST subclass a shared stage without replacing its
body and MUST supply its differences through fixtures and a per-domain driver. A domain
MAY insert stages of its own; a stage whose body differs between domains is not shared.

#### Scenario: A shared stage changes

- **WHEN** a shared stage's preview, advance, or assertion changes
- **THEN** every compute lane that runs the canonical deal runs the changed stage without
  a per-domain edit

#### Scenario: A domain's part of a shared stage

- **WHEN** a shared stage needs supply seeding, provision terms, mock rules and their
  release, the lease view, settlement-preview expectations, the settlement's dispatch,
  result and access assertions, or the claim that re-reserves released supply and its
  release
- **THEN** the domain's driver supplies it and the stage's body is unchanged

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way, or a domain outside the compute family
  runs a complete deal
- **THEN** it keeps its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

### Requirement: Each domain runs in its own lane

The end-to-end pipeline MUST run each market domain's scenarios in a lane of its own, as
a pipeline job separate from every other domain's lane, so a failure in one domain's
lane cannot hide or stand in for another's evidence. Each lane MUST build the images its
own stack runs and compose only its own services, including every registry its
scenarios read.

#### Scenario: The pipeline runs

- **WHEN** the end-to-end pipeline runs
- **THEN** the VM, bare-metal, and API-credit lanes each build their own stack's images
  and run their own stack and scenarios, in parallel
- **AND** the VM lane's stack does not include the API-credit services

#### Scenario: A scenario reads a registry of another schema

- **WHEN** a lane's scenario discovers across registries of more than one schema
- **THEN** the lane deploys each of those registries in its own stack, and the scenario
  reads them from that lane's settings

#### Scenario: A compute lane provisions through the mock profile

- **WHEN** a compute lane runs
- **THEN** its provisioning services run their mock profile because the run selects mock
  provisioning, not because the lane's local overlay or stack hard-codes it
- **AND** no storefront in the lane carries a provisioning mode

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

#### Scenario: Process stops while the lease is active

- **WHEN** the storefront is rebuilt while a delivered lease is active
- **THEN** repeated status, result, access, and settlement-status reads return what they returned before, with no second reservation or fulfillment start

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** after the rebuild, a repeated teardown returns the same lease release operation and the site releases capacity once
