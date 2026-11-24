# Tasks — switch-on-hosted-per-period-vm

Sections 1–4 are the internal work, proven on the lanes; sections 5–8 are live
verification, which ends waiting for the deployment's evidence (D3, D9) before the
pre-closeout review. Section 9 is a defect fix to the payments kit's local example. The live scenarios belong to no pipeline lane: the pipeline proves
their lane twins, and the deployment runs them against a topology meeting their stated
requirements.

## 1. The mediation double executes a ruling's `stop` and `penalty`

Delivers the mediation double applying a ruling's `stop` and `penalty` effects at the
payments double, `award` still refused. Implements D6; requirement "Lanes run a
mediation double that answers from programmed rules" (`test-compatibility`, modified).
Touches `tools/mediation-lane-double` (`rules.py`, `service.py`, its tests, README,
`pyproject.toml` and lock), the consumers' pins of it if any, and the convergence
change's index row and Goal 8 gap (inert paths).

- [x] 1.1 Admit `stop` and `penalty` in the double's rules and operator decisions
      (`tools/mediation-lane-double/src/mediation_lane_double/rules.py`,
      `_APPLIED_EFFECTS`), keeping `award` refused at install with a typed code and
      nothing installed; the controls' `Ruling` model already admits every contract
      `Effect` (`tools/lane-double-controls/src/lane_double_controls/models.py`) and
      needs no change (D6). Verify (unit, `tools/mediation-lane-double/tests/unit/test_rules.py`):
      a rule and a decision carrying `stop` or `penalty` install; one carrying `award`
      is refused and installs nothing.
      Done: `rules.check_ruling` is the one admission check, called by
      `RuleBook.install` and, outside the plan, by `MediationDouble.decide`, which
      checked no effect before; refusal `422 invalid_request` naming the effect.
      Unit (`test_rules.py`) and application integration (`test_controls.py`, through
      `ControlClient`): `reverse`, `stop` and `penalty` admitted; an `award` rule
      refused with nothing installed, an `award` decision refused with the case left
      open — pass.
- [x] 1.2 Apply them in `service.py` as the requirement states (D6): a `stop` as one
      stop event from the double's own account through the part's `chosen` stop entry,
      carrying the ruling's partial-period treatment, keyed like a `reverse`
      (`<case_ref>:<ruling>:<n>`) so every resend is the same request; a `penalty` as
      reversals of earned amounts still held, part by part in mandate order, up to the
      penalty and no further than what is held, each reversal keyed beneath its
      effect's key. A payments failure between effects, the gate and resume, and the
      close refusal behave as for `reverse` today. Verify (library integration,
      `tools/mediation-lane-double/tests/integration/test_rulings.py`, the double over
      HTTP against the payments double's engine): a ruling's `stop returned` on a
      running rate part leaves the part stopped with cause `authority` and treatment
      `returned`, and its repetition sends the same event; a `penalty` larger than what
      is held reverses exactly what is held, in mandate order; a gated ruling with a
      `stop` sends nothing until resumed; a payments failure after a `stop` and before a
      `reverse` resumes without stopping twice.
      Done: `service._payment_events` builds each effect's events once into
      `Case.events`, resent unchanged, rebuilt only on a refused first event
      (`Case.reached`); a `stop` carries its `at` only while not passed; a `penalty`
      reverses each part's `held` in mandate order, keyed
      `mediation:<case_ref>:<ruling>:effect:<n>:part:<i>` (design.md,
      "Implementation notes", section 1). Application integration, not library
      integration as planned (`test_rulings.py`, the app in process against the
      payments kit's `PaymentsAuthority` engine): the planned cases and the retry,
      rebuild and operator-decision paths — pass, suite 96; unit (`test_penalty.py`)
      — pass. A passed stop's reversal: superseded by section 12.
- [x] 1.3 Rewrite the double's README for the effects it applies ("Deviation from its
      producer"; the effects paragraph), bump `tools/mediation-lane-double`'s version and
      relock (`make lock`), and raise any consumer's minimum to it
      (`docs/guidance/repository/package-versions.md`). Verify: `scripts/change-workflow
      run pre-commit switch-on-hosted-per-period-vm` passes, the packaging check among
      its functional hooks.
      Done: the README states how each effect is applied and rebuilt, and that an
      `award` is refused (its passed-stop deviation later dropped by section 12).
      0.1.0 to 0.2.0, relocked; no project pins or imports the double, so no consumer
      minimum moves. `scripts/change-workflow run pre-commit` passed but for the
      citation of section 8's summary, expected until section 8.
- [x] 1.4 In `openspec/changes/README.md`, `converge-ongoing-compute-leases`' row Notes
      record that this change took the double's `stop` and `penalty` execution; in
      `docs/development/ROADMAP.md`'s Goal 8, the convergence gap row no longer says the
      double executes only `reverse` effects and that its rate rows first add that
      execution (D6; `docs/guidance/workflow/changes.md`, "Defects found during a
      change"). Verify: `scripts/change-workflow check index` passes.
      Done: the convergence row's Notes say so, its deliverables cell left for its own
      reverification; the Goal 8 gap row drops the clause. `check index` — pass. The
      Goal 8 current-state sentence on `reverse` effects is left for roadmap currency
      (14.5).
- [x] 1.5 Verification point: the double's unit and integration suites pass, and the VM
      lane's dispute scenarios still pass against the amended double (system, the VM
      lane's Compose stack: `make -C e2e-tests test-e2e-vm "E2E_MODULE=e2e_vm_payment_deal
      or e2e_vm_dispute_ruled_end or e2e_vm_dispute_discount or e2e_vm_dispute_lost_filing
      or e2e_vm_dispute_mediation_unavailable or e2e_vm_dispute_payments_hold or
      e2e_vm_dispute_hold_passed"`).
      End-to-end: `e2e_vm_payment_deal`, `e2e_vm_dispute_ruled_end`,
      `e2e_vm_dispute_discount`, `e2e_vm_dispute_lost_filing`,
      `e2e_vm_dispute_mediation_unavailable`, `e2e_vm_dispute_payments_hold`,
      `e2e_vm_dispute_hold_passed`; none yet exercises a `stop` or `penalty`, which
      section 3 adds.
      Nothing is owed to validation.
      Evidence: `make -C tools/mediation-lane-double test` — 96 passed. System, the VM
      lane's Compose stack with the double's image at 0.2.0, the command above — 107
      passed, 1851 deselected. The scenarios show the double still serves the
      reverse-only rows; none is evidence for `stop` or `penalty`.

Handoff (section 1):

- Outside the plan: `decide` checks its ruling (1.1); a defect `make test` found at the
  base, `scripts/tests/test_change_workflow_assumptions.py`, fixed by naming the
  validator in `market-change-workflow`'s README closing-checks row; comments and docs
  saying the double "extends, reverses and lifts" now include "stops" (the payments
  double's README sentence left, being its wheel's metadata and incomplete, not false).
- For closeout's promotion of D6: superseded by section 12 (12.1, 12.4); no deviation
  is promoted.
- Unowned: a penalty's kept reversal can exceed what is still held after a release
  between failure and resume; a row of Goal 8's "Work this goal found and leaves
  unowned" in `docs/development/ROADMAP.md`.
- Fresh-context checks: findings fixed. Declined: the convergence row's deliverables
  cell, left for its reverification.

## 2. The payment rows' producer outputs as shared assertions

Delivers, for the buyer's stop, funds running out, the spot preemption and the term end,
one assertion each over the payments producer's output, stating which fields it compares
exactly, by relation, or not at all, used by the existing VM lane rows now and by their
live twins in section 5. Implements D6 (the shared comparison); requirement "A live
verification scenario compares a producer's outputs with a lane's expectations"
(`test-compatibility`, added), its lane half. Touches `e2e-tests/tests/e2e/roles/helpers/`
(`recurring_purchase_stages.py`, `rate_servicing_stages.py`, and a new module holding the
assertions), and the VM recurring purchase and rate servicing modules that call them.

- [x] 2.1 Write the four assertions over what the payments double and the hosted
      service both emit — the signed snapshot's part stop (cause, stopping account,
      effective instant, treatment), settled and refunded amounts, the funded boundary —
      each naming its exact fields (cause, treatment, amounts derived from the row's
      price and periods), its relational ones (an effective instant equal to receipt plus
      notice; a terms stop at the snapshot's funded boundary; a term end at the
      Agreement's end) and the fields it ignores (identifiers, signatures, `observedAt`,
      sequence numbers) (D6). A stage that reads the producer's output and a stage that
      asserts on it are separate, so the read can be the lane's step-and-read or a live
      bounded poll. Verify (unit, `e2e-tests/tests/unit/`): each assertion passes on a
      recorded double output, fails naming the field and both values on an altered
      exact field, and ignores an altered identifier or `observedAt`.
      Done: `e2e-tests/tests/e2e/roles/helpers/producer_assertions.py`:
      `assert_payer_stop`, `assert_funds_exhausted`, `assert_payee_stop_pending`,
      `assert_payee_stop` and `assert_term_end`, each naming every differing field
      with both values; exact, relational and ignored fields stated in the module
      docstring. The read and the assertion are separate functions, not stages
      (design.md, "Implementation notes", section 2). Unit
      (`test_producer_assertions.py`, on engine snapshots rather than a committed
      recording) — 26 pass. Floor on `arkhai-kit-arkhai-payments` raised to 0.9.0;
      `arkhai-e2e-tests` 0.3.0 to 0.3.1, relocked; a later section takes no second
      bump.
- [x] 2.2 Make `e2e_vm_recurring_purchase`'s buyer stop and `e2e_vm_rate_servicing`'s
      three rows assert through them, the lanes' step-and-read stages unchanged, and the
      bare-metal rows untouched (D6). Verify (unit): `make -C e2e-tests test-unit`
      passes, the stage order and handoff checks (`ORDERS`) included.
      Done: `Recurring08_BuyerEnds`, `Exhaustion07_FundsRunOut`,
      `Preemption07_SellerNoticeHeld`, `Preemption08_StopTakesEffect` and
      `MaximumTerm07_TermEnds` assert through the shared functions; the preemption
      keeps its lane-only timing checks; no stage order changed. Bare metal declares
      the same shared classes, so its rows assert through them too, its modules
      untouched (run in 2.3). `make -C e2e-tests test-unit` — 1051 passed, 1 skipped.
- [x] 2.3 Verification point: the VM lane's recurring purchase and rate rows pass on the
      shared assertions (system, the VM lane's Compose stack: `make -C e2e-tests
      test-e2e-vm "E2E_MODULE=e2e_vm_recurring_purchase or e2e_vm_rate_servicing"`).
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_vm_rate_servicing`.
      Nothing is owed to validation.
      Evidence: system, the VM lane's Compose stack, the command above — 121 passed,
      1862 deselected. Outside the plan: system, the bare-metal lane's Compose stack,
      `make -C e2e-tests test-e2e-bare-metal "E2E_MODULE=e2e_bare_metal_recurring_purchase
      or e2e_bare_metal_rate_servicing"` — 249 passed. `scripts/change-workflow run
      pre-commit` passed but for section 8's citation.

## 3. A dispute on a running rate deal in the VM lane

Delivers two VM lane rows on rate deals, each ruled with an authority stop, proving what
the storefront does after a ruling, and their shared assertions over the dispute
authority's and payments' output. Implements D6; requirement "A dispute on a running rate
deal is qualified in the VM lane" (`test-compatibility`, added). Touches a new
`e2e-tests/tests/e2e/roles/scenarios/vms/rate_dispute/` (conftest, stages, two modules),
the assertions module of section 2, `e2e-tests/pyproject.toml`'s markers, the Makefile's
VM lane list, and `e2e-tests/README.md`.

- [x] 3.1 The seller's filing row: on a delivered on-demand rate deal reached through the
      recurring purchase's stages, with lane time past the first period's end so
      earnings are held, the storefront's administrator ends delivery through the typed
      seller lifecycle client and the storefront files as the payee; a rule installed
      for that filing rules as the producer documents a mechanical ruling — basis
      `payee_filed`, a delivery end, `stop` with `returned`, a `reverse` of earnings since
      the end, a `penalty`, and close. Step servicing and assert: the authority's stop
      recorded and classified `ruling` with no further filing, the payer returned the
      unstarted remainder and the reversed and penalised earnings, the teardown, and,
      once the case is closed, the seller's list reading the deal `ended` with no open
      extension (D6). Verify (system): the module passes in the VM lane.
      Done: `rate_dispute/test_seller_filing.py`, on its own executor, pool, resource
      and GPU model. Differs from the plan: the administrator's end is
      `admin_interrupt_deal` with `interruption_kind="failure"`, not the seller
      lifecycle client; and the rule is held at its gate while lane time moves a
      period on, so the stop is a stop now with earnings since the end, and the row
      declares the rate rows' `Reservation06` (design.md, "Implementation notes",
      section 3). The recorded end is the ruling's delivery end, the final stop the
      authority's, and no filing follows it. The ruling's `reverse`: superseded by
      section 12. System, the VM lane, `E2E_MODULE=e2e_vm_rate_dispute` — its 35
      stages pass (3.5's run).
- [x] 3.2 The buyer's contested case row: on a delivered on-demand rate deal, the buyer
      files through the mediation kit's dispute adapter in the harness, as the VM dispute
      controls do; the storefront's respondent discovery contests it; an operator
      decision through the typed control client rules `stop` with `returned` and a
      `reverse`. Assert the ruled end recorded, the payer's returns, the teardown and the
      deal `ended` once the case closes (D6, D5's policy row's lane twin). Verify
      (system): the module passes in the VM lane.
      Done: `rate_dispute/test_buyer_contested_case.py`: the buyer claims the end a
      minute into the second period; one servicing step appends the seller's answer;
      the operator decision rules a stop at the claimed end and a reverse of the held
      first period, closing the case. Both rows end with the shared teardown, the
      payer down only by what the part kept, and the seller's list `ended` with no
      outstanding code, open case or extension. System, the same run — 34 stages pass.
- [x] 3.3 Write the two dispute assertions over the producer's output — the filing's
      per-part protection; the ruled entry's basis and effects and their applied state;
      the snapshot's authority stop, reversals and lifted extensions; the closed case —
      with exact, relational and ignored fields named as in 2.1, and have both rows
      assert through them (D6). Verify (unit, `e2e-tests/tests/unit/`): each passes on a
      recorded double output and fails naming the field on an altered one.
      Done: `producer_assertions.assert_payee_filing_ruled` and
      `assert_contested_case_ruled`, over the record as the public client reads it
      (`helpers/mediation.py`'s new `read_record`, each entry verified) and the
      snapshot; both rows assert through them. Unit
      (`test_producer_dispute_assertions.py`, 13 pass, not on a committed recording:
      design.md, "Implementation notes", section 3); `read_record` against the kit's
      `MediationContractFake` (`test_mediation_helper.py`). Reversal matching:
      superseded by section 12 (12.3).
- [x] 3.4 Register the marker (`e2e_vm_rate_dispute`, lane-double evidence) in
      `e2e-tests/pyproject.toml` and the VM lane's default module list in
      `e2e-tests/Makefile`, and describe the rows in `e2e-tests/README.md` (D6). Verify
      (unit): `make -C e2e-tests test-unit` passes, `ORDERS` included.
      Done: the marker, the lane list, a "Rate-deal disputes" README section and the
      shared payment-scenario list. `test_recurring_purchase_stages.py` holds both
      modules' shared stages to their orders and handoff, and its reservation check
      now reads a module's whole run order. `make -C e2e-tests test-unit` — 1081
      passed, 1 skipped.
- [x] 3.5 Verification point: the two rows pass, leaving no payment hold, mock rule or
      held loop (system, the VM lane's Compose stack: `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_rate_dispute"`), and the whole VM lane passes.
      End-to-end: `e2e_vm_rate_dispute`.
      Nothing is owed to validation.
      Evidence: system, the command above — 69 passed, 2015 deselected; the whole VM
      lane, `make -C e2e-tests test-e2e-vm` — 513 passed, 1568 deselected; nothing
      left held, as the assertions and the cleanup fixtures show.
      `scripts/change-workflow run pre-commit` passed but for section 8's citation.

Handoff (section 3):

- For section 6's live twins: `read_record` is the public read they poll; the
  contested case's reverse amount is not compared unless given, since the topology's
  policy chooses it. The rows borrow `RateRow` from `rate_servicing/conftest.py`.
- Fresh-context check: findings fixed. Declined: a domain-stage order check and a
  `RateRow` of the rows' own (reasons in design.md, "Implementation notes", section 3).

Round 1's triage fix (28 F1): both dispute assertions take `claimed_end` and compare
the filed entry's kind (`delivery_end`) and `ended_at` with it exactly;
`assert_payee_filing_ruled` also holds the ruling's `end_delivery` to it;
`assert_contested_case_ruled` compares the ruled end only when given `ruled_end`. The
live modules pass the storefront's recorded end (seller) or the filed end with no
`ruled_end` (buyer). Evidence: unit, `test_producer_dispute_assertions.py` — 18 passed;
system, the VM lane, `E2E_MODULE=e2e_vm_rate_dispute` — 69 passed, 2020 deselected.

## 4. The VM chart's production example

Delivers `helm/charts/storefront/examples/production-values.yaml`: an agent settling in
`arkhai.payments.v1` in live mode, declaring `[charged, returned]` with `setup = false`,
and publishing an on-demand and a spot recurring clause whose payments clause sets
`delivery_deadline_seconds` and a dispute window covering it plus the authority's minimum
filing window. Implements D1 and D7; requirement "The VM storefront chart ships a
production example offering on-demand and spot" (`deployment-state`, added). Touches the
example, `helm/charts/storefront/tests/test_render.py`, and
`scripts/tests/test_committed_time_sources.py`.

- [x] 4.1 Write the example: every value a public placeholder or a well-known
      development value, no secret (the payments key and dispute credential named as
      overlay entries in comments), wall time (D1, D7;
      `docs/guidance/engineering/repository-content.md`). Verify (unit):
      `scripts/tests/test_committed_time_sources.py` lists it among the chart examples
      and passes.
      Done: the storefront chart's values installed alone; one agent in
      `arkhai.payments.v1` alone, live mode; the declaration; an on-demand and a spot
      clause, `delivery_deadline_seconds = 1800`, a fifteen-day dispute window (the
      fourteen-day minimum plus a day); no `[Time]`; every value a placeholder, the
      payments key and `[[DisputeCredential]]` named as Secret entries in the header.
      `make test-release-tooling TESTS=scripts/tests/test_committed_time_sources.py`
      — 5 passed. Examples ship with the chart, so the storefront chart and umbrella
      go 0.5.0 to 0.5.1.
- [x] 4.2 Render it and run the storefront's own loader and startup check over the
      rendered `storefront.json`, as the bare-metal chart's test does with its example
      (`helm/charts/bare-metal-storefront/tests/test_render.py`, "the storefront's own
      loader"), under `STOREFRONT_PYTHON` (requirement scenario "The production example
      is rendered"). Verify (unit, the chart render tests, `make -C helm test-render`
      with `STOREFRONT_PYTHON` set): the render succeeds and the check reports no
      problem.
      Done, in `helm/charts/storefront/tests/test_render.py` ("the production
      example"): the rendered `storefront.json` read; the startup refusal finds
      nothing; the loader reads it reporting no setting it would read otherwise. The
      refusal caught a receipt identity no Ed25519 key spells, and the loader a
      portless `base_url`; both fixed in the example.
- [x] 4.3 The publication check (18 F2): from the rendered example's loaded
      configuration, derive its recurring clauses through the storefront's publication
      path against a representative dispute authority advertisement and pool horizon
      (the payments kit's recurring-options fixture,
      `kit/arkhai-payments/src/market_arkhai_payments/fixtures/`), and assert an
      on-demand and a spot option published, each carrying the clause's deadline, a
      dispute window covering it plus the authority's minimum, and the `charged` and
      `returned` treatments, with no clause refused; then, with the example's
      `rate_servicing` removed, no recurring option published (requirement scenarios
      "The production example publishes both recurring options" and "… withdraws rate
      servicing"; continued servicing of held deals is "Rate servicing is a composition
      capability"'s existing scenario). Verify (unit, in the chart render tests): both
      cases pass.
      Done, a probe under `STOREFRONT_PYTHON` publishing each clause through the
      kit's `ClausePublication` step with no pool deadline (the VM composition
      supplies none): an on-demand and a spot option, each with the 1800-second
      deadline, the fifteen-day window and exactly `charged` and `returned`, nothing
      refused; with `rate_servicing` removed, both refused
      `rate_servicing_undeclared`. Its wiring is stated, not taken from the
      composition (design.md, "Implementation notes", section 4).
      Correction (section 7): the probe passed the fixture's day as the horizon by
      hand, which hid that the example stated none — the packaged
      `default_max_duration_seconds = 0` means unbounded, so deployed alone it
      would refuse both clauses `recurring_horizon_unbounded`. The example now
      states a day, the probe reads the configuration's default listing bounds,
      and the `deployment-state` delta names the horizon; 7.1's notes give the
      evidence.
- [x] 4.4 Verification point: the chart render tests pass with the loader and
      publication checks run, not skipped, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; the `helm` evidence kind runs these render and chart-to-loader
      checks against the tree, and no pipeline scenario reads the example.
      Nothing is owed to validation.
      Evidence: `make -C helm test-render` with `STOREFRONT_PYTHON` set (`make
      init-storefront`) — every chart's checks pass, the three example tests `ok`,
      none skipped. `scripts/change-workflow run pre-commit` passed but for section
      8's citation.

Handoff (section 4):

- For section 7's seller quickstart: the example's agent `config` is the TOML to show,
  and `_startup_refusal` with `_example_config` in the chart's render test is the
  loader check to reuse.
- For closeout's promotion: `docs/guidance/repository/chart-render-tests.md`, "Where
  they live and how they run", does not yet name the production example's startup and
  publication checks beside the bare-metal example's; it is the destination to add to
  D8.

## 5. Wall-time reach and the live payment scenarios

Delivers `LaneTime.reach`'s wall-time case and the four live payment scenarios — the
buyer's stop, funds running out, the spot preemption, the term end — each extending its
VM lane twin in the live verification form and asserting through section 2's shared
assertions, with its topology requirements in prose. Implements D4, D6 and D13;
requirements "An external-topology scenario extends a locally verifiable scenario"
(modified), "A live verification scenario compares a producer's outputs with a lane's
expectations", "Each live verification scenario states its topology requirements" and
"Rate deals and dispute filings are verified live against a prepared topology"
(`test-compatibility`, added). Touches `e2e-tests/tests/e2e/roles/helpers/lane_time.py`,
`helpers/payments.py`, a new `e2e-tests/tests/e2e/roles/scenarios/vms/live/` (conftest
and four modules), `e2e-tests/pyproject.toml`'s markers and `e2e-tests/README.md`.

Replanned after the section's return (the notes below): 5.5 and 5.6 no longer run the
live modules against the local Helm release, which serves no payment scenario and whose
payments target is lane-owned, so 5.2 refuses it by design; the deployment's run in
section 8 is the only run of the live modules, and the in-repository evidence is the
unit checks, the lane twins, and each live module refusing the lane's double.

- [x] 5.1 Give `LaneTime.reach` its admitted wall-time case: an instant an authority
      recorded as the effect of the scenario's own request, read from a signed record —
      a pending stop's effective instant, the snapshot's funded boundary — waited for
      with a bound, failing at the bound; any other instant on a wall run stays a
      blocked skip; injected runs are unchanged. Add the bounded poll of a producer's
      public read that the live scenarios use for an asynchronous output (D4, D6).
      Verify (unit, `e2e-tests/tests/unit/`): the case waits to the recorded instant,
      fails past its bound, still skips an unrecorded instant on wall time, and an
      injected run sets lane time as before.
      Done: `LaneTime.reach` takes `recorded_by_authority` and `bound`, refusing an
      instant further off than the bound before any wait; `wait_until` takes a
      `bound`; `poll_until` reads a producer's public read until a predicate holds,
      failing at its bound on the monotonic clock, naming what it waited for and the
      last read; `reach_lane_instant` passes both through for a run with no lane time.
      Unit (`test_lane_time.py`, fake parties and clocks, and `reach_lane_instant`'s
      no-lane-time path) — 41 pass.
- [x] 5.2 Read the live scenarios' period, payee notice and maximum term from run
      settings, defaulting to the lanes' values (D4), and have the live modules refuse a
      lane-owned payments target with a blocked skip naming it, since a double yields no
      live evidence. Verify (unit): the settings parse and default, and a lane-owned
      target skips.
      Done: `helpers/live_verification.py` reads the `LIVE` settings (defaults 900,
      120, 3600 and a 120-second poll bound), failing values it can see are wrong,
      and the provenance SOURCE_REVISION, TARGET_ALIAS and PAYMENTS_REVISION, each
      missing one a blocked skip. `payments.live_payments` refuses a lane-owned target
      first. Unit (`test_live_verification.py`, `test_payments_helper.py`) — pass.
- [x] 5.3 Write the four modules, marker `e2e_vm_live_rate_servicing` in no lane: each
      runs its lane twin's shared stages against the external payments target until the
      producer's output, reads it by the bounded poll, asserts through section 2's
      assertion, and runs no stage after (D6). Funds running out reads the payer's
      starting balance against the N periods its requirements state and skips naming
      the requirement when it differs; the preemption reads the pending stop's effective
      instant; the term end reaches the Agreement's end (D4). Each logs the live-evidence
      label with public-safe provenance — source revision, target alias, the authority's
      revision identifier, provisioning mode — and the identifiers each stage reads.
      Verify (unit): `make -C e2e-tests test-unit` passes, `ORDERS` and the shared-stage
      checks included.
      Done: the shared stages read the per-period terms from the driver
      (`RecurringPurchaseDriver.rate_terms`); the buyer's end and the seller's notice
      are factored out of `Recurring08` and `Preemption07`. Four modules under
      `scenarios/vms/live/` run their twin's shared stages through `Stage09c2`, then
      `live/stages.py`'s: `Live00` logs the label and provenance; each observation
      polls the snapshot and asserts through section 2's assertion. Funds running out
      requires exactly three periods' balance and a longer term, reading the boundary
      from `reservedThrough`. Each module declares `OBSERVATIONS`. Prerequisites are
      `live/conftest.py` fixtures set up before any hold, each unmet one a blocked
      skip naming it (design.md, "Implementation notes", section 5). `make -C
      e2e-tests test-unit` — 1151 passed, 1 skipped, `ORDERS` and the new
      prerequisite-order check included. The live stages run only against a hosted
      target (section 8). Outside the plan's "Touches" line: the shared stage
      modules, both domains' purchase drivers, `host_registry.py`,
      `rate_servicing/conftest.py`, the Makefile's lane comment, `qualification.py`
      and `tests/unit/test_scenario_cleanup_order.py`.
- [x] 5.4 Write each module's topology requirements in prose beside its description
      under a "Live verification" heading in `e2e-tests/README.md`: what it proves,
      mock provisioning, Arkhai payments in test mode executing rate parts, its accounts
      and starting balances, the run settings it reads, and the balance reset and
      cleanup its caller owes between runs; naming no infrastructure (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` passes.
      Done: `e2e-tests/README.md`, "Live verification": what the modules prove, the
      inputs and compared outputs, and the topology requirements in prose, naming no
      deployment; the payment-scenario list names the marker. `make
      check-doc-citations` reports only section 8's summary.
- [x] 5.5 Show the live modules inert on a lane: collected in the VM lane, each refusing
      the lane's payments double at its first live fixture with a blocked skip naming
      the lane-owned target, logging its observation unproven with that reason, and
      running no stage after; the lane twins on the shared stages passing beside them
      (D6; `test-compatibility`, "A live verification scenario compares a producer's
      outputs with a lane's expectations": a double yields no live evidence). Verify
      (system, the VM lane's Compose stack): `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_recurring_purchase or e2e_vm_rate_servicing or
      e2e_vm_rate_dispute or e2e_vm_live_rate_servicing"` passes, every skip a live
      module's refusal naming the lane-owned target; the bare-metal lane's recurring and
      rate rows pass on the shared stages the section changed.
      Done. System, the VM lane's Compose stack, the command above — 190 passed, 110
      skipped, 1964 deselected: every skip a live module's stage at `payments_config`,
      `blocked: the payments target https://payments-double:8443 is a lane's own
      double (PAYMENTS.LANE_OWNED), which yields no live evidence`, each observation
      logged unproven with that reason. System, the bare-metal lane's
      Compose stack, `make -C e2e-tests test-e2e-bare-metal
      "E2E_MODULE=e2e_bare_metal_recurring_purchase or e2e_bare_metal_rate_servicing
      or e2e_bare_metal_rate_watchdog"` — 249 passed.
- [x] 5.6 Verification point: the `e2e-tests` unit suite passes, 5.5 holds, the whole VM
      lane passes, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` reports no failure but the citation of section 8's
      summary.
      End-to-end: none in the pipeline — `e2e_vm_live_rate_servicing` belongs to no lane,
      and its evidence is the deployment's (section 8); the lane twins are
      `e2e_vm_recurring_purchase` and `e2e_vm_rate_servicing`.
      Nothing is owed to validation.
      Evidence: unit, `make -C e2e-tests test-unit` — 1151 passed, 1 skipped. The
      whole VM lane, `make -C e2e-tests test-e2e-vm` with `e2e_vm_live_rate_servicing`
      added — 513 passed, 110 skipped (the live modules' refusals), 1633 deselected,
      before the fresh-context fixes, which touched the lane's shared stages only in
      docstrings and one message; the live modules' final code ran in 5.5.
      `scripts/change-workflow run pre-commit` passed but for section 8's citation.

Handoff (section 5):

- The section returned to planning once; why the live modules cannot run against the
  local Helm release is in design.md, "Implementation notes", section 5.
- For closeout's promotion of D4 (14.9): `docs/guidance/repository/deal-scenarios.md`,
  "The discipline every scenario follows" (the wall-time bullet), and
  `docs/development/TESTING.md`, "Lane time", still say a wall-time run waits only for
  an instant the Agreement fixes; both are destinations to add to D4's promotion.
- The rate rows', watchdog row's and rate dispute rows' lane-only stages still read
  `PERIOD_GROSS` and `PERIOD_SECONDS`, holding them to the lanes' period.
- Fresh-context checks (two): findings fixed. Declined, with reasons in design.md,
  "Implementation notes", section 5: a stale funded boundary, and unifying
  `HOURLY_GROSS`.

Fix from the sections 5–7 round's triage (`reviews/41-implementation.triage.md`,
41 F1, outside the plan): the buyer's-stop observation could pass with nothing charged.
`assert_payer_stop` now also requires the stop effective later than the part's
`started`; `LiveBuyerStop` sends the stop no earlier than `STOP_INTO_PERIOD_SECONDS`
after the Agreement's start (`reach_lane_instant(fixed_by_agreement=True)`), failing
naming LIVE.MAXIMUM_TERM_SECONDS when that instant is not before the Agreement's end
(design.md, "Implementation notes", section 5). For closeout's promotion of
D4 and D6 (14.9): `deal-scenarios.md` and `TESTING.md`, "Lane time", admit on wall time
"an instant the deal's Agreement fixes, such as its start", which does not literally
cover the Agreement's start plus the scenario's own minute, though the delta's "its own
data fixes" and `system-tests.md` do; the promoted wording should cover it. Unit:
`test_producer_assertions.py`'s new case, a payer stop in the start second failing
(evidence in section 7's round note). The live stage's wait runs only against a hosted
target (section 8).

## 6. The live dispute scenarios

Delivers the two live dispute scenarios — the seller's filing, and the buyer's contested
case ruled by a topology's declared policy — each extending its section 3 twin in the
live verification form through the public mediation and payments clients, with its
topology requirements in prose. Implements D5, D6 and D13; requirements "Rate deals and
dispute filings are verified live against a prepared topology" and "Each live
verification scenario states its topology requirements" (`test-compatibility`, added).
Touches `e2e-tests/tests/e2e/roles/scenarios/vms/live/` (two modules),
`e2e-tests/pyproject.toml` and `e2e-tests/README.md`.

Replanned after section 5's return: 6.4 and 6.5 no longer run the modules against the
local Helm release, for section 5's reasons and because the release's e2e pods hold no
control token for its mediation double; section 8 is their only run.

- [x] 6.1 The seller's filing module: the storefront's own payee filing on a running
      rate deal, sent by its journal through the mediation kit's adapter as in 3.1; read,
      by bounded polls of the public record and snapshot reads, the per-part protection,
      the authority's ruled entry, the authority stop, reversals, penalty, lifted
      extensions and closed case, and assert through 3.3's assertion. No operator
      endpoint is called (D5, D6). Verify (unit): the module's stages pass the order and
      shared-stage checks.
      Done: `scenarios/vms/live/test_seller_filing.py`, marker `e2e_vm_live_dispute`:
      the twin's shared stages, then `Live00` (adding LIVE.MEDIATION_REVISION);
      `LiveDispute07` (the Agreement must pin the run's authority, else a blocked
      skip; a bounded poll until the first period's earnings are held);
      `LiveSellerFiling09` (the failure end; a missing dispute credential a blocked
      skip); `LiveSellerFiling10` (the record polled until closed, the snapshot read
      once, `assert_payee_filing_ruled`). One poll, not two as planned (design.md,
      "Implementation notes", section 6). The inputs are functions in
      `rate_dispute/stages.py` shared with the lane row. `live_mediation` refuses a
      lane-owned mediation target and a run with no MEDIATION.BUYER_API_KEY before
      anything is bought. `make -C e2e-tests test-unit` — 1184 passed, 1 skipped. The
      live stages' bodies run only against a hosted target (section 8).
- [x] 6.2 The buyer's contested case module: the buyer's filing through the mediation
      kit's adapter, the storefront's contest, then the ruling the topology's declared
      policy makes, read and asserted through 3.3's assertion; with no policy applied by
      the bound, the ruling observation is unproven naming the policy requirement, its
      filing and contest observations standing (D5, D13). Verify (unit): as 6.1, and the
      unproven outcome names the requirement.
      Done: `live/test_buyer_contested_case.py`, observations `the buyer's filing`,
      `the storefront's contest` and `the policy's ruling`: file, contest in one
      servicing step, then `await_case_closed` with `RULING_POLICY_REQUIREMENT` and
      `assert_contested_case_ruled` with no `ruled_end` or `reverse_amount`. The poll
      skips naming the requirement only when the case has no `ruled` entry at the
      bound; a ruling with the case open, or a failing read, fails. Unit
      (`test_live_verification.py`) — pass. Not exercised here: the stage passing the
      requirement, and the cleanup in the last stage's teardown (design.md,
      "Implementation notes", section 6).
- [x] 6.3 Register the marker `e2e_vm_live_dispute`, in no lane, and write both modules'
      topology requirements in prose under "Live verification" in `e2e-tests/README.md`:
      a hosted mediation authority serving filing, the respondent listing and record
      reads, the contested case's ruling policy in this repository's own words (a
      buyer's contested `delivery_end` ruled with a `stop returned` and a reverse), the
      accounts, settings, and the cleanup its caller owes — closing any case left
      awaiting an operator and resetting balances (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` and
      `make -C e2e-tests test-unit` pass.
      Done: the marker, in no lane, and under "Live verification" the inputs and
      outputs and the topology requirements — the storefront's dispute credential,
      the recommended authority, a hosted `arkhai.mediation.v1` authority in test
      mode (its mechanical ruling the output compared, not a requirement), the ruling
      policy as the assertion holds it, accounts, settings, and what the caller owes.
      The credential's handling: corrected by 41 F2 (the note after the handoff
      below). `make check-doc-citations` reports only section 8's summary; `make -C
      e2e-tests test-unit` — 1184 passed, 1 skipped.
- [x] 6.4 Show both modules inert on a lane, as 5.5 does: collected in the VM lane, each
      refusing the lane's doubles at its first live fixture with a blocked skip naming
      the lane-owned target, logging its observations unproven with that reason, and
      running no stage after; the lane twin `e2e_vm_rate_dispute` passing beside them
      (D6). Verify (system, the VM lane's Compose stack): `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_rate_dispute or e2e_vm_live_dispute"` passes, every skip a live
      module's refusal naming the lane-owned target.
      Done. System, the VM lane's Compose stack, the command above — 69 passed, 59
      skipped, 2228 deselected: every skip a live module's stage refused at
      `payments_config` as lane-owned, every observation logged unproven with that
      reason. The mediation target's refusal is unit-tested (`live_mediation`).
- [x] 6.5 Verification point: the `e2e-tests` unit suite passes, 6.4 holds, the whole VM
      lane passes, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` reports no failure but the citation of section 8's
      summary.
      End-to-end: none in the pipeline — `e2e_vm_live_dispute` belongs to no lane; its
      lane twin is `e2e_vm_rate_dispute`.
      Nothing is owed to validation.
      Evidence: unit, `make -C e2e-tests test-unit` — 1184 passed, 1 skipped. The
      whole VM lane, `make -C e2e-tests test-e2e-vm` with both live markers added —
      513 passed, 169 skipped (the six live modules' refusals), 1669 deselected,
      before the fresh-context fixes, which the lane twins' final run in 6.4 covers.
      `scripts/change-workflow run pre-commit` passed but for section 8's citation.

Handoff (section 6):

- Outside the plan's "Touches" line: `rate_dispute/stages.py` (the shared input
  functions), `live/stages.py`, `live/conftest.py`, `helpers/mediation.py`,
  `helpers/live_verification.py`, `helpers/lane_time.py` (`PollBoundPassed`),
  `host_registry.py`, the Makefile's lane comment, and four unit files.
- If the hosted payments service refuses the buyer's own `end` with the case open, the
  contested ruling reads failed rather than unproven; a deployment seeing it records it
  beside the summary.
- For closeout's promotion of D6 (14.9), "bounded polling of a live producer for an
  effect of the scenario's own request": `LiveDispute07`'s wait for the first
  period's earnings is such a poll, bounded by up to a whole period plus the poll
  bound, with no instant reached; `system-tests.md`, `deal-scenarios.md` and
  `TESTING.md`, "Lane time", admit on wall time only an instant the scenario's
  data fixes, so the promoted paragraph should cover a poll whose bound outlasts
  the poll bound by the producer's own schedule.
- Fresh-context checks (two): findings fixed; the one declined finding (skipping the
  contest on a missing credential) was since made by 41 F2.

Fix from the sections 5–7 round's triage (`reviews/41-implementation.triage.md`,
41 F2, outside the plan): a storefront with no dispute credential failed the contest
rather than leaving it unproven. `LiveContestedCase09` now reads the deal's lifecycle
first, and `storefront_credential_missing` makes it a blocked skip naming
`CREDENTIAL_REQUIREMENT`, the contest and ruling unproven and the filing standing; the
seller's filing's skip names the same requirement; the delta is unchanged. Unit
(`test_live_verification.py`) — pass. Proven against a hosted storefront only at
section 8.

## 7. What sellers, buyers and storefront operators are told

Delivers the seller and buyer quickstart sections and the storefront operator's runbooks.
Implements D1, D7, D10 and D11. Touches `docs/seller-quickstart.md`,
`docs/buyer-quickstart.md` and `docs/operator-handbook.md`.

- [x] 7.1 `docs/seller-quickstart.md`, a new section "Offering on-demand and spot": the
      on-demand and spot recurring clauses, the declaration `[charged, returned]` with
      `setup = false`, the clause's `delivery_deadline_seconds` and a dispute window
      covering it plus the authority's minimum, withdrawal by removing the table, and
      payout timing — at the earliest the part's stop plus the dispute window plus the
      payments service's payout delay, 7 days in live mode by that service's
      documentation; pointing at the chart's production example (D1, D7, D10). Verify:
      the TOML shown parses as the storefront's settings (the same loader as 4.2) and
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` passes.
      Done: the section, after "6. Preview and publish", shows one TOML block (the
      declaration, `[pricing]` with its horizon, the two clauses), then the term,
      penalty, deadline (linking the handbook's runbook), window, payout,
      `deals preempt` and withdrawal. Verified by a render test, outside the plan's
      "Touches" line:
      `test_the_seller_quickstart_shows_the_production_examples_rate_servicing`
      (`helm/charts/storefront/tests/test_render.py`) holds the block equal to the
      example's tables, loads it through the storefront's loader and publishes both
      options through 4.3's probe. Static configuration test, `make -C helm
      test-render` — every check passes. `make check-doc-citations` reports only
      section 8's summary; the new links were checked by hand. Outside the plan, two
      defects fixed: the example's missing horizon (4.3's correction; the chart stays
      0.5.1), and the quickstart's once-only clause ("2. Configure") lacking the
      required `dispute_window_seconds`, now stated with a deadline (evidence: the
      code read only).
- [x] 7.2 `docs/buyer-quickstart.md`, a new section on on-demand and spot options: the
      default refusals and the waiver for each, approval refused when the balance cannot
      cover the first reservation, a top-up before the funded boundary keeping a deal
      running and after it a new deal, the premature-stop penalty collectible only from
      the seller's earnings still held, and the dispute remedy a case (D10). Verify: each
      command and flag shown is in the installed `market --help` output, and the
      citations check passes.
      Done: "7. On-demand and spot", after "6. Service and reclaim": buying a
      recurring option, the default refusals and waivers, funding, `market end` and
      `--end-now-regardless` (which files the buyer's `delivery_end`), `buy
      --watchdog` with its conditional bound, the penalty, and a case as the remedy.
      Commands and flags checked against the CLI's source, not `market --help`, which
      the session could not run; no test runs them. New unowned row in Goal 8's table
      (`docs/development/ROADMAP.md`): a buy the default refusals alone empty exits 0
      (design.md, "Implementation notes", section 7). `make check-doc-citations` —
      only section 8's summary.
- [x] 7.3 `docs/operator-handbook.md`, a new section for a storefront serving rate deals:
      truncating a lease abandoned before delivery and monitoring committed reservations
      still unactivated past their deadline, through the storefront's and the site's
      existing operator interfaces; draining running payment deals before a receipt key
      change (`settlement-configuration`'s "A receipt identity change is a cutover");
      and what a seller operator sees for each dispute outcome — the recorded end, the
      `ending` codes, a ruled end with no stop left `ending` with its payment running as
      the authority's to correct — linking the dispute authority's policy where it is
      published, hosting none of it (D7, D11). Verify: each command and route named
      exists (`--help`, the storefront's route table), and the citations check passes.
      Done: "Serving rate deals", after "Payments access": "Leases the storefront has
      not delivered", "Draining payment deals before a receipt key change" and "What
      each dispute outcome shows" (the ruled end with no stop left `ending` with
      `payment_running`). Differs from the plan: it links no published policy, none
      being known here, and points at the authority description's `contact`. Outside
      the plan: `settlement-configuration/configuration.md` now says a retiring
      receipt identity requires `valid_until`, as `receipts.py` enforces. Routes and
      commands checked in the route tables and CLI source (no `--help` run); no test
      runs them. `make check-doc-citations` — only section 8's summary.
- [x] 7.4 Verification point: `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; documentation.
      Nothing is owed to validation.
      Evidence: `scripts/change-workflow run pre-commit` passed but for section 8's
      citation, the functional hooks running the chart render tests with 7.1's
      quickstart test `ok`.

Handoff (section 7):

- The handbook's "Serving rate deals" is the runbook `renewable-compute-lease-deadlines`
  retires in part (its abandoned-lease and unactivated-reservation subsection); the
  seller quickstart links it as `operator-handbook.md#serving-rate-deals`.
- For closeout's promotion (14.9): D7's quickstart and D10/D11's documents are written
  here. D11's `deal-lifecycle/architecture.md` "Current limits" sentence and D1's caveat
  corrections stay closeout's, and the caveats wait for section 8's evidence (D3);
  `settlement-configuration`'s companion still says no shipped configuration declares
  rate servicing, which 14.9's D1 corrects.
- For 14.5: the buyer quickstart states that `market` files no case on a running deal
  but the surrender `end --end-now-regardless` makes, Goal 8's existing unowned row;
  and that a buy its default refusals alone empty says nothing and exits 0, the new
  unowned row.
- Fresh-context checks (two): findings fixed. Declined, with reasons in design.md,
  "Implementation notes", section 7: the payments service's own facts in the
  quickstarts, and how a refused approval surfaces.

The sections 5–7 round's triage (`reviews/41-implementation.triage.md`; validation 42
passed at `68b5566e4`, the owner's notes 43 had none) fixed 41 F1 and 41 F2, each
recorded in the notes of the section it concerns (5 and 6). Evidence for the fix
commit: unit, `make -C e2e-tests test-unit` — 1190 passed, 1 skipped;
`scripts/change-workflow run pre-commit` passed but for section 8's citation. Declined
at the fresh-context check: listing the buyer's stop's LIVE.MAXIMUM_TERM_SECONDS failure
in the README's settings paragraph — the market refuses any term short enough to meet
it.

## 8. Live verification evidence

Delivers the deployment's sanitized live verification summary in the change, and the
check that D3's threshold is met. Implements D3 and D9; requirement "Rate deals and
dispute filings are verified live against a prepared topology" (`test-compatibility`,
added). This section waits for the deployment: it reads the requirements written in
sections 5 and 6, prepares a topology meeting them, runs `e2e_vm_live_rate_servicing`
and `e2e_vm_live_dispute` at the branch's code, and records its summary. Touches
`docs/attachments/switch-on-hosted-per-period-vm/`.

- [x] 8.1 Receive the deployment's summary at
      `docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`: per
      observation, made, failed or unproven, with public-safe provenance — source
      revision, target alias, authority revision identifiers, provisioning mode — no raw
      log, record, endpoint, account identifier or credential, and whether D3's
      threshold is met (D9; `docs/guidance/engineering/system-tests.md`, "Locally
      verifiable and external-topology scenarios";
      `docs/guidance/engineering/repository-content.md`). Verify: the public-content
      checks pass in `scripts/change-workflow run pre-commit`, and the source revision
      is the branch's code at the run.
      Done: received for the run of 2026-11-23 at source revision `3b12f82ea`, the
      branch's code at the run. Its authority revision is an opaque build label, since
      a public repository holds no private commit identifier; the deployment holds
      what it identifies. Before it, a rehearsal against the hosted dispute authority
      found the seller filing's ruling shaped differently from the lane twin's, which
      section 12 corrected.
- [x] 8.2 Confirm the threshold (D3): the buyer's stop, funds running out, the spot
      preemption, the term end and the seller's filing each made; the buyer's contested
      case made, or unproven naming the requirement it lacked. A failed comparison
      returns the change to design with the evidence (D14); an unproven required
      observation holds the change here for the deployment to meet the requirement it
      names, or, on the owner's word, returns it to design (D3). Verify: the summary
      states each of the five made.
      Done: the buyer's stop, funds running out, the spot preemption, the term end and
      the seller's filing are made. The buyer's contested case has its filing and the
      storefront's contest made and the policy's ruling unproven, naming the ruling
      policy the topology lacks, for closeout to record as the Goal 8 gap D3 names.
- [x] 8.3 Verification point: 8.1 and 8.2 hold.
      End-to-end: `e2e_vm_live_rate_servicing`, `e2e_vm_live_dispute`, run by the
      deployment, not by the pipeline.
      Nothing is owed to validation.

## 9. The payments kit's local example names only what a client knows

Delivers a local example, and the documents around it, that ask of the payments
service only what any client of it has: its origin, its pinned public receipt
identity, an authentication it admits, and accounts its operator has prepared. Until
now the example derived the service's receipt identity from the service's own
signing seed. Its README started the service with the service's own internal
settings and funded accounts through the service's operator route, none of which is
a client's to give. Implements no design decision. This is a
defect fix outside the stated scope, taken in at the owner's direction
(`docs/guidance/workflow/changes.md`, "Defects found during a change"). Touches
`kit/arkhai-payments/examples/local_e2e.py`, `kit/arkhai-payments/README.md`,
`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py` and `client.py`
(a comment, a docstring and a message),
`docs/seller-quickstart.md` and `domains/vms/buyer/src/arkhai_vms_buyer/config_cli.py`
(a placeholder each).

- [x] 9.1 `examples/local_e2e.py` takes the service's public receipt identity from
      `PAYMENTS_SERVICE_IDENTITY`, the canonical unpadded base64url Ed25519 public key
      a role states as `service_identity.identifier`. It verifies receipts against
      that pinned identity, as a client configured by `ArkhaiPaymentsConfig` does, and
      no longer reads or decodes a signing seed. It still refuses a non-loopback
      `PAYMENTS_URL` and still authenticates with `development_account`. Verify: the
      example passes against a local payments service that admits header identity,
      given that service's public identity alone (9.4). A wrong identity fails
      receipt verification.
      Done: the identity is read and checked before any request. Against a local
      service it passed with the service's identity; another well-formed key exited
      "service receipt did not verify against this Agreement"; a malformed and an
      unset value each exited with their own message before any request.
- [x] 9.2 `README.md`, the local example's section, states the example's inputs as a
      client's:
      - a loopback `PAYMENTS_URL`;
      - the service's public identity in `PAYMENTS_SERVICE_IDENTITY`;
      - a service that admits `development_account`'s header identity;
      - the payer funded for the fixture amount and the payee an existing ledger party,
        both prepared by whoever runs the service.
      Starting such a service, and preparing its accounts, is left to the service's
      own documentation. The section names none of the service's settings, ports,
      tokens, operator routes or ledger commands. Verify: the section's commands are
      the ones 9.4 runs, and it names no service setting.
      Done: the run command takes the port and the identity as quoted placeholders;
      the optional `PAYMENTS_FEE_BPS` and `ARKHAI_DISPUTE_AUTHORITY` are listed as
      client inputs (9.4 ran with both unset).
- [x] 9.3 The documents that describe header identity, receipt modes or a pinned
      identity describe them as a client sees them:
      - `README.md`'s `development_account` and `development_auth` paragraphs describe
        a header identity that only a service admitting it accepts, not the service's
        development mode or authenticator.
      - `settlement_config.py`'s `livemode` comment says a live service signs `true`
        and any other signs `false`, naming no other service mode.
      - The `service_identity` placeholder in `docs/seller-quickstart.md` and in the
        buyer's configuration template (`config_cli.py`) names the service's public
        receipt identity, not its signing key.
      Verify: no document, comment or message in the kit, the quickstart or the
      template names an internal mode of the payments service (a development or mock
      mode) or its signing key. Test and live, which a client sees as a receipt's
      `livemode` and as a deployment it is pointed at, stay. The storefront
      chart's quickstart render test still passes.
      Done: also `client.py`'s `PaymentsClient` docstring and its HTTPS refusal
      message. No test reads either string or either placeholder.
- [x] 9.4 Verification point: the example passes against a local payments service, and
      `scripts/change-workflow run pre-commit switch-on-hosted-per-period-vm` passes.
      End-to-end: none; no scenario runs the example.
      Nothing is owed to validation.
      Evidence: the example, run as 9.2 shows against a local payments service
      admitting header identity, printed "approved, receipt verified, Agreement
      deposited, and reversed", and failed as 9.1 records otherwise.
      `scripts/change-workflow run pre-commit` passed but for section 8's citation;
      one earlier run failed a storefront integration test,
      `test_delivery_recovery_loop.py::test_a_deal_whose_evidence_fails_its_re_check_is_not_driven`
      (`negotiate/new` answered 409), which passed five runs alone and the next full
      run; nothing in this section reaches the storefront.

Handoff (section 9):

- The section was recorded as a round of its own by the owner (log seq 79 and 80)
  while section 8 waited for the deployment.
- For closeout: section 9 changes no capability's behaviour, so 14.9 promotes nothing
  from it. The kit README and the quickstart are already the permanent documents.

## 10. The live harness reaches a topology's authority through a configured proxy

Delivers a run setting through which the live dispute scenarios reach a mediation
authority whose origin resolves only inside its topology. Until now the harness
dialled MEDIATION.SERVICE_URL itself, which must equal the origin the Agreement pins,
so a run outside the topology could reach the authority only by changing how the
runner's machine resolves names. The owner directed on 2026-11-23 that the tests be
configurable instead, through a proxy the run reaches by a port forward. Implements
no design decision; it serves section 8's run (`docs/guidance/workflow/changes.md`,
"Defects found during a change"). Touches
`e2e-tests/tests/e2e/roles/helpers/mediation.py` and `payments.py`, their unit
tests, and `e2e-tests/README.md`, its `MEDIATION` settings and "Live verification".

- [x] 10.1 MEDIATION.PROXY_URL names an HTTP proxy for the mediation target. With it:
      - the readiness probe asks the target's `/health` through that proxy alone,
        still ignoring environment proxies (`target_ready`'s `proxy`);
      - the harness's own mediation client, for the buyer's filing and the record
        reads, goes through it, verifying the target's certificate under
        MEDIATION.CA_BUNDLE_PATH when one is set (`target_transport`);
      - the buyer processes the harness starts receive it as their `HTTPS_PROXY`,
        both cases, with `NO_PROXY` covering loopback, so every HTTPS request they
        make outside loopback goes through it (`buyer_mediation_environment`);
      - an unready target is named with the proxy it was asked through.
      MEDIATION.SERVICE_URL stays the pinned origin, compared with the Agreement's
      authority as before. Without the setting nothing changes. Verify: unit tests,
      each failing once its behaviour is removed.
      Done: six tests in `test_mediation_helper.py` and two in
      `test_payments_helper.py`, each failing with its behaviour removed; restored,
      the two files pass (81). A fresh-context check ran a local TLS origin behind a
      CONNECT proxy: the transport tunnels and verifies the certificate under the
      bundle.
- [x] 10.2 `e2e-tests/README.md`: the `MEDIATION` settings list names PROXY_URL, and
      "Live verification"'s run settings say where it applies (an origin resolving
      only inside the topology), what the harness and the buyer processes do with it,
      and that SERVICE_URL and its certificate stay the pinned origin's. Verify: the
      paragraphs name no deployment.
- [x] 10.3 Verification point: 10.1 and 10.2 hold. Section 8's run uses the setting.
      Nothing is owed to validation beyond the unit tests.

## 11. Mock provisioning mounts no SSH key

Delivers a provisioning chart that asks a deployment running mock provisioning for
no SSH key. Until now the chart mounted the Secret `sshKey.secretName` names and
required it whatever the mode, though the mock runner opens no connection. A
deployment preparing section 8's topology had to create an SSH key no host trusts
to satisfy it. Implements no design decision. This is a defect fix outside the
stated scope, taken in at the owner's direction on 2026-11-23
(`docs/guidance/workflow/changes.md`, "Defects found during a change"). Touches
`helm/charts/provisioning/` (its Deployment, helpers, values, schema, render tests
and version), the umbrella's `helm/values.yaml`, `helm/values.schema.json` and
`Chart.yaml` pin, its render test `helm/scripts/test-render.sh`, the local
topology's `helm/Makefile`, `helm/scripts/topology-secrets.sh` and `helm/bare-metal-release-values.yaml`, and
`docs/development/DEPLOYMENT_AND_CONFIG.md`, `docs/development/VALIDATION_RUNBOOK.md`
and `docs/guidance/repository/chart-render-tests.md`.

- [x] 11.1 With `mockMode: true` the provisioning Deployment mounts no SSH key and
      reads no Secret for one, and both schemas accept an empty or absent
      `sshKey.secretName`. The umbrella's values name no SSH key Secret. With real
      provisioning the key is mounted as before, and an empty or missing name is
      refused by name, by the umbrella's schema, the subchart's schema and the
      template. `mockMode` is a boolean in both schemas.
      Verify: the provisioning service reads no key in mock mode; render tests for
      both modes, each failing once its behaviour is removed.
      Done: under the `mock` profile each domain's runtime selects
      `MockAnsibleRunner`, `container.py` gives the connectivity probe the mock
      runner, and `config-mock.yml` sets both playbook paths to `/dev/null`, so no
      startup path or probe opens the key; `/system/status` lists key files for
      information only. Three subchart render tests (mock mounts nothing for a
      default, empty or null name; real mounts the key in the application container
      only, mode 0400; real refuses an empty or null name) and three umbrella checks
      in `test-render.sh`, each failing with its guard reverted. The template's
      `required` is a backstop the schemas reach first.
- [x] 11.2 The local Helm topology, whose provisioning releases all run mock, no longer
      creates `arkhai-provisioning-ssh`. Its placeholder key variable and messages
      are gone. The Compose lane's placeholder mount stays. The documents that
      describe the chart's secrets say the key is mounted only when provisioning is
      real, and where a real release's key goes. Verify:
      `test_topology_secrets_creates_every_secret_both_releases_read` and
      `make -C helm test-render` pass.
- [x] 11.3 The provisioning chart is versioned 0.1.3, and the umbrella pins it. The
      umbrella stays at the 0.5.1 this branch already bumped it to. Verify:
      `make check-version-bumps` and `test_subchart_pins.py` pass.
- [x] 11.4 Verification point: 11.1–11.3 hold. `helm lint` and `helm template` of the
      umbrella with `local-values.yaml`, and with release 2's values, render no SSH key.
      With `provisioning.mockMode=false` the key is mounted, and an empty name is
      refused. Nothing is owed to validation beyond the render and release-tooling
      tests.

## 12. The mechanical ruling's shape matches the dispute authority's

Delivers a lane twin, a mediation double and a shared assertion that hold a seller's
filing to the ruling the dispute authority actually makes. A live rehearsal against
the hosted dispute authority found the seller's filing ruled with a delivery end, a
`stop` returning its period and the premature-stop `penalty`, and no `reverse`
effect: the authority reverses what the part earned since a passed stop time as that
stop's own reversal, attributed to the stop, as its documentation of a stop effect
states. The lane twin's rule, the double and `assert_payee_filing_ruled` instead
modelled a `reverse` effect of its own, and the assertion took the first reversal for
it, so the live observation failed though the authority behaved as documented. Amends
D6 at the owner's direction on 2026-11-23 (workflow seq 88): the double applies a
passed stop's reversal, and the mechanical ruling carries no `reverse`. Touches
`tools/mediation-lane-double/` (`service.py`, its README and tests), the
test-compatibility delta, design D6,
`e2e-tests/tests/e2e/roles/helpers/producer_assertions.py`, `rate_dispute/stages.py`,
`live/stages.py` and `live/test_seller_filing.py`, their
unit tests (`test_producer_dispute_assertions.py`, `test_live_verification.py`), and
`e2e-tests/README.md`.

- [x] 12.1 The mediation double applies a `stop` whose time has passed as a stop now
      and, once payments accepts it, one `reverse` of the earnings beyond what a stop
      at the ruling's time would have earned under its partial-period rule, as far as
      the part still holds them, carrying the stop's effect id under a key beneath the
      stop's; none when nothing is beyond it, and none for a stop requested at its
      time or not recorded. The reversal is derived once and kept, and resent as it
      was after a payments failure. Explicit `reverse` effects stay, for operator
      decisions. Verify: integration and unit tests, each failing once its behaviour
      is removed.
      Done: `stop_reversal_amount` derives the amount; `_apply` sends the stop's
      events, then derives the reversal once, kept under `<effect id>:since` in
      `Case.events` (empty when none); `_send` sends a kept list (design.md,
      "Implementation notes", section 12). Integration and unit tests for a passed
      stop with and without a period earned since, a stop not yet reached, a refused
      reversal resumed without a second stop, a lost answer resent as it was, and the
      amount's cases — each failing with its behaviour removed. The guard on a stop
      payments has not recorded has no test. The double's suite passes.
- [x] 12.2 The lane twin's seller filing (`SellerFiling08`) rules a delivery end, the
      `stop` at that end with `returned` and the `penalty`, with no `reverse`;
      `SellerFiling10` still lets the part earn a period after the end, so the stop's
      reversal is that period and the penalty takes what is held after it, the same
      money as before. The buyer's contested case (`ContestedCase10`) is unchanged:
      its operator's stop is at the claimed end, the lane instant no stage has moved
      since, so the stop's time has not passed and it brings no reversal; the
      operator's own `reverse` of the held first period is the only one, as the
      dispute authority would apply that decision. Verify: the stages' docstrings say
      so; the VM lane's `e2e_vm_rate_dispute` passes.
      Owed: validation (`e2e_vm_rate_dispute`).
- [x] 12.3 `assert_payee_filing_ruled` expects the effects `end_delivery`, `stop` and
      `penalty`, and matches each authority reversal to the ruling's effect whose id
      its payload names, summing each effect's: the stop's, the periods earned after
      the delivery end up to the stop at the period price, or nothing; the penalty's,
      the Agreement's penalty capped at what the part held after the stop's reversal;
      and none attributed to anything else. `assert_contested_case_ruled` matches its
      reversals the same way, the reverse effect's amount to the reverse, and takes
      the period's price and length for the stop's. Verify: unit tests on outputs
      shaped as the doubles emit them, including the hosted shape: a ruling applied
      within the end's period, with no stop reversal and one penalty reversal.
      Done: `_reversals_by_effect` groups the reversals and `_reversal_checks`
      compares each effect's sum; the live contested stage passes the run's rate
      terms. Unit tests for both penalty timings, a split stop reversal, and each
      misattribution failing naming its check, each failing with its behaviour
      removed. The e2e unit suite passes.
- [x] 12.4 D6, the test-compatibility delta's mediation double requirement (with a
      scenario for a passed stop) and its live and lane rows, the double's README
      (dropping the deviation that a passed stop brings nothing more),
      `e2e-tests/README.md`'s rate-dispute and live tables and the live ruling
      requirements, and closeout's promotion list (14.9) describe the stop's
      reversal and the ruling's three effects. Verify: `scripts/openspec validate
      switch-on-hosted-per-period-vm --strict`; no permanent document still describes
      a `reverse` effect in a mechanical ruling.
- [x] 12.5 Verification point: 12.1–12.4 hold. Section 8's run asserts the seller's
      filing through the amended assertion. Owed to validation:
      `e2e_vm_rate_dispute`.

## 13. A live run's buyer CLI

Delivers instructions for the buyer's `market` that work on a branch whose package
versions are unpublished. Until now the harness's skip message and docstring advised
`cd domains/vms/buyer && uv sync`, which resolves against published packages and
fails when the branch's kits are newer; the same live rehearsal ran the harness's own
`market` instead. Implements no design decision; it serves section 8's run
(`docs/guidance/workflow/changes.md`, "Defects found during a change"), recorded at
the owner's direction on 2026-11-23 (workflow seq 88). Touches
`e2e-tests/tests/e2e/roles/buyer_cli.py` and `e2e-tests/README.md`.

- [x] 13.1 `buyer_cli.py`'s docstring and skip message name the repository's path:
      `make init-buyer` at the repository root, which builds `.dist/` and the
      buyer's environment from it, or MARKET_CLI_BIN naming a `market` installed from
      the same wheels, such as `e2e-tests/.venv/bin/market` after `make dist-ci` and
      `make -C e2e-tests init`. Verify: the targets exist (`Makefile`'s `init-buyer`
      and `dist-ci`, `e2e-tests/Makefile`'s `init`).
- [x] 13.2 `e2e-tests/README.md`, "Live verification": the buyer's `market` is
      SOURCE_REVISION's own, installed from the run checkout's wheels, and where it
      comes from. Verify: the paragraph names no deployment.
- [x] 13.3 Verification point: 13.1 and 13.2 hold. Section 8's run records how its
      `market` was built. Nothing is owed to validation.

## 13a. Two comments that the comment check or the values beneath contradict

Delivers the fix round closeout returned for (14.1, workflow seq 105, the owner's
direction at seq 107): rewording a comment the merge of `origin/dev` brought in, which
`make check-comment-hygiene` matches, and an older chart comment the values beneath it
contradict. Implements no design decision; it answers the comment rule
(`docs/guidance/engineering/comments.md`, "Comments describe the current system") and
closeout's comment hygiene (`docs/guidance/workflow/closeout.md`, "Comment hygiene"),
which fails the closing checks until it passes. Touches
`scripts/tests/test_change_next_step.py` and `helm/values.yaml`, comments only.

- [x] 13a.1 Reword the comment at `scripts/tests/test_change_next_step.py:1265–1266`
      so it names the test's fixture sections without a numeral, keeping what it says —
      the newly planned section joins the open round, and its reading and review start
      from that round's base, so the section planned before it is still read and
      reviewed with it — for example "The third section joins the open round: its
      reading and review start from the open round's base, so the second is still read
      and reviewed with it." Verify: `make check-comment-hygiene` passes, and the test
      module still passes (unit, `uv run --no-project --with pytest --with pyyaml pytest
      -q scripts/tests/test_change_next_step.py`).
      Done: the comment reads as the example. `make check-comment-hygiene` passes; the
      module (unit) passes, 270 tests.
- [x] 13a.2 Reword the comment at `helm/values.yaml:414–415` so it describes the
      values beneath it: the e2e-tests subchart's credentials come only from the
      pre-existing Secret `secretName` names (`createSecret: false`, lines 427–430), and
      the chart carries no key value. Verify: the chart render tests pass (unit,
      `make -C helm test-render`), no value changing.
      At the owner's direction (workflow seq 110) the same header's lines 412–413,
      which said the subchart is disabled by default though `enabled: true` sits
      beneath them, are reworded too.
      Done: the header says the suite is for development and CI, enabled by the
      chart's defaults, a release running no tests setting `e2e-tests.enabled=false`
      as `bare-metal-release-values.yaml` does, and its credentials come only from
      pre-existing Secrets, the one `secretName` names and the buyer's
      `buyer.credentialSecret`. Differs from the task's wording, which named only
      `secretName`'s Secret: the test pods also mount `buyer.credentialSecret`
      (`helm/charts/e2e-tests/templates/tests/`). Outside the plan, the subchart's own
      header (`helm/charts/e2e-tests/values.yaml:2–3`) now says the umbrella's
      defaults enable it. `git diff` shows comment lines only. The chart render tests
      (`make -C helm test-render`, static configuration tests, not unit as the Verify
      line labels them) pass.
- [x] 13a.3 Verification point: 13a.1 and 13a.2 hold, and `scripts/change-workflow run
      pre-commit switch-on-hosted-per-period-vm` passes every check, the citations
      check included now that section 8's summary exists.
      End-to-end: none; comments only, no scenario's behaviour changes.
      Nothing is owed to validation.
      Done: `scripts/change-workflow run pre-commit switch-on-hosted-per-period-vm`
      passed, exit 0; `check-repository` passed all nine checks, the comment hygiene
      and citations checks among them. Handoff: closeout resumes at 14.1, whose check
      now passes; 14.7 runs again on this tree.

## 14. Closeout

Closes the change through `docs/guidance/workflow/closeout.md`'s parts in order, with
this repository's own parts (`openspec/README.md`, "This repository's closeout parts")
after campaign index currency.

- [x] 14.1 Comment hygiene: run `make check-comment-hygiene`; a finding, or a comment this
      change added that names a change, a task or a review, returns the change to
      implementation.
      First closeout run, at `f32db7037`: the check failed on a test comment the merge
      of `origin/dev` brought in (`scripts/tests/test_change_next_step.py`, numbered
      fixture sections), and closeout returned the change to implementation; section
      13a reworded it and two chart comments.
      Resumed closeout 2026-11-23, at `e0e15208f`: `make check-comment-hygiene` passes
      (no change-ID, task-number or change-name reference outside `openspec/`). The
      comments the change added against `6d1340c02` were read for history wording or a
      named change, review or migration; those matching words like "now" describe
      runtime order (the double's stop reversal, a test's prorated stop), not history.
      Nothing to rewrite.
- [x] 14.2 Import placement: confirm every import this change added is at module level,
      or return the change to implementation.
      Closeout 2026-11-23: the change's Python diff against `origin/dev` adds no
      indented `import` or `from … import` line, so every import it added is at module
      level. Rechecked at `e0e15208f`, against `6d1340c02`: still none.
- [x] 14.3 Documentation compliance: re-check D1–D14 against
      `docs/guidance/workflow/openspec-documentation.md` and `openspec/README.md`,
      "Documentation placement", and that every permanent document written describes the
      current state, declaratively and with no wording relative to the change.
      Done: each decision's destination, in the design-promotion record, is the layer
      and document the placement table gives it — engineering rules in
      `docs/guidance/engineering/` with neutral examples, the workflow rule (D2) in
      `docs/guidance/workflow/changes.md`, repository rules in
      `docs/guidance/repository/`, this repository's form in `TESTING.md` and
      `ARCHITECTURE.md`, capability detail in the companions, requirements in the
      specs by the archive, live evidence under `docs/attachments/`, and the
      decision's history in `design.md`. The documents implementation wrote (the
      quickstarts, the operator handbook, the e2e-tests and double READMEs, the chart
      example) and those promoted here were read for change-relative wording: none
      remains. One judgement: 14.9's D7 wording names `renewable-compute-lease-deadlines`
      as retiring the clause deadline; a companion naming a planned change is wording
      relative to it (`documentation.md`, "Permanent documents describe the current
      state"), so the companion states the current deadline and its enforcement, and
      the roadmap's open-gap row keeps the mapping to that change.
- [x] 14.4 Narrative compression: shorten completed tasks to final behaviour, evidence,
      deferred work and destinations, moving any rationale into `design.md` first.
      Done: sections 1–13a's notes shortened from about 2010 to about 1070 lines,
      keeping every task's planned text, its final behaviour, evidence with level and
      result, every `End-to-end:` and owed line, deviations still true of the code,
      unowned rows and promotion destinations; the implementation reasoning and
      producer facts moved first to `design.md`, "Implementation notes", by section.
      Dropped: fixed fresh-context findings (declined ones kept with their reasons),
      repeated pre-commit narratives and session tool denials.
- [x] 14.5 Roadmap currency: in `docs/development/ROADMAP.md`'s Goal 8, remove this
      change's open-gap row; absorb into the current state that on-demand and spot VM
      are a supported seller configuration, in production once a release carries them,
      qualified live as the summary of section 8 records (citing it), and that the
      mediation double executes `stop` and `penalty` with the VM lane's rate-deal
      disputes as lane-double evidence; correct the hosted-mediation sentences ("still
      runs an older revision"; "not yet deployed to the hosted test target") from what
      the summary observed; align the accepted limitations' dispute-policy sentence with
      D11; and, if the buyer's contested case is unproven, add a row to "Work this goal
      found and leaves unowned" naming the missing ruling policy. Name the edit in the
      design-promotion record.
      Done, all five parts: the open-gap row removed and the table's lead-in now says
      the rows complete the full form; the "dark" qualifiers dropped where VM now has
      a supported configuration; a current-state paragraph on the VM switch-on, the
      double's `stop` and `penalty`, the VM rate-deal dispute rows and the live
      verification, citing the summary and `TESTING.md`, "Live verification"; the
      hosted-mediation sentences replaced by what the summary observed (one build
      with payments, ruling a payee's filing mechanically); the dispute-policy
      sentence of the accepted limitations aligned with D11; and an unowned row for
      the live contested case's missing ruling policy. Recorded in the
      design-promotion record.
- [x] 14.6 Campaign index currency: update this change's row in
      `openspec/changes/README.md` and the Goal 8 campaign prose and graph annotation
      for this change; leave other rows' `Depends on` as they are; run
      `make check-change-index`.
      Done: the row is `in closeout`, its Notes naming the promotion and the unproven
      case's unowned row; the campaign prose records the summary's outcome; the graph
      annotation reads "qualified live, the policy-ruled buyer case unproven". No
      other row's `Depends on` or status changed. Two rows found at promotion added
      under "Unowned work with no campaign": `deployment-state`'s committed-files
      requirement narrower than the promoted configuration guidance, and the
      `e2e_vm_rate_dispute` marker description still listing a `reverse` among the
      seller's filing's effects. `make check-change-index` — pass. Archival repoints
      the row's link (14.12).
- [x] 14.7 Packaging: run `make check-packaging`, then `make check-architecture-change
      CHANGE=switch-on-hosted-per-period-vm`; resolve every failure or owned exception;
      run `make check-agent-skills` only if the change touched `.agents/`, `.claude/` or
      `.codex/`.
      Run early, at `f32db7037`, so the return under 14.1 names every code finding at
      once: `make check-packaging` passed, and `make check-architecture-change
      CHANGE=switch-on-hosted-per-period-vm` passed ("owns no architecture row"). The
      change touched no file under `.agents/`, `.claude/` or `.codex/`. Left unchecked:
      the resumed closeout runs it again on the fix round's tree.
      Resumed closeout, at `e0e15208f`: `scripts/change-workflow run pre-archive
      switch-on-hosted-per-period-vm` ran both — `make check-packaging` passed every
      check, `make check-architecture-change` "owns no architecture row" — exit 0. The
      change touches nothing under `.agents/`, `.claude/` or `.codex/` (diff against
      `6d1340c02`), so `make check-agent-skills` is not owed; the skills check runs
      among the closing checks' defaults anyway.
- [x] 14.8 End-to-end pipeline: record, from the latest passing validation, the pipeline
      run and its result, and the scenarios exercising this change —
      `e2e_vm_rate_dispute`, `e2e_vm_recurring_purchase`, `e2e_vm_rate_servicing`,
      `e2e_vm_payment_deal` and the `e2e_vm_dispute_*` scenarios; the live scenarios'
      evidence is section 8's summary, not the pipeline's. Closeout dispatches no run.
      Done, from validation 64 (passed) at `078cb2ac7`, which the closeout commit's
      code matches: `HEAD` differs from it only in `tasks.md` and the change index, and
      closeout changes only inert paths. Pipeline: e2e.yml run 45257630385, success —
      VM lane 513 passed, bare-metal 249, API-credit 4, the native Ansible gate 19 run
      and none failed. The record's coverage: `e2e_vm_payment_deal` and
      `e2e_vm_dispute_ruled_end`, `e2e_vm_recurring_purchase`,
      `e2e_vm_rate_servicing` and `e2e_vm_rate_dispute` passed in the VM lane (not run
      against Helm, whose default charts serve no settlement mechanism); the other
      `e2e_vm_dispute_*` modules ran in the same lane. Owed by validation:
      `e2e_vm_rate_dispute` (12.2, 12.5), shown passed by that run. Local (packaging
      and every suite) and Helm (scenario pod, 14 passed) passed too. The live
      scenarios, `e2e_vm_live_rate_servicing` and `e2e_vm_live_dispute`, belong to no
      lane; their evidence is section 8's summary.
- [x] 14.9 Promotion: write the permanent documents below and complete the
      design-promotion record (`docs/guidance/workflow/changes.md`, "The design-promotion
      record"); the `test-compatibility` and `deployment-state` `spec.md` files are
      written by the archive.
      - D1: `openspec/specs/settlement-configuration/configuration.md`, "Settlement
        consumer configuration and cutover" (the declaration offered by the VM chart's
        production example, and the "which hosted qualification has not yet shown"
        clause replaced by what section 8's summary shows);
        `openspec/specs/deal-lifecycle/architecture.md`, "External authorities" (the
        producer's-qualification and `chosen` sentences) and "Current limits" (rate deals
        "never against a deployed authority"); the seller quickstart and the example,
        written in sections 4 and 7.
      - D2: `docs/guidance/workflow/changes.md`, a new section "A change cuts no
        release": creating a release is independent of any change, and no change
        declares anything in production.
      - D3: `docs/guidance/engineering/system-tests.md`, "Locally verifiable and
        external-topology scenarios" (a repository declares each live scenario's
        topology requirements naming no infrastructure, the deployment prepares a
        topology from them, and an unmet requirement leaves its observations unproven);
        `docs/development/TESTING.md`, a new "#### Live verification" under "### 4.
        System Integration Tests (End-to-End)" (where this repository's requirements
        live, and the live markers outside every lane).
      - D4: `system-tests.md`, "Locally verifiable and external-topology scenarios" (a
        live test's provisioning mode follows what it proves);
        `openspec/specs/test-compatibility/architecture.md`, "Lane time and the doubles'
        controls" (`LaneTime.reach`'s wall-time case);
        `docs/guidance/repository/deal-scenarios.md`, "The discipline every scenario
        follows" (its wall-time bullet), and `docs/development/TESTING.md`, "Lane
        time": a wall-time run also waits for an instant the scenario's own data
        fixes, such as the Agreement's start plus the scenario's offset, as
        `LiveBuyerStop` does (sections 5 and 7's notes; review 67 F1).
      - D5: `docs/guidance/engineering/test-doubles.md`, "A double mirrors its producer"
        (no dependency on an endpoint the producer's public client lacks; past it, the
        producer's own live tests qualify); `docs/development/ARCHITECTURE.md`,
        "Authority boundaries" (the dispute authority's interface ending at its public
        client); `system-tests.md`, "Locally verifiable and external-topology scenarios"
        (a person's decision comes from a topology policy or the test; a policy watcher
        is a double for a person).
      - D6: `system-tests.md`, "Locally verifiable and external-topology scenarios" (the
        live verification form in the owner's words, beside the complete form; the
        shared assertion; failure on difference; the caller's balance reset and
        cleanup) and "A scenario is a sequence of state changes" (bounded polling of a
        live producer for an effect of the scenario's own request);
        `test-doubles.md`, "A double mirrors its producer" (a producer's later decision
        observed by polling is programmed and the poller stepped; an inbound call is
        spoofed through the real interface, or made by a double control);
        `openspec/specs/test-compatibility/architecture.md`, "The in-lane mediation
        double" (the `stop`, with its reversal of the earnings since a passed time,
        and the `penalty` it applies) and "Payment evidence ownership" (live
        evidence as boundary comparisons); `docs/development/TESTING.md`,
        "Private Service Dependencies" (the mediation double's effects), and "The
        canonical compute deal" (the VM rate-deal dispute rows); `deal-scenarios.md`,
        "The discipline every scenario follows" (its wall-time bullet), and
        `TESTING.md`, "Lane time": a wall-time run also polls a live producer for an
        effect of the scenario's own request, its bound outlasting the poll bound by
        the producer's own schedule, as `LiveDispute07`'s wait for the first period's
        earnings does (section 6's note; review 67 F1); the double's README, written
        in section 1.
      - D7: `settlement-configuration/configuration.md`, "Settlement consumer
        configuration and cutover" (the clause deadline as the storefront-enforced
        stopgap `renewable-compute-lease-deadlines` retires); the seller quickstart,
        written in section 7.
      - D8: the `test-compatibility` and `deployment-state` specs, by the archive;
        `openspec/specs/deployment-state/configuration.md`, its production-examples
        passage, if it lists them; `docs/guidance/repository/chart-render-tests.md`,
        "Where they live and how they run": the VM storefront chart's render test runs
        the storefront's startup refusal over the production example's render and
        publishes both its recurring options, under `STOREFRONT_PYTHON`, beside the
        bare-metal example's checks it names (section 4's note; review 67 F1).
      - D9: the summary, written in section 8; cited by Goal 8 (14.5).
      - D10: the quickstarts, written in section 7.
      - D11: the operator handbook, written in section 7;
        `deal-lifecycle/architecture.md`, "Current limits" (each environment's receipt
        key assumed stable for a deal's life, a key change a drained cutover, the
        authority's policy its own).
      - D12, D14: no permanent destination.
      - D13: `system-tests.md`, "Locally verifiable and external-topology scenarios" (a
        mode earns its own scenario only where it makes the external party run different
        code, with an example); `TESTING.md`, "Live verification" (the requirements in
        `e2e-tests/README.md`).
      - Three principles the owner stated on 2026-11-20 and directed into this
        closeout. They are no design decision of this change:
        - `docs/guidance/engineering/helm.md`, a new section: every component of an
          umbrella chart can be switched off on its own, so a deployment of fewer
          components is a values file that switches the others off, never a separate
          chart.
        - `docs/guidance/engineering/configuration.md`, "Application settings stay out
          of the environment": a third-party process that reads no configuration file
          of its own is started by a wrapper on the shared configuration loader. The
          wrapper resolves the process's profiles as a service resolves its own, and
          passes their values to it through its environment, never its arguments.
          Where the process reads configuration files of its own, those are preferred.
        - `configuration.md`, "Secrets travel in a secret profile or overlay file":
          where a stack's secret values come from, in the owner's words as revised on
          2026-11-23: "A production deployment's secret values should be managed
          externally from the chart, such as in a secret store, and injected into the
          pods using secret profiles. A local stack's secrets come from [A stack's
          configuration lives in committed files](#a-stacks-configuration-lives-in-committed-files)."
      - A fourth the owner agreed on 2026-11-21, likewise directed into this closeout:
        `docs/guidance/engineering/deployment.md`, amending "A deployment does not wait
        on a service's dependencies".
        - A service serves degraded only where it has meaningful work to do without the
          dependency. A service that has such work starts with the dependency
          unreachable, reports it degraded, and retries. A service that can do no
          meaningful work without it exits when it is unreachable, and the
          orchestrator's restarts are its retries.
        - Either way, configuration that can never work, an absent or malformed setting,
          is refused at startup, naming it. A well-formed address that reaches nothing
          is unreachable, never refused as wrong.
        - Native sidecars that are part of one service's own unit, such as its own state
          store or its database connection, may hold the service back until their
          startup probes pass. Each must refuse configuration it cannot use and exit on
          what it cannot reach, so the wait hides no failure that cannot heal. A
          dependency outside the unit is never waited on.
      - A fifth the owner agreed on 2026-11-23, likewise directed into this closeout,
        with the "Secrets travel" sentence above. Read literally, `configuration.md`'s
        "A stack's configuration lives in committed files" does not describe how
        stacks work today: a committed `.example` beside a gitignored copy, and a
        target writing generated keys into gitignored files. These are the agreed
        texts.
        - `configuration.md`, "A stack's configuration lives in committed files": its
          first two sentences are replaced by the text below; from "A value the base
          topology fixes" on, the section is unchanged.
          > Every stack a repository runs, whether a development stack, an end-to-end
          > lane or a local cluster, takes every non-secret value from committed
          > profile, overlay and values files. Each of its secret files is one of two
          > kinds:
          > - **Committed public development values.** Used where the stack runs
          >   unattended from a clean checkout, or where something else pins an
          >   identity derived from them, such as a lane's fixed seed. They are never
          >   for a public network.
          > - **A gitignored copy of a committed `.example` beside it.** Used wherever
          >   a person runs the stack by hand or brings a credential of their own. The
          >   `.example` names every field and says how to fill it: either a generated
          >   value and the command that makes one, or a held credential and where its
          >   holder gets it. A copy is filled by hand, or by a make target that only
          >   copies the `.example` and fills its generated fields. The target leaves
          >   an existing copy untouched and prints no value. A generated file with no
          >   fields, such as a private key, needs no `.example`: the target that
          >   writes it and the committed file it pairs with name it.
          >
          > The compose layer reads the copies where it would read committed files,
          > and a launcher refuses a missing copy, naming how to make one. A cluster
          > gets a stack's secret files from a separate target at the Helm layer,
          > which reads them and writes the cluster's secrets. Nothing generates a
          > value straight into a cluster. A chart's committed development secret
          > values are in a local values file, never in its defaults
          > ([Helm](helm.md#a-charts-defaults-carry-no-secret-value)).
          >
          > A deployed stack's secret profile or overlay is never a committed file: it
          > is the file an operator-supplied secret holds. The tooling that deploys the
          > chart is responsible for selecting the configuration of that deployment.
          > It should never carry a value itself. Configuration files should be
          > populated by a separate step an operator runs before the deployment
          > tooling runs.
        - `helm.md`, a new section:
          > ## A chart's defaults carry no secret value
          >
          > A chart's `values.yaml` holds its development defaults, which a release
          > gets for anything it doesn't state. They hold no secret value, not even a
          > public development one: no password, private key, token or seed. Where a
          > local release needs secret values, they are committed in a separate local
          > values file, which a local install names explicitly. A release that names
          > no source for a secret fails to start, naming the missing setting. Failing
          > to start is preferable to accidentally deploying public test values.
        - `kubernetes.md`, its local-cluster guidance: one line pointing to the
          Helm-layer target in `configuration.md`.
        - Before promoting, check this repository's charts against the new `helm.md`
          section: no `values.yaml` sets a secret value, and each committed
          development secret value is in a local values file such as
          `helm/local-values.yaml`. A chart that departs is a defect fixed in this
          change ("Defects found during a change").
      Run `make check-spec-index CHANGE=switch-on-hosted-per-period-vm`; neither touched
      capability has an `index.md`, and `openspec/specs/README.md` needs no row.
      Done: every document above written, and the design-promotion record completed in
      `design.md`, each decision and principle with its anchor. Where the writing
      departs from the list: D1's and D7's companion text describes the current
      deadline and the live findings without naming the change that retires the
      clause deadline (14.3); D8's `deployment-state/configuration.md` has no
      production-examples passage, so nothing is written there; `kubernetes.md` has
      no local-cluster section, so its one line is a bullet of "Configuration travels
      through mounted files"; the fifth principle's agreed text replaces
      "A stack's configuration lives in committed files" up to "A value the base
      topology fixes", the old third sentence on build tooling included, since the
      agreed text's last paragraph restates it and the old "never generates" would
      contradict the make target it admits; the fourth principle's text is the amended
      section's three bullets, with the next section's "reported, not refused" aligned
      to the exit it admits. The charts were checked against `helm.md`'s new section
      first: no `values.yaml` under `helm/` sets a secret value — identifiers are
      public addresses, Secrets are named, not filled — and the committed development
      secret values are in `helm/local-values.yaml`, so no defect. Promoting the fifth
      principle found `deployment-state`'s committed-files requirement narrower than
      it; that needs a decision this change does not make, so it is an unowned row
      (14.6) for the closeout review to read. `make check-spec-index
      CHANGE=switch-on-hosted-per-period-vm` — pass. The `test-compatibility` and
      `deployment-state` specs are written by the archive (14.12).
- [x] 14.10 Guidance placement: read the paragraphs promoted in 14.9 against the layer
      test — `system-tests.md`'s and `test-doubles.md`'s in the engineering layer with
      neutral examples, `changes.md`'s in the workflow's — then run `make check-guidance`.
      Done: the engineering sections added or rewritten (`system-tests.md`,
      `test-doubles.md`, `helm.md`, `configuration.md`, `deployment.md`,
      `kubernetes.md`) hold without the workflow and use neutral examples — a payment
      provider, a billing service, a webhook — naming nothing of this repository;
      `changes.md`'s "A change cuts no release" is the workflow's and names no
      repository's release scheme; the repository's wall-time bullet and chart render
      checks sit in `docs/guidance/repository/` beside the rules they extend; no
      exception was added. Nothing moved, so no citation was re-pointed. `make
      check-guidance` — pass (104 files tagged, no link to a higher layer, every
      cited anchor a heading). For the closeout review: `deployment-state`'s
      committed-files requirement against the promoted `configuration.md` (14.9).
- [x] 14.11 Documentation citations: run `make check-doc-citations
      CHANGE=switch-on-hosted-per-period-vm` and resolve every match, then
      `scripts/change-workflow openspec validate switch-on-hosted-per-period-vm --strict`.
      Done: `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` — every
      cited path resolves, none a tombstone; the links and anchors the promotion wrote
      were also checked to resolve. `scripts/change-workflow openspec validate
      switch-on-hosted-per-period-vm --strict` — valid.
- [x] 14.12 Archival: `scripts/change-workflow openspec archive
      switch-on-hosted-per-period-vm -y`, merging the deltas into `test-compatibility`
      and `deployment-state`; the index row then links the archive directory.
      Done: the deltas were compared with the permanent specs first — none of their
      requirements was there — so the archive merged them:
      `scripts/change-workflow openspec archive switch-on-hosted-per-period-vm -y`
      added one requirement to `deployment-state` and four to `test-compatibility`,
      and modified two there; the change moved to
      `openspec/changes/archive/2026-11-23-switch-on-hosted-per-period-vm/`. The
      diffs read: each added and modified requirement appears once, as its delta
      states it, the modified requirements' other scenarios kept, and nothing else
      changed. The index row links the archive directory; no other link named the
      change's directory.
