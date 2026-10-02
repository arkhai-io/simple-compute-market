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
implementation of a control it binds.

#### Scenario: A storefront previews settlement

- **WHEN** an administrator requests evaluate-settle for an escrow on a VM or bare-metal
  storefront
- **THEN** the settlement runtime returns the domain's fulfillment preview without
  reserving, scheduling, or persisting anything

#### Scenario: A domain gains a control

- **WHEN** a storefront that lacked a deal control needs it
- **THEN** it binds the kit route service and reaches it through the canonical client
  method every other domain uses

### Requirement: Compute mock executors share one compute-family mechanism

Under the provisioning mock profile, each compute provisioning adapter MUST register a
mock executor for its own actions built on one rule and gate mechanism owned by compute
provisioning beside the job lifecycle: rule matching, pause gates, a deterministic
signal when a job reaches a gate, job-done events, the evaluate-job dry run, and a
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
