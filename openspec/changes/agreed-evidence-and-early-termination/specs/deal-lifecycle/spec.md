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

A ruling's outcome MUST be a list of consequences, each a payment effect on one part (reverse an amount of a payment part, award an amount of a bond, stop a `rate` part at a *T* no later than now) or a delivery end at *T*. The storefront MUST send an outcome's delivery end, read through `watch`, to end service. An outcome without a delivery end MUST leave the term running.

#### Scenario: A ruling discounts a deal

- **WHEN** a ruling reverses a quarter of a hosted deal's held `once` payment and has no delivery end
- **THEN** the payment authority records one partial `reverse` by the dispute authority with the case reference, and the lease is unchanged

### Requirement: Requests are intents or interface requests

A case's requested outcome MUST be either a deal-level intent SCM issues, at least `exceptional_end(at)`, or an interface request the dispute adapter built or validated. The dispute adapter MUST map an intent into its interface's request or reject it as unsupported. The generic lifecycle kits MUST NOT contain any interface's request vocabulary, and the lifecycle layer MUST NOT compute per-part effects for a request.

#### Scenario: A buyer requests a refund for an outage

- **WHEN** a buyer files a case requesting a refund of the share of its deal lost to an outage
- **THEN** the dispute adapter builds the interface request, and the buyer half sends it with no per-part amounts of its own

#### Scenario: An interface has no exceptional end

- **WHEN** a seller issues `exceptional_end(now)` on a deal whose dispute interface defines no such request
- **THEN** the outcome is `rejected` as unsupported and no authority is contacted

### Requirement: Outcome effects are acted on once

The storefront MUST read a ruling's effects from the dispute authority's record by their stable IDs and applied states, and MUST act on each effect at most once, whether the record shows it partly or wholly applied.

#### Scenario: A ruling is read while partly applied

- **WHEN** `watch` yields a ruling with a reverse and a delivery end, of which only the reverse is shown applied, and later the same ruling with both applied
- **THEN** end service receives the delivery end once

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

Each payment adapter MUST derive holds under which each amount a part holds pays out no earlier than the part's end plus `adjudication.dispute_window_seconds`. A `once` part's end MUST be the Agreement's term end, `start_utc + duration_seconds`; a rate part's end MUST be its stop, or the term end if it is not stopped. The window MUST NOT be shorter than the dispute authority's advertised minimum. SCM MUST NOT refuse a filing for being after the window; that is the dispute authority's policy.

#### Scenario: A once deal's hold is derived

- **WHEN** a hosted mandate is derived for a deal whose term ends at 13:00 with a one-day window
- **THEN** its `once` part has `end` 13:00 and hold `{afterStop: P1D}`, so it pays out no earlier than 13:00 the next day, or one day after an earlier stop

#### Scenario: A rate part stops early

- **WHEN** a spot deal with a 30-day maximum term and a 14-day window is stopped after one hour
- **THEN** its rate part's amounts are derived to pay out 14 days after the stop, not after the maximum term

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

### Requirement: Mechanical rulings are the authority's policy

A party's request against itself MUST be an ordinary `dispute`, with no kind of its own. SCM MUST NOT depend on which disputes an authority rules without a person: the storefront MUST NOT change delivery on filing, and MUST act only on rulings read from the authority's record.

#### Scenario: A seller's hardware fails

- **WHEN** a seller files `exceptional_end(now)` on a hosted `once` deal
- **THEN** the lease is unchanged until `watch` yields the ruling's delivery end, which end service then applies

#### Scenario: A filing is not ruled

- **WHEN** a seller's filing is sent to the authority's triage and no ruling follows
- **THEN** the storefront keeps delivering and sends no payment command

### Requirement: A seller's exceptional end is an intent

The seller half's exceptional-end command MUST file `exceptional_end(now)` with the agreement's dispute authority through its dispute adapter, carrying no per-part amounts computed by the storefront.

#### Scenario: An administrator files an exceptional end

- **WHEN** an administrator files an exceptional end on a hosted `once` deal
- **THEN** the dispute adapter maps `exceptional_end(now)` into its interface's request, and the filing carries no per-part amounts

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

The VM and bare-metal storefronts MUST expose the seller half's `submit`, `read`, and `list` through the administrator-principal contract. The VM and bare-metal storefronts MUST expose a buyer route for `commit` and `hint`, authenticated as the negotiation's buyer principal, with signed responses. The storefront MUST NOT relay a buyer's authority command.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through the VM admin route
- **THEN** the route files `exceptional_end(now)` with the agreement's dispute authority through the seller half, and the lease changes only through end service, once the ruling is read

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

A `dispute` MUST carry one case about the agreement: the commitment reference, the committed agreement or where to fetch it, the terms, the claim, the requested outcome (an intent or an interface request), and ordered evidence items. Each item MUST be an evidence-store record with kind, producer, time, content digest, and the exact original bytes or the authority's signed record. A party MUST be able to export the case as one bundle.

#### Scenario: A buyer files a dispute

- **WHEN** a buyer files a dispute through the buyer half
- **THEN** the case payload is built from its evidence store, and each item carries the exact bytes it received

### Requirement: Refund is a reverse command; reconciliation finds unreported commitments

A VM or bare-metal seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain and find commitments a buyer never reported.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** the reconciliation pass finds the commitment and the seller serves or reverses it
