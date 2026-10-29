## MODIFIED Requirements

### Requirement: The payments mandate is derived exactly from the Agreement
The mandate MUST bind sha256(JCS(agreement)) as deal, sha256(JCS(mandate)) as transaction ID, settlement_params.payer_account as from and selected payee account as to, the published fee policy and nonce arkhai.payments.v1. Once-only options MUST derive one once part; rate options MUST derive the selected rate and optional setup parts. Every part MUST use the foundation's entitlement/adjudication authority derivation and hold cap; hosted bond remains unsupported.

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

#### Scenario: Notice is explicitly priced
- **GIVEN** a payer entitlement with notice_seconds zero and settles_through started_period
- **WHEN** the adapter derives the rate part using the foundation codec
- **THEN** payer notice remains zero and partialPeriod is charged, without a second hidden tail

#### Scenario: All stop and end treatments are explicit
- **WHEN** the shared codec derives rate/setup parts
- **THEN** every stop-authority entry and each part end carries partialPeriod
- **AND** the dispute authority's rate stop entry is {account, notice: PT0S, partialPeriod: chosen}, requiring its stop event to supply treatment
- **AND** mediation does not require returned on seller entries; negotiation decides accepted treatment, seller presets offer last_boundary, and the terms-owned buyer policy defaults to refusing other payee or term-end treatments

#### Scenario: Setup uses its own term
- **WHEN** the setup once part ends at activation
- **THEN** its mechanical mediation mapping uses Agreement start through that part end, not the maximum compute term
- **AND** a zero-length term is wholly unserved before its end and wholly served from it

#### Scenario: Provisioning starts late
- **GIVEN** a finite maximum term equal to accepted duration_seconds
- **WHEN** rate start occurs after Agreement start_utc
- **THEN** the derived part end instant remains start_utc plus max_term_seconds
- **AND** its own partialPeriod determines the final period's charge, not a rounded-down term

### Requirement: Hosted rate commands preserve part identity and uncertain outcomes
The hosted adapter MUST translate lifecycle commands into explicit per-part events with stable operation-derived request identities. It MUST require a matching ActivatedDeliveryRef for rate start, reject key reuse with changed content, and expose unknown outcomes for resolution by verified reads before another monetary delta is issued.

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

### Requirement: Rate stops bind started-period treatment at the payment authority
SCM MUST derive rate stop treatment through the shared lifecycle codec's settles_through/partialPeriod mapping. Publication and acceptance MUST refuse terms the vendored contract cannot express. SCM MUST NOT compute or submit automatic end-correction reversals; exceptional ends use the dispute adapter's exceptional_end(at).

#### Scenario: The contract has no partialPeriod field yet
- **WHEN** an interim spot preset is offered against a contract supporting only charged behavior
- **THEN** payer and payee entitlements both commit started_period
- **AND** last_boundary or stop terms refuse before publication or acceptance
- **AND** the terms-owned default buyer policy refuses the interim offer; proceeding requires explicit buyer acceptance of started_period on payee stops and any charged term end

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
- **THEN** its event supplies partialPeriod: payee treatment for exceptional_end, payer treatment for buyer_end, or the operator ruling's stated treatment
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
- **THEN** its lawful end attribution is preserved without exceptional_end self-filing merely for non-availability
- **AND** only seller non-delivery follows the classified self-filing handoff

#### Scenario: A site reports an earlier exceptional end
- **WHEN** the seller learns service ended without an entitlement covering that end
- **THEN** it files exceptional_end at the reported instant
- **AND** the dispute authority determines the stop-now and reversal effects

#### Scenario: Start evidence is absent or mismatched
- **WHEN** rate start has no valid ActivatedDeliveryRef matching the deal, commitment and activated lease
- **THEN** the adapter refuses start before contacting the payment authority

### Requirement: Absolute rate ends bind their own started-period treatment
SCM MUST bind the rate option's explicit end_partial_period to the payment end's partialPeriod, preserving start_utc plus max_term_seconds as its instant. Compute presets MUST use returned when expressible. Publication and acceptance MUST refuse unexpressible end treatments; an explicitly disclosed charged interim option MUST NOT be presented as returned or repaired by a local refund.

#### Scenario: A late start leaves an incomplete final period
- **GIVEN** authority start 10, period 60, amount 100 and absolute end 120 with returned treatment
- **WHEN** that end is reached
- **THEN** billing keeps 100 for [10,70) and returns the incomplete [70,130) period
- **AND** delivery still ends at 120 without rounding down the accepted duration

#### Scenario: Only charged absolute ends are expressible
- **WHEN** an interim spot or on-demand rate preset is published
- **THEN** its option explicitly commits charged end treatment and discloses the final partial-period charge
- **AND** an option requesting returned or prorated refuses publication and acceptance

### Requirement: Rate observations require verified authority state
The hosted adapter MUST consume the foundation's verified snapshot interface before interpreting start, funding, pending stop, stop, extensions, releaseAt or event sequence. It MUST expose per-part changes to lifecycle read/watch without treating a courtesy hint or a missing funding field as an authoritative stop.

#### Scenario: A pending stop survives the storefront
- **GIVEN** a verified authority pendingStop
- **WHEN** the storefront restarts after its effective time
- **THEN** adapter read exposes the authority's resulting stop and cause for end service
- **AND** no local payment-stop schedule is required

#### Scenario: The snapshot cannot be verified
- **WHEN** snapshot verification fails or its known sequence regresses
- **THEN** no rate state from it is used for billing, start admission or funding renewal

### Requirement: Running hosted rate deals can re-anchor during identity overlap
SCM MUST provide current-key verified snapshot evidence for durable rate-deal re-anchoring during bounded identity overlap, preserving original signed bytes. Its retirement inventory MUST include all hosted deals: rate deals MUST re-anchor or drain, and once-only deals MUST drain before their key is removed. A mode change MUST require draining, not re-anchoring.

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
