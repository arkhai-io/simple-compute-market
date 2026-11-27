## MODIFIED Requirements

### Requirement: Signed heartbeat evidence
The buyer MAY emit signed deal heartbeats while service is healthy; the seller
MUST authenticate the signer as the exact canonical scheme-tagged principal
authorized as the deal buyer and persist accepted heartbeats as deal-scoped
evidence. A heartbeat the seller has already persisted for the same deal, principals
and send time MUST be answered as recorded before its send time's skew and its
newness are checked, so an exact retry of an accepted heartbeat is never refused as
stale or not newer.

#### Scenario: Heartbeat identity mismatches the deal
- **WHEN** a heartbeat signature does not authenticate the complete principal
  authorized as the deal buyer
- **THEN** the seller rejects it without updating settlement evidence

#### Scenario: An accepted heartbeat is retried
- **WHEN** a buyer's heartbeat is persisted, its acknowledgement is lost, and its exact
  retry arrives after the send time has left the skew window
- **THEN** the seller answers the recorded heartbeat and persists nothing new
