## ADDED Requirements

### Requirement: Storefront deal controls are kit-owned route services

The storefront's deal controls MUST be framework-free route services in the kit that
composes or owns the mechanism each exposes, bound by every storefront behind its own
authentication: the stage-event read, evaluate-negotiate, and force-accept (storefront
kit); settle verify, evaluate-settle, and settle wait (settlement runtime kit); and admin
reserve and the capacity-released callback (capacity and publication kit).
Evaluate-negotiate MUST call the negotiation runtime's opening preview and force-accept
its administrative acceptance; neither may record negotiation state through any other
path. Evaluate-settle MUST call a per-domain fulfillment-preview hook. Evaluate-negotiate,
evaluate-settle, and settle verify MUST make no durable write. Wire paths and canonical
client methods MUST be the same for every domain that binds a control. A storefront MUST NOT carry a domain-local
implementation of a control it binds. The stage-event read's route service MUST rebuild
the resource the canonical client signs and refuse a query parameter that resource does
not bind, a repeated one, or a stream request. Force-accept MUST answer a listing-source
refusal as every negotiation route does: 409 for a declared mismatch or taken capacity,
503 for a source that cannot be confirmed.

#### Scenario: A storefront previews settlement

- **WHEN** an administrator requests evaluate-settle for an escrow on a VM or bare-metal
  storefront
- **THEN** the settlement runtime returns the domain's fulfillment preview without
  reserving, scheduling, or persisting anything

#### Scenario: A domain gains a control

- **WHEN** a storefront that lacked a deal control needs it
- **THEN** it binds the kit route service and reaches it through the canonical client
  method every other domain uses

#### Scenario: An event read carries a parameter the signature does not bind

- **WHEN** an administrator's stage-event read carries an unknown or repeated query
  parameter, or asks for a stream
- **THEN** every storefront refuses it with 400 before reading the log

### Requirement: The trading pause is one process-local kit mechanism

A storefront's trading pause MUST be one process-local mechanism owned by the storefront
kit, separate from the lifecycle pause that holds its loops, set and cleared through one
kit route service every storefront binds at the same paths. While it is set, the
negotiation runtime MUST refuse a new negotiation, and an opening preview MUST report
that refusal. A restarted storefront MUST start with trading resumed.

#### Scenario: A storefront is paused and restarted

- **WHEN** an authenticated operator pauses a storefront's trading and the process
  restarts
- **THEN** the restarted storefront accepts new negotiations without a resume

#### Scenario: Trading and loop pauses are separate

- **WHEN** an operator pauses a storefront's trading
- **THEN** its loops keep running, and pausing its loops leaves trading open

### Requirement: Compute mock executors share one compute-family mechanism

Under the provisioning mock profile, each compute provisioning adapter MUST register a
mock executor for its own actions built on one rule and gate mechanism owned by compute
provisioning beside the job lifecycle: rule matching, pause gates, a deterministic
signal when a job reaches a gate, the evaluate-job dry run, and a
framework-free test route service. A mock executor MUST be assembled from shared
execution mechanics and the adapter's contributed default output; no adapter's mock MAY
derive from another adapter's. The mechanism MUST NOT be presented as a foundation kit,
and a non-compute domain's executor mock MUST NOT be added to it. Each adapter MUST
mount its rule routes under its own prefix; job draining and waiting MUST stay shared.

#### Scenario: A bare-metal grant runs under the mock profile

- **WHEN** a bare-metal grant job runs with the mock profile active
- **THEN** the bare-metal mock returns output bare metal's codec reads as a grant, unless
  a bare-metal rule shapes, pauses, or fails it

#### Scenario: A test waits for a held job

- **WHEN** a test needs a job held at a rule's gate
- **THEN** it waits on the gate-reached signal, not on elapsed time

#### Scenario: A VM rule is installed

- **WHEN** a scenario installs a VM mock rule
- **THEN** it matches VM jobs only and never a bare-metal job

## MODIFIED Requirements

### Requirement: Kit-owned synchronous negotiation runtime
The signed synchronous negotiation lifecycle MUST live in a foundation kit and MUST be
composed by storefront domain roots. The kit MUST own round ordering, canonical-principal
checks, transcript persistence, terminal-state transitions, exact continuation recovery,
and the acceptance chokepoint, through which administrative acceptance also passes, and
MUST offer a side-effect-free preview of an opening. A domain MUST inject its listing resolver, schema codecs,
seller policy, configuration-derived values, accepted-artifact builder, and domain
persistence/effect hooks; neither the kit nor core may import a concrete domain or infer a
domain by inspecting terms, proposals, listings, or persisted payloads.

A domain whose listings derive from a declaration MAY contribute a listing-source check.
The runtime MUST obtain its verdict before every seller decision and before a buyer's or
an administrator's acceptance, never on a buyer's exit, and MUST enforce it itself, whatever
the domain's policy chain contains: a declared mismatch or taken capacity refuses the
round or acceptance, and a source that cannot be confirmed is a retryable refusal raised
before any write.

A thread MUST be recorded as successful only after its agreed terms, any hold, and its
accepted artifacts are recorded. The runtime MUST NOT counter, accept, or force-accept a
non-terminal thread whose transcript records an acceptance or whose agreement or plan is
recorded; a buyer MAY still exit it.

#### Scenario: A domain runs a negotiation round

- **WHEN** a VM, API-credit, or bare-metal storefront processes a signed negotiation
  request
- **THEN** the shared kit state machine advances the round while the selected domain
  contract alone decodes terms, evaluates policy, and constructs accepted artifacts

#### Scenario: A continuation is resumed

- **WHEN** an authenticated buyer or administrator continues a recorded negotiation
- **THEN** the runtime loads its canonical buyer and seller principals, recorded listing
  identity, transcript, terms, strategy, and pinned proposal before invoking domain policy

#### Scenario: Recorded state does not match its domain binding

- **WHEN** continuation resolution or a domain persistence hook detects a listing,
  principal, transcript, or accepted-input mismatch
- **THEN** the runtime fails before a round, hold, agreement, or settlement artifact is
  recorded

#### Scenario: A new storefront domain is composed

- **WHEN** the domain supplies the negotiation resolver and complete domain hook set
- **THEN** it obtains the same protocol guards without copying a VM or API-credit runtime

#### Scenario: An administrator force-accepts a negotiation

- **WHEN** an authenticated administrator accepts a non-terminal negotiation at an amount
- **THEN** the runtime builds the acceptance through the recorded domain's hooks, records
  the administrator as the accepting author, and commits through the same acceptance path
  as a negotiated acceptance, so the domain's hold and accepted artifacts are recorded

#### Scenario: An opening is previewed

- **WHEN** an administrator previews a negotiation opening
- **THEN** the runtime runs the same decode, opening validation, principal, listing,
  settlement-selection, and round-zero policy steps as a real opening and records no
  thread, message, hold, or artifact

#### Scenario: A listing's source changed before acceptance

- **WHEN** a buyer accepts, or an administrator force-accepts, a negotiation whose
  listing's source check now reports a declared mismatch or taken capacity
- **THEN** the runtime refuses the acceptance before recording anything, even where the
  domain's chain has no inventory guard

#### Scenario: A listing's source cannot be confirmed

- **WHEN** a domain's source check reports that the listing's source cannot be confirmed
- **THEN** an opening, round, or acceptance is refused as retryable before any write, an
  opening preview reports the refusal, and a buyer's exit still succeeds

#### Scenario: An acceptance is interrupted

- **WHEN** the process stops after an acceptance recorded its message or agreement but
  before the thread was recorded as successful
- **THEN** the thread is not successful, settlement never reads it, and a later counter,
  accept, or force-accept on it is refused
