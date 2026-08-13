## ADDED Requirements

### Requirement: Deployment uses one settlement hierarchy

Role TOML, committed defaults, environment overlays, Helm values/schema/templates, Compose, examples, and generated configuration MUST use the same typed `[Settlement]` root and mechanism subsection names. Marketplace deployment MUST keep public identity, wallet/chains, and mechanism trust/policy separate from Secret-injected credentials, and MUST reject hosted provider/admin/webhook secrets or service-owned state.

#### Scenario: VM chart enables hosted settlement only

- **WHEN** the chart receives a valid public hosted consumer configuration and identity Secret reference
- **THEN** it renders the Stripe mechanism subsection and no wallet, chain, RPC, provider, webhook, database, or hosted migration configuration

#### Scenario: Legacy environment variable remains

- **WHEN** startup receives a removed hosted or Alkahest configuration path after cutover
- **THEN** readiness fails with the corresponding new path and migration command rather than applying hidden precedence

### Requirement: Configuration cutover is atomic and coordinated

Migration tooling MUST be deployable before runtime rejection, and production cutover MUST preview, back up, migrate, and validate every role file, Secret mapping, Helm value, Compose environment, and automation caller before enabling the clean-cutover release. Old and new names MUST NOT be accepted concurrently by runtime. Rollback before activation MUST restore the matching config and prior artifacts together.

#### Scenario: Helm values and image contract differ

- **WHEN** a new image receives old settlement values or an old image receives new settlement values
- **THEN** schema validation or startup readiness fails before publication or settlement mutation

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path editing validation, environment/Helm schema fragments, and reference tables. Generated outputs MUST be checked for drift in CI and MUST omit secret values and fields not applicable to the role.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, and reference output to change together
