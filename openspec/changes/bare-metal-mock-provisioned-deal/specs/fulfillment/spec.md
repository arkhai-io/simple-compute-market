## MODIFIED Requirements

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
