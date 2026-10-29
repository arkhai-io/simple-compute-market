## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement
The mandate MUST bind sha256(JCS(agreement)) as deal, sha256(JCS(mandate)) as transaction ID, settlement_params.payer_account as from and selected payee account as to, the published fee policy and nonce arkhai.payments.v1. Once-only options MUST derive one once part for the agreed amount and asset; rate options MUST derive the selected rate and optional setup parts, all with per-part authorities.

Every once hold MUST last at least until its own part end plus adjudication.dispute_window_seconds (prepaid service ends at Agreement term end; delivered setup ends at activation). Approval MUST expire after approval_window. Hosted options MUST NOT carry bond until seller-funded parts are supported. Once-only mandates MUST authorize no start or stop. Reverse MUST be authorized for seller and the Agreement's dispute authority, whose account MUST come from the option's adjudication.dispute, never Settlement.arkhai_payments configuration. Only that authority MUST be listed under extend, also authorizing lift. Each part MUST carry maxHoldExtension from adjudication.case_hold_max_seconds, null when unbounded. Reverse MAY name a part and an amount up to what it still holds.

Rate authorities and term ends MUST use the deal-lifecycle codec. Optional setup MUST bind a qualified activation trigger and bounded no-activation fallback in the approved mandate; an unexpressible setup contract MUST refuse publication and acceptance.

#### Scenario: Hold and approval expiry follow the accepted timing
- **WHEN** a once-only mandate is derived from an Agreement accepted at accepted_at
- **THEN** its hold is ceil(start_utc - accepted_at) + duration_seconds + dispute_window_seconds whole seconds and approval expires at floor(accepted_at) + approval_window
- **AND** fractional timestamps remain unchanged in Agreement bytes and its deal hash

#### Scenario: A once mandate is derived
- **WHEN** the option has only one once part and no early_termination
- **THEN** it authorizes no start or stop, authorizes reverse for payee and the option's dispute authority, and extend/lift only for that dispute authority
- **AND** its hold lasts through term end plus dispute window and maxHoldExtension comes from case_hold_max_seconds, null when unbounded

#### Scenario: A hosted option names a bond
- **WHEN** a hosted option includes bond
- **THEN** publication refuses the unsupported term

#### Scenario: A mixed mandate is derived
- **WHEN** a rate option includes setup_amount
- **THEN** setup once precedes rate, each with per-part authorities and maxHoldExtension
- **AND** setup end is activation, rate hold is afterStop plus dispute window, and approval expiry still uses approval_window

## ADDED Requirements

### Requirement: Hosted rate mandates are derived from the selected option
SCM MUST derive time rate parts through the agreed-price accessor and lifecycle codec, using the selected Agreement's asset, period, reservation lead, absolute term end, adjudication hold and cap. The buyer MUST independently check all parts and authorities before approval, including any disclosed setup once part.

#### Scenario: A mixed setup and rate option is selected
- **GIVEN** a selected option with setup_amount and a price accessor returning a per-period charge
- **WHEN** buyer and seller derive the mandate
- **THEN** both derive setup once followed by rate, with the same amounts, asset, end, afterStop hold, maxHoldExtension and per-part authorities
- **AND** neither reads Agreement.amount as a direct charge

#### Scenario: A seller adds stop authority to on-demand
- **GIVEN** an accepted option with no payee early-termination entitlement
- **WHEN** the buyer checks a mandate containing a payee stop authority on the rate part
- **THEN** the mandate is refused before approval

#### Scenario: The rate adapter consumes lifecycle treatment
- **GIVEN** the deal-lifecycle requirements for stop-authority and term-end treatment
- **WHEN** a returned-capable rate mandate is derived
- **THEN** the adapter uses the shared codec for rate stop entries and rate end, including the dispute authority's chosen entry
- **AND** setup once ends carry no partialPeriod field

#### Scenario: Setup is activated or lawfully cancelled
- **GIVEN** a qualified setup contract linked to the rate part
- **WHEN** payee start wins
- **THEN** setup becomes served and its dispute-window release anchor is activation
- **WHEN** a lawful rate stop or absolute end wins before activation
- **THEN** setup returns in full, records terminal unserved status at cancellation, and can drain without seller-fault attribution
- **AND** no setup payout is possible while awaiting the start trigger

#### Scenario: Provisioning starts late
- **GIVEN** a finite maximum term equal to accepted duration_seconds
- **WHEN** rate start occurs after Agreement start_utc
- **THEN** the derived part end instant remains start_utc plus max_term_seconds
- **AND** its own partialPeriod determines the final period's charge, not a rounded-down term

### Requirement: Hosted rate commands preserve part identity and uncertain outcomes
The hosted adapter MUST translate lifecycle commands into explicit per-part events with stable operation-derived request identities. It MUST require the deal-lifecycle versioned activated-delivery envelope for rate start and compare new descriptors against the caller-supplied journaled descriptor/digest. The caller MUST reject changed-content key reuse before I/O. Unknown outcomes MUST resolve by verified read before another monetary delta.

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

#### Scenario: A stop is repeated
- **WHEN** a stop submission reports an already-stopped part
- **THEN** the adapter confirms satisfaction only from a verified same-or-earlier effective stop
- **AND** it never reports a later local timestamp as the authority's end

### Requirement: Rate stops consume authority-priced period treatment
The hosted rate adapter MUST consume the deal-lifecycle stop-authority mapping and capability refusal rules. It MUST observe the winning authority entry rather than compute cooperative end-price corrections. Seller exceptional_end MUST instead use its separate payee self-correction translation.

#### Scenario: The contract has no partialPeriod field yet
- **WHEN** an interim spot or on-demand preset is offered against a contract supporting only charged behavior
- **THEN** every present entitlement and term end commits started_period; absent wire treatment fields use vector-qualified fixed charged semantics, including dispute stops
- **AND** last_boundary or stop terms refuse before publication or acceptance
- **AND** the buyer-orchestration default acceptance policy refuses the interim offer; proceeding requires explicit buyer acceptance of started_period on payee stops and any charged term end

#### Scenario: Returned-capable spot reaches default buyers
- **GIVEN** a vendored revision expressing returned and an offered spot option with payee and term-end settles_through last_boundary
- **WHEN** the buyer's default acceptance policy and exact mandate check run
- **THEN** those treatments pass policy without loosening it
- **AND** an unexpressible returned treatment is never replaced with charged

#### Scenario: Rate earning follows completed periods or stop
- **WHEN** a rate period begins
- **THEN** its amount remains reserved until the period ends or the part stops
- **AND** a stop prices the partial period under its committed or chosen treatment without SCM clawback
- **AND** afterStop payout timing is unchanged

#### Scenario: A dispute stop selects its treatment
- **WHEN** a verified stop is issued under the dispute authority's chosen entry
- **THEN** its event supplies the human ruling's treatment; buyer_end preserves payer notice and payer treatment
- **AND** exceptional_end is not a dispute intent or ruling
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
- **GIVEN** a controlling buyer end, entitled authority stop, terms end or ruling before disclosure
- **WHEN** delivery reports that availability was not reached
- **THEN** its lawful end attribution is preserved without exceptional_end self-correction merely for non-availability
- **AND** only seller non-delivery follows the classified self-correction handoff

#### Scenario: A site reports an earlier exceptional end
- **WHEN** the seller learns service ended without an entitlement covering that end
- **THEN** it submits exceptional_end at the reported instant to its payment adapter
- **AND** the adapter computes stop-now and reversal effects from the mandate, without filing a case

#### Scenario: Start evidence is absent or mismatched
- **WHEN** rate start has no valid deal-lifecycle activation envelope matching the deal, commitment and activated lease
- **THEN** the adapter refuses start before contacting the payment authority

### Requirement: Absolute rate ends preserve the accepted capacity bound
The rate adapter MUST derive end.partialPeriod only from early_termination.settles_through under deal-lifecycle's “Term ends carry their own partial-period treatment”, preserving start_utc plus max_term_seconds as its instant. Late activation MUST NOT shorten or extend that accepted bound.

#### Scenario: A late start leaves an incomplete final period
- **GIVEN** authority start 10, period 60, amount 100 and absolute end 120 with returned treatment
- **WHEN** that end is reached
- **THEN** billing keeps 100 for [10,70) and returns the incomplete [70,130) period
- **AND** delivery still ends at 120 without rounding down the accepted duration

#### Scenario: Only charged absolute ends are expressible
- **WHEN** an interim spot or on-demand rate preset is published
- **THEN** its early_termination.settles_through explicitly commits started_period and discloses the final partial-period charge
- **AND** an option requesting returned or prorated refuses publication and acceptance

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

### Requirement: Seller exceptional ends translate to payee self-correction
The hosted adapter MUST translate the seller's journaled exceptional_end(at) into per-part payee events from the accepted mandate, without a case. It MUST preserve command identity, resolve unknown outcomes before further deltas and avoid double-returning unearned reservations. Future-dated at MUST refuse; pre-start failures MUST journal immediately and act at Agreement start.

#### Scenario: On-demand service fails without a payee entitlement
- **WHEN** exceptional_end is applied for a service failure at at
- **THEN** every rate part is stopped now with returned regardless of payee entitlement and its earned amount since at is reversed
- **AND** once parts reverse their time-unserved share, setup all if undelivered and none if delivered
- **AND** any supported bond is awarded in full; unsupported bond remains a publication refusal
- **AND** mediation receives no exceptional_end filing

#### Scenario: The stop response or reversal response is lost
- **WHEN** a per-part self-correction event has unknown outcome
- **THEN** read and identical-key replay resolve it before another amount is computed
- **AND** held-money shortfalls are surfaced as repair, not invented credits

#### Scenario: The contract cannot perform the buyer-favourable payee stop
- **WHEN** the vendored contract cannot stop without entitlement with returned treatment
- **THEN** self-correction qualification refuses instead of substituting charged or a dispute filing

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

### Requirement: Running hosted rate deals can re-anchor during identity overlap
SCM MUST provide current-key verified snapshots for rate re-anchoring during bounded identity overlap, preserving original bytes. Verification MUST accept identity validity windows, embedded old-receipt attestation and a caller-supplied minimum sequence. Retirement MUST inventory all hosted deals: rate deals MUST re-anchor or drain; once-only deals MUST drain. Mode changes MUST require draining.

#### Scenario: An old-key receipt is embedded in a new-key snapshot
- **GIVEN** an old receipt verified during the configured overlap
- **WHEN** a fresh current-key snapshot attests that receipt and matches the mandate, parties, mode and sequence
- **THEN** SCM provides that snapshot for durable replacement of the approval trust anchor
- **AND** the retiring key is removable only after dependent deals re-anchor or drain

#### Scenario: A stale snapshot attempts to restore old trust
- **WHEN** a restart sees evidence below the persisted sequence or signed only by a retired key
- **THEN** it cannot replace the current approval evidence or revive the retired anchor

#### Scenario: Test mode changes to live
- **WHEN** payment livemode changes
- **THEN** the running test-mode deal cannot re-anchor as a live deal
