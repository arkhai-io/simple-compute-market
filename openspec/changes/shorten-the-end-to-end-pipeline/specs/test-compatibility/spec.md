## MODIFIED Requirements

### Requirement: Scenarios hold shared services for the whole module

Every end-to-end scenario module a compute pipeline lane selects MUST hold, for the whole
module, its lane's storefront lifecycle loops, provisioning's fulfillment convergence,
and its lease watchdog; a module the VM lane selects MUST also hold Alice's storefront
loops. A lane's selection is its marker expression, not its directory; a module no lane
selects is outside this rule, and so is a module under `scenarios/core/`, which reaches
only the dev chain and messages no storefront or provisioning service. Each hold MUST be the
lane's hold fixture, built on one shared helper per pause kind, taken before the module's
first stage, waiting until each held loop reports itself paused at its gate, and released
in a finaliser whatever the module's outcome, after the module's other cleanup. A stage
MUST assert a hold and MUST NOT pause or resume a service itself. Source checks MUST refuse
a scenario or stage that calls a pause route directly, and a module this rule covers whose
resolved fixtures lack one of its lane's holds. Every lane that holds
MUST use the same mechanism.

#### Scenario: A deal scenario fails part-way

- **WHEN** a VM or bare-metal deal scenario fails in a stage after its storefront's loops
  and the lease watchdog were held
- **THEN** both are resumed when the module ends, and the next module finds them running

#### Scenario: The Helm deal test passes

- **WHEN** the in-cluster deal test completes against a persistent Helm release
- **THEN** the seller storefront's lifecycle loops report running afterwards

#### Scenario: A stage pauses a service

- **WHEN** a scenario module or stage calls a storefront or provisioning pause route
  directly
- **THEN** the source check fails, naming the call

#### Scenario: A compute-lane module omits a hold

- **WHEN** the resolved fixtures of a scenario module a compute pipeline lane selects,
  outside `scenarios/core/`, lack its lane's storefront, fulfillment-convergence, or lease-watchdog hold, or a module the
  VM lane selects lacks Alice's storefront hold
- **THEN** the source check fails, naming the module and the missing hold

#### Scenario: A module no lane selects

- **WHEN** a scenario module in a compute lane's directory is selected by no pipeline
  lane, such as one run by hand against a real host
- **THEN** the hold check does not require its lane's holds of it

#### Scenario: A lane selects a module outside its directory

- **WHEN** a compute lane's marker expression selects a scenario module outside the lane's
  directory
- **THEN** the hold check requires the lane's holds of it, unless it is a chain-only module
  under `scenarios/core/`, such as the Alkahest escrow codec module the VM lane selects

## ADDED Requirements

### Requirement: Pipeline scenarios advance only by their own steps

An end-to-end scenario in a pipeline lane MUST prove a deterministic sequence of state
changes, never the passage of time. A transition a service's timer would make MUST be made
by the stage stepping that loop while it is held. A stage MUST wait only for an effect of
a request it made, bounded, and MUST NOT wait for a duration or a window to pass. Where a
service reads another's state live, the stage MUST read the effect once after its step
rather than poll for it.

#### Scenario: A buy reaches ready with convergence held

- **WHEN** a compute-lane scenario runs `market buy` while its lane's fulfillment
  convergence is held
- **THEN** the stage advances convergence once the buy's job is submitted, and the buy
  reaches `ready` with no convergence timer cycle

#### Scenario: A stage awaits a message its request sent

- **WHEN** a stage's request causes a service to send a message off the request path,
  such as an introduction's seller-side delivery
- **THEN** the stage waits for that message, bounded, and fails naming it if it does not
  arrive

#### Scenario: A behaviour depends on a window passing

- **WHEN** a behaviour is defined by a window or interval elapsing, such as the
  introduction retention sweep
- **THEN** no pipeline stage waits for it; a test at the level that can drive the clock
  proves it
