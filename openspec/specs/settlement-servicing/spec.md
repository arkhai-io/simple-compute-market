# Settlement Servicing Specification

## Purpose

Define Agreement-based payment settlement, escrow obligation servicing, and signed evidence.

## Requirements

### Requirement: Mechanism-neutral plan carrier

Settlement plans MUST carry stable participant/value fields and tagged `{mechanism, params}` envelopes for mechanisms using the obligation runtime. Existing carriers retain escrow claimant, expiration, and condition fields; Arkhai payments MUST consume the Agreement without constructing a `SettlementPlan` or `SettlementObligation` or implementing the conditional-escrow client port.

#### Scenario: Charge-first settlement is selected

- **WHEN** an Agreement selects `arkhai.payments.v1`
- **THEN** settlement uses the mandate and transaction receipt without creating an escrow obligation

### Requirement: Durable idempotent servicing

The Alkahest servicing path MUST bind one immutable fulfillment reference, persist each condition/effect attempt under a stable operation identity, retry transient or pending outcomes, and avoid duplicate successful collection across restarts.

#### Scenario: Collection succeeds before a restart

- **WHEN** the Alkahest servicing path resumes the same obligation
- **THEN** it observes the durable terminal state and does not collect twice

#### Scenario: Condition remains pending across restart

- **WHEN** Alkahest returns pending with updated opaque mechanism state
- **THEN** that state is persisted before backoff and supplied to the next authoritative status or condition check

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
live in the Alkahest kit behind the shared conditional-escrow client port. Where
a reclaim carries mechanism-scoped options, only the mechanism's own client MUST
interpret them; the buyer transport, storefront routes, and settlement runtime
that relay them MUST NOT name any option or condition its meaning on one.

#### Scenario: Runtime evaluates an Alkahest obligation
- **WHEN** it needs mechanism-specific status, readiness, collection, or
  reclaim behavior
- **THEN** it dispatches through the registered Alkahest client with the stable
  operation reference and prior durable mechanism state

#### Scenario: A mechanism needs a reclaim-only input

- **WHEN** a mechanism's reclaim requires an input that only its own client
  understands
- **THEN** that client alone reads it out of the reclaim's mechanism-scoped
  options and places it on its own request, and no relaying layer names it

### Requirement: Durable independent obligation lifecycle

Alkahest servicing MUST derive stable repository identity for every ordered plan obligation and persist materialization, condition evaluation, collection, reclaim, attempt, uncertain-acknowledgement, and receipt state independently. Equivalent retries MUST reuse one operation identity; changed reuse MUST fail closed. Alkahest collection and reclaim MUST reserve one mutually exclusive compare-and-swap winner before mechanism I/O.

#### Scenario: Plan contains obligations in both directions

- **WHEN** an accepted Alkahest plan contains buyer-funded and seller-funded obligations
- **THEN** each obligation is materialized by its payer and collected by its claimant without interpreting list position as direction

#### Scenario: One obligation fails after a sibling completes

- **WHEN** an operation requires retry or manual repair after another Alkahest obligation reached a terminal effect
- **THEN** the completed sibling remains terminal and operator status identifies the affected obligation without replaying the completed effect

#### Scenario: Acknowledgement is uncertain across restart

- **WHEN** an Alkahest mutation may have succeeded before its acknowledgement was lost
- **THEN** retry uses the same obligation and operation identity

#### Scenario: Collection races reclaim

- **WHEN** claimant collection and payer reclaim concurrently target one Alkahest obligation
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

Alkahest operator-facing settlement status MUST derive the plan aggregate from every authoritative obligation row and MUST include each obligation's lifecycle state. Aggregate status MUST be `complete` only when every obligation has a successful collection or reclaim, `manual_required` when any obligation needs repair, `partial` when only some obligations are terminal, and `active` otherwise.

#### Scenario: Mixed terminal and active obligations

- **WHEN** one Alkahest obligation is collected while a sibling remains pending
- **THEN** aggregate status is partial and both independent states are visible

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MUST NOT expose a stable payer, instrument, or provider model to the runtime.

Reclaim MAY additionally carry mechanism-scoped options supplied by the
requesting participant for that one operation. The runtime MUST pass them to the
mechanism client without interpreting them, MUST NOT persist them, and MUST NOT
project them into any receipt, mechanism state, or public status. Because two
reclaims of one obligation naming different options are two different requests,
the reclaim reservation MUST bind the options it was given, so that a later
reclaim naming different ones is refused rather than silently reusing the first
reservation.

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged

#### Scenario: A reclaim carries mechanism-scoped options

- **WHEN** a payer requests reclaim supplying options the selected mechanism understands
- **THEN** the runtime dispatches them to that mechanism's client unread and unstored, and the obligation's durable state gains no field naming them

#### Scenario: A second reclaim names different options

- **WHEN** a reclaim is requested for an obligation whose earlier reclaim reservation bound different options
- **THEN** the reservation is refused, and the refusal names a conflicting request rather than reaching the mechanism

#### Scenario: A mechanism that needs no options is unaffected

- **WHEN** a reclaim supplies no options, or supplies options to a mechanism that reads none
- **THEN** the operation proceeds exactly as it does today with no additional mechanism input

### Requirement: Secret-free fulfillment projection

The VM domain MUST encode only the versioned evidence allowed by the accepted mechanism's condition. Generic fulfillment results, tenant credentials, SSH material, connection details, arbitrary provider fields, URLs, and headers MUST NOT enter fulfillment references, settlement-stage evidence, settlement rows, logs, or generated fixtures.

#### Scenario: VM fulfillment contains connection credentials

- **WHEN** a condition evidence projection is generated from a successful fulfillment result
- **THEN** credentials and connection fields are absent and a canary test rejects any projection that would include them

### Requirement: Mechanism configuration cannot reinterpret durable plans

Mechanism configuration and readiness MAY govern new option publication and admission, but an accepted Agreement MUST retain its exact settlement mechanism, selected option, and parameters. Recovery MUST use the accepted Agreement and mechanism-owned operation identity even when that mechanism is no longer preferred or enabled for new deals.

#### Scenario: Payment mechanism is disabled after acceptance

- **WHEN** reconciliation resumes an existing Arkhai transaction after operators disable new Arkhai payment options
- **THEN** the transaction continues under its accepted mechanism and exact ID rather than switching or being abandoned

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
- **THEN** it addresses the same site and durable identities while the provisioning authority dispatches its recorded offering mode; no current publication mode or VM default is consulted

#### Scenario: Contract is unavailable after acceptance

- **WHEN** a recoverable operation's exact domain/version is not installed or its site trust binding is missing
- **THEN** the operation remains blocked under its original identities and no capacity, fulfillment, settlement, result, or teardown call occurs

### Requirement: Non-financial obligations are serviceable

An obligation with no amount, no asset, and no funding requirement MUST be a valid
obligation when its mechanism declares a non-financial deliverable. Servicing MUST
materialize it to ready on the mechanism's availability signal, report it satisfied,
and produce a receipt referencing the accepted `service_terms`, without requiring
funding state, a chain client, or an expiration-driven reclaim path.

#### Scenario: Servicing an introduction obligation

- **WHEN** a `contact-exchange.v1` obligation is registered and its mechanism reports
  the introduction available
- **THEN** the runtime records it ready, completes collection with a receipt, and no
  funding or reclaim machinery is invoked

### Requirement: Agreement-to-settlement-stage handoff

Negotiation MUST emit one explicit Agreement containing only accepted deal terms, and the selected settlement stage MUST consume that Agreement before domain provisioning begins. A successful negotiation is not evidence of funding or settlement. A mechanism may produce its own settlement evidence from the Agreement; the domain provisioning stage MUST receive that evidence before its protected provisioning effect.

#### Scenario: Arkhai payments agreement is accepted

- **WHEN** negotiation accepts an Agreement selecting `arkhai.payments.v1`
- **THEN** the seller derives the mandate from that Agreement and provisioning remains blocked until the seller verifies a matching signed transaction receipt

### Requirement: Principal-bound marketplace actions use exact actors

Settlement Agreements, accepted fulfillment references, heartbeats, payment approvals, status and refund requests, and mechanism operation authorization MUST bind the canonical scheme-tagged principals that the accepted negotiation and selected mechanism authorize. No address, identifier, payment account reference, provider identifier, or API credential may replace one. The marketplace MUST treat principals as opaque and MUST NOT infer or persist wallet or private-key aliases from them.

#### Scenario: Heartbeat uses the wrong scheme

- **WHEN** a heartbeat identifier matches the recorded buyer text but its principal scheme differs
- **THEN** the storefront rejects the heartbeat and does not update evidence or reclaim timing

#### Scenario: Arkhai buyer approves with its owner credential

- **WHEN** an authorized buyer approves an `arkhai.payments.v1` mandate using its owner's WorkOS user-scoped API credential
- **THEN** approval is bound to the buyer's Arkhai account and does not resolve wallet or chain settings

#### Scenario: Buyer and seller poll one transaction

- **WHEN** the buyer and seller poll the same accepted Arkhai transaction
- **THEN** both use the transaction ID derived from the accepted mandate, and the seller provisions only after receipt verification

### Requirement: Mechanism credentials remain scoped

A settlement mechanism MAY require an EVM address, wallet, RPC endpoint, chain ID, or deployed contract only when its selected effect performs that EVM operation. Generic settlement carriers and non-EVM mechanisms MUST NOT require or infer those values from marketplace principals.

#### Scenario: Arkhai payment uses no EVM credentials

- **WHEN** an `arkhai.payments.v1` Agreement is settled through the external HTTP service
- **THEN** approval, polling, receipt verification, and `reverse` require no EVM credential or RPC dependency

#### Scenario: Alkahest condition requires an EVM subject

- **WHEN** an Alkahest obligation selects a condition whose contract requires an EVM subject or transaction
- **THEN** the Alkahest kit validates the explicitly tagged EVM input without reinterpreting an Ed25519 principal

### Requirement: Arkhai payments settles charge-first from an agreement

The `arkhai.payments.v1` seller kit MUST derive a mandate from the exact accepted Agreement and return the mandate and Agreement, so both parties know the transaction ID before approval. Both parties MUST poll that same transaction ID. The seller MUST NOT provision until it verifies an Arkhai-signed receipt matching the transaction and the Agreement's `deal`.

#### Scenario: Seller derives a mandate before approval

- **WHEN** negotiation accepts an Agreement selecting `arkhai.payments.v1`
- **THEN** the seller returns the Agreement and its derived mandate, and both parties compute the same transaction ID before the buyer approves

#### Scenario: Seller provisions only on a matching signed receipt

- **WHEN** the seller polls the transaction ID and receives a receipt
- **THEN** it verifies the Arkhai signature and matching transaction and Agreement deal before provisioning, and rejects an invalid, absent, or mismatched receipt

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from`, the selected option's payee account as `to`, and one `once` part for the agreed amount and asset. It MUST use the service's published fee policy and the fixed nonce `arkhai.payments.v1`, and authorize `start` and `stop` for buyer and seller and `reverse` for the seller and Arkhai dispute authority.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** the hold is `ceil(start_utc - accepted_at) + duration_seconds + window` whole seconds, approval expires at `floor(accepted_at) + window`, and fractional timestamps stay unchanged in the Agreement and its deal hash

### Requirement: The buyer approves only a mandate it has checked

The buyer kit MUST check the mandate against the exact Agreement and its own policy before approving it with the owner's WorkOS user-scoped API credential. It MUST attach the exact Agreement at approval only when its `attach_agreement` policy is enabled, which it is not by default, and MUST NOT perform the seller's deposit.

#### Scenario: Buyer attaches only by its own policy

- **WHEN** the buyer approves a mandate with `attach_agreement` disabled
- **THEN** the approval carries no attachment, whatever the selected option's
  `deposit_agreement` setting

### Requirement: The seller deposits the Agreement before delivering

If the selected option sets `deposit_agreement` and the transaction has no Agreement attachment, the seller MUST attach it after verifying the receipt and before any delivery effect. A failed deposit MUST be retryable and MUST block delivery.

#### Scenario: Seller deposits before delivering

- **WHEN** the selected option sets `deposit_agreement` and the verified
  transaction has no Agreement attachment
- **THEN** the seller attaches the exact Agreement before any delivery effect,
  and a deposit failure returns retryable unavailable without delivery

### Requirement: Only the seller reverses a held payment

A refund MUST be seller-initiated through `reverse`, which is authorized for the seller and the Arkhai dispute authority and never for the buyer. The payments service releases an un-reversed hold without a settlement-service call.

#### Scenario: Seller operator refunds a held payment

- **WHEN** a seller-authenticated refund request names an accepted payment deal
  with a verified receipt and still-held funds
- **THEN** the storefront records refund intent, requests `reverse` for that
  transaction, and records the deal refunded; repeats return the same result
  without a second reversal

#### Scenario: Refund and delivery start race

- **WHEN** a refund request and the start of delivery for the same deal overlap
- **THEN** exactly one transition wins: if refund intent was recorded first,
  delivery does not start; if delivery started first, the refund proceeds and
  the deal records both the delivery and the refund

#### Scenario: Only the seller initiates a refund

- **WHEN** delivery fails or a buyer requests settlement after any outcome
- **THEN** no storefront issues `reverse` unless a seller-authenticated refund
  request names the deal, or the seller has enabled the `refund` failure action
  and the deal failed before any delivery; the buyer's recourse is a dispute
  through the payments service

### Requirement: Negotiation-scoped payment settlement converges

The seller MUST derive the mandate at acceptance and store it in opaque `settlement_data` beside exact `agreement_bytes` in `negotiation_threads`. Buyer settlement requests MUST carry only the negotiation ID. The seller MUST authenticate the accepted buyer, load accepted state, poll the deterministic transaction ID, and verify the signed receipt against the mandate before VM or bare-metal provisioning or API-credit issuance.

#### Scenario: Accepted timestamps have fractional seconds

- **WHEN** acceptance and start times are not whole seconds
- **THEN** mandate derivation rounds the hold interval up and approval expiry down without rewriting the Agreement

### Requirement: Payment settlement is retryable and idempotent

Missing or pending payment evidence MUST return retryable pending without a protected effect. Repeated calls MUST reuse transaction and fulfillment or grant identities, return completed state idempotently, and re-drive nonterminal domain state rather than leave it pending. Receipt evidence and domain progress MUST remain domain-owned, not a local ledger or payment-servicing daemon.

#### Scenario: Settlement is called before approval completes

- **WHEN** the seller has no matching signed receipt for the accepted mandate
- **THEN** it returns retryable pending and creates no VM, host access, or credit grant

#### Scenario: Issuance or provisioning acknowledgement is lost

- **WHEN** a retry finds nonterminal domain progress after a verified payment
- **THEN** it resumes or retrieves the same durable domain operation without charging or delivering twice

### Requirement: Seller integration faults are blocked, not retried

A failure caused by the seller's own integration (an authentication or authorization error, an unknown account, missing credentials or servicing configuration, a protocol or schema violation, another transaction ID, or a non-matching Agreement attachment) MUST be `Blocked`: the storefront answers 500 and logs it as an error, and a refund reports the matching `RefundBlocked`.

#### Scenario: The seller's integration fault blocks settlement

- **WHEN** the payments service refuses the seller's credential while a deal settles
- **THEN** the storefront answers 500, records nothing, and logs the fault as an error rather than reporting a retryable outage

### Requirement: A fulfillment attempt may be deferred to its domain's convergence

A fulfillment attempt MUST report one of three outcomes: fulfilled, failed, or deferred.
Deferred means work remains that the domain's own convergence will finish: the workload
exists, but a step after it did not complete. A deferred outcome MUST be persisted through
the domain, so the domain can leave its deal open; no fulfillment MAY be bound for it, and
servicing MUST NOT be woken for it.

#### Scenario: A domain defers a fulfillment

- **WHEN** a domain's fulfillment reports deferred
- **THEN** the outcome is persisted, no fulfillment reference is bound to the obligation,
  and servicing is not woken

### Requirement: A fulfillment submission with an unknown outcome is never repeated

A fulfillment step that publishes evidence to an external authority MUST make every
retry safe. A publication the authority deduplicates by a stable operation identity,
derived from the obligation and the evidence, MAY be retried under that identity. A
publication without one MUST record its submission intent on the obligation's
fulfillment operation before submitting, and MUST NOT submit again while a recorded
intent has no recorded reference, unless a supported lookup finds the reference the
earlier submission created.

The intent and the reference MUST each be first-write-wins: recording the same value
again changes nothing, and recording a different value for the same operation is
refused. The reference MUST be recorded before the fulfillment is completed with it. The
intent MAY be cleared only by the attempt holding the operation's lease, and only after
the publisher reports that nothing was submitted or that the authority refused it.

A publisher without a stable operation identity MUST report one of four outcomes:
published, with the reference it created; not submitted, when the failure provably
preceded the submission; outcome unknown; or rejected, when the authority refused it. Not
submitted and rejected clear the intent and MAY be retried; a step MAY bound the retries
of a rejection and then park the obligation for an operator with a reason. An outcome
unknown, or a recorded intent with no recorded reference, parks the obligation for an
operator with a reason. The settlement repository MUST count the obligations parked for
an operator, by mechanism status or by any operation.

#### Scenario: The process stops after submitting

- **WHEN** a fulfillment step recorded its intent and submitted, and the process stopped
  before recording the reference
- **THEN** the next attempt does not submit, and the obligation waits for an operator with
  a reason

#### Scenario: The process stops after recording the reference

- **WHEN** a fulfillment step recorded the reference and the process stopped before
  completing the fulfillment
- **THEN** the next attempt completes the fulfillment with the recorded reference and does
  not submit

#### Scenario: A different intent is recorded for the same operation

- **WHEN** an attempt records an intent that differs from the one already recorded for the
  operation
- **THEN** the write is refused and the recorded intent is unchanged

#### Scenario: The submission provably never left

- **WHEN** a publisher reports that its submission was not sent
- **THEN** the attempt clears its intent and records a retry, and a later attempt may
  submit

#### Scenario: The authority refuses the submission repeatedly

- **WHEN** a publisher reports a rejection on each attempt until the step's bound
- **THEN** each earlier rejection clears the intent and records a retry, and the last parks
  the obligation for an operator with a reason

#### Scenario: A publication is deduplicated by the authority

- **WHEN** a publication carries a stable operation identity the authority deduplicates
- **THEN** a retry after an uncertain acknowledgement reuses that identity, and no intent
  is required

#### Scenario: Parked obligations are counted

- **WHEN** obligations wait for an operator by mechanism status or by an operation
- **THEN** the repository's count includes each such obligation once

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
