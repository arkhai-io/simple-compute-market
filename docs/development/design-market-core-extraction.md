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

The composition wants **two** behavior hooks; `run_buy` injects **six**
today (`build_escrow_proposal`, `derive_prices`, `build_escrow_terms`,
`create_escrow`, `confirm_settlement`, `chain`):

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

| Package                                | Role                                                                                                                                                                                                        | Depends on              |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `market-core` (new)                    | from-above: role contracts (buyer/seller/indexer) + discovery/negotiation/aggregation/settlement skeletons, defined over injected callables + generic primitives. No alkahest, no compute, no provisioning. | from-below kit only     |
| from-below kit (existing, stays split) | `market-policy` (middlewares), `market-service` (generic schemas + `service.identity` + infra clients), `registry-client` / `storefront-client`. Mutually independent utilities.                            | nothing in the skeleton |
| `market-compute` (eventual)            | the schema instantiation: ERC20 escrow construction, compute resource schema, GPU filter-spec, provisioning hooks, the buyer CLI + storefront server as thin shells wiring kit impls into core hooks.       | core + kit              |
| `registry-service` (unchanged)         | already schema-agnostic; only coupling is the shipped `filter-spec.yaml` (config, not code).                                                                                                                | —                       |

The kit does **not** need to be one wheel — "from below" means "depended on,
never depending up." The only kit cleanup the principle implies: ensure
nothing in the kit imports up into the skeleton once the core is extracted.

Distribution model (the why): a registry centralizes a schema; the
per-schema instantiation is the _registry operator's_ deliverable. The core
repo ships `market-core` plus the kit; an operator publishes a schema (the
filter-spec plus its typed client counterpart, versioned together) and the
storefront/buyer plugins. The first realistic driver is two compute
registries with incompatible listing shapes.

### Buyer CLI and schema plugins

The buyer CLI is part of the schema instantiation, not the invariant core.
The core command surface should own orchestration only: discover listings,
call a schema-provided filter builder, call schema-provided listing
rendering, run negotiation, and hand the resulting `Terms` to settlement.
It should not know compute flags such as `--gpu-model`, `--ram-gb-min`, or
`--virt`, nor should it assume ERC20-oriented selectors such as
`--token-contract` are meaningful for every accepted escrow.

Target split:

| Layer | Owns |
| ----- | ---- |
| Core CLI shell | command lifecycle, config loading, registry fan-in, generic `--filter key=value` passthrough, run-log plumbing, calling `discover → negotiate → settle` |
| Schema plugin | named filter flags, conversion from CLI args to registry filter params, listing/resource rendering, price-floor extraction, schema-specific prompts and validation |
| Escrow/settlement plugin or codec | accepted-escrow selection UX, proposal materialization, demand encoding, chain submission/verification |

The registry already advertises its schema through `filter-spec.yaml`; the
missing packaging piece is a stable schema identity/version that lets the
buyer select the right schema plugin for a registry. Until that mechanism
exists, the current buyer CLI should be treated as the compute schema
plugin embedded in the `buyer/` package. A generic fallback such as
repeatable `--filter name=value` can land early because it aligns with the
registry's filter-spec without requiring plugin discovery.

## Concrete seams (the actual work)

Ordered cheap → structural. The first two are independent, land-anytime
wins; the last two are the packaging payoff.

### 0. Buyer CLI settlement/run-log repair

This is a correctness slice that can land independently of the core
extraction. It fixes the current CLI drift caused by generic listing
escrows and listing-level arbiter demands.

- **Now:** `market buy` has the seller-echoed `EscrowProposal` in memory
  and can settle from it, but split flows (`market negotiate` followed by
  `market settle --from` or `market escrow create --run`) persist only
  scalar fragments in the run log: seller URL, listing ID, agreed amount,
  duration, token/chain hints, and legacy recipient fields. The follow-up
  commands then reconstruct an ERC20-shaped proposal from config. That is
  wrong for non-ERC20 escrows and wrong for demands-as-listing-data.
- **Target:** on agreement, persist the accepted `EscrowProposal` and
  accepted delivery/provision terms as the canonical run-log handoff.
  `market settle --from` and `market escrow create --run` must replay that
  accepted proposal into the settlement hook. Token/chain flags become
  legacy overrides only for old logs or are removed from these commands.
- **Also:** add generic repeatable `--filter name=value` to `market buy`
  and `market listing list` while keeping compute-specific flags as
  convenience aliases. Improve listing rendering to show accepted escrow
  kind/shape and top-level `demands`, not just ERC20-ish token/price
  columns.
- **Boundary:** this does not require plugin discovery, `market-core`, or a
  `ProvisionTerms` wire change. It makes the current compute-instantiated
  CLI honest about the new listing/proposal model so later extraction is a
  move, not another behavior change.

### 1. Escrow-shape validation: pre-chain gate → middleware

- **Now:** `storefront/.../utils/sync_negotiation.py::_validate_escrow_proposal`
  - `_match_accepted_escrow` raise `OfferUnfulfillableError` _before_
    `_compute_round_zero_decision` runs. The infra decides "out-of-set ⇒
    reject."
- **Target:** the `(chain, escrow_address)` membership check becomes a
  negotiation middleware (a from-below utility) that returns
  `Some(reject)` or `Some(counter-with-corrected-proposal)` or `None`
  (pass). It runs _inside_ the chain, symmetric with `bisection`. A
  seller can then swap reject for correct, or drop it.
- **Watch:** `Decision`'s `counter` already carries a `proposal`, so
  correction is expressible without a new action type. Keep the default
  seller chain shipping a reject-guard first for ergonomic early errors —
  that's a _default_, not a core invariant.
- **Already-policy precedent:** field-equality lives in
  `escrow_fields_strict_match`; this just files the membership check the
  same way.

### 2. Collapse the six behavior hooks to `negotiate` + `settle`

- **Now:** `buy_orchestrator.run_buy(...)` injects six behavior hooks —
  `build_escrow_proposal`, `derive_prices`, `build_escrow_terms`,
  `create_escrow`, `confirm_settlement`, `chain`. Several are consecutive
  or bundled steps the core has no reason to separate.
- **Target** (collapse toward the two-hook surface above):
  - `derive_prices` → fold into negotiation-policy setup (bisection's
    bounds are policy input; a non-bisection policy supplies its own).
  - `build_escrow_proposal` → the opening-message construction is the
    policy forming its first message; into `negotiate`.
  - `confirm_settlement` → the buyer's commit is its final negotiation
    step, not a separate gate; into `negotiate`.
  - `build_escrow_terms` + `create_escrow` → one `settle: Terms →
Receipt`; "materialize then submit" is internal factoring.
  - `run_buy`'s from-above signature should mention neither prices nor
    escrow construction — only `negotiate` and `settle`.
- **Watch:** the DI points exist partly for test isolation (run the
  orchestrator without alkahest-py). Preserve that by letting the
  _instantiation_ inject test doubles for `negotiate`/`settle`, rather
  than the core exposing finer-grained seams for testability.

### 3. `ProvisionTerms` genericization

- **Now:** `service/schemas.py::ProvisionTerms` carries `ssh_public_key`,
  `duration_seconds`, `compute_resource` — compute-specific. The negotiate
  wire protocol names these explicitly.
- **Target:** the core carries delivery terms as an opaque schema blob (as
  the registry already carries `offer_resource`); `market-compute` defines
  the concrete `ProvisionTerms`. Structural validation of delivery terms
  (within what the listing offers) is core; semantic validation is an
  injected compute validator — same protocol-vs-policy split as escrow.
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

## Phases

1. **Seam 1** (cheap, independent, no signature change): escrow guard →
   chain middleware. Lands behind existing negotiation tests; immediately
   unlocks counter-correction and operator-swappable matching.
2. **Seam 0** (buyer CLI repair, independent correctness slice): persist
   accepted terms/proposals in run logs; make split settlement commands
   consume them; add generic filter passthrough + better listing rendering.
   This can land before any extraction and should be done while the buyer
   CLI is visibly out of sync.
3. **Seam 2** (hook collapse): reduce the six behavior injections to
   `negotiate` + `settle`. Touches `run_buy`'s signature and the seller
   per-round path; preserve test isolation by injecting doubles at the
   two-hook granularity. No packaging change yet — still inside
   `buyer/` + `storefront/`.
4. **Seam 3**: `ProvisionTerms` opaque in core, concrete in compute;
   negotiate wire change + client wheel bumps + e2e migration.
5. **Seam 4**: extract `market-core` package; split `buyer`/`storefront`
   into skeleton-consumers; verify the kit has no upward imports.

Each phase keeps the branch green and the e2e suite passing. Seam 1 is the
isolated cheap win; seam 2 is the one that most directly files the
most-touched code (negotiation) against the principle and is worth doing
even if 3–4 are deferred — once the surface is `negotiate` + `settle`, the
later packaging extraction is mostly a move.

## What's deferred / non-goals

- A second resource domain. Validate the principle with heterogeneous
  _compute_ schemas first; the split stands without a wholly different
  thing-being-traded. Settlement mechanism and currency are a separate
  from-below axis — ERC20 escrow today, another escrow or settlement asset
  later — composing orthogonally with the listing and negotiation schema, so
  swapping settlement is a from-below substitution available within any
  domain.
- A formal plugin-discovery mechanism for schema packages. Until a second
  schema exists, `market-compute` can just be the current buyer+storefront
  depending on the extracted core. The buyer CLI should still be shaped so
  compute-specific filter flags and listing rendering are clearly
  schema-plugin behavior, with generic `--filter` passthrough as the
  interim bridge.
- Generic aggregation beyond the current buyer aggregation policy.

## File map

```
buyer/market_buyer/buy_orchestrator.py        seam 2, 4 — skeleton + derive_prices peer
buyer/market_buyer/groups/buy.py              seam 0, 2 — run-log handoff, filters, derive_prices wiring
buyer/market_buyer/groups/negotiate.py        seam 0 — persist accepted proposal/terms
buyer/market_buyer/groups/settle.py           seam 0 — consume accepted proposal/terms
buyer/market_buyer/groups/escrow.py           seam 0 — consume accepted proposal/terms or retire split create
buyer/market_buyer/groups/listing.py          seam 0 — generic filters + schema-aware rendering
storefront/.../utils/sync_negotiation.py      seam 1, 4 — pre-chain gate + per-round protocol
storefront/.../utils/action_executor.py       seam 4 — interleaved generic/compute logic
policy/src/market_policy/negotiation_middleware.py  seam 1 — home for the escrow guard
service/src/service/schemas.py                seam 3 — ProvisionTerms
service/src/service/clients/                  kit — must not import up into core
registry-service/                             unchanged (already schema-agnostic)
```

## References

- `ARCHITECTURE.md` → "Organizing Principle: composition from above and below"
- `TODO.md` → Core Stack → "Market Core Extraction"
- `docs/configuration.md` — current negotiation/aggregation policy config surface
