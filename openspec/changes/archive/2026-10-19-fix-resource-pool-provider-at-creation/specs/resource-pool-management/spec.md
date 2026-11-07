## ADDED Requirements

### Requirement: The default pool is created with its intended provider

On an empty provisioning database with a configured pool definition document,
schema initialization MUST leave default-pool creation to ordinary atomic
startup document import. Contributed definitions MUST be imported before pools,
and host inventory MUST follow pools. Without a configured document, schema
initialization MUST retain the VM bootstrap.
Existing databases MUST retain default-pool identity and host backfill; a mounted
document MUST NOT change an existing pool's provider.

#### Scenario: A fresh bare-metal site declares its default

- **WHEN** a fresh provisioning database starts with a valid document declaring `default` as `bare_metal.ansible`
- **THEN** import creates that pool with its declared configuration and records the digest atomically before admitting inventory
- **AND** no implicit VM default is created, including on repeated migration before first startup

#### Scenario: A fresh site has no pool document

- **WHEN** a fresh provisioning database has no configured pool document
- **THEN** migration creates the enabled VM default with its configured VM playbook

#### Scenario: An existing site gains a pool document

- **WHEN** migration runs against existing state with a newly configured pool document
- **THEN** existing host membership and the default pool are preserved
- **AND** startup import refuses a differing default provider

#### Scenario: The configured document is missing or invalid

- **WHEN** a fresh provisioning database has a configured pool document that cannot be imported
- **THEN** startup fails without substituting an implicit VM default

### Requirement: VM provider identity is namespaced

The VM adapter MUST register as `vm.ansible`, alongside `bare_metal.ansible`.
Upgrade MUST canonicalize historical `ansible` routing columns in pools and
fulfillment records while preserving pool IDs, configuration, host membership,
lifecycle state, job identity and accepted operation envelopes. Runtime documents
and callers MUST use the canonical name; no historical-name alias is required.

#### Scenario: Existing VM state is upgraded

- **WHEN** migration encounters pools or fulfillment records with provider `ansible`
- **THEN** only their provider routing columns become `vm.ansible`
- **AND** configuration, members and accepted work retain their values, including on repeated migration
- **AND** bare-metal records are unchanged

#### Scenario: A canonical VM pool is administered

- **WHEN** an operator creates or edits a VM pool with provider `vm.ansible`
- **THEN** the VM adapter validates its configuration and handles fulfillment through that registration

### Requirement: A pool's provider is fixed at creation

A Resource Pool's provider MUST NOT change after creation. Replace, patch and
authoritative import MUST reject a differing provider before mutation, preserving
metadata and configuration. An otherwise-valid request naming a registered
differing provider MUST receive HTTP 400 with both providers named and the
second-pool member-migration path explained.

Provider configuration MUST remain editable within the declared provider.
`PoolUpdate.provider` MUST remain accepted; an equal value MUST act as omission
and MUST NOT by itself trigger a configuration write.

#### Scenario: Replace supplies a different registered provider

- **WHEN** an otherwise-valid replacement supplies a registered provider differing from the pool's own
- **THEN** the request is rejected with HTTP 400 before any mutation
- **AND** all metadata and existing provider configuration are unchanged
- **AND** the message names both providers and directs the operator to declare a second pool and migrate its members

#### Scenario: Patch supplies a different registered provider

- **WHEN** an otherwise-valid patch supplies a registered differing provider alongside other changes
- **THEN** the request is rejected with HTTP 400
- **AND** none of its metadata or configuration changes are applied

#### Scenario: Patch supplies only the same provider

- **WHEN** patch supplies only the pool's own provider
- **THEN** the pool remains unchanged
- **AND** the provider configuration handler performs no configuration write

#### Scenario: Configuration is edited within the provider

- **WHEN** replacement or patch supplies valid new configuration for the pool's own provider
- **THEN** configuration is updated under the existing replacement or patch semantics
- **AND** provider is unchanged and existing secret-retention rules still apply

#### Scenario: Inventory moves to a different provider

- **WHEN** an operator needs inventory delivered by a different provider
- **THEN** the supported path is a second pool declaring that provider and explicit member reassignment
- **AND** capacity-resource reassignment remains subject to the site-capacity requirement “A capacity resource does not move pools under live obligations” in `openspec/specs/site-capacity/spec.md`
- **AND** host reassignment continues through existing pool-change hooks

### Requirement: Shared validation of pool immutability

Provider and backing immutability MUST use shared stored-state validation across
individual writes and document administration. Request-only validation MUST
precede the stored-state comparison. Omitted patch fields MUST retain their
stored values for comparison. The allowance for supplying backing where none is
stored MUST remain unchanged.

#### Scenario: A patch omits immutable fields

- **WHEN** a valid patch changes only mutable metadata and omits provider and policy tags
- **THEN** the immutability comparison treats both as unchanged
- **AND** the metadata change succeeds without rewriting provider configuration

#### Scenario: A pool without stored backing is repaired

- **GIVEN** a stored pool whose tags lack backing
- **WHEN** an otherwise valid write supplies backing without changing provider
- **THEN** the existing backing repair allowance accepts the declaration

#### Scenario: Request-only document validation fails first

- **WHEN** a document fails request-only validation and also proposes an immutable-field change
- **THEN** validation reports its request-only problems without a stored-state comparison or diff
- **AND** no data is changed

### Requirement: Documents report immutable providers atomically

After a document passes request-only and provider-configuration validation,
validate-only MUST report a differing provider at `pools[<i>].provider` with code
`provider_immutable`, using the submitted index, and no diff. That stage MUST report
every immutable-field problem. Import MUST refuse the whole document before
application, retaining HTTP 400 with path-named detail text. A refused startup
import MUST leave its recorded digest unchanged.

#### Scenario: A document changes an existing provider

- **WHEN** an otherwise-valid document names a registered differing provider for an existing pool
- **THEN** validate-only returns `valid: false`, no diff and a `provider_immutable` problem at that entry's provider path
- **AND** validation writes no metadata or configuration
- **AND** import refuses with HTTP 400 and applies none of the document's changes

#### Scenario: Both immutable fields change

- **WHEN** an otherwise-valid document changes provider and an existing backing value
- **THEN** validate-only reports both `provider_immutable` and `capacity_backing_immutable` at their field paths
- **AND** import refuses without applying any entry or omitted-pool disablement

#### Scenario: A changed mounted document changes provider

- **WHEN** startup reconciles a changed document changing an existing pool's provider
- **THEN** startup fails with the offending entry named
- **AND** no entry or new digest is committed, so the next startup retries

#### Scenario: A new document entry declares its provider

- **WHEN** a valid document contains an ID absent from stored pools
- **THEN** the entry may create that pool with its declared registered provider
- **AND** the comparison does not treat creation as a provider change

### Requirement: Typed pool models validate policy hints

`PoolCreate`, `PoolReplace` and a `PoolUpdate` supplying tags MUST reject malformed
hold, SLA, listing-shape, asking-rate and pricing rate-list hints through shared
contracts-owned checks reused by raw document validation. Individual service
writes MUST rely on validated models rather than repeat those checks. Malformed
hints in individual HTTP bodies MUST receive HTTP 422 before mutation. Unknown
tags and structurally valid domain-owned values MUST keep existing acceptance.

#### Scenario: A typed caller constructs a malformed hint

- **WHEN** create, replace or tag-supplying patch construction supplies a hint rejected by its shared structural check
- **THEN** Pydantic construction fails before any request is sent

#### Scenario: A malformed hint reaches the server

- **WHEN** an individual API request body contains a malformed policy hint
- **THEN** the server rejects it with HTTP 422
- **AND** no metadata or provider configuration changes

#### Scenario: A document carries the same malformed hint

- **WHEN** a raw document entry carries a hint rejected by the shared structural check
- **THEN** validate-only reports its existing field-specific structured problem
- **AND** import retains HTTP 400 and changes nothing

#### Scenario: A hint is structurally valid but domain-specific

- **WHEN** a hint passes structural checks but names a family, field or period no reading domain supports
- **THEN** model validation accepts it
- **AND** the reading domain retains responsibility for its meaning

#### Scenario: A patch leaves policy tags alone

- **WHEN** patch construction omits policy tags
- **THEN** model validation does not require replacement tags
- **AND** the write retains stored tags

### Requirement: Provider validation remains service-owned

Handler registration, provider-specific configuration validation and semantics
requiring stored state MUST remain service-owned. Pool model hint validation
MUST NOT import service or provider implementations. Asking-rate structural
validation MUST be contracts-owned while its resolution behavior remains unchanged.

#### Scenario: Provider knowledge is needed

- **WHEN** a structurally valid typed request names an unregistered provider or invalid provider-owned configuration
- **THEN** the service refuses it through the existing boundary with HTTP 400
- **AND** the contracts model gains no dependency on provider implementations

#### Scenario: An asking rate is resolved

- **WHEN** the authority resolves a declared asking rate
- **THEN** it uses the contracts-owned structural entry check
- **AND** its domain checks, accepted publication periods and source precedence remain unchanged

### Requirement: Configuration handlers follow the non-destructive lifecycle

The pool configuration handler protocol MUST support validation, reads and
same-provider replacement without exposing a standalone configuration-deletion
operation. Disablement MUST retain configuration needed to resolve existing work.

#### Scenario: A handler implements pool configuration

- **WHEN** a provider implements the pool configuration protocol
- **THEN** no deletion operation is required or exposed by that protocol

#### Scenario: A pool is disabled

- **WHEN** an operator disables a pool
- **THEN** its provider configuration remains available for existing work
