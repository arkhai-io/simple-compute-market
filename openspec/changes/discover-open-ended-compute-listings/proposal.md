## Why

Once a listing can carry per-period options with an interruption policy and a date
the seller's offer ends
([`negotiate-open-ended-compute-terms`](../negotiate-open-ended-compute-terms/)), a
buyer still cannot find them. The registry (`core/registry/filter-spec.yaml`, compute
schema v2) stores `max_duration_seconds` but cannot filter on it, knows nothing of
`available_until_utc`, and does not index settlement-option fields at all; the publish
route persists an explicit carrier set — `listing_resource`, `accepted_escrows`,
`settlement_options`, `demands`, `max_duration_seconds`, `oracle_address` — and
discards any other top-level field, the defect `store-registry-listings-as-published`
owns. Both buyer CLIs can name a listing by ID and nothing else.

This is the discovery change of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)),
split from the terms change so that the registry's carrier policy gates the product's
switch-on rather than its terms: a dark product needs no filter.

## What Changes

- `available_until_utc` becomes a declared top-level registry field, carried on the
  model `store-registry-listings-as-published` produces, with a minimum-bound filter;
  `max_duration_seconds` gains the filter it lacks.
- The option's `interruption` and billing period are **buyer clause fields** —
  `interruption.seller_may_interrupt`, `interruption.notice_seconds`,
  `arkhai_payments.period` — evaluated locally after the registry query, as
  `arkhai_payments.window` is today. Where `drop-escrow-from-shared-wire`'s
  registry-side clause filtering has landed, the same fields are evaluated at the
  registry; this change names that as where server-side filtering on preemptibility
  arrives and adds no listing-level copy of the policy.
- `--class reserved|on_demand|spot` on both buyer CLIs is sugar expanding to the
  filters and clauses, never a listing term.
- `asking_rate.period` keeps `[hour]`; a per-period option's `rates` keep `per: hour`,
  and the billing `period` is the option's own param.

## Capabilities

### Modified Capabilities

Expected: `registry-discovery` (the field and filters), `cli-query-language` (the
clause fields), `buyer-orchestration` (`--class`). `.openspec.yaml` sets `skip_specs`
until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- The terms themselves: `negotiate-open-ended-compute-terms`.
- Registry-side filtering on option fields ahead of `drop-escrow-from-shared-wire`;
  a listing-level summary of the policy for indexing (rejected there as a second
  statement of one promise).

## Dependencies and Related Changes

- Depends on `negotiate-open-ended-compute-terms` (the terms exist) and on
  `store-registry-listings-as-published`, gating design: its carrier policy decides how
  `available_until_utc` is stored and served. That change depends on
  `add-database-migration-commands`, so both precede this one — and gate only the
  activation follow-on, not the build.
- `drop-escrow-from-shared-wire` is where registry-side clause filtering arrives;
  this change evaluates the clauses locally until then.
- `publish-shape-bounds` also touches the registry's filter spec; coordinate.

## Impact

`core/registry`'s filter spec, schema, and carrier model as its dependency leaves
it; `core/buyer`'s clause evaluation; both buyer CLIs; the discovery end-to-end
scenarios.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `registry-discovery`, `cli-query-language`,
  `buyer-orchestration`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The seller's bounds are registry fields; the option's policy and billing period
  are buyer clause fields; `--class` is sugar — `registry-discovery`,
  `cli-query-language`, and `buyer-orchestration` specs.
