## MODIFIED Requirements

### Requirement: Dispute credentials are bound by identity and no template ships an authority

`[[DisputeCredential]]` entries MUST bind a credential to an authority identity, either as `api_key`, a secret setting a service states in its secret overlay, or as `api_key_env`, an environment-variable reference, and MAY name a `ca_bundle_path`. Every consumer MUST obtain the credential through the entry's one resolution and pass the resolved token, and any CA bundle, to the mediation client, which MUST NOT read the environment itself. No configuration template MAY ship an authority. Resolved credentials MUST NOT appear in any option, Agreement or status.

#### Scenario: A template is written

- **WHEN** a role CLI writes a fresh configuration template
- **THEN** it contains no `[[Dispute]]` entry and no operator's authority account, origin or key

#### Scenario: A storefront's dispute credential is in its secret overlay

- **WHEN** a storefront's secret overlay states a `[[DisputeCredential]]` with an `api_key` for an authority
- **THEN** servicing contacts that authority with that token and reads no environment variable for it

#### Scenario: A mediation credential is built from an unusable token

- **WHEN** a mediation credential is constructed with a token that is not a secret value, or is empty, has surrounding whitespace, or contains a line break
- **THEN** construction fails, and no mediation client authenticates with that value

#### Scenario: A dispute credential names a private CA

- **WHEN** a role's `[[DisputeCredential]]` names a `ca_bundle_path`
- **THEN** its mediation client verifies that authority against that bundle alone, without changing the process's trust store, and a credential naming none uses the default trust store
