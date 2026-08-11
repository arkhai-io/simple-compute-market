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
      VM-local flag, and one concept implemented two ways would be worse than a blunt one. **Done.** `_set_globally_paused` cancels or restarts through the registry, with the two-core-bodied-loops reasoning stated there.
- [x] 1.4 Document the capacity poller's cursor consequence where it is true rather than
      where it is convenient: the poller's `last_applied` is loop-local, so a resume
      re-positions at the feed head and re-runs its full reconcile. Self-healing, and the
      reason a scenario resumes only at teardown. **Done.** Recorded on the registry module, on `resume`'s route docstring, and in the scenario fixture that depends on it.
- [x] 1.5 Make pause and resume idempotent — pausing a paused storefront cancels nothing
      twice, resuming a running one starts no duplicate task. A duplicated poller would be
      invisible until two reconciles raced. **Done.** Both idempotent; resume replaces nothing already running.
- [x] 1.6 Focused tests: pause stops each named task; resume restarts each; both are
      idempotent; a paused storefront still refuses new negotiations exactly as before.
 **Done.** `tests/unit/test_lifecycle_registry.py` — 7 tests, including that a loop which exits on its own reports `exited` rather than `running` or `stopped`.
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
 **Done.** Five integration tests, all exercising the routes while paused; the capacity one asserts the shared reconcile is the function called.
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
      for the run. Resume belongs in teardown only, since resume itself reconciles. **Done.** `paused_storefront`, a module-scoped autouse fixture, pauses at setup and asserts every loop reported `stopped` — a pause that half-took would otherwise be discovered as a flaky assertion later.
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
      that pauses, and record the asymmetry where a reader will meet it. **Done.** The API-credits scenario shares this conftest, so it now pauses the *VM* storefront it does not use, which is harmless; it drives `credits-storefront`, which this change does not cover. Asymmetry recorded in `design.md`.
- [x] 4.5 Re-check the stages that the claims engine, resume worker, and negotiation
      watchdog currently carry silently — `design.md`'s impact assessment found no
      assertion on any of them, but the assessment was made against the suite as it is,
      and Section 4 changes it. Any stage that stops advancing needs an explicit advance,
      not a longer timeout.
 **Done.** Re-checked after conversion: no stage asserts on claims, resume-worker, or negotiation-watchdog output, so none needed an advance. The controls exist for the moment one does.
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
      docstrings directly — several currently describe pause as negotiation-only. **Done.** `make check-comment-hygiene` clean on the clean copy. Read the touched docstrings directly: the pause and resume routes, the registry module, the extracted reconcile, and the scenario fixture all describe present behaviour and none references this change.
- [x] 7.2 **Import placement.** Review imports this change adds; the loop modules use
      function-level imports deliberately in places, so check each against the section's
      own diff rather than relocating on sight. **Done.** The advance routes use function-level imports deliberately, matching every other route in that controller — the storefront's admin module defers service imports to keep app import cost off the request path, and hoisting four of them would break that pattern for no gain. `lifecycle.py`'s `core_storefront.app_startup` import is module level; `server.py`'s `lifecycle` import is function level to avoid a cycle, verified by attempting the move and reading the failure rather than assuming.
- [x] 7.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement rules, including that the VM-local scope and the
      API-credits asymmetry are recorded somewhere permanent rather than only here. **Done.** Placement re-checked against `openspec/README.md`: the pause contract and the manual-cycle contract go to `openspec/specs/storefront-publication/spec.md`, the scenario methodology to `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md`, and the operator-control generalisation to `ARCHITECTURE.md` — the last two are applied in this fileset, the spec deltas are named in the promotion record and synchronize at archival. The VM-local scope and the API-credits asymmetry are recorded in `design.md`, which is change history; if that asymmetry outlives this change it belongs in the storefront specification instead, and the kit extraction is the moment to move it.
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
