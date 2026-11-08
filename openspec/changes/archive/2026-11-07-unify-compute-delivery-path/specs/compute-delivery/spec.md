## ADDED Requirements

### Requirement: Compute storefronts deliver through one family path behind domain ports

The VM and bare-metal storefronts MUST deliver through the compute-family library at `domains/compute/delivery`, which owns the delivery order and keeps no table of its own. Each storefront MUST supply a `DeliveryProgress` port over its existing progress row and a `ComputeDeliveryDomain` port for its claim, exact fulfillment request, ready evidence and continuation. The library MUST NOT import a storefront and MUST NOT branch on a domain or mechanism identity. API-credit issuance MUST remain outside it.

#### Scenario: Both domains run the same order

- **WHEN** a VM deal and a bare-metal deal each settle with verified evidence
- **THEN** each storefront's fulfillment hook calls the same library operation with its own two port implementations
- **AND** each deal's reservation and fulfillment identities and activation instant are recorded in that domain's own progress row

#### Scenario: API credits delivers

- **WHEN** an API-credit deal reaches issuance
- **THEN** its existing path runs, with no compute activation or delivery-path call

### Requirement: Delivery is driven one deal at a time and reports where it stands

The library MUST expose `drive(negotiation_id)`, returning one of `waiting(wake_at)`, `pending`, `repair_required(reason)`, `available`, `converged` or `ended`. Each call MUST reconcile the deal's recorded state before acting and MUST be safe to repeat. A fulfillment hook MUST map `available` and `converged` to fulfilled, `waiting`, `pending` and `repair_required` to deferred, and `ended` to failed only once the end hand-off is durable.

`drive` MUST fail closed on state it cannot read. A deal with no servicing delivery record or no verified settlement evidence MUST be `repair_required(no_accepted_deal)` with nothing written. An accepted deal with no progress row is a first drive, whose row MUST be created under admission for `reserve`. An unknown stored step, a malformed or conflicting recorded identity, a port result of the wrong kind or an empty fulfillment result MUST be `repair_required` and MUST NOT lead to a reserve, dispatch, activation or availability on the deal. The reason MUST be one of `no_accepted_deal`, `timing_invalid`, `progress_unreadable`, `domain_result_invalid`, `activation_unexplained` or `site_unanswered`. Every `repair_required` and `ended` outcome MUST carry the deal's recorded reservation and fulfillment identities and the reference of the authority evidence it rests on.

#### Scenario: A domain worker resumes a deal

- **WHEN** a storefront's recovery worker calls `drive` for a deal interrupted after dispatch
- **THEN** the path polls the recorded fulfillment and continues from that step without scheduling or beginning another

#### Scenario: Repair-required stays visible

- **WHEN** a deal's accepted timing is missing or its site activation answer is unexplained
- **THEN** `drive` returns `repair_required` with the reason, the recorded identities and the authority evidence it rests on, and the deal keeps its recorded resource

#### Scenario: A deal that was never accepted is driven

- **WHEN** `drive` is called for a negotiation with no servicing delivery record
- **THEN** it returns `repair_required(no_accepted_deal)` and nothing is reserved or written

#### Scenario: A progress row holds an unknown step

- **WHEN** a deal's progress row records a step the library does not know
- **THEN** `drive` returns `repair_required(progress_unreadable)` with the recorded identities, and no reserve or fulfillment is begun

#### Scenario: A fulfillment result is empty

- **WHEN** the domain port returns an empty result for the recorded fulfillment
- **THEN** `drive` returns `repair_required(domain_result_invalid)`, the deal is not recorded available, and no replacement fulfillment is begun

### Requirement: Delivery commits the Agreement window

Every commit and recovery MUST use the Agreement's `start_utc` and `start_utc + duration_seconds` under the same reservation identity. Delivery MUST NOT substitute the current time for a start or a default for a duration; missing or conflicting timing MUST be repair-required without replacing an existing resource. Late settlement MUST shorten service and MUST NOT move the end.

#### Scenario: Settlement completes late

- **GIVEN** an Agreement from 12:00 through 14:00
- **WHEN** settlement completes at 12:30
- **THEN** both domains commit 12:00 through 14:00, on the first attempt and on every retry

#### Scenario: Recovery lacks timing

- **WHEN** an unfinished delivery has no valid accepted start or duration
- **THEN** it is repair-required with its recorded resource, not a replacement or a guessed hour

### Requirement: A deal that starts later waits for its start

Capacity MAY be committed at settlement before the Agreement start. Dispatch, activation, billing start and disclosure MUST NOT happen before `start_utc`. Before then `drive` MUST return `waiting` with the start as its wake time, release the deal's convergence claim, and leave the deal to the domain's existing recovery worker, which MUST recheck admission when the deal is driven again.

#### Scenario: A forward reservation waits

- **WHEN** an Agreement starting at 12:00 settles at 10:00
- **THEN** the reservation is committed for 12:00 through 14:00 at 10:00 and nothing is dispatched
- **AND** at 12:00 the domain's worker drives the deal, admission passes and dispatch begins

#### Scenario: An end is recorded while a deal waits

- **WHEN** the buyer's end is recorded at 11:00 for a deal waiting for a 12:00 start
- **THEN** at 12:00 admission refuses and nothing is dispatched

### Requirement: Protected steps are authorized and admitted

Before commit, dispatch, billing start and disclosure the path MUST call end service's `authorize_delivery` for that phase, and before activation it MUST pass end service's admission for `activate`. A pending or unknown outcome MUST leave the deal pending and resolve the same attempt; a financial allow MUST NOT override a due local end; a mechanism with no adapter MUST NOT be allowed.

#### Scenario: An end wins before dispatch

- **WHEN** an end is recorded after the dispatch authorization was read but before dispatch
- **THEN** the stale admission fails, nothing is dispatched, and the deal goes to the end hand-off

#### Scenario: An authorization outcome is unknown

- **WHEN** the payment adapter cannot establish its authorization outcome
- **THEN** the deal stays pending and the next drive resolves the same authorization

### Requirement: Activation precedes billing start and availability

After ready evidence and admission for `activate`, and no earlier than the Agreement start, the path MUST call `CapacityEffects.activate_lease` for the binding's site. On success it MUST record the site's `activated_at_utc` once through the progress port and adopt the lease's current end; it MUST NOT extend or restore an end. On a 409 it MUST read the lease through the compute contract's `LeaseView`, entering the end hand-off for a `releasing` or `released` lease and repair-required otherwise; on a 404, or when the site cannot be asked or answers unsigned, the deal MUST be repair-required and MUST NOT be treated as activated.

#### Scenario: A truncation precedes activation

- **WHEN** end service truncates a lease to 13:00 before activation
- **THEN** activation records the site's instant and the deal's lease ends at 13:00

#### Scenario: Expiry claims the lease first

- **WHEN** activation is refused with 409 and `LeaseView` shows the lease `releasing`
- **THEN** no billing start is issued and the deal goes to the end hand-off

#### Scenario: The site cannot activate

- **WHEN** the activation call reaches no site, or is answered without a valid signature
- **THEN** the deal is repair-required, its activation instant stays null, and the call is retried later

### Requirement: Billing start uses end service's one intent

After activation and a `start` authorization the path MUST call `begin_billing` with a stable operation key and a `DeliveryEvidence` naming the negotiation, commitment, reservation and fulfillment, an `ActivatedDeliveryRef` whose reference is the capacity reservation identity and whose instant is the site's, and the domain's ready evidence. Delivery MUST NOT keep a billing intent of its own; recovery MUST repeat the call under the same key.

#### Scenario: A billing-start acknowledgement is lost

- **WHEN** the payment authority accepted the start but the storefront restarted before recording the result
- **THEN** the next drive calls `begin_billing` under the same key and adopts the recorded outcome without a second start

#### Scenario: A once-only deal starts billing

- **WHEN** a prepaid or Alkahest deal reaches billing start
- **THEN** its once-only adapter returns a no-op and no payment start is created

### Requirement: Availability and convergence have explicit meanings

Available MUST mean readiness, activation, billing start and disclose authorization are durable, without any buyer read. Converged MUST additionally mean the domain's continuation — an Alkahest claim or evidence publication — is acknowledged, or that the domain has none.

An end due after availability MUST NOT stop the continuation, which settles service already delivered. Every drive of an available deal MUST run the continuation and then reconcile a due end: while the continuation is unacknowledged and an end is due, `drive` MUST return `pending`; once it is acknowledged, or the domain has none, it MUST return `ended`, never `available` or `converged`.

#### Scenario: A buyer never reads

- **WHEN** a deal's ready evidence, activation, billing start and disclose authorization complete
- **THEN** `available` is recorded although the buyer has made no request

#### Scenario: Evidence publication is pending

- **WHEN** a deal is available but publishing its Alkahest evidence failed
- **THEN** `drive` returns `available`, not `converged`, and retries the publication without another fulfillment

#### Scenario: A buyer ends an available deal before its claim is acknowledged

- **WHEN** a buyer's end falls due for an available Alkahest deal whose claim is not yet acknowledged
- **THEN** the next drive runs the claim again and returns `pending`
- **AND** the drive after the claim is acknowledged returns `ended`, with no delivery failure recorded beside the buyer's end

### Requirement: Every step recovers the same resource

A lost acknowledgement at any step MUST be recovered without a second resource: reserve through the site's placement key, dispatch through the recorded dispatch step and fulfillment identity, activation by repeating it for the same reservation, and billing start under the same key. The progress port MUST record the dispatch before `begin_fulfillment` is called.

#### Scenario: A reserve acknowledgement is lost

- **WHEN** the storefront restarts after the site reserved capacity and before the identity was recorded
- **THEN** the next drive's reserve under the same placement key returns the same reservation

#### Scenario: A recovered reservation has been released

- **WHEN** the replayed reservation comes back released
- **THEN** the deal is repair-required or goes to the end hand-off, and no fresh reservation is placed

### Requirement: A live acceptance hold is adopted

When the domain supplies an accepted acceptance-time hold, delivery MUST commit that hold under the deal before placing any other reservation. A commit with no answer or an unsigned answer MUST be retried and MUST NOT lead to a fresh reserve. Only a refused commit of a hold verified lapsed — its replay under `<negotiation_id>:hold` returns it expired or released, or, for a hold carrying no placement key, its recorded expiry has passed — MAY be replaced by a reserve under `<negotiation_id>:settlement`. A refused commit of a live hold MUST be handled as a commit refused after reservation.

#### Scenario: A live hold is committed

- **WHEN** a VM deal settles while its acceptance hold is live
- **THEN** delivery commits that hold for the Agreement window and records it as the deal's reservation, and no second reservation is placed

#### Scenario: A hold commit's answer is lost

- **WHEN** the site commits the hold but the answer never reaches the storefront
- **THEN** the next drive retries the same commit and adopts the hold, and no reserve under `:settlement` is made

### Requirement: An undelivered deal is handed to the end operation with classified evidence

Before availability, a refusal, provisioning failure, elapsed window or lapsed activation MUST enter end service's `record_end`. Delivery MUST supply the actor, cause and source, the Agreement start, the fixed failure-observation time, the resource identities and verified evidence, and MUST NOT classify by event kind, compute amounts or send a payment stop or reverse. Any site refusal of the commit after a reservation was made, other than the refused commit of a hold verified lapsed, MUST be recorded as seller failure before dispatch, with its filing at the Agreement start and the reservation released through end service's no-dispatch path under one key.

#### Scenario: A lawful end wins before availability

- **WHEN** the buyer's end request is recorded before the deal is available
- **THEN** delivery supplies it beside the never-delivered basis and acts on the classification end service returns, filing no self-penalty for a lawful end

#### Scenario: A commit is refused after reservation

- **WHEN** the site refuses the commit of a reservation the deal already holds
- **THEN** a seller-failure end with its filing is recorded, nothing is dispatched, and the reservation is released through the no-dispatch path
- **AND** a restart before the release is acknowledged retries the same release and places no second reservation

#### Scenario: Settlement arrives after the window

- **WHEN** settlement completes after the Agreement's end
- **THEN** nothing is dispatched and never-delivered evidence is supplied, with no buyer fault inferred from the lateness

### Requirement: A deal ended before delivery settles the wait as ended

A compute storefront's settlement status MUST report `ended` for a deal whose end took effect before it was delivered, and its administrator's settle wait MUST take `ended` as terminal beside `ready` and `failed`, returning at once rather than polling to its deadline. An end recorded for later MUST NOT be reported as `ended` before it takes effect.

#### Scenario: A placement finds no capacity

- **WHEN** a settlement placement finds no capacity, the deal ends before delivery, and an administrator then waits on its settlement
- **THEN** the wait returns at once with status `ended`, and nothing was begun

### Requirement: Credentials are disclosed only through a live, admitted read

A buyer's credential read MUST require `available` or `converged`, the Agreement start reached and end service's admission; it MUST fetch from provisioning's fulfillment result outside any transaction and recheck the revision and due end before the response is signed, discarding the fetched material if an end won. It MUST NOT read a payment snapshot. A credential-capable route's exact retry MUST run this read again. Because a recorded replay body names no route, each compute storefront MUST clear access material from every recorded body by its shape when it upgrades, leaving each record's status and completion in place.

#### Scenario: An end wins during the fetch

- **WHEN** an end is admitted after the fetch begins but before the response is authorized
- **THEN** the fetched material is discarded and disclosure is refused

#### Scenario: A credential read is retried after an end

- **WHEN** a buyer repeats an exact authenticated credential request after a locally admitted end
- **THEN** the read runs again and is refused, and no earlier response body is returned

#### Scenario: A bare-metal storefront upgrades with recorded access responses

- **WHEN** a bare-metal storefront starts on a database whose replay records hold a body with `method` `ssh` and its host, port and username
- **THEN** that body loses its host, port and username, and the record keeps its status and remains a completed outcome

#### Scenario: A response is already in flight

- **WHEN** a response was authorized before an end was admitted
- **THEN** no claim is made to retract it, and physical teardown revokes the disclosed access
