## Why

Goal 8's MVP change `offer-per-period-vm-terms` lets a VM buyer find on-demand and
spot options through documented `--resource`/`--settlement` recipes over the
registry's existing lifecycle filters, which already correlate every predicate to one
option, and a local `arkhai_payments.period` settlement clause field. It takes reduced
forms of this change's tasks 1.2, 2.2 (its local half) and 2.3, and replaces 3.1's
shortcut with recipes.

Buyers still cannot filter by how long a seller's capacity lasts: the registry
carries `max_duration_seconds` but does not filter it, and no listing publishes the
calendar date `available_until_utc` that `negotiate-open-ended-compute-terms` adds.
They must also spell out class predicates by hand, in both compute buyer CLIs, and
the Alkahest registration exposes no public billing-kind or release projection to
tell its prepaid options apart. Listing-level policy copies would misrepresent
mixed-option listings.

## What Changes

- Add a typed lower-bound filter on `max_duration_seconds`, which the registry
  already carries, with the missing-value rule of design D1.
- Add the listing-level UTC availability field `available_until_utc` and its
  lower-bound filter, using the carrier policy `store-registry-listings-as-published`
  delivers.
- Add `--class reserved|on_demand|spot` to both compute buyer CLIs, compiled to the
  same typed predicates the MVP's recipes document over billing kind and entitlement,
  never a stored class, and conjoined with every explicit settlement alternative.
- Expose the Alkahest registration's public billing-kind and release-condition
  eligibility, so reserved excludes the prepaid interruptible splitter without
  inventing a common entitlement.

## Capabilities

### Modified Capabilities

- `registry-discovery`: bound carriers and filters with existing filter-spec authority.
- `cli-query-language`: correlated class expansion.
- `buyer-orchestration`: `--class` and deterministic explanation in both domains.
- `settlement-configuration`: the Alkahest billing and release projections class discovery reads.

### New Capabilities

None. The shared lifecycle codec, its projections and their registry pushdown are
`deal-lifecycle`'s and `cli-query-language`'s already.

## Non-Goals

- Defining terms, entitlements, setup fees, class display at approval or servicing:
  the terms, foundation and rate changes own these.
- The common lifecycle projections and their registry pushdown, which the archived
  foundation implemented, and the local `arkhai_payments.period` field and unit
  preservation, which `offer-per-period-vm-terms` owns.
- Registry pushdown of `arkhai_payments.period`: the period predicate stays local.
- A stored class, registry policy summary or another interruption codec.
- Owning registry opaque-payload migration ahead of its carrier dependency.
- Enabling a disabled mechanism, substituting an option after acceptance, or treating
  a legacy splitter as an enforceable hosted entitlement.

## Dependencies and Related Changes

- `offer-per-period-vm-terms`: the `arkhai_payments.period` field, its typed
  missing-period and billing-kind representation, derived class semantics, and the
  recipes `--class` compiles to.
- `negotiate-open-ended-compute-terms` (its task 2.2) and
  `store-registry-listings-as-published`: publication and the registry carrier of
  `available_until_utc`. Only that field waits for them; the `max_duration_seconds`
  filter, `--class` and the Alkahest projections do not.
- `publish-shape-bounds`: reverify its filter-spec edits before changing the same
  file. `drop-escrow-from-shared-wire`: coordinate its server clause pushdown when
  present; local evaluation remains authoritative for predicates not pushed.
- Discovery gates `activate-per-period-compute-servicing`, not dark term work.

## Impact

`core/registry/src/core_registry/filter-spec.yaml` and carrier/filter code,
`core/src/market_core/query_dsl.py`, buyer discovery/selection,
`kit/alkahest/src/market_alkahest/settlement_config.py` and both compute buyer CLIs.
No new listing-level lifecycle-policy copy or stored class is added.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Bound filter/carrier semantics and the missing-value rule: `registry-discovery` spec and architecture companion.
- Class expansion over every settlement alternative: `cli-query-language` spec.
- Alkahest billing and release projections: `settlement-configuration` spec.
- Class shortcut and explanation: `buyer-orchestration` spec/architecture companion.
- Repository-wide authority/namespace design stays foundation-owned; no additional
  architecture decision is introduced here.
