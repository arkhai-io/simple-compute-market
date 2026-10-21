## MODIFIED Requirements

### Requirement: A storefront chart passes service configuration through

A storefront chart MUST render an agent's service configuration from its values
without enumerating the service's keys, so a setting or settlement mechanism the
storefront gains deploys through values alone with no template or hand-written schema
change. The chart MUST NOT supply a default for a service setting and MUST NOT
implement a service's semantic validation of its own configuration.

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
provisioning service, that does not include the release's provisioning principal; or a
stated port that differs from the agent's. The chart MAY read the passed-through
configuration to make a Kubernetes decision, such as waiting for a configured chain's
RPC endpoint, or for the internal registry when the agent uses it, before the
storefront starts. The chart MUST match every key it reads or writes as the
storefront's loader matches it, without regard to case, and MUST refuse a
configuration that states one key in two spellings at any depth.

A chart that runs several agents MUST key them by agent name, never list them. A
`null` assigned to a mapping key in a values file MUST remove that key — whether it
names an agent, a value of an agent, or a key at any depth of an agent's
configuration, including mapping keys inside list elements — whether or not the
Helm release's merge removed it. A removed key MUST reach no agent-reading template,
and the agent MUST render as it would had the key never been stated. The chart MUST
NOT render `null` as a mapping value. List elements MUST retain their item schema's
meaning; a `null` list element MUST NOT be removed by mapping-key normalization.

An agent map that names no agent once its null-valued entries are removed MUST be
refused at render, as an empty agent map is refused by the values schema, and so
MUST an agent that states no port or no identity once its null-valued keys are
removed, naming the agent and the missing value. A key the values schema refuses
MUST stay refused when its value is `null`.

A values file using a retired values shape MUST be refused at render, naming the
retired key, rather than passed through as keys the storefront ignores.

#### Scenario: A storefront gains a settlement mechanism

- **WHEN** an operator adds a mechanism's section and its priority entry to an agent's
  configuration values
- **THEN** the rendered storefront configuration carries the section exactly as
  written
- **AND** no chart template or hand-written values schema changed

#### Scenario: Numbers and strings keep their type

- **WHEN** an agent's configuration carries integers, including ones above a million,
  fractional numbers, and an EVM address
- **THEN** the storefront reads each integer as an integer, each fractional number as
  a number, and the address as a string

#### Scenario: An operator omits a mechanism setting

- **WHEN** an agent's configuration omits a setting the storefront defaults
- **THEN** the rendered configuration omits it and the storefront applies its own
  default

#### Scenario: A setting fails the storefront's semantic validation

- **WHEN** an agent's configuration passes the values schema but carries a value the
  storefront's typed configuration refuses
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
  release's principal, or its stated port differs from the agent's port
- **THEN** rendering fails with a message naming the disagreement

#### Scenario: A key is stated in two spellings

- **WHEN** an agent's configuration states both `Settlement` and `settlement`, or
  one nested key in two spellings
- **THEN** rendering fails naming both

#### Scenario: A release-owned key is spelled differently

- **WHEN** an agent's configuration states `Port` with a value other than the agent's
  port
- **THEN** rendering fails naming the disagreement

#### Scenario: A values file uses the retired shape

- **WHEN** an agent's values use a retired key such as `seller` or `storefrontDomains`
- **THEN** rendering fails naming the key

#### Scenario: An overlay removes an agent

- **WHEN** a values file sets to `null` an agent an earlier values file defines
- **THEN** no workload, Service, ConfigMap, Secret, or volume is rendered for that agent
- **AND** the release's other agents render as they would without it

#### Scenario: An overlay removes the only agent

- **WHEN** a values file sets to `null` the only agent an earlier values file defines,
  through the umbrella chart or the storefront chart alone
- **THEN** rendering fails naming the empty agent map

#### Scenario: An overlay removes a defaulted setting

- **WHEN** a values file sets to `null`, at any depth, a key of an agent's
  configuration that the storefront defaults and the chart does not add
- **THEN** the rendered configuration omits the key and the storefront applies its own
  default

#### Scenario: An overlay removes a value the release knows

- **WHEN** a values file sets to `null` a key of an agent's configuration that the
  chart adds when it is absent, such as `db_path`, `registry.urls`, or `port`
- **THEN** the rendered configuration carries the release's value, as when the agent's
  configuration omits the key

#### Scenario: An overlay removes a required setting

- **WHEN** a values file sets to `null` a setting the storefront requires and the chart
  does not add
- **THEN** the chart renders the configuration without it and the storefront refuses
  it at startup

#### Scenario: An overlay removes a chart-level agent value

- **WHEN** a values file sets to `null` an agent's `component`, `configMapName`,
  runtime `secret`, or Alkahest address book, or a key under either of the last two
- **THEN** the agent renders as it would had the value never been stated: its name as
  the component, the generated ConfigMap name, no runtime overlay or address book, and
  for a key under them its default, or none mounted where the key names the Secret or
  ConfigMap to mount

#### Scenario: An overlay removes an agent's port or identity

- **WHEN** a values file sets an agent's `port` or `identity` to `null`
- **THEN** rendering fails naming the agent and the missing value

#### Scenario: An overlay removes internal-registry trust

- **WHEN** a values file sets an agent's `internalRegistryTrust` to `null` while the
  agent uses the internal registry
- **THEN** rendering fails naming the missing internal-registry trust, not the `null`

#### Scenario: A refused key stays refused as null

- **WHEN** a values file sets a key the values schema refuses, such as a wallet's
  private key, to `null` in an agent's configuration
- **THEN** rendering fails naming the key
