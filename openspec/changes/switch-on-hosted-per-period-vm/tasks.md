# Tasks — switch-on-hosted-per-period-vm

Sections 1–4 are the internal work, proven on the lanes; sections 5–8 are live
verification, which ends waiting for the deployment's evidence (D3, D9) before the
pre-closeout review. The live scenarios belong to no pipeline lane: the pipeline proves
their lane twins, and the deployment runs them against a topology meeting their stated
requirements.

## 1. The mediation double executes a ruling's `stop` and `penalty`

Delivers the mediation double applying a ruling's `stop` and `penalty` effects at the
payments double, `award` still refused. Implements D6; requirement "Lanes run a
mediation double that answers from programmed rules" (`test-compatibility`, modified).
Touches `tools/mediation-lane-double` (`rules.py`, `service.py`, its tests, README,
`pyproject.toml` and lock), the consumers' pins of it if any, and the convergence
change's index row and Goal 8 gap (inert paths).

- [ ] 1.1 Admit `stop` and `penalty` in the double's rules and operator decisions
      (`tools/mediation-lane-double/src/mediation_lane_double/rules.py`,
      `_APPLIED_EFFECTS`), keeping `award` refused at install with a typed code and
      nothing installed; the controls' `Ruling` model already admits every contract
      `Effect` (`tools/lane-double-controls/src/lane_double_controls/models.py`) and
      needs no change (D6). Verify (unit, `tools/mediation-lane-double/tests/unit/test_rules.py`):
      a rule and a decision carrying `stop` or `penalty` install; one carrying `award`
      is refused and installs nothing.
- [ ] 1.2 Apply them in `service.py` as the requirement states (D6): a `stop` as one
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
- [ ] 1.3 Rewrite the double's README for the effects it applies ("Deviation from its
      producer"; the effects paragraph), bump `tools/mediation-lane-double`'s version and
      relock (`make lock`), and raise any consumer's minimum to it
      (`docs/guidance/repository/package-versions.md`). Verify: `scripts/change-workflow
      run pre-commit switch-on-hosted-per-period-vm` passes, the packaging check among
      its functional hooks.
- [ ] 1.4 In `openspec/changes/README.md`, `converge-ongoing-compute-leases`' row Notes
      record that this change took the double's `stop` and `penalty` execution; in
      `docs/development/ROADMAP.md`'s Goal 8, the convergence gap row no longer says the
      double executes only `reverse` effects and that its rate rows first add that
      execution (D6; `docs/guidance/workflow/changes.md`, "Defects found during a
      change"). Verify: `scripts/change-workflow check index` passes.
- [ ] 1.5 Verification point: the double's unit and integration suites pass, and the VM
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

## 2. The payment rows' producer outputs as shared assertions

Delivers, for the buyer's stop, funds running out, the spot preemption and the term end,
one assertion each over the payments producer's output, stating which fields it compares
exactly, by relation, or not at all, used by the existing VM lane rows now and by their
live twins in section 5. Implements D6 (the shared comparison); requirement "A live
verification scenario compares a producer's outputs with a lane's expectations"
(`test-compatibility`, added), its lane half. Touches `e2e-tests/tests/e2e/roles/helpers/`
(`recurring_purchase_stages.py`, `rate_servicing_stages.py`, and a new module holding the
assertions), and the VM recurring purchase and rate servicing modules that call them.

- [ ] 2.1 Write the four assertions over what the payments double and the hosted
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
- [ ] 2.2 Make `e2e_vm_recurring_purchase`'s buyer stop and `e2e_vm_rate_servicing`'s
      three rows assert through them, the lanes' step-and-read stages unchanged, and the
      bare-metal rows untouched (D6). Verify (unit): `make -C e2e-tests test-unit`
      passes, the stage order and handoff checks (`ORDERS`) included.
- [ ] 2.3 Verification point: the VM lane's recurring purchase and rate rows pass on the
      shared assertions (system, the VM lane's Compose stack: `make -C e2e-tests
      test-e2e-vm "E2E_MODULE=e2e_vm_recurring_purchase or e2e_vm_rate_servicing"`).
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_vm_rate_servicing`.
      Nothing is owed to validation.

## 3. A dispute on a running rate deal in the VM lane

Delivers two VM lane rows on rate deals, each ruled with an authority stop, proving what
the storefront does after a ruling, and their shared assertions over the dispute
authority's and payments' output. Implements D6; requirement "A dispute on a running rate
deal is qualified in the VM lane" (`test-compatibility`, added). Touches a new
`e2e-tests/tests/e2e/roles/scenarios/vms/rate_dispute/` (conftest, stages, two modules),
the assertions module of section 2, `e2e-tests/pyproject.toml`'s markers, the Makefile's
VM lane list, and `e2e-tests/README.md`.

- [ ] 3.1 The seller's filing row: on a delivered on-demand rate deal reached through the
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
- [ ] 3.2 The buyer's contested case row: on a delivered on-demand rate deal, the buyer
      files through the mediation kit's dispute adapter in the harness, as the VM dispute
      controls do; the storefront's respondent discovery contests it; an operator
      decision through the typed control client rules `stop` with `returned` and a
      `reverse`. Assert the ruled end recorded, the payer's returns, the teardown and the
      deal `ended` once the case closes (D6, D5's policy row's lane twin). Verify
      (system): the module passes in the VM lane.
- [ ] 3.3 Write the two dispute assertions over the producer's output — the filing's
      per-part protection; the ruled entry's basis and effects and their applied state;
      the snapshot's authority stop, reversals and lifted extensions; the closed case —
      with exact, relational and ignored fields named as in 2.1, and have both rows
      assert through them (D6). Verify (unit, `e2e-tests/tests/unit/`): each passes on a
      recorded double output and fails naming the field on an altered one.
- [ ] 3.4 Register the marker (`e2e_vm_rate_dispute`, lane-double evidence) in
      `e2e-tests/pyproject.toml` and the VM lane's default module list in
      `e2e-tests/Makefile`, and describe the rows in `e2e-tests/README.md` (D6). Verify
      (unit): `make -C e2e-tests test-unit` passes, `ORDERS` included.
- [ ] 3.5 Verification point: the two rows pass, leaving no payment hold, mock rule or
      held loop (system, the VM lane's Compose stack: `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_rate_dispute"`), and the whole VM lane passes.
      End-to-end: `e2e_vm_rate_dispute`.
      Nothing is owed to validation.

## 4. The VM chart's production example

Delivers `helm/charts/storefront/examples/production-values.yaml`: an agent settling in
`arkhai.payments.v1` in live mode, declaring `[charged, returned]` with `setup = false`,
and publishing an on-demand and a spot recurring clause whose payments clause sets
`delivery_deadline_seconds` and a dispute window covering it plus the authority's minimum
filing window. Implements D1 and D7; requirement "The VM storefront chart ships a
production example offering on-demand and spot" (`deployment-state`, added). Touches the
example, `helm/charts/storefront/tests/test_render.py`, and
`scripts/tests/test_committed_time_sources.py`.

- [ ] 4.1 Write the example: every value a public placeholder or a well-known
      development value, no secret (the payments key and dispute credential named as
      overlay entries in comments), wall time (D1, D7;
      `docs/guidance/engineering/repository-content.md`). Verify (unit):
      `scripts/tests/test_committed_time_sources.py` lists it among the chart examples
      and passes.
- [ ] 4.2 Render it and run the storefront's own loader and startup check over the
      rendered `storefront.json`, as the bare-metal chart's test does with its example
      (`helm/charts/bare-metal-storefront/tests/test_render.py`, "the storefront's own
      loader"), under `STOREFRONT_PYTHON` (requirement scenario "The production example
      is rendered"). Verify (unit, the chart render tests, `make -C helm test-render`
      with `STOREFRONT_PYTHON` set): the render succeeds and the check reports no
      problem.
- [ ] 4.3 The publication check (18 F2): from the rendered example's loaded
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
- [ ] 4.4 Verification point: the chart render tests pass with the loader and
      publication checks run, not skipped, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; the `helm` evidence kind runs these render and chart-to-loader
      checks against the tree, and no pipeline scenario reads the example.
      Nothing is owed to validation.

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

- [ ] 5.1 Give `LaneTime.reach` its admitted wall-time case: an instant an authority
      recorded as the effect of the scenario's own request, read from a signed record —
      a pending stop's effective instant, the snapshot's funded boundary — waited for
      with a bound, failing at the bound; any other instant on a wall run stays a
      blocked skip; injected runs are unchanged. Add the bounded poll of a producer's
      public read that the live scenarios use for an asynchronous output (D4, D6).
      Verify (unit, `e2e-tests/tests/unit/`): the case waits to the recorded instant,
      fails past its bound, still skips an unrecorded instant on wall time, and an
      injected run sets lane time as before.
- [ ] 5.2 Read the live scenarios' period, payee notice and maximum term from run
      settings, defaulting to the lanes' values (D4), and have the live modules refuse a
      lane-owned payments target with a blocked skip naming it, since a double yields no
      live evidence. Verify (unit): the settings parse and default, and a lane-owned
      target skips.
- [ ] 5.3 Write the four modules, marker `e2e_vm_live_rate_servicing` in no lane: each
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
- [ ] 5.4 Write each module's topology requirements in prose beside its description
      under a "Live verification" heading in `e2e-tests/README.md`: what it proves,
      mock provisioning, Arkhai payments in test mode executing rate parts, its accounts
      and starting balances, the run settings it reads, and the balance reset and
      cleanup its caller owes between runs; naming no infrastructure (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` passes.
- [ ] 5.5 Run each module against the local Helm release on wall time, its payments
      double standing in for the producer, where it can serve the module, recording
      which observations it made there and which it could not and why (the double
      reserves only through its control, so funds running out cannot complete there);
      this is not live evidence (D4, D6). Verify (system, the local Helm release): the
      buyer's stop, preemption and term-end modules make their observations with short
      period settings.
- [ ] 5.6 Verification point: the `e2e-tests` unit suite passes, 5.5's runs are recorded,
      and the VM lane still passes with the live modules collected and skipped.
      End-to-end: none in the pipeline — `e2e_vm_live_rate_servicing` belongs to no lane,
      and its evidence is the deployment's (section 8); the lane twins are
      `e2e_vm_recurring_purchase` and `e2e_vm_rate_servicing`.
      Nothing is owed to validation.

## 6. The live dispute scenarios

Delivers the two live dispute scenarios — the seller's filing, and the buyer's contested
case ruled by a topology's declared policy — each extending its section 3 twin in the
live verification form through the public mediation and payments clients, with its
topology requirements in prose. Implements D5, D6 and D13; requirements "Rate deals and
dispute filings are verified live against a prepared topology" and "Each live
verification scenario states its topology requirements" (`test-compatibility`, added).
Touches `e2e-tests/tests/e2e/roles/scenarios/vms/live/` (two modules),
`e2e-tests/pyproject.toml` and `e2e-tests/README.md`.

- [ ] 6.1 The seller's filing module: the storefront's own payee filing on a running
      rate deal, sent by its journal through the mediation kit's adapter as in 3.1; read,
      by bounded polls of the public record and snapshot reads, the per-part protection,
      the authority's ruled entry, the authority stop, reversals, penalty, lifted
      extensions and closed case, and assert through 3.3's assertion. No operator
      endpoint is called (D5, D6). Verify (unit): the module's stages pass the order and
      shared-stage checks.
- [ ] 6.2 The buyer's contested case module: the buyer's filing through the mediation
      kit's adapter, the storefront's contest, then the ruling the topology's declared
      policy makes, read and asserted through 3.3's assertion; with no policy applied by
      the bound, the ruling observation is unproven naming the policy requirement, its
      filing and contest observations standing (D5, D13). Verify (unit): as 6.1, and the
      unproven outcome names the requirement.
- [ ] 6.3 Register the marker `e2e_vm_live_dispute`, in no lane, and write both modules'
      topology requirements in prose under "Live verification" in `e2e-tests/README.md`:
      a hosted mediation authority serving filing, the respondent listing and record
      reads, the contested case's ruling policy in this repository's own words (a
      buyer's contested `delivery_end` ruled with a `stop returned` and a reverse), the
      accounts, settings, and the cleanup its caller owes — closing any case left
      awaiting an operator and resetting balances (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` and
      `make -C e2e-tests test-unit` pass.
- [ ] 6.4 Run both modules against the local Helm release on wall time, its doubles
      standing in, recording which observations they made there: the filing and its
      protection, and the contest; the rulings are unproven there, since the double
      rules only on a rule (D6). Verify (system, the local Helm release): the filing
      observations are made.
- [ ] 6.5 Verification point: the `e2e-tests` unit suite passes, 6.4's runs are recorded,
      and the VM lane still passes with the live modules collected and skipped.
      End-to-end: none in the pipeline — `e2e_vm_live_dispute` belongs to no lane; its
      lane twin is `e2e_vm_rate_dispute`.
      Nothing is owed to validation.

## 7. What sellers, buyers and storefront operators are told

Delivers the seller and buyer quickstart sections and the storefront operator's runbooks.
Implements D1, D7, D10 and D11. Touches `docs/seller-quickstart.md`,
`docs/buyer-quickstart.md` and `docs/operator-handbook.md`.

- [ ] 7.1 `docs/seller-quickstart.md`, a new section "Offering on-demand and spot": the
      on-demand and spot recurring clauses, the declaration `[charged, returned]` with
      `setup = false`, the clause's `delivery_deadline_seconds` and a dispute window
      covering it plus the authority's minimum, withdrawal by removing the table, and
      payout timing — at the earliest the part's stop plus the dispute window plus the
      payments service's payout delay, 7 days in live mode by that service's
      documentation; pointing at the chart's production example (D1, D7, D10). Verify:
      the TOML shown parses as the storefront's settings (the same loader as 4.2) and
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` passes.
- [ ] 7.2 `docs/buyer-quickstart.md`, a new section on on-demand and spot options: the
      default refusals and the waiver for each, approval refused when the balance cannot
      cover the first reservation, a top-up before the funded boundary keeping a deal
      running and after it a new deal, the premature-stop penalty collectible only from
      the seller's earnings still held, and the dispute remedy a case (D10). Verify: each
      command and flag shown is in the installed `market --help` output, and the
      citations check passes.
- [ ] 7.3 `docs/operator-handbook.md`, a new section for a storefront serving rate deals:
      truncating a lease abandoned before delivery and monitoring committed reservations
      still unactivated past their deadline, through the storefront's and the site's
      existing operator interfaces; draining running payment deals before a receipt key
      change (`settlement-configuration`'s "A receipt identity change is a cutover");
      and what a seller operator sees for each dispute outcome — the recorded end, the
      `ending` codes, a ruled end with no stop left `ending` with its payment running as
      the authority's to correct — linking the dispute authority's policy where it is
      published, hosting none of it (D7, D11). Verify: each command and route named
      exists (`--help`, the storefront's route table), and the citations check passes.
- [ ] 7.4 Verification point: `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; documentation.
      Nothing is owed to validation.

## 8. Live verification evidence

Delivers the deployment's sanitized live verification summary in the change, and the
check that D3's threshold is met. Implements D3 and D9; requirement "Rate deals and
dispute filings are verified live against a prepared topology" (`test-compatibility`,
added). This section waits for the deployment: it reads the requirements written in
sections 5 and 6, prepares a topology meeting them, runs `e2e_vm_live_rate_servicing`
and `e2e_vm_live_dispute` at the branch's code, and records its summary. Touches
`docs/attachments/switch-on-hosted-per-period-vm/`.

- [ ] 8.1 Receive the deployment's summary at
      `docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`: per
      observation, made, failed or unproven, with public-safe provenance — source
      revision, target alias, authority revision identifiers, provisioning mode — no raw
      log, record, endpoint, account identifier or credential, and whether D3's
      threshold is met (D9; `docs/guidance/engineering/system-tests.md`, "Locally
      verifiable and external-topology scenarios";
      `docs/guidance/engineering/repository-content.md`). Verify: the public-content
      checks pass in `scripts/change-workflow run pre-commit`, and the source revision
      is the branch's code at the run.
- [ ] 8.2 Confirm the threshold (D3): the buyer's stop, funds running out, the spot
      preemption, the term end and the seller's filing each made; the buyer's contested
      case made, or unproven naming the requirement it lacked. A failed comparison
      returns the change to design with the evidence (D14); an unproven required
      observation holds the change here for the deployment to meet the requirement it
      names, or, on the owner's word, returns it to design (D3). Verify: the summary
      states each of the five made.
- [ ] 8.3 Verification point: 8.1 and 8.2 hold.
      End-to-end: `e2e_vm_live_rate_servicing`, `e2e_vm_live_dispute`, run by the
      deployment, not by the pipeline.
      Nothing is owed to validation.

## 9. Closeout

Closes the change through `docs/guidance/workflow/closeout.md`'s parts in order, with
this repository's own parts (`openspec/README.md`, "This repository's closeout parts")
after campaign index currency.

- [ ] 9.1 Comment hygiene: run `make check-comment-hygiene`; a finding, or a comment this
      change added that names a change, a task or a review, returns the change to
      implementation.
- [ ] 9.2 Import placement: confirm every import this change added is at module level,
      or return the change to implementation.
- [ ] 9.3 Documentation compliance: re-check D1–D14 against
      `docs/guidance/workflow/openspec-documentation.md` and `openspec/README.md`,
      "Documentation placement", and that every permanent document written describes the
      current state, declaratively and with no wording relative to the change.
- [ ] 9.4 Narrative compression: shorten completed tasks to final behaviour, evidence,
      deferred work and destinations, moving any rationale into `design.md` first.
- [ ] 9.5 Roadmap currency: in `docs/development/ROADMAP.md`'s Goal 8, remove this
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
- [ ] 9.6 Campaign index currency: update this change's row in
      `openspec/changes/README.md` and the Goal 8 campaign prose and graph annotation
      for this change; leave other rows' `Depends on` as they are; run
      `make check-change-index`.
- [ ] 9.7 Packaging: run `make check-packaging`, then `make check-architecture-change
      CHANGE=switch-on-hosted-per-period-vm`; resolve every failure or owned exception;
      run `make check-agent-skills` only if the change touched `.agents/`, `.claude/` or
      `.codex/`.
- [ ] 9.8 End-to-end pipeline: record, from the latest passing validation, the pipeline
      run and its result, and the scenarios exercising this change —
      `e2e_vm_rate_dispute`, `e2e_vm_recurring_purchase`, `e2e_vm_rate_servicing`,
      `e2e_vm_payment_deal` and the `e2e_vm_dispute_*` scenarios; the live scenarios'
      evidence is section 8's summary, not the pipeline's. Closeout dispatches no run.
- [ ] 9.9 Promotion: write the permanent documents below and complete the
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
        controls" (`LaneTime.reach`'s wall-time case).
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
        double" (the `stop` and `penalty` it applies) and "Payment evidence ownership"
        (live evidence as boundary comparisons); `docs/development/TESTING.md`,
        "Private Service Dependencies" (the mediation double's effects), and "The
        canonical compute deal" (the VM rate-deal dispute rows); the double's README,
        written in section 1.
      - D7: `settlement-configuration/configuration.md`, "Settlement consumer
        configuration and cutover" (the clause deadline as the storefront-enforced
        stopgap `renewable-compute-lease-deadlines` retires); the seller quickstart,
        written in section 7.
      - D8: the `test-compatibility` and `deployment-state` specs, by the archive;
        `openspec/specs/deployment-state/configuration.md`, its production-examples
        passage, if it lists them.
      - D9: the summary, written in section 8; cited by Goal 8 (9.5).
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
      Run `make check-spec-index CHANGE=switch-on-hosted-per-period-vm`; neither touched
      capability has an `index.md`, and `openspec/specs/README.md` needs no row.
- [ ] 9.10 Guidance placement: read the paragraphs promoted in 9.9 against the layer
      test — `system-tests.md`'s and `test-doubles.md`'s in the engineering layer with
      neutral examples, `changes.md`'s in the workflow's — then run `make check-guidance`.
- [ ] 9.11 Documentation citations: run `make check-doc-citations
      CHANGE=switch-on-hosted-per-period-vm` and resolve every match, then
      `scripts/change-workflow openspec validate switch-on-hosted-per-period-vm --strict`.
- [ ] 9.12 Archival: `scripts/change-workflow openspec archive
      switch-on-hosted-per-period-vm -y`, merging the deltas into `test-compatibility`
      and `deployment-state`; the index row then links the archive directory.
