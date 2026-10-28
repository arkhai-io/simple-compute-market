# Design

The decisions below were settled at goal level with the owner on 2026-10-28 for
[`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops),
and revised the same day against four rounds of independent design review of the
goal. This change's own design review may reopen any of them with a finding; its
design session verifies them against the code and adds the spec deltas.

## Context

Verified against the tree on 2026-10-28; re-verify before planning.

- `Agreement` (`core/src/market_core/schemas.py`) carries `amount`, `asset`,
  `duration_seconds` (`ge=0`), `start_utc`, the selected `settlement` option verbatim,
  `settlement_params`, `provision_terms`, `accepted_at`; no end or term field. The
  negotiation runtime resolves a relative start at acceptance. VM substitutes a
  listing maximum or 3600 for a missing duration in three places —
  `negotiation_runtime.py:244` at round zero, and
  `fulfillment_resume_runtime.py:95` and `:264` on resume; `VmTerms` and
  `BareMetalTerms` require `duration_seconds ≥ 1`.
- A settlement option is `{option_id, mechanism, asset, rates: [RateValue{field,
  per, value}], params}`, its ID the SHA-256 of the canonical payload of the last
  four, so the option is identity-bound and reaches the Agreement unchanged. The
  payments option params are `PaymentsOptionParams{payee_account, asset, window,
  deposit_agreement}` with `extra="forbid"`; the registration declares
  `negotiates_scalar_amount`. `compute_rate_total` prices `rate × duration` for
  `per: hour`, the only time unit `PER_UNIT_SECONDS` knows; the bare-metal buyer and
  seller call it directly.
- `negotiation-driven-capacity-resize` §2, in implementation: where an offering
  carries a resolvable rate structure, the negotiated scalar is a multiplier in basis
  points over the advertised minimum rate structure; the quote is
  `ceil(evaluate(rates, shape, duration) × bps / 10 000)`, derived by each side and
  not carried on the wire; the seller's floor is one bound on the multiplier; a quote
  that does not fit the asset's amount type is refused (its `negotiation-protocol`
  delta, "Rate-multiplier negotiation").
- VM: `VmListing.max_duration_seconds` (None = unlimited; `[pricing].default_max_duration_seconds = 0`),
  per-model and pool-override tiers; `listing_resource.interruptible = True` and
  `settlement_model: splitter_refund` set by the VM adapter
  (`domains/vms/domain/src/arkhai_vms/storefront_adapter.py`) from
  `[Settlement.alkahest].interruptible` — a listing-level projection of one
  mechanism's release model, the kind of shared field `drop-escrow-from-shared-wire`
  removes. Bare metal: `min_duration_seconds` and `max_duration_seconds`, with
  `positive_lease_bound` holding a pool that resolves no positive maximum
  (`pool_lease_bound_missing`). Bare metal declares only the `recipient` and
  `oracle_gated` release models, so the splitter never applies to it.
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
  commitment"); a storefront publishes only what its composition can settle and
  deliver (`storefront-publication`).
- Discovery of these terms is [`discover-open-ended-compute-listings`](../discover-open-ended-compute-listings/)',
  split out on the goal's fourth review round so the registry chain gates the
  switch-on rather than this change.

## Goals / Non-Goals

**Goals:** a seller can offer compute per period until stopped, with or without the
right to take it back, bounded by when their offer ends; a buyer can take it without
naming a horizon, see what it will cost, and tell the three classes apart; nothing
stored can contradict the terms it summarizes; a per-period deal is accepted only
where it can be serviced.

**Non-Goals:** settling a per-period deal; the lease machinery that keeps one alive;
acting on the interruption terms; a stored class; discovery.

## Decisions

### D1. No class field: reserved, on-demand, and spot are derived

The class is a projection of two independent terms of the selected option — its
billing kind and its `interruption.seller_may_interrupt`:

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

### D2. The billing kind is a settlement term; one accessor prices the Agreement

A per-period deal is one whose selected payments option states a `period` (and
`reserve_ahead`) in its params; the mandate derives a `rate` part with `until: stop`
from it, a `once` part otherwise (`settle-ongoing-compute-through-arkhai-payments`).
The Agreement is unchanged in shape.

What `Agreement.amount` *is* follows `negotiation-driven-capacity-resize` §2, which
lands first: a multiplier in basis points where the offering carries a resolvable
rate structure, an absolute amount where it does not. The billing kind decides only
what the quote is *for*: the whole term for a prepaid option, `duration` the
Agreement's; one period for a per-period option, `duration` the option's
`period_seconds`. Rounding is the resize change's upward rounding everywhere, so a
quote is never below what the multiplier promises the seller.

One accessor in core, `agreed_price(agreement, listing)`, derives the quote from the
Agreement, the selected option, and the listing's advertised rate structure, and
returns it **with its unit** — `total` or `per_period`. Every reader prices through
it: both domains' seller policies and reference amounts, VM's amount check, both
buyers' caps and display, the mandate derivation and the buyer's mandate check. A
repository check in `scripts/` refuses a read of `Agreement.amount` outside the
accessor and the kit's negotiation hooks, as the architecture check refuses a layer
edge, so a reader that has to know which of four readings applies never exists.
Worked, at an advertised 2,500,000 `USD/6` per hour, multiplier 10,000: a two-hour
prepaid deal quotes 5,000,000 `total`; a `PT1H` per-period option quotes 2,500,000
`per_period`; a `PT15M` one 625,000; a `PT1M` one 41,667 (rounded up). Scenarios: a
multi-hour prepaid deal, a sub-hour per-period one, recovery of an accepted prepaid
Agreement, and the check refusing a direct read. No Agreement field says "until
stopped"; an older reader would misread a per-period Agreement, and no such Agreement
exists until servicing is declared, which D9 ensures.

A per-period option may also state a `minimum_spend` — an amount, or a count of
periods at the rate — under which the buyer pays `max(minimum, usage)`: the
enforceable minimum cost of a lease, which a buyer's stop cannot recover, so repeated
provisioning costs the buyer the minimum each time — the principle Goal 5 records,
price the abused resource rather than limit identity, which is free to mint. Its
refund rule is a committed, buyer-visible term of the option: reversed when delivery
fails for the seller's reasons or the buyer stops before the create is dispatched,
kept after. A seller who wants no minimum states none and bears the churn. A true
minimum needs the payments service to draw usage down against a prepaid part, which
the published contract cannot express, so the term is published only once that
capability lands (`settle-ongoing-compute-through-arkhai-payments`); until then
per-period options state no minimum on VM, and bare metal publishes none (D13).

*Rejected:* a `once` part beside the `rate` part under a minimum's name — it is an
additional fee ($5.00 for the first hour at $2.50/h with one period stated), and an
honestly named `initial_fee` is a different product from the one buyers recognise.
*Rejected:* `amount` as an absolute hourly rate for per-period options, bypassing the
multiplier — a VM storefront would negotiate two quantities for two options on one
listing, the seller's floor would not apply to the per-period one, and the resize
change's requirement would be violated for the offerings it names. *Rejected:*
waiting for §2 to land before designing — the design as recorded would restate the
unit wrongly meanwhile. *Rejected:* an explicit rate carrier beside `amount`; an
additive `term` on the Agreement; `duration_seconds = 0` as the signal; a floored
derivation from an hourly `amount` (withdrawn, with the earlier claim that `amount`
is hourly today). *Rejected* for the churn vector: rate limiting and a principal
blacklist, for Goal 5's reasons. A storefront-side refusal of a *payer account* — a
payments-service account funded through Stripe, the one identity with a cost behind
it — is recorded as unowned rather than designed here.

### D3. `interruption` is a field of the settlement option, beside `params`

`SettlementOption` gains a mechanism-neutral field, `interruption`, next to `params`;
`params` stays the mechanism's own and each mechanism's params model keeps forbidding
what it does not define. The option ID covers it — two options differing only in
their policy must not share an ID, and the Agreement's identity binding must reach
the policy — so `derive_settlement_option_id` adds the field to its canonical payload
*only when present*: an option without a policy hashes exactly as it does today, so
API-credit and existing listings keep their IDs and nothing is rebuilt. The object is
part of the core option model, versioned with the listing wire like `rates`; it
carries no schema tag of its own.

One VM listing, three options, fixture values; the first is today's reserved deal,
the second on-demand, the third spot:

```json
{
  "listing_id": "lst_example",
  "listing_resource": {"resource_id": "pool-a/gpu-1x", "asking_rate": {"per": "hour", "value": "2500000"}},
  "max_duration_seconds": 2592000,
  "available_until_utc": "2026-12-31T00:00:00Z",
  "settlement_options": [
    {
      "option_id": "<sha256 of mechanism, asset, rates, params, interruption>",
      "mechanism": "arkhai.payments.v1",
      "asset": "USD/6",
      "rates": [{"field": "amount", "per": "hour", "value": "2500000"}],
      "params": {"payee_account": "acct_seller_example", "asset": "USD/6", "window": "PT15M"},
      "interruption": {"seller_may_interrupt": false, "notice_seconds": 0, "compensation": "refund_unused"}
    },
    {
      "option_id": "<sha256>",
      "mechanism": "arkhai.payments.v1",
      "asset": "USD/6",
      "rates": [{"field": "amount", "per": "hour", "value": "2500000"}],
      "params": {"payee_account": "acct_seller_example", "asset": "USD/6", "window": "PT15M", "period": "PT1H", "reserve_ahead": "PT2H"},
      "interruption": {"seller_may_interrupt": false, "notice_seconds": 0, "compensation": "none"}
    },
    {
      "option_id": "<sha256>",
      "mechanism": "arkhai.payments.v1",
      "asset": "USD/6",
      "rates": [{"field": "amount", "per": "hour", "value": "1200000"}],
      "params": {"payee_account": "acct_seller_example", "asset": "USD/6", "window": "PT15M", "period": "PT1H", "reserve_ahead": "PT2H"},
      "interruption": {"seller_may_interrupt": true, "notice_seconds": 120, "compensation": "none"}
    }
  ]
}
```

- `seller_may_interrupt` — the promise: whether the seller may end the deal at its
  discretion. It is not immunity from infrastructure: the site's physical right to
  withdraw a resource is unconditional, and a withdrawal of a deal whose policy says
  `false` is an exceptional end attributed to its cause and reconciled to its
  effective instant, with the remedy following this policy and the dispute authority.
  Nothing is non-preemptible by construction while the payee holds stop authority.
- `notice_seconds` — how long before teardown the buyer can observe the pending end;
  0 means none; the preemption route schedules the effective time from it. A pending
  end is observable through the deal's status; the design does not promise the buyer
  is told.
- `compensation` — `none`, or `refund_unused` for a prepaid term. For a per-period
  deal it is `none`, since billing stops at the effective time; a seller-caused end
  of a per-period deal additionally reverses the started period
  (`converge-ongoing-compute-leases` D5), which is the mechanism's rule rather than a
  value of this field.

Resolved through the three tiers every term of sale uses, keyed per option as the
option's own rate is; the storefront's configured default ships as `{false, 0,
none}`. The accepted option carries it into the Agreement verbatim, so the
preemption route and the mechanism judge `agreement.settlement.interruption` and
never the current listing. It retires `listing_resource.interruptible` and
`settlement_model`; an Alkahest splitter option carries the same object with
`seller_may_interrupt: true` and `compensation: refund_unused`, which is what the
splitter's oracle-declared split means, and a VM storefront configured for the
splitter whose policy does not state both holds the candidate, as an unreadable rate
holds a pool.

The authority follows `ARCHITECTURE.md`'s rule: the policy is a promise to the buyer
the site can neither see nor price, and nothing physical distinguishes a preemptible
lease from one that is not, so admission has nothing to enforce. The site keeps its
unconditional right to withdraw a resource (terminate, oversight, force-release),
which is not the seller interrupting but the resource being withdrawn; the policy
decides what that costs on the storefront side (`converge-ongoing-compute-leases`).

*Rejected:* a listing-level provision term in `provision_terms` with its own registry
columns — the policy's `compensation` means different things under a prepaid and a
per-period option, so a listing-level value has a meaning the option decides; a pool
offering reserved, on-demand, and spot capacity is one listing with three options,
not three listings; and the registry is being emptied of exactly this kind of shared
field. *Rejected:* a key inside each mechanism's `params` — it would make a
mechanism-neutral term each mechanism's to validate. *Rejected:* a listing-level
summary beside the option clause for registry indexing — two statements of one
promise. *Rejected:* a site-declared bound carried into admission. Revisit trigger: a
site serving a storefront it does not operate wants to forbid promises it cannot
honour (`ARCHITECTURE.md`, "Operators"). *Omitted deliberately:* a permitted-cause
list (a cause the site cannot verify is unenforceable, and maintenance is covered by
withdrawal); a buyer-side right (the buyer may always stop,
`buyer-initiated-compute-termination`); a buyer cancellation term.

### D4. The policy is present on every compute option

Under "Omission states no commitment", an absent policy would read as "the seller may
interrupt", silently flipping today's reserved listings, whose absent `interruptible`
means the interrupt route refuses them. So every compute option carries the policy it
resolved, and the shipped default keeps the promise reserved deals carry now.
Publication refuses a compute option without `interruption`, a per-period option
whose `compensation` is `refund_unused`, and an option with `notice_seconds` nonzero
and `seller_may_interrupt: false`. This is the one term of sale that is never
omitted, and the reason is recorded in `ARCHITECTURE.md` beside the omission rule.
API-credit options carry none, and hash as today.

### D5. Two seller bounds, with distinct meanings

`max_duration_seconds` (relative, existing): the longest any one deal may run from
its start. `available_until_utc` (absolute, new): the latest end of any lease the
listing sells — no lease sold under the listing ends after it, which implies no new
deal is taken after it. Both are pool hints with storefront override and configured
default, keyed per offering mode, and both stay on the listing: they are facts about
the capacity, not terms of an option. A reserved deal must satisfy both — `duration ≤
max_duration` as today and `start + duration ≤ available_until`, which nothing checks
today. A seller who later moves `available_until_utc` does not extend running leases:
the Agreement's horizon is fixed at acceptance and no lease extension operation
exists.

*Rejected:* one bound only. A relative bound is a real product (a maximum instance
lifetime), and a seller who means a date should not restate it as a shrinking
duration on every refresh; VM's "0 = unlimited" cannot bound a lease at all.
*Rejected:* a rename to a lease-end name, or a second "offer end" bound beside it —
nothing today needs the two to differ, and two bounds a seller must keep consistent
is the kind of term that disagrees with itself. Revisit trigger: a seller who stops
taking new deals before the hardware goes.

### D6. `duration_seconds` keeps its shape; a per-period horizon defaults to the seller's bound

For a per-period selection the buyer may name a horizon and usually names none, in
which case `duration_seconds` is the distance from `start_utc` to the earliest seller
bound: `start + max_duration_seconds` where positive, `available_until_utc` where
stated. It is always finite and ≤ both bounds. The site commits the Agreement's
window, `lease_end_utc = start_utc + duration`, in both domains — VM does today and
bare metal commits from `now`, which an absolute bound cannot tolerate; the one
delivery path [`unify-compute-delivery-path`](../unify-compute-delivery-path/) owns
the derivation. "Open-ended" is the commercial term, not the lease window. What the
buyer is promised is stated plainly on every surface: service continues until the
earliest of the buyer's stop, a permitted preemption, the funding lapsing, or this
bound — the buyer selects no end date, and buys no unconditional right to run.

### D7. An unbounded per-period candidate yields no option

A pool whose per-period candidate resolves no finite bound yields no per-period
option, reported in the site derivation log under its own reason, while its reserved
option publishes as today. By the hold-versus-close rule this is a close, not a hold:
every declaration reads, and the storefront can say what it would sell — a bounded
reserved term only. For VM this means a storefront whose configured default is
"unlimited" sells per period only from pools that state a bound: a seller opts into
open-ended selling by stating when it ends. Bare metal's existing hold of a pool with
no positive maximum stays as it is for reserved candidates.

### D8. One listing per pool; one option per billing kind and interruption shape

A pool offering reserved, on-demand, and spot capacity publishes one listing with one
option per combination it offers, each at its own rate, keyed in `asking_rates`-style
hints and overrides. Capacity is shared under site admission as every listing's is;
`listing_cardinality_mode` is untouched.

*Rejected:* one listing per shape, which D3's listing-level policy required and which
the per-option policy makes unnecessary.

### D9. A per-period option publishes, and is accepted, only where the composition can service it

The payments registration declares, as a capability like `negotiates_scalar_amount`,
whether the composition runs the per-period continuation and against which contract
(`settle-ongoing-compute-through-arkhai-payments` D10). Three doors read that one
declaration, never the listing, which may be stale:

1. **Publication.** A per-period option from a storefront that does not declare
   servicing is refused at publication as `no_settlement_option`, so no per-period
   option exists anywhere until the declaration is made, and the same configuration
   publishes the moment it is.
2. **Acceptance.** The seller's acceptance refuses a per-period selection when the
   composition does not declare servicing, with the refusal shape a withdrawn option
   gets, so a buyer holding a cached option learns to refetch. A storefront that
   stops declaring servicing stops publishing and accepting per-period options and
   keeps servicing its accepted per-period deals, as accepted deals already survive
   a mechanism being disabled.
3. **Materialization and startup.** Settlement materialization refuses to derive a
   rate-part mandate where servicing is undeclared, and a storefront holding
   accepted per-period deals refuses to start without the continuation composed
   (`converge-ongoing-compute-leases` D9).

The three are one invariant with two outcomes: a per-period selection is serviced,
or refused at the first door it reaches. One lane scenario per door.

*Rejected:* publication as the only gate — acceptance is where the seller commits,
and acceptance and materialization are separate requests with a possible restart
between them. *Rejected:* materialization as the only gate — an accepted Agreement
that can never be funded.

### D10. Discovery is `discover-open-ended-compute-listings`'

The registry filter on `available_until_utc` and `max_duration_seconds`, the buyer
clause fields on the option's `interruption` and `arkhai_payments.period`, and the
`--class` sugar are that change's; it depends on this one and on the registry's
carrier policy, and a dark product needs none of it. This change publishes the terms;
that one finds them.

### D11. Seller policy reads both bounds and accepts an unnamed horizon

Both domains' duration checks read both bounds. A per-period selection naming no
horizon is accepted at the seller's bound; one naming a horizon is checked against
both. VM's three substitutions of a listing maximum or 3600 for a missing duration
are retired: the round-zero one (`negotiation_runtime.py:244`) here, so a reserved
selection with no duration is refused as bare metal's is; the two on resume
(`fulfillment_resume_runtime.py:95`, `:264`) by `unify-compute-delivery-path`, whose
window comes from the Agreement.

### D12. What the buyer sees before approving

For a per-period selection both buyer CLIs show, as distinct numbers: the recurring
charge per period (D2), the minimum spend if any with its refund rule, the initial
reserve the service will hold (`reserve_ahead` at the rate), the maximum horizon
(D6), and the policy's three fields. With them, in plain words: billing begins at the
seller's `start` and the client records the delivery instant; the period in which a
buyer-caused end falls is charged in full, and a seller-caused end charges completed
periods only; a buyer may be charged for at most `reserve_ahead` past an end the
storefront did not observe; how long the seller's record of the deal is guaranteed
to be kept (`buyer-initiated-compute-termination` D4). For a reserved deal: the term
runs from the agreed start to the agreed end, settlement and provisioning time come
out of it, and a deal the site reclaims before delivery is refunded in full. The
hourly rate is shown as the listing states it.

*Recommendation for this change's session, not a goal decision:* a prorated refund of
provisioning time on prepaid deals — `activation − commit` over the term — would make
provisioning unbilled under both billing kinds; and prorating every per-period end,
buyer-caused included, by reverse would give the vast.ai-style bill the goal cites.
Both are commercial choices on reserved and buyer-caused ends respectively; the
service's prorated final period (welcome request) is the version of the second that
needs no local arithmetic.

### D13. Bare metal's per-period options require a minimum spend

Provisioning a host is unbilled and expensive, an order of magnitude beyond a VM's.
Bare metal's per-period options are refused at publication and at acceptance (D9)
without a `minimum_spend`, so bare-metal per-period waits on the service's minimum
while VM's does not; the roadmap's accepted churn risk applies to VM only. Revisit
trigger: a provisioning fact from the bare-metal domain that its provisioning is
cheap enough to treat as VM's.

*Rejected:* the same treatment for both domains — accepting the risk without pricing
it. *Rejected:* a storefront-local refusal of repeated selections from one buyer
identity — keyed on an identity the buyer can rotate for free; the deny list the goal
records as unowned.

## Open questions

- Where the per-period candidate dimension sits in the derivation key, so a listing
  keeps its identity across refreshes and reopens. Settled in design against
  `kit/capacity-publication`'s binding.
- The option-param shape (`period`, `reserve_ahead`, `minimum_spend`) is frozen in
  `settle-ongoing-compute-through-arkhai-payments`' design session before this one;
  this design reads it and does not restate it. The accessor's unit contract (D2) is
  frozen here before that change derives from it.

## Implementation cadence (recommended)

Two rounds. Round 1: the option field and its hash rule in core, the accessor and
the repository check, the terms through hints, overrides, defaults, and listing
models, publication with the servicing gate and the three refusals, the Alkahest flag
retired. Round 2: negotiation and the buyers — both seller policies with the
acceptance gate, the per-period horizon default, the optional duration flag, the
pre-approval display, and the listing-shape scenarios. One session per round.

## Permanent documentation destinations

| Decision | Destination |
|---|---|
| D1, D2 | `docs/development/ARCHITECTURE.md`, "One name per concept"; `negotiation-protocol` spec (the accessor beside "Rate-multiplier negotiation"); `settlement-servicing` spec (the per-period charge and the minimum) |
| D3 | `ARCHITECTURE.md`, "Authority boundaries" and "Deciding which party is authoritative"; `storefront-publication` spec and architecture companion; `negotiation-protocol` spec (the option field) |
| D4 | `ARCHITECTURE.md`, "Omission states no commitment" |
| D5, D6, D7 | `storefront-publication` spec and architecture companion; `resource-pool-management` spec |
| D8, D9, D13 | `storefront-publication` spec; `settlement-configuration` spec (the capability) |
| D11, D12 | `negotiation-protocol` spec; `buyer-orchestration` spec |
