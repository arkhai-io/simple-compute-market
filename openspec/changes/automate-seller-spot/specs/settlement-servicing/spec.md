## ADDED Requirements

### Requirement: Idempotent interruption split execution

Seller interruption automation MUST calculate and validate the applicable settlement split, submit it idempotently, persist transaction/receipt identity, and reconcile terminal chain state independently from site lease or teardown state.

#### Scenario: Split submission is retried

- **WHEN** a runner retries after uncertain acknowledgment
- **THEN** the same interruption/decision identity does not create a duplicate declaration and reconciliation returns the existing transaction or receipt

#### Scenario: Split fails after lease truncation

- **WHEN** site lease truncation succeeds but settlement split submission or confirmation fails
- **THEN** the system records a partial repairable state and does not report settlement completion
