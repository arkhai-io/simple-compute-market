## MODIFIED Requirements

### Requirement: On-chain fulfillment reconciliation

The storefront SHALL query authoritative chain state by escrow reference before resubmitting after an ambiguous on-chain fulfillment outcome when the configured Alkahest integration exposes a supported bounded reference-query capability. It SHALL adopt an exactly matching attestation and SHALL NOT blindly resubmit when discovery is unavailable, fails, or returns conflicting matches.

#### Scenario: Successful submission response is lost

- **GIVEN** the storefront recorded that on-chain submission started
- **AND** the matching obligation attestation exists on-chain
- **AND** its UID was not persisted locally
- **WHEN** recovery runs with a supported reference-query capability
- **THEN** the storefront finds and validates the matching attestation
- **AND** adopts its UID without submitting another obligation
- **AND** continues settlement convergence

#### Scenario: Current dependency cannot discover the attestation

- **GIVEN** an on-chain submission outcome is ambiguous
- **AND** the configured Alkahest integration exposes no supported reference-query capability
- **WHEN** recovery runs
- **THEN** the storefront does not submit another obligation
- **AND** leaves the escrow pending
- **AND** emits an operator-visible reconciliation error
