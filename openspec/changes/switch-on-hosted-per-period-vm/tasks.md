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

- [x] 1.1 Admit `stop` and `penalty` in the double's rules and operator decisions
      (`tools/mediation-lane-double/src/mediation_lane_double/rules.py`,
      `_APPLIED_EFFECTS`), keeping `award` refused at install with a typed code and
      nothing installed; the controls' `Ruling` model already admits every contract
      `Effect` (`tools/lane-double-controls/src/lane_double_controls/models.py`) and
      needs no change (D6). Verify (unit, `tools/mediation-lane-double/tests/unit/test_rules.py`):
      a rule and a decision carrying `stop` or `penalty` install; one carrying `award`
      is refused and installs nothing.
      Done: `rules.check_ruling` holds the one admission check, which `RuleBook.install`
      and now `MediationDouble.decide` both call, so an operator decision is checked
      before it rules anything; refusal `422 invalid_request` naming the effect.
      Outside the plan: before this, `decide` checked no effect at all, so a decision
      carrying a `stop` would have been recorded and then failed building a reverse
      from it. Unit (`test_rules.py`, the rule book and `check_ruling` directly): a
      rule and a decision with `reverse`, `stop` or `penalty` are admitted; a rule
      carrying an `award` beside applied effects is refused with nothing installed,
      and a decision carrying one is refused — pass. Application integration (`tests/integration/test_controls.py`, the app in
      process through the typed `ControlClient`): an `award` rule refused at install,
      and an operator decision carrying an `award` refused with the case left open,
      nothing reversed and only its `filed` entry recorded — pass.
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
      Done: `service._payment_events` builds each effect's events once, stored per
      effect in `Case.events` (a list: one for a `reverse` or `stop`, one per part
      reversed for a `penalty`) and resent unchanged until applied. A `stop` is sent
      with the ruling's `partialPeriod`, and with its `at` only while that instant
      has not passed by the double's clock: payments refuses a past `at`
      (`invalid_event`) and never backdates a stop, so a passed time is a stop now.
      The contract would also reverse the still-held earnings beyond a stop at that
      time; the double computes nothing, so a ruling wanting that programs a
      `reverse`, and the README states it as a deviation. A `penalty` reads the
      snapshot once every earlier effect is applied and reverses each part's `held`,
      in mandate order, keyed `mediation:<case_ref>:<ruling>:effect:<n>:part:<i>`.
      Application integration, not library integration as planned
      (`tests/integration/test_rulings.py`: the app in process, filed through the
      kit's real `MediationClient` over an ASGI transport, ruled by rules installed
      through the typed `ControlClient`, against the payments kit's `PaymentsAuthority`
      engine behind `FakePaymentsClient`, on one injected time): a ruled
      `stop returned` on a running rate part, its first answer lost after commit,
      leaves the part stopped with cause `authority` and `returned`, only the first
      hour earned, and its resend is the identical request with one stop recorded; a
      stop time not yet reached is pending at that time, and a passed one stops the
      part now; a `penalty` of 1000 after a `reverse` of 100 on two once parts holding
      300 each reverses exactly the 200 and 300 left, in part order, keyed beneath
      its effect, and a payments refusal of its second reversal resumes with each
      part reversed once; a `penalty` on the running rate part reverses its held
      first hour and leaves its reservation; a gated ruling with a `stop` sends
      nothing until resumed; a payments refusal of the `reverse` after the `stop`
      resumes with one stop sent and recorded; an operator decision through
      `ControlClient.decide` ruling `stop returned` stops the part as the authority;
      a stop with a future time that payments refuses once, resumed after lane time
      passes that time, is built afresh and sent as a stop now; and a stop payments
      took with its answer lost, then refused on its resend, is resent unchanged on
      the next resume and takes effect at its own time — all pass, with the whole
      suite (96). Unit (`tests/unit/test_penalty.py`, `penalty_reversals` directly):
      the split over parts' holdings, capped, into a later part, within the first,
      past a part holding nothing, and with nothing held — pass. An effect's events
      are kept once built, so a lost answer or a later event's failure resends them
      unchanged; only when payments refuses an effect's first event that no earlier
      send can have delivered (`Case.reached`) are they built again on resume, since
      a kept stop with a passed `at` would be refused `invalid_event` on every
      resend, leaving the case applying for good.
      `scripts/change-workflow run test-before` could not show the new cases failing
      before the change: its command runs pytest with no project environment, so
      the module fails at collection importing `lane_double_controls`, which shows
      nothing about the change.
- [x] 1.3 Rewrite the double's README for the effects it applies ("Deviation from its
      producer"; the effects paragraph), bump `tools/mediation-lane-double`'s version and
      relock (`make lock`), and raise any consumer's minimum to it
      (`docs/guidance/repository/package-versions.md`). Verify: `scripts/change-workflow
      run pre-commit switch-on-hosted-per-period-vm` passes, the packaging check among
      its functional hooks.
      Done: the README's effects paragraph lists how each effect is applied and when
      an effect is rebuilt, and "Deviation from its producer" states that the double
      executes what a ruling programs, that a passed stop time is a stop now with no
      reversal beside it, and that an `award` is refused. Version 0.1.0 to 0.2.0,
      new behaviour before 1.0 (`origin/dev` holds 0.1.0); `make lock
      PROJECTS=tools/mediation-lane-double` rewrote its own lock's version line. No
      project pins or imports the double, so no consumer minimum moves.
      `scripts/change-workflow run pre-commit` on the final tree: `after-functional-change`
      passed; `pre-commit-functional` passed (local evidence for tree `af8c9d7cfd6f`:
      `check-packaging` and `make test` passed, the tree unchanged); `pre-commit`'s
      workflow checks passed (index, tasks, skills, strict OpenSpec validation) and
      `check-repository` passed 8 of 9: documentation citations reports
      `docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`, the
      summary 8.1 cites and the deployment writes in section 8 — expected until then.
- [x] 1.4 In `openspec/changes/README.md`, `converge-ongoing-compute-leases`' row Notes
      record that this change took the double's `stop` and `penalty` execution; in
      `docs/development/ROADMAP.md`'s Goal 8, the convergence gap row no longer says the
      double executes only `reverse` effects and that its rate rows first add that
      execution (D6; `docs/guidance/workflow/changes.md`, "Defects found during a
      change"). Verify: `scripts/change-workflow check index` passes.
      Done: the convergence row's Notes say this change took the double's `stop` and
      `penalty` execution and its matrix rows keep their use; its deliverables cell is
      left for its own reverification. The Goal 8 gap row drops the clause. This
      change's own row is `in implementation`. `check index` — pass. The Goal 8
      current-state sentence naming the double's `reverse` effects is left for
      roadmap currency (9.5), as planned.
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
      Evidence, on the section's final code: the double's suite, `make -C
      tools/mediation-lane-double test` (unit and application integration) — 96
      passed. System, the VM lane's Compose stack with the double's image rebuilt at
      0.2.0, the command above — 107 passed, 1851 deselected (also run twice on
      earlier states of the section, each 107 passed); the stack was taken down after
      each run (`make -C e2e-tests e2e-vm-down`).
      End-to-end scenarios confirmed as listed: they show the amended double still
      serves the reverse-only rulings, filings and protection the dispute rows use;
      none is evidence for `stop` or `penalty`, whose evidence is the suite above
      until section 3's rows.

Handoff (section 1):

- Outside the plan: `decide` now checks its ruling (1.1). Also outside the plan,
  a defect found by `make test`: `scripts/tests/test_change_workflow_assumptions.py`
  failed at the round's base, since the step table names `scripts/openspec` and
  `market-change-workflow`'s README, "How this repository provides the workflow's
  roles", did not; its closing-checks row now names the validator it runs.
  Comments and docs saying the double "extends, reverses and lifts" now include
  "stops" (`authority.py`, its `fixtures/authority.toml`, its `pyproject.toml`,
  `tools/payments-lane-double/README.md` and `fixtures/accounts.toml`,
  `dev-env/identities/README.md`, a docstring in
  `scripts/tests/test_committed_stack_values.py`); in `payments-lane-double` only a
  fixture comment, outside its wheel, so it takes no bump. Its README's matching
  sentence is left as it is: the README is its wheel's metadata, and the sentence
  is incomplete rather than false.
- For closeout's promotion of D6 to `test-compatibility`'s "The in-lane mediation
  double": state the `stop` deviation the README now states — a passed stop time is
  a stop now with no reversal of the earnings beyond it, which a ruling programs
  as its own `reverse`. The delta requirement's "one stop event" already implies
  it; the fresh-context check suggested naming it, and triage may prefer the delta.
- For section 3's rows: the lane mandate's authority entry is `chosen` with no
  notice (`kit/deal-lifecycle`'s `authorities.py`), so a ruled stop at the ruling's
  instant takes effect at once. A `penalty` reverses each part's snapshot `held`
  (earned and unreleased; a rate part's `reserved` is not held, as the rate-part
  penalty case shows), read after the ruling's earlier
  effects, so a `reverse` of earnings since the end placed before it leaves the
  penalty only what remains. The double's integration suite now has a rate-part
  helper, `support.Lane.approve_rate`, and a `Recording` payments peer.
- A penalty's reversals are kept once one is taken: if money is released from an
  unprotected part between a failure and the resume, a kept reversal can exceed
  what is still held and be refused on every resend. No lane row meets this; it is
  an unowned row of Goal 8's "Work this goal found and leaves unowned" in
  `docs/development/ROADMAP.md`.
- `scripts/change-workflow run test-before` cannot run this package's tests (no
  project environment); a later session needing that proof should not expect it.
- Two fresh-context checks ran. The first found stale "extends, reverses and lifts"
  comments, this change's own row and proposal naming only `stop`, the operator
  decision's `stop` untested, and a kept stop whose time passed refused forever;
  all fixed. The second found the rebuild on a refused first event wrong after a
  lost answer (a middleware refusal comes before payments' replay), fixed with
  `Case.reached`; the penalty split moved to a pure `penalty_reversals`, unit
  tested, with one integration case left; penalty retries and a rate-part penalty
  tested; the edge case above recorded as unowned. Declined: the convergence row's
  deliverables cell is left for its reverification, which its Notes now say.

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
      Done: `e2e-tests/tests/e2e/roles/helpers/producer_assertions.py`, functions over
      the snapshot as JSON: `assert_payer_stop`, `assert_funds_exhausted`,
      `assert_payee_stop_pending` and `assert_payee_stop` (the preemption's two
      observations, pending then final), and `assert_term_end`. Each collects every
      differing field and fails naming it with expected and actual values (and, for a
      related field, what it relates to). Exact: cause, treatment, the stopping
      event's account (the `terms` issuer for a terms stop), nothing left reserved, a
      funding stop's settled `N × price`. By relation: `effectiveAt` (or a pending
      stop's `at`) equal to the stop event's `receivedAt` plus the notice, the funded
      boundary passed in, or the Agreement's end; settled gross the periods between
      `started` and the stop (the one in progress too for `charged`) at the price;
      `held + released` equal to it; `refunded` the gross less settled and reversed.
      Ignored, stated in the module docstring: identifiers, signatures and the
      snapshot's signing identity, `observedAt`, sequence numbers (an event's is
      read only to find the stopping event), fee and net, holds, releases,
      extensions. A funding stop's treatment is ignored too: it falls between
      periods. The read and the assertion are separate functions rather than
      separate stages (see the handoff). Unit (`tests/unit/test_producer_assertions.py`,
      the assertions directly, on snapshots from the payments kit's
      `PaymentsAuthority` engine — the engine the payments double serves — driven
      through each row's input on the lane's terms, the term ending five minutes
      into a thirteenth period, rather than on a committed recording): each passes;
      an altered exact field and an instant off its relation each fail naming the
      field and both values; an altered refund names its relation and both values;
      a term end settling its partial final period as a whole one fails; two
      differing fields are both named; a changed transaction id, `observedAt`,
      `latestEventSequence`, proof, ledger and request ids are ignored — 26 pass.
      The engine's further reservation first ships in `arkhai-kit-arkhai-payments`
      0.9.0, so `e2e-tests/pyproject.toml`'s floor on it rises from 0.4.0 (already
      below what the helpers used) to 0.9.0, with `arkhai-e2e-tests` 0.3.0 to 0.3.1
      and `make lock PROJECTS=e2e-tests`.
      `scripts/change-workflow run test-before` fails at collection, the base's
      `e2e-tests/tests/conftest.py` importing `web3` with no project environment,
      which shows nothing about the change.
- [x] 2.2 Make `e2e_vm_recurring_purchase`'s buyer stop and `e2e_vm_rate_servicing`'s
      three rows assert through them, the lanes' step-and-read stages unchanged, and the
      bare-metal rows untouched (D6). Verify (unit): `make -C e2e-tests test-unit`
      passes, the stage order and handoff checks (`ORDERS`) included.
      Done: `Recurring08_BuyerEnds`, `Exhaustion07_FundsRunOut`,
      `Preemption07_SellerNoticeHeld`, `Preemption08_StopTakesEffect` and
      `MaximumTerm07_TermEnds` read the snapshot as before and assert through the
      shared functions in place of their inline checks; the preemption keeps its
      lane-only checks that the stop is due at the notice's lane instant plus the
      notice and within the first reservation. No module and no stage order changed.
      These stages are shared with bare metal, which declares the same classes, so
      its rows assert through them too while its modules are untouched (a VM-only
      copy would break the rule that a compute lane's shared stage has one body);
      the bare-metal rows were run for that (2.3). Unit: `make -C e2e-tests
      test-unit` — 1051 passed, 1 skipped, `ORDERS` and the handoff checks included.
- [x] 2.3 Verification point: the VM lane's recurring purchase and rate rows pass on the
      shared assertions (system, the VM lane's Compose stack: `make -C e2e-tests
      test-e2e-vm "E2E_MODULE=e2e_vm_recurring_purchase or e2e_vm_rate_servicing"`).
      End-to-end: `e2e_vm_recurring_purchase`, `e2e_vm_rate_servicing`.
      Nothing is owed to validation.
      Evidence: system, the VM lane's Compose stack, the command above — 121 passed,
      1862 deselected; the stack taken down after (`make -C e2e-tests e2e-vm-down`).
      Outside the plan, since the shared bodies also run in bare metal: system, the
      bare-metal lane's Compose stack, `make -C e2e-tests test-e2e-bare-metal
      "E2E_MODULE=e2e_bare_metal_recurring_purchase or
      e2e_bare_metal_rate_servicing"` — 249 passed, 1734 deselected; that stack
      taken down after (`make -C e2e-tests e2e-bare-metal-down`).
      End-to-end scenarios confirmed as listed; they are lane-double evidence that the
      double emits what each shared assertion expects, and the bare-metal recurring
      purchase and rate rows now exercise the same assertions.
      `scripts/change-workflow run pre-commit` on the final tree:
      `after-functional-change` passed; `pre-commit-functional` passed (local
      evidence for tree `3d2f5beadd95`: `check-packaging` and `make test`); the
      workflow checks passed and `check-repository` passed 8 of 9, documentation
      citations reporting only section 8's summary, as in section 1.

Handoff (section 2):

- The plan's "a stage that reads … and a stage that asserts … are separate" is met
  as two functions, not two stage classes: the shared stages keep reading as they
  did and call the assertion. Separate stage classes would change every module's
  stage order, bare metal's included, which the plan leaves untouched. For section
  5, a live module composes its own stages: the input its lane twin's stage sends
  (the buyer's `end`, a seller's notice), a bounded poll of the snapshot, then the
  same assertion. `Recurring08_BuyerEnds` and the rows' ending stages bundle the
  input, the read, the assertion and the storefront's servicing in one body, so a
  live module cannot subclass them whole; factoring the input out of each is
  section 5's to do.
- Inputs a live run must supply each assertion: the payer or payee account, the
  period price and seconds, the notice, and for funds running out the funded
  boundary read from the snapshot's `fundedThrough` before the stop and the
  number of periods the topology's balance funds; for the term end, the
  Agreement's end rounded up to the whole second.
- `Recurring08` used to assert one period's price held and released outright;
  the shared assertion checks the settled amount against the periods between the
  part's start and its stop, so the exact one period now rests on the stage
  setting the stop a minute into the first period and on `Recurring09`'s balance.
- `e2e-tests` is 0.3.1 in this change; a later section changing its `src/` or
  `pyproject.toml` takes no second bump.
- The fresh-context check found: the dependency floor (raised), docstring
  sentences describing live callers not yet written (rewritten), "issuer"
  ambiguous (now the snapshot's signing identity), a test class named `Lane`
  (now `Engine`), notes overstating the sequence and term-end coverage (tests
  added for a partial final period and two differing fields, notes corrected).

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
      Done: `e2e-tests/tests/e2e/roles/scenarios/vms/rate_dispute/test_seller_filing.py`,
      on its own executor, pool, resource and GPU model (`host_registry.py`). Differs
      from the plan in two places. The administrator's end is the storefront client's
      `admin_interrupt_deal` with `interruption_kind="failure"`, not the seller
      lifecycle client, which offers only `notice`, `read` and `list`; that route
      records the operator end, files `delivery_end` as the payee and begins the
      teardown. And since the double rules at filing and the end is at the filing's
      instant, "earnings since the end" would be nothing: the rule is held at its
      gate (`pause_before_effects`), lane time moves a period on past the second
      period's end, then the rule resumes, so the stop (its time passed) is a stop
      now, the reverse takes the period earned after the end, and the penalty (the
      Agreement's, 24 periods) is capped at the first period still held. That needs
      the part funded past its first reservation, so the row declares the rate
      rows' `Reservation06`. The storefront's recorded end is then the ruling's
      delivery end at the operator's instant (a `dispute-effect:` source sorts before
      the `operator:` one at the same instant), the part's final stop is the
      authority's, and the only filing is the operator end's own, accepted — no
      filing for the authority's stop, which is what its classification `ruling`
      yields; no route reads the classification itself.
      System, the VM lane's Compose stack, `E2E_MODULE=e2e_vm_rate_dispute` on the
      final code — the module's 35 stages pass (3.5's run), each dispute stage
      logged as run.
- [x] 3.2 The buyer's contested case row: on a delivered on-demand rate deal, the buyer
      files through the mediation kit's dispute adapter in the harness, as the VM dispute
      controls do; the storefront's respondent discovery contests it; an operator
      decision through the typed control client rules `stop` with `returned` and a
      `reverse`. Assert the ruled end recorded, the payer's returns, the teardown and the
      deal `ended` once the case closes (D6, D5's policy row's lane twin). Verify
      (system): the module passes in the VM lane.
      Done: `rate_dispute/test_buyer_contested_case.py`: lane time a minute into the
      second period, the buyer's filing claims the end at that instant; one servicing
      step appends the seller's answer; the operator decision rules a stop at the
      claimed end (`returned`) and a reverse of the held first period, closing the
      case. A servicing step then shows the ruled end (`ruling`, at the claimed
      instant), the authority's final stop and no filing. Both rows end with the
      shared teardown stages, the payer's balance down only by what the part kept
      (nothing, in both runs), and the seller's list `ended` with no outstanding code,
      no open case and no open extension, the double holding only the row's case.
      System, the same run — its 34 stages pass.
- [x] 3.3 Write the two dispute assertions over the producer's output — the filing's
      per-part protection; the ruled entry's basis and effects and their applied state;
      the snapshot's authority stop, reversals and lifted extensions; the closed case —
      with exact, relational and ignored fields named as in 2.1, and have both rows
      assert through them (D6). Verify (unit, `e2e-tests/tests/unit/`): each passes on a
      recorded double output and fails naming the field on an altered one.
      Done: `producer_assertions.assert_payee_filing_ruled` and
      `assert_contested_case_ruled`, over the record as the mediation kit's public
      client reads it (`helpers/mediation.py`'s new `read_record`, as the buyer, each
      entry verified against the Agreement's record key) and the payments snapshot.
      Exact: filed once by the filer, the part held; the basis; the effects' kinds in
      order, each applied; the case closed as ruled; the authority's stop with
      `returned`, nothing reserved; the extension lifted; for the contest, one answer
      by the payee before the ruling; the reverse amount where the caller's ruling
      fixed it. By relation: the extension the filing reports is the one the
      authority extended and lifted at payments; the ruled entry's effects are the
      closed entry's; the stop stated at the delivery end and effective then or at
      its receipt once passed; the seller's reverse the periods earned after the end;
      the penalty's reversals the Agreement's penalty capped at what the part held;
      the refund the rest. Ignored: record references and signatures, payment
      payloads (reversals matched to effects by order), and the penalty effect's
      recorded amount. Both rows assert through them, so the lane run asserts the
      doubles' real outputs; that run is the only evidence on those. Unit
      (`tests/unit/test_producer_dispute_assertions.py`, 13 pass) is not on a
      committed recording, which the logged outputs make too large to commit (the
      filed entry carries the whole Agreement), but on snapshots the payments engine
      produces from payment events the test writes as the mediation double's
      `service.py` sends them, keys and payloads included, and record entries the
      test writes in the double's shape, each validated by the mediation kit's
      `RecordEntry` model (a stub Agreement in the filing): each assertion passes,
      the seller's with a penalty above and below the holdings; another basis,
      another stop cause, an effect left prepared, a reverse other than the earnings
      since the end, a penalty beyond its cap, a stop effective before its receipt,
      an extension left open, a missing contest and a reverse amount other than the
      caller's each fail naming the field and both values; with no reverse amount
      given, the policy's amount is not compared; renamed record references,
      payloads, a signature and `observedAt` are ignored by both. `read_record` is
      unit tested against the mediation kit's `MediationContractFake`
      (`tests/unit/test_mediation_helper.py`): a filed, ruled and closed case read as
      the buyer in pages of two, entries returned in sequence; a tampered entry
      raises the kit's `RecordVerificationError`. Its page size is a parameter for
      that test, 1000 by default. The engine helper both payment-assertion unit
      files share moved to `tests/unit/payments_engine.py`.
- [x] 3.4 Register the marker (`e2e_vm_rate_dispute`, lane-double evidence) in
      `e2e-tests/pyproject.toml` and the VM lane's default module list in
      `e2e-tests/Makefile`, and describe the rows in `e2e-tests/README.md` (D6). Verify
      (unit): `make -C e2e-tests test-unit` passes, `ORDERS` included.
      Done: the marker, the lane list and its comment, a "Rate-deal disputes" README
      section (which also names the payment assertions) and the module in the
      shared payment-scenario list. `tests/unit/test_recurring_purchase_stages.py`
      holds both modules' shared stages to their orders, reads `rate_dispute/stages.py`
      for the handoff check with `RateDisputeState`'s fields, and its reservation
      check now reads a module's whole run order, so a domain stage setting lane time
      past the first reservation (`SellerFiling10_RulingApplied`) is held to
      reserving first. Where the domain's own dispute stages sit, and that their
      subclasses' bodies are empty, is held only by the handoff check, as the rate
      rows' domain stages are. Unit: `make -C e2e-tests test-unit` — 1081 passed, 1
      skipped,
      `ORDERS`, the hold and cleanup-order checks included.
- [x] 3.5 Verification point: the two rows pass, leaving no payment hold, mock rule or
      held loop (system, the VM lane's Compose stack: `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_rate_dispute"`), and the whole VM lane passes.
      End-to-end: `e2e_vm_rate_dispute`.
      Nothing is owed to validation.
      Evidence: system, the command above, on the final code — 69 passed, 2015
      deselected;
      the whole VM lane, `make -C e2e-tests test-e2e-vm` — 513 passed, 1568
      deselected, on the scenario code as committed but for `read_record`'s page
      size becoming a parameter (its default unchanged) and docstrings; the stack
      taken down after each. Nothing left held: each row's payment ends stopped,
      nothing reserved or held, its extension lifted, as its assertion and
      `RateDispute12` show; its teardown completed; and its cleanup finished without
      error — `lane_double_rules` fails a module whose rule still holds a case and
      `run_cleanup` raises on any step failing, the mock gates' rules removed among
      them — while the loops' holds release in their finalisers, which the modules
      after the rows in the whole lane, holding and stepping the same loops, also
      show.
      End-to-end scenarios confirmed as listed: `e2e_vm_rate_dispute`, lane-double
      evidence of the storefront's handling of a ruled stop on a rate deal.
      `scripts/change-workflow run pre-commit` on the final tree:
      `after-functional-change` passed; `pre-commit-functional` passed (local
      evidence for tree `0f85e67c3606`: `check-packaging` and `make test`); the
      workflow checks passed and `check-repository` passed 8 of 9, documentation
      citations reporting only section 8's summary.

Handoff (section 3):

- For section 6's live twins: `read_record` is the public read they poll; the
  dispute assertions take the record and snapshot whole. The seller's live ruling
  is the hosted authority's own, at its own time, so the reverse relation
  (periods earned after the end up to the stop) and the penalty cap need no lane
  instant; the contested case's reverse amount is ignored when `reverse_amount` is
  not given, since the topology's policy chooses it. Reversals are matched to
  effects by order, not by the double's payload; a producer that orders them
  otherwise fails the comparison, which is what it is for.
- The seller row's gate is how the lane makes the earnings since the end real;
  the hosted authority rules a filing later than it is filed anyway, and the live
  twin needs no gate.
- `admin_interrupt_deal` answers the filing's outcome inline; with the gate it is
  `accepted` and the case `applying`.
- The rows borrow `RateRow` from `rate_servicing/conftest.py`, leaving its notice
  and second-payer fields at their defaults; a row needing either would set it
  there.
- The fresh-context check found: `read_record` with no unit test (tests added
  against the kit's contract fake, with the page-size parameter); the 3.3 notes
  calling hand-written events and entries the double's (corrected, and the
  events now carry the double's keys and payloads); three failure tests checking
  only the field (now both values), ignored fields tested on one assertion (now
  both), the contested case's reverse-amount branches untested (tests added); the
  first targeted run predating the unit files (rerun on the final code); the
  leftover-state claim resting on later modules (restated on the cleanup
  fixtures); two docstring sentences on sequences and entries' `at` (corrected);
  an unused import (removed). Declined: a domain-stage order check, which the
  rate rows' domain stages lack too and the handoff check partly covers; and a
  `RateRow` of the rows' own, since the borrowed one carries what they need.

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
      Done: `helm/charts/storefront/examples/production-values.yaml`, values of the
      storefront chart installed alone, as the bare-metal example is of its chart:
      it states the globals the chart reads on its path, the release's own
      provisioning service and its principal (the registry's globals are read only
      for the internal registry, which it does not use); one agent, `seller`,
      settling in
      `arkhai.payments.v1` alone in live mode against `https://payments.example.com`;
      `[Settlement.rate_servicing.arkhai_payments]` with `charged` and `returned`
      and `setup = false`; an on-demand and a spot clause, USD 1.00 an hour paid by
      the hour, ten minutes to approve, `delivery_deadline_seconds = 1800` and a
      fifteen-day dispute window (the authority's fourteen-day minimum filing window
      plus a day, as the harness's default coverage); an external registry; no
      `[Time]`. Every principal is an Ed25519 placeholder of one repeated
      character, accounts the `00000000-0000-4000-8000-…` fixture form, URLs under
      `example.com`, and the header names the host, Secret and storage class names
      placeholders too; the payments key and `[[DisputeCredential]]` are named as
      runtime-Secret entries in the header. `base_url` states its port, which the
      VM storefront's loader otherwise warns of. Unit:
      `make test-release-tooling TESTS=scripts/tests/test_committed_time_sources.py`
      — 5 passed, its family check now naming both chart examples. Examples are
      packaged with the chart (`helm/.helmignore` leaves `charts/*/examples/` in),
      so the storefront chart takes 0.5.0 to 0.5.1 and the umbrella 0.5.0 to 0.5.1,
      its pin following (`origin/dev` holds 0.5.0 for both).
- [x] 4.2 Render it and run the storefront's own loader and startup check over the
      rendered `storefront.json`, as the bare-metal chart's test does with its example
      (`helm/charts/bare-metal-storefront/tests/test_render.py`, "the storefront's own
      loader"), under `STOREFRONT_PYTHON` (requirement scenario "The production example
      is rendered"). Verify (unit, the chart render tests, `make -C helm test-render`
      with `STOREFRONT_PYTHON` set): the render succeeds and the check reports no
      problem.
      Done, in `helm/charts/storefront/tests/test_render.py` ("the production
      example"): the chart renders alone over the example; one test reads the
      rendered `storefront.json` (payments alone in live mode, the declaration, both
      clauses' coverage, no time source, the derived provisioning URL and default
      site, no key or dispute credential); another runs the storefront's startup
      refusal over it under `STOREFRONT_PYTHON`, which finds nothing, and its loader,
      reading the port, principal and registries as rendered and reporting no
      setting it would read otherwise (no `[CONFIG]` line on its stderr). The
      refusal caught a payments receipt identity no Ed25519 key can spell, refused as
      an invalid `[Settlement.arkhai_payments]`; the loader's report showed a
      portless `base_url`, which it keeps raw, and the last assertion now holds the
      example to stating it.
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
      Done, a probe under `STOREFRONT_PYTHON`: the storefront's loader reads the
      rendered document, its settlement registry resolves the configuration, and
      each of `settlement_publication_defaults()`' clauses is published through the
      kit's `ClausePublication` step — the one the VM storefront's
      `publication_artifacts` composes — with the payments kit's preset helper
      (`payments_rate_wiring`), the storefront's default penalty multiple, a ready
      payments mechanism, an `arkhai.mediation.v1` authority advertising a fourteen-day
      minimum filing window, the recurring-options fixture's horizon (a day, no
      availability end) and no pool deadline — the fixture passes one, but the VM
      composition supplies none, so each clause's own publishes — at a fixed
      instant. It publishes an
      on-demand option (payer entitlement alone) and a spot one (payer and payee),
      each with the 1800-second deadline, the fifteen-day window, and treatments
      exactly `charged` and `returned`, and nothing refused, the default buyer's
      refusals included; rendered with `rate_servicing` removed, it publishes no
      option and refuses both clauses `rate_servicing_undeclared`. The step's class
      is the storefront's own, but the probe states its wiring as
      `publication_artifacts` does rather than taking it from the composition, so
      the two could drift without this check failing; the rest of
      `publication_artifacts` — readiness of a reachable service, the listing's
      resources — is not run, since the render check has no service.
- [x] 4.4 Verification point: the chart render tests pass with the loader and
      publication checks run, not skipped, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; the `helm` evidence kind runs these render and chart-to-loader
      checks against the tree, and no pipeline scenario reads the example.
      Nothing is owed to validation.
      Evidence: `make -C helm test-render`, the VM storefront environment built by
      `make init-storefront` so `test-render.sh` sets `STOREFRONT_PYTHON` — every
      chart's checks pass, the three example tests among them reporting `ok` and no
      check reporting a skip, the subchart-pin check among them after the bump.
      `scripts/change-workflow run pre-commit` on the final tree:
      `after-functional-change` passed; `pre-commit-functional` passed (local
      evidence for tree `d900fc7b6c65`: `check-packaging` and `make test`, whose
      deployment-packaging target runs these render checks); the workflow checks
      passed and `check-repository` passed 8 of 9, documentation citations
      reporting only section 8's summary, as in sections 1 to 3.
      End-to-end scenarios confirmed: none, as planned.

Handoff (section 4):

- For section 7's seller quickstart (7.1, "the TOML shown parses as the
  storefront's settings, the same loader as 4.2"): the example's agent `config` is
  the TOML to show, and `_startup_refusal` with `_example_config` in the chart's
  render test is the loader check to reuse; the quickstart should point at
  `helm/charts/storefront/examples/production-values.yaml`.
- The VM storefront chart rendered alone needs `global.provisioning` (and the
  registry globals unless `config` names `registry.urls`): the example states the
  former and names its registry, so it installs with the chart alone.
- The chart's own checks do not validate a principal's spelling; only the
  storefront's loader does, so a placeholder change to the example wants
  `STOREFRONT_PYTHON` set when its render tests run.
- For closeout's promotion: `docs/guidance/repository/chart-render-tests.md`,
  "Where they live and how they run", describes what the VM chart's render test
  runs under `STOREFRONT_PYTHON` and does not yet name the production example's
  startup and publication checks, beside the bare-metal example's it names; 9.9's
  D8 lists only the specs and `deployment-state/configuration.md`, which has no
  production-examples passage, so the guidance file is the destination to add.
- The fresh-context check found: the test file's docstring describing only
  umbrella renders (updated), the probe comment and the 4.3 note attributing "no
  pool deadline" to the fixture (corrected: the VM composition's), the 4.2 note
  claiming a check caught the portless `base_url` (the loader assertion added makes
  it so), placeholders the header did not name (named), the 4.1 note's "two
  globals" (made precise), the probe's wiring stated rather than taken from the
  composition (stated in 4.3's note), and the guidance file above (left to
  closeout).

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
