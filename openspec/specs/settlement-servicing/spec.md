# Settlement Servicing Specification

## Purpose

Define the implemented mechanism-neutral settlement-plan carrier, persisted claim servicing, and signed heartbeat evidence.
## Requirements

### Requirement: Hosted obligation pins profile and authorization

Every newly accepted `fiat.stripe.v1` obligation MUST carry one exact `funding_profile`, deterministic marketplace operation ID, and operation-scoped `funding_authorization_ref` whose hosted materialization fingerprint agrees with accepted amount, currency, payer, claimant, destination account, expiry, and condition. The mechanism-neutral runtime MUST treat the profile and safe authorization reference as immutable mechanism parameters and MUST reject changed reuse.

Marketplace persistence MUST NOT contain a stable hosted payer/instrument ref, Customer, PaymentMethod, mandate, bank/card detail, provider ID/payload, client secret, or raw action. New operations MUST accept only `card.v1`, `us_bank_transfer.v1`, or `us_ach_debit.v1`; legacy card representation is recovery-only.

#### Scenario: Authorization and plan profiles differ

- **WHEN** hosted materialization reports that the authorization does not bind the accepted obligation/profile
- **THEN** servicing fails before funding and does not request another authorization or profile

#### Scenario: Exact materialization is retried

- **WHEN** the same obligation, profile, authorization reference, and operation ID are retried after uncertain acknowledgement
- **THEN** the runtime and adapter reuse one hosted settlement and operation identity

### Requirement: Authoritative profile funding precedes every domain effect

For hosted obligations, only the authority's provider-neutral `funded` state after the exact profile's success and availability gate MAY transition the shared runtime into fulfillment. Setup/payment redirects, confirmation, bank instructions, Checkout completion, webhook-derived local hints, and pending/deferred status MUST NOT authorize fulfillment, evidence, or collection. Status MAY persist only safe reason, deadline, and action metadata.

#### Scenario: ACH reports processing

- **WHEN** authoritative hosted status remains awaiting payment or availability
- **THEN** no domain fulfillment lease, fulfillment side effect, condition evidence, or collect operation is reserved

#### Scenario: Push-transfer instructions were displayed

- **WHEN** the buyer received bank instructions but attributable funds are not authoritatively funded
- **THEN** servicing remains pending and does not treat interaction as payment

### Requirement: Profile-specific reclaim and loss remain authority-owned

The marketplace MUST request reclaim through the same opaque hosted settlement and operation identities and project provider-neutral pending/success/manual outcomes. It MUST NOT select a Stripe cancellation, return, refund, reversal, or dispute operation. A pre-fulfillment funding return MUST block fulfillment and collection and follow hosted reclaim/recovery. A return after fulfillment starts but before collection MUST preserve the immutable fulfillment record, block collection, order domain-owned VM teardown and capacity cleanup to convergence, and delegate financial return/reclaim entirely to the hosted authority. A post-collection loss MUST project an incident/manual status without rewriting completed marketplace fulfillment or attempting local reclaim.

#### Scenario: ACH returns before fulfillment

- **WHEN** hosted authority reports the accepted debit returned before the marketplace committed fulfillment
- **THEN** the runtime performs no fulfillment or collection and follows the eligible reclaim/recovery state

#### Scenario: Funding returns after VM fulfillment

- **WHEN** authoritative funding returns after VM fulfillment committed but before collection reserved or succeeded
- **THEN** collection remains blocked, the immutable fulfillment record remains attributable, VM teardown and capacity cleanup converge, and hosted financial recovery proceeds without marketplace-selected provider action

#### Scenario: ACH return appears after collection

- **WHEN** hosted status reports a post-collection loss incident
- **THEN** marketplace keeps completed fulfillment and collection identities and exposes safe operator-required state

### Requirement: Legacy card obligations recover without public alias

A migrated marketplace row whose accepted plan used the historical card-only shape MUST continue status, fulfillment, collection, and reclaim recovery with its original option, obligation, hosted settlement, and operation identities. The legacy decoder MUST be selected only from persisted historical state and MUST NOT be used by publication, negotiation, new materialization, or configuration.

#### Scenario: Legacy card row is pending at upgrade

- **WHEN** the shared runtime loads a nonterminal historical card obligation
- **THEN** it resumes the exact legacy hosted operation without requiring a new payer profile, funding authorization, or `card.v1` relabel
### Requirement: Negotiation-to-plan handoff
Negotiation MUST produce deterministic Terms and the settlement path MUST
register every accepted obligation as a mechanism-neutral Settlement Plan
before a fulfillment side effect begins. A seller MAY adopt a separately
verified pre-materialized obligation without invoking materialization again.

#### Scenario: Pre-materialized escrow is accepted
- **WHEN** the seller verifies the exact obligation represented by an existing
  mechanism reference
- **THEN** the runtime registers the accepted plan and idempotently adopts that
  reference for the verified obligation index before fulfillment

### Requirement: Mechanism-neutral plan carrier
Core settlement-plan carriers MUST express lifecycle-universal fields and
carry mechanism-specific data in tagged `{mechanism, params}` envelopes.

#### Scenario: New settlement mechanism is added
- **WHEN** a composition registers a client for a new mechanism
- **THEN** the settlement runtime carries its opaque parameters and public-safe
  outcomes without importing the mechanism kit

### Requirement: Durable idempotent servicing
The settlement-runtime worker MUST bind one immutable fulfillment reference,
persist every condition/effect attempt through the canonical operation
journal, retry transient or pending outcomes, and avoid duplicate successful
collection across restarts.

#### Scenario: Collection succeeds before a restart
- **WHEN** the worker resumes the same obligation
- **THEN** it observes the durable terminal state and does not collect twice

#### Scenario: Condition remains pending across restart
- **WHEN** a client returns pending with updated opaque mechanism state
- **THEN** the repository persists that state before backoff and supplies it to
  the next authoritative status or condition check

### Requirement: Signed heartbeat evidence
The buyer MAY emit signed deal heartbeats while service is healthy; the seller
MUST authenticate the signer as the exact canonical scheme-tagged principal
authorized as the deal buyer and persist accepted heartbeats as deal-scoped
evidence.

#### Scenario: Heartbeat identity mismatches the deal
- **WHEN** a heartbeat signature does not authenticate the complete principal
  authorized as the deal buyer
- **THEN** the seller rejects it without updating settlement evidence

### Requirement: Mechanism clients own mechanism vocabulary
Alkahest-specific plan, status, arbiter, collection, and reclaim encoding MUST
live in the Alkahest kit behind the shared conditional-escrow client port.

#### Scenario: Runtime evaluates an Alkahest obligation
- **WHEN** it needs mechanism-specific status, readiness, collection, or
  reclaim behavior
- **THEN** it dispatches through the registered Alkahest client with the stable
  operation reference and prior durable mechanism state

### Requirement: Durable independent obligation lifecycle
Settlement servicing MUST derive stable repository identity for every ordered
plan obligation and MUST persist materialization, condition evaluation,
collection, reclaim, attempt, uncertain-acknowledgement, and receipt state
independently. Equivalent retries MUST reuse one operation identity; changed
reuse MUST fail closed. Collection and reclaim MUST reserve one mutually
exclusive compare-and-swap winner before mechanism I/O.

#### Scenario: Plan contains obligations in both directions
- **WHEN** an accepted plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized by its payer and collected by its claimant without interpreting list position as direction

#### Scenario: One obligation fails after a sibling completes
- **WHEN** a plan operation requires retry or manual repair after another obligation reached a terminal effect
- **THEN** the completed sibling remains terminal and operator status identifies the affected obligation without replaying the completed effect

#### Scenario: Acknowledgement is uncertain across restart
- **WHEN** a mechanism mutation may have succeeded before its acknowledgement was lost
- **THEN** the operation journal records uncertainty and retry uses the same obligation and operation identity

#### Scenario: Collection races reclaim
- **WHEN** claimant collection and payer reclaim concurrently target one obligation
- **THEN** exactly one reservation may invoke the mechanism and the other observes a busy or terminal outcome

### Requirement: Deterministic interval and penalty-bond policy
The Alkahest settlement policy MUST be able to split an accepted positive total
across deterministic time intervals and create an explicit seller-funded,
buyer-claimable penalty bond. Interval amounts MUST be positive, proportional
to interval duration, allocate integer remainder to earliest intervals, and
sum exactly to the accepted total. Derived obligations MUST preserve the
accepted mechanism demand bytes and payer/claimant direction.

#### Scenario: Duration has a short final interval
- **WHEN** a duration is not evenly divisible by the interval size
- **THEN** the final boundary uses the remaining duration and all interval amounts still conserve the accepted total exactly

#### Scenario: Total is too small for positive intervals
- **WHEN** splitting would create a zero-value obligation
- **THEN** policy rejects the schedule before materialization

#### Scenario: Seller penalty bond is accepted
- **WHEN** accepted policy requires a penalty bond
- **THEN** the resulting obligation names the seller as payer, the buyer as claimant, and is serviced independently from buyer-funded payment obligations

### Requirement: Aggregate and per-obligation status
Operator-facing settlement status MUST derive the plan aggregate from every
authoritative obligation row and MUST include each obligation's lifecycle
state. Aggregate status MUST be `complete` only when every obligation has a
successful collection or reclaim, `manual_required` when any obligation needs
repair, `partial` when only some obligations are terminal, and `active`
otherwise.

#### Scenario: Mixed terminal and active obligations
- **WHEN** one obligation is collected while a sibling remains pending
- **THEN** aggregate status is partial and both independent states are visible

### Requirement: Hosted financial authority lifecycle

`fiat.stripe.v1` MUST use the shared obligation journal and conditional-escrow port while the separately operated hosted service remains the sole payer-profile and financial authority. Marketplace rows MUST contain only exact funding profile, operation-scoped funding authorization and settlement references, public lifecycle/reason/deadline/action metadata, condition anchors, canonical fulfillment references, and opaque receipts; they MUST NOT persist stable payer/instrument refs, provider identifiers, Checkout/setup/confirmation/bank-instruction URLs, payment/bank/card/mandate data, credentials, or raw evidence/provider payloads.

#### Scenario: Hosted funding becomes authoritative

- **WHEN** the hosted authority reports the accepted obligation and exact profile funded
- **THEN** the storefront provisions once, binds one immutable condition evidence reference, and only then reports the settlement ready and resumes check/collect through the shared worker

#### Scenario: Reclaim races fulfillment

- **WHEN** the buyer reclaims at expiry while fulfillment, satisfied evaluation, or collection is reserved or complete
- **THEN** the repository compare-and-set rejects reclaim; pending or false evaluation alone does not prevent an otherwise eligible reclaim

#### Scenario: Hosted funding remains delayed

- **WHEN** a bank profile reports a safe pending state or future availability deadline
- **THEN** the shared runtime retains the same obligation and operation without fulfillment, collection, or mechanism fallback

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MAY contain one exact public funding profile and operation-scoped authorization reference but MUST NOT expose a stable payer/instrument or provider model to the runtime.

#### Scenario: Hosted materialization requires buyer action

- **WHEN** `fiat.stripe.v1` materialization or confirmation creates a hosted action
- **THEN** the runtime persists the opaque hosted reference and public action kind/expiry while the URL/client secret remains transient and service-owned

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

### Requirement: Versioned hosted condition input

A hosted obligation MUST carry exactly one immutable condition descriptor with a unique condition ID, a versioned evaluator kind, a configuration-owned resolver ID where applicable, and canonical demand encoded as either `evm-abi` or `application/jcs+json`. Negotiated condition parameters MUST contain immutable policy inputs only and MUST NOT contain credentials, URLs, RPC endpoints, headers, or signing keys.

#### Scenario: Hosted option contains an unconfigured resolver URL
- **WHEN** the adapter validates a condition whose negotiated parameters contain a caller-supplied resolver URL
- **THEN** materialization fails before buyer payment action is created

### Requirement: Hosted adapter validation and state projection

The `fiat.stripe.v1` adapter MUST accept only buyer-funded, seller-claimed obligations with a positive integer minor-unit amount, lowercase ISO 4217 currency, immutable account reference, exact supported funding profile, operation-scoped funding authorization reference, expiry, and supported typed condition. It MUST verify exact client/manifest/schema/profile capability before use. Provider-neutral awaiting-payment, action-required, deadline, return, and loss states MUST map monotonically into the shared lifecycle. Hosted `operator_review` or post-collection loss MUST project as `manual_required` without inventing a successful outcome or provider detail.

#### Scenario: Condition is not currently satisfied

- **WHEN** the hosted authority returns an authoritative false evaluation before expiry
- **THEN** the shared worker retains a pending condition and may check again without collecting or marking terminal failure

#### Scenario: Hosted authority requires operator review

- **WHEN** status reports `operator_review`
- **THEN** marketplace state reports manual intervention and does not collect, reclaim, or guess provider outcome

#### Scenario: Profile is unsupported by the release

- **WHEN** an accepted new-format obligation names a profile absent from the verified client/manifest capability set
- **THEN** adapter admission fails closed before materialization

### Requirement: Fulfillment and reclaim exclusion

Hosted servicing MUST use the shared obligation identity, exact profile and authorization, operation journal, work leases, and compare-and-set transitions. At stored expiry, reclaim MAY reserve only after re-retrieving current hosted state and only when no authoritative funded state, fulfillment lease or success, submitted collect/provider transfer, or reserved satisfied evaluation exists. Authoritative funded state MAY begin fulfillment; fulfillment success MUST permanently remove marketplace reclaim authority and MUST resume check and collect after restart even when expiry subsequently passes.

#### Scenario: Fulfillment succeeds immediately before expiry

- **WHEN** immutable VM fulfillment commits before the reclaim compare-and-set
- **THEN** reclaim is rejected and restart resumes hosted condition check and collection

#### Scenario: Pending condition reaches expiry without fulfillment success

- **WHEN** no authoritative funding/fulfillment lease or success, collect reservation, or satisfied evaluation exists at expiry after current hosted status retrieval
- **THEN** reclaim may reserve and the shared lifecycle prevents a later collect reservation

#### Scenario: Funding wins at expiry

- **WHEN** re-retrieval proves the accepted bank operation funded before reclaim reservation
- **THEN** the runtime proceeds toward fulfillment under the same obligation rather than reclaiming or releasing it as unpaid

### Requirement: Secret-free fulfillment projection

The VM domain MUST encode only the versioned evidence allowed by the accepted condition. EAS mode MUST send a configured resolver ID and fulfillment UID; portable mode MUST send only the allowlisted proof projection. Generic fulfillment results, tenant credentials, SSH material, connection details, arbitrary provider fields, URLs, and headers MUST NOT enter fulfillment references, hosted requests, settlement rows, logs, or generated fixtures.

#### Scenario: VM fulfillment contains connection credentials
- **WHEN** a condition evidence projection is generated from a successful fulfillment result
- **THEN** credentials and connection fields are absent and a canary test rejects any projection that would include them


### Requirement: Principal-bound settlement evidence and authority

Settlement plans, accepted fulfillment references, heartbeats, start/status/reclaim requests, claims, and operation-journal authorization MUST bind payer, claimant, storefront, and service actors as canonical scheme-tagged principals. Matching a bare address, identifier, hosted account reference, or provider identifier MUST NOT grant settlement authority.
The mechanism-neutral runtime MUST treat those principals as opaque
authorization values and MUST NOT infer or persist wallet or private-key aliases
from them.

#### Scenario: Heartbeat uses the wrong scheme

- **WHEN** a heartbeat identifier matches the recorded buyer text but its principal scheme differs
- **THEN** the storefront rejects the heartbeat and does not update evidence or reclaim timing

#### Scenario: Hosted buyer reclaims without a wallet

- **WHEN** an authorized Ed25519 payer requests reclaim after the hosted obligation becomes eligible
- **THEN** the mechanism-neutral runtime and hosted client submit the stable operation without resolving wallet or chain settings

#### Scenario: Either participant reconciles shared status

- **WHEN** the payer-facing status route and claimant-side servicing worker reconcile the same non-terminal obligation
- **THEN** both calls share one principal-bound status operation keyed by the canonical payer and claimant pair rather than conflicting on which authorized participant initiated the poll

### Requirement: Chain credentials are mechanism-scoped

A settlement adapter MAY require an EVM address, wallet, RPC endpoint, chain ID, or deployed contract only for an obligation whose selected mechanism or condition performs that EVM effect. Generic settlement carriers and hosted non-EVM obligations MUST NOT require or infer those values from marketplace principals.

#### Scenario: Hosted condition is non-EVM

- **WHEN** a `fiat.stripe.v1` obligation uses an admitted built-in or signed non-EVM condition
- **THEN** materialization, check, collect, reclaim, and reconciliation run with no EVM credential or RPC dependency

#### Scenario: EAS condition is selected

- **WHEN** a hosted or Alkahest obligation selects a condition whose contract requires an EVM subject or transaction
- **THEN** the owning adapter validates the explicitly tagged EVM input without reinterpreting an Ed25519 principal

### Requirement: Hosted client owns hosted identity wire

The hosted settlement adapter and payer/authorization consumer MUST pass the selected or recorded persistent marketplace signer through the exact manifest-pinned hosted client identity interface and MUST NOT duplicate hosted canonicalization, headers, scheme implementations, response verification, payer/profile models, authorization encoding, setup/confirmation behavior, or provider models.

#### Scenario: Hosted release lacks the required identity capability

- **WHEN** buyer/storefront startup or publication preflight sees a hosted manifest that does not advertise the configured principal, payer, authorization, and funding-profile contract versions
- **THEN** hosted settlement remains unavailable and no fiat option or funding authorization is created

### Requirement: Configuration composes one settlement runtime

Each composition root MUST build installed mechanism clients from the typed settlement registrations and inject them into the single mechanism-neutral settlement runtime. Enablement, priority, or mechanism-specific commands MUST NOT create a parallel lifecycle, operation journal, claim engine, retry loop, or status authority.

#### Scenario: Both mechanisms are enabled

- **WHEN** Alkahest and hosted Stripe registrations are ready
- **THEN** both dispatch through the same obligation identity, operation journal, leases, retry rules, and aggregate status contract

### Requirement: Mechanism configuration cannot reinterpret durable plans

Mechanism configuration and readiness MAY govern new option publication and admission, but a persisted accepted plan MUST retain its canonical mechanism, exact parameters, payer/claimant direction, and stable operation identities. Recovery MUST use authoritative stored state even when that mechanism is no longer preferred or enabled for new deals.

#### Scenario: Hosted mechanism is disabled after funding

- **WHEN** reconciliation resumes an existing funded hosted obligation after operators disable new hosted publication
- **THEN** the runtime continues authoritative status/collection/reclaim recovery for that obligation rather than switching or abandoning it

### Requirement: Accepted domain binding governs the servicing lifecycle

Settlement verification, plan construction, materialization, condition/effect servicing, capacity, fulfillment scheduling, status/result projection, recovery, and teardown MUST resolve the exact contract bound to the accepted negotiation. A safe copy of that binding and trusted site MUST be persisted with the fulfillment context and compared on every restart. Live listing state, request payloads, current pool mode, result kind, and installed-contract order MUST NOT redirect accepted work.

#### Scenario: VM and bare-metal obligations service concurrently

- **WHEN** one process services accepted VM and bare-metal negotiations
- **THEN** each operation invokes only its recorded contract through the domain-neutral settlement and fulfillment contexts and addresses only its recorded site

#### Scenario: Selected result kind is wrong

- **WHEN** the recorded site's fulfillment result contains a domain result rejected by the accepted contract's result codec
- **THEN** recovery reports a data-integrity failure before persisting result or credential state and does not try another codec

#### Scenario: Teardown repeats after restart

- **WHEN** recovery repeats teardown for a recorded fulfillment/reservation
- **THEN** it addresses the same site and durable identities while the provisioning authority dispatches its recorded executor kind; no current publication mode or VM default is consulted

#### Scenario: Contract is unavailable after acceptance

- **WHEN** a recoverable operation's exact domain/version is not installed or its site trust binding is missing
- **THEN** the operation remains blocked under its original identities and no capacity, fulfillment, settlement, result, or teardown call occurs

## Evidence

- Plan envelopes and lifecycle-universal fields:
  `core/src/market_core/schemas.py` and `kit/alkahest/tests/unit/test_plans.py`.
- Stable obligation identity, operation journals, migration/backfill, work
  leases, compare-and-swap transitions, and aggregate status:
  `core/storefront/src/core_storefront/{settlement_lifecycle,settlement_runtime,sqlite_client,sqlite_migrations}.py`.
- Restart, uncertain acknowledgement, payer/claimant direction, partial
  outcomes, and collect/reclaim exclusion:
  `core/storefront/tests/unit/test_settlement_{runtime,obligation_persistence}.py`.
- Exact interval conservation and seller-funded bond policy:
  `kit/alkahest/src/market_alkahest/plans.py` and
  `kit/alkahest/tests/unit/test_plans.py`.
- Signed heartbeat authentication and persistence:
  `core/storefront/tests/unit/test_heartbeats.py`.
- Alkahest mechanism dispatch and claim hooks:
  `kit/alkahest/tests/unit/test_claims.py` and `test_claim_hooks.py`.
- Accepted-domain settlement/fulfillment carriers, exact-object dispatch, result codec routing, and mismatch rejection: `core/storefront/tests/unit/test_domain_lifecycle.py` and `domains/vms/storefront/tests/unit/test_settlement_composition.py`.
- Selected-site restart and teardown routing: `domains/vms/storefront/tests/unit/test_fulfillment_resume_runtime.py`, `test_fulfillment_service.py`, and `test_lease_truncation.py`.
