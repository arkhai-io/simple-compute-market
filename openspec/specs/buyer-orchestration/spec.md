# Buyer Orchestration Specification

## Purpose

Define registry fan-in, domain plugins, policy-driven negotiation, aggregation, settlement, and run recovery.

## Requirements

### Requirement: Plugin-composed buyer CLI
The core `market` CLI MUST discover domain plugins through entry-point metadata and let each plugin register namespaced verbs without core importing the domain.

#### Scenario: A domain plugin is installed
- **WHEN** the buyer CLI starts
- **THEN** the plugin's verbs are registered without the core package importing that domain

### Requirement: Linear buy orchestration

A buy run MUST compose discovery, candidate filtering/aggregation, negotiation and the domain-owned selected settlement hook, and persist results needed for inspection and recovery. Core MUST dispatch using the exact accepted Agreement's mechanism through the buyer-role table, not escrow-proposal presence. The selected stage owns its actor sequence and kit-specific prerequisites.

#### Scenario: Settlement response is lost

- **WHEN** the run log contains accepted terms and a deal reference
- **THEN** recovery inspects or resumes that Agreement's same table entry and operation without renegotiating a second agreement

### Requirement: Fresh and resumed buyers use the same stage declaration

A domain's buy, settle-from-run and resume surfaces MUST use the same buyer-role table. Stages MUST receive exact accepted Agreement bytes, opaque settlement data and the recorded profile signer. Selection prerequisites and acceptance validation specific to a mechanism MUST be owned by its entry, and core MUST NOT require an escrow proposal or buyer-first action.

#### Scenario: Payment buy has a stray escrow field

- **WHEN** the accepted Agreement selects a declared payment stage and the outcome also contains an escrow proposal
- **THEN** dispatch still selects the payment entry solely from the Agreement and never creates an Alkahest escrow

#### Scenario: Alkahest proposal is missing

- **WHEN** the accepted Agreement selects Alkahest but its outcome lacks the required proposal
- **THEN** the selected Alkahest entry refuses its own malformed input without core choosing a different mechanism

#### Scenario: Current priority changes before resume

- **WHEN** a buyer resumes a recorded accepted Agreement after another mechanism becomes first priority
- **THEN** it uses the recorded mechanism, exact accepted inputs, profile principal and established operation identity

#### Scenario: Role entry is absent

- **WHEN** the recorded Agreement's mechanism cannot resolve in the domain's buyer-role table
- **THEN** the command reports unsupported accepted work before wallet, payment or seller mutations

### Requirement: Buyer evidence is separate from private delivery

Buyer settlement progress MUST retain its recorded opaque settlement reference, exact accepted Agreement bytes and domain settlement data for recovery. Delivery results and credentials MUST remain in the domain's authenticated result handling and MUST NOT be substituted for accepted settlement state or persisted as public run evidence. Seller delivery authorization remains the storefront's verified SettlementEvidence, not buyer-local progress.

#### Scenario: Buyer retrieves a delivered API key

- **WHEN** the buyer retrieves a grant after settlement has completed
- **THEN** buyer recovery retains the accepted settlement reference while the bearer credential uses the private result boundary and stays out of the run log

### Requirement: Domain-owned negotiation surface
Domain buyer adapters MUST own settlement compatibility checks and CLI parameters, negotiation policies MUST own opening and per-round decisions, and the core MUST deliver policy inputs without interpreting schema-specific fields.

#### Scenario: Listing has no compatible settlement tuple
- **WHEN** the selected buyer policy rejects every advertised tuple
- **THEN** the buyer reports no compatible format rather than negotiating malformed terms

### Requirement: Policy-specific opening constraints
Buyer role documentation MUST expose any configured policy constraint that can terminate negotiation before a counter-round. For the current maximizing bisection policy, an explicit opening below the seller's advertised primary rate is unsupported; the default listed-price policy opens at that rate.

#### Scenario: Buyer chooses a bisection opening
- **WHEN** a buyer explicitly configures the maximizing bisection policy
- **THEN** role guidance tells the buyer to choose an initial price at least as high as the listing's advertised primary rate

### Requirement: Schema-opaque aggregation
Core aggregation control flow MUST order and select candidates through registered policies without embedding domain or settlement-kit price vocabulary.

#### Scenario: Alkahest price ordering is requested
- **WHEN** a registered Alkahest aggregation policy is selected
- **THEN** kit code interprets price fields while core applies the resulting ordering

### Requirement: Domain-provided buyer integration
The core buyer role MUST obtain domain command registration, provision-terms construction, negotiation policy hooks, and fulfillment-result decoding through the selected market-domain contract rather than concrete-domain imports or name-based branches.

#### Scenario: Buyer invokes a domain command
- **WHEN** a discovered domain command constructs a purchase request
- **THEN** the domain hooks produce versioned provision terms, the core runs schema-opaque orchestration, and the domain decodes the terminal result

#### Scenario: Core runs without a concrete domain
- **WHEN** no domain plugin is installed
- **THEN** generic discovery and diagnostic commands remain available while domain purchase commands are absent

### Requirement: Shared domain conformance suite
Every shipped buyer domain plugin MUST pass one contract suite covering identity, command registration, terms construction, policy integration, and result decoding.

#### Scenario: Domain integration changes
- **WHEN** VM, bare-metal, or API-credit buyer integration is modified
- **THEN** the shared conformance suite runs against that implementation in addition to its domain-specific behavior tests

### Requirement: Policy-constrained settlement preference

Buyer orchestration MUST apply buyer-policy preference only to settlement candidates that
already satisfy compatibility and active chain/token constraints. A policy MUST NOT select
or introduce a candidate outside that set, and invalid policy output MUST fall back or fail
actionably without bypassing compatibility.

#### Scenario: Several compatible candidates remain

- **WHEN** noninteractive orchestration has several compatible settlement candidates and
  policy returns a valid preference
- **THEN** orchestration selects according to that preference before balance-based or
  deterministic default fallback

#### Scenario: Policy returns an unknown candidate

- **WHEN** policy output references a settlement tuple not present in the constrained input
  set
- **THEN** orchestration rejects that output and does not submit settlement using the
  unknown tuple

#### Scenario: Interactive choice is requested

- **WHEN** the buyer explicitly requests interactive selection among compatible candidates
- **THEN** the user's valid choice remains authoritative rather than being silently replaced
  by policy preference

#### Scenario: Zero or one candidate remains

- **WHEN** compatibility filtering leaves zero or one candidate
- **THEN** orchestration respectively reports no valid settlement choice or uses the sole
  candidate without requiring a preference decision

### Requirement: Mechanism-neutral constrained preference

Buyer orchestration MUST normalize legacy escrow entries and settlement options into immutable preference candidates only after installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses MUST be evaluated in command order before configured-policy ranking, and every predicate in one clause MUST match the same advertised option. Policy output MUST NOT introduce an unadvertised or incompatible choice. When no explicit clause is supplied, configured mechanism priority remains the pre-acceptance policy input.

#### Scenario: Buyer requests Arkhai payments
- **WHEN** a Arkhai payment clause and supported asset leave several payment options
- **THEN** buyer policy ranks only those matching payment options and exact deterministic fallback applies if it expresses no preference

#### Scenario: Buyer selects Alkahest
- **WHEN** an Alkahest clause or interactive choice selects an existing compatible Alkahest option
- **THEN** the existing escrow creation/submission path and run-log fields remain unchanged and no payments API is called

#### Scenario: Several clauses match
- **WHEN** more than one explicit settlement clause has compatible candidates
- **THEN** the earliest matching clause wins before configured mechanism priority and no later clause is considered after acceptance

### Requirement: Buyer normal path consumes two DSLs

Domain purchase commands MUST accept one resource-query DSL input and zero or more settlement-clause DSL inputs. Resource filtering MUST complete before settlement compatibility, clause ordering, negotiation policy, and any mechanism-specific prerequisite resolution. Removed convenience flags MUST NOT remain as hidden aliases or alternate precedence layers.

#### Scenario: Resource matches have no settlement match
- **WHEN** the resource query returns listings but the buyer has not enabled any mechanism advertised by those listings
- **THEN** the command reports a settlement incompatibility rather than claiming that the registry returned no resource listings

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below a
`settlement <mechanism>` command group: `market settlement <mechanism>` at the root for a
domain whose plugin registers its group there, or `market <domain> settlement <mechanism>`
below the domain's own command, so that no two installed domains register one root
`settlement` group. Payment approval is an internal accepted-run step, not payer-profile
administration. Normal `market buy`, `market settle`, resume, and accepted-obligation
lifecycle commands MUST derive mechanism inputs from the selected option, persistent buyer
profile, and accepted run and MUST NOT accept chain-, token-, provider-, raw payer-ref-, or
browser-specific override flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

#### Scenario: A domain's mechanism utilities sit below its own command

- **WHEN** the bare-metal buyer plugin is installed
- **THEN** its contact-exchange utilities are `market bare-metal settlement contact`, and it
  registers no root-level `settlement` group

### Requirement: No payment mutation before accepted terms

Discovery, filtering, preference, and proposal construction MUST use advertised options and local configuration only. Mandate approval MUST NOT occur until exact seller-accepted Agreement bytes and settlement data are durably recorded.

#### Scenario: Negotiation exits before acceptance

- **WHEN** the buyer declines, times out, or reaches a pricing limit
- **THEN** it creates no payment transaction or domain delivery operation

### Requirement: Identity-first buyer orchestration

The core buyer role MUST receive one injected marketplace signer for discovery-authenticated actions, negotiation, storefront settlement, heartbeat, and recovery. The signer-provided buyer identity MUST be the exact canonical `{scheme, identifier}` principal; identifier equality under a different scheme MUST NOT authorize the buyer. Core orchestration MUST resolve wallet and chain settings only when the selected domain or settlement adapter declares an EVM effect, and it MUST NOT name or pass private-key strings through schema-opaque orchestration.

#### Scenario: Buyer chooses Arkhai payments

- **WHEN** an Ed25519 buyer selects a compatible `arkhai.payments.v1` option
- **THEN** core negotiation and settlement use that signer while wallet, chain, RPC, token-balance, and gas checks are not invoked

#### Scenario: Buyer chooses Alkahest

- **WHEN** the selected obligation requires an Alkahest transaction
- **THEN** the Alkahest adapter separately resolves and validates its EVM wallet and chain inputs before the chain effect

### Requirement: Buyer recovery binds public principal

Buyer run logs MUST persist the exact canonical `{scheme, identifier}` public principal, signature-contract version, settlement obligation/operation identities, and domain state needed to resume, but MUST NOT persist private signing material. A recovery command MUST fail closed unless the available signer matches the recorded principal or an active replacement authorized by a completed rotation.

#### Scenario: Another signer resumes a run

- **WHEN** a valid signer whose principal is not authorized for the recorded buyer attempts recovery
- **THEN** the buyer refuses to continue or submit a settlement mutation

### Requirement: Buyer consumes common settlement preference

Buyer orchestration MUST filter advertised options by installed/enabled mechanisms and use the canonical configured priority as policy input before accepted Terms. It MUST resolve mechanism-specific prerequisites only after a concrete option is selected and MUST NOT treat priority as permission to switch an accepted obligation.

#### Scenario: Arkhai payments is preferred

- **WHEN** a compatible Arkhai payment and Alkahest option are both advertised and `arkhai.payments.v1` is first in buyer priority
- **THEN** the buyer policy may select Arkhai payments without resolving wallet, chain, RPC, token, or gas inputs

#### Scenario: Preferred option is incompatible

- **WHEN** the first-priority mechanism has no compatible advertised option
- **THEN** policy may evaluate the next configured mechanism before negotiation acceptance, but it does not rewrite a seller option or invent fallback after acceptance

### Requirement: Buyer config template is role-appropriate

Generated buyer configuration MUST use the shared `[Settlement]` vocabulary while omitting seller-only publication, authority administration, onboarding, and provider fields. Mechanism-specific buyer constraints MAY appear only in the owning typed subsection.

#### Scenario: Payments-only buyer initializes configuration

- **WHEN** the user generates an Ed25519 payment buyer config
- **THEN** the output contains profile-store and settlement preference inputs but no private identity or wallet/chains

### Requirement: Core owns profile selection and signer injection

The core `market profile` surface MUST provide create, import, list, show, select, rotate, retire, and delete without requiring a domain plugin. Fresh domain commands MUST receive one resolved selected-primary signer plus safe immutable profile context. Recovery commands MUST receive the exact signer recorded by profile UUID and canonical principal in the run, regardless of current selection.

Every buyer plugin MUST declare `core.resolved-buyer-identity.v1`; plugin discovery MUST fail before command registration when the contract is absent. Plugins MUST NOT read `[Identity]`, resolve a raw marketplace credential, or add a fallback provider.

#### Scenario: Selection changes between fresh and resumed work

- **WHEN** a new profile is selected after a run was accepted
- **THEN** a fresh run uses the new primary signer while `--from` resolves the accepted run's retained profile and principal

#### Scenario: No profile is selected

- **WHEN** a fresh buyer command starts without one selected active profile
- **THEN** it fails before discovery, negotiation, settlement, or a domain-specific effect

### Requirement: Buyer configuration references profiles without secrets

Generated buyer configuration MUST reference the XDG profile store and credential-provider setup workflow, reject direct legacy `[Identity]` and raw secret aliases, and keep optional wallet/chain settings independent.

#### Scenario: Headless configuration is generated

- **WHEN** strict file or explicit environment credential storage is selected
- **THEN** output contains only the provider kind, bounded locator guidance, and profile commands, never the resolved signing value

### Requirement: Payment buyers preserve accepted state

VM, bare-metal, and API-credit buyers selecting `arkhai.payments.v1` MUST retain exact Agreement bytes, the advertised option, opaque settlement selection parameters, and seller-derived `settlement_data`. Resume MUST reuse that accepted state and transaction identity, not current priority or an incomplete reconstructed listing.

#### Scenario: Payment buyer resumes after approval

- **WHEN** the accepted run is resumed after an approval acknowledgement is lost
- **THEN** it validates and reuses the same mandate and transaction, then retrieves or resumes the same domain result without renegotiation

#### Scenario: Bare-metal buyer retrieves access

- **WHEN** the recorded buyer retrieves an active selected-site lease result
- **THEN** authenticated transient access coordinates are delivered separately from public payment state and never enter the run log

#### Scenario: API-credit buyer retrieves a grant

- **WHEN** a verified payment has issued credits but the buyer did not observe credentials
- **THEN** it retrieves the same grant through the authenticated seller boundary rather than approving or issuing again

### Requirement: Payment buyers approve and settle by negotiation

The buyer MUST supply its Arkhai account as `payer_account`, validate the mandate against the Agreement and local payment policy, approve with owner-scoped WorkOS credentials, poll the deterministic transaction ID, and call seller settlement with only the negotiation ID. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials.

#### Scenario: Payment and marketplace credentials stay separate

- **WHEN** a payment buyer approves a mandate and then settles
- **THEN** the approval uses the owner's WorkOS credential, and the settle request is signed by the recorded profile signer and carries only the negotiation ID

### Requirement: The typed client settles Agreement deals apart from EVM deals

The typed storefront client MUST settle an Agreement-settled deal with `settle_agreement(negotiation_id)`, which sends only the negotiation ID and the signer's principal; EVM settlement is the separate `settle_evm`, so EVM arguments never appear on the agreement path. Both use the settle route contract, and the storefront dispatches on the accepted Agreement's mechanism.

#### Scenario: A buyer settles a payments deal through the typed client

- **WHEN** a buyer settles an accepted Arkhai payments deal with `settle_agreement`
- **THEN** the request carries the negotiation ID and the buyer's principal and no EVM fields

### Requirement: Agreement-settlement responses are strict on both sides

The client MUST refuse an agreement-settlement or refund response missing a required field, and each storefront MUST validate its payment payload through the core response models before returning it.

#### Scenario: A drifted settlement response is refused

- **WHEN** an agreement-settlement or refund response omits a required field
- **THEN** the client raises a storefront client error rather than returning a partial result

### Requirement: Negotiation opens from the selected advertised option

When a domain's buyer hook selects a settlement option, buyer orchestration MUST resolve that selection to the option the listing advertises before negotiating, and MUST give that option's rate and acceptance contract to the negotiation policy and to settlement revalidation. A selection that resolves to no advertised option MUST end that candidate's attempt before revalidation and without contacting its seller.

#### Scenario: A listing advertises differently priced options

- **WHEN** a buyer selects a listing's payment option and the listing also advertises an escrow option at another rate
- **THEN** negotiation opens with the payment option's mechanism and option ID, at an amount derived from the payment option's rate

#### Scenario: A selection names nothing the listing advertises

- **WHEN** a hook's selection names a mechanism or option ID absent from the listing's advertised options
- **THEN** the candidate's attempt exits as `unadvertised_settlement_selection`, and no negotiation is opened with its seller

### Requirement: The match cap counts candidates the buyer can settle with

A buy command's limit on the matches it tries MUST count only candidates with a usable settlement choice: a candidate with none MUST NOT take one of the tries.

#### Scenario: Some discovered listings cannot be settled with

- **WHEN** a buyer limits a purchase to N matches and some earlier discovered listings advertise no option the buyer can use
- **THEN** the buyer negotiates with up to N listings that do, and no unusable listing takes one of the N tries

### Requirement: Credit purchases stop selecting at the match cap

`market credits buy` MUST choose settlement for discovered listings in discovery order and stop once its match limit's worth of usable candidates is found, so no buyer is prompted, and no settlement prerequisite is read, for a listing past the limit.

#### Scenario: More usable listings are discovered than the limit

- **WHEN** a credit buyer limits a purchase to N matches and more than N discovered listings have a usable settlement choice
- **THEN** selection evaluates no listing after the Nth usable one

### Requirement: A buyer funds only what it derives

A buyer MUST fund an Alkahest escrow only from terms it derives itself, through its
domain's mechanism hooks, from its accepted proposal or selection and the release
condition the selected listing advertised, and MUST NOT fund terms a seller supplied.
The buyer MUST require the seller's accept reply to carry a settlement plan, and its
derivation to equal the plan's obligation before funding, on every path that funds an
escrow, through the plan check its domain supplies; a reply carrying none MUST be refused
before funding, naming `seller_plan_missing`. A buyer MUST record the selected listing's
advertised release conditions in its run-log at acceptance, and a resumed run MUST derive
the escrow from its recorded accepted proposal and those recorded conditions, at the
recorded Agreement's exact amount, and hold it to the recorded seller plan. A resumed run
whose run-log predates the recorded conditions and records no escrow MUST NOT fund one: it
MUST end naming that the run was accepted before release conditions were recorded.

#### Scenario: A seller's plan names another recipient

- **WHEN** a seller's accept reply carries a plan whose release condition pays a recipient
  other than the one its listing advertised
- **THEN** the buyer creates no escrow and ends the run naming the mismatch

#### Scenario: An API-credit buyer proposes an escrow

- **WHEN** an API-credit buyer's escrow proposal is accepted
- **THEN** the buyer derives the escrow, checks it against the seller's plan, and funds
  its own derivation

#### Scenario: A seller's accept reply carries no plan

- **WHEN** a seller accepts an Alkahest escrow and its reply carries no settlement plan
- **THEN** the buyer creates no escrow and ends the run naming `seller_plan_missing`

#### Scenario: A run is resumed with only an accepted proposal

- **WHEN** a buyer resumes a run whose run-log holds the accepted proposal, the Agreement,
  the seller's plan, and the listing's recorded release conditions, but no escrow
- **THEN** it derives the escrow from the accepted proposal and the recorded conditions at
  the Agreement's exact amount, requires it to equal the seller's plan, and creates it,
  rather than refusing

#### Scenario: A run-log predates recorded release conditions

- **WHEN** a buyer resumes a run whose run-log holds an accepted proposal and seller terms
  but no recorded release conditions and no escrow
- **THEN** it creates no escrow and ends the run naming that it was accepted before
  release conditions were recorded

### Requirement: Two domains may not register one root command

The core buyer application MUST refuse at startup when two installed domain plugins
register the same root-level command name, naming both domains and the command, rather
than letting the later registration replace or shadow the earlier one.

#### Scenario: Two plugins register `settlement`

- **WHEN** the buyer CLI starts with two installed domain plugins that each register a
  root-level `settlement` command group
- **THEN** it refuses to start, naming the command and both domains

#### Scenario: Bare metal's settlement commands are namespaced

- **WHEN** the buyer CLI starts with the VM and bare-metal plugins installed
- **THEN** it starts, VM's settlement commands are at the root, and bare metal's are
  under `market bare-metal settlement`

### Requirement: A bare-metal purchase pays the selected option's total for its duration

The bare-metal `buy` command MUST quote the selected payment option's one time-scaled `amount`
rate, identified by its field, over the requested duration, truncated to whole base units, and
MUST negotiate that quote as the deal's absolute bounds, scaled by no further unit count. A quote
that truncates to zero, and an option charging on any field other than `amount`, MUST be refused
before any request to the seller. Before the mandate is approved, and again inside the negotiation
before an accepted round is kept, the buyer MUST refuse an accepted Agreement whose amount differs
from the quote or whose duration differs from the one requested, and MUST end the run as exited
with that reason, so no approval follows and the run is not left open.

#### Scenario: Half an hour is bought

- **WHEN** a buyer buys 1800 seconds of an option charging 1000000 base units an hour
- **THEN** the buyer negotiates 500000 as both its opening and its ceiling, with a unit count of one

#### Scenario: The seller's Agreement pays another amount

- **WHEN** the accepted Agreement for that purchase names 250000, or another duration
- **THEN** the buyer refuses it, no mandate is approved, and the run ends as exited

#### Scenario: The option charges another field

- **WHEN** a payment option carries a rate on a field other than `amount`, beside its amount
  rate or alone
- **THEN** the command refuses before any negotiation request

#### Scenario: The quote is zero

- **WHEN** a buyer buys 60 seconds of an option charging 1 base unit an hour
- **THEN** the command refuses before any negotiation request
