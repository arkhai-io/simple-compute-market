## MODIFIED Requirements

### Requirement: Dependency boundary

`market_fulfillment` is a higher kit layer than the site and resource-pool authorities. It may depend on `market_site`, `market_resource_pools` and its wire contracts `market_resource_pools_contracts`, and the core carrier package `market_core`, which provides `VersionedEnvelope`. Those lower layers MUST NOT import `market_fulfillment`, including under `TYPE_CHECKING`.

Carrier modules for IDs, envelopes, requests, requirements, resources, and provider protocols MUST remain independent of concrete service implementations. Scheduler modules MAY depend on site and resource-pool service interfaces required to enumerate and bind eligible resources.

#### Scenario: Type-only reverse import is introduced

- **WHEN** `market_site` or `market_resource_pools` imports `market_fulfillment` under `TYPE_CHECKING`
- **THEN** the repository dependency-boundary validation rejects the import as an upward dependency

#### Scenario: A concrete VM adapter implements fulfillment

- **WHEN** the VM provisioning composition registers an Ansible provider
- **THEN** the adapter depends on `market_fulfillment` and VM/Ansible packages while the fulfillment kit remains free of VM vocabulary

### Requirement: Versioned envelopes

Generic dictionaries crossing a domain, provider, process, or persistence boundary MUST be wrapped in `VersionedEnvelope` or a more specific typed model. `VersionedEnvelope` is provided by the dependency-light `arkhai-core` distribution (`market_core`), so a wire-contract package can carry one without depending on this fulfillment kit; fulfillment uses that one implementation and defines no envelope of its own.

An envelope contains:

- non-empty `kind` identifying the payload schema;
- integer `schema_version >= 1`;
- the payload.

Envelopes are immutable after validation. A reader that does not recognize the `(kind, schema_version)` pair MUST refuse interpretation. Incompatible shape changes increment the schema version.

This contract applies to prepared provider inputs, provider metadata snapshots, and settlement/fulfillment result payloads once those values cross a durable or cross-domain boundary. Internal transient dictionaries that never cross such a boundary do not require an envelope.

#### Scenario: Unknown envelope version

- **WHEN** a reader receives a recognized kind with an unsupported schema version
- **THEN** it rejects the payload rather than attempting best-effort decoding

#### Scenario: Typed payload is invalid

- **WHEN** a generic envelope is parameterized with a typed payload model and required payload fields are missing
- **THEN** validation fails before dispatch or persistence

#### Scenario: A wire-contract package carries an envelope

- **WHEN** a thin contracts package declares a model with a `VersionedEnvelope` field
- **THEN** it depends on `arkhai-core` alone for it, not on the fulfillment kit
