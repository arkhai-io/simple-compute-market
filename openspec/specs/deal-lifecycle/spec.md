# Deal Lifecycle Specification

## Purpose

Define what happens after commitment: per-part payment events and holds, the agreed lifecycle terms, independent dispute authorities and their cases, end and admission journals, retained evidence, and each role's servicing of them.

## Requirements

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
- **THEN** the storefront reads the outcome through `watch`, sends end service no delivery end, and the lease keeps running

### Requirement: Requests are intents or interface requests

A case's requested outcome MUST be either a deal-level intent SCM issues, including delivery_end with either cause filed by either party, or an interface request the dispute adapter built or validated. The dispute adapter MUST map an intent into its interface's request or reject it as unsupported. Generic lifecycle kits MUST NOT contain any interface's request vocabulary, and generic callers MUST NOT compute per-part effects for a case request.

#### Scenario: A seller's failure is filed as an intent

- **WHEN** the seller half issues delivery_end(cause=payee) for a deal
- **THEN** it hands the dispute adapter the deal-level intent, and the adapter maps it into its interface's request

#### Scenario: A buyer requests a refund for an outage

- **WHEN** a buyer files a case requesting a refund of the share of its deal lost to an outage
- **THEN** the dispute adapter builds the interface request, and the buyer half sends it with no per-part amounts of its own

#### Scenario: An interface has no buyer-end request

- **WHEN** a buyer issues `delivery_end(cause=payer)` and the dispute interface defines no such request
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

The storefront MUST act on buyer-authenticated end_delivery at its durable receipt time without an authority read, reject supplied at, and preserve receipt on same-key retry. Its signed response MUST state receipt, recorded end and physical progress, not claim queued teardown released. It MUST NOT stop billing; the storefront has no authority to do so for the buyer. Compute deals without adapters MUST allow surrender; outside-settlement stages MUST refuse it.

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

### Requirement: Payment adapters send only entitled stops

The payment-adapter protocol MUST send a stop only under a stop entry the mandate states for that account, and a reverse only under the reverse authority. It MUST NOT assume an implicit rule about whose favour an action serves, waive a payer's notice, release held money early, or carry an exceptional-end event kind or field. Unsupported contract capabilities MUST reject before I/O; they MUST NOT invent an entitlement or dispute. SCM MUST leave case effects to the authority's own entries.

#### Scenario: A stop has no entry

- **WHEN** the adapter is asked to send a stop for which the mandate states no entry for the sender
- **THEN** it rejects before I/O rather than sending it or changing a priced entitlement

### Requirement: A settlement option states price, settlement and lifecycle

A settlement option MUST state its `price` (`asset`, `rates`; absent on a rateless option) and `settlement` (a `schema` naming the mechanism, its parameters flat beside it, none named `schema`), and MAY state a `lifecycle` carrying adjudication (version, dispute, dispute_window_seconds, case_hold_max_seconds), early_termination (version, payer/payee entitlements with notice_seconds/settles_through, term-end settles_through, premature_stop_penalty), `delivery_deadline_seconds` and reserved bond.

#### Scenario: A lifecycle option is encoded

- **WHEN** a seller publishes an Arkhai payments option with a one-day dispute window and a payer entitlement
- **THEN** the option carries `price`, `settlement` and `lifecycle` as three objects, `settlement.schema` names the mechanism with its parameters beside it, and `lifecycle` holds the adjudication and early_termination terms

### Requirement: The delivery deadline is the site's availability term

`delivery_deadline_seconds` MUST be a positive integer: the seconds after the later of the commitment instant and the Agreement start within which the resource is available to the buyer, as the storefront's durable `available` record. A compute option whose mechanism has a lifecycle adapter MUST carry the deadline its site enforces and omit it where the site enforces none; a default buyer MUST refuse such an option without it, unless explicitly opted out.

#### Scenario: A default buyer meets an option without a deadline

- **WHEN** a default buyer is offered a compute Arkhai payments option with no `delivery_deadline_seconds`
- **THEN** it refuses the option unless its operator has explicitly opted out

### Requirement: An option without a lifecycle adapter makes no delivery promise

An option whose mechanism has no lifecycle adapter MUST carry no `lifecycle`, and so no deadline term; its lease takes the site's own capacity safeguard, and the buyer MUST be shown that the option makes no delivery promise. The shared codec MUST decode `lifecycle` as Agreement bytes and option identity, and no settlement mechanism's model MAY own its keys.

#### Scenario: An Alkahest compute option is shown

- **WHEN** a buyer is shown a VM listing's Alkahest option
- **THEN** the option carries no `lifecycle`, and the buyer is shown that it makes no delivery promise

### Requirement: Lifecycle terms are part of the selected option

The shared codec MUST own optional lifecycle terms beside price and schema-owned settlement parameters. The canonical option ID MUST include price, settlement and lifecycle, omitting lifecycle when absent. Compute delivery deadlines MUST follow site policy and default buyer acceptance; bond MUST remain reserved until supported.

#### Scenario: A term changes the option ID

- **WHEN** a seller changes an option's dispute window and republishes
- **THEN** the option has a new option ID

#### Scenario: The delivery deadline is the site's

- **WHEN** a compute storefront publishes an option for a pool whose effective `delivery_deadline_seconds` is 1800
- **THEN** the option's `lifecycle.delivery_deadline_seconds` is 1800 and the site's activation deadline for a deal on it is the same 1800 seconds after the later of the commitment instant and the Agreement start
- **AND** a pool that enforces no deadline yields an option without the term, which the default buyer refuses

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

`case_hold_max_seconds` MUST be a nonnegative integer or `null`. A `dispute_window_seconds` or `case_hold_max_seconds` below the dispute authority's advertised minimum MUST be refused at publication and by the buyer. On a compute option, `dispute_window_seconds` MUST be at least `delivery_deadline_seconds` plus the authority's minimum window, so no `once` part pays out before non-delivery can be established and filed on; publication and the buyer MUST refuse an option failing this.

#### Scenario: A negative case hold is refused

- **WHEN** a seller configures `case_hold_max_seconds: -1`
- **THEN** publication refuses the option

#### Scenario: A zero case hold is below the minimum

- **WHEN** a seller configures `case_hold_max_seconds: 0` for an authority that advertises `null` as its minimum
- **THEN** publication refuses the option

#### Scenario: The dispute window ends before the delivery deadline can be filed on

- **WHEN** a compute option carries a one-hour dispute window, a three-hour delivery deadline and an authority advertising a one-day minimum window
- **THEN** publication refuses the option, naming the window that would let its setup part pay out before the seller could be found late, and a buyer offered it refuses it

#### Scenario: A supported shorter authority minimum still covers delivery timing

- **WHEN** an authority advertises a sixty-second minimum and a compute option has a
  six-hundred-second delivery deadline
- **THEN** publication and the buyer refuse a dispute window below six hundred and
  sixty seconds and accept that threshold when all other terms are valid
- **AND** the payment hold derives from the full accepted window, not only the
  authority minimum

### Requirement: Term values agree with the Agreement and the seller's budget

The deal's horizon is the Agreement's `duration_seconds`; `early_termination` MUST NOT carry a maximum term of its own, and every rate part's `end` MUST be `start_utc + duration_seconds`. Seller servicing-budget diagnostics MUST NOT introduce another notice or publication/acceptance refusal. `exposure_seconds` and `stop+exposure` MUST be rejected as retired codec values.

#### Scenario: Reserve is below the servicing budget

- **WHEN** a storefront polls every 290 seconds with a 60-second teardown budget and the seller chooses a 300-second reserve
- **THEN** it warns about the budget without inventing a paid tail or stopping lifecycle loops

#### Scenario: The horizon is the Agreement's

- **WHEN** two buyers accept the same recurring option at different starts
- **THEN** each Agreement carries its own `duration_seconds`, each mandate's rate part ends at its own `start_utc + duration_seconds`, and both Agreements carry the same option with the same ID

### Requirement: Entitlements are the stop authorities

The adapter MUST derive entitled stop entries and the option's dispute authority on stoppable parts. Only the dispute authority MAY use its entry for outcomes. Seller stop entries MUST exist only for entitlements, such as spot's notice entry. No early_termination MUST mean no entitled stop entries. Builders MUST refuse terms their mechanism cannot realize, including unsupported seller-funded bonds.

#### Scenario: An on-demand option is derived

- **WHEN** an option's `early_termination` has a `payer` entitlement only
- **THEN** the payer and dispute authority have the derived stop entries, the seller holds no stop entry, and the mandate does not enforce that the seller will not preempt; that is enforced by the premature-stop penalty and a buyer's case over held money

### Requirement: Each party has one priced stop notice

The adapter MUST carry each party's entitlement `notice_seconds` unchanged into its stop-authority entry beside `partialPeriod`. It MUST NOT add another tail. The dispute authority's notice MUST be zero and its stop entry MUST use partialPeriod chosen, requiring event-supplied treatment.

#### Scenario: A payer's notice is zero

- **WHEN** the selected payer entitlement has zero notice
- **THEN** its mandate stop authority has zero notice regardless of the seller's polling or teardown budget

### Requirement: Started-period treatment is a committed payment term

The codec MUST map `settles_through` values `started_period`, `last_boundary`, `stop` to payments `partialPeriod` values `charged`, `returned`, `prorated` respectively. Publication and buyer acceptance MUST refuse values the vendored contract cannot express. SCM MUST NOT replace an entitled stop's committed treatment with a storefront refund; a seller's exceptional end is a dispute filing.

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

Each payment adapter MUST derive holds under which each amount a part holds pays out no earlier than the part's end plus `adjudication.dispute_window_seconds`, a window no shorter than the authority's advertised minimum. A prepaid `once` part MUST end at the Agreement term end, a setup once part at Agreement start (effectively clamped to approval if later), a rate part at its stop or term end. SCM MUST NOT refuse a filing for being after the window; that is the authority's policy.

#### Scenario: A window shorter than the authority's minimum

- **WHEN** a seller configures a one-hour dispute window for an authority advertising a one-day minimum
- **THEN** publication refuses the option

#### Scenario: A once deal's hold is derived

- **WHEN** a hosted mandate is derived for a deal whose term ends at 13:00 with a one-day window
- **THEN** its `once` part has `end` 13:00 and hold `{afterStop: P1D}`, so it pays out no earlier than 13:00 the next day

#### Scenario: A setup part ends at the term start

- **WHEN** a deal with a setup `once` part and a one-day dispute window is approved at or after its Agreement start
- **THEN** setup pays out no earlier than one day after approval, independently of the maximum running term
- **AND** a buyer's stop before activation does not return it, and the seller's self-penalty for non-delivery does

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

SCM MUST permit late filings and report the authority's answer without promising recovery of paid-out money. It MUST send a recorded delivery end to end service even when the authority reports no money held; it MUST NOT compute or apply a financial remedy.

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

### Requirement: Respondent discovery is durable

The mediation adapter MUST consume authenticated GET /respondent?after=<cursor>&limit=n and preserve cases, next_after and has_more. SCM MUST journal respondent answers before advancing its discovery cursor, independently of deal watch. Foreign commitments MUST be skipped without local repair rows; temporarily unresolved local commitments MUST retry fairly without blocking discovery.

#### Scenario: A seller restarts before answering

- **WHEN** polling found a case but the storefront restarts before its append is acknowledged
- **THEN** restart retries its journaled answer with the same key, without losing the case

### Requirement: SCM signs matching claims or contests them

The storefront MUST compare ended_at, delivered and cause with durable available/end records. A payer claim MUST match the selected buyer end, not a superseded request. It MUST append SignedDeliveryEndClaim concurrence for a match, and contesting items otherwise, as payee account mandate.to. An append MUST contain items or concurrence. Dead or non-SCM respondents MUST remain triage cases, never a safety dependency.

#### Scenario: A cooperative seller agrees

- **WHEN** a buyer files cause=payee and the seller's durable records match the exact claim
- **THEN** the storefront signs and appends concurrence; mismatched facts instead receive contesting evidence

### Requirement: Receipts embed reusable signed claims

For selected buyer surrender, end_delivery MUST embed SignedDeliveryEndClaim(cause=payer, delivered=true) at durable receipt time, signed by Agreement.seller through its dispute adapter. An earlier selected end MUST suppress the claim and automatic payer filing. Same-key retry MUST preserve claim/proof while surrender stays selected. The buyer MUST verify/retain it and MAY later file Filing.concurrence. It MUST NOT claim the receipt attests earlier time.

#### Scenario: Payments is unreachable

- **WHEN** end_delivery returns its signed claim while the buyer's own stop is pending
- **THEN** the buyer can file receipt concurrence for the mechanical rule without a later seller response, and still reports separate stop/case progress

### Requirement: Case appends follow interface authorization

Either party MAY append evidence to its open case, repeatedly, through its half of the lifecycle interface; only the payee MAY append concurrence; a closed case takes no append, and evidence that arrives after closure is a new case the authority nets against the first. A dispute adapter MUST follow its interface's append authorization with operation-derived idempotency keys. SCM's mediation respondent MUST send items or concurrence as mandate.to and preserve the record's actor attribution. A counterparty case surfaced through watch MUST journal the seller's answer by case_ref; the dispute cursor MUST wait for that answer or confirmed closure. Authority-side append policy is external context.

#### Scenario: The seller answers a buyer's case

- **WHEN** a buyer's case on a hosted deal appears in the seller's `watch`
- **THEN** the seller appends the buyer's signed message the agreement rests on and its received peer messages from its evidence store, and the dispute record shows them under the seller

#### Scenario: The storefront crashes before appending

- **WHEN** the storefront sees a buyer's case and restarts before its append is acknowledged
- **THEN** after restart it appends with the same idempotency key, and the record shows the seller's items once

#### Scenario: The claimant adds evidence

- **WHEN** a payee claimant appends a second evidence item to its open case
- **THEN** the record shows both submissions under the payee, in order

#### Scenario: The buyer answers the respondent's contest

- **WHEN** the seller, as respondent, appends contesting evidence to a buyer's open case and the buyer then appends the site-signed `lease_ended` report it retrieved after filing
- **THEN** the record shows both under their actors, in order, and the person ruling sees the exchange in one case rather than a second case opened to rebut

### Requirement: An append to a closed case is skipped

When the authority confirms a case closed before the seller's journaled append lands, the journal MUST record the append as skipped for a closed case, keep the local evidence, and let observation continue. An append acknowledged before closure MUST keep its acknowledgement.

#### Scenario: A case is filed and closed while the storefront is down

- **WHEN** a buyer's case is filed, ruled and closed while the storefront is down
- **THEN** after restart the seller's append is journaled as skipped for a closed case, the evidence stays in the store, and the ruling is still acted on

#### Scenario: The case closes during the append

- **WHEN** an append was acknowledged and the case then closes before the journal records the acknowledgement
- **THEN** a retry with the same idempotency key returns the original acknowledgement, and the journal records the append done

### Requirement: Filing is not a delivery ruling

Filing a case MUST NOT itself change delivery; only a verified ruling's delivery end MAY do so. A seller's exceptional end MUST end delivery through the seller's own journaled attributed end, not by awaiting a ruling.

#### Scenario: A filing is not ruled

- **WHEN** a buyer's case remains in triage without a ruling
- **THEN** filing alone changes neither the lease nor payment state in SCM

### Requirement: A seller's exceptional end is a dispute filing

The seller half MUST atomically journal delivery_end {ended_at, delivered, cause: payee} with its delivery end and file through the dispute adapter. It MUST send no stop/reverse for the claim. delivered MUST reflect durable availability, false for never-delivered or past-deadline failure. Future ended_at MUST refuse; unknown results MUST resolve by stable key. Payments MUST gain no claim vocabulary.

#### Scenario: An administrator ends a once-only deal

- **WHEN** the seller administrator issues delivery_end(cause=payee) for a hosted once-only deal
- **THEN** end service records the attributed delivery end and the dispute adapter files delivery_end(cause=payee) with a stable key; the seller sends no reverse, and delivery does not await the ruling

#### Scenario: Setup returns by delivery, not by time

- **WHEN** one deal with a setup part clamped to approval ends unentitled before its resource was ever available, and another after it was available
- **THEN** the seller half files the first with `delivered: false` and the second with `delivered: true`, from durable availability whatever share of the term has passed, and sends no reverse of setup for either

#### Scenario: Hardware fails on a spot deal

- **WHEN** the seller's hardware fails on a rate deal whose seller holds a notice entry
- **THEN** the seller files delivery_end(cause=payee) as its emergency exit and sends no stop or reverse, and the payments service receives no cause or exceptional-end field

#### Scenario: An unsupported claim is triaged

- **WHEN** the dispute adapter cannot map the Agreement or the claim onto its interface's revision
- **THEN** the seller half reports repair required and sends no stop or reverse in place of the filing

### Requirement: Delivery end is one claim for either party

The dispute adapter MUST map DeliveryEndClaim {kind: delivery_end, ended_at: int Unix seconds <= now, delivered: bool, cause: payee|payer} for either filer. Its concrete schema and signed payload MUST come from the mediation kit's vendored published contract (provenance in `kit/arkhai-mediation/schema/SOURCE.md`). Separate seller-end, buyer-end and end-acknowledgement mediation kinds MUST NOT be emitted.

#### Scenario: Buyer files a seller failure

- **WHEN** a seller machine fails without reporting its stop
- **THEN** the buyer may file cause=payee without seller cooperation; an unanswered case stays triaged

### Requirement: Concurrence binds the exact Agreement and claim

SignedDeliveryEndClaim MUST contain agreement (JCS SHA-256 hex equal to mandate.deal), claim, signer Identity and SignatureProof. Valid concurrence MUST have JCS-equal case claim, signer equal to Agreement.seller and a verified proof. Filing.concurrence and Append.concurrence MUST use this contract-owned model; invalid concurrence MUST remain evidence for an operator.

#### Scenario: A signature covers another claim

- **WHEN** a buyer presents a valid seller signature over a different ended_at or Agreement
- **THEN** it is not concurrence and the case stays with an operator

### Requirement: Claim signing uses the canonical identity frame

Signing MUST use kit/identity frame_fields(["arkhai.mediation.delivery-end-claim.v1", agreement, signer.scheme, signer.identifier, str(ended_at), "true"|"false", cause]). ed25519 MUST sign those bytes; eip191 MUST personal_sign them. Clients MUST use the vendored vectors for both schemes, not a locally invented frame.

#### Scenario: Both seller identity schemes sign

- **WHEN** the same claim is signed by ed25519 and eip191 seller identities
- **THEN** each signature verifies against its mediation vector and only its Agreement seller principal

### Requirement: Mechanical claims require payee agreement and guards

SCM MUST preserve the signed authority record's ruling basis (payee_filed, payee_signed or operator) and MUST NOT infer a ruling from silence or manufacture a mechanical ruling. Its claims and concurrence MUST bind the exact Agreement and fixed end evidence; unsupported mapping or revision MUST report repair required. The authority's mechanical guards and triage policy are external context.

#### Scenario: A payee-signed buyer claim

- **WHEN** a payer files a matching seller-signed claim and the authority's signed record states a ruling with basis `payee_signed`
- **THEN** SCM preserves that basis as recorded and reports it the same whichever party filed

#### Scenario: A repeated mechanical end

- **WHEN** the seller revises a delivery_end after an earlier mechanical delivery_end ruling on the Agreement
- **THEN** the dispute adapter routes the revision to an operator under the same semantic filing identity, allocating no new operation key

#### Scenario: Respondent stays silent

- **WHEN** a claim has neither payee filing nor valid concurrence and the respondent never answers
- **THEN** SCM infers no ruling from the silence, and the case stays pending until a signed authority outcome is observed

### Requirement: Payee-caused ends return held unserved value

For cause=payee, SCM MUST file the fixed delivery-end claim and evidence with the Agreement's authority, preserve its signed outcome and forward any delivery end to end service. The filer MUST NOT compute or apply stops, unserved-share reversals or penalties; those remedies belong to the external authority.

#### Scenario: The seller files its failure

- **WHEN** the payee files delivery_end(cause=payee)
- **THEN** the seller half files the fixed claim and evidence, computes and sends no stop, reversal or penalty, and forwards to end service any delivery end the signed outcome carries

### Requirement: Setup returns by delivered for either cause

SCM MUST encode setup's once end at Agreement start and send delivered from retained availability/end evidence for either cause, not substitute site activation or elapsed time. It MUST leave setup reversal to the authority. Setup-bearing presets MUST remain disabled until a hosted dispute authority is qualified on the vendored delivery_end revision. The authority's delivered-based remedy is external context.

#### Scenario: Undelivered payer-caused end

- **WHEN** a buyer files a cause=payer claim on a deal whose resource was never available
- **THEN** SCM sends `delivered: false` from its retained availability evidence, not from site activation or elapsed time, and leaves setup's reversal to the authority

### Requirement: Payer-caused ends preserve priced stop terms

For cause=payer, SCM MUST retain accepted terms, stop outcomes and the receipt-backed claim so the authority can resolve priced notice and treatment. It MUST NOT waive notice, backdate a payment stop or compute a net remedy. SCM MUST report the authority's result separately from surrender; rate-stop execution belongs to the rate adapter, not the once-only adapter.

#### Scenario: A receipt-backed end preserves notice

- **WHEN** a receipt-backed payer claim is filed before its payer notice has elapsed
- **THEN** SCM files it with the accepted notice and stop terms unchanged, backdates no payment stop, and reports the authority's result apart from the surrender

### Requirement: Premature-stop penalties consume only held earnings

SCM MUST carry the accepted premature_stop_penalty and fixed claim to the dispute authority without computing a monetary delta. It MUST preserve the signed aggregate penalty answer rather than invent a per-part decomposition, and MUST NOT promise recovery beyond held money. Bond award MUST remain reserved for hosted bonds. The authority's held-earnings cap and mandate-order allocation are external context.

#### Scenario: Held earnings cap the penalty

- **WHEN** an unentitled end carries a 2400 minor-unit penalty and only 900 of earned amounts remain held after refunds
- **THEN** SCM files the claim carrying the accepted 2400 term, computes no monetary delta, and preserves the authority's signed aggregate penalty answer without a per-part decomposition or a promise of more than held money

### Requirement: Premature-stop penalty is an option term

The codec MUST include early_termination.premature_stop_penalty in Agreement bytes and option identity as a nonnegative integer amount in the option asset's minor units, encoded as a canonical decimal string. Absent or zero MUST mean none; negative, fractional or noncanonical amounts MUST refuse publication and acceptance.

#### Scenario: The seller changes the penalty

- **WHEN** a seller changes the premature-stop penalty and republishes
- **THEN** the option identity changes and the accepted Agreement's penalty remains fixed

### Requirement: The seller files ends its terms do not entitle

An unentitled site withdrawal or failed/never-started delivery MUST journal `delivery_end(cause=payee)` for dispute-adapter filing at actual end. Never-delivered timing MUST follow "Never-delivered correction has a fixed non-future basis". A correlated end MUST adopt its controller's classification/filing, not a second fault. A later superseded source MUST remain evidence without a new filing; an established earlier failure MUST remain correctable.

#### Scenario: A withdrawal is reported late

- **WHEN** a site reports at 16:01 that service ended at 14:00
- **THEN** the seller journals delivery_end(cause=payee) and files it with the dispute authority, sending no stop or reverse

#### Scenario: An entitled end needs no filing

- **WHEN** verified buyer stop, terms end or ruling causes admission refusal
- **THEN** that refusal creates no seller-failure filing

### Requirement: Never-delivered correction has a fixed non-future basis

End service MUST fix the accepted Agreement start as the basis with never-delivered evidence, including a pre-start failure recorded after that start. If accepted start is ahead, it MUST journal now but file at that start with at equal to start. It MUST NOT future-date the filing, recompute on retry, or resume delivery.

#### Scenario: Failure precedes accepted start

- **WHEN** a seller failure is observed at 09:00 for an accepted 10:00 start
- **THEN** end and filing intent are recorded atomically at 09:00, the filing waits until 10:00 with at 10:00, and restart preserves the same key without delivery

### Requirement: Non-delivery is established at the delivery deadline

Non-delivery MUST be established when `available` is not durably recorded by the earlier of the Agreement's term end and `delivery_deadline_seconds` after the later of the commitment instant and `start_utc`, whether or not the term continues and whatever the site's activation phase. End service MUST then refuse a new billing start; a `start` the payment authority accepted before the deadline MUST stand as history, remedied by the seller's `delivery_end` filing, not a local reversal.

#### Scenario: The term ends before the deadline

- **WHEN** an Agreement's term ends before its delivery deadline and `available` was never recorded
- **THEN** non-delivery is established at the term end

### Requirement: Cause classification is owned by end service

End service MUST classify verified evidence as lawful (entitled stop, term end/exhaustion, ruling, surrender), seller failure (unentitled withdrawal, provisioning/start failure, activation lapse, established non-delivery) or pending, and correlate site reports with their controllers. It MUST follow evidence and entitlements, never event kind or arrival order; admission refusal or a later stop MUST NOT erase earlier non-delivery or alone create a penalty. Physical work MUST NOT wait for it.

#### Scenario: Delivery deadline passes without availability

- **WHEN** the accepted delivery deadline passes without durable available evidence
- **THEN** end service classifies the end as seller non-delivery established at the deadline, refuses a new billing start, and journals the seller's `delivery_end(cause=payee)` filing

#### Scenario: A site report confirms a lawful end

- **WHEN** a site report is correlated to an already recorded lawful authority end
- **THEN** end service retains both evidence sources without inventing seller fault

#### Scenario: The seller activates after the delivery deadline inside a long term

- **WHEN** a thirty-day deal with `delivery_deadline_seconds` 1800 is approved at 12:00 and the resource is not available to the buyer at 12:30
- **THEN** end service classifies the end as seller non-delivery at 12:30, not a lawful end, and the seller half files `delivery_end` with that basis although the term continues

#### Scenario: The site activates in time but the buyer cannot use the resource by the deadline

- **WHEN** the site activates the lease at 12:29 against a 12:30 deadline and the storefront records `available` only after 12:30, or never
- **THEN** the deal is seller non-delivery, established at 12:30, and the seller half files `delivery_end(cause=payee)` — the Agreement start, the never-delivered basis; a `begin_billing` not yet sent is refused and no new rate part starts; the site's activation is a capacity fact the lifecycle does not treat as delivery

#### Scenario: Billing started seconds before the deadline and availability failed

- **WHEN** the payment authority accepts the payee's `start` at 12:29:58 against a 12:30 deadline and the storefront crashes before recording `available`, recovering at 12:40
- **THEN** the accepted start stands as history and is not refused after the fact; the deal is seller non-delivery, established at 12:30, access is never granted, the resource is ended through end service, and the seller half files `delivery_end(cause=payee)` with the Agreement start as its never-delivered basis, sending no stop or reverse of its own

#### Scenario: Billing ran for many periods before the deadline and availability failed

- **WHEN** a spot deal with a one-minute period, no setup charge and no penalty is approved at 12:00 with a 12:30 deadline, billing starts at 12:01, the storefront crashes before `available` and recovers at 12:40
- **THEN** the seller half files `delivery_end(cause=payee)` with `delivered: false` and the Agreement start as its basis, and sends no reverse for the thirty-nine completed periods, whose return is the dispute authority's ruling

### Requirement: Pending correction resolves in the same journal

record_end MUST atomically retain any pending-classification slot beside the end. resolve_correction(source_ref, expected_revision, evidence, classification, filing_intent?, controlling_source_ref?) MUST atomically discharge it, adopt a verified controlling source's filing, or journal the fixed-basis filing in that journal, without changing the original request. Stale revisions MUST retry without a synthetic end or second journal. Physical work MUST NOT await classification.

#### Scenario: Evidence arrives after a pending end

- **WHEN** later verified evidence resolves an end's pending classification as seller failure
- **THEN** the same journal atomically resolves the slot and records its fixed-basis filing without repeating physical work

### Requirement: Revised cases carry their prior rulings

A prior mechanical delivery_end ruling MUST route a revision to an operator. Revised or linked cases MUST carry prior ruling and effect references and net prior authority effects after unknown originals resolve.

#### Scenario: A revision follows a ruling

- **WHEN** the seller revises a delivery_end on a case the authority has already ruled
- **THEN** the revised case carries the prior ruling and effect references

### Requirement: Filing identities and revised requests are safe across callers

The dispute adapter MUST bind the semantic filing identity to commitment, Agreement authority, cause/end revision and fixed request, and MUST resolve or adopt the equivalent case without a concurrent-writer duplicate. An unresolved original writer MUST remain retryable rather than become a terminal rejection. Unsupported identity or revision mapping MUST report repair required, not allocate another key or use append as amendment.

#### Scenario: An original filing's result is unknown

- **WHEN** an original filing's submission returns no answer
- **THEN** the filing stays retryable under the same semantic identity and is not recorded as rejected

#### Scenario: An operator and online replay submit one intent

- **WHEN** operator recovery and online replay submit the same semantic filing identity concurrently
- **THEN** both resolve one case, or refuse with repair required if the adapter cannot prove safe adoption

### Requirement: Delivery-end filings survive a crash

End service MUST journal a required delivery_end filing with its final request and stable operation key. The dispute adapter MUST resolve an unknown result by that key before replay and MUST NOT file twice; absent sufficient evidence it MUST report repair required.

#### Scenario: Replay after restart

- **WHEN** the storefront restarts with an unacknowledged delivery_end filing
- **THEN** it resolves the same operation key at the dispute authority before retrying and files no second case

### Requirement: Lifecycle commands have defined outcomes

`submit` MUST take a command `{negotiation_id, kind, operation_key, at, payload}`, never an event. Its outcome MUST be `accepted` with the counterpart's records, `rejected` with its reason, `pending`, or `unknown`; a `dispute`'s outcome is the dispute authority's. An `unknown` outcome MUST be resolved by `read`. Each part event's idempotency key MUST derive from the operation key; a retry with the same key and different content MUST be rejected locally.

#### Scenario: A reverse's response is lost

- **WHEN** a seller's `reverse` times out in transport
- **THEN** the outcome is `unknown`, and a retry with the same operation key returns the one recorded reversal

#### Scenario: A retry changes content

- **WHEN** a command is retried with the same operation key and a different `at`
- **THEN** it is rejected without contacting the authority

### Requirement: Dispute writes are idempotent

A `dispute` and an `append` MUST carry stable idempotency keys, so a retry returns the one case or item recorded. Delivery-end filings MUST use the semantic identity and original-writer reservation; other filings and appends MUST derive keys from the command's operation key. Caller keys MUST still reject changed command content.

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

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token and each deal's negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state, current deadline, open-extension flag and open cases. Once-only deals MUST run from verified commitment until delivery ends. Rejected required filings MUST remain terminal, set repair required, expose every filing outcome in read/list and MUST NOT auto-resubmit.

#### Scenario: A rejected filing is visible after restart

- **WHEN** the authority rejects a required seller filing and servicing restarts
- **THEN** the rejection remains visible under repair required, every filing outcome is returned, and the refused filing is not sent again

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

#### Scenario: Listed lifecycle states are explicit

- **WHEN** a deal is returned by `list`
- **THEN** its lifecycle state is unstarted, running, ending, ended or repair required

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

A role's authorities MUST be its own `[[Dispute]]` entries in preference order, followed by the authorities its registry's descriptor recommends where `use_registry_dispute_authorities` is true, which it is by default for a storefront and not for a buyer. Each authority MUST carry a copy of its advertisement, which publication and buyer checks read.

#### Scenario: A buyer uses its registry's recommendation

- **WHEN** a buyer with no `[[Dispute]]` entries and `use_registry_dispute_authorities = true` selects from a registry whose descriptor recommends one authority
- **THEN** it accepts options naming exactly that authority and refuses others

#### Scenario: A buyer has configured no authority

- **WHEN** a buyer with no `[[Dispute]]` entries and the default setting selects from a registry that recommends an authority
- **THEN** it refuses every hosted option, and the diagnostic says to list an authority or set `use_registry_dispute_authorities = true`

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

VM and bare-metal storefronts MUST expose seller `submit/read/list` under the administrator-principal contract and buyer `commit/hint/end_delivery` under the negotiation's buyer principal, keyed by negotiation ID with signed responses. Buyer authority commands MUST NOT be relayed. VM admin interrupt MUST submit the notice stop when the accepted option entitles the payee, and journal the delivery_end filing otherwise.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route uses an entitlement

- **WHEN** an administrator interrupts a spot deal whose accepted option grants the payee a stop entitlement
- **THEN** the route submits the notice stop through the seller half and delivery follows the authority's effective stop, without a self-penalty filing

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through the VM admin route
- **THEN** the route journals an attributed delivery end and delivery_end(cause=payee) filing through the seller half; end service drives the lease without awaiting a ruling

#### Scenario: Another principal ends delivery

- **WHEN** a principal other than the accepted negotiation's buyer sends `end_delivery`
- **THEN** the storefront rejects it without making a final request or contacting the site

### Requirement: End service keeps the earliest final request

End service MUST take attributed final requests from watched authority stops, dispute delivery rulings, verified site end reports and local delivery decisions, including buyer surrender and terminal settlement. It MUST retain the earliest T. Local decisions MUST NOT claim payment completion; money moves only at the payment authority.

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
- **THEN** the recorded earliest end becomes 12:00 with the site's cause, both source records remain, teardown is not restarted, and any required `delivery_end(cause=payee)` filing is journaled

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

End service MUST expose begin_billing(operation_key, activated_delivery_ref) and journal its key/evidence before I/O. Delivery MUST retain only an intent reference. The versioned secret-free `DeliveryEvidence` passed as that reference MUST bind the negotiation, commitment, reservation and fulfillment identities, a nested `ActivatedDeliveryRef` carrying the site activation record reference and instant, and the validated ready-evidence reference and digest. Activation MUST precede rate start; unknown effects MUST resolve by read/same-key retry before disclosure.

#### Scenario: A once-only delivery activates

- **WHEN** validated activation evidence reaches the once-only payment adapter through end service
- **THEN** billing start is a no-op and the delivery record retains only the end-service intent reference

#### Scenario: Billing start lacks activation evidence

- **WHEN** `begin_billing` receives `DeliveryEvidence` with no `ActivatedDeliveryRef`
- **THEN** end service refuses before any authority call and journals no billing intent

### Requirement: Delivery phases use a shared evidence-gated protocol

The foundation MUST define reserve, commit, dispatch, activate, start and disclose phases. Current Alkahest MUST compose explicit no-financial-action after typed/versioned selected-stage evidence validation and local admission; missing adapter entries MUST NOT imply allow. Foundation MUST own the neutral acknowledgement binding/verifier in kit/deal-lifecycle for buyer and double consumers, without servicing dependency.

#### Scenario: Alkahest has no rate operation

- **WHEN** current Alkahest authorizes a protected delivery transition
- **THEN** explicit evidence validation and local admission precede allow, with no fabricated billing start

### Requirement: Admission shares the end-service transaction and revision

End service MUST provide `admit(negotiation_id, phase, expected_revision) → admitted | ended(T), revision` using the caller's storefront database session. A durable revision/CAS MUST order reservation, dispatch, activation and credential authorization against end recording. Stale revisions MUST retry admission without authorizing effects.

#### Scenario: A credential authorization races an end

- **WHEN** an end is recorded after a delivery worker reads the revision but before it authorizes credentials
- **THEN** its stale admission fails and the worker retries against the recorded end, including after restart

### Requirement: End recording and required filing are one operation

End service MUST provide `record_end(final_request, filing_intent? | pending_classification?)`, atomically journaling the final request and any required delivery_end filing in the caller's storefront transaction. An earlier buyer, terms or ruling end MUST NOT cause a seller self-penalty merely because admission is refused.

#### Scenario: A crash separates recording from payment submission

- **WHEN** the storefront crashes after `record_end` commits but before submitting its required filing
- **THEN** restart replays the same intent under its stable operation key; neither half is lost

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded. The buyer's store MUST be the buyer-side lifecycle kit's, under a root the buyer composition passes beside the buyer profile, and the kit MUST NOT depend on core buyer; the storefront's MUST be the servicing kit's.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

#### Scenario: The seller's availability record is weighed, not conclusive

- **WHEN** a seller's storefront recorded `available` before the delivery deadline and the buyer's case carries its kept observation that nothing was reachable
- **THEN** the buyer's display names the seller's record as the seller's assertion and the buyer's observation as its own, the case enters human triage with both, and neither alone decides it

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

### Requirement: Compute readiness progresses without buyer polling

For a committed VM or bare-metal deal, seller servicing MUST adopt the existing
fulfillment's validated active delivery and durably record availability without
a buyer calling a fulfillment status or access route. Adoption MUST preserve
selected-site and resource identity, source-evidence validation, deadlines and
end-service admission. It MUST NOT dispatch another fulfillment.

#### Scenario: The buyer disconnects after commit

- **WHEN** the selected site's existing fulfillment becomes active before the delivery deadline after an accepted commitment
- **THEN** seller servicing records availability and the buyer's signed lifecycle read reports delivery progress without a legacy fulfillment read
- **AND** repeated servicing preserves one fulfillment and the recorded availability instant

#### Scenario: Readiness observation fails

- **WHEN** the site cannot return or validate its active result during servicing
- **THEN** availability remains unproved and later servicing retries the same fulfillment
- **AND** recovery of site end reports and physical teardown remains independently runnable

#### Scenario: A final end precedes adoption

- **WHEN** an end or delivery deadline already refuses disclosure when the active result is observed
- **THEN** servicing does not mark the resource available or disclose access
- **AND** the existing fulfillment follows the ordinary physical end path

### Requirement: Mediation case recovery preserves protection outcomes

Recovery of an existing mediation case MUST distinguish accepted case protection
from pending protection. An accepted answer MUST match the requested case,
Agreement and transaction; a pending answer MUST match the requested case.
Neither outcome alone replaces verified signed filing evidence or authorizes a
duplicate filing.

#### Scenario: Accepted case recovery

- **WHEN** an existing delivery-end filing is recovered and the authority returns an accepted case envelope
- **THEN** recovery verifies its bindings and adopts the original signed filing without creating another case

#### Scenario: Protection is still pending

- **WHEN** the authority reports pending protection for the requested case
- **THEN** recovery remains pending and sends no duplicate filing

#### Scenario: Response names another case or deal

- **WHEN** a case answer names a different case, Agreement or transaction
- **THEN** recovery rejects the response without adopting evidence or sending another filing
