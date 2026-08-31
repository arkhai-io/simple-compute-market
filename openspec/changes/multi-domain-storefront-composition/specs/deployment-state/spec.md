## ADDED Requirements

### Requirement: Multi-domain storefront configuration is explicit
A compute-family storefront deployment MUST configure a non-empty set of domain registrations, each with one offering mode, exact domain identity, supported market-contract version, and installed package contribution. It MUST configure trusted site authority/principal bindings independently. Startup MUST reject duplicate modes or identities, missing packages or capabilities, unsupported versions, secret-bearing domain metadata, and any recoverable durable binding not supplied by the configuration.

#### Scenario: Combined VM and bare-metal deployment starts
- **WHEN** the image contains both exact domain distributions and configuration registers `vm` and `bare_metal` with complete trusted sites
- **THEN** one storefront process becomes ready with both registrations and reports their safe identities, versions, modes, and blockers

#### Scenario: Only one domain is configured
- **WHEN** an operator intentionally deploys the combined runtime with one explicit supported registration
- **THEN** it runs the same registry and selector without an inferred default, hidden second domain, or singleton code path

#### Scenario: A configured package is absent
- **WHEN** configuration names a domain contribution that is not installed or does not export the declared exact contract
- **THEN** startup fails before migrations, publication, recovery, or network mutation and identifies the missing contribution

### Requirement: Storefront domain-binding migration is transactional and explicit
The storefront-owned ordered migration chain MUST add immutable binding state for listings, common derived mappings, negotiation threads, and recoverable lifecycle correlation. For a legacy database with no discriminator, an operator MUST provide one exact legacy offering-mode/domain/version binding corresponding to the quiesced source role. The migration MUST validate the complete owned population with that contract before committing, preserve all listing, negotiation, settlement, reservation, fulfillment, and operation identities, and be idempotent on rerun.

The migration MUST refuse missing legacy input, mixed or contradictory artifact kinds, unsupported versions, orphaned relationships, duplicate/colliding derivation identities, or pre-existing conflicting bindings. It MUST NOT infer VM from absence, installed-package count, payload shape alone, or executor defaults. Legacy per-domain mapping tables MUST cease to be writable authorities after successful cutover.

#### Scenario: A legacy VM database is migrated
- **WHEN** the operator explicitly selects the exact VM binding and every listing, thread, accepted artifact, and recoverable lifecycle row validates against it
- **THEN** the migration atomically records that binding and common mapping state while every public and operation identifier remains unchanged

#### Scenario: One legacy row is contradictory
- **WHEN** any candidate artifact, mapping, or relationship cannot validate under the selected legacy binding
- **THEN** the migration rolls back the complete population and reports the offending stable record without leaving mixed bound and unbound state

#### Scenario: Migration is rerun after success
- **WHEN** the same migration runs against the fully bound database
- **THEN** it makes no semantic change and all identifiers and bindings remain byte-equivalent

#### Scenario: Two live databases are offered for merge
- **WHEN** rollout attempts to combine independently writable VM and bare-metal storefront databases
- **THEN** the supported migration refuses the merge; operators must quiesce and select one authoritative source rather than synthesize cross-database ordering or ownership

### Requirement: Multi-domain packaging and rollout are coordinated
The storefront build MUST produce installable wheels and one compute-family image containing the shared shell plus the configured VM and bare-metal domain contributions without editable sibling paths. Compose and Helm configuration/schema/templates MUST render explicit public registrations, trusted site bindings, one storefront database, and the same Recreate/single-writer persistence rule. Domain or signer secrets MUST remain in their existing Secret boundaries and MUST NOT enter registrations, ConfigMaps, image layers, diagnostics, or migration reports.

Rollout MUST stage artifacts, quiesce publication and lifecycle workers, preview and apply the binding migration, verify configured registrations against the migrated binding set and pool-mode/site readiness, then resume effects. Rollback before new effects may restore the prior artifact/config/database set; after effects resume, recovery MUST roll forward under the recorded bindings.

#### Scenario: Helm renders a combined storefront
- **WHEN** both domains and two trusted sites are configured
- **THEN** the rendered workload runs one storefront command and one writable volume, includes both domain packages, and exposes no private credential in public configuration

#### Scenario: A migrated binding lacks a configured contract
- **WHEN** preflight finds a nonterminal row whose binding is absent from the staged registry
- **THEN** activation remains quiesced and identifies the exact missing mode/domain/version

#### Scenario: Rollback is requested after new effects
- **WHEN** the combined process has created a new accepted negotiation, reservation, or fulfillment under recorded bindings
- **THEN** operators recover forward with those bindings rather than restoring an unbound database or changing domain registration to redirect the effect
