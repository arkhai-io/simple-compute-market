# Tasks — open-ended compute terms

Design-stage plan; no implementation is claimed. Verification levels follow
`docs/development/TESTING.md`. New acceptance test implementation requires the
maintainer's approval; the scenarios below are the intended contract, not tests
added by this reconciliation.

This plan builds on Goal 8's MVP change `offer-per-period-vm-terms`, which lands
first. Tasks it took whole, and tasks moved to another change, keep their numbers as
plain lines; a task it took in part keeps its checkbox with the residual work
(design D10).

## 1. Freeze dependency contracts and decision gates

1.1 — moved to `negotiation-driven-capacity-resize`: the negotiated multiplier's
reading of the unit-bearing accessor, its discriminator, and keeping an
absolute-reading Agreement absolute (design D2).

1.2 — withdrawn: the option's `lifecycle` placement is implemented and promoted by
the archived foundation (`deal-lifecycle`, "Lifecycle terms are part of the selected
option"), the codec refuses lifecycle terms on a mechanism without an adapter
(`kit/deal-lifecycle/tests/unit/test_terms.py`), and the placement probe described
the option shape the foundation replaced. The per-period round trip is
`offer-per-period-vm-terms`'s; the bare-metal one is task 4.2's.

- [ ] 1.3 With `spot-deals-through-arkhai-payments`, freeze the injected
  preset-helper interface (D3), separate setup pricing and the payout hold term's
  encoding (D9), over the `period` and `reserve_ahead_seconds` that
  `derive-rate-parts-in-the-payments-kit` fixed and the presets
  `offer-per-period-vm-terms` publishes. A VM per-period preset carries no setup part
  unless the seller configures a price; a bare-metal per-period preset requires a
  seller-priced setup part (D8). Setup-bearing presets publish in a lane once spot
  derives setup parts; a production composition declares them only after the hosted
  mediation service runs the vendored delivery_end revision.
- [ ] 1.3a In `kit/settlement-runtime`, define the declared treatment list (D6): the
  `partialPeriod` treatments a composition has qualified, empty meaning no rate
  servicing, with the MVP's flag as the list `[charged]`. Freeze it with spot (which
  lifts derivation per declared treatment) and with
  `derive-rate-parts-in-the-payments-kit`'s materialization gate. Verify at unit level
  that an option naming an undeclared treatment on any entitlement or at the term end
  is reported as such.
- [ ] 1.3b In `kit/deal-lifecycle`, add the payout hold term to the lifecycle codec
  (D9): optional, in Agreement bytes and the option ID, absent meaning the
  foundation's hold until stop plus the dispute window; add its common query
  projection beside the other lifecycle projections. Verify codec round trip, ID
  sensitivity, absent-means-default and malformed refusal in
  `kit/deal-lifecycle/tests/unit/test_terms.py`; derivation into a mandate is spot's.

## 2. Quote and capacity terms

- [ ] 2.1 Building on the accessor `offer-per-period-vm-terms` ships, migrate bare
  metal's policy/reference readers and buyer caps to it, and add the fail-closed
  guard under `scripts/`, integrated into the existing check targets. Verify at unit
  level with `core/tests/unit/test_rate_helpers.py`, `test_settlement_options.py` and
  the guard's own fixtures: whole-term and recurring readings, an MVP Agreement
  keeping its absolute reading, accepted recovery, and the guard's rejected direct
  reads.
- [ ] 2.2 Add validated relative/UTC absolute hints for `available_until_utc` in
  `kit/resource-pools-contracts`, models in `domains/vms/domain/src/arkhai_vms` and
  `domains/bare_metal/src/arkhai_bare_metal`, and both storefronts' override/default
  resolution; VM's `max_duration_seconds` horizon is `offer-per-period-vm-terms`'s.
  Keep bounds on the listing, not on each option. Verify pure validation and tier
  precedence in the package unit suites; no network or lease changes here.
- [ ] 2.3 Building on the VM on-demand and spot options `offer-per-period-vm-terms`
  publishes: emit bare metal's separately priced per-period options on existing
  listing identities using the codec and injected preset helper; add to both domains'
  presets the premature_stop_penalty (on-demand default 24 periods' price through the
  accessor, seller override), the setup once part per 1.3, payee `last_boundary` for
  spot and term-end `last_boundary` where the composition declares `returned`, and
  the payout hold term with seller choice (D9). Publish whatever
  `delivery_deadline_seconds` the composition supplies. Apply D5's runway inequality
  to the default horizon and report a failing default as a close reason. Omit
  unbounded bare-metal recurring candidates with diagnostics. Missing hosted helper
  omits recurring candidates. Report each term a default buyer refuses in the
  derivation log (D3). Unit targets: both domain suites and
  `domains/vms/storefront/tests/unit`; app-integration targets: VM
  `tests/integration/test_publication_loop.py`, `test_pool_overrides_api.py`,
  `test_listing_identity_carryover.py` and the bare-metal storefront integration
  suite. Prove mixed options preserve capacity identity and valid reserved options.

## 3. Servicing doors and acceptance

- [ ] 3.1 Wire the bare-metal storefront's publication and acceptance to the declared
  treatment list (1.3a), as `offer-per-period-vm-terms` does for VM with `[charged]`;
  in both, omit or refuse an option naming an undeclared treatment, rejecting cached
  recurring options before acceptance persistence. Unit verification covers
  declared, undeclared and partly declared lists; app integration uses each
  storefront's typed client and real persistence to prove the cached-option refusal
  has no acceptance side effect.
- [ ] 3.2 In bare metal's negotiation runtime and policy, resolve the horizon into
  `duration_seconds` and require whole-second recurring starts as
  `offer-per-period-vm-terms` does for VM. In both domains, bind
  `available_until_utc` at the agreed start without rounding, require at least one
  whole period, refuse a recurring horizon that fails D5's runway naming the minimum
  that passes (verify: "The horizon leaves no runway"), refuse expired, excessive or
  sub-period horizons, and refuse a missing reserved duration, removing VM's fallback
  that substitutes the listing maximum or an hour for a reserved option. Carry
  term-end `settles_through` into payments `end.partialPeriod` through the codec.
  Unit targets: domain terms/policy suites; app integration:
  `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py` and
  bare-metal negotiation tests. Delivery uses the same accepted start/end on resume
  and provisioning; do not duplicate its window logic.
- [ ] 3.3 Verify the declaration seam using injected declared lists and stable lane
  identity in bare metal, and the partly declared list in both domains: publication
  omits and cached acceptance refuses an undeclared treatment before persistence.
  Commit reproducible fixtures for those two gates; VM's `[charged]` fixtures are
  `offer-per-period-vm-terms`'s. Spot owns materialization tests and evidence,
  convergence owns startup/continuation tests and evidence; neither gates this task.

## 4. Buyer first use and focused validation

First use includes one mixed bare-metal listing with a hosted on-demand option
carrying its setup part and `delivery_deadline_seconds` and an Alkahest reserved
option carrying no `lifecycle`, selected by a default buyer: the hosted option is
checked for the term and the Alkahest option is shown as making no delivery promise,
not refused for lacking one (D3); and one VM listing adding penalty, payout hold and
returned spot presets to the MVP's options.

- [ ] 4.1 Bring the bare-metal buyer CLI and policy to `offer-per-period-vm-terms`'s
  VM behaviour: optional recurring horizon, required reserved duration and the MVP's
  display. In both CLIs, replace the MVP default acceptance policy with D3's (refuse a
  payee entitlement not settling through `last_boundary`; accept charged on the
  buyer's own stop and at the term end; never require a penalty; never refuse a
  shorter payout hold), each with explicit buyer configuration, and extend D7's
  display with the setup charge and its return rule, the penalty as a ceiling, the
  payout hold with a shorter hold stated as reduced protection, returned and prorated
  treatment, adjudication/retention, the unrounded effective horizon and
  stop-then-hint semantics. The default refusal of a compute option without a
  delivery deadline already exists in the codec. Never promise a reserve-ahead loss
  cap. Unit targets: `domains/vms/buyer/tests/test_buy_resume_cli.py`,
  `test_explain_cli.py` and `domains/bare_metal/buyer/tests`. Integration verifies
  displayed/approved values agree with selected terms and the fixture-derived
  expected mandate; live rate materialization evidence belongs to spot and does not
  gate this task.
- [ ] 4.2 Prepare committed publication/selection fixtures with reserved/on-demand/spot
  candidate options and both bounds in bare metal, and penalty, setup, payout hold
  and returned candidates in both domains, using injected declared lists rather than
  requiring runnable rate or mediation services. Start at each buyer's selection
  surface and observe omitted/shorter horizon, displayed treatments, the default
  policy's refusals and cached-option refusal. Consumer lane qualification belongs to
  spot/convergence/activation, not a prerequisite to this terms archive. Keep fixture
  evidence distinct from runtime rate/live-hosted evidence; readiness-check any
  actual lane before driving it.
- [ ] 4.3 Run affected package unit/app-integration suites, existing VM listing-shape
  scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`,
  `offer-per-period-vm-terms`'s per-period scenarios and existing reserved compute
  deal scenarios in both domains (rate consumer scenarios are not this archive's
  gate). Record exact targets/results and disclose dependency-gated runs. Run
  `make check-change CHANGE=negotiate-open-ended-compute-terms` and strict OpenSpec
  validation before pre-closeout review.

## 5. Closeout

Documentation-only, in `openspec/README.md#plan-closeout-requirements` order;
anything requiring code returns to implementation. These are future implementation
closeout tasks, not authorization to promote unimplemented behavior now.

- [ ] 5.1 **Comment hygiene:** run `make check-comment-hygiene`; confirm touched
  comments describe current invariants, not change provenance.
- [ ] 5.2 **Import placement:** confirm touched imports are module-level unless an
  experimentally verified circularity or deliberate lazy-load reason is recorded.
- [ ] 5.3 **Documentation compliance:** classify D1–D10, including the horizon as the
  Agreement's refinement and which parts `offer-per-period-vm-terms` promoted first;
  verify each permanent home and no duplicated codec/authority ownership.
- [ ] 5.4 **Narrative compression:** reduce completed-task notes to behavior, material
  evidence, residual work and permanent destinations; retain reasoning in design.
- [ ] 5.5 **Roadmap currency:** update Goal 8's terms/display/bounds gap and current
  state in `docs/development/ROADMAP.md`; record the disposition in the promotion
  record.
- [ ] 5.6 **Campaign index currency:** update this row/dependency graph in
  `openspec/changes/README.md` and run `make check-change-index`. The integrating
  owner coordinates the shared campaign; this change supplies row text only.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=negotiate-open-ended-compute-terms`; resolve
  all failures/owned exceptions. Run agent-skill checks if instructions were touched.
- [ ] 5.8 **End-to-end pipeline:** record the pipeline run/result and scenarios proving
  both domains' classes, bounds, display, default policy and the
  declaration/publication/acceptance gates. Materialization and startup/continuation
  pipeline evidence belongs to spot and convergence, respectively, not this change's
  closeout. Readiness/dependency failures are explicit blockers, never passing
  evidence or live-deployment claims.
- [ ] 5.9 **Promotion:** after code review, promote D1–D10 to the destinations in the
  design-promotion table, including publication/buyer architecture companions and
  architecture vocabulary, as modifications of what `offer-per-period-vm-terms`
  promoted. Archive merges deltas into negotiation, publication, resource-pool,
  settlement-configuration and buyer specs; record destinations and identity decision
  outcomes. No new capability-index entry is needed.
- [ ] 5.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `scripts/change-workflow openspec validate negotiate-open-ended-compute-terms --strict`.
- [ ] 5.11 **Archival:** last, run
  `bunx @fission-ai/openspec@1.14.0 archive negotiate-open-ended-compute-terms -y`
  and link the campaign row to the resulting archive.
