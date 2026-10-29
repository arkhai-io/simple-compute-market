# Tasks — discover open-ended compute listings

Design-stage plan, not implementation evidence. Use verification jurisdictions in
`docs/development/TESTING.md`; new acceptance test implementation requires maintainer
approval. No tests are added by this reconciliation.

## 1. Reverify dependency contracts

- [ ] 1.1 Consume `agreed-evidence-and-early-termination`'s common projections and
  exact-option correlation in `core/src/market_core/query_dsl.py` and
  `kit/settlement-runtime`. Reverify false/missing/malformed behavior without forking
  the codec.
- [ ] 1.2 Consume `negotiate-open-ended-compute-terms`'s bound/class semantics and the
  rate registration's `period` projection. Decide and record D3's typed billing-kind/
  missing-period representation with the registration and DSL before class work;
  any needed public grammar change is explicit and validated first. Preserve the
  existing Alkahest splitter exclusion without inventing stop entitlements.
- [ ] 1.3 Reverify the landed carrier from `store-registry-listings-as-published`
  (after `add-database-migration-commands`), the filter-spec edits of
  `publish-shape-bounds`, and `drop-escrow-from-shared-wire`'s pushdown state. Record
  local versus server predicate ownership before registry implementation.

## 2. Bound filters and correlated option discovery

- [ ] 2.1 In `core/registry/filter-spec.yaml` and its carrier/filter code, declare UTC
  availability and lower-bound filters for both capacity bounds. Preserve ETag
  preconditions and the dependency's opaque carrier policy. Unit targets:
  `core/registry/tests/unit/test_filter_spec.py`, `test_filter_eval.py`; app-integration
  targets: `core/registry/tests/integration/test_filter_spec.py`, `test_listings_filtering.py`
  and `test_listings.py`. Prove UTC instant comparison, missing/unlimited semantics
  and round-trip publication using the canonical typed registry client.
- [ ] 2.2 In buyer query/selection and registry pushdown where supported, consume
  common `early_termination.*`/`adjudication.*` fields and registered
  `arkhai_payments.period`, retaining eligible option IDs. Include premature_stop_penalty
  in option-asset minor units (absent zero), with asset-correlated comparisons; a positive
  discovery match is not acceptance or a held-money guarantee. Do not create a second
  evaluator or `interruption.*` alias. Unit targets:
  `core/tests/unit/test_query_dsl.py`,
  `core/registry/tests/unit/test_option_aware_filters.py` and
  `kit/settlement-runtime` clause tests. App integration verifies same-option
  correlation and local/server survivor parity, including predicates that only
  collectively match different options and must fail.
- [ ] 2.3 Preserve units: asking rate's declared period, option rate's `per` and
  billing period remain distinct. Verify sub-hour billing against an hourly rate
  without inventing an hourly amount carrier; do not change approval/dispute timing
  field meanings. Unit verification belongs in query/registration projection suites.

## 3. Class shortcut and first use

- [ ] 3.1 In `domains/vms/buyer/src/arkhai_vms_buyer` and
  `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer`, add `--class` using the
  section 1 contract. Conjoin class with every explicit alternative, require a payer
  entitlement for recurring presets, and exclude prepaid splitter from reserved.
  Reuse explanation's deterministic sanitized output; never enable a disabled
  mechanism or relax a no-match class. Verify at unit level in existing buyer CLI/
  explanation suites, including `domains/vms/buyer/tests/test_explain_cli.py` and
  the bare-metal buyer tests. Reverify actual package paths before editing.
- [ ] 3.2 Prepare committed mixed-option fixtures using existing lane tooling and the
  payments/mediation doubles from `add-arkhai-payments-lane-double`. Each domain has
  two capacity bounds and reserved/on-demand/spot options with differing prices and
  notices; include one negative correlation listing. Driver entry point is each
  buyer's discover/buy command with `--class spot --explain`, then purchase with
  omitted horizon. Record exact runnable commands and lane readiness; no ignored
  worktree-only setup may be required.
- [ ] 3.3 Run affected query/registry/buyer suites and discovery/listing scenarios
  under `e2e-tests/tests/e2e/roles/scenarios`, readiness-gated. Record which
  predicates ran locally versus at the registry. Distinguish double-backed evidence
  from hosted activation; blocked dependencies leave runs unrun, never green.
  Run `make check-change CHANGE=discover-open-ended-compute-listings` and pinned
  strict OpenSpec validation before pre-closeout review.

## 4. Closeout

Documentation-only, following `openspec/README.md#plan-closeout-requirements` in
order. Code defects return to implementation; do not promote planned behavior.

- [ ] 4.1 **Comment hygiene:** run `make check-comment-hygiene` and confirm comments
  describe current invariants rather than change history.
- [ ] 4.2 **Import placement:** confirm touched imports are module-level unless a real
  circularity or deliberate lazy-load rationale is recorded and verified.
- [ ] 4.3 **Documentation compliance:** classify D1–D4 and the typed predicate decision;
  verify permanent placement and that no codec/authority ownership was duplicated.
- [ ] 4.4 **Narrative compression:** keep final behavior, material validation evidence,
  residual work and destinations in completed tasks; retain reasoning in design.
- [ ] 4.5 **Roadmap currency:** update Goal 8 discovery/filter/class current state and
  gap mapping in `docs/development/ROADMAP.md`; record it in the promotion table.
- [ ] 4.6 **Campaign index currency:** update this row and dependency graph in
  `openspec/changes/README.md`; run `make check-change-index`. The integrating owner
  coordinates shared campaign edits; this reconciliation supplies proposed row text.
- [ ] 4.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=discover-open-ended-compute-listings`;
  resolve all failures and owned exceptions. Run agent-skill checks if applicable.
- [ ] 4.8 **End-to-end pipeline:** record pipeline run/result and scenarios proving
  class discovery, both bounds, same-option matching and explanation in both domains.
  A not-ready deployment or dependency is a blocker, not passing evidence.
- [ ] 4.9 **Promotion:** after code review promote the design table to registry spec/
  architecture, CLI-query-language spec, settlement-configuration spec and buyer spec/
  architecture; archive merges the delta-covered specs. Complete the record with
  missing-value/predicate choices. Repository architecture and capability-index
  entries need no additional change beyond the foundation; record that disposition.
- [ ] 4.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=discover-open-ended-compute-listings`, resolve
  matches, then
  `bunx @fission-ai/openspec@1.14.0 validate discover-open-ended-compute-listings --strict`.
- [ ] 4.11 **Archival:** last run
  `bunx @fission-ai/openspec@1.14.0 archive discover-open-ended-compute-listings -y`
  and link the campaign row to its archive.
