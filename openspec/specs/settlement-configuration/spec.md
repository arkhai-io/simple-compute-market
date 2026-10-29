# Settlement Configuration Specification

## Purpose

Define one typed operator and consumer contract for configuring, validating, inspecting, migrating, publishing, and selecting independently implemented settlement mechanisms.

## Requirements

### Requirement: Payments configuration separates accounts and credentials

Shared Arkhai payments registration, typed configuration, and owner-scoped client provision MUST live in `kit/arkhai-payments`'s `settlement_config.py`. `[Settlement.arkhai_payments]` MUST contain the trusted service origin, Ed25519 receipt identity, fee policy, dispute authority, the expected service mode `livemode`, and an API-key environment-variable reference, not the resolved credential. `livemode` MUST default to `false`, so a role that does not declare a live service accepts only test-mode receipts. Payment credentials MUST NOT appear in public options, Agreement bytes, run logs, or status.

#### Scenario: Credentials stay out of public surfaces

- **WHEN** a storefront or buyer is configured for Arkhai payments
- **THEN** its configuration names the API key's environment variable only, and the credential appears in no public option, Agreement, run log, or status

#### Scenario: An undeclared mode accepts no live receipt

- **WHEN** a storefront or buyer configured for Arkhai payments does not set `livemode`
- **THEN** it expects test-mode receipts, and a receipt signed with `livemode` true does not verify

### Requirement: Payment accounts come from domain input and the accepted option

Buyer domain input MUST supply `payer_account` independently of marketplace identity and service policy: VM uses `[vms].payer_account` and API credits `[apicredits].payer_account`. Seller client ownership MUST come from the accepted option's `payee_account`, not a service-policy account field.

#### Scenario: Buyer chooses a payer account

- **WHEN** an Ed25519 buyer selects `arkhai.payments.v1`
- **THEN** its account travels in `SettlementSelection.params.payer_account` and Agreement `settlement_params`, while its marketplace signer and owner-scoped API credential remain separate

### Requirement: Agreement attachment is a policy each side owns

The buyer's `attach_agreement` setting, default `false`, MUST be the only control that attaches the Agreement at approval. A seller asks for the Agreement through its payment option's `deposit_agreement` and, when the buyer did not attach it, MUST attach it after verifying the receipt and before any delivery effect.

#### Scenario: A seller configuration sets the buyer's attachment policy

- **WHEN** a seller's `[Settlement.arkhai_payments]` section sets `attach_agreement`
- **THEN** publication preflight reports a blocker, because the setting belongs to the buyer

#### Scenario: The seller deposits what the buyer did not attach

- **WHEN** the selected option sets `deposit_agreement` and the approved transaction has no Agreement attachment
- **THEN** the seller attaches the Agreement after recording the verified receipt and before any delivery effect

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

### Requirement: Common sanitized mechanism readiness

Preflight for every mechanism MUST report canonical mechanism ID, configured, enabled, ready, stable blocker codes/messages, capabilities, and contract/schema versions, with only allowlisted safe public detail. A status check MUST be observational and MUST NOT publish, create Account Links or Checkout sessions, submit chain/provider mutations, change settlement state, or expose credentials, provider IDs, private RPC data, transient URLs, or administrator state.

#### Scenario: Enabled mechanism is not ready

- **WHEN** a required public trust pin, account readiness result, wallet/chain dependency, deployed address, or capability is absent
- **THEN** status reports `ready=false` and the mechanism-owned sanitized blocker without performing a side effect

### Requirement: Priority orders choices but never changes accepted settlement

Storefront publication MUST emit options in configured priority order for every enabled and ready registration with a valid publication clause and a supported seller-stage entry. Buyer compatibility/selection MUST intersect registration compatibility with supported buyer-stage entries and MAY use priority as policy input. Accepted Terms MUST pin one exact option; configuration, readiness or priority changes MUST NOT switch an accepted or in-flight mechanism.

#### Scenario: One of two enabled mechanisms is unready

- **WHEN** one supported mechanism preflight fails and the other is ready
- **THEN** publication suppresses only the unready mechanism, reports its blocker and advertises the ready mechanism

#### Scenario: No enabled mechanism is ready

- **WHEN** every enabled mechanism fails preflight
- **THEN** publication derives no option and refuses the candidate, as storefront publication's "A compute candidate with no settlement option yields no listing" requires, without replacing existing accepted Terms or starting a settlement

#### Scenario: Registration lacks a domain stage

- **WHEN** an installed registration has no supporting entry for the publishing or selecting role
- **THEN** no fresh option for that role is published or selected, even if its configuration and preflight are valid

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

Settlement configuration MUST have one root with a duplicate-free ordered list of mechanism IDs and one typed subsection per installed mechanism (`alkahest.v1` as `[Settlement.alkahest]`, `arkhai.payments.v1` as `[Settlement.arkhai_payments]`). `fiat.stripe.v1` MUST NOT be registered, aliased, or mapped to Arkhai payments. Identity, wallet, and chain resources MUST stay outside mechanism subsections. Unknown IDs or keys, duplicates, and role-inapplicable required fields MUST fail validation.

#### Scenario: Seller enables Arkhai payments only

- **WHEN** `[Settlement].priority` contains `arkhai.payments.v1`, its typed subsection is valid and enabled, and Alkahest is disabled
- **THEN** seller configuration is valid without a wallet or chain section

#### Scenario: Priority names an uninstalled mechanism

- **WHEN** configuration names a mechanism for which the composition root has no registration, including `fiat.stripe.v1`
- **THEN** startup and publication fail with the unknown canonical mechanism ID and do not substitute another mechanism

### Requirement: New configuration chooses no mechanism

New defaults MUST enable no mechanism and no implicit priority; initialization MUST require an explicit choice, while migration of still-supported settings MUST preserve the effective enabled set and order.

#### Scenario: New config has no mechanism choice

- **WHEN** an operator generates or starts from defaults without selecting a settlement mechanism
- **THEN** no mechanism is enabled or preferred and publication/settlement remains unavailable until configuration is explicit

### Requirement: Mechanism registrations own typed configuration and readiness

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. A client factory and accepted-obligation or verifier hooks MAY be absent for an Agreement-based stage that does not use the conditional-escrow runtime.

#### Scenario: Arkhai payments readiness is evaluated

- **WHEN** common status preflights `arkhai.payments.v1`
- **THEN** its registration returns a common sanitized result without exposing an API credential or performing a payment mutation

#### Scenario: Agreement-deposit preference is evaluated

- **WHEN** a buyer clause filters on the public agreement-deposit setting of an advertised `arkhai.payments.v1` option
- **THEN** the mechanism registration projects that typed option value and shared selection compares it without interpreting opaque parameters

### Requirement: Mechanism clause fields stay in their namespace

Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition, and MUST NOT interpret chain-, arbiter-, condition-, or financial-authority fields.

#### Scenario: A mechanism contributes a clause field

- **WHEN** a mechanism adds a publication clause field
- **THEN** the field lives under the mechanism's configuration key with its declared roles, operators, and value types, and the shared grammar composes it without interpreting its value

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

A listing MUST advertise settlement choices through `settlement_options` with the shared fields `{option_id, mechanism, asset, rates, params}`. The accepted Agreement MUST select one exact option, and the core MUST NOT interpret mechanism-specific values in `params`.

#### Scenario: Alkahest option is published

- **WHEN** a seller publishes an Alkahest settlement choice
- **THEN** its escrow policy is interpreted by the Alkahest kit, not by Arkhai payments

### Requirement: Each mechanism's option carries its own parameters

Alkahest options MUST carry their escrow policy in mechanism-owned parameters; legacy Alkahest listing fields remain supported by the escrow path and MUST NOT become requirements of Arkhai payments. An `arkhai.payments.v1` option MUST carry the mechanism-owned payee account, hold window, and agreement-deposit setting needed to derive and disclose its payment policy.

#### Scenario: Arkhai payment option is published

- **WHEN** a seller publishes an `arkhai.payments.v1` option
- **THEN** the option identifies its payee account, declared hold window, and agreement-deposit setting while core exposes only the shared option envelope

### Requirement: Registration and settlement execution are distinct

Registration MUST remain the shared contract for typed configuration, publication, readiness and compatibility. Settlement execution MUST use the domain role table, not a required registration settlement hook. Existing obligation/artifact hooks MUST NOT imply that every mechanism uses the obligation runtime or follows a shared stage convention.

#### Scenario: An Agreement-only mechanism is installed

- **WHEN** a domain composes an Agreement-only stage and its typed registration
- **THEN** publication and compatibility work without conditional-escrow clients, a servicing worker or a universal settle interface

#### Scenario: A mechanism opts out of the convention

- **WHEN** a domain supports a stage with a different actor sequence or fused delivery
- **THEN** it remains a full registered peer and requires no opt-in-convention adapter

### Requirement: Accepted recovery retains supported stage identity

Disabling publication or selection for a mechanism MUST NOT reinterpret accepted work. Recovery MUST retain the domain entry required by the recorded Agreement or report an unavailable accepted stage before effects. It MUST NOT restore eligibility through escrow-shaped fallback or current configuration priority.

#### Scenario: A mechanism is disabled after acceptance

- **WHEN** a previously accepted Agreement is resumed after its registration is disabled for new work
- **THEN** its existing entry resumes that exact mechanism and operation identity without advertising it for fresh work

### Requirement: An Alkahest section that cannot settle makes Alkahest unready

A configured `[Settlement.alkahest]` section that parses but under which no deal could be
settled MUST make the Alkahest mechanism unready, with a configuration blocker naming the
setting, and MUST NOT stop the storefront, whether or not the section is enabled. That
covers an oracle-gated section with no trusted oracle; a trusted or interruptible oracle
equal to the seller wallet's address or to the account its key signs as; an interruptible
section with no interruptible oracle; a seller wallet with neither an address nor a key,
whatever clients the storefront composes; a missing wallet key or no configured chain
where the storefront needs them to settle; and a release model the storefront's domain
cannot deliver. A release condition MUST NOT fall back to the seller wallet as its oracle.
A section that does not parse MUST stop startup, as any configuration does.

#### Scenario: An oracle-gated section names no oracle

- **WHEN** a storefront starts with an oracle-gated Alkahest section that lists no trusted
  oracle
- **THEN** it starts, Alkahest is unready with a configuration blocker naming the missing
  oracle, and its other mechanisms publish

#### Scenario: The oracle is the seller's own wallet

- **WHEN** a storefront's Alkahest section names the seller wallet as its trusted oracle
- **THEN** Alkahest is unready with a configuration blocker, and no candidate is refused
  per cycle for it

#### Scenario: The seller wallet has no address

- **WHEN** a VM or API-credit storefront composes Alkahest clients but its seller wallet
  states no address and has no key to derive one from
- **THEN** Alkahest is unready with a configuration blocker, and no listing advertises a
  release condition with no recipient

### Requirement: Readiness blockers state their kind

Every mechanism's readiness blocker MUST carry a kind: `configuration`, which the
storefront's own configuration causes and only an operator can clear, or `reachability`,
raised because a dependency the mechanism needs could not be reached, or has not yet been
probed, to determine readiness. The kind MUST be set on every blocker: by each
mechanism's preflight on the blockers it reports, and by the settlement runtime on the
`not_configured` and `disabled` blockers it builds itself, which are configuration
blockers. Status MUST report it. A mechanism whose readiness contacts nothing reports only
configuration blockers. A disabled section's readiness MUST list, after `disabled`, the
configuration blockers its mechanism's preflight reports for it.

#### Scenario: A chain cannot be reached

- **WHEN** Alkahest's chain probe cannot reach a configured chain
- **THEN** its blocker is the reachability blocker `alkahest.chain_unreachable`

#### Scenario: A required contract is not deployed

- **WHEN** Alkahest's chain probe reaches a chain that has no code at an address its
  address configuration requires
- **THEN** its blocker is the configuration blocker `alkahest.contract_missing`

#### Scenario: A wallet is missing

- **WHEN** Alkahest's seller wallet states no address and has no key to derive one from
- **THEN** its blocker is a configuration blocker

#### Scenario: A mechanism is disabled

- **WHEN** a mechanism's section is absent or disabled
- **THEN** the settlement runtime's `not_configured` or `disabled` blocker is a
  configuration blocker

#### Scenario: A disabled section could not settle

- **WHEN** a seller's Alkahest section is disabled and lacks its wallet key, or names a
  release model its domain cannot deliver
- **THEN** its readiness reports `disabled` followed by the configuration blocker naming
  the problem, and no reachability blocker

### Requirement: Alkahest probes its chains apart from readiness

A storefront composing Alkahest MUST probe each configured chain apart from readiness
evaluation, in its `alkahest-chain-probe` lifecycle loop, which the Alkahest kit supplies
and the storefront registers beside its other loops, with the pause and explicit step
every storefront loop has: reading the chain's identity and the code at each contract
address its address configuration requires, the loop's timer probing each chain once per
configured probe interval and an explicit step probing at once, with every call bounded by
a timeout. Alkahest readiness MUST read each chain's
last probe result and MUST NOT call a chain itself. A chain not yet probed since start
MUST read as a reachability blocker. A result MUST NOT expire while the loops are held. A
chain whose client could not be constructed MUST be probed at each probe until its
client's construction succeeds, a probe finding no construction running starting one and
waiting for it no longer than the same timeout; at most one construction per chain MUST
run at a time, a probe finding one still running MUST start no other, and a construction
finishing after its probe's wait MUST be adopted by a later probe; until it succeeds the chain MUST read as a reachability blocker whatever its RPC answers,
and every consumer of the storefront's Alkahest clients MUST read them through the map the
probe updates, so the storefront recovers without a restart. Readiness MUST judge the
chains a publication names, and with no publication input every configured chain; every
storefront's status MUST evaluate readiness with no publication input, and report each
chain's last result and when it was taken.

#### Scenario: Readiness is evaluated for many candidates

- **WHEN** a publication cycle evaluates Alkahest readiness for every candidate it builds
- **THEN** no chain is called more than its probe interval allows

#### Scenario: A storefront starts with its chain down

- **WHEN** a storefront starts while its chain's RPC is unreachable, and the RPC later
  answers
- **THEN** Alkahest is unready with a reachability blocker until a probe succeeds, then
  ready, without a restart

#### Scenario: A chain answers but its client cannot be built

- **WHEN** a chain's RPC answers the probe's calls but its client's construction fails or
  does not finish within the timeout
- **THEN** Alkahest is unready with a reachability blocker for that chain, and the next
  probe that constructs the client makes it ready, without a restart

#### Scenario: A client's construction never returns

- **WHEN** a chain's client construction never returns, across many probes
- **THEN** only that one construction runs, the chain reads as a reachability blocker at
  each probe, and the storefront's other work goes on

#### Scenario: A configured chain no listing publishes on stops answering

- **WHEN** a storefront configures two chains, its listings publish on one, and the other
  stops answering
- **THEN** status reports Alkahest unready with a reachability blocker, since servicing a
  deal accepted on that chain needs it, while publication on the answering chain goes on

#### Scenario: A scenario holds the loops

- **WHEN** a storefront's loops are held after a probe and its chain later stops answering
- **THEN** readiness keeps reporting the held result, with the time it was taken, until
  the `alkahest-chain-probe` loop is stepped or resumed

### Requirement: A publication clause's mechanism input is a mapping

A settlement publication clause MAY omit `mechanism_input`, which then means no input. A
stated `mechanism_input` MUST be a mapping: a clause stating any other value -- null, a
list, a number, or text -- MUST be refused as malformed rather than read as no input, by
every consumer that reads clauses, whatever the clause's mechanism and before that
mechanism's enablement is judged.

#### Scenario: A clause states a mechanism input that is not a mapping

- **WHEN** a publication clause, in a storefront's configuration or in a pool's hint,
  states `mechanism_input` as null or as a list
- **THEN** the clause is refused as malformed, naming `mechanism_input`, whether or not
  its mechanism is enabled

#### Scenario: A clause omits its mechanism input

- **WHEN** a publication clause states no `mechanism_input`
- **THEN** it is read as a clause with no mechanism input

### Requirement: A seller's wallet address and key name one account

A seller's Alkahest readiness MUST report `alkahest.wallet_address_mismatch` when its
configured wallet address is not the address its wallet key signs as, in every storefront.
A seller that states no address MUST use the key's. Alkahest's check that a release oracle
is not the seller MUST compare the oracle with the signing account as well as the address.

#### Scenario: The address names another account

- **WHEN** a storefront's `[Wallet].address` differs from the address its key derives
- **THEN** Alkahest is unready with `alkahest.wallet_address_mismatch`, the storefront keeps
  running its other mechanisms, and no Alkahest option is published

#### Scenario: The address is omitted

- **WHEN** a seller configures a wallet key and no address
- **THEN** the storefront uses the key's address wherever the seller's address is named

#### Scenario: The oracle is the signing key

- **WHEN** a seller configures as its release oracle the account its wallet key signs as
- **THEN** Alkahest is unready, whatever address is configured

### Requirement: Alkahest address books are named per chain in the Alkahest section

A role MUST name each chain's Alkahest address book only in `[Settlement.alkahest.address_books]`,
a table from configured chain name to book; a chain it does not name uses the SDK's
built-in addresses. Every reader of a chain's book MUST resolve it through that table. A
key naming no configured chain MUST make Alkahest unready. `[Chains.<name>].alkahest_address_config_path`
and `[Settlement.alkahest].address_config_path` MUST be refused with a diagnostic naming the
table, and migration MUST move either into it.

#### Scenario: A seller trades on two chains

- **WHEN** a seller names an address book for `anvil` and none for `base_sepolia`
- **THEN** publication, verification, and claim servicing use the book for `anvil` and the
  built-in addresses for `base_sepolia`

#### Scenario: A retired key is stated

- **WHEN** configuration states `[Chains.anvil].alkahest_address_config_path`
- **THEN** the role refuses it, naming `[Settlement.alkahest.address_books]`

#### Scenario: A configuration is migrated

- **WHEN** an operator migrates a configuration naming a book under either retired key
- **THEN** the book is named under `[Settlement.alkahest.address_books]` for its chain, and
  migration refuses two different books for one chain

#### Scenario: The section key does not reach every chain

- **WHEN** an operator checks the migration of a seller configuration whose
  `[Settlement.alkahest].address_config_path` moves to some of several configured chains
- **THEN** migration names each other configured chain, whose claims will be serviced
  against its entry in `[Settlement.alkahest.address_books]` or, where it has none, the
  SDK's built-in addresses, before anything is written
