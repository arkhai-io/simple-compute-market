# Tasks — kit-owned storefront loop lifecycle

Implemented; awaiting code review, then the end-to-end pipeline and promotion. No
blocking dependency. Prerequisite of `contact-payload-retention` and
`bare-metal-mock-provisioned-deal`.

Validation levels follow `docs/development/TESTING.md`. The controller and route
service have no persistence, so kit tests are unit tests; storefront tests that drive
routes use the canonical `StorefrontClient` over `ASGITransport`.

## 1. Design

- [x] 1.1 **Decision gate.** Decide whether the loop lifecycle is extracted on its own
      or within `kit-owned-storefront-shell`. Decided: carved out and delivered first.
- [x] 1.2 **Decision gate.** Decide the controller's home and scope. Decided:
      `kit/storefront`, one instance per storefront process.
- [x] 1.3 **Decision gate.** Decide whose semantics the controller adopts. Decided:
      VM's, unchanged, with a step for every loop including the negotiation watchdog.
- [x] 1.4 **Decision gate.** Decide how a loop body orders its wait, gate, and work.
      Decided: gate on entry with a short held poll, work when due, then wait through
      the controller; the shared watchdog and servicing runners are reordered. Amended
      during implementation from "wait, then gate, then work", which leaves a loop
      unobservable for its first interval; see `design.md`.
- [x] 1.5 **Decision gate.** Decide which storefronts compose it in this change.
      Decided: all three, per the extraction requirement; API credits gains controls,
      and VM's aggregate capacity-poller loop moves into `kit/capacity-publication`
      so API credits does not copy it.
- [x] 1.6 **Decision gate.** Decide whether the loop pause persists across restart.
      Decided: no, matching VM.
- [x] 1.7 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations.

## 2. Kit controller and route service

- [x] 2.1 Add `kit/storefront/src/market_storefront_kit/lifecycle.py` with
      `StorefrontLoopController`, carrying VM's semantics from
      `domains/vms/storefront/src/market_storefront/lifecycle.py` as instance state:
      - `start_loop(task, *, route=None, step=None, preview=None, task_logger=None)`
        starts a `core_storefront.app_startup.StorefrontBackgroundTask`, keeps its
        handle, logs its completion, and registers its step under the route name;
      - `register_step(name, *, route, step, preview=None)` for a loop with no timer;
      - `declare(name)` returning a bound gate for fan-out loops it holds no handle for;
      - `gate(name)` acknowledging in the same call, and `loop_gate(name)`;
      - `idle(seconds, *, wake=None)` returning on the interval, `wake`, or a pause;
      - `request_pause(paused)` setting the flag and signal without waiting, and
        `pause()` / `resume()` returning per-loop states, `pause()` awaiting bounded
        quiescence (5 seconds);
      - `states()`, `registered_loop_names()`, `starting_loop_names()`,
        `failed_loop_names()`, `loops_check()`, and `is_pause_requested()`;
      - `run_cycle(route)` and `dry_run(route)`, invoking the registered step or
        preview and returning its result unchanged, raising a not-found error for an
        unknown route or a route with no preview.
      Keep the reasons VM's comments give for flag-not-cancel, acknowledge-in-gate,
      `starting` versus `pausing`, and declared names; cite the `market-composition`
      requirements this change adds.
- [x] 2.2 Add `kit/storefront/src/market_storefront_kit/lifecycle_routes.py` with a
      framework-free `StorefrontLifecycleRouteService` over one controller — `pause`,
      `resume` (each answering `{"paused": bool, "loops": states}`), `run_cycle(route)`,
      and `dry_run(route)` — and `LifecycleRouteError(status_code, detail)` answering 404
      for an unknown route or a route with no preview.
- [x] 2.3 Export both from `kit/storefront/src/market_storefront_kit/__init__.py`.
- [x] 2.4 **Unit.** `kit/storefront/tests/unit/test_lifecycle_controller.py`, carrying
      over the cases in VM's `tests/unit/test_lifecycle_registry.py` against a fresh
      controller per test: `starting`, `running`, `pausing`, `paused`, `exited`,
      `cancelled`; bounded quiescence naming unacknowledged loops; declared names
      waited on; an unregistered gated name reported once; `idle` waking on pause;
      `request_pause` without waiting; `run_cycle` invoking exactly the registered step
      while held and leaving the loops held.
- [x] 2.5 **Unit.** `kit/storefront/tests/unit/test_lifecycle_routes.py`: response
      shapes, step results returned unchanged, 404 for an unknown route and for a
      route with no preview.

## 3. Shared loop runners

- [x] 3.1 `kit/storefront/src/market_storefront_kit/negotiation_watchdog.py`:
      `run_negotiation_watchdog` gains `wait: Callable[[float], Awaitable[None]] | None`
      and runs wait, then gate with the existing 0.05-second held poll, then sweep. Keep
      the initial-delay deadline. Without `wait` it sleeps, as today.
- [x] 3.2 `kit/settlement-runtime/src/market_settlement_runtime/servicing.py`:
      `SettlementServicingWorker.run` gains `wait` and the same order.
- [x] 3.3 **Unit.** `kit/storefront/tests/unit/test_negotiation_watchdog.py` and
      `kit/settlement-runtime/tests/test_servicing.py`: a pause requested during the
      wait prevents the next cycle's work; an injected wait that returns early lets the
      gate be read before the interval would have elapsed; with no pause, one cycle runs
      per wait.

## 4. Capacity-event poller aggregate

- [x] 4.1 Move VM's aggregate capacity-poller loop out of
      `domains/vms/storefront/src/market_storefront/services/capacity_client.py`
      (`capacity_events_poller_loop` and `_AGGREGATE_GATE_SECONDS`) into
      `kit/capacity-publication/src/market_capacity_publication/capacity.py` as a
      method beside `poll_events`, taking the aggregate gate, the per-site gate factory,
      and the gate cadence. It starts the fan-out as its own task, gates on the
      aggregate name, surfaces the fan-out's failure, and cancels the fan-out on exit.
      Keep VM's comment explaining why the fan-out cannot be awaited directly.
      Implemented as the module function `run_capacity_event_pollers`, taking the
      runtime's bound `poll_events`, so it is testable without a configured runtime.
- [x] 4.2 **Unit.** In `kit/capacity-publication/tests/`: the aggregate holds while
      gated, surfaces a failed fan-out, and cancels it on exit.

## 5. VM

- [x] 5.1 `domains/vms/storefront/src/market_storefront/lifecycle.py` becomes a binding
      of one `StorefrontLoopController`: the loop-name constants,
      `capacity_site_loop_name`, and the module functions its call sites import
      (`gate`, `loop_gate`, `idle`, `declare_and_gate`, `start_registered_loop`,
      `loop_states`, `loops_check`, `registered_loop_names`, `failed_loop_names`,
      `starting_loop_names`, `reset_for_tests`) delegate to it. Remove the function-local
      import of the pause flag. Remove the comments claiming a health surface gates on
      loop state, and replace the dangling `storefront-publication` citation with the
      `market-composition` requirement.
- [x] 5.2 `domains/vms/storefront/src/market_storefront/server.py`: remove
      `_LOOPS_PAUSED`, `are_loops_paused`, and `_set_loops_paused`; the controller owns
      the flag.
- [x] 5.3 Add `domains/vms/storefront/src/market_storefront/lifecycle_steps.py` holding
      the step and preview bodies now inline in the admin controller —
      settlement servicing, fulfillment resume, site projections, capacity events with
      its preview, and publication with its preview — plus a negotiation-watchdog step
      calling `sweep_stale_negotiations`. Each returns the response shape its route
      returns today.
- [x] 5.4 `domains/vms/storefront/src/market_storefront/startup.py`: start every loop
      with its route and step; pass the controller's `idle` as `wait` to the watchdog
      and servicing runners.
- [x] 5.5 `domains/vms/storefront/src/market_storefront/controllers/admin_controller.py`:
      replace the per-loop lifecycle routes and `ADVANCE_LOOP_NAMES` with `pause`,
      `resume`, `{loop}/run-cycle`, and `{loop}/dry-run` delegating to the kit route
      service. Keep `/capacity/projections/refresh`. Confirm
      `middleware/admin_identity.py`'s lifecycle path mapping is unchanged.
- [x] 5.6 `domains/vms/storefront/src/market_storefront/services/capacity_client.py`:
      `capacity_events_poller_loop` calls the kit aggregate.
- [x] 5.7 Tests. Tombstone `domains/vms/storefront/tests/unit/test_lifecycle_registry.py`,
      whose cases move to 2.4. Update `tests/unit/test_loop_gate_wiring.py`,
      `tests/unit/test_lifecycle_advance_routes.py`, and
      `tests/integration/test_publication_loop.py` to drive the pause through the
      controller instead of `server._LOOPS_PAUSED`, and to assert route names against
      registrations rather than `ADVANCE_LOOP_NAMES`. Add the watchdog step's
      route-level case. Steps register when `lifecycle_steps` is imported, so routes
      answer whether or not startup ran; with its imports at module level, the
      advance-route tests patch collaborators on `market_storefront.lifecycle_steps`.

## 6. Bare metal

- [x] 6.1 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py`:
      `BareMetalStorefrontRuntime` owns one `StorefrontLoopController`.
- [x] 6.2 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/server.py`:
      start the negotiation watchdog and settlement-servicing worker through the
      controller with their gates, `wait`, and steps (`negotiation-watchdog`,
      `settlement-servicing`); register `publication` as a step with no timer and no
      preview, keeping the publication lock.
- [x] 6.3 `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`: add
      `pause`, `resume`, and `{loop}/dry-run`, and route `{loop}/run-cycle` through the
      kit route service, each authenticated by `_admin` under the canonical client's
      operation names and resources.
- [x] 6.4 **Integration.** `domains/bare_metal/storefront/tests/test_http_system.py`
      through `StorefrontClient`: pause reports both loops `paused`; each step runs
      while held and the loops stay held; resume reports them running; an unsigned
      pause is refused; publication has no preview; an unrun loop is still not found;
      concurrent publication steps still serialize.
      `tests/test_app_composition.py`: the registered loop names equal the loops
      startup creates. The startup-registration case landed in `test_http_system.py`
      beside the other lifecycle cases. The runtime owns its controller as an
      `init=False` field, so `dataclasses.replace` builds a fresh one, and registers
      settlement servicing only when a worker is composed.

## 7. API credits

- [x] 7.1 `domains/apicredits/storefront/src/apicredits_storefront/container.py` holds
      one `StorefrontLoopController`; `startup.py` starts the watchdog and servicing
      worker through it with gates, `wait`, and steps, and the capacity-event pollers
      through the kit aggregate with per-site declared gates, a step draining one cycle
      per site, and a preview.
- [x] 7.2 `services/capacity_client.py`: `capacity_events_poller_loop` calls the kit
      aggregate.
- [x] 7.3 Add `controllers/lifecycle_controller.py` with `pause`, `resume`,
      `{loop}/run-cycle`, and `{loop}/dry-run` over the kit route service, and add to
      `middleware/admin_auth.py` a dependency authenticating an administrator under an
      explicit operation and resource — the canonical client's — rather than the route
      name and path. Include the router in `server.py`.
- [x] 7.4 **Integration.** `domains/apicredits/storefront/tests/integration/test_lifecycle_routes.py`
      through `StorefrontClient`: pause holds all three loops, each step runs while
      held, resume, an unsigned request refused, an unknown loop not found. **Unit.**
      `tests/unit/test_server_composition.py`: registered loop names equal the loops
      startup creates. The canonical client is a new development dependency of the
      API-credit storefront, relocked with `make lock`.

## 8. Validation

- [x] 8.1 `make test` in `kit/storefront`, `kit/settlement-runtime`, and
      `kit/capacity-publication`: 45, 92, and 55 passed.
- [x] 8.2 `make test` in `domains/vms/storefront`, `domains/bare_metal/storefront`, and
      `domains/apicredits/storefront`, after `make dist` so each environment installs the
      rebuilt kit wheels. VM 1069 unit and 266 integration passed; its two
      `test_alkahest` integration cases need a local chain fixture and fail identically
      before this change. Bare metal 220, API credits 90 passed. VM's environment was
      installed from its frozen lock because re-resolving it fetches `torch` metadata
      from a host the validation environment could not reach.
- [x] 8.3 `make test` in every other project whose lock includes `kit/storefront`,
      `kit/settlement-runtime`, or `kit/capacity-publication`, found from the locks. All
      passed. `domains/apicredits`'s aggregate stops at its TypeScript and Rust
      middleware toolchain check, unavailable in the validation environment, after its
      Python suites pass. `e2e-tests` unit: one failure,
      `test_buyer_deployment_mounts_separate_profile_state_and_credential`, asserting on
      `docker-compose.yml`, which this change does not touch.

## 9. Closeout

- [x] 9.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Keep the rationale for flag-not-cancel, acknowledge-in-gate, the held
      poll, and declared names at the controller, not at each consumer.
- [x] 9.2 **Import placement.** Review imports this change added or touched; VM's
      function-local import of the pause flag is removed rather than moved. Verify
      against the real suites. VM's step imports moved to module level. Two bare-metal
      step imports and one API-credit step import stay local, each a circular import
      verified by attempting the move.
- [x] 9.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. Confirm the controller contract and the
      loop-state semantics landed as `market-composition` requirements.
- [x] 9.4 **Narrative compression.** Shorten completed-task notes to final behaviour
      and material evidence.
- [ ] 9.5 **Roadmap currency.** Goal 4's timer-loop row leaves the table in
      `docs/development/ROADMAP.md`, and its result joins Goal 4's current-state prose.
- [ ] 9.6 **Campaign index currency.** Update this change's row and Goal 4's graph in
      `openspec/changes/README.md`, and the rows of the changes it unblocks.
- [x] 9.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=kit-owned-storefront-loop-lifecycle` and resolve
      every match.
- [x] 9.8 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports. Passed.
- [ ] 9.9 **End-to-end pipeline.** Not yet run: it runs in GitHub Actions from a pushed
      branch, after review. Confirm both lanes pass and record the run: the VM
      lane's lifecycle-paused scenarios exercise the migrated VM binding, and the
      bare-metal lane's publication scenario exercises the bare-metal publication step
      through the kit route service. If the pipeline cannot run for a reason unrelated
      to this change, record the blocker and treat its validations as unrun.
- [ ] 9.10 **Promotion.** Complete the design-promotion record below, after code
      review: the `market-composition` delta, `ARCHITECTURE.md`, `TESTING.md`'s loop
      table, and the roadmap and index currency of 9.5 and 9.6.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One kit-owned loop controller per storefront process; every timer loop registers with it, paired with its step | `openspec/specs/market-composition/spec.md` |
| A loop waits, then gates, then works | `openspec/specs/market-composition/spec.md` |
| A loop's reported state is established by the loop | `openspec/specs/market-composition/spec.md` |
| The loop pause is process-local | `openspec/specs/market-composition/spec.md` |
| `kit/storefront` owns the loop controller beside the shell seams | `docs/development/ARCHITECTURE.md#kit-layers`, `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` |
| Every storefront's loops are held and stepped through the kit controller | `docs/development/TESTING.md` loop table |
| Goal 4's timer-loop gap closes | `docs/development/ROADMAP.md` Goal 4 |
