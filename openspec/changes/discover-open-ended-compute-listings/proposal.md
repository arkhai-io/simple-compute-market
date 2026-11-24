## Why

`negotiate-open-ended-compute-terms` (archived) publishes reserved, on-demand and spot
options on compute listings that carry `max_duration_seconds` and
`available_until_utc`, and the Arkhai payments registration already exposes
`arkhai_payments.period`, `arkhai_payments.billing_kind` and
`arkhai_payments.approval_window` as local clause fields
(`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`).
`store-registry-listings-as-published` (archived) retains each signed listing as
published, nulls included.

Buyers still cannot filter by how long a seller's capacity lasts: the registry
carries `max_duration_seconds` but does not filter it, and its schema neither declares
nor filters `available_until_utc` (`core/registry/src/core_registry/filter-spec.yaml`).
No documentation shows how to find an on-demand or spot option, so buyers must
spell out class predicates by hand in both compute buyer CLIs, and the Alkahest
registration exposes no public billing-kind or release projection to tell its prepaid
options apart. Listing-level policy copies would misrepresent mixed-option listings.

## What Changes

- Add a typed lower-bound filter on `max_duration_seconds`, which the registry
  already carries, with the missing-value rule of design D1.
- Add the listing-level UTC availability field `available_until_utc` and its
  lower-bound filter, using the carrier policy `store-registry-listings-as-published`
  delivers.
- Document `--resource`/`--settlement` recipes for each class over the registered
  billing kind and the common entitlement projections, in the buyer quickstart.
- Add `--class reserved|on_demand|spot` to both compute buyer CLIs, compiled to the
  same typed predicates the recipes document, never a stored class, and conjoined with
  every explicit settlement alternative.
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
  foundation implemented, and the local `arkhai_payments.period` and
  `arkhai_payments.billing_kind` fields and unit preservation, which the archived
  `negotiate-open-ended-compute-terms` implemented; this change confirms them (tasks
  1.2, 2.2, 2.3).
- Registry pushdown of `arkhai_payments.period`: the period predicate stays local.
- A stored class, registry policy summary or another interruption codec.
- Owning registry opaque-payload migration ahead of its carrier dependency.
- Enabling a disabled mechanism, substituting an option after acceptance, or treating
  a legacy splitter as an enforceable hosted entitlement.

## Dependencies and Related Changes

- `negotiate-open-ended-compute-terms` and `store-registry-listings-as-published`, both
  archived: the published bounds, the payments registration's clause fields and the
  as-published registry carrier. Nothing open gates this change.
- `publish-shape-bounds`: reverify its filter-spec edits before changing the same
  file. `drop-escrow-from-shared-wire`: coordinate its server clause pushdown when
  present; local evaluation remains authoritative for predicates not pushed.
- Not one of Goal 8's MVP changes, which find options without `--class`. Discovery gates
  `activate-per-period-compute-servicing`, not dark term work.

## Impact

`core/registry/src/core_registry/filter-spec.yaml` and carrier/filter code,
`core/src/market_core/query_dsl.py`, buyer discovery/selection,
`kit/alkahest/src/market_alkahest/settlement_config.py`, both compute buyer CLIs and
`docs/buyer-quickstart.md`.
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
- Class recipes: `docs/buyer-quickstart.md`.
- Repository-wide authority/namespace design stays foundation-owned; no additional
  architecture decision is introduced here.
