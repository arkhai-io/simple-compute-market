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
| A loop's reported state is established by the loop reaching its gate, not by the existence of its task; reading the pause and acknowledging it are one operation | `specs/storefront-publication/spec.md` (delta) |
| Readiness, liveness, and diagnosis are separate surfaces: a loop that has not begun cycling fails readiness, a loop that has ended fails liveness while nothing restarts it, and a paused storefront stays ready | `specs/storefront-publication/spec.md` (delta) · `helm/charts/storefront/templates/deployment.yaml` and the VM compose healthchecks (applied) |
| A bounded operator query reports its own truncation rather than returning a short result silently | `specs/storefront-publication/spec.md` (delta) |
| A domain's settlement stage events carry that domain's settlement identity alongside the core engine's mechanism-neutral claim reference, translated at the domain seam | `specs/settlement-servicing/spec.md` (delta) |

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
| A single gate shared by every per-site capacity poller | **Temporary.** Exact at one site, optimistic in the unsafe direction beyond that. Resolving it means registering each site poller as its own loop, which changes how the loop is composed rather than how it gates. Trigger: a storefront configured with more than one site. Recorded at the loop, not only here. |
| An ended loop failing liveness rather than readiness alone | **Temporary, and conditional on the absence of loop supervision.** Pod replacement is the only recovery available today, so liveness is how it is requested. If a supervisor that restarts a dead loop is ever added, this becomes a readiness-only condition. Stated in the requirement and at the route. |

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

## 9. Every loop acknowledges its gate (defect, run 31623897337)

Section 8 closed this change asserting "five gated loops". One loop gates. The other four
read the pause flag without acknowledging, so the bounded wait always expires and every
`/admin/lifecycle/pause` reports four loops as `pausing` forever. The spec delta this
change ships already requires per-loop state "only the loop itself can establish by
reaching its gate", so this is a defect in the change rather than a wording problem.
See `design.md`, "Post-merge defect review — run 31623897337".

- [x] 9.1 Add loop-name constants to `market_storefront/lifecycle.py` and use them at both
      ends. Each name is currently a bare string in two places — the
      `StorefrontBackgroundTask` in `startup.py` and the gate call in the loop body — and a
      mismatch reproduces the symptom just diagnosed from a different cause. Make `gate`
      log a warning when handed a name that was never registered, so a future mismatch
      reports itself instead of presenting as a loop that never gates.
      Files: `lifecycle.py`, `startup.py`.
      **Done.** Five constants in `lifecycle.py`, used by `startup.py`'s registrations and by every gate call. `gate` warns once per unknown name and names the registered set, so a drifted name reports itself rather than presenting as a loop that never gates; covered by `TestGateNameDiscipline`.

- [x] 9.2 Move all four unacknowledged reads onto the acknowledging gate:
      `negotiation_watchdog.watchdog_loop` and
      `fulfillment_resume_runtime.fulfillment_resume_loop` call `gate(<name>)` inline;
      `claims_runtime.claims_engine_loop` and `capacity_client.capacity_events_poller_loop`
      pass a name-bound gate as the `paused` predicate their `core_storefront` loop bodies
      already accept. No `core_storefront` change is required for this task.
      Files: `negotiation_watchdog.py`, `services/fulfillment_resume_runtime.py`,
      `services/claims_runtime.py`, `services/capacity_client.py`.
      **Done.** `negotiation_watchdog` and `fulfillment_resume` call `gate(<name>)` inline; `claims_runtime` and `capacity_client` pass `loop_gate(<name>)` as the `paused` predicate their core loop bodies already accept. No `core_storefront` change was needed for this task, as planned.

- [x] 9.3 Make the unacknowledged read unavailable: `lifecycle.is_paused` becomes
      module-private. After 9.2 it has no production consumer outside `lifecycle` itself,
      so keeping it exported preserves only the ability to reintroduce this defect. Audit
      test imports in the same step — `tests/unit/test_lifecycle_registry.py` and
      `tests/integration/test_admin_api.py` both reach into the module.
      Files: `lifecycle.py`, `tests/unit/test_lifecycle_registry.py`,
      `tests/integration/test_admin_api.py`.
      **Done.** `is_paused` is now `_pause_requested`, module-private, with the reason at the definition. No production consumer remains outside `lifecycle`. `test_lifecycle_registry.py` reaches the flag through `server._LOOPS_PAUSED` where it needs to; `test_admin_api.py` already used `gate`.

- [x] 9.4 Record what one registered name means for the capacity poller.
      `capacity_events_poller_loop` fans out one `site_events_poller` per configured site
      under a single registered name, so the acknowledgement is set by whichever site
      poller reaches its gate first. With one site — every current stack — this is exact.
      With several it is optimistic in the `pausing`→`paused` direction, which is the unsafe
      direction. Decide between a per-site registered name and an all-sites-acknowledged
      aggregate, record the decision at the loop, and state which is implemented.
      **Decided: one shared gate, recorded at the loop.** Every per-site poller shares one name-bound gate, so the loop counts as gated once any site poller reaches its gate. Exact at one site — every current stack. With several it is optimistic in the `pausing` -> `paused` direction, which is the unsafe one, and the comment says so. Not split into per-site registered names because the per-site pollers are started inside the loop body rather than by the registry, so a per-site name would have no task handle and `loop_states` derives `exited` from that handle. Resolving it properly means registering each site poller as its own loop, which changes how this loop is composed rather than how it gates; the trigger is a storefront configured with more than one site.

- [x] 9.5 Add `tests/unit/test_loop_gate_wiring.py`: for every loop `startup.py` registers,
      assert the loop acknowledges under that same registered name. Verify against the
      defect by reverting one call site to the unacknowledged read and confirming the test
      turns red — the existing `test_lifecycle_registry.py` drives a synthetic loop and
      passes against all four defective call sites, which is exactly the gap. Where a loop
      cannot be driven cheaply in a unit test, say so in the test rather than asserting a
      weaker property that looks like the strong one.
      **Done, and verified against the defect.** `tests/unit/test_loop_gate_wiring.py` drives each production loop's real coroutine with its dependencies stubbed and asserts the acknowledgement arrives under the registered name. Reverting `fulfillment_resume` to the unacknowledged read turns it red; restoring turns it green. All five loops are covered behaviourally, including both core-bodied ones through the composed predicate, so nothing was weakened to a structural check.

- [x] 9.6 Amend `tests/unit/test_lifecycle_registry.py`'s module docstring and
      `_counting_loop`'s comment. Both currently claim the synthetic loop gates "as every
      production loop does". That claim was false when written and must not survive as a
      true-again coincidence.
      **Done.** The module docstring now states that these tests prove the mechanism and not the wiring, names `test_loop_gate_wiring.py` as the file that covers the wiring, and records that all four defective call sites passed this file throughout. `_counting_loop`'s comment no longer asserts that production loops gate this way.

## 10. Readiness, liveness, and a loop that has never run

`running` today means a task object exists. Registration is `create_task` inside the
lifespan, so all five names appear before any coroutine executes a step, and the scenario's
pre-pause check passed with the negotiation watchdog at zero gate calls. Compose and both
Kubernetes probes point at `/health`, which says nothing about background work at all.

- [x] 10.1 Add `starting` to `loop_states()`: registered, never acknowledged a gate.
      Distinct from `pausing`, which means a cycle began before the pause request. This is
      also the "has this loop ever gated" signal, taken from the state machine rather than a
      parallel field. `_GATE_CALLS` stays diagnostic logging and is not exposed.
      Files: `lifecycle.py`.
      **Done.** `starting` = registered, never acknowledged a gate, checked ahead of the pause states so a loop that cannot observe a pause is never reported as obeying one. `_GATE_CALLS` is promoted from diagnostic to load-bearing with the reason recorded; `_ACKED` cannot carry the distinction because an unpaused gate call clears the event it would have to set.

- [x] 10.2 Add a `checks["loops"]` entry to the storefront's health payload, supplied
      through an injected provider in the same shape as `_projection_status_provider`
      rather than by importing `lifecycle` into `SystemService` — the existing
      `lifecycle` ↔ `server` cycle makes a direct import fragile.
      Files: `services/system_service.py`, `container.py`, `startup.py`.
      **Done.** `checks["loops"]` from an injected `loop_health_provider`, defaulting to `lifecycle.loops_check()` resolved inside the function — `lifecycle` and `server` already reference each other and a module-scope import would draw a service into that cycle.

- [x] 10.3 Add `/ready` and its versioned alias `/api/v1/system/ready`. Returns 503 with
      `status: "starting"` while any loop is `starting` or none is registered, 503 with
      `status: "degraded"` when any loop has ended on its own, 200 otherwise. A paused
      storefront is ready: pause is operator-requested, the storefront still serves and
      trades, and failing readiness on it would mark every scenario's container unhealthy
      the moment it paused. Unauthenticated, like the other probe routes.
      Files: `controllers/system_controller.py`, `core/storefront/src/core_storefront/models/system_models.py`.
      **Done.** `/ready` and `/api/v1/system/ready`, unauthenticated, no registry probe. 503 with `status: "starting"` while a loop is starting or none is registered, 503 while a loop has ended, 200 otherwise. A paused storefront is ready, pinned by `TestAPausedStorefrontIsReady`.

- [x] 10.4 Make `/health` return 503 when a loop has ended on its own, and only then.
      Liveness stays a process-level question; a still-starting loop must not restart a pod.
      Record at the route why `exited` is fatal: no supervisor restarts a dead loop, so pod
      replacement is the recovery mechanism and liveness is how it is requested.
      Files: `controllers/system_controller.py`.
      **Done.** `/health` returns 503 only for a loop that ended on its own, with the reason at the route: nothing restarts a loop, so pod replacement is the recovery and liveness is how it is requested.

- [x] 10.5 Point the storefront chart's `readinessProbe` at `/ready`, leave `livenessProbe`
      on `/health`, and correct the comment above them, which currently states `/health` is
      a fast SQLite ping suitable for both.
      Files: `helm/charts/storefront/templates/deployment.yaml`.
      **Done.** `readinessProbe` on `/ready`, `livenessProbe` unchanged on `/health`, and the comment above them rewritten — it described one route serving both.

- [x] 10.6 Point the `bob-storefront` and `alice-storefront` compose healthchecks at
      `/ready`, so `docker compose up -d --wait` gates the e2e run on the loops being live.
      Leave `credits-storefront` on `/health`: it runs equivalent loops through a runtime
      with no lifecycle registry, the route will not exist there, and a 404 healthcheck
      would fail the stack. State that asymmetry at the credits healthcheck, where a reader
      changing one of the three will meet it.
      Files: `domains/vms/compose.yml`, `domains/apicredits/compose.yml`.
      **Done.** Bob and Alice healthcheck `/ready`, so `docker compose up -d --wait` gates the run on the loops being live. `credits-storefront` stays on `/health` with the asymmetry stated at its own healthcheck: its runtime has no lifecycle registry, so `/ready` does not exist there and a copied probe would 404 the stack.

- [x] 10.7 Stop the loops dying silently, so `exited` stays exceptional enough for
      liveness to key off it. `fulfillment_resume_loop` has no `try/except` around its
      sweep — the per-escrow handler does, but a failure in
      `list_incomplete_primary_escrows` or client construction escapes and ends the loop —
      and `capacity_events_poller_loop` ends if its `gather` raises. Add cycle-level
      handling to both in the shape the other three already use, and attach a done-callback
      in `start_registered_loop` that logs a loop's completion with its exception. A loop
      ending is currently invisible until someone reads a status surface.
      Files: `services/fulfillment_resume_runtime.py`, `services/capacity_client.py`,
      `lifecycle.py`.
      **Done, and one case the plan did not anticipate.** Cycle-level handling added to `fulfillment_resume_loop`; `start_registered_loop` attaches a done-callback logging a loop's end with its exception at `error`. The unanticipated case: `capacity_events_poller_loop` *ended immediately* with no configured site, because `gather()` over nothing returns — which after 10.4 would fail liveness and replace the pod for a configuration fact. It now gates and idles instead, covered by `test_capacity_events_poller`.

- [x] 10.8 Convert the scenarios' pre-pause check from an assumption to an assertion.
      `pause_storefront` asserts every loop is `running`; with 10.1 that becomes a real
      guarantee — every loop has completed a gate call, so the pause it is about to request
      is observable within one interval. Do not add a poll or a wait: compose's healthcheck
      now gates the stack, so the stage asserts and fails loudly rather than waiting for
      convergence, per `TESTING.md`. Update the helper's docstring, which currently explains
      the check as guarding against loops that "have not begun" — after this it guards
      against a regression in the gate wiring, which is a different claim.
      Files: `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`.
      **Done.** Assertion, not a poll: the stack's readiness gate has already established this before any scenario runs, so a wait here would restate it as a wait and absorb the regression it exists to catch. The helper's docstring now explains the check as guarding the gate wiring rather than a slow start, and says why `running` is the load-bearing word.

- [x] 10.9 Tests: `starting` before a first gate and `running` after; a paused storefront
      is ready; an exited loop fails both `/health` and `/ready`; `/ready` returns 503 with
      `status: "starting"` rather than an error body. Storefront unit and integration
      suites.
      **Done.** `tests/integration/test_readiness_and_liveness.py`, nine cases against the real registry rather than an injected provider. Two of them initially passed for the wrong reason: a loop that gates on its first step is already `running` by the time a probe reads it, because any `await` in the handler yields to the event loop, so the starting window is unobservable without a deliberately slow-to-start loop. Recorded at the fixture.

## 11. Loops observe a pause within one interval of starting

- [x] 11.1 Restructure `watchdog_loop`'s startup delay. It sleeps 15s before entering the
      loop and sleeps again at the top of the body, so its first gate lands ~17s after boot;
      the suite's first pause landed 13s after registration, inside that window. Enter the
      loop immediately, gate every interval, and hold the *sweep* behind a not-before
      deadline — the delay's purpose is not to misclassify threads created while the clock
      settles, which constrains the sweep and not the gate. Assert the preserved property
      directly: no sweep before the deadline, a gate acknowledged before it.
      Files: `negotiation_watchdog.py`.
      **Done.** The loop is entered immediately and gates every interval; the 15s delay became a `STARTUP_SWEEP_DELAY_SECONDS` not-before deadline holding only the sweep. Both halves asserted directly — the gate is reached during a 30s delay, and no sweep runs inside it.

- [x] 11.2 Move `ClaimsEngine.run`'s interval sleep after the gate check rather than before
      it, so a pause is observed on the cycle it is requested rather than one interval
      later. This strikes the proposal's "No `core_storefront` change" fence for one
      ordering change; `design.md` records why the fence existed and why this does not
      breach it. Check the first-cycle consequence explicitly — the sweep now runs at
      startup rather than one interval in — and either accept it with a reason or preserve
      the delay the way 11.1 does.
      Files: `core/storefront/src/core_storefront/settlement_lifecycle.py`.
      **Done.** Gate first, sleep last. First-cycle consequence checked and accepted rather than preserved: the sweep now runs at startup rather than one interval in, and the engine is idempotent by claim reference, so this changes when a due claim is serviced and not whether it is serviced twice. Stated at the docstring.

- [x] 11.3 Correct the two comments the 4.2e split left describing a superseded revision:
      `AdminPauseResponse`'s docstring still says pause "halts them as well as refusing new
      negotiations", and `HealthResponse.loops` documents the vocabulary as
      `"running", "stopped", "cancelled", "exited"` — `stopped` does not exist, `paused` and
      `pausing` are missing, and 10.1 adds `starting`. Neither is a class
      `make check-comment-hygiene` catches. Mirror both in the client models.
      Files: `core/storefront/src/core_storefront/models/system_models.py`,
      `core/storefront-client/src/storefront_client/models.py`.
      **Done.** `AdminPauseResponse` no longer says pause halts the loops as well as refusing negotiations; both `HealthResponse.loops` comments carry the real vocabulary including `starting`, server-side and client-side.

## 12. A truncated event query says so

- [x] 12.1 Log at the clamp. `SQLiteClient.list_stage_events` silently reduces `limit` to
      500; every in-process caller meets it, and over HTTP the controller's own `le=500`
      turns it into a 422 instead. Keep both bounds — a loud rejection beats a silent short
      read — and log when the clamp applies.
      Files: `core/storefront/src/core_storefront/sqlite_client.py`.
      **Done.** The clamp logs at warning with both the requested and the effective limit. Both bounds kept: the controller's 422 is a loud rejection and the persistence cap catches every in-process caller.

- [x] 12.2 Add `truncated` to the stage-event response on both sides. `count` alone cannot
      distinguish a complete page of 500 from a truncated one, which is the same diagnosis
      problem one layer up from the one 12.1 fixes. A caller asking for the whole log can
      then assert it got it.
      Files: `core/storefront/src/core_storefront/models/system_models.py`,
      `controllers/system_controller.py`,
      `core/storefront-client/src/storefront_client/models.py`.
      **Done.** `list_stage_events_page` returns `(rows, truncated)` and `list_stage_events` remains as a rows-only wrapper for callers that do not need the distinction. Detection reads one row past the page, so `truncated` means rows were withheld rather than that the cap was reached exactly — the boundary case is pinned. `StageEventResponse` and the client's `StageEventListResponse` both carry the flag; both storefront controllers populate it.

- [x] 12.3 Fix stage 09bb's request and assert the flag. It asks for `limit=1000` against a
      cap of 500 and is rejected before it reads anything. Request the maximum and assert
      `truncated` is false, so "the whole claims log" is a checked claim rather than an
      assumed one.
      Files: `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal.py`.
      **Done.** Stage 09bb requests 500 and asserts `not events.truncated` before filtering, so "the whole claims log" is checked rather than assumed.

- [x] 12.4 Tests: the clamp logs; a bounded query reports `truncated`; both client variants
      parse it, with the parity check `TESTING.md` requires.
      **Done.** `core/storefront/tests/unit/test_stage_event_pagination.py` — seven cases including the exactly-at-limit boundary, the log line, and that a filtered query counts only matching rows.

## 13. The claims stage event carries the escrow identity it is filtered by

Stage 09bb filters `data["escrow_uid"]`, which no claims-lifecycle event sets. The stage is
new, not stale — this change's own claims impact assessment records that no scenario
referenced `claim_submitted` at the time, task 4.2c added the stage afterwards, and run
31623897337 is the first run to reach it, where the 422 stopped it two lines earlier. The
filter has never executed.

- [x] 13.1 Translate at the domain seam. `claims_runtime._on_event` is the VM hook over
      core's mechanism-neutral emitter and already performs this exact translation one line
      below, where it feeds `escrow_uid=fields.get("claim_ref")` into lease truncation. Add
      `escrow_uid` alongside `claim_ref` for the alkahest mechanism there, and in
      `submit_claim` for the direct fulfillment-path emission. `ClaimsEngine` keeps emitting
      `claim_ref` and learns no alkahest vocabulary.
      Files: `services/claims_runtime.py`.
      **Done.** `_with_escrow_identity` at the domain seam, applied by `_on_event` and by `submit_claim`. Alkahest only: another mechanism's claim reference is not an escrow uid, and copying it under that name would assert an identity that does not hold. Core still emits `claim_ref` alone.

- [x] 13.2 Confirm the indexed column populates. `stage_log._persist` fills
      `stage_events.escrow_uid` only from a field of that name, which is why every
      claims-lifecycle row has it NULL while `lease_truncated_after_abandonment` — emitted
      by the same module — fills it. After 13.1 the column carries the escrow for the whole
      claims stage, and `GET /api/v1/system/events` can filter on it rather than scanning
      JSON. State whether a query filter is added or deliberately not.
      **Confirmed, and no query filter added.** `stage_log._persist` fills the indexed column from a field of that name, so the column now populates for the whole claims stage. Stage 09bb matches on `e.escrow_uid` rather than the JSON payload, which is what proves the translation happened end-to-end. A query filter is deliberately not added: no caller needs one, and the stage-filtered page is well inside the cap.

- [x] 13.3 Tests: a submitted claim's stage event carries both `claim_ref` and `escrow_uid`
      and they agree; the persisted row's column is populated. Storefront unit or
      integration level — this is provable below end-to-end and should not rely on 09bb.
      **Done.** `tests/unit/test_claims_stage_event_identity.py` — submission carries both names and they agree, another mechanism is left alone, an explicit identity is not overwritten, and an event without a claim reference is unchanged.

## 14. Validation

- [x] 14.1 Run the VM storefront unit and integration suites, `core/storefront`,
      `core/storefront-client`, and the e2e harness suites, by the command the repository
      uses rather than by naming test paths. Disclose any suite not run and why, separating
      an absence in the session environment from a defect in the code.
      **Done, with three disclosures.** Measured against a pristine baseline copy before any
      edit and again after, by each project's own default test command:

      | Suite | Baseline | After |
      |---|---|---|
      | VM storefront unit | 862 passed, 1 skipped | 883 passed, 1 skipped |
      | VM storefront integration | 166 passed, 3 failed | 175 passed, 3 failed |
      | `core/storefront` unit | 104 passed | 111 passed |
      | `core` unit | 70 passed | 70 passed |
      | `core/storefront-client` | 24 passed | 24 passed |
      | e2e harness unit | 13 passed, 2 skipped | 13 passed, 2 skipped |
      | apicredits storefront | not run at baseline | 51 passed |

      `make check-comment-hygiene` passes.

      **Disclosure 1 — the `reinit` step of each `make test` target was not run.** It resolves
      internal packages from `.dist`, which this session has no built wheels for; internal
      packages were installed from source instead. That is a session arrangement and not a
      change to the packaging discipline, but it means these runs do not exercise wheel
      packaging. `make check-wheel-manifests` and `make check-wheel-closure` were not run
      for the same reason.

      **Disclosure 2 — two integration failures are the pre-existing environmental pair.**
      `test_alkahest.py::test_rust` and `::test_python` need a local chain runtime, and fail
      identically on the untouched baseline, as task 6.1 already recorded.

      **Disclosure 3 — one integration failure is pre-existing and NOT established as
      environmental.** `test_negotiate_controller.py::TestNegotiateNew::test_amountless_exact_escrow_can_start_and_accept`
      fails `'counter' == 'accept'`, meaning `accept_exact_listing_middleware` found no peer
      proposal in the history it was given. It fails identically on the unmodified baseline
      here and is untouched by this change, but whether it also fails in CI was not
      determined, so it is reported as an open question rather than dismissed. Worth a check
      against a CI run before it is assumed harmless.

      Also disclosed: the apicredits storefront suite needs the repository root on
      `PYTHONPATH` to import its `domains.apicredits.*` test subjects, which its own
      `pythonpath = ["src"]` does not supply. Unrelated to this change and not fixed here.
- [ ] 14.2 One end-to-end run. The five failures in 31623897337 clear, and the run reaches
      stage 09bb's assertion rather than erroring before it — 09bb's filter has never
      executed, so its first green is new information, not a re-confirmation.
      **Owed — cannot be run in this session.** The end-to-end suite needs the compose stack
      and the CI workflow. Four specific predictions to check against the next run, so that a
      failure distinguishes which part was wrong: every pause reports five `paused` rather
      than four `pausing`; the compose log shows gate calls for all five registered names,
      not only `site_projection_poller`; stage 09bb reaches its filter and matches on
      `escrow_uid`; and the storefront containers reach healthy through `/ready`, which is a
      new gate and the most likely place for this change to fail in a way no suite here can
      see.
- [ ] 14.3 Confirm from the compose log that all five loops acknowledge: gate calls present
      for every registered name, and every pause reporting five `paused`. The previous run's
      `gate calls so far: {'site_projection_poller': 48}` is the line that diagnosed this;
      its successor is the line that proves the fix.
- [x] 14.4 Append the run's findings to
      `openspec/changes/compose-domain-wheels-and-policies/e2e-inventory-findings.md`,
      which carries this campaign's run-by-run record.
      **Done for run 31623897337** — the diagnosis, not the fix. The next run's outcome is
      owed there too, and belongs with 14.2.
- [ ] 14.5 Section 6.2 still owes a second green run under lifecycle control. This section's
      run does not discharge it — it is the first run of a changed pause path, not a
      repetition of a stable one.

## 15. Closeout — after the defect sections

Per `openspec/README.md#plan-closeout-requirements`. Section 8 was the final pass for the
change as it stood; it closed a change whose central invariant the code did not hold, which
is the reason this pass exists rather than an amendment to that one.

- [x] 15.1 **Comment hygiene.** `make check-comment-hygiene`, plus a direct read of every
      docstring these sections touch — `lifecycle`'s module docstring and its state
      vocabulary, the three probe routes, the four gated loop bodies, `_on_event`, and the
      scenario pause helper. Section 8 recorded that three comments described a previous
      revision rather than current behaviour and that the target does not catch that class;
      11.3 shows two more survived. Read for that class specifically.
- [x] 15.2 **Import placement.** Cross-referenced against these sections' own diff. Every
      import added here is module level except two, both with a verified reason at the
      definition: `lifecycle._pause_requested` imports `server` inside the function because
      the cycle is real, and `system_service._default_loop_health_provider` imports
      `lifecycle` inside the function so a service is not drawn into that same cycle — the
      reason 10.2 injected a provider rather than importing directly. Both were checked by
      running the storefront suites, not by a syntax check.
- [x] 15.3 **Documentation compliance.** Two claims, stated separately.

      *Code claim.* All five loops read the pause through the acknowledging gate; the
      unacknowledged read is private; `starting` is derived from gate calls; `/health` fails
      only on an ended loop and `/ready` also on a starting one or an empty registry; a
      paused storefront stays ready; bounded stage-event queries report truncation; alkahest
      claim events carry `escrow_uid`. Each is covered by a test named in the sections above.

      *Documentation claim.* The `storefront-publication` delta's three new requirements and
      the `settlement-servicing` delta's one were each re-read against that list. The one
      place the wording outruns the code is deliberate and stated in the requirement itself:
      the readiness requirement says liveness fails for a loop that has ended *while no
      supervisor restarts one*, which is a condition on the current implementation rather
      than a permanent claim, and 10.4's route comment names the same trigger. No requirement
      asserts an invariant the code does not hold — which is the failure this change already
      shipped once.
- [x] 15.4 **Narrative compression.** Each task above carries final behaviour, its evidence,
      and anything left open. The reasoning — why the unacknowledged read became private, why
      readiness and liveness are separate surfaces, why the translation belongs at the domain
      seam — stays in `design.md`'s post-merge review section rather than being restated here.
      Two findings that arrived during implementation rather than planning are recorded where
      they were found (10.7's zero-site loop exit, 10.9's unobservable starting window)
      because both are traps for the next reader of those files.
- [x] 15.5 **Roadmap currency.** Disposition: no roadmap edit owed, recorded rather than
      omitted. Goal 4's entry already names lifecycle control as a cross-cutting storefront
      concern implemented once in the VM storefront, with its gap row owned by
      `kit-storefront-composition-seam`. Readiness reporting is part of that same concern and
      lands in the same place, so the current-state description and the gap mapping are both
      still accurate. Nothing here changes what the market can do.
- [x] 15.6 **Promotion.** The record below gains four rows and one classification. Every
      destination resolves.
