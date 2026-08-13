## Purpose

Define one typed operator and consumer contract for configuring, validating, inspecting, migrating, publishing, and selecting independently implemented settlement mechanisms.

## ADDED Requirements

### Requirement: Peer mechanism configuration hierarchy

Settlement configuration MUST have one root containing a duplicate-free ordered list of canonical mechanism IDs and one typed subsection per installed mechanism. `alkahest.v1` MUST map to `[Settlement.alkahest]` and `fiat.stripe.v1` MUST map to `[Settlement.stripe]`. Identity, wallet, and chain resources MUST remain outside mechanism subsections. New defaults MUST enable no mechanism or implicit priority; initialization MUST require an explicit choice, while legacy migration MUST preserve the effective enabled set and order. Unknown mechanism IDs, unknown keys, duplicate priority entries, and role-inapplicable required fields MUST fail validation.

#### Scenario: Seller enables hosted fiat only

- **WHEN** `[Settlement].priority` contains `fiat.stripe.v1`, the Stripe subsection is valid/enabled, and Alkahest is disabled
- **THEN** seller configuration is valid with no wallet or chain section

#### Scenario: Priority names an uninstalled mechanism

- **WHEN** configuration names a mechanism for which the composition root has no registration
- **THEN** startup and publication fail with the unknown canonical mechanism ID

#### Scenario: New config has no mechanism choice

- **WHEN** an operator generates or starts from defaults without selecting a settlement mechanism
- **THEN** no mechanism is enabled or preferred and publication/settlement remains unavailable until configuration is explicit

### Requirement: Mechanism-owned typed registration

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, and any mechanism-specific operator commands. The shared foundation MUST own only registration, ordering, common status, and composition; it MUST NOT interpret chain-, provider-, arbiter-, condition-, or financial-authority fields.

#### Scenario: Stripe readiness is evaluated

- **WHEN** the common status command preflights `fiat.stripe.v1`
- **THEN** the hosted adapter validates its trust/account/condition contract and returns a common sanitized result without shared code importing provider behavior

### Requirement: Common sanitized mechanism readiness

Preflight for every mechanism MUST report canonical mechanism ID, configured, enabled, ready, stable blocker codes/messages, capabilities, and contract/schema versions, with only allowlisted safe public detail. A status check MUST be observational and MUST NOT publish, create Account Links or Checkout sessions, submit chain/provider mutations, change settlement state, or expose credentials, provider IDs, private RPC data, transient URLs, or administrator state.

#### Scenario: Enabled mechanism is not ready

- **WHEN** a required public trust pin, account readiness result, wallet/chain dependency, deployed address, or capability is absent
- **THEN** status reports `ready=false` and the mechanism-owned sanitized blocker without performing a side effect

### Requirement: Priority orders choices but never changes accepted settlement

Storefront publication MUST emit options for every enabled and ready mechanism in configured priority order. Buyer compatibility/selection MUST use the same canonical mechanism vocabulary and MAY use priority as policy input. Accepted Terms MUST pin one exact option, and no current configuration, readiness loss, or later priority change MAY switch the mechanism of an accepted or in-flight obligation.

#### Scenario: One of two enabled mechanisms is unready

- **WHEN** one mechanism preflight fails and the other is ready
- **THEN** publication suppresses only the unready mechanism, reports its blocker, and advertises the ready mechanism

#### Scenario: No enabled mechanism is ready

- **WHEN** every enabled mechanism fails preflight
- **THEN** publication fails without replacing existing accepted Terms or starting a settlement

### Requirement: Unified seller settlement commands

The storefront CLI MUST expose one `settlement status` summary and mechanism-owned subcommands under `settlement <mechanism>`. Stripe onboarding/status MUST use the released hosted client and the configured marketplace signer. Alkahest checks MUST use its configured wallet/chains only when invoked or enabled. A separate hosted seller executable and top-level mechanism-specific publication flow MUST NOT remain after cutover.

#### Scenario: Seller onboards Stripe

- **WHEN** the seller invokes `market-storefront settlement stripe onboard`
- **THEN** the storefront client performs owner-authorized hosted onboarding, treats the Account Link as transient, and reports authoritative readiness without exposing provider IDs or retaining the URL

#### Scenario: Seller requests common status

- **WHEN** both mechanisms are installed
- **THEN** one machine-readable response contains a common result for each in configured order plus mechanism-owned sanitized blockers

### Requirement: Uniform configuration precedence and secret placement

Resolution MUST apply declared CLI overrides, then environment/Secret overlay, then role/user TOML, then committed defaults; a higher-layer list MUST replace the lower list. Public identity, authority, manifest, capability, account reference, currency, condition profile, chain name, and deployed-address configuration MAY be ordinary values. Private identity/wallet/request credentials MUST come from approved secret files or environment/Secret overlays and MUST never appear in generated public templates, ConfigMaps, status, source reports, logs, or release artifacts. Hosted provider/admin/webhook secrets MUST be rejected by marketplace schemas.

#### Scenario: Environment replaces priority

- **WHEN** an environment overlay supplies a valid priority list over TOML
- **THEN** the entire ordered list is replaced and the resolved source is reportable without revealing any secret value

### Requirement: Explicit atomic configuration migration

Each affected role MUST provide a dry-run and write mode that maps legacy hosted and Alkahest settlement settings to the typed hierarchy, derives canonical priority, leaves identity/wallet/chains in their owning namespaces, preserves unrelated configuration, redacts secrets, refuses conflicting old/new values, validates the complete result, writes and backs up with restrictive permissions, and replaces atomically. Repeating migration MUST be a no-op. Runtime and config editing MUST reject legacy paths after cutover with the exact migration command.

#### Scenario: Migration preview is requested

- **WHEN** an operator runs config migration in check mode
- **THEN** it reports every moved/removed key and conflict with secret values redacted and changes no file

#### Scenario: Old and new values conflict

- **WHEN** a legacy key and its destination both exist with different values
- **THEN** migration aborts without modifying the source or backup and identifies both key paths

#### Scenario: Migration is repeated

- **WHEN** a successfully migrated file is processed again
- **THEN** the tool reports no changes and preserves byte-equivalent effective configuration

### Requirement: Recovery uses pinned mechanism identity

Run logs MAY record configuration-schema version, public resolved mechanism set, and source-free fingerprints, but MUST NOT store secrets. Recovery MUST use the accepted plan's canonical mechanism, obligation, and operation identities rather than current priority, current enablement, or another mechanism's readiness.

#### Scenario: Priority changes during a funded obligation

- **WHEN** recovery resumes an obligation after another mechanism becomes first priority
- **THEN** it resumes the originally pinned mechanism and stable operation identity without fallback
