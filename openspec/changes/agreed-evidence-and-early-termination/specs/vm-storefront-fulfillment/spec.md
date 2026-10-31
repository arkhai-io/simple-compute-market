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

## ADDED Requirements

### Requirement: VM buyers can end delivery through end service

The VM storefront MUST accept the accepted buyer's `end_delivery` peer message through the shared lifecycle route and realize it through end service, including before fulfillment begins. When the end is due it MUST invoke the site's termination or undelivered-hold release path immediately, not truncate to now and wait for a watchdog. Its signed response MUST distinguish a recorded end from proven capacity release.

#### Scenario: A buyer ends before provisioning

- **WHEN** a committed VM deal's buyer sends `end_delivery` while no resource has been dispatched
- **THEN** the storefront records the end, releases any undelivered hold and prevents later reconciliation from starting delivery

#### Scenario: A buyer ends a running VM

- **WHEN** the accepted buyer sends `end_delivery` for a running VM
- **THEN** end service requests termination at its recorded site and reports teardown progress until the site's capacity-released callback proves capacity return

### Requirement: VM lease ends keep the requested instant

The VM storefront MUST send and record lease ends to at least one-second precision, and MUST still read lease ends already recorded to the minute.

#### Scenario: A lease is truncated mid-minute

- **WHEN** end service truncates a VM lease to 12:00:30
- **THEN** the site receives 12:00:30, not 12:00 or 12:01
