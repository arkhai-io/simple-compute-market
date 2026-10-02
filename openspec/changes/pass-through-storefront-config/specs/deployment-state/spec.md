## ADDED Requirements

### Requirement: A storefront chart passes service configuration through

A storefront chart MUST render an agent's service configuration from its values
without enumerating the service's keys, so a setting or settlement mechanism the
storefront gains deploys through values alone with no template change. The chart
MUST NOT supply a default for a service setting and MUST NOT validate a service's own
configuration; the storefront's typed configuration, applied at startup, is the only
validation of its keys.

The chart MAY add a value only the release knows: the agent's port, which MUST equal
the port its container, probes, and Service use; the agent's Service URL as its public
URL; the internal registry's and provisioning service's URLs; a `default` capacity
site bound to the effective provisioning URL; and the database path under the
persistence mount. Except for the port, it MUST add each only where the agent's
configuration does not state it.

A value whose position depends on a name only the release creates — trust for the
internal registry, keyed by that registry's derived URL — MUST be stated by the
operator as a chart-level agent value and written by the chart under the derived key.
Trust MUST be stated by the operator and checked by the chart; the chart MUST NOT add
a principal to a trust list.

The chart MAY refuse a release whose parts disagree with each other: internal-registry
trust whose authority or principals do not include the release's registry identity;
provisioning trust, or a provisioning service peer for a site bound to the internal
provisioning service, that does not include the release's provisioning principal; a
configuration that does not state the settlement configuration schema version, or
states one that differs from the image's; or a stated port that differs from the
agent's. The chart MAY read the passed-through configuration to make a Kubernetes
decision, such as waiting for a configured chain's RPC endpoint, or for the internal
registry when the agent uses it, before the storefront starts.

An agent's pass-through configuration is public: it renders into a ConfigMap as
written. Settings the storefront's typed configuration marks secret belong in the
storefront's Secret overlay.

A values file using a retired values shape MUST be refused at render, naming the
retired key, rather than passed through as keys the storefront ignores.

#### Scenario: A storefront gains a settlement mechanism

- **WHEN** an operator adds a mechanism's section and its priority entry to an agent's
  configuration values
- **THEN** the rendered storefront configuration carries the section exactly as
  written
- **AND** no chart template or values schema changed

#### Scenario: Numbers keep their type

- **WHEN** an agent's configuration carries integers, including ones above a million,
  and fractional numbers
- **THEN** the rendered configuration carries each integer as an integer and each
  fractional number as a number

#### Scenario: An operator omits a mechanism setting

- **WHEN** an agent's configuration omits a setting the storefront defaults
- **THEN** the rendered configuration omits it and the storefront applies its own
  default

#### Scenario: A service setting is invalid

- **WHEN** an agent's configuration carries a value the storefront's typed
  configuration refuses
- **THEN** the chart renders it unchanged and the storefront refuses it at startup

#### Scenario: The release knows a value the agent omits

- **WHEN** an agent's configuration names no registry, no provisioning URL, no
  capacity sites, and no database path
- **THEN** the rendered configuration carries the internal registry's URL with the
  agent's internal-registry trust under it, the provisioning service's URL, a
  `default` site bound to that URL, and a database path under the persistence mount
- **AND** a value the agent states is rendered as stated

#### Scenario: Release parts disagree

- **WHEN** an agent's internal-registry trust or provisioning trust omits the
  release's principal, its settlement schema version is absent or differs from the
  image's, or its stated port differs from the agent's port
- **THEN** rendering fails with a message naming the disagreement

#### Scenario: A values file uses the retired shape

- **WHEN** an agent's values use a retired key such as `seller` or `storefrontDomains`
- **THEN** rendering fails naming the key

### Requirement: A storefront reads chart-rendered configuration between its file and its overlay

A storefront MUST read its public configuration from `storefront.toml`, then
`storefront.yaml`, then its Secret overlay `storefront.secrets.toml`, under its
configuration directory, with a later file winning on a conflicting key. Its
configuration-reporting commands MUST report the same merged configuration the server
loads, including when only the rendered files are present.

#### Scenario: A chart-deployed storefront starts

- **WHEN** the configuration directory holds a rendered `storefront.yaml` and a
  `storefront.secrets.toml`, and no `storefront.toml`
- **THEN** the storefront loads both, with the overlay's values winning
- **AND** `market-storefront config show` reports the merged configuration

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

### Requirement: Identity configuration separates public and secret material

Private identity credentials MUST arrive through role-scoped Secret references and MUST NOT enter committed values, ConfigMaps, manifests, run logs, public principal fields, public URLs, or generated evidence. A chart's own credential values accept only Secret references; a credential an operator places in pass-through service configuration is rendered as written and refused by the service at startup. Hosted consumer profiles MUST additionally keep provider credentials and provider/customer/payment-method/mandate/bank/card data out of all marketplace roles; opaque payer binding belongs only to owner-restricted local buyer profile state, while stable instrument refs remain authority-side or transient direct-client state. Runtime MUST derive the public principal from the credential and compare it with configured public identity before readiness.

#### Scenario: Public identity configuration contains a private credential

- **WHEN** a chart's own values, a release artifact, readiness response, log, or conformance fixture contains private identity material
- **THEN** validation fails and the value is not deployed or published

#### Scenario: Hosted payer data enters storefront values

- **WHEN** a storefront's configuration declares a payer profile, instrument, Customer, PaymentMethod, mandate, bank detail, or action URL
- **THEN** the storefront's typed configuration refuses it before serving

#### Scenario: Fiat-only storefront is rendered

- **WHEN** a profile enables only Ed25519 marketplace identity and hosted non-EVM settlement
- **THEN** Helm/Compose rendering requires the identity Secret reference but no wallet, chain, RPC, deployed-address, or gas configuration

#### Scenario: Identity secret is missing

- **WHEN** a role has a public principal but cannot load matching private credential material
- **THEN** startup fails before serving authenticated routes, publishing, negotiating, or submitting settlement operations

#### Scenario: A service-peer profile is rendered

- **WHEN** a storefront and provisioning authority are configured to trust one another
- **THEN** ordinary configuration contains each exact scheme-tagged public principal and site trust binding, while each role's matching signer credential is supplied only through its own Secret boundary
