## ADDED Requirements

### Requirement: Buyer profile state follows XDG and restrictive permissions

Ephemeral and long-running buyer deployments MUST resolve profile metadata from the configured XDG data boundary and buyer public configuration from the configured XDG config boundary. Profile metadata and credential secret files MUST be mounted separately. Metadata directories and files MUST be owned by the buyer process identity and deny group/other writes; secret files MUST be regular non-symlink files owned by that identity with no group or other permission bits.

A deployment MUST fail before authenticated buyer work when the store version, ownership, permissions, selected profile, or credential-provider reference is invalid. Multiple processes MUST use atomic replacement and store-level serialization rather than accepting concurrent partial writes.

#### Scenario: Headless buyer mounts profile and secret state

- **WHEN** an orchestrated buyer uses a strict file credential provider
- **THEN** it receives a persistent XDG profile metadata mount and a distinct owner-only secret file mount, while generated public configuration contains only the provider reference

#### Scenario: Secret mount is a symlink

- **WHEN** the configured credential path resolves through a symlink
- **THEN** startup or command resolution fails before the secret is read or authenticated work begins

### Requirement: Credential provider deployment is explicit

Deployment and generated role configuration MUST select exactly one credential provider for each profile credential reference: OS keyring, strict secret file, or explicit environment-name reference. Local interactive defaults MAY select OS keyring only when available and requested. Headless examples MUST use an explicit strict file or environment reference. Runtime and deployment MUST NOT fall back between keyring, file, environment, wallet, legacy identity, or embedded values.

Kubernetes and Compose secret injection MUST expose the secret only to the buyer process that resolves it. ConfigMaps, Helm values, generated TOML, image layers, arguments, logs, probes, examples, and marketplace release artifacts MUST contain only safe provider kinds and references.

#### Scenario: Environment reference is missing

- **WHEN** a headless deployment selects an exact environment-name reference but does not inject that variable into the buyer process
- **THEN** the buyer fails before authenticated work without consulting another secret source

#### Scenario: Keyring is selected in a keyring-less container

- **WHEN** an operator explicitly deploys a profile whose credential provider is unavailable OS keyring
- **THEN** readiness or command startup fails actionably rather than reading a mounted file or environment fallback

### Requirement: Buyer profile cutover is explicit and atomic

Migration tooling MUST preview legacy identity input, credential availability, derived-principal equality, duplicate/conflict conditions, XDG destinations, and permission changes without mutating either source. A write MUST create or update the complete profile store atomically, preserve the legacy source until the new store validates, and require explicit operator removal of rejected runtime identity fields before the clean-cutover release runs.

Old and new identity resolution MUST NOT coexist at runtime. Rollback before authenticated activation MAY restore the prior release and legacy configuration together. After new runs record profile IDs and principal history, recovery MUST roll forward with the profile store and MUST NOT downgrade those run logs to raw legacy identity.

#### Scenario: Migration preview detects mismatch

- **WHEN** the legacy public principal differs from the selected credential-derived principal
- **THEN** preview reports the exact public mismatch without displaying the secret and write performs no mutation

#### Scenario: New-profile run has started

- **WHEN** a buyer run has durably recorded a profile ID and exact principal
- **THEN** rollback does not discard the profile store or reinterpret the run through legacy `[Identity]`

## MODIFIED Requirements

### Requirement: Identity configuration separates public and secret material

Every deployed service role MUST resolve a supported public principal and trust pins from ordinary profile configuration and its private signer credential from an approved Secret boundary. Every buyer role MUST instead select a versioned local buyer profile whose metadata contains public principals and exact credential-provider references; the selected provider alone resolves private material. Wallet and chain configuration MUST remain optional and separate. ConfigMaps, rendered command arguments, image layers, release artifacts, logs, probes, generated TOML, profile metadata, and examples MUST NOT contain private signing material or resolved environment/keyring/file values.

#### Scenario: Fiat-only storefront is rendered

- **WHEN** a profile enables only Ed25519 marketplace identity and hosted non-EVM settlement
- **THEN** Helm/Compose rendering requires the identity Secret reference but no wallet, chain, RPC, deployed-address, or gas configuration

#### Scenario: Identity secret is missing

- **WHEN** a role has a public principal but cannot load matching private credential material
- **THEN** startup fails before serving authenticated routes, publishing, negotiating, or submitting settlement operations

#### Scenario: A service-peer profile is rendered

- **WHEN** a storefront and provisioning authority are configured to trust one another
- **THEN** ordinary configuration contains each exact scheme-tagged public principal and site trust binding, while each role's matching signer credential is supplied only through its own Secret boundary

#### Scenario: Buyer profile is rendered

- **WHEN** a headless buyer deployment selects an existing local profile
- **THEN** public configuration and profile metadata expose only canonical principals and the exact credential reference while the secret is mounted or injected through the selected provider boundary

### Requirement: Identity migrations are coordinated and fail closed

Each owning service MUST migrate its identity-bearing rows through its own ordered migration chain while preserving cross-service opaque IDs and provider-operation identity. The buyer profile store and versioned buyer run logs MUST each have an explicit failure-atomic migration path preserving exact principals, stable local profile IDs, authority payer bindings, run identities, and operation identities. Authorities and buyers MUST reject old schema, old signature versions, drift, ambiguous principals, duplicate active ownership, principal/credential mismatch, or partially migrated state. Production cutover MUST quiesce authenticated mutations until all required stores, authorities, and clients report the new identity capability.

#### Scenario: One authority remains on the old signature contract

- **WHEN** deployment readiness detects a registry, storefront, service peer, or hosted authority that lacks the pinned identity version
- **THEN** the affected workflow remains unavailable rather than downgrading or submitting a legacy proof

#### Scenario: Migration encounters conflicting owners

- **WHEN** two address-only rows would create an invalid active-principal ownership relation
- **THEN** that service migration rolls back completely and readiness remains false

#### Scenario: Buyer import conflicts with an existing profile

- **WHEN** legacy identity import would duplicate an active principal or profile name
- **THEN** the complete profile-store update rolls back and the legacy source remains unchanged

#### Scenario: Run-log migration cannot bind a profile

- **WHEN** an existing recoverable run's exact principal cannot be assigned to one retained profile history
- **THEN** migration fails without rewriting the run or accepting mixed recovery state

### Requirement: Generated configuration has one source of truth

Typed configuration metadata MUST generate role-appropriate init templates, dotted-path editing validation, environment/Helm schema fragments, and reference tables. Buyer outputs MUST generate profile-store/XDG and credential-provider reference inputs and MUST exclude direct legacy `[Identity]` and resolved secret values. Generated outputs MUST be checked for drift in CI and MUST omit secret values and fields not applicable to the role.

#### Scenario: Mechanism field changes

- **WHEN** a mechanism's typed configuration adds or removes an operator field
- **THEN** drift validation requires the applicable templates, schema, and reference output to change together

#### Scenario: Buyer credential provider changes

- **WHEN** the approved buyer credential-reference vocabulary changes
- **THEN** profile commands, role templates, schema fragments, deployment examples, and reference output must change together without emitting a secret value
