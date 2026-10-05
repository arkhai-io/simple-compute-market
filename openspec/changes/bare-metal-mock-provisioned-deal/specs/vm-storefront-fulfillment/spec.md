## ADDED Requirements

### Requirement: A step after physical fulfillment defers a VM deal, never fails it

Once physical fulfillment has produced a running VM, a failure of a later step (committing
the capacity reservation's window, registering the lease, or publishing the fulfillment
evidence) MUST NOT mark the escrow failed. The foreground path MUST report the fulfillment
as deferred and leave the escrow unfinished. Restart convergence MUST then complete the deal
from the recorded fulfillment, without beginning a second one. Neither path MAY publish
the fulfillment evidence before the lease is registered, since a registered lease is an
obligation of a delivered deal.

#### Scenario: Lease registration fails after provisioning

- **WHEN** the VM is running and its lease registration fails
- **THEN** the deal is deferred, its evidence is not published, and the escrow is neither
  ready nor failed

#### Scenario: Evidence publication fails after provisioning

- **WHEN** the VM is running, its lease is registered, and publishing its fulfillment
  evidence fails
- **THEN** the deal is deferred, and restart convergence publishes the evidence

#### Scenario: Restart convergence while the provisioning service is unreachable

- **WHEN** restart convergence cannot commit the reservation or register the lease
- **THEN** it stops before publishing the evidence, and a later pass completes the deal once
  the provisioning service answers
