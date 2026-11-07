## ADDED Requirements

### Requirement: Physical payment fulfillment recovers on accepted evidence

Retries and restart recovery MUST recheck accepted receipt evidence and converge on the same reservation and physical operation. VM's local provisioning-progress row MAY use the negotiation ID but MUST NOT turn the transaction into a chain escrow, settlement plan, or obligation.

#### Scenario: Verified VM provisioning restarts

- **WHEN** foreground work or recovery resumes verified payment progress
- **THEN** the existing convergence lease and durable physical fulfillment ID prevent duplicate delivery

### Requirement: Signed payment receipts gate selected-site execution

For `arkhai.payments.v1`, VM and bare-metal storefronts MUST load the accepted mandate from shared `negotiation_threads.settlement_data` beside exact `agreement_bytes` and verify the service-signed receipt against that mandate before any protected physical effect. Fulfillment MUST use the accepted domain/site binding and durable fulfillment identity, not buyer-supplied routing or current listing state.

#### Scenario: Receipt is pending or mismatched

- **WHEN** the seller cannot verify a matching signed receipt
- **THEN** it reports retryable pending or rejects invalid evidence without provisioning or creating access

#### Scenario: Bare-metal receipt is verified

- **WHEN** payment settlement succeeds for an accepted bare-metal Agreement
- **THEN** reservation, fulfillment, result retrieval, and teardown continue against that Agreement's selected-site authority

## REMOVED Requirements

### Requirement: Hosted funding gates whole-host allocation

**Reason**: Hosted Stripe settlement (`fiat.stripe.v1`, `kit/hosted-settlement`, and the hosted client) was removed, and this requirement governed it.

**Migration**: None. Arkhai payments settles through the payments service under the requirements this change adds; no hosted state is migrated.
