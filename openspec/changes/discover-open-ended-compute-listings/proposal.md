## Why

Compute buyers need to discover the recurring and seller-stoppable options published
by `negotiate-open-ended-compute-terms`, distinguish their price/notice tradeoffs,
and find capacity available through a required date. Current registry carriers and
filters do not expose both seller bounds, and existing buyer CLIs have no class
shortcut. Listing-level policy copies would misrepresent mixed-option listings.

## What Changes

- Add the listing-level UTC availability field and lower-bound filters on
  `available_until_utc` and `max_duration_seconds`, using the carrier policy delivered
  by `store-registry-listings-as-published`.
- Consume the foundation codec's common option projections:
  `early_termination.payer`, `early_termination.payee`,
  `early_termination.payee.notice_seconds`, `adjudication.dispute.interface` and
  `adjudication.dispute.account`. Do not add `interruption.*` or mechanism-owned
  aliases for these fields.
- Keep billing period under the rate registration's namespace,
  `arkhai_payments.period`; approval expiry is `arkhai_payments.approval_window`,
  not the old window name or a dispute-hold duration.
- Add `--class reserved|on_demand|spot` to both compute buyer CLIs as explained
  predicates over billing kind and entitlement, never a stored class. Correlate all
  predicates against the same option, locally and in any registry pushdown.
- Preserve asking-rate/option-rate units; do not silently normalize them to the
  billing period. A period-sized charge is derived by the agreed-price accessor.

## Capabilities

### Modified Capabilities

- `registry-discovery`: bound carriers and filters with existing filter-spec authority.
- `cli-query-language`: common/registered projection use and correlated class expansion.
- `buyer-orchestration`: `--class` and deterministic explanation in both domains.

### New Capabilities

None. The shared lifecycle codec/projections are owned by the foundation change.

## Non-Goals

- Defining terms, entitlements, setup fees, class display at approval or servicing:
  the terms/foundation/rate changes own these.
- A stored class, registry policy summary or another interruption codec.
- Owning registry opaque-payload migration ahead of its carrier dependency.
- Requiring server filtering before a locally filterable product can be developed.
- Enabling a disabled mechanism, substituting an option after acceptance, or treating
  a legacy splitter as an enforceable hosted entitlement.

## Dependencies and gates

- `agreed-evidence-and-early-termination`: shared projections, exact authority identity
  checks and clause correlation. Consume them, do not implement a second evaluator.
- `negotiate-open-ended-compute-terms`: bound/class semantics and final option shape.
- `store-registry-listings-as-published`, transitively
  `add-database-migration-commands`: carrier policy gates registry implementation.
- `drop-escrow-from-shared-wire`: coordinate its server clause pushdown when present;
  local evaluation remains authoritative for predicates not pushed. Reverify
  `publish-shape-bounds`'s filter-spec edits before changing the same file.
- Freeze the rate registration's period/billing-kind projection before class wiring.
  Discovery gates `activate-per-period-compute-servicing`, not dark term work.

## Impact

`core/registry/filter-spec.yaml` and carrier/filter code, `core/src/market_core/query_dsl.py`,
buyer discovery/selection, `kit/settlement-runtime` projections and both compute
buyer CLIs. No new listing-level lifecycle-policy copy or stored class is added.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Bound filter/carrier semantics: `registry-discovery` spec and architecture companion.
- Correlated use of common term fields and period predicates: `cli-query-language`
  spec and the existing settlement configuration contract.
- Class shortcut and explanation: `buyer-orchestration` spec/architecture companion.
- Repository-wide authority/namespace design stays foundation-owned; no additional
  architecture decision is introduced here.
