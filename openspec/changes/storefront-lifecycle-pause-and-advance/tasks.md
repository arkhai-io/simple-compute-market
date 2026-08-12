# Implementation Tasks

Sections are ordered so the control surface exists before the scenarios depend on it, and
so the scenario backport lands with the change rather than after it — a scenario carried
today by a background sweep will simply stop advancing once pause halts the loops, and it
must be converted in the same commit that can stop it.

## 1. Pause halts every timer loop

- [x] 1.1 Confirm by inspection that `design.md`'s "Context" still holds: five loops, all
      started through `core_storefront.app_startup.start_storefront_background_task`, the
      pause flag read only by `sync_negotiation`, and the two loop bodies that live in
      core. Record drift in `design.md` rather than working around it. **Done.** Five loops, one shared seam, two core-bodied. No drift.
- [x] 1.2 Hold the task handles the startup helper already returns, in a VM-local registry
      keyed by the `StorefrontBackgroundTask.name` each loop is already given. The names
      exist; nothing keeps the handles today. **Done.** `market_storefront/lifecycle.py` keeps name→spec and name→handle separately, since a paused storefront has specs and no handles.
- [x] 1.3 Make `_set_globally_paused(True)` cancel every registered task and `False`
      restart them from the same factories. State at the registry why cancellation rather
      than a flag each loop consults: two loop bodies are in core and cannot see a
      VM-local flag, and one concept implemented two ways would be worse than a blunt one. **Revised and done.** Cancellation was replaced by a pause flag each loop consults once per cycle, after review found that `Task.cancel()` only *requests* cancellation and could interrupt a cycle part-way — the exact property task 1.4 was written to protect. Two `core_storefront` loops take the predicate as an optional keyword defaulting to `None`; the three VM-local loops read it directly. See `design.md`.
- [x] 1.4 Document the capacity poller's cursor consequence where it is true rather than
      where it is convenient: the poller's `last_applied` is loop-local, so a resume
      re-positions at the feed head and re-runs its full reconcile. Self-healing, and the
      reason a scenario resumes only at teardown. **No longer applicable, and better for it.** The cursor consequence was an artefact of cancellation. A loop held idle keeps its feed position, so resume continues rather than re-converging from the feed head. The claim was removed from the registry module, the resume route, `ARCHITECTURE.md`, and `design.md` rather than left as a stale caveat.
- [x] 1.5 Make pause and resume idempotent — pausing a paused storefront cancels nothing
      twice, resuming a running one starts no duplicate task. A duplicated poller would be
      invisible until two reconciles raced. **Done.** Both idempotent by construction — setting a flag twice is setting it once.
- [x] 1.6 Focused tests: pause stops each named task; resume restarts each; both are
      idempotent; a paused storefront still refuses new negotiations exactly as before.
 **Done.** `tests/unit/test_lifecycle_registry.py` — 8 tests asserting behaviour rather than bookkeeping: a running loop does work, a paused loop does none across ten intervals, pausing does not stop the task, resuming returns *the same* task to work, and a loop that exits on its own reports `exited` rather than `paused`.
## 2. Per-loop advance controls

Each endpoint calls the operation the loop was already invoking and returns what that
operation returns. No endpoint reimplements a loop body, and none synthesises a richer
response than the underlying call already produces.

- [x] 2.1 `claims_engine` → `ClaimsEngine.tick()`. `run()` is a thin loop over it, so the
      production handler is already isolated. **Done.** `/admin/lifecycle/claims/run-cycle` → `ClaimsEngine.tick()`.
- [x] 2.2 `fulfillment_resume` → `resume_incomplete_fulfillments_once(sqlite_client=...)`. **Done.** `/admin/lifecycle/fulfillment-resume/run-cycle` → `resume_incomplete_fulfillments_once`.
- [x] 2.3 `negotiation_watchdog` → `_watchdog_tick(sqlite_client)`. **Done.** `/admin/lifecycle/negotiation-watchdog/run-cycle` → `_watchdog_tick`.
- [x] 2.4 `capacity_events_poller` → the storefront's own `_full_reconcile`, the callback
      the poller invokes at startup and after a ledger reset. Record at the endpoint that
      this runs both the close and reopen passes unconditionally while the delta
      subscriber runs one or both by delta kind, so this exercises a superset rather than
      an identical path — and that a scenario needing per-kind routing is the trigger for
      extracting a one-cycle function from `site_events_poller` in core. **Done.** `/admin/lifecycle/capacity-events/run-cycle` → `full_capacity_reconcile`, which was lifted from the poller's closure to module scope so the poller and the control call one function rather than two that agree today. The superset caveat is stated at the route.
- [x] 2.5 Add no advance control for `site_projection_poller`;
      `POST /api/v1/admin/capacity/projections/refresh` already is one. Confirm rather than
      assume, and record the disposition. **Done.** Confirmed: `/admin/capacity/projections/refresh` already advances the projection poller; no second control added.
- [x] 2.6 Add the client methods for each new endpoint to both the sync and async
      storefront clients in this change, with the parity contract test
      `docs/development/TESTING.md` requires. **Done.** `admin_run_lifecycle_cycle` on both clients, plus `tests/test_lifecycle_client_parity.py`.
- [x] 2.7 Focused tests: each advance invokes its underlying operation exactly once and
      propagates its result; each works while paused, since that is when it is used.
 **Partly done.** Five integration tests exercise the routes while paused through the real typed client. Three assert the route's contract, not invocation count — the note previously claimed "exactly once and propagates its result", which those tests do not establish, and the claim is withdrawn rather than the tests overstated. The capacity test no longer patches `full_capacity_reconcile`: patching an owned production function is the mocked-internals shape `TESTING.md` forbids. Two attempts to replace it with an observable listing transition did not produce one against `tests/fake_site` for a reason not yet identified, so it asserts only what it can honestly observe and the transition assertion is recorded as owed in 2.8.
- [ ] 2.8 **Owed.** Assert a lifecycle advance through an observable state transition
      rather than through its return contract, at least for the capacity-events control.
      This is the assertion 2.7 wanted and could not produce against the current fake;
      identifying why the reconcile finds nothing to change there is the first step, and
      that answer is adjacent to `monotonic-listing-reconciliation`.

## 3. Observable pause state

- [x] 3.1 Report per-loop running state on the admin status surface, read from the task
      registry, replacing the bare `paused` boolean with something that distinguishes
      "flag set" from "loops actually stopped". **Done.** `loops` on `/api/v1/system/status` and on both pause/resume responses, in the server and client models.
- [x] 3.2 Add read APIs for any state a converted scenario needs to inspect between
      advances, rather than widening advance responses to carry it. Identify these from
      Section 4's conversion, not in anticipation. **Done.** No new read API was needed: the listing statuses the converted scenario inspects were already readable through `get_listing`. Recorded rather than skipped — the task said identify from the conversion, and the conversion identified none.
- [x] 3.3 Extend the smoke suite's pause/resume test to assert the loops stopped, not only
      that new negotiations are refused. Pause returning 200 has never proven the
      background work halted, and after this change that is the substantive half of what
      pause means.
 **Amended.** The smoke suite has no pause test to extend; the conftest's claim that pause/resume 'moved to the smoke suite' was stale and is corrected. Deliberately not added: a smoke test runs against a deployed stack and pausing one halts its background work for real, which is not a side effect a wiring check should have. Coverage lives in the storefront integration suite instead.
## 4. Scenario backport — all scenarios, this change

- [x] 4.1 Pause the storefront in each VM scenario's readiness stage and leave it paused
      for the run. Resume belongs in teardown only, since resume itself reconciles. **Revised and done.** An autouse fixture was replaced by an explicit `test_00_pauses_the_storefront` stage calling `pause_storefront`, which asserts every loop reports `paused`. A scenario should name the state it depends on, and this also keeps the pause with the scenario that wants it — the API-credits scenario shares the module and drives a storefront with no such control.
- [x] 4.2b **Done, with one scenario deliberately excluded and one coverage loss recorded.**
      Four more scenarios now pause in a named `test_00_pauses_the_storefront` stage —
      `test_buy_oneshot_buyer_cli`, `test_full_deal`, `test_full_deal_buyer_cli`, and
      `test_multi_registry` — and every listing-status assertion in them advances the
      capacity poller first. `test_non_erc20_settlement` is excluded: it is written as
      parametrized module-level functions rather than staged classes, so there is no
      readiness stage to pause in and adding one would restructure the scenario for a
      benefit it does not need — it makes no listing-status assertion.

      The prerequisite this task set was to check whether pausing the claims and
      fulfillment-resume loops breaks CLI-driven settlement. It does not: the settle path
      drives fulfillment synchronously, the only stage-event wait in these scenarios is on a
      `provision` event from that synchronous path, and no scenario asserts on claims output.

      **The coverage loss is real and worth stating.** The green run 31591230862 shows
      Bob's claims engine completing three full claim cycles — submitted, collectable,
      collected — entirely incidentally, and after this change it will not run unless asked.
      Nothing asserted on it before, so nothing fails; the suite simply stops exercising a
      path it was exercising by accident.
- [ ] 4.2c **Open — make the claims path deliberate rather than dropped.** Add an explicit
      `advance_storefront(..., "claims")` after settlement in one deal scenario and assert
      the claim was submitted. That converts incidental coverage into intentional coverage,
      which is strictly better than either the old accident or the new silence. Assert on
      submission rather than collection: collection depends on on-chain conditions this
      scenario does not control, and asserting it would reintroduce exactly the timing
      dependence this whole change removes.
- [x] 4.3b Assert the durable fulfillment identity at 09c, not `create_job_id`. That
      field is written only when a caller registers a lease with an Ansible job id, so a
      deal on the durable path never has one — the third instance in this campaign of a
      scenario asserting on the identity the old path produced. **Done.**
- [x] 4.2 Convert every assertion that currently depends on a loop having run into an
      explicit advance followed by the assertion. Work scenario by scenario rather than
      failure by failure: a stage that passes today because a sweep happened to fire is as
      wrong as one that fails. **Done for the scenario that had racing assertions.** The other VM scenarios assert on synchronous responses and on provisioning-side state, which the provisioning controls already gate.
- [x] 4.3 Delete the four single-sample listing-status assertions' dependence on timing:
      pause, reserve, assert closed *before* any reconcile, advance once, assert still
      closed. This is strictly stronger than either the polling or the single-sample form,
      and it is what turns `monotonic-listing-reconciliation` into a deterministic failure
      rather than a race. **Done.** Each reserve now asserts twice: once before anything can react, once after exactly one reconcile. Strictly stronger than either previous form.
- [x] 4.4 Audit the API-credits scenario. It runs against a storefront this change does
      not cover, so it keeps its current behaviour; confirm it does not share a fixture
      that pauses, and record the asymmetry where a reader will meet it. **Done.** With the pause now an explicit stage rather than autouse, the API-credits scenario simply does not call it and is unaffected. The limitation that its storefront has no lifecycle controls is recorded permanently in the `storefront-publication` spec delta, not only in change history.
- [x] 4.5 Re-check the stages that the claims engine, resume worker, and negotiation
      watchdog currently carry silently — `design.md`'s impact assessment found no
      assertion on any of them, but the assessment was made against the suite as it is,
      and Section 4 changes it. Any stage that stops advancing needs an explicit advance,
      not a longer timeout.
 **Done.** Re-checked after conversion: no stage asserts on claims, resume-worker, or negotiation-watchdog output, so none needed an advance. The controls exist for the moment one does.
## 4b. Startup wiring, and the interval a pause has to wait for

- [x] 4b.1 Fix `run_storefront_startup_steps(..., task_logger=logger)`. A rename of
      `logger=` to `task_logger=` across `startup.py` caught one call too many, and the
      storefront exited 3 at container start with `TypeError: got an unexpected keyword
      argument`. Every suite passed: `_startup_tasks` runs only inside a live
      application lifespan, so nothing below the end-to-end level executes it. **Done.**
- [x] 4b.2 Add `tests/unit/test_startup_wiring.py`, which walks `startup.py` for every
      call to the step runner and the loop registry and validates each keyword against
      the real signature. Verified against the defect: reintroducing it turns the test
      red. Recorded because the first version of this test inspected the `_start_*`
      helpers instead and passed against the very defect it was written for — the
      offending call was in `_startup_tasks`, which that inspection never reached.
      **Done.**
- [x] 4b.3 Shorten the timer intervals in the two e2e storefront configs only —
      `negotiation_watchdog_interval`, `claims_sweep_interval`, and
      `fulfillment_resume_sweep_interval` to 2s, against shipped defaults of 60s and
      30s. A loop can only observe a pause at the end of an interval, so the shipped
      values would make a scenario wait a minute before asserting anything. This changes
      when a loop notices, never what it does, and production keeps the shipped values.
      **Done.**

## 4c. Interruptibility cannot be expressed on an offer (found in run 31499398440)

- [x] 4c.1 **Resolved by restructuring, and the defect filed separately.** Both full-deal
      scenarios now trigger teardown by back-dating the lease rather than posting an
      interrupt. Expiry is what ends a lease in production; interruption is an operator
      escape hatch, and driving the main teardown path with the escape hatch left the
      ordinary path uncovered — `DealLease.backdate` was written for exactly this and had
      never been called by anything in the suite. Everything downstream (10b's explicit
      `check_leases` cycle, the held `vm_remove` gate, 11a, 11b) is unchanged, because it
      keys off the lease view and the mock rule rather than the interrupt response. The
      guard's own defect is now
      `declare-interruptible-on-a-compute-offer`. **Done.**
- [x] 4c.2 Rename the stage to match what it does — `TestStage10a_LeaseExpirySetup` /
      `test_10a_expire_lease_and_arm_teardown_gate`, and the phase banner with it. A stage
      named for interruption that expires a lease is worse than either. **Done.**
- [x] 4c.3 Declare `deal_lease` in 10a's `require_state`. The stage now reaches through it,
      so a missing lease view must skip rather than raise two lines later. **Done.**
- [ ] 4c.4 **Original note, retained.** `POST /admin/deals/{uid}/interrupt` gates
      on `offer_resource["interruptible"]`, and `ComputeResource` has no such field, so
      pydantic drops it and no deal in the suite can satisfy the guard. Its fallback test
      — a splitter-gated buyer escrow proposal — is also false for a plain ERC20 escrow.
      Three candidate fixes are set out in
      `compose-domain-wheels-and-policies/e2e-inventory-findings.md`; adding a first-class
      field changes the published offer's wire shape, which is why this is not a test-side
      choice. `11a` and `11b` are blocked behind it.

## 5. Documentation

- [x] 5.1 Rewrite the `pause`/`resume` endpoint summaries and `AdminPauseResponse`
      messages: pause halts timer-driven work as well as refusing new negotiations. This
      is a behaviour change on an existing operator endpoint and belongs in its
      description, not only in a spec. **Done.** Both summaries and both messages rewritten; resume's docstring states that resuming itself reconciles.
- [x] 5.2 Add the pause-verify-advance rule to `docs/development/TESTING.md`'s async
      discipline section, beside the existing no-sleeps rule it completes. **Done.** `docs/development/TESTING.md` gains 'Lifecycle discipline — pause, verify, advance' beside the no-sleeps rule it completes.
- [x] 5.3 Extend `docs/development/ARCHITECTURE.md`'s "Operator lifecycle controls" so it
      covers storefronts rather than reading as provisioning-only.
 **Done.** `ARCHITECTURE.md`'s operator-lifecycle section now covers storefronts and states the no-reimplementation rule for a loop whose work has no callable unit.
## 6. Validation

- [x] 6.1 Run the VM storefront unit and integration suites, the e2e harness suites, and
      the smoke suite. Disclose any suite not run. **Done, with one disclosure.** On a clean baseline with this change applied: `core/storefront-client` 24 passed; VM storefront 853 unit / 1 skipped and 165 integration; provisioning 622 unit+integration; e2e harness 13 unit / 2 skipped and 108 scenarios collecting; `scripts` 42. Two integration failures are excluded as environmental and pre-existing: `test_alkahest.py::test_rust` and `::test_python` need a local Alkahest chain runtime (Rust/Cargo/Foundry/Anvil) that this session does not have, and fail identically on the unmodified baseline. The storefront's `make test` target could not be used because its `reinit` step re-resolves `[rl]`'s torch against a python-3.13/darwin/arm64 marker with no wheel; `uv sync --frozen` plus targeted `--reinstall-package` of the seven edited internal wheels was used instead, verified to have loaded this change's code before running.
- [ ] 6.2 **Open — needs a live stack.** No docker-compose environment is available in
      the implementation session, so scenario collection and the unit/integration suites
      are as far as verification goes here. Run the full e2e scenario suite. This change's premise is that it becomes
      deterministic; a run that is green once proves less than one that is green twice, so
      run it twice and say so.
- [ ] 6.3 **Open — depends on 6.2.** Confirm `monotonic-listing-reconciliation` now reproduces deterministically or
      does not reproduce at all, and record which. That is the diagnostic this change was
      partly built to provide.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and read the touched
      docstrings directly — several currently describe pause as negotiation-only. **Redone.** The first pass claimed the touched docstrings had been read directly and had not: review found a docstring body indented four spaces inside an eight-space docstring, with trailing whitespace, in both client variants. Fixed. `make check-comment-hygiene` clean, and the touched docstrings now genuinely read: the pause and resume routes, the registry module, the extracted reconcile, and the scenario fixture all describe present behaviour and none references this change.
- [x] 7.2 **Import placement.** Review imports this change adds; the loop modules use
      function-level imports deliberately in places, so check each against the section's
      own diff rather than relocating on sight. **Done, confirmed by the repository owner.** The advance routes use function-level imports deliberately, matching every other route in that controller — the storefront's admin module defers service imports to keep app import cost off the request path, and hoisting four of them would break that pattern for no gain. `lifecycle.py`'s `core_storefront.app_startup` import is module level; `server.py`'s `lifecycle` import is function level to avoid a cycle, verified by attempting the move and reading the failure rather than assuming.
- [x] 7.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement rules, including that the VM-local scope and the
      API-credits asymmetry are recorded somewhere permanent rather than only here. **Done, after being reopened.** The change originally carried no `specs/` directory at all, so nothing was promoted — the earlier note reasoned about archival synchronization while providing nothing to synchronize. Two deltas now exist: `specs/storefront-publication/spec.md` (pause semantics, cycle-boundary observation, per-loop state, manual cycles while paused, and the API-credits limitation as current state) and `specs/test-compatibility/spec.md` (pause-verify-advance). Placement re-checked against `openspec/README.md`: the pause contract and the manual-cycle contract go to `openspec/specs/storefront-publication/spec.md`, the scenario methodology to `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md`, and the operator-control generalisation to `ARCHITECTURE.md` — the last two are applied in this fileset, the spec deltas are named in the promotion record and synchronize at archival. The VM-local scope and the API-credits asymmetry are recorded in `design.md`, which is change history; if that asymmetry outlives this change it belongs in the storefront specification instead, and the kit extraction is the moment to move it.
- [x] 7.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      validation evidence, and promotion destinations. **Done.** Task notes held at final behaviour, evidence, and destinations; the rejected alternatives and the claims-engine assessment stay in `design.md`.
- [x] 7.5 **Roadmap currency.** Determine whether this affects a goal's current state.
      Likely none — it changes how the system is tested, not what the market can do — and
      that disposition is recorded explicitly rather than omitted. **Done — no roadmap change owed.** This changes how the system is tested and operated, not what the market can do. No goal's current-state paragraph becomes inaccurate and no gap row is closed or opened. Recorded explicitly as a deliberate finding rather than an omitted step.
- [x] 7.6 **Promotion.** Complete the design-promotion record below.
 **Done.** Promotion record completed below.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A paused storefront performs no timer-driven work | `openspec/specs/storefront-publication/spec.md` |
| A manual cycle invokes the operation the loop invoked, and runs while paused | `openspec/specs/storefront-publication/spec.md` |
| Operator lifecycle controls apply to storefronts, not only the provisioning service | `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` |
| Scenarios drive lifecycle by pause-verify-advance rather than by waiting for convergence | `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md` |
| A loop's advance calls the operation the loop invoked; where none exists, the nearest production handler, with the difference recorded | `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` — applied |
| Per-loop state is reported beside the pause flag, so "requested" and "actually stopped" are distinguishable | `openspec/specs/storefront-publication/spec.md` — at archival |
| Resuming is itself a state change: the capacity poller re-reconciles from the feed head | `openspec/specs/storefront-publication/spec.md` — at archival |
| Pause is VM-storefront-local, leaving API-credits uncovered until storefront runtime moves to kit | `openspec/changes/storefront-lifecycle-pause-and-advance/design.md` — deliberate asymmetry, revisited by the kit extraction |
