## ADDED Requirements

### Requirement: Compute storefronts share one protected delivery path

VM and bare-metal storefront fulfillment hooks MUST delegate protected compute delivery to one compute-family library through injected ports. Core hook-result identity validation MUST remain in force. Domain preparation and result codecs MUST remain injected. The path MUST consume selected-stage evidence without mechanism-ID branching; API-credit issuance MUST remain outside it.

#### Scenario: Both entry points deliver

- **WHEN** payment settle or the selected Alkahest continuation invokes either domain's fulfillment hook
- **THEN** the hook delegates to the same protected-transition implementation
- **AND** core still validates its returned negotiation and fulfillment identities

#### Scenario: API credits delivers

- **WHEN** an API-credit deal reaches issuance
- **THEN** its existing path has no compute activation requirement

### Requirement: Delivery commits the Agreement window

Delivery MUST commit and recover the accepted Agreement's exact start and duration under the same reservation identity. It MUST NOT substitute now or a default duration. Missing or conflicting timing MUST be repair-required without replacing an existing resource. An elapsed window before availability MUST enter the classified end handoff.

#### Scenario: Settlement completes late

- **GIVEN** an Agreement from 12:00 through 14:00
- **WHEN** settlement completes at 12:30
- **THEN** both domains commit 12:00 through 14:00 on first attempt and retry

#### Scenario: Recovery lacks timing

- **WHEN** an unfinished delivery lacks valid accepted timing
- **THEN** it remains repair-required with its recorded resource, not a replacement or a guessed hour

### Requirement: Future-start delivery waits inside its admitted window

Capacity MAY be committed at settlement before the Agreement start. Dispatch, activation, billing start and availability MUST NOT precede that start. The path MUST retain a durable wake time and recheck admission on wake. Credential reads MUST NOT disclose before the start.

#### Scenario: A forward reservation waits

- **WHEN** a 12:00 Agreement commits at 10:00
- **THEN** it remains deferred until 12:00 without dispatch or early access
- **AND** recovery repeats the same commit and wake time
- **AND** the site's provisional deadline is anchored by the activation-deadline contract

### Requirement: Delivery authorization is a decision separate from billing effects

The path MUST call the injected neutral authorization protocol before commit, dispatch, billing start and initial disclose. It MUST record outcome, reason, operation identity and evidence references before use. Pending and unknown outcomes MUST remain pending. The prepaid decision MUST issue no financial mutation.

#### Scenario: A prepaid deal passes authorization

- **WHEN** selected-stage evidence and local admission permit delivery
- **THEN** the prepaid financial decision allows without a payment start

#### Scenario: An outcome is unknown

- **WHEN** the authorization adapter cannot establish its outcome
- **THEN** delivery stays pending and resolves the same attempt

### Requirement: Protected transitions consume lifecycle admission

Each protected transition, activation, recovery and credential-response authorization MUST consume the lifecycle owner's revision-bearing admission port. The path MUST use its transaction boundary for checkpoint/disclosure CAS without remote I/O in the transaction. A financial allow MUST NOT override a due local end.

#### Scenario: An end wins before dispatch

- **WHEN** lifecycle admission records a due end before dispatch
- **THEN** delivery does not dispatch despite an earlier financial allow
- **AND** hands recovery to the lifecycle owner

### Requirement: Billing start follows activation under one effect identity

After acknowledged activation and start authorization, delivery MUST persist one billing-start intent and invoke the injected start effect under its stable identity. It MUST supply commitment/fulfillment identities and validated ready-evidence envelope/digest without credentials. Unknown results MUST resolve under that identity. Rate servicing owns payment interpretation; prepaid start MUST be a no-op.

#### Scenario: Rate start acknowledgement is lost

- **WHEN** the authority accepted start but its acknowledgement was not persisted
- **THEN** recovery resolves the same start key and adopts its verified record
- **AND** does not start billing again or allocate a second resource

#### Scenario: Activation fails

- **WHEN** expiry claims the lease before activation succeeds
- **THEN** no billing-start effect has been issued
- **AND** delivery enters the classified end handoff

### Requirement: Delivery checkpoints recover stable effects

Each negotiation MUST have one durable delivery record with ordered checkpoints authorized, dispatched, activated, started, available and converged. Intents and stable identities MUST precede remote reserve, commit, dispatch, activation and billing effects; acknowledgements advance checkpoints. Recovery MUST reconcile the same effect and resource, including reservation creation, and recheck admission.

#### Scenario: Reserve acknowledgement is lost

- **WHEN** reserve succeeds before its returned identity is persisted
- **THEN** negotiation-keyed exact-request replay recovers the same reservation
- **AND** a conflicting request is refused rather than creating a second hold

#### Scenario: A protected write fails

- **WHEN** an admission or intent write cannot be persisted
- **THEN** the next protected effect is deferred
- **AND** any existing physical resource remains adopted while persistence is retried

#### Scenario: Adjacent checkpoints are interrupted

- **WHEN** either storefront restarts between adjacent checkpoints or an intent and acknowledgement
- **THEN** it reconciles authoritative state before advancing
- **AND** reaches availability only after ready evidence, activation and billing-start acknowledgement

### Requirement: Availability and convergence have explicit meanings

Available MUST mean that readiness and disclose authorization are durable without waiting for a buyer read. Converged MUST additionally mean the selected stage's required evidence, readiness and claim-binding continuation is acknowledged or explicitly absent. Pending, persistence retry and repair-required MUST map to deferred hook outcomes; terminal failure MUST map to failed only after the end handoff is durable.

#### Scenario: A buyer never reads

- **WHEN** ready evidence, activation, billing-start acknowledgement and disclose authorization complete
- **THEN** delivery records available without waiting for a credential read

#### Scenario: Evidence publication remains pending

- **WHEN** availability is durable but the selected continuation is unfinished
- **THEN** delivery is not converged and retries that continuation without another physical delivery

### Requirement: Activation consumes the reservation's current end

Before billing start and availability, every compute delivery MUST invoke reservation-only activation and journal retries. It MUST validate the returned end as the immutable commit end or a verified earlier end recorded by end service, and adopt the site's active instant. Unexplained mismatches MUST remain repair-required. A claimed expiry MUST NOT be resurrected.

#### Scenario: Truncation precedes activation

- **WHEN** end service has recorded and applied an earlier future end before activation
- **THEN** activation supplies no target deadline and preserves that shorter end

#### Scenario: Activation acknowledgement is lost before truncation

- **WHEN** activation succeeds, its acknowledgement is lost and end service then truncates
- **THEN** retry adopts the current shorter end without extension or a replacement lease

#### Scenario: A reserved lease survives allowance

- **WHEN** a reserved lease activates and its former provisional deadline passes before its current end
- **THEN** it remains active without renewal or a funded horizon

### Requirement: Safeguard enablement follows compatible callers

This change MUST enable the compute composition's activation safeguard only after all delivery and recovery callers are deployed and qualified. A verified null-phase legacy leased view MUST use unchanged legacy behavior. Missing activation support MUST be tolerated only for that verified legacy case; non-null or unknown phase without working activation MUST be repair-required.

#### Scenario: Storefronts upgrade before the site

- **WHEN** the path observes a verified legacy null-phase leased view and no activation route
- **THEN** it preserves legacy delivery behavior without claiming a new site activation

#### Scenario: A protected site has no working activation route

- **WHEN** a lease is awaiting activation but activation is unavailable
- **THEN** delivery stays pending and reports repair-required, not assumed success

### Requirement: Delivery supplies classified evidence to the single end operation

Before availability, terminal refusal, provisioning failure, elapsed window and activation lapse MUST enter the lifecycle owner's single end-plus-optional-filing operation. Delivery MUST supply actor, cause, source, accepted start, fixed observed failure time, resource identities and evidence. It MUST NOT compute corrections or duplicate that owner's cause/timing policy. Unsupported adapters MUST be reported honestly.

#### Scenario: A lawful end wins before availability

- **WHEN** a buyer request, entitled stop, terms end or ruling already controls the end
- **THEN** delivery preserves that cause and supplies the existing final request
- **AND** does not request a seller self-penalty solely because availability was not reached

#### Scenario: Seller failure occurs before a future start

- **WHEN** a never-delivered deal fails before its accepted start
- **THEN** delivery supplies both accepted start and the fixed failure-observation time
- **AND** the lifecycle owner journals a valid immediate intent under its pre-start policy, not a future-dated command or a retry-time recomputation

#### Scenario: Settlement arrives after the window without established buyer fault

- **WHEN** the window has elapsed and no resource became available
- **THEN** delivery does not dispatch and supplies never-delivered evidence
- **AND** does not infer a buyer-fault exemption from settlement lateness alone

#### Scenario: An end overlaps dispatch

- **WHEN** a final request wins after dispatch was sent
- **THEN** delivery adopts that fulfillment and supplies its identity to end service
- **AND** keeps signed site evidence without treating end intent as proven release

### Requirement: Credential disclosure uses live local admission even on exact retry

Buyer-authenticated credential responses MUST require available or converged, a reached start and lifecycle admission. They MUST fetch live outside the transaction and recheck revision/time before response authorization. Credential-capable response bodies MUST NOT be retained in replay storage; exact retries MUST re-enter the guard while changed requests remain rejected. No payment snapshot is required per read.

#### Scenario: An end wins during fetch

- **WHEN** a due end is admitted after fetching starts but before response authorization
- **THEN** the fetched access material is discarded and disclosure refused

#### Scenario: A successful credential response is retried after end

- **WHEN** an exact authenticated retry arrives after a due end
- **THEN** it re-runs eligibility rather than replaying the earlier credential body
- **AND** replay storage retains no access material

#### Scenario: The buyer polls VM settlement status

- **WHEN** the VM buyer reads credentials through settle status
- **THEN** the existing typed response is populated by the live guarded read, not a stored fallback

#### Scenario: A response is already in flight

- **WHEN** response authorization precedes end admission
- **THEN** no claim is made to retract in-flight bytes
- **AND** physical termination remains revocation for disclosed material
