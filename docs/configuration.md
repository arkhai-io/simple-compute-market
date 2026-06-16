# Configuration reference

Four pluggable hooks in the marketplace:

1. **Seller negotiation policies** (`storefront.toml` →
   `[negotiation] policies`) — what the seller does each round.
2. **Buyer negotiation policy** (`buyer.toml` →
   `[negotiation] policy`, or an explicit `[negotiation] policies`
   chain) — what the buyer does each round, plus the pricing flags
   `buy`/`negotiate` expose. Same middleware shape as the seller;
   different bundled defaults.
3. **Buyer aggregation policy** (`buyer.toml` → `[aggregation] policy`) —
   how the buyer iterates across candidate listings.
4. **Storefront fulfillment failure policy** (`storefront.toml` →
   `[fulfillment.failure_policy] actions`) — what the seller does when
   provisioning/fulfillment fails.

Everything else is procedural. This page documents these config
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

`policies` may be either an ordered list or a per-escrow-kind table.

As an ordered list, the storefront runs entries in sequence at every
`/negotiate/new` and `/negotiate/{id}` call. The **first** non-`None`
decision returned terminates the chain; guards may return `None` to
defer. There is no separate "terminal" policy type — every policy has
the same shape — but a chain whose every entry defers raises
`NegotiationChainExhausted` rather than substituting a default, so the
**last** policy in a chain must always decide.

As a table, the storefront keeps the default seller guards
(`has_matching_inventory_guard`, `escrow_shape_guard`) and dispatches
the terminal policy by the selected proposal's Alkahest escrow kind:

```toml
[negotiation.policies]
erc20 = "erc20_bisection"
native_token = "native_token_bisection"
erc1155 = "erc1155_bisection"
default = "accept_exact_listing"

[negotiation.policies.erc721]
chain = ["accept_exact_listing"]
```

Keys may be exact Alkahest kinds such as
`erc20_escrow_obligation_nontierable`, family keys such as `erc20`,
`native_token`, or `erc1155`, or `default`. A string value is a single
terminal policy. A nested table with `chain = [...]`, `policies = [...]`,
or `policy = "..."` is used when one escrow kind needs its own sequence.

### Bundled policies

| Name | Type | Round(s) | Behavior |
|---|---|---|---|
| `has_matching_inventory_guard` | Guard | 0 | Rejects with `no_matching_inventory` if the seller's portfolio has no available resource matching the listing's `offer_resource`. |
| `escrow_shape_guard` | Guard | every | Rejects with `escrow_field_mismatch` if any seller-pinned key on `accepted_escrows[i].literal_fields` doesn't equal the buyer's value in `escrow_proposal.literal_fields`. |
| `max_rounds_guard` | Guard | every | Exits with `max_rounds_reached` once `len(history) >= [negotiation].max_rounds` (default 5). |
| `bisection` | Decider | every | Bisects between the seller's floor (`accepted_escrows[0]` primary rate × duration) and the peer's latest offer; accepts within ~1% convergence, counters at midpoint, exits with `price_unreasonable` when the peer's offer is below `floor / 1.5`. No ML dependencies. |
| `listed_price` | Decider | every | Accepts the peer's proposal when its amount is within the side's bound (≥ the floor in `maximize`, ≤ the ceiling in `minimize`); exits with `price_above_bound` otherwise. Never counters beyond the opening; accepts amountless escrow shapes as proposed. |
| `rl` | Decider | every | Loads the trained pufferlib checkpoint at `domains/vms/negotiation/rl/models/arkhai_negotiator_seller.pt` and produces the next move. Requires the `[rl]` extra (torch + pufferlib). Exits with `torch_unavailable` if torch isn't installed; exits with `model_missing` if the checkpoint isn't at the configured path. |
| `erc20_bisection`, `native_token_bisection`, `erc1155_bisection` | Decider | every | Escrow-family names for the same scalar-`amount` bisection policy. Useful in `[negotiation.policies]` dispatch tables. |
| `erc20_rl`, `native_token_rl`, `erc1155_rl` | Decider | every | Escrow-family names for the same scalar-`amount` RL policy. Requires the same torch/checkpoint setup as `rl`. |
| `accept_exact_listing` | Decider | every | Accepts only when the buyer proposal exactly matches the selected listing escrow entry, listing-level demands, and concrete amount; rejects all mismatches and never counters. |
| `buyer_escrow_shape_guard` | Guard | every | Buyer-side mirror of `escrow_shape_guard`: rejects when the seller's counter changes a field the buyer pinned at round 0 (excludes `amount`, which is what's being negotiated). |

`bisection` is the seller's safe default decider. `rl` is opt-in — keep
it out of the list unless torch is installed and the model file exists;
the `/api/v1/system/status` `negotiation_strategy` check will catch a
broken `rl` setup at startup.

## Storefront: fulfillment failure policy

Provisioning failure and external fulfillment failure callbacks run the
same storefront-side failure policy. The default repairs inventory and
emits a stage event:

```toml
[fulfillment.failure_policy]
actions = ["release_capacity", "emit_event"]
webhook_url = ""
webhook_timeout = 5.0
```

Supported actions:

| Action | Behavior |
|---|---|
| `release_capacity` | Mark the held compute allocation released, refresh aggregate resource availability, and reopen any derived listings that are now publishable. |
| `emit_event` | Write a `stage_events` row with `stage="fulfillment"` and `event="failed"`; this is visible through `/api/v1/system/events` and its SSE stream. |
| `webhook` | POST the failure payload to `webhook_url`. Failures are logged and do not block the rest of the policy chain. |
| `refund` | Attempt the explicit seller refund path: send already-claimed assets back to the buyer. Token escrows dispatch through the selected escrow codec, covering native token, ERC-20, ERC-721, ERC-1155, and token-bundle escrows. Rows without a stored escrow proposal are skipped rather than deriving refund details from listing defaults. |

Actions run in order. For example, an operator that wants local repair,
alerting, and automatic refund can configure:

```toml
[fulfillment.failure_policy]
actions = ["release_capacity", "emit_event", "webhook", "refund"]
webhook_url = "https://alerts.example/internal/arkhai/fulfillment-failed"
```

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

## Buyer: negotiation policy

The buyer runs the **same middleware shape** as the seller — same
`(history, context) -> (Maybe<Response>, Context)` contract, same
`load_negotiation_chain()` registry. But the buyer's primary config
surface is one level up: a named **buyer policy** (a `BuyerPolicy`
object) that bundles the middleware chain with everything around it —
which escrow formats it can negotiate (escrow tuple selection offers
the policy only formats it claims), which pricing flags `buy` and
`negotiate` expose, and how omitted flags are derived from the listing.
The policy, not the verb, owns the pricing vocabulary: `--initial-price`
/ `--max-price` / `--price-markup` are the scalar policies' flags, and a
policy with no scalar notion would surface different ones (or none).

### Config

```toml
[negotiation]
# The named buyer policy. Default "listed_price".
# policy = "listed_price"

# Explicit chain override — bypasses the policy's middleware list but
# keeps the policy's CLI/derivation surface:
# policies = ["buyer_escrow_shape_guard", "bisection"]

# Legacy back-compat key (synthesized into
# `["buyer_escrow_shape_guard", <policy_mode>]` when `policies` is absent):
# policy_mode = "bisection"
```

With only `policy` set (or nothing), the chain is
`["buyer_escrow_shape_guard", *policy.middlewares]`. An unknown `policy`
name is an error — it never silently becomes the default. Per-verb
overrides without a named flag go through the escape hatch
`--policy-param name=value` (repeatable; values reach the chain's
context verbatim).

### Bundled buyer policies

| Name | Behavior |
|---|---|
| `listed_price` *(default)* | Opens at the listing's advertised price and accepts anything at or under the buyer's bound; never counters. When flags are omitted, derives initial = max = the advertised rate (interactively confirmed under `buy`, where the user is approving the aggregation policy's pick; `--yes` or no TTY skips the prompt). `--price-markup` applies only when `--initial-price` alone is given. |
| `bisection` | Haggles: opens below the ceiling (markup headroom) and bisects toward agreement. Opt-in — haggling rounds carry no information until proposals carry reasons for a new number. |

Both scalar policies declare compatibility with scalar-`amount` escrow
shapes (ERC20, native-token, ERC1155-style); a listing offering only
exact-match formats is refused with "no compatible escrow format"
rather than negotiated blindly.

The run-log records the policy name and parameters at run start, and
`--from <run_id>` resumes rebuild the chain under the recorded policy —
not whatever the config says today.

The buyer also supports the per-kind table form. It keeps
`buyer_escrow_shape_guard` first and dispatches the terminal by the
proposal's selected escrow kind:

```toml
[negotiation.policies]
erc20 = "erc20_bisection"
native_token = "native_token_bisection"
erc1155 = "erc1155_bisection"
default = "accept_exact_listing"
```

### Bundled middlewares usable on the buyer side

The same registry serves both sides — every middleware listed in the
seller's "Bundled policies" table above is importable in an explicit
`[negotiation] policies` chain here too. The ones that make sense
buyer-side:

| Name | Why on the buyer side |
|---|---|
| `buyer_escrow_shape_guard` | Rejects any seller counter that diverges from a buyer-pinned escrow field (token, arbiter, escrow contract, expiration). Default first entry. |
| `max_rounds_guard` | Same as seller — exits after `[negotiation].max_rounds`. |
| `listed_price` *(default decider)* | Accepts any seller number within the buyer's ceiling (`minimize` direction); exits otherwise. |
| `bisection` | Symmetric — bisects from the buyer's side (`minimize` direction). |
| `rl` | Symmetric — loads the buyer's trained checkpoint at `domains/vms/negotiation/rl/models/arkhai_negotiator_buyer.pt`. |
| `erc20_bisection`, `native_token_bisection`, `erc1155_bisection` | Symmetric aliases for the scalar-`amount` bisection decider. |
| `erc20_rl`, `native_token_rl`, `erc1155_rl` | Symmetric aliases for the scalar-`amount` RL decider. |
| `accept_exact_listing` | Useful for non-negotiated exact-match escrow kinds. |

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
from domains.vms.buyer.aggregation import (
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
from domains.vms.buyer.aggregation import (
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

- Seller settings schema: `domains/vms/storefront/src/market_storefront/settings.toml`.
- Buyer settings example: `domains/vms/buyer/config_cli.py` (the
  `init-user` template comment).
- Middleware module: `kit/policy/src/market_policy/negotiation_middleware.py`.
- Aggregation module: `domains/vms/buyer/aggregation.py`.
