# Refactor: policy → procedural (except negotiation)

**Status:** phases 1–4 complete on `refactor/procedural-policy`; phase 5
(docs/config) lands alongside the PR.

The codebase used to be a state-machine interpreter: policies emitted
`DomainAction` objects, an `action_executor` match-cased on
`ActionType`, and `DomainEvent` parameter structs were dispatched
through this pipeline. That architecture was right when actions were
genuinely emitted by an autonomous agent loop. After the refactor to
buyer-as-HTTP-client and seller-as-request-response, the interpreter
survives only in cold paths and obscures the actual control flow.

## Target architecture

**Buyer side (procedural with two pluggable policy hooks):**

```
listings = discover(registry_urls, constraints)
terms    = aggregate(negotiate, listings)     # higher-order; aggregate owns iteration
receipt  = settle(terms)
```

`aggregate` takes the `negotiate` function and the candidate list, and
internally drives the iteration. NOT `aggregate([negotiate(l) for l in
listings])` — strategies like "fastest wins" need to race per-listing
negotiations and short-circuit on first agreement, impossible if all
`negotiate` calls have already completed. Already correctly shaped in
`buyer/market_buyer/aggregation.py`.

**Seller side (HTTP endpoints):**

- `GET /listings` — registry discovery
- `POST /negotiate/new`, `POST /negotiate/{id}` — per-round reply driven
  by the seller-side negotiation chain
- `POST /settle/{escrow_uid}` — settlement

**Policy is only relevant in negotiation.** Implemented as a chain of
middlewares with signature:

```
middleware(message_history, context) -> (Maybe<Response>, Context)
```

- `Some<Response>` → chain terminates, that response is sent
  (counter-offer, reject, accept, exit)
- `None` → control passes to the next middleware with the (possibly
  updated) `Context`
- Context is threaded through the chain so middlewares can record
  intermediate state (e.g. computed inventory match) for downstream
  middlewares to read without recomputing

This unifies what's currently two separate systems:

1. Per-round negotiation strategy (`BisectionStrategy.decide` →
   `NegotiationDecision`)
2. Pre-flight guards (`has_matching_inventory`, `escrow_fields_strict_match`
   → `REJECT_OFFER` via DomainEvent/composite)

Both become middlewares in one chain. Round 0 sees empty history;
subsequent rounds see prior messages. Guards typically short-circuit on
round 0 with a reject; the base strategy is the terminal middleware
that always returns a response.

Configured in TOML:
```toml
[negotiation]
chain = ["has_matching_inventory_guard", "escrow_shape_guard", "max_rounds_guard", "bisection"]
```

Loader parallels `buyer/market_buyer/aggregation.py`: named registry +
file discovery + entry-point discovery.

**Everything else** (listing create/close, lease start/end, resource
state transitions) is procedural state mutations on the seller's
inventory. No policy layer.

## Locked-in decisions

- **All listing-state side-effects are procedural.** No policy hooks on
  `POST /listings/create`, `/close`, `/pause`, `/resume`. Lease
  transitions (mark-leased on settle, mark-available on lease end via
  watchdog PATCH) stay direct.
- **Seller negotiation config = chain of named middlewares** in TOML.
  Replaces the single `[negotiation].policy_mode` selector. Old key
  remains readable for back-compat → maps to
  `chain = ["has_matching_inventory_guard", "escrow_shape_guard", policy_mode]`.
- **Listings storage stays dual** — storefront SQLite as inventory
  source-of-truth + write-through sync to registry on state change.
- **`POST /api/v1/alerts/resource` deleted entirely.** Dormant, no
  caller, conceptually unrelated to lease lifecycle (which is already
  procedural via `PATCH /api/v1/resources/{id}` + `apply_resource_set_transition`).
- **Buyer-side aggregation already aligned** (`aggregate(negotiate_fn,
  candidates)` in `buyer/market_buyer/aggregation.py`) — no changes needed.

---

## Phase 1 — Strip dormant state-machine code

**Goal:** remove machinery that has zero or only-dormant callers. No
behavior change.

**Risk:** low. Pure removal.

**Estimated delta:** ~−600 LOC.

**Deletions:**

- `POST /api/v1/alerts/resource` route, `alerts_controller.py`,
  `ResourceAlertRequest`, `ResourceImbalanceEvent` types,
  `ri.*` policy callables in `domain/.../store.py`
- `policy/src/market_policy/action_builders.py::NegotiationActionBuilder`
  (zero callers across the repo)
- 5 dead `ActionType` enum values in `service/src/service/schemas.py`:
  `RESPOND_TO_ORDER`, `IGNORE_ORDER`, `OUTSOURCE`, `RESOLVE_INTERNALLY`,
  `NOOP`
- Match-case branches for the above in `storefront/.../utils/action_executor.py`
- Admin policy-management endpoints + their controllers + request/response
  models:
  - `POST /api/v1/admin/policy/seed`
  - `GET /api/v1/system/policy`
  - `POST /api/v1/system/policy/evaluate`
- Dry-run wrappers (no policy → nothing to dry-run):
  - `POST /api/v1/admin/listings/evaluate-create`
  - `POST /api/v1/admin/listings/{id}/evaluate-close`

**Tests:** delete tests for the above endpoints + the
`NegotiationActionBuilder` module. Other tests should be unaffected.

**Commit subject:** `refactor: strip dormant state-machine code (phase 1/4)`

---

## Phase 2 — Inline listing create/close as procedural

**Goal:** the listing flow stops going through `DomainEvent → policy →
DomainAction → action_executor`. Direct procedural calls instead.

**Risk:** medium. Every e2e test exercises `POST /api/v1/listings/create`.
Behavior must be preserved exactly (paused flag, registry publish/unpublish,
error paths, signature verification).

**Estimated delta:** ~−400 LOC.

**Changes:**

- `listing_service.create_listing`: validate inputs → `sqlite_client.upsert_listing`
  → `publish_order_to_registry`. Lift the registry-publish helper from
  `action_executor` into the service (or `utils/`). Drop the policy
  evaluation entirely.
- `listing_service.close_listing`: SQLite update → registry unpublish.
  Same shape.

**Deletions:**

- `ListingCreatedEvent`, `ListingClosedEvent` (`storefront/.../models/domain_models.py`)
- `_build_listing_created_event`, `_build_listing_closed_event` in `policy_service`
- `oc.action.make_offer_from_order_create`, `oc.action.close_order`
  callables in `domain/.../store.py`
- `evaluate_create_listing_policy`, `execute_create_listing`,
  `evaluate_close_listing_policy`, `execute_close_listing` from
  `policy_service`
- `case ActionType.MAKE_OFFER.value:` and `case ActionType.CLOSE_ORDER.value:`
  branches in `action_executor.execute_action`
- `EventType.ORDER_CREATE`, `EventType.ORDER_CLOSE` enum values

After this phase, `action_executor.execute_action` has no active
dispatch branches in production. Leave the function in place until
Phase 4 (the negotiate-request guard might still go through it briefly
during Phase 3 in-progress states).

**Tests to update:**

- `storefront/tests/integration/test_listings_api.py` (full lifecycle)
- `storefront/tests/unit/test_publications_wiring.py` (publish helpers)
- `storefront/tests/unit/services/test_*.py` for policy_service-touched paths
- Any test that mocks `_build_listing_created_event` or `execute_create_listing`

**Commit subject:** `refactor: inline listing create/close as procedural (phase 2/4)`

---

## Phase 3 — Unify negotiation policy as middleware chain

**Goal:** one middleware system for guards + base strategy. Per-round
signature with explicit context threading.

**Risk:** high. This is the design-load-bearing phase. Negotiation is
exercised by every e2e test.

**Estimated delta:** +400 LOC added, ~−800 LOC deleted (the two existing
systems collapse into one).

**New module: `policy/src/market_policy/negotiation_middleware.py`:**

```python
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class NegotiationContext:
    listing: dict
    our_wallet: str
    chain_name: str
    escrow_proposal: dict | None
    # extension slot for middleware-computed intermediate state
    intermediate: dict

@dataclass
class NegotiationResponse:
    action: str          # "counter" | "accept" | "exit"
    price: float | None
    reason: str | None

# Maybe<Response> * Context
# Returning (None, ctx) means "didn't decide, pass updated ctx to next"
# Returning (Some, ctx) terminates the chain with that response
NegotiationStep = tuple[Optional[NegotiationResponse], NegotiationContext]

NegotiationMiddleware = Callable[
    [list[NegotiationRound], NegotiationContext],
    NegotiationStep,
]

@register_negotiation_middleware("name")
def my_middleware(history, context) -> NegotiationStep: ...
```

**Built-in middlewares to port:**

- `has_matching_inventory_guard` — from `domain/.../store.py:93`
  (`negotiate.guard.has_matching_inventory`)
- `escrow_shape_guard` — from `domain/.../store.py:163`
  (`negotiate.guard.escrow_fields_strict_match`)
- `max_rounds_guard` — new, parameterizable
- `stale_counter_guard` — new (or port from `BisectionStrategy` internals)
- `bisection` — port `BisectionStrategy.decide` → terminal middleware
- `rl` — port `RLStrategy.decide` → terminal middleware (lazy-imports torch)
- `whitelist_guard` / `blacklist_guard` — new, configurable allow/block lists

**Chain runner:**

```python
def run_negotiation_chain(
    chain: list[NegotiationMiddleware],
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationResponse:
    for mw in chain:
        response, context = mw(history, context)
        if response is not None:
            return response
    raise RuntimeError(
        "chain exhausted without a response — the terminal middleware "
        "(typically `bisection` or `rl`) must always return Some"
    )
```

**Call site updates:**

- `storefront/.../utils/sync_negotiation.py`:
  - `start_sync_negotiation` (round 0) builds `NegotiationContext` once
    + calls `run_negotiation_chain(chain, [], context)` instead of
    `strategy_obj.decide(...)`
  - Per-round handler reuses the same chain with the accumulated history
- `POST /negotiate/new` controller: if the round-0 response has
  `action="exit"`, map `reason` to HTTP 409 `{"reason": reason}`. The
  current `consult_pre_negotiation_guards` path disappears.

**TOML config (storefront.bob.toml, storefront.alice.toml):**

```toml
[negotiation]
chain = ["has_matching_inventory_guard", "escrow_shape_guard", "max_rounds_guard", "bisection"]
```

Loader resolves names via registry → entry points → file-based discovery.
Parallel to `buyer/market_buyer/aggregation.py`. Back-compat: if
`[negotiation].policy_mode = "bisection"` is set and `chain` is absent,
synthesize the chain.

**Deletions:**

- `policy/.../negotiation_strategy.py::NegotiationStrategy` Protocol
  (replaced by `NegotiationMiddleware` callable type)
- `BisectionStrategy`, `RLStrategy` classes (their `.decide` impls
  become middleware functions; the parameter-bag config stays as
  module-level constants on the middleware module)
- `_load_storefront_strategy` (replaced by `_load_negotiation_chain`)
- `policy_service.consult_pre_negotiation_guards` (round 0 of the new
  chain does this work)
- `NegotiationRequestedEvent`, `EventType.NEGOTIATION_REQUESTED`
- `negotiate.guard.*` callables in `domain/.../store.py`
- `policy/.../registry.py::policy_callable` decorator +
  `CALLABLE_REGISTRY` global (replaced by
  `register_negotiation_middleware` + a registry specific to the new
  type)

**Tests to update:**

- Every test mocking `_load_storefront_strategy` → switch to mocking
  the chain loader (or to a fixture that injects a test chain)
- Every test asserting on `REJECT_OFFER` from pre-flight guards →
  assert on `NegotiationResponse(action="exit", reason=...)`
- Add unit tests for the chain runner (short-circuit, context threading,
  exhausted-chain error)
- Add unit tests for each ported middleware (focused on the contract,
  not on internals)

**Commit subject:** `refactor: unify negotiation policy as middleware chain (phase 3/4)`

---

## Phase 4 — Delete the dispatch machinery

**Goal:** the `DomainEvent` / `DomainAction` / `action_executor`
machinery is now unreferenced. Final delete.

**Risk:** medium. Lots of files, but pure delete after phases 2 + 3
land cleanly.

**Estimated delta:** ~−500 LOC.

**Deletions:**

- `storefront/.../utils/action_executor.py::execute_action` (no remaining
  cases) — keep the file if helpers like `publish_order_to_registry`,
  `_make_registry_client`, `_extract_initial_price_from_order` still live
  there; just delete the dispatch function and the `ActionType` enum
  import
- `service/src/service/schemas.py`: `DomainAction`, `ActionType`,
  `EventType`, `DomainEvent`, `DecisionContext`, `Decision`
- `policy/.../store.py::PolicyStore.evaluate_policy` (and probably the
  whole class — `PolicyStore` exists only to evaluate composites)
- `storefront/.../policy/seeding.py` (entire file — `ComputePolicySeeder`
  and friends)
- `storefront/.../services/policy_service.py` (entire file — listing
  methods moved to `listing_service` in phase 2; negotiation-guard
  method died in phase 3)
- `domain/compute/agent/app/policy/store.py` (entire file — everything
  in it ported to middlewares in phase 3 or already removed in phase 1)
- `policy/.../registry.py::policy_callable` decorator +
  `CALLABLE_REGISTRY` (if not already removed in phase 3)
- Alembic migration: drop `policies` and `policy_composite` tables from
  storefront SQLite

**Tests:** delete tests for the removed modules. Verify nothing else
imports the deleted symbols.

**Commit subject:** `refactor: delete the dispatch machinery (phase 4/4)`

---

## Phase 5 — Docs cleanup (continuous, lands with relevant phase)

- `docs/ARCHITECTURE.md`: drop "policy engine" framing; replace with
  "two pluggable policy hooks: buyer-side aggregation, seller-side
  negotiation chain"
- `docs/TODO.md`: drop entries superseded by this refactor (the
  "Agent → Storefront mop-up" entry's residual `agent.py` move is the
  only thing left to track separately)
- `docs/seller-quickstart.md`: document `[negotiation].chain` config +
  how to write a custom middleware
- `storefront/storefront.bob.toml`, `storefront.alice.toml`: replace
  `policy_mode = "bisection"` with the explicit chain (kept back-compat
  in code for one release cycle)

---

## Verification per phase

Each phase commits independently and runs:

1. `make test-storefront` (unit + integration tier)
2. `make test-registry` (unit + integration tier)
3. `make test-render` (helm + compose template validation)
4. Phase 2 onward also: `make test-module MODULE=e2e_deal` against a
   rebuilt seller compose stack

See `reference_full_verification_process` memory entry for the full
multi-package verification flow.

## Total estimated delta

Across all four code phases: +400 / −2300, net **−1900 LOC**.

## References

- Memory: [project-buyer-chain-shape](../../.claude/projects/-Users-mlegls-dev-simple-market-service/memory/project_buyer_chain_shape.md)
- Memory: [project-negotiation-middleware-shape](../../.claude/projects/-Users-mlegls-dev-simple-market-service/memory/project_negotiation_middleware_shape.md)
- PR #103 (merged): the cleanup that preceded this refactor (market →
  storefront renames, JIT agent indexing). Commit `02b8072` on staging.
