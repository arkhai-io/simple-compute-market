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
maximum duration (`pool_lease_bound_missing`); no option says how a deal is billed or
whether the seller may take it back; and the one interruption term,
`listing_resource.interruptible` with `settlement_model: splitter_refund`, is a
listing-level projection of the Alkahest splitter release model, set only from that
mechanism's configuration.

## What Changes

The commercial classes a buyer thinks in — reserved, on-demand, spot — are **derived,
never stored**, from two terms of the selected settlement option:

- **How the deal is billed** is a settlement term carried by the option's params. A
  payments option whose params state a billing `period` (and `reserve_ahead`) is billed
  per period until stopped; one without is prepaid, as today. What `Agreement.amount`
  is follows `negotiation-driven-capacity-resize`, which lands first — a basis-point
  multiplier where the offering carries a rate structure, an absolute amount where it
  does not — and the billing kind decides only what the quote is for: the whole term,
  or one period. One accessor in core derives the agreed price from the Agreement,
  the option, and the listing's rate structure and returns it with its unit, and a
  repository check refuses a read of `Agreement.amount` outside it. A per-period
  option may state a `minimum_spend`, a true minimum with a committed refund rule,
  published once the payments service can draw usage down against a prepaid part;
  until then no minimum is stated on VM, and bare metal's per-period options require
  one. The option params themselves are
  [`settle-ongoing-compute-through-arkhai-payments`](../settle-ongoing-compute-through-arkhai-payments/)'s;
  this change makes the rest of the system read them.
- **Whether the seller may interrupt** is a mechanism-neutral field of the settlement
  option beside `params`, `interruption`: `seller_may_interrupt`, `notice_seconds`,
  and `compensation` (`none` or `refund_unused`). It is present on every compute
  option, resolved as every term of sale is — storefront override, else pool hint,
  else the storefront's configured default, shipped as `{false, 0, none}`, the promise
  reserved deals carry today — covered by the option ID when present, and carried into
  the Agreement by the accepted option. It retires `listing_resource.interruptible`
  and `settlement_model`; an Alkahest splitter option carries the same object with
  `seller_may_interrupt` and `refund_unused`.

So reserved is a prepaid option with `seller_may_interrupt: false`, on-demand a
per-period option with `false`, spot a per-period option with `true`, and a prepaid
option with `true` is the Alkahest splitter model that exists today. Nothing stored can
disagree with anything.

The seller's bounds on a deal:

- `max_duration_seconds` keeps its meaning — the longest any one deal may run from its
  start.
- A new `available_until_utc` — when the seller stops offering the resource, the date
  a seller means by "I have this machine until March" — with the same three tiers. A
  reserved deal must also end by it, which nothing checks today. Both stay on the
  listing: they are facts about the capacity.
- `duration_seconds` keeps its shape: a reserved buyer asks for it; a per-period buyer
  usually names none, and it defaults to the distance from `start_utc` to the earliest
  seller bound. It is always finite and ≤ both bounds. A pool whose per-period candidate
  resolves no finite bound yields no per-period option, reported in the derivation
  log, while its reserved option publishes as today.

Publication: a pool offering reserved, on-demand, and spot capacity publishes one
listing with one option per combination, each at its own rate. A per-period option
publishes **and is accepted** only where the storefront's composition declares the
per-period continuation, and settlement materialization refuses a rate-part mandate
where it does not: three doors reading one declaration, never the listing, so a
buyer holding a cached option is refused rather than served without a continuation
behind it.

Seller policy: both domains' duration checks read both bounds; a per-period selection
with no buyer horizon is accepted at the seller's bound; the VM round-zero duration
fallback is retired here and its two resume fallbacks by
[`unify-compute-delivery-path`](../unify-compute-delivery-path/). Before approving a
per-period selection the buyer sees the recurring charge, the minimum spend and its
refund rule, the initial reserve, the maximum horizon, the policy, and the plain
statements of what billing begins at, what a started period costs, the bounded
residual, and how long the seller's record is kept.

Discovery — the registry filters, the buyer clause fields on the option's policy and
billing period, and `--class` — is
[`discover-open-ended-compute-listings`](../discover-open-ended-compute-listings/)',
so the registry's carrier policy gates the switch-on, not this change.

## Capabilities

### Modified Capabilities

Expected: `storefront-publication` (terms, tiers, the option per shape, the
held/closed rule for an unbounded per-period candidate, the three doors),
`negotiation-protocol` (the option field and its hash rule, the accessor, Agreement
semantics for a per-period selection, the acceptance gate), `resource-pool-management`
(the hints), `buyer-orchestration` (optional duration, the display). `.openspec.yaml`
sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Deriving or settling a `rate` part, snapshot verification, the `start`/`stop` calls:
  `settle-ongoing-compute-through-arkhai-payments`.
- Any lease-side change (`renew_by_utc`, the renewal-lapse policy):
  `renewable-compute-lease-deadlines`; the window derivation at commit:
  `unify-compute-delivery-path`.
- The seller's preemption route and spot's end-to-end evidence:
  `publish-and-preempt-spot-compute`. This change publishes the policy; that one acts
  on it.
- Discovery: `discover-open-ended-compute-listings`.
- A stored commercial class on the listing or the Agreement (rejected; `design.md`).
- A storefront deny list of payer accounts, the one identity with a cost behind it;
  unowned, recorded in the goal. Rate limits and principal blacklists are rejected for
  Goal 5's reasons.
- A permitted-cause list for seller interruption, or a buyer cancellation term.
- Extending a running lease when `available_until_utc` moves later: no lease
  extension operation exists, and the Agreement's horizon is fixed at acceptance.

## Dependencies and Related Changes

- Depends on nothing in this index. `negotiation-driven-capacity-resize` §2 is a
  design-time contract: its "Rate-multiplier negotiation" requirement is what the
  accessor builds on, and this change's design session re-verifies against §2 as
  landed.
- Reads the option params `settle-ongoing-compute-through-arkhai-payments` adds, whose
  shape that change's design session freezes first; this change freezes the accessor's
  unit contract before that change derives from it; the two are then worked in
  parallel and the index records no dependency.
- `drop-escrow-from-shared-wire` is the direction the retired listing fields were
  leaving in; this change retires them and adds nothing shared.
- `settle-capacity-claim-vocabulary` touches the provision-term carriers.

## Impact

`core/src/market_core/schemas.py` (the option field, the hash rule, the accessor),
a repository check in `scripts/`, both compute domains' listing and term models,
`kit/resource-pools-contracts`' hints, both storefronts' publication terms, pool
overrides, seller policies, and negotiation runtimes, `kit/alkahest`'s splitter
option, both buyer CLIs, and the listing-shape end-to-end scenarios. The listing wire
format gains an option field and the VM listing loses `interruptible` and
`settlement_model`; pre-1.0, no compatibility promise; options without the field keep
their IDs.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "One name per concept" gains the derived
  classes; "Authority boundaries" gains the interruption policy's row; "Omission
  states no commitment" gains the explicit-policy exception and why
- [x] Existing subsystem specification: `storefront-publication`,
  `negotiation-protocol`, `resource-pool-management`, `buyer-orchestration`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The commercial class is derived from the billing kind and the interruption policy,
  never stored — `ARCHITECTURE.md`, "One name per concept".
- `interruption` is a mechanism-neutral field of the settlement option, final at the
  storefront, with the site's physical right to withdraw a resource unconditional and
  separate — `ARCHITECTURE.md`, "Deciding which party is authoritative";
  `storefront-publication` architecture companion; `negotiation-protocol` spec.
- One accessor prices an Agreement and returns the unit; nothing reads `amount`
  directly — `negotiation-protocol` spec.
- A per-period option publishes, is accepted, and materializes only where the
  composition declares servicing — `storefront-publication`, `negotiation-protocol`,
  and `settlement-configuration` specs.
- The two seller bounds, their meanings, and how a per-period horizon defaults —
  `storefront-publication` spec and architecture companion.
- Why the policy is explicit on every option rather than omitted — `ARCHITECTURE.md`,
  "Omission states no commitment".
