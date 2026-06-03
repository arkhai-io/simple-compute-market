# Configuration reference

Three pluggable hooks in the marketplace:

1. **Seller negotiation policies** (`storefront.toml` →
   `[negotiation] policies`) — what the seller does each round.
2. **Buyer negotiation policies** (`buyer.toml` →
   `[negotiation] policies`) — what the buyer does each round. Same
   middleware shape as the seller; different bundled defaults.
3. **Buyer aggregation policy** (`buyer.toml` → `[aggregation] policy`) —
   how the buyer iterates across candidate listings.

Everything else is procedural. This page documents all three config
surfaces, the bundled options that ship with the wheels, and how to
write your own.

## Seller: negotiation policies

The seller runs an ordered list of policies (middlewares) per
negotiation round. Each policy looks at the round history + context and
either short-circuits the chain with a response, or defers to the next
policy.

### Config

```toml
[negotiation]
policies = [
  "has_matching_inventory_guard",
  "escrow_shape_guard",
  "max_rounds_guard",
  "bisection",
]

# Optional directories scanned at startup for custom policies.
# Each immediate subdirectory is treated as a policy named after the
# folder; the subdir must contain a policy.py exposing
# `factory(cfg) -> NegotiationMiddleware`. See "Custom policies" below.
# extra_policy_paths = []

# Legacy back-compat key (synthesized into a default chain when
# `policies` is absent): "bisection" | "rl".
# policy_mode = "bisection"
```

`policies` is an ordered list — the storefront runs them in sequence at
every `/negotiate/new` and `/negotiate/{id}` call. The **first**
non-`None` decision returned terminates the chain. The **last** policy
must always return a decision (it's the terminal); guards may return
`None` to defer.

### Bundled policies

| Name | Type | Round(s) | Behavior |
|---|---|---|---|
| `has_matching_inventory_guard` | Guard | 0 | Rejects with `no_matching_inventory` if the seller's portfolio has no available resource matching the listing's `offer_resource`. |
| `escrow_shape_guard` | Guard | every | Rejects with `escrow_field_mismatch` if any seller-pinned key on `accepted_escrows[i].literal_fields` doesn't equal the buyer's value in `escrow_proposal.literal_fields`. |
| `max_rounds_guard` | Guard | every | Exits with `max_rounds_reached` once `len(history) >= [negotiation].max_rounds` (default 5). |
| `bisection` | Terminal | every | Bisects between the seller's floor (`accepted_escrows[0]` primary rate × duration) and the peer's latest offer; accepts within ~1% convergence, counters at midpoint, exits with `price_unreasonable` when the peer's offer is below `floor / 1.5`. No ML dependencies. |
| `rl` | Terminal | every | Loads the trained pufferlib checkpoint at `domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt` and produces the next move. Requires the `[rl]` extra (torch + pufferlib). Exits with `torch_unavailable` if torch isn't installed; exits with `model_missing` if the checkpoint isn't at the configured path. |
| `buyer_escrow_shape_guard` | Guard | every | Buyer-side mirror of `escrow_shape_guard`: rejects when the seller's counter changes a field the buyer pinned at round 0 (excludes `amount`, which is what's being negotiated). |

`bisection` is the safe default terminal. `rl` is opt-in — keep it out
of the list unless torch is installed and the model file exists; the
`/api/v1/system/status` `negotiation_strategy` check will catch a
broken `rl` setup at startup.

### The middleware contract

```python
from market_policy import NegotiationContext, NegotiationDecision

# Maybe<Response> * Context
#   None         → defer to the next policy with the (possibly updated) ctx
#   Some<Response> → short-circuit the chain; that response is sent
NegotiationStep = tuple[Optional[NegotiationDecision], NegotiationContext]

NegotiationMiddleware = Callable[
    [list[NegotiationRound], NegotiationContext],
    NegotiationStep,
]
```

`NegotiationContext` carries the listing, the buyer's escrow proposal,
the seller's reference price for this round, the agreed direction
(`minimize` | `maximize`), and a free-form `intermediate: dict` slot
that policies can use to publish computed state for downstream policies
without recomputing.

### Custom policies

Two ways to register:

**1. Decorator (in-process):** any Python module imported by the
storefront can register a middleware:

```python
from market_policy import (
    NegotiationDecision,
    register_negotiation_middleware,
)

@register_negotiation_middleware("region_lock")
def region_lock(history, context):
    if context.listing.get("offer_resource", {}).get("region") not in {"California, US"}:
        return (
            NegotiationDecision(action="reject", reason="region_not_supported"),
            context,
        )
    return None, context
```

Then list `"region_lock"` in `[negotiation] policies`.

**2. File discovery (no Python packaging):** drop a policy folder under
`$XDG_CONFIG_HOME/arkhai/policies/<policy_name>/policy.py` (or under a
directory listed in `[negotiation] extra_policy_paths`). The file must
expose `factory(cfg) -> NegotiationMiddleware`. The storefront
discovers and registers them at startup; the folder name becomes the
policy name listed in `[negotiation] policies`.

---

## Buyer: negotiation policies

The buyer runs the **same middleware shape** as the seller — same
`(history, context) -> (Maybe<Response>, Context)` contract, same
`load_negotiation_chain()` registry. The difference is which middlewares
make sense on each side: the buyer's default ships with a
`buyer_escrow_shape_guard` (rejects seller counters that mutate buyer-
pinned fields) plus a terminal (`bisection` or `rl`).

### Config

```toml
[negotiation]
policies = ["buyer_escrow_shape_guard", "bisection"]

# Legacy back-compat key (synthesized into
# `["buyer_escrow_shape_guard", <policy_mode>]` when `policies` is absent):
# policy_mode = "bisection"
```

`policies` and `policy_mode` work the same way as on the seller — if
both are unset, `negotiate_with_seller` falls through to its default
chain (the same default the synthesis produces).

### Bundled policies usable on the buyer side

The same registry serves both sides — every middleware listed in the
seller's "Bundled policies" table above is importable here too. The
ones that make sense buyer-side:

| Name | Why on the buyer side |
|---|---|
| `buyer_escrow_shape_guard` | Rejects any seller counter that diverges from a buyer-pinned escrow field (token, arbiter, escrow contract, expiration). Default first entry. |
| `max_rounds_guard` | Same as seller — exits after `[negotiation].max_rounds`. |
| `bisection` *(default terminal)* | Symmetric — bisects from the buyer's side (`minimize` direction). |
| `rl` | Symmetric — loads the buyer's trained checkpoint at `domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt`. |

The seller-only guards (`has_matching_inventory_guard`,
`escrow_shape_guard`) reference seller-side context that doesn't exist
on the buyer's chain — they're no-ops on the buyer side and shouldn't
be listed.

Custom policies — register via `@register_negotiation_middleware(...)`
or drop into `[negotiation] extra_policy_paths` exactly as described in
the seller section.

---

## Buyer: aggregation policy

The buyer runs **one** aggregation policy across the listings the
registry returned. The policy owns the iteration shape — sequential vs.
parallel, take-first-agreed vs. compare-all — and returns the winning
`(listing, negotiation_outcome)` tuple. It receives a `negotiate`
callback as a parameter so it can race per-listing negotiations and
short-circuit (e.g. "fastest wins" cancels everyone else).

### Config

```toml
[aggregation]
# policy = "best_price"

# Optional wall-clock cap (seconds) for the `best_price` policy.
# Candidates still negotiating at the deadline are cancelled and the
# lowest agreed price among those that completed wins. Unset = wait
# for all candidates.
# best_price_timeout = 30.0

# Optional directories scanned at startup for custom aggregation
# policies (see "Custom policies" below).
# extra_policy_paths = []
```

The CLI flag `--aggregate-by <name>` overrides the TOML key for a
single `market buy` invocation.

### Bundled policies

| Name | Iteration | Winner |
|---|---|---|
| `best_price` *(default)* | Parallel across all candidates | Lowest `agreed_amount` |
| `cheapest_first` | Sequential, ascending advertised price | First candidate that agrees |
| `registry_order` | Sequential, registry's response order | First candidate that agrees |
| `random_shuffle` | Sequential, uniform shuffle | First candidate that agrees |
| `priceless_last` | Sequential — priced (cheapest first) then priceless | First candidate that agrees |
| `fastest_agreed` | Parallel race | First candidate that agrees (others cancelled) |

`best_price` is the headline comparison-shopping policy. Bound the
candidate list upstream with `max_matches_to_try` to control fan-out,
and set `best_price_timeout` so one slow seller can't hold up the buy.

`fastest_agreed` is for provision-ASAP, price-insensitive buys —
sellers that exit or raise are dropped and the race continues against
the survivors.

### The aggregation contract

```python
from market_buyer.aggregation import (
    AggregationPolicy,
    NegotiateFn,
    register_aggregation_policy,
)

# AggregationPolicy = Callable[
#   [list[Listing], NegotiateFn],
#   Awaitable[tuple[Listing, NegotiationOutcome] | None]
# ]
```

Returning `None` means "no candidate agreed."

### Custom policies

Same two paths as on the seller side:

**1. Decorator (in-process):**

```python
from market_buyer.aggregation import (
    NegotiationOutcome,
    register_aggregation_policy,
)

@register_aggregation_policy("my_strat")
async def my_strat(candidates, negotiate):
    for c in candidates:
        outcome = await negotiate(c)
        if outcome.status == "agreed":
            return c, outcome
    return None
```

**2. File discovery:** drop a folder under
`$XDG_CONFIG_HOME/arkhai/aggregation_policies/<name>/policy.py`
exposing `factory(cfg) -> AggregationPolicy`, or list extra
directories in `[aggregation] extra_policy_paths`. The folder name
becomes the policy name.

(Note: the seller's policy directory is `policies/` under
`~/.config/arkhai/`; the buyer's is `aggregation_policies/`. Distinct
folders because the two policy types are unrelated and a single
registry would conflict if a folder name overlapped.)

---

## Reference

- Seller settings schema: `storefront/src/market_storefront/settings.toml`.
- Buyer settings example: `buyer/market_buyer/groups/config.py` (the
  `init-user` template comment).
- Middleware module: `policy/src/market_policy/negotiation_middleware.py`.
- Aggregation module: `buyer/market_buyer/aggregation.py`.
