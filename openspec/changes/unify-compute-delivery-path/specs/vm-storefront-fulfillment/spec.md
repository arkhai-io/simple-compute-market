## MODIFIED Requirements

### Requirement: Accepted-deal delivery priority

Once a deal has been accepted, commercial delivery takes priority over local bookkeeping durability. The storefront MUST retry and loudly report failed local checkpoint writes and MUST NOT abandon an otherwise deliverable VM solely because storefront-local persistence failed. Required admission decisions and external-effect intents are exceptions to live progress: a protected effect MUST remain pending until its prerequisite writes succeed. Recovery MUST reconcile authoritative external state when local checkpoints are absent or stale, without replacing an existing resource.

#### Scenario: Local checkpoint failure does not abandon delivery

- **WHEN** an accepted deal can still deliver a VM but a storefront-local checkpoint write exhausts its retries
- **THEN** the storefront reports the missing checkpoint at high severity and retries persistence
- **AND** does not tear down or discard the deliverable VM solely because of that write failure
- **AND** defers any further protected effect whose required admission or intent has not been persisted

### Requirement: Full settlement convergence ownership

The VM storefront MUST own capacity reservation, physical fulfillment, credential delivery and listing/delivery progress through the shared compute-family delivery path. It MUST commit the deal's reservation before fulfillment begins and activate the delivered lease to the Agreement end before availability; lease-ending effects MUST go through end service. The selected settlement stage MUST own mechanism-specific attestation, readiness and claim binding; the claims engine retains submission/collection, not physical recovery. Common delivery MUST consume evidence and MUST NOT compare mechanism IDs. The storefront MUST hold and commit site capacity under `deal_ref.negotiation_id` whatever the settlement mechanism, without a settlement reference in the reservation.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an operator or test looks up the site reservation of a VM deal settled through Alkahest
- **THEN** it finds the reservation by the negotiation its hold names, not by the escrow

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** common delivery validates readiness, completes start authorization and site activation, and records availability without persisting credentials
- **AND** refreshes capacity and updates listing/delivery progress
- **AND** the selected Alkahest continuation reconciles on-chain fulfillment, escrow readiness and settlement claims when applicable
- **AND** every step is safe to revisit after interruption

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces an active VM
- **THEN** common delivery returns the same domain result without creating an escrow claim or choosing a no-chain path by mechanism ID

#### Scenario: Terminal settlement ends a lease

- **WHEN** a VM deal's settlement reaches a terminal state before its lease end
- **THEN** the storefront requests end service, which truncates or terminates the lease

#### Scenario: An Alkahest delivery activates

- **WHEN** an Alkahest-settled VM reaches verified physical readiness and local end admission permits delivery
- **THEN** the shared path activates its lease to the Agreement end before availability without issuing a hosted payment start
