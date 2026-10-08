# Market Composition Specification

## Purpose

Define the dependency direction and role/domain/plugin boundaries that keep market orchestration schema-opaque.

## Requirements

### Requirement: Schema-opaque core orchestration

Core role packages MUST own discovery and negotiation control flow without importing a concrete market domain or settlement mechanism. Core MUST expose the accepted Agreement and settlement-option carriers but MUST NOT impose a shared settlement-stage API or escrow lifecycle on mechanism and domain compositions.

#### Scenario: Installing core without a domain plugin

- **WHEN** the core buyer CLI runs without a domain entry-point plugin
- **THEN** it exposes generic discovery and negotiation behavior and no concrete market verbs or settlement implementation

### Requirement: Domain-owned deterministic semantics
A domain package MUST own the listing, message, terms, materialization, receipt, result vocabulary, and pure interpretation required for independent implementations of that market to agree.

#### Scenario: Adding a market domain
- **WHEN** a new listing schema is introduced
- **THEN** its deterministic codecs and reference semantics can be installed without modifying core orchestration

### Requirement: From-below kit dependencies
Kit and domain concept modules MUST NOT depend on core composition packages; role implementations MAY depend on both the relevant core role and domain/kit contracts.

#### Scenario: Architecture boundary tests run
- **WHEN** imports are checked for core, kit, and domain concept packages
- **THEN** core has no domain imports and from-below modules have no upward composition imports

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
and the acceptance chokepoint. A domain MUST inject its listing resolver, schema codecs,
seller policy, configuration-derived values, accepted-artifact builder, and domain
persistence/effect hooks; neither the kit nor core may import a concrete domain or infer a
domain by inspecting terms, proposals, listings, or persisted payloads.

#### Scenario: A domain runs a negotiation round

- **WHEN** a VM or API-credit storefront processes a signed negotiation request
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
timer does not. A loop with no timer MAY register a step alone.

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

Every capacity-backed publication candidate MUST carry one exact durable
`CapacityBinding(site_id, offering_mode, source_id)`: trusted `site_id`,
pool-declared `offering_mode`, and opaque domain-owned `source_id`. The public
offer's mode MUST equal the binding's
mode. Reservation, commit, release, close, reopen, and restart recovery MUST
reload and compare the same binding and MUST NOT infer a home site, default an
offering mode, choose an authority from response data, or fan out after a
binding is recorded.

#### Scenario: A domain publishes a capacity-backed candidate

- **WHEN** the domain derives a schema-valid candidate from a trusted site
  projection
- **THEN** the kit publishes it only after the domain hook confirms that its
  exact site, source, and advertised offering mode equal durable local state

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
  reconciliation

#### Scenario: Recovery loses an in-memory routing cache

- **WHEN** commit, release, or fulfillment resumes after restart
- **THEN** the effect is sent only to the site in the persisted binding, and a
  missing or unconfigured binding fails closed without authority fan-out

#### Scenario: A pool cannot deliver the advertised mode

- **WHEN** a candidate's selected Resource Pool does not declare the candidate
  offering mode or its listing codec projects another mode
- **THEN** publication is rejected before registry or capacity effects

### Requirement: Pre-terms mechanism dispatch is registration-owned

The settlement mechanism for a deal MUST be resolved exactly once, from the buyer's
settlement selection or the legacy flat-proposal coercion, and pre-terms option interpretation MUST use that registration. Domain composition MUST dispatch the accepted Agreement to its supported settlement stage; mechanism-specific mandate and provisioning translations belong to that composition, not schema-opaque core.

#### Scenario: A third mechanism is composed

- **WHEN** a new mechanism registration is added to a domain's composition root and
  enabled in `[Settlement]`
- **THEN** its options use the registration, and a supporting domain explicitly composes its settlement and provisioning stages

#### Scenario: A mechanism conditional is sought in domain code

- **WHEN** the pre-terms path of any composed domain is inspected
- **THEN** no `if <mechanism> … else` branch on a concrete mechanism identifier exists
  outside the composition root's registration list

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

Headless calls to the Arkhai payments service MUST authenticate with WorkOS user-scoped API keys issued for the caller's Arkhai account. Arkhai payment receipts MUST use the service's Ed25519 `arkhai.payments.receipt.v1` signature framing and be verified through the identity kit. Marketplace registry, storefront, and negotiation request authentication MUST remain on their existing contracts and MUST NOT become a cross-repository source dependency.

#### Scenario: Arkhai payment request is authenticated

- **WHEN** a buyer or seller kit calls the Arkhai payments service
- **THEN** the request uses the owner's WorkOS user-scoped API credential, and the caller verifies a returned receipt with the published signature contract rather than copying marketplace request-signing code

### Requirement: Arkhai payments registers as a peer settlement mechanism

A domain composition that supports Arkhai payments MUST register `arkhai.payments.v1` beside `alkahest.v1` through the shared typed settlement registration surface. Selection MUST pin one exact mechanism and option, and core MUST dispatch without a mechanism-specific branch. A domain MUST NOT require or install the Arkhai payments client when that registration is absent.

#### Scenario: A domain registers both peer mechanisms

- **WHEN** a domain installs `alkahest.v1` and `arkhai.payments.v1`
- **THEN** both options appear through their registrations and each accepted Agreement dispatches to its selected settlement stage

#### Scenario: A domain omits Arkhai payments

- **WHEN** a domain installs Alkahest without the Arkhai payments kit
- **THEN** it publishes no Arkhai payment option and acquires no Arkhai payment-service dependency

### Requirement: Deals compose negotiate, settle, and provision stages

A deal MUST flow from negotiation to a selected settlement stage and then to domain provisioning. Negotiation MUST pass its exact accepted Agreement to the selected settlement stage. That stage MUST return its own settlement evidence; the domain's provisioning stage MUST consume that evidence and translate it into the domain's internal paid or ready form.

#### Scenario: Arkhai payment gates domain provisioning

- **WHEN** the seller settles an accepted Agreement through `arkhai.payments.v1`
- **THEN** VM, bare-metal, or API-credit provisioning remains blocked until the seller verifies a signed receipt matching the transaction ID and Agreement deal hash

### Requirement: Domains compose only the stages they support

A domain MUST compose only mechanism stages it supports, and each stage MUST understand its predecessor's output rather than a shared escrow adapter API. Settlement and provisioning MAY be fused when one mechanism provides both, as `contact-exchange.v1` does.

#### Scenario: A domain composes two settlement mechanisms

- **WHEN** a domain advertises both Alkahest and Arkhai payment options
- **THEN** its composition routes each accepted Agreement to the selected mechanism stage and passes that stage's evidence to compatible provisioning without a new core mechanism conditional

#### Scenario: A settlement mechanism also provides the service

- **WHEN** a deal selects `contact-exchange.v1`
- **THEN** the composed mechanism may fuse settlement and provisioning into one stage that consumes the negotiation output

### Requirement: Arkhai payments authority remains external

`kit/arkhai-payments` MUST consume the published HTTP and JSON Schema contract from `arkhai-io/arkhai-payments` and generate its Python wire models from it, rather than importing the service implementation or copying a TypeScript contract. The payments service MUST remain the authority for its ledger, account credentials, fees, hold release, dispute attachment, and payment-provider operations.

#### Scenario: Payments service owns the ledger

- **WHEN** a marketplace domain composes `arkhai.payments.v1`
- **THEN** it uses the external payments API and signed receipt as authority and keeps no local ledger, payment-provider integration, or settlement daemon

### Requirement: Marketplace roles hold no payment ledger

Marketplace roles MUST NOT own ledger state or implement cash movement, Stripe top-ups, payouts, or provider recovery. The kit MUST keep no settlement servicing state or daemon; headless callers supply owner-scoped credentials per request and verify service-signed receipts through the identity kit.

#### Scenario: A headless caller checks a payment

- **WHEN** a buyer or seller process checks a payment
- **THEN** it supplies its owner-scoped credential for that request and verifies the service-signed receipt through the identity kit, keeping no servicing state between calls

### Requirement: Buyer dispatch preserves Agreement-only settlement

`make_settle_hook` MUST route a selected negotiation outcome with no escrow proposal to the composing domain's `agreement_settlement` stage. Core MUST pass the outcome unchanged and MUST NOT infer escrow terms, synthesize an obligation, or select a replacement mechanism.

#### Scenario: Payments outcome has no escrow proposal

- **WHEN** an accepted outcome has a settlement selection and no escrow proposal
- **THEN** the injected Agreement settlement stage receives the exact outcome
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

## Evidence

- Import boundaries: `core/tests/unit/test_carrier_purity.py` and `domains/vms/storefront/tests/unit/test_architecture_imports.py`.
- Core CLI fallback and shipped plugin contracts: `core/buyer/tests/unit/test_cli.py`, `domains/vms/buyer/tests/test_plugin_export.py`, and `domains/apicredits/buyer/tests/test_plugin_export.py`.
- Distribution entry points: `core/buyer/pyproject.toml`, `domains/vms/buyer/pyproject.toml`, and `domains/apicredits/buyer/pyproject.toml`.
- Frozen storefront registry, startup discovery, record-bound lifecycle carriers, and exact-object resolution: `core/storefront/tests/unit/test_domain_registry.py`, `test_domain_plugins.py`, `test_app_composition.py`, and `test_domain_lifecycle.py`.

- One schema-driven flattening of family-grouped capability shapes, its canonical digest, and its standard-library-only boundary: `kit/capability-shape/tests/unit/test_capability_shape.py` and `test_import_boundary.py`; the VM family schema against `DIMENSION_KEYS`: `domains/vms/domain/tests/test_capability_shapes.py` and `test_schema.py`.
- The schema-driven inverse of flattening: `kit/capability-shape/tests/unit/test_capability_shape.py`.
- One compute-family capability schema bound by both compute domains: `domains/compute/tests/test_capability_schema.py` and `test_import_boundary.py`, `domains/vms/domain/tests/test_compute_requirements.py`, and `domains/bare_metal/tests/test_import_boundary.py`.
