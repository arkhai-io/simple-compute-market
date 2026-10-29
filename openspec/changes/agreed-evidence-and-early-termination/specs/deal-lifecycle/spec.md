## ADDED Requirements

### Requirement: Payment events are per part

A payment event MUST be read from the payment authority the committed agreement names, and MUST record what happened to one part of the deal. It MUST carry `negotiation_id`, `commitment_ref`, `part`, `kind`, `actor`, `at`, `amount` where it moves money, `cause`, the `case_ref` of the case that caused it if any, the `extension_ref` an `extend` opened or a `lift` ended, `sequence`, and the authority's record reference. The lifecycle layer MUST treat the commitment reference as opaque.

#### Scenario: A reverse is recorded

- **WHEN** the payments service records a partial `reverse` of a hosted deal's `once` part
- **THEN** the seller's `watch` yields it with the part, the amount, the actor, the authority's sequence number, and its record reference

### Requirement: Disputes are per agreement and separate from payment

A case MUST be filed about an agreement, not a part, with the dispute authority its `adjudication.dispute` names. Dispute events (filed, appended, ruled, closed) MUST carry the case reference and be read from that authority's record, whose sequence is per agreement across its cases and whose entries a party MUST verify against the Agreement's `adjudication.dispute.record_key` before acting on them. A transaction MAY have any number of cases. The payment adapter MUST NOT file or decide cases.

#### Scenario: Two cases on one deal

- **WHEN** a buyer files a case, it is ruled, and later files a second case on the same deal
- **THEN** both cases are recorded against the agreement, each with its own outcome

### Requirement: Only the dispute authority acts on a case

A party's dispute adapter MUST communicate only with the agreement's dispute authority, and MUST only file, append and read. A filing's or append's outcome MUST be the dispute authority's response; it MUST NOT be a payment authority response passed through. A party's adapters MUST NOT send a case's `extend` or `lift` or apply its outcome. Lifecycle events within the deal's terms, such as an entitled stop, MUST be applied by the party directly at the payment authority.

#### Scenario: A filed case requests a reverse

- **WHEN** a buyer files a case requesting a partial reverse
- **THEN** the buyer's dispute adapter sends nothing to the payment authority, and any reverse is recorded with the dispute authority as actor

#### Scenario: The authority cannot complete an extension

- **WHEN** a buyer files a case and the dispute authority's `extend` fails at the payments service or misses the authority's deadline
- **THEN** the buyer receives the dispute authority's own error or pending result, and the buyer half reports no payments-service response as the filing's outcome

### Requirement: An outcome is a list of per-part effects

A ruling's outcome MUST be a list of consequences, each a payment effect on one part (reverse an amount of a payment part, award an amount of a bond, stop a `rate` part at its ruled effective time with stated treatment) or a delivery end at *T*. The storefront MUST send an outcome's delivery end, read through `watch`, to end service. An outcome without a delivery end MUST leave the term running.

#### Scenario: A ruling discounts a deal

- **WHEN** a ruling reverses a quarter of a hosted deal's held `once` payment and has no delivery end
- **THEN** the payment authority records one partial `reverse` by the dispute authority with the case reference, and the lease is unchanged

### Requirement: Requests are intents or interface requests

A case's requested outcome MUST be either a deal-level intent SCM issues, including `buyer_end(at)` but not the payment command `exceptional_end(at)`, or an interface request the dispute adapter built or validated. The dispute adapter MUST map an intent into its interface's request or reject it as unsupported. The generic lifecycle kits MUST NOT contain any interface's request vocabulary, and generic lifecycle callers MUST NOT compute per-part effects for a case request.

#### Scenario: A buyer requests a refund for an outage

- **WHEN** a buyer files a case requesting a refund of the share of its deal lost to an outage
- **THEN** the dispute adapter builds the interface request, and the buyer half sends it with no per-part amounts of its own

#### Scenario: An interface has no buyer-end request

- **WHEN** a buyer issues `buyer_end(at)` and the dispute interface defines no such request
- **THEN** the dispute adapter rejects it as unsupported before contacting an authority

### Requirement: Outcome effects are acted on once

The storefront MUST read a ruling's effects from the dispute authority's record by their stable IDs and applied states, and MUST act on each effect at most once, whether the record shows it partly or wholly applied.

#### Scenario: A ruling is read while partly applied

- **WHEN** `watch` yields a ruling with a reverse and a delivery end, of which only the reverse is shown applied, and later the same ruling with both applied
- **THEN** end service receives the delivery end once

### Requirement: Peer messages are hints until the authority confirms them

A peer message (`commit`, `hint`, `end_delivery`) MUST be buyer-to-seller and MUST be kept as evidence. `commit` and `hint` MUST NOT change lifecycle state until a read of the authority confirms what they report.

#### Scenario: A forged hint arrives

- **WHEN** a seller receives a `hint` that the buyer acted, and the authority's record shows no such event
- **THEN** the seller keeps the hint as evidence and continues service unchanged

### Requirement: A buyer's end-delivery request is acted on directly

The storefront MUST act on buyer-authenticated end_delivery at its durable receipt time without an authority read, reject supplied at, and preserve receipt on same-key retry. Its signed response MUST state receipt, recorded end and physical progress, not claim queued teardown released. It MUST journal required cooperative payment actions atomically with receipt. Compute deals without adapters MUST allow surrender; outside-settlement stages MUST refuse it.

#### Scenario: A buyer tries to backdate surrender

- **WHEN** a buyer served until noon sends its first end_delivery with at 10:00
- **THEN** the route rejects the supplied field, signs no historical end, and a valid request without at records the storefront's receipt time

#### Scenario: A once-only buyer ends delivery

- **WHEN** the accepted buyer sends `end_delivery` for a committed `once`-only deal
- **THEN** delivery ends without a payment stop or automatic cancellation refund

#### Scenario: A retry finds teardown in progress

- **WHEN** the buyer repeats an acknowledged `end_delivery` while the site is tearing down
- **THEN** the response finds the same recorded end and reports current progress rather than released capacity


### Requirement: The end-delivery acknowledgement is signed by the Agreement's seller

The storefront MUST sign its response to `end_delivery` with the version 2 response signature under the Agreement's `seller` principal, binding the request identity, status, timestamp and body, so that the buyer's signed request and that response verify against the Agreement alone.

#### Scenario: A case export carries an acknowledgement

- **WHEN** the buyer exports its end request and the storefront's response
- **THEN** both signatures verify against the Agreement's buyer and seller principals, and the response binds the storefront's receipt rather than a buyer-asserted historical instant

### Requirement: Adapters translate deal commands into per-part events

A mechanism adapter MUST translate each deal-level command into the events of the parts it affects, and MUST send the authority only per-part events. A part MUST be offered only the events its shape supports; a `once` part has no stop event.

#### Scenario: A buyer tries to stop a once-only deal

- **WHEN** a buyer submits an early end on a hosted deal whose only part is `once`
- **THEN** the outcome is `rejected`, naming the part shape, and no authority is contacted

#### Scenario: A reverse names a part

- **WHEN** a seller submits `reverse` of an amount on a hosted deal
- **THEN** the adapter sends one `reverse` event naming the `once` part and that amount

### Requirement: Payment adapters act only through explicit mandate entries

The payment-adapter protocol MUST send a stop only under a stop entry the mandate states for that account, and a reverse only under the reverse authority. It MUST NOT assume an implicit rule about whose favour an action serves, waive a payer's notice, or release held money early. Unsupported contract capabilities MUST reject before I/O; they MUST NOT invent an entitlement or dispute. The dispute authority MUST act through its own entries.

#### Scenario: A stop has no entry

- **WHEN** the adapter is asked to send a stop for which the mandate states no entry for the sender
- **THEN** it rejects before I/O rather than sending it or changing a priced entitlement

#### Scenario: Several entries are not vendored

- **WHEN** a spot seller must hold both its notice entry and its restitution entry on one part and the vendored contract allows one stop entry per account per part
- **THEN** the seller's immediate stop is unavailable and its emergency exit waits out its notice

### Requirement: Lifecycle terms are part of the selected option

A settlement option MAY carry `adjudication` (`version`, `dispute`, `dispute_window_seconds`, `case_hold_max_seconds`), `early_termination` (`version`, `entitlements` keyed by `payer` or `payee` with `notice_seconds` and `settles_through`, `max_term_seconds`, term-end `settles_through`), and `bond` (`version`, `amount`, reserved until a mechanism can hold a seller-funded stake) in its `params`. The shared codec MUST decode them, so they are part of the Agreement bytes and the option ID.

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

`max_term_seconds` MUST equal the Agreement's `duration_seconds`. Seller servicing-budget diagnostics MUST NOT introduce another notice or publication/acceptance refusal. `exposure_seconds` and `stop+exposure` MUST be rejected as retired codec values.

#### Scenario: Reserve is below the servicing budget

- **WHEN** a storefront polls every 290 seconds with a 60-second teardown budget and the seller chooses a 300-second reserve
- **THEN** it warns about the budget without inventing a paid tail or stopping lifecycle loops

#### Scenario: Maximum term disagrees with the Agreement

- **WHEN** an accepted Agreement's `duration_seconds` differs from its option's `max_term_seconds`
- **THEN** the buyer refuses to commit

### Requirement: Entitlements are the stop authorities

The adapter MUST derive entitled stop entries and the option's dispute authority on stoppable parts. Only the dispute authority MAY use its entry for outcomes. The adapter MUST also add the seller's restitution entry `{account: seller, notice: PT0S, partialPeriod: returned}` to every part's stop authorities, visible to the buyer's mandate check and not an entitlement. No early_termination MUST mean no entitled stop entries. Builders MUST refuse terms their mechanism cannot realize, including unsupported seller-funded bonds.

#### Scenario: An on-demand option is derived

- **WHEN** an option's `early_termination` has a `payer` entitlement only
- **THEN** the payer and dispute authority have the derived stop entries, the seller holds only its restitution entry and no payee notice entry, and the mandate does not enforce that the seller will not preempt

### Requirement: Each party has one priced stop notice

The adapter MUST carry each party's entitlement `notice_seconds` unchanged into its stop-authority entry beside `partialPeriod`. It MUST NOT add another tail. The dispute authority's notice MUST be zero and its stop entry MUST use partialPeriod chosen, requiring event-supplied treatment.

#### Scenario: A payer's notice is zero

- **WHEN** the selected payer entitlement has zero notice
- **THEN** its mandate stop authority has zero notice regardless of the seller's polling or teardown budget

### Requirement: Started-period treatment is a committed payment term

The codec MUST map `settles_through` values `started_period`, `last_boundary`, `stop` to payments `partialPeriod` values `charged`, `returned`, `prorated` respectively. Publication and buyer acceptance MUST refuse values the vendored contract cannot express. SCM MUST NOT replace an entitled stop's committed treatment with a storefront refund; seller self-correction uses its restitution entry.

#### Scenario: Returned treatment is not expressible

- **WHEN** a spot option names payee `last_boundary` but the vendored contract supports only charged periods
- **THEN** publication and acceptance refuse it; interim spot offers must explicitly name `started_period` for both parties

#### Scenario: Stop authorities use one notice

- **WHEN** an entitlement has `notice_seconds: 0` and `settles_through: started_period`
- **THEN** its stop entry has zero notice and charged treatment, with no exposure tail

### Requirement: Term ends carry their own partial-period treatment

The sole term-end carrier MUST be early_termination.settles_through, distinct from entitlements. The adapter MUST map it to rate end.partialPeriod through the stop-authority mapping. Compute presets MUST use last_boundary/returned and fail closed if unsupported; interim charged ends MUST disclose started_period. No mechanism-specific field MAY duplicate it.

#### Scenario: A rate end is not a billing boundary

- **WHEN** activation starts rate billing after the Agreement start and the absolute term end falls within a billing period
- **THEN** the compute preset's `end.partialPeriod` is returned, so billing ends at the last boundary without running past the agreed maximum
- **AND** publication and acceptance refuse that preset until the vendored contract expresses it

### Requirement: The dispute window sets the earliest payout

Each payment adapter MUST derive holds under which each amount a part holds pays out no earlier than the part's end plus `adjudication.dispute_window_seconds`. A prepaid `once` part MUST end at the Agreement term end; a setup `once` part at activation; a rate part at its stop or term end. The window MUST NOT be shorter than the dispute authority's advertised minimum. SCM MUST NOT refuse a filing for being after the window; that is the dispute authority's policy.

#### Scenario: A once deal's hold is derived

- **WHEN** a hosted mandate is derived for a deal whose term ends at 13:00 with a one-day window
- **THEN** its `once` part has `end` 13:00 and hold `{afterStop: P1D}`, so it pays out no earlier than 13:00 the next day

#### Scenario: A setup part ends at activation

- **WHEN** a deal activates with a setup `once` part and a one-day dispute window
- **THEN** setup pays out no earlier than one day after activation, independently of the maximum running term
- **AND** setup publication is refused until the vendored contracts express its activation-anchored end

#### Scenario: A buyer files after the window

- **WHEN** a buyer files a case after the window while another case holds the deal's `once` part
- **THEN** the buyer half sends the filing to the dispute authority and reports the authority's answer

### Requirement: Protection is what the authority reports

The halves MUST report a filing's per-part protection as the dispute authority states it, and MUST treat a part as protected by a case only while the payment authority's record shows that case's open extension on it.

#### Scenario: Payout wins against the extension

- **WHEN** a buyer files a case moments before a `once` hold pays out, and the dispute authority answers that the part is `not_held` because it paid out
- **THEN** the buyer half reports `accepted` with the case reference and the part `not_held`, paid out

#### Scenario: A held part shows its extension

- **WHEN** the authority answers that a part is `held` with an extension ref
- **THEN** the seller's `read` shows that open extension on the part, and `list` shows the deal with an open extension

### Requirement: A filing's outcome is the authority's answer

A `dispute` MUST be `accepted` with the case reference and each part's status, `held` with its extension ref or `not_held` with the authority's reason (paid out or reversed), once the authority has answered for every part. It MUST be `rejected` only when the dispute authority refuses the filing, and otherwise `pending` or `unknown` until the case is read.

#### Scenario: Parts differ

- **WHEN** a case is filed on a deal with two `once` parts, one still held and one already paid out
- **THEN** filing returns `accepted` with the first part `held` with its ref and the second `not_held`, paid out

#### Scenario: A part was wholly reversed

- **WHEN** a case is filed after an earlier ruling reversed a `once` part in full
- **THEN** filing returns `accepted` with that part `not_held`, reversed, and does not wait for an extension on it

### Requirement: A late case moves no paid-out money

A late case MAY be recorded and ruled, and its outcome MAY end delivery. An outcome MUST act only on money still held.

#### Scenario: A late case ends delivery

- **WHEN** a buyer files a case after the `once` hold has paid out, and it is ruled with a delivery end
- **THEN** filing returned `accepted` with every part `not_held`, the storefront ends delivery through end service, and no payment effect is applied

### Requirement: Open extensions are observed per ref

`read` and `watch` MUST report each open extension on a part by its `ref` and case, and MUST show a part held while any extension on it is open. A `lift` MUST close only the extension its `ref` names in SCM's view.

#### Scenario: Two cases overlap

- **WHEN** case A and case B each hold a deal's `once` part, and A's `lift` is recorded after B's `extend`
- **THEN** `read` shows B's extension still open and the part still held

### Requirement: Case holds are capped by terms

Mandate derivation MUST carry `case_hold_max_seconds` into each part's maximum extension, `null` when the term is `null`.

#### Scenario: A bounded case hold is derived

- **WHEN** a hosted mandate is derived from an option with `case_hold_max_seconds: 604800`
- **THEN** each part's `maxHoldExtension` is 604800 seconds

#### Scenario: An unbounded case hold is derived

- **WHEN** a hosted mandate is derived from an option with `case_hold_max_seconds: null`
- **THEN** each part's `maxHoldExtension` is `null`

### Requirement: Only the dispute authority extends and lifts

Every derived mandate MUST authorize `extend` and `lift` for the agreement's dispute authority only, the account its `adjudication.dispute` names.

#### Scenario: A mandate's extend authorities are derived

- **WHEN** a hosted mandate is derived for a deal
- **THEN** its `extend` authorities list only the dispute authority's account, and neither the payer nor the payee

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

### Requirement: An append to a closed case is skipped

When the authority confirms a case closed before the seller's journaled append lands, the journal MUST record the append as skipped for a closed case, keep the local evidence, and let observation continue. An append acknowledged before closure MUST keep its acknowledgement.

#### Scenario: A case is filed and closed while the storefront is down

- **WHEN** a buyer's case is filed, ruled and closed while the storefront is down
- **THEN** after restart the seller's append is journaled as skipped for a closed case, the evidence stays in the store, and the ruling is still acted on

#### Scenario: The case closes during the append

- **WHEN** an append was acknowledged and the case then closes before the journal records the acknowledgement
- **THEN** a retry with the same idempotency key returns the original acknowledgement, and the journal records the append done

### Requirement: Filing is not a delivery ruling

SCM MUST NOT depend on mechanical rulings. Filing a case MUST NOT itself change delivery; only a verified ruling's delivery end MAY do so. A seller exceptional end MUST NOT be filed as a case.

#### Scenario: A filing is not ruled

- **WHEN** a buyer's case remains in triage without a ruling
- **THEN** filing alone changes neither the lease nor payment state in SCM

### Requirement: A seller's exceptional end is a payment-adapter command

The seller half MUST journal exceptional_end(at) with a delivery end and send it only to its payment adapter; the payments vocabulary MUST NOT contain an exceptional-end event kind or field, and the cause MUST stay in end service's record and the evidence store. The adapter MUST translate it into ordinary payee events: `stop {part}` per rate part under the seller's `PT0S`/returned restitution entry, and `reverse {part, amount}` for earnings since at and each once part's unserved time share, with amounts it computes. Setup MUST reverse all if undelivered, none after activation. Future at MUST refuse; unknown effects MUST resolve before retry.

#### Scenario: An administrator ends a once-only deal

- **WHEN** the seller administrator issues exceptional_end(now) for a hosted once-only deal
- **THEN** end service records the attributed delivery end and the payment adapter reverses its unserved share with stable keys, without filing a case or awaiting a ruling

#### Scenario: Hardware fails on an on-demand deal

- **WHEN** the seller's hardware fails on a rate deal whose seller holds only the restitution entry
- **THEN** the adapter sends `stop {part}` under that entry and `reverse` events for the amounts it computes, and the payments service receives no cause or exceptional-end field

#### Scenario: Hardware fails on a spot deal before several entries exist

- **WHEN** the seller's hardware fails on a deal whose seller holds a notice entry and the contract allows one stop entry per account per part
- **THEN** the seller's stop waits out its notice and the adapter reverses the amounts it computes

### Requirement: The seller corrects ends its terms do not entitle

For an unentitled site withdrawal or failed/never-started delivery, end service MUST journal `exceptional_end(at)` through the payment adapter at the actual end. Never-delivered timing MUST follow "Never-delivered correction has a fixed non-future basis". A correlated lawful end MUST NOT create a second seller fault; an established earlier failure MUST remain correctable.

#### Scenario: A withdrawal is reported late

- **WHEN** a site reports at 16:01 that service ended at 14:00
- **THEN** the seller journals exceptional_end(14:00) through its payment adapter with no mediation filing

#### Scenario: An entitled end needs no self-penalty

- **WHEN** verified buyer stop, terms end or ruling causes admission refusal
- **THEN** that refusal creates no seller-failure self-correction

### Requirement: Never-delivered correction has a fixed non-future basis

End service MUST fix min(accepted start, failure-observation time) with never-delivered evidence. If accepted start is ahead, it MUST journal now but act at that start with at equal to start. Otherwise it MUST submit at the fixed minimum basis. It MUST NOT future-date the command, recompute on retry, or resume delivery.

#### Scenario: Failure precedes accepted start

- **WHEN** a seller failure is observed at 09:00 for an accepted 10:00 start
- **THEN** end and payment intent are recorded atomically at 09:00, submission waits until 10:00 with at 10:00, and restart preserves the same key without delivery

### Requirement: Cause classification is owned by end service

End service MUST distinguish lawful buyer/authority/terms/ruling ends from unentitled seller failures and correlate site reports to controlling requests. Admission refusal alone MUST NOT create a seller penalty or erase an established earlier seller failure. It MUST expose pending classification and payment-action journaling hooks for servicing consumers.

#### Scenario: A site report confirms a lawful end

- **WHEN** a site report is correlated to an already recorded lawful authority end
- **THEN** end service retains both evidence sources without inventing seller fault

### Requirement: Self-correction payment actions survive a crash

End service MUST journal required self-correction with its final request and stable per-operation identity. The adapter MUST resolve unknown effects from verified payment records before replay. It MUST NOT duplicate reversals; absent sufficient prior-effect evidence it MUST report repair required, not financial completion.

#### Scenario: Replay after restart

- **WHEN** the storefront restarts with an unacknowledged stop or reverse sent for an exceptional end
- **THEN** it resolves the same operation key at payments before retrying and files no mediation case

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

On VM and bare-metal deals the buyer half MUST offer `submit` and `read(negotiation_id)` without the caller branching on mechanism. `read` MUST return the deal's lifecycle state, each part's open extensions, its authority events and its cases where an adapter exists, and MUST return the storefront's delivery progress and obtained signed site reports independently.

#### Scenario: A buyer reads a deal with no lifecycle adapter

- **WHEN** a buyer reads an Alkahest deal through the buyer half
- **THEN** the authority view is `rejected`, naming the mechanism, and the storefront delivery view still returns recorded end progress and any obtained site-signed reports

### Requirement: A read without an adapter still shows delivery

When the mechanism has no adapter the buyer half's `read` MUST return the authority view explicitly `rejected`, naming the mechanism, without suppressing the delivery view or inventing authority state.

#### Scenario: An Alkahest deal is read

- **WHEN** the buyer reads a deal whose mechanism has no lifecycle adapter
- **THEN** the authority view is `rejected` naming the mechanism, and delivery progress and site reports are returned

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

Dispute adapters MUST resolve through a dispute adapter table the domain composition fills, keyed by `adjudication.dispute.interface`. The lifecycle kits MUST receive both adapter tables injected and MUST NOT import a payment or dispute kit, and a dispute kit MUST NOT name a payment mechanism. An interface with no adapter MUST be `rejected` before any request. Advertised compatibility MUST be checked only before commitment, never on a committed deal's commands.

#### Scenario: A deal names an interface with no adapter

- **WHEN** a party files a dispute on a deal whose `adjudication.dispute.interface` has no entry in the dispute adapter table
- **THEN** the outcome is `rejected`, naming the interface, and no authority is contacted

### Requirement: Dispute authorities are named per deal

The Agreement's `adjudication.dispute` MUST be the only source of a committed deal's dispute authority. A role's credential for an authority MUST be bound by the authority's identity (`interface`, `origin`, `account`, `record_key`), independently of preference. Changing preferences, registry recommendations or advertisements MUST NOT affect accepted deals. A running deal whose authority has no bound credential MUST be shown as repair required in `list`.

#### Scenario: A seller stops offering an authority

- **WHEN** a seller marks an authority not offered while a deal under it is running
- **THEN** new options do not name it, and the running deal's `watch` and appends still reach it with the credential bound to its identity

#### Scenario: An authority's credential is missing

- **WHEN** a running deal's authority has no bound credential
- **THEN** `list` shows the deal as repair required

### Requirement: A role's authorities are its entries and its registry's recommendations

A role's authorities MUST be its own `[[Dispute]]` entries in preference order, followed by the authorities its registry's descriptor recommends unless `use_registry_dispute_authorities` is false. Each authority MUST carry a copy of its advertisement, which publication and buyer checks read.

#### Scenario: A buyer uses its registry's recommendation

- **WHEN** a buyer with no `[[Dispute]]` entries selects from a registry whose descriptor recommends one authority
- **THEN** it accepts options naming exactly that authority and refuses others

### Requirement: A buyer accepts an authority only on an exact identity match

A buyer MUST accept an option's authority only when its `interface`, `origin`, `account` and `record_key` equal one authority in its list, and its `params` equal that authority's or pass the interface's acceptance check.

#### Scenario: A seller pairs the real account with its own origin

- **WHEN** an option names an accepted authority's account with a different origin or record key
- **THEN** the buyer refuses the option, naming the mismatched field

### Requirement: With no authorities, no hosted options

With no authorities, a storefront MUST publish no hosted option and a buyer MUST accept none, and each MUST report it at startup.

#### Scenario: No authority is available

- **WHEN** a storefront has no `[[Dispute]]` entries and its registry recommends none
- **THEN** it publishes no hosted option and reports why at startup

### Requirement: Lifecycle servicing is composed by the compute domains

The VM and bare-metal roles MUST compose the buyer half, the seller half, both evidence stores and `watch`. API-credit roles MUST compose the authority list they need to check options at publication, selection and the mandate check, and are not required to compose the halves, the evidence stores or `watch`.

#### Scenario: An API-credit storefront publishes a hosted option

- **WHEN** an API-credit storefront publishes an `arkhai.payments.v1` option
- **THEN** the option carries `adjudication` checked against the storefront's authority list, and the storefront runs no lifecycle loop

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

VM and bare-metal storefronts MUST expose seller `submit/read/list` under the administrator-principal contract and buyer `commit/hint/end_delivery` under the negotiation's buyer principal, keyed by negotiation ID with signed responses. Buyer authority commands MUST NOT be relayed. VM admin interrupt MUST submit the notice stop when the accepted option entitles the payee, and journal the exceptional-end payment command otherwise.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route uses an entitlement

- **WHEN** an administrator interrupts a spot deal whose accepted option grants the payee a stop entitlement
- **THEN** the route submits the notice stop through the seller half and delivery follows the authority's effective stop, without a self-penalty filing

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through the VM admin route
- **THEN** the route journals an attributed delivery end and exceptional_end(now) payment intent through the seller half; end service drives the lease without awaiting a dispute ruling

#### Scenario: Another principal ends delivery

- **WHEN** a principal other than the accepted negotiation's buyer sends `end_delivery`
- **THEN** the storefront rejects it without making a final request or contacting the site

### Requirement: End service keeps the earliest final request

End service MUST take attributed final requests from watched authority stops, dispute delivery rulings, verified site end reports and local delivery decisions, including buyer surrender and terminal settlement. It MUST retain the earliest T. Local decisions MUST NOT claim payment completion; journaled cooperative actions move money only at the payment authority.

#### Scenario: A buyer tears down bare metal

- **WHEN** a bare-metal buyer sends `end_delivery` through the storefront
- **THEN** end service terminates the lease with the buyer as actor, the request is kept as evidence, and no payment command is sent

#### Scenario: A VM buyer ends delivery

- **WHEN** a VM buyer sends `end_delivery`
- **THEN** end service terminates the lease with the buyer as actor and the storefront's signed response acknowledges the end at that time

### Requirement: The recorded end retains cause and source

End service MUST durably keep final requests with stable source identities, actors, causes, instants and evidence references, including superseded requests, and MUST expose the earliest request's attribution and physical progress through lifecycle reads. Earlier evidence received after teardown begins MUST NOT resurrect delivery or duplicate physical effects; financial correction MUST use the dispute authority, not a storefront financial-end record.

#### Scenario: A site reports an earlier end late

- **WHEN** a site report for 12:00 arrives after a 12:10 local end has already begun teardown
- **THEN** the recorded earliest end becomes 12:00 with the site's cause, both source records remain, teardown is not restarted, and any required `exceptional_end(12:00)` is journaled

#### Scenario: Two causes have the same instant

- **WHEN** two final requests name the same earliest instant
- **THEN** both source records remain and replay selects the same attribution without changing the end instant

### Requirement: Site end reports are kept and returned to the buyer

The storefront MUST authenticate a `lease_ended` report against the reservation's configured site peer, deduplicate by event identity, retain the exact signed bytes, and submit a final request with its instant and cause. The buyer-authenticated lifecycle read MUST return those bytes and proof verbatim beside end-service attribution and physical progress.

#### Scenario: A report is pushed twice and then read

- **WHEN** the site retries a signed report after losing its acknowledgement
- **THEN** the storefront records one source request and the buyer reads the site's original signed bytes, not a storefront reconstruction

#### Scenario: A push is lost

- **WHEN** the storefront's next lease read recovers a signed `lease_ended` report it has not received
- **THEN** it keeps and acts on that report as it would the authenticated push

#### Scenario: The site reports release failure

- **WHEN** a valid report records an intended end and `release_failed`
- **THEN** the end is recorded with that cause, but status still reports incomplete physical recovery and listings do not reopen

### Requirement: Site end reports are recoverable and not authority records

A `lease_ended` report whose push was missed MUST be recoverable from the authenticated lease read. Site reports MUST NOT be treated as payment authority records or proof of capacity return.

#### Scenario: A report is not a stop

- **WHEN** the storefront holds a site-signed `lease_ended` report for a hosted deal
- **THEN** it sends no payment command because of the report alone, and capacity stays unavailable until the release guard allows it

### Requirement: End service terminates or truncates, and journals each effect

When *T* is now or past, end service MUST terminate the lease; otherwise it MUST truncate it to *T* at one-second precision or finer. Each effect MUST be journaled with a stable operation identity and retried under that identity until done. A shortfall in the seller's servicing budget at runtime MUST only warn and MUST NOT stop the lifecycle loops.

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

### Requirement: Neutral delivery decisions delegate payment interpretation

kit/deal-servicing MUST own authorize_delivery for commit, dispatch, start and disclose with durable allow/refuse/pending, reason, operation ID and evidence references. The foundation payment-adapter protocol MUST expose authorize(phase, evidence) and start_billing(operation_key, activated_delivery_evidence). Generic servicing MUST NOT interpret hosted part fields; once-only adapters MUST validate commitment evidence and use no-op billing start.

#### Scenario: A financial decision is pending

- **WHEN** the injected adapter cannot resolve authority evidence for dispatch
- **THEN** delivery stays pending and a later allow still cannot override end-service admission

### Requirement: Billing-start intent and evidence have one owner

End service MUST journal billing-start key and activated-delivery evidence before I/O, using delivery's stable operation key. Delivery MUST retain only an intent reference. The versioned secret-free envelope MUST bind negotiation, commitment, resource identities and validated ready-evidence digest/projection. Activation MUST precede rate start; unknown effects MUST resolve by read/same-key retry before disclosure.

#### Scenario: A once-only delivery activates

- **WHEN** validated activation evidence reaches the once-only payment adapter through end service
- **THEN** billing start is a no-op and the delivery record retains only the end-service intent reference

### Requirement: Admission shares the end-service transaction and revision

End service MUST provide `admit(negotiation_id, phase, expected_revision) → admitted | ended(T), revision` using the caller's storefront database session. A durable revision/CAS MUST order reservation, dispatch, activation and credential authorization against end recording. Stale revisions MUST retry admission without authorizing effects.

#### Scenario: A credential authorization races an end

- **WHEN** an end is recorded after a delivery worker reads the revision but before it authorizes credentials
- **THEN** its stale admission fails and the worker retries against the recorded end, including after restart

### Requirement: End recording and required payment action are one operation

End service MUST provide `record_end(final_request, payment_intent?)`, atomically journaling the final request and any required cooperative payment action in the caller's storefront transaction. An earlier buyer, terms or ruling end MUST NOT cause a seller self-penalty merely because admission is refused.

#### Scenario: A crash separates recording from payment submission

- **WHEN** the storefront crashes after `record_end` commits but before submitting its required payment action
- **THEN** restart replays the same intent under its stable operation key; neither half is lost

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded. The buyer's store MUST be the buyer-side lifecycle kit's, under a root the buyer composition passes beside the buyer profile, and the kit MUST NOT depend on core buyer; the storefront's MUST be the servicing kit's.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

### Requirement: Each party keeps its commitment envelopes and authority records

The buyer MUST keep the seller's signed acceptance with its proof headers and exact body before committing. The seller MUST keep the buyer's signed message the agreement rests on: the buyer's opening or counteroffer the seller accepted, or the buyer's acceptance of a seller counter; an administrative acceptance MUST be kept with its administrator as author.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the proof headers and exact body before committing

#### Scenario: The seller accepts the buyer's opening

- **WHEN** a seller accepts a buyer's opening offer with no counter
- **THEN** the seller's store keeps the buyer's signed opening request with its exact bytes

#### Scenario: An administrator accepts

- **WHEN** an administrator accepts a negotiation on the seller's behalf
- **THEN** the store keeps the buyer's signed message the acceptance answered and records the administrator as the accepting author

### Requirement: End service's records are retained as evidence

Both parties MUST keep the peer messages they sent or received, including the signed end-delivery acknowledgement, the authority records they receive and the site-signed end reports they obtain.

End service's final requests and effect journal MUST be retained under the same rule as the commitment envelopes, and site reports MUST be kept as evidence rather than authority records.

#### Scenario: The journal outlives the deal

- **WHEN** a deal's evidence is retained
- **THEN** its final requests and effect journal are retained with it

### Requirement: Envelopes are captured at the signed transport boundary

Each party MUST capture its commitment envelopes through an injected envelope-capture seam at the signed transport boundary, which carries the exact bytes and verification context to the party's evidence store before commitment.

#### Scenario: The buyer's transport verifies an acceptance

- **WHEN** the buyer's signed transport verifies the seller's acceptance and returns its parsed payload
- **THEN** the seam has already passed the proof headers, exact body and verification context to the buyer's store

### Requirement: Evidence outlives the deal and its cases

For a deal with `adjudication` and a lifecycle adapter, records MUST be kept until the Agreement's `dispute_window_seconds` after the latest of the deal's delivery end and physical recovery, the last payout of every part as the party observes it, and the close of every case on the deal. An accepted negotiation never committed MUST be kept for the same window after its acceptance expires.

#### Scenario: A long deal passes the window

- **WHEN** a running deal's last authority event is older than the dispute window
- **THEN** its evidence records are kept

#### Scenario: A case stays open

- **WHEN** a case on an ended deal remains unresolved past the window
- **THEN** its evidence records are kept until the window after its resolution

#### Scenario: A ruling ends a deal early and a case follows

- **WHEN** a ruling ends a hosted `once` deal mid-term, and the buyer files a case contesting its amount while the remaining payment is still held
- **THEN** both parties still hold their commitment envelopes and authority records, since the last payout has not happened

### Requirement: Pruning observes payouts first

The storefront MUST observe payouts and case closes through `watch`; the buyer MUST prune only through a command that reads each deal first.

#### Scenario: A buyer prunes

- **WHEN** a buyer runs the prune command
- **THEN** it reads each deal before deleting any of its records, and deletes nothing for a deal it cannot read

### Requirement: Evidence without lifecycle terms is kept

Records of a deal with no lifecycle terms or no adapter MUST be kept until a pruning path for them is specified.

#### Scenario: An Alkahest deal's envelopes are kept

- **WHEN** a VM deal settled through Alkahest, or an accepted Alkahest negotiation never committed, is older than any dispute window
- **THEN** its captured envelopes remain, and no prune deletes them

### Requirement: A dispute is one case payload

A dispute MUST be one exportable case: commitment reference, exact Agreement, terms, claim, requested outcome and ordered evidence. Hosted cases MUST carry that Agreement for verification against mandate deal hash regardless of deposit. Each evidence item MUST carry kind, producer, time, digest and exact original bytes or the authority's signed record.

#### Scenario: Neither party deposited an Agreement attachment

- **WHEN** a buyer files a hosted case and neither party attached the Agreement at payments
- **THEN** the adapter sends the exact Agreement in the case for verification against the committed mandate's deal hash, without requiring seller cooperation or an attachment

#### Scenario: A buyer files a dispute

- **WHEN** a buyer files a dispute through the buyer half
- **THEN** the case payload is built from its evidence store, and each item carries the exact bytes it received

### Requirement: Refund is a reverse command; reconciliation finds unreported commitments

A VM or bare-metal seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain and find commitments a buyer never reported.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** the reconciliation pass finds the commitment and the seller serves or reverses it
