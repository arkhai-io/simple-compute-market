## MODIFIED Requirements

### Requirement: Payment settlement is retryable and idempotent

Missing or pending payment evidence MUST return retryable pending without a protected effect. Repeated calls MUST reuse transaction and fulfillment or grant identities, return completed state idempotently, and re-drive nonterminal domain state rather than leave it pending. Receipt evidence and domain progress MUST remain domain-owned, not a local ledger or payment-servicing daemon. A neutral lifecycle loop MAY journal the authorities' observations and the effects of its injected adapters, and MUST NOT journal balances or amounts owed.

#### Scenario: Settlement is called before approval completes

- **WHEN** the seller has no matching signed receipt for the accepted mandate
- **THEN** it returns retryable pending and creates no VM, host access, or credit grant

#### Scenario: Issuance or provisioning acknowledgement is lost

- **WHEN** a retry finds nonterminal domain progress after a verified payment
- **THEN** it resumes or retrieves the same durable domain operation without charging or delivering twice

#### Scenario: The servicing loop journals a stop, not a balance

- **WHEN** the `deal-servicing` loop observes a rate part's final stop
- **THEN** it journals the verified stop and the end it selects, and journals no balance, funded amount or amount owed
