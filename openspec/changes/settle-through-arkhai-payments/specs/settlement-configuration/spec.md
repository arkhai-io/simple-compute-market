## REMOVED Requirements

### Requirement: Hosted options use exact funding profiles

**Reason**: `fiat.stripe.v1` and its provider-specific funding profiles are removed.

**Migration**: Configure an installed settlement mechanism instead. Stripe settings are not aliases for `arkhai.payments.v1`.

### Requirement: Hosted profile readiness is independent and exact

**Reason**: The Stripe hosted-client manifest, profile, and funding-authorization contract is removed.

**Migration**: Each remaining mechanism reports its own typed readiness through its registration.

### Requirement: Buyer hosted compatibility includes local payer readiness

**Reason**: Buyer-local Stripe payer bindings and funding-profile selection are removed.

**Migration**: Buyer compatibility is evaluated against the selected mechanism's advertised option and installed registration.

### Requirement: Buyer off-session automation policy is explicitly bounded

**Reason**: The Stripe off-session payer automation contract is removed.

**Migration**: Arkhai payments approval uses the buyer's owner-scoped credentials and explicit approval; it does not inherit the old profile automation policy.

### Requirement: Hosted consumer configuration pins the expanded release

**Reason**: The hosted Stripe client, manifest, and release-pin model is removed.

**Migration**: The Arkhai payments kit consumes the payments service's published API contract; no Stripe release configuration remains in marketplace roles.

### Requirement: A payer submits its own instrument setup verification

**Reason**: Payer instrument setup and verification are owned by the removed Stripe integration.

**Migration**: Configure and approve Arkhai payment mandates through the `arkhai.payments.v1` mechanism.

### Requirement: Peer mechanism configuration hierarchy

**Reason**: Its only non-Alkahest peer is `fiat.stripe.v1`, which is removed.

**Migration**: Use the explicit typed settlement configuration and peer mechanism identifiers defined below.

### Requirement: Mechanism-owned typed registration

**Reason**: The hosted Stripe registration, readiness, and clause-projection examples are removed with that mechanism.

**Migration**: Register Arkhai payments and other supported mechanisms through the typed shared registration surface.

### Requirement: Mechanism-specific utilities stay namespaced

**Reason**: Its Stripe onboarding command is removed with the hosted settlement integration.

**Migration**: Keep any installed mechanism diagnostics under that mechanism's registration namespace.

### Requirement: Unified seller settlement commands

**Reason**: Stripe onboarding and hosted seller command behavior are removed.

**Migration**: Use one common seller status surface over enabled mechanism registrations.

### Requirement: Recovery uses pinned mechanism identity

**Reason**: Its selected funding-profile and hosted-authorization recovery contract is removed.

**Migration**: Recovery follows the mechanism and option pinned by the accepted Agreement.

## MODIFIED Requirements

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

## ADDED Requirements

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

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and MUST declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition; it MUST NOT interpret chain-, arbiter-, condition-, or financial-authority fields.

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

The storefront CLI MUST expose one `settlement status` summary and mechanism-owned subcommands under `settlement <mechanism>`. Alkahest checks MUST use its configured wallet/chains only when invoked or enabled. A separate hosted seller executable and top-level mechanism-specific publication flow MUST NOT remain after cutover.

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

A listing MUST advertise settlement choices through `settlement_options` with the shared fields `{option_id, mechanism, asset, rates, params}`. The accepted Agreement MUST select one exact option. The core MUST NOT interpret mechanism-specific values in `params`. Alkahest's option parameters MUST carry its accepted escrow forms, arbiter demands, and oracle address rather than listing-level `accepted_escrows`, `demands`, or `oracle_address` fields. An `arkhai.payments.v1` option MUST carry the mechanism-owned payee account, hold window, and agreement-deposit setting needed to derive and disclose its payment policy.

#### Scenario: Alkahest option is published

- **WHEN** a seller publishes an Alkahest settlement choice
- **THEN** its escrow forms, demands, and oracle address are carried by that option's `params`, not by parallel core listing fields

#### Scenario: Arkhai payment option is published

- **WHEN** a seller publishes an `arkhai.payments.v1` option
- **THEN** the option identifies its payee account, declared hold window, and agreement-deposit setting while core exposes only the shared option envelope
