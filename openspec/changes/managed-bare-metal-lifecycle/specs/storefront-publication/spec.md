## ADDED Requirements

### Requirement: Capacity publication confirms release relisting

Capacity publication MUST keep held and quarantined capacity closed, and MUST treat relisting as successful only after exact authenticated readback of the intended signed listing. A capacity cursor MUST advance only after the reconciliation it acknowledges succeeds; otherwise an explicit pending reconciliation MUST persist and be retried on the next cycle. Intended request and target identity MUST be persisted before a remote write, uncertain writes MUST be reconciled by readback before any retry, and local state MUST be committed only after confirmation. A remote publication failure MUST NOT repeat completed physical release steps.

#### Scenario: Initial full reconciliation fails

- **WHEN** the first full reconciliation after startup or a ledger reset fails
- **THEN** the cursor does not advance, and the next cycle retries the full reconciliation

#### Scenario: Remote write times out after acceptance

- **WHEN** a relisting write is accepted remotely but the response is lost
- **THEN** publication confirms the listing through readback rather than creating a duplicate listing

#### Scenario: New reservation races a reopen

- **WHEN** a reservation commits while a released host's listing is being reopened
- **THEN** publication rechecks current capacity and does not publish capacity the reservation now holds
