# Settlement Servicing Architecture

The [normative contract](spec.md) defines Agreement-based payments, plans, claims, and heartbeat behavior. This document distinguishes obligation servicing from receipt-gated payment delivery.

## Servicing lifecycle

Some obligations complete immediately; others depend on conditions that become true later. For Alkahest and other obligation-runtime mechanisms, settlement produces a plan persisted and serviced over time:

```text
accepted Agreement
      ↓ materialize
SettlementPlan
      ↓
active obligations ── evaluate ── collect / abandon / expire
```

The settlement-runtime kit owns restartable lifecycle structure and stable obligation state. It does not understand an oracle predicate, token transfer, or domain-specific evidence. Core supplies schema-opaque carriers and storefront composition contracts; persistence adapters, retries, and operator inspection remain consistent while mechanism implementations evolve independently.

A ready step may find its domain's delivery not yet active, as bare metal's does while a lease is starting. Waiting is not failing: were it counted as an attempt, the error backoff, 30 seconds doubling to 30 minutes, would let evidence publication, and with it the seller's collection, lag activation by up to half an hour, with nothing in production to wake it. The step calls `SettlementRuntime.defer_fulfillment`, which in one journal write releases the fulfillment lease, returns the attempt its reservation counted, sets `awaiting_delivery` on the `fulfill` operation, and makes it due at once. The worker reads the operation after the step returns: one awaiting delivery keeps its due time and is rechecked on the next cycle, and honouring the mark consumes it, so a later step that neither starts fulfillment nor waits takes the backoff rather than a mark it did not write. Any other pending operation takes the error backoff, and a step that raises stays on the error path.

The mark is a flag on the operation, added to `settlement_operations` by the runtime's own migration, and the operation stays `pending`, rather than a new state. The due query, `schedule_settlement_retry`, and `wake_settlement_obligation` all select pending operations, so only the deferral's write and the worker's post-step read know the flag. A release that predates it reads an ordinary pending operation, due now with its attempt returned, and backs it off as it always did: a rollback degrades to the slower cadence and never strands an obligation, where a state an older due query never selects would stall every deal awaiting delivery. A typed outcome returned by the ready step was rejected as a second signal that must agree with the lease it released and would still need a journal write to return the attempt.

Awaiting delivery is not the deferred fulfillment *outcome*. A deferred outcome means the workload exists and the domain's own convergence finishes what remains, so servicing is not woken for it; awaiting delivery means fulfillment has not started, and servicing rechecks it every cycle. The two keep separate names so each word means one thing.

Every step scheduled for retry is logged at warning with its obligation, operation, and error, whether or not a storefront composed an event callback, so a failing step is never silent; each storefront that composes the worker also composes its callback, writing its `claims` stage events.

The administrator's settle wait (`GET /api/v1/admin/settle/{ref}/wait`) is the settlement-runtime kit's `SettlementAdminRouteService`, and the kit decides what a reference names. At each poll it resolves the reference afresh (`SettlementLookup.resolve`): by the settlement evidence whose settlement reference it is — an Alkahest escrow, an Arkhai payments transaction — and otherwise by the evidence of the negotiation it names, whatever the mechanism, since evidence may be recorded, or its reference established, while the wait runs. A reference that resolves to nothing is a poll that found nothing terminal. The kit owns the terminal states, `ready`, `failed` and `ended` — delivered, or never to be. A storefront supplies only its two evidence lookups, by settlement reference and by negotiation, each returning `market_core.SettlementEvidence` or nothing, and its delivery status for a resolved settlement, which the wait returns to the administrator as reported. So every storefront answers a payments deal by its negotiation or its transaction, and an Alkahest deal by its escrow, in the same way; a domain-local resolution would let one storefront's wait miss a deal another's finds. The resolver is a public kit operation, so another caller can resolve a reference the same way without waiting.

The wait treats a failed read, a lookup's or the delivery status's, as a poll that reached nothing terminal and returns the last error beside `ready: false` at its deadline, so a site briefly unreachable does not fail a wait that would have succeeded; a refusal, such as a settlement the storefront does not know, is an answer and ends the wait. Bare metal's delivery status keeps its live fulfillment read and also wakes the obligation's servicing once it finds delivery ready, which a scenario holding the servicing loops relies on; it wakes one only for evidence whose source names an obligation, the Alkahest path, since a payments deal adopts no settlement-runtime obligation. Each buyer-facing settle status route still resolves a reference its own way, and each domain keeps its own settlement evidence table.

## Plan and codec boundary

Existing plans carry participant, value, and escrow lifecycle fields and versioned mechanism payloads. Kit codecs translate between shared carriers and mechanism-specific obligations. Domain policy selects conditions and interprets their business meaning.

Keeping codecs explicit is safer than generic dispatch on an arbitrary escrow-kind string: each supported `(kind, schema_version)` has an owning validator and materializer, and unknown versions fail instead of being guessed into a current model.

## Conditional-escrow clients and durable mechanism state

Obligation-runtime mechanisms satisfy the shared `ConditionalEscrowClient` port for
materialize, authoritative status, check, collect, and expired reclaim. They
receive a stable operation reference and may return only public-safe opaque
references, actions, anchors, receipts, and mechanism state. The repository
persists returned mechanism state even when a condition remains pending. This
is what makes request-once/poll workflows survive restart without repeating an
external mutation.

Condition interpretation and collection remain separate because an asynchronous condition may be false many times before collection is valid. Same-wallet chain operations may need serialization to avoid nonce races, but that mechanism constraint does not become a generic marketplace lock.

## Obligation identity and competing terminal effects

Plan identity stays out of the negotiation wire carrier. The servicing
repository combines a stable agreement reference, ordered obligation index,
and canonical validated obligation snapshot to derive an immutable
`obligation_ref`. This keeps legacy model dumps stable while giving every
mechanism operation one durable idempotency boundary.

Materialization, condition evaluation, collection, and reclaim have separate
state because their failure and recovery semantics differ. Mutation attempts
are journaled before external I/O; uncertain acknowledgement is retained so a
restart retries the same operation rather than inventing a new effect.
Collection and reclaim use one database serialization point because they are
financially exclusive even when separate workers and roles initiate them.

Aggregate status is derived from obligation rows rather than stored as another
authority. Partial completion is a normal inspectable state: a completed
payment does not erase a bond that needs repair, and a failed bond does not
replay a completed payment.

## Interval and bond policy

Intervals allocate accepted integer value in proportion to each interval's
duration, then distribute the bounded rounding remainder to the earliest
intervals. This rule is deterministic on both sides and conserves the accepted
total without zero-value mechanism obligations.

A penalty bond is an ordinary directional obligation, not a special runtime
branch. Policy changes payer and claimant to seller and buyer while preserving
the accepted mechanism demand. The same materialize/check/collect/reclaim
engine therefore handles payment intervals and bonds.

## Heartbeat evidence

A heartbeat timestamp serves two purposes: it is part of the signed value and the monotonic replay key for one deal. Signature verification proves authorship; bounded clock skew and strict monotonicity prevent capture of an older valid heartbeat from extending an obligation after a newer one was accepted. Domain code owns the heartbeat payload's meaning, while core owns authentication and replay protection.

Heartbeat authorization resolves the signer as the complete scheme-tagged
principal assigned to the deal buyer. Matching identifier text under another
scheme does not authenticate evidence even when the signature itself is
cryptographically valid for that other principal.

## Capacity coupling

Commercial abandonment may request early physical termination, but it does not
free capacity. End service records one attributed delivery instant before physical
I/O: due ends terminate immediately, future ends truncate the immutable lease
horizon at second precision. Proven teardown (or an explicit force-release) still
controls site capacity return. A signed intended-end report, its acknowledgement
and the capacity-released callback are three different facts.

Admission and end recording share caller-session revision/CAS ordering around
reserve, dispatch, activation/billing intent and disclosure. Authority reads happen
before that transaction; stale revisions retry without effects. In-flight physical
work is adopted before termination. An ambiguous site end retains a classification
slot; a correlated report adopts the verified controller's filing instead of
inventing another fault. Classification and seller case filing never delay teardown.
See [end/admission model](../deal-lifecycle/architecture.md#one-end-instant-transactional-admission).

## Principal and mechanism boundaries

Marketplace authorization binds payer, claimant, storefront, and service actors as complete scheme-tagged principals throughout plans, fulfillment references, heartbeats, start/status/reclaim requests, claims, and operation-journal reservations. Bare identifiers, payment account references, provider identifiers, and EVM addresses inside mechanism payloads are resources or effect inputs, not credentials.

A principal is a credential identity, while agreement, obligation, account, and
provider references remain stable subjects or resources. The mechanism-neutral
runtime therefore carries principals opaquely and never derives or persists a
wallet or private-key alias from them.

Wallet and chain configuration is mechanism-scoped. Arkhai payment calls use owner-scoped WorkOS credentials; signed receipt verification uses the trusted service's Ed25519 identity, with no EVM wallet or RPC dependency. Alkahest validates its own chain inputs without reinterpreting marketplace principals.


## Configuration and durable runtime state

Typed registration controls readiness, publication, and selection. Alkahest and contact exchange use the obligation lifecycle and operation journal. Arkhai payments consumes accepted Agreement bytes and its persisted mandate directly and does not produce a plan or obligation.

Current priority and readiness govern new deals only. Recovery uses exact accepted state and the same transaction or obligation identity.

## Accepted domain continuity

The accepted negotiation binding is a second routing dimension beside the
settlement mechanism. It selects the domain plan builder and schema-opaque
fulfillment hook while the mechanism registry selects financial effects. Core
carriers retain the accepted buyer, site, mode, domain payload, and public
operation identity without provider configuration or credentials. Hooks return
validated lifecycle projections, including a domain result that is decoded by
only the selected contract.

Fulfillment contexts persist the exact binding and site. Restart, result
retrieval, failure handling, and teardown compare those values before any call;
they do not consult current listings or payload kinds. Provisioning remains the
executor authority and dispatches teardown from its durable offering mode, so
the storefront never derives VM versus bare-metal teardown locally.



## Charge-first payment settlement

The seller derives the mandate at acceptance from exact Agreement bytes, the selected option, and buyer `settlement_params.payer_account`. The mandate lives in shared `negotiation_threads.settlement_data` next to `agreement_bytes`, not a per-domain mandate table. Transaction identity is `sha256(JCS(mandate))`; deal identity is `sha256(JCS(agreement))`. Whole-second hold intervals round up and approval expiry rounds down, without changing accepted timestamps.

Buyer approval validates both the mandate and local policy. Buyer and seller poll the same deterministic transaction ID; seller settlement reloads accepted state by negotiation ID and verifies the signed receipt against it. A pending transaction authorizes no domain effect. Retries return completed state or re-drive nonterminal provisioning/issuance with the same durable identity.

VM and bare metal retain selected-site physical authority and teardown; API credits
retains its grant and credential authority. Those journals are not ledger state.
Voluntary refund uses payment `reverse`; exceptional delivery ends use the
Agreement-named dispute authority, not a local stop/refund calculation. Payments
owns hold release/extensions, fees and cash; the dispute authority owns cases,
rulings and their effects. Both adapters are stateless. Storefront `DealWatch` and
end service own repeated observation and orchestration, under the shared loop
controller rather than a timer in either authority kit.

**Delivery start and refund intent are ordered.** Each domain records two transitions with single-statement compare-and-set writes in its own tables. Delivery start, before any external effect, succeeds only while the deal is verified and carries no refund intent. Refund intent records `refunding` before the reversal is requested: if delivery had not started, it can no longer start; if it had, the delivery completes and its details are kept beside the `refunded` status. A refund first confirms a verified payment exists, and abandons its intent if nothing remains to reverse, so an unpaid deal is never left blocked.

**Attachments must match the deal.** Every Agreement attachment is a deal attachment validated against the transaction's deal hash, so the client and its test fake examine every attachment, return the matching one, and refuse any mismatch as a blocked integration fault.

**Snapshots and receipts have separate verified roles.** The payments kit verifies
snapshot attestation, exact deal/mandate/receipt, service mode, identity validity
windows and the caller's durable minimum event sequence before consuming part
state. Current/retiring receipt pins can validate an old receipt attested by a
current snapshot without changing its bytes. Published vectors and the shared
clock-injected `PaymentsAuthority` fixture cover these proofs and per-part events;
`FakePaymentsClient` consumes that same engine, not a second financial model.

**A receipt key change drains rather than re-anchors.** The retiring pin serves the
moment of a switch, so a fresh approval does not fail while clocks and configurations
differ; it keeps no deal alive past the removal of its entry, and nothing re-anchors
a running deal to the new key. Draining suffices because no deployed deal outlives
one: the released marketplace's payment deals are once-only with a guaranteed end,
and no rate deal is delivered while end service refuses to commit one. Removing the
retired identity at the cutover is what closes it: every snapshot must be signed by
an identity valid at the snapshot's own claimed `observedAt`, so a retired identity
left configured with a closed window still lets a holder of that key, were it
compromised, sign a snapshot backdated into its window. A drain can last as long as
the dispute window and any hold extension, so a seller facing a fixed switch date ends
or refunds what remains; the cutover's rule is
[settlement configuration's](../settlement-configuration/configuration.md#settlement-consumer-configuration-and-cutover).

**One transaction adapter, composed by part kind.**
`market_arkhai_payments.adapter.PaymentAdapter` implements the lifecycle
`PaymentAdapter` protocol for every mandate. Shared components — verified snapshot
reads, descriptor recording and refusal classification (`transaction.py`) — and the
`once` behaviour (reverse, extend, observations) serve every deal; the rate behaviour
(`rate_parts.py`: start, stop, notice, rate observations and the `authorize` phases) is
composed in when the mandate has a rate part. Neither subclasses the other: a
once-only mandate's `start_billing` is a no-op, and it refuses every rate command.
Every monetary rate operation — start, `start_billing`, stop, notice and reverse —
records its immutable descriptor's digest through the caller's `OperationStore`
(`OperationKeys.store`, under a part-derived key) before any I/O, so a changed retry
is refused before the authority is called and an identical retry resends one request
identity, with the authority's `request_id_reused` as the backstop; a once-only
reverse records when its caller supplies a store. The stop path reads nothing first:
an authority answering a stop of a stopped part with its winning stop satisfies the
new one only when that stop is effective no later. The adapter keeps no database and
imports neither `kit/deal-servicing` nor a domain: end service journals the one
billing-start key with the activated-delivery envelope, the adapter derives per-part
request identities from it, and `start` refuses before any call on missing,
malformed or mismatched activation evidence.

**Rate mandates.** For a rate option the kit derives, through the foundation codec,
the setup `once` part when the seller priced one and then the time-rate part. The rate
part charges one period's price, read through the agreed-price accessor, per `period`,
with `reserveAhead`, an absolute end at `start + duration_seconds` that a late start
never extends, `{afterStop: dispute_window}` holds and `maxHoldExtension`. `start` is
the payee's alone; stop entries exist only for accepted entitlements — the payer's,
and the payee's with its priced notice on spot, none on on-demand — and the dispute
authority's entry is `{notice: PT0S, partialPeriod: chosen}`, so each of its stops
carries its own treatment. Each prepaid `once` part ends at Agreement term end; the
setup part encodes Agreement start and the service clamps it to approval if later,
and both carry the inert `returned` end the schema requires. Each hold is after that
part's own end by the dispute window, separate from approval expiry. Only the
Agreement's dispute authority gets extend/lift with the accepted cap. Party rights are
codec-derived, not independent client permission defaults. The buyer re-derives every
part, its order, authorities, notices, holds, end, cap, asset and amount before
approval, and approves under its run's terms policy.

**The payment authority prices the period in progress.** Every rate stop entry and the
rate end carry a `partialPeriod` mapped from the accepted `settles_through`:
`started_period` is `charged`, `last_boundary` `returned`, `stop` `prorated`. The
authority computes the price, from the winning stop record — a party's entry, the
end's own treatment, the dispute authority's chosen one — and SCM computes no end
correction, cumulative target or refund. Periods earn at their end or at the part's
stop; exhaustion stops every co-funded part at `fundedThrough`. A seller's exceptional
end is a `delivery_end` filing to the dispute authority, whose self-penalty stops
rates `returned`; the seller sends no stop or reverse of its own. Beside a rate part
every raw stop is projected as a stop request, the setup part's terms end included,
and the deal's payment end is a rate part's final stop; in a once-only mandate a
part's stop stays the deal's end.

**Rate authorization is pure.** `authorize(phase, evidence, billing)` answers commit,
dispatch, start and disclose with allow, refuse or pending, a reason, the operation
identity and verified evidence references, and starts no billing. A snapshot decides
only within `snapshot_freshness_seconds` of the storefront's clock, and every stop,
end and funding bound is checked at the storefront's `now`; missing, unverifiable or
regressing state is pending, never allow. Disclosure needs a verified rate `start`
bound to end service's journaled billing start. Refusals are classified by the
authority's structured code: `transaction_stopped` at `start` is a delivery end,
`request_id_reused` and `hold_not_reversible` require repair,
`insufficient_held_funds` is reconciled from a read, `hold_matured` surfaces the
shortfall and the case path, and `insufficient_funds` at buyer approval is
`PaymentApprovalInsufficientFunds`; transport and server errors stay unknown.

Watch keeps payment/dispute cursors independent and last verified history separate
from the current refresh outcome. Respondent discovery signs or contests from
retained facts and journals the answer before advancing; deal watch waits for
that answer or confirmed closure. Original semantic filings have one durable
writer; lost responses resolve/adopt a signed equivalent case, never a fresh
case key. Initial missing mediation history permits the first filing only.
Neither cached history nor an absent authority is a current successful refresh.

## Current limits

The adapter starts, stops and observes rate parts, but no storefront services a
running rate deal: end service refuses to commit one, and funding-timer
classification, continued servicing and the consolidated rate qualification are not
implemented. Hosted execution of every offered treatment, the dispute entry's `chosen`
stop included, is unqualified; lane runs are lane-double evidence only. Local case
filing/observation is not deployed rate/ruling-execution qualification. The
Agreement pins the dispute origin/key for deal life without mid-deal rotation.
An unresolved unanswered case holds its deal's dispute cursor. The retention
observer and refresh-before-prune API are composed, but no production storefront
prune trigger exists, so seller evidence is retained indefinitely. VM/bare-metal
respondent lifetimes and term-end recovery differ as recorded in
[lifecycle limits](../deal-lifecycle/architecture.md#current-limits).

Heartbeat evidence remains persisted but is not an automated adjudication
policy. Evidence freshness, neutral oracle authority, disputed outcomes, and
splitter/oracle contract selection require a separate accepted design.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
