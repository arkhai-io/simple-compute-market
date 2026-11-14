## REMOVED Requirements

### Requirement: Started-period treatment is a committed payment term

**Reason**: Its "Returned treatment is not expressible" scenario describes a contract that never shipped: the vendored published contract expresses `charged`, `returned`, `prorated` and `chosen`, so what limits an offer is the composition's servicing declaration, not the contract.

**Migration**: "Started-period treatment is a committed and declared payment term" carries the same mapping and refusal of storefront refunds, refuses what the servicing declaration does not list, and keeps the one-notice scenario.

## MODIFIED Requirements

### Requirement: Lifecycle routes are authenticated per role

VM and bare-metal storefronts MUST expose seller `submit/read/list` under the administrator-principal contract and buyer `commit/hint/end_delivery` under the negotiation's buyer principal, keyed by negotiation ID with signed responses. Buyer authority commands MUST NOT be relayed. For a committed `arkhai.payments.v1` deal, each compute storefront's admin interrupt MUST carry out the command the seller half's classification gives its kind ("Administrator interruption explicitly classifies its cause"): the notice stop for a preemption under the accepted payee entitlement, the journaled delivery_end filing for a failure.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route uses an entitlement

- **WHEN** an administrator interrupts with kind preemption a spot deal whose accepted option grants the payee a stop entitlement
- **THEN** the route submits the notice stop through the seller half and delivery follows the authority's effective stop, without a self-penalty filing

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal with only `once` parts through either compute storefront's admin route, naming no kind or kind failure
- **THEN** the route journals an attributed delivery end and delivery_end(cause=payee) filing through the seller half; end service drives the lease without awaiting a ruling

#### Scenario: Another principal ends delivery

- **WHEN** a principal other than the accepted negotiation's buyer sends `end_delivery`
- **THEN** the storefront rejects it without making a final request or contacting the site

### Requirement: Term ends carry their own partial-period treatment

The sole term-end carrier MUST be early_termination.settles_through, distinct from entitlements. The adapter MUST map it to rate end.partialPeriod through the stop-authority mapping. Compute presets MUST use last_boundary/returned, and a term end MAY be offered only under a treatment the composition's servicing declaration lists. No mechanism-specific field MAY duplicate it.

#### Scenario: A rate end is not a billing boundary

- **WHEN** activation starts rate billing after the Agreement start and the absolute term end falls within a billing period
- **THEN** the compute preset's `end.partialPeriod` is returned, so billing ends at the last boundary without running past the agreed maximum
- **AND** publication and acceptance refuse that preset where the servicing declaration does not list `returned`

### Requirement: Neutral delivery decisions delegate payment interpretation

kit/deal-servicing MUST own authorize_delivery for commit, dispatch, start and disclose with durable allow/refuse/pending, reason, operation ID and evidence references. The foundation payment-adapter protocol MUST expose authorize(phase, evidence, billing) and start_billing(keys, activated_delivery_evidence). `billing` is optional: end service's journaled billing-start intent, its operation key and, once recorded, its result, which end service MUST pass at disclosure. `keys` are the operation keys of end service's one billing-start intent and MUST carry its operation store, so a mechanism records each operation it derives before any I/O. Generic servicing MUST NOT interpret hosted part fields; once-only adapters MUST validate commitment evidence and use no-op billing start.

While end service services no rate deals, authorize_delivery MUST refuse the commit phase of a deal whose committed seller projection is not once-only, before it asks the payment adapter and without I/O, with the refusal code `rate_servicing_unavailable`; a servicing declaration enables rate offers and MUST NOT by itself enable their delivery. A deal with no committed seller projection MUST be refused without that code. A delivery authorization MAY carry a closed refusal code; every answer other than this refusal MUST omit it, and a journaled authorization recorded without one MUST still read.

For a deal whose committed seller projection is not once-only, end service's admission MUST NOT record the delivery-deadline end or journal its filing until a successful payment observation made at or after the deadline shows no lawful end effective at or before it; while the payment authority cannot be read the deal MUST stay unended with nothing filed. Each compute domain's recovery MUST read the payment authority before it admits a missed deadline. A once-only deal keeps admission's deadline rule unchanged.

#### Scenario: A rate deal is committed before rate servicing exists
- **GIVEN** a committed deal whose seller projection is not once-only, under a composition declaring the rate treatments its option uses
- **WHEN** delivery asks authorize_delivery to commit it
- **THEN** end service refuses with the code `rate_servicing_unavailable` and its reason, without asking the payment adapter
- **AND** no capacity is placed and no billing intent is journaled for the deal

#### Scenario: A once-only deal is committed
- **WHEN** delivery asks authorize_delivery to commit a deal whose seller projection is once-only
- **THEN** end service asks the payment adapter as before, and its answer carries no refusal code

#### Scenario: A refused rate deal passes its delivery deadline
- **GIVEN** a rate deal refused at commit and never available, whose buyer has not stopped
- **WHEN** it is driven after its delivery deadline, following a payment observation made after the deadline
- **THEN** admission records seller non-delivery at the deadline and journals the seller's `delivery_end(cause=payee, delivered=false)` filing

#### Scenario: A buyer stops while the storefront is down
- **GIVEN** a rate deal refused at commit whose buyer's stop took effect at the payment authority before the delivery deadline, while the storefront was down and the hint was lost
- **WHEN** the storefront recovers after the deadline
- **THEN** recovery reads the authority before admitting the deadline, records the buyer's lawful end, and journals no seller non-delivery filing

#### Scenario: The payment authority is unreadable at the deadline
- **GIVEN** a rate deal refused at commit and never available
- **WHEN** it is driven after its delivery deadline and the payment authority cannot be read
- **THEN** no end is recorded and no filing is journaled, and a later drive after a successful read admits the deadline

#### Scenario: A financial decision is pending

- **WHEN** the injected adapter cannot resolve authority evidence for dispatch
- **THEN** delivery stays pending and a later allow still cannot override end-service admission

#### Scenario: Disclosure reads the journaled billing start

- **GIVEN** end service has journaled its billing-start intent and recorded its result
- **WHEN** delivery asks authorize_delivery to disclose
- **THEN** the adapter receives that intent's operation key and recorded result
- **AND** no other phase receives a billing start

## ADDED Requirements

### Requirement: Stop requests are distinct from final stops, readable by released clients

A raw stop request MUST NOT end delivery. The lifecycle contracts MUST carry each part's verified rate bounds and its pending and final stops (`PaymentPartObservation`, `AuthorityView.parts`) and a payment event's treatment (`PaymentEvent.settles_through`). Because notice maturity can carry no new event sequence, the watch MUST read each part's final stop outside its event cursor and record it once by authority record, refusing a replay that changes the recorded end. The lifecycle read and list MUST omit an empty `parts` and a null `settles_through`, so a once-only deal's read and list stay valid for clients of `kit/deal-lifecycle-contracts` 0.1.0, whose models forbid unknown fields.

#### Scenario: A stop request is pending

- **WHEN** the authority records a stop request effective in the future
- **THEN** the watch records no end, and read exposes the pending stop

#### Scenario: Notice matures without a new event

- **GIVEN** the watch consumed a stop request's event in an earlier poll
- **WHEN** the authority's final stop appears with no new event sequence
- **THEN** the watch records the end once, by the stop's authority record
- **AND** a later read changing that stop's end is refused

#### Scenario: A released client reads a once-only deal

- **WHEN** a client of contracts 0.1.0 validates a once-only deal's lifecycle read or list
- **THEN** it validates, since the read omits the empty `parts` and every null `settles_through`

### Requirement: Started-period treatment is a committed and declared payment term

The codec MUST map `settles_through` values `started_period`, `last_boundary`, `stop` to payments `partialPeriod` values `charged`, `returned`, `prorated` respectively. Publication and buyer acceptance MUST refuse a value the composition's servicing declaration does not list. SCM MUST NOT replace an entitled stop's committed treatment with a storefront refund; a seller's exceptional end is a dispute filing.

#### Scenario: A treatment is not declared

- **WHEN** a spot option names payee `last_boundary` but the composition's servicing declaration lists only `charged`
- **THEN** publication and acceptance refuse it, naming the undeclared treatment
- **AND** the same option publishes under a declaration listing `charged` and `returned`

#### Scenario: Stop authorities use one notice

- **WHEN** an entitlement has `notice_seconds: 0` and `settles_through: started_period`
- **THEN** its stop entry has zero notice and charged treatment, with no exposure tail

### Requirement: Seller notice uses lifecycle submit and authority-hosted stop
The seller half MUST admit a negotiation-keyed notice command only under the accepted payee entitlement. It MUST use the lifecycle submit command contract, submit stop immediately through the payment adapter, and return authority status rather than claim a locally scheduled payment end.

#### Scenario: A seller preempts an accepted spot deal
- **GIVEN** an authenticated seller and an accepted payee notice entitlement
- **WHEN** the seller submits notice with a stable operation key
- **THEN** the seller half preserves the command identity without a correction obligation
- **AND** the adapter submits explicit affected-part stops to the payment authority
- **AND** read/list expose the verified pending stop and its effective time

#### Scenario: The notice response is lost
- **WHEN** the authority accepted stop but its response was lost
- **THEN** lifecycle reports unknown and resolves by read or identical-key retry
- **AND** no local due-time payment-stop task is created

#### Scenario: A buyer stops earlier during notice
- **GIVEN** a seller pending stop and an earlier authority-recorded buyer stop
- **WHEN** lifecycle reads the authority
- **THEN** it exposes the earlier effective stop for end service
- **AND** a repeated seller command cannot postpone that stop

#### Scenario: On-demand cannot be dressed as preemption
- **GIVEN** an accepted option without payee entitlement
- **WHEN** the seller submits notice
- **THEN** the command is refused before sending a payment event
- **AND** the response identifies delivery_end as the dispute-filing path for a seller-caused failure

### Requirement: Compute operator preemption delegates through the typed lifecycle client
Both compute storefront operator CLIs MUST provide deals preempt by negotiation ID, using the lifecycle client's notice method and seller authentication. The command MUST preserve its operation key and optional at and display the authority's status and effective time without claiming a local timestamp is authoritative.

#### Scenario: An operator requests a future stop
- **WHEN** the operator invokes deals preempt with negotiation ID, operation key and at
- **THEN** the CLI delegates the same command through lifecycle submit
- **AND** displays pending, unknown or accepted authority state without bypassing notice

### Requirement: Administrator interruption explicitly classifies its cause
An administrator interruption MUST distinguish `interruption_kind=preemption` from `interruption_kind=failure`, and the classification from kind to command MUST live in `kit/deal-servicing`'s seller half, which every compute storefront's interrupt route calls rather than classifying in a domain. Preemption MUST delegate the existing notice admission and journaled stop, requiring the accepted payee entitlement. Failure MUST end delivery and file delivery_end for both spot and on-demand, without a local rate-part payout remedy. An omitted kind MUST refuse for rate deals; once-only deals retain failure as their compatibility default. The free-text administrator reason remains required for hosted interruptions, and the seller half MUST record the administrator and reason under the operation's key, refusing a same-key retry that changes either.

#### Scenario: A lawful administrator preemption
- **GIVEN** the accepted option grants a payee entitlement
- **WHEN** an administrator interrupts with kind preemption
- **THEN** it delegates notice through the same lifecycle submit and operation journal
- **AND** it waits for the effective authority stop before ending delivery

#### Scenario: Failure is independent of spot permission
- **GIVEN** a spot or on-demand deal
- **WHEN** an administrator interrupts with kind failure and a hardware-failure reason
- **THEN** delivery ends and delivery_end is filed under the existing seller-failure path
- **AND** no automatic rate-part reverse or self-penalty is attempted

#### Scenario: Missing classification cannot guess a rate deal's cause
- **WHEN** a rate interruption omits its kind or an unentitled deal requests preemption
- **THEN** the request refuses before any notice, physical end or filing

#### Scenario: A retry changes the administrator's reason
- **GIVEN** an interruption accepted under an operation key
- **WHEN** the same key is sent again with a different reason
- **THEN** the seller half refuses it, keeping the first attribution

### Requirement: Canonical rate buyer end preserves service during notice
The buyer half MUST normally submit rate stop at the payment authority and send hint, allowing delivery until effective stop reaches end service through watch. It MUST reserve end_delivery for explicit immediate surrender or the unreachable-payment-authority delivery_end(cause=payer) case path. Immediate surrender MUST disclose that paid notice may outlast service. Both compute domains MUST expose this end as their canonical `end` verb, registered from the buyer half's shared command, with `--end-now-regardless` selecting immediate surrender.

#### Scenario: A payer has nonzero notice
- **GIVEN** an accepted rate option with payer notice 300 seconds
- **WHEN** the buyer invokes normal end and stop is accepted pending
- **THEN** the buyer sends hint, not end_delivery, and service continues until the effective authority stop
- **AND** losing the hint does not cancel or postpone that stop

#### Scenario: The buyer explicitly gives up remaining notice service
- **WHEN** the buyer chooses end-now-regardless
- **THEN** the buyer half submits stop and sends end_delivery with the immediate-surrender disclosure

#### Scenario: The payment authority cannot be reached
- **WHEN** the buyer invokes end but payment stop is unknown or unavailable
- **THEN** the buyer follows buyer-orchestration's “The buyer's end is backed by its own stop or a case”, including its foundation-owned outage recovery rather than a rate-specific duplicate
