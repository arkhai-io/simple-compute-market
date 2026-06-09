# Market core extraction — design + scope

Pick-up doc for the refactor that separates the schema-invariant market
skeleton ("from above") from the schema-specific utilities and
instantiation ("from below"). See `ARCHITECTURE.md` → "Organizing
Principle" for the conceptual frame; this doc is the executable scope.

## Principle (the filing test)

A behavior belongs in the market core (composed _from above_) **iff it is
invariant across every possible listing schema**. If it varies by schema,
it is a from-below utility the core invokes through an injected hook.
"Requiring the hook" is from above; "implementing it" is from below.

Negotiation is an exchange of opaque, schema-defined **messages**. The core's
universal surface is that the whole buyer pipeline is well-typed end to end:

```
listings = discover(query)
terms    = aggregate(negotiate, listings)
receipt  = settle(terms)
```

Discovery yields listings; aggregation drives `negotiate` across them and
reduces to a single `Terms`; settlement consumes exactly that `Terms` to
produce a `Receipt`. Each composition point is enforced by the core.
Aggregation is higher-order over `negotiate` — it receives the negotiation
function, not finished results, so it owns the cross-listing control flow
(e.g. racing listings and taking the first acceptable terms). The core knows
only these shapes and how they compose: messages flow between participants;
discovery returns listings; a negotiation reduces its message history to
`Terms`; `settle(Terms) → Receipt`; settlement runs and reports. The
schema-specific parts plug in from below: the discovery `query` (the
filter-spec), the aggregation policy, the per-turn negotiation policy, and
the `settle` implementation.

It knows nothing about message _content_ (offer / counter / bid /
acceptance are schema vocabulary), how a participant picks its next
message, an acceptance set, floor/ceiling/whitelist semantics, or how a
mismatched message is answered. Seller-advertised data (`accepted_escrows`,
`min_price`, `max_duration_seconds`, …) is just fields on the listing;
interpreting it and responding to mismatches is policy, uniform across
every dimension of a message. Price and escrow shape are the same kind of
thing. Settlement verification needs both sides to derive identical
`Terms`, which holds because `negotiate` is a pure reduction over a shared
message history (the echo mechanism keeps the histories shared).

> **Naming note:** the code says `EscrowProposal` / `Decision.proposal` /
> `_validate_escrow_proposal` where this doc says message/terms. The core
> abstraction is a **message** (the wire unit) reducing to **terms**
> (settlement input); "proposal" names one schema's message shape. Aligning
> the concrete names is part of this refactor, not a precondition for it.

## Hook surface and core structure

The core owns the _structure_ of the exchange and exposes a small number
of hooks within it. The structure: the round loop, signed request/response
transport, thread/history persistence, middleware-chain execution
semantics (a middleware that returns a value terminates the chain;
returning none passes context to the next), and the determinism contract.
Schemas supply the hooks; any further factoring inside a hook (helpers,
shared logic) is the implementation's business, not the core contract.

The composition wants **two** behavior hooks. `run_buy` now exposes
only `negotiate` and `settle`, while the current compute instantiation
still adapts the previous fine-grained hooks outside the core
orchestration call
(`build_escrow_proposal`, `derive_prices`, `build_escrow_terms`,
`create_escrow`, `confirm_settlement`, `chain`) into that surface:

| Core hook   | Type                                                                                                  | Absorbs (today)                                                                                                                                                          |
| ----------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `negotiate` | a per-turn message policy `respond(history) → message \| terms`, run by the core's negotiation engine | `chain`, `derive_prices` (bisection bound = policy input), `build_escrow_proposal` (opening-message construction), `confirm_settlement` (buyer's commit = final message) |
| `settle`    | `Terms → Receipt`                                                                                     | `build_escrow_terms` + `create_escrow` ("materialize" then "submit" is internal factoring of one hook)                                                                   |

`negotiate` is a per-turn decision the engine drives, not a function that
runs the whole negotiation — the existing middleware chain is exactly this
shape.

**When two hooks merge vs stay separate:** merge when the core does
nothing between them; keep separate when a core-enforced boundary sits in
the gap.

- `build_escrow_terms → create_escrow`: nothing of the core sits between
  "materialize the on-chain shape" and "submit it" — one hook.
- `negotiate → settle`: the determinism contract lives in the gap (both
  sides derive identical `Terms`; the seller echoes; settlement verifies
  against the chain-read), and each side runs on different machinery (round
  engine vs settlement/verification) — two phases, with `Terms` as the
  typed handoff.

Separation does not require the hooks to be interchangeable across schemas;
a schema's `negotiate` and `settle` are co-designed and don't
cross-compose. Hooks separate on where the core's boundaries fall, not on
mix-and-match reuse.

**How deep the core goes.** Two kinds of invariant, filed differently:

- _Invariant by typing_ — `settle ∘ negotiate` composition, the
  determinism contract, the role definitions. The irreducible core.
- _Invariant across every market shape currently in view_ — negotiation as
  request/response rounds driven by a middleware chain. Part of the core,
  and the layer that would become a swappable protocol template if a
  structurally-different negotiation appeared: a sealed-bid auction (one
  message, no rounds), a continuous order book (no pairwise negotiation),
  an oracle-priced take-it-or-leave-it (degenerate negotiation). The round
  engine stays in the core until such a market is concrete; factoring it
  out beforehand is a seam with one implementation.

## Target packaging

The eventual top-level repo shape is:

```
core/
  buyer/              # buyer orchestration contracts/helpers, no concrete CLI
  storefront/         # storefront server factory/contracts, no concrete VM app
  registry/           # schema-agnostic listing index service
  registry-client/    # registry protocol client
  storefront-client/  # storefront protocol client

kit/
  identity/           # domain-agnostic identity models/verifiers
  alkahest/           # settlement codecs + token/chain helpers
  config/             # shared config loading and registry URL helpers
  policy/             # only the schema-agnostic policy-chain machinery

domains/
  vms/
    listings/         # VM listing schema, filter vocabulary, rendering, validation
    negotiation/      # VM negotiation message schema, validators, policies, RL runtime
    settlement/       # VM settlement selection + Alkahest materialization
    provisioning/     # VM fulfillment backend
    buyer/            # concrete VM buyer executable package
    storefront/       # concrete VM storefront executable package
    wiring/           # thin adapters that bind VM hooks into core roles
    training/         # offline training code/artifacts for VM policies
```

Tests and users should depend on packages under `domains/` for concrete
markets. `core/` should not ship a default concrete market or runnable
fallback; it should define role contracts, protocol helpers, and
orchestration pieces only in terms of injected dependencies. `kit/`
provides reusable from-below implementations of those dependencies, but
does not depend upward into `core/` or sideways into a domain package.

| Package / subtree                 | Role                                                                                                                                                                                                        | Depends on              |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `core/`                           | from-above: role contracts (buyer/seller/indexer) + discovery/negotiation/aggregation/settlement skeletons, defined over injected callables + generic primitives. No default market, no alkahest, no compute, no provisioning. | from-below kit only     |
| `kit/identity`                    | domain-agnostic identity models + verifiers.                                                                                                                                                                | no core/domain deps     |
| `kit/alkahest`                    | settlement codecs + token/chain helpers.                                                                                                                                                                    | no core/domain deps     |
| `kit/config`                      | shared config loading + registry URL helpers.                                                                                                                                                               | no domain deps          |
| `kit/policy`                      | middleware-chain mechanics and other schema-invariant policy utilities only. VM inventory guards, scalar amount extraction, and Alkahest dispatch do not belong here.                                       | no domain deps          |
| `domains/vms`                     | the concrete VM market product surface: runnable buyer/storefront packages plus VM listing schema/filtering, negotiation messages/policies, settlement wiring, and provisioning. Thin role adapters bind those concepts into core. | core + kit              |
| compatibility packages            | existing names such as `market-service`, `market-buyer`, `market-storefront`, `registry-service`, and client packages may temporarily re-export or wrap the new locations during migration.                 | target package only     |

The kit does **not** need to be one wheel — "from below" means "depended on,
never depending up." The only kit cleanup the principle implies: ensure
nothing in the kit imports up into the skeleton once the core is extracted.

`domains/vms` should not mirror `core/`'s executable roles. The domain
owns the concepts shared by those roles: listings are used by buyers,
storefronts, and registries for filtering/publishing/validation;
negotiation messages and validators are shared by both participants;
settlement is the VM market's chosen payment/escrow materialization; and
provisioning is the VM fulfillment backend. Role-specific files under
`domains/vms/buyer`, `domains/vms/storefront`, or `domains/vms/wiring/`
should be thin adapters, not the main home for domain logic.

The old "agent" name is obsolete. Runtime VM RL negotiation policy code
and checkpoints live under `domains/vms/negotiation/rl/`, with offline
training code kept under `domains/vms/training/`. The legacy
`domains/vms/agent/app/policy` modules are compatibility wrappers during
the migration.

Distribution model (the why): a registry centralizes a schema; the
per-schema instantiation is the _registry operator's_ deliverable. The core
repo ships `market-core` plus the kit; an operator publishes a schema (the
filter-spec plus its typed client counterpart, versioned together) and the
storefront/buyer plugins. The first realistic driver is two compute
registries with incompatible listing shapes.

### Buyer executable and schema packages

The buyer CLI is part of the schema instantiation, not the invariant core.
The concrete `market` executable should eventually come from
`domains/vms/buyer`, not from `core`. Core can expose reusable buyer
orchestration helpers — discover listings, call a domain-provided filter
builder, run negotiation, and hand the resulting `Terms` to settlement —
but it should not own a default CLI, default schema plugin, or generic
runtime fallback. It should not know compute flags such as `--gpu-model`,
`--ram-gb-min`, or `--virt`, nor should it assume ERC20-oriented selectors
such as `--token-contract` are meaningful for every accepted escrow.

Target split:

| Layer | Owns |
| ----- | ---- |
| Core buyer helpers | callable contracts, registry fan-in helper, run-log carrier, `discover → negotiate → settle` orchestration over injected functions |
| Domain buyer package | executable CLI, named filter flags, conversion from CLI args to registry filter params, listing/resource rendering, price-floor extraction, schema-specific prompts and validation |
| Domain settlement package | accepted-escrow selection UX, proposal materialization, demand encoding, chain submission/verification |

The registry already advertises its schema through `filter-spec.yaml`; the
missing packaging piece is a stable schema identity/version that lets a
domain buyer package prove it is compatible with a registry. Schema
packages are a real target, not just documentation: registry/schema
maintainers should distribute buyer-side packages that declare named
filter flags, render listings, and build the schema-specific registry
query. Repeatable `--filter name=value` can stay as a lower-level escape
hatch in concrete domain CLIs, but it is not a core-provided default
market and should not accrete schema behavior.

## Concrete seams (the actual work)

Ordered by remaining implementation value. The completed buyer CLI repair
is kept here as a historical seam because later plugin work builds on it.
The next executable change is the escrow guard middleware.

### 0. Buyer CLI settlement/run-log repair — mostly done

This is a correctness slice that can land independently of the core
extraction. It fixes the current CLI drift caused by generic listing
escrows and listing-level arbiter demands.

- **Done:** on agreement, run logs persist the accepted
  `EscrowProposal`, accepted `EscrowTerms`, and accepted delivery/provision
  terms as the canonical handoff. `market settle --from` and
  `market escrow create --run` replay the accepted proposal/terms instead
  of reconstructing an ERC20-shaped proposal from token/chain fragments.
  Token/chain flags are legacy helpers for old logs and explicit override
  cases, not the generic settlement path.
- **Done:** `market buy` and `market listing list` accept repeatable
  `--filter name=value` passthrough while keeping compute-specific flags as
  convenience aliases. Listing rendering now shows accepted escrow
  kind/shape instead of relying on ERC20-ish token/price columns.
- **Verify/cleanup:** ensure top-level listing `demands` render wherever
  listing detail output should expose payment constraints, and keep old-log
  compatibility code clearly marked as legacy rather than schema core.
- **Boundary:** this does not require plugin discovery, `market-core`, or a
  `ProvisionTerms` wire change. It makes the current compute-instantiated
  CLI honest about the new listing/proposal model so later extraction is a
  move, not another behavior change.

### 0b. Buyer executable schema package boundary

This is the remaining buyer-side schema boundary. It is related to seam 0,
but it is not the same thing: seam 0 made the current VM buyer CLI honest;
this seam moves that concrete executable behavior toward `domains/vms`
instead of treating core as having an embedded default market.

- **Done so far:** `domains/vms/buyer` owns the concrete VM CLI assembly
  and VM command implementations for listing, buy, negotiate, settle, and
  escrow lifecycle commands. The historical `market_buyer.cli` and
  `market_buyer.groups.{listing,buy,negotiate,settle,escrow}` modules are
  compatibility wrappers/aliases.
- **Still present:** `buyer/market_buyer` still owns reusable buyer
  orchestration helpers, protocol clients, run-log utilities, config
  commands, logs/network/chain commands, and compatibility imports. The
  domain command implementations still call those helpers directly.
- **Target:** the VM domain package owns the concrete buyer executable. It
  owns named filter options, conversion to registry query params,
  listing/resource rendering, price-floor extraction, schema-specific
  prompts/validation, and accepted-escrow selection UX.
- **No core default:** if no domain package is installed, core should not
  produce a concrete `market buy` experience. Core helpers may be used by
  a domain package, but users/tests depend on the domain package.
- **Boundary:** until the physical move is complete, the current `buyer/`
  package can act as a compatibility wrapper around VM-domain functions.
  That wrapper is migration scaffolding, not the final default.

### 1. Escrow-shape validation: pre-chain gate → middleware — done

- **Done:** `storefront/.../utils/sync_negotiation.py::_validate_escrow_proposal`
  no longer raises on proposals outside the listing's `accepted_escrows`.
  It only canonicalizes matched proposals by merging listing
  `literal_fields` and `rates`.
- **Done:** the default seller `escrow_shape_guard` middleware now owns the
  `(chain, escrow_address)` membership check and literal-field equality.
  It returns `Some(reject)` for proposals outside the accepted set, or
  `None` when there is no advertised set / no real proposal / legacy zero
  address.
- **Remaining extension:** `Decision`'s `counter` already carries a
  `proposal`, so a custom seller middleware can replace the default guard
  with counter-correction behavior without a new action type.

### 2. Collapse the six behavior hooks to `negotiate` + `settle` — done

- **Done:** `buy_orchestrator.run_buy(...)` requires high-level
  `negotiate` and `settle` hooks and composes only
  discover → negotiate → settle at the top level. Tests can inject doubles
  at that two-hook granularity.
- **Done:** the current compute buyer keeps compatibility adapter
  factories for `build_escrow_proposal`, `derive_prices`,
  `build_escrow_terms`, `create_escrow`, `confirm_settlement`, and
  `chain`. The `market buy` call site and legacy-behavior tests construct
  explicit `negotiate` / `settle` hooks through those adapters; `run_buy`
  itself no longer accepts the fine-grained parameters.
- **Done:** the seller-side synchronous HTTP wrappers now call an
  injectable seller round hook. The default hook owns the current compute
  instantiation: strategy lookup, seller reference amount, configured
  middleware chain, and the resulting `NegotiationDecision`.
  `start_sync_negotiation` and `continue_sync_negotiation` own
  persistence/events and pass only protocol-visible inputs to the hook. The
  default compute hook captures the storefront DB adapter behind the
  callable and collects an available-inventory snapshot internally for the
  compute inventory guard. Policy implementations may be internally
  stateful, but policy-private decision state lives behind the callable
  rather than in generic negotiation tables.
- **Mapped into the two-hook surface:**
  - `derive_prices` → fold into negotiation-policy setup (bisection's
    bounds are policy input; a non-bisection policy supplies its own).
  - `build_escrow_proposal` → the opening-message construction is the
    policy forming its first message; into `negotiate`.
  - `confirm_settlement` → the buyer's commit is its final negotiation
    step, not a separate gate; into `negotiate`.
  - `build_escrow_terms` + `create_escrow` → one `settle: Terms →
Receipt`; "materialize then submit" is internal factoring.
  - done: `run_buy`'s from-above signature dropped the legacy
    prices/escrow construction parameters entirely.
- **Watch:** the DI points exist partly for test isolation (run the
  orchestrator without alkahest-py). Preserve that by letting the
  _instantiation_ inject test doubles for `negotiate`/`settle`, rather
  than the core exposing finer-grained seams for testability.

### 3. `ProvisionTerms` genericization

- **Done:** `service/schemas.py::ProvisionTerms` carries delivery terms as
  `{kind, payload}`. The old flat compute shape
  `{duration_seconds, ssh_public_key, compute_resource}` is accepted for
  compatibility and normalized into `payload`.
- **Done:** compute-specific duration validation now lives at the
  storefront compute negotiation boundary rather than in the shared
  carrier.
- **Still present:** the current compute adapter interprets
  `kind="compute.v1"` through convenience accessors
  (`duration_seconds`, `ssh_public_key`, `compute_resource`). That adapter
  still lives in `buyer/` + `storefront/`; moving it into a separate
  package belongs to seam 4.
- **Target:** `market-compute` defines and validates the concrete compute
  payload. Structural validation of delivery terms (within what the
  listing offers) is core; semantic validation is an injected compute
  validator — same protocol-vs-policy split as escrow.
- **Cost:** wire-compat change on `/negotiate/*`; bump client wheels.

### 4. Extract `market-core`

- Move the discover→negotiate→settle skeleton (`buy_orchestrator`'s
  flow, the seller's per-round protocol from `sync_negotiation`, the
  settlement protocol) into `market-core`, defined over injected hooks +
  generic primitives only.
- `buyer/` + `storefront/` (or a new `market-compute`) become the
  instantiation: wire ERC20 escrow construction, compute resource schema,
  provisioning, the GPU filter-spec into the core hooks.
- The untangling work is real: `action_executor.py` (~960 LOC) and
  `sync_negotiation.py` (~949 LOC) interleave generic flow with
  compute-flavored steps. The function-signature joints are clean; the
  file-level separation is not.

### 5. Package migration prerequisites

The remaining physical moves from top-level packages (`buyer/`,
`storefront/`) to `core/`, `kit/`, and `domains/vms/` should happen after
the code boundaries express the target graph. Otherwise the move becomes a
rename plus a behavior refactor plus a deployment refactor in one step. The protocol
client packages (`registry-client`, `storefront-client`) have already moved
under `core/` while preserving their wheel/import names; the registry
service has moved to `core/registry`, and the provisioning service has
moved to `domains/vms/provisioning/service/`, while preserving their
wheel/import names.

Recommended order:

1. **Done: split and move `kit/policy/`.** `kit/policy/` now keeps only the
   schema-invariant middleware machinery:
   `NegotiationRound`, `NegotiationDecision`, the context carrier,
   middleware-chain execution, and policy discovery. VM/Alkahest-specific
   behavior moved to concept homes under
   `domains/vms/negotiation/` and `domains/vms/settlement/`: scalar amount
   extraction from `proposal.fields["amount"]`, bisection over token
   amounts, escrow-kind dispatch, schema validation, and
   inventory/resource guards. The core can require "run this policy chain"
   without knowing those meanings.
2. **In progress: cut the buyer domain boundary.**
   `domains/vms/listings/` now owns VM models, resource adapters, resource
   CSV import, compute listing reconciliation, filter construction, listing
   rendering, price-floor extraction, compute-resource extraction, and
   strategy selection used by the compatibility `buyer/` and `storefront/`
   packages.
   `domains/vms/settlement/` now owns accepted-escrow selection,
   proposal materialization, compute lease encoding, token materialization,
   Alkahest escrow terms/create helpers, and post-provisioning fulfillment
   submission.
   `domains/vms/provisioning/` now owns VM capacity checks,
   provision-term construction, fulfillment-plan construction,
   provisioning job-spec construction, and provisioning-service client
   helpers.
   `domains/vms/buyer/` now owns the concrete VM CLI assembly and VM
   command implementations for listing, buy, negotiate, settle, and escrow
   lifecycle commands, while the corresponding `market_buyer` modules
   remain compatibility wrappers/aliases.
   `buyer/` remains a temporary compatibility package that calls domain
   functions. Later, core receives only reusable orchestration helpers, not
   a concrete buyer executable.
3. **In progress: extract storefront hooks before moving files.** The generic
   storefront belongs in `core/storefront`: auth, route shells, negotiation
   thread/history persistence, event/stage logging, and invocation of
   injected listing/negotiation/settlement hooks. VM code should be filed
   by concept: `domains/vms/listings/` for `domain_models.py`,
   `resources.py`, resource CSV importers, capacity checks, compute
   listing reconciliation, and compute config defaults;
   `domains/vms/negotiation/` for message validators and runtime policies
   including RL checkpoints; `domains/vms/settlement/` for settlement
   verification/materialization; and `domains/vms/provisioning/` for VM
   fulfillment and lease/listing lifecycle hooks. Done so far:
   `market_core.storefront.models` owns the schema-invariant HTTP
   request/response model surface for listings, negotiation, and
   settlement, while `market_storefront.models.*` remains a compatibility
   wrapper.
   `market_core.storefront.stage_log` owns structured stage-event logging
   and SQLite persistence mechanics; the storefront wrapper only supplies
   the configured DB path.
   `domains/vms/negotiation/storefront_round.py` owns the default VM
   seller-round hook, file policy discovery, and storefront chain loading.
   `domains/vms/provisioning/fulfillment.py` owns VM fulfillment
   orchestration behind explicit storefront callbacks. `sync_negotiation.py`
   and `action_executor.py` remain compatibility/stateful HTTP wrappers.
   `market_core.registry_publication` owns schema-agnostic registry
   publish/close fan-out through injected registry clients and request
   factories; the storefront wrapper keeps settings, SQLite publication
   persistence, and stage-event logging.
4. **Done: move provisioning as VM fulfillment.** `provisioning-service` is
   not core; it is the VM fulfillment backend. It moved to
   `domains/vms/provisioning/service/` after updating Docker build contexts,
   compose service paths, e2e image/build references, storefront dependency
   references, and path-sensitive docs while preserving its wheel/import
   names.
5. **Done: move registry service once schema config is clearly injected.**
   The registry service is already mostly schema-agnostic, so it moved to
   `core/registry` earlier than the storefront. Compute filter behavior
   lives in `filter-spec.yaml` / configured schema data, not in service
   code.
   **Done:** `registry-client` and `storefront-client` have moved under
   `core/` as protocol clients while preserving their Python import names
   (`registry_client`, `storefront_client`) and wheel names.
6. **Use compatibility wrappers, then delete them.** For each package,
   move implementation to the target subtree, leave old top-level modules
   as thin re-exports or console-script wrappers, update internal imports
   and deployment paths, run unit/e2e, then remove wrappers in a separate
   cleanup once consumers are on the new import paths.

## Phases

1. **Seam 1** (done): escrow guard → chain middleware. Default behavior
   still rejects invalid shapes, but the decision now lives in policy and
   can be swapped for correction or softer matching.
2. **Seam 2** (done): reduce the six behavior injections to
   `negotiate` + `settle`. The buyer orchestrator now has the two-hook
   surface, adapter factories for the legacy compute behavior, and the
   `market buy` call site uses explicit hooks. The seller synchronous
   negotiation wrappers now call an injectable seller round hook. The later
   package move happens in seam 4. No packaging change yet — still inside
   `buyer/` + `storefront/`.
3. **Seam 3** (done): `ProvisionTerms` is opaque on the wire; concrete
   compute validation is no longer in the shared carrier. Moving the
   compute adapter into its own package belongs to seam 4.
4. **Seam 4**: extract `market-core` package; split `buyer`/`storefront`
   into skeleton-consumers; verify the kit has no upward imports.
5. **Seam 0b**: extract the concrete VM buyer behavior into the VM domain
   package. The existing `buyer/` package is a compatibility wrapper until
   docs, tests, and scripts depend directly on the VM domain executable.
6. **Package migration**: once the code boundaries are explicit, move the
   remaining top-level packages into `core/`, `kit/`, and `domains/vms/`
   with temporary compatibility wrappers and deployment-path updates.
7. **Policy split cleanup**: the implementation now lives in the right
   direction, but old imports are still compatibility-exported from
   `market_policy.negotiation_middleware`. Remove those shims after buyer
   and storefront code import only the domain policy module.

Each phase keeps the branch green and the e2e suite passing. Seam 3 is the
current target: the wire shape now carries opaque provision terms, and the
remaining work is to move concrete compute interpretation out of shared
core-shaped code. Seam 4 is the later packaging extraction.

## What's deferred / non-goals

- A second resource domain. Validate the principle with heterogeneous
  _compute_ schemas first; the split stands without a wholly different
  thing-being-traded. Settlement mechanism and currency are a separate
  from-below axis — ERC20 escrow today, another escrow or settlement asset
  later — composing orthogonally with the listing and negotiation schema, so
  swapping settlement is a from-below substitution available within any
  domain.
- Shipping multiple schema plugins in this repo. The mechanism for loading
  registry/schema-maintainer plugins is in scope, but until a second schema
  exists, `market-compute` can just be the current buyer+storefront
  depending on the extracted core. Generic `--filter` passthrough remains
  the fallback for registries whose plugin is not installed.
- Generic aggregation beyond the current buyer aggregation policy.

## File map

```
buyer/market_buyer/buy_orchestrator.py        seam 2, 4 — two-hook skeleton + legacy adapters
domains/vms/buyer/buy_cli.py                  seam 0b, 2 — VM market buy command; old market_buyer module aliases this
buyer/market_buyer/groups/buy.py              seam 0b compatibility wrapper
domains/vms/buyer/negotiate_cli.py            seam 0 legacy — accepted proposal/terms run-log handoff
buyer/market_buyer/groups/negotiate.py        seam 0b compatibility wrapper
domains/vms/buyer/settle_cli.py               seam 0 legacy — consume accepted proposal/terms
buyer/market_buyer/groups/settle.py           seam 0b compatibility wrapper
domains/vms/buyer/escrow_cli.py               seam 0 legacy — consume accepted proposal/terms or retire split create
buyer/market_buyer/groups/escrow.py           seam 0b compatibility wrapper
domains/vms/buyer/listing_cli.py              seam 0b — VM listing commands; old market_buyer module wraps this
buyer/market_buyer/groups/listing.py          seam 0b compatibility wrapper
buyer/market_buyer/schema_plugins/ (new)      seam 0b — eventual plugin registry/loading boundary
core/src/market_core/storefront/models/       seam 4 — schema-invariant storefront HTTP models
storefront/src/market_storefront/models/{listing,negotiation,settle}_models.py  seam 4 compatibility wrappers
core/src/market_core/storefront/stage_log.py  seam 4 — schema-invariant stage-event logger/persistence helper
storefront/src/market_storefront/utils/stage_log.py  seam 4 compatibility wrapper supplying settings.db_path
storefront/.../utils/sync_negotiation.py      seam 4 — per-round protocol; seam 1 normalization only
storefront/.../utils/action_executor.py       seam 4 — stateful storefront wrapper; registry publication now delegates to market_core
kit/policy/src/market_policy/negotiation_middleware.py  seam 1 — home for the escrow guard
service/src/service/schemas.py                seam 3 — ProvisionTerms
service/src/service/clients/                  kit — must not import up into core
kit/policy/                                   package migration — generic policy-chain machinery; wheel/import names unchanged
domains/vms/provisioning/service/             package migration — VM provisioning service; wheel/import names unchanged
core/registry/                                package migration — core registry service; wheel/import names unchanged
core/registry-client/, core/storefront-client/  package migration — core protocol clients; Python import names unchanged
```

## References

- `ARCHITECTURE.md` → "Organizing Principle: composition from above and below"
- `TODO.md` → Core Stack → "Market Core Extraction"
- `docs/configuration.md` — current negotiation/aggregation policy config surface
