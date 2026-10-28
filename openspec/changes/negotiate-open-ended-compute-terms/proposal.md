## Why

Every compute deal is a reserved term: the buyer names a duration, the amount is
`rate × duration`, and the lease ends at `start + duration`. `Agreement.duration_seconds`
is required at every layer (`core/src/market_core/schemas.py`, `VmTerms`,
`BareMetalTerms`, pricing, the payments mandate, Alkahest plans); `market vms buy`
refuses a fresh run without `--duration-hours`, and the VM storefront substitutes the
listing maximum or an hour when a duration is missing. A buyer who wants the compute
now and for as long as they want it — the on-demand product — or as cheaply as possible
on the understanding the seller may take it back — spot — cannot be served, and those
two are the bulk of compute demand outside committed offtake.

Nothing in the listing can express either. Bare metal holds any pool without a positive
maximum duration (`pool_lease_bound_missing`); the registry stores
`max_duration_seconds` but cannot filter on it and knows nothing of interruptibility,
billing period, or when the seller's offer ends; and the one interruption term,
`listing_resource.interruptible` with `settlement_model: splitter_refund`, is set only
from the Alkahest splitter release model and passes through the registry as an
undeclared field.

## What Changes

The commercial classes a buyer thinks in — reserved, on-demand, spot — are **derived,
never stored**, from two terms that have homes of their own:

- **How the deal is billed** is a settlement term carried by the selected option. A
  payments option whose params state a billing `period` (and `reserve_ahead`) is billed
  per period until stopped; one without is prepaid, as today. The Agreement's `amount`
  keeps its unit — the option's hourly rate, for both kinds — and the per-period charge
  is derived from it once, in the mandate, by exact floored arithmetic both sides
  re-derive. A per-period option may state a `minimum_spend`, a true minimum with a
  committed refund rule, published once the payments service can draw usage down
  against a prepaid part; until then no minimum is stated. The option params
  themselves are
  [`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)'s;
  this change makes the rest of the system read them.
- **Whether the seller may interrupt** is a listing term, `interruption_policy`:
  `seller_may_interrupt`, `notice_seconds`, and `compensation` (`none` or
  `refund_unused`). It is published explicitly on every compute listing, resolved as
  every term of sale is — storefront override, else pool hint, else the storefront's
  configured default, shipped as `{false, 0, none}`, the promise reserved deals carry
  today — and reaches the Agreement through `provision_terms`. It retires
  `listing_resource.interruptible` and `settlement_model`; an Alkahest splitter clause
  requires a policy stating `seller_may_interrupt` with `refund_unused`.

So reserved is a prepaid option with `seller_may_interrupt: false`, on-demand a
per-period option with `false`, spot a per-period option with `true`, and a prepaid
option with `true` is the Alkahest splitter model that exists today. Nothing stored can
disagree with anything.

The seller's bounds on a deal:

- `max_duration_seconds` keeps its meaning — the longest any one deal may run from its
  start — and gains a registry filter.
- A new `available_until_utc` — when the seller stops offering the resource, the date
  a seller means by "I have this machine until March" — with the same three tiers and a
  registry filter. A reserved deal must also end by it, which nothing checks today.
- `duration_seconds` keeps its shape: a reserved buyer asks for it; a per-period buyer
  usually names none, and it defaults to the distance from `start_utc` to the earliest
  seller bound. It is always finite and ≤ both bounds. A pool whose per-period candidate
  resolves no finite bound yields no per-period listing, reported in the derivation
  log, while its reserved candidate publishes as today.

Publication: a per-period option is a candidate dimension beside offering mode, so a
pool offering both spot and on-demand publishes one listing per interruption shape and
billing kind it offers, each with its own asking rate, keyed in pool hints and
overrides as `listing_shapes` and `asking_rates` are keyed today.

Discovery: `interruption_policy` and `available_until_utc` become declared registry
fields with filters (`in` on `seller_may_interrupt`, minimum bounds on `notice_seconds`
and `available_until_utc`, and on `max_duration_seconds`), carried on the model
`store-registry-listings-as-published` produces — the registry today discards any
top-level field outside its fixed carrier set, so this change depends on that one; the
billing kind stays a buyer-side settlement clause (`arkhai_payments.period`) evaluated
locally after the registry query, as `arkhai_payments.window` is. A
`--class reserved|on_demand|spot` on both buyer CLIs is sugar expanding to the registry
filter plus the local clause; the buyer's duration flag becomes optional, and before
approving a per-period selection the buyer sees the recurring charge, the minimum
spend and its refund rule, the initial reserve, and the maximum horizon as distinct
numbers.

Publication: a per-period option publishes only where the storefront's composition
declares the per-period continuation, so no per-period listing exists until
[`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/) composes it.

Seller policy: both domains' duration checks read both bounds; a per-period selection
with no buyer horizon is accepted at the seller's bound; the VM round-zero duration
fallback is retired.

## Capabilities

### Modified Capabilities

Expected: `storefront-publication` (terms, tiers, candidate dimension, the held/closed
rule for an unbounded per-period candidate), `negotiation-protocol` (Agreement
semantics for a per-period selection), `registry-discovery` (fields and filters),
`resource-pool-management` (the hints), `buyer-orchestration` (`--class`, optional
duration), `cli-query-language` (the clause field). `.openspec.yaml` sets `skip_specs`
until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Deriving or settling a `rate` part, snapshot verification, the `start`/`stop` calls:
  `settle-ongoing-compute-through-arkhai-payments`.
- Any lease-side change (`renew_by_utc`, the renewal-lapse policy):
  `converge-ongoing-compute-leases`.
- The seller's preemption route and spot's end-to-end evidence:
  `publish-and-preempt-spot-compute`. This change publishes the policy; that one acts
  on it.
- A stored commercial class on the listing or the Agreement (rejected; `design.md`).
- A storefront deny list of payer accounts, the one identity with a cost behind it;
  unowned, recorded in the goal. Rate limits and principal blacklists are rejected for
  Goal 5's reasons.
- A permitted-cause list for seller interruption, or a buyer cancellation term.
- Extending a running lease when `available_until_utc` moves later: no lease
  extension operation exists, and the Agreement's horizon is fixed at acceptance.

## Dependencies and Related Changes

- Depends on `store-registry-listings-as-published`, gating design: its carrier policy
  decides how this change's two registry fields are stored and served. That change
  depends on `add-database-migration-commands`, so both precede this one.
- Reads the option params `settle-ongoing-compute-through-arkhai-payments` adds, whose
  shape that change's design session freezes first; the two are then worked in
  parallel and the index records no dependency.
- `publish-shape-bounds` also touches the registry's filter spec; coordinate.
- `settle-capacity-claim-vocabulary` touches the provision-term carriers.

## Impact

`core/registry`'s filter spec, schema, and carrier model as its dependency leaves it, `core/src/market_core/schemas.py` only if the
Agreement needs to carry anything new (expected: nothing), both compute domains'
listing and term models, `kit/resource-pools-contracts`' hints, both storefronts'
publication terms, pool overrides, seller policies, and negotiation runtimes,
`kit/alkahest`'s splitter clause requirement, both buyer CLIs, and the listing-shape
and discovery end-to-end scenarios. The registry wire format gains fields and the VM
listing loses `interruptible` and `settlement_model`; pre-1.0, no compatibility
promise.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "One name per concept" gains the derived
  classes; "Authority boundaries" gains the interruption policy's row; "Omission
  states no commitment" gains the explicit-policy exception and why
- [x] Existing subsystem specification: `storefront-publication`,
  `negotiation-protocol`, `registry-discovery`, `resource-pool-management`,
  `buyer-orchestration`, `cli-query-language`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The commercial class is derived from the billing kind and the interruption policy,
  never stored — `ARCHITECTURE.md`, "One name per concept".
- `interruption_policy` is a storefront term of sale, final at the storefront, with
  the site's physical right to withdraw a resource unconditional and separate —
  `ARCHITECTURE.md`, "Deciding which party is authoritative"; `storefront-publication`
  architecture companion.
- `amount` keeps its hourly unit; the per-period charge is derived once in the
  mandate, and a minimum spend is a true minimum with a committed refund rule —
  `settlement-servicing` spec.
- A per-period option publishes only where the composition declares servicing —
  `storefront-publication` and `settlement-configuration` specs.
- The two seller bounds, their meanings, and how a per-period horizon defaults —
  `storefront-publication` spec and architecture companion.
- Why the policy is explicit on every listing rather than omitted — `ARCHITECTURE.md`,
  "Omission states no commitment".
