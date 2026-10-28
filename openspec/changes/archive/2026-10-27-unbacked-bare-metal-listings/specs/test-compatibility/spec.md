## ADDED Requirements

### Requirement: Scenarios hold shared services for the whole module

An end-to-end scenario that needs a shared service's timer held — a storefront's
lifecycle loops, provisioning's fulfillment convergence, or its lease watchdog — MUST
take its lane's hold fixture for the whole module, built on one shared helper per pause
kind. A hold MUST be taken before the module's first stage, MUST wait until each held
loop reports itself paused at its gate, and MUST be released in a finaliser whatever the
module's outcome, after the module's other cleanup. A stage MUST assert a hold and MUST
NOT pause or resume a service itself, and a source check MUST refuse a scenario or stage
that calls a pause route directly. Every lane MUST use the same mechanism.

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
