# Tasks — open-ended compute terms

Design-stage plan; no implementation is claimed. Verification levels follow
`docs/development/TESTING.md`. New acceptance test implementation requires the
maintainer's approval; the scenarios below are the intended contract, not tests
added by this reconciliation.

## 1. Freeze dependency contracts and decision gates

- [ ] 1.1 Reverify `negotiation-driven-capacity-resize`'s landed multiplier contract
  against `core/src/market_core/schemas.py` and `core/tests/unit/test_rate_helpers.py`.
  Record scalar, rounding and amount-range behavior before migrating readers. Resolve resize task
  2.1a's accepted rate-structure carrier before recovery/mandate reads; retain its bound evidence,
  never substitute a current listing after restart or repricing.
- [ ] 1.2 With `agreed-evidence-and-early-termination`, once `kit/deal-lifecycle` exists,
  add a regression test that both objects round-trip through hosted and `kit/alkahest`
  option params, splitter service terms and both buyer commitment checks by the same
  codec (D4). Do not implement a mechanism-specific term codec. Start from `placement-probe.md`.
- [ ] 1.3 With the reconciled rate change (`spot-deals-through-arkhai-payments`),
  freeze `period`, `reserve_ahead_seconds`, separate setup pricing, accessor unit and
  servicing-declaration contracts. With the foundation, decide and record the
  start/absolute-bound/final-option identity gate in D5 without weakening advertised
  option correlation. This gates acceptance work. Record any required protocol delta.

## 2. Quote and capacity terms

- [ ] 2.1 In `core/src/market_core/schemas.py` implement the unit-bearing accessor;
  migrate both domains' policy/reference readers, buyer caps, VM checks and the rate
  adapter to it. Add the fail-closed guard under `scripts/`, integrated into the
  existing check targets. Verify at unit level with `core/tests/unit/test_rate_helpers.py`
  and `test_settlement_options.py`: whole-term, sub-hour recurring, rounding, absolute
  amount fallback, accepted recovery and the guard's rejected direct reads.
- [ ] 2.2 Add validated relative/UTC absolute hints in `kit/resource-pools-contracts`,
  models in `domains/vms/domain/src/arkhai_vms` and
  `domains/bare_metal/src/arkhai_bare_metal`, and both storefronts' override/default
  resolution. Keep bounds on the listing, not on each option. Verify pure validation
  and tier precedence in the package unit suites; no network or lease changes here.
- [ ] 2.3 In both storefront publication adapters, emit separately priced options on
  existing listing identities using the foundation codec, and omit unbounded
  recurring candidates with diagnostics. Consume, do not redo, the foundation's
  Alkahest release-model migration. Unit targets: both domain suites and
  `domains/vms/storefront/tests/unit`; app-integration targets: VM
  `tests/integration/test_publication_loop.py`, `test_pool_overrides_api.py`,
  `test_listing_identity_carryover.py` and the bare-metal storefront integration
  suite. Prove mixed options preserve capacity identity and valid reserved options.

## 3. Servicing doors and acceptance

- [ ] 3.1 In `kit/settlement-runtime` define the composition-owned declaration agreed
  with the rate adapter. Wire both storefronts' publication and acceptance checks;
  reject cached recurring options before acceptance persistence. Unit verification
  covers published/proposed contract selection and lane-only opt-in; app integration
  uses each storefront's typed client and real persistence to prove the cached-option
  refusal has no acceptance side effect.
- [ ] 3.2 In both negotiation runtimes/policies, resolve start/bounds before final
  signature according to section 1's identity decision, round the effective horizon down to whole periods,
  bind equal duration/max term,
  refuse expired/excessive horizons and missing reserved duration. Remove only VM's
  round-zero fallback here. Unit targets: domain terms/policy suites;
  app integration: `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py`
  and bare-metal negotiation tests. `unify-compute-delivery-path` gates using the same
  accepted start/end on resume and provisioning; do not duplicate its window logic.
- [ ] 3.3 With the rate change, exercise materialization's undeclared-servicing refusal
  after acceptance/restart; with `converge-ongoing-compute-leases`, exercise startup
  refusal without accepted-deal continuation and continued servicing when offers are
  disabled. Do not turn on recurring publication until these gates pass. Library
  integration owns durable adapter behavior; app integration owns composition and
  fail-before-effect behavior. Exercise one readiness-gated lane scenario per door.

## 4. Buyer first use and focused validation

- [ ] 4.1 Update both buyer CLIs and policies: optional recurring horizon, required
  reserved duration and D7's display of class/price unit/setup/reserve/terms, including
  per-stopper `settles_through`, effective whole-period horizon and stop-then-hint semantics. Use
  accepted codec values; never promise a reserve-ahead loss cap. Unit targets:
  `domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py` and
  `domains/bare_metal/buyer/tests`. Integration verifies displayed/approved values
  agree with the selected option and materialized mandate.
- [ ] 4.2 Prepare committed first-use fixtures and commands using existing e2e lane
  tooling: one pool with reserved/on-demand/spot options and two finite bounds in
  each domain, with the payments/mediation doubles from
  `add-arkhai-payments-lane-double`. Readiness-check before scenarios; record double
  evidence distinctly from live hosted activation. Start at each buyer's buy surface
  and observe unnamed horizon, a shorter named horizon and a cached-option refusal.
- [ ] 4.3 Run affected package unit/app-integration suites, existing VM listing-shape
  scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` and
  compute deal scenarios in both domains. Record exact targets/results and disclose
  dependency-gated runs. Run `make check-change CHANGE=negotiate-open-ended-compute-terms`
  and pinned strict OpenSpec validation before pre-closeout review.

## 5. Closeout

Documentation-only, in `openspec/README.md#plan-closeout-requirements` order;
anything requiring code returns to implementation. These are future implementation
closeout tasks, not authorization to promote unimplemented behavior now.

- [ ] 5.1 **Comment hygiene:** run `make check-comment-hygiene`; confirm touched
  comments describe current invariants, not change provenance.
- [ ] 5.2 **Import placement:** confirm touched imports are module-level unless an
  experimentally verified circularity or deliberate lazy-load reason is recorded.
- [ ] 5.3 **Documentation compliance:** classify D1–D8 and identity gate
  outcomes; verify each permanent home and no duplicated codec/authority ownership.
- [ ] 5.4 **Narrative compression:** reduce completed-task notes to behavior, material
  evidence, residual work and permanent destinations; retain reasoning in design.
- [ ] 5.5 **Roadmap currency:** update Goal 8 terms/display/bounds gap and current state
  in `docs/development/ROADMAP.md`; record the disposition in the promotion record.
- [ ] 5.6 **Campaign index currency:** update this row/dependency graph in
  `openspec/changes/README.md` and run `make check-change-index`. The integrating
  owner coordinates the shared campaign; this reconciliation supplies row text only.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=negotiate-open-ended-compute-terms`; resolve
  all failures/owned exceptions. Run agent-skill checks if instructions were touched.
- [ ] 5.8 **End-to-end pipeline:** record the pipeline run/result and scenarios proving
  both domains' classes, bounds, display and all three doors. Readiness/dependency
  failures are explicit blockers, never passing evidence or live-deployment claims.
- [ ] 5.9 **Promotion:** after code review, promote D1–D8 to the destinations in the
  design-promotion table, including publication/buyer architecture companions and
  architecture vocabulary. Archive merges deltas into negotiation, publication,
  resource-pool, settlement-configuration and buyer specs; record destinations and
  identity decision outcomes. No new capability-index entry is needed.
- [ ] 5.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict`.
- [ ] 5.11 **Archival:** last, run
  `bunx @fission-ai/openspec@1.14.0 archive negotiate-open-ended-compute-terms -y`
  and link the campaign row to the resulting archive.
