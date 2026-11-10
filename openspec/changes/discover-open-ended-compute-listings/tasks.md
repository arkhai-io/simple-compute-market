# Tasks — discover open-ended compute listings

Design-stage plan, not implementation evidence. Use verification jurisdictions in
`docs/development/TESTING.md`; new acceptance test implementation requires maintainer
approval. No tests are added by this reconciliation.

This plan builds on Goal 8's MVP change `offer-per-period-vm-terms`, which lands
first. Tasks taken whole, or already implemented, keep their numbers as plain lines;
a task taken in part keeps its checkbox with the residual work (design D5).

## 1. Reverify dependency contracts

1.1 — already present: the archived foundation compiles the common lifecycle
projections and their exact-option correlation locally
(`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`) and pushes them to
the registry (`core/registry/src/core_registry/filter-spec.yaml`).

1.2 — moved to `offer-per-period-vm-terms`: the `arkhai_payments.period` field, its
typed missing-period and billing-kind representation, and the class semantics its
recipes document. The Alkahest splitter exclusion stays with 1.4 and 3.1.

- [ ] 1.3 Reverify the landed carrier from `store-registry-listings-as-published` for
  `available_until_utc` only, including whether it keeps an explicit null apart from
  an absent field (design D1), the filter-spec edits of `publish-shape-bounds`, and
  `drop-escrow-from-shared-wire`'s pushdown state. Record local versus server
  predicate ownership before 2.1a.
- [ ] 1.4 In `kit/alkahest/src/market_alkahest/settlement_config.py`, expose public
  billing-kind and release-condition eligibility projections using the
  representation `offer-per-period-vm-terms` defined. Verify recipient eligibility
  and splitter exclusion in `kit/alkahest/tests/unit/test_settlement_config.py`;
  shared discovery must not inspect arbiter trees or invent lifecycle entitlements.

## 2. Bound filters and correlated option discovery

- [ ] 2.1 In `core/registry/src/core_registry/filter-spec.yaml` and its filter code,
  add the lower-bound filter on `max_duration_seconds`, which the registry already
  carries, with D1's missing-value rule. Preserve ETag preconditions. Unit targets:
  `core/registry/tests/unit/test_filter_spec.py`, `test_filter_eval.py`;
  app-integration targets: `core/registry/tests/integration/test_filter_spec.py`,
  `test_listings_filtering.py` and `test_listings.py`. Prove known-unlimited versus
  unknown semantics and round-trip publication using the canonical typed registry
  client.
- [ ] 2.1a After 1.3 and `negotiate-open-ended-compute-terms` task 2.2, declare UTC
  `available_until_utc` and its lower-bound filter on the dependency's carrier. Prove
  UTC instant comparison, equivalent timezone-normalized instants, unknown
  availability failing an explicit minimum, and round-trip publication, on the same
  targets as 2.1.

2.2 — moved to `offer-per-period-vm-terms`: the local `arkhai_payments.period` field.
The common `early_termination.*`/`adjudication.*` fields, the asset-correlated
penalty projection and their registry pushdown are already present (1.1); the period
predicate stays local (design D2).

2.3 — moved to `offer-per-period-vm-terms`: unit preservation of asking rate, option
rate and billing period.

## 3. Class shortcut and first use

- [ ] 3.1 In `domains/vms/buyer/src/arkhai_vms_buyer` and
  `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer`, add `--class`, compiled to
  the same typed predicates `offer-per-period-vm-terms`'s recipes document, with
  1.4's Alkahest projections. Conjoin class with every explicit alternative, require
  a payer entitlement for recurring presets, and exclude the prepaid splitter from
  reserved. Reuse explanation's deterministic sanitized output; never enable a
  disabled mechanism or relax a no-match class. Update the recipe documentation to
  name `--class` as their shorthand. Verify at unit level in existing buyer CLI/
  explanation suites, including `domains/vms/buyer/tests/test_explain_cli.py` and
  the bare-metal buyer tests. Reverify actual package paths before editing.
- [ ] 3.2 Prepare committed mixed-option fixtures using existing lane tooling and the
  payments and mediation lane doubles, reusing `offer-per-period-vm-terms`'s VM
  per-period listing. Each domain has two capacity bounds and reserved/on-demand/spot
  options with differing prices and notices; include one negative correlation
  listing. Driver entry point is each buyer's discover/buy command with
  `--class spot --explain`, then purchase with omitted horizon. Record exact runnable
  commands and lane readiness; no ignored worktree-only setup may be required.
- [ ] 3.3 Run affected query/registry/buyer suites and discovery/listing scenarios
  under `e2e-tests/tests/e2e/roles/scenarios`, readiness-gated. Record which
  predicates ran locally versus at the registry. Distinguish double-backed evidence
  from hosted activation; blocked dependencies leave runs unrun, never green.
  Run `make check-change CHANGE=discover-open-ended-compute-listings` and strict
  OpenSpec validation before pre-closeout review.

## 4. Closeout

Documentation-only, following `openspec/README.md#plan-closeout-requirements` in
order. Code defects return to implementation; do not promote planned behavior.

- [ ] 4.1 **Comment hygiene:** run `make check-comment-hygiene` and confirm comments
  describe current invariants rather than change history.
- [ ] 4.2 **Import placement:** confirm touched imports are module-level unless a real
  circularity or deliberate lazy-load rationale is recorded and verified.
- [ ] 4.3 **Documentation compliance:** classify D1–D5, including D1's missing-value
  rule as the carrier settled it; verify permanent placement and that no
  codec/authority ownership was duplicated.
- [ ] 4.4 **Narrative compression:** keep final behavior, material validation evidence,
  residual work and destinations in completed tasks; retain reasoning in design.
- [ ] 4.5 **Roadmap currency:** update Goal 8 discovery/filter/class current state and
  gap mapping in `docs/development/ROADMAP.md`; record it in the promotion table.
- [ ] 4.6 **Campaign index currency:** update this row and dependency graph in
  `openspec/changes/README.md`; run `make check-change-index`. The integrating owner
  coordinates shared campaign edits; this change supplies proposed row text.
- [ ] 4.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=discover-open-ended-compute-listings`;
  resolve all failures and owned exceptions. Run agent-skill checks if applicable.
- [ ] 4.8 **End-to-end pipeline:** record pipeline run/result and scenarios proving
  class discovery, both bounds, same-option matching and explanation in both domains.
  A not-ready deployment or dependency is a blocker, not passing evidence.
- [ ] 4.9 **Promotion:** after code review promote the design table to registry spec/
  architecture, CLI-query-language spec, settlement-configuration spec and buyer spec/
  architecture; archive merges the delta-covered specs. D2 needs no new promotion:
  its projections are already permanent and the period field is the MVP's. Repository
  architecture and capability-index entries need no change; record that disposition.
- [ ] 4.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=discover-open-ended-compute-listings`, resolve
  matches, then
  `scripts/change-workflow openspec validate discover-open-ended-compute-listings --strict`.
- [ ] 4.11 **Archival:** last run
  `bunx @fission-ai/openspec@1.14.0 archive discover-open-ended-compute-listings -y`
  and link the campaign row to its archive.
