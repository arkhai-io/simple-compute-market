## MODIFIED Requirements

### Requirement: Payment settlement is retryable and idempotent

Missing or pending payment evidence MUST return retryable pending without a protected effect. Repeated calls MUST reuse transaction and fulfillment/grant identities and re-drive nonterminal domain state. Receipt evidence and domain progress MUST remain domain-owned. A kit-owned lifecycle loop MAY retain observations and operation journals and act through injected adapters, never keep balances or a payment ledger.

#### Scenario: Settlement is called before approval completes

- **WHEN** the seller has no matching signed receipt for the accepted mandate
- **THEN** it returns retryable pending and creates no VM, host access or credit grant

#### Scenario: Issuance or provisioning acknowledgement is lost

- **WHEN** retry finds nonterminal domain progress after verified payment
- **THEN** it resumes the same durable operation without charging or delivering twice

#### Scenario: Rate lifecycle work continues after delivery

- **WHEN** the shared lifecycle loop observes an authority stop for a committed rate deal
- **THEN** it journals domain recovery and adapter-mediated work without becoming a local financial ledger
