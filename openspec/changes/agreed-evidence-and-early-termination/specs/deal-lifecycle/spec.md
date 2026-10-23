## ADDED Requirements

### Requirement: Authority events come from the named authority

An authority event MUST be read from the authority the committed agreement names, and MUST record what happened to one part of the deal. It MUST carry `negotiation_id`, `commitment_ref`, `part`, `kind`, `actor`, `at`, `cause`, `sequence`, and the authority's record reference. The lifecycle layer MUST treat the commitment reference as opaque.

#### Scenario: A start is recorded

- **WHEN** the payments service records the payee's `start` of a hosted deal's `once` part
- **THEN** the seller's `watch` yields it with the part, the payee as actor, the authority's sequence number, and its record reference

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

#### Scenario: A seller concedes on a bonded once deal

- **WHEN** a seller concedes a dispute on a hosted deal with a `once` part and a `bond` part
- **THEN** the adapter sends a `reverse` of the `once` part for the case's requested outcome and a forfeit of the `bond` part

### Requirement: Lifecycle terms are part of the selected option

A settlement option MAY carry `adjudication` (`version`, `regime`), `early_termination` (`version`, `entitlements` keyed by `payer` or `payee` with `notice_seconds` and `settles_through`, `exposure_seconds`, `max_term_seconds`), and `bond` (`version`, `amount`) in its `params`. The shared codec MUST decode them, so they are part of the Agreement bytes and the option ID.

#### Scenario: A term changes the option ID

- **WHEN** a seller changes an option's bond amount and republishes
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

An unknown `version`, `regime`, initiator key, or `settles_through` value MUST make a builder refuse to emit the option and a buyer refuse to select it. Empty `entitlements`, and `early_termination` on an option with no stoppable part, MUST be refused at publication.

#### Scenario: A buyer meets an unknown regime

- **WHEN** a listing's option names a `regime` the buyer client does not recognize
- **THEN** the buyer does not select that option and reports the unrecognized regime

### Requirement: Term values agree with the Agreement and the seller's budget

`max_term_seconds` MUST equal the Agreement's `duration_seconds`. A mechanism with a reserve-ahead parameter MUST have it at least `exposure_seconds`. A storefront MUST refuse, at publication and at acceptance, an option whose `exposure_seconds` is below its polling interval plus its configured watchdog and teardown budget, and MUST refuse a configuration change that would put an active deal over its exposure.

#### Scenario: Exposure is below the servicing budget

- **WHEN** a storefront polls every 290 seconds with a 60-second teardown budget and an option declares 300 seconds of exposure
- **THEN** it refuses to publish the option and names the budget and the declared exposure

#### Scenario: Maximum term disagrees with the Agreement

- **WHEN** an accepted Agreement's `duration_seconds` differs from its option's `max_term_seconds`
- **THEN** the buyer refuses to commit

### Requirement: Entitlements are the stop authorities of stoppable parts

An adapter MUST make each initiator with an entitlement a `stop` authority of the option's stoppable parts, and nobody else. A part without a stop event MUST have no stop authorities.

#### Scenario: An on-demand option is derived

- **WHEN** an option's `early_termination` has a `payer` entitlement only
- **THEN** the payer is the only stop authority of its stoppable parts

### Requirement: A concession ends now and acts through each part

A `concede` MUST name an end time no later than now. The adapter MUST apply it through each affected part's events, forfeiting any `bond` part. A seller-filed concession's requested outcome for a `once` part MUST default to reversing the unserved share of the term by time.

#### Scenario: A concession names a future end

- **WHEN** a seller submits `concede` with an end time later than now
- **THEN** the adapter rejects it before contacting the authority

### Requirement: Lifecycle commands have defined outcomes

`submit` MUST take a command `{negotiation_id, kind, operation_key, at, payload}`, never an event. Its outcome MUST be `accepted` with the authority records, `rejected` with the reason, `pending`, or `unknown`. An `unknown` outcome MUST be resolved by `read`. Each part event's idempotency key MUST derive from the operation key; a retry with the same key and different content MUST be rejected locally.

#### Scenario: A reverse's response is lost

- **WHEN** a seller's `reverse` times out in transport
- **THEN** the outcome is `unknown`, and a retry with the same operation key returns the one recorded reversal

#### Scenario: A retry changes content

- **WHEN** a command is retried with the same operation key and a different `at`
- **THEN** it is rejected without contacting the authority

### Requirement: The buyer half hides the mechanism

The buyer half MUST offer `submit` and `read(negotiation_id)` without the caller branching on mechanism. `read` MUST return the deal's lifecycle state and authority events, or `rejected` when the deal's mechanism has no adapter.

#### Scenario: A buyer reads a deal with no lifecycle adapter

- **WHEN** a buyer reads an Alkahest deal through the buyer half
- **THEN** the result is `rejected`, naming the mechanism

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token. Each deal MUST carry its negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state (unstarted, running, ending, ended, repair required), and current deadline.

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

### Requirement: Adapters resolve per mechanism and arbiter

Adapters MUST resolve through the domain's role table by negotiation ID and the Agreement's mechanism, not through the conditional-escrow port. Within a mechanism they MUST resolve by arbiter, and by oracle or oracle schema for oracle-backed arbiters.

#### Scenario: A mechanism has no adapter for a command

- **WHEN** a party submits a kind the deal's adapter does not support
- **THEN** the outcome is `rejected` with a reason naming the unsupported kind, and no authority is contacted

### Requirement: Watch replays from a durable cursor

`watch(negotiation_id)` MUST yield the current state first, then each later authority event and deadline change in the authority's sequence order. Its cursor MUST be stored durably per deal and advanced only after end service records the resulting effect. A restart MUST resume from the stored cursor.

#### Scenario: The storefront restarts mid-deal

- **WHEN** the storefront restarts after the authority recorded a reversal it had not yet acted on
- **THEN** `watch` yields that reversal again and its effect is recorded once

### Requirement: Lifecycle routes are authenticated per role

The storefront MUST expose the seller half's `submit`, `read`, and `list` through the administrator-principal contract. The VM and bare-metal storefronts MUST expose a buyer route for `commit` and `hint`, authenticated as the negotiation's buyer principal, with signed responses. The storefront MUST NOT relay a buyer's authority command.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal through the VM admin route
- **THEN** the route submits through the seller half, and the lease changes only through end service

### Requirement: Only the payee starts a hosted deal, after provisioning

For hosted payments `start` MUST be the payee's alone. The seller MUST read the authority, provision, read again, and then submit `start`. If the payer stopped meanwhile, `start` is rejected, or provisioning has not finished by the Agreement's `start_utc + max_term_seconds`, end service MUST terminate the provisioned resource. A crash between provisioning and `start` MUST resume from the journal with the same decision.

#### Scenario: Start is rejected after provisioning

- **WHEN** the authority rejects the seller's `start` after the VM is provisioned
- **THEN** the seller does not retry the start, and end service terminates the provisioned resource

### Requirement: End service keeps the earliest final request

End service MUST take final requests, "end delivery at *T*" with actor, cause, and source, from authority stops through `watch` and from local delivery decisions: bare-metal buyer teardown, a failed start, and terminal settlement. Repeated final requests for one deal MUST keep the earliest *T*. A local decision MUST NOT move money.

#### Scenario: A buyer tears down bare metal

- **WHEN** a bare-metal buyer requests teardown through the storefront
- **THEN** end service terminates the lease with the buyer as actor, the request is kept as evidence, and no payment command is sent

### Requirement: Funding is a renewable timer

End service MUST keep a funded-through deadline as a local timer that advances with each deadline change, and MUST issue a final request only when the timer expires without renewal.

#### Scenario: Funding advances

- **WHEN** a deal funded through 12:05 is funded through 12:10 before 12:05
- **THEN** the lease is not truncated, and the timer moves to 12:10

### Requirement: End service terminates or truncates, and journals each effect

When *T* is now or past, end service MUST terminate the lease; otherwise it MUST truncate it to *T* at one-second precision or finer. Each effect MUST be journaled and retried until done. A shortfall in the exposure budget at runtime MUST only warn and MUST NOT stop the lifecycle loops.

#### Scenario: A stop arrives after its effective time

- **WHEN** end service receives a stop whose time has passed
- **THEN** it terminates the lease rather than truncating it to a past time

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded. The buyer's store MUST be the buyer-side lifecycle kit's, beside the buyer profile; the storefront's MUST be the servicing kit's.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

### Requirement: Each party keeps its commitment envelopes and authority records

The buyer MUST keep the seller's signed acceptance with its proof headers and exact body before committing; the seller MUST keep the buyer's signed accepting request. Both MUST keep the peer messages they sent or received and the authority records they receive.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the proof headers and exact body before committing

### Requirement: Evidence outlives the deal and its disputes

Records MUST be kept while the deal, its physical recovery, or any dispute on it is open, and for the dispute window after the last of these closes. An accepted negotiation never committed MUST be kept for the window after its acceptance expires. The buyer MUST apply the window the listing published.

#### Scenario: A long deal passes the window

- **WHEN** a running deal's last authority event is older than the dispute window
- **THEN** its evidence records are kept

#### Scenario: A dispute stays open

- **WHEN** a dispute on an ended deal remains unresolved past the window
- **THEN** its evidence records are kept until the window after its resolution

### Requirement: A dispute is one case payload

A `dispute` or `concede` MUST carry one case: the commitment reference, the committed agreement or where to fetch it, the terms, the claim, the requested outcome, and ordered evidence items. Each item MUST be an evidence-store record with kind, producer, time, content digest, and the exact original bytes or the authority's signed record. A party MUST be able to export the case as one bundle.

#### Scenario: A buyer files a dispute

- **WHEN** a buyer files a dispute through the buyer half
- **THEN** the case payload is built from its evidence store, and each item carries the exact bytes it received

### Requirement: Refund is a reverse command; reconciliation finds unreported commitments

A seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain and find commitments a buyer never reported.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** the reconciliation pass finds the commitment and the seller serves or reverses it
