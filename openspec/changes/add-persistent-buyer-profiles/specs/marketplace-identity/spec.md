## ADDED Requirements

### Requirement: Versioned local buyer profile store

The marketplace identity capability MUST provide a versioned local buyer-profile metadata store under the platform's XDG data boundary. Each profile MUST receive a random opaque UUID at creation and preserve that stable local profile ID across rename, selection, migration, and restart; it also has a unique user-visible name, lifecycle state, selected-state projection, one primary canonical principal, complete principal history, credential references, and per-authority opaque payer bindings. The local profile ID, hosted payer binding, credential reference, and provider resource MUST NOT be interpreted as a marketplace principal or credential.

Profile metadata updates MUST validate the complete candidate and replace it atomically with restrictive owner-only permissions. A malformed, unsupported-version, duplicate-name, duplicate active principal, or interrupted write MUST leave the last valid store unchanged. One canonical principal MUST NOT be primary in more than one active local profile.

#### Scenario: Profile store is created

- **WHEN** a buyer creates the first valid named profile
- **THEN** the store records its stable profile ID, public principal, credential reference, and lifecycle metadata atomically without private signing material

#### Scenario: Store write is interrupted

- **WHEN** profile creation or update fails before atomic replacement completes
- **THEN** the prior valid store remains readable and no partial profile or selected pointer is accepted

#### Scenario: Principal already belongs to another profile

- **WHEN** a caller attempts to create or import an active profile whose canonical principal is already active in the store
- **THEN** the operation fails without changing either profile

### Requirement: Credential references use explicit approved providers

A buyer profile credential reference MUST select exactly one approved provider and provider-owned locator. Approved providers are OS keyring for durable local use, a strict owner-readable secret file for headless use, and an explicit environment-name reference for orchestrated injection. Resolution MUST NOT fall back to another provider, raw metadata value, wallet field, default environment variable, or legacy `[Identity]` secret when the selected provider is unavailable or invalid.

The secret-file provider MUST reject symlinks, non-regular files, files not owned by the current user, and any group or other permission bits. The environment provider MUST store only the bounded variable name and MUST fail when that exact variable is absent. Provider errors and object representations MUST not include secret values.

#### Scenario: Keyring entry is missing

- **WHEN** a profile selects a keyring reference whose entry is unavailable
- **THEN** signer resolution fails actionably without trying a file, environment variable, or wallet

#### Scenario: Headless secret file is group-readable

- **WHEN** a file credential has any group or other permission bit
- **THEN** the provider rejects it before reading or constructing a signer

#### Scenario: Environment reference is configured

- **WHEN** a profile selects an explicit environment-name reference and that variable contains a valid credential
- **THEN** the provider constructs the matching signer while the metadata store and diagnostics retain only the variable name

### Requirement: Profile creation and explicit legacy import are failure-atomic

Profile creation MUST support generating an Ed25519 keypair through a selected writable credential provider and importing an existing supported credential reference. Key generation MUST write the private seed only through that provider, derive and verify the canonical public principal, then atomically commit public metadata. If metadata commit fails after a newly generated secret is stored, the operation MUST remove that unreferenced secret or report a bounded cleanup-required failure without selecting or exposing it.

Legacy `[Identity]` import MUST be explicit. It MUST resolve the declared credential through the selected provider, derive the principal, compare the exact canonical `{scheme, identifier}` with the legacy public identity, validate all duplicate/conflict conditions, and write the profile only after the complete candidate is valid. Import MUST NOT establish runtime fallback or precedence for legacy configuration.

#### Scenario: Imported credential does not match principal

- **WHEN** the credential-derived principal differs by scheme or identifier from the declared legacy principal
- **THEN** import aborts without writing profile metadata, selecting a profile, or changing the credential

#### Scenario: Metadata commit fails after generation

- **WHEN** a generated Ed25519 seed is stored but profile metadata cannot be committed
- **THEN** the unreferenced generated entry is removed when safe or a bounded cleanup-required result identifies only its credential reference

#### Scenario: Completed import is repeated

- **WHEN** the same exact legacy identity and credential reference are imported again
- **THEN** the operation converges on the existing profile or reports an exact duplicate without creating another profile or principal record

### Requirement: Buyer profile lifecycle preserves signer history

Profile selection MUST affect only fresh buyer runs. Rotation MUST use the shared canonical dual-proof intent and prove possession of both the current primary and replacement signers before making the replacement primary. The prior principal and credential reference MUST remain retained while any recoverable run, authority payer binding, bounded overlap, or incomplete authority rotation requires it. Retirement of one named non-primary predecessor MUST prevent new resolution and MUST fail while a required run or binding still depends on it.

Whole-profile retirement is a distinct transition. It MUST fail until every principal and binding is retirement-eligible; on success it MUST mark the profile retired and atomically clear its selected pointer, including in a one-profile store. Profile deletion MUST require this retired, unselected state and MUST also fail when the profile has recoverable runs, retains an active or incompletely rotated authority binding, or owns principal history required for audit or recovery. Deletion MAY remove only metadata and credential entries the user explicitly authorizes and the provider confirms are not shared; it MUST never silently export or erase a credential.

#### Scenario: New run follows rotation

- **WHEN** dual-proof rotation promotes a replacement principal
- **THEN** subsequent fresh runs use the replacement while an earlier run remains bound to its recorded predecessor

#### Scenario: Active run blocks retirement

- **WHEN** a recoverable run records the predecessor principal
- **THEN** retirement and credential deletion are refused until that run is no longer recoverable or an explicit supported recovery transition removes the dependency

#### Scenario: Hosted binding has not rotated

- **WHEN** a profile has an authority payer binding still owned by the predecessor
- **THEN** local retirement fails rather than stranding hosted payer control

#### Scenario: Selected one-profile store is retired

- **WHEN** the selected profile is the store's only profile and all principal, run, and authority-binding retirement blockers have cleared
- **THEN** whole-profile retirement marks it retired and clears selection in one atomic store replacement so a later confirmed metadata deletion is reachable

### Requirement: Hosted payer bindings remain opaque profile metadata

A buyer profile MAY record one authority/environment-scoped opaque hosted payer binding and safe lifecycle metadata needed to coordinate ownership. The store MUST NOT contain a Stripe Customer, PaymentMethod, mandate, bank or card detail, provider payload, client secret, raw action URL, funding operation, or seller-visible correlation value. Hosted payer bindings MUST NOT authorize marketplace requests and MUST be accessed only through the profile owner and the registered hosted consumer.

#### Scenario: Hosted binding is stored

- **WHEN** an authorized hosted consumer associates a payer profile with the selected local buyer profile
- **THEN** metadata records only the authority/environment key, opaque binding, bound marketplace principal, and safe lifecycle state

#### Scenario: Provider data is offered as binding metadata

- **WHEN** a caller attempts to store a Customer ID, PaymentMethod ID, mandate payload, bank detail, or action URL
- **THEN** strict profile validation rejects the update without changing the store

## MODIFIED Requirements

### Requirement: Identity secrets never enter durable public carriers

Private signing material MUST be supplied through an approved explicit credential-provider reference, consumed only to construct the selected signer, and MUST NOT appear in principals, buyer-profile metadata, hosted payer bindings, request bodies, database rows, run logs, listing or negotiation payloads, settlement plans, release artifacts, diagnostics, reprs, ConfigMaps, generated TOML, or public examples. Public principals, provider kind and bounded locator references, trust pins, and opaque hosted bindings MAY appear only in their role-authorized ordinary metadata carriers.

#### Scenario: Recovery state is persisted

- **WHEN** a buyer or storefront records resumable operation state
- **THEN** the record contains the canonical public principal and operation identity but no private signing material

#### Scenario: Buyer profile is displayed

- **WHEN** a user lists or shows local profiles
- **THEN** output contains public profile and principal metadata plus redacted credential references but no resolved secret or provider object representation
