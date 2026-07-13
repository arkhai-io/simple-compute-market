# Registry Discovery Specification

## Purpose

Define listing publication, schema-driven discovery, publisher identity, and filter-spec consistency.

## Requirements

### Requirement: Schema-driven listing validation
A registry MUST validate publish candidates and compile discovery filters from its configured filter-spec rather than hardcoding a concrete market schema into route signatures.

#### Scenario: Publisher submits a listing
- **WHEN** a signed listing candidate is published
- **THEN** the registry validates it against the filter-spec listing shape before storing it

### Requirement: Opaque market payload storage
The registry MUST treat domain offer payloads as opaque data except for declarative filter paths and validation rules supplied by the filter-spec.

#### Scenario: Registry serves a different schema
- **WHEN** an operator replaces the configured filter-spec and restarts the registry
- **THEN** discovery and validation use the replacement schema without domain-specific registry code

### Requirement: Publisher-scoped identity
Publication and mutation MUST be authorized by a scheme-tagged signing identity associated with the listing's publisher; the first valid publication MAY create that publisher and identity lazily.

#### Scenario: Non-owner mutates a listing
- **WHEN** a signature does not verify against an identity of the owning publisher
- **THEN** the registry rejects the mutation

### Requirement: Filter-spec consistency
The registry MUST identify a filter-spec version with an ETag and MUST reject a listing query carrying a stale `If-Match` value rather than evaluate it under different filter semantics.

#### Scenario: Cached filter spec is stale
- **WHEN** a client queries listings with an ETag that does not match the active filter-spec
- **THEN** the registry returns HTTP 412

### Requirement: Compatibility-preserving schema rollout
Non-additive registry API or persistence changes MUST preserve coexistence of old and new client/pod versions or wait for the Postgres rollout that enables gradual deployment.

#### Scenario: Additive response rollout
- **WHEN** a response field is introduced before all clients update
- **THEN** old clients continue to parse the response and new clients tolerate its absence during the rollout window

<!-- Provenance: ARCHITECTURE.md “arkhai-core-registry”, “Registry client compatibility constraint”; evidence: core/registry/src/api/filter_spec.py, filter_eval.py, listing routes and registry client tests -->
