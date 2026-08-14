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
After accepted terms, a VM buyer selecting `fiat.stripe.v1` MUST start and
poll the opaque settlement through the seller storefront. It MUST NOT sign
requests directly to the hosted financial authority. Checkout URLs are
transient display/browser actions and MUST NOT enter run-log events.

#### Scenario: Buyer selects hosted Checkout
- **WHEN** explicit mechanism and asset constraints select one advertised
  hosted option
- **THEN** the buyer submits that exact selection during negotiation, starts
  the accepted obligation by deterministic ID, and reports ready only after
  the storefront confirms authoritative funding and fulfillment

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

After accepted terms are submitted, the buyer MAY start the accepted hosted obligation and retrieve its current action. Fresh purchase and resume MUST apply the common `--action open|print|fail` policy. The CLI MUST persist only the opaque settlement reference, public status, action type, and expiry; it MUST NOT persist or log an action URL, payment/customer/card data, provider identity, request credential, or raw service body.

#### Scenario: Hosted Checkout action is returned
- **WHEN** settlement start returns a browser redirect action and action policy is `open`
- **THEN** the CLI opens it and stores only the allowed opaque action metadata

#### Scenario: Hosted Checkout action is printed
- **WHEN** settlement start or resume returns a browser redirect action and action policy is `print`
- **THEN** the CLI displays it without opening it or writing it to the run log

#### Scenario: Buyer resumes after losing the redirect
- **WHEN** a run log contains the hosted settlement reference but no URL
- **THEN** the buyer retrieves the current action/status from the storefront and applies the current action policy rather than relying on a persisted URL or creating another settlement

### Requirement: Buyer normal path consumes two DSLs

Domain purchase commands MUST accept one resource-query DSL input and zero or more settlement-clause DSL inputs. Resource filtering MUST complete before settlement compatibility, clause ordering, negotiation policy, and any mechanism-specific prerequisite resolution. Removed convenience flags MUST NOT remain as hidden aliases or alternate precedence layers.

#### Scenario: Resource matches have no settlement match
- **WHEN** the resource query returns listings but the buyer has not enabled any mechanism advertised by those listings
- **THEN** the command reports a settlement incompatibility rather than claiming that the registry returned no resource listings

### Requirement: Buyer mechanism utilities are namespaced

Raw mechanism-specific setup, inspection, and mutation commands MUST live below `market settlement <mechanism>`. Normal `market buy`, `market settle`, resume, and accepted-obligation lifecycle commands MUST derive mechanism inputs from the selected option or accepted run and MUST NOT accept chain-, token-, provider-, or browser-specific flags.

#### Scenario: Accepted Alkahest run is resumed
- **WHEN** `market settle --from <run>` resumes Terms containing an Alkahest obligation
- **THEN** the command derives chain, token, decimals, and escrow identity from accepted state and typed configuration without legacy override flags

### Requirement: No provider call before accepted terms

Discovery, filtering, preference, and proposal construction MUST use listing data only. Stripe or hosted-authority mutation MUST NOT occur until seller-accepted terms containing the exact settlement selection are durably recorded.

#### Scenario: Negotiation exits before acceptance
- **WHEN** the buyer declines, times out, or reaches a pricing limit before accepted terms
- **THEN** no hosted escrow, Checkout Session, charge, account mutation, or provider operation is created


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
- **THEN** the output contains identity and settlement preference inputs but no wallet/chains or seller account configuration

## Evidence

- Core/domain import purity and entry-point composition: `core/buyer/tests/unit/test_carrier_purity.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Injected orchestration and aggregation-policy control: `core/buyer/tests/unit/test_orchestrator.py` and `kit/alkahest/tests/unit/test_aggregation.py`.
- Persisted negotiation resume and agreed-run settlement continuation: `domains/vms/buyer/tests/test_buyer_client_resume.py` and `domains/vms/buyer/tests/test_buy_resume_cli.py`.
- Policy-owned negotiation behavior: VM buyer policy and client tests.
- Constrained settlement preference and fallback precedence:
  `core/buyer/tests/unit/test_escrow_selection.py`.

Simultaneous command registration for every installed domain plugin is not independently covered by the cited tests; the baseline claim is limited to the plugin boundary and each shipped plugin's export contract.
