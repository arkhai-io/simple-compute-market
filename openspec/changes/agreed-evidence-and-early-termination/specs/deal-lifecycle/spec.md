## ADDED Requirements

### Requirement: Payment events are per part

A payment event MUST be read from the payment authority the committed agreement names, and MUST record what happened to one part of the deal. It MUST carry `negotiation_id`, `commitment_ref`, `part`, `kind`, `actor`, `at`, `amount` where it moves money, `cause`, the `case_ref` of the case that caused it if any, the `extension_ref` an `extend` opened or a `lift` ended, `sequence`, and the authority's record reference. The lifecycle layer MUST treat the commitment reference as opaque.

#### Scenario: A reverse is recorded

- **WHEN** the payments service records a partial `reverse` of a hosted deal's `once` part
- **THEN** the seller's `watch` yields it with the part, the amount, the actor, the authority's sequence number, and its record reference

### Requirement: Disputes are per agreement and separate from payment

A case MUST be filed about an agreement, not a part, with the dispute authority its `adjudication.dispute` names. Dispute events (filed, appended, ruled, closed) MUST carry the case reference and be read from that authority's record, whose sequence is per agreement across its cases and whose entries are signed with the Agreement's `adjudication.dispute.record_key`. A transaction MAY have any number of cases. The payment adapter MUST NOT file or decide cases.

#### Scenario: Two cases on one deal

- **WHEN** a buyer files a case, it is ruled, and later files a second case on the same deal
- **THEN** both cases are recorded against the agreement, each with its own outcome

### Requirement: Only the dispute authority acts on a case

A party's dispute adapter MUST communicate only with the agreement's dispute authority, and MUST only file, append and read. A filing's or append's outcome MUST be the dispute authority's response; it MUST NOT be a payment authority response passed through. Only the dispute authority MAY send a case's `extend` and `lift` or apply its outcome. Lifecycle events within the deal's terms, such as an entitled stop, MUST be applied by the party directly at the payment authority.

#### Scenario: A filed case requests a reverse

- **WHEN** a buyer files a case requesting a partial reverse
- **THEN** the buyer's dispute adapter sends nothing to the payment authority, and any reverse is recorded with the dispute authority as actor

#### Scenario: The authority cannot complete an extension

- **WHEN** a buyer files a case and the dispute authority's `extend` fails at the payments service or misses the authority's deadline
- **THEN** the buyer receives the dispute authority's own error or pending result, and the buyer half reports no payments-service response as the filing's outcome

### Requirement: An outcome is a list of per-part effects

A ruling's outcome MUST be a list of consequences, each a payment effect on one part (reverse an amount of a payment part, award an amount of a bond, stop a `rate` part at a *T* no later than now) or a delivery end at *T*. The storefront MUST send an outcome's delivery end, read through `watch`, to end service. An outcome without a delivery end MUST leave the term running.

#### Scenario: A ruling discounts a deal

- **WHEN** a ruling reverses a quarter of a hosted deal's held `once` payment and has no delivery end
- **THEN** the payment authority records one partial `reverse` by the dispute authority with the case reference, and the lease is unchanged

### Requirement: Requests are stated in the authority's terms

A case's requested outcome MUST be stated in the terms of the dispute authority's interface. The lifecycle layer MUST NOT compute per-part effects for a request; the dispute authority derives them from the committed form.

#### Scenario: A buyer requests a refund for an outage

- **WHEN** a buyer files a case requesting a refund of the share of its deal lost to an outage
- **THEN** the buyer half sends the request in the interface's terms, with no per-part amounts of its own

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

### Requirement: The adjudication term names the dispute authority

`adjudication.dispute` MUST carry the authority's `interface` and that interface's fields: `origin`, `account`, `record_key`, and interface-owned `params`.

#### Scenario: The same interface at another origin

- **WHEN** two sellers' options name `arkhai.mediation.v1` authorities with different origins and accounts
- **THEN** they are different dispute authorities, and each option's mandate authorizes only its own authority's account

### Requirement: Builders emit terms only where they bind

An option builder MUST emit `adjudication` on every option whose mechanism has a lifecycle adapter, and MUST emit `early_termination` only when some part of the option can be stopped. Options whose mechanism has no lifecycle adapter MUST carry no lifecycle terms.

#### Scenario: A hosted once option is built

- **WHEN** a storefront builds an `arkhai.payments.v1` option with a single `once` part
- **THEN** the option carries `adjudication` and no `early_termination`

#### Scenario: An Alkahest option is built

- **WHEN** a storefront builds an Alkahest option with any arbiter it supports today
- **THEN** the option carries no lifecycle terms, and its release condition keeps its existing service terms

### Requirement: Malformed terms are refused

An unknown `version`, initiator key, or `settles_through` value, a `dispute` whose interface has no adapter, or a `dispute` authority that does not advertise the option's payment mechanism, MUST make a builder refuse to emit the option and a buyer refuse to select it. A buyer MUST refuse an option whose dispute authority matches none of the authorities it accepts. Empty `entitlements`, and `early_termination` on an option with no stoppable part, MUST be refused at publication.

#### Scenario: A buyer meets an authority it has not accepted

- **WHEN** a listing's option names an `arkhai.mediation.v1` authority whose account matches none of the buyer's accepted authorities
- **THEN** the buyer does not select that option and reports the unaccepted authority

#### Scenario: An authority does not serve the payment mechanism

- **WHEN** a seller configures an option whose dispute authority does not advertise the option's payment mechanism
- **THEN** publication refuses the option, naming the authority and the mechanism

### Requirement: Dispute timing terms are bounded

`case_hold_max_seconds` MUST be a nonnegative integer or `null`. A `dispute_window_seconds` or `case_hold_max_seconds` below the dispute authority's advertised minimum MUST be refused at publication and by the buyer.

#### Scenario: A zero case hold is below the minimum

- **WHEN** a seller configures `case_hold_max_seconds: 0` for an authority that advertises `null` as its minimum
- **THEN** publication refuses the option

### Requirement: Term values agree with the Agreement and the seller's budget

`max_term_seconds` MUST equal the Agreement's `duration_seconds`. A mechanism with a reserve-ahead parameter MUST have it at least `exposure_seconds`. A storefront MUST refuse, at publication and at acceptance, an option whose `exposure_seconds` is below its polling interval plus its configured watchdog and teardown budget, and MUST refuse a configuration change that would put an active deal over its exposure.

#### Scenario: Exposure is below the servicing budget

- **WHEN** a storefront polls every 290 seconds with a 60-second teardown budget and an option declares 300 seconds of exposure
- **THEN** it refuses to publish the option and names the budget and the declared exposure

#### Scenario: Maximum term disagrees with the Agreement

- **WHEN** an accepted Agreement's `duration_seconds` differs from its option's `max_term_seconds`
- **THEN** the buyer refuses to commit

### Requirement: Entitlements are the stop authorities

An adapter MUST make each initiator with an entitlement a `stop` authority of the stoppable parts, and the agreement's dispute authority, the account in `adjudication.dispute`, a `stop` authority of every stoppable part, and nobody else. The dispute authority MUST use its stop only to apply outcomes. An option without `early_termination` MUST have no stop authorities. A builder MUST refuse a term its mechanism cannot realize, such as `bond` on a mechanism that cannot hold a seller-funded stake.

#### Scenario: An on-demand option is derived

- **WHEN** an option's `early_termination` has a `payer` entitlement only
- **THEN** the payer and the dispute authority are the only stop authorities, and the payee is not one

### Requirement: The dispute window sets the earliest payout

Each payment adapter MUST derive holds under which each amount a part holds pays out no earlier than the part's end plus `adjudication.dispute_window_seconds`. A `once` part's end MUST be the Agreement's term end, `start_utc + duration_seconds`; a rate part's end MUST be its stop, or the term end if it is not stopped. The window MUST NOT be shorter than the dispute authority's advertised minimum. Whether a case filed after the window is taken MUST be the dispute authority's policy.

#### Scenario: A once deal's hold is derived

- **WHEN** a hosted mandate is derived for a deal whose term ends at 13:00 with a one-day window
- **THEN** its `once` hold ends no earlier than 13:00 the next day, later by however long approval is delayed

#### Scenario: A rate part stops early

- **WHEN** a spot deal with a 30-day maximum term and a 14-day window is stopped after one hour
- **THEN** its rate part's amounts pay out 14 days after the stop, not after the maximum term

#### Scenario: A case is filed after the window while another holds the part

- **WHEN** case A holds a `once` part past its normal payout, and a party files case B after the window
- **THEN** the payments service accepts B's `extend`, since nothing has paid out, and the part stays held until both are lifted

### Requirement: A case holds money only through an accepted extension

On each part, a case MUST protect exactly the money for which the payment authority accepted the dispute authority's `extend`. Arkhai mediation MUST send `extend` on every part with held money at filing, with no human step, before acknowledging the case, keyed by case and part.

#### Scenario: A case is filed at the last moment

- **WHEN** a buyer files a case one minute before a `once` hold pays out, and mediation rules a week later with `case_hold_max_seconds` null
- **THEN** filing returns `accepted` with the part `held`, the ruling's partial `reverse` is applied, and `lift` pays the remainder to the seller

#### Scenario: Payout wins against the extension

- **WHEN** a case reaches the dispute authority at 12:59:59.9, the hold pays out at 13:00:00, and the `extend` reaches the payment authority at 13:00:00.1
- **THEN** the payment authority refuses the `extend`, and filing returns `accepted` with the case reference and the part `paid_out`

#### Scenario: The authority restarts before extending

- **WHEN** the dispute authority records a case and restarts before its `extend` is acknowledged
- **THEN** it resends `extend` with the same idempotency key, the payment authority returns the one extension it recorded, and filing reports the part `held` only then

### Requirement: A filing's outcome is the authority's answer

A `dispute` MUST be `accepted` with the case reference and each part's status, `held` with its extension ref or `paid_out`, once every extension is resolved. It MUST be `rejected` only when the dispute authority refuses the filing, and otherwise `pending` or `unknown` until the case is read.

#### Scenario: Parts differ

- **WHEN** a case is filed on a deal with two `once` parts, one still held and one already paid out
- **THEN** filing returns `accepted` with the first part `held` with its ref and the second `paid_out`

### Requirement: A late case moves no paid-out money

A late case MAY be recorded and ruled, and its outcome MAY end delivery. An outcome MUST act only on money still held.

#### Scenario: A late case ends delivery

- **WHEN** a buyer files a case after the `once` hold has paid out, and it is ruled with a delivery end
- **THEN** filing returned `accepted` with every part `paid_out`, the storefront ends delivery through end service, and no payment effect is applied

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

Every mandate MUST authorize `extend` and `lift` for the agreement's dispute authority only, the account its `adjudication.dispute` names.

#### Scenario: A party tries to extend

- **WHEN** a payer sends `extend` on a hosted deal's part
- **THEN** the payment authority refuses it, since the mandate lists only the dispute authority

### Requirement: Any party may append to a case

A dispute adapter MUST offer `append {case_ref, items}` on an open case to either party, repeatedly, with an idempotency key derived from the command's operation key. The dispute record MUST show each appended item under the actor that sent it. A case the counterparty filed, surfaced through the seller's `watch`, MUST make the seller's append of its evidence a journaled effect keyed by `case_ref`, which the dispute cursor waits for.

#### Scenario: The seller answers a buyer's case

- **WHEN** a buyer's case on a hosted deal appears in the seller's `watch`
- **THEN** the seller appends the buyer's signed message the agreement rests on and its received peer messages from its evidence store, and the dispute record shows them under the seller

#### Scenario: The storefront crashes before appending

- **WHEN** the storefront sees a buyer's case and restarts before its append is acknowledged
- **THEN** after restart it appends with the same idempotency key, and the record shows the seller's items once

#### Scenario: The claimant adds evidence

- **WHEN** a buyer appends a second evidence item to its open case
- **THEN** the record shows both submissions under the buyer, in order

### Requirement: Mechanical rulings are the authority's policy

A party's request against itself MUST be an ordinary `dispute`, with no kind of its own. Which disputes an authority rules with no person MUST be its published policy, and the lifecycle layer MUST NOT depend on it. Arkhai mediation's policy MUST rule mechanically only payee-filed requests at least as strong as the standard self-penalty on every part, and MUST send every other dispute, including any filed by the payer, to its triage, until that policy is widened.

#### Scenario: A seller's hardware fails

- **WHEN** a seller files the standard self-penalty on a hosted `once` deal halfway through its term
- **THEN** Arkhai mediation rules it mechanically and applies a `reverse` of half the payment with the case reference in its payload, and the storefront reads the delivery end through `watch` and ends delivery now

#### Scenario: A seller requests a bare stop

- **WHEN** a seller with no stop entitlement files a dispute requesting only that a rate part stop now
- **THEN** Arkhai mediation sends it to triage and nothing is applied until a person rules

#### Scenario: A buyer asks for a stop it is not entitled to

- **WHEN** a buyer files a dispute requesting only that a rate part stop now
- **THEN** the dispute goes to a person and nothing is applied until it is ruled

### Requirement: A seller's exceptional end is a standard request

The seller half's exceptional-end command MUST file, with the agreement's dispute authority, the interface's standard self-penalty with a delivery end of now. The standard self-penalty MUST end delivery now, reverse the unserved share of `once` parts by time, stop `rate` parts now, and award any bond in full, as computed by the dispute authority from the committed form.

#### Scenario: An administrator files an exceptional end

- **WHEN** an administrator files an exceptional end on a hosted `once` deal
- **THEN** the filed request names the standard self-penalty and a delivery end of now, and carries no per-part amounts computed by the storefront

### Requirement: Lifecycle commands have defined outcomes

`submit` MUST take a command `{negotiation_id, kind, operation_key, at, payload}`, never an event. Its outcome MUST be `accepted` with the counterpart's records, `rejected` with its reason, `pending`, or `unknown`; a `dispute`'s outcome is the dispute authority's. An `unknown` outcome MUST be resolved by `read`. Each part event's idempotency key MUST derive from the operation key; a retry with the same key and different content MUST be rejected locally.

#### Scenario: A reverse's response is lost

- **WHEN** a seller's `reverse` times out in transport
- **THEN** the outcome is `unknown`, and a retry with the same operation key returns the one recorded reversal

#### Scenario: A retry changes content

- **WHEN** a command is retried with the same operation key and a different `at`
- **THEN** it is rejected without contacting the authority

### Requirement: Dispute writes are idempotent

A `dispute` and an `append` MUST carry an idempotency key derived from the command's operation key, so a retry returns the one case or item recorded.

#### Scenario: A filing's response is lost

- **WHEN** a buyer's `dispute` times out in transport and is retried with the same operation key
- **THEN** the dispute authority returns the one case it recorded, and no second case or extension exists

### Requirement: The buyer half hides the mechanism

On VM and bare-metal deals the buyer half MUST offer `submit` and `read(negotiation_id)` without the caller branching on mechanism. `read` MUST return the deal's lifecycle state, each part's open extensions, its authority events and its cases, or `rejected` when the deal's mechanism has no adapter.

#### Scenario: A buyer reads a deal with no lifecycle adapter

- **WHEN** a buyer reads an Alkahest deal through the buyer half
- **THEN** the result is `rejected`, naming the mechanism

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token. Each deal MUST carry its negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state (unstarted, running, ending, ended, repair required), current deadline, whether any part has an open extension, and its open cases. A deal with only `once` parts MUST be running from its verified commitment until delivery ends.

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

### Requirement: Adapters resolve per mechanism and arbiter

Payment adapters MUST resolve through the domain's role table by negotiation ID and the Agreement's mechanism, not through the conditional-escrow port. Within a mechanism they MUST resolve by arbiter, and by oracle or oracle schema for oracle-backed arbiters.

#### Scenario: A mechanism has no adapter for a command

- **WHEN** a party submits a kind the deal's adapter does not support
- **THEN** the outcome is `rejected` with a reason naming the unsupported kind, and no authority is contacted

### Requirement: Dispute adapters resolve by dispute interface

Dispute adapters MUST resolve through a dispute adapter table the domain composition fills, keyed by `adjudication.dispute.interface`. The lifecycle kits MUST receive both adapter tables injected and MUST NOT import a payment or dispute kit, and a dispute kit MUST NOT name a payment mechanism. An interface with no adapter, or an authority that does not advertise the deal's payment mechanism, MUST be `rejected` before any request.

#### Scenario: A deal names an interface with no adapter

- **WHEN** a party files a dispute on a deal whose `adjudication.dispute.interface` has no entry in the dispute adapter table
- **THEN** the outcome is `rejected`, naming the interface, and no authority is contacted

### Requirement: Dispute authorities are named per deal

The Agreement's `adjudication.dispute` MUST be the only source of a committed deal's dispute authority: its origin, account and record key. Configured `[[Dispute]]` entries MUST be defaults ordered by preference: a storefront's builders fill options from its entries that advertise the option's payment mechanism, and a buyer accepts only authorities matching its entries. Mandate derivation MUST read the dispute authority's account from the option. Changing an entry MUST NOT affect accepted deals.

#### Scenario: A seller changes its preferred authority

- **WHEN** a seller reorders its `[[Dispute]]` entries while a deal accepted under the old first entry is running
- **THEN** new options name the new first entry, and the running deal's cases still go to the authority its Agreement names

### Requirement: Lifecycle servicing is composed by the compute domains

The VM and bare-metal roles MUST compose the buyer half, the seller half, both evidence stores and `watch`. API-credit roles MUST compose the `[[Dispute]]` entries they need to check options at publication, selection and the mandate check, and are not required to compose the halves, the evidence stores or `watch`.

#### Scenario: An API-credit storefront publishes a hosted option

- **WHEN** an API-credit storefront publishes an `arkhai.payments.v1` option
- **THEN** the option carries `adjudication` checked against the storefront's dispute entries, and the storefront runs no lifecycle loop

### Requirement: Watch replays from a durable cursor per record

`watch(negotiation_id)` MUST yield the current state, then each later event and deadline change, ordered within each record only. It MUST keep one durable cursor per record per deal: the payment authority's transaction sequence and the dispute record's agreement sequence. A restart MUST resume each record from its cursor, surfacing cases filed while the storefront was down.

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

- **WHEN** `watch` yields a seller's own filed case, an append to it, and its `extend`
- **THEN** both cursors advance without an end-service request or an append

### Requirement: A watch cursor advances after its effect is journaled

A `watch` cursor MUST advance only after the event's effect is journaled: by end service for a delivery end, and as the seller's append for a case the counterparty filed. An event with no effect MUST advance its cursor at once.

#### Scenario: A buyer's case arrives

- **WHEN** `watch` yields a case the buyer filed
- **THEN** the dispute cursor advances only after the seller's append is journaled

### Requirement: Lifecycle routes are authenticated per role

The VM and bare-metal storefronts MUST expose the seller half's `submit`, `read`, and `list` through the administrator-principal contract. The VM and bare-metal storefronts MUST expose a buyer route for `commit` and `hint`, authenticated as the negotiation's buyer principal, with signed responses. The storefront MUST NOT relay a buyer's authority command.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through the VM admin route
- **THEN** the route files the standard self-penalty with the agreement's dispute authority through the seller half, the authority applies it, and the lease changes only through end service

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

### Requirement: The earliest final request governs delivery admission

End service MUST record a deal's earliest final request whether or not a lease exists. Delivery start, including reconciliation's, MUST be ordered against it as against refund intent: a deal whose end has arrived MUST NOT start delivery, a lease started later MUST end no later than it, and fulfillment already dispatched MUST be adopted and terminated. A deal ended before any resource was dispatched MUST complete with no teardown pending.

#### Scenario: A ruling ends delivery before the lease exists

- **WHEN** a ruling with a delivery end of now arrives for a committed VM deal that has not been provisioned
- **THEN** no delivery starts, reconciliation does not start it later, and end service records the deal ended with nothing to tear down

#### Scenario: The end overlaps delivery start

- **WHEN** a final request arrives while provisioning for the same deal is dispatched
- **THEN** the dispatched fulfillment is adopted and terminated, and the lease ends no later than the request's *T*

#### Scenario: The storefront restarts between the end and provisioning

- **WHEN** the storefront restarts after recording a final request for an unprovisioned deal
- **THEN** after restart the deal still does not start delivery

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded. The buyer's store MUST be the buyer-side lifecycle kit's, under a root the buyer composition passes beside the buyer profile, and the kit MUST NOT depend on core buyer; the storefront's MUST be the servicing kit's.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

### Requirement: Each party keeps its commitment envelopes and authority records

The buyer MUST keep the seller's signed acceptance with its proof headers and exact body before committing. The seller MUST keep the buyer's signed message the agreement rests on: the buyer's opening or counteroffer the seller accepted, or the buyer's acceptance of a seller counter; an administrative acceptance MUST be kept with its administrator as author. Both MUST keep the peer messages they sent or received and the authority records they receive.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the proof headers and exact body before committing

#### Scenario: The seller accepts the buyer's opening

- **WHEN** a seller accepts a buyer's opening offer with no counter
- **THEN** the seller's store keeps the buyer's signed opening request with its exact bytes

#### Scenario: An administrator accepts

- **WHEN** an administrator accepts a negotiation on the seller's behalf
- **THEN** the store keeps the buyer's signed message the acceptance answered and records the administrator as the accepting author

### Requirement: Envelopes are captured at the signed transport boundary

Each party MUST capture its commitment envelopes through an injected envelope-capture seam at the signed transport boundary, which carries the exact bytes and verification context to the party's evidence store before commitment.

#### Scenario: The buyer's transport verifies an acceptance

- **WHEN** the buyer's signed transport verifies the seller's acceptance and returns its parsed payload
- **THEN** the seam has already passed the proof headers, exact body and verification context to the buyer's store

### Requirement: Evidence outlives the deal and its cases

Records MUST be kept until the Agreement's `dispute_window_seconds` after the latest of the deal's delivery end and physical recovery, the last payout of every part as the party observes it, and the close of every case on the deal. The storefront MUST observe through `watch`; the buyer MUST prune only through a command that reads each deal first. An accepted negotiation never committed MUST be kept for the same window after its acceptance expires.

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

A VM or bare-metal seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain and find commitments a buyer never reported.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** the reconciliation pass finds the commitment and the seller serves or reverses it
