## REMOVED Requirements

### Requirement: Started-period treatment is a committed payment term

**Reason**: Its "Returned treatment is not expressible" scenario describes a contract that never shipped: the vendored published contract expresses `charged`, `returned`, `prorated` and `chosen`, so what limits an offer is the composition's servicing declaration, not the contract.

**Migration**: "Started-period treatment is a committed and declared payment term" carries the same mapping and refusal of storefront refunds, refuses what the servicing declaration does not list, and keeps the one-notice scenario.

## MODIFIED Requirements

### Requirement: Term ends carry their own partial-period treatment

The sole term-end carrier MUST be early_termination.settles_through, distinct from entitlements. The adapter MUST map it to rate end.partialPeriod through the stop-authority mapping. Compute presets MUST use last_boundary/returned, and a term end MAY be offered only under a treatment the composition's servicing declaration lists. No mechanism-specific field MAY duplicate it.

#### Scenario: A rate end is not a billing boundary

- **WHEN** activation starts rate billing after the Agreement start and the absolute term end falls within a billing period
- **THEN** the compute preset's `end.partialPeriod` is returned, so billing ends at the last boundary without running past the agreed maximum
- **AND** publication and acceptance refuse that preset where the servicing declaration does not list `returned`

## ADDED Requirements

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
The VM administrator interrupt verb MUST distinguish `interruption_kind=preemption` from `interruption_kind=failure`. Preemption MUST delegate the existing notice admission and journaled stop, requiring the accepted payee entitlement. Failure MUST end delivery and file delivery_end for both spot and on-demand, without a local rate-part payout remedy. An omitted kind MUST refuse for rate deals; once-only deals retain failure as their compatibility default. The free-text administrator reason remains required for hosted interruptions.

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

### Requirement: Canonical rate buyer end preserves service during notice
The buyer half MUST normally submit rate stop at the payment authority and send hint, allowing delivery until effective stop reaches end service through watch. It MUST reserve end_delivery for explicit immediate surrender or the unreachable-payment-authority delivery_end(cause=payer) case path. Immediate surrender MUST disclose that paid notice may outlast service.

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
