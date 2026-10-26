## ADDED Requirements

### Requirement: Payment events are per part

A payment event MUST be read from the payment authority the committed agreement names, and MUST record what happened to one part of the deal. It MUST carry `negotiation_id`, `commitment_ref`, `part`, `kind`, `actor`, `at`, `amount` where it moves money, `cause`, the `case_ref` of the case that caused it if any, the `extension_ref` an `extend` opened or a `lift` ended, `sequence`, and the authority's record reference. The lifecycle layer MUST treat the commitment reference as opaque.

#### Scenario: A reverse is recorded

- **WHEN** the payments service records a partial `reverse` of a hosted deal's `once` part
- **THEN** the seller's `watch` yields it with the part, the amount, the actor, the authority's sequence number, and its record reference

### Requirement: Arbitration is per agreement and separate from payment

A case MUST be filed about an agreement, not a part, at the intake of the dispute mechanism its `adjudication.dispute` names. Dispute events (filed, appended, ruled, closed) MUST carry the case reference and be read from that dispute mechanism's record, whose sequence is per agreement across its cases and whose entries the dispute authority signs. A transaction MAY have any number of cases. The payment adapter MUST NOT file or decide cases.

#### Scenario: Two cases on one deal

- **WHEN** a buyer files a case, it is ruled, and later files a second case on the same deal
- **THEN** both cases are recorded against the agreement, each with its own outcome

### Requirement: Only the dispute authority acts on a case

A party's dispute adapter MUST only file, append and read. Only the dispute authority MAY send a case's `extend` and `lift` or apply its outcome. Lifecycle events within the deal's terms, such as an entitled stop, MUST be applied by the party directly at the payment authority.

#### Scenario: A filed case requests a reverse

- **WHEN** a buyer files a case requesting a partial reverse
- **THEN** the buyer's dispute adapter sends nothing to the payment authority, and any reverse is recorded with the dispute authority as actor

### Requirement: An outcome is a list of per-part effects

A ruling's outcome MUST be a list of consequences, each a payment effect on one part (reverse an amount of a payment part, award an amount of a bond, stop a `rate` part at a *T* no later than now) or a delivery end at *T*. An effect the deal's mechanism cannot perform MUST NOT be part of an outcome. The storefront MUST send an outcome's delivery end, read through `watch`, to end service. An outcome without a delivery end MUST leave the term running.

#### Scenario: A ruling discounts a deal

- **WHEN** a ruling reverses a quarter of a hosted deal's held `once` payment and has no delivery end
- **THEN** the payment authority records one partial `reverse` by the dispute authority with the case reference, and the lease is unchanged

### Requirement: Outcome effects are applied once

The dispute authority MUST apply each payment effect at the payment authority with its own authority and the case reference, and MUST record each effect with a stable ID and an applied state, so a partly applied outcome resumes without repeating an effect.

#### Scenario: Application is interrupted

- **WHEN** the dispute authority has applied one of an outcome's two effects and restarts
- **THEN** it applies only the second, and the record shows both effects applied

#### Scenario: Two outcomes reverse the same part

- **WHEN** two outcomes on one hosted deal each reverse part of its `once` payment
- **THEN** both reverses are applied, the second bounded by what is still held

### Requirement: Peer messages are hints until the authority confirms them

A peer message (`commit`, `hint`) MUST be buyer-to-seller and MUST be kept as evidence. It MUST NOT change lifecycle state until a read of the authority confirms what it reports.

#### Scenario: A forged hint arrives

- **WHEN** a seller receives a `hint` that the buyer acted, and the authority's record shows no such event
- **THEN** the seller keeps the hint as evidence and continues service unchanged

### Requirement: Adapters translate deal commands into per-part events

A mechanism adapter MUST translate each deal-level command into the events of the parts it affects, and MUST send the authority only per-part events. A part MUST be offered only the events its shape supports; a `once` part has no stop event.

#### Scenario: A buyer tries to stop a once-only deal

- **WHEN** a buyer submits an early end on a hosted deal whose only part is `once`
- **THEN** the outcome is `rejected`, naming the part shape, and no authority is contacted

#### Scenario: A reverse names a part

- **WHEN** a seller submits `reverse` of an amount on a hosted deal
- **THEN** the adapter sends one `reverse` event naming the `once` part and that amount

### Requirement: Lifecycle terms are part of the selected option

A settlement option MAY carry `adjudication` (`version`, `dispute`, `dispute_window_seconds`, `case_hold_max_seconds`), `early_termination` (`version`, `entitlements` keyed by `payer` or `payee` with `notice_seconds` and `settles_through`, `exposure_seconds`, `max_term_seconds`), and `bond` (`version`, `amount`, reserved until a mechanism can hold a seller-funded stake) in its `params`. The shared codec MUST decode them, so they are part of the Agreement bytes and the option ID.

#### Scenario: A term changes the option ID

- **WHEN** a seller changes an option's dispute window and republishes
- **THEN** the option has a new option ID

### Requirement: Builders emit terms only where they bind

An option builder MUST emit `adjudication` on every option whose mechanism has a lifecycle adapter, and MUST emit `early_termination` only when some part of the option can be stopped. Options whose mechanism has no lifecycle adapter MUST carry no lifecycle terms.

#### Scenario: A hosted once option is built

- **WHEN** a storefront builds an `arkhai.payments.v1` option with a single `once` part
- **THEN** the option carries `adjudication` and no `early_termination`

#### Scenario: An Alkahest option is built

- **WHEN** a storefront builds an Alkahest option with any arbiter it supports today
- **THEN** the option carries no lifecycle terms, and its release condition keeps its existing service terms

### Requirement: Malformed terms are refused

An unknown `version`, `dispute`, initiator key, or `settles_through` value, or a `dispute` whose kit does not declare the option's payment mechanism, MUST make a builder refuse to emit the option and a buyer refuse to select it. Empty `entitlements`, and `early_termination` on an option with no stoppable part, MUST be refused at publication.

#### Scenario: A buyer meets an unknown dispute mechanism

- **WHEN** a listing's option names a `dispute` the buyer client does not recognize
- **THEN** the buyer does not select that option and reports the unrecognized dispute mechanism

#### Scenario: A dispute mechanism does not serve the payment mechanism

- **WHEN** a seller configures an option whose `dispute` kit does not declare the option's payment mechanism
- **THEN** publication refuses the option, naming the pair

### Requirement: Term values agree with the Agreement and the seller's budget

`max_term_seconds` MUST equal the Agreement's `duration_seconds`. A mechanism with a reserve-ahead parameter MUST have it at least `exposure_seconds`. A storefront MUST refuse, at publication and at acceptance, an option whose `exposure_seconds` is below its polling interval plus its configured watchdog and teardown budget, and MUST refuse a configuration change that would put an active deal over its exposure.

#### Scenario: Exposure is below the servicing budget

- **WHEN** a storefront polls every 290 seconds with a 60-second teardown budget and an option declares 300 seconds of exposure
- **THEN** it refuses to publish the option and names the budget and the declared exposure

#### Scenario: Maximum term disagrees with the Agreement

- **WHEN** an accepted Agreement's `duration_seconds` differs from its option's `max_term_seconds`
- **THEN** the buyer refuses to commit

### Requirement: Entitlements are the stop authorities

An adapter MUST make each initiator with an entitlement a `stop` authority of the stoppable parts, and the dispute authority a `stop` authority of every stoppable part, and nobody else. The dispute authority MUST use its stop only to apply outcomes. An option without `early_termination` MUST have no stop authorities. A builder MUST refuse a term its mechanism cannot realize, such as `bond` on a mechanism that cannot hold a seller-funded stake.

#### Scenario: An on-demand option is derived

- **WHEN** an option's `early_termination` has a `payer` entitlement only
- **THEN** the payer and the dispute authority are the only stop authorities, and the payee is not one

### Requirement: Holds last through the dispute window

`adjudication.dispute_window_seconds` MUST bound filing: each payment adapter MUST derive holds lasting no less than the Agreement's term end, `start_utc + duration_seconds`, plus the window. The window MUST NOT be shorter than the dispute mechanism's minimum.

#### Scenario: A once deal's hold is derived

- **WHEN** a hosted mandate is derived for a deal whose term ends at 13:00 with a one-day window
- **THEN** its `once` hold ends no earlier than 13:00 the next day, later by however long approval is delayed

### Requirement: A case is in time when its extension is accepted

A case MUST be in time if and only if the payment authority accepts the dispute authority's `extend` for it. The dispute authority MUST send `extend` on every part with held money at filing, with no human step, before acknowledging the case, keyed by case and part. A `dispute` MUST be `accepted` only once every extension is recorded, and `rejected` with "hold already paid out" when the payment authority refuses; otherwise it is `pending` or `unknown` until the case is read.

#### Scenario: A case is filed at the last moment

- **WHEN** a buyer files a case one minute before a `once` hold pays out, and mediation rules a week later with `case_hold_max_seconds` null
- **THEN** filing returns `accepted` with the extension recorded, the ruling's partial `reverse` is applied, and `lift` pays the remainder to the seller

#### Scenario: Payout wins against the extension

- **WHEN** a case reaches the intake at 12:59:59.9, the hold pays out at 13:00:00, and the `extend` reaches the payment authority at 13:00:00.1
- **THEN** the payment authority refuses the `extend`, filing returns `rejected` with "hold already paid out", and the case is recorded as late

#### Scenario: The intake restarts before extending

- **WHEN** the intake records a case and restarts before its `extend` is acknowledged
- **THEN** it resends `extend` with the same idempotency key, the payment authority returns the one extension it recorded, and filing is `accepted` only then

### Requirement: A late case moves no paid-out money

A late case MAY be recorded and ruled, and its outcome MAY end delivery. An outcome MUST act only on money still held.

#### Scenario: A late case ends delivery

- **WHEN** a buyer files a case after the `once` hold has paid out, and it is ruled with a delivery end
- **THEN** filing returned `rejected`, the storefront ends delivery through end service, and no payment effect is applied

### Requirement: Each case owns its hold extensions

`extend {part, until?}` MUST open an extension and return its `ref`, and `lift {ref}` MUST end that extension only. A held amount MUST NOT pay out while an extension on its part without `until` is open, nor before the latest `until` among the open ones. The dispute authority MUST lift a case's extensions only after its outcome is applied.

#### Scenario: Two cases overlap

- **WHEN** case A and case B on one deal each hold its `once` part, and A closes and its `lift` arrives after B's `extend`
- **THEN** the part stays held until B's extension is lifted

### Requirement: Case holds are capped by terms

A held amount MUST pay out no later than its normal date plus the part's maximum extension, taken from `case_hold_max_seconds`. With `null`, an extension without `until` MUST last until it is lifted.

#### Scenario: A bounded case hold expires

- **WHEN** a case stays open longer than `case_hold_max_seconds` past the hold's normal end
- **THEN** the held money pays out at the cap without a `lift`

### Requirement: Only the dispute authority extends and lifts

Every mandate MUST authorize `extend` and `lift` for the dispute authority only.

#### Scenario: A party tries to extend

- **WHEN** a payer sends `extend` on a hosted deal's part
- **THEN** the payment authority refuses it, since the mandate lists only the dispute authority

### Requirement: Any party may append to a case

A dispute adapter MUST offer `append {case_ref, items}` on an open case to either party, repeatedly. The dispute record MUST show each appended item under the actor that sent it. A case surfaced through the seller's `watch` MUST be the seller's cue to append its evidence.

#### Scenario: The seller answers a buyer's case

- **WHEN** a buyer's case on a hosted deal appears in the seller's `watch`
- **THEN** the seller appends the buyer's signed accepting request and its received peer messages from its evidence store, and the dispute record shows them under the seller

#### Scenario: The claimant adds evidence

- **WHEN** a buyer appends a second evidence item to its open case
- **THEN** the record shows both submissions under the buyer, in order

### Requirement: Arkhai mediation rules only payee self-penalties mechanically

A party's request against itself MUST be an ordinary `dispute`, with no kind of its own. `optimistic.arkhai` MUST rule a dispute with no adjudicator only when it is filed by the payee, every requested effect is a reverse, bond award or stop, and any delivery end is no later than now. A dispute filed by the payer MUST NOT be ruled mechanically.

#### Scenario: A seller's hardware fails

- **WHEN** a seller files its standard exceptional-end request on a hosted `once` deal halfway through its term
- **THEN** the dispute authority rules it mechanically and applies a `reverse` of half the payment with the case reference in its payload, and the storefront reads the delivery end through `watch` and ends delivery now

#### Scenario: A buyer asks for a stop it is not entitled to

- **WHEN** a buyer files a dispute requesting only that a rate part stop now
- **THEN** the dispute goes to a person and nothing is applied until it is ruled

### Requirement: A seller's exceptional end is a standard request

The seller's standard request for an exceptional end MUST end delivery now, reverse the unserved share of `once` parts by time, stop `rate` parts now, and award any bond in full. The `optimistic.arkhai` dispute adapter MUST reject a payee self-penalty request with a later delivery end before contacting the intake.

#### Scenario: A seller's request names a future end

- **WHEN** a seller files its standard exceptional-end request with a delivery end later than now
- **THEN** the dispute adapter rejects it before contacting any authority

### Requirement: Lifecycle commands have defined outcomes

`submit` MUST take a command `{negotiation_id, kind, operation_key, at, payload}`, never an event. Its outcome MUST be `accepted` with the authority records, `rejected` with the reason, `pending`, or `unknown`; a `dispute` is `accepted` only once its money is held. An `unknown` outcome MUST be resolved by `read`. Each part event's idempotency key MUST derive from the operation key; a retry with the same key and different content MUST be rejected locally.

#### Scenario: A reverse's response is lost

- **WHEN** a seller's `reverse` times out in transport
- **THEN** the outcome is `unknown`, and a retry with the same operation key returns the one recorded reversal

#### Scenario: A retry changes content

- **WHEN** a command is retried with the same operation key and a different `at`
- **THEN** it is rejected without contacting the authority

### Requirement: The buyer half hides the mechanism

The buyer half MUST offer `submit` and `read(negotiation_id)` without the caller branching on mechanism. `read` MUST return the deal's lifecycle state, each part's open extensions, its authority events and its cases, or `rejected` when the deal's mechanism has no adapter.

#### Scenario: A buyer reads a deal with no lifecycle adapter

- **WHEN** a buyer reads an Alkahest deal through the buyer half
- **THEN** the result is `rejected`, naming the mechanism

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token. Each deal MUST carry its negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state (unstarted, running, ending, ended, repair required), current deadline, and whether any part has an open extension. A deal with only `once` parts MUST be running from its verified commitment until delivery ends.

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

### Requirement: Adapters resolve per mechanism and arbiter

Payment adapters MUST resolve through the domain's role table by negotiation ID and the Agreement's mechanism, not through the conditional-escrow port. Within a mechanism they MUST resolve by arbiter, and by oracle or oracle schema for oracle-backed arbiters.

#### Scenario: A mechanism has no adapter for a command

- **WHEN** a party submits a kind the deal's adapter does not support
- **THEN** the outcome is `rejected` with a reason naming the unsupported kind, and no authority is contacted

### Requirement: Dispute adapters resolve by dispute mechanism

Dispute adapters MUST resolve through a dispute adapter table the domain composition fills, keyed by `adjudication.dispute`. The lifecycle kits MUST receive both adapter tables injected and MUST NOT import a payment or dispute kit. An unknown dispute mechanism, or one whose kit does not declare the deal's payment mechanism, MUST be `rejected` before any request.

#### Scenario: A deal names a dispute mechanism with no adapter

- **WHEN** a party files a dispute on a deal whose `adjudication.dispute` has no entry in the dispute adapter table
- **THEN** the outcome is `rejected`, naming the dispute mechanism, and no intake is contacted

### Requirement: Watch replays from a durable cursor per record

`watch(negotiation_id)` MUST yield the current state, then each later event and deadline change, ordered within each record only. It MUST keep one durable cursor per record per deal: the payment authority's transaction sequence and the dispute record's agreement sequence. A cursor MUST advance after end service journals the event's effect, or at once for an event with no physical effect. A restart MUST resume each record from its cursor, surfacing cases filed while the storefront was down.

#### Scenario: The storefront restarts mid-deal

- **WHEN** the storefront restarts after the authority recorded a reversal it had not yet acted on
- **THEN** `watch` yields that reversal again and its effect is recorded once

#### Scenario: A delivery-only ruling arrives during a restart

- **WHEN** a ruling with a delivery end and no payment effect is recorded while the storefront is down
- **THEN** after restart `watch` yields it from the dispute cursor, end service ends delivery, and the payment cursor is unchanged

#### Scenario: A discount needs no physical effect

- **WHEN** `watch` yields a ruling whose only effect is a partial reverse
- **THEN** both cursors advance without an end-service request

#### Scenario: A case's extension is observed

- **WHEN** `watch` yields a filed case, an append to it, and its `extend`
- **THEN** both cursors advance without an end-service request

### Requirement: Lifecycle routes are authenticated per role

The storefront MUST expose the seller half's `submit`, `read`, and `list` through the administrator-principal contract. The VM and bare-metal storefronts MUST expose a buyer route for `commit` and `hint`, authenticated as the negotiation's buyer principal, with signed responses. The storefront MUST NOT relay a buyer's authority command.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through the VM admin route
- **THEN** the route files the seller's standard exceptional-end request through the seller half, the dispute authority applies it, and the lease changes only through end service

### Requirement: End service keeps the earliest final request

End service MUST take final requests, "end delivery at *T*" with actor, cause, and source, from authority stops through `watch`, from dispute outcomes with a delivery end, and from local delivery decisions: bare-metal buyer teardown, terminal settlement, and the further local sources of mechanisms built on this interface. Repeated final requests for one deal MUST keep the earliest *T*. A local decision MUST NOT move money.

#### Scenario: A buyer tears down bare metal

- **WHEN** a bare-metal buyer requests teardown through the storefront
- **THEN** end service terminates the lease with the buyer as actor, the request is kept as evidence, and no payment command is sent

### Requirement: End service terminates or truncates, and journals each effect

When *T* is now or past, end service MUST terminate the lease; otherwise it MUST truncate it to *T* at one-second precision or finer. Each effect MUST be journaled and retried until done. A shortfall in the exposure budget at runtime MUST only warn and MUST NOT stop the lifecycle loops.

#### Scenario: A stop arrives after its effective time

- **WHEN** end service receives a stop whose time has passed
- **THEN** it terminates the lease rather than truncating it to a past time

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded. The buyer's store MUST be the buyer-side lifecycle kit's, under a root the buyer composition passes beside the buyer profile, and the kit MUST NOT depend on core buyer; the storefront's MUST be the servicing kit's.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

### Requirement: Each party keeps its commitment envelopes and authority records

The buyer MUST keep the seller's signed acceptance with its proof headers and exact body before committing; the seller MUST keep the buyer's signed accepting request. Both MUST keep the peer messages they sent or received and the authority records they receive.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the proof headers and exact body before committing

### Requirement: Evidence outlives the deal and its cases

Records MUST be kept until the Agreement's `dispute_window_seconds` after the latest of the deal's delivery end and physical recovery, the last payout of every part as the party observes it through `read` or `watch`, and the close of every case on the deal. An accepted negotiation never committed MUST be kept for the same window after its acceptance expires.

#### Scenario: A long deal passes the window

- **WHEN** a running deal's last authority event is older than the dispute window
- **THEN** its evidence records are kept

#### Scenario: A case stays open

- **WHEN** a case on an ended deal remains unresolved past the window
- **THEN** its evidence records are kept until the window after its resolution

#### Scenario: A ruling ends a deal early and a case follows

- **WHEN** a ruling ends a hosted `once` deal mid-term, and the buyer files a case contesting its amount while the remaining payment is still held
- **THEN** both parties still hold their commitment envelopes and authority records, since the last payout has not happened

### Requirement: A dispute is one case payload

A `dispute` MUST carry one case about the agreement: the commitment reference, the committed agreement or where to fetch it, the terms, the claim, the requested outcome, and ordered evidence items. Each item MUST be an evidence-store record with kind, producer, time, content digest, and the exact original bytes or the authority's signed record. A party MUST be able to export the case as one bundle.

#### Scenario: A buyer files a dispute

- **WHEN** a buyer files a dispute through the buyer half
- **THEN** the case payload is built from its evidence store, and each item carries the exact bytes it received

### Requirement: Refund is a reverse command; reconciliation finds unreported commitments

A seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain and find commitments a buyer never reported.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** the reconciliation pass finds the commitment and the seller serves or reverses it
