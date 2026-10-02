## ADDED Requirements

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

### Requirement: A storefront reads chart-rendered configuration between its file and its overlay

A storefront MUST read its public configuration from `storefront.toml`, then
`storefront.json`, then its Secret overlay `storefront.secrets.toml`, under its
configuration directory, with a later file winning on a conflicting key. The rendered
layer is JSON so that every string, including a 160-bit EVM address, is read back as a
string. Its
configuration-reporting commands MUST report the configuration the server loads,
merged by the same rules, including when only the rendered files are present, and
MUST NOT print the Secret overlay verbatim.

#### Scenario: A chart-deployed storefront starts

- **WHEN** the configuration directory holds a rendered `storefront.json` and a
  `storefront.secrets.toml`, and no `storefront.toml`
- **THEN** the storefront loads both, with the overlay's values winning
- **AND** `market-storefront config show` reports the merged configuration

#### Scenario: Two layers spell a section differently

- **WHEN** one layer states `[Chains.anvil]` and a later layer states `[chains.anvil]`
- **THEN** `market-storefront config show` reports one merged `chains` section, as the
  server loads it

#### Scenario: The raw layers are shown

- **WHEN** an operator runs `market-storefront config show --raw`
- **THEN** each public layer present is printed verbatim under its path, in load
  order, and the Secret overlay is not printed

## MODIFIED Requirements

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path
editing validation, environment schema fragments, and reference tables. Generated
outputs MUST be checked for drift in CI and MUST omit secret values and fields not
applicable to the role.

A chart that passes a service's configuration through MUST carry a values-schema
fragment generated from that service's typed configuration models, refusing under the
pass-through configuration every field the models mark secret or not applicable to the
role, and every field a typed section's model does not have, each in every spelling
the service's loader reads, and MUST accept every other typed field in every such
spelling. The fragment MUST NOT carry defaults, MUST NOT require a field's presence,
and MUST NOT constrain settings the service reads untyped. A secret the
service reads without a typed model MUST be declared by the service with the same
secret marker, so the generated fragment refuses it. A section that carries public
identity MUST be declared closed to its public keys, so the generated fragment admits
those keys and refuses every other.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, reference
  output, and generated values-schema fragment to change together

#### Scenario: A secret is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values carry a secret-marked setting,
  such as a wallet private key or a registry write token
- **THEN** values-schema validation fails before render, naming the setting
- **AND** no ConfigMap is produced

#### Scenario: Private identity material is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values carry a key under `Identity`,
  at any level, that the public identity declaration does not name
- **THEN** values-schema validation fails before render, naming the key
- **AND** no ConfigMap is produced

#### Scenario: Hosted payer data is placed in pass-through configuration

- **WHEN** a storefront agent's configuration values declare a payer profile,
  instrument, Customer, PaymentMethod, mandate, bank detail, or action URL in a
  settlement section
- **THEN** values-schema validation fails before render, naming the field

#### Scenario: A typed field is spelled differently

- **WHEN** a storefront agent's configuration values spell a typed field
  differently from its model, such as `Settlement.Priority`
- **THEN** values-schema validation accepts it, as the storefront's loader does
- **AND** a secret-marked or retired key spelled differently is still refused,
  naming the key

#### Scenario: A typed section gains a field

- **WHEN** a storefront's settlement mechanism adds a public operator field and the
  fragment is regenerated
- **THEN** the field passes through the chart with no template or hand-written schema
  change
