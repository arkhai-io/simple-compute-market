## MODIFIED Requirements

### Requirement: Payment settlement is retryable and idempotent

Missing or pending payment evidence MUST return retryable pending without a protected effect. Repeated calls MUST reuse transaction and fulfillment or grant identities, return completed state idempotently, and re-drive nonterminal domain state rather than leave it pending. Receipt evidence and domain progress MUST remain domain-owned, not a local ledger or mechanism-owned daemon. A neutral lifecycle loop MAY journal observations and injected-adapter effects, never balances.

#### Scenario: Settlement is called before approval completes

- **WHEN** the seller has no matching signed receipt for the accepted mandate
- **THEN** it returns retryable pending and creates no VM, host access, or credit grant

#### Scenario: Issuance or provisioning acknowledgement is lost

- **WHEN** a retry finds nonterminal domain progress after a verified payment
- **THEN** it resumes or retrieves the same durable domain operation without charging or delivering twice

#### Scenario: Rate lifecycle work continues after delivery

- **WHEN** the shared lifecycle loop observes an authority stop for a committed rate deal
- **THEN** it journals domain recovery and adapter-mediated work without becoming a local financial ledger
