## ADDED Requirements

### Requirement: Early-termination fields are projected per option

A mechanism registration whose options carry the `early_termination` clause MUST project its entitlements as typed settlement fields (for example `early_termination.payer` and `early_termination.payee.notice_seconds`), evaluated per option like every other settlement field.

#### Scenario: A buyer asks for buyer-stoppable options

- **WHEN** a clause contains `early_termination.payer=true` and a listing has one option with a payer entitlement and one without
- **THEN** only the option with the entitlement matches
