# Settlement Configuration Specification

## Purpose

Define one typed operator and consumer contract for configuring, validating, inspecting, migrating, publishing, and selecting independently implemented settlement mechanisms.

## Requirements

### Requirement: Hosted options use exact funding profiles

The `fiat.stripe.v1` registration MUST admit only the exact funding profiles `card.v1`, `us_bank_transfer.v1`, and `us_ach_debit.v1`. Each hosted publication clause MUST name exactly one profile, lowercase currency, positive minor-unit rate, interaction capability, and typed condition profile. New options MUST NOT contain `payment_method_types`, free-form provider methods, unversioned aliases, or a recovery-only legacy card value.

The funding profile MUST participate in the complete deterministic option identity and in the immutable accepted settlement projection. Equal resource, rate, currency, parties, and condition under different profiles MUST produce distinct option identities.

#### Scenario: Card and ACH have the same rate

- **WHEN** a seller configures `card.v1` and `us_ach_debit.v1` with otherwise identical clauses
- **THEN** publication produces two separately identifiable options whose accepted plans retain their exact profile

#### Scenario: Unsupported funding string is configured

- **WHEN** a clause contains `card`, `sepa_debit`, a Stripe method type, or another unregistered value
- **THEN** typed validation fails before readiness, publication, negotiation, or provider I/O

### Requirement: Hosted profile readiness is independent and exact

Hosted preflight MUST verify the exact signed client/API/schema and payer/profile/authorization capabilities plus authority, seller account, condition resolver, currency, country policy, and profile readiness required by each configured clause. It MUST return one safe result per profile. An unready profile MUST suppress only clauses for that profile, while ready hosted profiles and Alkahest remain available. Accepted operations MUST remain recoverable after a profile becomes unready for new materialization.

#### Scenario: ACH is unready while card is ready

- **WHEN** the authority reports a safe ACH blocker and valid card capability/readiness
- **THEN** publication suppresses ACH options, retains card and Alkahest options, and reports no provider identifier or secret

#### Scenario: Manifest lacks a selected profile

- **WHEN** the verified release does not advertise one configured profile or authorization contract
- **THEN** that profile remains unavailable and no compatible-major or unversioned fallback is used

### Requirement: Buyer hosted compatibility includes local payer readiness

Buyer compatibility for a hosted option MUST require the exact installed profile capability, supported USD/country policy, required interaction ability under the current action policy, and a selected local buyer profile with an active opaque payer binding ready for that authority/environment. Discovery-time checks MUST use only local profile metadata and advertised option data; they MUST perform no hosted mutation. Compatibility MUST be revalidated immediately before negotiation start and exact authorization.

A setup that the authority reports as awaiting payer-held verification MUST be treated as not yet ready. It MUST NOT be reported as revoked, unavailable, or failed, and it MUST NOT satisfy a saved or off-session mode until the authority reports the instrument ready.

#### Scenario: Buyer selects an ACH interaction mode

- **WHEN** an advertised ACH option survives resource filtering and the selected local profile has an active authority/environment binding plus interaction capability
- **THEN** explicit interactive mode remains compatible without a saved mandate, while saved/off-session mode requires the exact ready instrument and mandate

#### Scenario: Local readiness changes after discovery

- **WHEN** the selected payer binding or instrument readiness becomes revoked before negotiation starts
- **THEN** revalidation fails without accepting terms or switching to another profile

#### Scenario: A setup is awaiting payer-held verification

- **WHEN** the authority reports a bank-funded setup as pending the payer's own verification evidence
- **THEN** saved and off-session modes remain incompatible for that instrument, the profile is not reported as revoked or unavailable, and no other funding option is substituted

### Requirement: Buyer off-session automation policy is explicitly bounded

Buyer configuration MAY enable off-session authorization only through a typed policy that names the exact authority/environment, funding profile, currency, maximum amount per purchase, maximum aggregate amount over a declared window, and optional seller-principal bounds. Disabled or absent policy MUST require ordinary interactive authorization handling. The policy MUST NOT contain provider IDs, instruments, mandates, action URLs, raw hosted payloads, or blanket seller permission.

Policy evaluation MUST occur only for one accepted obligation and MUST produce a decision to sign that exact authorization or require interaction. It MUST NOT change profile, instrument selection, amount, currency, destination, seller, obligation hash, marketplace operation ID, or expiry.

#### Scenario: Purchase exceeds per-purchase bound

- **WHEN** an accepted obligation exceeds the configured exact profile/currency amount limit
- **THEN** automation refuses to sign and the buyer follows the interactive action policy without selecting another funding option

#### Scenario: Seller is outside the allowlist

- **WHEN** a seller-controlled obligation otherwise matches but its canonical principal is outside optional policy bounds
- **THEN** automation refuses and no hosted funding authorization is created automatically

### Requirement: Hosted consumer configuration pins the expanded release

Enabling any expanded hosted profile MUST pin one exact verified hosted manifest, client wheel, API/schema version, payer-profile contract, funding-authorization contract, funding-profile set, identity capability, and service image identity. Buyer and storefront roles MUST agree on those public pins before publication or authorization. Marketplace schemas MUST reject hosted provider, Customer, PaymentMethod, mandate, webhook, database, migration, and administrator fields.

Those pins MUST be taken from the hosted release the run bound. A consumer MUST NOT carry an API version, schema version, or capability set of its own that a bound release is then measured against, because a consumer that names one release in its own configuration cannot admit the next one, and reports a genuine contract disagreement as a configuration edit that was not made. Where a run binds a release, the rendered consumer configuration MUST state that release's coordinates; where no release is bound, no consumer configuration MUST be rendered at all.

Enforcement MUST NOT weaken. A disagreement between the bound release and the composed authority MUST fail closed before publication or authorization exactly as it does when the pins are written down.

#### Scenario: Buyer and storefront pins differ

- **WHEN** the buyer expects a different payer/profile capability or client identity from the publishing storefront's verified authority release
- **THEN** compatibility fails before terms acceptance or payer authorization

#### Scenario: A run binds a hosted release the consumer has never seen

- **WHEN** a run binds a hosted release whose API version, schema version, or capability set differs from every release bound before it
- **THEN** the rendered consumer configuration pins that release's own coordinates and the run proceeds, without a change to consumer source

#### Scenario: The composed authority contradicts the bound release

- **WHEN** the authority a run composed serves an API version, schema version, or capability set other than the one the run bound
- **THEN** the run fails closed before publication or payer authorization and names the disagreement

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

Each installed mechanism MUST register its canonical ID, configuration key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public settlement-clause projections, and any mechanism-specific operator commands. Mechanism-contributed clause fields MUST live under the mechanism's configuration-key namespace and MUST declare their applicable roles, operators, and value types. The shared foundation MUST own registration, grammar integration, ordering, common status, exact option correlation, and composition; it MUST NOT interpret chain-, provider-, arbiter-, condition-, or financial-authority fields.

#### Scenario: Stripe readiness is evaluated

- **WHEN** the common status command preflights `fiat.stripe.v1`
- **THEN** the hosted adapter validates its trust/account/condition contract and returns a common sanitized result without shared code importing provider behavior

#### Scenario: Stripe clause field is evaluated

- **WHEN** a buyer clause uses an allowlisted `stripe`-qualified field
- **THEN** the hosted registration validates and projects that public value while shared selection compares the typed projection without reading opaque hosted parameters

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

### Requirement: Mechanism-specific utilities stay namespaced

Seller and buyer CLIs MUST expose common settlement status and normal lifecycle commands without mechanism-specific flags. Setup, diagnostics, raw inspection, and raw mutation operations that are genuinely mechanism-specific MUST live under `settlement <mechanism>` and MAY consume only that registration's typed configuration and resources. A mechanism namespace MUST NOT create a separate publication path, settlement lifecycle, priority model, or accepted-plan interpretation.

#### Scenario: Seller completes Stripe onboarding

- **WHEN** the seller invokes `market-storefront settlement stripe onboard`
- **THEN** the mechanism-owned utility uses the configured hosted client while normal `publish` remains mechanism-neutral

#### Scenario: Buyer inspects an Alkahest escrow

- **WHEN** the buyer invokes the raw escrow inspection utility
- **THEN** it resolves under `market settlement alkahest` and no raw escrow command remains at the top level

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

Run logs MAY record configuration-schema version, public resolved mechanism set, selected funding profile, safe funding-authorization reference, and source-free fingerprints, but MUST NOT store secrets, stable payer/instrument refs, provider data, or raw actions. Recovery MUST use the accepted plan's canonical mechanism, exact funding profile, obligation, funding authorization, and operation identities rather than current priority, current profile readiness, current automation policy, or another mechanism/profile's readiness.

#### Scenario: Priority changes during a funded obligation

- **WHEN** recovery resumes an obligation after another mechanism becomes first priority
- **THEN** it resumes the originally pinned mechanism, funding profile, authorization, and stable operation identity without fallback

#### Scenario: Profile is disabled during pending funding

- **WHEN** recovery resumes an accepted bank operation after operators disable that profile for new deals
- **THEN** it continues status/reclaim under the accepted profile and never converts the obligation to card or Alkahest

### Requirement: A payer submits its own instrument setup verification

Where the bound hosted release declares the direct payer instrument setup capability, a buyer MUST be able to complete a bank-funded instrument setup by submitting the verification evidence the payer's own bank made available to them, without a browser session and without an operator acting on the payer's behalf.

One submission MUST name exactly one pending setup under exactly one opaque payer binding, and MUST carry exactly one form of evidence: either the deposited minor-unit amounts, or the descriptor code. Carrying both, or neither, MUST fail before any hosted mutation.

The submission and its result MUST carry no provider identifier, Customer, PaymentMethod, mandate, bank or card detail, client secret, action URL, or raw provider payload, and marketplace persistence MUST NOT retain the submitted evidence. The result MUST expose only the opaque setup reference, public readiness, and any transient action the authority returns.

Starting a setup that the payer will answer directly MAY carry one opaque provider token naming the instrument the payer already holds, because an authority given no instrument issues a hosted page instead and the setup is no longer one the payer can answer. That token MUST be transient on the same terms as an action URL: passed to the authority, never persisted in a marketplace row, never projected, and never reported. Marketplace configuration MUST continue to reject provider and payment-method fields outright.

Where the bound release does not declare the capability, the operation MUST be reported as an unavailable prerequisite naming that capability, before any hosted mutation, rather than attempted and failed.

#### Scenario: A payer submits microdeposit amounts

- **WHEN** a payer submits the two deposited minor-unit amounts against a setup the authority reports as awaiting verification
- **THEN** the authority's readiness for that setup is returned, the instrument becomes usable for saved and off-session modes once it is ready, and no provider material is persisted or reported

#### Scenario: A submission carries both forms of evidence

- **WHEN** a submission names both deposited amounts and a descriptor code, or names neither
- **THEN** it is refused before any hosted call, and the pending setup is left untouched

#### Scenario: The bound release lacks the capability

- **WHEN** a verification submission is attempted against a bound release that does not declare direct payer instrument setup
- **THEN** the capability is reported as the unavailable prerequisite before any hosted mutation, and no alternate path is substituted

#### Scenario: A setup is started from an instrument the payer holds

- **WHEN** a setup is started with an opaque provider token for the payer's own instrument
- **THEN** the authority reports the setup as awaiting verification with no hosted action, and the token appears in no marketplace row, projection, or report

#### Scenario: Verification evidence is not retained

- **WHEN** a submission has been made and its result recorded
- **THEN** marketplace persistence and any report contain the opaque setup reference and public readiness only, and contain no amounts, descriptor code, or provider payload

### Requirement: A mechanism builds the accepted obligation it advertised

A mechanism whose options can be exactly selected MUST supply the accepted
obligation builder for its own registration; a domain MUST NOT construct an
obligation for a mechanism it composed, and a selection naming a mechanism with
no builder MUST be refused before any negotiation, obligation or capacity record
is written.

The builder MUST derive the obligation through the same materialization the
counterparty re-derives it from, so the funded payload is one derivation rather
than two implementations that can drift. Acceptance inputs the option cannot
carry — the counterparty-chosen expiry, the negotiated duration, the domain's own
option parameters and the seller's published demands — are supplied by the domain
as acceptance context, and the seller's injected settlement resources travel with
it so a mechanism that materializes against a chain accepts using the same
address book and payout wallet it published from. The domain MUST NOT read the
resulting mechanism parameters.

#### Scenario: An advertised on-chain option is exactly selected

- **WHEN** a buyer selects an option advertising an accepted escrow and no expiry,
  supplying its own expiry and the lease duration
- **THEN** the mechanism scales the advertised rate by that duration and returns one
  obligation whose nested materialized payload equals what the buyer re-derives
  from the same advertised entry

#### Scenario: A selected mechanism builds no accepted obligation

- **WHEN** a selection names a composed mechanism that supplies no accepted
  obligation builder
- **THEN** the request is refused and no negotiation, obligation or capacity record
  is written

### Requirement: An exactly selected agreement settles against its accepted obligation

Settlement of an exactly selected agreement MUST verify the funded mechanism
state against the immutable accepted obligation that agreement committed, never
against the listing's current advertised terms: a listing may be republished
under the same identity, so its advertised terms are not the financial authority
for an agreement already accepted. The accepted obligation MUST NOT be rebuilt at
settlement, and no accepted record may be rewritten to make verification pass.

The accepted plan is that authority only while it still agrees with the rest of
the committed record. For a bare-metal agreement settled through the Alkahest
escrow rail — the path this contract is written for, and the only one that
implements it — settlement MUST refuse, before any mechanism read or any write,
an agreement whose plan does not carry exactly one Alkahest obligation, whose
declared parties, obligation roles or principals differ from the negotiation's,
whose amount, asset or mechanism payload disagrees with the committed agreement,
whose declared conditions the mechanism does not verify, whose selected option is
not the one the plan settles, or whose physical facts — provision terms and the
binding restating them — differ from the committed domain terms artifact and
listing. A value an opaque mechanism carrier holds in an unreadable form MUST be
refused the same way rather than raised as a fault. Other domains and mechanisms
keep their own plan shapes, including plans carrying several obligations; this
requirement places no restriction on them.

Where a mechanism verifies against an external system, the accepted obligation
MUST be carried into that verification whole, including the accepted expiry that
fixes the collect-versus-reclaim boundary. A verification interface that accepts
an expected payload without its expiry leaves that boundary unpinned, and an
otherwise matching state with a different deadline MUST NOT settle.

#### Scenario: A funded escrow carries a different deadline

- **WHEN** the funded escrow matches the accepted obligation payload but its
  expiry is not the accepted one, earlier or later and still in the future
- **THEN** verification fails and nothing is adopted or recorded

#### Scenario: An accepted bare-metal record disagrees with itself

- **WHEN** a bare-metal Alkahest plan's parties, roles, amount, asset, conditions,
  selected option, physical binding or physical terms differ from the committed
  thread and domain artifacts, or an opaque carrier holds an unreadable value
- **THEN** settlement is refused with a settlement error before any mechanism read
  or write

### Requirement: A domain buyer drives every rail its seller publishes

A seller composition that installs several mechanism registrations publishes an
option per ready mechanism from one publication round. The buyer for that domain
SHALL resolve the rail from the option the buyer selected, and SHALL NOT assume
one mechanism's option shape when reading another's.

Mechanism-specific acceptance validation remains mechanism-specific. A buyer that
supplies `validate_advertised_plan` to the shared negotiation client replaces the
shared `params`/`conditions` equality check for that agreement, so the callback
SHALL verify the financial and collection semantics it displaced — at minimum the
escrow target, chain, funded asset, and collection conditions — against the
buyer's own proposal. It SHALL NOT restate the principal, amount, expiry, asset
or mechanism checks the shared client already performs.

#### Scenario: A published option is selectable on either rail
- **WHEN** one publication advertises both an on-chain and a hosted option
- **THEN** the selected `option_id` decides which rail the buyer drives
- **AND** an option naming a mechanism the buyer cannot drive is refused by name

#### Scenario: An advertised escrow entry carries no expiry
- **WHEN** a buyer selects an on-chain option
- **THEN** the escrow expiry is the buyer's own chosen instant
- **AND** it is not read from the advertised entry, which does not carry one

#### Scenario: A substituted plan is refused before funding
- **WHEN** an accepted plan differs in any part of its funded obligation from
  the one the buyer's proposal derives
- **THEN** acceptance fails and no escrow is created

The comparison SHALL be against the mechanism's own canonical materialization of
the buyer's proposal, not an enumerated list of fields. A mechanism that encodes
terms inside a funded payload — an arbiter or payee within the obligation data —
would otherwise pass a top-level check while funding different terms.

Where the buyer cannot derive a value from its own proposal, such as the address
the seller will be paid at when the listing advertises none, the specification
SHALL record that as an unpinned input rather than implying it is verified.

The value re-derived from SHALL be the accepted obligation's negotiated absolute
total, which the shared client has already required to equal the negotiated
amount before delegating. An advertised rate is per unit and is not that total
for any rental of a different length; a mechanism callback SHALL NOT validate
against the advertised rate, and SHALL NOT introduce its own scaling or rounding
of it.

#### Scenario: A rental shorter than one rate unit
- **WHEN** an hourly option is accepted for a fraction of an hour
- **THEN** the accepted plan settles at the scaled negotiated total
- **AND** an accepted plan carrying the unscaled hourly rate is refused

### Requirement: Negotiation is not purchase

An accepted agreement SHALL NOT be treated as a completed purchase. For an
on-chain rail the buyer SHALL create the accepted obligation's escrow, obtain the
seller's authoritative verification of it, and begin fulfillment, before any
capacity is reserved or any delivery view is read.

The escrow's identity SHALL be recorded before verification is requested, so that
an escrow which exists on chain but was never verified remains reclaimable.

#### Scenario: A resumed run adopts its escrow
- **WHEN** a settlement run is repeated with an already-funded escrow reference
- **THEN** that escrow is verified and begun
- **AND** no second escrow is created

A domain buy command records its run in the shared run log: the run's opening
inputs, the accepted agreement, and the run's end. The opening record carries the
registry the listing was read from, that registry's authority, the listing, its
storefront, and the publisher principals the listing was signed under, so the
purchased agreement is bound to an authenticated discovery. A consumer of that
log SHALL assert the events the command emits; it SHALL NOT depend on names no
producer writes.

Beginning fulfillment is not delivery. The buyer-visible physical projection
reports its own state, and the delivery and access views are meaningful only once
that state is active, so a consumer SHALL wait on the projection rather than read
those views when the settlement command returns.

#### Scenario: The purchased listing came from the configured registry
- **WHEN** a run's opening record names another registry, another authority, or
  carries no publisher principals
- **THEN** the run is not accepted as evidence of authenticated discovery
