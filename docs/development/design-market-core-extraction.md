# Market core extraction — design + scope

Pick-up doc for the refactor that separates the schema-invariant market
skeleton ("from above") from the schema-specific utilities and
instantiation ("from below"). See `ARCHITECTURE.md` → "Organizing
Principle" for the conceptual frame; this doc is the executable scope.

## Principle (the filing test)

The core/kit/domain split is about **composition direction**, not only
universality. `core` is composed _from above_: it defines role shapes,
protocol boundaries, and the points where behavior is injected. `kit` is
composed _from below_: reusable implementations and utilities that can help
an injected dependency do its job. Domain packages are also from-below:
they implement the hooks for a concrete market shape and may depend on kit
packages, but the target architecture keeps them from depending back up on
`core`.

Universality is a useful smell, but it is not the filing rule. A behavior
belongs in core when the core must require it as part of the role contract
or protocol skeleton. A behavior belongs in kit or a domain package when it
is an implementation of one of those requirements. "Requiring the hook" is
from above; "implementing it" is from below.

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
shared logic) is the implementation's business, not the core contract. A
domain implementation should be able to expose callables with the required
shape without importing the core package; adapters or composition roots can
wire those callables into the core runner.

The composition wants **two** behavior hooks for the current synchronous
instantiation. (Asynchronous-arbiter settlement adds a third post-settle
phase, `service`; that is additive and planned separately in
`design-settlement-lifecycle-and-capacity.md` — it does not change this
extraction.) `run_buy` now exposes
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
  buyer/              # core-buyer role shell; concrete market behavior injected
  storefront/         # core-storefront role shell; concrete market behavior injected
  registry/           # core-registry listing index shell; schema behavior injected
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
    hooks/            # exported VM hook implementations, no core imports
    training/         # offline training code/artifacts for VM policies
```

`core` is shorthand for the three market roles, not one installable market
package. The role packages are independently installable and executable
(`core-buyer`, `core-storefront`, `core-registry`), but none ships a default
concrete market. Each role executable is a composition root that loads or is
given a domain implementation.

> **Resolved:** `core/src/market_core/` survives as the shared
> `market-core` wheel — the protocol-carrier package for the
> negotiation/settlement wire shapes (escrow proposals/terms, rate
> slots, the opaque provision-terms envelope) that buyer and storefront
> must derive identically from the same message history. It cannot fold
> into either role package without inverting a dependency (the other
> role would import it), and duplicating it would break the determinism
> contract, so it stays a peer of the protocol clients
> (`registry-client`, `storefront-client`). Two rules, both now
> enforced: zero domain vocabulary (the `compute.v1` accessors moved to
> `domains/vms/provisioning/terms.py`; the only residue is the
> explicitly marked legacy wire shim that leaves with the
> `storefront-client` wire bump), and zero dependencies beyond pydantic
> (`core/tests/unit/test_carrier_purity.py` walks the imports).
>
> **Known divergence — settlement-mechanism vocabulary.** The purity
> rules cover the resource/market axis and the import graph, but the
> current escrow carriers bake one settlement *mechanism* into their
> required fields: `EscrowTerms` is literally the alkahest
> `doObligation(data, expirationTime)` call shape, and
> `EscrowProposal`/`AcceptedEscrow` key on
> `(chain_name, escrow_address)`. Alkahest must not be the only
> structurally supported mechanism (fiat escrow is already requested:
> same payer/claimant/amount/expiration/conditions lifecycle, different
> identifier scheme and verification semantics — provider + payment
> refs instead of chain + contract; "provider object satisfies the
> agreed terms" instead of byte-compare against a chain read). The
> wheel's contract is therefore *lifecycle universals + mechanism
> envelope*, not alkahest shapes: each obligation carries
> payer/claimant, asset/amount, expiration, conditions, and a
> mechanism tag with opaque params whose deterministic interpretation
> lives in kit codecs (`kit/alkahest` first, fiat providers later) —
> the same pattern as the `ProvisionTerms` `{kind, payload}` envelope.
> Deliberately NOT fixed standalone: the carrier reshape rides the
> settlement-plan generalization (work item I.1 of
> `design-settlement-lifecycle-and-capacity.md`) so the
> `/negotiate/*` wire and client wheels churn once, not twice. The
> current flat alkahest shapes then become a marked legacy coercion,
> exactly like the flat compute provision terms.

**Executable entrypoints split by role.** The buyer executable is
core-owned: `core-buyer` ships the `market` console script, the common
verb skeleton (`list`, `buy`, …), and schema-plugin discovery (Python
entry-points group); domain buyer packages ship plugins, not competing
CLIs. The buyer is the distribution-sensitive role — one binary, many
registry schemas — and plugin inversion preserves the dependency
direction (core discovers plugins by contract; it never imports
`domains.*`). Without plugins the core binary offers only generic
`--filter` passthrough and raw listing output, never a concrete buy
experience. Storefront executables are the opposite: domain packages own
them, one storefront process per market schema domain. A multi-domain
operator (e.g. raw VMs plus inference) runs parallel storefront
processes that share backend services (capacity/site authority — see
`design-settlement-lifecycle-and-capacity.md`) rather than one
multi-domain process; the shared parts are libraries in
`core_storefront`, not a shared process. The registry stays a core
executable with schema injected as config (`filter-spec.yaml`), as
today. `kit/` provides reusable from-below
implementations used by those domain hooks. The target dependency direction
is one-way from the role runner/composition root into injected domain
behavior; domain hook packages and kit packages do not import upward into
`core`.

| Package / subtree                 | Role                                                                                                                                                                                                        | Depends on              |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `core/{buyer,storefront,registry}` | from-above: independently installable role shells + discovery/negotiation/aggregation/settlement/indexing skeletons, defined over injected callables + generic primitives. No default market, no alkahest, no compute, no provisioning. | kit only where needed   |
| `kit/identity`                    | from-below identity models + verifiers that can implement core hooks or domain utilities.                                                                                                                    | no core/domain deps     |
| `kit/alkahest`                    | from-below settlement codecs + token/chain helpers.                                                                                                                                                          | no core/domain deps     |
| `kit/config`                      | shared config loading + registry URL helpers.                                                                                                                                                               | no domain deps          |
| `kit/policy`                      | from-below middleware-chain mechanics and other policy utilities. VM inventory guards, scalar amount extraction, and Alkahest dispatch do not belong here.                                                   | no domain deps          |
| `domains/vms`                     | the concrete VM market product surface: listing schema/filtering, negotiation messages/policies, settlement wiring, provisioning, and any VM-specific executables. It implements core hook shapes without importing core in the target graph. | kit                     |
| compatibility packages            | existing names such as `market-storefront`, `registry-service`, and client packages may temporarily re-export or wrap the new locations during migration. `market-service` and `market-buyer` have been removed on the reorganization branch. | target package only     |

The kit does **not** need to be one wheel — "from below" means "depended on,
never depending up." The cleanup the principle implies: ensure nothing in
the kit or domain hook packages imports up into the skeleton once the core
is extracted.

`domains/vms` should not mirror `core/`'s executable roles. The domain
owns the concepts shared by those roles: listings are used by buyers,
storefronts, and registries for filtering/publishing/validation;
negotiation messages and validators are shared by both participants;
settlement is the VM market's chosen payment/escrow materialization; and
provisioning is the VM fulfillment backend. Role-specific files under
`domains/vms/buyer`, `domains/vms/storefront`, or `domains/vms/hooks/`
should be thin adapters over those concepts, not the main home for domain
logic. Hook exports are shaped so a core runner can inject them, but the
exports themselves do not import core.

The old "agent" name is obsolete. Runtime VM RL negotiation policy code
and checkpoints live under `domains/vms/negotiation/rl/`, with offline
training code kept under `domains/vms/training/`. The legacy
`domains/vms/agent/` compatibility wrappers have been removed; the
checkpoints are plain state_dicts that embed no module paths, so they
load unchanged from the new location.

Distribution model (the why): a registry centralizes a schema; the
per-schema instantiation is the _registry operator's_ deliverable. The core
repo ships `market-core` plus the kit; an operator publishes a schema (the
filter-spec plus its typed client counterpart, versioned together) and the
storefront/buyer plugins. The first realistic driver is two compute
registries with incompatible listing shapes.

### CLI surfaces

The buyer CLI has a cross-domain user-facing shape: concrete domains should
converge on common verbs such as `list` and `buy`, because buyers, scripts,
and registry/schema plugin authors interact with that surface directly.
That shape belongs in the core buyer role shell, but the command behavior is
incomplete until a domain plugin supplies named filter vocabularies,
rendering, prompts, negotiation hooks, and settlement UX.

The storefront CLI is different. Buyers and registries care about the
storefront HTTP/API contract and registry publication behavior, not the
operator command surface. `core-storefront` owns the generic server shell
and role API. Operator commands such as `start`, `update`, and `publish`
are domain/plugin commands unless they are purely generic lifecycle controls.
If those commands share mechanics, put the mechanics in kit packages.

### Buyer executable and schema packages

The buyer executable is a core role shell with domain injection. The
concrete VM buyer package supplies a plugin/adapter for the core buyer role:
filter flags, query construction, listing rendering, negotiation policy,
settlement materialization, and run-log presentation. Core can define the
buyer role contracts and orchestration skeleton — discover listings, call
an injected filter/query builder, run negotiation, and hand the resulting
`Terms` to settlement — but it should not own a default schema plugin or
generic concrete market fallback. Core should not know compute flags such as
`--gpu-model`, `--ram-gb-min`, or `--virt`, nor should it assume
ERC20-oriented selectors such as `--token-contract` are meaningful for
every accepted escrow.

Target split:

| Layer | Owns |
| ----- | ---- |
| Core buyer role | `core-buyer` role shell, callable contracts, registry fan-in helper, run-log carrier, `discover → negotiate → settle` orchestration over injected functions |
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

- **Done so far:** `domains/vms/buyer` owns the concrete VM CLI assembly,
  VM command implementations, aggregation policies, orchestration helpers,
  negotiation client, run-log utilities, and buyer config/log/network/chain
  commands. The historical top-level buyer compatibility package has been
  removed on the reorganization branch; tests and the console entrypoint
  import the domain package directly.
- **Done (plugin inversion):** `core_buyer.cli` ships the `market`
  console script and verb skeleton; `core_buyer.plugins` defines the
  `BuyerSchemaPlugin` contract discovered through the
  `market.buyer_plugins` entry-point group. `domains/vms/buyer/cli.py`
  is the first plugin: it claims `buy`/`negotiate`/`settle` and the
  `listing` group (named compute filter flags, rendered output) plus the
  operator groups, and `market-buyer` publishes it via the entry point
  instead of a competing console script. The PyInstaller binary
  pre-assembles the same plugin explicitly since frozen bundles can't
  rely on entry-point metadata.
- **Done (no core default):** without plugins the core binary offers only
  generic `market listing list/show` (raw JSON, repeatable
  `--filter name=value` passthrough) and helpful stubs for the buy verbs;
  verbs a plugin claims replace the core fallbacks. Covered by
  `core/buyer/tests/unit/test_cli.py` and the domain-side
  `tests/test_plugin_export.py` end-to-end discovery test.
- **Done:** the physical buyer packaging/test project now lives under
  `domains/vms/buyer/`; the top-level `buyer/` source folder has been
  removed from git.

### 1. Escrow-shape validation: pre-chain gate → middleware — done

- **Done:** `domains/vms/storefront/.../utils/sync_negotiation.py::_validate_escrow_proposal`
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

- **Done:** `core_buyer.run_buy(...)` requires high-level
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

- **Done:** `ProvisionTerms` (now `core/src/market_core/schemas.py`)
  carries delivery terms as
  `{kind, payload}`. The old flat compute shape
  `{duration_seconds, ssh_public_key, compute_resource}` is accepted for
  compatibility and normalized into `payload`.
- **Done:** compute-specific duration validation now lives at the
  storefront compute negotiation boundary rather than in the shared
  carrier.
- **Still present (and relocated into core):** the `compute.v1`
  convenience accessors
  (`duration_seconds`, `ssh_public_key`, `compute_resource`) are now
  defined on `market_core.schemas.ProvisionTerms` itself, so the compute
  interpretation sits inside `core/` — the wrong direction. The carrier
  should stay an opaque `{kind, payload}` envelope; the accessors and
  payload validation move to `domains/vms` as part of seam 4, with VM
  code interpreting the payload through its own adapter.
- **Target:** `market-compute` defines and validates the concrete compute
  payload. Structural validation of delivery terms (within what the
  listing offers) is core; semantic validation is an injected compute
  validator — same protocol-vs-policy split as escrow.
- **Cost:** wire-compat change on `/negotiate/*`; bump client wheels.

### 4. Extract `market-core`

- Move the discover→negotiate→settle skeleton (`buy_orchestrator`'s
  flow, the seller's per-round protocol from `sync_negotiation`, the
  settlement protocol) into `market-core`, defined over injected hooks +
  generic primitives only. *(How it actually landed: the role skeletons
  went into the role packages — `core_buyer.orchestrator`,
  `core_storefront.negotiation_sync` — and `market-core` kept only the
  shared wire carriers; see the resolved callout in "Target
  packaging".)*
- `domains/vms/buyer/` + the remaining `domains/vms/storefront/` package become the
  instantiation: wire ERC20 escrow construction, compute resource schema,
  provisioning, the GPU filter-spec into the core hooks.
- The untangling work is real: the old `action_executor.py` has been split
  into semantic storefront services, but `sync_negotiation.py` still
  interleaves generic flow with compute-flavored steps. The function-signature
  joints are clean; the remaining file-level separation is not.

### 5. Package migration prerequisites

The remaining physical moves from top-level packages to `core/`, `kit/`,
and `domains/vms/` should happen after
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
   strategy selection used by the VM buyer and remaining storefront
   package.
   `domains/vms/settlement/` now owns accepted-escrow selection,
   proposal materialization, compute lease encoding, token materialization,
   Alkahest escrow terms/create helpers, and post-provisioning fulfillment
   submission.
   `market_alkahest.schemas` owns generic Alkahest accepted-escrow
   matching and proposal normalization across escrow kinds; VM code only
   extracts the listing's `accepted_escrows` collection before calling it.
   `market_alkahest.alkahest` owns generic proposal-to-terms payload
   materialization; VM storefront code only supplies the chain address
   config path.
   `domains/vms/provisioning/` now owns VM capacity checks,
   provision-term construction, fulfillment-plan construction,
   provisioning job-spec construction, and provisioning-service client
   helpers.
   `domains/vms/buyer/` now owns the concrete VM CLI assembly and VM
   command implementations for listing, buy, negotiate, settle, escrow
   lifecycle commands, aggregation policies, negotiation HTTP client, run
   logs, buyer config/log/network/chain commands, and the packaging/test
   project for the VM buyer console script.
   `core-buyer` now owns the schema-invariant buyer config/result
   carriers, registry discovery fan-in, and `discover -> negotiate ->
   settle` orchestration over injected hooks. The VM buyer module re-exports
   those pieces while retaining VM-specific hook adapters.
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
   `core_storefront.models` owns the schema-invariant HTTP
   request/response model surface for listings, negotiation, settlement,
   and generic system responses; VM provisioning/admin payloads live in
   `domains/vms/provisioning/storefront_models.py`.
   `core_storefront.stage_log` owns structured stage-event logging
   and SQLite persistence mechanics; the VM storefront configures its DB
   path during FastAPI lifespan startup.
   `core_storefront.services.negotiation_service` owns the generic
   negotiation list/detail/admin-advance service logic over injected
   continue-round and stage-event hooks; the storefront wrapper supplies
   the current VM sync-negotiation and logging functions.
   `core_storefront.negotiation_sync` owns generic synchronous-negotiation
   error carriers, live-listing status constants, pinned-proposal
   reconstruction, persisted-message-to-round history conversion,
   sync-negotiation thread creation, and message plus terminal-state
   persistence; the VM
   wrapper keeps policy/config adapters, listing validation, proposal amount
   extraction, and settlement-term materialization.
   `core_storefront.auth` owns framework-free signed request
   verification and admin-key checks; `market_storefront.middleware.*`
   remains the FastAPI/settings adapter layer.
   `domains/vms/negotiation/storefront_round.py` owns the default VM
   seller-round hook, file policy discovery, storefront chain loading, and
   opening/counter semantic checks through `round_zero_opening_guard` and
   `buyer_counter_guard`.
   `domains/vms/provisioning/fulfillment.py` owns VM fulfillment
   orchestration behind explicit storefront callbacks. `sync_negotiation.py`
   remains a compatibility/stateful HTTP wrapper. `fulfillment_service.py` is now
   limited to VM fulfillment orchestration for settled compute obligations.
   `domains/vms/settlement/proposals.py` owns VM accepted-escrow response
   artifact assembly by supplying domain inputs to the generic Alkahest kit
   materializer.
   `core_storefront.registry_publication` owns schema-agnostic registry
   publish/close fan-out through injected registry clients and request
   factories; `market_storefront.services.publication_service` keeps VM
   storefront settings, SQLite publication persistence, dynamic listing close
   reconciliation, and stage-event logging.
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

Top-level folder tracker:

1. **Done: remove `domain/`.** This was a stale one-file package; the real
   domain namespace is `domains/`.
2. **Done: remove top-level `provisioning-service/`.** The VM fulfillment
   backend lives under `domains/vms/provisioning/service/`.
3. **Done: remove top-level registry packages.** The registry service and
   protocol clients live under `core/` while preserving their import/wheel
   names.
4. **Done: remove top-level `buyer/`.** The VM buyer implementation,
   packaging project, tests, and build entrypoint live under
   `domains/vms/buyer/`. Remaining ignored local state under top-level
   `buyer/` can be deleted locally without affecting repo source.
5. **Done: remove top-level `service/`.** Shared schemas, config, identity,
   Alkahest, token, and chain helpers are consumed directly from
   `core/` and `kit/`; the compatibility `market-service` wheel is gone.
6. **Done: remove top-level `storefront/`.** The VM storefront executable,
   packaging project, tests, Dockerfile, and sample configs live under
   `domains/vms/storefront/`, while the already extracted schema-invariant
   storefront pieces remain under `core/storefront/`.
7. **Done: move VM provisioning IaC.** The Ansible/Packer VM execution
   tree lives under `domains/vms/provisioning/iac/`, next to the
   provisioning service and storefront-facing provisioning hooks.
8. **Done: remove compute listing reconciliation wrapper.** Storefront
   callers import `domains.vms.listings.reconciler` directly.
9. **Done: remove VM resource/import wrapper modules.** Storefront code
   imports VM listing resources, resource CSV import, host CSV import, and
   capacity checks directly from `domains.vms.*`.
10. **Done: remove stale storefront validation helpers.** Validation and
   strategy selection now live directly in VM listing modules rather than
   a storefront utility wrapper.
11. **Done: remove pure VM helper exports from action executor.** VM
   pricing, compute extraction, and compute lease encoding are referenced
   through `domains.vms.listings` / `domains.vms.settlement`; the
   storefront action executor remains only as stateful composition.
12. **In progress: drain `domains/vms/storefront/` internals.** Move
   remaining schema-invariant storefront runtime into `core/storefront`,
   and VM listing/negotiation/settlement/provisioning hooks into
   `domains/vms/*`. `utils/sync_negotiation.py` is now a thin
   stateful/config wrapper over `core_storefront.negotiation_sync`; the
   remaining `market_storefront` controllers/middleware/services are
   adapters over core, which is the intended end shape. **Constraint:**
   do not drain the capacity/inventory tables (`hosts`,
   `compute_allocations`) into `core_storefront` — they are slated to
   move *down* into the site authority, while the aggregation tables
   (`compute_inventory_pools`, `compute_pool_members`,
   `derived_compute_listings`) stay storefront-side as the market-domain
   view. See `design-settlement-lifecycle-and-capacity.md`.

This tracker intentionally ignores generated or local-only top-level
directories such as `.dist/`, `.uv-cache/`, `.pytest_cache/`, `src/`,
and `shared-env/`.

## Phases

1. **Seam 1** (done): escrow guard → chain middleware. Default behavior
   still rejects invalid shapes, but the decision now lives in policy and
   can be swapped for correction or softer matching.
2. **Seam 2** (done): reduce the six behavior injections to
   `negotiate` + `settle`. The buyer orchestrator now has the two-hook
   surface, adapter factories for the legacy compute behavior, and the
   `market buy` call site uses explicit hooks. The seller synchronous
   negotiation wrappers now call an injectable seller round hook. The later
   package move happens in seam 4. The buyer packaging has moved to
   `domains/vms/buyer/`; the remaining packaging split is storefront-side.
3. **Seam 3** (done): `ProvisionTerms` is opaque on the wire; concrete
   compute validation is no longer in the shared carrier. Moving the
   compute adapter into its own package belongs to seam 4.
4. **Seam 4** (done): the role skeletons live in the role packages
   (`core_buyer`, `core_storefront`), the remaining storefront package
   is skeleton-consuming adapters, the kit has no upward imports
   (enforced by the dependency-direction guardrail), and `market-core`
   is settled as the pure protocol-carrier wheel (stdlib + pydantic
   only, enforced by `test_carrier_purity.py`).
5. **Seam 0b** (done): extract the concrete VM buyer behavior, packaging,
   tests, and scripts into the VM domain package.
6. **Package migration**: once the code boundaries are explicit, move the
   remaining top-level packages into `core/`, `kit/`, and `domains/vms/`
   with temporary compatibility wrappers and deployment-path updates.
7. **Policy split cleanup** (done): `market_policy.negotiation_middleware`
   now exports only the schema-agnostic chain machinery
   (`NegotiationRound`, `NegotiationDecision`, context, chain execution,
   policy discovery); remaining importers consume only the generic types.

Each phase keeps the branch green and the e2e suite passing. Seams 0–4,
0b, and the policy cleanup are done. Seam 4 closed in four moves: the
`compute.v1` interpretation moved out of `market_core.schemas` into
`domains/vms/provisioning`; the buyer plugin extraction landed (verb
skeleton + entry-point plugin discovery in `core-buyer`, the VM CLI as
the first plugin); the storefront's capacity access went behind the
site-authority client boundary (`core_storefront.capacity` contract,
embedded adapter, snapshot/reserve re-route, event-driven stale-listing
closure — work items II.1–II.3 of the capacity doc); and the
`market-core` carriers-wheel question is settled (the wheel survives as
the pure protocol-carrier package — see the resolved callout in
"Target packaging"). Known residue: the `storefront-client` wheel still
sends the flat legacy provision-terms wire shape, which is what keeps
the marked legacy shim in `ProvisionTerms`; genericizing that client
API is the remaining wire-compat item. Follow-on architecture beyond
this reorganization — asynchronous settlement lifecycles and the shared
capacity/site-authority split (next: work item II.4, the site-authority
service itself) — is planned in
`design-settlement-lifecycle-and-capacity.md`.

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
core/src/market_core/schemas.py               seam 3, 4 done — pure protocol carriers (escrow/rate/provision-terms wire shapes); purity enforced by core/tests/unit/test_carrier_purity.py
core/buyer/                                   seam 2, 4 — core buyer role carriers, discovery fan-in, run_buy shell
domains/vms/buyer/buy_orchestrator.py         seam 2, 4 — VM legacy negotiate/settle hook adapters
domains/vms/buyer/buy_cli.py                  seam 0b, 2 — VM market buy command
domains/vms/buyer/negotiate_cli.py            seam 0 legacy — accepted proposal/terms run-log handoff
domains/vms/buyer/settle_cli.py               seam 0 legacy — consume accepted proposal/terms
domains/vms/buyer/escrow_cli.py               seam 0 legacy — consume accepted proposal/terms or retire split create
domains/vms/buyer/listing_cli.py              seam 0b — VM listing commands
domains/vms/buyer/aggregation.py              seam 0b — across-seller aggregation policies
core/buyer/src/core_buyer/{cli,plugins}.py    seam 0b done — `market` console script, verb skeleton, entry-points plugin loading
domains/vms/buyer/cli.py                      seam 0b done — VM schema plugin exposed via `market.buyer_plugins` entry point
core/storefront/src/core_storefront/models/   seam 4 — schema-invariant storefront HTTP models
core/storefront/src/core_storefront/stage_log.py  seam 4 — schema-invariant stage-event logger/persistence helper
core/storefront/src/core_storefront/services/negotiation_service.py  seam 4 — generic negotiation query/admin service over injected hooks
core/storefront/src/core_storefront/negotiation_sync.py  seam 4 — generic sync negotiation carriers/history reconstruction
domains/vms/storefront/src/market_storefront/server.py  seam 4 — VM composition point wiring core negotiation service hooks
core/storefront/src/core_storefront/auth.py   seam 4 — framework-free signed request/admin-key verification
domains/vms/storefront/src/market_storefront/middleware/  seam 4 FastAPI/settings auth wrappers
domains/vms/storefront/.../utils/sync_negotiation.py      seam 4 — per-round protocol; seam 1 normalization only
domains/vms/storefront/.../services/publication_service.py  seam 4 — VM storefront registry publication/close wiring over core publication helpers
domains/vms/storefront/.../services/fulfillment_service.py    seam 4 — VM fulfillment orchestration wrapper for settled compute obligations
kit/policy/src/market_policy/negotiation_middleware.py  seam 1 — home for the escrow guard
kit/policy/                                   package migration — generic policy-chain machinery; wheel/import names unchanged
domains/vms/provisioning/service/             package migration — VM provisioning service; wheel/import names unchanged
core/registry/                                package migration — core registry service; wheel/import names unchanged
core/registry-client/, core/storefront-client/  package migration — core protocol clients; Python import names unchanged
```

## References

- `ARCHITECTURE.md` → "Organizing Principle: composition from above and below"
- `TODO.md` → Core Stack → "Market Core Extraction"
- `docs/configuration.md` — current negotiation/aggregation policy config surface
- `docs/development/design-settlement-lifecycle-and-capacity.md` —
  follow-on architecture: asynchronous settlement lifecycles, shared
  capacity / site authority, executable entrypoint topology
