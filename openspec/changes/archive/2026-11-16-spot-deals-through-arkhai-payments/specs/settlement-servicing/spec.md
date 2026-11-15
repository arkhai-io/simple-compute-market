## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Snapshot verification accepts bounded identity history

**Reason**: Its one scenario promised re-anchoring evidence the verifier does not supply, and a receipt identity change is a cutover that re-anchors no deal. The requirement continues, its text unchanged and its scenario reworded, as "Snapshot verification accepts configured identity history".
**Migration**: None: the verifier is unchanged.

## ADDED Requirements

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
