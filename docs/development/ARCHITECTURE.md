# Arkhai Market Stack — Architecture Reference

> **Purpose:** Current repository-wide architecture for implementation and review. Detailed normative subsystem contracts live in [`openspec/specs/`](../../openspec/specs/); proposed transitions live in [`openspec/changes/`](../../openspec/changes/). This document describes what the system is and why its major boundaries exist. It is not a backlog or changelog: the goals being pursued and the value each delivers belong to [`ROADMAP.md`](ROADMAP.md), and delivery readiness belongs to [`openspec/changes/README.md`](../../openspec/changes/README.md).

## Document map

| Section | Purpose |
|---|---|
| [System overview](#system-overview) | Marketplace purpose and production shape |
| [Composition from above and below](#composition-from-above-and-below) | Core, kit, domain, and composition-root ownership |
| [Package and dependency layers](#package-and-dependency-layers) | Enforceable one-way package rules |
| [Runtime service map](#runtime-service-map) | Processes, authorities, and principal calls |
| [Authority boundaries](#authority-boundaries) | Which component is authoritative for each kind of state, and how authority is decided |
| [Shared vocabulary and identities](#shared-vocabulary-and-identities) | Official cross-service terms and identifiers |
| [Major lifecycle flows](#major-lifecycle-flows) | Negotiation, settlement servicing, capacity, and fulfillment |
| [Deployment topology](#deployment-topology) | Local and deployed structure, and who operates it |
| [Build, packaging, and initialization](#build-packaging-and-initialization) | Internal wheels, images, migrations, and reinit rules |
| [Recovery workers](#recovery-workers) | Timer-driven durable recovery: capacity, fulfillment convergence, lease expiry |
| [Testing strategy](#testing-strategy) | Test levels; see `TESTING.md` for methodology |
| [Capability documentation index](#capability-documentation-index) | Permanent detailed contracts and rationale |

Directional context — which goals are being pursued, the value each delivers, and which change owns each open gap — lives in [`ROADMAP.md`](ROADMAP.md). This document states what is true now; the roadmap states where it is going.

## System overview

Arkhai is a reference implementation of an agent-driven marketplace. Buyers discover listings through registries, negotiate with seller storefronts through signed synchronous HTTP rounds, settle accepted Agreements through a selected mechanism, then receive domain delivery. Market-domain code defines what is traded; shared role packages provide schema-opaque control flow; reusable kit capabilities provide identity, policy, settlement, capacity, resource-pool, and fulfillment machinery.

Physical delivery is deliberately separate from commercial agreement. A seller may advertise fungible capacity or intentionally expose a specific resource. The storefront owns market-facing listings and deal state. Site authorities own admitted capacity. Resource-pool services own provisioning routing metadata. Fulfillment scheduling binds admitted capacity to a settlement resource, and providers execute against that selected resource.

Not every market has physical delivery. API credits reuse the same schema-opaque negotiation and settlement roles while a quota authority issues prepaid bearer-key balances. They do not acquire compute-provisioning dependencies merely to fit the physical lifecycle.

```text
buyer (`market`) ── discovery ──> registry
       │                            ▲
       └─ signed negotiation ──> storefront
                                  │
                                  ├─ settlement ──> chain / Arkhai payments
                                  └─ capacity + fulfillment ──> site authority / compute provisioner
```

Production permits independently operated registries and seller stacks. Buyers may be ephemeral CLI invocations or long-running agents. Local development adds an Anvil fixture and test-only composition.

## Composition from above and below

A behavior belongs in the market core when it is invariant across listing schemas. Shared carriers define only what at least two of buyer, seller, and registry read: settlement options and the accepted Agreement. Mechanism status, servicing, refunds, and provisioning translations belong to their owning kits and domain compositions. Behavior that varies by schema is supplied from below through injected domain or kit hooks.

The schema-opaque market composition is:

```text
agreement = negotiate(messages...)
evidence  = settle(agreement)
result    = provision(evidence)
```

Core owns schema-opaque carriers and role structure around these phases: signed transport, round sequencing, persistence mechanics, and deterministic handoffs. Domain packages own listing vocabulary, message content, validation, deterministic interpretation of terms, fulfillment requirements, and result vocabulary. Kit packages own reusable mechanisms and authorities, including obligation servicing and stateless payment clients and the shared storefront application/lifecycle shell. Composition roots wire concrete domain and kit implementations into role packages.

Each domain-owned storefront validates one immutable `MarketDomainContract` at its composition boundary before constructing persistence, services, workers, or the HTTP application. The validated object is carried through common listing/negotiation/artifact bindings and lifecycle contexts. Domain contributions expose that contract through `market.storefront_contributions`; shared core dispatch resolves only the frozen domain identity/version and never guesses from a payload or imports the domain.

The VM and bare-metal storefronts can run as separate one-domain processes or as installed contributions selected by a shared shell. Bare metal owns its seller policy, site bindings, and provisioning adapters and imports no VM services. The common binding schema freezes offering mode, domain identity/version, site, and Physical Resource for both shapes, so restart and composition changes do not change the authority selected by an accepted agreement.

The `arkhai-kit-storefront` distribution (`market_storefront_kit`) owns the
shared FastAPI app, lifespan, container, ordered-route, middleware, Alkahest
client-construction, and negotiation-watchdog composition seams. A
domain-owned executable supplies one exact validated contract, immutable
service lifecycle callbacks, its route contribution, and configuration. The
VM, API-credit, and bare-metal roots all use this shell. Domain codecs, policy,
settlement, fulfillment, and publication hooks stay in their injected
contract; neither the kit nor a route recovers them from a global domain
resolver. Extracted kit mechanisms have one implementation: domains retain
only the values and hooks that instantiate them.

Two hooks remain separate when core-owned machinery or a typed invariant sits between them. They may be merged when the core does nothing between them and the split would expose only implementation detail.

The registry is the schema-centralizing point for discovery. A registry publishes one filter/listing schema and remains opaque to market-domain payloads beyond its configured validation and filter vocabulary. A market-domain operator composes the relevant buyer and storefront plugins around that registry schema.

See the [market composition specification](../../openspec/specs/market-composition/spec.md).

## Package and dependency layers

### Repository layers

```text
composition roots / deployed services
        ↓
domain packages and role implementations
        ↓
family kits
        ↓
family vocabulary packages
        ↓
repository-wide kit capabilities
        ↓
core carrier and role contracts
```

Core carrier packages must not import domain vocabulary. Domain packages may implement core hook shapes but should not make core depend on a concrete market. Composition roots own wiring and may depend on all lower layers.

A family vocabulary package holds what sibling domains of one market family share, so they bind one definition instead of importing each other. `domains/compute` (`arkhai_compute`) is the compute family's: the capability schema whose families, fields, and flat names both the VM and bare-metal domains publish, claim, and declare capacity in. It depends only on foundation kits, never on a domain, a role, or core. The vocabulary belongs to neither the market-neutral foundation kit, which knows no family, nor core, which carries no market's vocabulary. See the [market composition architecture](../../openspec/specs/market-composition/architecture.md#the-compute-family-vocabulary).

### Family kits

A family kit owns reusable mechanism, authority, and optionally persistence for concepts whose scope is one market family rather than every market or one concrete domain. It is the operational counterpart to a family vocabulary package. Unqualified "kit" in this document means a repository-wide kit capability, whose abstractions are family-neutral; a family kit is not one, because it speaks its family's vocabulary.

A capability belongs in a family kit when it belongs intrinsically to the family: several sibling domains use it, or it is the family's single cross-domain authority. Code that merely looks similar across domains does not qualify. A family kit stays meaningful independently of any one domain, and a new sibling domain consumes it by contributing values, codecs, hooks, or registrations, never by adding domain-specific branches to it. It carries no concrete domain's listing schema, policy, result meaning, domain-specific infrastructure choices, or composition wiring, so it belongs to no sibling domain.

A family kit may own durable state, workers, and authority lifecycles for its family. It may depend on its family's vocabulary package, repository-wide kit capabilities, core contracts, and lower-level family-kit distributions of the same family. Dependencies among a family's kit distributions must be acyclic: an optional implementation distribution may depend on the family's base mechanisms and authorities, and those base distributions must not depend back on an optional implementation. A family kit must not depend on a concrete domain, another family's packages, a concrete role implementation, or a deployed service. The permitted edges point downward only: a repository-wide kit must never depend on a family kit. Any import is a dependency, whether at module top level, inside a function, under `TYPE_CHECKING`, or behind `try`/`except`, so every tier shares one definition of "depends on" and boundary checks walk every import, not only module-level ones.

Domains define the values, codecs, hooks, and registrations a family kit consumes; composition roots select and assemble those contributions, provide configuration and external resources, and wire runtime instances. A family kit never discovers or imports its domains. A family may split its kit into more than one distribution where dependency weight or an optional implementation technology would otherwise force unrelated consumers to install dependencies they do not use; such optional implementation distributions are not a further architectural tier.

Family vocabulary packages stay the lower and narrower layer: they define a family's shared names, schemas, identifiers, and value semantics, own no authority or persistence, and never depend on a family kit.

Placement tests, applied in order:

- **Outside the family.** A capability meaningful and family-neutral for every market belongs in a repository-wide kit. Behaviour invariant across marketplace roles may instead belong in core.
- **Contribution or change.** If adding a sibling domain would mean registering a new contribution, the capability belongs in the family kit; if it would mean changing the capability's internal domain semantics, it belongs in the domain.
- **Third domain.** A family kit passes only if a third domain of its family could use it without the kit learning that domain's schema or branching on its identity.
- **Wiring.** Instance wiring, process lifecycle, route mounting, and aggregation of contributions belong in the composition root.

Another market family needing apparently similar behaviour is a signal to evaluate extraction into a repository-wide kit, not an automatic promotion. Promotion is right only when the capability's vocabulary and authority semantics can be made family-neutral without depending on either family's identity or domain meaning; otherwise two family kits are correct.

In the compute family, `domains/compute` (`arkhai_compute`) is the vocabulary and `provisioning/compute` (`compute_provisioning`) is the family kit for cross-domain physical provisioning: executor registration, provisioning jobs, the operational host registry, lease lifecycle, shared release, and job-backed fulfillment support. The VM and bare-metal provisioning adapters contribute their execution preparation, codecs, playbooks, result interpretation, credentials, and provider semantics, and neither imports the other or the deployed service. The compute provisioning service is the composition root that wires them.

### Kit layers

Repository-wide kit is not a flat peer group. It has an explicit one-way hierarchy:

1. **Foundation capabilities** — identity, configuration, generic policy, `kit/negotiation-runtime`'s schema-opaque round lifecycle, settlement-mechanism primitives, `kit/settlement-runtime`'s domain-neutral obligation/operation lifecycle, `kit/capability-shape`'s family-grouped capability shapes, which import only the standard library so buyers, pool administration, sites, and domains can all depend on them, and `kit/capability-pricing`'s exact pricing of a shape from per-family rates behind a replaceable aggregator, which imports only the standard library and the shape kit so storefronts, buyers, and hold billing can all price a shape.
2. **Authority capabilities** — `kit/site` and `kit/resource-pools`, which own capacity and pool administration and depend only on foundation capabilities.
3. **Fulfillment lifecycle** — `kit/fulfillment`, which owns provider-neutral scheduling and provider execution contracts and may depend on authority capabilities.
4. **Storefront role composition** — `kit/storefront`, which composes the core storefront shell with injected domain service and route hooks, and owns the storefront loop controller every storefront holds its timer loops with, and may depend only on core storefront contracts and foundation capabilities.

```text
kit/fulfillment
    ├──> kit/site
    └──> kit/resource-pools

kit/site ───────────────> foundation only
kit/resource-pools ─────> foundation only

kit/storefront
    ├──> core/storefront
    └──> foundation only
```

Dependencies never point upward. Imports guarded by `TYPE_CHECKING` still count as architectural dependencies. Kit packages never import deployed services or domain adapters.

`kit/pool-overrides` is a storefront-side kit beside `kit/capacity-publication`: the durable, site-scoped storefront pool override store and its reader, the write checked against a site's live projection, override status, the signed-resource contract, a typed client extension, and a framework-free route service each storefront binds with its own router and administrator authentication. It depends only on the identity kit, the site client, and pydantic. Each market contributes its vocabulary per offering mode — the VM and bare-metal storefronts both do — and its typed client wraps any transport exposing the core client's generic `authenticated_request`, so the core storefront client carries no market's vocabulary. See the [storefront publication architecture](../../openspec/specs/storefront-publication/architecture.md#storefront-pool-overrides).

What stays in a core package is universal to every market. `market_core.identifier_encoding` is: it encodes operator-chosen identifiers unambiguously for any market that joins them into a key.

One edge does not match this hierarchy: the site ledger in `kit/site` reads Resource Pool rows through `kit/resource-pools` for admission, registration, and the host requirement. The exception is tracked in the [change index](../../openspec/changes/README.md). No new site read of pool state should be added while it stands.

The settlement-runtime distribution is
`arkhai-kit-settlement-runtime`, imported as
`market_settlement_runtime`. It owns stable obligation identity, the operation
journal and work leases, conditional-escrow client ports, materialize/status/
check/collect/reclaim transitions, durable servicing, and ordered failure
dispatch. Storefront composition roots inject database repositories,
mechanism clients, domain fulfillment and projection callables, and real
failure actions. The kit does not import a storefront, domain, mechanism, or
provider SDK.

The negotiation-runtime distribution is
`arkhai-kit-negotiation-runtime`, imported as
`market_negotiation_runtime`. It owns signed round ordering, complete canonical
principal checks, durable transcript and terminal-state transitions, exact
continuation recovery, and the acceptance chokepoint. A storefront domain
injects authoritative opening and continuation resolvers plus codecs, seller
policy, agreement and artifact construction, and domain persistence/effect
hooks. The runtime treats the selected domain binding and every payload as
opaque; it never imports a domain or guesses one from a listing, terms, or
proposal shape.

The fulfillment distribution is `arkhai-kit-fulfillment`, imported as `market_fulfillment`. It owns both scheduling and provider-neutral fulfillment contracts. Keeping those contracts together avoids a reverse dependency from resource-pool administration into provisioning execution while preserving module-level separation between pure carriers and operational scheduling.

Within `market_fulfillment`, carrier modules such as identifiers, envelopes, requests, resources, and provider protocols must not import concrete services. Scheduler implementations may depend on the site and resource-pool authorities explicitly permitted by this layer.

### Marketplace identity

`kit/identity` is the foundation owner for canonical scheme-tagged principals, Ed25519 and EIP-191 signer/verifier dispatch, version 2 authenticated request and response envelopes, replay reservation, and dual-proof rotation. Composition roots resolve public principal configuration and secret credential material separately, construct signers, and inject them into roles and typed clients. Core, domain, settlement, and service-peer code handles only the signer interface and complete public principals; it does not receive raw private-key fields or infer identity from an address.

The scheme-neutral role lifecycle supports wallet-free Ed25519 discovery, negotiation, Arkhai payment settlement, status, and recovery. Wallet and chain inputs are required only for selected EVM effects. Payment calls use separate owner-scoped WorkOS credentials; receipts use trusted Ed25519 `arkhai.payments.receipt.v1` framing through the identity kit.

Buyer identity lifecycle is core-owned above that cryptographic foundation.
`market_identity.profiles` stores versioned public XDG metadata: stable random
profile UUIDs, canonical principal history, redacted provider references,
selection/lifecycle, and opaque authority bindings. `market_identity.credentials`
is the closed keyring/strict-file/environment provider registry. Neither package
depends upward into buyer core or a domain.

Core resolves one `ResolvedBuyerIdentity` at the command boundary. Fresh work
uses the selected primary; run-log-v3 recovery uses the exact recorded profile
UUID and retained canonical principal. Every buyer plugin declares
`core.resolved-buyer-identity.v1` and receives only the signer plus safe profile
context. VM and API-credit packages cannot add direct `[Identity]` precedence or
resolve provider values themselves. Rotation therefore advances new work while
accepted runs recover under immutable ownership.

See the [marketplace identity contract](../../openspec/specs/marketplace-identity/spec.md) and its [architecture](../../openspec/specs/marketplace-identity/architecture.md).

### Registry self-description

Each registry publishes a strict portable descriptor at
`/.well-known/arkhai/registry-descriptor.json`. The route uses the same
scheme-neutral version 2 request authentication, durable replay, and signed
response path as listing discovery. The descriptor's authority principal is
the live response signer, its schema identity is the active filter
specification, and its access posture is the live read gate. The registry
process does not maintain duplicate configuration for those facts.

The public URL, display name, operator identity, and any key-acquisition
pointer remain operator-owned deployment configuration. A response proof
establishes possession of the named credential, not third-party endorsement.
Directory curation and offline operator signatures therefore remain outside
the registry service boundary.

### Capacity publication and multi-domain storefront composition

`arkhai-kit-capacity-publication` owns the storefront-side multi-site capacity
source, exact site projections, capacity-event reconciliation loop, registry
fan-out, durable publication result recording, and close-before-reopen
lifecycle. It also owns how an async storefront drives one publication cycle:
the driver that runs the synchronous core publication runner in a worker thread
and returns each source callback to the event loop, the cycle report, and the
registry convergence every publication pass ends with. A domain contribution
supplies only schema-opaque candidates and codecs plus hooks that resolve each
listing's durable capacity binding. Each storefront keeps its domain's cycle
semantics — which sources it reads, what it derives, closes, and holds — and
composes them onto that driver; VM publication reads the kit's site projections
and capacity events, while bare-metal publication fetches each site's
resource-pool projection itself on every run.

Every capacity-backed candidate carries
`CapacityBinding(site_id, offering_mode, source_id)`. The site ID comes from
trusted local composition, the offering mode must be declared by the selected
Resource Pool and must equal the public offer's mode, and the opaque source ID
identifies the pool, quota resource, or Physical Resource. The offering mode
itself resolves from the frozen contribution registration; the Resource Pool's
declaration is a separate authorization gate, rechecked at each execution layer,
and applies only where a pool was selected. Publication,
reservation, commit, release, and restart recovery reload and compare that
exact binding. An unknown site, missing mode, changed binding, or incomplete
candidate fails closed; the runtime never invents a home site, scans other
authorities after restart, or defaults an offering mode. VM, API-credit, and
bare-metal contributions inject their candidate derivation and binding codecs
into this same runtime, so each publishes, reconciles, and converges its
registries through one implementation. A bare-metal binding's source is the
Physical Resource the listing sells. The kit imports no VM, API-credit, bare-metal, provider, or
deployed-service package.

The storefront role is one domain-neutral compute-family shell. At startup it
discovers installed `market.storefront.contributions`, applies the operator's
explicit `[storefront_domains]` selection, and freezes one registry. Each
registration binds a contribution ID, pool offering mode, exact domain
identity, contract version, and the exact validated `MarketDomainContract`.
One-domain deployments use the identical registry with one entry; there is no
singleton, module getter, installed-order fallback, global selection, or
contract reconstruction.

The common database owns immutable listing, negotiation-thread, and domain
artifact bindings. They retain the selected site, mode, domain
identity/version, and collision-safe provenance. Opening a thread inherits its
listing binding before domain policy runs. Publication, negotiation,
settlement, fulfillment, result recovery, and teardown resolve only that
recorded binding against the frozen registry. Selected-site calls are pinned
and never fan out. Removing a mode closes new publication but does not
reinterpret accepted work.

Settlement retains domain-neutral `StorefrontSettlementFulfillmentInput`: the
immutable thread binding, buyer principal, schema-opaque domain input, and any
fulfillment anchor. When servicing reaches delivery, core adds the accepted
escrow identity and caller-owned authority ports to form
`StorefrontFulfillmentContext`, then invokes the fulfillment hook on the exact
contract resolved from the binding. Core validates that the returned
negotiation, escrow, and site identities did not change. The VM hook alone
translates the opaque domain input into VM executor arguments. Core and kit
therefore own lifecycle and dispatch while each domain owns payload meaning
and concrete fulfillment; a missing hook fails closed rather than becoming a
no-op.

Legacy single-domain databases cross this boundary only through an explicit
contribution migration adapter. Check mode validates the complete population.
Write mode uses a restrictive backup and atomic replacement; ambiguity,
orphaned provenance, cross-domain rows, or unsupported versions abort without
partial state. The bare-metal contribution currently supplies codecs and
publication semantics but not the production fulfillment hook. Complete live
VM/bare-metal restart, teardown, and capacity-restoration proof remains gated
on that external production contribution and its selected-site POOLS-7
lifecycle; the shared shell does not manufacture evidence or substitute a
no-op.

### Settlement configuration

Marketplace roles configure settlement mechanisms through one typed `[Settlement]` root. Its duplicate-free `priority` list contains canonical mechanism IDs; registered `alkahest`, `arkhai_payments`, and `contact` subsections own their mechanism policy and public client inputs. Identity, wallet, and chains remain independent shared resources. Composition roots register installed mechanisms explicitly and inject only the resources each declares.

A market may settle by introduction: the `contact-exchange.v1` mechanism completes a deal with no payment and no provisioning — buyer and seller are put durably into contact with the context established during negotiation, revealed only after acceptance through the authenticated introductions surface. Its options are rateless (the mechanism declines scalar negotiation), its one obligation is non-financial, and contact payloads are bounded, deliberately persisted PII that never appears in listings or discovery.

Each side may deliver its own copy of a revealed introduction to sinks its operator configures locally — a file, a local program, a webhook, mail, or any sink installed as a plugin. Delivery is recipient-side and self-addressed: the storefront delivers the buyer's contact to the seller's own destinations and the buyer's CLI delivers the seller's to theirs, and neither side ever sends anything to an address the counterparty supplied. It is never authoritative — a sink failure cannot fail a deal, change obligation servicing, or extend a counterparty's request — because the reveal is durable and idempotently re-readable, which is also why delivery is best-effort with explicit re-delivery rather than a queue. A delivered copy falls outside the introduction retention boundary: `delete_introduction` governs what the marketplace persists, not what a recipient's own mailbox or file already holds.

The shared CLI comparison grammar has two typed uses. Resource queries derive their fields, aliases, operators, types, and missing-value semantics from the active registry filter specification and carry its ETag. Settlement clauses use common option identity fields plus mechanism-owned public projections. Buyer clauses are correlated ordered alternatives after resource filtering; storefront clauses are complete option-construction inputs. Provider, secret, raw RPC, and administrator fields are outside both languages.

The only shared lexer, source-spanned AST, comparison operators, typed field
descriptors, validation, and canonical rendering live in
`market_core.query_dsl`, shipped by the dependency-light `arkhai-core`
distribution. That module imports no registry client, settlement runtime, role,
domain, CLI framework, or provider package. Schema-specific compilation stays
with the owning lower-level consumers: `arkhai-core-registry-client` converts
filter specifications into resource descriptors, while
`arkhai-kit-settlement-runtime` combines common settlement descriptors with
registration-owned projections and publication-input validators.

The dependency edges point downward and never back into role or domain code:

```text
buyer/storefront role compositions
        ├──> arkhai-core-registry-client ──> arkhai-core (`market_core.query_dsl`)
        └──> arkhai-kit-settlement-runtime ─> arkhai-core (`market_core.query_dsl`)
```

Role compositions may consume the schema compilers, but they do not own or
fork the parser. Neither compiler may import an affected buyer/storefront role
to obtain vocabulary or policy.

Preflight remains mechanism-owned but projects one sanitized readiness contract. Storefront publication combines enabled ready registrations with explicit typed clauses in configured mechanism order; it never uses one untyped price for multiple mechanisms. Buyer policy ranks only compatible advertised survivors after ordered explicit clauses. Priority and clauses apply before acceptance only. Accepted Terms and persisted operation identities remain authoritative through readiness or configuration changes.

Typed metadata generates role-appropriate templates, edit validation, environment and Helm schema fragments, clause descriptors, and reference output. Marketplace schemas admit public consumer trust and policy but reject payment-provider, administrator, webhook, ledger database, and service-migration state. See the [CLI query language](../../openspec/specs/cli-query-language/spec.md), [settlement configuration contract](../../openspec/specs/settlement-configuration/spec.md), and its [architecture](../../openspec/specs/settlement-configuration/architecture.md).

## Runtime service map

```text
┌──────────────────────────────────────────────────────────────┐
│                   Settlement mechanisms                      │
│                Alkahest / Arkhai payments                    │
└───────────────────┬──────────────────────────┬───────────────┘
                    │                          │
          ┌─────────▼─────────┐       ┌────────▼──────────┐
          │ Registry         │       │ Seller storefront │
          │ listings/schema  │◄──────┤ publication       │
          └─────────▲─────────┘       │ negotiation       │
                    │                 │ settlement claims │
                    │                 └────────┬──────────┘
          ┌─────────┴─────────┐                │
          │ Buyer (`market`)  │                │ capacity / fulfillment
          │ discovery         │                ▼
          │ negotiation       │       ┌────────────────────┐
          │ settlement       │       │ Compute provisioner │
          └───────────────────┘       │ site authority      │
                                      │ resource pools      │
                                      │ scheduler/providers │
                                      │ jobs/lease release  │
                                      │ recovery watchdogs  │
                                      └─────────┬──────────┘
                                                │
                                      ┌─────────▼──────────┐
                                      │ VM / bare-metal /  │
                                      │ future domains     │
                                      └────────────────────┘
```

The buyer is normally a pure HTTP client. The registry is a shared discovery service. A storefront is seller-owned market state. The compute provisioner hosts the site capacity authority and shared physical-provisioning service, with concrete domain adapters registered at composition time; it also runs the timer-driven recovery watchdogs described in "Recovery workers" below. The API-credits seller stack instead composes a storefront with a credits service and quota authority; the credits service owns keys, balances, grants, and online consumption.

## Service Architecture

Within a service, controllers stay thin: HTTP routing, request/response schemas, and translating exceptions into status codes. Business rules, orchestration, and I/O composition live in the 'service' layer beneath them. A per-service breakdown of its own layers belongs in that subsystem's `architecture.md`, not here.

### Route contracts and their HTTP binding

A capability that serves HTTP routes is split into five pieces. The package that owns the capability owns the wire models, the route contract, and the route service:

1. **Wire models**: the request and response schemas.
2. **Route contract**: each route's method, path, signed operation name, the resource a request binds, and the caller roles it admits. Request authentication and the typed client both bind requests from it, so the two cannot disagree.
3. **Typed client**: a method for every route, sync and async where both are offered, built on the route contract. It may live beside the capability or in a thin client package of its own that depends only on the models and the contract, so a caller does not install the capability's service code to call it.
4. **Route service**: a framework-free class over the capability's collaborators that validates and performs each route and shapes its response. It reports a refusal as an error carrying a status code and detail, and it imports no web framework.
5. **HTTP binding**: the thin controller that maps each route to its route service, turns the route-service error into a response, and sits behind the process's authentication. It belongs to whatever composes the process: a storefront for storefront capabilities, the provisioning service for the compute family kit's routes, and a domain package for the routes that domain contributes.

A domain that contributes routes to a service it does not compose declares their contracts in its own package and supplies its router as a factory taking accessors for its collaborators, so no route reaches into the composing service's module state. Because a binding repeats its contract's path, the provisioning service, which assembles its route table from contributions, tests that every route it mounts resolves to exactly one contract and that every contract resolves to a mounted route.

`kit/pool-overrides` is the reference instance. `kit/site` predates the pattern and ships its own FastAPI router.

## Authority boundaries

| State or decision | Authority | Notes |
|---|---|---|
| Listing schema and discovery filters | Registry operator | Published through `filter-spec.yaml`; storefronts and buyers consume the schema |
| Marketplace principal normalization, proof dispatch, and canonical envelopes | Identity kit | Scheme-neutral foundation capability; roles inject signers and authorities own subject/role bindings |
| Listing, negotiation, deal, and seller policy state | Storefront | Market-facing state, not physical inventory |
| Capacity admission and reservation | Site authority | Serialization point for competing reservations |
| Sellable capacity: each Physical Resource's declared shape, quantity, pool, and match attributes | Site authority | Declared by registration, a capacity-definitions document, or derivation from legacy host inventory; host records are connection identity only |
| VM listing shapes a storefront publishes | Storefront, within what the site declares | A storefront pool override, else the pool's `listing_shapes` hint, else the VM domain's default generator; feasibility is judged against the site's declarations, and admission remains the site's |
| A bare-metal listing's shape | Site authority, through the Physical Resource's declaration | Derived from the declared capacity and attributes; the storefront chooses nothing |
| Resource-pool metadata and provider configuration | Resource-pool service | Provisioning routing metadata; disabled pools remain resolvable |
| Pool deliverable-mode authorization | Resource-pool operator and service | One explicit set per pool; absence authorizes no mode, and each execution layer rechecks it |
| Pool advertisement authorization and capacity backing | Resource-pool operator and service | Both declared explicitly on every pool write, never defaulted; a backed pool advertises only what it delivers, an unbacked pool delivers nothing, and backing is fixed at creation |
| Settlement-resource selection | Fulfillment scheduler | Placement occurs before provider execution |
| Provider-specific create/status/teardown | Fulfillment provider | Executes against the selected resource and does not substitute placement |
| Asynchronous infrastructure job state | Compute provisioner | Durable job identity with in-process execution queue |
| Lease expiry and physical release | Provisioning lifecycle plus fulfillment convergence | Lease lifecycle owns the release decision; fulfillment convergence owns teardown dispatch/recovery — see "Release" and "Recovery workers" |
| Escrow claims and obligation journal | Settlement-runtime and Alkahest kit | Domain codecs and fulfillment policy |
| Payment transactions, ledger, hold release, fees, disputes, and cash movement | External Arkhai payments service | SCM consumes the published API and verified receipt, not provider state |
| API keys, credit balances, grants, and consumption | API-credits service | Marketplace purchase ownership is distinct from bearer authorization for use |

### Deciding which party is authoritative

Where two components could each decide something, authority follows what each can
see and what each controls, judged as if they were separate businesses that
disagree: the authority is the party that can make its answer stick. Applied across
the storefront–site boundary:

- **The site never sees commercial terms.** Nothing commercial crosses the
  provisioning boundary — a capacity claim carries dimensions, offering mode, and
  placement requirements, never a price — so a site cannot refuse a deal on price.
  A price a site declares on its pools is a default the storefront may adopt or
  replace through its own override, and the storefront's resolution decides.
- **The site sees every dimension a claim reserves and controls admission**, so it
  prevails on physical capacity, offering mode, and the host requirement. A
  storefront that has agreed a shape cannot make the site admit it; the storefront
  mirrors those constraints early, from its projections, only to avoid committing to
  what admission will refuse.
- **Either party can refuse more than the other would; neither can make the other
  accept.**

A rule a site declares but does not enforce at admission is therefore advisory to
the storefront whatever its wording. A rule that must bind every storefront acting
for a site belongs in site admission, over what a claim carries.

### Omission states no commitment

A term a declaration leaves out states that nothing is committed on it. It is not a
default value and not an error: the decision belongs to the party holding the next
decision, and site admission keeps the last word on whether a deal is scheduled and
provisioned. Existing terms already behave this way. A dimension a VM shape omits is
outside the listing's commitment and is supplied by the pool's defaults or downstream
provisioning; a capacity family with no rate is not charged; a pool that states no
asking rate publishes none. A term that is present but cannot be read is not an
omission, and asking rates and family rates never treat it as one.

### Storefront capacity boundary

The storefront owns capacity offerings and projections used to publish and negotiate listings. It is not the source of truth for physical resources. A projection may be stale; authoritative admission occurs at the site authority.

Specific-resource listings are a valid opt-in: the seller exposes a concrete resource and permits the buyer to constrain placement. The ordinary fungible path reserves capacity and lets fulfillment scheduling select a settlement resource.

Storefront capacity pools and provisioning resource pools are separate concepts. Mapping is explicit configuration or attributes, never a cross-service foreign key.

A listing's capacity backing is declared by the pool it derives from and read from that declaration; it is never inferred from absent capacity data, an empty projection, or a stale generation. It is fixed on the listing's binding when the listing is created, and it is independent of how a pool's listings are enumerated and of which settlement mechanisms a listing offers. A capacity-backed listing is admitted at its site; an unbacked listing has no admission authority behind it, so it never reaches reservation and publishes only settlement options its domain does not fulfil through capacity. A listing's origin site is where it was declared, not an authority that admits it.

Every VM listing is a listing shape, and a published dimension is a commitment: the claim a VM listing produces reserves every quantity it publishes, so it publishes exactly the quantities its shape declares. A dimension its shape omits is outside the commitment; fulfillment may supply it from the pool's configured VM defaults or leave it to downstream provisioning, and the operator keeps capacity sufficient for it. A VM shape comes from the storefront's own override for that site and pool, else the pool's `listing_shapes` hint, else the VM domain's default generator, and it is published only where a source member is feasible for it.

A bare-metal listing's shape is derived, not chosen: it is its Physical Resource's declaration read through the compute-family schema, published under the same flat names so the compute filters read both domains alike. Its commitment is one whole unit: the claim reserves exactly one `units` of the resource, exclusively, and requires the shape's attributes, while the shape's quantities describe what that unit contains rather than being reserved one by one. The shape's digest completes the listing's derivation identity, so a corrected declaration closes the listing and publishes a successor. API-credit listings are not listing shapes. A configured site whose projection the storefront does not hold is unknown, not empty: its listings are held, and nothing is derived from local tables in its place. See the [storefront publication architecture](../../openspec/specs/storefront-publication/architecture.md#listing-shapes-and-the-storefronts-authority).

VM publication runs on its own as a storefront lifecycle loop over the site projections the storefront trusts; a storefront that disables projection-backed derivation still derives capacity-backed listings from its local tables, and unbacked listings only ever from projections. Bare-metal publication remains operator-invoked. Terms of sale come only from durable sources — pool declarations, per-pool overrides, and configuration — never from a command's arguments.

Which registry a listing is published to is an operator curation decision, expressed by forking a filter spec, rather than a property of the listing. A registry deployment serves one filter spec and buyer commands match its declared schema identity, so listing shape is deployment-scoped — but the compute family's form factors share one schema identity rather than needing a registry each. Separate profiles exist for listings whose shape genuinely differs, such as the sparse option-only profile an introduction market ships.

### Site authority

A site authority owns resources, allocations, reservation expiry, capacity versions, and the event feed for one failure domain or datacenter. One storefront may aggregate several sites.

Capacity claims name their requested offering mode explicitly. The authority
records that value on the reservation and never derives it from host
attributes, resource type, or a default offering mode. Admission refuses a matching
resource when its pool does not authorize the mode; durable legacy rows are
backfilled only from single-valued evidence and otherwise quarantined from
execution.

Each provisioning connection is bound to an operator-configured `site_id` and an exact service-peer principal. Marketplace version 2 proofs authenticate requests and signed responses or callbacks against those public trust pins; matching an address-like body value, administrator key, private-key field, or identifier under another scheme never substitutes for the configured principal and role. The trusted connection binding, not a counterparty assertion, selects the site.

Capacity events are anonymous availability deltas broadcast through a pull feed. Deal-scoped fulfillment events are point-to-point to the owning storefront and retain deal context. A storefront reconciles listings in response to capacity deltas regardless of which seller action caused the change.

A site authority's client-facing surface splits into two separately typed clients, both living in `kit/site-client`: a buyer-facing read/reserve/commit client (`SiteCapacityClient`) never used for operator writes, and a typed capacity-administration client (`SiteCapacityAdminClient`) for operator resource registration and update. Neither client depends on the other's implementation.

### Resource pools

Resource pools group the Physical Resources a settlement may be placed on, identify the provider and
provider-specific configuration used after selection, and declare the exact set
of offering modes that configuration can deliver. The declaration belongs to
the pool rather than each host because provider, playbook, and requirement
delegate are pool-owned execution policy; missing or empty declarations deliver
nothing. Pool disablement prevents new assignment but does not erase existing
host membership or lifecycle records. Pool administration is distinct from
scheduling policy.

A pool also declares which offering modes its listings may advertise and whether
it is capacity-backed. Advertisement is separate from delivery so a seller with no
execution integration can list without fabricating provider configuration; a
backed pool may advertise only what it delivers, and an unbacked pool delivers
nothing, which keeps it out of every capacity path through the deliverable
recheck each execution layer already performs rather than through new backing
checks. Readers of the resource-pool projection resolve both declarations through
the pool kit's shared resolver. See the
[resource-pool management architecture](../../openspec/specs/resource-pool-management/architecture.md).

The site authority, fulfillment scheduler, and fulfillment orchestrator all use
the shared pool-membership predicate at their own boundary. Rechecking before
provider dispatch means narrowing a declaration blocks a held or assigned
operation without rewriting its historical requested mode. This authorization
does not replace physical accounting: a pool may authorize both VM slices and
whole-host delivery while the exclusive/shareable conflict rule still prevents
them from overlapping on one physical host.

A pool's provider also decides whether declarations in the pool must name a host.
Each provider declares it, and the provisioning composition supplies the
per-provider requirement as plain data. Site admission and settlement scheduling
each refuse a declaration naming no host where the pool's provider needs one: the
same layer-by-layer recheck, so no layer relies on another having refused.
Dispatch is the last check. It renders execution inventory only from the
registered host record and refuses a host with none. A composition that delivers
nothing through hosts supplies no requirement, and its admission is host-agnostic.

## Shared vocabulary and identities

### Marketplace principals

A marketplace principal is the complete canonical `{scheme, identifier}` credential identity. The scheme is part of the authorization namespace, so equal identifier text under different schemes does not imply equal authority. Stable publishers, storefronts, negotiations, settlements, accounts, and service peers remain separate subjects whose owning authority binds active principals to explicit roles. Public principals and trust pins may cross configuration and protocol boundaries; private signing material remains inside Secret-backed signer construction and never enters public carriers or durable state.

### Authenticated service boundaries

Authenticated service-to-service calls use the scheme-neutral version 2 request and response proofs in both directions. The caller binds its role, complete principal, semantic operation and resource, request identity, timestamp, and canonical body digest; the authority reserves the replay identity before dispatch. The response or callback is likewise signed and verified against the exact public service principal and role pinned for that connection before its payload is trusted. Trust therefore comes from operator-configured public principals and authority bindings, never from an address or principal asserted inside the payload, an administrator token, or access to either side's signer credential.

### Terms

| Term | Definition | Primary authority |
|---|---|---|
| **Market Agreement** | Commercial terms accepted after negotiation | Core/domain and storefront |
| **Capacity Offering** | Market-facing representation of sellable capacity | Storefront |
| **Capacity Projection** | Storefront view of capacity believed sellable | Storefront, sourced from sites |
| **Capacity Reservation** | Admitted hold against authoritative capacity | Site authority |
| **Physical Resource** | Real supply resource such as host, pod allocation, storage, power, or bandwidth | Site/provisioning |
| **Capacity Declaration** | Authoritative statement of a Physical Resource's sellable shape and quantity, its pool, and the attributes claims match | Site authority |
| **Resource Pool** | Provisioning-owned group and provider-routing context | Resource-pool service |
| **Capacity-backed** | Said of a pool with an admission authority behind it: capacity can be reserved, committed, and released against it. Backing means an admission authority exists, not that hardware does | Resource-pool service |
| **Unbacked** | Said of a pool with no admission authority behind it: nothing can be reserved against it, and its deliverable set is empty | Resource-pool service |
| **Capacity Settlement Assignment** | Durable binding of a capacity reservation to one settlement resource | Site/fulfillment boundary |
| **Settlement Resource** | Physical resource selected to satisfy a reservation | Fulfillment scheduler |
| **Physical Settlement** | Provider-specific execution that makes the agreed resource available | Fulfillment provider |
| **Fulfillment** | Post-acceptance lifecycle encompassing assignment, provider execution, status, teardown, and results | Fulfillment capability |
| **Provisioned Resource** | One output created by fulfillment, such as a VM or pod | Domain/provider |
| **Settlement Record** | Durable lifecycle record linking reservation, resource, provider snapshot, operations, and results | Compute provisioning lifecycle |

Avoid `SettlementTarget` as a noun. Use `SettlementResource`; method names may use `select_target_resource` only where it improves call-site clarity.

### One name per concept

Five concepts sit close enough together to have been conflated, and each has
exactly one name.

| Concept | Name |
|---|---|
| What the seller is offering: `vm`, `bare_metal`, `container`, `api_credits` | `offering_mode` |
| The machine and its connection identity | `host`, identified by `host_id` |
| The fulfillment implementation selected for a pool | `provider` |
| The component that validates, submits, and polls an execution action | `executor` |
| One listing a publication pass could publish, derived from a source declaration before anything is decided about it | `publication candidate` |

The offering mode carries one name on every surface that names it: the capacity
claim, the Resource Pool's deliverable and advertisable declarations, the durable
listing binding, and the published listing. So does the pool's identifier,
`pool_id`, including in the site's resource-pool and capacity-bucket projections. It is a separate axis from the
site-inventory `resource_kind`/`resource_type` discriminator, and naming it
consistently does not merge the two.

The host is named `host_id` on every interface that names it: the host
registry's key, a capacity declaration's host link, a reservation's
`executor_ref`, fulfillment metadata, job parameters, lease APIs, playbook
variables, and the bare-metal listing. One exception remains: the VM
storefront's local physical-inventory tables and the plumbing that reads them
still say `vm_host`. They are no longer an authority for anything this
paragraph lists and are scheduled for removal rather than renaming, as
[`ROADMAP.md`](ROADMAP.md)'s Goal 1 records. The address the provisioner connects to is the host's
`ssh_host`. `physical_host_id` is a different concept and keeps its own name: the
stable identity of a physical machine across hosts. A host belongs to exactly one
Resource Pool, so one machine offered both as VM slices and as a whole host is
registered as two hosts, and `physical_host_id` is what lets cross-mode accounting
see one machine.

A seller's published shape is a **listing**, never an offer. `offer` names a
negotiation message either party sends. For a domain using capability-shaped
publication, what one listing offers, in its family-grouped vocabulary, is its
**listing shape**; VM publication states its shapes, from an override or a pool's
`listing_shapes` hint, and bare-metal publication derives each one from a Physical
Resource's declaration. A buyer's family-grouped statement of what it needs
is a capability shape, not a listing shape. How many publication candidates a pool yields
is its `listing_cardinality_mode`, which carries cardinality only — not what is
offered, how a deal settles, or whether an admission authority backs the listing.

`executor` names the action-dispatch abstraction **as a head noun** and nothing
else: not the offering mode, not the machine, not the delivery handler.
`executor_`-prefixed compounds naming that abstraction's own targets, references,
or actions do keep the name, because `executor` carries its action-dispatch sense
in them — `executor_ref` is the executor's reference and `executor_target` is the
target of an executor action. The prohibition is on the head noun, not the prefix.
See [physical provisioning](../../openspec/specs/physical-provisioning/spec.md).

A **publication candidate** is what a storefront's publication pass derives from a
source declaration — a site's projected pool, Physical Resource, or quota resource —
before deciding anything: a candidate with no listing is published, one matching an
existing listing refreshes or reopens it, and an open listing no candidate matches
closes. It is not a scheduling candidate, a Physical Resource considered for placement
of an admitted reservation, which is chosen after a deal and never becomes a listing.

### Identifiers

Fulfillment lifecycle identifiers are opaque UUIDv7 strings. They are not encoded composite keys and callers must not derive routing data from them.

| Identifier | Meaning |
|---|---|
| `capacity_reservation_id` | Admitted capacity and idempotency boundary for scheduling/begin fulfillment |
| `fulfillment_id` | Durable post-acceptance fulfillment aggregate |
| `settlement_resource_id` | Selected underlying supply resource |
| `provisioned_resource_id` | One provider-created output; one fulfillment may create several |
| `result_id` | One durable settlement/fulfillment result |
| `site_id` | Explicit authority/routing identity; never encoded into another ID |
| `pool_id` | Site-local operator slug for a pool; every durable or public reference keys on `(site_id, pool_id)`, never `pool_id` alone |

Accepted deal identity is the negotiation ID and exact Agreement. Mechanisms using the obligation runtime correlate through `obligation_ref` in `settlement_obligations`, with escrow and introduction references as `mechanism_ref`. Arkhai payments instead stores the mandate in `negotiation_threads.settlement_data` and derives its transaction ID from it; it creates no plan or obligation. Domain receipt and delivery progress remain linked to the negotiation ID. Legacy escrow rows are backfilled only where persisted plans provide neutral obligation identity.

`fulfillment_uid` is a distinct, older identifier predating `fulfillment_id`: the on-chain settlement-claim identity a storefront's settlement mechanism (Alkahest today) issues for escrow arbitration. It is not part of the fulfillment-lifecycle UUIDv7 family above, is owned by the settlement mechanism rather than the fulfillment capability, and MUST NOT be confused with `fulfillment_id` — a storefront workflow row may legitimately carry both, for the same deal, meaning two different things.

`site_id` is owned at the storefront aggregation boundary and bound to a configured provisioning connection. Provisioning-local capacity persistence is already scoped by its database authority and does not duplicate that storefront-owned identity on every pool, resource, or reservation row. Counterparties cannot self-assert the routing identity used by the storefront.

Commercial agreement identity does not cross the generic provisioning boundary merely for correlation. Storefronts retain commercial context and translate it into fulfillment requirements. The capacity reservation is the generic physical-lifecycle identity.

## Major lifecycle flows

### Discovery and negotiation

The buyer discovers listings from a registry and drives signed synchronous request/response rounds against a storefront. Acceptance emits one Agreement with accepted terms, exact option and opaque selection parameters, canonical parties, explicit start, and domain provision terms. Relative starts resolve once at acceptance. Both parties retain exact response bytes rather than reconstructing the Agreement from the transcript. Seller policy evaluates listing data, captured side inputs, and the message history; protocol infrastructure does not reinterpret domain policy.

VM, bare-metal, and API-credit storefronts use that one kit lifecycle. Opening resolution
selects the storefront's configured domain contract and listing before the
runtime persists anything. Continuation resolution starts from the recorded
thread, re-establishes the exact listing and canonical buyer/seller binding,
then lets the selected domain validate its persisted terms before a policy or
acceptance effect can run. Domain policy remains the only component that
interprets the provision-term and proposal schemas.

Normal buyer commands apply two separate constraint layers in fixed order: one filter-spec-typed resource query is pushed to the registry, then zero or more settlement clauses are evaluated locally against installed, enabled, compatible advertised options. Every comparison in one settlement clause must match the same option; repeated clauses are alternatives in command order. Explanation stops before negotiation and reports registry-owned predicates, local settlement rejections, and survivor counts without making a physical indexing claim.

Negotiation is a conversation of counter-offers over what capacity is being sold, not over which specific physical resource serves it. A buyer and seller negotiate pooled capacity ("4 GPUs", not "host `kvm-17`"); a counter-offer that changes the requested shape (fewer/more units, a different dimension mix) is a negotiation event, and a durable shape change is expressed by resizing the reservation for that negotiation, never by mutating an existing reservation or committed settlement assignment in place (see "Capacity reservation" below, and `openspec/specs/site-capacity/spec.md`'s reservation-supersede requirement). Today's negotiation rounds exchange hard counters; the same model extends to richer forms (a buyer asking what shape a given price can buy, or what price a given shape costs) without changing this premise.

A listing is priced either flat or by its shape. A flat-priced listing's settlement clause states one rate for the whole listing, whatever its shape. A shape-priced listing states rates per capacity family — per GPU of a model, per vCPU, per GiB of memory or storage — in an asset; each settlement option's rate is the listing's own shape evaluated against those rates through the domain's aggregator, which lives in `kit/capability-pricing` and is exact for amounts beyond 64 bits. A family without a rate is not charged, and a listing that would be free in an asset is never published. The resolved rates are recorded on the storefront's listing record so a revised shape can be priced from them; they never reach a registry, which sees only each option's composed rate. Whatever the mode, a seller negotiates from the rate of the settlement option or accepted escrow the buyer's proposal selects, in that option's own asset, and from its configured floor only when the selected option advertises no rate. See `openspec/specs/storefront-publication/spec.md`, "Shape-resolvable commercial rates", and `openspec/specs/negotiation-protocol/spec.md`, "The seller's reference amount is the selected option's rate".

Physical resource identity (`resource_id`, `host_id`, and equivalent identifiers) is an optional pinning/telemetry pathway, not the unit buyers and sellers negotiate over. It is deliberately not exposed across the capacity-reservation boundary (`openspec/specs/site-capacity/spec.md`'s opaque-reservation requirement) for exactly this reason: the storefront and buyer should not need to know or care which physical resource ultimately serves a deal in the ordinary case. Code that makes ordinary fulfillment depend on a physical resource identity being present is very likely encoding the wrong unit of negotiation.

```text
registry listing
    ↓
buyer opening message
    ↓
signed synchronous rounds
    ↓
seller acceptance
    ↓
exact Agreement bytes + opaque settlement_data
```

### Settlement servicing

The selected settlement stage consumes the exact Agreement and produces its own evidence. Alkahest uses plans, obligations, condition checks, collection, and expiry/reclaim through the shared settlement-runtime journal and its own client. Contact exchange may fuse settlement and delivery. A charge-first stage does not implement a conditional-escrow API.

`arkhai.payments.v1` is a stateless peer of Alkahest in VM, bare-metal, and API-credit compositions. Shared registration, typed configuration, and owner-scoped client provision live in `kit/arkhai-payments`'s `settlement_config.py`. Seller acceptance returns the derived mandate in opaque `settlement_data`, persisted next to exact `agreement_bytes` in `negotiation_threads`. Buyer `payer_account` travels in selection params and Agreement `settlement_params`, separately from marketplace identity.

The kit defines `deal = sha256(JCS(agreement))` and transaction ID `sha256(JCS(mandate))`. Hold intervals round up and approval expiry rounds down without rewriting fractional Agreement timestamps. The buyer validates/approves the mandate and polls that ID; its seller settle call carries only the negotiation ID. The seller loads accepted state, polls the same transaction, and verifies the signed receipt against the mandate before provisioning or issuing. Pending is retryable, completed delivery is idempotent, and nonterminal domain progress is re-driven. `make_settle_hook` routes a selected outcome with no escrow proposal to the domain's `agreement_settlement` hook.

The payments service owns the ledger, fees, hold release, disputes, and cash providers. The kit has no servicing daemon, ledger, plan, or obligation; refund calls `reverse`. Domain receipt and delivery journals are local recovery state, not financial authority.

```text
Alkahest: Agreement → SettlementPlan → active obligations → Receipt
                         ├─ condition checks
                         ├─ claims / collection
                         ├─ heartbeats
                         └─ expiry / reclaim
```

### Capacity reservation

Negotiation-time availability is advisory. Authoritative reservation occurs at a site authority.

1. The storefront reads snapshots for listing and policy decisions.
2. Accepted terms create a TTL soft hold where required.
3. Settlement commits or recreates the reservation before physical execution.
4. Fulfillment runs against the committed reservation.
5. Lease expiry or early termination invokes physical teardown before capacity release.

A reservation whose negotiated shape changes is superseded, never mutated: `CapacityLedgerService.resize_reservation` atomically releases the old reservation and admits a new one under a new `capacity_reservation_id`, so the reservation's committed dimensions always reflect the shape actually being negotiated. Scheduling (see "Fulfillment" below) MAY further narrow within a reservation's bound for a placement or pricing check against a candidate shape; a scheduling narrower than the reservation reports back exactly what it scheduled, not the reservation's original shape, since that is what gets provisioned if accepted (`openspec/specs/site-capacity/spec.md`'s committed-dimensions-through-scheduling requirement). As of this writing, `resize_reservation` has no negotiation-side caller — this describes the intended negotiation model, not yet-implemented wiring between negotiation and reservation resizing.

#### Layered placement ownership

Which physical resource ultimately serves a deal is decided up to three separate times, by two different processes, and these decisions must not be conflated:

| Decision | Owned by | When | Mechanism |
|---|---|---|---|
| Which pool/resource a listing represents | Storefront | Publish time | Baked into the listing's `listing_resource` at creation |
| Which site to route a reserve/probe call to | Storefront (`AggregateCapacityClient`) | Reserve/negotiate time | `fill_first`/`most_available` ranking policies over a live per-request snapshot |
| Which concrete host within that pool fulfills the reservation | Provisioning service (`PhysicalSettlementScheduler`) | Schedule time | Deterministic round-robin (or a replaceable fairness policy) |

The second layer stays storefront-owned rather than moving into the provisioning service alongside the third: pooling/placement ranking is a commercial judgment a seller makes about their own sites, not a physical-fulfillment concern, so it lives in the storefront process. The second and third layers pick among fundamentally different things — sites versus hosts within one already-chosen site — and are correctly separated by process boundary, not merely by convention.

The second layer's ranking policies (`fill_first`/`most_available`) read a live, per-request capacity snapshot, never a storefront's own advisory `CapacityProjection` cache — that cache is explicitly allowed to go stale for display/listing purposes, and routing a real reservation attempt through it would turn a display cache into a load-bearing admission input, defeating the reason it's allowed to be stale. The ranking policies' own claim-matching is deliberately a *coarse, best-effort hint*, not shared code with the enforcement-level predicates `kit/site` and fulfillment scheduling use: a wrong ranking costs one extra round-trip when the aggregator falls through to the next site, not an incorrect admission, so the two matchers are allowed to diverge in a way an actual eligibility gate never could.

### Fulfillment

```text
Capacity Reservation
        ↓
PhysicalSettlementRequest
        ↓
PhysicalSettlementScheduler.schedule_resource(...)
        ↓
Capacity Settlement Assignment / SettlementResource
        ↓
FulfillmentProvider.create(...)
        ↓
Provider result + zero or more Provisioned Resources
        ↓
status / teardown / durable results
```

VM and bare-metal payment delivery requires a matching signed receipt before any protected physical effect. Accepted selected-site bindings govern fulfillment and recovery; VM's local provisioning progress under the negotiation ID is not a chain escrow or obligation. API-credit payment similarly gates idempotent authority-owned issuance and private credential delivery.

Scheduling and provider execution are separate. The scheduler selects and binds a resource. The provider may validate the selected resource but must not choose a substitute. Retries for the same reservation and equivalent request return the existing assignment or operation result; conflicting retries are rejected.

Provider-specific dictionaries crossing domain or persistence boundaries use a versioned envelope with a non-empty `kind`, positive `schema_version`, and typed or explicitly validated payload. Readers reject unknown `(kind, schema_version)` pairs rather than guessing.

The current round-robin scheduling policy is deterministic for the same candidate order and state. Multidimensional fit checks every requested dimension; a candidate missing a requested dimension has zero availability for that dimension.

### Fulfillment status and results

A caller observes fulfillment progress by pulling `GET /fulfillment/{fulfillment_id}/status` and `GET /fulfillment/{fulfillment_id}/result` from the durable aggregate — there is no push channel from provisioning to the storefront today. `status` is a plain read with no provider call. `result` returns a provider-neutral `fulfillment.result.v1` envelope; for a fulfillment in `active` state it also performs a live, uncached credential fetch against the provider (never persisted) outside any open database transaction, so every read reflects current provider-reported credentials rather than a value captured once at creation. A live credential-fetch failure on an otherwise-healthy `active` fulfillment is its own stable error category (`credential_fetch_failed`), distinct from a create/status/teardown failure.

Push-based result delivery (provisioning notifying the storefront rather than the storefront polling) is planned future work, tracked as `replace-polling-with-authenticated-push`, and requires a new provisioning→storefront authenticated channel that does not exist yet. It does not change the durable persistence this section describes, only the delivery transport.

### Release

Physical release is proof-driven and split across two cooperating state machines with distinct retry ownership. Lease lifecycle (site/provisioning-lease layer) owns `releasing`/`released` and the final capacity-return decision; it never dispatches a second teardown operation itself. Fulfillment convergence (see "Recovery workers" below) owns dispatch, requeue, and recovery of the teardown states themselves (`teardown_dispatch_pending` → `tearing_down` → `torn_down`/`teardown_failed`). Lease-side retry re-observes the same fulfillment aggregate by its durable `fulfillment_id` rather than resubmitting a teardown.

A kind-routed `ReleaseJobPort` connects the two: for VM-backed reservations it reads the fulfillment aggregate's teardown state (`torn_down` → succeeded, `teardown_failed` → failed, otherwise pending); other offering modes continue to resolve through the shared job queue unchanged. Capacity is never returned to scheduling until the aggregate reaches `torn_down` or an operator explicitly force-releases after external verification; the audit state distinguishes forced release from proven teardown.

`begin_fulfillment_teardown(fulfillment_id)` is the whole-fulfillment teardown entrypoint: it resolves the aggregate, reuses an already-prepared teardown operation when present (as legacy-backfilled rows carry) or prepares one via the provider when a native row reaches teardown for the first time, then hands off to convergence for dispatch — it never dispatches to the provider inline.

## Deployment topology

### Local development

Compose is organized by market domain and includes the shared development chain. There is no required long-running buyer service. The bare-metal seller uses its dedicated image, role-owned writable storefront database, durable reservation-to-site route map, and separately injected seller signer and trusted site-binding configuration. VM and bare-metal storefront services are independently selectable and may share a provisioning authority without sharing writable storefront databases. The root compose file combines domain stacks for full end-to-end work.

### Production and staging

The deployment surfaces support independently selectable registries, VM and bare-metal storefront roles, compute provisioning, and optional development/test components. The umbrella chart uses the schema-opaque registry subchart for its default compute registry and may enable a second aliased API-credits registry. Each registry has its own schema path, authority signer Secret, descriptor, Service, and retained PVC. `helm/charts/bare-metal-storefront` installs the dedicated one-domain role with its own service, persistence boundary, health probes, public URL, external signer Secret, and external site-binding Secret; the umbrella/shared-shell chart may instead select installed domain contributions. Disabling one role creates no wait or reference from another.

Configuration resolution, ConfigMap/Secret mounting, stateful-service persistence strategy, and migration-at-startup conventions are covered in [`docs/development/DEPLOYMENT_AND_CONFIG.md`](DEPLOYMENT_AND_CONFIG.md) and [the deployment and state specification](../../openspec/specs/deployment-state/spec.md).

### Operators

Sites and storefronts are currently deployed and operated by one business, which
upgrades them together. Authority boundaries are still drawn as if the two were
independent parties, because that is what decides where each rule belongs. What a
single operator does not yet need is upgrade-order guidance between independently
operated sites and storefronts — for example, a site writing a declaration that a
storefront release cannot yet read. Designs record where such ordering would matter,
to be revisited once operators are no longer all known, at the first major release.

## Build, packaging, and initialization

Internal Python packages are built as wheels into the repository `.dist` directory, and every project consumes them from there; no project resolves a sibling through a source path. A rebuilt wheel keeps its version, so each environment, image, and lock refreshes its internal packages explicitly, and the set is derived from the project's lock when the operation runs rather than listed anywhere:

```text
make dist                      build every internal wheel
        ↓
make reinit (in the project)   sync, upgrading and reinstalling the lock's internal packages
        ↓
run focused tests
        ↓
image build                    install the committed lock unchanged, same internal packages
```

One root `.python-version` fixes the interpreter for every environment and image. Docker builds copy `.dist` from the build context into builder stages; runtime stages receive only the finished environment. [`BUILD_AND_PACKAGING.md`](BUILD_AND_PACKAGING.md) owns the mechanics — `scripts/uv_project.py`, `make lock`, the image layout — and the `make check-packaging` checks that enforce them.

Aggregate Make targets must run every included subproject's default tests. A standalone subproject target remains useful for focused work, but the aggregate contract is complete coverage, not a curated subset.

Schema changes are additive by default. Non-additive changes use expand/contract across releases. Config-driven operational seeding belongs in runtime initialization; migrations may seed only deterministic system rows required to satisfy a new schema constraint.

See the [deployment and state specification](../../openspec/specs/deployment-state/spec.md).

## Recovery workers

The compute provisioner runs three independent timer-driven workers, composed once at startup alongside the request-serving app, each owning a distinct slice of durable recovery:

| Worker | Owns |
|---|---|
| `CapacityReservationWatchdog` | Expiring stale/unconfirmed capacity holds |
| `FulfillmentConvergenceWatchdog` | Create and teardown dispatch/status convergence for the fulfillment aggregate (see "Fulfillment" and "Release" above) |
| `LeaseWatchdog` | Lease expiry detection that triggers release |

`FulfillmentConvergenceWatchdog` runs four handler passes each cycle — create-submission recovery, create-status convergence, teardown-submission recovery, teardown-status convergence — plus a `teardown_failed` requeue step, sharing one timer rather than one watchdog per pass. Each pass claims eligible rows durably (a short transaction reserving the row with a lease and worker identity), performs any provider call entirely outside a database transaction, and applies the outcome in a second short transaction only if the claim is still owned — a claim whose lease lapsed before the provider call returns is silently superseded, not double-applied. No attempt-count ceiling exists anywhere in this recovery path; a fresh worker instance resumes purely from durable claim state after a restart, with per-row exponential backoff and jitter between attempts.

## Operator lifecycle controls

Long-running lifecycle workers may expose authenticated one-cycle controls when deterministic recovery, testability, or customer-issue diagnosis requires them. A manual cycle must invoke the same production handler as the timer-driven worker; it must not implement alternate lifecycle transitions. Diagnostic responses are bounded and may expose aggregate state counts, claim ages, and failure counts, but not credentials or unbounded provider payloads.

Each storefront process holds its timer loops with one loop controller from `kit/storefront`. Every loop registers with it, bound to the step that runs one cycle, so the pause route holds every loop at a cycle boundary without cancelling it and each `run-cycle` route runs exactly the operation the loop's timer runs. A loop gates on entry and immediately before its work, and waits between cycles through the controller, which returns on a pause request, so a pause is observed within its bounded wait whatever the interval; a loop's reported state comes from what it has acknowledged at its gate. Kits below `kit/storefront` take the gate and wait as injected callables. The loop pause is process-local and separate from the trading pause. Each storefront binds the controller's framework-free route service behind its own administrator authentication. See [market composition](../../openspec/specs/market-composition/spec.md).

## Testing strategy

Tests belong at the lowest level that can prove the behavior: unit, integration, smoke, and end-to-end, each defending the narrowest observable contract appropriate to its level — no level should rely on end-to-end tests alone for behavior it could prove itself. See [`docs/development/TESTING.md`](TESTING.md) for the level definitions, coverage jurisdiction between them, the client-contract "no raw calls" rule, contract fixtures, boundary-change validation, cross-language conformance, and offline review validation, and [the testing and compatibility specification](../../openspec/specs/test-compatibility/spec.md) for the normative requirements.

## Capability documentation index

The canonical [capability documentation index](../../openspec/specs/README.md) links each normative `spec.md` and its optional freeform `architecture.md` companion. Capability contracts own detailed behavior; companions own durable subsystem models and rationale; this document remains the cross-system map.

## Deterministic database-concurrency tests

Database-concurrency tests use independent sessions and connections against the same database, establish transaction ownership through explicit synchronization at a semantic persistence boundary, and assert final durable state. Tests must not depend on uncontrolled thread races, scheduler timing, or elapsed-time ordering. Synchronization waits are bounded so lock regressions fail rather than hang. Test-only subclasses or adapters may pause a narrow persistence interface after a meaningful write; production code must not expose test-only hooks.



### Durable fulfillment acceptance

The fulfillment kit owns provider-neutral acceptance orchestration. It loads an already-selected settlement resource, freezes provider-specific prepared input and pool configuration in one transaction, dispatches after commit, and acknowledges provider metadata in a second transaction. Preparation receives the acceptance session and uses it for any local resource claims, so a rejected request rolls back those claims with acceptance. Preparation performs no external provider I/O, and validation disables acquisition. Domain adapters own provider-specific payloads and metadata interpretation. Provisioning composition supplies the database unit of work and concrete providers; storefront code does not import provider-specific types.

### Atomic workload-lifecycle cutovers

A schema cutover that transfers ownership of active workloads between persistence models must treat the workload and its known provider-operation identity as authoritative. The compute provisioner's legacy VM lease conversion validates the complete candidate population and writes fulfillment aggregates atomically before retiring the legacy table. Any unsafe ambiguity rolls back the entire conversion; unused pre-release reservation rows must not override or obscure an active lease.
