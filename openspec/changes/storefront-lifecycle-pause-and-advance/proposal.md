## Why

An end-to-end scenario should observe every state change the system makes, in the order
it makes them. That requires the system to change state only when the scenario tells it
to. The provisioning service already supports this: `pause_lease_watchdog` /
`resume_lease_watchdog` halt the timer, `force_check_leases` and
`fulfillment-convergence/run-cycle` drive one production cycle on demand, and
`ARCHITECTURE.md`'s "Operator lifecycle controls" states the rule those follow — a manual
cycle MUST invoke the same production handler, never an alternate transition. Scenario
stage 10a already opens with `pause_lease_watchdog()` for exactly this reason.

The storefront has no equivalent. It starts five timer-driven background loops at
startup — `negotiation_watchdog`, `claims_engine`, `fulfillment_resume`,
`capacity_events_poller`, `site_projection_poller` — and exposes no way to halt or step
any of them. Its `POST /api/v1/admin/pause` gates *new negotiations* only; every loop
keeps mutating storefront state while the storefront reports itself paused.

The cost is visible in the suite. Derived-listing assertions race the capacity-events
poller's one-second interval, and the only way to make them pass has been to wait for the
system to settle — which `docs/development/TESTING.md` explicitly forbids ("Async test
discipline — no sleeps") and which cannot prove ordering even when it passes. A wait also
hides defects: `monotonic-listing-reconciliation` was reproduced three times before it
could be characterised, because whether a scenario saw it depended on which side of a
race the run landed on.

Pause-verify-advance removes the race from the observation rather than tolerating it. It
does not detect race conditions, and is not meant to — that is not what these scenarios
are for.

> **Post-merge defect review, 2026-08-12.** Run 31623897337 showed that four of the five
> loops read the pause flag without acknowledging their gate, so every pause reported them
> as still stopping. The scope below is extended by Sections 9–15 of `tasks.md`: gate
> acknowledgement at all five loops, a `starting` loop state, separate readiness and
> liveness surfaces, a negotiation-watchdog startup restructure, a truncation flag on
> bounded event queries, and the settlement stage event's escrow identity. Rationale is in
> `design.md`, "Post-merge defect review — run 31623897337".

## What Changes

- Make `POST /api/v1/admin/pause` halt every storefront timer loop in addition to
  refusing new negotiations, and `resume` restart them. "Paused" comes to mean the
  storefront changes no state on its own, which is what the word should already have
  meant. Rename the endpoint summaries and response messages to match, and correct the
  operator documentation.
- Pause at a cycle boundary. A loop checks the flag at the top of each iteration and
  skips the body; it is never cancelled mid-cycle, and no cursor, claim, or sweep
  position advances while paused.
- Add one manual-advance endpoint per loop. Each calls the operation the loop was already
  invoking — `ClaimsEngine.tick()`, `resume_incomplete_fulfillments_once`,
  `_watchdog_tick`, the storefront's own capacity reconcile — and returns what that
  operation returns. `site_projection_poller` already has its control in
  `POST /api/v1/admin/capacity/projections/refresh` and gains no second one.
- Report per-loop running state on the admin status surface, so a scenario and an operator
  can both confirm a pause took effect rather than trusting a 200.
- Add read APIs for state a scenario needs to inspect, rather than enriching advance
  responses. An advance that returns only "done" is sufficient when the state it changed
  is separately readable.
- Convert the VM end-to-end scenarios to pause at setup and advance deliberately, and
  delete the polling helper introduced as a stopgap.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: a storefront exposes operator lifecycle controls with the
  same contract the provisioning service already follows — pause halts timer-driven
  work, and a manual cycle invokes the production handler.
- `test-compatibility`: end-to-end scenarios drive storefront lifecycle by pause and
  explicit advance rather than by waiting for convergence.

## Non-Goals

- Do not add per-loop *pause* endpoints. One flag, one storefront, matching the existing
  pause's scope. Per-loop *advance* endpoints are added, which is a different axis.
- Do not extend this to the API-credits storefront. It starts the same loops through the
  same core helper and would be covered by a core-level implementation, which this change
  deliberately avoids.
- Do not change what any loop does when it runs. This governs *when* a cycle happens,
  never the transitions inside it.
- Do not detect or defend against race conditions in scenarios. Pause-verify-advance
  makes ordering observable; it does not test concurrency, and the suite does not claim
  to.
- Do not pre-empt `replace-polling-with-authenticated-push`. When delivery becomes push,
  the advance control becomes "force a push" rather than "force a pull" and the scenario
  methodology is unchanged — see Dependencies.

## Impact

- **Affected code:** primarily the VM storefront — `server.py`'s pause flags and the loop
  registry in `lifecycle.py`, `startup.py`, `admin_controller`, `system_controller`'s
  status, health, and readiness surfaces, and the five loop modules. Two
  `core_storefront` changes are in scope after the post-merge defect review: the claims
  engine's gate ordering and the stage-event response's truncation flag (see `design.md`,
  "Post-merge defect review"). Deployment surfaces are touched for the readiness probe:
  the storefront Helm chart and the VM compose stack's storefront healthchecks. No kit
  change; the API-credits storefront is deliberately not covered (see `design.md`).
- **Affected tests:** storefront unit and integration suites for pause, gate-wiring,
  readiness, and settlement stage-event identity; `core/storefront` and
  `core/storefront-client`; the VM and API-credits e2e scenarios.
- **Affected documentation:** `docs/development/TESTING.md`'s async-discipline section
  gains the pause-verify-advance rule; `ARCHITECTURE.md`'s operator lifecycle controls
  section stops being provisioning-only.
- **Wire compatibility:** `pause`/`resume` keep their routes and meaning; the lifecycle
  pause is a separate pair of routes rather than a widening of them. Two additive
  behaviour changes land with the readiness work: `/health` begins returning 503 when a
  timer loop has ended on its own, where it previously returned 200 with a degraded body,
  and a new `/ready` route becomes the storefront's readiness probe in the Helm chart and
  the VM compose healthchecks. An operator running the chart gets pod replacement for a
  dead loop that previously went unnoticed, which is the intended effect and worth calling
  out. The stage-event response gains a `truncated` field; existing clients ignore it.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — operator lifecycle controls apply to
      storefronts as well as the provisioning service
- [x] Existing subsystem specification — `openspec/specs/storefront-publication/spec.md`,
      `openspec/specs/test-compatibility/spec.md`, and
      `openspec/specs/settlement-servicing/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- A paused storefront performs no timer-driven work; a manual cycle invokes the
  production handler and bypasses the pause — `openspec/specs/storefront-publication/spec.md`.
- End-to-end scenarios drive lifecycle by pause and explicit advance rather than by
  waiting — `docs/development/TESTING.md` and
  `openspec/specs/test-compatibility/spec.md`.
- A loop's reported state is established by the loop reaching its gate, not by the
  existence of its task; reading the pause and acknowledging it are one operation —
  `openspec/specs/storefront-publication/spec.md`.
- Readiness, liveness, and diagnosis are separate surfaces: a loop that has not begun
  fails readiness, a loop that has ended fails liveness while nothing restarts it, and a
  paused storefront stays ready — `openspec/specs/storefront-publication/spec.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- A bounded operator query reports its own truncation —
  `openspec/specs/storefront-publication/spec.md`.
- A domain's settlement stage events carry that domain's settlement identity alongside the
  core engine's mechanism-neutral claim reference, translated at the domain seam —
  `openspec/specs/settlement-servicing/spec.md`.

## Dependencies and Related Changes

- `replace-polling-with-authenticated-push` replaces the cross-service pull loops with
  authenticated delivery and plans to refactor scenarios to await delivered events. It
  supersedes the *transport* this change steps, not the methodology: a scenario that
  today forces a pull will force a push, and pause-verify-advance survives. Landing this
  first gives that change a deterministic suite to refactor against rather than one that
  waits on intervals.
- `refactor-e2e-fulfillment-lifecycle` has three tasks parked since July on a live run it
  cannot make deterministic. This is the mechanism that unparks them.
- `monotonic-listing-reconciliation` should be diagnosed with this control in place: with
  the poller paused, a reserve's effect is observable before any reconciliation runs, and
  a single advance shows whether the reopen is a stale-view defect or a write-ordering
  one — the question that change's open list cannot currently settle.
