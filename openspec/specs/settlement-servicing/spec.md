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

### Requirement: The mandate binds the deal and its parties

The mandate's `deal` MUST be `sha256(JCS(agreement))` and its transaction ID `sha256(JCS(mandate))`. It MUST name `settlement_params.payer_account` as `from` and the selected option's payee account as `to`, and use the service's published fee policy and the fixed nonce `arkhai.payments.v1`. On once-only options it MUST carry one `once` part for the agreed amount and asset; on rate options, one `rate` part charging the agreed per-period amount, preceded by one `once` setup part for `setup_amount` when the option carries one. Every part MUST carry its own authorities.

#### Scenario: A once-only mandate is bound

- **WHEN** buyer and seller derive the mandate of an accepted once-only payments Agreement
- **THEN** both derive the same `deal`, transaction ID, `from` and `to`, with one `once` part for the agreed amount and asset

#### Scenario: A rate mandate is bound

- **WHEN** buyer and seller derive the mandate of an accepted per-period payments Agreement whose amount is one period's price
- **THEN** both derive one `rate` part charging that amount, and no part charging it once or charging a term total
- **AND** a setup-bearing option adds one `once` setup part for `setup_amount` before the rate part

### Requirement: Mandate holds and approval follow the option's timing

Every `once` hold MUST last at least its part end plus the option's `adjudication.dispute_window_seconds`; prepaid service ends at Agreement term end, and setup encodes its end at Agreement start, clamped effectively to approval if later. Every `rate` hold MUST be `{afterStop: dispute_window}`, so each earned amount stays held until its part's stop plus the window, and every rate part MUST end at `start_utc + duration_seconds`. Approval MUST expire after the option's `approval_window`, which readers also accept under the released name `window`. Each part MUST carry `maxHoldExtension` from `adjudication.case_hold_max_seconds`, `null` when unbounded. A hosted option MUST NOT carry `bond` until payments can hold a seller-funded part.

#### Scenario: An unbounded case hold

- **WHEN** an option's `adjudication.case_hold_max_seconds` is `null`
- **THEN** every part of its mandate carries `maxHoldExtension: null`

#### Scenario: A rate part's hold follows its stop

- **WHEN** a rate mandate is derived
- **THEN** its rate part's hold is `{afterStop: dispute_window}` and its end is the Agreement's absolute term end, however late the part starts

### Requirement: A once-only mandate authorizes the seller and the dispute authority

A `once`-only mandate MUST authorize no `start` and no `stop`. It MUST authorize `reverse` for the seller and the agreement's dispute authority, the account the option's `adjudication.dispute` names rather than one from `[Settlement.arkhai_payments]`, and MUST list only that authority under the one `extend` authorities key, which also authorizes `lift`. A `reverse` MAY name a part and an amount up to what that part still holds.

#### Scenario: The buyer is never a reverse authority

- **WHEN** a once-only mandate is derived
- **THEN** its `reverse` authorities are the seller and the option's dispute authority, and the buyer is neither

### Requirement: The payments mandate is derived exactly from the Agreement

The mandate MUST be derived only from the exact accepted Agreement, binding its JCS hash, deterministic transaction ID, parties, asset, amounts, part shapes, authorities, holds, caps and approval window. Buyer and seller MUST derive the same mandate under the selected mechanism's vendored contract; unsupported bonds or terms MUST refuse. Rate authorities and term ends MUST use the deal-lifecycle codec. Every part MUST carry its own lifecycle authorities and its maximum hold extension, null where the accepted terms leave the case hold uncapped; the mandate MUST NOT carry mandate-level authorities, and a stored mandate that does is refused, never rewritten.

#### Scenario: Hold and approval expiry follow the accepted timing

- **WHEN** a seller derives a mandate from an Agreement accepted at `accepted_at`
- **THEN** each prepaid once part has absolute end start_utc + duration_seconds and hold {afterStop: dispute_window}; approval expires at floor(accepted_at) + approval_window, and fractional Agreement timestamps stay unchanged in its deal hash
- **AND** delayed approval does not shift the part end or replace the stop-relative hold with a duration from acceptance

#### Scenario: A once mandate is derived

- **WHEN** a mandate is derived from an option with one `once` part and no `early_termination`
- **THEN** it has no `start` or `stop` authority, only the dispute authority may `extend` or `lift`, and its hold ends no earlier than the dispute window after the term end

#### Scenario: A hosted option names a bond

- **WHEN** a seller configures a hosted option with `bond`
- **THEN** the builder refuses to emit it, naming the unsupported term

#### Scenario: A mixed mandate is derived

- **WHEN** a rate option includes setup_amount
- **THEN** setup once precedes rate, each with per-part authorities and maxHoldExtension
- **AND** setup's encoded end is Agreement start, effectively clamped to approval if later, both holds are afterStop plus dispute window, and approval expiry still uses approval_window

#### Scenario: The part's own authorities grant nothing beyond the accepted rights

- **WHEN** a seller derives a mandate and the buyer checks it
- **THEN** both derive the identical mandate: each once part authorizes no start or stop, each rate part derives its start and stop entries only from the accepted rights, reverse is limited to the seller and dispute authority, only the dispute authority extends holds, and each part states its accepted maxHoldExtension, null when unbounded
- **AND** there are no mandate-level authorities

#### Scenario: A mandate in the previous wire is refused

- **WHEN** stored settlement data or a counterparty's mandate carries mandate-level `authorities`, or a part without its own authorities or maximum hold extension
- **THEN** it is refused before any approval or verification, and the stored Agreement bytes and mandate are left as they are

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

### Requirement: Only the seller refunds a held payment

A refund MUST be seller-initiated through `reverse`. `reverse` is authorized for the seller and the agreement's dispute authority, which uses it only to apply outcomes, and never for the buyer. A full refund MUST keep its ordering against delivery start; a partial `reverse` that leaves money held, such as a discount on a running deal, MUST record no refund intent and change no deal status. The payments service releases an un-reversed hold without a settlement-service call.

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

#### Scenario: A seller discounts a running deal

- **WHEN** a seller submits a `reverse` of a quarter of a delivered deal's held payment
- **THEN** the storefront sends one partial `reverse` for that amount, records no refund intent, and leaves the deal's status and lease unchanged

#### Scenario: Only the seller initiates a refund

- **WHEN** delivery fails, the seller voluntarily corrects an unentitled end, or a buyer requests settlement after any outcome
- **THEN** no storefront issues `reverse` unless a seller-authenticated refund request names the deal, or the seller has enabled the `refund` failure action and the deal failed before any delivery; otherwise a committed deal's failure or correction is filed as delivery_end with the agreement's dispute authority, with no stop or reverse for it, and a buyer disputing the account files a case

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
servicing MUST NOT be woken for it. A deferred outcome is distinct from a ready step
awaiting delivery, whose fulfillment has not started and which servicing rechecks every
cycle.

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

### Requirement: Settlement verifies against the accepted plan

Every storefront that settles Alkahest deals MUST verify a buyer's escrow, register its
obligations, and settle against the settlement plan committed when the deal was
accepted, and MUST NOT re-derive the plan, its release condition, or its escrow terms
from the listing as currently stored or from current settlement configuration. Every
other reader of an accepted deal's settlement terms — an administrator's preview of its
verification, its oracle evidence's heartbeat interval, and an administrator's interrupt
deciding whether it is interruptible — MUST read the same plan. A seller's change to its
release policy, its wallet, or the address-book entries of its release conditions after
acceptance MUST NOT change how an accepted deal is verified. The address book is read only
to find the codec of the escrow contract a deal funded, so an address book that stops
naming that contract leaves the deal unverifiable, and the buyer's escrow reclaimable at
expiry.

#### Scenario: The seller changes its release policy after acceptance

- **WHEN** a VM, bare-metal, or API-credit deal is accepted under the recipient release
  model, the seller then configures another model, and the buyer settles an escrow funded
  under the accepted plan
- **THEN** settlement verifies the escrow against the accepted plan and proceeds

#### Scenario: The seller's address book moves the arbiter after acceptance

- **WHEN** a deal is accepted and the seller's address book then names another recipient
  arbiter, and the buyer settles an escrow funded under the accepted plan
- **THEN** settlement verifies the escrow against the accepted plan and proceeds

#### Scenario: An escrow does not match the accepted plan

- **WHEN** a buyer settles an escrow whose arbiter, demand, token, or contract differs
  from the accepted plan's obligation
- **THEN** settlement refuses it, whatever the listing now states

#### Scenario: An administrator previews verification after a policy change

- **WHEN** a seller changes its release policy after acceptance and an administrator
  previews verification of the deal's escrow
- **THEN** the preview checks the escrow against the accepted plan and agrees with
  settlement's verification

### Requirement: A ready step awaiting delivery is rechecked every cycle

A servicing worker's ready step that finds its domain's delivery not yet active, and
leaves the obligation awaiting delivery, MUST NOT count that as a failed attempt: the
obligation MUST be due again on the worker's next servicing cycle, and the error backoff
MUST NOT lengthen. A failed ready step keeps the error backoff.

The settlement operation journal MUST record the wait: a ready step leaves its obligation
awaiting delivery through the runtime's operation for it, which in one write releases the
fulfillment lease, returns the attempt its reservation counted, marks the operation
awaiting delivery while it stays pending, and makes it due at once. The worker MUST read
the operation after the ready step returns and MUST NOT apply the error backoff to an
operation awaiting delivery; an operation still pending and not awaiting delivery keeps
the error backoff. A release that does not know the mark MUST still find the operation
pending and due.

#### Scenario: Delivery takes several cycles

- **WHEN** a ready step leaves an obligation awaiting delivery because its delivery is not
  yet active, on several consecutive cycles
- **THEN** each time the obligation is due on the next cycle, and its attempts are not
  counted toward the backoff

#### Scenario: The process stops just after the mark is written

- **WHEN** a ready step's awaiting-delivery mark is written and the process stops before
  the worker schedules anything
- **THEN** the restarted worker finds the obligation due, its lease free, and the
  attempt not counted

#### Scenario: A ready step returns without starting or awaiting delivery

- **WHEN** a ready step returns, has not marked its obligation awaiting delivery, and has
  bound no fulfillment
- **THEN** the obligation takes the error backoff

#### Scenario: A release without the mark services the obligation

- **WHEN** a release that predates the awaiting-delivery mark runs against a journal
  holding an operation awaiting delivery
- **THEN** it finds the operation pending and due, and retries it on the error backoff

#### Scenario: A ready step fails

- **WHEN** a ready step raises
- **THEN** the obligation is retried after the error backoff, as before

### Requirement: Every failing servicing step is reported

A servicing worker MUST log every step it schedules for retry, naming the obligation, the
operation, and the error, whether or not an event callback is composed. Each storefront
that composes the worker MUST compose its event callback.

#### Scenario: A step fails without a callback

- **WHEN** a servicing step fails in a worker composed with no event callback
- **THEN** the worker logs the retry with the obligation, operation, and error

### Requirement: The settle wait polls through a failed status read

An administrator's settle wait MUST treat a failed read of a settlement's status as a
poll that did not reach a terminal state, keep polling until its deadline, and on reaching
the deadline report `ready: false` with the last error.

#### Scenario: The site is briefly unreachable

- **WHEN** one status read during a settle wait fails and a later one reports the
  settlement terminal
- **THEN** the wait reports ready

#### Scenario: Every read fails

- **WHEN** every status read until the deadline fails
- **THEN** the wait reports `ready: false` with the last error, rather than failing

### Requirement: The settle wait resolves a settlement by its reference or its negotiation

An administrator's settle wait MUST resolve the reference it is given to a settlement
the same way in every storefront that binds it, whatever the settlement's mechanism: by
the settlement evidence whose settlement reference it is, and otherwise by the
settlement evidence of the negotiation it names. The settlement runtime kit MUST own
that resolution and the wait's terminal states, `ready`, `failed` and `ended`; a storefront MUST
supply only its lookups of settlement evidence by settlement reference and by
negotiation, and its delivery status for a resolved settlement. A reference that
resolves to no settlement MUST be treated as a poll that found nothing terminal.

#### Scenario: A payments deal is waited on by its negotiation

- **WHEN** an administrator waits on an `arkhai.payments.v1` deal's negotiation in any
  storefront, and the deal's delivery becomes ready
- **THEN** the wait reports ready

#### Scenario: A payments deal is waited on by its transaction

- **WHEN** an administrator waits on an `arkhai.payments.v1` deal by its transaction,
  the settlement reference its evidence records
- **THEN** the wait resolves the same settlement and reports the deal's delivery status

#### Scenario: An Alkahest deal is waited on by its escrow

- **WHEN** an administrator waits on an Alkahest deal by its escrow
- **THEN** the wait resolves the settlement whose evidence records that escrow, as it
  did before

#### Scenario: The reference names no settlement

- **WHEN** an administrator waits on a reference that names no settlement evidence and
  no negotiation with any
- **THEN** the wait polls until its deadline and reports `ready: false`

### Requirement: Snapshot verification accepts configured identity history

Hosted snapshot verification MUST accept configured current/retiring identities with validity windows, embedded-receipt attestation and a caller-supplied minimum sequence. It MUST refuse unverified, cross-deal, mode-changed or regressing state. A fresh current-key snapshot MAY attest an embedded old receipt while retaining original bytes; consumers MUST NOT implement a parallel verifier.

#### Scenario: A current-key snapshot attests a retiring identity's receipt

- **WHEN** a snapshot signed by the current identity embeds a receipt that a configured retiring identity signed within its window
- **THEN** verification checks identity windows, commitment and mode binding and minimum sequence, and accepts the snapshot while that retiring identity stays configured
- **AND** once that identity leaves configuration the snapshot is refused, as "A receipt identity change is a cutover" requires

### Requirement: A rate mandate authorizes from the accepted rights
A `rate` part MUST authorize `start` for the payee alone. Its `stop` entries MUST be exactly one per accepted entitlement, carrying that entitlement's `notice_seconds` and the `partialPeriod` its `settles_through` maps to, followed by the dispute authority's `{account, notice: PT0S, partialPeriod: chosen}`; on-demand has no payee entry. It MUST authorize `reverse` for the payee and the dispute authority, and only the dispute authority under `extend`. A setup part MUST use the `once` permissions. The buyer MUST refuse any authority not derived this way before approval.

#### Scenario: Spot and on-demand stop entries
- **WHEN** a spot mandate and an on-demand mandate are derived from options with the same payer entitlement
- **THEN** the spot rate part's stop entries are the payer's, the payee's with its notice, and the dispute authority's `chosen` entry, in that order
- **AND** the on-demand rate part's are the payer's and the dispute authority's only

#### Scenario: A seller stop entry is added without an entitlement
- **WHEN** the buyer checks a mandate whose rate part carries a stop entry no accepted entitlement derives
- **THEN** it refuses before approval

### Requirement: Hosted rate mandates are derived from the selected option
SCM MUST derive time rate parts through the agreed-price accessor and lifecycle codec, using the selected Agreement's asset, period, reservation lead, absolute term end, adjudication hold and cap. The buyer MUST independently check all parts and authorities before approval, including any disclosed setup once part.

#### Scenario: A mixed setup and rate option is selected
- **GIVEN** a selected option with setup_amount and a price accessor returning a per-period charge
- **WHEN** buyer and seller derive the mandate
- **THEN** both derive setup once followed by rate, with the same amounts, asset, end, afterStop hold, maxHoldExtension and per-part authorities
- **AND** neither reads Agreement.amount as a direct charge

#### Scenario: Service starts after the approval window
- **GIVEN** a rate mandate whose service start is later than approval expiry
- **WHEN** its finite duration is derived or checked
- **THEN** its end MUST leave the delivery deadline and one whole period after max(approval expiry, start_utc)
- **AND** acceptance horizon resolution and mandate derivation use the same runway calculation

#### Scenario: On-demand has no seller stop entitlement
- **GIVEN** an accepted option with no seller early-termination entitlement
- **WHEN** the buyer checks a mandate containing a seller stop entry
- **THEN** it refuses that extra authority before approval
- **AND** the no-preemption promise is enforced by the premature-stop penalty and a buyer case over held money, not a guarantee of physical service

#### Scenario: Spot has its accepted notice entry
- **GIVEN** an accepted spot option with a seller notice entitlement
- **WHEN** the buyer checks the mandate
- **THEN** its seller stop entry carries the accepted notice and treatment, without an extra restitution entry
- **AND** the seller's emergency exit is a delivery_end filing through the dispute adapter, not its own payment stop

#### Scenario: The rate adapter consumes lifecycle treatment
- **GIVEN** the deal-lifecycle requirements for stop-authority and term-end treatment
- **WHEN** a rate mandate is derived
- **THEN** the adapter uses the shared codec for rate stop entries and rate end, including the dispute authority's chosen entry
- **AND** setup once ends retain the published schema's required inert returned partialPeriod, which prices no recurring period

#### Scenario: A buyer stops before activation
- **GIVEN** an approved mandate with a setup part
- **WHEN** the buyer's stop takes effect before the seller activates the lease
- **THEN** a lawful buyer surrender keeps setup with delivered=true in its claim, with payout one dispute window after its effective end
- **AND** no reverse of it is issued and no filing is made

#### Scenario: The seller never delivers
- **GIVEN** an approved mandate with a setup part
- **WHEN** the seller files delivery_end for non-delivery, including a term end that arrives before activation
- **THEN** the mediation self-penalty returns all of setup to the buyer while it is held

#### Scenario: Provisioning starts late
- **GIVEN** a finite accepted duration_seconds
- **WHEN** rate start occurs after Agreement start_utc
- **THEN** the derived part end instant remains start_utc plus duration_seconds
- **AND** its own partialPeriod determines the final period's charge, not a rounded-down term

### Requirement: Hosted rate commands preserve part identity and uncertain outcomes
The hosted adapter MUST translate lifecycle commands into explicit per-part events with stable operation-derived request identities. It MUST require the deal-lifecycle versioned activated-delivery envelope for rate start. Every monetary rate call MUST record each descriptor's digest through the caller's operation store, under a part-derived key, before any I/O, so changed-content key reuse is refused before any authority call. Unknown outcomes MUST resolve by verified read before another monetary delta.

#### Scenario: A start response is lost
- **GIVEN** the end service's sole durably keyed start_billing intent with verified activation and provisioning-ready evidence
- **WHEN** its response is lost
- **THEN** the adapter reports unknown and exposes the authority event through read
- **AND** retry uses the same part, bytes and request identity derived from the end service's supplied operation key, while delivery retains only a reference, not a separately allocated start

#### Scenario: Delivery authorizes before starting billing
- **WHEN** delivery requests authorization to attempt billing start
- **THEN** authorization is a pure decision with no payment mutation
- **AND** only the separate post-activation start_billing effect translates to authority start commands

#### Scenario: Start loses to a stop
- **GIVEN** the rate part is already stopped at the authority
- **WHEN** start is refused as transaction_stopped
- **THEN** the adapter reports the failed start for delivery-end handling, not successful start

#### Scenario: A monetary command needs repair
- **WHEN** the authority refuses a rate command with HTTP 409 request_id_reused or hold_not_reversible
- **THEN** the adapter reports a rejected outcome requiring repair before another monetary operation
- **AND** server or transport failures remain unknown and retryable

#### Scenario: Approval cannot reserve the initial funds
- **WHEN** approval returns HTTP 409 insufficient_funds
- **THEN** the buyer receives a typed PaymentApprovalInsufficientFunds refusal identifying the funding action
- **AND** no receipt polling or delivery commitment follows that refusal

#### Scenario: A stop is repeated
- **WHEN** a stop submission reports an already-stopped part
- **THEN** the adapter confirms satisfaction only from a verified same-or-earlier effective stop
- **AND** it never reports a later local timestamp as the authority's end

#### Scenario: A retry changes its content
- **GIVEN** a rate stop, start or reverse whose descriptor the caller's operation store recorded under its operation key
- **WHEN** a retry under the same key carries different content
- **THEN** the adapter refuses it before any authority call
- **AND** an identical retry is sent again under the same request identity, which the authority answers with the event it recorded

#### Scenario: A rate operation has no operation store
- **WHEN** a rate deal's monetary command or billing start arrives without the caller's operation store
- **THEN** the adapter refuses it before any authority call

### Requirement: Rate stops consume authority-priced period treatment
The hosted rate adapter MUST consume the deal-lifecycle stop-authority mapping and capability refusal rules. It MUST observe the winning authority entry rather than compute cooperative end-price corrections. Seller delivery_end MUST instead be filed through the dispute adapter, with no seller-side stop or reverse for that filing.

#### Scenario: Returned spot reaches default buyers
- **GIVEN** a composition declaring charged and returned and an offered spot option with payee and term-end settles_through last_boundary
- **WHEN** the buyer's default acceptance policy and exact mandate check run
- **THEN** those treatments pass policy without loosening it
- **AND** an undeclared returned treatment is refused, never replaced with charged

#### Scenario: A charged spot needs the buyer's waiver
- **GIVEN** an offered spot option whose payee stop and term end settle through started_period, under a declaration listing charged
- **WHEN** a default buyer selects or approves it
- **THEN** it is refused, naming each charged term
- **AND** a buyer whose run waives each of those terms through its per-term waivers selects and approves it

#### Scenario: Rate earning follows completed periods or stop
- **WHEN** a rate period begins
- **THEN** its amount remains reserved until the period ends or the part stops
- **AND** a stop prices the partial period under its committed or chosen treatment without SCM clawback
- **AND** afterStop payout timing is unchanged

#### Scenario: A dispute stop selects its treatment
- **WHEN** a verified stop is issued under the dispute authority's chosen entry
- **THEN** its event supplies the ruling's treatment; delivery_end is human-ruled and preserves payer notice and payer treatment
- **AND** delivery_end is a dispute intent whose at-least-standard payee self-penalty is mediation's payee-signed delivery_end ruling
- **AND** SCM observes the effect without computing a compensating reverse

#### Scenario: The stop crosses a period boundary
- **GIVEN** authority start 0, period 60 and amount 100
- **WHEN** effective stop is 60
- **THEN** charged, returned and prorated each charge 100
- **WHEN** effective stop is 61
- **THEN** charged charges 200, returned charges 100, and prorated follows the published authority rounding vector
- **AND** SCM issues no compensating reverse for any of them

#### Scenario: A part never started
- **WHEN** an approved unstarted rate part stops
- **THEN** its earned charge is zero and reservations return at the authority
- **AND** SCM does not treat returned reservations as earnings to reverse

#### Scenario: Another stop wins during seller notice
- **GIVEN** a pending seller stop and a winning earlier payer stop
- **WHEN** verified authority records expose the winner
- **THEN** SCM observes that payer entry's partialPeriod, not a locally journaled seller correction
- **AND** equal-time requests use the authority's recorded winner, not local arrival order

#### Scenario: Exhaustion or a ruling stops a part
- **WHEN** exhaustion stops a rate part
- **THEN** fundedThrough is a period boundary with no partial period to price
- **WHEN** a dispute authority applies a stop and reversal
- **THEN** SCM observes the ruling without a second correction

#### Scenario: An independent discount already exists
- **GIVEN** a prior discount or penalty on a running rate part
- **WHEN** an entitled stop takes effect
- **THEN** SCM neither absorbs that effect into a cumulative end target nor submits an overlapping correction

#### Scenario: A lawful end precedes disclosure
- **GIVEN** a verified buyer end, payer stop or ruling before disclosure
- **WHEN** delivery reports that availability was not reached
- **THEN** attribution follows deal-lifecycle's “Cause classification is owned by end service”, without a seller-fault filing merely for non-availability
- **AND** only classified seller non-delivery follows the dispute-filing handoff

#### Scenario: A site reports an earlier exceptional end
- **WHEN** the seller learns service ended without an entitlement covering that end
- **THEN** handling follows deal-lifecycle's “A seller's exceptional end is a dispute filing”
- **AND** the hosted payment adapter exposes no exceptional-end operation or direct-payment fallback

#### Scenario: Start evidence is absent or mismatched
- **WHEN** rate start has no valid deal-lifecycle activation envelope matching the deal, commitment and activated lease
- **THEN** the adapter refuses start before contacting the payment authority

### Requirement: Absolute rate ends preserve the accepted capacity bound
The rate adapter MUST derive end.partialPeriod only from early_termination.settles_through under deal-lifecycle's “Term ends carry their own partial-period treatment”, preserving start_utc plus duration_seconds as its instant. Late activation MUST NOT shorten or extend that accepted bound.

#### Scenario: A late start leaves an incomplete final period
- **GIVEN** authority start 10, period 60, amount 100 and absolute end 120 with returned treatment
- **WHEN** that end is reached
- **THEN** billing keeps 100 for [10,70) and returns the incomplete [70,130) period
- **AND** delivery still ends at 120 without rounding down the accepted duration

### Requirement: Rate delivery authorization is pure and phase-specific
The hosted rate adapter MUST implement authorize(phase, evidence) for commit, dispatch, start and disclose without mutation. Results MUST carry allow/refuse/pending, reason, operation identity and verified evidence references. Missing or unverified state MUST NOT allow work. The neutral servicing composition MUST NOT inspect hosted part fields.

#### Scenario: Commit is authorized
- **WHEN** commit authorization receives an exact verified mandate approved within its approval window and no terminal end
- **THEN** it allows even after the new-approval deadline passes
- **AND** an incompatible or terminal commitment refuses; an expired unapproved mandate cannot commit

#### Scenario: Dispatch or physical start is authorized
- **GIVEN** a verified valid commitment and initial reserved funding
- **WHEN** dispatch or start is requested before any effective stop or absolute end
- **THEN** it allows, including during future pending notice, without starting billing
- **AND** missing pre-start fundedThrough alone is not exhaustion
- **WHEN** a verified effective stop, exhaustion or absolute end controls
- **THEN** it refuses and returns that authority provenance

#### Scenario: Disclosure waits for billing start
- **WHEN** disclose has a verified rate start bound to the journaled intent, valid funding and no effective end
- **THEN** it allows
- **WHEN** start is absent or unresolved
- **THEN** it returns pending; a definitive failed start or effective end refuses

#### Scenario: Authorization evidence cannot establish a decision
- **WHEN** authority state is absent, unreachable, unverifiable or regresses below the supplied minimum sequence
- **THEN** it returns pending, never allow
- **AND** an unknown phase or malformed/cross-deal envelope refuses
- **AND** a known pending stop bound cannot be crossed using stale evidence

#### Scenario: The authority's and the storefront's clocks differ
- **WHEN** a verified snapshot's observedAt lags the storefront's clock by more than the configured freshness window
- **THEN** the phase is pending until a fresher snapshot is read
- **AND** a snapshot observed within the window, or ahead of the storefront's clock, decides the phase with every stop, end and funding bound checked at the storefront's now

### Requirement: Hosted payments expose no exceptional-end operation
The hosted payment adapter MUST expose no exceptional-end operation and MUST NOT provide a direct-payment fallback for seller exceptional ends. It MUST consume verified authority effects from the foundation-owned filing path under deal-lifecycle's “A seller's exceptional end is a dispute filing”, without duplicating its journal or mediation's computation.

#### Scenario: A seller files its emergency exit
- **GIVEN** seller-caused failure on an on-demand or spot deal
- **WHEN** the foundation-owned exceptional-end filing path runs
- **THEN** the hosted adapter receives only ordinary authority records, with no exceptional-end payment event kind or field and no seller stop/reverse fallback

#### Scenario: Filing outcome is uncertain
- **WHEN** the dispute filing response is lost
- **THEN** recovery remains with the foundation-owned journal and identical-key read/retry, never a direct hosted-payment fallback

#### Scenario: The mediation self-penalty result is observed
- **GIVEN** the vendored delivery_end mapping for a cause=payee claim meeting payee-agreement and mapping/time/replay guards
- **WHEN** the adapter observes the resulting verified authority records
- **THEN** it reports rate stops now with returned and rate earnings since at reversed, including always-returned on-demand treatment
- **AND** once parts reflect their time-unserved reversal, with setup all if undelivered and none once delivered, then min(premature_stop_penalty, earned amounts still held) reversed to the payer across parts in mandate order; no bond award
- **AND** SCM does not duplicate mediation's computation or apply a second correction

#### Scenario: The standard package cannot be qualified
- **WHEN** the dispute intent, published mapping or required returned/chosen-entry contract support is absent or unqualified
- **THEN** qualification reports the missing dependency without a seller-side stop/reverse substitute

### Requirement: Rate observations require verified authority state
The hosted adapter MUST consume the verified snapshot interface before interpreting start, funding, pending stop, stop, extensions, releaseAt or event sequence. It MUST expose per-part changes to lifecycle read/watch without treating a courtesy hint or a missing funding field as an authoritative stop.

#### Scenario: A pending stop survives the storefront
- **GIVEN** a verified authority pendingStop
- **WHEN** the storefront restarts after its effective time
- **THEN** adapter read exposes the authority's resulting stop and cause for end service
- **AND** no local payment-stop schedule is required

#### Scenario: The snapshot cannot be verified
- **WHEN** snapshot verification fails or its known sequence regresses
- **THEN** no rate state from it is used for billing, start admission or funding renewal

### Requirement: Rate stop requests are projected apart from final stops
The hosted adapter MUST project a raw stop event on a rate-bearing mandate as a stop request, which never ends delivery, and MUST expose each rate part's verified pending and final stop, with the treatment its winning entry applied, as that part's observation. The winning final stop, an equal-time winner included, MUST come from the part's verified record, never from local arrival order. A once-only mandate's part stop MUST keep its projection as the deal's payment end.

#### Scenario: A payee notice is pending
- **WHEN** the authority records a payee stop effective after its notice
- **THEN** the adapter's read carries a stop request event and the part's pending stop, and no final stop

#### Scenario: The notice matures
- **WHEN** the pending stop takes effect
- **THEN** the part's final stop carries the authority's effective time and the treatment its entry applied

### Requirement: One payments transaction adapter serves every part kind by composition
One payments transaction adapter MUST implement the lifecycle payment-adapter protocol for every `arkhai.payments.v1` mandate, composed of parts every part kind shares — mandate binding, verified snapshot reads, reverse, event projection, refusal classification and descriptor recording — and of rate behaviour — start, stop, notice, rate observations and the rate delivery phases — composed in only when the mandate has a rate part. Once and rate behaviour MUST NOT inherit from one another: no private flag switches a once-only guard off, and neither the seller stage nor a buyer chooses an adapter class by part kind. A once-only mandate MUST refuse rate commands, and its billing start MUST be a no-op once its commitment and the activation evidence are verified. A stop MUST NOT pre-read the authority to detect a changed retry, since descriptor recording refuses one before any call.

#### Scenario: A mixed mandate in one adapter
- **GIVEN** an accepted mandate with a setup `once` part and a rate part
- **WHEN** the payee reverses part of the setup and stops the rate through one adapter
- **THEN** the setup reverse is projected as an ordinary once movement with its amount
- **AND** only the rate part carries a rate observation, whose pending stop the read exposes

#### Scenario: A once-only mandate starts billing
- **WHEN** end service starts billing for a once-only mandate with verified activation evidence
- **THEN** the adapter sends nothing to the authority and reports a no-op start

## Evidence

- Plan envelopes and lifecycle-universal fields:
  `core/src/market_core/schemas.py` and `kit/alkahest/tests/unit/test_plans.py`.
- Stable obligation identity, operation journals, work leases,
  compare-and-swap transitions, and aggregate status:
  `core/storefront/src/core_storefront/{settlement_lifecycle,settlement_runtime,sqlite_client,migrations}.py`.
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
- Selected-site restart and teardown routing: `domains/vms/storefront/tests/integration/test_fulfillment_resume_runtime.py`, `domains/vms/storefront/tests/unit/test_fulfillment_service.py`, and `test_lease_truncation.py`.
