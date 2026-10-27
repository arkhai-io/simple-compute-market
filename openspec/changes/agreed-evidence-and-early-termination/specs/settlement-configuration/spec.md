## MODIFIED Requirements

### Requirement: Payments configuration separates accounts and credentials

Shared Arkhai payments registration, typed configuration, and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST contain the trusted service origin, Ed25519 receipt identity, fee policy, and an API-key environment-variable reference, not the resolved credential; the dispute authority is named per option and configured through `[[Dispute]]` defaults. Payment credentials MUST NOT appear in public options, Agreement bytes, run logs, or status.

#### Scenario: Credentials stay out of public surfaces

- **WHEN** a storefront or buyer is configured for Arkhai payments
- **THEN** its configuration names the API key's environment variable only, and the credential appears in no public option, Agreement, run log, or status

### Requirement: Mechanism clause fields stay in their namespace

Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and declare their applicable roles, operators, and value types. The lifecycle term codec's common fields (`adjudication.*`, `early_termination.*`) are the one exception: the codec owns them for every mechanism. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition, and MUST NOT interpret chain-, arbiter-, condition-, or financial-authority fields.

#### Scenario: A mechanism contributes a clause field

- **WHEN** a mechanism adds a publication clause field
- **THEN** the field lives under the mechanism's configuration key with its declared roles, operators, and value types, and the shared grammar composes it without interpreting its value

#### Scenario: A lifecycle term is filtered

- **WHEN** a clause names `early_termination.payer`
- **THEN** the lifecycle codec's projection evaluates it for every mechanism whose options carry the term

### Requirement: Explicit atomic configuration migration

Each affected role MUST provide dry-run and write modes that map still-supported legacy Alkahest settlement settings to the typed hierarchy, derive canonical priority, leave identity/wallet/chains in their owning namespaces, preserve unrelated configuration, redact secrets, refuse conflicting old/new values, validate the complete result, write and back up with restrictive permissions, and replace atomically. Repeating migration MUST be a no-op. Legacy `fiat.stripe.v1` or `[Settlement.stripe]` settings MUST be rejected with an actionable removal diagnostic and MUST NOT be converted to `arkhai.payments.v1`. `[Settlement.alkahest].oracle_gated = true` MUST be mapped to `release_models = ["oracle_gated"]`, `interruptible = true` to `["interruptible"]`, and neither to `["recipient"]`.

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

#### Scenario: The interruptible flag is migrated

- **WHEN** migration encounters `[Settlement.alkahest].interruptible = true`
- **THEN** it writes `release_models = ["interruptible"]` and removes the flag

### Requirement: Each mechanism's option carries its own parameters

Alkahest options MUST carry their escrow policy in mechanism-owned parameters; legacy Alkahest listing fields remain supported by the escrow path and MUST NOT become requirements of Arkhai payments. An `arkhai.payments.v1` option MUST carry the mechanism-owned payee account, approval window, and agreement-deposit setting needed to derive and disclose its payment policy, and its hold follows the option's `adjudication.dispute_window_seconds`.

#### Scenario: Arkhai payment option is published

- **WHEN** a seller publishes an `arkhai.payments.v1` option
- **THEN** the option identifies its payee account, approval window, dispute window, and agreement-deposit setting while core exposes only the shared option envelope

## ADDED Requirements

### Requirement: Dispute authorities are configured as defaults

`[[Dispute]]` entries MUST be ordered by preference, each naming one authority: `interface`, `origin`, `account`, `record_key`, interface-owned `params`, the payment mechanisms it advertises, its minimum dispute window and case hold, and the role's credential reference for filing. A storefront's entries MUST be the authorities its builders offer; a buyer's MUST be the authorities it accepts. The resolved credential MUST NOT appear in any option, Agreement or status.

#### Scenario: A buyer prefers one authority

- **WHEN** a buyer lists two accepted authorities and a listing offers equal options naming each
- **THEN** the buyer selects the option naming its first entry

### Requirement: Alkahest release models are listed per option

`[Settlement.alkahest].release_models` MUST list the release models a storefront offers, drawn from `recipient`, `oracle_gated` and `interruptible`, and the storefront MUST publish one Alkahest option per model. Oracle-address settings MUST be validated against list membership, and a domain that cannot deliver a listed model MUST refuse to start. A listing MUST NOT carry a listing-level interruptible marker.

#### Scenario: A storefront offers two Alkahest release models

- **WHEN** a VM storefront configures `release_models = ["recipient", "interruptible"]`
- **THEN** each listing carries two Alkahest options, only the interruptible one's release condition describes interruption, and the listing resource has no interruptible field
