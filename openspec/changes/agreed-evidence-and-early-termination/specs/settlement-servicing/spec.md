## MODIFIED Requirements

### Requirement: Signed heartbeat evidence
The buyer MAY emit signed deal heartbeats while service is healthy; the seller
MUST authenticate the signer as the exact canonical scheme-tagged principal
authorized as the deal buyer and persist accepted heartbeats as deal-scoped
evidence. When the accepted option's regime names heartbeats as evidence, the
seller MUST keep each accepted heartbeat's exact signed envelope in the evidence
store.

#### Scenario: Heartbeat identity mismatches the deal
- **WHEN** a heartbeat signature does not authenticate the complete principal
  authorized as the deal buyer
- **THEN** the seller rejects it without updating settlement evidence

#### Scenario: A regime names heartbeats
- **WHEN** a seller accepts a heartbeat on a deal whose regime names heartbeats
- **THEN** the evidence store holds its signature, proof headers, and exact body
