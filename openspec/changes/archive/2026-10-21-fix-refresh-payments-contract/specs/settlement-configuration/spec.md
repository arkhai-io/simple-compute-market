## MODIFIED Requirements

### Requirement: Payments configuration separates accounts and credentials

Shared Arkhai payments registration, typed configuration, and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST contain the trusted service origin, Ed25519 receipt identity, fee policy, dispute authority, the expected service mode `livemode`, and an API-key environment-variable reference, not the resolved credential. `livemode` MUST default to `false`, so a role that does not declare a live service accepts only test-mode receipts. Payment credentials MUST NOT appear in public options, Agreement bytes, run logs, or status.

#### Scenario: Credentials stay out of public surfaces

- **WHEN** a storefront or buyer is configured for Arkhai payments
- **THEN** its configuration names the API key's environment variable only, and the credential appears in no public option, Agreement, run log, or status

#### Scenario: An undeclared mode accepts no live receipt

- **WHEN** a storefront or buyer configured for Arkhai payments does not set `livemode`
- **THEN** it expects test-mode receipts, and a receipt signed with `livemode` true does not verify
