# Tasks — open-ended compute terms

Implementation started on the stacked resize and registry branches. The partial
2.1 checkpoint adds the quote carrier/accessor and VM pricing-proof retention;
consumer migration and recurring behavior are not implemented. Verification levels follow
`docs/development/TESTING.md`. New acceptance test implementation requires the
maintainer's approval; the scenarios below are the intended contract, not tests
added by this reconciliation.

## 1. Freeze dependency contracts and decision gates

- [x] 1.1 Reverify `negotiation-driven-capacity-resize`'s landed multiplier contract
  against `core/src/market_core/schemas.py` and `core/tests/unit/test_rate_helpers.py`.
  Record scalar, rounding and amount-range behavior before migrating readers. Resolve resize task
  2.1a's accepted rate-structure carrier before recovery/mandate reads; retain its bound evidence,
  never substitute a current listing after restart or repricing.
- [x] 1.2 With `agreed-evidence-and-early-termination`, once `kit/deal-lifecycle` exists,
  run a replayable regression diagnostic (rather than a new permanent acceptance
  test, per the standing owner instruction) that the option's top-level `lifecycle` round-trips through
  hosted publication, the registry carrier and both buyer commitment checks by the same
  codec (D4), and that an Alkahest option carries none and is refused if it does (the
  binding rule). Do not implement a mechanism-specific term codec. `placement-probe.md`
  records the rejected in-params placement; the nested-shape check there is the
  regression, not a decision gate.
- [x] 1.3 With the reconciled rate change (`spot-deals-through-arkhai-payments`),
  freeze the injected preset-helper interface (D3), `period`, `reserve_ahead_seconds`, separate setup pricing, accessor unit and
  servicing-declaration contracts. The option carries no maximum term: the horizon
  is resolved into `duration_seconds` at acceptance and the option's ID is unchanged
  from the registry to the Agreement (D5). Setup-bearing preset publication and acceptance wait for foundation 12.1's delivery_end revision and vectors, not another payments wire change; preserve valid setup-free options while it is pending.

### Dependency-contract checkpoint (2026-11-06)

- Base: `ba77a3b30` (`resize-multiplier`, PR #350); merged
  `registry-as-published` (PR #349) as `faa339eea`. D-a–D-e remain accepted
  for implementation, pending maintainer review. The webapp owner authorized
  implementation before design review; the campaign row records that disposition.
- At this initial checkpoint, task 1.1 was exercised but left unchecked because the observed contract
  contradicts D2: resize negotiates basis points but writes the **derived monetary
  total** to `Agreement.amount`. The multiplier remains in the transcript and
  `negotiation_threads.agreed_price`. `design.md`'s dependency re-verification
  records the decision needed before changing this signed carrier.
- Focused evidence: `make dist-ci` passed; core's existing `test_rate_helpers.py`
  and `test_settlement_options.py` passed (21 tests); VM storefront's existing
  unit and library-integration `test_vm_multiplier.py` files passed (8 tests).
  The latter uses real SQLite and runtime calls, not the application's HTTP client.
  Exact commands/results are in
  `docs/attachments/negotiate-open-ended-compute-terms/dependency-contract.md`.
  `make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
  and pinned strict OpenSpec validation passed. The change check initially
  refused missing D1–D8 destination bullets; commit `7cb03533e` names the already
  planned post-review destinations without promoting behavior.
- At this initial checkpoint, no tests were added, no production readers migrated,
  and tasks 1.2 onward had not started. No deployment/E2E or closeout evidence is claimed.
- Initial restart point (resolved by D2a below): resolve the scalar-versus-money question in design D2, update
  its delta and tasks to the chosen contract, then finish 1.1 and proceed to 1.2.
  Do not divide or multiply the current Agreement amount as if it were basis
  points. Use `make dist-ci` and the focused commands in the evidence packet
  to recreate the local package environments; they are not committed state.

### D2a continuation (2026-11-06)

- The webapp owner resolved the checkpoint: keep `Agreement.amount` monetary;
  transcript state keeps the multiplier. D2a and the negotiation delta record
  pre-acceptance per-period derivation and accepted-evidence verification on
  recovery/mandate checks. Maintainer review is pending on the PR.
- 1.1 contract verification and 1.3 consumer handoff are recorded in
  `dependency-contracts.md`. Actual accepted snapshot/proof retention and verification
  before recovery/mandate reads remain in 2.1; the existing field subset is not
  sufficient evidence and is not claimed otherwise.
- 1.2 evidence: hosted once builder → neutral carrier → shared codec → exact
  Agreement and both domain pre-approval checks pass; actual registry publication,
  readback and historical seller-signature verification pass in an invocation-owned
  in-process app with real SQLite. Alkahest with no lifecycle is admitted, while
  attaching lifecycle is refused. Early-termination identity/round-trip is structural
  only, not a claim of hosted recurring support. The probes are temporary change
  evidence, not new permanent acceptance tests.
- Existing focused suites passed: lifecycle terms (unit, 47), payments agreement/
  buyer/config (unit, 51), registry listings (application integration through its
  typed client, 17), VM stage-dispatch/orchestrator (unit, 21), bare-metal composition/
  recovery (unit and controlled in-process application paths, 15). The bare-metal
  invocation initially inherited an unsupported SOCKS proxy; clearing proxy variables
  for that invocation made it pass without changing code or installing a dependency.
- `make check-packaging` and `make check-change
  CHANGE=negotiate-open-ended-compute-terms` passed. No product code, live approval,
  or deployment is claimed. Exact setup/probe commands and limits:
  `docs/attachments/negotiate-open-ended-compute-terms/codec-contract.md`.
- No deployed E2E marker proves these dark, injected contracts yet. Section 4.3
  names the existing listing/reserved system regressions; rate consumer evidence
  remains owned by spot. No push-only workflow evidence is owed for section 1's
  contract freeze. Independent implementation review remains pending.
- Resume at 2.1: implement the accessor without reinterpreting monetary Agreement
  amounts; preserve verified acceptance evidence before migrating recovery readers,
  then migrate both domains and install the fail-closed direct-read guard. Work
  through 2.2 onward in order. Promotion and archival remain post-review.

### Partial 2.1 checkpoint (2026-11-07)

- Added core `PriceBasis`, `AgreedPrice` and `agreed_price`. The accessor returns
  accepted money without recomputing it; selected options require an explicit,
  mechanism-owned `project_billing` callback. Core never reads a mechanism's period.
  A supplied acceptance-bound listing must contain the exact selected option and
  matching listing identity. This correspondence check is not authentication.
- For rate-structured listings, both VM buyer recording paths now retain seller publication bytes, complete
  authenticated request, publisher trust/provenance and existing pricing fields
  together, with a deep copy. Existing logs are not backfilled from current listings.
  Retention alone does not establish verified accepted pricing evidence.
- `price_probe.py` exercises the actual VM acceptance-record hook, JSON recovery,
  historical seller-signature verification and isolation from later source edits.
  It also drives the core accessor with prepaid and injected sub-hour recurring
  projections. This is a temporary diagnostic, not a new permanent acceptance test
  or proof of supported hosted recurring mandates.
- Focused validation and replay instructions:
  `docs/attachments/negotiate-open-ended-compute-terms/price-checkpoint.md`.
  No deployed first use, E2E, promotion, archival or independent review is claimed.
- **Restart at the remainder of 2.1**, not 2.2: wire billing projection through
  installed mechanism registrations/compositions (once mechanisms explicitly total;
  rate projection belongs to its adapter). Verify retained seller publication at its
  signed timestamp against accepted trust, listing identity/context, rate structure
  and exact selected option. Bind and verify the transcript multiplier and signed
  acceptance/Agreement before migrating recovery and buyer mandate readers. Preserve
  the original accepted snapshot; never use a fresh listing or rewrite old logs.
  Then migrate both domains' readers/caps/VM checks/rate adapter and add the fail-closed
  repository guard. The accessor by itself authenticates none of these inputs.
  Pre-acceptance recurring amount derivation also remains unimplemented.
- Keep 2.1 unchecked until its consumers and guard are complete. All later tasks
  remain in their existing order; promotion and archival remain post-review. This
  is an authorized session checkpoint, not completion of the terms feature.

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
  existing listing identities using the foundation codec and injected preset helper; include
  premature_stop_penalty, recommended on-demand default 24 periods' price with seller override,
  and `delivery_deadline_seconds` from the pool's effective value, read like the bound hints, on
  every compute option (none when the pool enforces none; the diagnostic names the refusal). Apply D5's
  runway inequality to the default horizon and report a failing default as a close reason.
  Missing hosted helper omits recurring candidates. Omit unbounded
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
  signature per D5, resolving the horizon into `duration_seconds`; require whole-second recurring starts,
  refusing fractional values without rewriting accepted bytes; bind equal duration/max term
  without rounding, require at least one whole period for recurring horizons, refuse a
  recurring horizon that fails D5's runway inequality naming the minimum that passes
  (verify: "The horizon leaves no runway"), and
  refuse expired/excessive horizons and missing reserved duration. Carry term-end
  `settles_through` into payments `end.partialPeriod` through the foundation codec;
  compute presets use returned and fail closed until vendored. Interim recommendation:
  absolute end with a charged final partial period disclosed in the option. Remove only VM's
  round-zero fallback here. Unit targets: domain terms/policy suites;
  app integration: `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py`
  and bare-metal negotiation tests. `unify-compute-delivery-path` gates using the same
  accepted start/end on resume and provisioning; do not duplicate its window logic.
- [ ] 3.3 Verify this change's declaration seam using injected published/proposed/absent
  declarations and stable lane identity: publication omits and cached acceptance refuses
  undeclared servicing before persistence. Commit reproducible fixtures for those two gates.
  Handoff declaration/accessor contracts after 1.3, 2.1 and 3.1 to spot materialization;
  spot owns its restart/refusal tests and evidence, convergence owns startup/continuation
  tests and evidence. Do not wait for either consumer to close this task or archive this change.
  Deployed recurring offers remain disabled until the consuming gates pass.

## 4. Buyer first use and focused validation

First use includes one mixed listing per domain with a hosted on-demand option carrying
`delivery_deadline_seconds` and an Alkahest reserved option carrying no `lifecycle`,
selected by a default buyer: the hosted option is checked for the term and the Alkahest
option is shown as making no delivery promise, not refused for lacking one (D3).

- [ ] 4.1 Update both buyer CLIs and policies: optional recurring horizon, required
  reserved duration and D7's display of class/price unit/setup/reserve/terms, including
  per-stopper and term-end `settles_through`, premature-stop penalty amount/asset/cap,
  the delivery deadline as seconds after approval, recommended default acceptance refusal of
  on-demand without positive penalty and of a compute option whose mechanism has a lifecycle
  adapter without a delivery deadline (explicit buyer opt-out; an option without an adapter
  is shown as making no delivery promise), unrounded effective horizon and
  stop-then-hint semantics. Use
  accepted codec values; never promise a reserve-ahead loss cap. Unit targets:
  `domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py` and
  `domains/bare_metal/buyer/tests`. Integration verifies displayed/approved values
  agree with selected terms and the fixture-derived expected mandate; live rate
  materialization evidence belongs to spot and does not gate this task.
- [ ] 4.2 Prepare committed publication/selection fixtures with reserved/on-demand/spot
  candidate options and both bounds in each domain, using injected proposed declarations
  rather than requiring runnable rate or mediation services. Start at each buyer's selection
  surface and observe omitted/shorter horizon, displayed treatments and cached-option refusal.
  Consumer lane qualification of all three doors belongs to spot/convergence/activation,
  not a prerequisite to this terms archive. Keep proposed fixture evidence distinct from
  runtime rate/live-hosted evidence; readiness-check any actual lane before driving it.
- [ ] 4.3 Run affected package unit/app-integration suites, existing VM listing-shape
  scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` and
  existing reserved compute deal scenarios in both domains (rate consumer scenarios are not
  this archive's gate). Record exact targets/results and disclose
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
- [ ] 5.3 **Documentation compliance:** classify D1–D8, including the horizon as the Agreement's
  refinement; verify each permanent home and no duplicated codec/authority ownership.
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
  both domains' classes, bounds, display and the declaration/publication/acceptance gates.
  Materialization and startup/continuation pipeline evidence belongs to spot and convergence,
  respectively, not this change's closeout. Readiness/dependency
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
