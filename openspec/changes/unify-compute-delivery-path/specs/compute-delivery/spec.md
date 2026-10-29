## ADDED Requirements

### Requirement: Compute storefronts share one protected delivery path

VM and bare-metal storefronts MUST compose one compute-family implementation of capacity commit, dispatch, start authorization, activation and availability. Domain preparation, result codecs and authenticated route surfaces MUST remain injected contributions. The family path MUST consume selected-stage evidence and injected lifecycle ports rather than branch on mechanism IDs or import domain/storefront implementations.

#### Scenario: Both compute domains deliver

- **WHEN** a VM or bare-metal deal reaches verified commitment evidence
- **THEN** its storefront uses the same protected-transition implementation
- **AND** only its domain preparation, result interpretation and route model differ

#### Scenario: An API-credit deal delivers

- **WHEN** an API-credit deal reaches delivery
- **THEN** its existing issuance path is used without compute lease or activation requirements

### Requirement: Delivery commits the Agreement window

Compute delivery MUST derive its lease window from the accepted Agreement's `start_utc` and `duration_seconds`, and MUST repeat that exact window and reservation identity on recovery. It MUST NOT substitute `now` or a default duration. Missing or conflicting timing MUST be reported as repair-required without replacing an existing resource. An elapsed window before availability MUST take the undelivered handoff.

#### Scenario: Settlement completes late but before the end

- **GIVEN** an Agreement starting at 12:00 with a two-hour duration
- **WHEN** settlement completes at 12:30 in either compute domain
- **THEN** delivery commits 12:00 through 14:00, not 12:30 through 14:30
- **AND** a retry repeats 12:00 through 14:00

#### Scenario: Settlement completes after the end

- **WHEN** commitment is observed after the Agreement window has elapsed with nothing dispatched
- **THEN** no new fulfillment is dispatched
- **AND** delivery takes the undelivered handoff

#### Scenario: Recovery lacks timing

- **WHEN** an unfinished delivery has no valid accepted duration
- **THEN** it is repair-required rather than assigned an hour
- **AND** an existing fulfillment is retained by identity, not replaced

### Requirement: Authorization is recorded per protected transition

The family path MUST call `authorize_delivery(deal, phase)` before each `commit`, `dispatch`, `start` and initial-availability `disclose` attempt, not every later credential read. It MUST record outcome, reason, operation identity and evidence references durably before using the result. Each attempt MUST also use end service's admission port under the lifecycle contract's final-request ordering, including reconciliation and restart. A financial allow MUST NOT bypass a local end.

#### Scenario: A prepaid deal is admitted

- **WHEN** a prepaid deal passes its selected stage's evidence checks and local end admission
- **THEN** the default financial hook records allow without issuing a payment start
- **AND** the path still checks end admission at later protected transitions

#### Scenario: An end wins before dispatch

- **WHEN** end service has admitted a due final request before the dispatch attempt
- **THEN** the path does not dispatch even if its financial hook previously allowed commit
- **AND** it uses end service's existing no-dispatch recovery path

#### Scenario: Authorization is uncertain

- **WHEN** the hook reports pending or an unknown authority result
- **THEN** the protected transition remains pending
- **AND** recovery resolves the same operation rather than assuming refusal or success

### Requirement: The rate hook uses authority records through adapters

The rate hook MUST be injected by rate servicing, not implemented in the compute path. Its evidence contract MUST support verified commitment/reservation and start/stop records through the payment adapter, including pending stops' effective times. At `start` the path MUST supply verified provisioning evidence without credentials. The hook MUST NOT require a billing horizon, payee vouch or a lease renewal.

#### Scenario: A provisioned rate deal starts

- **WHEN** provisioning is ready and local admission still permits delivery
- **THEN** the hook receives the commit and fulfillment identities plus verified ready evidence
- **AND** delivery reaches `started` only after the hook confirms the authority's start record

#### Scenario: An unstarted rate part has reservations but no funded-through time

- **WHEN** the adapter verifies commitment and the first reserved batch with no effective stop
- **THEN** absence of a running-part funded-through time alone does not refuse commit or dispatch

#### Scenario: A stop is pending at the authority

- **WHEN** the payment adapter reports a future pending stop
- **THEN** the hook evaluates its effective time rather than treating it as an immediate end
- **AND** no local stop scheduler replaces authority-hosted notice

### Requirement: Delivery checkpoints recover stable effects

Each negotiation MUST have one durable storefront delivery record with ordered checkpoints `authorized`, `dispatched`, `started`, `activated`, `available`, `active`. External-effect intents and stable identities MUST be persisted before calls; acknowledgements advance checkpoints. Recovery MUST reconcile the same effect/resource and recheck admission. Required persistence failure MUST defer protected effects without abandoning an existing resource solely for bookkeeping failure.

#### Scenario: Recovery crosses an intent acknowledgement gap

- **WHEN** the storefront restarts after commit, dispatch, start or activation was sent but before its acknowledgement was persisted
- **THEN** it resolves or retries the recorded effect under the same identity
- **AND** it does not create replacement capacity or assume a payment start succeeded

#### Scenario: Recovery crosses adjacent checkpoints

- **WHEN** either compute storefront restarts between any two adjacent delivery checkpoints
- **THEN** it resumes from the persisted checkpoint and effect intent using authoritative state
- **AND** it reaches availability only after verified provisioning, start authorization and site activation

#### Scenario: A protected write fails

- **WHEN** the required decision or effect-intent write cannot be persisted
- **THEN** the next protected effect is deferred and the persistence failure is reported
- **AND** an existing physical resource remains adopted while persistence is retried

#### Scenario: A buyer never reads its result

- **WHEN** provisioning, start authorization, activation and disclose authorization complete
- **THEN** the storefront records `available` without waiting for a buyer read

### Requirement: Every delivered compute lease activates to the agreed end

After `started` and before `available`, the path MUST call the site's activation operation with the Agreement's lease end for every compute deal, regardless of payment structure. It MUST journal the intent and retry idempotently after an unknown acknowledgement. The active instant MUST come from the site. A lease whose expiry has already been claimed MUST NOT be resurrected and MUST take the undelivered handoff.

#### Scenario: A reserved lease runs beyond the provisioning allowance

- **WHEN** a reserved VM or bare-metal lease activates successfully before its awaiting-activation deadline
- **THEN** activation names the Agreement end and records the site's active instant
- **AND** the lease may remain active beyond the pool's provisioning allowance without renewal

#### Scenario: A rate lease activates

- **WHEN** a rate deal's start is verified and its lease can still activate
- **THEN** activation names the Agreement end, not a funded horizon

#### Scenario: Activation loses to expiry

- **WHEN** the site has already claimed expiry before activation is accepted
- **THEN** delivery never becomes available
- **AND** the path adopts the site-end evidence and takes the undelivered handoff

### Requirement: Undelivered lifecycle deals hand off an end and a self-filing intent

A terminal failure before `available` MUST hand end service a local final request and the seller half an `exceptional_end(at)` intent with `at` equal to the Agreement's start. The handoff MUST use the lifecycle owner's joint end/filing journal, not a separate refund or end log. The path MUST supply cause/source evidence and MUST NOT compute per-part corrections. Without an adapter it MUST report unsupported self-filing and retain the mechanism's existing recovery behavior.

#### Scenario: Provisioning fails before dispatch

- **WHEN** provisioning fails terminally with proof that nothing was dispatched
- **THEN** the path hands off the local end and exceptional-end intent
- **AND** end service can complete physical recovery without teardown

#### Scenario: An activation deadline expires while the storefront is down

- **WHEN** recovery observes the site's signed end report for an awaiting-activation lease that never became available
- **THEN** it supplies that report as evidence for the local end and `exceptional_end` at the Agreement's start
- **AND** the lifecycle journal owns retry of the filing even if an authority is unavailable

#### Scenario: Billing started but delivery never became available

- **WHEN** activation fails after the authority recorded a rate start
- **THEN** the undelivered intent still names the Agreement's start, not the payment start or the later failure
- **AND** the path issues no direct stop, refund amount or backdated payment event

#### Scenario: A final request overlaps dispatch

- **WHEN** a due final request is recorded after dispatch was sent
- **THEN** the path adopts that fulfillment and hands its identity to end service rather than scheduling another
- **AND** any undelivered self-filing retains the final request's actor, cause and source

### Requirement: Storefront credential disclosure is ordered with local ends

Buyer-authenticated credential reads MUST require delivery `available` or `active` and admission under end service's recorded end. They MUST fetch credentials live outside a database transaction and recheck local eligibility before authorizing a response. They MUST NOT read payment snapshots per credential request, cache credentials or treat blocked reads as revocation of material already disclosed. The ordering guarantee is local response authorization, not remote receipt of in-flight bytes.

#### Scenario: An end wins during a credential fetch

- **WHEN** a due local end is admitted after a credential fetch begins but before its response is authorized
- **THEN** the storefront discards the fetched material and refuses disclosure
- **AND** no cached credentials are returned

#### Scenario: A recorded future end has arrived but teardown is delayed

- **WHEN** the recorded end time has arrived and provisioning still reports an active resource
- **THEN** the storefront refuses credential disclosure without consulting a payment snapshot

#### Scenario: An earlier credential response is in flight

- **WHEN** local disclosure authorization precedes the local end but the response is still in transit
- **THEN** the end does not claim to retract those bytes
- **AND** end service's physical teardown remains the revocation path
