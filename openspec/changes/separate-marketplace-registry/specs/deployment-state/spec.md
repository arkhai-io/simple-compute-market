## ADDED Requirements

### Requirement: Explicit shared-registry deployment topology

A provider seller deployment MUST default to a configured external registry API URL and MUST NOT render or wait for an embedded registry unless an operator explicitly enables that role. Marketplace-operator and local/test profiles MAY enable the embedded registry and MUST use the same canonical full URL for configuration, health probing, publication, and authentication lookup.

#### Scenario: Provider uses an external registry

- **WHEN** a provider renders the default seller deployment with a valid external registry URL
- **THEN** no embedded registry resources or internal-registry wait target are emitted and the storefront uses the configured URL

#### Scenario: Operator enables the embedded registry

- **WHEN** a marketplace-operator or local profile explicitly enables the registry role
- **THEN** the registry resources render and every consumer resolves their canonical URL to that service

#### Scenario: External URL has TLS and a path prefix

- **WHEN** an operator configures an HTTPS registry URL containing a path prefix
- **THEN** health probing, publication, queries, and credential lookup preserve the normalized scheme, authority, and prefix
