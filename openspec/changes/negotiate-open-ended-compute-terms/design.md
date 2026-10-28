# Design

The decisions below were settled with the owner in the goal-level design of
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)
on 2026-10-28, across the goal's five changes. This change's own design session
verifies them against the code and adds the spec deltas; it does not reopen them
without a finding.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `Agreement` (`core/src/market_core/schemas.py`) carries `amount`, `asset`,
  `duration_seconds` (`ge=0`), `start_utc`, the selected `settlement` option,
  `settlement_params`, `provision_terms`, `accepted_at`; no end or term field. The
  negotiation runtime resolves a relative start at acceptance; VM's `_agreement`
  substitutes the listing's `max_duration_seconds`, else 3600, for a missing
  duration; `VmTerms` and `BareMetalTerms` require `duration_seconds ≥ 1`.
- A settlement option is `{option_id, mechanism, asset, rates: [RateValue{field,
  per, value}], params}`, its ID the hash of those four. The payments option params
  are `PaymentsOptionParams{payee_account, asset, window, deposit_agreement}`; the
  registration declares `negotiates_scalar_amount`. `compute_rate_total` prices
  `rate × duration` for `per: hour`, the only time unit `PER_UNIT_SECONDS` knows.
- VM: `VmListing.max_duration_seconds` (None = unlimited; `[pricing].default_max_duration_seconds = 0`),
  per-model and pool-override tiers; `listing_resource.interruptible` and
  `settlement_model: splitter_refund` set by `publication_terms` from
  `[Settlement.alkahest].interruptible`. Bare metal: `min_duration_seconds` and
  `max_duration_seconds`, with `positive_lease_bound` holding a pool that resolves no
  positive maximum (`pool_lease_bound_missing`). Bare metal declares only the
  `recipient` and `oracle_gated` release models, so the splitter never applies to it.
- The registry (`core/registry/filter-spec.yaml`, compute schema v2) declares
  `offering_mode`, `capacity_backing`, the shape dimensions, `asking_rate{amount,
  asset, period ∈ [hour]}`, and top-level `max_duration_seconds` (stored, no filter);
  `interruptible` passes through `additionalProperties`. Settlement-option params are
  not indexed; buyer clauses evaluate them locally after the query.
- Pool hints are `listing_cardinality_mode`, `max_reservation_hold_seconds`,
  `region`, `sla`, `pricing`, `listing_shapes`, `asking_rates`; VM pool override
  terms are `sla`, `max_duration_seconds`, `pricing`; bare metal's are
  `min_duration_seconds`, `max_duration_seconds`.
- Seller policy: VM rejects `duration ≤ 0` and above the listing maximum; bare
  metal rejects below the minimum and above the maximum. Neither checks an absolute
  bound.
- Authority: the site never sees commercial terms, and a rule it declares but does
  not enforce at admission is advisory (`ARCHITECTURE.md`, "Deciding which party is
  authoritative"); an omitted term states no commitment ("Omission states no
  commitment").

## Goals / Non-Goals

**Goals:** a seller can offer compute per period until stopped, with or without the
right to take it back, bounded by when their offer ends; a buyer can find it, take it
without naming a horizon, and tell the three classes apart; nothing stored can
contradict the terms it summarizes.

**Non-Goals:** settling a per-period deal; the lease machinery that keeps one alive;
acting on the interruption policy; a stored class.

## Decisions

### D1. No class field: reserved, on-demand, and spot are derived

The class is a projection of two independent terms — the selected option's billing
kind and the listing's `interruption_policy.seller_may_interrupt`:

| Billing | `seller_may_interrupt` | Class |
|---|---|---|
| prepaid (`once`) | false | reserved |
| per period | false | on-demand |
| per period | true | spot |
| prepaid (`once`) | true | the Alkahest splitter model, as today |

The fourth row is not an error; it is a prepaid term the seller may cut with a refund
of the unused part, which exists. The class appears only in the buyer's `--class`
sugar and in prose.

*Rejected:* a stored `service_class` on the listing and Agreement. It could disagree
with the terms it summarizes, every reader would then need reconciliation handling,
and its only real use — filtering — is served by filters on the terms themselves.
Revisit trigger: a product needs a class no combination of the two terms expresses.

### D2. The billing kind is a settlement term; "until stopped" needs no term of its own

A per-period deal is one whose selected payments option states a `period` (and
`reserve_ahead`) in its params; the mandate derives a `rate` part with `until: stop`
from it, a `once` part otherwise (`settle-ongoing-compute-through-arkhai-payments`).
The Agreement is unchanged in shape: `amount` is the per-period rate for such an
option, and VM's `selected_amount_not_duration_scaled` check does not apply because
payments builds no obligation. No Agreement field says "until stopped".

*Rejected:* an additive `term: fixed | until_stopped` on the Agreement — redundant
with the option, and a second place to disagree. *Rejected:* `duration_seconds = 0`
as the signal — VM substitutes a duration today, so 0 is indistinguishable from an
omission.

### D3. `interruption_policy` is a listing term of sale, final at the storefront

Shape, versioned like other provision terms:

```json
{"interruption_policy": {"seller_may_interrupt": true, "notice_seconds": 120, "compensation": "none"}}
```

- `seller_may_interrupt` — the promise itself.
- `notice_seconds` — how long before teardown the buyer is told; 0 means none; the
  preemption route schedules the effective time from it.
- `compensation` — `none`, or `refund_unused` for a prepaid term. For a per-period
  deal it is `none`, since billing stops at the effective time.

Resolved through the three tiers every term of sale uses, keyed per offering mode as
`asking_rates` is; the storefront's configured default ships as
`{false, 0, none}`. It reaches the Agreement in `provision_terms`, so the preemption
route and the mechanism judge the accepted deal and never the current listing. It
retires `listing_resource.interruptible` and `settlement_model`; an Alkahest splitter
clause requires a resolved policy with `seller_may_interrupt` and `refund_unused`, and
a VM storefront configured for the splitter whose policy does not state both holds
the candidate, as an unreadable rate holds a pool.

The authority follows `ARCHITECTURE.md`'s rule: the policy is a promise to the buyer
the site can neither see nor price, and nothing physical distinguishes a preemptible
lease from one that is not, so admission has nothing to enforce. The site keeps its
unconditional right to withdraw a resource (terminate, oversight, force-release),
which is not the seller interrupting but the resource being withdrawn; the policy
decides what that costs on the storefront side (`converge-ongoing-compute-leases`).

*Rejected:* a site-declared bound carried into admission. Revisit trigger: a site
serving a storefront it does not operate wants to forbid promises it cannot honour
(`ARCHITECTURE.md`, "Operators"). *Omitted deliberately:* a permitted-cause list (a
cause the site cannot verify is unenforceable, and maintenance is covered by
withdrawal); a buyer-side right (the buyer may always stop,
`buyer-initiated-compute-termination`); a buyer cancellation term.

### D4. The policy is published explicitly on every compute listing

Under "Omission states no commitment", an absent policy would read as "the seller may
interrupt", silently flipping today's reserved listings, whose absent `interruptible`
means the interrupt route refuses them. So every compute listing publishes the policy
it resolved, and the shipped default keeps the promise reserved deals carry now. This
is the one term of sale that is never omitted, and the reason is recorded in
`ARCHITECTURE.md` beside the omission rule.

### D5. Two seller bounds, with distinct meanings

`max_duration_seconds` (relative, existing): the longest any one deal may run from
its start. `available_until_utc` (absolute, new): when the seller stops offering the
resource. Both are pool hints with storefront override and configured default, keyed
per offering mode. A reserved deal must satisfy both — `duration ≤ max_duration` as
today and `start + duration ≤ available_until`, which nothing checks today. A seller
who later moves `available_until_utc` does not extend running leases: the Agreement's
horizon is fixed at acceptance and no lease extension operation exists.

*Rejected:* one bound only. A relative bound is a real product (a maximum instance
lifetime), and a seller who means a date should not restate it as a shrinking
duration on every refresh; VM's "0 = unlimited" cannot bound a lease at all.

### D6. `duration_seconds` keeps its shape; a per-period horizon defaults to the seller's bound

For a per-period selection the buyer may name a horizon and usually names none, in
which case `duration_seconds` is the distance from `start_utc` to the earliest seller
bound: `start + max_duration_seconds` where positive, `available_until_utc` where
stated. It is always finite and ≤ both bounds. The site commits `lease_end_utc =
start + duration` exactly as today; "open-ended" is the commercial term, not the lease
window. The Agreement carries one horizon in one representation, and nothing new.

### D7. An unbounded per-period candidate yields no listing

A pool whose per-period candidate resolves no finite bound yields no per-period
listing, reported in the site derivation log under its own reason, while its reserved
candidate publishes as today. By the hold-versus-close rule this is a close, not a
hold: every declaration reads, and the storefront can say what it would sell — a
bounded reserved term only. For VM this means a storefront whose configured default is
"unlimited" sells per period only from pools that state a bound: a seller opts into
open-ended selling by stating when it ends. Bare metal's existing hold of a pool with
no positive maximum stays as it is for reserved candidates.

### D8. One listing per billing kind and interruption shape a pool offers

A per-period option is a candidate dimension beside offering mode: a pool offering
spot and on-demand publishes two listings, each with its own asking rate and policy,
keyed in `listing_shapes`-style hints and overrides. Capacity is shared under site
admission as every listing's is. `listing_cardinality_mode` keeps governing
cardinality only.

### D9. Discovery: registry filters on the listing terms, a local clause on the billing kind

`interruption_policy` and `available_until_utc` become declared top-level registry
fields with filters: `in` on `seller_may_interrupt`, minimum bounds on
`notice_seconds`, `available_until_utc`, and `max_duration_seconds`. The billing
kind lives inside the mechanism's option params, which the registry does not index,
so it is a buyer settlement clause field, `arkhai_payments.period`, evaluated locally
after the registry query as `arkhai_payments.window` is. `--class` on both buyer CLIs
expands to the registry filter plus the local clause and is never a listing term.
`asking_rate.period` keeps `[hour]`; a per-period option's `rates` keep `per: hour`,
and the billing `period` is the option's own param.

### D10. Seller policy reads both bounds and accepts an unnamed horizon

Both domains' duration checks read both bounds. A per-period selection naming no
horizon is accepted at the seller's bound; one naming a horizon is checked against
both. VM's round-zero substitution of a listing maximum or 3600 for a missing
duration is retired: a reserved selection with no duration is refused, as bare
metal's is.

## Open questions

- Whether `interruption_policy` is keyed per offering mode only, or per listing shape
  as `asking_rates` is, when one pool sells several shapes with different policies.
  Settled in design with a concrete hint document; revisit trigger: a seller wants
  different policies per shape.
- Where the per-period candidate dimension sits in the derivation key, so a listing
  keeps its identity across refreshes and reopens. Settled in design against
  `kit/capacity-publication`'s binding.

## Implementation cadence (recommended)

Two rounds. Round 1: the terms — the policy and `available_until_utc` through hints,
overrides, defaults, listing models, publication, and the registry schema and
filters, with the Alkahest flag retired. Round 2: negotiation and the buyers — both
seller policies, the per-period horizon default, `--class`, the optional duration
flag, and the discovery and listing-shape scenarios. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `docs/development/ARCHITECTURE.md`, "One name per concept"; `negotiation-protocol` spec |
| D3 | `ARCHITECTURE.md`, "Authority boundaries" and "Deciding which party is authoritative"; `storefront-publication` spec and architecture companion |
| D4 | `ARCHITECTURE.md`, "Omission states no commitment" |
| D5, D6, D7 | `storefront-publication` spec and architecture companion; `resource-pool-management` spec |
| D8 | `storefront-publication` spec |
| D9 | `registry-discovery` spec; `cli-query-language` spec; `buyer-orchestration` spec |
| D10 | `negotiation-protocol` spec |
