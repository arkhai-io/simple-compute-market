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

### Requirement: Buyer evidence is separate from private delivery

Buyer settlement progress MUST retain secret-free SettlementEvidence correlated to the accepted negotiation when supplied by the selected stage. Delivery results and credentials MUST remain in the domain's authenticated result handling and MUST NOT be substituted for settlement evidence or persisted as public run evidence.

#### Scenario: Buyer retrieves a delivered API key

- **WHEN** the buyer retrieves a grant after settlement has completed
- **THEN** settlement evidence retains its accepted reference while the bearer credential uses the private result boundary and stays out of the run log

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

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Payment approval is an internal accepted-run step, not payer-profile administration. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism inputs from the selected option, persistent buyer profile, and accepted run and MUST NOT accept chain-, token-, provider-, raw payer-ref-, or browser-specific override flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

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

#### Scenario: Fiat-only buyer initializes configuration

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

VM, bare-metal, and API-credit buyers selecting `arkhai.payments.v1` MUST retain exact Agreement bytes, the advertised option, opaque settlement selection parameters, and seller-derived `settlement_data`. The buyer MUST supply its Arkhai account as `payer_account`, validate the mandate against the Agreement and local payment policy, approve with owner-scoped WorkOS credentials, poll the deterministic transaction ID, and call seller settlement with only the negotiation ID. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials. Resume MUST reuse accepted state and transaction identity, not current priority or an incomplete reconstructed listing.

#### Scenario: Payment buyer resumes after approval

- **WHEN** the accepted run is resumed after an approval acknowledgement is lost
- **THEN** it validates and reuses the same mandate and transaction, then retrieves or resumes the same domain result without renegotiation

#### Scenario: Bare-metal buyer retrieves access

- **WHEN** the recorded buyer retrieves an active selected-site lease result
- **THEN** authenticated transient access coordinates are delivered separately from public payment state and never enter the run log

#### Scenario: API-credit buyer retrieves a grant

- **WHEN** a verified payment has issued credits but the buyer did not observe credentials
- **THEN** it retrieves the same grant through the authenticated seller boundary rather than approving or issuing again
