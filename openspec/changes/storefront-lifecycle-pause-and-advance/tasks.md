# Implementation Tasks

Sections are ordered so the control surface exists before the scenarios depend on it, and
so the scenario backport lands with the change rather than after it — a scenario carried
today by a background sweep will simply stop advancing once pause halts the loops, and it
must be converted in the same commit that can stop it.

## 1. Pause halts every timer loop

- [ ] 1.1 Confirm by inspection that `design.md`'s "Context" still holds: five loops, all
      started through `core_storefront.app_startup.start_storefront_background_task`, the
      pause flag read only by `sync_negotiation`, and the two loop bodies that live in
      core. Record drift in `design.md` rather than working around it.
- [ ] 1.2 Hold the task handles the startup helper already returns, in a VM-local registry
      keyed by the `StorefrontBackgroundTask.name` each loop is already given. The names
      exist; nothing keeps the handles today.
- [ ] 1.3 Make `_set_globally_paused(True)` cancel every registered task and `False`
      restart them from the same factories. State at the registry why cancellation rather
      than a flag each loop consults: two loop bodies are in core and cannot see a
      VM-local flag, and one concept implemented two ways would be worse than a blunt one.
- [ ] 1.4 Document the capacity poller's cursor consequence where it is true rather than
      where it is convenient: the poller's `last_applied` is loop-local, so a resume
      re-positions at the feed head and re-runs its full reconcile. Self-healing, and the
      reason a scenario resumes only at teardown.
- [ ] 1.5 Make pause and resume idempotent — pausing a paused storefront cancels nothing
      twice, resuming a running one starts no duplicate task. A duplicated poller would be
      invisible until two reconciles raced.
- [ ] 1.6 Focused tests: pause stops each named task; resume restarts each; both are
      idempotent; a paused storefront still refuses new negotiations exactly as before.

## 2. Per-loop advance controls

Each endpoint calls the operation the loop was already invoking and returns what that
operation returns. No endpoint reimplements a loop body, and none synthesises a richer
response than the underlying call already produces.

- [ ] 2.1 `claims_engine` → `ClaimsEngine.tick()`. `run()` is a thin loop over it, so the
      production handler is already isolated.
- [ ] 2.2 `fulfillment_resume` → `resume_incomplete_fulfillments_once(sqlite_client=...)`.
- [ ] 2.3 `negotiation_watchdog` → `_watchdog_tick(sqlite_client)`.
- [ ] 2.4 `capacity_events_poller` → the storefront's own `_full_reconcile`, the callback
      the poller invokes at startup and after a ledger reset. Record at the endpoint that
      this runs both the close and reopen passes unconditionally while the delta
      subscriber runs one or both by delta kind, so this exercises a superset rather than
      an identical path — and that a scenario needing per-kind routing is the trigger for
      extracting a one-cycle function from `site_events_poller` in core.
- [ ] 2.5 Add no advance control for `site_projection_poller`;
      `POST /api/v1/admin/capacity/projections/refresh` already is one. Confirm rather than
      assume, and record the disposition.
- [ ] 2.6 Add the client methods for each new endpoint to both the sync and async
      storefront clients in this change, with the parity contract test
      `docs/development/TESTING.md` requires.
- [ ] 2.7 Focused tests: each advance invokes its underlying operation exactly once and
      propagates its result; each works while paused, since that is when it is used.

## 3. Observable pause state

- [ ] 3.1 Report per-loop running state on the admin status surface, read from the task
      registry, replacing the bare `paused` boolean with something that distinguishes
      "flag set" from "loops actually stopped".
- [ ] 3.2 Add read APIs for any state a converted scenario needs to inspect between
      advances, rather than widening advance responses to carry it. Identify these from
      Section 4's conversion, not in anticipation.
- [ ] 3.3 Extend the smoke suite's pause/resume test to assert the loops stopped, not only
      that new negotiations are refused. Pause returning 200 has never proven the
      background work halted, and after this change that is the substantive half of what
      pause means.

## 4. Scenario backport — all scenarios, this change

- [ ] 4.1 Pause the storefront in each VM scenario's readiness stage and leave it paused
      for the run. Resume belongs in teardown only, since resume itself reconciles.
- [ ] 4.2 Convert every assertion that currently depends on a loop having run into an
      explicit advance followed by the assertion. Work scenario by scenario rather than
      failure by failure: a stage that passes today because a sweep happened to fire is as
      wrong as one that fails.
- [ ] 4.3 Delete the four single-sample listing-status assertions' dependence on timing:
      pause, reserve, assert closed *before* any reconcile, advance once, assert still
      closed. This is strictly stronger than either the polling or the single-sample form,
      and it is what turns `monotonic-listing-reconciliation` into a deterministic failure
      rather than a race.
- [ ] 4.4 Audit the API-credits scenario. It runs against a storefront this change does
      not cover, so it keeps its current behaviour; confirm it does not share a fixture
      that pauses, and record the asymmetry where a reader will meet it.
- [ ] 4.5 Re-check the stages that the claims engine, resume worker, and negotiation
      watchdog currently carry silently — `design.md`'s impact assessment found no
      assertion on any of them, but the assessment was made against the suite as it is,
      and Section 4 changes it. Any stage that stops advancing needs an explicit advance,
      not a longer timeout.

## 5. Documentation

- [ ] 5.1 Rewrite the `pause`/`resume` endpoint summaries and `AdminPauseResponse`
      messages: pause halts timer-driven work as well as refusing new negotiations. This
      is a behaviour change on an existing operator endpoint and belongs in its
      description, not only in a spec.
- [ ] 5.2 Add the pause-verify-advance rule to `docs/development/TESTING.md`'s async
      discipline section, beside the existing no-sleeps rule it completes.
- [ ] 5.3 Extend `docs/development/ARCHITECTURE.md`'s "Operator lifecycle controls" so it
      covers storefronts rather than reading as provisioning-only.

## 6. Validation

- [ ] 6.1 Run the VM storefront unit and integration suites, the e2e harness suites, and
      the smoke suite. Disclose any suite not run.
- [ ] 6.2 Run the full e2e scenario suite. This change's premise is that it becomes
      deterministic; a run that is green once proves less than one that is green twice, so
      run it twice and say so.
- [ ] 6.3 Confirm `monotonic-listing-reconciliation` now reproduces deterministically or
      does not reproduce at all, and record which. That is the diagnostic this change was
      partly built to provide.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and read the touched
      docstrings directly — several currently describe pause as negotiation-only.
- [ ] 7.2 **Import placement.** Review imports this change adds; the loop modules use
      function-level imports deliberately in places, so check each against the section's
      own diff rather than relocating on sight.
- [ ] 7.3 **Documentation compliance.** Re-check the accepted decisions against
      `openspec/README.md`'s placement rules, including that the VM-local scope and the
      API-credits asymmetry are recorded somewhere permanent rather than only here.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      validation evidence, and promotion destinations.
- [ ] 7.5 **Roadmap currency.** Determine whether this affects a goal's current state.
      Likely none — it changes how the system is tested, not what the market can do — and
      that disposition is recorded explicitly rather than omitted.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A paused storefront performs no timer-driven work | `openspec/specs/storefront-publication/spec.md` |
| A manual cycle invokes the operation the loop invoked, and runs while paused | `openspec/specs/storefront-publication/spec.md` |
| Operator lifecycle controls apply to storefronts, not only the provisioning service | `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` |
| Scenarios drive lifecycle by pause-verify-advance rather than by waiting for convergence | `docs/development/TESTING.md` and `openspec/specs/test-compatibility/spec.md` |
| Pause is VM-storefront-local, leaving API-credits uncovered until storefront runtime moves to kit | `openspec/changes/storefront-lifecycle-pause-and-advance/design.md` — deliberate asymmetry, revisited by the kit extraction |
