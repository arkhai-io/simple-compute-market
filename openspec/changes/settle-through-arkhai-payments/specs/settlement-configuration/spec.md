## ADDED Requirements

### Requirement: Agreement attachment is a policy each side owns

The buyer's `attach_agreement` setting, default `false`, MUST be the only control that attaches the Agreement at approval. A seller asks for the Agreement through its payment option's `deposit_agreement` and, when the buyer did not attach it, MUST attach it after verifying the receipt and before any delivery effect.

#### Scenario: A seller configuration sets the buyer's attachment policy

- **WHEN** a seller's `[Settlement.arkhai_payments]` section sets `attach_agreement`
- **THEN** publication preflight reports a blocker, because the setting belongs to the buyer

#### Scenario: The seller deposits what the buyer did not attach

- **WHEN** the selected option sets `deposit_agreement` and the approved transaction has no Agreement attachment
- **THEN** the seller attaches the Agreement after recording the verified receipt and before any delivery effect

### Requirement: Common seller status covers enabled mechanisms

The storefront CLI MUST expose one `settlement status` summary and mechanism-owned subcommands under `settlement <mechanism>`. Alkahest checks MUST use its configured wallet/chains only when invoked or enabled. Normal publication MUST remain mechanism-neutral.

#### Scenario: Seller requests common status

- **WHEN** Alkahest and `arkhai.payments.v1` are both installed
- **THEN** one machine-readable response contains a common result for each in configured order plus mechanism-owned sanitized blockers

#### Scenario: Seller invokes an Alkahest check

- **WHEN** the seller invokes an Alkahest check
- **THEN** the command uses Alkahest's configured wallet and chain resources without making those resources prerequisites for Arkhai payments

### Requirement: Each mechanism's option carries its own parameters

Alkahest options MUST carry their escrow policy in mechanism-owned parameters; legacy Alkahest listing fields remain supported by the escrow path and MUST NOT become requirements of Arkhai payments. An `arkhai.payments.v1` option MUST carry the mechanism-owned payee account, hold window, and agreement-deposit setting needed to derive and disclose its payment policy.

#### Scenario: Arkhai payment option is published

- **WHEN** a seller publishes an `arkhai.payments.v1` option
- **THEN** the option identifies its payee account, declared hold window, and agreement-deposit setting while core exposes only the shared option envelope

### Requirement: Mechanism clause fields stay in their namespace

Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition, and MUST NOT interpret chain-, arbiter-, condition-, or financial-authority fields.

#### Scenario: A mechanism contributes a clause field

- **WHEN** a mechanism adds a publication clause field
- **THEN** the field lives under the mechanism's configuration key with its declared roles, operators, and value types, and the shared grammar composes it without interpreting its value

### Requirement: Mechanism registrations own typed configuration and readiness

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. A client factory and accepted-obligation or verifier hooks MAY be absent for an Agreement-based stage that does not use the conditional-escrow runtime.

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

### Requirement: New configuration chooses no mechanism

New defaults MUST enable no mechanism and no implicit priority; initialization MUST require an explicit choice, while migration of still-supported settings MUST preserve the effective enabled set and order.

#### Scenario: New config has no mechanism choice

- **WHEN** an operator generates or starts from defaults without selecting a settlement mechanism
- **THEN** no mechanism is enabled or preferred and publication/settlement remains unavailable until configuration is explicit

### Requirement: Payment accounts come from domain input and the accepted option

Buyer domain input MUST supply `payer_account` independently of marketplace identity and service policy: VM uses `[vms].payer_account` and API credits `[apicredits].payer_account`. Seller client ownership MUST come from the accepted option's `payee_account`, not a service-policy account field.

#### Scenario: Buyer chooses a payer account

- **WHEN** an Ed25519 buyer selects `arkhai.payments.v1`
- **THEN** its account travels in `SettlementSelection.params.payer_account` and Agreement `settlement_params`, while its marketplace signer and owner-scoped API credential remain separate

### Requirement: Payments configuration separates accounts and credentials

Shared Arkhai payments registration, typed configuration, and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST contain the trusted service origin, Ed25519 receipt identity, fee policy, dispute authority, and an API-key environment-variable reference, not the resolved credential. Payment credentials MUST NOT appear in public options, Agreement bytes, run logs, or status.

#### Scenario: Credentials stay out of public surfaces

- **WHEN** a storefront or buyer is configured for Arkhai payments
- **THEN** its configuration names the API key's environment variable only, and the credential appears in no public option, Agreement, run log, or status

### Requirement: Recovery follows the accepted settlement option

Run logs MAY record configuration-schema version, the public resolved mechanism set, the selected settlement option, and non-secret mechanism references, but MUST NOT store credentials, provider data, or raw actions. Recovery MUST use the accepted Agreement's exact mechanism, settlement option, opaque parameters, and stable operation identity rather than current priority, current readiness, or another mechanism's state.

#### Scenario: Priority changes during an Arkhai payment

- **WHEN** recovery resumes a transaction after another mechanism becomes first priority
- **THEN** it continues with the accepted `arkhai.payments.v1` option and the same transaction ID without fallback

#### Scenario: A mechanism is disabled for new agreements

- **WHEN** recovery resumes an accepted operation after its mechanism is disabled for new deals
- **THEN** it continues under the accepted mechanism and exact operation identity rather than converting the Agreement to another mechanism

### Requirement: Settlement configuration selects explicit peer mechanisms

Settlement configuration MUST have one root with a duplicate-free ordered list of mechanism IDs and one typed subsection per installed mechanism (`alkahest.v1` as `[Settlement.alkahest]`, `arkhai.payments.v1` as `[Settlement.arkhai_payments]`). `fiat.stripe.v1` MUST NOT be registered, aliased, or mapped to Arkhai payments. Identity, wallet, and chain resources MUST stay outside mechanism subsections. Unknown IDs or keys, duplicates, and role-inapplicable required fields MUST fail validation.

#### Scenario: Seller enables Arkhai payments only

- **WHEN** `[Settlement].priority` contains `arkhai.payments.v1`, its typed subsection is valid and enabled, and Alkahest is disabled
- **THEN** seller configuration is valid without a wallet or chain section

#### Scenario: Priority names an uninstalled mechanism

- **WHEN** configuration names a mechanism for which the composition root has no registration, including `fiat.stripe.v1`
- **THEN** startup and publication fail with the unknown canonical mechanism ID and do not substitute another mechanism

### Requirement: Settlement options keep mechanism-owned parameters opaque

A listing MUST advertise settlement choices through `settlement_options` with the shared fields `{option_id, mechanism, asset, rates, params}`. The accepted Agreement MUST select one exact option, and the core MUST NOT interpret mechanism-specific values in `params`.

#### Scenario: Alkahest option is published

- **WHEN** a seller publishes an Alkahest settlement choice
- **THEN** its escrow policy is interpreted by the Alkahest kit, not by Arkhai payments

### Requirement: The refund failure action is opt-in and follows the accepted mechanism

A seller's `[fulfillment.failure_policy].actions` MAY include `refund`, off by default, meaning "refund the buyer when my own fulfillment fails". The action MUST dispatch on the deal's accepted Agreement: Alkahest keeps its token refund, and Arkhai payments reverses the held payment.

#### Scenario: A payments deal's fulfillment fails before delivery

- **WHEN** the refund action is enabled and fulfillment of an undelivered payments deal fails
- **THEN** the seller reverses the held payment and the deal ends `refunded`

#### Scenario: A delivered deal is not refunded automatically

- **WHEN** the refund action is enabled and a payments deal had already been delivered
- **THEN** the action does not run, and a refund stays an operator decision

#### Scenario: The reversal fails

- **WHEN** the action's reversal fails
- **THEN** the deal stays failed with the action's recorded failure, and the operator refund route remains the backstop

#### Scenario: The action is not enabled

- **WHEN** a seller has not enabled the refund action
- **THEN** a failed fulfillment refunds nothing automatically

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

## REMOVED Requirements

### Requirement: A payer submits its own instrument setup verification

**Reason**: Payer instrument setup and verification are owned by the removed Stripe integration.

**Migration**: Configure and approve Arkhai payment mandates through the `arkhai.payments.v1` mechanism.

### Requirement: Buyer hosted compatibility includes local payer readiness

**Reason**: Buyer-local Stripe payer bindings and funding-profile selection are removed.

**Migration**: Buyer compatibility is evaluated against the selected mechanism's advertised option and installed registration.

### Requirement: Buyer off-session automation policy is explicitly bounded

**Reason**: The Stripe off-session payer automation contract is removed.

**Migration**: Arkhai payments approval uses the buyer's owner-scoped credentials and explicit approval; it does not inherit the old profile automation policy.

### Requirement: Hosted consumer configuration pins the expanded release

**Reason**: The hosted Stripe client, manifest, and release-pin model is removed.

**Migration**: The Arkhai payments kit consumes the payments service's published API contract; no Stripe release configuration remains in marketplace roles.

### Requirement: Hosted options use exact funding profiles

**Reason**: `fiat.stripe.v1` and its provider-specific funding profiles are removed.

**Migration**: Configure an installed settlement mechanism instead. Stripe settings are not aliases for `arkhai.payments.v1`.

### Requirement: Hosted profile readiness is independent and exact

**Reason**: The Stripe hosted-client manifest, profile, and funding-authorization contract is removed.

**Migration**: Each remaining mechanism reports its own typed readiness through its registration.

### Requirement: Mechanism-owned typed registration

**Reason**: The hosted Stripe registration, readiness, and clause-projection examples are removed with that mechanism.

**Migration**: Register Arkhai payments and other supported mechanisms through the typed shared registration surface.

### Requirement: Mechanism-specific utilities stay namespaced

**Reason**: Its Stripe onboarding command is removed with the hosted settlement integration.

**Migration**: Keep any installed mechanism diagnostics under that mechanism's registration namespace.

### Requirement: Peer mechanism configuration hierarchy

**Reason**: Its only non-Alkahest peer is `fiat.stripe.v1`, which is removed.

**Migration**: Use the explicit typed settlement configuration and peer mechanism identifiers defined below.

### Requirement: Recovery uses pinned mechanism identity

**Reason**: Its selected funding-profile and hosted-authorization recovery contract is removed.

**Migration**: Recovery follows the mechanism and option pinned by the accepted Agreement.

### Requirement: Unified seller settlement commands

**Reason**: Stripe onboarding and hosted seller command behavior are removed.

**Migration**: Use one common seller status surface over enabled mechanism registrations.
