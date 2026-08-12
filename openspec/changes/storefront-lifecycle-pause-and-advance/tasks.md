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
- [ ] 2.8 **Owed, after a third failed attempt — and the attempts have narrowed it.**
      Assert a lifecycle advance through an observable state transition rather than a
      return contract. Three constructions have now failed against `tests/fake_site`: a
      listing seeded and reconciled with capacity free, the same with the reserve applied,
      and the same with every unit held by a `leased` reservation so the site reports the
      resource exhausted. In all three the reconcile runs and closes nothing.

      What the attempts established, which is more than the first note had:
      `stale_open_listing_ids` skips a listing with no `derived_compute_listings` row
      unless `configured_site_count == 1`, and it decides staleness from
      `current_available_resource_keys` rather than from raw units — so the precondition is
      about which keys the availability view produces, not simply about a resource being
      exhausted. The next attempt should assert on that function directly with a known
      availability view before going through the route, so a failure distinguishes "the
      reconcile did not run" from "the reconcile ran and correctly found nothing stale".

      Left open rather than replaced with a passing test that asserts less than it appears
      to; the route-return test alongside it is honest about its own scope.

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
- [x] 4.2d **Corrected.** Pausing at each deal scenario's readiness stage broke the deals:
      pause refuses new negotiations, which was its meaning before this change extended it to
      the loops, so a scenario cannot hold the pause across agreement. Each deal scenario now
      pauses immediately before the assertion that needs determinism, after settlement.
      `test_multi_registry` loses its pause entirely — no listing-status assertion to protect,
      and a negotiation to lose. The dynamic-listing scenario keeps its early pause because it
      reserves through the admin API and never negotiates; that difference is now stated in
      its docstring, since it is why the pattern looked general when it was not. **Done.**
- [x] 4.2e **Split, as decided.** `/admin/pause` keeps its original meaning — trading only,
      new negotiations receive 503 — and `/admin/lifecycle/pause` and `/lifecycle/resume`
      hold the timer loops idle. Two module-level flags, `_GLOBALLY_PAUSED` and
      `_LOOPS_PAUSED`, and neither implies the other; two integration tests pin that
      independence in both directions. The status surface reports `paused` and
      `loops_paused` separately, both models carry the field, and both client variants gain
      `admin_pause_lifecycle_loops` / `admin_resume_lifecycle_loops`.

      The split was cheap because the two meanings were never entangled in code — the
      trading flag had exactly one functional consumer, `sync_negotiation`. They were
      entangled only in the name, which is what I did wrong: I added a second meaning to an
      existing flag instead of giving it its own.

      Consequences carried through: the scenario helper pauses loops rather than trading, so
      4.2d's late-pause workaround is reverted and the three deal scenarios pause at their
      readiness stage again; teardown resumes both; `ARCHITECTURE.md`, `TESTING.md`, and the
      `storefront-publication` delta describe two controls; and the registry unit tests
      exercise the loop flag rather than the trading one.
- [x] 4.2f **Test isolation, found while pinning independence.** Both flags are module-level
      and leaked between integration tests — one test paused the loops and the next read
      `loops_paused=True` before touching anything. Harmless in that pair, but the same leak
      would let a pause set by one test silently gate an unrelated one. An autouse fixture
      now clears both. **Done.**

- [x] 4.2g **Advance before reading, not before asserting.** Run 31606573720 confirmed the
      split works in a live stack — all three deal scenarios negotiate and settle with their
      loops idle — and failed on my own ordering error: the advance sat between the
      `get_listing` and the assertion, so the row predated the reconcile it was meant to
      observe. Fixed in both deal scenarios, with the reason stated at the call site, and the
      other five advance sites audited (all already read after advancing).

      Recorded because of what it shows about the methodology rather than the typo: under
      timer-driven loops this bug would have passed most runs and failed occasionally,
      looking exactly like the reconciliation defect. Deliberate advance converts "reads
      state at the wrong moment" from an intermittent failure into a repeatable one.
      **Done.**
- [x] 4.2c **Done, and the premise needed correcting.** A `09bb` stage in `test_full_deal`
      now advances the claims engine and asserts a `claim_submitted` event exists for the
      fulfilled escrow.

      The correction: 4.2b claimed pausing would stop the suite exercising claims. Run
      31608431467 shows nine claims events on Bob's storefront *with the loops paused* —
      submission happens on the fulfillment path, and the sweeps land where a module's
      teardown resumes the loops. So the coverage was not lost, it became conditional on
      when a scenario happened to resume, which is worse than either having it or not:
      nothing asserts it and nothing controls it.

      Asserts submission rather than collection, deliberately. A claim becomes collectable
      when its on-chain obligation window opens, which this scenario does not control;
      asserting collection would put a chain condition behind a test assertion and
      reintroduce the timing dependence these controls removed. Submission is entirely the
      storefront's own act.

      The assertion reads the whole claims log rather than only what this sweep added,
      because submission may legitimately precede the sweep. What it pins is the property
      that matters: a fulfilled escrow has a registered seller claim. An empty log there
      means a settled deal nobody will ever be paid for.
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

## 5. Documentation

- [x] 5.1 **Superseded by the split; final behaviour differs from this task's wording.**
      `/admin/pause` keeps its original meaning — trading only — and `/admin/lifecycle/pause`
      halts timer-driven work. Both pairs' summaries and `AdminPauseResponse` messages say
      which of the two they do, and each points at the other. No existing operator endpoint
      changed behaviour in the end, which is a better outcome than the one this task
      planned for. **Done.** Both summaries and both messages rewritten; resume's docstring states that resuming itself reconciles.
- [x] 5.2 Add the pause-verify-advance rule to `docs/development/TESTING.md`'s async
      discipline section, beside the existing no-sleeps rule it completes. **Done.** `docs/development/TESTING.md` gains 'Lifecycle discipline — pause, verify, advance' beside the no-sleeps rule it completes.
- [x] 5.3 Extend `docs/development/ARCHITECTURE.md`'s "Operator lifecycle controls" so it
      covers storefronts rather than reading as provisioning-only.
 **Done.** `ARCHITECTURE.md`'s operator-lifecycle section now covers storefronts and states the no-reimplementation rule for a loop whose work has no callable unit.
## 6. Validation

- [x] 6.1 Run the VM storefront unit and integration suites, the e2e harness suites, and
      the smoke suite. Disclose any suite not run. **Done, with one disclosure.** On a clean baseline with this change applied: `core/storefront-client` 24 passed; VM storefront 853 unit / 1 skipped and 165 integration; provisioning 622 unit+integration; e2e harness 13 unit / 2 skipped and 108 scenarios collecting; `scripts` 42. Two integration failures are excluded as environmental and pre-existing: `test_alkahest.py::test_rust` and `::test_python` need a local Alkahest chain runtime (Rust/Cargo/Foundry/Anvil) that this session does not have, and fail identically on the unmodified baseline. The storefront's `make test` target could not be used because its `reinit` step re-resolves `[rl]`'s torch against a python-3.13/darwin/arm64 marker with no wheel; `uv sync --frozen` plus targeted `--reinstall-package` of the seven edited internal wheels was used instead, verified to have loaded this change's code before running.
- [ ] 6.2 **One of two green runs under lifecycle control (31608431467): 98 passed, 12 skipped.**
      Four pause calls, four resumes, and eight capacity-events advances in the run. The plan
      asks for two, and this is one — a second run is still owed before calling the suite
      stable, since a single green run cannot distinguish "deterministic" from "lucky".
- [x] 6.3 **Answered: it does not reproduce with the loops idle.** Zero
      `compute_listings_reopened` events in run 31608431467, against a flap present in three
      runs while the poller was running. That supports `monotonic-listing-reconciliation`'s
      stale-view reading — the reopen needs the timer path acting on an availability view
      older than a reservation it has not seen — and it deliberately does *not* claim the
      reconcile logic is correct: an advance-driven reconcile reads a current view, so it
      would not exhibit a stale-view defect even if one exists. The defect stands for
      production; the suite has stopped sampling it at random.

## 7a. Closeout — first pass (historical)

Ran before sections 4b, 4c and the pause split existed, so it closes a smaller change than
this one became. Kept rather than deleted: two of its six items were overturned by the second
pass, both because they asserted something had been checked that had not, and that sequence is
the useful part of the record.

## 7b. Closeout — second pass (historical)

Per `openspec/README.md#plan-closeout-requirements`. Superseded; see the final pass below.

- [x] 7.1 **Comment hygiene.** **Re-run.** `make check-comment-hygiene` clean. Read the docstrings added since the first pass: the two pause routes, the two lifecycle routes, the split flags in `server.py`, the claim-clearing control, and the scenario pause helper. The first pass's claim about docstrings was withdrawn once review found bad indentation; this pass checked the rendered text rather than trusting the edit.
- [x] 7.2 **Import placement.** **Re-run, and corrected.** The first pass asserted the advance routes' function-level imports were deliberate. Four of them hoisted cleanly and are now module level. Two imports remain local and now state the verified reason: `lifecycle.is_paused` ↔ `server` is a real cycle, confirmed by attempting the move and reading `ImportError: cannot import name ... from partially initialized module`.
- [x] 7.3 **Documentation compliance.** **Re-run.** Two spec deltas exist and now describe two independent pause controls rather than one. `ARCHITECTURE.md` and `TESTING.md` updated for the split. The API-credits limitation stays in the `storefront-publication` delta as current state.
- [x] 7.4 **Narrative compression.** **Re-run.** Compressed the notes that accumulated across nine end-to-end runs; the reasoning that is still load-bearing stays in `design.md` and `e2e-inventory-findings.md`.
- [x] 7.5 **Roadmap currency.** **Re-run — still no roadmap change owed.** The change now includes two operator controls and a product fix to convergence backoff, which is more than testing methodology; none of it changes what the market can do. Recorded explicitly, again.
- [x] 7.6 **Promotion.** **Re-run.** Promotion record extended below for the split, the pending-poll fix, and the claim-clearing control.
## Design promotion record

Change history; stays here. The destinations describe current state only. "Delta" means the
requirement is written in this change's `specs/` tree and synchronizes into `openspec/specs/`
at archival — the tool's job, not a hand-copy that would drift.

| Accepted decision | Permanent location |
|---|---|
| Closing for business and stopping background work are independent controls; neither implies the other | `specs/storefront-publication/spec.md` (delta) · `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` (applied) |
| A storefront with its loops paused performs no timer-driven work, observed at a cycle boundary so a cycle either completes or never begins | `specs/storefront-publication/spec.md` (delta) |
| A paused loop is held, not stopped, so loop-local position survives and resuming continues rather than re-converging | `specs/storefront-publication/spec.md` (delta) · `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` (applied) |
| Per-loop state is reported beside the pause flag, distinguishing what was requested from what has stopped, and a loop that exited on its own from one held idle | `specs/storefront-publication/spec.md` (delta) |
| A manual cycle invokes the operation the loop invokes and runs while paused; where a loop's work has no callable unit, the nearest production handler is used and the difference recorded at the control | `specs/storefront-publication/spec.md` (delta) · `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` (applied) |
| Lifecycle control coverage is per storefront and is not implied for every storefront; API-credits currently has none | `specs/storefront-publication/spec.md` (delta) · `docs/development/ROADMAP.md` Goal 4 current state and gap row (applied) |
| End-to-end scenarios drive lifecycle by pause and explicit advance, never by waiting for convergence; resuming is itself a state change and belongs in teardown | `specs/test-compatibility/spec.md` (delta) · `docs/development/TESTING.md` system-integration section (applied) |
| A still-running provider operation is re-polled on a poll interval rather than charged to a failure backoff, and keeps its claim so two cycles do not both poll one provider | `provisioning/compute/service` — enforced by unit tests. No spec row: the interval is a tuning decision, not a contract, and writing a number into a specification would freeze it |
| A claim lease outlives the cycle that took it, so an operator control frees claimed records without changing their state | `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` (applied) |

### Classified, not promoted

Recorded because `openspec/README.md` asks every accepted material decision to be classified,
and "not promoted" is a classification.

| Decision | Classification |
|---|---|
| Pause implemented by cancelling loop tasks | **Superseded.** Replaced by the flag before merge; `Task.cancel()` only requests cancellation and could interrupt a cycle mid-write. Reasoning in `design.md`. |
| One flag meaning both trading and loop pause | **Superseded.** Split after it made the loop pause unusable — a scenario pausing to steady its assertions could no longer negotiate. |
| Extracting a one-cycle drain from `site_events_poller` in core | **Rejected for this change**, on a minimal-core-change constraint. Recorded in `design.md` as the tidier shape for whoever revisits it; the trigger is a scenario needing per-delta-kind routing. |
| Pause implemented VM-locally rather than in core or kit | **Temporary.** No kit package owns storefront background work, and creating one exceeds this change. Resolves when storefront runtime moves to kit; tracked by the Goal 4 gap row above. |
| Shortened timer intervals in the two e2e storefront configs | **Temporary, test-scoped.** Bounds how long a loop takes to notice a pause. Production keeps the shipped values; nothing depends on the shortened ones being correct. |
| `StorefrontClient.admin_release_one_reservation` targeting an unimplemented route | **Not this change's.** Annotated in place; the route and its scenario belong to `capacity-reservation-lifecycle-hardening`. |

## 8. Closeout — final

Third and last pass, against the change as it stands: two independent pause controls with
acknowledged quiescence, five gated loops, four per-loop advance endpoints, a claim-clearing
control, a convergence backoff fix, and five converted scenarios. Sections 7a and 7b are
history; both closed a smaller change than this became.

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` clean on a clean baseline with
      the change applied, and the touched docstrings read directly rather than assumed —
      the four pause/lifecycle routes, `server.py`'s flag header, `lifecycle.py`'s module
      docstring and `gate`/`await_quiescence`, the four advance handlers,
      `_hold_claim_for_pending`, `clear_all_claims`, and the scenario helpers. Three
      comments that described what a previous revision did, rather than what holds now,
      were rewritten; `check-comment-hygiene` does not catch that class.
- [x] 8.2 **Import placement.** Every import this change adds is module level except two,
      both verified rather than assumed: `lifecycle` ↔ `server` is a real cycle, confirmed
      by attempting each move and reading `ImportError: cannot import name ... from
      partially initialized module`. Four advance-route imports that an earlier pass had
      defended as deliberate were hoisted, with the suites re-run after each move.
- [x] 8.3 **Documentation compliance.** Two spec deltas carry the normative behaviour,
      including the bounded-wait rule and `pausing` as a legitimate reported state.
      `ARCHITECTURE.md` and `TESTING.md` carry the repository-wide material. Checked that
      the specification does not claim more than the implementation does — it did until
      this pass, which is the defect review found.
- [x] 8.4 **Narrative compression.** Notes hold final behaviour, evidence, deferred work,
      and destinations; reasoning lives in `design.md`, and the run-by-run sequence in
      `compose-domain-wheels-and-policies/e2e-inventory-findings.md`.
- [x] 8.5 **Roadmap currency.** Goal 4 records lifecycle control as a ninth cross-cutting
      storefront concern implemented once, with a gap row owned by
      `kit-storefront-composition-seam`. Earlier passes recorded "no roadmap change owed",
      which stopped being true once this change added operator controls and a product fix.
- [x] 8.6 **Promotion.** The record below is complete, every destination resolves, and
      decisions that were superseded, rejected, or temporary are classified rather than
      omitted.

### Deliberately left open

- `2.8` — an observable state transition through a lifecycle advance. Three attempts have
  failed and narrowed the question; see the task for what they established.
- `6.2` — one of two green runs under lifecycle control. The second is owed, and after this
  many race-related iterations repetition is worth more than usual.
