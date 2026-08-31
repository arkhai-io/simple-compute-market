## ADDED Requirements

### Requirement: Buyer profile store and provider failures are deterministic

Focused identity tests MUST cover versioned profile-store creation, import, selection, update, rotation, retirement, deletion, restart, and recovery with deterministic filesystem and credential-provider controls. They MUST cover atomic replacement, interrupted writes, malformed and unsupported stores, duplicate profile/name/principal, strict ownership and permissions, symlink rejection, unavailable provider, missing exact secret, principal mismatch, generated-secret cleanup, rotation overlap, active-run and hosted-binding retention, and deletion refusal.

Tests MUST assert public metadata and behavior without reading secrets through a second path, relaxing permissions, patching domain-local identity loaders, or emitting secret values in failures.

#### Scenario: Store replacement is interrupted

- **WHEN** the deterministic filesystem seam fails after candidate validation but before atomic replacement
- **THEN** the prior store remains valid after restart and no partial selected profile or credential reference is accepted

#### Scenario: Credential provider is unavailable

- **WHEN** the selected keyring, strict file, or explicit environment provider cannot resolve its exact reference
- **THEN** signer resolution fails under that provider and test evidence proves no fallback provider was called

#### Scenario: Active run retains predecessor

- **WHEN** rotation promotes a replacement while a recoverable fixture run records the prior principal
- **THEN** fresh-run resolution uses the replacement and exact recovery continues to resolve the predecessor until retirement becomes eligible

#### Scenario: Profile metadata changes

- **WHEN** a profile is renamed, selected, migrated, or reloaded after restart
- **THEN** its random opaque UUID remains unchanged and is never recomputed from name, principal, credential reference, or provider state

### Requirement: Multi-domain buyer injection uses one conformance matrix

The shared buyer-domain conformance suite MUST exercise every shipped buyer plugin with the same persistent-profile cases: fresh selected primary, missing selection, principal/credential mismatch, retained-principal resume, selected-profile change after run creation, legacy direct identity rejection, and secret-free carrier output. Domain-specific suites MUST add only schema-owned behavior and MUST NOT duplicate or bypass identity resolution.

#### Scenario: VM and API-credit buyers use one profile

- **WHEN** the conformance matrix runs both shipped domain plugins against the same selected Ed25519 profile
- **THEN** both receive the same canonical signer through core injection and their run logs contain only stable profile ID and public principal metadata

#### Scenario: Domain fixture contains raw identity

- **WHEN** a migrated plugin test fixture still supplies `[Identity]` or a raw private field
- **THEN** the fixture fails at configuration validation and cannot establish a second identity path

### Requirement: Buyer profile secret canaries cover every carrier

Credential canaries MUST prove that private seeds, private keys, keyring values, file contents, and environment values do not enter profile metadata, run-log JSONL, generated TOML, listings, negotiation messages, settlement plans, domain results, logs, diagnostics, exception text, reprs, ConfigMaps, Helm/Compose renders, wheels, images, or release artifacts. Public provider kind and bounded locator names MAY appear only where required and MUST not be confused with resolved secret values.

#### Scenario: Fresh and resumed runs are inspected

- **WHEN** VM and API-credit fresh and resumed flows execute with a canary credential under each approved provider
- **THEN** all durable and emitted carriers contain the exact public principal and operation identities but no canary secret

#### Scenario: Provider raises with secret-bearing text

- **WHEN** a credential backend exception includes the resolved secret value
- **THEN** normalization emits only a bounded provider/reference error and canary scanning finds no secret in output or logs

### Requirement: Legacy profile and run-log migrations remain transactional

Migration tests MUST use populated legacy identity and run-log fixtures and prove complete candidate validation, exact principal derivation, stable run/negotiation/settlement/operation identifiers, explicit profile binding, idempotent rerun, and complete rollback on malformed, conflicting, mismatched, interrupted, or ambiguous state. No test MAY accept mixed legacy runtime identity and profile-based resolution after cutover.

#### Scenario: Existing run binds uniquely

- **WHEN** migration finds one exact imported profile history matching the run's recorded principal
- **THEN** it records the stable profile ID without changing the run, negotiation, settlement, or operation identity

#### Scenario: Existing run is ambiguous

- **WHEN** a recoverable run cannot be assigned to exactly one profile principal history
- **THEN** migration rolls back all candidate run-log and profile changes and runtime remains unavailable
