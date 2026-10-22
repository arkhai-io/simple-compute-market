## ADDED Requirements

### Requirement: Authority events come from the named authority

An authority event (`start`, `notice`, `stop`, `reverse`, `dispute`, `concede`, or a stop the authority applies itself) MUST be read from the authority the committed agreement names. It MUST carry `negotiation_id`, `commitment_ref`, `kind`, `actor`, `at`, `cause`, `sequence`, and the authority's record reference. The lifecycle layer MUST treat the commitment reference as opaque.

#### Scenario: A stop is recorded

- **WHEN** the payments service records a payer stop on a hosted deal
- **THEN** the seller's `watch` yields it with the payer as actor, the authority's sequence number, and its record reference

### Requirement: Peer messages are hints until the authority confirms them

A peer message (`commit`, `hint`) MUST be buyer-to-seller and MUST be kept as evidence. It MUST NOT change lifecycle state until a read of the authority confirms what it reports.

#### Scenario: A forged hint arrives

- **WHEN** a seller receives a `hint` that the buyer stopped, and the authority's record shows no stop
- **THEN** the seller keeps the hint as evidence and continues service unchanged

#### Scenario: A hint brings a read forward

- **WHEN** a seller receives a `hint` and the authority's record shows a stop
- **THEN** end service runs from the authority's stop record, not from the hint

### Requirement: The early-termination clause is part of the selected option

A settlement option MAY carry an `early_termination` object in its `params` with `version`, `regime`, `entitlements` keyed by initiator (`payer`, `payee`, each with `notice_seconds` and `settles_through`), `exposure_seconds`, `max_term_seconds`, and an optional `concession`. The shared lifecycle codec MUST decode it, so it is part of the Agreement bytes and the option ID.

#### Scenario: A clause changes the option ID

- **WHEN** a seller changes an option's `notice_seconds` and republishes
- **THEN** the option has a new option ID

### Requirement: Builders emit the clause only where it binds

An option builder MUST emit the clause only for a part shape and arbiter whose committed form encodes its entitlements, its authority-applied stops, and its concession floor.

#### Scenario: A hosted once option is built

- **WHEN** a storefront builds an `arkhai.payments.v1` option with a single `once` part
- **THEN** the option carries no `early_termination` clause

#### Scenario: An Alkahest option is built

- **WHEN** a storefront builds an Alkahest option with any arbiter it supports today
- **THEN** the option carries no `early_termination` clause, and its release condition keeps its existing service terms

### Requirement: Malformed clauses are refused

An unknown `version`, `regime`, initiator key, or `settles_through` value MUST make a builder refuse to emit the option and a buyer refuse to select it. Empty `entitlements` MUST be refused at publication.

#### Scenario: A buyer meets an unknown regime

- **WHEN** a listing's option carries a clause whose `regime` the buyer client does not recognize
- **THEN** the buyer does not select that option and reports the unrecognized regime

### Requirement: Clause values agree with the Agreement and mechanism

A missing clause MUST mean no early-end entitlement, with the mechanism's default authorities for the part shape. `max_term_seconds` MUST equal the Agreement's `duration_seconds`. A mechanism with a reserve-ahead parameter MUST have it at least `exposure_seconds`.

#### Scenario: Reserve-ahead is below exposure

- **WHEN** a seller configures an option whose reserve-ahead is shorter than its clause's `exposure_seconds`
- **THEN** the builder refuses to emit the option and names both values

#### Scenario: Maximum term disagrees with the Agreement

- **WHEN** an accepted Agreement's `duration_seconds` differs from its option's `max_term_seconds`
- **THEN** the buyer refuses to commit

### Requirement: Entitlements are the stop authorities

A mechanism's stop authorities for a deal MUST be derived from the clause's entitlements and nothing else. An initiator without an entitlement MUST NOT be a stop authority. An exceptional end MUST be a dispute, not a stop. Funding exhaustion and the maximum term MUST be stops the authority applies with cause "terms", needing no entitlement. A payer stop at *t* MUST settle through *t* plus `exposure_seconds` when its entitlement says `stop+exposure`.

#### Scenario: A seller tries to stop an on-demand deal

- **WHEN** a seller submits `stop` on a deal whose clause has no `payee` entitlement
- **THEN** the authority rejects it and the outcome is `rejected`

### Requirement: A concession meets the clause's floor

A `concede` MUST end the deal at its stated end time and MUST give at least the clause's concession floor. The floor MUST be at least no charge after the end time and a refund of reserved but unserved funds. A concession giving less MUST be rejected by the authority.

#### Scenario: A seller concedes after hardware failure

- **WHEN** a seller concedes on the buyer's behalf with an end time and the floor's refund
- **THEN** the authority records a stop with cause authority, and end service ends delivery at that time

#### Scenario: A concession gives too little

- **WHEN** a concession would charge past its end time
- **THEN** the authority rejects it and billing continues unchanged

### Requirement: Notice is a scheduled stop

A seller reclaim with notice MUST be one `notice` command whose effective time is no earlier than now plus the entitlement's `notice_seconds`. The authority MUST apply the stop at the effective time without a further seller command. The adapter MUST refuse a notice with an earlier effective time before contacting the authority.

#### Scenario: The seller goes silent after notice

- **WHEN** a seller posts a notice and sends nothing further
- **THEN** the authority stops the deal at the notice's effective time with cause payee

### Requirement: Lifecycle commands have defined outcomes

`submit` MUST take a command `{negotiation_id, kind, operation_key, at, payload}`, never an event. Its outcome MUST be `accepted` with the authority record, `rejected` with the authority's reason, `pending`, or `unknown`. An `unknown` outcome MUST be resolved by `read`. The operation key MUST be passed to the authority as its idempotency key; a retry with the same key and different content MUST be rejected locally.

#### Scenario: A stop's response is lost

- **WHEN** a buyer's `stop` times out in transport
- **THEN** the outcome is `unknown`, and a retry with the same operation key returns the one recorded stop

#### Scenario: A retry changes content

- **WHEN** a command is retried with the same operation key and a different `at`
- **THEN** it is rejected without contacting the authority

### Requirement: The buyer half hides the mechanism

The buyer half MUST offer `submit` and `read(negotiation_id)` without the caller branching on mechanism.

#### Scenario: A buyer reads a deal with no lifecycle adapter

- **WHEN** a buyer reads an Alkahest deal through the buyer half
- **THEN** the outcome is `rejected` naming the mechanism, in the same shape as any other outcome

### Requirement: The seller half lists deals

The seller half MUST offer `submit`, `read`, `list`, and `watch`. `list` MUST return bounded pages with a continuation token. Each deal MUST carry its negotiation ID, commitment reference, domain, mechanism, entitlements, lifecycle state (unstarted, running, ending, ended, repair required), and current deadline.

#### Scenario: A seller lists its deals

- **WHEN** a seller with no committed deals calls `list`
- **THEN** it receives an empty page, not an error

### Requirement: Adapters resolve per mechanism and arbiter

Adapters MUST resolve through the domain's role table by negotiation ID and the Agreement's mechanism, not through the conditional-escrow port. Within a mechanism they MUST resolve by arbiter, and by oracle or oracle schema for oracle-backed arbiters.

#### Scenario: A mechanism has no adapter for an event kind

- **WHEN** a party submits a kind the deal's adapter does not support
- **THEN** the outcome is `rejected` with a reason naming the unsupported kind, and no authority is contacted

### Requirement: Watch replays from a durable cursor

`watch(negotiation_id)` MUST yield the current state first, then each later authority event and deadline change in the authority's sequence order. Its cursor MUST be stored durably per deal and advanced only after end service records the resulting effect. A restart MUST resume from the stored cursor.

#### Scenario: The storefront restarts mid-deal

- **WHEN** the storefront restarts after the authority recorded a stop it had not yet acted on
- **THEN** `watch` yields that stop again and end service ends delivery once

### Requirement: Lifecycle routes are authenticated per role

The storefront MUST expose the seller half's `submit`, `read`, and `list` through the administrator-principal contract, and a buyer route for `commit` and `hint` authenticated as the negotiation's buyer principal. The storefront MUST NOT relay a buyer's authority command.

#### Scenario: Another principal sends commit

- **WHEN** a principal other than the negotiation's buyer sends `commit` for it
- **THEN** the storefront rejects it without reading the authority

#### Scenario: The admin interrupt route ends a hosted deal

- **WHEN** an administrator interrupts a hosted deal through the VM admin route
- **THEN** the route submits through the seller half, and the lease changes only through end service

### Requirement: Only the payee starts a hosted deal, after provisioning

For hosted payments `start` MUST be the payee's alone. The seller MUST read the authority, provision, read again, and then submit `start`. If the payer stopped meanwhile or `start` is rejected, end service MUST terminate the provisioned resource. A crash between provisioning and `start` MUST resume from the journal with the same decision.

#### Scenario: The buyer stops during provisioning

- **WHEN** the buyer's stop is recorded after the seller's first read and before `start`
- **THEN** the seller does not start the deal and end service terminates the provisioned resource

### Requirement: End service takes every source and keeps the earliest end

End service MUST take "end delivery at *T*" with actor, cause, and source. Its sources MUST be authority events through `watch` and local delivery decisions: bare-metal buyer teardown, a failed start, and terminal settlement. Repeated requests for one deal MUST keep the earliest *T*. A local decision MUST NOT move money.

#### Scenario: A buyer tears down bare metal

- **WHEN** a bare-metal buyer requests teardown through the storefront
- **THEN** end service terminates the lease with the buyer as actor, the request is kept as evidence, and no payment command is sent

#### Scenario: Two ends race

- **WHEN** end service receives a funded-through deadline and then an earlier stop
- **THEN** the lease ends at the earlier stop's time

### Requirement: End service terminates or truncates, and journals each effect

When *T* is now or past, end service MUST terminate the lease; otherwise it MUST truncate it to *T*. Each effect MUST be journaled and retried until done.

#### Scenario: A stop arrives after its effective time

- **WHEN** end service receives a stop whose time has passed
- **THEN** it terminates the lease rather than truncating it to a past time

### Requirement: Polling stays within exposure

A storefront MUST refuse to start lifecycle loops whose polling interval exceeds the smallest `exposure_seconds` among its active deals.

#### Scenario: Polling exceeds exposure

- **WHEN** a storefront's lifecycle polling interval is longer than an active deal's `exposure_seconds`
- **THEN** its lifecycle loops refuse to start and name the deal and both values

### Requirement: Evidence is keyed by negotiation

A party MUST keep evidence as exact bytes in a store separate from replay state, keyed by negotiation ID. The commitment reference MUST be recorded once known, and a superseded commitment MUST be kept and marked superseded.

#### Scenario: Replay state is pruned

- **WHEN** authenticated replay state for an accepted negotiation is pruned
- **THEN** the acceptance envelope remains in the evidence store with its exact bytes

### Requirement: Each party keeps its commitment envelopes and regime records

The buyer MUST keep the seller's signed acceptance with its proof headers and exact body; the seller MUST keep the buyer's signed accepting request. Both MUST keep the peer messages they sent or received and the authority records their regime names.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the proof headers and exact body before committing

### Requirement: Evidence is kept for the dispute window

Records MUST be kept until the configured dispute window after the deal's last authority event, then deleted. The window MUST be disclosed with the listing.

#### Scenario: The dispute window passes

- **WHEN** a deal's last authority event is older than the dispute window
- **THEN** its evidence records are deleted

### Requirement: A dispute is one case payload

A `dispute` or `concede` MUST carry one case: the commitment reference, the committed agreement or where to fetch it, the clause, the claim, the requested outcome, and ordered evidence items. Each item MUST be an evidence-store record with kind, producer, time, content digest, and the exact original bytes or the authority's signed record. A party MUST be able to export the case as one bundle.

#### Scenario: A buyer files a dispute

- **WHEN** a buyer files a dispute through the buyer half
- **THEN** the case payload is built from its evidence store, and each item carries the exact bytes it received

### Requirement: Refund is a reverse command; reconciliation is a backstop

A seller's refund of a hosted payment MUST be a `reverse` command through the seller half. The reconciliation pass MUST remain, finding commitments a buyer never reported, and MUST NOT be required for safety.

#### Scenario: A buyer never sends commit

- **WHEN** a buyer approves a mandate and never sends `commit`
- **THEN** no funds move, and the reconciliation pass may find and serve the deal
