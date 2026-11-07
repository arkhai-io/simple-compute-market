## MODIFIED Requirements

### Requirement: Payments configuration separates accounts and credentials

Arkhai payments registration, typed configuration and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST hold the trusted service origin, Ed25519 receipt identity, fee policy, an optional CA bundle path, and the API key either as `api_key`, a secret setting a service states in its secret overlay, or as `api_key_env`, the environment variable a buyer's provider reads; the two MUST be mutually exclusive, and each with `development_auth`. One key resolution MUST serve client construction, readiness and the payments check. When `ca_bundle_path` is set, the payments client MUST verify the service against that bundle alone, without changing the process's trust store. The credential MUST NOT appear in public options, Agreement bytes, run logs, status, or a chart's public configuration. A `dispute_authority` setting MUST be rejected naming `[[Dispute]]`.

#### Scenario: The retired dispute authority key is set

- **WHEN** a role's configuration sets `[Settlement.arkhai_payments].dispute_authority`
- **THEN** validation fails with a diagnostic naming `[[Dispute]]`

#### Scenario: Credentials stay out of public surfaces

- **WHEN** a storefront or buyer is configured for Arkhai payments
- **THEN** the credential appears in no public option, Agreement, run log, status or public configuration file

#### Scenario: A storefront's key is in its secret overlay

- **WHEN** a storefront's secret overlay states `[Settlement.arkhai_payments].api_key`
- **THEN** its payments client, readiness and payments check authenticate with that key and read no environment variable for it

#### Scenario: Both key forms are set

- **WHEN** a role's payments configuration states both `api_key` and `api_key_env`
- **THEN** validation fails naming both

#### Scenario: A private CA is configured

- **WHEN** a role's payments configuration names a `ca_bundle_path`
- **THEN** its payments client trusts that bundle for the payments service, and the role's other HTTPS clients keep their own trust

#### Scenario: An undeclared mode accepts no live receipt

- **WHEN** a storefront or buyer configured for Arkhai payments does not set `livemode`
- **THEN** it expects test-mode receipts, and a receipt signed with `livemode` true does not verify

### Requirement: Dispute credentials are bound by identity and no template ships an authority

`[[DisputeCredential]]` entries MUST bind a credential to an authority identity, either as `api_key`, a secret setting a service states in its secret overlay, or as `api_key_env`, an environment-variable reference. Every consumer MUST obtain the credential through the entry's one resolution and pass the resolved token to the mediation client, which MUST NOT read the environment itself. No configuration template MAY ship an authority. Resolved credentials MUST NOT appear in any option, Agreement or status.

#### Scenario: A template is written

- **WHEN** a role CLI writes a fresh configuration template
- **THEN** it contains no `[[Dispute]]` entry and no operator's authority account, origin or key

#### Scenario: A storefront's dispute credential is in its secret overlay

- **WHEN** a storefront's secret overlay states a `[[DisputeCredential]]` with an `api_key` for an authority
- **THEN** servicing contacts that authority with that token and reads no environment variable for it

#### Scenario: A mediation credential is built from an unusable token

- **WHEN** a mediation credential is constructed with a token that is not a secret value, or is empty, has surrounding whitespace, or contains a line break
- **THEN** construction fails, and no mediation client authenticates with that value
