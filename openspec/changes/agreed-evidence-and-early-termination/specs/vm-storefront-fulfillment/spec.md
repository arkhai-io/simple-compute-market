## MODIFIED Requirements

### Requirement: Full settlement convergence ownership

The VM storefront MUST own capacity reservation, physical fulfillment, credential delivery, and listing/delivery progress. It MUST commit the deal's reservation before the fulfillment begins, which begins the lease; afterwards only end service writes to the lease. The selected settlement stage MUST own mechanism-specific attestation, readiness and claim binding; the claims engine retains submission/collection, not physical recovery. Common delivery MUST consume evidence and MUST NOT compare mechanism IDs. The VM storefront MUST hold and commit site capacity under the deal's negotiation (`deal_ref.negotiation_id`) whatever the settlement mechanism, so a deal's site reservation is found by its negotiation and carries no settlement reference.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an operator or test looks up the site reservation of a VM deal settled through Alkahest
- **THEN** it finds the reservation by the negotiation its hold names, not by the escrow

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** common delivery records credentials, refreshes capacity, and updates listing/delivery progress
- **AND** the selected Alkahest continuation reconciles on-chain fulfillment, escrow readiness and settlement claims when applicable
- **AND** every step is safe to revisit after interruption

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces an active VM
- **THEN** common delivery returns the same domain result without creating an escrow claim or choosing a no-chain path by mechanism ID

#### Scenario: Terminal settlement ends a lease

- **WHEN** a VM deal's settlement reaches a terminal state before its lease end
- **THEN** the storefront requests end service, which truncates or terminates the lease
