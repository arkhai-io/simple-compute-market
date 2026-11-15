## ADDED Requirements

### Requirement: Both compute storefronts mount the administrator interrupt route

The VM and bare-metal storefronts MUST each serve `POST /api/v1/admin/deals/{negotiation_id}/interrupt` for a committed `arkhai.payments.v1` deal, authenticated as the storefront's administrator under the canonical storefront client's `admin_interrupt_deal` operation, and MUST carry out the interruption through `kit/deal-servicing`'s seller-half classification, ending delivery through end service. A refusal of that classification MUST answer 409 with nothing recorded. A hosted interruption takes effect at receipt, so the route MUST refuse a caller-supplied interruption time. The canonical client's sync and async `admin_interrupt_deal` MUST expose the interruption kind and operation key.

#### Scenario: A bare-metal administrator preempts a spot deal

- **GIVEN** a committed bare-metal rate deal whose accepted option grants a payee entitlement
- **WHEN** the administrator interrupts it with kind preemption through the canonical storefront client
- **THEN** the route answers `notice_stop` with the authority's outcome, and the read shows the pending stop
- **AND** no end or filing is recorded

#### Scenario: A bare-metal administrator reports a failure

- **WHEN** the administrator interrupts a committed bare-metal deal with kind failure and a reason
- **THEN** the route answers `delivery_end_filing`, the end is recorded with the administrator's reason, and a `delivery_end` filing is journaled with cause payee

#### Scenario: An interruption the classification refuses

- **WHEN** a rate interruption omits its kind, or an unentitled deal is preempted
- **THEN** either storefront's route answers 409 and records nothing

## MODIFIED Requirements

### Requirement: Delivery is driven one deal at a time and reports where it stands

The library MUST expose `drive(negotiation_id)`, returning one of `waiting(wake_at)`, `pending`, `repair_required(reason)`, `available`, `converged` or `ended`. Each call MUST reconcile the deal's recorded state before acting and MUST be safe to repeat. A fulfillment hook MUST map `available` and `converged` to fulfilled, `waiting`, `pending` and `repair_required` to deferred, and `ended` to failed only once the end hand-off is durable.

`drive` MUST fail closed on state it cannot read. A deal with no servicing delivery record or no verified settlement evidence MUST be `repair_required(no_accepted_deal)` with nothing written. An accepted deal with no progress row is a first drive, whose row MUST be created under admission for `reserve`. An unknown stored step, a malformed or conflicting recorded identity, a port result of the wrong kind or an empty fulfillment result MUST be `repair_required` and MUST NOT lead to a reserve, dispatch, activation or availability on the deal. The reason MUST be one of `no_accepted_deal`, `timing_invalid`, `progress_unreadable`, `domain_result_invalid`, `activation_unexplained`, `site_unanswered` or `rate_servicing_unavailable`. Every `repair_required` and `ended` outcome MUST carry the deal's recorded reservation and fulfillment identities and the reference of the authority evidence it rests on.

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

### Requirement: Protected steps are authorized and admitted

Before commit, dispatch, billing start and disclosure the path MUST call end service's `authorize_delivery` for that phase, and before activation it MUST pass end service's admission for `activate`. A pending or unknown outcome MUST leave the deal pending and resolve the same attempt; a financial allow MUST NOT override a due local end; a mechanism with no adapter MUST NOT be allowed. A refusal carrying end service's `rate_servicing_unavailable` code, when no end is due, MUST be `repair_required(rate_servicing_unavailable)` with nothing reserved; any other refusal when no end is due MUST be `repair_required(no_accepted_deal)`.

#### Scenario: An end wins before dispatch

- **WHEN** an end is recorded after the dispatch authorization was read but before dispatch
- **THEN** the stale admission fails, nothing is dispatched, and the deal goes to the end hand-off

#### Scenario: An authorization outcome is unknown

- **WHEN** the payment adapter cannot establish its authorization outcome
- **THEN** the deal stays pending and the next drive resolves the same authorization

#### Scenario: End service refuses a rate deal at commit

- **WHEN** end service refuses a deal's commit with the code `rate_servicing_unavailable`
- **THEN** `drive` returns `repair_required(rate_servicing_unavailable)`, no capacity is reserved, and the next drive asks again

### Requirement: An undelivered deal is handed to the end operation with classified evidence

Before availability, a site refusal, provisioning failure, elapsed window or lapsed activation MUST enter end service's `record_end`; a refusal by end service's `authorize_delivery` is handled as "Protected steps are authorized and admitted" says. Delivery MUST supply the actor, cause and source, the Agreement start, the fixed failure-observation time, the resource identities and verified evidence, and MUST NOT classify by event kind, compute amounts or send a payment stop or reverse. Any site refusal of the commit after a reservation was made, other than the refused commit of a hold verified lapsed, MUST be recorded as seller failure before dispatch, with its filing at the Agreement start and the reservation released through end service's no-dispatch path under one key.

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
