# Buyer Orchestration Specification

## Purpose

Define registry fan-in, domain plugins, policy-driven negotiation, aggregation, settlement, and run recovery.
## Requirements

### Requirement: Buyer payer-profile utilities are direct and namespaced

The core buyer CLI MUST expose hosted payer management under `market settlement stripe payer`. Create/show/delete, owner rotate/retire, setup/status, instrument list/default/revoke/delete commands MUST use the exact released hosted client and the selected or recorded persistent marketplace signer. Only these payer operations and exact per-purchase authorization MAY call the hosted authority directly; escrow start/status/reclaim remain storefront-mediated.

The local buyer profile MUST store only authority/environment, opaque payer binding, bound canonical principal, and safe lifecycle metadata. CLI output and metadata MUST exclude Customer, PaymentMethod, mandate, bank/card detail, client secret, provider payload/identifier, and raw action URL.

#### Scenario: Buyer creates a hosted payer profile

- **WHEN** the selected marketplace signer completes the released payer create operation
- **THEN** the local profile atomically records only the opaque authority binding and safe owner state

#### Scenario: Setup requires action

- **WHEN** payer setup returns a transient hosted action
- **THEN** the CLI applies `--action open|print|fail` and stores no URL or client secret

### Requirement: Exact purchase authorization precedes storefront start

After accepted terms are durably recorded and before hosted start, the buyer MUST construct the exact authorization from accepted obligation hash, amount, currency, destination account, funding profile, marketplace operation ID, expiry, local payer binding, and user-selected interactive mode or ready instrument. The selected profile signer MUST sign through the released hosted client. Exact retry MUST return the same `funding_authorization_ref`; changed input MUST fail without starting settlement.

Only the operation-scoped authorization reference MAY be written to the run log or submitted to the storefront. The buyer MUST revalidate local payer/instrument/profile readiness immediately before authorization and MUST NOT select another profile or instrument after acceptance.

#### Scenario: Instrument was revoked after negotiation

- **WHEN** the selected saved instrument is no longer ready before authorization
- **THEN** authorization fails without starting the storefront settlement or falling back to another instrument

#### Scenario: Authorization acknowledgement is lost

- **WHEN** the buyer retries the identical accepted obligation and marketplace operation ID
- **THEN** the hosted authority returns the same safe authorization reference and storefront start retains one operation identity

### Requirement: Off-session automation is buyer-owned and obligation-exact

When the configured automation policy exactly admits authority, profile, currency, amount, aggregate window, and optional seller principal, the buyer MAY sign the current exact purchase authorization without prompting. Policy failure, missing consent/mandate, revoked binding/instrument, or hosted `requires_action` MUST use the ordinary interactive action flow. The seller, storefront, listing, and hosted authority MUST NOT broaden or override local policy.

#### Scenario: Accepted purchase is within all bounds

- **WHEN** the buyer opted in and one accepted obligation matches every policy bound and ready saved-instrument requirement
- **THEN** the buyer signs only that exact authorization and records its safe operation-scoped reference

#### Scenario: Hosted confirmation is required

- **WHEN** an automated off-session attempt returns `requires_action`
- **THEN** the same obligation and operation continue through transient confirmation without switching instrument, profile, amount, destination, or operation ID

### Requirement: Delayed bank state is resumable and provider-neutral

Fresh and resumed buyer flows MUST understand provider-neutral awaiting-payment reason/deadline/action metadata for bank instructions, ACH processing, and off-session confirmation. Run logs MUST retain only opaque settlement and authorization refs, funding profile, public state/reason/deadline, action kind/expiry, and accepted identities. Resume MUST re-fetch current state and apply the current action policy; it MUST NOT rely on a persisted URL, bank detail, or provider status.

#### Scenario: Push transfer is awaiting funds

- **WHEN** status reports safe bank-instruction action metadata but no authoritative funding
- **THEN** the buyer may present the transient action and remains pending without claiming readiness

#### Scenario: ACH resumes after restart

- **WHEN** a run restarts while ACH remains pending its availability gate
- **THEN** the buyer reuses the exact settlement/authorization/operation identities and polls current public state without creating another debit
### Requirement: Plugin-composed buyer CLI
The core `market` CLI MUST discover domain plugins through entry-point metadata and let each plugin register namespaced verbs without core importing the domain.

#### Scenario: A domain plugin is installed
- **WHEN** the buyer CLI starts
- **THEN** the plugin's verbs are registered without the core package importing that domain

### Requirement: Linear buy orchestration
A buy run MUST compose discovery, candidate filtering/aggregation, negotiation, and settlement through injected hooks and persist stage results needed for inspection and recovery.

#### Scenario: Settlement response is lost
- **WHEN** the run log contains accepted terms and a deal reference
- **THEN** recovery can inspect or resume the deal without renegotiating a second agreement

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

### Requirement: Storefront-mediated hosted buyer action

After accepted terms, a VM buyer selecting `fiat.stripe.v1` MUST obtain one exact purchase authorization directly from the hosted authority, then start and poll the opaque settlement through the seller storefront. Direct hosted calls are limited to payer-profile/instrument management and exact purchase authorization; escrow creation, status, reclaim, fulfillment, and collection MUST remain mediated by the storefront. Setup, payment, confirmation, and bank-instruction actions are transient and MUST NOT enter run-log events.

#### Scenario: Buyer selects hosted Checkout

- **WHEN** explicit mechanism/profile/currency constraints select one advertised hosted option
- **THEN** the buyer records accepted terms, obtains the exact funding authorization, starts the accepted obligation by deterministic ID through the storefront, and reports ready only after the storefront confirms authoritative funding and fulfillment

### Requirement: Mechanism-neutral constrained preference

Buyer orchestration MUST normalize legacy escrow entries and settlement options into immutable preference candidates only after installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses MUST be evaluated in command order before configured-policy ranking, and every predicate in one clause MUST match the same advertised option. Policy output MUST NOT introduce an unadvertised or incompatible choice. When no explicit clause is supplied, configured mechanism priority remains the pre-acceptance policy input.

#### Scenario: Buyer requests hosted fiat
- **WHEN** a Stripe settlement clause and supported asset leave several hosted options
- **THEN** buyer policy ranks only those matching hosted options and exact deterministic fallback applies if it expresses no preference

#### Scenario: Buyer selects Alkahest
- **WHEN** an Alkahest clause or interactive choice selects an existing compatible Alkahest option
- **THEN** the existing escrow creation/submission path and run-log fields remain unchanged and no hosted API is called

#### Scenario: Several clauses match
- **WHEN** more than one explicit settlement clause has compatible candidates
- **THEN** the earliest matching clause wins before configured mechanism priority and no later clause is considered after acceptance

### Requirement: Hosted buyer action handling

Payer setup, accepted start, and resume MAY return a transient setup, payment, confirmation, or bank-instruction action. Fresh purchase and resume MUST apply the common `--action open|print|fail` policy. The CLI MUST persist only opaque payer binding where locally authorized, operation-scoped funding authorization and settlement references, public status/reason/deadline, action type, and expiry; it MUST NOT persist or log an action URL, client secret, bank/card/payment/customer data, stable instrument ref in storefront state, provider identity, request credential, or raw service body.

#### Scenario: Hosted Checkout action is returned

- **WHEN** settlement start returns a browser redirect action and action policy is `open`
- **THEN** the CLI opens it and stores only the allowed opaque action metadata

#### Scenario: Hosted Checkout action is printed

- **WHEN** settlement start or resume returns a browser redirect action and action policy is `print`
- **THEN** the CLI displays it without opening it or writing it to the run log

#### Scenario: Buyer resumes after losing the redirect

- **WHEN** a run log contains the hosted settlement and authorization references but no URL
- **THEN** the buyer retrieves the current action/status from the storefront and applies the current action policy rather than relying on a persisted URL or creating another settlement

#### Scenario: Bank instructions are returned

- **WHEN** payer or settlement state returns transient push-transfer instructions
- **THEN** the CLI presents them according to action policy and persists only safe kind, expiry, reason, and deadline metadata

### Requirement: Buyer normal path consumes two DSLs

Domain purchase commands MUST accept one resource-query DSL input and zero or more settlement-clause DSL inputs. Resource filtering MUST complete before settlement compatibility, clause ordering, negotiation policy, and any mechanism-specific prerequisite resolution. Removed convenience flags MUST NOT remain as hidden aliases or alternate precedence layers.

#### Scenario: Resource matches have no settlement match
- **WHEN** the resource query returns listings but the buyer has not enabled any mechanism advertised by those listings
- **THEN** the command reports a settlement incompatibility rather than claiming that the registry returned no resource listings

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Hosted payer lifecycle commands MUST live below `market settlement stripe payer`; direct purchase authorization is an internal accepted-run step rather than a top-level raw mutation. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism/profile inputs from the selected option, persistent buyer profile, and accepted run and MUST NOT accept chain-, token-, provider-, raw payer-ref-, or browser-specific override flags.

#### Scenario: Accepted Alkahest run is resumed

- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

#### Scenario: Buyer manages a saved ACH instrument

- **WHEN** the buyer invokes the Stripe payer instrument namespace
- **THEN** the released client uses the selected profile signer and returns only safe instrument metadata plus transient actions

### Requirement: No provider call before accepted terms

Discovery, filtering, preference, and proposal construction MUST use listing data plus local selected-profile readiness only. Hosted payer profile/setup/instrument management MAY occur as an explicit namespaced user command before a purchase, but exact purchase authorization, hosted escrow, and funding mutation MUST NOT occur until seller-accepted terms containing the exact settlement option/profile are durably recorded.

#### Scenario: Negotiation exits before acceptance

- **WHEN** the buyer declines, times out, or reaches a pricing limit before accepted terms
- **THEN** no purchase authorization, hosted escrow, Checkout/payment/debit, charge, transfer, refund, or settlement operation is created

#### Scenario: Buyer performs setup independently

- **WHEN** the buyer explicitly invokes a payer setup command without negotiating
- **THEN** only the payer-authorized setup lifecycle may run and no marketplace obligation or funding authorization is created


### Requirement: Identity-first buyer orchestration

The core buyer role MUST receive one injected marketplace signer for discovery-authenticated actions, negotiation, storefront settlement, heartbeat, and recovery. The signer-provided buyer identity MUST be the exact canonical `{scheme, identifier}` principal; identifier equality under a different scheme MUST NOT authorize the buyer. Core orchestration MUST resolve wallet and chain settings only when the selected domain or settlement adapter declares an EVM effect, and it MUST NOT name or pass private-key strings through schema-opaque orchestration.

#### Scenario: Buyer chooses hosted fiat

- **WHEN** an Ed25519 buyer selects a compatible `fiat.stripe.v1` option
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

#### Scenario: Hosted fiat is preferred

- **WHEN** a compatible hosted and Alkahest option are both advertised and `fiat.stripe.v1` is first in buyer priority
- **THEN** the buyer policy may select hosted fiat without resolving wallet, chain, RPC, token, or gas inputs

#### Scenario: Preferred option is incompatible

- **WHEN** the first-priority mechanism has no compatible advertised option
- **THEN** policy may evaluate the next configured mechanism before negotiation acceptance, but it does not rewrite a seller option or invent fallback after acceptance

### Requirement: Buyer config template is role-appropriate

Generated buyer configuration MUST use the shared `[Settlement]` vocabulary while omitting seller-only hosted account, authority administration, onboarding, publication, and provider fields. Mechanism-specific buyer constraints MAY appear only in the owning typed subsection.

#### Scenario: Fiat-only buyer initializes configuration

- **WHEN** the user generates an Ed25519 hosted-fiat buyer config
- **THEN** the output contains profile-store and settlement preference inputs but no private identity, wallet/chains, or seller account configuration

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

### Requirement: Bare-metal buyers preserve accepted hosted authority

The installed `bare-metal` buyer plugin MUST use the selected persistent profile signer, authenticated registry results, and one exact advertised settlement option. Hosted start, status, resume, and reclaim MUST use the core schema-opaque storefront transport. Buyer inputs MAY choose an advertised funding profile, bounded off-session behavior, lease duration, and an SSH public key; they MUST NOT supply seller, site, Physical Resource, executor, condition, or provider identities.

#### Scenario: Hosted-only buyer has no wallet

- **WHEN** an Ed25519 buyer selects a ready `fiat.stripe.v1` bare-metal option
- **THEN** discovery and settlement start without wallet, chain, RPC, Stripe model, or provider credential configuration
- **AND** persisted run output contains only accepted marketplace identities, operation-scoped references, safe action metadata, and physical public results

### Requirement: API-credit hosted buys share accepted-state transport

The API-credit buyer MUST select one exact advertised settlement option, verify
mechanism, profile, currency, interaction, service, quantity, key mode/key ID,
buyer and claimant against accepted seller state, and use the core hosted
start/status/reclaim/resume transport. A hosted-only Ed25519 buyer MUST NOT
resolve wallet, chain, RPC, or Alkahest state. Resume MUST reuse the recorded
principal, obligation, authorization, and settlement references.

#### Scenario: Hosted API-credit buyer resumes after restart
- **WHEN** the run log contains an accepted hosted plan and safe authorization reference
- **THEN** the buyer polls the same storefront settlement, handles current action metadata transiently, and neither renegotiates nor creates a second grant

#### Scenario: Hosted-only API-credit buyer starts
- **WHEN** policy enables only `fiat.stripe.v1`
- **THEN** selection and settlement run with the persistent Ed25519 signer and no wallet or chain resolution

## Evidence

- Core/domain import purity and entry-point composition: `core/buyer/tests/unit/test_carrier_purity.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Injected orchestration and aggregation-policy control: `core/buyer/tests/unit/test_orchestrator.py` and `kit/alkahest/tests/unit/test_aggregation.py`.
- Persisted negotiation resume and agreed-run settlement continuation: `domains/vms/buyer/tests/test_buyer_client_resume.py` and `domains/vms/buyer/tests/test_buy_resume_cli.py`.
- Policy-owned negotiation behavior: VM buyer policy and client tests.
- Constrained settlement preference and fallback precedence:
  `core/buyer/tests/unit/test_escrow_selection.py`.

Simultaneous command registration for every installed domain plugin is not independently covered by the cited tests; the baseline claim is limited to the plugin boundary and each shipped plugin's export contract.

