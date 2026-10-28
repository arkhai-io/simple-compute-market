# Market Composition Specification

## Purpose

Define the dependency direction and role/domain/plugin boundaries that keep market orchestration schema-opaque.

## Requirements

### Requirement: Schema-opaque core orchestration

Core role packages MUST own discovery and negotiation control flow without importing a concrete market domain or settlement mechanism. Core MUST expose the accepted Agreement, settlement-option carriers, a mechanism-to-stage table carrier and SettlementEvidence, but MUST NOT impose a shared mechanism-stage API, actor order or escrow lifecycle on mechanism and domain compositions.

#### Scenario: Installing core without a domain plugin

- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery and negotiation behavior and no concrete market verbs or settlement implementation

### Requirement: Domain-owned deterministic semantics
A domain package MUST own the listing, message, terms, materialization, receipt, result vocabulary, and pure interpretation required for independent implementations of that market to agree.

#### Scenario: Adding a market domain
- **WHEN** a new listing schema is introduced
- **THEN** its deterministic codecs and reference semantics can be installed without modifying core orchestration

### Requirement: From-below kit dependencies
Every package MUST depend only on packages in its own layer or a lower one, without a cycle inside a layer, and only on packages whose scope is a subset of its own. Layer, kind, and scope MUST be read from the package's path and name, never inferred from its imports. Any import and any declared internal distribution is a dependency. One repository-wide check MUST hold these rules over every project, and every divergence it reports MUST be an owned exception that expires with its cause.

#### Scenario: Architecture boundary tests run
- **WHEN** the repository architecture check runs over every project outside the tooling paths
- **THEN** every project is classified by layer, kind, and scope, and every dependency a rule forbids is reported unless an owned exception row excuses it

#### Scenario: A lower layer depends on a higher one
- **WHEN** a kit or specialization imports a composition, at module level, inside a function, under `TYPE_CHECKING`, or behind `try`
- **THEN** the architecture check fails and names the importing file and line and the imported distribution

#### Scenario: Packages in one layer import each other
- **WHEN** two packages in the same layer depend on each other directly or through others in that layer
- **THEN** the architecture check fails and names the cycle

#### Scenario: A package knows a scope it is not placed in
- **WHEN** a package depends on one whose scope is not a subset of its own, such as a domain composition declaring a sibling domain's contribution without importing it
- **THEN** the architecture check fails and names the dependency and the scope elements it adds

#### Scenario: A package imports an internal distribution it does not declare
- **WHEN** a project's source imports a repository distribution its `pyproject.toml` does not declare
- **THEN** the architecture check fails and names the importing file and line

#### Scenario: A package imports a plugin
- **WHEN** any package imports a package that registers into a plugin entry-point group
- **THEN** the architecture check fails, while a declaration that installs the plugin passes

#### Scenario: A light kind depends outside its kind allowlist
- **WHEN** a contracts or client package depends on a distribution its kind allowlist does not name
- **THEN** the architecture check fails and names the dependency

#### Scenario: An exception outlives its cause
- **WHEN** an exception row's edge is gone, or the edge no longer breaks the rule the row names
- **THEN** the architecture check fails and names the row and its owning change

#### Scenario: An override outlives its cause
- **WHEN** an override row's project now classifies the same from its path alone, or the row grants a scope element none of the project's dependencies uses
- **THEN** the architecture check fails and names the row

### Requirement: Role-owned executable composition
The buyer executable MUST be core-owned and load domain plugins, and registry behavior MUST be core-owned and schema-configured. VM, bare-metal, and API-credit storefront executables and the VM provisioning executable are domain-owned composition roots. Each storefront contribution MUST provide one validated `MarketDomainContract` plus its domain-owned runtime builder without importing another domain implementation.

#### Scenario: A buyer domain plugin is installed
- **WHEN** the core `market` executable starts
- **THEN** that plugin registers its domain verbs through entry-point composition

#### Scenario: Seller starts a domain storefront
- **WHEN** a VM, bare-metal, or API-credit storefront is launched
- **THEN** the domain-owned composition root assembles the shared storefront role with that domain's runtime and infrastructure adapters

#### Scenario: Seller loads the bare-metal contribution in a shared shell
- **WHEN** a composition shell discovers the bare-metal storefront entry point
- **THEN** it receives the validated bare-metal contract and runtime builder without importing VM services or duplicating registry selection

### Requirement: Versioned market-domain contract
Core role packages MUST expose one versioned market-domain contract for deterministic codecs and role integration hooks, and concrete domain packages MUST implement that contract without core importing their implementations.

#### Scenario: Shipped domains are loaded
- **WHEN** VM, bare-metal, and API-credit plugins are discovered independently
- **THEN** each satisfies the same supported contract version and registers a unique domain identity without modifying core

#### Scenario: Unsupported contract version is installed
- **WHEN** a domain plugin declares a contract version the role does not support
- **THEN** startup fails with the domain identity and supported version range before serving requests

### Requirement: Explicit optional domain capabilities
A domain MUST declare optional capabilities and supply the typed hook set required by each declaration; absence of a capability MUST be valid and MUST NOT require placeholder or no-op implementations.

#### Scenario: API-credit domain has no compute provisioner
- **WHEN** the API-credit domain is composed without a compute-provisioning capability
- **THEN** buyer and storefront roles remain usable and expose no compute-provisioning hooks for that domain

#### Scenario: Declared capability is incomplete
- **WHEN** a domain declares a capability but omits a required hook
- **THEN** composition rejects the plugin with an actionable capability validation error

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
before any write. A seller decision that would counter or accept is subject to the
verdict; one that independently rejects or exits keeps its own reason, so a malformed
request is refused for what is wrong with it rather than as retryable.

A thread MUST be recorded as successful only after its agreed terms, any hold, and its
accepted artifacts are recorded. The runtime MUST NOT counter, accept, or force-accept a
non-terminal thread unless its transcript ends with the seller's counter, nor one whose
agreement or plan is recorded; a buyer MAY still exit it.

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
- **THEN** a seller decision that would counter or accept, and a buyer's or an
  administrator's acceptance, are refused as retryable before any write, an opening
  preview reports the refusal, and a buyer's exit still succeeds

#### Scenario: A seller's own rejection keeps its reason

- **WHEN** seller policy rejects or exits a round for its own reason while the listing's
  source cannot be confirmed
- **THEN** the round ends with the policy's reason, not a retryable refusal

#### Scenario: An acceptance is interrupted

- **WHEN** the process stops after an acceptance recorded its message or agreement but
  before the thread was recorded as successful
- **THEN** the thread is not successful, settlement never reads it, and a later counter,
  accept, or force-accept on it is refused

#### Scenario: A round is interrupted before the seller answers

- **WHEN** the process stops after recording a buyer's opening or counter but before the
  seller's decision
- **THEN** a later counter, accept, or force-accept on the thread is refused, so no
  buyer accepts an offer the seller never made; the buyer may exit it, and the
  negotiation watchdog abandons it

### Requirement: From-below identity capability

Canonical principal, signer/verifier dispatch, authenticated-envelope, replay, and rotation contracts MUST live in a foundation kit. Core roles MAY consume that kit, and domain and settlement implementations MAY receive its opaque interfaces, but identity code MUST NOT depend on role composition, a concrete domain, a settlement mechanism, a hosted provider, or chain runtime. Core orchestration MUST carry complete scheme-tagged principals opaquely and MUST NOT interpret identifiers as wallet addresses, provider accounts, or mechanism configuration.

#### Scenario: A new market domain is installed

- **WHEN** the domain composes buyer and storefront roles without blockchain functionality
- **THEN** it can use the shared Ed25519 identity capability without importing an EVM or hosted-provider package

#### Scenario: Core carries a non-chain principal

- **WHEN** registry, negotiation, service-peer, or settlement orchestration receives an Ed25519 principal
- **THEN** it preserves the complete scheme and identifier as the authenticated actor without deriving a wallet, provider account, or chain setting

### Requirement: Composition roots inject signers

Buyer, registry, storefront, provisioning, and domain composition roots MUST load one selected signer from secret-bound identity configuration and construct only the counterparty verifier registry needed for the role. Arkhai payment calls MUST use the appropriate owner's WorkOS user-scoped API credential separately from the marketplace signer. Public config, process arguments, logs, and durable public carriers MUST remain credential-free.

#### Scenario: Buyer starts with an Ed25519 profile

- **WHEN** buyer config names an Ed25519 principal and its Secret supplies the matching seed
- **THEN** buyer composition constructs an Ed25519 signer for marketplace requests without loading an EVM private key

#### Scenario: Storefront rotates its signer

- **WHEN** storefront configuration resolves a replacement principal with an old overlapping verifier
- **THEN** the composition signs new marketplace requests with the replacement and accepts authenticated peer requests under the declared overlap without changing accepted buyer ownership

#### Scenario: Registry serves mixed consumer schemes

- **WHEN** buyer and storefront principals use different supported schemes
- **THEN** the registry verifies both through the marketplace identity kit without selecting a shared secret or wallet

#### Scenario: VM composition selects Arkhai payments

- **WHEN** the VM buyer and storefront select `arkhai.payments.v1` with their marketplace signers and owner-scoped payment credentials
- **THEN** the payment calls use the Arkhai account credentials without loading an Alkahest wallet or chain configuration

#### Scenario: A chain mechanism is selected

- **WHEN** a composition selects an Alkahest or other EVM effect
- **THEN** its concrete mechanism resolves the required wallet, chain, and provider dependencies without exposing them to scheme-neutral core orchestration

#### Scenario: Arkhai payments is published

- **WHEN** a composition installs the Arkhai payments kit
- **THEN** it uses the published HTTP and receipt contracts without duplicating their wire encoding, canonicalization, or signature verification

### Requirement: Explicit settlement configuration registration

Composition roots MUST register installed settlement mechanisms with canonical ID, typed config schema, preflight, option builder, buyer compatibility, and optional operator commands; obligation-runtime client factories are optional for Agreement-based stages. Core role packages MUST consume only the shared registration/status contract and MUST NOT branch on mechanism IDs or import concrete mechanism configuration.

#### Scenario: Composition omits payments client

- **WHEN** a domain installs only the Alkahest registration and omits the Arkhai payments kit
- **THEN** common status, publication, and buyer selection expose only the installed Alkahest registration without payment placeholders or no-op hooks

### Requirement: Shared resources are injected on demand

Identity, wallet, and chain resources MUST be composed independently of settlement mechanism configuration and injected only into registrations that declare them. Installing a non-EVM mechanism MUST NOT require placeholder wallet or chain resources.

#### Scenario: Payment-only VM storefront starts

- **WHEN** VM composition installs only `arkhai.payments.v1` with its required payment-service credential
- **THEN** startup, readiness, publication, and payment settlement succeed without constructing an Alkahest wallet or chain client

### Requirement: Storefront roots inject a frozen domain registry

A storefront composition root MUST discover and validate a non-empty configured set of complete storefront contributions once at startup. Each immutable registration MUST bind one explicit offering mode, one exact `DomainIdentity` and supported market-contract version, and one installed contribution. A one-domain deployment MUST use the same registry and shared role shell with one explicit registration. Core and kit packages MUST remain schema-opaque and MUST NOT import domain implementations, construct a contract from stored strings, or select a default.

#### Scenario: VM and bare-metal contributions start together

- **WHEN** the common compute-family storefront starts with installed `vms`/`vm`/`compute.v1`/`1.0` and `bare_metal`/`bare_metal`/`bare_metal.v1`/`1.0` contributions
- **THEN** one frozen registry retains the exact validated objects and the common application, persistence, publication, negotiation, settlement, fulfillment, recovery, and teardown boundaries receive that same registry

#### Scenario: One explicit contribution starts

- **WHEN** an operator intentionally configures one complete supported contribution
- **THEN** the same common shell starts with one registration and no missing-domain fallback or alternate role implementation

#### Scenario: Registration is incomplete or ambiguous

- **WHEN** configuration names a duplicate mode, identity, contribution, unsupported version, absent package, assertion mismatch, secret-bearing field, or incomplete capability set
- **THEN** startup fails before persistence migration, network preflight, publication, or background work

#### Scenario: Durable work names an unavailable contract

- **WHEN** startup or recovery finds nonterminal state whose exact binding cannot resolve to a configured registration
- **THEN** readiness fails for that record without reconstructing a contract, selecting another mode, or dispatching a side effect

### Requirement: Cross-cutting storefront runtime is kit-owned

Storefront functionality that differs between market domains only in which
immutable domain hooks it invokes and which configuration values it reads MUST
live in the storefront kit and be composed by a domain, not reimplemented in
the domain layer. A domain MUST supply its validated contract, service
lifecycle hooks, route contribution, and configuration explicitly. The shared
runtime MUST NOT discover a contract through module-global state, import a
concrete domain, or depend on a deployed service.

#### Scenario: Two domains need the same storefront mechanism

- **WHEN** two domains require a storefront mechanism that differs only in
  codecs, policy hooks, and configuration
- **THEN** the mechanism lives in kit and both composition roots inject their
  immutable domain contributions

#### Scenario: A new domain composes a storefront

- **WHEN** a domain supplies an app description, service/container lifecycle,
  ordered routes, and middleware around its validated contract
- **THEN** the shared shell carries that exact contract through application
  state and the lifespan-owned container without a global resolver

#### Scenario: Kit runtime would reach for a domain

- **WHEN** a reusable storefront mechanism needs domain semantics
- **THEN** the dependency is inverted through the validated contract or an
  explicit composition hook rather than a domain import

### Requirement: Storefront timer loops are held and stepped through one kit controller

Each storefront process MUST hold exactly one kit-owned loop controller and MUST
register with it every timer-driven loop the process runs. A domain MUST NOT
implement its own pause flag, gate, or loop-state reporting. A loop whose tasks are
created by a kit runtime the storefront composes, such as a per-site fan-out, MUST be
declared to the controller by name so that a pause waits for it.

A registration MUST bind the loop's name to the step that runs exactly one cycle of
it, and MAY bind a read-only preview of that cycle. The step MUST invoke the same
operation the loop's timer invokes, so a manual cycle cannot exercise behaviour the
timer does not. A loop MUST register in one of two forms: a timer loop, whose timer
the controller runs over its step, or a fan-out, whose task a composed kit runtime
owns and which runs independent per-child cycles, each child under its own declared
name. A fan-out MUST register with its step and the names of its children, and each
child MUST be declared as the fan-out's child when it registers, so status lists every
child before its first cycle; a child the fan-out's task reaches later MUST be declared
then. A name registered in one form MUST be refused in the other. A storefront MAY
register a loop's step before the loop itself, so every step is invocable from the
moment the storefront serves, but a step registration runs no loop. Starting the
registered loops MUST be the only way a loop's task starts, and it MUST start every
registered timer and fan-out together; it MUST name every fan-out's children before
starting any task, so a fan-out whose children cannot be named leaves no loop started.

One pause MUST hold every registered loop at a cycle boundary without cancelling it:
a cycle either completes or never starts, and loop-local state survives the pause.
While held, every registered step MUST remain invocable. Resuming MUST return every
held loop to work. Holding loops MUST NOT affect whether the storefront accepts new
negotiations, which is a separate control.

A loop body MUST read its gate when it starts, so a pause is observable from the
moment the loop runs, and MUST read its gate immediately before doing any work. It
MUST wait out its interval through the controller, which returns early when a pause
is requested. A pause requested at any point in a loop's interval MUST therefore be
observed before that loop's next cycle's work, independently of the interval's
length.

The loop pause MUST be process-local. A restarted storefront MUST resume its loops.

#### Scenario: Every storefront loop is held by one pause

- **WHEN** an operator pauses the lifecycle loops of a storefront
- **THEN** every timer-driven loop that storefront runs, including loops created by a
  composed kit runtime, stops at its next cycle boundary
- **AND** the storefront continues to accept new negotiations

#### Scenario: A held loop is stepped

- **WHEN** the loops are held and an operator runs one cycle of a registered loop
- **THEN** exactly the operation the loop's timer invokes runs once and its result is
  returned
- **AND** the loops remain held

#### Scenario: A pause arrives during a long interval

- **WHEN** a loop with a long interval is waiting between cycles and a pause is
  requested
- **THEN** the loop reaches its gate without waiting out the interval and performs no
  further work until resumed or stepped

#### Scenario: A fan-out's children are listed before their first cycle

- **WHEN** a storefront registers its capacity-event fan-out for its configured sites
- **THEN** status lists each site's poller before the fan-out starts, and starting the
  storefront's loops starts the fan-out's task with the timers

#### Scenario: A name is registered in both forms

- **WHEN** a loop name registered as a timer loop is registered as a fan-out, or the
  reverse
- **THEN** the second registration is refused and the first stands

#### Scenario: An unregistered loop is stepped

- **WHEN** an operator runs one cycle of a name no loop registered
- **THEN** the request is refused as not found and no work runs

#### Scenario: A storefront restarts while paused

- **WHEN** a storefront whose loops were held restarts
- **THEN** its loops run on their timers until an operator pauses them again

### Requirement: A loop's reported state is established by the loop

A loop's reported state MUST be derived from what the loop has itself acknowledged
at its gate, never from the existence of the task running it. The controller MUST
report each registered or declared loop as one of:

- `starting` — the loop has not yet reached its gate, and so cannot yet observe a
  pause;
- `running` — no pause is requested and the loop has reached its gate;
- `pausing` — a pause is requested and the loop has not yet acknowledged it, so a
  cycle that began before the request may still be writing;
- `paused` — the loop has acknowledged the pause at its gate;
- `exited` or `cancelled` — the loop's task has ended.

A pause request MUST wait, within a bounded window, for every live loop to
acknowledge and MUST then report each loop's state as it stands. A loop that has not
acknowledged within the window MUST be reported `pausing` or `starting`, never
`paused`. The controller MUST be able to name which loops are `starting` and which have
`exited` or been `cancelled`, so a health surface can distinguish a loop that has not
begun from one that has ended.

#### Scenario: A loop is mid-cycle when a pause is requested

- **WHEN** a pause is requested while a loop is part-way through a cycle
- **THEN** that loop is reported `pausing` until it reaches its gate, and `paused`
  only afterwards

#### Scenario: A loop has not yet begun cycling

- **WHEN** a pause is requested before a newly started loop has reached its gate
- **THEN** that loop is reported `starting`, not `paused`

#### Scenario: A loop ends on an exception

- **WHEN** a registered loop's task ends on its own
- **THEN** the loop is reported `exited` rather than `paused` or `running`
- **AND** the controller names it among the loops that have ended

### Requirement: An extracted concern leaves no domain-local implementation

When a storefront concern moves into kit, every domain that implemented it
MUST compose the kit implementation in the same change, every obsolete
domain-local implementation MUST be removed, and a domain that lacked the
concern MUST gain it by composition. The extracted mechanism MUST retain the
domain's configured timing, terminal vocabulary, readiness, and client
construction behavior.

#### Scenario: A concern is extracted

- **WHEN** a reusable storefront concern moves into kit
- **THEN** VM, API-credit, and applicable bare-metal roots compose it and no
  domain retains a second implementation

#### Scenario: Existing copies have drifted

- **WHEN** the copies differ in observable control flow
- **THEN** the chosen behavior is recorded and configured explicitly rather
  than silently selecting one copy

### Requirement: Kit-owned capacity and publication lifecycle

The storefront-side multi-site capacity source, exact site projection,
capacity-event reconciliation loop, registry publication, durable publication
result recording, and close/reopen mechanics MUST be owned by one foundation
kit. A composing domain MUST contribute only schema-opaque publication
candidates, listing codecs, candidate reconciliation policy, and durable
binding lookup hooks. The kit MUST NOT import a concrete domain, provider, or
deployed service, and a composing domain MUST NOT retain a parallel capacity or
publication lifecycle.

Every publication candidate MUST carry one exact durable
`PublicationBinding(site_id, offering_mode, source_id, backing)`: trusted
`site_id`, pool-declared `offering_mode`, opaque domain-owned `source_id`, and the
backing delegate its pool's declared label selects. Every domain MUST build it from
the durable listing binding through the kit's one constructor, never from a
published payload. The public offer's mode MUST equal the binding's mode.
Reservation, commit, release, lease truncation, close, reopen, and restart recovery
MUST reload and compare the same binding and MUST NOT infer a home site, default an
offering mode, choose an authority from response data, or fan out after a binding
is recorded. Every storefront capacity effect MUST go through the kit's capacity
effects, whose guard is the binding's backing delegate, whether a domain composes the
kit's capacity runtime or its own aggregate capacity client.

#### Scenario: A domain publishes a capacity-backed candidate

- **WHEN** the domain derives a schema-valid candidate from a trusted site
  projection
- **THEN** the kit publishes it only after the domain hook confirms that its
  exact site, source, advertised offering mode, and backing equal durable local
  state

#### Scenario: An authenticated seller creates a capacity-backed listing

- **WHEN** the seller submits a schema-valid public offer with its exact
  trusted site and pool or Physical Resource source
- **THEN** the storefront verifies that the source identity, GPU quantity,
  configured site, and offering mode match the offer and atomically persists
  the listing and immutable binding before registry publication

#### Scenario: Seller source provenance disagrees with the offer

- **WHEN** the submitted site is unconfigured or the source pool, Physical
  Resource, GPU quantity, or offering mode differs from the public offer
- **THEN** listing creation fails before local listing persistence or registry
  publication

#### Scenario: Capacity changes after publication

- **WHEN** a configured site emits a consuming, releasing, or mixed-direction
  capacity delta
- **THEN** the kit obtains exact site-keyed projections, asks the domain hooks
  for the affected candidates, and executes deterministic close-before-reopen
  reconciliation over the listings whose backing is reconciled by availability

#### Scenario: Recovery loses an in-memory routing cache

- **WHEN** commit, release, or fulfillment resumes after restart
- **THEN** the effect is sent only to the site in the persisted binding, through
  the kit's capacity effects, and a missing or unconfigured binding fails closed
  without authority fan-out

#### Scenario: A pool cannot deliver the advertised mode

- **WHEN** a candidate's selected Resource Pool does not declare the candidate
  offering mode or its listing codec projects another mode
- **THEN** publication is rejected before registry or capacity effects

#### Scenario: Two bindings differ only in backing

- **WHEN** a supplied binding equals a persisted binding in site, mode, and source
  but carries a different backing
- **THEN** the two are unequal, and the kit refuses to publish, close, or reopen
  under the persisted binding

### Requirement: Pre-terms mechanism dispatch is registration-owned

The settlement mechanism for a deal MUST be resolved exactly once, from the buyer's settlement selection or the existing legacy flat-proposal coercion. Pre-terms option interpretation MUST use that registration and the domain's corresponding supported-stage entry. Domain composition MUST dispatch the accepted Agreement through its role table; mechanism-specific validation, mandate construction and settlement translations belong to that entry, not schema-opaque core or common delivery.

#### Scenario: A third mechanism is composed

- **WHEN** a new mechanism registration and supporting role stage are added to a domain and enabled in `[Settlement]`
- **THEN** its options use the registration and its accepted Agreements use that domain's declared stage without another mechanism conditional

#### Scenario: A mechanism conditional is sought in domain code

- **WHEN** the pre-terms path of any composed domain is inspected
- **THEN** concrete-mechanism dispatch exists only in its role table, and any mechanism-specific validation is inside the selected entry's owned hooks

### Requirement: Deal identity is mechanism-neutral for every mechanism

Every accepted deal MUST retain its negotiation ID and exact Agreement. Mechanisms using the obligation runtime MUST have a durable `settlement_obligations` record keyed by `obligation_ref`, with the mechanism's identifier as `mechanism_ref`. Arkhai payments MUST instead correlate its accepted mandate and transaction evidence by negotiation ID; its transaction ID MUST NOT be represented as an escrow obligation.

#### Scenario: An Alkahest deal is recorded neutrally

- **WHEN** an Alkahest deal settles
- **THEN** it has a `settlement_obligations` record whose `mechanism_ref` is the
  escrow uid, in addition to its legacy mechanism-surface records

### Requirement: Delivery sinks compose without importing implementations

Core and kit packages MUST assemble a configured delivery sink set through the
installed-plugin contract alone and MUST NOT import, name, or branch on any
concrete sink implementation. Enabling delivery MUST NOT make a mechanism kit a
dependency of a core role package, and a sink MUST NOT be reachable only by
importing a composition root. A sink that fails to load, fails to deliver, or
blocks MUST NOT degrade registry discovery, negotiation, settlement, servicing, or
command assembly.

#### Scenario: Core delivers without depending on a mechanism kit

- **WHEN** the core buyer role package delivers a revealed introduction
- **THEN** it resolves sinks through the plugin contract and imports no
  mechanism-specific package to do so

#### Scenario: A sink degrades

- **WHEN** an installed sink raises on load or blocks while delivering
- **THEN** market orchestration on that side proceeds unchanged and the sink is
  reported as a local delivery fault

### Requirement: Arkhai payment request and receipt authentication

Headless calls to the Arkhai payments service MUST authenticate with WorkOS user-scoped API keys issued for the caller's Arkhai account. Arkhai payment receipts MUST use the service's Ed25519 `arkhai.payments.receipt.v1` signature framing and be verified through the identity kit. A receipt MUST verify only when its signed `livemode` equals the verifying role's configured `livemode`: a test-mode receipt never proves a live payment, and a live receipt never satisfies a test deployment. Marketplace registry, storefront, and negotiation request authentication MUST remain on their existing contracts and MUST NOT become a cross-repository source dependency.

#### Scenario: Arkhai payment request is authenticated

- **WHEN** a buyer or seller kit calls the Arkhai payments service
- **THEN** the request uses the owner's WorkOS user-scoped API credential, and the caller verifies a returned receipt with the published signature contract rather than copying marketplace request-signing code

#### Scenario: A receipt from the other mode proves nothing

- **WHEN** a buyer or seller stage receives a correctly signed receipt for the accepted mandate whose signed `livemode` differs from the stage's configured `livemode`
- **THEN** the receipt does not verify, the stage produces no verified settlement evidence, and delivery or issuance stays blocked

### Requirement: Arkhai payments registers as a peer settlement mechanism

A domain composition that supports Arkhai payments MUST register `arkhai.payments.v1` beside `alkahest.v1` through the shared typed settlement registration surface. Selection MUST pin one exact mechanism and option, and core MUST dispatch without a mechanism-specific branch. A domain MUST NOT require or install the Arkhai payments client when that registration is absent.

#### Scenario: A domain registers both peer mechanisms

- **WHEN** a domain installs `alkahest.v1` and `arkhai.payments.v1`
- **THEN** both options appear through their registrations and each accepted Agreement dispatches to its selected settlement stage

#### Scenario: A domain omits Arkhai payments

- **WHEN** a domain installs Alkahest without the Arkhai payments kit
- **THEN** it publishes no Arkhai payment option and acquires no Arkhai payment-service dependency

### Requirement: Deals compose negotiate, settle, and provision stages

Negotiation MUST pass its exact accepted Agreement to the domain's selected settlement stage. Protected delivery MUST consume that stage's verified SettlementEvidence rather than compare mechanism IDs or infer payment from an escrow's presence. Core MUST NOT prescribe the actors' order or require separate buyer-confirm and seller-verify steps. Domains MUST compose only supported stages; settlement and delivery MAY be fused.

#### Scenario: Arkhai payment gates domain provisioning

- **WHEN** the seller settles an accepted Agreement through `arkhai.payments.v1`
- **THEN** VM, bare-metal or API-credit delivery remains blocked until its stage verifies a signed receipt matching the transaction ID and Agreement deal hash and produces verified evidence

### Requirement: Domains compose only the stages they support

A domain MUST compose only mechanism stages it supports, and each stage MUST understand its predecessor's output rather than a shared escrow adapter API. Settlement and provisioning MAY be fused when one mechanism provides both, as `contact-exchange.v1` does.

#### Scenario: A domain composes two settlement mechanisms

- **WHEN** a domain advertises both Alkahest and Arkhai payment options
- **THEN** its role table routes each accepted Agreement to the selected stage and compatible delivery reads normalized evidence without a new core or delivery mechanism conditional

#### Scenario: A settlement mechanism also provides the service

- **WHEN** a deal selects `contact-exchange.v1`
- **THEN** the composed stage may fuse settlement and delivery, produce its introduction evidence and invoke no payment or physical-provisioning phase

#### Scenario: A mechanism requires seller action first

- **WHEN** a supporting domain composes a stage whose first effect belongs to the seller
- **THEN** core dispatches that role's entry without requiring a prior buyer deposit, confirmation or escrow proposal

### Requirement: Arkhai payments authority remains external

`kit/arkhai-payments` MUST consume the payments service's published HTTP and JSON Schema contract, vendored with its conformance vectors and identified by content hash rather than by source location, and generate its Python wire models from it, rather than importing the service implementation or copying a TypeScript contract. The payments service MUST remain the authority for its ledger, account credentials, fees, hold release, dispute attachment, and payment-provider operations.

#### Scenario: Payments service owns the ledger

- **WHEN** a marketplace domain composes `arkhai.payments.v1`
- **THEN** it uses the external payments API and signed receipt as authority and keeps no local ledger, payment-provider integration, or settlement daemon

### Requirement: Marketplace roles hold no payment ledger

Marketplace roles MUST NOT own ledger state or implement cash movement, Stripe top-ups, payouts, or provider recovery. The kit MUST keep no settlement servicing state or daemon; headless callers supply owner-scoped credentials per request and verify service-signed receipts through the identity kit.

#### Scenario: A headless caller checks a payment

- **WHEN** a buyer or seller process checks a payment
- **THEN** it supplies its owner-scoped credential for that request and verifies the service-signed receipt through the identity kit, keeping no servicing state between calls

### Requirement: Buyer dispatch preserves Agreement-only settlement

Core buyer settlement MUST select the composing domain's role-table entry using `Agreement.settlement.mechanism` and pass the accepted outcome unchanged. It MUST NOT choose a path from escrow-proposal presence, infer escrow terms, synthesize an obligation or select a replacement mechanism. A missing accepted entry MUST fail before settlement effects.

#### Scenario: Payments outcome has no escrow proposal

- **WHEN** an accepted Agreement selects Arkhai payments and its outcome contains no escrow proposal
- **THEN** the declared Arkhai buyer entry receives the exact accepted outcome

#### Scenario: Alkahest outcome contains its proposal

- **WHEN** an accepted Agreement selects Alkahest
- **THEN** its declared buyer entry reads the proposal from the outcome and core does not use that field to choose the entry

#### Scenario: Accepted mechanism has no stage

- **WHEN** accepted durable work names an unavailable role-table entry
- **THEN** settlement fails actionably before a mutation and never falls through to another mechanism

### Requirement: One settlement declaration per domain role

Each settlement-capable domain role MUST declare one immutable table from canonical mechanism ID to domain-owned stage. Core MUST require only the table and evidence carrier, not shared stage methods. Mechanism IDs MUST NOT select behavior elsewhere in domain orchestration; mechanism-owned input validation inside an entry remains permitted. Fresh admission MUST expose only supported entries.

#### Scenario: Role support differs

- **WHEN** a domain's seller supports several stages but its buyer supports one
- **THEN** each role exposes exactly its declared support and neither role inherits another role's stage or default

#### Scenario: Composition is incomplete

- **WHEN** a settlement-capable role supplies no valid table or duplicate/invalid entry identities
- **THEN** composition rejects it before publication, negotiation or settlement effects

### Requirement: Core evidence shape and domain payload ownership

SettlementEvidence MUST carry `negotiation_id`, `mechanism`, opaque `settlement_ref`, domain-defined `status` and domain-owned `evidence`. Core MUST preserve identities and validate shared shape without interpreting the payload, prescribing status transitions or treating a mechanism ID as delivery permission. Stages MUST keep credentials out of evidence.

#### Scenario: Evidence crosses the domain delivery boundary

- **WHEN** a selected stage hands evidence to delivery
- **THEN** the accepted negotiation and established reference remain unchanged and only the domain interprets its validated payload

#### Scenario: Buyer progress is not seller authorization

- **WHEN** a buyer reports local settlement completion but the seller has not verified authoritative evidence
- **THEN** seller protected delivery remains blocked

### Requirement: Mechanism continuation stays stage-owned

Mechanism-specific post-delivery attestation, claim binding, compensation and source-evidence revalidation MUST remain in the selected stage's continuation. Common delivery and restart runtimes MUST consume validated evidence and domain results without comparing mechanism IDs. Recovery MUST resolve the stage from accepted state, not current priority or serialized executable objects.

#### Scenario: Physical delivery needs an Alkahest attestation

- **WHEN** common physical delivery returns its result to an Alkahest stage
- **THEN** that stage handles its attestation and claim binding while the common delivery runtime recognizes no mechanism ID

#### Scenario: Receipt-backed work resumes

- **WHEN** a payment stage resumes delivery after restart
- **THEN** it revalidates its stored receipt before passing evidence to common recovery and reuses accepted operation identities

#### Scenario: A servicing worker's hook needs a stage continuation

- **WHEN** a generic settlement servicing worker reports an obligation ready or ended
- **THEN** the domain resolves the continuation from the seller entry the accepted Agreement selected, and the hook compares no mechanism ID

#### Scenario: A stage requires seller action first

- **WHEN** a domain composes a supporting stage whose first effect belongs to the seller
- **THEN** core dispatches its role entry without requiring a prior buyer deposit, confirmation or escrow proposal

### Requirement: Family-grouped capability shapes share one flattening contract

A capability shape MUST be expressed in the family-grouped form: a mapping of family name to
a mapping of field name to a scalar value. One shared utility in a foundation kit that imports
only the standard library MUST validate that form's structure, flatten a shape into
quantities and attributes, and compute a canonical digest of a shape. The utility is capacity
vocabulary rather than part of the market core, because only markets that admit capacity
against declared supply have shapes; the market core MUST NOT carry it.

- **Schema.** Flattening MUST be driven by a schema the owning domain supplies. For each
  family field the schema states whether it is a quantity or an attribute, whether it is
  required, and its flat name. The utility MUST NOT contain any domain's family or field
  names.
- **Digest.** The canonical digest MUST be taken over the family-grouped form, so changing a
  schema's flat names does not change a shape's digest.
- **Refusals.** A shape naming a family or field its schema does not define, missing a
  required field, or carrying a value of the wrong kind MUST be refused with the offending
  path named.
- **Inverse.** The utility MUST build a family-grouped shape from flat quantities and
  attributes through a schema, as the exact inverse of flattening, refusing every flat name
  the schema does not define and every problem flattening would refuse.
- **One implementation.** Kit, role, and domain code that needs to validate, flatten,
  unflatten, or digest a capability shape MUST use this utility rather than a local
  implementation.

#### Scenario: The VM domain flattens a shape

- **WHEN** a VM shape `{gpu: {count: 1, model: H100}, memory: {gib: 64}}` is flattened with
  the VM schema
- **THEN** the result's quantities are `gpu_count: 1` and `ram_gb: 64` and its attributes
  are `gpu_model: H100`

#### Scenario: A schema renames a flat field

- **WHEN** a domain's schema changes the flat name of a field
- **THEN** the digest of every shape using that field is unchanged

#### Scenario: A shape names an undefined field

- **WHEN** a shape names a field the supplied schema does not define
- **THEN** flattening refuses it and names the family and field

#### Scenario: Structure is checked without a schema

- **WHEN** a shared kit validates a shape's structure without a domain schema
- **THEN** it accepts any well-formed family-grouped mapping and refuses only malformed
  structure

#### Scenario: A declaration is read back into a shape

- **WHEN** flat quantities `gpu_count: 8`, `ram_gb: 2048` and attribute `gpu_model: H200` are
  unflattened with the compute-family schema
- **THEN** the shape is `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`, and flattening
  it returns the same flat values

#### Scenario: A flat name is outside the schema

- **WHEN** a flat quantity the schema does not name is unflattened
- **THEN** the utility refuses it, naming the flat field

### Requirement: The compute family shares one capability schema

The compute-family capability schema — the families `gpu`, `cpu`, `memory`, and `storage`,
their fields, and each field's flat name — MUST be owned by one compute-family domain package
that every compute domain binds. The VM and bare-metal domains MUST NOT each define a schema,
and neither MUST obtain the schema by importing the other. The package MUST depend only on
the standard library and the capability-shape foundation kit.

#### Scenario: Two compute domains flatten one shape

- **WHEN** the VM and bare-metal domains each flatten `{gpu: {count: 8, model: H200}, memory: {gib: 2048}}`
- **THEN** both produce `gpu_count: 8`, `ram_gb: 2048`, and `gpu_model: H200` through the
  same schema object

#### Scenario: The bare-metal storefront binds the schema

- **WHEN** the bare-metal storefront's import boundary is checked
- **THEN** it imports the compute-family package and no VM package

### Requirement: Capability shape admissibility is owned by one kit

A foundation kit SHALL own the admissibility of capability shapes, depending only on the
capability-shape kit and the standard library, so storefronts, buyers, and pool
administration can all depend on it. It SHALL be the only reader of a shape constraint:
every other caller SHALL hold a parsed declaration and a resolved policy as opaque
values, and SHALL obtain a stated listing shape's base shape from the kit rather than by
reading its constraints.

The kit SHALL expose two groups of operations.

**Declaration handling**, each given a tier label that every problem it returns, and
every problem resolution later returns about it, SHALL carry:

- splitting a stated listing shape into its base shape and either its declaration or its
  constraint problems. Without a schema it SHALL check structure only; given a domain's
  capability schema it SHALL also check that every constrained path is a quantity field
  the schema defines. The kit SHALL know no family or field name. It SHALL read the base
  shape first: a constraint that leaves the base shape unreadable under the schema SHALL
  be reported as a base-shape problem with no declaration, and only a constraint error
  on a readable base shape SHALL be a constraint problem.
- splitting a stated list of listing shapes entry by entry, and reporting each base shape
  that two entries state with different constraints, naming each conflicting entry,
  without needing a schema. Entries identical in base shape and constraints SHALL
  collapse to one. No caller SHALL compare two entries itself.
- parsing a constraint-only declaration, which states no offer.
- resolving declarations given highest tier first, with a schema, into a resolved policy
  or every problem found. Each constraint form SHALL own its merge rule. An empty range
  SHALL be a problem naming each tier's conflicting value.

**Evaluation on a resolved policy**, neither returning unconditional bounds:

- a check of a whole shape that returns every problem found, empty when the shape is
  admissible, each problem naming every `family.field` path it involves, a code, a
  message, and its tier. A shape malformed under the policy's schema SHALL be reported
  as problems; the schema's required fields SHALL NOT be checked.
- the values one dimension may take given a partial shape: those for which the partial
  shape, with that dimension set to the value, can still be completed to an admissible
  shape. Dimensions the partial shape does not state are free; a value it states for the
  requested dimension is ignored; an empty partial shape is valid. A dimension that is
  not a quantity the schema defines, or a partial shape malformed under the schema,
  SHALL raise an error carrying every problem.

The returned values SHALL be an opaque set answering membership, emptiness, the greatest
admissible value not above a given value, the least not below it, and its minimum and
maximum, where an absent maximum means unbounded. An empty set SHALL report itself
empty and contain no value, and each of its value-returning accessors SHALL answer
nothing. No operation SHALL return a range for a dimension independent of the rest of a
shape. An answer SHALL be valid only for the partial shape it was computed
from. Fixing dimensions one at a time, in any order, each to a value from the current
answer SHALL never leave a later answer empty and SHALL end at an admissible shape.

A shape SHALL be admissible exactly when it can be completed to an admissible shape, so
a dimension a shape omits never makes it inadmissible by its absence.

#### Scenario: A shape outside one bound

- **WHEN** a shape states a quantity above the resolved maximum for that field
- **THEN** the check returns one problem naming that field's path and the tier that set
  the maximum, and no problem for any field within its bounds

#### Scenario: A shape inside every bound

- **WHEN** every quantity a shape states lies within its field's resolved bounds
- **THEN** the check returns no problems

#### Scenario: A shape omits a bounded field

- **WHEN** a resolved policy bounds a field with a minimum and a shape does not state
  that field
- **THEN** the shape is admissible

#### Scenario: Admissible values are requested for one dimension

- **WHEN** the values for a bounded dimension are requested with a partial shape whose
  stated dimensions are admissible
- **THEN** the answer contains exactly the resolved range for that dimension and answers
  the greatest admissible value not above a requested one

#### Scenario: The partial shape is already inadmissible

- **WHEN** the values for one dimension are requested with a partial shape that states
  another dimension outside its bounds
- **THEN** the answer is empty

#### Scenario: Values are requested for a field that is not a quantity

- **WHEN** the values are requested for an attribute, or for a path the schema does not
  define
- **THEN** the request raises an error naming the path, and no empty answer is returned

#### Scenario: Values are requested from an empty partial shape

- **WHEN** the values for a bounded dimension are requested with a partial shape stating
  nothing
- **THEN** the answer is that dimension's resolved range

#### Scenario: A counter-shape is built one dimension at a time

- **WHEN** a policy fixes each dimension in turn to a value from the current answer for
  that dimension
- **THEN** no answer along the way is empty and the resulting shape has no problems

#### Scenario: Tiers merge per field

- **WHEN** a higher tier bounds only the maximum of a field and a lower tier bounds its
  minimum and maximum
- **THEN** the resolved policy takes the higher tier's maximum and the lower tier's
  minimum

#### Scenario: A higher tier omits a lower tier's bound

- **WHEN** a lower tier bounds a field and a higher tier states nothing for it
- **THEN** the resolved policy keeps the lower tier's bound

#### Scenario: Tiers merge to an empty range

- **WHEN** a lower tier states a minimum above a higher tier's maximum for one field
- **THEN** resolution returns a problem naming the field and both tiers with their
  values, and no policy

#### Scenario: The kit is used by a domain it does not know

- **WHEN** declarations and shapes are expressed in a schema with no compute vocabulary
- **THEN** every operation behaves as for any other schema, and the kit imports nothing
  beyond the capability-shape kit and the standard library

### Requirement: Shape constraints are stated inline and strictly

A stated listing shape SHALL be able to give any quantity field a constraint mapping in
place of its scalar value. The mapping SHALL hold `offer`, `min`, `max`, or any of them
but not none; each SHALL be a positive integer, `min` SHALL NOT be above `max`, and an
`offer` SHALL lie within the field's own `min` and `max`. A plain scalar SHALL be
shorthand for a mapping holding only `offer`. The listing's base shape SHALL hold each
field's offer and SHALL omit a field whose mapping states none. An offer without `min`
or `max` SHALL NOT constrain the field. A constraint-only declaration SHALL use the same
field syntax without `offer`. Under the `min`/`max` merge rule, for each field's `min`
and `max` the highest tier stating it SHALL win, and a tier that does not state one SHALL
leave a lower tier's value in place. The admissible region SHALL be the intersection of
every constraint. A key the kit does not define SHALL make the shape's constraints
unreadable rather than be ignored.

#### Scenario: A field carries an unknown key

- **WHEN** a constraint mapping holds a key other than `offer`, `min`, and `max`
- **THEN** splitting returns a constraint problem naming the path and no declaration

#### Scenario: A constraint names an attribute

- **WHEN** a shape is split with a domain's schema and gives a constraint mapping to a
  field the schema defines as an attribute, or does not define
- **THEN** splitting returns a constraint problem naming that path

#### Scenario: An offer lies outside its own range

- **WHEN** a constraint mapping states an `offer` above its `max` or below its `min`
- **THEN** splitting returns a constraint problem, with or without a schema

#### Scenario: A constraint mapping is empty

- **WHEN** a field's constraint mapping states no key
- **THEN** splitting returns a constraint problem naming the path

#### Scenario: A field constrains without offering

- **WHEN** a shape gives `memory.gib` only a `max`
- **THEN** the base shape omits `memory.gib`, and the policy bounds a shape that states it

#### Scenario: An offer alone does not constrain

- **WHEN** a shape states `cpu.count` as a plain scalar and no tier bounds it
- **THEN** the base shape states that count, and a shape stating any other count is
  admissible on that field

#### Scenario: A constraint removes a required field from the base shape

- **WHEN** a shape is split with a schema that requires a field, and the shape gives that
  field a constraint mapping with no `offer`
- **THEN** splitting returns a base-shape problem naming the field as required, and no
  declaration

#### Scenario: A list states one base shape with different constraints

- **WHEN** a stated list is split, with or without a schema, and two entries share a base
  shape but differ in their constraints
- **THEN** the split reports that base shape as conflicting, naming both entries

#### Scenario: A list repeats an identical entry

- **WHEN** a stated list holds two entries identical in base shape and constraints
- **THEN** the split yields that entry once and reports no problem

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
mount its rule and evaluate-job routes under its own prefix, contributing their route
contracts from the family's template instantiated with its mount; job draining and
waiting MUST stay shared.
The test route service MUST answer with response models the compute family's contracts
distribution owns, so every adapter's rule routes answer the same typed shapes.

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

#### Scenario: Two adapters' rule routes answer one shape

- **WHEN** a scenario lists the rules installed through VM's and through bare metal's rule
  routes
- **THEN** both answers are the family's typed rule models

### Requirement: Per-site projection state is kit-owned and held once per process

The storefront-side capacity and publication kit MUST own per-site projection state: for
every site a storefront's aggregate capacity client names, the resource-pool and
capacity-bucket projections, their poller, a per-site refresh, the poller's cycle on demand,
the drift check a topology-sensitive error triggers, and a per-site, per-family status. A
storefront that derives listings from site projections MUST compose exactly one instance per
process, built by its composition root and injected into every
consumer; the kit MUST NOT keep that state at module level, and a domain MUST NOT keep a
projection cache of its own. The poller MUST run as a loop registered with the storefront's
loop controller, and its step MUST run exactly the poller's cycle. The state MUST be
domain-neutral: it holds whatever generation a site serves, and a domain's acceptance rules
for a generation apply when that domain reads it. It MUST run one operation at a time on a
site's family, including its version check, so a caller arriving during an operation waits for
it and a failed operation never replaces a confirmation that completed after it began.

#### Scenario: Two consumers read one site

- **WHEN** a storefront's publication cycle and its opening recheck both read one site's
  resource-pool projection
- **THEN** both read the same held generation from the one instance their composition root
  built, and neither fetches the site

#### Scenario: The projection step is run while held

- **WHEN** an operator runs one cycle of the site-projection loop while the loops are held
- **THEN** exactly the poller's cycle runs, waking publication if a resource-pool
  generation changed, and the loops remain held

#### Scenario: One domain refuses a generation

- **WHEN** a site serves a generation one domain's acceptance rule refuses
- **THEN** the state holds that generation, the refusing domain holds that site's listings,
  and any other reader of the state still reads it

### Requirement: A loop records each cycle's outcome with the controller

A storefront loop whose cycle can fail MUST record each cycle's outcome with the kit loop
controller, whether its timer or an operator's step ran the cycle: when it finished,
whether it completed, and, for a failure, the stage that failed and its error. Each
invocation MUST record exactly one terminal outcome, including one that raised, and a
preview MUST record none; a step cancelled while it waits for the loop's lock records a
cancelled outcome naming no stage, because no stage began. A recorded error MUST carry the exception's type and MUST carry its
message only when the storefront's own configuration or publication error raised it, so no
credential, secret, or private URL reaches status. The controller MUST be the one place a loop's cycle runs: a loop
registers its step and its interval, the controller's timer runs the step through the same
operation an operator's step does, and that operation holds the loop's lock, so the timer and a
step never run a cycle concurrently. A kit runtime that fans one loop out into independent
per-site cycles MUST serialize each site's cycle and that site's step instead, and MUST record
each site's timer cycle with the controller under that site's own loop name.
The controller MUST report, in one snapshot, every loop's state and the last outcome each loop
recorded, for a storefront's system status to read; a loop that has exited or been cancelled
MUST remain distinguishable from a running loop whose last cycle failed.

#### Scenario: A stepped cycle fails

- **WHEN** an operator steps the publication loop and the cycle fails
- **THEN** the controller's snapshot reports that cycle as failed with its error, as it
  would for a timer-run cycle

#### Scenario: A step is requested while the timer's cycle runs

- **WHEN** an operator steps a loop whose timer cycle is in progress
- **THEN** the step runs after that cycle completes, never alongside it, and each records its
  own outcome

#### Scenario: One site's capacity-event feed fails

- **WHEN** one site's capacity-event poller cycle fails while another site's succeeds
- **THEN** the controller's snapshot reports the failing site's loop with that cycle failed, by
  its error's type, and the other site's loop with its own outcome

#### Scenario: A cycle fails on an unexpected exception

- **WHEN** a publication cycle raises an exception that is not one of the storefront's own
  errors, with a message naming a site URL
- **THEN** the recorded outcome names the failing stage and the exception's type, and not its
  message

## Evidence

- Layer, scope, and kind rules over every project: `make check-architecture`, `docs/development/ARCHITECTURE.toml`, `scripts/architecture.py`, and `scripts/tests/test_architecture.py`; VM concept-module and contract-construction guardrails: `domains/vms/storefront/tests/unit/test_architecture_imports.py`.
- Core CLI fallback and shipped plugin contracts: `core/buyer/tests/unit/test_cli.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Distribution entry points: `core/buyer/pyproject.toml`, `domains/vms/buyer/pyproject.toml`, and `domains/apicredits/buyer/pyproject.toml`.
- Frozen storefront registry, startup discovery, record-bound lifecycle carriers, and exact-object resolution: `core/storefront/tests/unit/test_domain_registry.py`, `test_domain_plugins.py`, `test_app_composition.py`, and `test_domain_lifecycle.py`.

- One schema-driven flattening of family-grouped capability shapes, its canonical digest, and its standard-library-only boundary: `kit/capability-shape/tests/unit/test_capability_shape.py`, with its empty `allowed-dependencies` in `kit/capability-shape/pyproject.toml`; the VM family schema against `DIMENSION_KEYS`: `domains/vms/domain/tests/test_capability_shapes.py` and `test_schema.py`.
- The schema-driven inverse of flattening: `kit/capability-shape/tests/unit/test_capability_shape.py`.
- Capability shape admissibility — splitting, list-level conflicts, labelled resolution, evaluation, the opaque value set, the one-dimension-at-a-time guarantee as a property test, and neutrality against a synthetic schema: `kit/capability-admissibility/tests/unit/test_admissibility.py`; its dependency on the shape kit and the standard library alone is its package allowlist, held by `make check-architecture`.
- One compute-family capability schema bound by both compute domains: `domains/compute/tests/test_capability_schema.py`, `domains/vms/domain/tests/test_compute_requirements.py`, and the compute vocabulary's `allowed-dependencies` and the sibling-domain scope rule, both held by `make check-architecture`.
