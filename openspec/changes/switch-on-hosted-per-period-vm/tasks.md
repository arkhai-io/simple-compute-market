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

Round 1's triage fix (28 F1): the dispute assertions now bind the comparison to the
claim the scenario sent. Before, nothing compared a filing's claim or the ruled delivery
end with any input: a ruling consistent with itself on another end passed. Both
assertions take `claimed_end` and compare exactly the filed entry's
`filing.request.kind` (`delivery_end`) and `ended_at` with it. `assert_payee_filing_ruled`
also holds the ruling's `end_delivery` at to it, as a mechanical ruling of the claim
states it. `assert_contested_case_ruled` compares the ruled end only when given
`ruled_end`, as it does `reverse_amount`, since a live topology's policy chooses both.
Both rows pass `delivery_end_at`; the contested row passes it as `ruled_end` too, its
operator decision being the row's own. The module docstring's exact class now includes
the inputs a scenario sent. For 6.1–6.2: the seller's live module passes the end the
storefront recorded as `claimed_end`; the buyer's passes the end it filed and no
`ruled_end`. The lane double records `end_delivery` at its own clock when it rules,
which equals the claim in both rows only because lane time is held at the claimed
instant from filing to ruling.
Evidence: unit, `tests/unit/test_producer_dispute_assertions.py` — 18 passed, the new
cases a changed filed end and kind failing in both assertions naming both values, the
ruling's end and stop moved together half a minute (every relation still holding)
failing in both naming only the ruled end, and the contested case with no `ruled_end`
holding on the moved ruling; with `test_producer_assertions.py` and
`test_recurring_purchase_stages.py`, 85 passed. System, the VM lane's Compose stack,
`make -C e2e-tests test-e2e-vm "E2E_MODULE=e2e_vm_rate_dispute"` — 69 passed, 2020
deselected, both rows' `[s10]` and `[c10]` asserting through the new checks on the
doubles' and storefront's real output; the stack's teardown (`make -C e2e-tests
e2e-vm-down`) was refused in the triage session and is left to the owner.
`scripts/change-workflow run test-before` failed on import at the round's base (no
project environment, `web3` missing), as in sections 1 and 3: no proof the new tests
fail there. The fresh-context check found the module docstring's exact class not
covering the claimed end (widened to the inputs a scenario sent) and a kind mutation
using a value the contract lacks (`effects` now); nothing declined.
`scripts/change-workflow run pre-commit` on the fix's tree: `after-functional-change`
passed; `pre-commit-functional` passed (local evidence for tree `414b73918d4d`:
`check-packaging` and `make test`); the index, tasks, skills and strict OpenSpec checks
passed, and `check-repository` passed 8 of 9, documentation citations reporting only
section 8's summary.

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
      Done: `LaneTime.reach` takes `recorded_by_authority` and `bound`: on wall time
      it waits for an instant an authority recorded as the effect of the scenario's
      own request, refusing one further off than the bound before any wait; any
      other instant stays a blocked skip; injected runs set it as before.
      `wait_until` takes a `bound` (default the old two minutes). `poll_until` reads a
      producer's public read until a predicate holds, failing at its bound, measured
      on the monotonic clock, naming what it waited for and the last read.
      `recurring_purchase_stages.reach_lane_instant` passes both through for a run
      with no lane time. Unit (`tests/unit/test_lane_time.py`, `LaneTime` with fake
      parties and wait, `wait_until` and `poll_until` with fake clocks): a recorded
      instant waited for within its bound; one past its bound refused with no sleep;
      the wait sleeping until the instant passes; an unrecorded instant still a
      blocked skip; an injected run setting a recorded instant; a poll returning the
      first read carrying the output, and failing at its bound naming both; and
      `reach_lane_instant` with no lane time, the path a hosted run takes, skipping
      an unrecorded instant, refusing a recorded one past its bound before any wait,
      and returning at once for one already passed (those three on the real wall
      clock, sleeping never) — 41 pass.
      `scripts/change-workflow run test-before` fails at collection at the round's
      base (`web3` missing, no project environment), as in sections 1 to 3: no proof
      the new cases fail there.
- [x] 5.2 Read the live scenarios' period, payee notice and maximum term from run
      settings, defaulting to the lanes' values (D4), and have the live modules refuse a
      lane-owned payments target with a blocked skip naming it, since a double yields no
      live evidence. Verify (unit): the settings parse and default, and a lane-owned
      target skips.
      Done: `helpers/live_verification.py` reads the `LIVE` section: PERIOD_SECONDS,
      PAYEE_NOTICE_SECONDS, MAXIMUM_TERM_SECONDS and POLL_BOUND_SECONDS, defaulting to
      the lanes' 900, 120, 3600 and 120, failing a value that is no positive whole
      number of seconds, a term past the listing's hour, a period past the term and
      a notice not inside it — not every term no deal can hold: the market refuses
      the rest at publication or negotiation, which the README's "Run settings"
      states (a term shorter than approval's expiry plus the delivery deadline and
      a period, an approval window, deadline and period not fitting the listing's
      hour); and the provenance
      SOURCE_REVISION, TARGET_ALIAS and PAYMENTS_REVISION, a blocked skip naming each
      missing one. `payments.live_payments` is a blocked skip naming a lane-owned
      target before anything else. Unit (`tests/unit/test_live_verification.py`,
      `tests/unit/test_payments_helper.py`, the readers directly over a stubbed
      setting lookup): defaults, short terms as numbers or text, bad values and terms
      each named, the provenance read and its skip, a lane-owned target refused as
      `True` or `"true"`, an external target taken, none blocked — pass.
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
      Done: the shared stages read the option's per-period terms from the driver
      (`RecurringPurchaseDriver.rate_terms`, a `RateTerms` whose lanes' value
      `LANE_RATE_TERMS` is the old constants; both domains' recurring drivers default
      to it), so `Recurring04` and `07`, which the live modules run, and the option's
      clause and check hold a live run's period (`08` and `09`, lane-only, read it
      too); only the clause is unit tested at another period. The buyer's end (`end_by_the_buyers_stop`) and the
      seller's notice (`submit_the_sellers_notice`) are factored out of `Recurring08`
      and `Preemption07`, their state writes left in the stages' bodies for the
      handoff check. `VmLiveRatePurchaseDriver` asks `market buy` for the run's term
      in seconds. Four modules under `scenarios/vms/live/` (marker
      `e2e_vm_live_rate_servicing`, in no lane), each on its own host, pool, resource
      and GPU model (`host_registry.py`, RTX 3090 Ti, 3090, 3080 Ti, 3080), run their
      twin's shared stages through `Stage09c2`, then `live/stages.py`'s: `Live00` logs
      the label and provenance (the provisioning mode as the provisioning service
      reports it); the buyer's stop, funds running out (the rate payer holding
      exactly three periods' price, else a blocked skip naming it; each funded
      boundary reached in turn until the terms stop), the preemption (pending, then
      its recorded instant reached and the final stop) and the term end (the
      Agreement's end reached), each polling the snapshot and asserting through
      section 2's assertion, with no stage after. Each module declares
      `OBSERVATIONS`, so `qualification.py` logs its outcome. The modules take their
      prerequisites first among their fixtures (`live/conftest.py`):
      `payments_config` (a lane-owned target, none, or one the run states is in live
      mode a blocked skip), `live_provenance`, `mock_provisioning` (real execution a
      blocked skip), and the payer — `funded_buyer`, at least one term's price, or
      for funds running out `funded_rate_payer`, exactly three periods' price, its
      account and key settings the run owes and a term no longer than the three
      periods failing naming the setting — so a topology missing a requirement is a
      blocked skip naming it before the module's holds and anything it buys; only
      the session's fixtures and the VM lane's autouse, idempotent host
      registration set up before them. Funds running out holds the stop's boundary
      before the Agreement's end, and reads the boundary from the part's
      `reservedThrough`, which a stopped part still reports where the snapshot's
      `fundedThrough` is gone; the preemption fails naming the notice when it is no
      shorter than the term left. Unit: `make -C e2e-tests test-unit` — 1151
      passed, 1 skipped: the four modules in `ORDERS` (their stage order and
      handoff checks read source), and `test_scenario_cleanup_order.py` reading the
      fixture order pytest resolves for them — holds released after their cleanup,
      and, new, every prerequisite set up in order before the first hold, every
      live module listed for that check. The live stages themselves run only
      against a hosted target (section 8); in this repository they are evidenced only
      as ordered and handed off by those source checks, and as refusing the lane's
      double in the VM lane (5.5); the provenance, mock-mode and balance skips run
      first against a hosted topology (section 8). Outside the plan's "Touches"
      line: the shared stage modules, both domains' purchase drivers,
      `host_registry.py`, `rate_servicing/conftest.py`'s `RateRow` comment, the
      Makefile's lane comment, `qualification.py`'s docstring and
      `tests/unit/test_scenario_cleanup_order.py`.
- [x] 5.4 Write each module's topology requirements in prose beside its description
      under a "Live verification" heading in `e2e-tests/README.md`: what it proves,
      mock provisioning, Arkhai payments in test mode executing rate parts, its accounts
      and starting balances, the run settings it reads, and the balance reset and
      cleanup its caller owes between runs; naming no infrastructure (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` passes.
      Done: `e2e-tests/README.md`, "Live verification": what the modules prove, the
      table of inputs and compared outputs, and the topology requirements in prose —
      mock provisioning, Arkhai payments in test mode executing rate parts, the
      accounts and the rate payer's exact balance, the `PAYMENTS` and `LIVE`
      settings and the limits a deal places on the terms, and what the caller owes
      between runs — naming no deployment; the
      shared payment-scenario list names the marker, and the Makefile's lane comment
      says it is in no lane. `make check-doc-citations
      CHANGE=switch-on-hosted-per-period-vm` reports only section 8's summary, as in
      sections 1 to 4.
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
      Done. System, the VM lane's Compose stack, the command above on the final code
      — 190 passed, 110 skipped, 1964 deselected: every skip is one of the four live
      modules' 110 stages, each skipped at `payments_config` with `blocked: the
      payments target https://payments-double:8443 is a lane's own double
      (PAYMENTS.LANE_OWNED), which yields no live evidence`, and each module logs its
      observation (the buyer's stop, funds running out, the spot preemption, the term
      end) unproven naming that reason for every stage, so no stage ran; the
      recurring purchase, rate servicing and rate dispute rows pass beside them on the
      shared stages. The same command passed the same way on the code before the
      second fresh-context check's fixes. System, the bare-metal lane's Compose
      stack, `make -C e2e-tests test-e2e-bare-metal
      "E2E_MODULE=e2e_bare_metal_recurring_purchase or e2e_bare_metal_rate_servicing
      or e2e_bare_metal_rate_watchdog"` — 249 passed, on code whose shared stages
      differ from the final only in `Recurring06`'s assertion message and
      docstrings. Each stack taken down after (`make -C e2e-tests e2e-vm-down`,
      `e2e-bare-metal-down`).
- [x] 5.6 Verification point: the `e2e-tests` unit suite passes, 5.5 holds, the whole VM
      lane passes, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` reports no failure but the citation of section 8's
      summary.
      End-to-end: none in the pipeline — `e2e_vm_live_rate_servicing` belongs to no lane,
      and its evidence is the deployment's (section 8); the lane twins are
      `e2e_vm_recurring_purchase` and `e2e_vm_rate_servicing`.
      Nothing is owed to validation.
      Evidence: unit, `make -C e2e-tests test-unit` on the final code — 1151 passed,
      1 skipped. 5.5 holds, as above. The whole VM lane, `make -C e2e-tests
      test-e2e-vm` with the lane's default module list and `e2e_vm_live_rate_servicing`
      added — 513 passed, 110 skipped (the live modules' refusals, as in 5.5), 1633
      deselected, on the code before the fresh-context checks' fixes; those fixes
      changed the live modules, their conftest and the unit checks, and in the lane's
      shared stages only docstrings, one assertion message and one line's wrapping,
      so the lane's own rows ran the final behaviour, and the live modules' final
      code ran in 5.5's command. `scripts/change-workflow run pre-commit` on the final
      tree: `after-functional-change` passed; `pre-commit-functional` passed (local
      evidence for tree `8e128778e8bb`: `check-packaging` and `make test`); the
      index, tasks, skills and strict OpenSpec checks passed, and `check-repository`
      passed 8 of 9, documentation citations reporting only section 8's summary
      (`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`). A
      first run, on tree `82883b2d30bc`, also failed history wording on a conftest
      comment's "no longer" (a comparison, reworded); the run above is on the
      reworded tree.
      End-to-end scenarios confirmed: none in the pipeline, as planned; the lane twins
      `e2e_vm_recurring_purchase` and `e2e_vm_rate_servicing` are lane-double evidence
      of the shared stages the live modules run, not of the live producer, whose
      evidence is section 8's summary.

Handoff (section 5):

- The section returned to planning once (commit "section 5, work in progress"):
  5.5 then planned a rehearsal of the live modules against the local Helm release,
  which cannot run there, for these reasons, kept for section 6, whose old 6.4 met
  the same ones:
- 5.2 has the live modules refuse a lane-owned payments target, and the local Helm
  release's payments target is its payments double marked lane-owned:
  `helm/local-values.yaml`, `e2e-tests.payments.lane_owned: true`. Run there, every
  live module is a blocked skip at its first fixture, by design, before any
  observation.
- The release's storefront cannot serve a rate deal: Bob's agent in
  `helm/local-values.yaml` declares no `[Settlement.rate_servicing.arkhai_payments]`,
  so publication refuses every recurring option (`rate_servicing_undeclared`, as 4.3's
  probe shows with the table removed), and the release's e2e profile states "the
  release serves no payment scenario"; validation's helm kind lists every payment
  module as not run against Helm for that reason (`reviews/34-validation.md`).
- Serving the modules there needs a values change outside the section's plan (Bob's
  declaration, the e2e profile's `LIVE` settings and short terms, and either
  LANE_OWNED cleared for the rehearsal, which contradicts 5.2's refusal, or a
  rehearsal-only bypass of it), and a deployment of the release, which the
  implementation step's rules do not admit (no deploy target; `kubectl` is denied).
  The replan made section 8's deployment run the only run of the live modules.
- For section 6's live dispute modules: `live/conftest.py` and `live/stages.py` are
  the pattern — the prerequisites first in `usefixtures` (`payments_config`,
  `live_provenance`, `mock_provisioning`, the payer's balance), each a module
  fixture that skips naming an unmet requirement, and the module added to
  `LIVE_GATES` in `tests/unit/test_scenario_cleanup_order.py`, which holds them
  before the holds; `Live00` for the label (its provenance names only the payments
  authority's revision, so a dispute module adds the mediation authority's, a
  `LIVE` setting beside PAYMENTS_REVISION); `poll_until` for the record and
  snapshot reads; `OBSERVATIONS` so `qualification.py` logs the outcome. A
  mediation target needs its own lane-owned refusal, as `live_payments` gives
  payments', and a fixture name declared with `name=` reads as an unknown
  finaliser to the cleanup-order check (below).
- For section 8's deployment: a run's wall-time length is set by the `LIVE` terms;
  the term end waits out the whole term and funds running out three periods, so a
  short period and term keep a run short, within what the market accepts: at a
  one-minute period the term must exceed the five-minute approval window, the
  five-minute delivery deadline and a period, so about a quarter of an hour
  serves; the rate payer's exact balance follows the period (README, "Live
  verification").
- For closeout's promotion of D4 (9.9): beside `test-compatibility/architecture.md`
  and `system-tests.md`, two permanent documents still say a wall-time run waits
  only for an instant the Agreement fixes, which `LaneTime.reach`'s recorded case
  now widens: `docs/guidance/repository/deal-scenarios.md`, "The discipline every
  scenario follows" (the wall-time bullet), and `docs/development/TESTING.md`,
  "Lane time". Both are destinations to add to D4's promotion.
- The recurring purchase's shared stages the live modules run read the period from
  the driver's `rate_terms`. The rate rows' lane-only stages
  (`rate_servicing_stages.py`), the watchdog row's and the rate dispute rows'
  (`rate_dispute/stages.py`) still read `PERIOD_GROSS` and `PERIOD_SECONDS`, which
  holds them to the lanes' period; a stage section 6 shares from the dispute rows
  with a live module reads the driver's terms instead.
- `scripts/change-workflow run test-before` cannot run `e2e-tests`' unit tests (no
  project environment, `web3` missing), as in sections 1 to 3.
- `test_scenario_cleanup_order.py` maps a fixture by its function's name, so a
  fixture declared with `name=` reads as unknown and so as one with a finaliser;
  the live fixtures are named by their functions, the helpers they call reached
  through the `live_verification` module.
- The fresh-context check found: funds running out buying a deal from a wrongly
  funded payer before its balance skip, so the observation would read failed (the
  check moved to the `funded_rate_payer` fixture, with a missing account failing as
  the companion's "Payment evidence ownership" asks); provenance skipped only
  after the purchase (now the `live_provenance` fixture); an unconverted funded
  boundary when the part had stopped already (now read as an integer); stale
  docstrings in `recurring_purchase_stages.py`, `lane_time.py` and
  `qualification.py` (rewritten); two long lines (wrapped); the closeout
  destinations above (recorded); `reach_lane_instant`'s no-lane-time path untested
  (tests added); and overstated notes — the settings' "terms no deal can hold",
  "before any hold or write", the shared stages' period, the source checks called
  collection, and a too-short term in this handoff (each corrected, the README
  stating the market's limits). Declined: none.
- A second fresh-context check, on the fixed diff, found: the settings' "terms no
  deal can hold" still in `live_verification.py`'s and its unit test's docstrings
  and a test name (narrowed), a double-only assertion message in `Recurring06` and
  `RateRow.rate_payer`'s comment (rewritten), "only the host registration" before
  the prerequisites (the session's fixtures too; reworded), the README's release
  of "its" reservations (it releases the site's, so the site holding only the
  run's is now a requirement), the long `usefixtures` lines (wrapped), no check
  holding the prerequisites before the holds (`test_scenario_cleanup_order.py`
  now does), funds running out able to take a term end for itself (the term
  longer than three periods required, and the boundary held before the
  Agreement's end), an underfunded buyer failing the term end (the
  `funded_buyer` skip), real provisioning and live mode failing rather than
  skipping (now skips), and a notice outlasting the term (now fails naming it).
  Declined: a stale funded boundary when one read shows both a further
  reservation and the stop — `fundedThrough` is absent once the one part has
  stopped (the payments kit's `PaymentsAuthority` snapshot sets it only over
  parts still running), so no such read exists; the boundary now comes from the
  part's `reservedThrough`, and the `max` with the stopping read covers a
  producer that reports one; and `HOURLY_GROSS`'s third definition, the purchase
  drivers' being the one-shot option's price, a separate offering whose
  unification is outside the section.

Fix from the sections 5–7 round's triage (`reviews/41-implementation.triage.md`,
41 F1, outside the plan): the buyer's-stop observation could pass with nothing
charged. `assert_payer_stop` settled `ceil(elapsed / period)` periods, zero for a stop
effective in the second the part started, and the live stage sent the stop as soon as
its earlier stages ended. The payments kit's contract fixture charges nothing for a
`charged` stop with no time elapsed (`fixtures/authority.py`, `_stop`), as the
archived serve-running-rate-deals design records, so the shared assertion keeps that
calculation and now also requires, by relation, the stop effective later than the
part's `started`, failing naming both instants — the lane twin's stop a minute in
holds it. `LiveBuyerStop` now sends the stop as its twin does,
no earlier than `STOP_INTO_PERIOD_SECONDS` after the Agreement's start, an instant the
scenario's own data fixes, reached with `reach_lane_instant(fixed_by_agreement=True)`
within the run's reach bound (at once when the earlier stages took longer; a part
started later than that instant still meets the assertion's check, which fails it
rather than passing), and fails naming LIVE.MAXIMUM_TERM_SECONDS when that instant is
not before the Agreement's end. The README's input column, `test_buyer_stop.py`'s and
`live/stages.py`'s docstrings say so. For closeout's promotion of D4 and D6 (9.9):
`deal-scenarios.md` and `TESTING.md`, "Lane time", admit on wall time "an instant the
deal's Agreement fixes, such as its start", which does not literally cover the
Agreement's start plus the scenario's own minute, though the delta's "its own data
fixes" and `system-tests.md` do; the promoted wording should cover it. The lane twins
pass `fixed_by_agreement=False` for the same instant, which an injected run ignores. Unit: `test_producer_assertions.py`'s new case, a payer stop in the
start second from the payments kit's engine, settling nothing, failing naming the
check and both instants (`make -C e2e-tests test-unit`, the round's fix evidence in
section 7's note). The live stage's wait runs only against a hosted target
(section 8).

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
      Done: `scenarios/vms/live/test_seller_filing.py`, marker `e2e_vm_live_dispute`,
      on its own host, pool, resource and GPU model (`host_registry.py`, RTX 3070 Ti),
      observation `the seller's filing`. Its twin's shared stages through `Stage09c2`,
      then `live/stages.py`'s: `Live00` (its provenance now names the mediation
      authority's revision, LIVE.MEDIATION_REVISION, for a module filing a case —
      the module overrides `live_provenance` with `mediation=True`); `LiveDispute07`
      holds the Agreement to pinning the run's dispute authority (another is a
      blocked skip naming both, `mediation.pinned_authority_difference`), then
      polls the snapshot until a period is earned and its earnings held, or the
      part stopped, bounded by the time left until the first period's end (the
      part's `started` plus the period) and the poll bound after it, and requires
      the part still running — a poll of the producer's output, not a reached
      instant, so `LaneTime.reach`'s recorded case is not widened;
      `LiveSellerFiling09` ends the delivery as a failure through
      `admin_interrupt_deal`, as 3.1's row does, and takes the storefront's typed
      refusal for want of a dispute credential (its seller lifecycle's
      `repair required: Agreement authority credential is missing`, matched as
      `MISSING_CREDENTIAL_REPAIR`) as a blocked skip naming that requirement —
      the reason is read from `kit/deal-servicing`'s seller lifecycle, not seen
      in any run here; `LiveSellerFiling10` polls the record
      until the case is closed and reads the snapshot once, then
      `assert_payee_filing_ruled` with the storefront's recorded end as the claimed
      one, the Agreement's penalty and the run's period. One poll, not two as
      planned: the snapshot is read once after the record shows the case closed,
      since the closed entry records each effect applied at payments; a snapshot
      lagging it fails the assertion naming the field. Shared with the lane row by
      factoring its inputs out of `rate_dispute/stages.py`'s stages into functions
      both call — `end_delivery_as_a_failure` and `filed_as_payee` (the end, then
      its answer held to the filing, split so the live stage reads a refusal
      between them), `file_the_buyers_claim`, `contest_as_respondent`,
      `premature_stop_penalty` — the lane stages keeping their double-only checks
      (the double's case state, the lane instant); the administrator's end now
      also requires the outcome's `filing`, from which the case reference is read.
      `pinned_authority_difference` fails, rather than reading as another
      authority, on an Agreement naming none. The record is read by `read_record` as the buyer, so
      `live_mediation` (`helpers/mediation.py`) refuses a lane-owned mediation target
      with a blocked skip naming it, as `live_payments` does payments', and fails a
      run with no MEDIATION.BUYER_API_KEY before anything is bought. The module takes
      `payments_config`, `mediation_target`, `live_provenance`, `mock_provisioning`
      and `funded_buyer` before its holds. Unit: `make -C e2e-tests test-unit`
      (1184 passed, 1 skipped): the module in `ORDERS` (`LIVE_ORDER`, its shared
      stages once each in order, and the handoff check over `live/stages.py`,
      which reads the union of every state's fields and so does not show which
      state declares them; `LiveRateState` carrying `RateDisputeState`'s fields and
      its own is a test of its own, `test_live_verification.py`), and in `LIVE_GATES`
      (`test_scenario_cleanup_order.py`, its prerequisites set up in order before
      any hold, read from pytest's setup plan); `live_mediation`'s refusal, external
      target, missing and unready target and missing token, and
      `pinned_authority_difference` on the mediation kit's contract fake's
      Agreement, the run's authority differing in nothing, another account named
      with both, and an Agreement with no lifecycle terms failing
      (`test_mediation_helper.py`); the provenance with and
      without the mediation revision and the skip naming it
      (`test_live_verification.py`). The live stages' bodies — the first-period
      poll, the filing and its credential refusal, the ruled output's read and the
      assertion's arguments — run only against a hosted target (section 8); in
      this repository they are
      evidenced only as ordered and handed off by those source checks and as
      refusing the lane's double (6.4).
- [x] 6.2 The buyer's contested case module: the buyer's filing through the mediation
      kit's adapter, the storefront's contest, then the ruling the topology's declared
      policy makes, read and asserted through 3.3's assertion; with no policy applied by
      the bound, the ruling observation is unproven naming the policy requirement, its
      filing and contest observations standing (D5, D13). Verify (unit): as 6.1, and the
      unproven outcome names the requirement.
      Done: `live/test_buyer_contested_case.py` (RTX 3070), observations `the buyer's
      filing`, `the storefront's contest` and `the policy's ruling`: the shared stages,
      `Live00` and `LiveDispute07` require all three; `LiveContestedCase08` files
      through `file_the_buyers_claim` claiming the end now; `LiveContestedCase09`
      (declaring the contest and the ruling) contests through `contest_as_respondent`
      in one servicing step, marking the case contested; `LiveContestedCase10`
      (declaring the ruling alone) requires the contest, so after a failed one it
      skips at once rather than waiting out the bound, and polls
      the record through `live_verification.await_case_closed` with the policy
      requirement, then `assert_contested_case_ruled` with the buyer's claimed end
      and no `ruled_end` or `reverse_amount`. `await_case_closed` fails at the bound
      naming the case, unless given a ruling requirement and the last record holds
      no `ruled` entry for the case, when it is a blocked skip naming the
      requirement (`RULING_POLICY_REQUIREMENT`, citing the README); a ruling made and
      the case still open at the bound fails, and so does a failure the read
      itself raises: `lane_time.poll_until` now raises `PollBoundPassed`, an
      `AssertionError` carrying the last read, which is all the helper catches.
      The stage marks the deal ending only when the snapshot shows the part
      stopped, so the cleanup ends an unruled deal by the buyer's own `end`. Unit
      (`test_live_verification.py`, the helper with a fake clock and the module's
      declared stages through `qualification`'s `stage_observations` and
      `observation_outcomes`): the record polled until closed; a case never closed
      failing at the bound naming it; no ruling of the case (another case's ruling
      beside it) a blocked skip naming the requirement; a ruling with the case open
      at the bound failing, not skipping; a read failing before the bound failing,
      not skipping; the skip the helper raises with `RULING_POLICY_REQUIREMENT`
      given as the ruling stage's reason leaves the filing and contest made and the
      ruling unproven with exactly that reason; a failed contest failing the
      contest and ruling, the filing made; a failed shared stage failing all three
      — pass, with the order, handoff and gate checks as 6.1. Not exercised in this
      repository: that `LiveContestedCase10` passes the requirement to the poll
      (read from its source only), and the module's cleanup in the last stage's
      teardown — `stage_result` counts a failed teardown as a failed stage, so
      the ruling reads unproven only if the buyer's own `end` succeeds with the
      case still open (the handoff).
- [x] 6.3 Register the marker `e2e_vm_live_dispute`, in no lane, and write both modules'
      topology requirements in prose under "Live verification" in `e2e-tests/README.md`:
      a hosted mediation authority serving filing, the respondent listing and record
      reads, the contested case's ruling policy in this repository's own words (a
      buyer's contested `delivery_end` ruled with a `stop returned` and a reverse), the
      accounts, settings, and the cleanup its caller owes — closing any case left
      awaiting an operator and resetting balances (D13). Verify:
      `make check-doc-citations CHANGE=switch-on-hosted-per-period-vm` and
      `make -C e2e-tests test-unit` pass.
      Done: the marker in `e2e-tests/pyproject.toml`, the Makefile's lane comment
      naming it in no lane, the shared payment-scenario list naming it, and under
      "Live verification" its command, what both modules do, a table of input and
      compared output, the contested case's three observations, and the topology's
      requirements: mock provisioning with the storefront's dispute credential (a
      deployment proves it with the storefront's own `check-mediation`; the
      seller's filing skips naming it on the storefront's refusal, the contest
      cannot read it and fails — corrected by 41 F2, the note after the handoff
      below) and the authority the buyer's registry recommends
      (an Agreement pinning another a blocked skip naming both, once bought — the
      opening paragraph now says such requirements are checked where the deal
      shows them); a hosted `arkhai.mediation.v1` authority against the payments
      target in test mode, serving filing with protection, appends, the respondent
      listing and record reads and applying effects before closing, its documented
      mechanical ruling of a payee's `delivery_end` stated as the output the
      seller's filing compares, not a topology requirement, so its absence at the
      bound fails; the ruling policy as the
      assertion holds it (once the payee has answered once, rule as an operator,
      basis `operator`, with exactly a delivery end, a `stop` returning its period
      and a `reverse` of its choosing, in that order, closing the case; other
      effects, order or basis fail); the accounts and the buyer's mediation token;
      the `MEDIATION` settings with LANE_OWNED unset and LIVE.MEDIATION_REVISION;
      and what the caller owes — topping up the buyer and closing a case left open.
      The README's opening paragraph describes the payment endings' form as theirs,
      and the rate modules' "No case is filed" became theirs alone.
      `make check-doc-citations` reports only section 8's summary, as in sections
      1 to 5; `make -C e2e-tests test-unit` — 1184 passed, 1 skipped.
- [x] 6.4 Show both modules inert on a lane, as 5.5 does: collected in the VM lane, each
      refusing the lane's doubles at its first live fixture with a blocked skip naming
      the lane-owned target, logging its observations unproven with that reason, and
      running no stage after; the lane twin `e2e_vm_rate_dispute` passing beside them
      (D6). Verify (system, the VM lane's Compose stack): `make -C e2e-tests test-e2e-vm
      "E2E_MODULE=e2e_vm_rate_dispute or e2e_vm_live_dispute"` passes, every skip a live
      module's refusal naming the lane-owned target.
      Done. System, the VM lane's Compose stack, the command above — 69 passed, 59
      skipped, 2223 deselected: the rate-dispute rows' 69 stages pass on the
      refactored stages (the administrator's end, the buyer's filing and the contest
      now through the shared functions); the 59 skips are the two live modules' 29
      and 30 stages, each at `payments_config` with `blocked: the payments target
      https://payments-double:8443 is a lane's own double (PAYMENTS.LANE_OWNED), which
      yields no live evidence`; each module logs every observation unproven naming
      that reason for every stage requiring it (116 stage reasons over the four
      observations, all that one), so no stage ran. The refusal is the payments
      target's, the first prerequisite; the mediation target's own refusal is the
      unit-tested `live_mediation`, which a lane never reaches. Run three times —
      before the first fresh-context check's fixes, after them, and on the final
      code after the second's (the lane stage's administrator end split into
      `end_delivery_as_a_failure` and `filed_as_payee`) — each with the same
      result (on the final code 69 passed, 59 skipped, 2228 deselected, the same
      four observation lines); the stack taken down after each (`make -C
      e2e-tests e2e-vm-down`).
- [x] 6.5 Verification point: the `e2e-tests` unit suite passes, 6.4 holds, the whole VM
      lane passes, and `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` reports no failure but the citation of section 8's
      summary.
      End-to-end: none in the pipeline — `e2e_vm_live_dispute` belongs to no lane; its
      lane twin is `e2e_vm_rate_dispute`.
      Nothing is owed to validation.
      Evidence: unit, `make -C e2e-tests test-unit` on the final code — 1184
      passed, 1 skipped. 6.4 holds, as above. The whole VM lane, `make -C e2e-tests
      test-e2e-vm` with the lane's default module list and both
      `e2e_vm_live_rate_servicing` and `e2e_vm_live_dispute` added — 513 passed,
      169 skipped, 1669 deselected: the skips are the six live modules' 110 and 59
      stages, every one of the 226 stage reasons over the eight observations the
      lane-owned payments target's refusal. That run was on the code before the
      fresh-context checks' fixes, which changed the live dispute stages and
      helpers the lane never runs past their first fixture, `poll_until`'s
      exception class (the live modules' alone call it), in `rate_dispute/stages.py`
      one comment and the split of the administrator's end into two functions,
      unit tests and the README; the lane twins' final code ran in 6.4's third
      run, and the rest of the lane touches none of it.
      `scripts/change-workflow run pre-commit` on the final tree:
      `after-functional-change` passed (no lock changed); `pre-commit-functional`
      passed (local evidence for tree `d5652a34cc83`: `check-packaging` and `make
      test`); the index, tasks, skills and strict OpenSpec checks passed, and
      `check-repository` passed 8 of 9, documentation citations reporting only
      section 8's summary
      (`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`). A
      first run, on the tree before the second fresh-context check's fixes, gave
      the same.
      End-to-end scenarios confirmed: none in the pipeline, as planned; the lane twin
      `e2e_vm_rate_dispute` is lane-double evidence of the inputs the live modules
      give — the administrator's end and filing, the buyer's filing and the contest,
      through the same functions — and of the assertions they compare with, not of
      the hosted authority, whose evidence is section 8's summary.

Handoff (section 6):

- Outside the plan's "Touches" line (the two modules, `pyproject.toml`, the README):
  `rate_dispute/stages.py` (the inputs factored into shared functions, the
  administrator's end split into `end_delivery_as_a_failure` and
  `filed_as_payee`, the lane stages' behaviour unchanged but the administrator's
  end now requiring the outcome's `filing`; `delivery_end_at`'s comment),
  `live/stages.py` (the dispute stages, `LiveRateState` extending
  `RateDisputeState`, `Live00` logging the mediation revision, `_poll_snapshot`
  taking a bound, `MISSING_CREDENTIAL_REPAIR`), `live/conftest.py` (the
  `mediation_target` and `buyer_evidence` fixtures, docstrings),
  `helpers/mediation.py` (`live_mediation`, `pinned_authority_difference`),
  `helpers/live_verification.py` (`MEDIATION_REVISION` provenance,
  `await_case_closed`), `helpers/lane_time.py` (`PollBoundPassed`),
  `host_registry.py` (two hosts, pools, resources, RTX 3070 Ti and 3070), the
  Makefile's lane comment, and the unit files `test_live_verification.py`,
  `test_mediation_helper.py`, `test_recurring_purchase_stages.py` and
  `test_scenario_cleanup_order.py`. `e2e-tests` stays 0.3.1, as section 2's
  handoff says.
- For section 8's deployment: the dispute modules need, beside the rate modules'
  topology, the `MEDIATION` section naming the hosted authority with the buyer's
  token, LIVE.MEDIATION_REVISION, the storefront's dispute credential for that
  authority, and the buyer's registry recommending it; POLL_BOUND_SECONDS must
  cover the authority's time to rule mechanically and the policy's to rule the
  contested case. The contest is one servicing step: a respondent listing that
  shows the case only later fails `the storefront's contest`. The first period's
  wait is up to a whole period, so a short LIVE period keeps both modules short.
- When no policy rules the contested case, the module's cleanup ends the deal by
  the buyer's own `end` with the case still open and its extension standing; if the
  hosted payments service refuses that stop, the last stage's teardown fails, and
  the ruling reads failed rather than unproven (the filing and the contest stand,
  since only the ruling stage requires it). Nothing here shows which the payments
  service does; a deployment seeing it records it beside the summary.
- Not met as the spec words it ("A requirement the topology does not meet MUST
  leave the observations needing it unproven"): in the contested case, a
  storefront holding no dispute credential fails the contest rather than leaving
  it unproven, since no route the harness holds shows the credential before a
  filing and the contest has none of the storefront's own; the seller's filing
  reads the storefront's refusal and skips. The README names the deployment's
  proof of the credential (`check-mediation`) and that the contest fails without
  it. For triage: accept it as the harness's limit, as section 5's "a requirement
  … the harness can read" does, or have the spec say so. A mechanical ruling not
  made within the bound is no such case: the README now states it as the
  authority's documented output, which failing to emit fails the observation as
  the spec's comparison requirement says.
  Corrected by the sections 5–7 round's triage (41 F2): the premise was wrong. The
  storefront's seller lifecycle reports a missing credential on every lifecycle read
  of the deal, before any filing — its authority outcome `Rejected` with
  `MISSING_CREDENTIAL_REPAIR` and state `repair_required`
  (`kit/deal-servicing`'s `seller.py`, `_observed`), which the buyer's read
  (`lifecycle_buyer_read`, `delivery_read`) returns. The contest now reads it first
  and is a blocked skip naming the requirement, so the requirement is met as the
  spec words it (below).
- For closeout's promotion of D6 (9.9), "bounded polling of a live producer for an
  effect of the scenario's own request": `LiveDispute07`'s wait for the first
  period's earnings is such a poll, bounded by up to a whole period plus the poll
  bound, with no instant reached; `system-tests.md`, `deal-scenarios.md` and
  `TESTING.md`, "Lane time", admit on wall time only an instant the scenario's
  data fixes, so the promoted paragraph should cover a poll whose bound outlasts
  the poll bound by the producer's own schedule.
- The seller's filing's claimed end is the storefront's recorded end, read from
  the administrator's answer; the buyer's is the instant the harness filed at. The
  hosted authority's ruling instant is its own, so the reverse relation and the
  penalty cap in `assert_payee_filing_ruled` need no lane instant, as section 3's
  handoff foresaw.
- `scripts/change-workflow run test-before` cannot run `e2e-tests`' unit tests (no
  project environment), as in sections 1 to 5.
- The fresh-context check found: the record poll catching an assertion raised
  inside a read, which a contested case would have read as an unmet policy
  (fixed: `PollBoundPassed`, with a test of a failing read); the first-period
  poll's condition narrower than its docstring (fixed: earnings held or the part
  stopped); the first-period wait passing `recorded_by_authority` for an instant
  derived from the recorded start (replaced by a bounded poll of the output); the
  pinned authority unchecked though readable (now a blocked skip naming both);
  6.2's outcome test writing its own skip reason (now the helper's real skip) and
  the unexercised stage wiring and teardown (stated in 6.2's note and above);
  `delivery_end_at`'s comment naming only lane time, and the README's policy
  requirement not stating the effects' order, basis and single answer (both
  fixed); and no single list of the departures from "Touches" (above). Declined
  then: skipping on a storefront without a dispute credential, which no route the
  harness holds can read — narrowed after the second check to the contest alone,
  and since made by 41 F2's fix, the storefront's lifecycle read showing it.
- A second fresh-context check, on the fixed diff, found: the spec gap above,
  then also covering the mechanical ruling (the seller's filing now skips on the
  storefront's credential refusal, and the README states the ruling as the
  authority's output); an Agreement with no dispute terms read as another
  authority and skipped (now fails); the first-period poll beyond the written
  wall-time rules (recorded above for closeout); the README's opening paragraph
  saying every readable requirement is checked before the purchase (now naming
  those the deal shows); 6.1's note claiming the handoff check shows
  `LiveRateState`'s base (corrected, with a test of its fields); two unit tests
  that would report a wrong skip as a skip (now catching both); the ruling stage
  running after a failed contest (now requires it); and the mediation authority's
  mode unstated (the README says it acts against the payments target in test
  mode). Declined: nothing beyond the contest's credential, above.

Fix from the sections 5–7 round's triage (`reviews/41-implementation.triage.md`,
41 F2, outside the plan): a storefront holding no dispute credential failed the
contested case's contest rather than leaving it unproven, as "Each live verification
scenario states its topology requirements" requires. `LiveContestedCase09` now reads
the storefront's lifecycle read of the deal through the driver before its servicing
step, and `storefront_credential_missing` — the authority outcome `rejected` with
`MISSING_CREDENTIAL_REPAIR` — makes it a blocked skip naming
`CREDENTIAL_REQUIREMENT`, so the contest and the ruling are unproven by it and the
buyer's filing stands. The seller's filing's skip names the same requirement. The
README's provisioning requirement and opening paragraph, and `live/stages.py`'s module
docstring, say so. The delta is unchanged. Unit (`test_live_verification.py`): the
check over a read refused for the credential, refused for another repair, pending
with that reason and accepted (only the first is missing); the contest stage given a
driver whose read names the missing credential skips naming the requirement before
asking the storefront anything, the ruling stage then skips at its prerequisite, and
the module's outcomes read the filing made, the contest and the ruling unproven by
that reason. That the hosted storefront's read carries the outcome rests on the
seller lifecycle's code; no run here removes the credential, so the stage's use of it
is proven only at section 8, as the seller's filing's skip is.

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
      Done: the section, after "6. Preview and publish", shows one TOML block — the
      declaration, `[pricing]` with `default_max_duration_seconds`, and the two
      clauses as `[[pricing.settlements]]` tables, the example's values with the
      payee account a placeholder, replacing the payments-only block's `[pricing]` —
      then the declaration, the term (a finite horizon, `recurring_horizon_unbounded`
      without one), the clauses (the on-demand penalty's default and override,
      collectible only from held earnings), the deadline (storefront-enforced, the
      site not, linking the handbook's runbook), the window against the option's
      authority (`dispute_window_before_delivery_deadline`), payout, the spot
      seller's `deals preempt`, and withdrawal (`rate_servicing_undeclared`, after a
      restart, since the declaration is read at startup). It names no later change:
      the deadline is described as the system stands. Verified by a render test
      rather than a one-off run, outside the plan's "Touches" line:
      `helm/charts/storefront/tests/test_render.py`,
      `test_the_seller_quickstart_shows_the_production_examples_rate_servicing`,
      takes the section's one TOML block, gives the placeholder the example's
      account, and requires it, parsed with `tomllib`, to equal the example's
      `rate_servicing` and whole `pricing`, so the two cannot drift; then the
      storefront's own loader reads the block as an operator's `storefront.toml`,
      beneath the rendered example with those tables removed, and the startup
      refusal finds nothing and 4.3's publication probe publishes an on-demand and a
      spot option with nothing refused; the stripped document alone publishes
      nothing, so the declaration, the clauses and a finite horizon all came from
      the TOML (the horizon's value is not asserted). Static configuration test
      (`static-configuration-tests.md`; the chart render tests, `make -C helm
      test-render`, `STOREFRONT_PYTHON` set by `test-render.sh`): every check passes,
      the new test `ok` and not skipped. With the example's
      `default_max_duration_seconds` removed for one run, 4.3's test failed on
      `recurring_horizon_unbounded` and this one on the TOML differing — restored
      after. Not shown failing before the change otherwise: the render tests are a
      script, not pytest, so `run test-before` does not run them; at the round's
      base the section is absent and the test's split raises. `make
      check-doc-citations` reports only section 8's summary, but it scans only the
      change's own documents; the new sections' links (`#serving-rate-deals`,
      `#offering-on-demand-and-spot`, `#settlement-consumer-configuration-and-cutover`,
      `deal-lifecycle/architecture.md#one-end-instant-transactional-admission`,
      `#7-on-demand-and-spot`) were checked by reading the headings they name.
      Outside the plan, two defects fixed. The production example (section 4)
      stated no horizon, and the storefront's packaged default,
      `default_max_duration_seconds = 0`, means none, so deployed alone it would
      refuse both clauses `recurring_horizon_unbounded`; 4.3's probe hid it by
      passing a day by hand. The example now states a day, and the probe reads the
      configuration's `default_max_duration_seconds` and
      `default_available_until_utc`, as `publication_terms.py` does for a pool with
      no override (the storefront chart stays 0.5.1, this change's unreleased
      version). And the quickstart's existing payments-only once-only clause ("2.
      Configure") stated no `dispute_window_seconds`, which
      `ArkhaiPaymentsPublicationInput` requires (no default; the once-only builder,
      `arkhai_payments_option_builder`, validates the clause with it), so it could
      not publish; it now states the window and a delivery deadline, the section's
      values, with a sentence pointing at the new section. Evidence for that one:
      the code read only — no test loads that block.
- [x] 7.2 `docs/buyer-quickstart.md`, a new section on on-demand and spot options: the
      default refusals and the waiver for each, approval refused when the balance cannot
      cover the first reservation, a top-up before the funded boundary keeping a deal
      running and after it a new deal, the premature-stop penalty collectible only from
      the seller's earnings still held, and the dispute remedy a case (D10). Verify: each
      command and flag shown is in the installed `market --help` output, and the
      citations check passes.
      Done: "7. On-demand and spot", after "6. Service and reclaim": a `market buy`
      selecting a recurring option (`arkhai_payments.billing_kind=per_period`, with
      `early_termination.payee=false` for on-demand or `true` for spot), what `buy`
      discloses before negotiating, the four default refusals and their waivers as a
      table with `--allow-unprotected-terms` (a treatment other than returning, so
      prorating too, is refused), how a refusal is reported, funding (approval
      refused `insufficient_funds`, a top-up before the funded boundary, a funding
      stop final and `market delivery`'s `funding_stop`), `market end` and
      `--end-now-regardless`, which files the surrender as a case, `buy --watchdog`,
      the penalty collectible only from held earnings, and a case as the remedy,
      any other filed through the authority's own interface (Goal 8's unowned row).
      The fresh-context check found two behaviours the first draft got wrong, both
      corrected from the source: `end --end-now-regardless` files the buyer's
      `delivery_end` (`ending.py`), and the default refusals are only logged
      (`BuyerTermsPolicy.__call__` reports them to `AuthoritySelection.report`,
      logging at info, and they never reach its `refusals`, which `emit_term_refusals`
      prints and `buy`'s exit code reads), so a buy they alone empty prints "No
      listings matched" and exits 0. That gap is a new unowned row in Goal 8's table
      (`docs/development/ROADMAP.md`). The second check found advice to compare
      options through `market listing show`, which shows no settlement option
      (removed), the watchdog described without its conditional bound, which
      `buyer-orchestration`'s companion requires wherever it is described, and
      without "consecutive" (both added), and the exit-code rule stated too narrowly
      (any refusal by those checks with nothing left exits 2; restated). Commands and
      flags checked against the CLI's source, not `market --help`: running the
      installed `market` was denied (no rule allows it), so Grep and Read stood in;
      flag existence and, after the two checks, the behaviour the section describes
      were read — `buy`'s options in
      `domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`
      (`--resource`, `--settlement`, `--duration-hours`, `--yes` from core's
      `assume_yes_option`, the four waivers and the shorthand from
      `kit/settlement-runtime`'s `TERM_WAIVERS`, `--watchdog`, `--watchdog-interval`,
      `--watchdog-threshold`), `end` and `delivery` with `--from` and
      `--end-now-regardless` (`kit/deal-lifecycle-buyer`'s `commands.py`, registered
      on the VM app by `end_cli.register`), and the settlement fields
      `arkhai_payments.billing_kind` (the payments kit's clause fields) and
      `early_termination.payee` (`kit/deal-lifecycle`'s `LIFECYCLE_QUERY_FIELDS`,
      a boolean as `kit/settlement-runtime`'s clause tests spell it). The disclosure
      rows are `buyer_terms.py`'s. No test runs the commands the section shows.
      `make check-doc-citations` — only section 8's summary (the section's links
      checked by hand, as 7.1).
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
      Done: "Serving rate deals", after "Payments access": the administrator's signed
      lifecycle list and read; "Leases the storefront has not delivered" — why the
      site holds an undelivered lease, the site's active VM leases with a null
      `activated_at_utc` past start (or commitment) plus the deadline, reading the
      deal, a servicing cycle run now, the administrator's failure interrupt, and
      terminating at the site when the storefront cannot service it; "Draining
      payment deals before a receipt key change" — trading paused, deals left to end
      (spot preempted), every payment deal listed `ended`, `receipt_identities` for the
      switch, `check-payments`, trading resumed; "What each dispute outcome shows" —
      the four `ending` codes and seven outcomes, the ruled end with no stop left
      `ending` with `payment_running` as the authority's to correct, and the
      authority's policy left to the authority. Differs from the plan: it links no
      published policy, since this repository knows no published location; it says
      the policy is the authority's to publish and points at an
      `arkhai.mediation.v1` authority's description's `contact`. The fresh-context
      check found the retiring receipt identity stated without the `valid_until` it
      must carry (`receipts.py` refuses one without; the cited
      `settlement-configuration/configuration.md` called it optional, and now says a
      retiring entry requires it — outside the plan), the deadline's cap
      at the term end, a page per servicing cycle, a negotiation already open when
      trading pauses, and the description it restated unlinked; each is fixed.
      Routes checked in the route tables, by Grep and Read (no `--help` run,
      as 7.2): the storefront's `GET /api/v1/admin/lifecycle` and
      `GET /api/v1/admin/lifecycle/{negotiation_id}` (`kit/deal-servicing`'s
      `routes.py`, administrators' signatures), `POST /api/v1/admin/pause`, `/resume`,
      `/lifecycle/resume`, `/lifecycle/{loop}/run-cycle` with the loop
      `deal-servicing`, and `/deals/{escrow_uid}/interrupt`, whose parameter takes a
      payment deal's negotiation id, with `interruption_kind` (the VM storefront's
      `admin_controller.py` and
      `deal_lifecycle.py`); the provisioning service's
      `GET /api/v1/contract/leases` filtered by `status` and `offering_mode` (`vm`),
      `POST …/terminate`, `retry-release` and `force-release`
      (`compute_provisioning_contracts/routes.py`, `leases_controller.py`, the
      administrator alone for the list); `LeaseView`'s `activated_at_utc`,
      `lease_start_utc` and `deal_ref.negotiation_id` (`compute_delivery/path.py`
      writes it); `market-storefront deals preempt --operation-key` and
      `check-payments`/`check-mediation` (`cli.py`, `groups/deals.py`). What a site
      termination becomes at the storefront is `classify_site_end`'s
      `unentitled_withdrawal`; the outcome rows rest on `DealSummary`, `ENDING_TEXT`,
      the watch's recorded causes (`ruling` for a ruled end, the payment stop's own
      cause) and `deal-lifecycle/architecture.md`. No test runs the routes the
      section shows. `make check-doc-citations` — only section 8's summary (the
      section's links checked by hand, as 7.1).
- [x] 7.4 Verification point: `scripts/change-workflow run pre-commit
      switch-on-hosted-per-period-vm` passes.
      End-to-end: none; documentation.
      Nothing is owed to validation.
      Evidence: `scripts/change-workflow run pre-commit` on the section's final tree
      but this note: `after-functional-change` passed, no lock changed;
      `pre-commit-functional` passed (local evidence for tree `253195c44d89`:
      `check-packaging` and `make test`, whose log shows the chart render tests'
      7.1 quickstart test `ok`); the index, tasks, skills and strict OpenSpec checks
      passed, and `check-repository` passed 8 of 9, documentation citations
      reporting only section 8's summary
      (`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`), as in
      sections 1 to 6. The example and the render test are outside the inert paths,
      so the functional hooks ran. Two earlier runs, before the fresh-context
      checks' fixes (trees `76b59cd3f74b` and `5692bc4a4062`), gave the same.
      End-to-end scenarios confirmed: none; no scenario reads the quickstarts or the
      handbook.

Handoff (section 7):

- Outside the plan's "Touches" line (the three documents): the render test 7.1 adds
  to `helm/charts/storefront/tests/test_render.py`, its module docstring, the
  `operator_toml` parameter of `_startup_refusal` and `_published`, and the
  publication probe reading the configured horizon; the production example's
  `default_max_duration_seconds`; the quickstart's once-only clause; the
  `valid_until` sentence of `settlement-configuration/configuration.md`; and a new
  unowned row in Goal 8's table of `docs/development/ROADMAP.md`. The test holds the
  quickstart's TOML equal to the production example's `rate_servicing` and
  `pricing`, so a change to either fails it until the other follows; the
  quickstart's block must stay the section's only TOML block, with the
  `<YOUR_PAYEE_ACCOUNT>` placeholder.
- The change's row in `openspec/changes/README.md` read `ready for implementation`,
  left so by the replanning of sections 5 and 6; it is `in implementation` again.
- For section 8's deployment and closeout: the production example only publishes
  recurring options because it now states `default_max_duration_seconds`; a
  deployment copying an older form of it would publish none.
- Running the installed `market` and `market-storefront` was denied in this session
  (no rule allows them), so 7.2's and 7.3's commands, flags and routes were checked
  against the CLI source and route tables instead; a later session needing `--help`
  output should not expect it.
- The handbook's "Serving rate deals" is the runbook `renewable-compute-lease-deadlines`
  retires in part (its abandoned-lease and unactivated-reservation subsection, once
  the site enforces the deadline); the seller quickstart's deadline bullet links it
  by its anchor, `operator-handbook.md#serving-rate-deals`.
- For closeout's promotion (9.9): D7's quickstart and D10/D11's documents are
  written here. D11's `deal-lifecycle/architecture.md` "Current limits" sentence and
  D1's caveat corrections stay closeout's, and the caveats wait for section 8's
  evidence (D3). The handbook says only what SCM relies on of the dispute
  authority, and points at the authority's own published policy and its
  description's `contact` rather than linking a document, since no published
  location is known to this repository.
- For 9.5: the buyer quickstart states that `market` files no case on a running
  deal but the surrender `end --end-now-regardless` makes, Goal 8's existing
  unowned row; and that a buy its default refusals alone empty says nothing and
  exits 0, the new unowned row.
- The fresh-context check's findings declined: the payments service's own facts in
  the quickstarts (the 7-day payout, held earnings, top-up behaviour) rest on the
  design's context, as D10 names them, not on code here; and that a refused
  approval (`insufficient_funds`) may surface to the buyer as an unhandled error
  rather than a clean refusal — the quickstart says only that nothing is bought,
  which holds, and the error's presentation was not traced further.
- Two fresh-context checks ran. The first's findings are in 7.1–7.3's notes; the
  second, on the fixed diff, found the `listing show` advice, the watchdog's bound,
  the exit-code wording, the `deployment-state` delta not naming the example's
  horizon (now it does, with 4.3's correction note), a test docstring saying "laid
  over" for "beneath", and two note phrasings (the test's level, an unasserted
  horizon value); all fixed. It also noted that `settlement-configuration`'s
  companion still says no shipped configuration declares rate servicing, which
  9.9's D1 corrects at closeout once section 8's evidence is in.

The sections 5–7 round's triage (`reviews/41-implementation.triage.md`; validation 42
passed at `68b5566e4`, the owner's notes 43 had none) fixed 41 F1 and 41 F2, each
recorded in the notes of the section it concerns (5 and 6). Evidence for the fix
commit:

- Unit, `make -C e2e-tests test-unit` — 1190 passed, 1 skipped: the payer stop in the
  part's start second failing (`test_producer_assertions.py`); the credential check
  and the contest's skip leaving the contest and the ruling unproven
  (`test_live_verification.py`). The first run failed only on the new contest test's
  own construction (the state's `domain_identity`, the ruling stage's method name),
  corrected.
- `scripts/change-workflow run test-before` could not run either test file at
  `68b5566e4` (`e2e-tests`' conftest needs `web3`, absent outside the project
  environment), as in sections 1 to 6. Before the fix, the same-second stop passes
  the assertion, and the credential names are not defined.
- `scripts/change-workflow run pre-commit`: `after-functional-change` passed (no lock
  changed); `pre-commit-functional` passed (local evidence for tree `6727c61660c5`:
  `check-packaging` and `make test`); the index, tasks, skills and strict OpenSpec
  checks passed; `check-repository` passed 8 of 9, documentation citations reporting
  only section 8's summary
  (`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`), which
  section 8 writes.
- A fresh-context check of the diff found no code defect. It found the stop's timing
  overstated as "a minute after" when `reach_lane_instant` reaches that instant or
  past it (now "no earlier than", with the assertion named as what refuses a stop in
  the start second); `live/stages.py`'s module docstring not naming the
  Agreement-fixed wait; the repository's wall-time wording not literally covering the
  Agreement's start plus the scenario's minute (recorded in section 5's fix note for
  closeout); 6.3's note and the handoff's "Declined then" still giving the contest's
  failure (each marked corrected); and the unit file's docstring not naming the
  credential skip. All fixed. Declined: listing the buyer's stop's
  LIVE.MAXIMUM_TERM_SECONDS failure in the README's settings paragraph — the market
  refuses any term short enough to meet it.

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
