## ADDED Requirements

### Requirement: A storefront chart passes service configuration through

A storefront chart MUST render an agent's service configuration from its values
without enumerating the service's keys, so a setting or settlement mechanism the
storefront gains deploys through values alone with no template change. The chart
MUST NOT supply a default for a service setting and MUST NOT validate a service's own
configuration; the storefront's typed configuration is the only validation of its
keys.

The chart MAY add a value only the release knows — the agent's own public URL and
port, its gateway root path, the internal registry's and provisioning service's URLs
and the registry's authority entry, a default capacity site, and the database path
under the persistence mount — and MUST add it only where the agent's configuration
does not state it.

The chart MAY refuse a release whose parts disagree with each other: an agent using
the internal registry whose registry trust does not include the release's registry
principal, provisioning trust or a provisioning service peer that does not include
the release's provisioning principal, or an image whose settlement configuration
schema version differs from the configuration's. Trust MUST be stated by the operator
and checked by the chart, not injected by it. The chart MAY read the passed-through
configuration to make a Kubernetes decision, such as waiting for a configured chain's
RPC endpoint before the storefront starts.

A values file using a retired values shape MUST be refused at render, naming the
retired key, rather than passed through as keys the storefront ignores.

#### Scenario: A storefront gains a settlement mechanism

- **WHEN** an operator adds a mechanism's section and its priority entry to an agent's
  configuration values
- **THEN** the rendered storefront configuration carries the section exactly as
  written
- **AND** no chart template or values schema changed

#### Scenario: An operator omits a mechanism setting

- **WHEN** an agent's configuration omits a setting the storefront defaults
- **THEN** the rendered configuration omits it and the storefront applies its own
  default

#### Scenario: A service setting is invalid

- **WHEN** an agent's configuration carries a value the storefront's typed
  configuration refuses
- **THEN** the chart renders it unchanged and the storefront refuses it at startup,
  as `config migrate --check` does before a deploy

#### Scenario: The release knows a value the agent omits

- **WHEN** an agent's configuration names no registry and no provisioning URL
- **THEN** the rendered configuration carries the internal registry's URL and
  authority entry and the provisioning service's URL
- **AND** a value the agent states is rendered as stated

#### Scenario: Release parts disagree

- **WHEN** an agent's provisioning trust omits the release's provisioning principal,
  or its settlement schema version differs from the image's
- **THEN** rendering fails with a message naming the disagreement

#### Scenario: A values file uses the retired shape

- **WHEN** an agent's values use a retired key such as `seller` or `storefrontDomains`
- **THEN** rendering fails naming the key

## MODIFIED Requirements

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path
editing validation, environment schema fragments, and reference tables. Generated
outputs MUST be checked for drift in CI and MUST omit secret values and fields not
applicable to the role. A Helm values schema MUST NOT carry a fragment describing a
service's own configuration: a chart passes that configuration through, and the
service's typed configuration validates it.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, and reference
  output to change together
- **AND** no Helm values schema changes
