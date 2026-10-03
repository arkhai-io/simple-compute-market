# Settlement Configuration Specification

## Purpose

Define one typed operator and consumer contract for configuring, validating, inspecting, migrating, publishing, and selecting independently implemented settlement mechanisms.

## Requirements

### Requirement: Payments configuration separates accounts and credentials

Shared Arkhai payments registration, typed configuration, and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST contain trusted service origin, Ed25519 receipt identity, fee policy, dispute authority, and an API-key environment-variable reference, not the resolved credential. Buyer domain input MUST supply `payer_account` independently of marketplace identity and service policy; VM uses `[vms].payer_account` and API credits uses `[apicredits].payer_account`. Seller client ownership MUST come from the accepted option's `payee_account`, not a service-policy account field. Payment credentials MUST NOT appear in public options, Agreement bytes, run logs, or status.

#### Scenario: Buyer chooses a payer account

- **WHEN** an Ed25519 buyer selects `arkhai.payments.v1`
- **THEN** its account travels in `SettlementSelection.params.payer_account` and Agreement `settlement_params`, while its marketplace signer and owner-scoped API credential remain separate

### Requirement: Common sanitized mechanism readiness

Preflight for every mechanism MUST report canonical mechanism ID, configured, enabled, ready, stable blocker codes/messages, capabilities, and contract/schema versions, with only allowlisted safe public detail. A status check MUST be observational and MUST NOT publish, create Account Links or Checkout sessions, submit chain/provider mutations, change settlement state, or expose credentials, provider IDs, private RPC data, transient URLs, or administrator state.

#### Scenario: Enabled mechanism is not ready

- **WHEN** a required public trust pin, account readiness result, wallet/chain dependency, deployed address, or capability is absent
- **THEN** status reports `ready=false` and the mechanism-owned sanitized blocker without performing a side effect

### Requirement: Priority orders choices but never changes accepted settlement

Storefront publication MUST emit options in configured priority order for every enabled and ready mechanism that has a valid publication clause. Buyer compatibility/selection MUST use the same canonical mechanism vocabulary and MAY use priority as policy input. Accepted Terms MUST pin one exact option, and no current configuration, readiness loss, or later priority change MAY switch the mechanism of an accepted or in-flight obligation.

#### Scenario: One of two enabled mechanisms is unready

- **WHEN** one mechanism preflight fails and the other is ready
- **THEN** publication suppresses only the unready mechanism, reports its blocker, and advertises the ready mechanism

#### Scenario: No enabled mechanism is ready

- **WHEN** every enabled mechanism fails preflight
- **THEN** publication fails without replacing existing accepted Terms or starting a settlement

### Requirement: Mechanism clause projections are public and observational

A mechanism's settlement-clause projection MUST derive only deterministic public values from the advertised option and MUST perform no preflight, client construction, RPC/provider call, account mutation, publication, or settlement transition. Credentials, provider IDs, raw URLs, webhook data, private RPC configuration, administrator state, and opaque receipts MUST NOT be declared or projected as clause fields.

#### Scenario: Clause is evaluated during discovery

- **WHEN** buyer discovery evaluates mechanism-qualified predicates across advertised options
- **THEN** evaluation is deterministic from listing data and performs no chain or provider I/O

### Requirement: Uniform configuration precedence and secret placement

Resolution MUST apply declared CLI overrides, then environment/Secret overlay, then role/user TOML, then committed defaults; a higher-layer list MUST replace the lower list. Public identity, authority, manifest, capability, account reference, currency, condition profile, chain name, and deployed-address configuration MAY be ordinary values. Private identity/wallet/request credentials MUST come from approved secret files or environment/Secret overlays and MUST never appear in generated public templates, ConfigMaps, status, source reports, logs, or release artifacts. Hosted provider/admin/webhook secrets MUST be rejected by marketplace schemas.

#### Scenario: Environment replaces priority

- **WHEN** an environment overlay supplies a valid priority list over TOML
- **THEN** the entire ordered list is replaced and the resolved source is reportable without revealing any secret value

### Requirement: Explicit atomic configuration migration

Each affected role MUST provide dry-run and write modes that map still-supported legacy Alkahest settlement settings to the typed hierarchy, derive canonical priority, leave identity/wallet/chains in their owning namespaces, preserve unrelated configuration, redact secrets, refuse conflicting old/new values, validate the complete result, write and back up with restrictive permissions, and replace atomically. Repeating migration MUST be a no-op. Legacy `fiat.stripe.v1` or `[Settlement.stripe]` settings MUST be rejected with an actionable removal diagnostic and MUST NOT be converted to `arkhai.payments.v1`.

#### Scenario: Migration preview is requested

- **WHEN** an operator runs config migration in check mode
- **THEN** it reports every moved/removed key and conflict with secret values redacted and changes no file

#### Scenario: Old and new values conflict

- **WHEN** a legacy Alkahest key and its destination both exist with different values
- **THEN** migration aborts without modifying the source or backup and identifies both key paths

#### Scenario: Migration is repeated

- **WHEN** a successfully migrated file is processed again
- **THEN** the tool reports no changes and preserves byte-equivalent effective configuration

#### Scenario: Stripe settings are encountered

- **WHEN** migration encounters `fiat.stripe.v1` or `[Settlement.stripe]`
- **THEN** it refuses to map those values to Arkhai payments and reports that the obsolete settings must be removed

### Requirement: Settlement configuration selects explicit peer mechanisms

Settlement configuration MUST have one root containing a duplicate-free ordered list of canonical mechanism IDs and one typed subsection per installed mechanism. `alkahest.v1` MUST map to `[Settlement.alkahest]` and `arkhai.payments.v1` MUST map to `[Settlement.arkhai_payments]`. `fiat.stripe.v1` MUST NOT be registered, accepted as an alias, or silently mapped to Arkhai payments. Identity, wallet, and chain resources MUST remain outside mechanism subsections. New defaults MUST enable no mechanism or implicit priority; initialization MUST require an explicit choice, while migration of still-supported settings MUST preserve the effective enabled set and order. Unknown mechanism IDs, unknown keys, duplicate priority entries, and role-inapplicable required fields MUST fail validation.

#### Scenario: Seller enables Arkhai payments only

- **WHEN** `[Settlement].priority` contains `arkhai.payments.v1`, its typed subsection is valid and enabled, and Alkahest is disabled
- **THEN** seller configuration is valid without a wallet or chain section

#### Scenario: Priority names an uninstalled mechanism

- **WHEN** configuration names a mechanism for which the composition root has no registration, including `fiat.stripe.v1`
- **THEN** startup and publication fail with the unknown canonical mechanism ID and do not substitute another mechanism

#### Scenario: New config has no mechanism choice

- **WHEN** an operator generates or starts from defaults without selecting a settlement mechanism
- **THEN** no mechanism is enabled or preferred and publication/settlement remains unavailable until configuration is explicit

### Requirement: Mechanism registrations own typed configuration and readiness

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. A client factory and accepted-obligation/verifier hooks MAY be absent for an Agreement-based stage that does not use the conditional-escrow runtime. Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and MUST declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition; it MUST NOT interpret chain-, arbiter-, condition-, or financial-authority fields.

#### Scenario: Arkhai payments readiness is evaluated

- **WHEN** common status preflights `arkhai.payments.v1`
- **THEN** its registration returns a common sanitized result without exposing an API credential or performing a payment mutation

#### Scenario: Agreement-deposit preference is evaluated

- **WHEN** a buyer clause filters on the public agreement-deposit setting of an advertised `arkhai.payments.v1` option
- **THEN** the mechanism registration projects that typed option value and shared selection compares it without interpreting opaque parameters

### Requirement: Mechanism-specific commands stay registration-owned

Seller and buyer CLIs MUST expose common settlement status and normal lifecycle commands without mechanism-specific flags. Setup, diagnostics, raw inspection, and raw mutation operations that are genuinely mechanism-specific MUST live under `settlement <mechanism>` and MAY consume only that registration's typed configuration and resources. A mechanism namespace MUST NOT create a separate publication path, settlement lifecycle, priority model, or accepted-agreement interpretation.

#### Scenario: Arkhai payment diagnostics are invoked

- **WHEN** an operator invokes a mechanism-specific Arkhai payment diagnostic
- **THEN** it runs through the `arkhai.payments.v1` registration and does not alter common publication, priority, or Agreement semantics

#### Scenario: Buyer inspects an Alkahest escrow

- **WHEN** the buyer invokes the raw escrow inspection utility
- **THEN** it resolves under `market settlement alkahest` and no raw escrow command remains at the top level

### Requirement: Common seller status covers enabled mechanisms

The storefront CLI MUST expose one `settlement status` summary and mechanism-owned subcommands under `settlement <mechanism>`. Alkahest checks MUST use its configured wallet/chains only when invoked or enabled. Normal publication MUST remain mechanism-neutral.

#### Scenario: Seller requests common status

- **WHEN** Alkahest and `arkhai.payments.v1` are both installed
- **THEN** one machine-readable response contains a common result for each in configured order plus mechanism-owned sanitized blockers

#### Scenario: Seller invokes an Alkahest check

- **WHEN** the seller invokes an Alkahest check
- **THEN** the command uses Alkahest's configured wallet and chain resources without making those resources prerequisites for Arkhai payments

### Requirement: Recovery follows the accepted settlement option

Run logs MAY record configuration-schema version, the public resolved mechanism set, the selected settlement option, and non-secret mechanism references, but MUST NOT store credentials, provider data, or raw actions. Recovery MUST use the accepted Agreement's exact mechanism, settlement option, opaque parameters, and stable operation identity rather than current priority, current readiness, or another mechanism's state.

#### Scenario: Priority changes during an Arkhai payment

- **WHEN** recovery resumes a transaction after another mechanism becomes first priority
- **THEN** it continues with the accepted `arkhai.payments.v1` option and the same transaction ID without fallback

#### Scenario: A mechanism is disabled for new agreements

- **WHEN** recovery resumes an accepted operation after its mechanism is disabled for new deals
- **THEN** it continues under the accepted mechanism and exact operation identity rather than converting the Agreement to another mechanism

### Requirement: Settlement options keep mechanism-owned parameters opaque

A listing MUST advertise settlement choices through `settlement_options` with the shared fields `{option_id, mechanism, asset, rates, params}`. The accepted Agreement MUST select one exact option. The core MUST NOT interpret mechanism-specific values in `params`. Alkahest options carry their escrow policy in mechanism-owned parameters; legacy Alkahest listing fields remain supported by the escrow path and MUST NOT become requirements of Arkhai payments. An `arkhai.payments.v1` option MUST carry the mechanism-owned payee account, hold window, and agreement-deposit setting needed to derive and disclose its payment policy.

#### Scenario: Alkahest option is published

- **WHEN** a seller publishes an Alkahest settlement choice
- **THEN** its escrow policy is interpreted by the Alkahest kit, not by Arkhai payments

#### Scenario: Arkhai payment option is published

- **WHEN** a seller publishes an `arkhai.payments.v1` option
- **THEN** the option identifies its payee account, declared hold window, and agreement-deposit setting while core exposes only the shared option envelope
