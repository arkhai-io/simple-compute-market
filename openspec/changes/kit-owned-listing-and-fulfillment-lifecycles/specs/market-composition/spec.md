## ADDED Requirements

### Requirement: Shared listing lifecycle

The seller listing lifecycle (close, pause, reopen and successor carry-over) MUST live in kit/capacity-publication. Domains MUST supply listing payload codecs and successor-identity rules, not duplicate lifecycle services.

#### Scenario: A seller closes a listing in any domain

- **WHEN** a seller closes, pauses, or reopens a listing through the shared routes
- **THEN** the kit mutates the common binding and publishes the result, and the
  domain's codec alone interprets the listing payload

### Requirement: Compute calling convergence uses protected delivery

Compute calling convergence MUST live in domains/compute/delivery or above, never the provisioning base kit. It MUST discover/resume obligations, reconcile executor results and drive terminal state with independent teardown through domain executor hooks, consuming shared delivery checkpoints and access retirement rather than duplicating protected-effect recovery. API credits MUST retain issuance ownership.

#### Scenario: A storefront restarts with accepted obligations

- **WHEN** a storefront restarts after settlement and before fulfillment completes
- **THEN** the compute calling convergence discovers and resumes accepted obligations,
  drives terminal state through domain hooks and consumes shared compute delivery's protected checkpoints
  and access retirement without duplicating their recovery; API credits retains issuance
