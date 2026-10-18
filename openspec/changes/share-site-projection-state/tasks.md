# Tasks — share site projection state

Carved out of `kit-owned-listing-and-fulfillment-lifecycles` on 2026-10-14 as the
prerequisite of `unbacked-bare-metal-listings`. Design reviewed in three rounds; planning
questions P1 and P2 decided 2026-10-15 with the review waived. Depends on nothing open.

Section order follows the layers: the core primitive and the kits first (2–7), then VM
(8–10), bare metal (11–14), the API-credit storefront and the loop controller's last
callers (15), the bare-metal chart (16), and closeout (17). Every section leaves each
end-to-end lane able to run: the bare-metal storefront's configuration and its Compose and
lane files change in one section (11), and its publication timer lands with the scenarios
that hold it (13). The bare-metal chart is non-functional from Section 11 until Section 16,
which the owner accepted; its render tests keep passing in between because they read only
the chart.

All paths under `domains/vms/storefront/` are VM's storefront, under
`domains/bare_metal/storefront/` bare metal's, and under `domains/apicredits/storefront/`
the API-credit storefront's; `src/` abbreviates each package's source root
(`market_storefront`, `arkhai_bare_metal_storefront`, `apicredits_storefront`).

## 1. Design

- [x] 1.1 **Decision gate.** Record the carve-out and its direction. Decided with the
      maintainer: bare metal shares VM's projection state and publication loop through
      the kit, as a prerequisite change, rather than adding a version watch to bare
      metal's publication ("A prerequisite, carved out of the kit lifecycle change";
      "Bare metal publishes on the same loop controller as VM").
- [x] 1.2 **Decision gate.** Decide each open question in `design.md` and record the
      decision there. Decided with the maintainer through three design reviews: D0–D6,
      D14 (D14a–d), and C1–C12; `design.md`'s open questions are none.
- [x] 1.3 Plan the implementation, naming the files each decision touches, the
      focused, integration, and end-to-end suites, and the permanent documentation
      destinations. Planned 2026-10-15; P1 and P2 decided on the way (`design.md` D6, C4).

The closeout placeholder that followed 1.3 was replanned as Section 17.

## 2. Per-site projection state in the kit

Delivers `SiteProjectionState` over a primitive that serializes each family's operations
(D2, D3, D4; `market-composition` "Per-site projection state is kit-owned and held once per
process"; `storefront-publication` "Projection-backed listing candidate derivation"). Touches
`core/storefront` and `kit/capacity-publication`; composes into no storefront yet.

- [x] 2.1 `core/storefront/src/core_storefront/site_projections.py`: `ProjectionCache` runs
      `poll_once`, `refresh`, and `refresh_after_topology_error` under one per-cache lock,
      the version check included. A caller arriving while an operation runs waits for it
      and returns its result rather than polling again, and a failed operation never
      replaces a `loaded` view or a `fetched_at` that a later-started operation already
      confirmed (D2, 03 F3). Keep the `validate` hook and every state transition as they
      are. Tests in `core/storefront/tests/unit/test_site_projections.py` (unit): a poll
      and a refresh started together run once each in order; a failing version check that
      began before a successful refresh completed leaves the view `loaded` with the later
      `fetched_at`; the existing coalescing test still passes.
      Done: every operation runs through one lock and records the running operation. A
      *poll* (`poll_once`, `refresh()` unforced, `refresh_after_topology_error`) arriving
      while any operation runs joins it and returns its view; a *forced refresh* waits for
      it and then fetches. The split follows D4's refresh-and-reconcile category: an inline
      refresh reconciles a change its caller has just made, so it needs a snapshot taken
      after that change and must not adopt an earlier-started poll's result. `design.md` D2
      is amended to state this rule, which its first wording ("an inline refresh … waits
      for it and returns its result") contradicted. The "started together" test does not
      distinguish the readings (it passes on the old cache too, since its two operations
      never overlap there); "a refresh requested during a poll waits for it before
      fetching" does. A joined poll whose operation is cancelled polls for itself, unless
      its own task is being cancelled too, when it re-raises. Unforced `refresh()` no
      longer re-enters the lock: it deadlocked on a remote identity change before. The
      private `_identity`/`_value`/`_state` fields VM's tests set are unchanged. Unit
      (`make test-core`, core storefront 202 passed, 2 skipped): ten new cases — the two
      named above, a refresh requested during a poll waiting for it, a poll during a
      refresh returning its result with no version call, three concurrent polls making one
      version call, a drift check sharing a running poll's check, a poll joined to a
      cancelled operation polling for itself, a cancelled caller joined to a cancelled
      operation not polling, unforced refresh as a poll, and unforced refresh after a
      remote change. Against the cache before this section (module swapped in, then
      restored), five fail and the unforced-refresh-after-change case hangs until its
      one-second timeout; the cancelled-caller case also fails against the first version
      of this fix. The existing coalescing test is renamed
      `test_concurrent_forced_refreshes_never_overlap`, since forced refreshes no longer
      coalesce. The tests synchronize on events the fake client sets when a call starts
      and gates it parks on; the one point no fake can observe — a caller parked on the
      cache's lock or joined to its running operation, which calls nothing — is reached
      through a single documented yield, `_let_new_tasks_reach_their_wait`, rather than a
      production hook. A missed join shows as an extra recorded call, so it fails the test.
- [x] 2.2 `kit/capacity-publication/src/market_capacity_publication/site_projections.py`
      (new): `SiteProjectionState` with the interface `design.md` D2 records, over a
      `core_storefront.aggregation.AggregateCapacityClient`. Move VM's
      `_RemoteProjectionClient` (`domains/vms/storefront/src/services/site_projection_cache.py`)
      here as the per-family client. The constructor builds a resource-pool and a
      capacity-bucket `ProjectionCache` for every site the aggregate names, installs each
      site's topology-error handler, and takes `on_resource_pool_change`. `values(family)`,
      `view(site_id, family)`, `status()` (as `core_storefront.models.system_models.ProjectionFamilyStatus`),
      `poll_once()` (first load included), `refresh_site(site_id, *, families=None)`, and
      `run(*, interval, gate, wait)`. An unconfigured site raises `CapacityBindingError`;
      an unknown family raises `ValueError`; `refresh_site` never raises for a failed
      fetch. Export `RESOURCE_POOL` and `CAPACITY_BUCKET` and the class from `__init__.py`.
      Done as planned; `freshly_confirmed` is exported too. The constructor refuses a
      client that is not an `AggregateCapacityClient` (`CapacityConfigurationError`),
      since only an aggregate names its sites. `run` gates, polls, and waits through the
      injected wait, re-reading a held gate every 50 ms as the kit's other gated runners
      do; a failing poll is logged and the loop continues. **Differed:** VM's
      `_RemoteProjectionClient` is copied, not yet removed, because its only caller is
      VM's loader, which 8.5 deletes; Section 8 removes VM's copy with it.
      **Correction:** 8.5's text now names `_RemoteProjectionClient` among what goes.
      `run` re-reads a held gate on the kit's held-poll interval rather than through the
      injected `wait`, as every kit runner and the controller's own `HELD_POLL_SECONDS`
      do: the controller's wait returns at once while a pause is requested, so waiting
      through it while held would spin. Its test observes each gate read and no longer
      depends on that interval.
- [x] 2.3 Same module: the refresh categories of D4. `poll_once` and the topology drift
      check (one coalesced check of every family of the site, never retrying the request)
      call `on_resource_pool_change` when a resource-pool identity changed;
      `refresh_site` never does. A failed operation in any category keeps the site's last
      generation `stale` with its error and does not advance its confirmation.
      Done: `poll_once` and each site's drift check compare every site's resource-pool
      identity before and after and wake on a difference (the first load is a change,
      as VM's poller treats it); the drift check runs `refresh_after_topology_error` on
      both of the site's families, so it shares a check already running on either.
- [x] 2.4 Same module: `freshly_confirmed(view, *, now, window_seconds)`, the source-check
      rule both domains apply (D5): `loaded`, a `fetched_at`, and an age within the window.
      The window itself is each storefront's configuration, resolved in Sections 9 and 13.
      Done; an age equal to the window still confirms.
- [x] 2.5 Tests in `kit/capacity-publication/tests/unit/test_site_projection_state.py`
      (new, unit, over a fake aggregate injected through the constructor): both families
      loaded per site; `values` omits a site holding nothing and maps a loaded empty site to
      `[]`; a failed poll keeps the last generation `stale` and omits nothing from
      `values`; `poll_once` wakes on a resource-pool change only; `refresh_site` never
      wakes; a topology error checks both families once and wakes on a resource-pool change;
      unknown site and family errors; `freshly_confirmed` at, inside, and past the window,
      and for each non-`loaded` state.
      Done (unit, `make -C kit test-capacity-publication`: 91 passed, 22 of them this
      file), plus refresh-site family selection, a failed refresh and a failed drift
      check confirming nothing, status reporting without rows, the non-aggregate
      refusal, and `run` polling per cycle and not while held, with a test-driven gate
      and wait.
- [x] 2.6 `kit/capacity-publication/pyproject.toml`: bump the version; pin the
      `arkhai-core-storefront` release carrying 2.1. Refresh the locks the repository's
      tooling names (`make lock`).
      Done: `arkhai-core-storefront` 0.12.1, `arkhai-kit-capacity-publication` 0.8.0
      pinning it; the three storefronts' exact `==0.7.0` pins of the kit move to
      `==0.8.0` so their locks resolve the wheel the tree builds. `make lock` relocked
      every project except `domains/vms/storefront`, `domains/vms/buyer`, and
      `kit/policy`: this session's egress policy refuses `download.pytorch.org` (403 on
      CONNECT), which those three declare as an index. Neither `kit/policy` nor the VM
      buyer names either bumped package, so their locks need no change (`check-locks`
      agrees). VM storefront's lock was updated by hand with exactly the five version
      and wheel-name substitutions uv wrote into bare metal's lock for the same two
      packages; `make check-packaging` passes with it (every lock matches its project
      and the wheels the tree builds). Relock it with `make lock
      PROJECTS=domains/vms/storefront` wherever the PyTorch index is reachable; it
      should produce no diff.
- [x] 2.7 Validation: `make test-core`, `make -C kit test-capacity-publication`,
      `make check-architecture`, `make check-packaging`, `make test`.
      End-to-end: none; nothing composes the state until Section 8.
      `make test-core` (core storefront 202 passed, 2 skipped) and `make -C kit
      test-capacity-publication` (91 passed) pass;
      `make check-architecture` and `make check-packaging` pass; `make
      check-comment-hygiene` passes; `make check-doc-citations
      CHANGE=share-site-projection-state` reports nothing. **Correction (end-to-end):**
      `SiteProjectionState` is composed nowhere yet, but 2.1 changes core's
      `ProjectionCache`, which VM's `services/site_projection_cache.py` already uses, so
      VM's projection-backed scenarios exercise the new serialization now: `e2e_deal`,
      `e2e_deal_buyer_cli`, `multi_registry` (its admin refresh), `e2e_listing_shapes`,
      `e2e_compute_dynamic_listings`, `e2e_pool_declared_modes`, and `e2e_vm_introduction`.
      No bare-metal or API-credit scenario reaches it.
      `make -k test`: every suite that ran passed (54 pytest runs, no failure), but three
      projects did not run, because their environments cannot be created while
      `download.pytorch.org` is refused: `kit/policy`, `domains/vms/buyer`, and
      `domains/vms/storefront`. The VM storefront is the one that matters here: its
      tests build `ProjectionCache`s and set their private fields, and they ran against
      neither the new cache nor the new kit in this session. They were then run against
      this section in torch-free environments (frozen sync from the committed locks, the
      internal wheels reinstalled): VM storefront unit 1036 passed, 1 skipped; VM storefront
      integration 411 passed, `test_alkahest` included against Anvil; `kit/policy` 63
      passed; VM buyer 197 passed. (`test-deployment-packaging` stopped at `helm-render`
      for want of a `helm` binary; nothing in this section reaches a chart.)

Section 2 handoff:

- `SiteProjectionState` composes nothing yet. Section 8 builds it over VM's capacity
  runtime aggregate; its topology handler replaces VM's (`set_topology_error_handler` is
  per site client, so installing the kit's overwrites VM's bucket-only handler once VM
  stops installing its own in 8.5).
- A topology handler needs a site client with `set_topology_error_handler` and the four
  projection methods: VM tests whose aggregate members are SQLite or fake clients will
  need those (Section 8's fake aggregate in `tests/fake_site.py`).
- The poll/refresh split in 2.1 is the behaviour Section 8's inline refreshes rely on:
  `refresh_site` always fetches after its caller's change, even while the poller runs.
- `ProjectionCache` keeps no `_refresh_lock` attribute; nothing outside core named it.
- Known, benign: `poll_once` compares every site's resource-pool identity before and after
  its cycle, so a `refresh_site` that lands a change mid-cycle can make the poller wake
  publication once more than the change alone would. A wake only makes publication run
  sooner, so no change is planned.

## 3. The loop controller is the one place a cycle runs

Delivers `run_cycle` as the single cycle boundary with outcome recording and a snapshot
(D6; `market-composition` "A loop records each cycle's outcome with the controller").
Touches `kit/storefront` and `kit/capacity-publication`. The existing `start_loop` and
step-only `register_step` stay until Section 15 removes them, once every storefront has
moved.

- [x] 3.1 `kit/storefront/src/market_storefront_kit/lifecycle.py`: `register_loop(name, *,
      step, interval_seconds, route=None, preview=None, wake=None)` registers a loop's step
      and interval; the controller starts its timer, a gate, `run_cycle`, `idle` loop over
      the same operation. `run_cycle(name)` holds that loop's lock, runs the step, and
      records exactly one terminal outcome in a `finally`; a held loop runs no timer cycle,
      so a step while held never waits on one. `dry_run` takes no lock and records nothing.
      Done. **Differed:** `register_loop` registers only; `start_loops()` starts the timer
      of every registered loop that has none, returning the handles, because VM registers
      its steps at import and starts its loops at startup, and bare metal registers in its
      runtime's constructor: a registration that started a task would need a running event
      loop at registration. A loop whose timer ended keeps its handle and is not restarted;
      `clear_loops` keeps registrations and drops handles, outcomes, and locks, so
      `start_loops` after it starts afresh. `register_loop` also takes
      `initial_delay_seconds` (default 0), because every kit runner but VM's publication
      makes its first cycle due one interval after start (watchdog, servicing, payment
      reconciliation, retention); the gate is read throughout the delay and a wake brings
      the cycle forward. `run_cycle` keeps its route-name key, as the lifecycle routes call
      it; the lock and the outcome are the loop name's. Every step goes through the locked,
      recorded cycle, a step-only `register_step` loop's included, so bare metal's stepped
      publication is serialized and recorded now. The timer re-reads the gate under the
      lock immediately before the step, so a timer that waited on an operator's step does
      not start a cycle a pause requested meanwhile holds; it clears its wake only there,
      when the cycle actually runs, so a wake a held timer did not act on still runs the
      loop promptly once resumed (D4). A failed timer cycle is recorded and the timer
      carries on to its interval; a failure before the step could start (the lock
      unobtainable) is logged with its traceback and the timer carries on too.
- [x] 3.2 Same module: outcome recording. Each outcome carries when the cycle finished,
      whether it completed, and for a failure the stage (`compose`, `run`, or `converge`)
      and the error. The step names its current stage through an operation the controller
      gives it. The controller takes, at construction, the exception types whose messages
      may be shown — each storefront's own configuration and publication errors — and
      records any other exception by type only; the full exception is logged.
      Done: `CycleOutcome(finished_at, trigger, completed, stage, error)` with
      `CycleError(type, message)`; `trigger` (`timer` or `step`) is added so status can say
      which ran it. The operation is `controller.enter_stage(stage)`, a plain
      `Callable[[str], None]` a domain can inject into a kit cycle driver; it finds its
      cycle through a context variable `run_cycle` sets, so `LoopStep` keeps its
      no-argument shape, and outside a cycle (a preview, a direct call) it records nothing.
      A cycle starts in `run`, so a loop naming no stages fails in `run`. The constructor
      takes `disclosed_errors` and an injectable `clock` (UTC by default). A cancelled cycle
      records `completed=False` with error type `CancelledError`. A step cancelled while it
      waits for the running cycle also records a cancelled outcome, naming no stage: the
      delta says each invocation records exactly one terminal outcome, and an operator's
      step request is an invocation even when it never reached its step. A timer that
      queued on the lock and was cancelled records nothing, as it had not passed its
      re-read gate. The full exception is logged at ERROR with its traceback when the
      cycle records it, for timer and step alike.
- [x] 3.3 Same module: `snapshot()` returning every loop's state and last outcome; an
      `exited` or `cancelled` loop stays distinct from a `running` one whose last cycle
      failed. Export the outcome and snapshot types from `__init__.py`.
      Done: `snapshot()` maps every loop name — every loop with a state, a registered
      step, or a recorded outcome — to `LoopSnapshot(name, state, last_outcome)`; `state`
      is `None` for a step-only loop. `last_outcome(name)` reads one. The three types have
      `to_dict()` for a status model to adopt; `CYCLE_STAGES`, `DEFAULT_CYCLE_STAGE`,
      `TIMER_TRIGGER`, and `STEP_TRIGGER` are exported beside them.
- [x] 3.4 `kit/capacity-publication/src/market_capacity_publication/capacity.py` and
      `capacity_remote.py`: each per-site capacity-event cursor has its own lock, taken by
      that site's poller cycle and by the capacity-events step for that site, the one
      exception in shape D6 names (`market-composition`: "A kit runtime that fans one loop
      out into independent per-site cycles MUST serialize each site's cycle").
      Done: `SiteEventCursor` carries an `asyncio.Lock`. The step
      (`CapacityRuntime.drain_events_once` → `drain_site_events_once`) holds it for the
      whole cycle; the site poller takes it and reads its gate again under it, immediately
      before any request, skipping the cycle when held, as the controller's timer does
      (`market-composition`: a loop reads its gate immediately before any work). The
      preview takes none. `capacity.py` changes only the step's docstring.
- [x] 3.5 Tests (unit). `kit/storefront/tests/unit/test_lifecycle_controller.py`: a step
      requested during a timer cycle runs after it, never alongside, each recording its
      own outcome; a raising step records one failed outcome naming its stage; a
      non-disclosed exception's message is absent from the outcome; a preview records
      nothing; a held loop runs no timer cycle and a step while held completes at once;
      the snapshot distinguishes an exited loop from a failing one; a pause still lands
      within the quiescence bound with a long interval and the real loop body.
      `kit/capacity-publication/tests/unit/test_capacity_event_pollers.py`: a site's step
      waits for that site's running poll and not for another site's.
      Done (unit). `make -C kit test-storefront`: 98 passed, 31 of them new in
      `test_lifecycle_controller.py` — the cases named above (the held step finding the
      lock free, one acquisition and no wait), plus: two steps of one loop serialized; a
      timer that queued behind a step while a pause landed running no cycle; a wake that
      held timer did not act on staying set and running the loop once resumed; a step
      cancelled while queued recording a cancelled outcome with no stage; a timer unable
      to start a cycle logging it and carrying on; the timer running the registered step;
      a wake ending the wait; a wake set while held running once resumed; the initial
      delay idling through the controller; a failing timer cycle not ending the timer; a
      cancelled cycle recorded; a completed cycle naming no stage; a failure naming no
      stage being in `run`; a disclosed exception keeping its message; the clock stamping
      outcomes; `enter_stage` outside a cycle and an unknown stage; a cancelled timer
      keeping its last outcome; a step-only loop with no state; and `clear_loops`
      dropping outcomes before `start_loops` restarts. The new tests synchronize through
      seams rather than yields: an observed lock injected with `cycle_lock_factory` (a
      constructor parameter, as `disclosed_errors` and `clock` are) that counts
      acquisitions, a timer's first gate read through the controller's injected logger,
      and timer handles from `start_loops`. Two exceptions remain: the shared fixtures'
      teardown and the snapshot test's `_ended` helper read the controller's private
      `_handles`, as the pre-existing tests do; and the two wake-while-held tests wait on
      the controller's real 50 ms held poll after resume, bounded by `wait_for`.
      `make -C kit test-capacity-publication`: 93 passed, two new over parked fake feeds
      with an observed cursor lock (one through `CapacityRuntime`, one calling
      `site_events_poller` directly with the runtime's client and reconcile hook): a site's step waits for that
      site's poll and not another's; a poller that queued behind a step while a pause
      landed reads no feed. Each mutation was checked by swapping the module and
      restoring it: with the controller's lock removed the two serialization tests fail;
      with its gate re-read removed the queued-timer and kept-wake tests fail; with the
      wake cleared before the lock (the first version) the kept-wake test fails; with the
      cursor lock removed the per-site test fails; with the poller's re-read removed the
      queued-poller test fails.
      **Also changed:** bare metal's
      `tests/test_http_system.py::test_concurrent_publication_steps_run_one_after_the_other`
      observed the second step on `publication_lock`; the controller's lock now stops it
      first, so the test observes that lock instead. To inject it, bare metal's runtime
      gains a `loop_controller_factory` init field (default `StorefrontLoopController`)
      from which `__post_init__` builds `loops`, still `init=False`: a factory rather than
      the controller, so a runtime copied with `dataclasses.replace` builds its own
      controller and registers its steps there exactly once instead of sharing the
      original's. The test passes `loop_controller_factory=lambda:
      StorefrontLoopController(cycle_lock_factory=...)`. Application integration, through
      `StorefrontClient`: `make test-bare-metal` 311 + 134 passed.
- [x] 3.6 Bump both packages' versions and refresh the locks. Validation:
      `make -C kit test-storefront test-capacity-publication`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until a storefront registers
      a loop this way (Sections 9, 13, 15).
      Done: `arkhai-kit-storefront` 0.4.0, `arkhai-kit-capacity-publication` 0.8.1; the
      three storefronts' exact pins follow. `make lock` relocked every project except
      `domains/vms/storefront`, `domains/vms/buyer`, and `kit/policy` (the PyTorch index is
      refused here, as in 2.6); neither the VM buyer nor `kit/policy` names either package.
      VM storefront's lock was edited by hand with exactly the six version, specifier, and
      wheel-name substitutions uv wrote into bare metal's lock for the same two packages;
      `make check-packaging` passes with it. Relock it with `make lock
      PROJECTS=domains/vms/storefront` where the index is reachable (16.6); it should produce
      no diff. `make check-architecture`, `make check-packaging`, `make check-comment-hygiene`
      pass; `make check-doc-citations CHANGE=share-site-projection-state` reports nothing.
      `make -k test`: every suite that ran passed except the bare-metal test 3.5 adapts,
      which passes after it; the three PyTorch-index projects cannot reinit here and were
      run in their frozen environments with the rebuilt wheels reinstalled: VM storefront
      unit 1036 passed, 1 skipped, integration 411 passed (`test_alkahest` against Anvil
      included); `kit/policy` 63 passed; VM buyer 197 passed. API-credit storefront
      (`make test-apicredits`) passes.
      **Correction (end-to-end):** the pipeline was not run for this section; the
      scenarios below are the ones that will exercise it. No storefront registers a loop
      with `register_loop` yet, but every registered step now runs through the locked,
      recorded `run_cycle`, so each scenario that steps a loop through `run-cycle`
      exercises it: VM `e2e_deal`,
      `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_non_erc20_settlement`, `e2e_vm_introduction`,
      `e2e_listing_shapes`; bare metal `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`. The per-site cursor lock
      is on every capacity-event poller's cycle, so every VM-lane and API-credit-lane
      scenario runs through it (`e2e_credits_deal`, `e2e_credits_payment_deal` among them).
      No scenario reads an outcome yet; status gains `lifecycle` in Sections 9 and 14.
      **Interim:** loops still started with `start_loop` (every VM, bare-metal, and
      API-credit loop until Sections 9, 13, and 15 move them) gate and run their timer
      cycles themselves, so they record outcomes only for steps, and their timer cycles
      take no controller lock.

Section 3 handoff:

- `register_loop` registers; `start_loops()` starts every registered loop's timer. VM
  (module-level controller, steps registered at import in `lifecycle_steps.py`) can call
  `register_loop` where it now calls `register_step` and `start_loops()` in `startup.py`;
  bare metal registers in the runtime's constructor and starts in `server._start_runtime`.
  Pass `initial_delay_seconds=interval` for loops whose kit runner made the first cycle due
  one interval after start (watchdog, servicing, payment reconciliation, retention), and no
  delay for VM's publication and the site-projection poller.
- `SiteProjectionState.run` (Section 2) is redundant for storefronts once Section 8
  registers the poller with `register_loop(SITE_PROJECTION_POLLER, step=…poll_once…,
  interval_seconds=poll_interval)`: the controller's timer is the gate, cycle, and wait
  `run` reimplements. It was left in place here; Section 8 (or 17's review) should remove
  it and its tests if nothing else calls it.
- The step names its stages with `controller.enter_stage("compose" | "run" | "converge")`;
  a kit cycle driver can take it as an injected `Callable[[str], None]`. Construct each
  storefront's controller with `disclosed_errors=(its configuration and publication
  errors,)` (Sections 9, 13, 15); VM's controller is the module-level one in
  `market_storefront/lifecycle.py`.
- `wake` is the caller's `asyncio.Event`; an Event binds to the event loop that first waits
  on it, so a process (or test) that clears and restarts its loops on another event loop
  should register a fresh one. The controller's own pause signal and cycle locks are
  recreated by `clear_loops`.
- Bare metal's `publication_lock` is now redundant beside the controller's lock for steps
  in this process (13.2 removes it). Its runtime builds `loops` from
  `loop_controller_factory`, an init field: 13.2 can pass a factory building the controller
  with bare metal's `disclosed_errors` there.
- `LifecycleRouteError` raised from a step (bare metal's 503 on a compose failure) is
  recorded as a failed cycle; it is disclosed only if a storefront lists it.
- Known test hazard: each `SiteEventCursor` lives in the module-global cursor table, and
  its `asyncio.Lock` binds to the first event loop that waits on it (only when contended).
  A test that contends a cursor's lock and a later test that contends the same site's
  cursor on another event loop would fail with a bound-to-a-different-loop error unless
  `reset_site_event_cursors()` runs between them, as the capacity-publication tests'
  fixture does. Production runs one event loop.

## 4. Site trust from the site's service peer

Delivers response verification against a provider of a site's active principals, and the
shared resolution of a site's service peer (D14b; `storefront-publication` "Site authority
principals rotate with bounded overlap"). Touches `kit/site-client`,
`provisioning/compute/client`, and `core/storefront`; composes into no storefront yet.

- [x] 4.1 `kit/site-client/src/market_site_client/client.py`: `_AuthenticatedSiteClient`
      and both public clients accept, in place of a fixed `TrustedIdentitySet`, a provider
      read at each response's verification. A fixed set remains accepted as a constant
      provider, so callers that pin one (registries, tests) are unchanged.
      Done: `expected_authorities` is an `AuthorityTrust` (exported), a `TrustedIdentitySet`
      or a zero-argument callable returning one. The provider is synchronous and is called
      once per response, inside `_verify_response`, on an async client's event loop too, so
      it should read only local state. A provider that raises, or returns anything but a
      trusted set, fails that response with `SiteCapacityAuthenticationError` carrying the
      response's status; anything else at construction is a `TypeError`.
- [x] 4.2 `provisioning/compute/client/src/compute_provisioning_client/base.py` and
      `client.py`: the same, because bare metal's per-site provisioning client verifies the
      same site authority's responses.
      Done, the same shape in `SigningBase` (both variants), failing closed with
      `ComputeProvisioningAuthenticationError`; `AuthorityTrust` is exported from the
      package. The two clients each define the alias rather than share one: they share no
      package but `kit/identity`, which this section does not touch.
- [x] 4.3 `core/storefront/src/core_storefront/identity_authority.py` (or a sibling module
      it owns): the resolution VM performs in
      `domains/vms/storefront/src/middleware/service_peer_auth.py`'s
      `_allowed_service_principals` and `initialize_service_peer_identities` moves here, so
      both compute storefronts share it: seeding configured service peers into durable
      state, refusing a site bound to no peer or to more than one, and a site's currently
      active principals (`active_principals(now)`) for both response verification and
      callbacks. VM's middleware calls it; its behavior is unchanged.
      Done in a sibling module, `core_storefront/service_peers.py`, over a
      `ServicePeerConfigs` mapping (peer ID to role, site, configured principals — the shape
      VM's `get_service_peer_configs()` returns, so each storefront passes its own
      configuration in): `seed_service_peers` (VM's seeding, moved verbatim, still raising
      `AuthError`; the middleware now reads `get_service_peer_configs()` on the event loop
      as an argument rather than inside the worker thread, an in-memory Dynaconf read),
      `require_one_service_peer_per_site` (the startup refusal Sections 10.1 and
      12.1 call, raising `ServicePeerConfigurationError` that names every site bound to no
      peer or to several), `site_active_principals` (VM's `_allowed_service_principals`,
      moved verbatim, for callbacks), and `site_trusted_authorities`, the provider 4.1 and
      4.2 accept: it re-reads the peer's durable state at every call and returns the
      primary first. VM's `initialize_service_peer_identities` is now a one-line call with
      its configuration and `_allowed_service_principals` is gone; the middleware still
      reads `get_service_peer_configs` through its own module, so the tests that patch it
      there are unchanged.
- [x] 4.4 Tests (unit). `kit/site-client/tests/unit/test_client.py`: a provider is read per
      response, so a rotation that ends its overlap is honored without rebuilding the
      client; the existing fixed-set tests pass unchanged. The provisioning client's unit
      suite: the same. `core/storefront/tests/unit/test_identity_authority.py`: peer
      seeding, the no-peer and two-peer refusals, and active principals through a rotation.
      VM's `tests/unit/test_service_peer_identity.py` passes unchanged.
      Done (unit): `make -C kit test-site-client` 57 passed, 8 new — one client of each kind,
      under both signature schemes, follows a rotation from the old principal through the
      overlap to the replacement alone with the provider read once per response; a raising
      provider and one returning no set each fail the response closed; a non-set,
      non-callable is refused at construction. With the provider called once at
      construction instead (module swapped, then restored) six of them fail.
      `make test-compute-provisioning-client` 50 passed, 5 new — the same rotation and
      failing-provider cases through the async and the sync client, and the construction
      refusal. **Differed (level):** the core cases are library integration, in
      `core/storefront/tests/integration/test_service_peers.py` (new), not
      `tests/unit/test_identity_authority.py`, because they run against a real SQLite
      database and `TESTING.md` puts such library tests in `integration/`; the existing unit
      file is untouched. `make test-core` (core storefront 211 passed, 2 skipped; 9 new):
      seeding once and idempotently, a new peer with two principals refused, a seeded peer's
      site kept, reseeding after a rotation keeping durable principals and refusing
      configuration that no longer covers them, the startup refusal naming each problem
      site, no-peer and two-peer sites authenticating nothing, active principals through an
      overlap and per site, the provider following a rotation through to retirement with
      no rebuild, and a disabled peer authenticating nothing. VM's
      `test_service_peer_identity.py` passes unchanged (below).
- [x] 4.5 Bump the three packages' versions and refresh the locks. Validation:
      `make -C kit test-site-client`, `make test-compute-provisioning-client`,
      `make test-core`, `make test-storefront`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: none until Sections 10 and 12.
      Done: `arkhai-kit-site-client` 0.11.0, `arkhai-compute-provisioning-client` 0.7.0,
      `arkhai-core-storefront` 0.13.0. **Also bumped:** `arkhai-kit-capacity-publication`
      0.8.2, because it pins core exactly (`==0.13.0` now), and the three storefronts' exact
      pins of it follow; VM's storefront declares `arkhai-core-storefront>=0.13.0`, since its
      middleware imports the new module. `make lock` relocked every project except the three
      PyTorch-index ones (refused here, as in 2.6). Neither `kit/policy` nor the VM buyer
      names a bumped package; VM storefront's lock was edited by hand with exactly the nine
      version, wheel-name, and specifier substitutions uv wrote into bare metal's lock for
      the same packages, plus its own core floor (ten edits); `make check-packaging` passes with it
      (16.6 relocks it). `make check-architecture` (in `check-packaging`), `make
      check-comment-hygiene` pass; `make check-doc-citations
      CHANGE=share-site-projection-state` reports nothing. `make -k test`: every suite that
      ran passed, `test-deployment-packaging` and the Helm render checks included; the three
      PyTorch-index projects cannot reinit here and were run in their frozen environments
      with the rebuilt wheels reinstalled: VM storefront unit 1036 passed, 1 skipped
      (`test_service_peer_identity.py` among them, unchanged), integration 411 passed (its
      callback-authentication cases in `test_admin_api.py` go through the moved
      resolution); `kit/policy` 63 passed; VM buyer 197 passed.
      **Correction (end-to-end):** the provider is composed nowhere until Sections 10 and 12,
      but VM's seeding and callback resolution now run in core: every VM-lane scenario seeds
      the storefront's service peers at startup, and those whose deal receives provisioning
      callbacks (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_non_erc20_settlement`,
      `e2e_compute_dynamic_listings`) authenticate them through it. The pipeline was not run
      for this section. No bare-metal or API-credit scenario reaches it.

Section 4 handoff:

- `site_trusted_authorities(db_path, peers, site_id)` is the provider Sections 10.2 and
  12.2 pass as a site's `expected_authorities`. `kit/capacity-publication`'s
  `CapacitySite.expected_authorities` is typed `Any` and passed straight to
  `SiteCapacityClient`, so a provider goes through `CapacitySite` with no kit change; VM's
  capacity-runtime cache key (`repr` of the authorities) must stop carrying principals,
  as 10.2 says, since a provider's `repr` names a function, not the trust.
- The provider must be built after `seed_service_peers` has run, and is read synchronously
  per response: two SQLite connections on the event loop. Core's storefront database does
  not run in WAL mode, so a read that meets a writer's commit can wait out `sqlite3`'s busy
  timeout and block the loop; the callback path, by contrast, reads in a worker thread.
  10.2 resolves this before composing the provider (see its text): verification is
  synchronous and the provisioning client's sync variant shares `SigningBase._verify`, so
  the provider itself must not block, not the client be made async-only.
- VM tests still patch `market_storefront.middleware.service_peer_auth.get_service_peer_configs`
  (`tests/unit/test_service_peer_identity.py`, `tests/integration/test_admin_api.py`,
  `tests/publication_app.py`), a module-level patch `TESTING.md` rules out. It predates this
  change and 4.3 kept the seam so those tests stay unchanged; Section 10, which recomposes
  VM's per-site trust, should inject the peer configuration instead and retire the patch.
- `require_one_service_peer_per_site(peers, site_ids)` is the startup refusal (10.1, 12.1);
  callers name their sites. It does not refuse a peer bound to a site that is not
  configured, which nothing has asked for.
- `seed_service_peers` and the per-site resolution raise `AuthError`, as VM's did; a
  composition root turning a seeding error into a named startup refusal wraps it.
- VM's `_callback` still requires exactly one configured service peer for the
  service-role status read, a VM rule left in VM; bare metal's status read (12.3) chooses
  its own.

## 5. The values-schema generator in `kit/config`

Delivers the generic generator in `kit/config`, VM keeping only its section list (D14c).
Touches `kit/config`, VM's storefront, and the root `Makefile`.

- [x] 5.1 `kit/config/src/market_config/values_schema.py` (new): the generic parts of
      `domains/vms/storefront/src/values_schema.py` — field publicizing, secret refusal,
      sink typing over sink models passed in (so `kit/config` takes no `kit/delivery`
      dependency), rendering, the drift check, and the `write`/`check` entry — plus the
      refusal of a retired key in a storefront's `config`, which C4 needs.
      Done: `any_case`, `other_spellings`, `any_case_fields`, `model_fragment(model, *,
      role)`, `settlement_fragment(mechanisms, *, role)` (reading only each registration's
      `config_key`, `config_model`, and `roles`, through a `SettlementSection` protocol,
      so tests need no full `MechanismRegistration`), `sink_typed_section`,
      `config_definition(sections, *, retired=())`, `render` and `stale_files` keyed by the
      definition's name, and `main(argv, *, build_definition, name, schema_files,
      description)`, whose `write`/`check` take the repository root as `--root` (the
      working directory by default) and resolve the service's named files under it. A
      retired key is a dotted path refused in any spelling: it adds a refusing pattern
      for its last segment, and for each section on the way a pattern declaring it an
      object, under a typed section exactly as under an untyped one, which leaves the rest
      of that section as it was. **Correction (review):** the first version also opened a
      section among entries an `additionalProperties` schema types, and a key matching a
      pattern skips that schema, so retiring `delivery.west.legacy` reopened a webhook's
      secret `url`. Generation now refuses a retired key that lies among such entries or
      under a combinator (`anyOf`, `allOf`, … — an optional model is one), whose fields a
      pattern cannot see; such a key is retired in its model instead. It also refuses a
      retired key a typed section still has, and a retired key under another retired key
      (it once reported the outer one as "still a typed field"). The section fragments are copied before retiring, so a
      caller's fragment is never mutated. The module is imported as
      `market_config.values_schema`, not re-exported from the package root, as
      `config_loader` and `registry_url` are not. **Differed:** `sink_typed_section` takes
      the sink key and the section's own settings as well as the sink models, because both
      are the delivery kit's vocabulary (`SINK_KEY`, `RESERVED_SECTION_KEYS`) that a kit
      without a `kit/delivery` dependency cannot name; and the definition's name is each
      service's, passed in, not a kit constant.
- [x] 5.2 `domains/vms/storefront/src/values_schema.py`: reduced to VM's section list, its
      discovered sinks, its settlement registry, and the schema files it writes (its own
      chart and the umbrella's storefront definition). The root `Makefile`'s
      `helm-values-schema` keeps its target and output.
      Done: `DEFINITION`, `ROLE`, `SCHEMA_FILES` (repository-relative), `RETIRED_KEYS`
      (empty; 10.3 adds `claims_sweep_interval`), `[Delivery]`'s own three settings, and
      `storefront_config_definition`, which discovers the installed sinks and builds the
      sections over the kit. The `Makefile` target keeps its name and writes the same two
      files, now passing `--root ../../..` rather than the file list, since the storefront
      names its files; its `STOREFRONT_VALUES_SCHEMAS` variable goes.
- [x] 5.3 Tests. `kit/config/tests/unit/test_values_schema.py` (new, unit): publicizing,
      secret refusal, sink typing, retired-key refusal, and drift detection over a small
      model set. VM's `tests/unit/test_values_schema.py` passes with the committed schemas
      unchanged, proving the move regenerates the same definition.
      Done. Kit (unit, `make -C kit test-config`: 155 passed, 24 of them this file):
      any-case and other-spelling patterns; a closed typed section; no defaults,
      references, markers, or exact names; case-only collisions refused; recursive
      references unconstrained; secret and role-inapplicable fields refused, and a field
      applying to the roles it names; a nested secret refused; settlement closed to the
      mechanisms registered for the role; the sink section's own settings, per-sink
      typing, a named table stating no other sink, a named instance typed by its `sink`, an
      untyped sink open, and the misspelled sink key refused; a retired key refused at the
      top level, in an untyped section, and in a typed one without mutating the caller's
      fragment; a retired key a typed section still has, and a malformed path, refused at
      generation; no retired keys adding nothing; render replacing only its definition;
      `stale_files` naming the stale file; and `write`/`check` round-tripping files under
      `--root`. **Amended (review):** 161 passed, six added — a retired key among entries an
      `additionalProperties` schema types (the sink section, a typed mapping), under an
      optional model's `anyOf`, and under another retired key (both orders) each refused at
      generation, and a missing schema file named with the root, exit 2, rather than a
      traceback. The two tests named "… any spelling" check that the schema keys a field by
      its `any_case` pattern, which `test_any_case_matches_every_spelling_and_nothing_else`
      proves; they are renamed to say so. No kit test validates documents against a
      schema: `kit/config` has no JSON Schema validator, and VM's tests validate its
      committed definition with `jsonschema`. VM (unit, frozen environment): the generic cases moved to the kit (any-case,
      case collisions, nested secrets, recursive references, the stale check, a sink
      without a declared model); VM's file keeps the cases on its own definition and its
      committed schemas, reads the schema paths from `SCHEMA_FILES`, and adds one: the
      command checks the files the storefront names under the repository root.
      `test_values_schema.py` 29 passed, the drift test against the committed schemas
      unchanged; `make helm-values-schema` rewrote both files (new modification times)
      with no diff.
- [x] 5.4 Bump `kit/config`'s version, declare it where VM imports it, refresh the locks.
      Validation: `make -C kit test-config`, `make test-storefront`,
      `make helm-values-schema` with no diff, `make -C helm test-render`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end: none.
      Done: `arkhai-kit-config` 0.3.0; VM declares `arkhai-kit-config>=0.3.0`. `make lock`
      relocked every project but the three PyTorch-index ones (refused here, as in 2.6); VM
      storefront's lock was edited by hand with the version, wheel-name, and specifier
      substitutions uv wrote for the same package elsewhere (16.6 relocks it), and so was
      `domains/vms/buyer/uv.lock`, which locks `arkhai-kit-config` too (its version and
      wheel name, 0.2.0 to 0.3.0); `kit/policy` does not lock it. Evidence, after `make
      dist` and reinstalling the rebuilt internal wheels into the frozen environments:
      `make -C kit test-config` (unit) 155 passed; VM storefront (frozen, `UV_FROZEN=1`) unit
      1031 passed, 1 skipped (five fewer than before: the generic cases moved to the kit),
      integration 411 passed, `test_alkahest` against Anvil included; `make
      helm-values-schema` (which runs `uv run --frozen --no-sync`, so VM's lock is not
      re-resolved) rewrote both schemas with no diff; `make -C helm test-render` with
      `STOREFRONT_PYTHON` set to VM's environment passed, the loader check
      (`test_rendered_document_loads_with_the_storefront_loader`) run, not skipped; `make
      check-packaging` (architecture rules included), `make check-comment-hygiene`, and
      `make check-doc-citations CHANGE=share-site-projection-state` pass, the last reporting
      nothing. `make -k test`: 50 pytest runs and every non-Python suite passed; it stopped
      only at the reinit of `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer`,
      whose frozen runs are VM storefront's above, `kit/policy` 63 passed, and VM buyer 197
      passed. No repository typing target exists; `mypy` run ad hoc on the kit module and on
      VM's `values_schema.py` (settlement registrations against the kit's
      `SettlementSection` protocol) reports no issues. End-to-end: none — the generator
      changes only the Helm values schemas, which the pipeline's Compose lanes never render.

Section 5 handoff:

- Bare metal's generator (16.1) is a module like VM's `market_storefront.values_schema`: its
  `DEFINITION`, `ROLE`, `SCHEMA_FILES` (only `helm/charts/bare-metal-storefront/values.schema.json`),
  `RETIRED_KEYS`, a `build_definition` over the kit's fragments, and `main` delegating to
  `market_config.values_schema.main`; the root `Makefile`'s `helm-values-schema` gains a second
  line running it in bare metal's environment with `--root ../../..`.
- `sink_typed_section` takes the delivery kit's `SINK_KEY` and the `[Delivery]` section's own
  settings from its caller, because `kit/config` may not import `kit/delivery`. VM states those
  settings as `_DELIVERY_SETTINGS`, by hand, one per key of `RESERVED_SECTION_KEYS`; bare metal
  will need the same three. If a second copy looks wrong at 16.1, the natural home for their
  schema is `kit/delivery` beside `RESERVED_SECTION_KEYS`, which both storefronts already import.
- `RETIRED_KEYS` is empty; 10.3 adds `claims_sweep_interval` and regenerates both schemas. A
  retired key a typed section still has is refused at generation, so retire a key only once
  its model no longer carries it.
- The VM drift test still runs only in VM's environment (`make test-storefront`), which this
  container builds frozen; `make helm-values-schema` uses `--frozen --no-sync` and so runs
  there unchanged.
- Retirements now have two homes. Both charts already refuse retired keys in a hand-written
  `config.allOf` block beside the generated definition
  (`helm/charts/storefront/values.schema.json`, `helm/values.schema.json`: `seller`,
  `registryAuthority`, `registryUrl`, `storefrontDomains`, `configMapName`,
  `hostedSettlement`, `chain`, the CSV inventory keys, `escrow_templates`,
  `capacity.use_site_projection_for_listings`; `DEPLOYMENT_AND_CONFIG.md` describes them).
  10.3 decides whether `claims_sweep_interval` goes in `RETIRED_KEYS`, as planned, and then
  either moves the old block's keys there or states which home is for which kind of key;
  17.9 documents the outcome.
- For 17.9: D14c says each storefront writes only its own chart's schema, yet VM also writes
  the umbrella `helm/values.schema.json`'s storefront definition (as 5.2 planned). That
  definition types the umbrella's `storefront` subchart, which is VM's chart, so it is VM's
  artifact; the promotion should say so, so "a domain's tooling never writes another
  domain's artifact" stays unambiguous.
- For 17.9: `TESTING.md`'s "A values schema generated from typed models" says packaging
  checks cannot run the drift test "because the generator imports the storefront's
  third-party dependencies". The generator is now `kit/config` (pydantic only) with its own
  unit tests; only each storefront's section list needs its environment.
- `settlement_fragment` states the `[Settlement]` root keys `schema_version` and `priority`
  itself: the settlement runtime names them only as string literals in
  `SettlementRegistry.resolve` and exports no constant for them, so there is nothing to
  import. A runtime constant for the root keys would let the generator read them.

Orchestration handoff (for the next session): sections run one at a time through a fresh
implementer agent following `.agents/skills/change-implement/SKILL.md`, then a fresh-context
review; fixes are amended into the section commit or land as a follow-up commit. This
container's network policy blocks `download.pytorch.org`, so `kit/policy`, `domains/vms/buyer`,
and `domains/vms/storefront` run in environments built with `uv sync --frozen --find-links
.dist --reinstall-package <internal...>` and tested with `UV_FROZEN=1` (task 16.6 relocks them
elsewhere); Foundry (`anvil`) and Helm (built from source with `go install
helm.sh/helm/v3/cmd/helm@v3.16.4`) must be reinstalled in a fresh container.

## 6. Alkahest release conditions derived by the mechanism

Delivers listing `demands` derived by `kit/alkahest` for every domain, with each domain
declaring its release models (D14d; `storefront-publication` "An Alkahest listing advertises
its release conditions"). Touches `kit/alkahest` and the VM, bare-metal, and API-credit
storefronts (the API-credit storefront added by 6.7). Bare metal still reads its settlement configuration from its present source; Section 11 changes
the source, not the derivation.

- [x] 6.1 `kit/alkahest/src/market_alkahest/` (a new `release_conditions.py`, exported):
      the derivation now in `domains/vms/storefront/src/services/publication_terms.py`
      (`_recipient_demands_for_chains`, `_heartbeat_oracle_demands_for_chains`,
      `_splitter_demands_for_chains`, `_demands_for_chains`), taking the
      `[Settlement.alkahest]` policy, the seller wallet, and each chain's address book, and
      returning one release condition per chain. It is built with the Alkahest publication
      option (`settlement_config.py`'s `alkahest_option_builder` or the registration), so
      every domain composing Alkahest gets it.
      Done: `kit/alkahest/src/market_alkahest/release_conditions.py`, exported from the
      package. `release_conditions(config, *, chain_names, chains, wallet_address)`
      returns one `{chain_name, arbiter, demand_data}` per chain in chain-name order,
      refusing a chain `chains` does not configure; `config` is the typed
      `AlkahestSettlementConfig` section (none selects `recipient`), and each chain is a
      mapping or an object whose `alkahest_address_config_path` names its address book,
      so VM's `ChainConfig` objects and bare metal's chain mappings both serve.
      `publication_release_conditions(config, clauses, ...)` derives for the chains the
      Alkahest clauses publish on and skips other mechanisms. Beside them:
      `configured_release_model`, the three model constants, `RELEASE_MODELS`,
      `ReleaseModelError` (a `ValueError`), and `require_deliverable_release_model`
      (6.2). The refusals are VM's, unchanged in wording: oracle-gated with no trusted
      oracle, the trusted oracle equal to the wallet, and the oracle-gated and
      interruptible models together. **Differed:** the conditions are not emitted by
      `alkahest_option_builder`. VM derives a listing's `demands` into its create
      request before the listing service builds its options, and refresh compares them
      there, so a builder output VM ignored would be a second derivation path; instead
      each domain calls the kit's one function where it builds the listing (VM's
      publication terms, bare metal's composition where it builds the options, 6.4).
- [x] 6.2 Release-model declaration: a domain's Alkahest seller stage declares the models it
      can deliver (`recipient`, `oracle_gated`, `interruptible`); composition refuses a
      configured model the domain does not declare, naming it. VM declares all three
      (`src/settlement_stages.py`'s `VmAlkahestSellerStage`); bare metal declares `recipient`
      and `oracle_gated` (`src/settlement_stages.py`, `src/settlement_composition.py`).
      Done. VM: `VmAlkahestSellerStage.release_models` is a required keyword field, as
      `fulfils_through_capacity` is; `vm_seller_stages` declares `RELEASE_MODELS`;
      `build_vm_settlement_composition` checks a configured section, enabled or not,
      against the domain's Alkahest entry. Bare metal: a new `AlkahestStage(SellerStage)`
      carries `release_models` (`recipient`, `oracle_gated`);
      `BareMetalStorefrontSettlementComposition.__post_init__` checks a configured
      section; `build_runtime_from_environment` re-raises `ReleaseModelError` naming the
      model, where any other refusal of the settlement root still reads "must be strict
      shared settlement config". **Consequence:** a VM section stating both the
      oracle-gated and the interruptible model now refuses VM's startup at composition;
      before, VM started and every Alkahest candidate failed publication.
      **Amended (review):** VM's check is `require_vm_release_model(domain)` in
      `src/settlement_composition.py`, which `_build_vm_services` calls before it builds
      the database, signer, or anything else (beside the admissibility default's parse),
      as well as the composition; `design.md` D14d records the refusal for promotion.
- [x] 6.3 VM: `publication_terms.py` reads the kit's derivation and keeps no derivation of
      its own; `demands_for_publication_clauses` and its caller in
      `services/publication_loop.py` are unchanged in output.
      Done: `demands_for_publication_clauses(clauses, *, wallet_address)` keeps its
      signature and its caller; it resolves the typed `[Settlement.alkahest]` section
      through the storefront's registry and calls `publication_release_conditions` over
      `CHAINS`. The four private derivation functions go, and so does each VM stage's
      `publication_chains`, whose only caller was that derivation.
- [x] 6.4 Bare metal: `src/publication_composition.py` takes the kit's derivation and stops
      reading `BARE_METAL_STOREFRONT_DEMANDS`; remove it from `compose.bare-metal.yml` and
      `tests/test_publication_cli.py`. Startup refuses `interruptible` (spec scenario "A
      domain is configured for a release model it cannot deliver").
      Done: `BareMetalStorefrontSettlementComposition.publication_payload` loses its
      `demands` parameter and derives the conditions itself, through the kit's
      `release_conditions`, for the chains of the Alkahest escrows it built, from its
      configured section, `resources["wallet"]` (the seller address), and
      `resources["chains"]`. `publication_composition.py` no longer reads
      `BARE_METAL_STOREFRONT_DEMANDS`; `compose.bare-metal.yml` and
      `tests/test_publication_cli.py` drop it. **Differed:** the derivation sits in the
      settlement composition, which holds the section, wallet, and chains, rather than in
      `publication_composition.py`; and it covers only Alkahest options actually built
      (a ready mechanism), whereas VM derives from its clauses whatever their readiness,
      as before. Startup refuses `interruptible` (6.2). `design.md` D14d now records the
      mechanism as delivered and each domain's input.
      **Amended (review):** the chains are taken only from escrows the Alkahest
      clauses built, and the seller wallet is read as an address string or as a
      wallet carrying `address` (mapping or object), as the kit's preflight reads it.
- [x] 6.5 Tests. `kit/alkahest/tests/unit/test_release_conditions.py` (new, unit): each
      model's condition per chain, the oracle-gated wallet-as-oracle refusal, the
      mutual-exclusion refusal, and the undeclared-model refusal. VM's
      `tests/unit/test_heartbeat_gated_listings.py` moves its derivation cases to the kit
      and keeps the composition cases. Bare metal (application integration, through the
      typed client): `tests/test_publication_cycle.py` — a listing with an Alkahest option
      advertises the recipient arbiter paying the seller wallet on its chain;
      `tests/test_app_composition.py` — startup refuses `interruptible`.
      Done. Kit (unit, `make -C kit test-alkahest`: 222 passed, 19 of them
      `test_release_conditions.py`): each model's condition per chain (recipient with
      and without a section, oracle-gated naming the first oracle, interruptible with an
      explicit refund authority and falling back to the wallet), one condition per chain
      in order, no chain deriving nothing, an unconfigured chain refused, the oracle-less
      and wallet-as-oracle refusals, the mutual-exclusion refusal through all three
      entry points, each section's model, a declared model returned, an undeclared model
      refused by name, an unknown declared model refused, and publication deriving per
      Alkahest clause chain and nothing for a non-Alkahest clause. Arbiters come from
      address books the tests write, so no SDK default is assumed. VM:
      `test_heartbeat_gated_listings.py` loses its seven derivation cases to the kit and
      keeps the listing-marking and plan cases; application integration, through the
      typed client, `tests/integration/test_publication_loop.py` gains
      `test_an_alkahest_listing_advertises_the_recipient_arbiter_paying_the_seller`, a
      backed pool published by the loop advertising the recipient arbiter from the anvil
      address book paying the configured wallet (`tests/publication_app.py`'s wallet
      constant becomes the public `SELLER_WALLET`). Three unit files that construct
      `VmAlkahestSellerStage` pass `release_models`. Bare metal:
      `tests/test_publication_cycle.py` gains
      `test_an_alkahest_listing_advertises_the_recipient_arbiter_paying_the_seller`,
      which runs the cycle with the real `publication_payload_builder` over a runtime
      holding the real Alkahest composition and option builder (the token's metadata
      cached under a temporary `XDG_CACHE_HOME`, so no chain is asked) and reads the
      registry body's `demands`; with the derivation replaced by `()` it fails.
      That file is the cycle's public API against a real database with site and
      registry doubles, which its own docstring says is not application integration.
      **Corrected (review):** the claim first recorded here, that no typed-client route
      reached a payload's terms more directly, was wrong. Application integration,
      through the typed client: `tests/test_http_publication_settlement.py` runs the real
      app and lifespan with the real settlement composition and option builder, steps
      publication through `StorefrontClient.admin_run_lifecycle_cycle("publication")`
      with `publication_payload_builder` composing the payload, and reads the listing a
      buyer fetches with `get_listing`: it advertises the recipient arbiter paying the
      seller wallet; it fails with the derivation replaced by `()`. The cycle-level case
      stays, sharing `alkahest_publication` and `RECIPIENT_CONDITION` from
      `test_publication_cycle.py`.
      `tests/test_app_composition.py` (application startup): the app's lifespan, given a
      runtime factory composing an interruptible section, refuses with
      `ReleaseModelError` naming the model and installs no storefront.
      `test_an_oracle_gated_section_composes` builds the runtime only (composition, not
      startup). `tests/test_runtime_environment.py`: the environment path
      refuses `interruptible`, enabled or disabled, naming the model rather than calling
      the root malformed. `tests/settlement_compositions.py`'s `alkahest_composition`
      takes `section` and `chains` overrides. VM (application integration, real app and
      lifespan): `tests/integration/test_release_model_startup.py` — a section stating
      both the oracle-gated and the interruptible model, enabled or not, refuses startup
      with `ReleaseModelError` with no database client created, no database file written,
      and no loop started. **Corrected (re-review):** it first asserted the container's
      client, which is set only after the build; with the signer's credential supplied it
      now fails when the early `require_vm_release_model(domain)` call is removed.
- [x] 6.6 Bump versions and refresh locks. Validation: `make -C kit test-alkahest`,
      `make test-storefront`, `make test-bare-metal`, `make check-architecture`,
      `make check-packaging`, `make test`. End-to-end: `e2e_deal`, `e2e_non_erc20_settlement`
      (VM lane), and `e2e_bare_metal_mock_deal` (bare-metal lane, whose listing now
      advertises its condition).
      Done: `arkhai-kit-alkahest` 0.5.0; VM's storefront raises its floor to `>=0.5.0`
      and bare metal's states it, both importing the new module. `make lock` relocked
      every project but the three PyTorch-index ones (refused here, as in 2.6). Two of
      those lock the kit: VM storefront's lock was edited by hand with the version,
      wheel-name, and specifier substitutions uv wrote into bare metal's lock for the same
      package (three edits), and VM buyer's with the version and wheel name (two);
      `kit/policy` does not lock it (16.6 relocks both). Evidence: `make -C kit
      test-alkahest` (unit) 222 passed; VM storefront in its frozen environment with the
      rebuilt kit reinstalled, unit 1024 passed, 1 skipped (seven fewer: the derivation
      cases moved to the kit) and integration 412 passed (one new; `test_alkahest`
      against Anvil included); `make test-bare-metal` 134 + 316 + 11 + 40 passed (five
      new); VM buyer (frozen) 197 passed; `kit/policy` (frozen) 63 passed. `make -k test`:
      56 pytest runs and every non-Python suite passed, `test-deployment-packaging` and
      the Helm render checks included; it stopped only at the reinit of the three
      PyTorch-index projects, run frozen above. `make check-packaging` (architecture
      rules included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), and `openspec validate
      --strict` pass. The pipeline was not run for this section.
      **Review fixes, re-run:** VM storefront (frozen) unit 1024 passed, 1 skipped,
      integration 414 passed (two new startup cases); bare metal 134 + 317 + 11 + 40
      passed (the application-integration case new); `make test-apicredits` all passed,
      storefront 143; `make -k test` passed everywhere but the three PyTorch-index reinits;
      `make check-packaging`, `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state`, and `openspec validate --strict` pass.
      **Correction (end-to-end):** every VM-lane scenario whose storefront publishes
      through its loop derives its listings' `demands` through the kit now, and every VM
      startup runs the release-model check: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
      `e2e_non_erc20_settlement`, `multi_registry`, `e2e_listing_shapes`,
      `e2e_compute_dynamic_listings`, `e2e_pool_declared_modes`, `e2e_vm_introduction`.
      In the bare-metal lane, `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      and `e2e_bare_metal_introduction` publish listings that now advertise the
      recipient arbiter from the lane's anvil address book paying the lane's seller
      wallet. The mock deal's opening names the zero escrow address and no demand, so
      `escrow_shape_guard` still skips it (Section 7 changes that) and materialization
      still falls back to the recipient arbiter for the seller wallet, which is the
      advertised condition and the one the scenario's escrow is created under, so the
      deal itself is unchanged.
- [x] 6.7 The API-credit storefront: its Alkahest seller stage declares `{recipient}`, its
      composition refuses any other configured model at startup, and its listings publish
      the kit-derived conditions for the chains of the Alkahest escrows they publish.
      **Plan gap (review):** the plan named VM and bare metal only, though D14d covers every
      domain composing Alkahest, and the API-credit storefront composes it with
      `escrow_shape_guard` among its default seller policies, so Section 7's fail-closed
      rules would otherwise refuse every API-credit Alkahest deal.
      Done: `src/settlement_stages.py`'s `AlkahestSellerStage` takes a required
      `release_models`; `src/settlement_composition.py` declares `{RECIPIENT_RELEASE}` (a
      credit grant judges no oracle's verdict and splits no refund), refuses another
      configured model, enabled or not, before building anything, and gains
      `ApiCreditsSettlementComposition.release_conditions(accepted_escrows)` over the kit's
      `release_conditions`, with the composition holding `seller_wallet_address` from
      `[wallet].address` (the mechanism resources carry no wallet, and adding one would
      change Alkahest's readiness inputs); `services/listing_service.py` publishes those
      conditions as the listing's `demands` for the accepted escrows that survive the
      backing filter — the caller's and the clauses' alike, accepted escrows being the
      API-credit Alkahest publication form. `pyproject.toml` requires
      `arkhai-kit-alkahest>=0.5.0`; its lock relocked. The lane's `storefront.credits.toml`
      names the anvil chain's address book and `[wallet].address`, so its seeded listing
      advertises the recipient arbiter paying that wallet. The API-credit buyer builds its
      proposal from the listing with `escrow_proposal_from_accepted_entry`, which now
      selects that demand; materialization then encodes the recipient arbiter for the seller
      wallet, the same condition its fallback used before. **Corrected (re-review):** the
      buyer suites passing was not evidence of that when first recorded, since no buyer test
      then carried a demand. The evidence is code reading, Section 7's
      `domains/apicredits/buyer/tests/test_negotiate_cli.py` Alkahest case (its listing
      advertises a condition, which the buyer's settlement stage selects through
      `escrow_proposal_from_accepted_entry`), and the pending `e2e_credits_deal` run for
      `market credits buy`, which no test covers.
      **Behaviour changes:** a caller-supplied escrow on a chain the storefront does not
      configure now refuses `publish_from_quota` with "accepted escrow names chain …,
      which this storefront does not configure under [chains]" (before, it published an
      escrow nothing could settle). With `[wallet].address` unset, a listing still derives
      and publishes a recipient condition with no recipient, consistent with Section 7:
      materialization refuses every deal under it as `release_condition_unreadable`.
      **Amended (re-review):** the release-model check is
      `require_api_credit_release_model`, which `_build_api_credit_services` calls first,
      before the signer, administrators, registry trust, Alkahest clients, or database, as
      well as the composition. The publish-from-quota route gains a typed client:
      `src/listing_publication.py` holds the route's request and response models (moved
      from the controller), its path and operation, `seller_resource` (which the seller
      authentication middleware now uses too), and `ApiCreditListingClient` and
      `SyncApiCreditListingClient` over the core client's `authenticated_request`.
      Tests, application integration through the typed client, the real app and lifespan:
      `tests/integration/test_alkahest_release_conditions.py` — the seller publishes from
      quota through `ApiCreditListingClient` into the listing service startup composed,
      and a buyer's `StorefrontClient.get_listing` reads the recipient arbiter from the
      anvil address book paying the configured wallet (it fails with the demands left
      empty); and startup refuses `interruptible`, enabled or disabled, naming it, with no
      database client created and no database file written (both fail with the early check
      removed). The test keeps two existing seams, patched as the suite's other tests patch
      them: `capacity_client.build_capacity_runtime` (the quota site) and the server's
      `_startup_tasks` (credits preflight and timer loops); removing them would need the
      listing service to take its capacity runtime by injection, a larger refactor. Unit:
      `tests/unit/test_listing_publication_client.py` — the sync and async clients share
      their methods and sign the same seller request. `test_publish_reconcile.py`'s
      composition double returns no conditions; `tests/unit/test_settlement_fulfillment.py`
      constructs the stage with its models.
      `make test-apicredits`: storefront 143 passed, and every other API-credit suite
      (buyer, domain, service, middleware) passed. End-to-end (API-credit lane):
      `e2e_credits_deal` (its seeded listing now advertises the condition, and its buyer
      selects it); `e2e_credits_payment_deal` publishes no Alkahest escrow. The pipeline
      was not run.

Section 6 handoff:

- Every published Alkahest option now comes with a listing `demands` entry for its chain
  in both domains, derived by `market_alkahest.release_conditions`; Section 7 can treat a
  listing without one for the proposal's chain as unauthorized. Bare metal derives only
  for Alkahest options actually built; VM derives from its clauses whatever the
  mechanism's readiness, as it did before, so a VM listing may advertise a condition for
  a chain whose option readiness suppressed.
- The kit does not refuse an empty seller wallet: a recipient condition would carry
  `recipient: ""`. VM's output for such a configuration is therefore unchanged; bare metal
  never reaches it (its runtime requires the EVM address with any Alkahest section, and
  its derivation runs only for a built option). Section 7's "a missing or invalid
  advertised condition fails closed" is where to decide whether that is invalid.
- Bare metal's `_release_conditions` reads `resources["wallet"]` as the seller address
  string and `resources["chains"]` as a mapping of chain name to a mapping carrying
  `alkahest_address_config_path`. Section 11, moving settlement and chains to
  `[Settlement]`, `[Wallet]`, and `[Chains.<name>]`, must keep those shapes or adapt it;
  the kit accepts chain objects as well.
- For the owner, undecided: every storefront still starts and then refuses every Alkahest
  candidate when `oracle_gated` names no trusted oracle or its oracle is the seller wallet.
  These could be startup refusals too, as the release model is; the wallet check needs the
  wallet at composition, which each storefront has there.
- `tests/settlement_compositions.py`'s `alkahest_composition` takes `section` and `chains`
  overrides; its default section's `address_config_path` names a file absent outside the
  image, which blocks Alkahest readiness, so a test that needs a built Alkahest option
  passes `section={"address_config_path": None}` and a chain with an address book, as
  `test_publication_cycle.py`'s new case does (with the token's metadata cached under a
  temporary `XDG_CACHE_HOME` and a chain ID no other test uses).

## 7. The release-condition invariant holds without seller policy

Delivers correction 9's fix: plan materialization uses exactly the authorized condition and
fails closed, and the escrow-shape guard fails closed (D14d; `negotiation-protocol` "An
Alkahest obligation uses exactly the release condition its listing authorizes"). Touches
`kit/alkahest`, `kit/policy`, and both domains' tests.

- [x] 7.1 Reproduce first: write these tests and run them against the unfixed code before
      7.2, recording the failing run in the task note (the section commits them passing):
      through each domain's seller
      negotiation runtime and plan materialization, a buyer naming the listing's arbiter
      with a substituted recipient, with no escrow-shape guard configured, reaches a
      materialized plan using the buyer's condition; a listing authorizing no condition
      accepts the buyer's; a proposal naming no escrow address skips the guard. VM:
      `tests/integration/test_negotiate_controller.py` (application integration, typed
      client). Bare metal: `tests/test_http_negotiation.py` (application integration,
      typed client). Kit: `kit/alkahest/tests/unit/test_plans.py`.
      Done; run against the unfixed code (the kit at 0.5.0) before any fix, then committed
      passing. Bare metal (application integration, real app through the typed
      `StorefrontClient`, real plan builder over the anvil address book):
      `tests/test_http_negotiation.py` gains four cases. Unfixed, 3 failed, 1 passed: a
      substituted recipient under the chain `listed_price` (no shape guard) was accepted
      with a plan whose demand paid the buyer's recipient; a listing advertising no
      condition, under the default chain, was accepted paying the buyer's recipient; an
      unpinned (zero-address) proposal, whose shape check the default guard skips, was
      accepted paying the buyer's recipient. That is correction 9 reproduced. The fourth,
      an unpinned opening naming no condition (the lane's opening), passed: it settled under
      the seller wallet's recipient condition, through the fallback. VM (application
      integration, typed client): `tests/integration/test_negotiate_controller.py` gains
      `TestReleaseConditionAuthorization`'s four cases. **Differed:** VM prepends the shape
      guard to every configured chain, so "no guard configured" is a seller-round hook
      injected into the fixture's runtime that accepts whatever is proposed. Unfixed, 3
      failed, 1 passed, and VM never used the buyer's condition: its Alkahest stage rebuilds
      the escrow from the listing entry, so a substituted recipient beside a selection was
      accepted and silently replaced by the listing's condition; a listing advertising none
      was accepted under the recipient fallback paying the seller wallet; an unpinned
      proposal naming a substituted condition, under the default chain, was accepted under
      the listing's. Each should have refused (spec: a selection the listing does not
      authorize rejects the round; a listing authorizing none fails closed). Kit (unit):
      `test_plans.py` gains five cases over the existing API; unfixed, 4 failed and 1 (the
      selected condition winning over an `arbiter` literal) passed: a proposal selecting no
      condition was materialized under the recipient fallback, including to a recipient
      named in its literal fields; an `arbiter`/`demand` stated among its literal fields
      was materialized as its condition; `escrow_proposal_from_accepted_entry` built a
      proposal with no condition for a listing advertising none, or only on another chain;
      `accepted_escrow_artifacts_from_proposal` recorded the failure beside artifacts with
      no plan instead of refusing. A sixth (an empty recipient refuses) was added after the
      fix. The substituted-recipient check at kit level needs the new authorization entry
      point, so it is in 7.4's `test_release_authorization.py`.
- [x] 7.2 `kit/alkahest/src/market_alkahest/alkahest.py`
      (`materialize_escrow_terms_from_proposal`) and `proposals.py`
      (`escrow_proposal_from_accepted_entry`, `validate_selected_escrow_plan`,
      `accepted_escrow_artifacts_from_proposal`): a selected condition must equal one the
      listing authorizes for its chain, arbiter and demand data both; with no selection
      the listing's authorized condition is used; a missing or unreadable authorized
      condition refuses before any obligation is accepted; the recipient-arbiter fallback
      to the buyer's recipient goes. The domains' plan builders
      (`domains/bare_metal/storefront/src/settlement.py`, VM's settlement stages) reach it
      unchanged in signature.
      Done, `arkhai-kit-alkahest` 0.6.0. `alkahest.py`: `ReleaseConditionError` (a
      `ValueError`, message `release_condition_<reason>: …`) and `encode_release_condition`,
      which encodes a condition's arbiter and demand data through the codec its arbiter's
      address resolves to on the chain; `materialize_escrow_terms_from_proposal` takes the
      obligation's `arbiter` and `demand` from the proposal's selected condition only,
      refusing none (`_unselected`), several (`_ambiguous`), or one it cannot encode
      (`_unreadable`); the recipient fallback and the `arbiter`/`demand`-literal path go, and
      `seller_wallet_address` is no longer read (kept in the signature). `proposals.py`:
      `authorized_release_conditions(listing, chain_name=…)` reads the listing's `demands`
      (list or JSON text, chain-scoped or unscoped) and refuses none on the chain
      (`_not_advertised`) or an unreadable entry (`_unreadable`);
      `authorized_release_condition(listing, chain_name=…, selected=…)` returns the
      listing's form of a selected condition equal in arbiter and demand data (hex compared
      case-insensitively), else refuses (`_not_authorized`), or the first authorized one
      with no selection; `selected_release_condition(proposal)`;
      `authorize_escrow_proposal(proposal, listing=…)` returns the proposal under exactly
      that condition, whatever its escrow address; `escrow_proposal_from_accepted_entry`
      gains `demand=` and builds under the authorized condition, so a buyer building against
      a listing advertising none now fails there too; `validate_selected_escrow_plan` gains
      `addr_config_path` and compares the plan's demand bytes as well as its arbiter;
      `accepted_escrow_artifacts_from_proposal` raises `ReleaseConditionError` instead of
      recording it. **Differed:** the plan builders keep their signatures by receiving an
      already-authorized proposal: each domain authorizes where its seller accepts, outside
      its policy chain. VM's Alkahest seller stage passes the buyer's selected condition to
      `escrow_proposal_from_accepted_entry`, and the runtime turns the refusal into the
      round's 409. Bare metal authorizes the escrow carrier at the opening (after the policy
      decides to counter or accept), so the thread pins the authorized proposal its
      settlement verification re-materializes, and again in `build_artifacts` before the
      plan builder; the Agreement's option and `accepted_escrow_proposal` carry it. The
      API-credit storefront (not named by the plan, but it materializes buyers' escrow
      carriers the same way) authorizes in `build_api_credit_accepted_artifacts` and on its
      settle path before verification, which now passes the listing. VM's refund
      (`failure_actions.py`) reads the accepted escrow proposal, since the buyer's opening
      may name no condition (**amended (review):** only the accepted one; it and settlement
      no longer fall back to the buyer's opening). The VM buyer's plan check reads the
      selected chain's address book from its `[chains.<name>]`. The empty-wallet question
      (Section 6's handoff) is settled by the fail-closed rule: a recipient condition with
      an empty recipient cannot be encoded, so it refuses as `_unreadable`; derivation and
      publication still emit it (recorded in `design.md` D14d as delivered, with the owner
      question of refusing it at startup). **Amended (7.6):** the owner moved the
      authorization inside the kit's materialization; the plan builders now take the listing
      and the domains' call-site authorization is gone, except bare metal's at the opening.
- [x] 7.3 `kit/policy/src/market_policy/scalar_policies.py`'s `escrow_shape_guard` (and
      `accept_exact_listing`'s same pattern): a listing advertising no condition for the
      proposal's chain rejects with its own reason instead of skipping the check.
      Done: `escrow_shape_guard` rejects `release_condition_not_advertised: …` and
      `accept_exact_listing` `exact_listing:release_condition_not_advertised`. The guard
      still passes a proposal carrying no escrow address or the zero placeholder, and a
      listing accepting no escrow, so the status probes' zero-address proposal still
      decides; `accept_exact_listing` rejects those as
      `exact_listing:escrow_not_in_accepted_set`, unchanged. **Corrected (review):** this
      note first said both policies pass them. The
      package keeps version 0.4.0: `kit/negotiation-runtime` pins it exactly, and no
      consumer needs a new name from it; its rebuilt wheel reaches every environment through
      reinit.
- [x] 7.4 Tests. The 7.1 reproductions now refuse, with no obligation accepted.
      `kit/policy/tests/unit/test_escrow_shape_guard.py` (new, unit): the guard's
      fail-closed and matching cases. VM's `tests/unit/test_escrow_fields_policy.py` and
      bare metal's `tests/test_negotiation.py` updated where they relied on the skip.
      Done. The seven reproductions (three VM, three bare metal, the kit's) refuse with a
      `release_condition_*` 409 and no thread recording an Agreement or plan; the positive
      cases settle under the listing's condition. Kit (unit): `test_release_authorization.py`
      (new, 20 cases): no selection takes the listing's condition, a case-differing
      selection is kept in the listing's form, a substituted recipient, arbiter, or demand
      data is refused, an unpinned escrow is held all the same, no condition on the chain
      (absent, null, empty, another chain only) and seven unreadable forms refuse, JSON and
      unscoped demands are read, two selected conditions are refused, and
      `escrow_proposal_from_accepted_entry` under its `demand=`.
      `test_selected_escrow_plan.py`: a substituted demand and a listing with no, another
      chain's, or an unreadable condition are refused. `test_escrow_kind_codec.py`'s four
      amount cases select a condition instead of stating arbiter literals. Policy (unit):
      `kit/policy/tests/unit/test_escrow_shape_guard.py` (new, 17 cases). VM:
      `test_escrow_fields_policy.py`'s listings advertise a condition their proposals
      select, plus both policies' fail-closed cases; `test_negotiate_controller.py`'s
      seeded listings authorize the configured wallet's condition and its pinned openings
      select it; `test_sync_negotiation_seller_round_hook.py` and
      `test_buyer_selection_negotiation.py` (the buyer's configured chain names the address
      book) likewise. Bare metal: `test_negotiation.py` (and a new default-chain refusal of
      a listing advertising none), `test_http_negotiation.py`, `test_http_settlement.py`,
      and `test_negotiation_runtime.py`, whose builder is shown receiving the listing's form
      of the condition. API credits (the negotiation runtime called directly over a real
      database, with no application; **corrected (review)** from "application
      integration"): `test_sync_negotiation.py` gains the refusal of a substituted recipient and
      of a listing advertising none under a seller hook accepting anything; its seeded
      listing, the shared proposal, `test_settlement_fulfillment.py`, and the unit
      artifacts tests carry a condition; the API-credit buyer's `test_negotiate_cli.py`
      listing advertises one.
- [x] 7.5 Bump versions and refresh locks. Validation: `make -C kit test-alkahest
      test-policy`, `make test-storefront`, `make test-bare-metal`, `make test-vms-buyer`
      (the buyer's `validate_selected_escrow_plan` caller), `make check-architecture`,
      `make check-packaging`, `make test-apicredits` (the API-credit storefront composes
      Alkahest and runs `escrow_shape_guard` by default), `make test`. End-to-end:
      `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_non_erc20_settlement`,
      `e2e_bare_metal_mock_deal`, and the API-credit lane's `e2e_credits_deal` and
      `e2e_credits_payment_deal`.
      Done. `arkhai-kit-alkahest` 0.6.0; the VM, bare-metal, and API-credit storefronts and
      the VM buyer require `>=0.6.0` (they use its new names). `arkhai-kit-policy` keeps
      0.4.0 (7.3). `make lock` relocked every project but the three PyTorch-index ones; VM
      storefront's and VM buyer's locks were edited by hand with the version, wheel-name,
      and specifier substitutions uv wrote into bare metal's lock for the same package
      (three edits each; the VM buyer's specifier is new, matching its new floor);
      `kit/policy` locks no alkahest. Evidence: `make -k test` ran every pytest suite and
      every non-Python suite (Helm render checks, deployment packaging, the middleware
      ports) and passed; it stopped only at the reinit of the three PyTorch-index
      projects, run frozen with the rebuilt wheels reinstalled: `kit/policy` 80 passed
      (unit), VM buyer 197 passed (unit), VM storefront unit 1026 passed, 1 skipped, and
      integration 418 passed (application integration; `test_alkahest` against Anvil
      included). Within `make -k test`: `kit/alkahest` 252 passed (unit; `make -k test` counted 251 because it ran before the empty-recipient case was added), bare metal
      134 + 322 + 11 + 40 passed (domain, storefront, buyer, adapter), and
      `make test-apicredits`'s suites all passed (domain 41, service 72, storefront 146,
      buyer 24, sample app 1, middleware 8). `make check-packaging` (architecture rules
      included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), and `openspec validate
      --strict` pass. The pipeline was not run for this section.
      **Review fixes, re-run:** `kit/alkahest` 252 passed (unit); `kit/policy` (frozen) 80;
      VM buyer (frozen) 199 (two new); VM storefront (frozen) unit 1028 passed, 1 skipped
      (two new), integration 418; `make test-bare-metal` 134 + 323 + 11 + 40 (one new);
      `make test-apicredits` all passed (storefront 149); `make check-packaging`,
      `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state`, and `openspec validate --strict` pass.
- [x] 7.6 The release-condition invariant is enforced inside `kit/alkahest`, so no caller can
      skip it (owner decision, 2026-10-16; recorded in `design.md` D14d, with the rejected
      alternative of authorization at each storefront's acceptance boundary). Every kit entry
      point that encodes an obligation's release condition from a proposal takes the listing
      and authorizes the condition itself: a selection must equal a condition the listing
      authorizes for the chain (arbiter and demand data), no selection takes the listing's,
      and a missing or unreadable authorized condition refuses before anything is accepted.
      No public kit entry point encodes a condition from a proposal without authorizing it.
      The plan
      builders' signatures change; every caller in VM, bare metal, the API-credit storefront,
      the VM and API-credit buyers, and the core buyer's orchestration moves to the new shape,
      and the call-site authorization the kit now does goes. Every Section 7 refusal reason,
      HTTP status, and test holds. Bump `arkhai-kit-alkahest` (minor, incompatible API) and
      raise every consumer's floor.
      Done, `arkhai-kit-alkahest` 0.7.0. Kit: `market_alkahest/release_authorization.py`
      (new) holds `ReleaseConditionError` and the reading of what a listing authorizes
      (`authorized_release_conditions`, `authorized_release_condition`,
      `selected_release_condition`), moved from `proposals.py`, which re-exports them, so
      `alkahest.py` can authorize without importing `proposals.py`. In `alkahest.py`,
      encoding one condition is private (`_encode_release_condition`) behind
      `encode_authorized_release_condition(listing, *, chain_name, selected, config_path)`;
      `materialize_escrow_terms_from_proposal` and its payload form,
      `plans.materialize_settlement_plan_from_proposal` and
      `settlement_plan_payload_from_proposal`, and
      `proposals.accepted_escrow_artifacts_from_proposal` take a required `listing` and drop
      `seller_wallet_address` (unread since 7.2); materialization authorizes before it builds
      any obligation data; `accepted_escrow_artifacts_from_proposal` authorizes first, so the
      recorded accepted proposal carries the listing's form; `verify_escrow_for_settlement`
      materializes its expected obligation against the listing it was already given, so its
      signature is unchanged. **Corrected (review):** `build_payment_obligation_data`, which
      encoded a recipient condition for any wallet (and, through an unused `demands=` branch,
      any caller-named condition), is gone from the public kit: its one caller was
      verification, so it became `escrow_verification._legacy_recipient_obligation_data`
      (recipient branch only). `verify_escrow_for_settlement` with `escrow_proposal=None` —
      the admin dry-run path (`admin_settle_service.py`) and bare metal's admin verify —
      expects a recipient condition paying the seller wallet without consulting the listing;
      its injected `build_obligation_data_fn` and `get_obligation_fn` hooks are test seams
      no production caller passes. `plans.py`'s function-local import of `alkahest` moved to module
      level (no cycle: `alkahest.py` imports neither). **Differed:** with no selection,
      materialization now uses the listing's condition rather than refusing
      `release_condition_unselected`, as the decision requires, so no kit refusal carries that
      reason any more (authorize-then-materialize behaved this way already, so no domain
      result changes). Callers: VM's seller stage binds the listing to its plan builder
      (`functools.partial` over the core build context, which carries no listing, so
      `core/storefront` is unchanged), as its settle path does with the stored listing; VM's
      refund (**corrected (review)**, which first re-materialized against the current listing)
      reads the token and amount of the accepted plan's one obligation on the escrow
      (`thread["settlement_plan"]`) and materializes nothing; bare metal's plan builder and
      `_build_settlement_from_context` take the listing record, `build_artifacts` no longer
      re-authorizes (its opening authorization stays: it pins the condition on the thread and
      refuses an unauthorized selection at the opening, before any acceptance), and
      `seller_wallet_address` leaves its negotiation-runtime builder, which only forwarded it;
      the API-credit storefront's `build_api_credit_accepted_artifacts` takes a required
      `listing` and neither it nor its settle path authorizes at the call site. Buyers: the
      core orchestration's `BuildEscrowTermsFn` takes the selected listing as its second
      argument in place of the seller wallet (**corrected (review):** `arkhai-core-buyer`
      0.5.0, every consumer moved, bare metal's exact pin to `==0.5.0`; `arkhai-vms-settlement`
      0.3.0, since it re-exports `accepted_escrow_artifacts_from_proposal`, the VM storefront
      and VM buyer requiring `>=0.3.0`), and each domain's `make_buyer_payment_escrow_terms_fn` closure passes it to the kit.
      **Differed (judgement):** the three resume paths (VM `escrow create`, VM settle resume,
      API-credit settle) materialized a run-log's accepted proposal when no accepted escrow
      terms were recorded; a run-log records no listing, so they now refuse by name (exit 3,
      `escrow_release_condition_missing`) through `resumed_proposal_refusal`, which keeps
      `release_condition_unselected` for a proposal naming no condition. A run-log written
      from a seller response carrying its plan is unaffected; recording the listing's
      conditions in the run-log would restore the path and is not done. Floors: every
      project declaring `arkhai-kit-alkahest` requires `>=0.7.0` (kit/storefront, VM
      settlement, listings, negotiation, buyer, storefront, bare-metal buyer and storefront,
      API-credit domain, buyer, storefront, e2e-tests). `make lock` relocked every project but
      the three PyTorch-index ones; the VM storefront's and VM buyer's locks were edited by
      hand with the three substitutions uv wrote into bare metal's lock (version, wheel name,
      root specifier); `kit/policy` locks no alkahest.
      Tests: kit (unit) `test_release_authorization.py` gains 41 cases calling each
      materializer directly (escrow terms and payload, plan and payload, accepted artifacts):
      a substituted recipient or arbiter, a listing authorizing none or another chain's only,
      and unreadable demands refuse with their `release_condition_*` reason; with no
      selection or a case-differing one each encodes the listing's condition; none can be
      called without `listing`; and settlement verification refuses a condition its listing
      does not authorize without reading the chain. Call shapes adapted, assertions kept:
      kit `test_plans.py` (its two no-selection cases now show the listing's condition is
      materialized, never the buyer's recipient or a literal arbiter — the decision's
      semantics, not a weakened check), `test_escrow_kind_codec.py`,
      `test_native_escrow_verification.py`; VM storefront `test_heartbeat_gated_listings.py`,
      `test_escrow_verification.py` (its fixture listing advertises the seller's condition),
      `test_settlement_composition.py`, `test_failure_policy.py`; VM buyer
      `test_escrow_client_dispatch.py`, `test_buy_orchestrator.py` (the builder receives the
      matched listing; its `test_escrow_client_dispatch.py` no longer stubs the removed
      builder), and two stubs' parameter names; bare metal `test_settlement.py`,
      `test_domain_runtime.py`, `test_negotiation_runtime.py` (the builder plans against the
      listing record); API credits `test_sync_negotiation.py` (unit: the listing is handed to
      the kit). **Review fixes, tests:** kit `test_plans.py`'s unmaterializable-artifacts case
      now gives an authorized condition that cannot be encoded, so it is refused inside
      materialization, not in authorization; `test_arbiter_codec.py` tests the moved legacy
      builder; VM storefront `test_failure_policy.py` refunds from a thread row carrying the
      accepted plan as the database returns it, with no materialization patched, and refuses
      (`escrow_refund_context_invalid`) a plan naming another escrow; VM buyer
      `test_release_condition_refusals.py` shows `escrow create` and the settle resume refuse a
      run-log whose accepted proposal names no condition and one that selects a condition;
      API-credit buyer `test_settle_credentials.py` shows `settle` refuses both, with no escrow
      created.
      Evidence: `make -C kit test-alkahest` 293 passed (unit; 252 before); `kit/policy`
      (frozen) 80 passed (unit); VM storefront (frozen) unit 1028 passed, 1 skipped, and
      integration 418 passed (application integration, typed client; the Section 7
      reproductions refuse with their 409s); VM buyer (frozen) 199 passed (unit);
      `make test-bare-metal` 134 + 323 + 11 + 40 passed (domain, storefront, buyer, adapter;
      the storefront's `test_http_negotiation.py` application-integration reproductions
      included); `make test-apicredits` all passed (domain 41, service 72, storefront 149,
      buyer 24, sample app 1, middleware 8); `make -k test` ran every other pytest and
      non-Python suite and passed, stopping only at the reinit of the three PyTorch-index
      projects (run frozen above); a kit edit landed while it ran, so every suite that
      installs `arkhai-kit-alkahest` was rerun on the final wheels, with the counts above.
      `make check-packaging`
      (architecture rules included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state`, and `openspec validate --strict` pass. End-to-end:
      as for 7.5, read again: `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
      `e2e_non_erc20_settlement`, `e2e_bare_metal_mock_deal`, `e2e_credits_deal` settle under
      the listing's condition, now materialized and verified against the listing; their
      buyers create escrows from the seller's accepted terms, so none reaches the resume
      refusal. The pipeline was not run.
      **Review fixes, re-run:** `make -C kit test-alkahest` 293 passed (unit); core buyer 134
      (unit); VM storefront (frozen) unit 1029 passed, 1 skipped (one new), integration 418;
      VM buyer (frozen) 202 (three new); `make test-bare-metal` 134 + 323 + 11 + 40;
      `make test-apicredits` all passed (buyer 26, two new); `make lock` (the VM storefront's
      and VM buyer's locks hand-edited for both bumped packages as before), `make
      check-packaging`, `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state`, and `openspec validate --strict` pass.
- [x] 7.7 **(04 F1)** An exact settlement selection of a mechanism the composed registry
      builds no accepted obligation for is accepted without a settlement plan only when
      that mechanism settles from the accepted Agreement alone (Arkhai payments). Any other
      — Alkahest, whose registration has no obligation builder — is refused with a named
      4xx reason before anything is recorded, in all three storefronts; contact exchange
      (it has a builder) and payments keep working.
      Done. Each storefront's seller entries declare `settles_from_agreement` (bare metal on
      its `SellerStage` base, defaulting to false; VM's and the API-credit storefront's stages
      share no base, so their runtimes read it with `getattr(..., False)`, a review-round
      correction), so a new builder-less entry fails closed with the named refusal: the
      payment entries say true, the Alkahest and contact entries false. Bare metal:
      `evaluate_exact_selection` refuses a builder-less mechanism whose entry does not settle
      from the Agreement, 409 `settlement_selection_requires_plan: …`, before the listing's
      options or admission are read. API credits: `_accepted_selection_artifacts` refuses it
      with `OfferUnfulfillableError("settlement_selection_requires_plan")` (409); it runs in
      every round's artifact build, so the opening is refused whatever the policy decides.
      VM: its Alkahest entry never reaches the planless branch — it rebuilds the escrow from
      the selected option under the listing's condition and materializes the authorized plan
      (the reviewer's other option, which VM already had) — so VM's instance of the shape is
      the generic branch of `_accepted_selection_artifacts`, which now takes the entry's
      `settles_from_agreement` and refuses the same way. **Differed (reading):** the owner's
      "refusing exact selection on all three storefronts" is carried out as refusing the
      planless acceptance, not VM's exact Alkahest selection: every VM Alkahest opening
      carries a selection (`resolve_proposal_stage` requires one) and VM accepts it only with
      its authorized plan, so refusing it would end VM's Alkahest deals (`e2e_deal`).
      Tests, each run first against the unfixed admission: bare metal (application
      integration, real app through `StorefrontClient`, real plan builder):
      `test_http_negotiation.py::test_an_exact_alkahest_selection_is_refused_with_nothing_accepted`,
      for a listing authorizing its condition and one with no demands — unfixed, both were
      accepted (`DID NOT RAISE`); now 409 named, no thread, no Agreement or plan.
      `test_selection_dispatch.py`'s Agreement-settled entry is now a `PaymentStage`
      (runtime called directly). API credits (application integration: the negotiate router,
      response authentication, and the real runtime over SQLite, through `StorefrontClient`;
      new `tests/integration/test_exact_selection_api.py`): an exact Alkahest selection is
      refused 409 named, for a listing with its condition and one with no demands, and no
      thread is written (unfixed, both accepted); an exact payment selection is accepted with
      its Agreement and mandate and no plan. VM: unit `test_selection_dispatch.py` — the
      generic branch refuses a builder-less mechanism that does not settle from the Agreement
      and accepts one that does; application integration
      `test_negotiate_controller.py::TestReleaseConditionAuthorization` — a selection-only
      Alkahest opening (no escrow carrier) is accepted with the authorized plan, which the
      thread records, and refused 409 `release_condition_not_advertised` with nothing
      recorded for a listing with no demands.
- [x] 7.8 **(04 F2)** Accepted escrow artifacts fail closed on any plan-materialization
      failure, in `kit/alkahest` (owner: "Solve this at the kit layer"), under a refusal of its
      own; `ReleaseConditionError`'s reasons stay as they are. Each storefront refuses the
      round with 409, and the storefronts' handling of a recorded failure goes.
      Done, `arkhai-kit-alkahest` 0.8.0. `accepted_escrow_artifacts_from_proposal` returns
      artifacts for a proposal only with their plan: any failure to materialize it other than
      a release condition raises the new `SettlementPlanMaterializationError` (a
      `ValueError`, message `settlement_plan_unmaterializable: …`, chained to its cause), and
      `accepted_escrow_terms_error` is gone; with no proposal there is no escrow and the
      artifacts are still empty. Non-acceptance callers, checked: the settle paths (VM's
      `prepare_vm_settlement` through its entry's plan builder, the API-credit
      `_prepare_alkahest_settlement`) rebuild the plan and already refused a planless one
      (core's settlement-artifacts check; "has no accepted settlement obligations"), so they
      now refuse earlier, by name. The API-credit storefront's non-accepting rounds called the
      accepted-artifacts builder and returned only its `accepted_escrow_proposal`, so they
      relied on the planless form: they now call the new, separately named
      `authorized_escrow_proposal_at_amount` (the proposal authorized against the listing at
      the round's amount, no plan; raises `ReleaseConditionError`), which the
      accepted-artifacts builder also uses. Storefronts: VM's `build_vm_accepted_artifacts`
      and the API-credit `build_api_credit_accepted_artifacts` lose their pop-and-log; VM's
      `_accepted_settlement_artifacts`, the API-credit `_build_response_artifacts`, and bare
      metal's `build_artifacts` map the new error to the round's 409 beside
      `ReleaseConditionError`; bare metal's `build_bare_metal_settlement_plan` loses its
      recorded-error check and its missing-plan check (an absent plan still fails its plan
      validation). **Found:** VM never accepted planless — the artifacts reached core's
      settlement-artifacts check, which raised, and VM answered 500 — so its change is the
      500 becoming the named 409; the API-credit storefront did accept planless. Floors: the
      VM, bare-metal, and API-credit storefronts require `>=0.8.0` (they import the new
      name); every other declaring project keeps `>=0.7.0`. `make lock` relocked every project
      but the three PyTorch-index ones; the VM storefront's lock was edited by hand with the
      three substitutions uv wrote into bare metal's lock (version, wheel name, root
      specifier) and the VM buyer's with the first two (its floor is unchanged); `kit/policy`
      locks no alkahest.
      Tests: kit (unit) `test_plans.py` — a proposal whose rate the codecs cannot price is
      refused with the named error, chained, and not as a release condition; accepted
      artifacts carry their plan and no error key; `authorized_escrow_proposal_at_amount`
      authorizes without building a plan (the unpriceable rate does not refuse it), keeps a
      non-scalar escrow's amount, and refuses an unauthorized condition. API credits (the
      negotiation runtime called directly over a real database, no application):
      `test_listed_price_accept_persists_terms_without_unfunded_hold` now asserts the real
      plan — the `db` fixture's `anvil_chain()` already names the development address book,
      so the plan was materialized but never asserted, and the "proposal echo" comment was
      stale — its one Alkahest obligation for 300 under the listing's arbiter and demand
      bytes, with the deal's principals, and the plan the thread stores; its companion
      `test_an_escrow_whose_plan_cannot_be_materialized_is_refused` opens with a rate the
      codecs cannot price under the listed-price default and is refused
      `settlement_plan_unmaterializable` with no thread written (against the kit's old
      recording behaviour it was accepted). VM (application integration, typed client):
      `TestReleaseConditionAuthorization::test_an_escrow_whose_plan_cannot_be_materialized_is_refused`
      — the selected option names an unpriceable rate; 409 named, nothing recorded (500
      against the old kit behaviour). Bare metal (unit) `test_settlement.py`: the
      recorded-error case goes.
- [x] 7.9 **(04 F3)** One application-integration test in the provisioning service suite
      composes `market_capacity_publication.SiteProjectionState` over the production
      `SiteCapacityClient` against the in-process provisioning app: the first `poll_once`
      loads both families, a capacity declaration is picked up by the next poll, and an
      authority outage keeps the last generation `stale` with its error.
      Done: `provisioning/compute/service/tests/integration/test_site_projection_state.py`
      (application integration). The state is built over an `AggregateCapacityClient` of one
      `SiteCapacityClient` signing as the storefront and verifying the service's responses;
      only the network is controlled, by a transport that forwards to the app's
      `ASGITransport` until it is cut. After a resource is declared, the first poll loads both
      families, each identity equal to the version document the site serves, the pool family
      holding the declared resource, and publication woken once; a second declaration moves
      both identities, adds the resource, adds one bucketed resource, and wakes publication
      again; with the network cut, the next poll leaves both families `stale` with an error,
      the same identity, rows, and confirmation time, and `status()` reports it. Dev group:
      `arkhai-kit-capacity-publication==0.9.2` (the storefronts' exact pin) and
      **differed:** `arkhai-core-storefront>=0.14.0` beside it, because the test imports
      `core_storefront.aggregation.AggregateCapacityClient` (the state takes only an
      aggregate) and every imported distribution is declared. `make check-architecture`
      does not read the dev group and passes.
      Evidence for 7.7–7.9 and Section 9's follow-up: `make -C kit test-alkahest` 296 passed
      (unit; 293 before); `make test-bare-metal`: domain 134, storefront 324 (two new, one
      removed), buyer 11, adapter 40; `make test-apicredits`: domain 41, service 72,
      storefront 153 (four new), buyer 26, sample app 1, middleware 8; provisioning service
      unit 675 and integration 463 (one new); `make -C kit test-capacity-publication` 94; VM
      storefront (frozen, rebuilt wheels reinstalled) unit 1043 passed, 1 skipped (two new),
      integration 431 (three new) in each of three full runs; VM buyer (frozen) 202;
      `kit/policy` (frozen) 80. `make -k test` passed every suite it ran (e2e unit 650, the
      Helm render and packaging suites among them) and stopped only at the reinit of the
      three PyTorch-index projects, run frozen above. `make lock`, `make check-packaging`
      (architecture rules included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), and `openspec validate
      --strict` pass. No repository typing target exists. End-to-end: no scenario sends an
      exact Alkahest selection to bare metal or the API-credit storefront (their buyers open
      Alkahest deals with escrow proposals; `e2e_credits_payment_deal` selects payments,
      still accepted), and VM's scenarios' selections are accepted with their plans as
      before; no scenario's escrow fails to materialize, so none reaches the new refusals,
      which are application-integration evidence only. The pipeline was not run.

Section 7 notes:

- End-to-end scenarios, read against each scenario's opening: `e2e_deal` (a selection
  beside an unpinned escrow carrier naming no condition, so the listing's recipient
  condition is used, as before); `e2e_deal_buyer_cli` and `e2e_buy` (the `market` buyer
  builds its proposal from the listing's condition and now checks the plan's demand bytes
  through its `[chains.anvil]` address book, which the scenarios' buyer configuration
  names); `e2e_non_erc20_settlement` (its proposals name the listing's recipient condition,
  lowercased, which the case-insensitive comparison accepts). `multi_registry` opens
  without a selection and stops at the seller's counter, so it materializes nothing.
  Bare-metal lane: `e2e_bare_metal_mock_deal`, whose unpinned opening names no condition:
  the opening now pins the listing's recipient condition, the same bytes the scenario's
  escrow is created under, so the deal is unchanged. API-credit lane: `e2e_credits_deal`
  (its buyer selects the listing's condition); `e2e_credits_payment_deal` creates no
  escrow. No scenario sends an unauthorized condition, and none was added: the refusals
  are application-integration evidence only. The pipeline was not run.

Section 7 handoff:

- The authorization lives in `market_alkahest.proposals` (`authorize_escrow_proposal`,
  `authorized_release_condition`, `selected_release_condition`, `ReleaseConditionError`,
  re-exported there from `alkahest.py`), and each domain calls it where its seller
  accepts. A new domain or acceptance path that materializes a buyer's escrow carrier must
  authorize it first; materialization alone refuses a proposal selecting no condition but
  cannot tell a buyer's selection from an authorized one.
  **Superseded (7.6):** materialization authorizes against the listing it now requires
  (`market_alkahest.release_authorization`), so an acceptance path cannot skip the check;
  `authorize_escrow_proposal` remains for a caller that wants the authorized proposal itself,
  as bare metal's opening does.
- Seller verification paths materialize a stored proposal: VM reads only the accepted
  escrow proposal (settlement data), bare metal's thread pins the authorized proposal at
  the opening, and the API-credit settle path authorizes the stored proposal against the
  current listing.
- Materialization failures other than a release condition (an unknown escrow contract,
  say) are still recorded as `accepted_escrow_terms_error`; VM and API credits log them at
  debug and accept with no plan, as before this section. Bare metal refuses them.
  **Superseded (7.8):** the kit raises `SettlementPlanMaterializationError` for them, and
  every storefront refuses the round with 409.
- Review fixes: VM's `accepted_proposal` and its refund no longer fall back to the buyer's
  raw opening when no accepted escrow proposal is recorded — settlement refuses
  ("no persisted accepted escrow proposal") and the refund action fails
  (`accepted_escrow_proposal_unavailable`); unit tests in
  `test_settlement_start_authority.py` and `test_failure_policy.py`. Bare metal's
  `build_artifacts` maps a `ReleaseConditionError` from its plan builder (an authorized
  condition it cannot encode, such as one paying an empty wallet) to the round's 409 rather
  than a 400; `test_http_negotiation.py` covers it, and fails with the 400 without the fix.
- Buyers fail safe. With the recipient fallback gone, a run-log whose accepted proposal
  names no condition, or one recording neither accepted terms nor a proposal, can no
  longer be turned into an escrow; nothing reaches the chain. The VM `escrow create`
  command, the VM settle resume, and the API-credit settle now end with a named refusal
  (exit 3, run-log event `escrow_release_condition_missing`) instead of a traceback;
  `domains/vms/buyer/tests/test_release_condition_refusals.py` covers the VM command's
  no-proposal branch and the settle resume of a proposal naming no condition. The core
  buyer's orchestration already catches the failure and exits its `BuyResult` with
  `build_escrow_terms_failed: release_condition_…`; unchanged. The VM `escrow create`
  command keeps its Alkahest import local beside its others: importing the kit costs the
  CLI about 0.4 s and only that command needs it.
  **Amended (7.6):** the resume paths no longer materialize a run-log's accepted proposal
  at all, since a run-log records no listing to authorize it against; with no accepted
  escrow terms recorded they refuse by name, and the `escrow create` command's local kit
  import went with that branch.
- The API-credit integration tests patch `storefront_config.CHAINS` (`anvil_chain()` in
  `credit_negotiation.py`, entered by the conftest's `db` fixture): the storefront's
  accepted-artifacts builder reads the module's chains and takes no injected chains, so
  there is no seam to use; the patch follows `test_alkahest_release_conditions.py`'s
  pre-existing pattern.
- Open for the owner (no code was changed for these):
  - (a) The invariant is enforced at each domain's acceptance call sites through
    `authorize_escrow_proposal`, with materialization refusing only a proposal selecting no
    condition. Inside kit materialization alone, as D14d first said ("where the plan is
    materialized") and 7.2 implies, it would need the listing passed to the plan builders,
    whose signatures 7.2 kept; a later acceptance path that skips the call is unguarded.
    **Decided (2026-10-16):** the owner chose enforcement inside `kit/alkahest`, the plan
    builders taking the listing; done in 7.6 and recorded in `design.md` D14d.
  - (b) An unpinned proposal (zero escrow address) may name any token; the shape guard
    skips it and authorization does not look at it. Pre-existing and outside correction 9.
  - (c) `kit/policy` and the storefronts changed code without version bumps (only
    `arkhai-kit-alkahest` moved, to 0.6.0), while the release guidance requires SemVer
    bumps for published packages; `kit/negotiation-runtime`'s exact `==0.4.0` pin is why
    `kit/policy` stayed.
    **Amended (7.6):** 7.6 bumped `arkhai-core-buyer` (0.5.0) and `arkhai-vms-settlement`
    (0.3.0) for their incompatible changes, moving every consumer; `kit/policy` and the
    storefronts still have the question.
  - (d) An empty seller wallet still derives and publishes a recipient condition with no
    recipient, which every deal refuses as `release_condition_unreadable`, rather than
    refusing at startup (beside Section 6's oracle-gated question).
  - (e) The API-credit settle path re-authorizes the stored proposal against the listing as
    it is at settle, not as accepted: a listing whose condition changed in between refuses
    settlement (fail-closed), and the API-credit storefront rebuilds its plan at settle from
    current configuration, as before.
- `escrow_verification.verify_escrow_for_settlement` still computes an
  `effective_recipient` from the proposal; it now reaches only its injected
  `build_obligation_data_fn` test seam and the legacy no-proposal path, not
  materialization. Left as it is.
- Section 17's promotion should carry D14d's "As delivered (Section 7)" paragraph to the
  negotiation-protocol requirement's explanation (its spec is written by the archive) and
  name `market_alkahest.proposals` as the place the invariant is held.
  **Amended (7.6):** name the kit's materialization (`market_alkahest.release_authorization`,
  read by every materializing entry point) as the place the invariant is held.
- (7.6) Open for the owner:
  - (f) Seller verification and bare metal's acceptance re-materialize against the listing as
    stored when they run, so a listing whose conditions changed after acceptance fails them
    closed — (e) widened to every domain. VM's refund does not: it reads the token and amount
    from the accepted plan, so a changed or deleted listing no longer blocks it.
  - (g) A resumed buyer run holding only an accepted proposal now refuses, while one holding
    the seller's accepted escrow terms creates the escrow from them unchecked. Recording the
    listing's demands in the run-log would let both be checked against the listing, and is
    the better fix.
  - (h) Settled in 7.6's review fixes: `arkhai-core-buyer` 0.5.0 and `arkhai-vms-settlement`
    0.3.0, beside (c).
  - (i) The buyer checks the seller's echoed terms against the listing only on the VM
    selection path (`validate_selected_escrow_plan`); core orchestration creates the escrow
    from `accepted_escrow_terms` unchecked for the API-credit buyer and VM's proposal path.
    Should the buyer verify them against the listing on every path? That needs a domain hook,
    since `core/buyer` cannot import `kit/alkahest`. Not implemented.

## 8. VM composes the shared projection state

Delivers VM on one injected `SiteProjectionState` (D2, D3, D4, C2, C7; corrections 3 and 7;
`storefront-publication` "Projection-backed listing candidate derivation"). Touches VM's
storefront only. The largest section by file count: about ten production modules and
fifteen test files, mechanically.

- [x] 8.1 Composition: `src/server.py` builds the state once over the capacity runtime's
      aggregate client, with `wake_publication_loop` as `on_resource_pool_change`;
      `src/container.py` holds it; `src/startup.py`'s `_load_site_projections` calls
      `poll_once()`. The poller registers as the `site_projection_poller` loop on the
      controller with `register_loop`, interval `[capacity].poll_interval`, replacing
      `site_projection_poller_loop`.
      Done. `_build_vm_services` builds `SiteProjectionState(capacity_runtime.client(),
      on_resource_pool_change=wake_publication_loop)` after the capacity runtime and
      before every consumer; `VmStorefrontServices.site_projections` carries it and
      `_start_vm_services` sets `container.resolved_site_projections`, which
      `clear_lifespan_state` clears (`container.site_projections()` is the accessor, raising
      when nothing is composed). `startup._load_site_projections` runs `poll_once()`.
      **Differed:** the poller registers in `lifecycle_steps.register_vm_lifecycle_steps`,
      at import, as `register_loop(SITE_PROJECTION_POLLER, route="site-projections",
      step=site_projections_step, interval_seconds=[capacity].poll_interval)`, not in
      `startup.py`: VM registers its steps at import, and `lifecycle_steps` imports
      `startup`, so `startup` cannot import it back. Startup's `site_projection_poller`
      step calls the new `lifecycle.start_loops()`, which starts every loop registered
      with an interval -- only the poller until Section 9 registers the rest.
      `site_projection_poller_loop` is gone. The interval is read from settings when the
      module is imported.
      **Amended (review):** `server.py` imports `lifecycle_steps` explicitly, so the
      registration no longer rests on the admin controller importing it, and startup's
      `_start_site_projection_poller` refuses, naming the loop, when `start_loops()` leaves
      no poller running; `test_loop_gate_wiring.py::test_startup_starts_the_site_projection_poller`
      covers it. The capacity reconciler's projection provider is now passed by the root:
      `build_capacity_runtime_for(..., site_projections=lambda: site_projections)`, a
      late-bound provider read when a delta arrives (the state is built over the runtime's
      aggregate, so after it). The cached runtime keeps one `_LateSiteProjections` binding
      the root rebinds; the legacy non-root `build_capacity_runtime` passes none and leaves
      it in place, and a runtime nothing bound reconciles no delta.
- [x] 8.2 Consumers take the injected state, never a module: `services/capacity_client.py`
      (`site_pool_projection`, `site_capacity_buckets`, `_reconcile`),
      `services/listing_sources.py`, `services/listing_source_check.py`,
      `services/publication_loop.py`, `negotiation_runtime.py`
      (`lookup_pool_policy_tags`), `failure_actions.py`, `services/system_service.py`
      (projection status from `status()`), `server.py` (`PoolOverrideService`'s
      `projection_source` reads `values(RESOURCE_POOL)` and `refresh_site` calls
      `refresh_site(site_id)`), and `controllers/admin_controller.py`.
      Done. Injected where a constructor or builder already takes its collaborators:
      `ListingService(site_projections=)` (its default source-backing resolver is
      `partial(resolve_source_backing, site_projections)`; `resolve_source_backing` takes
      the state first), `build_vm_negotiation_runtime(site_projections=)`, which passes it
      to `check_listing_source(site_projections=)` and `_place_capacity_hold` /
      `lookup_pool_policy_tags(repository, listing_id, site_projections)`,
      `SystemService(site_projections=)` (its default status and cardinality providers
      bind it), `build_pool_override_service(site_projections=)` (`projection_source` is
      `partial(site_pool_projection, state)`, `refresh_site` the state's), and
      `VmPublicationCycle(site_projections=)`. Read from the container when they run, as
      those modules read their other collaborators: `run_publication_cycle_once`,
      `failure_actions._release_capacity`, the admin controller, the lifecycle steps, and
      the capacity reconciler, whose `_capacity_reconciler(factory, *, site_projections=)`
      provider defaults to the container because the state is built over the runtime's
      own aggregate, after the runtime and its reconciler exist; with no state composed a
      delta reconciles nothing (logged). `capacity_client`'s `site_pool_projection(state)`,
      `site_capacity_buckets(state)`, and new `site_projection_status(state)` (the status
      models as dicts) are the three readers. **Behaviour change:** an override write now
      refreshes both of the site's families (`refresh_site`), not the resource-pool family
      alone.
      **Amended (review):** the admin controller takes the state through `Depends`, as it
      takes its database and capacity runtime, instead of reading the container in its
      methods. `apply_fulfillment_failure_policy(..., site_projections=)` threads the state
      to `_release_capacity` (the admin failure route passes the controller's; the
      settlement stages, which already build their runtime through the legacy container
      path, pass the container's), and once the site has released the reservation nothing
      after it fails the release: with no state the reopen is skipped (logged), and a site
      the state does not hold is reopened from what is held (logged), `refresh_site`
      itself never raising for a failed fetch. `test_failure_policy.py` runs the release
      with the state holding the site (refreshed before the reopen), absent, and holding
      only another site: each records `released` with its reservation id. The
      `publication` step and preview answer a 503 `LifecycleRouteError` before composition,
      as the other steps do, passing the state to `run_publication_cycle_once`
      (`test_lifecycle_advance_routes.py`).
- [x] 8.3 Refresh categories (D4, C7): inline reconciliation in `admin_controller.py`
      (`_close_oversized_compute_listings`, `_reopen_available_compute_listings`) and
      `failure_actions.py` (`_release_capacity`) calls `refresh_site` and never wakes; the
      admin route `POST /api/v1/admin/capacity/projections/refresh` runs `poll_once()` and
      returns `status()`, whether or not the loops are held, keeping its wire contract (D3);
      the override service's wake stays as it is.
      Done. `_close_oversized_compute_listings`, `_reopen_available_compute_listings`, and
      `_release_capacity` call `refresh_site(site)` and wake nothing (the old release-path
      comment that claimed a refresh wakes publication went with its local import). The
      admin refresh route runs `poll_once()` and returns `{"sites":
      site_projection_status(state)}`, the same wire shape as before (each family's
      `state`, `revision`, `digest`, `last_error`, `fetched_at`), held or not, and no
      longer replaces the caches. The override service's wake is unchanged.
      **Corrected (review):** the route first called `poll_once()` itself, bypassing the
      loop controller, recording no outcome, and -- since a poll joins one in flight --
      able to answer with the timer's pre-change generation. It now runs the controller's
      `run_cycle("site-projections")`, held or not, and returns that cycle's `sites`;
      `design.md` D3 says so. `test_site_projection_state.py::test_the_admin_refresh_waits_for_a_running_timer_cycle_and_polls_after_it`
      parks the timer's cycle after its version check, declares a pool, refreshes, and
      shows the answer holds the new pool, polled after the timer's cycle, recorded as a
      step; with the route's direct `poll_once()` restored it fails (the answer misses the
      pool), three runs of three.
- [x] 8.4 `lifecycle_steps.py`: the `site-projections` step runs `poll_once()` and returns
      `status()` (C2).
      Done: `site_projections_step` runs `poll_once()` on the container's state (503
      `LifecycleRouteError` before composition) and returns `{"loop", "sites":
      site_projection_status(state)}`; it is also the registered timer's step.
- [x] 8.5 `services/site_projection_cache.py` reduced to
      `listing_cardinality_mode_explanations`, reading the state it is given; `_caches`,
      the loaders, the poller, the refresh functions, and the unused
      `refresh_after_topology_error` go, and so does VM's `_RemoteProjectionClient`, which
      2.2 copied into the kit rather than moved. Rename the module if only explanations remain, and
      fix the docstring in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      that names it. Once the poller registers through `register_loop`, remove
      `SiteProjectionState.run` and its tests unless something else calls it: it reads its
      gate once and can then wait on a family's lock, the gap Section 3 closed for the
      controller's timer and the capacity-event poller.
      Done. `services/site_projection_cache.py` is deleted: `_caches`, the loaders,
      `site_projection_poller_loop`, the refresh functions, `refresh_after_topology_error`,
      `projection_status_summary`, and VM's `_RemoteProjectionClient` go. The explanations
      move to `services/listing_cardinality_explanations.py` as
      `listing_cardinality_mode_explanations(site_projections)`, its
      `arkhai_vms_listings` import now at module level. The VM listings reconciler's
      docstring names the state instead (docstring only; `arkhai-vms-listings` keeps
      0.5.0). Nothing called `SiteProjectionState.run`, so it goes with its test,
      `_HELD_POLL_SECONDS`, and the module logger: `arkhai-kit-capacity-publication` 0.9.0
      (an incompatible removal), the three storefronts' exact pins `==0.9.0`. `make lock`
      cannot run here (the PyTorch index is refused, as in 2.6), so `scripts/uv_project.py
      lock` relocked the four projects that lock the kit and resolve here
      (`domains/apicredits/storefront`, `domains/bare_metal/storefront`, `e2e-tests`,
      `kit/capacity-publication`); VM storefront's lock was edited by hand with the three
      substitutions uv wrote into bare metal's (version, wheel name, specifier) and
      `make check-packaging` passes with it (16.6 relocks it). **Also changed:**
      `openspec/specs/site-capacity/spec.md` cited the deleted
      `tests/unit/services/test_site_projection_cache.py` as evidence for per-site
      load-state reporting; it now cites `kit/capacity-publication/tests/unit/test_site_projection_state.py`,
      where that evidence lives, so the citation resolves.
- [x] 8.6 Tests build their own state over `tests/fake_site.py`'s fake aggregate and inject
      it through the container, never patching a module (`TESTING.md` "Mocking
      convention"): `tests/unit/services/test_site_projection_cache.py`,
      `tests/unit/test_listing_source_check.py`, `tests/unit/test_publications_wiring.py`,
      `tests/unit/test_remote_capacity_client.py`, `tests/unit/test_sync_negotiation_hold_cap.py`,
      `tests/unit/test_loop_gate_wiring.py`, `tests/unit/test_lifecycle_advance_routes.py`,
      `tests/unit/services/test_system_service.py`, `tests/integration/test_admin_api.py`,
      `tests/integration/test_negotiate_controller.py`,
      `tests/integration/test_abandon_truncation.py`, `tests/integration/test_listings_api.py`,
      `tests/integration/test_pool_overrides_api.py`, and the helpers
      `tests/publication_app.py` and `tests/fake_site.py`. New application-integration
      cases, through the typed client: the admin refresh with one site unreachable keeps
      that site's generation `stale` and wakes publication on another site's change, held
      and not held (spec scenario "An operator refreshes every site during an outage");
      a topology-sensitive refusal checks both families once and does not retry ("A
      refused reservation reveals drift"); stepping `site-projections` while held runs the
      poller's cycle ("The projection step is run while held").
      Done. `tests/fake_site.py`: `FakeProjectionSite` (one site's two families, served
      as a test sets them under a digest of the rows, `None` serving nothing, `failing`,
      per-family `snapshots`, `calls`, and the installed topology handler),
      `site_projection_state(sites)` over a fake aggregate or a runtime's own, and
      `loaded_site_projection_state`; `FakeSite` serves the capacity-bucket family when
      `capacity_buckets` is set (default `None`, keeping the bucket-less derivation the
      suites assumed); `site_capacity` is now an async context manager injecting a state
      over the runtime's own aggregate through the container, loaded with
      `project_pool_modes`; `pump_events` polls that state instead of writing a cache's
      value. Every listed file now builds a state and injects it (constructor or
      `container.resolved_site_projections`); no test patches a projection module. Also
      adapted, as their constructors changed: `test_domain_runtime_wiring.py`,
      `test_settlement_reconciliation.py`, `test_listing_settlement_config.py`,
      `test_order_pause_state.py`, `test_sync_negotiation_seller_round_hook.py`,
      `test_two_phase_reserve.py` (its pre-existing `lookup_pool_policy_tags` patch takes
      the new argument), `test_fulfillment_service.py`, `test_failure_policy.py`,
      `test_server_app_composition.py` (asserts the one state is the one the negotiation
      runtime was given, and is cleared), `test_negotiations_api.py`,
      `test_inventory_freeze.py`, `test_settle_controller.py`, `introduction_deals.py`,
      and `listing_service_fixtures.py` (collaborators carry an unpolled state).
      `test_site_projection_cache.py` became `test_listing_cardinality_explanations.py`
      (its load and status cases are the kit's now; one case added: a stale generation is
      still explained); `site_projection_status` is tested in
      `test_remote_capacity_client.py`, with a stale site keeping its generation and a
      reconciler with no state reconciling nothing. Projection patches that nothing read
      went without replacement (`test_abandon_truncation.py`, and the
      `test_publications_wiring.py` fixture): the tests pass without them.
      **Harness semantics:** the old harness gave its cache the pool list itself, so any
      edit was visible with no poll; the state holds what a site served at its last poll
      or refresh, as production does. The publication suites' `_cycle` helpers (and
      `introduction_deals.publish`) therefore step `site-projections` before stepping
      publication; two cases poll explicitly before stepping another loop or the guard;
      snapshot-count assertions measure the change around the write. A held state never
      forgets a site, so "a site with no projection" is now a restart:
      `publication_app(unreachable_sites=...)` fails a site from the first load, and a
      second app over the same `tmp_path` reopens the first's database
      (`test_pool_overrides_api.py`'s two cases); `test_negotiate_controller.py`'s
      "source cannot be read" cases rebuild the negotiation runtime over a state whose site
      never answered. Until Section 9's freshness window, a stale but held site still
      confirms a source check, so those cases cannot use a failed poll instead.
      New application integration, through `StorefrontClient`:
      `tests/integration/test_site_projection_state.py` -- the admin refresh with site-a
      unreachable, running and held: site-a reported `stale` with its error, site-b
      `loaded`, one wake for site-b's change, site-a's listing still derived (no hold) and
      site-b's new pool published, the loops still held (fails, both cases, with the route
      replaced by a per-site `refresh_site`, which wakes nothing); stepping
      `site-projections` while held runs the poller's cycle: one fetch of the changed site
      only, one wake, nothing published, still held, and a step with no change waking
      nothing. `tests/integration/test_admin_api.py::test_a_refused_reservation_checks_both_families_once_and_is_not_retried`
      -- a site answering the reservation 409 after its pool changed: one POST, then one
      version check of each family through the handler the state installed on the
      runtime's own site client, only the changed family fetched, one wake.
      VM storefront (frozen environment, `UV_FROZEN=1 make test-unit test-integration`):
      unit 1029 passed, 1 skipped; integration 422 passed (four new).
      **Amended (review):** `test_remote_capacity_client.py`'s no-state case observes that
      the reconciler never reaches for its repository, patching nothing;
      `test_server_app_composition.py` builds the root's state from an injected factory and
      asserts the one object reaches the negotiation runtime, listing service, system
      service, pool-override service, container (which the publication cycle reads), and
      the reconciler's provider, over the runtime's aggregate with
      `wake_publication_loop` as its wake; `test_loop_gate_wiring.py` registers the poller
      with an hour's interval before starting it (the configured 5 s is not "far longer"
      than its 1 s bound) and restores the configured registration after.
- [x] 8.7 Validation: `make test-storefront`, `make test-vms-domain`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `multi_registry` (which
      calls the admin refresh), `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`.
      Done. `make test-storefront` cannot reinit here (the PyTorch index is refused, as in
      2.6), so VM storefront ran in its frozen environment with the rebuilt wheels
      reinstalled (`UV_FROZEN=1 make test-unit test-integration`): unit 1029 passed,
      1 skipped; integration 422 passed (application integration, typed client;
      `test_alkahest` against Anvil included). `make -k test`: 54 pytest runs and every
      non-Python suite passed, `make test-vms-domain` (53 passed) among them, kit
      capacity-publication 92 (unit), bare metal 134 + 323 + 11 + 40 and API-credit
      storefront 149 on the 0.9.0 kit; it stopped only at the reinit of `kit/policy`,
      `domains/vms/storefront`, and `domains/vms/buyer`, run frozen: `kit/policy` 80
      passed, VM buyer 202 passed (with the rebuilt `arkhai-vms-listings` reinstalled).
      `make check-packaging` (architecture rules included), `make check-comment-hygiene`,
      `make check-doc-citations CHANGE=share-site-projection-state` (nothing reported),
      and `openspec validate --strict` pass. No repository typing target exists; none was
      run. The pipeline was not run for this section.
      **End-to-end, read from the scenarios' code (the pipeline was not run):** every
      VM-lane scenario composes the state at startup and publishes, negotiates, and checks
      sources through it. Those that reach the changed surfaces directly: `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`,
      `e2e_deal` (through `compute_deal_driver`), `e2e_deal_buyer_cli`, `e2e_buy`, and
      `e2e_non_erc20_settlement` call the admin refresh
      (`host_registry.refresh_storefront_projections`, now the poller's cycle through the
      controller, asserting every family `loaded`); `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_buy`, and `e2e_non_erc20_settlement` also step `site-projections`, and
      `e2e_compute_dynamic_listings` reads `listing_cardinality_mode_explanations` from
      status. `e2e_pool_declared_modes` reaches it only through startup and the source
      check. The smoke test `test_site_projections_loaded` reads status's
      `site_projections`, whose shape is unchanged. No bare-metal or API-credit scenario
      reaches it (bare metal still fetches live until Section 13).
      **Review fixes, re-run:** VM storefront (frozen) unit 1033 passed, 1 skipped, integration
      423 passed (application integration); `make -C kit test-capacity-publication` 93 passed (unit, one new);
      `make check-packaging`, `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state`, and `openspec validate --strict` pass.

Section 8 handoff:

- Section 9 registers the other VM loops with `register_loop` in
  `lifecycle_steps.register_vm_lifecycle_steps`, as the poller now is, and startup's one
  `lifecycle.start_loops()` (today in the `site_projection_poller` step, after
  `load_site_projections`) then starts them all; move that call to wherever every loop may
  start, keeping the poller's first timer cycle after the first load.
- The poller's interval is read from `[capacity].poll_interval` when `lifecycle_steps` is
  imported; a test wanting another interval registers the loop again before
  `start_loops()`.
- 9.2's freshness check has what it needs: `check_listing_source` receives the state
  (`site_projections=`); read each family with `view(site, family)` and
  `freshly_confirmed`. Until then a stale but held site still confirms a source check.
- 9.4's status can build on `capacity_client.site_projection_status(state)`.
- Tests: `tests.fake_site.FakeProjectionSite` and `site_projection_state` /
  `loaded_site_projection_state` build a state over fake sites; `site_capacity` (now
  `async with`) injects one over the runtime's own aggregate, so the topology handler is
  the real site client's. `FakeSite.capacity_buckets` is `None` by default (no bucket
  family served), which the existing derivation tests depend on; a test needing the
  bucket family sets a list. The publication harness's `wakes` records each wake;
  `unreachable_sites` plus a second app over the same `tmp_path` is how a test restarts
  with a site that holds nothing, because a held state never forgets a site.
- The publication suites step `site-projections` before every publication cycle
  (`_cycle`), so a held-loops test that negotiates after Section 9's window passes must
  step it again, as the e2e scenarios do.
- `build_capacity_runtime_for` caches the runtime by configuration key, so a rebuilt app
  in one process builds a new state over the same aggregate; the new state's constructor
  installs its topology handler over the old one's. 10.2's cache-key change keeps that.
- `container.site_projections()` raises when nothing is composed; the lifecycle steps turn
  a missing state into a 503 themselves, and the admin controller takes the state through
  `Depends` (the lifespan sets it before any route serves).
- For 17.9's promotion record: this section edited a permanent spec outside the change's
  deltas. `openspec/specs/site-capacity/spec.md`'s evidence line for per-site load-state
  reporting cited the deleted `test_site_projection_cache.py`; it now cites
  `kit/capacity-publication/tests/unit/test_site_projection_state.py`, which gained
  `test_a_site_that_never_loaded_loads_on_a_later_poll` so its "never-loaded retry" claim
  holds.
- The admin refresh and the `site-projections` step share the controller's lock, so a
  refresh during a timer cycle waits for it; `FakeProjectionSite.hold` parks a version
  check mid-poll for tests that need a cycle in flight.

## 9. VM loops on the cycle boundary, freshness, and lifecycle status

Delivers VM's loops on `run_cycle`, the confirmation window for source checks, and the
`lifecycle` status section (D5, D6; `storefront-publication` "The seller's inventory guard
checks a listing against its own source", "Operator-visible acceptance and projection
state"; `market-composition` "A loop records each cycle's outcome with the controller").
Touches VM's storefront, `core/storefront`'s status model, and the VM lane's configuration.

- [x] 9.1 `src/lifecycle.py` and `src/lifecycle_steps.py`: every VM loop —
      `negotiation_watchdog`, `settlement_servicing`, `fulfillment_resume`, `publication`,
      `introduction_retention`, and the site-projection poller from Section 8 — registers
      its step and interval with `register_loop`; `startup.py` starts none of them as a
      self-gating task. The per-site capacity-event pollers keep their fan-out with the
      per-site lock from 3.4. Publication's cycle (`services/publication_loop.py`) names
      its stages `compose`, `run`, `converge`, and VM's configuration and publication
      errors are the controller's disclosed types.
      Done. `lifecycle_steps.register_vm_lifecycle_steps()` (at import) registers every
      loop's step only, so each lifecycle route can run one; `register_vm_loops(*,
      retention_interval_seconds=None)` registers each loop's timer over the same step
      with its interval read when it runs: the watchdog (`negotiation_watchdog_interval`)
      and servicing (`claims_sweep_interval`) with `initial_delay_seconds` equal to their
      interval, as their kit runners delayed the first sweep; fulfillment resume
      (`fulfillment_resume_sweep_interval`), the poller (`[capacity].poll_interval`), and
      publication (`[capacity].publication_interval_seconds`, woken by the state) with no
      delay; and introduction retention, with its policy's sweep interval as interval and
      delay, only when given one. Startup's new `lifecycle_loops` step
      (`startup._start_lifecycle_loops`), last, after the first projection load and the
      capacity-event pollers, passes the composed retention's interval (contact exchange
      composed) or none, registers, and calls `start_loops()` once. The capacity-event
      aggregate is the one `start_registered_loop` left. Gone: `_start_negotiation_watchdog`,
      `_start_settlement_servicing`, `_start_introduction_retention`,
      `_start_fulfillment_resume`, `_start_publication_loop`, `_start_site_projection_poller`,
      `publication_loop()`, and `fulfillment_resume_loop()`; VM no longer calls the kit's
      `run_negotiation_watchdog`, `SettlementServicingWorker.run`, or
      `run_introduction_retention_sweep` (the kit keeps them for other storefronts).
      **Differed:** (a) the timers register at startup rather than at import, as Section 8
      did the poller's: retention's interval is the composition's and exists only while
      contact exchange is composed, and each start needs a fresh publication wake
      (`publication_loop.new_publication_wake()`, which `wake_publication_loop` sets),
      since an `asyncio.Event` binds to the event loop that first waits on it. Startup
      imports `lifecycle_steps` now, so `_negotiation_watchdog_policy` moved out of
      `startup` into `lifecycle_steps` as `negotiation_watchdog_policy` (the cycle that
      kept the poller's registration at import). (b) The fulfillment-resume step was not
      the timer's cycle: the loop also reconciled accepted payment deals after each sweep,
      the step did not. Both now run `fulfillment_resume_runtime.fulfillment_resume_cycle_once`
      (resume, then payment reconciliation). (c) The watchdog's "marked N stale" log moved
      into its step. (d) Every loop but the capacity pollers now starts after provisioning
      preflight and the first projection load, where the watchdog, servicing, retention,
      and resume started before them; startup runs before the app serves, so the only
      effect is that resume's first sweep waits out the preflight. Stages:
      `VmPublicationCycle(enter_stage=)` names `compose` (site list, projections,
      availability, the domain selection and its sources), `run` (the driver), and
      `converge` (registry convergence); `run_publication_cycle_once` enters `compose`
      before resolving the cycle's collaborators (the domain registry among them) and passes
      the controller's `enter_stage` (`lifecycle.enter_stage`). Disclosed types:
      `lifecycle.DISCLOSED_CYCLE_ERRORS` — VM defines no configuration or publication error
      of its own, so these are the ones its cycles raise for configuration and binding
      reasons, whose text names keys, site and listing IDs, and reasons:
      `CapacityBindingError`, `CapacityConfigurationError` (capacity-publication kit),
      `StorefrontDomainBindingError`, `StorefrontDomainRegistryError` (core). Kit
      `ConfigResolutionError` is not among them: its text can carry a pydantic input value.
      Unit (`tests/unit/test_loop_gate_wiring.py`, rewritten): startup registers and starts
      exactly the five timed loops, held from the start with no cycle run and no poll;
      with every interval an hour, the poller's and publication's first cycles run on start
      and a pause then holds all five within 1 s, none running again; publication's failing
      first cycle (over an absent database) is recorded `timer`, failed, in `converge`, and
      the loop carries on to its interval, where a pause holds it; a wake runs publication again without its interval; the
      retention sweep is registered while contact exchange is composed (last in the module,
      since a registration outlives a test); the capacity-poller cases are unchanged. Steps
      run over collaborators the container holds (a projection site marking its first
      poll, a capacity runtime marking each publication cycle), no module patched.
      `test_lifecycle_advance_routes.py` patches the renamed resume cycle;
      `test_negotiation_watchdog.py` imports the moved policy.
- [x] 9.2 Freshness (D5): `services/listing_source_check.py` confirms a listing only when
      every family it reads — resource pools, and the capacity buckets its fungible
      availability uses — is `freshly_confirmed` within `[capacity].source_confirmation_seconds`,
      defaulting to three times `[capacity].poll_interval` when not stated; any other
      condition is `unverifiable` (retryable). Document the key, commented with its default,
      in `src/settings.toml`.
      Done. `check_listing_source(..., confirmation_window_seconds=None, clock=None)` runs
      `_unconfirmed` before deriving anything, with no await between it and the projection
      read: the resource-pool family must hold a generation and be freshly confirmed; the
      capacity-bucket family must be too whenever the site holds a generation of it. A site
      holding no bucket generation is judged on its pools alone, as derivation then falls
      back to the pool rows (the interpretation of "every family it reads": a family with no
      generation is not read); a held but stale bucket generation refuses rather than being
      dropped (D5's rejected alternative). An unconfigured site is `unverifiable` too. The
      window is `utils.config.source_confirmation_seconds()`, read at each check (beside the
      new `site_projection_poll_interval()`, which the poller's registration also reads);
      `build_vm_negotiation_runtime(source_confirmation_clock=)` is the clock seam,
      current UTC by default. `settings.toml` documents `source_confirmation_seconds`,
      commented, under `[capacity]`. The key has no validation; a non-numeric value fails
      the check that reads it.
- [x] 9.3 The VM lane's overlays (`storefront.bob.toml`, `storefront.alice.toml`) widen
      `source_confirmation_seconds` to cover a held scenario's run, with a comment saying
      why, so a scenario that holds the loops and negotiates without stepping
      `site-projections` is not refused.
      Done: both set `[capacity].source_confirmation_seconds = 3600` with the comment
      (Alice gains a `[capacity]` table beside `[capacity.sites]`). Their poll intervals
      (Bob 1 s, Alice the shipped 5 s) would otherwise give 3 s and 15 s windows.
- [x] 9.4 Status: `core/storefront/src/core_storefront/models/system_models.py`'s
      `HealthResponse` gains `lifecycle` (each loop's state and last outcome, from the
      controller's snapshot), and `services/system_service.py` fills it. Additive on the
      wire.
      Done: `LoopCycleError`, `LoopCycleOutcome`, and `LoopStatus` (the kit's
      `LoopSnapshot.to_dict()` shape: `name`, `state`, `last_outcome`), and
      `HealthResponse.lifecycle: dict[str, LoopStatus] | None`, keyed by loop name; the
      publication loop's entry carries publication's last cycle. `SystemService` gains
      `lifecycle_provider` (default: `lifecycle.snapshot()` as dicts) and fills
      `lifecycle` on system status only, not the liveness probes. `arkhai-core-storefront`
      0.14.0; `arkhai-kit-capacity-publication` 0.9.1, which pins it exactly (`==0.14.0`),
      and the three storefronts' exact pins of it; VM requires `arkhai-core-storefront>=0.14.0`.
      `scripts/uv_project.py lock` relocked the eight projects locking either package that
      resolve here (`core/storefront`, `kit/capacity-publication`, `kit/storefront`,
      `domains/vms/domain`, `domains/bare_metal`, `domains/bare_metal/storefront`,
      `domains/apicredits/storefront`, `e2e-tests`); VM storefront's lock was edited by hand
      with the five substitutions uv wrote into bare metal's lock (both versions, both wheel
      names, the capacity-publication pin) plus its own core floor; neither `kit/policy` nor
      VM buyer locks either package (16.6 relocks VM storefront). **Not done:** the typed
      client's `HealthResponse` (`core/storefront-client`) has no `lifecycle` field, so a
      caller reads it from `extra["lifecycle"]`, which the client parses into; a typed
      field would bump the client and move the provisioning service's exact pin. Section 14
      reports bare metal's `lifecycle` too and is the natural place to add it.
      **Amended (review):** the typed client now names it: `arkhai-core-storefront-client`
      0.26.0's `HealthResponse.lifecycle`, read by `test_lifecycle_status.py` (see the
      review fixes below).
- [x] 9.5 Tests. Unit: `tests/unit/test_listing_source_check.py` — a loaded generation past
      the window, a stale bucket family beside a fresh resource-pool family, and the
      default window from `poll_interval`. Application integration, through the typed
      client: `tests/integration/test_negotiate_controller.py` — with the loops held past
      the window a round is refused as retryable and succeeds after stepping
      `site-projections` (spec scenario "The loops are held past the confirmation window"),
      and an unbacked listing's stale site refuses ("An unbacked listing's site is
      stale"); a status test — a failing publication cycle stepped and timer-run is
      reported failed with its stage, and a loop's state is reported ("Publication fails
      every cycle", "A stepped cycle fails"). `tests/unit/test_loop_gate_wiring.py` and
      `tests/unit/test_lifecycle_advance_routes.py` updated to the registered loops.
      Done. Unit (`test_listing_source_check.py`, six new): a loaded generation confirms at
      the window's edge and not a second past it, refused before any availability read; a
      stale bucket family beside a fresh pool family refuses, naming the bucket family, with
      no site call; a site serving no bucket family is judged on its pools; a failed poll
      refuses although the generation is held; the window is three poll intervals unless
      stated; an unstated window is the configured one. With the freshness test disabled
      (module swapped, then restored) four of them fail. Application integration, through
      `StorefrontClient`: `test_negotiate_controller.py::TestSourceConfirmationWindow` —
      every loop's timer registered and started held (`held_loops`), the runtime's clock set
      61 s after the site's last confirmed poll with a 60 s window: the opening is refused
      503 `listing_source_unverifiable`; `admin_run_lifecycle_cycle("site-projections")`
      polls, and an opening a second after that poll counters, the poller still paused (the
      fixture app now also mounts the admin router); and an unbacked listing whose site's
      latest poll failed refuses 503 with no site call. New
      `tests/integration/test_lifecycle_status.py` over `tests.publication_app`, the cycle
      failing in `compose` through a capacity runtime in the container: a timer-run cycle
      failing on `CapacityConfigurationError` is reported with the loop `running`,
      `trigger` `timer`, stage `compose`, and the error's type and message; a stepped cycle
      failing on a `ConnectionError` naming a site URL answers 500 and is reported
      `trigger` `step`, stage `compose`, type only, the URL absent from status and the
      response; and every timed loop held from the start is reported `paused` with no
      outcome. Status is read with `get_system_status()`'s `extra["lifecycle"]` (9.4). Also
      adapted: `test_publication_loop.py` starts the loops with `_start_lifecycle_loops()`
      and awaits the timers it cancels; `test_site_projection_state.py` registers the timers
      with `register_vm_loops()` before starting them (the poller is no longer registered at
      import), so its refresh-during-timer case now runs every loop's timer, not the poller's
      alone. VM storefront (frozen, `UV_FROZEN=1`): unit 1035 passed, 1 skipped; integration
      428 passed (five new; `test_alkahest` against Anvil included), twice. **Corrected
      (review):** a first integration run that made no progress for 15 minutes was not
      contention with a concurrent pytest process, as first recorded here: it was the
      kit's publication driver holding a worker thread forever once a test tore down a
      publication timer mid-cycle (see the review fixes below).
- [x] 9.6 Validation: `make test-storefront`, `make test-core`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`.
      Done. `make test-storefront` cannot reinit here (the PyTorch index is refused, as in
      2.6), so VM storefront ran frozen with the rebuilt wheels reinstalled: unit 1035
      passed, 1 skipped; integration 428 passed (application integration). `make test-core`:
      core storefront 211 passed, 2 skipped, and the other core suites passed. `make -k
      test`: every suite that ran passed (capacity-publication 93, kit storefront 98 among
      them, bare metal 134 + 323 + 11 + 40, API-credit storefront 149, e2e unit 650); it
      stopped only at the reinit of `kit/policy`, `domains/vms/storefront`, and
      `domains/vms/buyer`, run frozen: `kit/policy` 80 passed, VM buyer 202 passed, VM
      storefront as above. `make check-packaging` (architecture rules included), `make
      check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
      (nothing reported), and `openspec validate --strict` pass. No repository typing target
      exists; none was run. The pipeline was not run for this section.
      **End-to-end, read from the scenarios' code (the pipeline was not run):** every VM-lane
      scenario now runs the storefront's loops on the controller's timer, and its rounds and
      acceptances pass the confirmation window, which the lane overlays widen to an hour.
      **Corrected (review):** the Compose overlays only; the umbrella chart's `bob` agent
      (`helm/values.yaml`), which change-validate's Helm part deploys with the loops held,
      had no `[capacity]` and so the 15 s default until the review fixes widened it too.
      The scenarios that hold the loops and step them — `e2e_deal` and `e2e_buy` (through
      `compute_deal_stages` / `compute_deal`), `e2e_deal_buyer_cli`, `e2e_non_erc20_settlement`,
      `multi_registry`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, and
      `e2e_vm_introduction` — step `publication`, `site-projections`, and (`e2e_deal`)
      `settlement-servicing` through the same locked, recorded cycle the timers run, and
      `capacity-events` through the kit's per-site lock as before; no scenario steps
      `fulfillment-resume`, whose timer cycle now also reconciles accepted payment deals,
      which no VM-lane scenario creates. `e2e_vm_introduction` composes contact exchange, so its storefront
      registers the retention sweep at startup. `e2e_pool_declared_modes` reaches the window
      through its source check. No scenario reads `lifecycle` from status, and none runs
      held past the window; the window's refusal is application-integration evidence only.
      No bare-metal or API-credit scenario reaches this section's code (their storefronts
      take the core and capacity-publication bumps, unchanged in behaviour).


Section 9 review fixes (fresh-context review of the section commit):

- **The publication driver no longer strands its worker thread.** `PublicationCycleDriver`
  (`kit/capacity-publication/src/market_capacity_publication/cycle.py`) tracks the
  coroutines its callbacks hand to the loop; when the awaiting `run` is cancelled it cancels
  them, so the waiting callback fails at once with the new `PublicationCycleStopped` and so
  does every later call, and the runner's thread unwinds. Before, a test tearing down a
  running publication timer left the thread blocked in `run_coroutine_threadsafe(...).result()`
  on a closed loop, and interpreter exit hung joining it (the reviewer saw 2 of 9 runs hang;
  this session's 15-minute stall was the same). Production shutdown mid-cycle had the same
  fault. Unit: `kit/capacity-publication/tests/unit/test_cycle.py::test_cancelling_a_cycle_mid_callback_lets_its_worker_thread_finish`
  (fails against the old driver); `make -C kit test-capacity-publication` 94 passed.
  `arkhai-kit-capacity-publication` 0.9.2; the three storefronts' exact pins follow. VM's
  `test_site_projection_state.py` and the negotiate suite's `held_loops` now register and
  start the site-projection poller alone, so no publication timer runs where no case needs it.
- **A fungible listing needs a freshly confirmed bucket family; an exact listing does not
  read it.** `listing_source_check` decides from the listing's durable binding: one bound
  to a resource (`physical_resource_id`) is exact and reads the resource-pool family
  alone; any other is fungible and reads both, a bucket family with no generation being
  not held and refusing (D4: every site holds both). The first version confirmed a
  fungible listing from pools alone when the bucket family had never loaded. Test fakes:
  `FakeProjectionSite(derive_buckets=True)` serves a bucket family derived per member from
  its pool rows (`buckets_from_pools`, with the site's grouping attributes), which
  `HarnessProjectionSite` (the publication harness) and the source-check unit tests use;
  per-member buckets give a fungible pool exactly its pool rows' availability. Unit: a
  fungible listing whose bucket family never loaded refuses, naming it; an exact listing
  with no bucket family confirms; an exact listing still needs a fresh pool family.
  **Found:** capacity-event reconciliation reads the held bucket family, which a delta
  does not refresh, so where a site serves buckets a reservation closes a fungible
  listing only after the next projection poll; `test_a_capacity_event_acts_only_on_backed_listings`
  now steps `site-projections` after changing availability. This predates the section
  (Section 8's reconciler reads held buckets) and was hidden by fakes serving none; for
  the owner whether a capacity delta should refresh the site's bucket family inline.
- **The umbrella chart's `bob` agent widens the window** (`helm/values.yaml`,
  `capacity.source_confirmation_seconds: 3600`, commented); the storefront chart's
  default-release render test asserts it passes through beside the derived site. `make -C
  helm test-render` passed with the loader check run.
- **The window test proves the step polled:** the clock is pinned past the seeding poll's
  window, the refused round leaves `fetched_at` unchanged, and after the step the site was
  asked its version and `fetched_at` advanced before the clock moves to a second after it.
- **The typed client names `lifecycle`:** `arkhai-core-storefront-client` 0.26.0
  (`HealthResponse.lifecycle`, two client unit tests); VM requires `>=0.26.0`; the
  provisioning service's exact pin moves to `==0.26.0`.
- **Comments and logs:** `DISCLOSED_CYCLE_ERRORS`' comment says their text names public
  identifiers, versions, and reasons, never a secret, and that subclasses are disclosed
  too; `register_vm_loops`' docstring states why the sweeps' first cycle is delayed instead
  of "as they always have"; the retention step logs the payloads it deleted; startup logs
  each loop it starts with its interval (`register_vm_loops` returns them).
- **Stage and interval wiring:** `publication_step` enters `compose` before resolving the
  projection state, so a missing state fails in `compose`; `claims_sweep_interval` is read
  once, by `utils.config.settlement_servicing_interval()`, for the worker and the timer.
- **Startup refuses an unusable window:** `_require_source_confirmation_window` (a startup
  step before any loop) refuses a `source_confirmation_seconds` that is not a positive
  number, naming `capacity.source_confirmation_seconds`; unit-tested for 0, negative,
  text, and a boolean.
- **Fulfillment resume:** `resume_incomplete_fulfillments_once` lists deliveries before
  building any client and returns at once with none; `test_lifecycle_advance_routes.py`
  now injects a delivery store and a payments coordinator through the container and shows
  the step resumes and then reconciles payment deals, with no module patched.
- **Loop teardown:** the controller gains `stop_loops(*, keep_registrations=True)` and
  `clear_loops(*, keep_registrations=True)` (`arkhai-kit-storefront` 0.5.0, two kit unit
  tests; the storefronts' exact pins follow); VM's `reset_for_tests()` is async, stops and
  awaits every loop, and forgets timer registrations, so no fixture reads `_handles` and
  `TestIntroductionRetention` is order-independent.
- Locks: `scripts/uv_project.py lock` relocked `core/storefront-client`,
  `kit/capacity-publication`, `kit/storefront`, `provisioning/compute/service`, the
  bare-metal and API-credit storefronts, and `e2e-tests`; VM storefront's lock was edited
  by hand with the nine substitutions those packages need (three versions, three wheel
  names, three root specifiers).
- Evidence after the fixes: VM storefront (frozen) unit 1041 passed, 1 skipped, twice;
  integration 428 passed in nine of eleven full runs, none hanging (each about two
  minutes). Two runs failed one test,
  `test_payment_settlement.py::test_settlement_is_pending_until_a_verified_receipt_then_delivers_once`
  (`'ready' == 'provisioning'`), which passed 30 of 30 runs alone. It is a race in that
  test, not in this section's code: the coordinator starts delivery as a task and then
  awaits a database read before answering, so a delivery that completes during that read
  answers `ready`; no code it runs changed here. Left as it is and flagged. `make
  test-core` (storefront client 62 passed), `make -C kit test-capacity-publication` 94,
  `make -C kit test-storefront` 100, `make test-bare-metal` 134 + 323 + 11 + 40,
  `make test-apicredits` (storefront 149), `make test-provisioning` (service 462 among
  them), and `make test-kits` passed, the last stopping only at `kit/policy`'s reinit
  (the PyTorch index); `make -C helm test-render` passed with the loader check run; `make
  check-packaging`, `make check-comment-hygiene`, `make check-doc-citations
  CHANGE=share-site-projection-state`, and `openspec validate --strict` pass.

Section 9 follow-up (made with round 04's fixes; not a review finding):

- **The intermittent settlement test is deterministic.**
  `domains/vms/storefront/tests/integration/test_payment_settlement.py::test_settlement_is_pending_until_a_verified_receipt_then_delivers_once`
  failed about 2 runs in 11 (`'ready' == 'provisioning'`): the payments coordinator starts
  delivery as a task and then awaits a database read before answering, so a delivery that
  finished during that read answered `ready`. The test now holds the delivery at the
  harness's existing gate (`Delivery.started` / `Delivery.release`, the seam
  `test_a_refund_after_delivery_start_records_both` uses) until it has read the
  `provisioning` answer, then releases it and awaits the delivery task; nothing is left
  held. No production code changed. Application integration; 20 of 20 runs of the case
  passed alone, and the full VM integration suite passed three times (7.9's evidence).

Section 9 handoff:

- Startup's `lifecycle_loops` step registers every VM timer with
  `lifecycle_steps.register_vm_loops()` and starts them; import registers steps only. A test
  that starts timers without startup registers them first (`register_vm_loops()`, or one
  loop with `lifecycle.register_loop`). `await lifecycle.reset_for_tests()` stops and awaits
  every timer and forgets the timer registrations (the kit's `stop_loops(keep_registrations=False)`),
  so no test starts a loop another registered.
- The publication wake is renewed per registration (`new_publication_wake`);
  `wake_publication_loop` sets the current one. Bare metal's publication wake (13.2) needs
  the same care if its runtime is rebuilt on another event loop.
- `check_listing_source(confirmation_window_seconds=, clock=)` and
  `build_vm_negotiation_runtime(source_confirmation_clock=)` are the freshness seams; the
  window reads `utils.config.source_confirmation_seconds()` at each check. Bare metal's
  13.4 should read `[capacity].source_confirmation_seconds` the same way (three poll
  intervals by default).
- The source check reads the capacity-bucket family only when the site holds a generation
  of it; Section 13's bare-metal recheck reads the resource-pool family only, per D5.
- Status: `HealthResponse.lifecycle` (core 0.14.0) is keyed by loop name with the kit's
  `LoopSnapshot.to_dict()` shape; the typed client reads it as `HealthResponse.lifecycle`
  (`arkhai-core-storefront-client` 0.26.0), so 14.1 needs no client change.
- For the owner: the per-site capacity-event pollers' timer cycles record no outcome; only
  a `capacity-events` step does, through the controller. market-composition's "A loop
  records each cycle's outcome with the controller" asks for an outcome "whether its timer
  or an operator's step ran the cycle". Whether the kit's per-site poller should record
  per-site outcomes (and status report them) is undecided; nothing was changed.
- `lifecycle.DISCLOSED_CYCLE_ERRORS` is VM's disclosed set (kit and core configuration and
  binding errors; VM has none of its own). Bare metal's 13.2 picks its own, likely its
  configuration errors from Section 11 plus the same kit and core ones.
- For 17.9: `TESTING.md`'s VM loop row stays right (same routes), but its "Traps" text on
  self-gating loops now describes only the capacity pollers in VM; `ARCHITECTURE.md`'s
  "Operator lifecycle controls" already describes the controller's timer.

## 10. VM startup refusal, per-site trust, and the interval key

Delivers VM's refusal to start without publication, its per-site service-peer trust, and
`settlement_servicing_interval_seconds` (D6, D14b, C4; `storefront-publication` "A storefront
that cannot publish refuses to start", "Site authority principals rotate with bounded
overlap"). Touches VM's storefront, its chart's generated schema, and the VM lane's
configuration.

- [x] 10.1 Startup refusal (`src/startup.py` or a composition-time check beside it): no
      registry, or a registry without its authority pin while `enable_registry_discovery`
      is true; no enabled settlement mechanism; a configured site with no service peer or
      more than one (through 4.3). Each problem is named, and no loop starts. An empty
      `[pricing].settlements` is not a refusal.
      Done in a new module beside startup, `src/startup_refusal.py`:
      `publication_startup_problems(source)` collects every problem in order and
      `require_publishable_storefront(source)` raises `StorefrontStartupError` ("the
      storefront cannot publish: …", each problem named, `;`-joined). `_build_vm_services`
      calls it after the admissibility parse and the release-model check and before the
      database, signer, or any collaborator, so no database file and no loop exist when it
      refuses. Problems: a renamed setting still stated (10.3); `[registry].urls` empty, or
      `get_registry_authorities` refusing the pins (both only while
      `enable_registry_discovery` is on, the switch with which VM publishes to no registry
      on purpose -- D6's parenthetical read as covering both registry checks); no
      `[Settlement]` section enabled, or a root that does not resolve; no `[capacity.sites]`
      (also in the spec delta's "no configured site", which 10.1's text omitted for VM); and
      `require_one_service_peer_per_site` (4.3). `_start_vm_services` no longer calls
      `get_registry_authorities()` itself, since the refusal checks it first. Site reading
      moved into `utils.config.configured_capacity_sites(source)`, which
      `capacity_client._capacity_settings` now calls (same messages).
- [x] 10.2 Per-site trust: `services/capacity_client.py`'s `build_capacity_runtime_for`
      gives each site's `CapacitySite` the provider of that site's peer's active
      principals (4.1, 4.3) instead of the shared `[provisioning.identity]` set, and the
      runtime's cache key stops carrying principals. `[provisioning.identity]` remains
      only for `build_fulfillment_client` and `services/fulfillment_service.py`. The
      provider is read synchronously on the event loop per response, so it must not block
      on SQLite (04 F4): hold each peer's principal records in memory, loaded at seeding
      and reloaded when an identity rotation, completion, or retirement commits, and
      evaluate `active_principals(now)` over them at each call (still "at verification
      time", D14b); bare metal's 12.2 composes the same provider.
      Done (04 F4). Core: `core_storefront.service_peers.ServicePeerTrust(db_path, peers, *,
      clock)` holds each configured site's durable peer status in memory (replaced whole
      per load, under a lock, so a reader sees one complete load): `seed()` seeds and
      loads, `reload()` reads durable state (blocking; worker thread once serving),
      `site_active_principals(site, now=)` for callbacks, `site_trusted_set(site)` and
      `site_authorities(site)` (a provider: `partial` over memory, primary first) for site
      clients, and `identity_authority()`, a `StorefrontIdentityAuthority` whose
      `register_service_peer`, `apply_rotation`, `complete_rotation`, `retire`, and
      `disable` reload the trust in a `finally`, so a change committed through it reaches
      verification as it commits. A site bound to no peer, two, a disabled peer, or one
      disagreeing with configuration raises `AuthError` with the reason; before the first
      load, `AuthError` 503. The SQLite-reading `site_trusted_authorities` and
      `site_active_principals` functions are gone (nothing composed the first; the second
      was VM's callback read, now the trust's), so `arkhai-core-storefront` 0.15.0 (an
      incompatible removal); `arkhai-kit-capacity-publication` 0.9.3 pins it exactly, and
      the VM, bare-metal, API-credit storefronts' and the provisioning service dev group's
      exact pins follow; VM requires `arkhai-core-storefront>=0.15.0`. VM:
      `_build_vm_services` builds one trust over the storefront database and
      `get_service_peer_configs()`, passes it to `build_capacity_runtime_for`, and
      `VmStorefrontServices.service_peer_trust` carries it; `_start_vm_services` seeds it
      (in place of `initialize_service_peer_identities`, which is gone) and sets
      `container.resolved_service_peer_trust`. The runtime's sites carry
      `_LateServicePeerTrust.site_authorities(site)` providers, which read whichever trust
      the root last bound (the runtime is cached across compositions in one process, as
      Section 8's late-bound projection provider is); nothing bound fails each response
      closed. The cache key drops the principals and gains an optional
      `site_client_factory`, passed to `CapacityRuntime` as its constructor allows, so a
      test can give the production runtime a fake transport. The callback middleware reads
      the trust from the container (no thread, no SQLite) and the status read's single peer
      from `trust.peers`; it no longer imports `get_service_peer_configs`, retiring the
      module patch three VM test files used. The admin rotation and retirement routes
      commit through `trust.identity_authority()` (503 when no trust is composed).
      **Corrected (round 05/06, 05 F1):** this task's text left `build_fulfillment_client` on
      `[provisioning.identity]`, wider than D14b, which keeps that set for the
      provisioning-service client alone; 10.8 moves the per-site fulfillment clients onto their
      site's peer.
- [x] 10.3 Interval key (C4): `src/settings.toml`, `src/settlement_composition.py`,
      `src/startup.py`, `src/utils/config.py`'s `settlement_servicing_interval()` (the one
      reader, used by the servicing worker and `src/lifecycle_steps.py`'s registration),
      and the lane overlays use `settlement_servicing_interval_seconds`; a
      configuration stating `claims_sweep_interval` refuses startup naming its replacement;
      VM's section list marks the key retired and `make helm-values-schema` regenerates
      both schemas, so an agent's `config` stating it is refused at render. The charts'
      hand-written `config.allOf` block of retired keys is a second home for retirements:
      decide between them first (Section 5 handoff).
      Done. `settlement_servicing_interval()` reads `settlement_servicing_interval_seconds`
      (default 30), still the one reader (the worker in `settlement_composition.py` and the
      timer in `lifecycle_steps.py`); `settings.toml` ships the key; Bob's and Alice's
      overlays use it. `startup.py` needed no change: it reads no interval of its own.
      `utils.config.RENAMED_SETTINGS` maps the old key to its replacement and
      `renamed_setting_problems(source)` names each one stated, in any spelling, which the
      startup refusal reports; the old key is not read as the interval.
      **Decided (two homes):** `RETIRED_KEYS` in VM's `values_schema.py` holds keys of the
      storefront's own configuration that it no longer reads, generated with its section
      list; the chart's hand-written `config.allOf` block holds the chart's own retired
      values shape, the pre-0.2.0 keys the pass-through chart refused when it was introduced
      (`seller`, `registryAuthority`, `registryUrl`, `storefrontDomains`, `configMapName`,
      `hostedSettlement`, `chain`). By that rule the local-inventory keys the storefront
      retired later (`resources_csv_path`, `resources_csv_inline`, `escrow_templates`,
      `capacity.use_site_projection_for_listings`) moved from both hand blocks
      (`helm/charts/storefront/values.schema.json`, `helm/values.schema.json`) into
      `RETIRED_KEYS`, beside `*RENAMED_SETTINGS`; `make helm-values-schema` regenerated both
      definitions, which now refuse all five in any spelling. The existing render tests of
      the inventory keys pass unchanged against the generated refusal. `market-storefront
      config set`'s own list of inventory keys (`groups/config.py`) is unchanged. For 17.9:
      `DEPLOYMENT_AND_CONFIG.md` should state which home is for which kind of key.
- [x] 10.4 The VM lane's overlays declare every site's service peer if any does not yet,
      so the lane starts under 10.1.
      Already so: `storefront.bob.toml` and `storefront.alice.toml` each bind their one
      site, `default`, to `provisioning_default`, pin every registry, and enable Alkahest
      (Bob also contact exchange), so both pass the refusal; no change. The umbrella's
      `bob` agent and the chart fixtures declare the peer too. **Found (for the owner):** the
      umbrella's default `bob` agent (`helm/values.yaml`, and the storefront chart's own
      `values.yaml`) states `Settlement: {priority: []}`, so a release from the default
      values alone -- `make -C helm deploy-local` with no settlement overlay, as
      change-validate's Helm part deploys -- now refuses to start, naming "no settlement
      mechanism is enabled under [Settlement]". The render tests are unaffected (they do
      not start a storefront), and the fixtures `eip191-evm-values.yaml`,
      `payments-ed25519-values.yaml`, and `contact-exchange-values.yaml` each enable one.
      Not changed here, since which mechanism the default development release sells under
      is not decided in `design.md`. Options: (a) enable Alkahest in the default agent as
      the EVM fixture does (needs the wallet Secret and a chain the release has);
      (b) enable contact exchange, which needs no wallet, chain, or credential, with a
      development contact on a reserved domain; (c) keep the default unstartable and have
      the runbook deploy with a fixture that enables a mechanism. Recommended: (a), which
      matches the Compose lane and is what the Helm deal validation exercises.
- [x] 10.5 Tests. Unit: `tests/unit/test_config_loader.py` — the retired key's refusal.
      Application integration, through the typed client: startup refusals named per
      problem with no loop started; the empty-settlements storefront starts and publishes
      a pool whose override states clauses ("A storefront's terms live in its pools"); a
      site's responses verify against its peer's principals and, after the admin rotation
      routes complete a rotation and its overlap ends, only against the replacement,
      without a restart ("A site's responses follow its rotation"); a principal of one
      site does not verify another's responses. `helm/charts/storefront/tests/test_render.py`
      — `claims_sweep_interval` in an agent's `config` is refused naming the key.
      Done. Unit: `test_config_loader.py` (two new) -- the packaged and read interval key,
      and the old key in two spellings named with its replacement and not read;
      `tests/unit/test_startup_refusal.py` (new, nine, over Dynaconf sources) -- a
      storefront with no configured clauses is not refused; no registry; a registry without
      its pin; registries unchecked while discovery is off; no enabled mechanism (none, and
      one disabled); no site; a site with no peer and one with two, named together; the
      renamed key; every problem in one refusal. Application startup, the real app and
      lifespan: `tests/integration/test_publishable_startup.py` (new, six cases) -- from a
      configuration that publishes, each break (no registry, a registry without its pin, no
      enabled mechanism, a site with no peer, one with two, the old interval key) refuses
      with `StorefrontStartupError` naming it, no storefront installed, no database client
      created, no database file written, no loop. Application integration through
      `StorefrontClient`: `test_pool_overrides_api.py::test_a_storefront_with_no_configured_clauses_publishes_a_pool_whose_override_states_them`
      -- `[pricing].settlements` empty, the pool publishes nothing until an override states
      a clause, then publishes under it. **Differed (level):** that such a storefront
      *starts* is shown by the refusal unit test, not by a lifespan that runs its startup
      steps, which need a reachable provisioning service. `tests/integration/test_site_trust.py`
      (new, two): the production `build_capacity_runtime_for` composed with the seeded trust
      and fake site transports; a rotation applied through
      `admin_initiate_identity_rotation` admits either principal during its overlap, and once
      `admin_complete_identity_rotation` retires the old one only the replacement verifies,
      same runtime and clients; the other site's peer is untouched; neither site's principal
      verifies the other's responses. With the admin routes committing through a plain
      `StorefrontIdentityAuthority` (swapped, then restored) the rotation case fails.
      Core (library integration, `core/storefront/tests/integration/test_service_peers.py`,
      rewritten over the trust): seeding, the startup refusal, a site with no peer or two,
      nothing before the first load (503), active principals through an overlap and per
      site, the provider following a rotation from memory with the database file moved away
      (the overlap still ends by the clock) and a completion through the trust's authority,
      a change made outside it waiting for a reload, and a disabled peer. Adapted:
      `test_service_peer_identity.py`, `tests/publication_app.py`, and
      `test_admin_api.py` build and inject a seeded trust instead of patching
      `get_service_peer_configs`; `test_server_app_composition.py` asserts the one trust the
      root builds reaches the runtime and the container, is seeded, and is cleared (it
      stubs the refusal, since its configuration publishes nowhere);
      `test_admissibility_default_composition.py` and `test_loop_gate_wiring.py` follow.
      `tests/fake_site.py`'s `FakeSite.signer` lets a test choose the key a site signs
      with. Chart render: `test_the_renamed_servicing_interval_is_refused_in_any_spelling`
      (two spellings refused naming the key; the new key passes through).
- [x] 10.6 Validation: `make test-storefront`, `make -C helm test-render` (with
      `STOREFRONT_PYTHON` for the loader check), `make test`. End-to-end (VM lane): every
      VM scenario, since each starts the storefront; and the storefront smoke tests.
      Done. `make test-storefront` cannot reinit here (the PyTorch index is refused, as in
      2.6), so VM storefront ran frozen with the rebuilt core and capacity-publication
      wheels reinstalled (`UV_FROZEN=1 make test-unit test-integration`): unit 1055 passed,
      1 skipped (twelve new); integration 440 passed (nine new; application integration and
      application startup; `test_alkahest` against Anvil included), twice. `make
      helm-values-schema` regenerated both schemas (the five retired keys); `make -C helm
      test-render` with `STOREFRONT_PYTHON` set to VM's environment passed, the loader
      check (`test_rendered_document_loads_with_the_storefront_loader`) run, not skipped,
      and the new render case passing. `make -k test`: every suite it ran passed -- core
      storefront 213 passed, 2 skipped (library integration, two new), kit
      capacity-publication 94 + 81, kit storefront 100, provisioning service 675 + 463, bare
      metal 134 + 324 + 11 + 40, API-credit storefront 153, e2e unit 650, the Helm and
      deployment-packaging suites among them -- and it stopped only at the reinit of
      `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer`, run frozen:
      `kit/policy` 80 passed, VM buyer 202 passed, VM storefront as above. Locks:
      `scripts/uv_project.py lock` relocked the nine projects locking either bumped package
      that resolve here; VM storefront's lock was edited by hand with the six substitutions
      uv wrote into bare metal's lock for the same two packages (two versions, two wheel
      names, the capacity-publication pin) plus its own core floor (16.6 relocks it); neither
      `kit/policy` nor VM buyer locks either package. `make check-packaging` (architecture
      rules included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), and `openspec validate
      --strict` pass. No repository typing target exists. The pipeline was not run.
      **End-to-end, read from the lane's configuration (the pipeline was not run):** every
      VM-lane scenario starts Bob's and Alice's storefronts, whose overlays pass the startup
      refusal (registries pinned, Alkahest enabled, `default` bound to one peer) and now
      state `settlement_servicing_interval_seconds`; every site response those storefronts
      verify -- projection polls, capacity events, reservations -- is verified against the
      `default` site's seeded peer through the trust, and every provisioning callback
      (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_non_erc20_settlement`,
      `e2e_compute_dynamic_listings`) authenticates against it. No scenario rotates a peer or
      starts a storefront that cannot publish: those are application-integration evidence
      only. The Helm smoke tests run against a release from the default values, which now
      refuses to start without a settlement overlay (10.4's finding). No bare-metal or
      API-credit scenario reaches this section's code (their storefronts take the core and
      capacity-publication bumps, unchanged in behaviour).

Section 10 handoff:

- Bare metal's 12.1–12.3 compose the same `ServicePeerTrust`: build it over the
  storefront database and the configured peers, `seed()` it at startup, give each site
  client `trust.site_authorities(site)`, verify callbacks with
  `trust.site_active_principals(site, now=)`, and commit 12.5's rotation routes through
  `trust.identity_authority()`; a change committed any other way is invisible until
  `reload()`.
- `build_capacity_runtime_for(..., service_peer_trust=, site_client_factory=)`: the root
  binds the trust late, as it binds the projection provider; legacy non-root callers pass
  neither. The many tests patching `capacity_client.get_provisioning_authorities` still
  run (`build_fulfillment_client` reads it); for the capacity runtime it no longer
  matters.
- The startup refusal reads its configuration from `utils.config.settings` by default; a
  test composing the real app must give it a publishable configuration, as
  `test_publishable_startup.py`'s `_PUBLISHABLE` does. Dynaconf keeps an empty table set
  on a dotted key, so replace a section at its root to empty it.
- Bare metal's 11.5 and 12.1 refusal is its own; `startup_refusal.py` is VM's and reads
  VM's Dynaconf settings, so it is not shared. Its problem texts are a reasonable model.
- The umbrella's default release no longer starts without a settlement mechanism (10.4,
  for the owner).
- For 17.9: `DEPLOYMENT_AND_CONFIG.md` -- the startup refusal, per-site trust from each
  site's peer (and `[provisioning.identity]` only for the provisioning client), the
  renamed key, and the two homes of retired keys (10.3).

### Round 05/06 triage fixes (owner dispositions 2026-10-16)

Review 06 (external, Sections 8–10) and check 05 (Section 10's fresh-context check), both of
`5eff4a6`, were triaged together; every finding is disposed of, in
`reviews/06-implementation-external.triage.md`. The fixes below are owed before Section 11, as one
commit naming the round, followed by a fresh-context check of it and the gate question. Still to
ask the owner: whether validation of `5eff4a6` (no end-to-end run yet) is run or waived for this
round.

- [x] 10.7 (06 F1 / 05 F2) **Default release starts locally.** Chart defaults stay free of
      Alkahest. `helm/local-values.yaml` enables Alkahest against the Anvil instance the chart
      deploys, with the known development wallets (public, commented as test-only, never for a
      public network), and contact exchange with a development contact. A render test loads the
      `deploy-local` render's `storefront.json` through `STOREFRONT_PYTHON` and runs the real startup
      refusal (`publication_startup_problems`), asserting no problem. Document in
      `DEPLOYMENT_AND_CONFIG.md` at closeout (17.9).
      Done. `helm/local-values.yaml` repeats Bob's agent in full (Helm replaces lists), adding
      `Wallet.address` (Anvil's deterministic account 2, commented as a development value
      never for a public network), `Chains.anvil` on the dev-env chart's Anvil
      (`http://arkhai-node-operator-dev-env:8545`, chain 31337, the image's address book), an
      Alkahest publication clause in the dev chain's test token as the Compose lane sells, and
      `[Settlement]` with `alkahest.v1` and `contact-exchange.v1` enabled, the contact
      `bob-sales@seller.invalid` for `default`. The wallet key stays in the out-of-band
      `arkhai-bob-runtime` overlay, since the chart renders no key material and the refusal
      needs only an enabled mechanism. Chart defaults unchanged (`Settlement: {priority: []}`
      in both `values.yaml`). Chart render tests (`TESTING.md` "Chart Render Tests"; the loader
      half needs `STOREFRONT_PYTHON`): `test_the_local_release_sells_on_its_own_chain_and_the_defaults_enable_nothing`
      renders values.yaml with local-values.yaml, as `deploy-local` does, and the defaults;
      `test_the_local_release_passes_the_storefronts_startup_refusal` loads that render's
      `storefront.json` with the storefront's own loader and runs the real refusal,
      `require_publishable_storefront()` -- `publication_startup_problems` and, since 10.18,
      the retired-settings check beside it -- with no problem, and over the defaults' render it
      reports "no settlement mechanism is enabled under [Settlement]". With the overlay's
      mechanisms disabled (edited, then restored) both fail. `make -C helm test-render` with
      `STOREFRONT_PYTHON` passed, these run, not skipped. Evidence of a render the storefront
      accepts at its refusal, not of a running release: the steps after the refusal need the
      cluster, which validation's Helm part (`make validate-helm`, deploying `deploy-local`)
      exercises. `DEPLOYMENT_AND_CONFIG.md` at 17.9.
      **Corrected (round 08, 08 F1, F7):** `/app/alkahest_anvil_addresses.json` was not "the
      image's address book": the VM image carries no such file and the chart mounted none, so
      the release started but derived no Alkahest listing, which a refusal-only check cannot
      see. 10.20 mounts the dev-env chart's copy and derives the release conditions over the
      render, and 10.27 removes the repeated agent (agents are keyed by name); the first test
      named here is renamed there.
- [x] 10.8 (05 F1) **Per-site fulfillment trust.** `build_fulfillment_client` gives each per-site
      `ComputeProvisioningClient` its site's peer provider from `ServicePeerTrust`, as the capacity
      clients have; `[provisioning.identity]` stays only on the provisioning-service client
      (`fulfillment_service.py` `_provisioning_client`). Correct 10.2's text, which widened the
      exception beyond D14b. Tests: a rotation moves fulfillment response verification; one site's
      principal is refused on another site's fulfillment responses.
      Done. `build_fulfillment_client(capacity_client, *, client_factory=None)` gives each
      site's `ComputeProvisioningClient` `site_authorities(site)` of the trust the capacity
      runtime's site clients read (`_capacity_runtime_state["service_peer_trust"]`, which the
      root binds to its `ServicePeerTrust`; created at import, so a client built before any
      runtime fails closed), keyed by that binding and the factory, no principal.
      `get_provisioning_authorities` is now read only by `fulfillment_service._provisioning_client`;
      `capacity_client` no longer imports it, so four test modules that patched it there
      (`test_listings_api.py`, `test_settle_controller.py`, `test_sync_negotiation_seller_round_hook.py`,
      `test_order_pause_state.py`) drop the patch. 10.2's text is corrected beside it. Tests in
      `tests/integration/test_site_trust.py` (10.14; the production builder with each site's
      provisioning transport replaced by a fake answering a fulfillment status read signed as
      the site's current principal): before the rotation only the current principal verifies,
      during the overlap either, after completion only the replacement, the other site
      untouched; each site's principal is refused on the other's fulfillment responses. With
      every site's client given one site's provider (module edited, then restored) both tests
      fail.
- [x] 10.9 (06 F2) **Capacity events refresh buckets inline.** Capacity-event reconciliation calls
      `refresh_site(site_id, families=[CAPACITY_BUCKET])` before deriving candidates and never wakes
      publication (refresh-and-reconcile); a failed fetch keeps the generation stale and reconciles
      over what is held. Add the row to `design.md` D4 and a scenario to the storefront-publication
      delta. Regression test (application integration): change availability and emit a reserving
      event without stepping `site-projections` — the backed fungible listing closes; release —
      it reopens. Keep the existing explicit-refresh test.
      Done. `services/capacity_client._capacity_reconciler` refreshes the capacity-bucket
      family of the delta's site -- every configured site's for a full reconcile, whose delta
      is none -- through `refresh_site(site, families=[CAPACITY_BUCKET])` before it derives
      anything; `refresh_site` wakes nothing and never raises, so a failed fetch leaves the
      held generation stale and the reconcile runs over it. `design.md` D4 gains the table row
      and a paragraph with the rejected alternative; the storefront-publication delta's
      "Projection-backed listing candidate derivation" gains a sentence and the scenario "A
      capacity event arrives before the next poll". Application integration through
      `StorefrontClient`, over `tests.publication_app`:
      `test_publication_loop.py::test_a_capacity_event_reconciles_on_the_buckets_current_with_it`
      -- availability set to 0 and a `reserved` event emitted, `capacity-events` stepped with
      no `site-projections` step: the backed fungible listing is closed by reconciliation;
      availability 1 and `released`: reopened; no publication wake recorded. With the refresh
      removed (module edited, then restored) it fails. The explicit-refresh test
      (`test_a_capacity_event_acts_only_on_backed_listings`) is kept.
- [x] 10.10 (05 F3) **Registry discovery switch removed.** `enable_registry_discovery` is no
      longer read; registry publication is always on, so the startup refusal checks the registry
      and its authority pin unconditionally. A configuration stating the key refuses startup naming
      it as removed (refusing, not ignoring, so an operator who turned publication off is not
      silently switched on); add it to `RETIRED_KEYS` and regenerate both schemas. Reword D6's
      parenthetical; update tests that set the switch.
      Done. VM no longer reads the switch: `settings.toml` and the `config init` template drop
      it, `publication_service.build_publication_runtime` passes `enabled=True`, and the
      startup refusal checks the registry and its pin unconditionally. The key is retired in
      the new catalogue `market_storefront/retired_settings.py` (`REMOVED_SETTINGS`, in
      `RETIRED_KEYS`, 10.18): stated with any value it refuses startup, "enable_registry_discovery
      was removed: …", under the retired-settings heading; `make helm-values-schema`
      regenerated both schemas, which refuse it in any spelling. D6 reworded, with the
      decision. Tests that set the switch drop it (`test_startup_refusal.py`,
      `test_publications_wiring.py`, `test_admissibility_default_composition.py`,
      `test_publishable_startup.py`); those that turned it off to publish nowhere now publish to
      the two recorded test registries through the new `tests.publication_app.recorded_registries()`
      (`test_fulfillment_service.py`, `test_listings_api.py`, `test_admin_api.py`), and so does
      the publication harness, whose default was registries off: its `registries` parameter
      goes and it always records. `test_listings_api.py`'s seeded listings name the configured
      storefront URL, so `test_resume_returns_registry_status` now reads `published` where it
      read `disabled`. Unit: `test_startup_refusal.py` -- the switch stated true or false is
      refused and the registry is still checked. Application startup (real app and lifespan):
      `test_publishable_startup.py` "the removed registry switch". Chart render:
      `test_the_removed_registry_switch_is_refused_in_any_spelling` (fails against the schemas
      before regeneration). CLI unit: 10.18. The API-credit storefront keeps its own
      `enable_registry_discovery`: it derives no listings from site projections, so D6's
      refusal does not cover it.
- [x] 10.11 (06 F4) **Per-site capacity-event outcomes.** `run_capacity_event_pollers` (kit) records
      each per-site timer cycle's outcome through a callback the controller provides, under a
      per-site loop name in the snapshot, keeping the per-site cursor lock; the aggregate step keeps
      its aggregate outcome. VM composes it; a status test shows a failing site feed. Bump the kit
      and move pins. Section 15's API-credit pollers reuse it.
      Done. Kit capacity-publication: `SiteEventCycle.exception` (the exception ending a
      failed cycle, never in `to_dict()`); `site_events_poller(record=)` is called with every
      cycle it ran, after the cursor lock is released (a held cycle ran nothing and reports
      nothing); `CapacityRuntime.poll_events(record=)` takes a per-site factory, as `paused`
      is; `run_capacity_event_pollers(record_site_cycle=)` hands it through; `SiteEventCycle` is
      exported. Kit storefront: `StorefrontLoopController.record_cycle(name, *, error=None,
      trigger="timer")`, recording as `run_cycle` records (a failure in stage `run`, its
      message only for a disclosed type) under any name, so the snapshot reports it beside the
      declared gate's state. VM: `lifecycle.capacity_site_cycle_recorder(site)` records under
      `capacity_events_poller:<site>`, passed by `capacity_events_poller_loop`, which now polls
      the container's runtime -- the one the `capacity-events` step drains -- falling back to the
      cached builder, and reads its interval through `site_projection_poll_interval()` (10.12).
      The aggregate step keeps its outcome; the aggregate loop records none. Versions:
      `arkhai-kit-capacity-publication` 0.10.0 (pinning core `==0.15.1`, 10.13),
      `arkhai-kit-storefront` 0.6.0; the VM, bare-metal, API-credit storefronts' and the
      provisioning service's exact pins follow. market-composition delta: the fan-out clause
      and the scenario "One site's capacity-event feed fails"; D6 records the decision. Tests:
      kit unit, `make -C kit test-capacity-publication` 97 passed (three new in
      `test_capacity_event_pollers.py`: each site's poller reports every cycle with the
      exception ending a failed one, another site's its own; a held poller reports nothing
      while a step for its site still runs; the aggregate hands each site's recorder to the
      fan-out); kit unit, `make -C kit test-storefront` 101 passed (one new: an outcome recorded
      under a per-site name, disclosed by the rule, in the snapshot beside the declared gate).
      VM application integration through `StorefrontClient`, over `tests.publication_app`:
      `test_lifecycle_status.py::test_a_sites_failing_capacity_event_feed_is_reported_under_its_loop`
      -- the site unreachable, the pollers started by startup's `_start_capacity_events_poller`,
      the controller's failure log observed through a logging handler (no wait on time), then
      `get_system_status()` reports `capacity_events_poller:site-a` running with a failed timer
      outcome `{"type": "SiteCapacityClientError", "message": None}` and the aggregate with no
      outcome. `test_loop_gate_wiring.py`'s three capacity-poller cases inject their fake
      runtime through the container instead of patching `build_capacity_runtime`, the fake
      taking `record`. Section 15's API-credit pollers can pass the same recorder.
- [x] 10.12 (06 F3) **Poll interval validated.** `site_projection_poll_interval()` applies the
      positive, finite rule (zero refused, not defaulted); startup validates the interval and the
      derived window before anything runs. Tests: zero, negative, non-numeric, `nan`, `inf`, window
      unset.
      Done. `utils.config.site_projection_poll_interval()`: unset is five seconds; a stated
      value goes through `_positive_seconds`, so zero (no longer defaulted), negatives, text,
      a boolean, `nan`, and `inf` are refused naming `capacity.poll_interval`, and the derived
      window inherits only a usable interval. `capacity_events_poller_loop` read the interval
      itself, defaulting zero to five; it now reads this. Startup's
      `_require_source_confirmation_window` checks the interval and then the window, before any
      loop starts. **Differed:** it stays a startup step, as it was, after the database opens,
      rather than move into the pre-database refusal; nothing reads either value before it.
      Unit (`test_listing_source_check.py`): eight values with the window unset, each refused by
      key from `site_projection_poll_interval`, `source_confirmation_seconds`, and the startup
      step; unset gives five and a fifteen-second window. Application startup: 10.16's lifespan
      case stops at this step on `poll_interval = 0`.
- [x] 10.13 (05 F4) **Trust reload never masks a commit.** In `ServicePeerTrust`, a reload failure
      after a committed change is logged, never raised; the commit's result or refusal is returned;
      the trust is marked stale and the next verification or callback check retries the reload.
      `register_subject` is routed through the trust. Library integration test forcing a reload
      failure after a commit.
      Done. `core_storefront.service_peers.ServicePeerTrust.reload_after_change()`, called by
      the trust's identity authority after every change -- `register_subject` now among them --
      catches any failure, logs it, and marks the trust stale; the change's own result or
      refusal is what the call returns or raises. While stale, a read (`_site_status`, behind
      both the site provider and the callback check) reloads first and, while that fails,
      refuses with a 503 `AuthError`, so nothing verifies against records that predate a
      committed change. The load is factored into `_read_sites`. `arkhai-core-storefront`
      0.15.1; VM requires `>=0.15.1`. Library integration
      (`core/storefront/tests/integration/test_service_peers.py`, three new, through a test
      subclass whose `_read_sites` fails while armed, as `ARCHITECTURE.md` permits a narrow
      persistence interface to be paused): a rotation whose reload failed returns, durable state
      holds it, reads refuse 503 until the reload succeeds and then follow the rotation; a
      disable whose reload failed leaves its principal untrusted; a refused `register_subject`
      raises its own refusal. With the catch narrowed and the stale retry removed (module
      edited, then restored) all three fail. `make test-core`: core storefront 216 passed, 2
      skipped.
- [x] 10.14 (05 F5) **Site-trust test at its stated level.** Run the real app with its lifespan (the
      trust startup seeds), observe response verification through a storefront operation that
      calls the site, send `capacity_released` signed by the old principal after the overlap
      (refused) and the new one (accepted), reset state only through public seams; fix the
      docstring. If the lifespan cannot run without a reachable provisioning service, keep the
      router-level test and label it honestly.
      Done at the router level, labelled so. The lifespan cannot run here without a reachable
      provisioning service: startup's `preflight_provisioning` probes
      `provisioning.service_url` over the network with real waits, and its projection load and
      capacity-event pollers reach the sites through the root's runtime, which takes no
      transport. `tests/integration/test_site_trust.py` is rewritten and its docstring says
      what it is: router-level application integration -- the admin router behind both
      authentication middlewares, over the production capacity runtime, fulfillment client
      builder, projection state, and a trust seeded as startup seeds it, injected through the
      container. Verification is observed through storefront operations: a `site-projections`
      cycle through `admin_run_lifecycle_cycle` (the poll's signed answer verifies, or the
      site's family turns stale with its error) and a fulfillment status read (10.8). After the
      overlap a `capacity_released` callback through the typed client
      (`notify_capacity_released`) signed by the retired principal is refused (403, before any
      handler) and one signed by the replacement is applied, releasing a reservation at the
      site. State is reset only through public seams: a fresh client factory keys a fresh
      runtime and trust binding, container fields are restored, and settings go through
      `settings_overrides` and `replaced_setting`; no private module state is touched. Two
      cases pass.
- [x] 10.15 (05 F6) **No module patches in the composition test.** Inject the peer configuration
      and trust into the composition root (production defaults) instead of patching
      `server.get_service_peer_configs`, `server.ServicePeerTrust`,
      `server.require_publishable_storefront`; assert "no database" through the file's absence, not
      `sqlite_module._sqlite_client`; move `_replaced_setting` to a public test utility.
      Done. `server.VmCompositionSeams(service_peer_configs, service_peer_trust,
      startup_refusal)`, production's by default, is taken by `build_vm_storefront_app(...,
      seams=)` and `_build_vm_services`; `test_server_app_composition.py` passes one instead of
      patching `server.get_service_peer_configs`, `server.ServicePeerTrust`, and
      `server.require_publishable_storefront`, and asserts the configured peers reach the one
      trust. `test_publishable_startup.py`'s refused cases assert no database by the file's
      absence and no longer reset or read `sqlite_module._sqlite_client`. `_replaced_setting`
      becomes `tests._settings_overrides.replaced_setting`, documented, and its five importers
      follow. The composition test's other module patches predate Section 10 and stay.
- [x] 10.16 (05 F7) **Empty settlements start.** If cheap, a lifespan case with empty
      `[pricing].settlements` passing the refusal and reaching the database open; otherwise record
      the disclosed split as accepted.
      Done. Application startup, the real app and lifespan:
      `test_publishable_startup.py::test_a_storefront_whose_terms_live_in_its_pools_starts` --
      with `[pricing].settlements` empty the refusal passes and the lifespan opens the
      storefront's database (the file exists), then stops at the next startup check, a
      `poll_interval` of 0 (10.12), because the steps after it reach the network; no loop
      starts. The case isolates the process's SQLite client (reset to none, restored), which
      the lifespan creates and does not own clearing. That such a storefront publishes under its
      pools' clauses stays `test_pool_overrides_api.py`'s evidence.
- [x] 10.17 (05 F8) **Decisions recorded.** In `design.md`: the two homes for retired keys (beside
      C4), `[provisioning.identity]` only for the provisioning client (D14b), and this round's
      decisions (local-values settlement, capacity-event inline refresh in D4, the removed
      discovery switch in D6, per-site poller outcomes in D6). Name each destination in 17.9:
      `DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through configuration" (retired keys,
      removed switch, local-values settlement), storefront-publication architecture "Trusted site
      routing", the storefront-publication and market-composition deltas.
      Done. `design.md`: C4's "Two homes for retired keys" (now one catalogue for the
      storefront's own keys, 10.18); D14b's as-delivered note (every site client on the site's
      peer, `[provisioning.identity]` only for the provisioning-service client, the stale-trust
      rule); D4's capacity-event row and paragraph; D6's reworded refusal and its "Decided with
      the owner, 2026-10-16" list (the removed switch, the retired-settings heading, per-site
      poller outcomes, the local release's settlement). 17.9 names the destinations.
- [x] 10.18 (05 F9, F10, F11) **Smaller fixes.** `market-storefront config set` refuses every key in
      `RETIRED_KEYS`, naming its replacement, and the duplicate `_RETIRED_INVENTORY_KEYS` goes (unit
      test: `config set claims_sweep_interval` refused naming `settlement_servicing_interval_seconds`);
      the startup refusal reports retired-key problems under their own heading, separate from
      publication problems, docstring and test text updated; remove the unused
      `container.service_peer_trust()`; add a 17.10 note to confirm `startup_refusal.py`'s docstring
      citation resolves after the archive.
      Done. `market_storefront/retired_settings.py` is the one catalogue: the inventory keys,
      `RENAMED_SETTINGS`, `REMOVED_SETTINGS`, `RETIRED_KEYS`, `retired_setting(key)` (any
      spelling, a key under a retired table included), and `retired_setting_explanation`; it
      imports only the standard library, so the command line reads it without loading the
      storefront. `values_schema.RETIRED_KEYS` is it; `market-storefront config set` refuses
      every retired key with its explanation, and `_RETIRED_INVENTORY_KEYS` goes (CLI unit,
      `tests/unit/cli/test_config.py`: `claims_sweep_interval` in two spellings refused naming
      `settlement_servicing_interval_seconds`, `enable_registry_discovery` refused as removed,
      the inventory case unchanged). `utils.config`'s `RENAMED_SETTINGS` and
      `renamed_setting_problems` move to the catalogue and `startup_refusal.retired_setting_problems`;
      `require_publishable_storefront` reports "the storefront states retired settings: …"
      and "the storefront cannot publish: …" as separate sections, and
      `publication_startup_problems` reports publication problems only; module docstring and
      tests updated (`test_startup_refusal.py`, `test_config_loader.py`,
      `test_publishable_startup.py`, whose cases each assert their heading and not the other).
      `container.service_peer_trust()` removed. 17.10 carries the docstring citation note.
- [x] 10.19 Validation for the round: VM storefront frozen, kit capacity-publication, core storefront,
      `make -C helm test-render` with `STOREFRONT_PYTHON`, `make helm-values-schema` committed,
      `make -k test` plus the frozen projects, packaging, hygiene, citations, `openspec validate
      --strict`; then a fresh-context check and the gate question for reviews 05/06.
      Done, except the fresh-context check and the gate, which the orchestrator runs. VM
      storefront frozen with the rebuilt core, capacity-publication, and kit-storefront wheels
      reinstalled (`UV_FROZEN=1 make test-unit test-integration`): unit 1069 passed, 1 skipped;
      integration 444 passed (application integration and application startup; `test_alkahest`
      against Anvil included). `make -C kit test-capacity-publication` 97 passed and `make -C
      kit test-storefront` 101 passed (unit); `make test-core`: core storefront 216 passed, 2
      skipped (library integration among them). `make helm-values-schema` regenerated both
      schemas (the one new retired pattern each), committed; `make -C helm test-render` with
      `STOREFRONT_PYTHON` passed, the loader and startup-refusal checks run, not skipped. `make -k
      test`: every suite it ran passed -- bare metal 134 + 324 + 11 + 40, API-credit storefront
      153, provisioning service 675 + 463, e2e unit 943, the Helm and deployment-packaging suites
      among them -- and it stopped only at the reinit of `kit/policy`, `domains/vms/storefront`,
      and `domains/vms/buyer` (the PyTorch index is refused here, as in 2.6), run frozen:
      `kit/policy` 80 passed, VM buyer 202 passed, VM storefront as above. Locks:
      `scripts/uv_project.py lock` relocked the nine projects locking a bumped package that
      resolve here (`core/storefront`, `kit/capacity-publication`, `kit/storefront`,
      `domains/vms/domain`, `domains/bare_metal`, `domains/bare_metal/storefront`,
      `domains/apicredits/storefront`, `provisioning/compute/service`, `e2e-tests`); VM
      storefront's lock was edited by hand with the six substitutions uv wrote into bare metal's
      lock for the three packages (versions and wheel names) plus its three root specifiers
      (core floor, the two exact pins); neither `kit/policy` nor VM buyer locks any of them (16.6
      relocks VM storefront). `make check-packaging` (architecture rules included), `make
      check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
      (nothing reported), `make check-tasks CHANGE=share-site-projection-state`, and `openspec
      validate --strict` pass. No repository typing target exists. The pipeline was not run.
      **End-to-end, read from the lanes' configuration (the pipeline was not run):** every
      VM-lane scenario starts Bob's and Alice's storefronts, whose overlays state neither retired
      key and pass the refusal, and whose packaged defaults no longer state
      `enable_registry_discovery`, so each start exercises the retired-settings check; every
      deal scenario's fulfillment reads (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
      `e2e_non_erc20_settlement`) now verify against the `default` site's peer, whose principal
      the overlays also name under `[provisioning.identity]`, so the lane's trust is unchanged in
      effect; every scenario stepping `capacity-events` (`e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`,
      `e2e_non_erc20_settlement`) refreshes the site's bucket family in the step;
      and every VM-lane poller records per-site outcomes no scenario reads. Validation's Helm
      part deploys `deploy-local`, whose Bob now passes the refusal (10.7); the Helm smoke tests
      run against it. No bare-metal or API-credit scenario reaches the round's VM code; their
      storefronts take the kit and core bumps, unchanged in behaviour.

Round 05/06 handoff:

- VM's one retired-key catalogue is `market_storefront.retired_settings`; a key retired later
  goes there (and its model loses the field first, 5's handoff), and the schemas regenerate.
  Startup refuses renamed and removed keys only; the inventory keys stay schema and `config
  set` refusals.
- Every VM site client verifies against the late-bound trust in
  `capacity_client._capacity_runtime_state["service_peer_trust"]`; a new runtime key makes a
  fresh, unbound binding, which the root then binds. `build_fulfillment_client(...,
  client_factory=)` is the fulfillment seam, as `site_client_factory` is the capacity one.
  Bare metal's 12.2 needs the same for its per-site `ComputeProvisioningClient`s.
- `ServicePeerTrust.reload_after_change()` is the post-change reload; `reload()` still raises
  and is what seeding and a deliberate reload use. A test pauses the load by overriding
  `_read_sites` in a subclass.
- The capacity-event recorder: Section 15's API-credit storefront can pass
  `record_site_cycle=` a per-site `controller.record_cycle` wrapper as VM's
  `lifecycle.capacity_site_cycle_recorder` does. `capacity_events_poller_loop` now polls the
  container's runtime, so a test injects its runtime there, not by patching
  `build_capacity_runtime`.
- `server.VmCompositionSeams` is where further root seams belong; the composition test still
  patches the root's other builders (pre-existing).
- `tests.publication_app` always publishes to two recorded registries
  (`recorded_registries()`, usable alone); a test that closes or reopens a listing outside the
  harness needs it, since publication no longer runs without a registry.
- The API-credit storefront keeps its own `enable_registry_discovery`; D6's refusal does not
  cover it (it derives no listings from site projections). Section 15 renames only its interval
  key.

### Round 08 triage fixes (owner dispositions 2026-10-18)

Review 08 (`reviews/08-implementation.md`, of `8f5d102`) and validation 09 (`reviews/09-validation.md`,
same commit: pipeline passed in all three lanes; Helm deployment not run, no cluster) were triaged
together; dispositions in `reviews/08-implementation.triage.md`. The gate for reviews 05/06 passed
2026-10-18. The owner directed: make these fixes as one commit, run `make test` (with the frozen
projects), and begin Sections 11–14 with no end-to-end run or further review first.

- [x] 10.20 (08 F1) **The local release's Alkahest address book is mounted.** The storefront chart
      gains an optional address-book ConfigMap mount per agent, as the bare-metal chart's
      `alkahestAddressBook` already does; the local release mounts the development Anvil address
      book (a chart-carried copy of `kit/alkahest`'s deterministic Anvil file, marked development
      only), and both `alkahest_address_config_path` and `[Settlement.alkahest].address_config_path`
      name the mounted path. Extend the `STOREFRONT_PYTHON` render check to derive Bob's release
      conditions over the local render (not only the startup refusal), keep the chart's assertion
      that every configured address path is mounted, rename the over-claiming test, correct 10.7's
      note. Record for 17.9 (`DEPLOYMENT_AND_CONFIG.md`) which keys `arkhai-bob-runtime` must carry
      for `deploy-local` to sell under Alkahest.
      Done. The storefront chart's agent takes `alkahestAddressBook` (`configMapName`, empty
      mounting nothing; `key`, default `alkahest_addresses.json`; `mountPath`, default
      `/etc/arkhai/alkahest`), typed in both schemas as the bare-metal chart types its own, and
      the Deployment mounts that ConfigMap's key read-only at `<mountPath>/<key>`. **Placed (not
      named by the task):** the ConfigMap is the dev-env chart's,
      `<release>-dev-env-alkahest-addresses` from `helm/charts/dev-env/files/alkahest_anvil_addresses.json`,
      since that chart deploys the Anvil state the book describes (`dev-env/generate_state.py`
      writes both); its template's comment marks it development only, naming nothing on a public
      network (JSON carries no comment). `helm/local-values.yaml` mounts it, and both
      `Chains.anvil.alkahest_address_config_path` and `[Settlement.alkahest].address_config_path`
      name `/etc/arkhai/alkahest/alkahest_anvil_addresses.json`; the EVM fixture, which named the
      same unmounted `/app` path, mounts it too. Chart render tests (`TESTING.md` "Chart Render
      Tests"; the probe half needs `STOREFRONT_PYTHON`, set to VM's environment, and ran):
      `test_an_agent_mounts_its_named_address_book_read_only`;
      `test_the_local_release_names_only_the_dev_chains_mounted_address_book` -- every
      configured address path is the mounted `<mountPath>/<key>`, the release renders that
      ConfigMap, and its content equals `kit/alkahest`'s file (the copy's drift check); the EVM
      fixture's test asserts the same; `test_the_local_release_enables_alkahest_and_contact_exchange_and_the_defaults_nothing`
      (renamed from `..._sells_on_its_own_chain_...`, which over-claimed);
      `test_the_local_release_starts_and_derives_its_alkahest_release_conditions` (replacing the
      refusal-only test) runs the storefront's `require_publishable_storefront()` and then
      `demands_for_publication_clauses(settlement_publication_defaults(), wallet_address=get_evm_wallet_address())`
      over the local render's `storefront.json`, the mounted file re-rooted under a temporary
      directory because the probe runs outside the pod, and asserts one condition on `anvil`:
      the mounted book's recipient arbiter, paying Bob's wallet; over the defaults the refusal
      still names "no settlement mechanism". With the chain's path back at `/app/...` (edited,
      restored) the mount assertion fails and the probe raises `FileNotFoundError` for it, as 08
      F1 reproduced. Still render evidence, not a running release (16.5). For 17.9:
      `arkhai-bob-runtime`'s `storefront.secrets.toml` must carry `[Wallet] private_key`, Anvil
      account 2's published development key and never one for a public network, for
      `deploy-local` to build Bob's Alkahest client; `[registry.auth]` only for a registry that
      requires write keys, which the local registry does not.
- [x] 10.21 (08 F2) **Lease termination per site; `[provisioning.identity]` retired.** VM's
      `terminate_vm_lease` routes through the per-site fulfillment aggregate by the site that holds
      the reservation, as bare metal's teardown does (`site_clients.terminate_lease`), verifying
      against that site's peer; it stays the plumbing `vm-storefront-fulfillment` requires for a
      future buyer-requested early termination (buyer → storefront → site). `_provisioning_client`
      and every reader of `[provisioning.identity]` go; the key joins the retired-settings
      catalogue (stating it refuses startup naming it); the chart's provisioning-principal check
      moves onto the site's service peer; the lane overlays, chart values, and fixtures drop it;
      D14b's exception is removed. Test: termination reaches the reservation's own site and its
      response verifies against that site's peer.
      Done. `AggregateFulfillmentClient.terminate_lease(capacity_reservation_id, *, site_id,
      reason=None)` sends `LeaseTermination` to that site's client alone, as
      `begin_fulfillment_teardown` addresses its recorded site;
      `fulfillment_service.terminate_vm_lease(fulfillment_client, *, capacity_reservation_id,
      site_id, reason=None)` takes the storefront's per-site fulfillment client
      (`build_fulfillment_client`) and the site the deal's records bind the reservation to, and
      returns the site's `LeaseView`; it still has no caller (its docstring says so, citing
      `vm-storefront-fulfillment`). **Decided (signature):** the site is the caller's, as every
      record-bound VM fulfillment call passes it, rather than read from the in-memory
      `reservation_sites` cache; and the client is passed in, so the router-level test reaches
      the fake site transports through `build_fulfillment_client`'s factory seam.
      `_provisioning_client` and `utils.config.get_provisioning_authorities` are gone; the
      packaged `settings.toml`, the `config init` template, and both lane overlays drop
      `[provisioning.identity]`; `retired_settings.REMOVED_SETTINGS` gains it (stated, in any
      spelling, it refuses startup under the retired-settings heading, "provisioning.identity was
      removed: ...", and `config set` refuses it); `make helm-values-schema` regenerated both
      schemas, which refuse it. The chart's provisioning check is the existing service-peer one
      alone (`_helpers.tpl`); `values.yaml` and the fixtures drop the set. D14b's exception is
      removed (design.md, with the decision). Tests: unit
      `test_fulfillment_service.py::test_terminate_vm_lease_asks_only_the_reservations_site`
      (only the named site is asked, not the cached one; the reason passes through), the fakes of
      a `ComputeProvisioningClient` the module no longer uses dropped from two tests;
      application integration, router-level as 10.14,
      `test_site_trust.py::test_a_lease_terminates_only_at_its_sites_and_verifies_against_its_peer`
      -- through the production `build_fulfillment_client`, the termination reaches only the
      `away` site's fake provisioning surface with its reason and returns its lease, and the
      same answer signed by the `home` site's principal is refused
      (`ComputeProvisioningAuthenticationError`); unit `test_startup_refusal.py` (the set
      refused, publication unaffected); CLI unit `test_config.py` (`config set
      provisioning.identity.principals` refused); application startup
      `test_publishable_startup.py` "the removed provisioning trust set" (replaced at its root:
      a dotted override left an empty `provisioning.identity` table behind, which refused the
      next test); chart render `test_the_removed_provisioning_trust_set_is_refused_in_any_spelling`
      and a release-check case for a service peer lacking the release's principal. Tests that set
      the set to no effect drop it (`test_config_loader.py`, `test_remote_capacity_client.py`,
      `tests/publication_app.py`, `test_negotiate_controller.py`).
- [x] 10.22 (08 F3) **`proposal.md` current.** Amend What Changes and Impact: the `core/storefront`
      and `core/storefront-client` changes; the removed registry switch's and
      `[provisioning.identity]`'s startup refusals; `deploy-local` enabling Alkahest and contact
      exchange with its address book; per-site lease termination; the storefront chart's `agents`
      map (10.27).
      Done. What Changes gains the removed registry switch's and `[provisioning.identity]`'s
      refusals, per-site lease termination, the trust's failed-reload rule, and "A local Helm
      release that sells" (the address book and the `agents` map); Impact gains `core/storefront`
      (`ProjectionCache`, `ServicePeerTrust`, `HealthResponse.lifecycle`) and
      `core/storefront-client` (`HealthResponse.lifecycle`; checked against the branch's diff,
      nothing else changed there), the kit controller's fan-out children, the charts' changes
      (storefront and umbrella 0.3.0, dev-env's ConfigMap), and the deployment consequences.
- [x] 10.23 (08 F4) **Per-site loop state follows the fan-out.** A per-site capacity-event loop
      reports the aggregate fan-out's terminal state once it has ended (e.g. per-site names declared
      as children of the aggregate loop). Kit unit test: a fan-out ending while sites are declared.
      Done. `StorefrontLoopController.declare(name, *, parent=None)`: a name declared with the
      loop whose task runs its cycles reports that loop's `exited` or `cancelled` once its task
      has ended (in `states`, `snapshot`, `failed_loop_names`, and `loops_check`), and a pause no
      longer waits for it; a name declared alone behaves as before (the API-credit storefront's
      `loops.declare(name)` is unchanged; Section 15 can pass `parent=`). VM:
      `lifecycle.capacity_site_gate(site)` declares `capacity_events_poller:<site>` as the child
      of `capacity_events_poller`, and `capacity_events_poller_loop` passes it as the fan-out's
      `site_gate`; the unused `declare_and_gate` goes. Kit unit (`test_lifecycle_controller.py`,
      `TestAFanOutsChildrenFollowItsEnd`, three): a fan-out that declares two sites and raises
      leaves both `exited` beside it and named as failed; a pause with an unbounded quiescence
      window returns at once over an ended fan-out's child; a cancelled fan-out's child reports
      `cancelled`, having reported `running` before.
- [x] 10.24 (08 F5) **Per-site recorders only.** Replace the general `record_cycle` with recorders
      the controller issues only for names declared through the fan-out, so a loop the controller
      runs cannot be written to. Kit unit test.
      Done. `record_cycle` is replaced by `StorefrontLoopController.cycle_recorder(name)`, which
      returns `record(error=None)` only for a name declared with its parent, and raises
      `ValueError` for any other name -- one never declared, one declared alone, and one the
      controller runs as a loop or a step even if declared as a child. A recorder carries the
      generation it was issued in, so after `clear_loops` it records nothing. VM's
      `capacity_site_cycle_recorder(site)` takes the site's recorder (the fan-out calls the gate
      factory first, so the name is declared). `arkhai-kit-storefront` 0.7.0 (an incompatible
      removal); the VM, bare-metal, and API-credit storefronts' exact pins follow. Kit unit: the
      per-site recording test now records through issued recorders;
      `test_only_a_fan_outs_declared_child_is_issued_a_recorder` and
      `test_a_recorder_records_nothing_once_its_fan_out_is_torn_down` (new). VM's
      `test_lifecycle_status.py::test_a_sites_failing_capacity_event_feed_is_reported_under_its_loop`
      passes unchanged over the new wiring.
- [x] 10.25 (08 F6) **Stale trust never blocks the loop.** On a failed reload after a change,
      `ServicePeerTrust` holds nothing (`_sites = None`), so every read refuses with 503 from memory;
      the stale flag and the synchronous retry on reads go; a background reload retries with backoff
      off the event loop until it succeeds. The reload lock stays, ordering reloads so a slower
      reload can never install an older snapshot. Correct the `site_authorities` docstring. Test: a
      read during the outage returns at once without touching SQLite; the trust recovers after the
      background reload.
      Done. `ServicePeerTrust.reload_after_change()`: a failed load sets `_sites = None`, so
      every read refuses with the 503 "not loaded" `AuthError` from memory, and starts one
      background retry if none is pending; the stale flag and `_reload_if_stale` are gone, and no
      read touches SQLite. The retry waits `RELOAD_RETRY_FIRST_SECONDS` (0.5), doubling to
      `RELOAD_RETRY_MAX_SECONDS` (30), and reloads under the reload lock until one succeeds; a
      burst of failed reloads starts one retry. The lock stays: every reload reads durable state
      while holding it, so loads install in the order they ran. Seams, by constructor:
      `retry_wait` (default `time.sleep`) and `start_retry` (default a daemon thread). The class
      and `site_authorities` docstrings now say reads touch only memory and when they refuse.
      `arkhai-core-storefront` 0.15.2; `arkhai-kit-capacity-publication` 0.10.1 pins it exactly,
      and the VM, bare-metal, API-credit storefronts' and the provisioning service's exact pins
      follow; VM requires `>=0.15.2`. Library integration
      (`core/storefront/tests/integration/test_service_peers.py`, over the test subclass whose
      `_read_sites` fails while armed and counts its reads, with the retry captured rather than
      started): a rotation whose reload failed returns, every read then refuses 503 with no
      durable read attempted, and the captured retry reloads and the trust follows the rotation;
      a retry failing three times waits 0.5, 1, 2, and 4 seconds and then succeeds, a second
      failed change meanwhile starting no second retry; a disable whose reload failed trusts
      nothing until the retry, then refuses the principal as not active; a refused change still
      raises its own refusal.
- [x] 10.26 (08 F8) **Comments.** `scripts/validate_slice.py:64-66` names what the Helm release still
      lacks (touch only that comment); `test_site_trust.py`'s docstring says the fulfillment client
      the storefront builds is called directly.
      Done. `scripts/validate_slice.py`'s Helm comment names what the release lacks (a second
      storefront and registry, the API-credits and bare-metal services, Mailpit forwarding) and
      that the local release enables Alkahest and contact exchange; the `NOT_SERVED` string
      beside it still says "no settlement mechanism", left as directed (only the comment). The
      `test_site_trust.py` docstring says the built fulfillment client is called directly, for
      the status read and the lease termination. The `site_authorities` docstring rides 10.25.
- [x] 10.27 (08 F7) **The storefront chart's `agents` is a map keyed by agent name.** Helm merges maps
      key by key but replaces lists, so every overlay restated Bob's whole agent. Convert
      `storefront.agents` (umbrella and storefront chart) to `agents: {<name>: {...}}`: templates
      range over name/value, the generated values schema types map values, and the list shape is
      refused naming the new shape. Slim `helm/local-values.yaml` and the four fixtures
      (`eip191-evm-values.yaml`, `payments-ed25519-values.yaml`, `contact-exchange-values.yaml`,
      `invalid-missing-identity-secret-values.yaml`) to only what they change; update render tests,
      any scripts or e2e Helm configuration that read the list, and record for 17.9
      (`DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through configuration") the map shape and
      the guidance that a chart value overlays change per entry is keyed, not listed. Section 16's
      bare-metal chart keeps its one-agent-at-top-level shape (C8).
      Done. Every storefront template ranges over `name, entry` and gives the entry its key as
      `name` (`mergeOverwrite`, with an empty `secret` so an agent may omit its overlay); the
      smoke test and the umbrella's test configuration select `targetAgentName` or else the first
      agent by name. Both schemas: `agents` (and `storefrontAgent`) is an object of agents, at
      least one, each refusing `name` (its key is its name); a list is refused by an `if`/`then`
      whose message names the map ("agents is a map keyed by agent name, such as agents: {bob:
      {port: 8001}}, not a list"), since a schema error carries no other text. **Differed
      (found):** the storefront subchart now ships `agents: {}`, its old default agent kept as a
      commented example, because Helm does not remove a subchart's default from a parent's values
      with null (tried: `bob: null` left the subchart's `bob`), so a parent could never drop or
      replace it; the umbrella's `values.yaml` declares Bob. The storefront chart and the
      umbrella go to 0.3.0 (the values contract changed). `helm/local-values.yaml` and the four
      fixtures state only what they change: the EVM and payments fixtures now overlay Bob rather
      than replace him with `evm-bob` and `payments-bob` (their `provisioning.storefront.agentName`
      goes; the Secret names `test-render.sh` checks are unchanged; resource names are now
      `-storefront-bob`), and the missing-signer fixture blanks Bob's credential Secret name.
      `test-render.sh`'s `--set` paths read `storefront.agents.bob...`. Render tests now state an
      overlay of Bob's default agent, nulling what a case removes, so they exercise the merge an
      operator's overlay gets; new: an overlay changing one agent and adding another, a null
      removing an agent, the list refused naming the map, an entry's `name` refused. VM's
      `test_values_schema.py` reads each values file's agents merged into the umbrella's, as Helm
      renders them. `VALIDATION_RUNBOOK.md`'s `--set storefront.agents[0]...` becomes
      `storefront.agents.arkhai...` and its contact-exchange text no longer says Bob is repeated.
      No `scripts/` or `e2e-tests/` code read the list. For 17.9 (`DEPLOYMENT_AND_CONFIG.md`
      "Storefront agents: pass-through configuration"): `storefront.agents` is a map keyed by
      agent name and a list is refused naming it; an overlay states only what it changes, and
      `null` removes a key or an agent (`bob: null` drops the default agent, as a values file
      that defined its own agent in place of Bob must now say); a chart value that overlays
      change per entry is keyed, not listed; the subchart ships no agent.
- [x] 10.28 (08 F9) **Closeout note placed.** Move 17.10's post-archive citation note into 17.11
      (after the `archive` command, before the commit).
      Done: the note now sits under 17.11, marked as moved.
- [x] 10.29 Validation for the round: the affected suites, `make helm-values-schema` committed,
      `make -C helm test-render` with `STOREFRONT_PYTHON`, `make -k test` plus the three frozen
      projects, packaging, hygiene, citations, `make check-tasks`, `openspec validate --strict`. No
      end-to-end run or further review before Sections 11–14 (owner, 2026-10-18).
      Done. VM storefront frozen, with the rebuilt core-storefront 0.15.2,
      capacity-publication 0.10.1, and kit-storefront 0.7.0 wheels reinstalled (`UV_FROZEN=1
      make test-unit test-integration`): unit 1071 passed, 1 skipped; integration 446 passed
      (application integration and application startup; `test_alkahest` against Anvil included).
      `make -C kit test-storefront` 106 passed and `make -C kit test-capacity-publication` 97
      passed (unit); core storefront 217 passed, 2 skipped (library integration among them).
      `make helm-values-schema` regenerated both schemas (the `provisioning.identity` refusal;
      the `agents` map is their hand-written part), committed; `make -C helm test-render` with
      `STOREFRONT_PYTHON` passed, the loader check and the start-and-derive check run, not
      skipped. `make -k test`: every suite it ran passed -- core 123 + 134 + 217 + 62, the kits
      (capacity-publication 97, storefront 106, config 161, alkahest 296 among them),
      provisioning service 675 + 463, bare metal 134 + 324 + 11 + 40, API-credit storefront 153,
      e2e unit 38 -- except release tooling, whose
      `scripts/tests/test_multi_storefront_compose.py` read the lane overlays'
      `[provisioning.identity]`; it now asserts the overlays state none beside its existing
      service-peer assertion, and `make test-release-tooling` passed, 943. It stopped only at the
      reinit of `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch index
      is refused here, as in 2.6), run frozen: `kit/policy` 80 passed, VM buyer 202 passed, VM
      storefront as above. Locks: `scripts/uv_project.py lock` relocked the nine projects that
      lock a bumped package and resolve here (as 10.19's); VM storefront's lock was edited by hand
      with the nine substitutions uv wrote into bare metal's lock for the same three packages
      (versions, wheel names, root specifiers; neither `kit/policy` nor VM buyer locks any; 16.6
      relocks VM storefront). `make check-packaging` (architecture rules included), `make
      check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
      (nothing reported), `make check-tasks CHANGE=share-site-projection-state`, `make
      check-change-index`, and `openspec validate --strict` pass. No repository typing target
      exists. No end-to-end run and no fresh-context check here (owner, 2026-10-18; the
      orchestrator runs the check).
      **End-to-end, read from the lanes' configuration (the pipeline was not run):** every
      VM-lane scenario starts Bob's and Alice's storefronts, whose overlays and packaged defaults
      no longer state `[provisioning.identity]`, so each start passes the retired-settings check
      with it in the catalogue; their site trust is the `default` peer's as before, and the
      per-site capacity-event pollers now report as the aggregate loop's children, which no
      scenario reads. No scenario terminates a lease or fails a trust reload: those are library
      and application-integration evidence only. No lane deploys Helm; validation's Helm part
      deploys `deploy-local`, whose Bob now mounts the dev-env chart's address book and derives
      Alkahest release conditions over it, given an `arkhai-bob-runtime` Secret carrying the
      wallet key (10.20's note). No bare-metal or API-credit scenario reaches the round's code;
      their storefronts take the core and kit bumps, the API-credit storefront's per-site
      pollers still declared without a parent.

Round 08 handoff:

- Agents are keyed by name in the storefront chart and the umbrella; a values file states only
  what it changes in an agent, and `null` removes a key or an agent. The storefront subchart
  ships no agent (Helm cannot null a subchart's default from a parent), so the umbrella's
  `values.yaml` is where Bob lives. Section 16's bare-metal chart is untouched.
- An agent's `alkahestAddressBook` mounts an existing ConfigMap; the dev-env chart renders the
  Anvil book (`<release>-dev-env-alkahest-addresses`), whose copy a render test keeps equal to
  `kit/alkahest`'s. A fixture naming dev-env Services or that ConfigMap renders under the
  release name the Makefile installs (`arkhai-node-operator`), as the render tests now do.
- A render test overlays Bob's default agent: to remove a key, set it to `None`; to replace an
  agent outright, null it and add another key.
- `[provisioning.identity]` is retired in VM's catalogue; a test setting a retired table must
  replace its root (`replaced_setting("provisioning", ...)`), since a dotted override leaves an
  empty table that the refusal counts as stated.
- Fan-out children: `controller.declare(name, parent=...)` and `controller.cycle_recorder(name)`
  replace `declare(name)` plus `record_cycle`; Section 15's API-credit pollers should declare
  their sites with `parent=` and take recorders the same way (VM's `capacity_site_gate` and
  `capacity_site_cycle_recorder` are the model).
- `ServicePeerTrust(..., retry_wait=, start_retry=)` are the failed-reload seams; bare metal's
  12.x trust gets the background retry for free. A test captures the retry with `start_retry`
  and runs it when it chooses.
- `terminate_vm_lease(fulfillment_client, *, capacity_reservation_id, site_id, reason=)` is the
  plumbing a buyer-requested termination will call; it has no caller.

## 11. Bare-metal configuration through files

Delivers bare metal on `storefront.toml`, `storefront.json`, and `storefront.secrets.toml`
under VM's keys, with Compose and the lane mounting files (D14, D14a, C4, C9, C10, C11;
`deployment-state` "Independently deployable bare-metal seller role", "A storefront's
configuration reaches it through its configuration system"; `storefront-publication` "A
storefront that cannot publish refuses to start"). Touches bare metal's storefront, the
Compose files, the root `Makefile`, `e2e-tests/`, and `scripts/tests/`. Large: every
environment read changes in one commit so the lane never runs half-converted.

- [x] 11.1 `src/settings.toml` (new, packaged): defaults under VM's keys and defaults —
      `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]` (`poll_interval = 5`,
      `publication_interval_seconds = 30`), `[pricing]`, `[negotiation]`, `[Delivery]`,
      `[Wallet]`, `[Chains]`, `base_url`, `db_path`, `negotiation_timeout_seconds`,
      `negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
      `payment_reconciliation_interval`; and the site list, each site's URL and its service
      peer. `pyproject.toml` packages it and declares `arkhai-kit-config`.
      Done: `src/arkhai_bare_metal_storefront/settings.toml`, in the wheel (checked by
      listing the built wheel). Shipped: `base_url = "http://localhost:8000"`, `db_path =
      "bare-metal-storefront.db"` (bare metal's own default, relative to the image's working
      directory, its data volume; VM's default path is VM's tree), the four interval keys at
      1800/60/30/30, `[Settlement] schema_version = 1, priority = []`, `[registry] urls = []`
      and an empty `[registry.authorities]`, `[capacity]` (`placement = "fill_first"`,
      `poll_interval = 5`, `publication_interval_seconds = 30`) and an empty
      `[capacity.sites]`, `[pricing] settlements = []`; `[Identity]`, `[Delivery]`,
      `[Wallet]`, `[Chains]`, `[negotiation].policies`, and
      `[pricing].default_max_duration_seconds` are documented, commented, not shipped (C10:
      an absent bound holds the pool; Dynaconf merges lists across layers, so every shipped
      list is empty). The site list is VM's: `[capacity.sites]` maps each site to its URL, and
      each site's service peer is an `[Identity.service_peers.<peer>]` with `role`, `site_id`,
      and `principals`. `pyproject.toml` declares `arkhai-kit-config>=0.3.0` and
      `dynaconf>=3.0.0` (both imported) and raises `arkhai-core-storefront` to `>=0.13.0`
      (`core_storefront.service_peers`).
- [x] 11.2 `src/config.py` (new): the loader over `market_config.storefront_config_files()`
      with the packaged defaults and the loader's documented environment override layer,
      as VM's `utils/config.py` builds it, and typed models for bare metal's sections,
      named for their concepts (D14a). The signing credential stays
      `ARKHAI_IDENTITY_CREDENTIAL` and is never loaded into settings.
      Done. `settings_source()` builds the Dynaconf VM's loader builds (defaults file, the
      present files of `storefront_config_files()`, `merge_enabled`, no dotenv), read afresh
      on each call rather than at import, so a process or test reads the files present when
      it asks. The override layer's prefix is VM's, `STOREFRONT` (separator `__`).
      **Corrected (check):** it was first `BARE_METAL_STOREFRONT`, which read the retired
      variables still named in the chart and the documentation as settings; the owner's rule
      (follow VM) decided VM's, recorded in `design.md` D14a. Typed models:
      `BareMetalStorefrontSettings` over `StorefrontIdentitySettings` (`principal`,
      `administrators` of `AdministratorSettings`, `service_peers` of `ServicePeerSettings`),
      `RegistrySettings` (`urls`, `authorities` of `RegistryAuthoritySettings`),
      `CapacitySettings`, `PricingSettings`, `NegotiationSettings`, `WalletSettings`
      (`private_key` marked secret and kept out of `repr`), and `ChainSettings`. Section and
      key names are read in any case at each typed level (a principal's `scheme` and
      `identifier` too, which the override layer states in upper case); names inside a table
      keyed by name keep their spelling; a key the storefront does not read is ignored at
      every level, as VM's loader ignores one, so an older release starts on a newer
      configuration (**corrected (check):** typed sections first refused one; the generated
      values schema refuses a misspelling, Section 16; `design.md` D14a). `[Settlement]` is lowercased
      at every depth, as VM's `settlement_config_mapping` does, and `[Delivery]` keeps its
      spelling, as VM's does. A setting that cannot be read raises
      `BareMetalConfigurationError` naming each key path and reason, never a value.
      Helpers: `signer(credential)`, `administrator_principals()` (every subject's
      principals, one or two in all, as bare metal's admission takes them),
      `service_peer_configs()` (core's `ServicePeerConfigs` shape, ready for 12.1), and
      `registry_authorities()` (VM's exact-match pin rule over normalized URLs).
      `identity_credential()` reads `ARKHAI_IDENTITY_CREDENTIAL`, which the prefix does not
      match, so it never reaches settings.
- [x] 11.3 Every environment read moves to configuration, the variables retiring:
      `server.py` (watchdog, timeout, payment-reconciliation interval), `delivery.py`,
      `runtime.py` (chains, wallet key and address, identity, administrators, public URL,
      settlement, sites, placement, database path, negotiation policies, registry,
      servicing interval), `publication_service.py` (registry), `publication_composition.py`
      (publication clauses; it no longer receives `os.environ`), `pool_overrides.py`
      (maximum duration as `[pricing].default_max_duration_seconds`), and
      `pool_override_cli.py`. `[Settlement]` replaces the settlement JSON, `[Wallet]` and
      `[Chains.<name>]` and the overlay's wallet key replace their variables, and the
      all-or-none Alkahest input rule keeps its refusal (C11). Bare metal publishes to
      every `[registry].urls` entry (C10).
      Done; `config.py`'s credential read is the package's one environment read.
      `runtime.build_runtime_from_configuration(settings=None, *, credential=None,
      domain=None, build_chain_clients=build_alkahest_clients)` replaces
      `build_runtime_from_environment`; `storefront_signer_from_environment` and
      `_build_chain_clients_from_environment` go. The runtime carries what its consumers
      read: `negotiation_watchdog` (a `NegotiationWatchdogPolicy` from the timeout and
      interval), `payment_reconciliation_interval_seconds`, `settlement_servicing_interval_seconds`,
      `publication_clauses`, `default_max_duration_seconds`, and `registry_configuration`.
      `server._start_runtime` and the watchdog step read the runtime, so the step's
      function-local import of `server` goes. `delivery.storefront_introduction_delivery`
      takes the `[Delivery]` section. `publication_service.BareMetalRegistryConfiguration`
      holds every registry's pin (`authorities`, in configured order): its client factory
      fans out over all of them and status asks each, reporting the first that fails;
      the cycle takes `registry_urls` and the kit runtime publishes and converges every one.
      `publication_composition` reads the runtime only. `pool_overrides`'s environment reader
      becomes `positive_lease_bound`. The all-or-none rule names `[Wallet].address`,
      `[Chains]`, and `[Wallet].private_key`; `resources["wallet"]` stays the address string
      and `resources["chains"]` a mapping of chain name to its settings (Section 6's
      handoff). **Differed:** `[pricing].settlements` compile at startup, a clause that does
      not refusing startup naming the key, where the variable's clauses were compiled at each
      publication step; `parse_site_bindings(sites, peers)` takes each site's URL from
      `[capacity.sites]` and its principal from its one service peer's primary (first)
      principal, configuration-time trust until Section 12's durable state. **Also changed:**
      the image's `ENV BARE_METAL_STOREFRONT_DB_PATH` goes from `Dockerfile`: under the override
      layer's prefix it would have overridden every operator's `db_path`.
- [x] 11.4 C10: a pool whose effective maximum lease duration, through its override and
      then `[pricing].default_max_duration_seconds`, is absent or not positive is held and
      reported in the cycle's per-site report; the absent default is not a startup refusal.
      Done in `publication.BareMetalPublicationCycle._hold_unbounded_pools`: an admitted pool
      whose override's maximum, else the configured default, is absent or not positive is
      held -- its candidates are not published and its open listings neither refreshed nor
      closed -- and reported once, `hold` with `reason: pool_lease_bound_missing`, its site,
      and its pool. A non-positive default is treated as absent in the override-conflict
      check too, so such a pool is reported for its missing bound rather than as an override
      conflict. The cycle takes `default_max_duration_seconds` (was
      `configured_max_duration_seconds`).
- [x] 11.5 Startup refusal (D6), at composition: no `[registry].urls` or a registry without
      its authority pin; no enabled settlement mechanism; no configured site. (The
      one-peer-per-site refusal lands with durable trust in Section 12.) Each problem named,
      no loop started.
      Done: `src/startup_refusal.py`, VM's shape: `publication_startup_problems(settings)`
      and `require_publishable_storefront(settings)` raising `BareMetalStartupError` ("the
      storefront cannot publish: ...", every problem `;`-joined), the first step of
      `build_runtime_from_configuration`, before the signer, the settlement composition, or
      the database. Problems: `[registry].urls` empty; pins not exactly the URLs; `[Settlement]`
      unresolvable or enabling nothing; `[capacity.sites]` empty. **Differed:** the
      one-peer-per-site refusal is in place now, through core's
      `require_one_service_peer_per_site` (`[Identity.service_peers]: site ... is bound to no
      service peer`), because 11.3's site bindings take each site's principal from its peer and
      cannot be composed without exactly one; 12.1 keeps it and adds the durable seeding. No
      retired-settings catalogue: bare metal had no file configuration before, so it states no
      retired key, and it introduces neither `enable_registry_discovery` nor
      `[provisioning.identity]`.
- [x] 11.6 CLIs: `pool-override` and `publish` read the storefront's URL and identity from
      the same configuration files; `publish` still runs in-process until Section 14.
      Done. `pool-override` loads the settings and signs with `settings.signer(identity_credential())`,
      connecting to `--storefront-url`, else the configured `base_url` (whose packaged default
      is the old local fallback); its loading stays inside `_client`, under the existing
      lazy-load reason (help and the other commands load none of the client, identity, or
      configuration stack). `publish` and `redeliver-introduction` compose the runtime with
      `build_runtime_from_configuration()`; `run_publication_once` loses its `environ`.
- [x] 11.7 Development and lane files (C9): a committed development `storefront.toml` for
      bare metal (`domains/bare_metal/storefront/storefront.dev.toml`, fixture values
      commented as such) with shortened intervals as VM's overlays have, and a secrets file
      the lane writes; `domains/bare_metal/compose.yml`, `compose.bare-metal.yml`, and
      `compose.bare-metal-local.yml` mount them at `/etc/arkhai/` with `XDG_CONFIG_HOME=/etc`
      and pass only the credential through the environment; the root `Makefile`'s
      `e2e-bare-metal-dev-env` produces only bare-metal files and the variables the
      Compose files still read; `e2e-tests/Makefile` and `e2e-tests/config/config-docker.yml`
      follow.
      Done. `storefront.dev.toml` carries what the lane's variables carried (principal,
      administrator, the site and its service peer, the pinned registry, Alkahest and contact
      exchange with the 5-second retention window, `[Wallet].address`, `[Chains.anvil]`, the
      Alkahest clause, `default_max_duration_seconds = 86400`, the `bisection` seller chain),
      plus watchdog, servicing, and reconciliation intervals of 2 s and `poll_interval = 1`, as
      Bob's overlay has; every value is commented as a development value. **Differed (the
      secrets file):** the lane does not generate it: it is committed,
      `dev-env/identities/bare-metal.storefront.secrets.toml` (`[Wallet].private_key`, Anvil
      account 2's published key), as VM's `bob.storefront.secrets.toml` is, replacing
      `bare-metal.wallet.env`; the identities README follows. Compose: the domain file sets
      `XDG_CONFIG_HOME=/etc` and mounts `${BARE_METAL_STOREFRONT_CONFIG_FILE}` at
      `/etc/arkhai/storefront.toml`; the wrapper keeps the credential's env file and mounts
      `${BARE_METAL_STOREFRONT_SECRETS_FILE}` at `/etc/arkhai/storefront.secrets.toml` (required,
      as VM's overlay is); the development overlay keeps the chain wait and the address-book
      mount and loses the policy variable. `e2e-bare-metal-dev-env` names the two files and
      keeps only what the Compose files read (the storefront principal's two variables stay:
      the provisioning service binds its seller role to them); the never-read deadline
      variables and the unused constants go. `e2e-tests/Makefile` and `config-docker.yml`'s
      comments name the development storefront.toml.
- [x] 11.8 Tests. `tests/test_runtime_environment.py` becomes `tests/test_config_loader.py`
      (unit): defaults, file layering, the overlay winning, an override through the
      loader's environment layer applying and never refusing (spec scenario "An operator
      overrides a setting on a development cluster"), and the credential never in
      settings. Application integration: `tests/test_app_composition.py` — each startup
      refusal named and no loop started; `tests/test_publication_cycle.py` — a pool with no
      lease bound held and reported while others publish ("A bare-metal pool resolves no
      lease bound"). Every test that set bare-metal variables
      (`test_introduction_delivery.py`, `test_publication_cli.py`, `test_pool_override_cli.py`,
      `test_app_composition.py`) writes configuration files into a temporary
      `XDG_CONFIG_HOME` instead. `scripts/tests/test_bare_metal_compose.py` and
      `scripts/tests/test_lane_compose.py`: the storefront's environment carries only the
      credential and the configuration directory.
      Done. Shared helper `tests/storefront_configuration.py` writes `storefront.json`,
      `storefront.toml`, and the overlay under a temporary `XDG_CONFIG_HOME` and builds a
      publishable document. Unit, `tests/test_config_loader.py` (13; 14 after the check fixes): packaged defaults; each
      file layering over the one before; the overlay winning (and the wallet key out of
      `repr`); the override layer applying over every file, a principal's `@str` identifier
      included; the credential never in the settings' dump or `repr`, read apart and owning
      the principal; a missing credential named; names in any case, a site ID keeping its
      spelling; unreadable settings refused by key (a zero interval, a boolean interval, a
      bound as text, a malformed principal; an unknown key was a fifth until the check
      fixes made it ignored); administrators across
      subjects. `test_runtime_environment.py` is deleted; its composition cases move into
      `tests/test_app_composition.py` over the files (composition: the root's builder over
      real SQLite, the chain clients injected through `build_chain_clients` instead of the
      old module patch): principal, administrators, and the site's peer principal; a
      mismatched credential; the credential from its variable; every interval and term; the
      default and an unknown seller chain; every configured registry reaching the fan-out;
      clauses that do not compile; Alkahest composing (enabled and disabled), each of the three
      inputs required, each refused without a section, the undeliverable release model; the
      contact-only root. Application startup (the real app and lifespan from the files):
      `test_a_storefront_that_cannot_publish_refuses_to_start`, five cases -- no registry
      (spec "A bare-metal storefront has no registry"), an unpinned registry, no mechanism, no
      site, a site with no peer -- each `BareMetalStartupError` naming its problem, no database
      file, no storefront installed and so no loop; every problem named in one refusal
      (composition); and `test_a_storefront_configured_through_files_starts_and_serves`: from
      the files alone, with `STOREFRONT_NEGOTIATION_WATCHDOG_INTERVAL=45` injected,
      the lifespan starts, the override applies, and `StorefrontClient.get_health()` answers
      `ok` (spec "An operator overrides a setting on a development cluster"). **Corrected
      (level):** `test_publication_cycle.py` is the cycle's public API over a real database
      with site and registry doubles (its own docstring says so), not application integration:
      `test_a_pool_resolving_no_lease_bound_is_held_while_others_publish` (spec "A bare-metal
      pool resolves no lease bound": the pool whose override states a maximum publishes, the
      other is held and reported) and `test_a_bound_that_is_not_positive_holds_its_pools_listings_open`
      (0 and -1); both fail with the hold removed (edited, then restored). The application
      integration case is in `tests/test_http_publication_rates.py`, through
      `StorefrontClient`: `test_a_pool_resolving_no_lease_bound_is_held_through_the_running_app`
      (the step reports `pool_lease_bound_missing` and publishes nothing; an override stating
      a maximum then publishes). Its cycle factory hands the runtime's
      `default_max_duration_seconds` to the cycle itself, standing in for the production
      composition; that `build_publication_cycle` hands it over is shown only by
      `test_publication_cli.py` (the recorded cycle's arguments). Its `test_a_bound_conflict_after_the_write_holds_rather_than_fails`
      changed premise: a configuration change is now a restart, a second app over the same
      database, since an absent maximum holds the pool before any write. Adapted:
      `test_publication_cli.py` (every registry handed to the cycle; no registry refused; the
      command composed from the files), `test_pool_override_cli.py` (the URL order; and,
      application integration over the loopback-served app, `pool-override list` signing as
      the configured principal at the configured `base_url`), `test_introduction_delivery.py`
      (the section read from the files), `test_site_clients.py` (bindings from sites and
      peers, the refusals not echoing a URL), `test_pool_overrides_api.py` (the configured
      maximum on the runtime), `test_http_system.py` (registry status over the new
      configuration, and a second registry not asked once the first fails),
      `test_pool_override_terms.py` (`positive_lease_bound`), `test_http_publication_settlement.py`,
      and the cycle harness (`default_max_duration`, 3600 unless a case says otherwise). Static
      configuration tests (`scripts/tests`): the bare-metal render's storefront environment is
      exactly `XDG_CONFIG_HOME` and `ARKHAI_IDENTITY_CREDENTIAL`, both files mount at
      `/etc/arkhai/`, the address book only with the development overlay
      (`test_bare_metal_compose.py`), and the lane render's the same
      (`test_lane_compose.py::test_the_bare_metal_storefront_reads_its_settings_from_mounted_files`);
      `e2e-tests/tests/unit/test_domain_stack_configuration.py` requires the configuration and
      overlay files and no wallet key in the wrapper.
- [x] 11.9 Refresh the locks. Validation: `make test-bare-metal`, `make test-e2e-unit`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (bare-metal lane): `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`.
      Done. No package version moved. `scripts/uv_project.py lock` relocked bare metal's
      storefront and `e2e-tests` (each records the storefront's two new dependencies; bare
      metal's own the new specifiers); VM storefront's lock, which locks the bare-metal
      storefront for the combined image, was edited by hand with exactly the two dependency
      lines uv wrote into `e2e-tests/uv.lock` for the same package (16.6 relocks it).
      `docs/development/RELEASING.md`'s row for `arkhai-bare-metal-storefront` gains
      `arkhai-kit-config`, which release tooling's
      `test_the_release_guide_states_each_package_internal_deps` requires. Evidence: `make
      test-bare-metal`: domain 134, storefront 355 (324 before), buyer 11, adapter 40 passed;
      `make test-e2e-unit` 38 passed; the Compose render tests (`scripts/tests/test_bare_metal_compose.py`,
      `test_lane_compose.py`, static configuration tests over `docker compose config`) 21
      passed; `make check-architecture` and `make check-packaging` pass; `make -k test`: every
      suite it ran passed but release tooling's release-guide row (fixed above; `make
      test-release-tooling` then 944 passed), and it stopped only at the reinit of `kit/policy`,
      `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch index is refused here, as in
      2.6); VM storefront, which installs the rebuilt bare-metal wheel, ran frozen with it
      reinstalled: unit 1071 passed, 1 skipped, integration 446 passed; `kit/policy` and the VM
      buyer lock nothing this section changed and were not rerun. `make -C helm test-render`
      (with `STOREFRONT_PYTHON`) passed, the bare-metal chart's render tests unchanged.
      `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), `make check-tasks`, `make
      check-change-index`, and `openspec validate --strict` pass. No repository typing target
      exists. The pipeline was not run; the end-to-end reading is in the notes below.

Section 11 notes:

- End-to-end, read from the lane's files (the pipeline was not run): every bare-metal-lane
  scenario -- `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`, and
  `e2e_bare_metal_introduction` -- now starts a storefront configured only through
  `storefront.dev.toml` and `bare-metal.storefront.secrets.toml`, passes the startup refusal
  (one pinned registry, Alkahest and contact exchange enabled, `bare-metal-e2e` bound to one
  peer), and publishes with the lane's clause and 86400-second bound through the registry
  fan-out; the mock deal settles with the overlay's wallet key and the introduction scenario
  reads the contact and retention window from the file. No scenario starts a storefront that
  cannot publish or holds a pool for its lease bound: those are application-integration and
  application-startup evidence only. No VM-lane or API-credit-lane scenario reaches this
  section's code; the VM image installs the rebuilt bare-metal contribution unchanged in
  behaviour.

Section 11 check fixes (fresh-context check of `79d04e6..0ec0d54`; two items decided by the
owner's rule to follow VM, recorded in `design.md` D14a and C9):

- The override prefix is VM's `STOREFRONT`; typed sections ignore unknown keys. Tests (unit):
  `test_config_loader.py`'s overrides under `STOREFRONT_*`,
  `test_a_key_the_storefront_does_not_read_is_ignored` (a later release's
  `source_confirmation_seconds`, VM's `[Wallet].ssh_public_key`, a top-level `agent_id`), and
  `test_the_retired_variables_are_not_read_as_settings`; the lifespan case in
  `test_app_composition.py` injects `STOREFRONT_NEGOTIATION_WATCHDOG_INTERVAL`.
- The runtime's interval fields default from `config.packaged_settings()`, which reads the
  packaged `settings.toml` alone (no file, no override layer), so 1800/60/30/30 are stated once.
- `pool-override` reports configuration that cannot be read by its keys, apart from a missing
  identity or credential (`test_pool_override_cli.py::test_configuration_that_cannot_be_read_is_reported_as_such`).
- `pydantic>=2.7` is declared (imported directly, by `config.py` and modules before it); the
  locks follow.
- `design.md` records the committed secrets overlay (C9), clauses compiled at startup, the
  image's removed database-path variable, and the one-peer-per-site refusal in Section 11
  (D14a). 17.9 also names `docs/configuration.md` and `docs/attachments/baremetal-dispatch/index.md`.

Section 11 handoff:

- The runtime is composed once, by `build_runtime_from_configuration`, from a
  `BareMetalStorefrontSettings`; consumers read the values the runtime carries, never the
  settings or the environment. Section 13 must add the runtime fields it needs
  (`[capacity].poll_interval`, `publication_interval_seconds`, and the confirmation window)
  the same way: 13.4 adds `source_confirmation_seconds` to `CapacitySettings` (optional,
  three poll intervals by default). Until a section names a key, the loader ignores it, as
  VM's does. A runtime built directly takes its intervals from `config.packaged_settings()`,
  the packaged defaults alone; a new runtime interval should default the same way.
- 12.1: `settings.service_peer_configs()` is core's `ServicePeerConfigs`; the startup refusal
  already names a site bound to no peer or several. 12.2 replaces the configuration-time
  principal `parse_site_bindings` takes (the peer's first) with the peer's durable provider;
  `DurableReservationSiteMap` still pins that principal. 12.6's development `storefront.toml`
  already declares the site's peer (`bare_metal_e2e_site`).
- 13.2's disclosed error types: `BareMetalConfigurationError` names keys and reasons only;
  `BareMetalStartupError` never reaches a cycle.
- 14.2: the API-client `publish` signs as `settings.signer(identity_credential())` at
  `settings.base_url`, as `pool-override` now does.
- Section 16: the chart still passes the retired `BARE_METAL_STOREFRONT_*` variables as pod
  `env` (accepted until then). The override layer reads only `STOREFRONT_*`, so the loader
  does not read them at all: they neither override a setting nor break loading
  (`test_config_loader.py::test_the_retired_variables_are_not_read_as_settings`, with
  `_SETTLEMENT`, `_CHAINS`, and `_DB_PATH` set). Kubernetes injects service-link variables
  (`<SERVICE>_SERVICE_HOST`, `<SERVICE>_PORT`, `<SERVICE>_PORT_<n>_TCP...`) for every Service in
  the namespace; one whose name begins `storefront` lands in the override layer, as
  top-level keys the storefront ignores unless a name ever matches a setting (a `__` in the
  name would nest). Set `enableServiceLinks: false` on the bare-metal Deployment in 16.2. The
  typed models are what the values-schema generator reads: `WalletSettings.private_key` is
  marked secret as VM's is; the other sections are public, and the schema, not startup,
  refuses a key they do not name.
- The lane's principals, site, and registry pin are stated in three places --
  `storefront.dev.toml`, the root `Makefile`'s `e2e-bare-metal-dev-env` constants (which the
  provisioning service and registry read), and `e2e-tests/config/config-docker.yml` (which the
  scenarios read) -- as VM's lane states its own; no guard ties them together yet.
- Dynaconf merges two spellings of one key silently, so the loader cannot refuse them (a
  test for that was tried and dropped); the chart's generated schema refuses them at render.
- For 17.9: `DEPLOYMENT_AND_CONFIG.md` "Bare-metal role configuration", "Per-domain stack
  composition" (the development overlay and the two mounted files), and "Storefront listing
  shapes and pool overrides" (the bare-metal command's identity and URL, the maximum as
  `[pricing].default_max_duration_seconds`, a pool with no bound held) still describe the
  retired variables, as do `docs/bare-metal-seller-quickstart.md`, `docs/configuration.md`
  ("Bare-metal storefront": the seller chain is `[negotiation].policies`), and
  `docs/attachments/baremetal-dispatch/index.md` (its startup and settlement text); the
  override prefix `STOREFRONT` and the committed development files are the destinations'
  facts.
- Tests compose the storefront from files through `tests/storefront_configuration.py`;
  `storefront_config_files()` reads nothing under pytest unless `XDG_CONFIG_HOME` points
  away from the home directory, which `write_configuration` does.

## 12. Bare-metal durable site trust

Delivers bare metal's sites bound to durable service peers whose active principals verify
responses and callbacks, and reservations that survive a rotation (D14b;
`storefront-publication` "Site authority principals rotate with bounded overlap";
`deployment-state` "Independently deployable bare-metal seller role"). Touches bare metal's
storefront and its development configuration.

- [x] 12.1 Startup seeds each configured site's service peer into core's durable identity
      state through 4.3, refusing a site with no peer or more than one, naming it.
      Administrators stay on configuration.
      Done in `runtime.build_runtime_from_configuration`: once the database exists it builds
      one `ServicePeerTrust` over it and `settings.service_peer_configs()` and calls
      `seed()`, so the publication command's composition seeds too; a
      seeding refusal (a new peer with two principals, configuration that no longer covers
      the peer's durable principals) raises a `RuntimeError` naming it ("service peers cannot
      be seeded into its identity state: ..."). **Corrected (check):** VM seeds when its
      server starts, not when it composes, so this is a divergence, recorded in `design.md`
      D14b with its reason (the one-shot commands compose the runtime and must find the trust
      seeded); the root now seeds one peer at a time and the refusal names the peer
      ("service peer 'site_a_authority' cannot be seeded ..."). The runtime carries it as
      `service_peer_trust` (None authenticates no site). The one-peer-per-site refusal stays
      11.5's, before the database. Administrators are untouched (`admin_principals` from
      configuration). Composition (the root's builder over real SQLite,
      `tests/test_app_composition.py`):
      `test_startup_seeds_each_sites_service_peer_into_durable_identity_state` (the binding
      names the peer, the trust and the durable status hold its principal) and
      `test_configuration_that_no_longer_covers_a_seeded_peer_is_refused`. Application
      startup (the real app and lifespan): `test_a_storefront_that_cannot_publish_refuses_to_start`
      gains "a site with two service peers", and both peer cases now match the site's name.
      **Superseded (Section 14 check fixes):** seeding moved to the server's start hook, as
      VM seeds (`runtime.seed_service_peer_trust`, still one peer at a time and naming it);
      composition builds the trust unseeded. Both composition tests became application
      startup tests.
- [x] 12.2 `src/site_clients.py`: `BareMetalSiteBinding` carries the site's peer, not a
      principal; `parse_site_bindings` reads the configuration of 11.1;
      `build_trusted_site_clients` gives each site's `SiteCapacityClient` and
      `ComputeProvisioningClient` the provider of that peer's active principals (4.1, 4.2).
      Done. `BareMetalSiteBinding(site_id, service_peer, authority_url)`;
      `parse_site_bindings(sites, peers)` binds each site to its one peer's ID.
      `build_trusted_site_clients(..., trust, factories=SiteClientFactories())` gives both of
      a site's clients `trust.site_authorities(site)`, read at each response from memory.
      `SiteClientFactories` (capacity, fulfillment; the production clients by default) is the
      seam a test serves the sites through, as VM's `site_client_factory` and
      `client_factory` are; `build_runtime_from_configuration(site_clients=)` passes it.
      **Also changed:** `diagnostic(trust)` reports the site, its peer, and the peer's
      active principals now (primary first), with the trust's reason and no principals when
      it cannot answer, so health's and status's `sites` still report canonical authority
      principals (`deployment-state` "Site configuration is diagnosed"). Floors raised:
      `arkhai-core-storefront>=0.15.2` (the trust's failed-reload rule),
      `arkhai-kit-site-client>=0.11.0` and `arkhai-compute-provisioning-client>=0.7.0` (the
      provider, and `AuthorityTrust`). Composition, the builder over a real SQLite trust with
      fake site transports, its built clients called directly (`tests/test_site_clients.py`):
      `test_each_sites_clients_verify_against_its_peers_active_principals` -- the capacity
      client's projection version and the fulfillment client's lease read verify the
      current principal only, either during an overlap applied through the trust's identity
      authority, the replacement only once completed, and the other site's principal
      neither; with the providers replaced by sets read once at construction (edited, then
      restored) it fails, as does the application test below.
- [x] 12.3 Callbacks: `src/api.py`'s `capacity_released` and the service-role read of
      system status verify against the selected site's peer's active principals, the same
      set its responses verify against.
      Done through `_site_authority_principals`, which reads `trust.site_active_principals`
      for the sites named (503 while the trust holds nothing): `capacity_released`
      authenticates against the site its body names, as VM's callback does (the proof covers
      the body), so the after-the-fact principal comparison goes; the service-role status
      read accepts any configured site's peer, bare metal's own choice where VM requires
      exactly one peer (Section 4 handoff; VM adopts bare metal's rule in the check fixes). Application integration through the typed
      client: `test_deal_controls.py::test_only_the_named_sites_authority_may_report_a_release`
      (an impostor 403, a report naming an unconfigured site 403, an unknown reservation
      404; **corrected (check):** first described as "another site's report", which it is
      not, see the check fixes) and
      `test_a_recorded_release_is_a_stage_event_and_a_refused_one_is_not`,
      `test_http_settlement.py`'s release after a restart, and
      `test_http_system.py::test_a_configured_site_reads_status_as_a_service_and_another_cannot`,
      all over peers seeded through the new `tests/site_trust.py` (`seeded_sites`).
- [x] 12.4 Reservations: `bare_metal_selected_site_bindings` pins the site's peer subject;
      the principal it records is an audit record, so `DurableReservationSiteMap` loads
      after an authorized rotation. Written as fresh schema in `src/migrations.py`, with
      no upgrade or backfill, because bare metal has never been deployed outside the
      development cluster; the immutability trigger keeps the binding unchanged.
      Done. Migration 0004's table gains `service_peer TEXT NOT NULL` (non-blank), edited in
      place with its ID kept, and 0007's trigger covers it; `authority_scheme` and
      `authority_identifier` record the peer's primary when the reservation is made and are
      never compared. `DurableReservationSiteMap(db_path, bindings, trust)` refuses at load a
      reservation whose site is unconfigured or now bound to another peer, and records each
      new reservation against its site's peer, refusing one whose recorded site or peer
      differs. **Consequence:** a database that applied the earlier 0004 lacks the column, and
      a storefront started on it fails at composition (`no such column: service_peer`); the
      lane's volumes are removed with each stack (`down -v`), and the chart deploys nothing
      until Section 16. Migration test over a fresh real database
      (`tests/test_migrations.py::test_a_fresh_database_pins_each_reservation_to_its_sites_peer`:
      the columns, a blank peer refused, the trigger refusing an update of the peer and of the
      audit principal). Composition (`tests/test_site_clients.py`):
      `test_a_reservation_stays_bound_to_its_site_across_an_authorized_rotation` and
      `test_a_reservation_whose_site_is_bound_to_another_peer_refuses_restart`.
- [x] 12.5 Rotation routes: bare metal serves the identity rotation, completion, status,
      and retirement routes VM serves (`core_storefront.identity_lifecycle`), reached
      through `StorefrontClient`'s `admin_initiate_identity_rotation`,
      `admin_complete_identity_rotation`, and `admin_get_identity_status`.
      Done in `src/api.py`: `POST /api/v1/admin/identity/rotations` (`admin_rotate_identity`),
      `POST /api/v1/admin/identity/retirements` (`admin_retire_identity`, which is the
      completion: VM serves no separate retirement route), and `GET /api/v1/admin/identity/status`
      (`admin_identity_status`, exactly one `authority` and `subject` in the query), each the
      administrator's signed contract over the same resources VM binds, run off the loop.
      Rotation and retirement commit through `trust.identity_authority()` (503 without a
      trust); refusals are 409, an unknown subject on status 404, a malformed authority 400.
      Administrators are configuration and never a durable subject here, so a rotation
      naming one is refused as not registered. Application integration below (12.7).
- [x] 12.6 The development `storefront.toml` and the lane's site configuration declare the
      site's service peer.
      Already so (Section 11): `storefront.dev.toml` binds `bare-metal-e2e` to
      `[Identity.service_peers.bare_metal_e2e_site]`, Anvil account 0, the principal the root
      `Makefile` gives the lane's provisioning service and `e2e-tests/config/config-docker.yml`
      pins as `site_authority`. Only its comment changed, to say startup seeds the peer and its
      principals then rotate through the identity routes. No e2e scenario names the peer.
- [x] 12.7 Tests. `tests/test_site_clients.py`:
      `test_selected_site_binding_survives_restart_and_rejects_authority_rotation` becomes a
      restart after an authorized rotation that keeps the reservation bound ("A bare-metal
      storefront restarts after a rotation"); a site with no peer, or two, refuses startup
      ("A site has no service peer"). Application integration, through the typed client:
      a rotation completed through the routes moves both response verification and
      `capacity_released` callbacks to the replacement once the overlap ends;
      `tests/test_deal_controls.py`'s per-site callback checks pass against peers;
      `tests/test_migrations.py` covers the fresh schema.
      Done. `test_site_clients.py` (composition, real SQLite): the renamed restart test --
      a restart at the composition level, rebuilding the trust and the reservation map over
      the same database, not an application restart --
      rotation applied and completed through the trust's identity authority, restart with
      configuration naming the replacement (durable state then requires it: stale
      configuration refuses, 12.1), the reservation still bound and its audit principal the
      old one; the rebound-peer refusal; the two peer refusals named at the bindings (the
      startup refusal is `test_app_composition.py`'s, 12.1); the binding's diagnostic; the
      verb routing and immutability tests over seeded peers; the built clients (12.2).
      Application integration, new `tests/test_site_trust.py`: the real app and lifespan
      composed from the configuration files by `build_runtime_from_configuration`, which
      seeds the peer, with only the site's transport replaced by `tests/signed_sites.py`'s
      double: a pool-override write's live check verifies the configured principal and not
      the replacement; `admin_initiate_identity_rotation`, then both verify and
      `admin_get_identity_status` shows both active; `admin_complete_identity_rotation`, then
      only the replacement verifies, with no configuration change or restart; a
      `capacity_released` callback signed by the retired principal is refused 403 and one by
      the replacement is applied (`released`; the deal holding the reservation is inserted
      directly, service-internal setup no API reaches short of a settled deal). With the
      routes committing through a plain `StorefrontIdentityAuthority` (edited, then restored)
      it fails. Response verification is observed through the override write because that
      live check stays live (a non-goal of this change), while health's live version read
      becomes held state in Section 13. `test_deal_controls.py` passes over peers (12.3);
      `test_migrations.py` (12.4).
- [x] 12.8 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_mock_deal` (its release callback), `e2e_bare_metal_publication`,
      `e2e_bare_metal_introduction`.
      Done. No package version moved. `make lock PROJECTS="domains/bare_metal/storefront
      e2e-tests"`: bare metal's lock records its three raised floors; `e2e-tests/uv.lock` and
      VM storefront's lock, which lock the bare-metal storefront as a dependency by name only,
      needed no change. Bare-metal storefront suite 366 passed (355 before). `make -k test`
      (also covering Section 11's check fixes, which had not been rerun under it): every
      suite it ran passed -- core 123 + 134 + 217 + 62, the kits, provisioning service 675 +
      463, bare metal 134 + 366 + 11 + 40, API-credit storefront 153, e2e unit 38, release
      tooling 944 -- and it stopped only at the reinit of `kit/policy`,
      `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch index is refused here, as
      in 2.6), run frozen: VM storefront with the rebuilt bare-metal wheel reinstalled, unit
      1071 passed, 1 skipped, integration 446 passed (`test_alkahest` against Anvil included);
      `kit/policy` 80 passed; VM buyer 202 passed. `make test-e2e-unit` 38 passed. `make
      check-packaging` (architecture rules included), `make check-comment-hygiene`, `make
      check-doc-citations CHANGE=share-site-projection-state` (nothing reported), `make
      check-tasks`, `make check-change-index`, and `openspec validate --strict` pass. Not run:
      `make -C helm test-render` (no chart or loader input changed); no repository typing
      target exists; the pipeline was not run (the end-to-end reading is in the notes below).

Section 12 notes:

- End-to-end, read from the lane's files (the pipeline was not run): every bare-metal-lane
  scenario starts a storefront whose startup seeds `bare_metal_e2e_site` (Anvil account 0,
  the principal the lane's provisioning service signs with) into its durable identity
  state, and every site response the storefront verifies -- publication's live projection
  fetches (`e2e_bare_metal_publication`, `e2e_bare_metal_introduction`), and the mock deal's
  reservation, commit, scheduling, fulfillment, and lease reads (`e2e_bare_metal_mock_deal`)
  -- verifies against that peer through the trust, as do the mock deal's capacity-released
  callback and any status read the site makes as a service; each reservation is recorded
  against the peer. No scenario rotates the peer: rotation is application-integration
  evidence only. No VM-lane or API-credit-lane scenario reaches this section's code; the VM
  image installs the rebuilt bare-metal contribution, whose registration did not change.
- Restarting after a rotation needs configuration that names the replacement: a seeded
  peer's durable principals must stay covered (`storefront-publication` "Storefront
  authorization bindings are durable", "Startup configuration is stale during rotation"), as
  on VM. The delta scenario "A bare-metal storefront restarts after a rotation" holds under
  that configuration, which its text leaves implicit; closeout may state it.

Section 12 check fixes (fresh-context check of `0d293ef..41f8b9a`; decisions in `design.md`
D14b):

- **The service-role status read accepts every configured site's peer, in both
  storefronts.** VM's rule (exactly one configured peer, else 503) answered 503 to every
  site's readiness probe on a multi-site VM storefront; VM's `service_peer_auth` now verifies
  the read against the union of every configured site's active principals, skipping a site
  the trust cannot answer for and refusing as unavailable only when it can answer for none,
  as bare metal's `_site_authority_principals` does. The two are domain-local loops over the
  trust's public `site_active_principals`: a shared helper in `core_storefront` would have
  moved its version and, through `kit/capacity-publication`'s exact pin, every storefront's
  pins and locks, for six lines. Application integration through the typed client: VM
  `test_admin_api.py::TestHealthEndpoint::test_any_configured_sites_peer_reads_status` (site
  B's peer reads, a stranger is refused 403; fails against the old rule, checked by stashing
  the fix) and bare metal
  `test_http_system.py::test_every_configured_sites_peer_reads_status`.
- **A callback names one site and returns the trust's own refusal.** Bare metal's
  `capacity_released` refuses with the trust's reason and status for its named site (an
  unconfigured site: 403 "Provisioning site must have exactly one configured service peer"),
  as VM's callback does; only the status read skips a failing site. Both pass the request's
  one `now` to the principal lookup and to `authenticate_request`.
- **Evidence, truthfully.** New `test_deal_controls.py::test_one_configured_sites_authority_cannot_report_anothers_release`,
  two configured sites each with its peer: site B's authority signing a report naming site A
  is refused 403 (it fails site A's authentication); signing one naming itself for site A's
  reservation authenticates and is refused 404 "belongs to another site"; site A's own report
  is applied. The existing test now asserts the unconfigured site's 403 reason.
- **A database whose reservations name no peer is refused by structure.** Migration
  `bare-metal-storefront-0014-refuse-reservations-without-their-peer` (last in the chain, so a
  fresh database passes and records it) raises `RetiredReservationBindingError`, naming
  `docs/bare-metal-seller-quickstart.md`'s "Resetting the storefront database", when the
  selected-site table lacks `service_peer`; it rewrites nothing. Unit, over a connection
  (`test_migrations.py::test_reservations_without_their_peer_are_refused_by_structure`: no
  table, the old table, the new one) and a migration test over a real database whose table
  was replaced by the old shape (`test_a_database_whose_reservations_name_no_peer_refuses_every_start`,
  refused on two opens, its row unchanged). 12.4's "fails at composition (`no such column`)"
  is superseded by this refusal.
- `design.md` D14b says configuration seeds and must then cover the peer's durable
  principals, so a restart after a rotation needs configuration naming the replacement, and
  records the four delivered points above (binding and reservation, seeding at composition,
  the status read, the identity routes).
- Evidence: bare-metal storefront 372 passed; VM storefront frozen, the rebuilt bare-metal
  wheel reinstalled, unit 1071 passed, 1 skipped, integration 447 passed; `make
  check-packaging` (architecture rules included), `make check-comment-hygiene`, `make
  check-doc-citations CHANGE=share-site-projection-state` (nothing reported), `make
  check-tasks`, and `openspec validate --strict` pass. Core storefront was not touched. No
  package version moved and no lock changed.

Section 12 handoff:

- `runtime.service_peer_trust` is the process's one trust; every site client in
  `runtime.capacity_client` and `runtime.fulfillment_client` already verifies against it, so
  Section 13's `SiteProjectionState` over the aggregate inherits per-site rotating trust. A
  runtime built directly (tests) gets a seeded trust and bindings from `tests/site_trust.py`'s
  `seeded_sites`; a test that needs real site clients over a signing double uses
  `tests/signed_sites.py` (`SignedSites(...).factories()`, passed as
  `build_runtime_from_configuration(site_clients=)` or `build_trusted_site_clients(factories=)`).
- Health's and status's `sites` entries are now `site_id`, `service_peer`,
  `authority_principals` (the peer's active ones, primary first), and `trust_error` when the
  trust cannot answer; 14.1 keeps them beside `lifecycle`.
- `tests/test_site_trust.py` observes response verification through a pool-override write,
  whose live check this change keeps; it does not depend on health's live version read,
  which 13.6 turns into held state.
- Migration 0004 was edited in place (fresh schema, owner's rule): a bare-metal database that
  applied the earlier 0004 is refused at every start by migration 0014, naming
  `docs/bare-metal-seller-quickstart.md`'s "Resetting the storefront database", whose text
  17.9 should extend beyond the retired listing kind.
- For 17.9: `storefront-publication/architecture.md` "Trusted site routing" and "Role and
  service-peer identity" (bare metal's site binding names its peer; a reservation pins the
  peer subject and records the principal for audit; bare metal serves the identity routes;
  its administrators stay configuration); `ARCHITECTURE.md` "Site authority" ("an exact
  service-peer principal" becomes the site's service peer and its active principals) and
  "Local development" ("trusted site-binding configuration"); `DEPLOYMENT_AND_CONFIG.md`
  "Bare-metal role configuration" (each `[capacity.sites]` entry bound to one
  `[Identity.service_peers]` peer, seeded at startup, rotated through the identity routes,
  configuration then naming the replacement); `docs/bare-metal-seller-quickstart.md`.
- Section 16's chart must carry `[Identity.service_peers]` in `config`; its retiring
  `siteBindingsSecret` held the principal the binding no longer carries.

## 13. Bare metal on held projections and a publication loop

Delivers bare-metal publication, recheck, and overrides over the shared state, with every
loop on the cycle boundary and the scenarios holding them (D1, D2, D4, D5, D6, C2, C3, C5,
C6, C7; `storefront-publication` "Publication runs as a controllable storefront lifecycle
loop", "A site whose projection is not held holds its listings", "Bare-metal opening
rechecks its listing against its source", "Bare metal joins the site-scoped pool-override
store"). Touches bare metal's storefront and `e2e-tests/`.

- [x] 13.1 `src/runtime.py`: builds one `SiteProjectionState` over the sites' aggregate
      client with the publication wake as `on_resource_pool_change`, held by the runtime and
      passed to every consumer; startup loads it with `poll_once()`.
      Done. `build_runtime_from_configuration` builds the state over the aggregate
      `capacity_client` (`build_trusted_site_clients`'), whose site clients already verify
      against each site's peer through the trust (Section 12), and a `PublicationWake`
      (`lifecycle_steps`: a callable that sets its current `asyncio.Event`, renewed at each
      publication timer registration, as VM's `new_publication_wake`) as
      `on_resource_pool_change`. The runtime carries `site_projections` (None holds no site:
      nothing can be confirmed or published), `publication_wake`, and, read once from
      `[capacity]`, `site_projection_poll_interval_seconds`, `publication_interval_seconds`,
      and `source_confirmation_seconds`, each defaulting from `config.packaged_settings()`;
      `source_confirmation_clock` is the recheck's clock seam. Consumers read the state from
      the runtime: publication composition, the opening recheck (built in `__post_init__`),
      override status, health. `server._start_runtime` runs the escrow backfill, then
      `poll_once()`, then registers and starts the timers (13.2). A direct runtime (tests)
      composes its own state over a fake aggregate (`tests/source_sites.py`'s
      `source_projections`, `test_publication_cycle.projections_over`).
- [x] 13.2 Loops (`src/lifecycle_steps.py`, `src/server.py`): `site_projections` (step:
      `poll_once()` and `status()`, C2) and `publication` (interval
      `[capacity].publication_interval_seconds`, woken by the state) join
      `negotiation_watchdog`, `settlement_servicing`, `payment_reconciliation`, and
      `introduction_retention`, each registered with `register_loop`; `publication_lock`
      goes. Publication names its stages, and bare metal's configuration and publication
      errors are the controller's disclosed types. Each loop catches its failing cycle.
      Done. One table of loops (`lifecycle_steps._loops`) feeds
      `register_bare_metal_lifecycle_steps` (steps, when the runtime is built) and
      `register_bare_metal_loops` (timers, when the server starts), so the timer and the
      route run one operation. **Differed (name):** the poller is VM's
      `site_projection_poller` on route `site-projections`, not a loop named
      `site_projections`, so both storefronts report it alike. Its step polls and returns
      `{"loop", "sites": site_projection_status(state)}` (503 with no state). Publication and
      the poller start at once; the watchdog, servicing, payment reconciliation, and
      retention (its policy's sweep interval) one interval later, as VM's sweeps. The kit's
      `run_negotiation_watchdog`, `SettlementServicingWorker.run`,
      `run_payment_reconciliation`, and `run_introduction_retention_sweep` are no longer
      started; the watchdog and retention steps log what they did, as VM's do.
      `publication_lock` is gone. Stages: the step enters `compose` before composing the
      cycle; `BareMetalPublicationCycle(enter_stage=)` enters `compose` (overrides and held
      views), `run` (the driver), and `converge`. Disclosed: `DISCLOSED_CYCLE_ERRORS` --
      `BareMetalConfigurationError`, the new `BareMetalPublicationError` (a
      `LifecycleRouteError` 503 raised by composition for no projection state, no registry,
      no settlement composition), and VM's four kit/core capacity and registration errors;
      `bare_metal_loop_controller()` is the runtime's default `loop_controller_factory`.
      **Also changed:** the server gains a stop hook, `_stop_runtime`, that stops and awaits
      every timer (`stop_loops`), a divergence from VM recorded in `design.md` D6 (as
      delivered for bare metal).
- [x] 13.3 `src/publication.py`: `_classify_site` reads `values(RESOURCE_POOL)` and runs
      `trusted_bare_metal_projection` on the held value; a site holding nothing is
      `site_projection_unknown`, a refused generation `site_projection_refused`; the cycle
      fetches no site and records no generation.
      Done. The cycle takes `site_projections` and `site_ids` in place of `site_clients`.
      **Differed:** it reads each configured site's `view(site, RESOURCE_POOL)` -- value and
      identity together, every site before anything is awaited -- rather than `values()`,
      because a candidate carries the generation's revision and digest; a view with no value
      is `site_projection_unknown` (with the state's last error when there is one), and a
      stale one is derived from (D3). `record_accepted_generation` is no longer called.
- [x] 13.4 `src/listing_source_check.py`: the recheck reads `view(site, RESOURCE_POOL)`,
      requires `freshly_confirmed` within `[capacity].source_confirmation_seconds`
      (default three poll intervals) and an accepted generation, and calls no site (D5).
      Done. `build_listing_source_check(db, site_projections, *,
      confirmation_window_seconds, clock)`: an unconfigured site, no value, a generation not
      freshly confirmed (stale, or older than the window), or one `trusted_bare_metal_projection`
      refuses are each `unverifiable` (retryable), naming the reason; no state is unverifiable
      as before. `CapacitySettings.source_confirmation_seconds` (optional, positive) and
      `confirmation_window_seconds` (it, else three `poll_interval`s); `settings.toml`
      documents the key, commented. The window is resolved at composition (`design.md` D6,
      as delivered for bare metal), where VM reads it at each check.
- [x] 13.5 Overrides: `src/runtime.py`'s `pool_override_service()` gives
      `PoolOverrideService` `projection_source` over `values(RESOURCE_POOL)`, `refresh_site`
      over the state's `refresh_site`, and the publication wake; the write's live check is
      unchanged. C3: fresh databases stop creating `bare_metal_accepted_site_generations`,
      migration `bare-metal-storefront-0011` stays in the chain with its ID retired, and
      `record_accepted_generation` and `accepted_site_projection` go.
      Done. `refresh_site` refreshes both of the site's families, as VM's write does.
      **Corrected (wording):** "stays in the chain" contradicts C3 and
      `DEPLOYMENT_AND_CONFIG.md`'s frozen-table rule (a migration whose only effect is on a
      frozen table leaves the chain, its ID never reused); 0011 left the chain, with a comment
      at its place saying no migration takes its ID and a database that applied it keeps the
      table unread. `_add_accepted_site_generations`, `ACCEPTED_GENERATIONS_TABLE`,
      `record_accepted_generation`, and `accepted_site_projection` go; `pool_overrides`'
      docstring says status reads the held projection.
- [x] 13.6 C5, C7: `health()`'s `site_projections` comes from `status()` for both families
      and calls no site; `capacity_released` and the administrator reserve refresh nothing.
      Done: `health()` reports `site_projection_status(state)` (`{}` with no state) and
      the live version read `_site_projections` goes. The callback and the reserve already
      refreshed nothing; a test now holds them to it (13.8).
- [x] 13.7 C6 (`e2e-tests/`): an opt-in per-module fixture holding the bare-metal loops,
      resumed in a finaliser, taken with `pytest.mark.usefixtures` by
      `test_bare_metal_publication.py`, `test_bare_metal_mock_deal.py`, and
      `test_bare_metal_introduction.py` (whose `held_loops` it replaces); each steps
      `site-projections` wherever a site changed before stepping publication. The
      development `storefront.toml` widens `source_confirmation_seconds` for held
      scenarios, as 9.3 does for VM.
      Done. `scenarios/bare_metal/conftest.py`'s `bare_metal_loops_held` pauses through
      `pause_storefront` (every loop at its gate, retention's included, which
      introduction's own fixture asserted) and resumes in its finaliser. Site-projection
      steps: publication -- after declaring supply, withdrawing and reinstating the pool,
      pricing it, and the regionless pool (`_step_after_the_site_changed`), not after the
      override write, which refreshes the site itself, nor its deletion; introduction --
      after declaring the two hosts; mock deal -- the driver's `seed_supply` steps it (its
      health read is replaced by the step's own report, `loaded`), and 09a2 (machine leased)
      and 12a (released) step it before their previews. Module docstrings no longer say
      publication has no timer. `storefront.dev.toml`: `source_confirmation_seconds = 3600`,
      commented as VM's overlays are. Checked by compiling the modules and
      `make test-e2e-unit` (38 passed, the stage-set check among them); the scenarios run only
      in the pipeline.
- [x] 13.8 Tests, application integration through the typed client:
      `tests/test_publication_cycle.py` — an unknown site keeps its listings while another
      reconciles, a refused generation holds its site, a new pool publishes on the timer
      without a command, and two consumers read one generation without a site call ("Two
      consumers read one site"); `tests/test_http_system.py` — the startup loop set, the
      held step and preview, `test_concurrent_publication_steps_run_one_after_the_other`
      kept against `run_cycle`, health from held state; a recheck suite — not held,
      stale, expired, and refused generations each refuse as retryable with no site call;
      `tests/test_pool_overrides_api.py` — `test_status_follows_the_generations_publication_accepted`
      becomes status from the held projection, unknown before the first poll and after a
      restart, and an accepted write refreshes the site and wakes publication;
      `tests/test_migrations.py` — a fresh database has no accepted-generation table.
      Done; bare-metal storefront 388 passed (372 before). **Corrected (level):** as 11.8
      found, `tests/test_publication_cycle.py` is the cycle's public API over a real database
      and a real held state with site and registry doubles, not application integration;
      its harness polls every site before each cycle, as the lane steps `site-projections`,
      and a second `Storefront` over the same database is a restart. There: an unknown site
      (unreachable since a restart) and a refused generation each hold their site's listings
      while another site reconciles; a failed poll keeps deriving from the stale generation
      (spec "An operator refreshes every site during an outage"); publication and the recheck
      read one held generation with no site call ("Two consumers read one site"); a cycle
      fetches no site, sees a change only after a poll, and records no generation; a cycle
      names `compose`, `run`, `converge`. **Moved (level):** "a new pool publishes on the
      timer" needs the running app's timers, so it is in `tests/test_http_system.py`.
      `tests/test_http_system.py`, over the real app and its lifespan:
      `test_a_site_declaring_new_supply_is_published_by_the_timer` (loops running, poller at
      0.05 s, publication's interval an hour: the site's new pool is published by a `timer`
      cycle the poller's wake ran; the seam is a cycle factory reporting each completed
      cycle, waited on with a bound, no sleep) and `test_startup_starts_every_loop_on_the_controllers_timer`
      (the four timers and their routes; shutdown stops them) make no client call: they are
      the running app's composition observed through the controller and that seam.
      **Corrected (round 10, 10 F4):** the timer test's factory first built
      `BareMetalPublicationCycle` itself, with a recording registry and fixed terms, so the
      production composition was not exercised on the timer path; it now composes each cycle
      through `compose_publication_cycle` from the runtime, with Alkahest settlement terms and
      only the registry's fan-out replaced (13.13).
      `test_a_failed_publication_cycle_is_recorded_with_its_stage` steps publication through
      `StorefrontClient` and reads the outcome through the controller, not status (no
      registry: `compose`, `BareMetalPublicationError` with its message; a cycle raising
      `ConnectionError` naming a URL: type only). Through `StorefrontClient`:
      `test_the_projection_step_while_held_polls_and_publication_waits_for_resume`
      (stepping `site-projections` while held polls and wakes; the pause reports publication
      at its gate and the controller's snapshot keeps it `paused` with its first cycle's
      outcome, the gate being re-read under the cycle lock; once resumed the wake runs the
      cycle that publishes); health from held state, both families, no site call
      (`test_every_site_held_is_reported_loaded_and_health_calls_no_site`) and one site never
      answering (`unavailable`, outside the gate); the step, preview, and
      `test_concurrent_publication_steps_run_one_after_the_other` kept (the latter now over
      the controller's held `run_cycle` lock). Recheck, through the typed client
      (`tests/test_http_negotiation.py`): not held (site never answered), stale (the
      parametrized counter, accept, and force-accept cases step `site-projections` after the
      site fails), expired (`test_an_expired_confirmation_refuses_until_a_poll_confirms_the_site`:
      the runtime's clock 61 s past a 60 s window refuses 503 with no site call; after a
      held step it counters, the loops still held), and refused
      (`test_an_opening_on_a_refused_generation_is_refused_as_retryable`) each refuse as
      retryable with no site call; the declaration-changed and machine-taken cases step the
      poller before the round. With the freshness test disabled (edited, then restored) the
      expired and three stale cases fail. Overrides (`tests/test_pool_overrides_api.py`):
      `test_status_follows_the_generations_publication_accepted` becomes
      `test_status_follows_the_held_projection_of_the_overrides_site` (applied, orphaned after
      a poll, site-unconfigured) and `test_status_is_unknown_until_a_poll_holds_the_site` (a
      restart while unreachable is `unknown`, a step then `applied`); an accepted write
      refreshes the held projection to the site's new generation and wakes publication once,
      a refused one does neither. C7 (`tests/test_deal_controls.py`): an administrator
      reserve, a settlement, and a `capacity_released` callback make no site call and leave
      the held confirmation unchanged. Migrations (`tests/test_migrations.py`): a fresh
      database has no accepted-generation table and records no 0011; one that applied 0011
      keeps its table and row untouched. Unit (`tests/test_config_loader.py`): the window's
      default, a stated window, a negative one refused by key. Adapted: every test whose
      runtime rechecks a listing gives it a held state over its `SourceSite` (the fixture's
      digest now covers its content, so a changed projection is a new generation a poll
      fetches); app tests that step loops, or are composed with a registry nothing serves,
      start their loops held (`tests/held_loops.py`'s `held_loop_controller`); the
      file-composed lifespan and site-trust tests replace only the site's transport
      (`SignedSites`), so startup's first poll reaches a double; `test_publication_cli.py`
      shows the command hands the cycle the held state, loaded by one poll first.
- [x] 13.9 Validation: `make test-bare-metal`, `make test-e2e-unit`, `make test`.
      End-to-end (bare-metal lane): `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`.
      Done. No package version moved and no dependency changed, so no lock changed.
      `make test-bare-metal`: domain 134, storefront 388 (372 before), buyer 11, adapter 40
      passed; `make test-e2e-unit` 38 passed. `make -k test`: every suite it ran passed --
      core 123 + 134 + 217 (2 skipped) + 62, the kits (capacity-publication 97, storefront
      106, pool-overrides 81 among them), provisioning service 675 + 463, bare metal as above,
      API-credit storefront 153, e2e unit 38, release tooling 944 -- and it stopped only at the
      reinit of `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch
      index is refused here, as in 2.6), run frozen: VM storefront, with the rebuilt
      bare-metal wheel reinstalled (it installs the contribution for the combined image), unit
      1071 passed, 1 skipped, integration 447 passed; `kit/policy` 80 passed; VM buyer 202
      passed. `make check-packaging` (architecture rules included), `make
      check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
      (nothing reported), `make check-tasks`, `make check-change-index`, and `openspec
      validate --strict` pass. Not run: `make -C helm test-render` (no chart or loader input
      changed); no repository typing target exists; the pipeline was not run (the end-to-end
      reading is in the notes below).

Section 13 notes:

- End-to-end, read from the scenarios' code and the lane's files (the pipeline was not run):
  every bare-metal-lane scenario starts a storefront that loads its site's projections at
  startup and runs every loop on the controller's timer, publication and the
  site-projection poller among them. `e2e_bare_metal_publication`,
  `e2e_bare_metal_mock_deal`, and `e2e_bare_metal_introduction` hold the loops through
  `bare_metal_loops_held` and step `site-projections` wherever the site changed before
  stepping or previewing publication; publication reads only what that step loaded, the
  override write in the publication scenario refreshes the site itself, and every opening and
  acceptance recheck reads the held projection inside the lane's widened 3600-second window
  (the mock deal's second deal after 12a's step). No scenario lets a timer publish, observes
  a stale or expired generation, or reads `lifecycle`: those are application-integration
  evidence only. Between modules the loops run (publication every 30 s, the poller every
  1 s). No VM-lane or API-credit-lane scenario reaches this section's code; the VM image
  installs the rebuilt bare-metal contribution, whose registration is unchanged.
- The startup test case `test_a_storefront_configured_through_files_starts_and_serves` now
  replaces the site's transport and holds the loops; before this section its health read
  reached the configured site's URL over the network, and a startup poll and a publication
  timer would reach the site and the registry too.

Section 13 handoff:

- `runtime.site_projections` is the one state; `runtime.loops` the controller, built by
  `lifecycle_steps.bare_metal_loop_controller` with `DISCLOSED_CYCLE_ERRORS`. Steps are
  registered in `__post_init__`; timers in `server._start_runtime` through
  `register_bare_metal_loops`, after the first poll; `_stop_runtime` stops and awaits them, so
  outcomes are cleared at shutdown and a second lifespan over one runtime starts afresh. A
  second app started over a runtime whose loops still run is refused by `register_loop`
  ("already running").
- 14.1: `runtime.loops.snapshot()` gives each loop's state and last outcome (core's
  `HealthResponse.lifecycle` and the typed client's already carry the shape, Section 9);
  publication's per-site holds are in each cycle's report (`hold` with `site_id` and
  `reason`: `site_projection_unknown`, `site_projection_refused`, the pool reasons), which the
  cycle does not yet keep beyond the step's answer. `test_a_failed_publication_cycle_is_recorded_with_its_stage`
  reads the outcome through the controller, not status.
- 14.2: `publication_cli.run_publication_once` loads its own process's state with one poll
  before its cycle; an API-client `publish` drops that, and `test_publication_cli.py`'s
  composition cases become the in-process app's.
- Tests: a runtime that rechecks needs `site_projections`; `tests/source_sites.py`'s
  `source_projections` / `loaded_source_projections` (over `SourceSite`, whose digest covers
  its content) and `test_publication_cycle.projections_over` (over its `Site`, which serves
  both families). App tests that step loops, or carry a registry nothing serves, use
  `tests/held_loops.py`'s `held_loop_controller` as `loop_controller_factory`; a test of
  timer behaviour uses `bare_metal_loop_controller` and waits on a reported-cycle seam with a
  bound (`test_http_system._ObservedCycles`), never a sleep. A runtime with no registry logs
  a failed `compose` at each unheld publication cycle, harmlessly.
- For the owner: VM's stop hook does not stop its loops; bare metal's does (`design.md` D6,
  as delivered for bare metal). Whether VM adopts it, or the kit shell stops every
  storefront's loops, is `design.md`'s open question.
- A kit candidate: `lifecycle_steps.site_projection_status` is word for word VM's
  `services/capacity_client.site_projection_status`; `SiteProjectionState` could offer it.
- The mock deal's driver now asserts its `site-projections` step fetched a new generation
  (revision and digest changed), not merely `loaded`, which held before the step; VM's
  driver's equivalent check after its admin refresh asserts only `loaded` and is as weak.
- For 17.9, besides its list: `ARCHITECTURE.md` "Capacity publication and multi-domain
  storefront composition" ("bare-metal publication fetches each site's resource-pool
  projection itself on every run") and "Storefront capacity boundary" ("Bare-metal
  publication remains operator-invoked"); `DEPLOYMENT_AND_CONFIG.md` "Per-domain stack
  composition" ("The bare-metal storefront has no publication timer"), "Combined
  compute-family storefront" ("bare-metal publication remains an operator-invoked
  command"), and "Storefront listing shapes and pool overrides" (a bare-metal write refreshes
  the held projection and wakes the loop; status is judged against the held projection, not
  a recorded generation); `TESTING.md`'s two bare-metal rows become one (publication and
  `site-projections` among the held loops), and `[capacity].source_confirmation_seconds` for
  bare metal beside VM's. `design.md` D6's bare-metal decisions go to:
  `storefront-publication/architecture.md` "Autonomous publication" (bare metal's loops on
  the controller, stopped at shutdown, its disclosed errors, the window resolved at
  composition) and "Projection families" (publication reading each site's held view, value
  and identity, stale included); `DEPLOYMENT_AND_CONFIG.md` "Bare-metal role configuration"
  (`[capacity].source_confirmation_seconds`, three poll intervals unless stated).

Section 13 check fixes (fresh-context check of `2285e3e..fdaa4fe`; the five reported
divergences judged justified):

- Removed the orphaned comment of the deleted accepted-generation table in `migrations.py`.
- `test_app_composition.py`'s lifespan test no longer patches `server._start_runtime` or
  `_stop_runtime`: it runs the real hooks over a directly built runtime with held loops and
  observes them through its controller (both loops started, none registered after
  shutdown).
- The 13.8 note labels the timer, startup-loop, and failed-cycle tests by what they
  exercise, and says the timer test's factory builds the cycle itself.
- The held-step test's hold is read from the controller (gate state and unchanged last
  outcome) instead of an empty queue observed at an unsynchronized moment.
- The stop hook's docstring and `design.md` D6 state its real reasons: no cycle running
  against an uninstalled runtime, clean teardown, a fresh start over the same runtime; it
  awaits the loops' tasks, not a cycle's worker thread.
- `design.md`: VM's stop hook as an open question; D2's `values()` sentence points to bare
  metal's `view()` per site; the D6 decisions' permanent destinations are in the 17.9 list
  above.
- `kit/pool-overrides`' `PoolOverrideService` docstring no longer describes an
  operator-invoked publication; docstring only, so `arkhai-kit-pool-overrides` keeps 0.2.1
  (a same-version wheel is reinstalled by `reinit`, and its requirements are unchanged).
- `test_publication_cli.py`'s file-composed case is renamed for what it shows (a runtime
  composed from the files, handed to the command); its docstring says why no case lets the
  command compose its own (it would poll the configured site over the network).
- The mock deal's driver asserts the stepped generation changed. Nits: `__all__` sorted.

### Round 10 triage fixes (owner dispositions 2026-10-18)

Review 10 (`reviews/10-implementation-external.md`, the owner's external review of Sections
11-13 at `fa212f0`) was triaged in `reviews/10-implementation-external.triage.md`; its gate passed
2026-10-18, with these fixes to land and the fix commit to be validated (no validation record
exists for `fa212f0`). F3 (bare-metal tests never reach the real provisioning application) was
dispositioned as validation of the fix commit, not a fix: the client-to-API contract is
provisioning's integration suite's, and the wiring the end-to-end lane's.

- [x] 13.10 (10 F1, F2) **Shared setting types in `kit/config`.** A module of two Pydantic
      annotated types, each over a plain function, exported from `market_config`:
      `PositiveSeconds`, a positive, finite number of seconds a `timedelta` can represent, and
      `SiteAuthorityUrl`, an HTTP(S) origin. `kit/config` 0.3.0 to 0.4.0; both storefronts'
      floors `>=0.4.0`; every lock `make check-packaging` asks for refreshed.
      Done. `market_config/setting_types.py`: `positive_seconds` reads a number or numeric
      string and refuses a boolean (by name), NaN, infinity, zero, a negative, a non-number, and
      anything at or above `MAX_SECONDS` (`timedelta.max.total_seconds()`); `site_authority_url`
      refuses a non-string, a scheme other than http/https, no host, credentials, a query or
      fragment (a bare `?` or `#` included), a path other than empty or `/`, a URL `urlsplit`
      cannot parse, and a port that does not parse as a number in range, and strips whitespace
      and a trailing `/`. Each reason names no value. **Differed (bound):** the ceiling is
      exclusive, not "anything above": `timedelta.max.total_seconds()` rounds up to
      `86400000000000.0`, which `timedelta` itself refuses, so the bound refuses it too and the
      largest float below it builds one. **Superseded (round 10 check fixes, below):** the
      ceiling is the span from year 1 to the epoch, inclusive, a duration below a microsecond is
      refused, and the origin rule is stricter. The types are `PlainValidator`s over the functions with
      a `WithJsonSchema`: the duration's schema states `exclusiveMinimum` 0 and
      `exclusiveMaximum` `MAX_SECONDS`, the origin's is a string. `make dist`, then `make lock
      PROJECTS=...` relocked the sixteen projects that lock `arkhai-kit-config` and resolve here
      (kit capacity-publication, config, storefront; core buyer and storefront; VM domain and
      provisioning adapter; bare-metal domain, buyer, storefront, provisioning adapter;
      API-credit buyer and storefront; compute provisioning ansible and service; e2e-tests): the
      version and wheel name, and bare metal's root specifier. **Hand-edited (disclosed):**
      `domains/vms/storefront/uv.lock` and `domains/vms/buyer/uv.lock` cannot be relocked here
      (the PyTorch index is refused), so their `arkhai-kit-config` entries were edited to match
      exactly how uv wrote the same package in bare metal's regenerated lock (version `0.4.0`,
      wheel `arkhai_kit_config-0.4.0-py3-none-any.whl`, and VM storefront's root specifier
      `>=0.4.0`); `kit/policy` locks no `arkhai-kit-config`, so its lock is unchanged; 16.6
      relocks them. Unit (`kit/config/tests/unit/test_setting_types.py`): accepted durations and
      origins through the function and a `TypeAdapter`; each refused value; the boolean named;
      the bound refused and the float below it building a `timedelta`; 1e14 and `"1e14"`
      refused; no value echoed; both JSON schemas.
- [x] 13.11 (10 F1, F2) **Bare metal uses them.** `config.py`'s own `PositiveSeconds` is
      replaced by `kit/config`'s; the derived window (three `poll_interval`s) is refused by key
      when unrepresentable; `site_clients._authority_url` applies the origin rule, its
      refusals still naming the site.
      Done. `CapacitySettings` refuses, after its fields, an unstated window whose three poll
      intervals the shared rule refuses: `capacity: ... poll_interval sets
      source_confirmation_seconds when it is not stated, to 3 poll intervals, which must be
      below ... seconds`, naming keys only (`_CONFIRMATION_POLL_INTERVALS` is the one statement
      of three). `_authority_url` calls `site_authority_url`, the plain function behind
      `SiteAuthorityUrl`, and prefixes its reason with `site '<id>' authority_url`, so the
      refusal names the site without unpacking a `ValidationError`. Unit
      (`tests/test_config_loader.py`): a stated window of 1e14 refused by
      `capacity.source_confirmation_seconds`, a poll interval of 1e14 by `capacity.poll_interval`,
      and `test_a_derived_window_no_timedelta_holds_is_refused_by_its_interval` (3e13 refused
      unstated, accepted with a stated window). Unit (`tests/test_site_clients.py`): the
      parametrized invalid-binding test gains a path and a port that is not a number (neither
      echoed), and `test_a_site_url_that_is_not_an_origin_is_refused_naming_the_site` asserts
      the message.
- [x] 13.12 (10 F1, F2) **VM uses them.** `utils/config.py`'s `_positive_seconds` delegates to
      `PositiveSeconds` through a `TypeAdapter`, refusing by key; the derived window is
      refused when unrepresentable; `configured_capacity_sites` validates each URL through
      `SiteAuthorityUrl`, refusing by key.
      Done. One module-level `TypeAdapter` per type; a refusal is `[<key>] <reason>`, the reason
      taken from the type's `ValueError`. `source_confirmation_seconds()` refuses an unstated
      window three poll intervals cannot represent as `[capacity.poll_interval] sets
      [capacity].source_confirmation_seconds when it is not stated, ...`, so
      `_require_source_confirmation_window` refuses startup by the interval's key. A site URL
      is refused as `[capacity.sites.<site>] <reason>` (a `RuntimeError`, which the startup
      refusal already reports); an empty site ID keeps its own refusal. Docstrings of the
      interval reader and the startup check name the representability rule. Unit
      (`tests/unit/test_listing_source_check.py`): 1e14 and `"1e14"` windows and a 1e14 poll
      interval refused by key; `test_startup_refuses_a_derived_window_no_timedelta_holds_by_its_interval`;
      the startup check imported at module level. Unit (`tests/unit/test_startup_refusal.py`):
      `test_a_site_url_that_is_not_an_http_origin_is_refused_under_its_key` (path, bad port,
      credentials, query, no scheme, empty; none echoed) and
      `test_a_site_url_is_read_as_its_origin`. Chart render tests ran with `STOREFRONT_PYTHON`
      (VM's environment): the loader, start-and-derive, and generated-schema checks pass over
      the chart-derived `capacity.sites`; VM's typed models do not use the new types, so its
      generated schema is unchanged.
- [x] 13.13 (10 F4) **The timer test runs the production composition.**
      `test_a_site_declaring_new_supply_is_published_by_the_timer` composes its cycle through
      `compose_publication_cycle(runtime, cycle_factory=...)` with a reporting subclass of
      `BareMetalPublicationCycle`, substituting only the registry through the runtime's
      registry seam; the 13.8 note is corrected.
      Done (`tests/test_http_system.py`, application integration over the real app and its
      lifespan). `_ReportedCycle` subclasses `BareMetalPublicationCycle`, reporting each
      completed pass; `_ObservedCycles` returns `compose_publication_cycle(runtime,
      cycle_factory=partial(_ReportedCycle, completed=...))`; the runtime's
      `registry_configuration` is `_RecordedRegistries`, a `BareMetalRegistryConfiguration`
      whose `client_factory` returns the recording registry, so the registry is the one
      collaborator `compose_publication_cycle` is given in place of the real one; the sites and
      chain clients stay at the usual test doubles. The test sets `publication_cycle_factory`,
      so the runtime's default (`None`, composing through `compose_publication_cycle` with the
      plain cycle class) is functionally equivalent but bypassed. The runtime publishes under real Alkahest settlement
      (`test_publication_cycle.alkahest_publication`: the composition and compiled clauses, the
      payload built by `publication_payload_builder`), with the seller wallet and lease bound a
      configured runtime carries, and settlement servicing on an hour's interval. The runtime's
      settlement setup did not block it. `test_the_projection_step_while_held_polls_and_publication_waits_for_resume`
      shares the seam and so now runs the production composition too.
- [x] 13.14 Validation for the round: kit/config unit, the bare-metal storefront suite, VM
      storefront unit and integration (frozen), `make -k test` with the three PyTorch-index
      projects frozen, `make check-packaging`, `make check-comment-hygiene`, `make
      check-doc-citations`, `make check-tasks`, `openspec validate --strict`, chart render
      tests; the fresh-context check of the diff against `fa212f0`.
      Done. `kit/config` unit 213 passed (161 at round 08; `test_setting_types.py` among them).
      Bare-metal storefront 395 passed (388 before: unit configuration and binding cases, and
      the application-integration timer and held-step tests over the production composition).
      VM storefront frozen, with the 0.4.0 `kit/config` wheel and the rebuilt bare-metal
      storefront wheel installed (`uv sync --frozen --reinstall-package`; `UV_FROZEN=1 make
      test-unit test-integration`): unit 1082 passed, 1 skipped (1071 before); integration 447
      passed (application integration and application startup). Chart render tests (`make -C
      helm test-render`, `TESTING.md` "Chart Render Tests", `STOREFRONT_PYTHON` set to VM's
      environment): passed, the loader and start-and-derive checks run, not skipped. `make -k
      test`: every suite it ran passed -- core 123 + 134 + 217 (2 skipped) + 62, the kits
      (config 213, capacity-publication 97, storefront 106, pool-overrides 81, alkahest 296
      among them), provisioning service 675 + 463, bare metal 134 + 395 + 11 + 40, API-credit
      storefront 153, e2e unit 38, release tooling 944 -- and it stopped only at the reinit of
      `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch index is
      refused here, as in 2.6), run frozen: `kit/policy` 80 passed, VM buyer 202 passed (its
      environment synced frozen to the 0.4.0 wheel), VM storefront as above. `make
      check-packaging` (architecture rules included), `make check-comment-hygiene`, `make
      check-doc-citations CHANGE=share-site-projection-state` (nothing reported), `make
      check-tasks CHANGE=share-site-projection-state`, `make check-change-index`, and `openspec
      validate --strict` pass. No repository typing target exists. The pipeline was not run: the
      fix commit is validated next (the triage's disposition, which also carries F3).
      Fresh-context check of `fa212f0..3944152`: eight findings and a nit, all fixed in the
      "Round 10 check fixes" below, none declined.
      **End-to-end, read from the lanes' configuration (the pipeline was not run):** every
      VM-lane storefront states `[capacity.sites]` URLs that are origins (`http://provisioning:8081`,
      `http://alice-provisioning:8081`, the chart's `{default: <provisioning URL>}`) and
      intervals far below the ceiling, so each starts as before; the bare-metal lane's
      `storefront.dev.toml` names `http://bare-metal-provisioning:8081` and a 3600-second window.
      No scenario states an unrepresentable duration or a URL with a path: those are unit
      evidence only. No API-credit scenario reaches the round's code.

Round 10 check fixes (fresh-context check of `fa212f0..3944152`):

- The duration ceiling is the span from year 1 to the epoch, `(datetime(1970, 1, 1) -
  datetime(1, 1, 1)).total_seconds()` (about 6.2e10 s, inclusive), not
  `timedelta.max.total_seconds()`: 1e11 s built a `timedelta` but overflowed the watchdog's
  "now minus `negotiation_timeout_seconds`". The schema's bound is `maximum`. Tests: the bound
  subtracted from now and added to 8000-01-01 stay in range, the float above it and 1e11 are
  refused; bare metal refuses a 1e11 `negotiation_timeout_seconds`, window, and interval by key.
  The derived-window tests use 3e10 (three of them exceed the bound, one does not).
- A positive duration a `timedelta` holds as zero (below half a microsecond) is refused: 1e-7,
  5e-7, 5e-324 in kit/config; 1e-7 in bare metal and VM.
- The origin rule refuses whitespace and control characters anywhere in the value (checked
  before `urlsplit`, which drops tabs and newlines), an empty port and port 0, and a host that is
  neither a DNS name (labels of letters, digits, and hyphens, not starting or ending with one)
  nor an IP address (IPv6 bracketed), and returns the parsed origin `<scheme>://<netloc>` (so
  `HTTP://` reads as `http://`). The check's cases are kit/config unit cases; bare metal and VM
  add whitespace, empty-port or port-zero, and bad-host cases. **Superseded (Round 10
  follow-up, below):** the rule parses with pydantic's `AnyHttpUrl` instead.
- Refusals carry no value in their exception chain: kit/config's functions, bare metal's
  `_authority_url` and derived-window validator, and VM's `configured_capacity_sites` and
  `_positive_seconds` (through `_validated_setting`, which returns the reason) raise outside the
  handler, so `__context__` is `None`; tests assert it for credential-bearing URLs in all three
  packages and for a duration in kit/config.
- `design.md` D6's round-10 note names the durations that use the type and the two VM reads that
  do not (also in the handoff); D14b's says the values schema carries the duration only, the
  origin's placement rests on one rule shared without a domain-to-domain dependency, and bare
  metal refuses a bad URL at pod start in `parse_site_bindings`; the 17.9 amendment is narrowed
  to match.
- The storefront-publication delta's "A storefront that cannot publish refuses to start" gains
  the origin clause and the scenario "A site's authority URL is not an origin" (VM and bare
  metal, naming the site, never the URL).
- The 13.13 note and `_RecordedRegistries`' and `_ObservedCycles`' docstrings say the registry is
  the one collaborator `compose_publication_cycle` is given in place of the real one, the sites
  and chain clients stay doubles, and the runtime's default factory path is bypassed.
- Nit: `market_config/__init__.py`'s imports are in module order.
- Bare metal's `config._validated` raises its keys-and-reasons refusal outside the
  `except ValidationError` too, since that error keeps the refused values (a `[Wallet]` private
  key among them); `test_a_refusal_carries_no_secret_value_in_its_exception_chain` refuses an
  unreadable private key by key with no context and no value. Bare-metal storefront then 402
  passed.
- Evidence: kit/config unit 234 passed; bare-metal storefront 401 passed; VM storefront frozen
  (rebuilt 0.4.0 kit-config and bare-metal storefront wheels reinstalled) unit 1088 passed, 1
  skipped, integration 447 passed; `make -C helm test-render` with `STOREFRONT_PYTHON` passed,
  loader and start-and-derive checks run; `make check-packaging` (locks included; the 0.4.0 wheel
  is unreleased, so no bump, and the hand-edited VM locks record no hash), `make
  check-comment-hygiene`, `make check-doc-citations`, `make check-tasks`, and `openspec validate
  --strict` pass. `make test` was not rerun for these fixes (no package outside kit/config and
  the two storefronts changed).

Round 10 follow-up (owner, 2026-10-18, after the check fixes):

- **The site origin parses with pydantic's `AnyHttpUrl`** (`design.md` D14b, "An established
  parser, not our own"). `site_authority_url` validates through a `TypeAdapter(AnyHttpUrl)` and
  applies only the origin policy on top: path `/` or empty, query and fragment `None` (a bare `?`
  or `#` refused), no username or password. It returns `str(url)` without its trailing `/`, so
  `HTTP://Site-A:8081/` is `http://site-a:8081` and `https://bücher.example` is
  `https://xn--bcher-kva.example`; bare metal's binding and VM's site map carry that value to the
  clients. The hand-written host, port, whitespace, and control-character parsing and their tests
  are gone, and port 0 is accepted. A parse refusal's reason comes from the error type
  (`url_scheme`, else "it is not a valid URL"), raised outside the handler. Unit
  (`kit/config/tests/unit/test_setting_types.py`): normalization, IDN, IPv6 and IPv4, a default
  port dropped; hosts the standard accepts (`-`, `site-a;x`, `%41`) accepted; refused: the origin
  policy (path, `//`, query and bare `?`, fragment and bare `#`, credentials), a bad or
  out-of-range port, a space in the host, a malformed IPv6 host, a non-HTTP scheme, empty, no
  host; the no-echo, no-context tests kept. Bare metal (unit, `tests/test_site_clients.py`): the
  site-naming cases are a path, a bad port, a space in the host, and a non-HTTP scheme, and a
  binding carries the normalized origin; VM (unit, `tests/unit/test_startup_refusal.py`): port
  zero and `http://-` left the refused set, a malformed IPv6 host joined it, and the origin test
  checks normalization. The storefront-publication delta's clause says "a URL the WHATWG URL
  standard parses". `kit/config` stays 0.4.0 (unreleased in this change); the wheel was rebuilt.
- **A dry run logs a previewed refresh as a preview.** A dry run's refresh or reopen of an
  existing listing returned `{"status": "dry_run"}` to the driver, which counts any status other
  than unchanged, published, or disabled as a failed candidate, so each was logged as a warning,
  `bare-metal candidate ... failed: {'status': 'dry_run', ...}`. It now returns unchanged to the
  driver, since the preview changes nothing, and logs `bare-metal listing <id> would be refreshed
  (dry run): <fields>` (or reopened) at info; the report's `refresh`/`reopen` action is unchanged.
  A new publish was never logged as failed (its missing listing ID is not a failure).
  Unit-level cycle test (`tests/test_publication_cycle.py`, the cycle's public API over a real
  database): `test_a_dry_run_logs_a_refresh_it_would_make_as_a_preview_not_a_failure`, through
  `caplog`; against the unfixed code it fails with the reported warning.
- **Check of `12445bf`.** Before the parse, an ASCII control character anywhere in the value
  is refused (`without control characters`), since the standard drops a tab or newline inside a
  URL and C0 controls at its ends, which would rewrite the host rather than refuse it; kit/config
  unit cases `\t`, `\n`, `\x00`, `\x7f` and a tab in the no-echo, no-context test; bare metal's
  site-naming test a tab. Empty credentials (`http://@a`, `http://:@a`) are dropped by the parser
  and accepted as `http://a` (a kit/config case; D14b). The dry-run comment names the driver's
  rule (`unchanged` skipped, `published`/`disabled` counted published, any other status failed).
  `test_a_dry_run_logs_a_reopen_it_would_make_as_a_preview_not_a_failure` (a listing closed while
  leased, free again): the report's `reopen` is `dry_run`, it is logged at info as "would be
  reopened", nothing reopens, no failure is logged; against the unfixed code it fails with the
  warning. kit/config unit 235 passed; bare-metal storefront 405 passed; VM storefront unit
  frozen, rebuilt kit-config wheel reinstalled, 1087 passed, 1 skipped; `make check-packaging`, `make
  check-comment-hygiene`, `make check-tasks`, and `openspec validate --strict` pass.
- Evidence: kit/config unit 228 passed; bare-metal storefront 403 passed; VM storefront frozen
  (rebuilt 0.4.0 kit-config and bare-metal storefront wheels reinstalled) unit 1087 passed, 1
  skipped, integration 447 passed; `make check-packaging` (locks included), `make check-comment-hygiene`, `make
  check-doc-citations`, `make check-tasks`, and `openspec validate --strict` pass.

Round 10 handoff:

- `market_config.setting_types` (`kit/config` 0.4.0) holds `PositiveSeconds` / `positive_seconds`
  and `SiteAuthorityUrl` / `site_authority_url`, the latter pydantic's `AnyHttpUrl` with the
  origin policy on top, returning the normalized origin a site client is given. A new duration or site URL either storefront
  reads uses them: a typed model declares the type, an untyped VM read goes through a
  `TypeAdapter` and reports `[<key>] <reason>`. Section 16's bare-metal values schema takes the
  duration bounds from the typed models without a copy; the origin is typed as a string there,
  with no pattern, and is refused when the pod starts, by key, in `parse_site_bindings`.
- Unconverted duration reads: VM's `settlement_servicing_interval` (`utils/config.py`, a bare
  `float(...)` of `settlement_servicing_interval_seconds`) and its introduction-retention sweep
  interval (`startup.py`) do not go through `PositiveSeconds`.
- The bare-metal timer seam (`test_http_system._ObservedCycles`) composes through
  `compose_publication_cycle` with real Alkahest terms, so a timer test needs `monkeypatch`
  (for `alkahest_publication`'s token cache) and `_timed_runtime(tmp_path, monkeypatch, ...)`.
- 16.6 relocks VM storefront and VM buyer, whose `arkhai-kit-config` entries were edited by hand.

## 14. Bare-metal status and the publish command

Delivers the bare-metal `lifecycle` and derivation status and the API-client `publish`
command (D6, C1; `storefront-publication` "Operator-visible acceptance and projection
state", "Publication runs as a controllable storefront lifecycle loop"). Touches bare
metal's storefront.

- [x] 14.1 `src/models.py`'s `BareMetalHealthResponse` and `src/runtime.py`'s `status()`:
      `lifecycle` from the controller's snapshot, and the latest per-site derivation
      summary — each site's holds and their reasons, a refused generation and a pool held
      for missing terms or an unordered or absent lease bound included — as VM's
      `publication_derivation` reports.
      Done. `BareMetalHealthResponse` gains `lifecycle` (core's `LoopStatus` by loop name,
      the shape VM's status and the typed client's `HealthResponse.lifecycle` carry) and
      `publication_derivation`; `status()` fills both, so the administrator and a site's
      service-role read receive them, as VM's one status response does (pool overrides and
      obligations waiting for an operator stay the administrator's). Health carries neither.
      The summary is `publication.PublicationDerivation`, held by the runtime
      (`runtime.publication_derivation`) and handed to each cycle by
      `build_publication_cycle` (`derivation=`): once a cycle's compose stage has read every
      site, it records, per configured site, `holds`, `refusals`, and `reports` -- the cycle
      report's site-scoped `hold`, `refuse`, and `report` actions without their action and
      site (`site_projection_unknown`, `site_projection_refused` with its error, each pool or
      resource's region, declaration, rate, override (`pool_override_terms_conflict` for an
      unordered pair), and `pool_lease_bound_missing` holds; `pool_unbacked`; the notices). A
      clean site maps to empty lists; before any cycle the section is `{}`. **Differed:** a
      preview records nothing (VM's dry run records its reports), so the derivation and the
      last outcome describe the same cycle; the per-site keys are bare metal's report
      reasons, not VM's categories. Both in `design.md` D6 ("As delivered for bare metal
      (Section 14)"). **Also changed:** stale comments that described `publish` composing in
      its own process (the runtime's controller and cycle-factory comments, the run-cycle
      route's and `publication_composition`'s docstrings, the seeding comment, which now names
      `redeliver-introduction` as the one command that composes a runtime) and
      `pool_override_cli`'s docstring, which still said a write waited for the next run.
- [x] 14.2 `src/publication_cli.py` and `src/cli.py`'s `publish`: runs one cycle (or a
      preview) through `StorefrontClient.admin_run_lifecycle_cycle` /
      `admin_dry_run_lifecycle_cycle`, signing as the storefront's identity read from the
      configuration files, and opens no database (C1).
      Done. `publish [--dry-run] [--storefront-url URL]` calls
      `publication_cli.run_publication_cycle`, which runs or previews the `publication` route
      through `SyncStorefrontClient` and prints the report as JSON; a storefront refusal exits
      1 with its message. The administrator client is the new `admin_cli.py`
      (`storefront_admin_client`, `reporting_failures`, `storefront_url`), moved out of
      `pool_override_cli`, which now wraps it: it signs as `settings.signer(identity_credential())`
      at `--storefront-url`, else `settings.base_url`, and keeps the client, identity, and
      configuration stack loading inside the function under its existing lazy-load reason
      (help and the commands that call no storefront load none of it). `run_publication_once`,
      the in-process composition, and its extra poll are gone. `cli.py` now imports `json`,
      `reporting_failures`, and `run_publication_cycle` at module level (all light; the
      command's old local imports went). **Differed (from VM's `market-storefront publish`):**
      JSON output rather than VM's table, and no `--abort-all`; `design.md` C1 ("as
      delivered") gives the reasons.
- [x] 14.3 Tests. Application integration, through the typed client: status reports a
      failing cycle with its stage, a refused generation as loaded with the site's hold
      ("A bare-metal site serves a generation bare metal refuses"), and a held pool's
      reason. `tests/test_publication_cli.py`: the command reaches a running in-process app
      through its client and touches no database ("An operator runs the bare-metal
      publication command", "Publication runs from the command").
      Done. Application integration, the real app and its lifespan, status through
      `StorefrontClient.get_system_status()` (`tests/test_http_system.py`):
      `test_a_failed_publication_cycle_is_reported_in_status_with_its_stage` (renamed from
      `..._is_recorded_...`, which read the controller): a stepped cycle that cannot compose is
      reported `paused`, `step`, failed in `compose` with `BareMetalPublicationError`'s message,
      and one failing on a `ConnectionError` naming a URL by type only, the URL absent;
      `test_status_reports_a_running_loop_whose_timer_cycles_fail` (spec "Publication fails
      every cycle"): loops running, no registry, the timer's first cycle fails and status
      reports publication `running` with a failed `timer` outcome -- the seam is a logging
      handler on the controller's failure log, waited on with a bound, no sleep;
      `test_status_reports_a_refused_generation_as_loaded_with_the_sites_hold`: a site serving
      a bare-metal view naming another pool is `loaded` in `site_projections` and held
      `site_projection_refused` with its error, the other site present with empty lists;
      `test_status_reports_a_held_pools_reason_from_the_latest_cycle_only` (spec "A bare-metal
      pool resolves no lease bound"): `{}` before any cycle and after a preview, then
      `{"pool_id": "pool-1", "reason": "pool_lease_bound_missing"}`, and every loop `paused`.
      These two run the production composition (`compose_publication_cycle` with real Alkahest
      terms), only the registry's fan-out recorded. With the recording removed both fail; with
      the preview recording too, the second fails (edited, then restored).
      `tests/test_publication_cli.py`, rewritten as application integration over the
      loopback-served app (`loopback.serving`, lifespan, loops held), the command reading its
      identity and `base_url` from configuration files whose `db_path` must never come to exist
      (asserted after every invocation): the step's cycle, composed in the storefront by
      `compose_publication_cycle` with a recording cycle class, is handed the runtime's one
      held state (both sites loaded by startup, no site called by the step), both sites, both
      registries (the client factory pins exactly them), the configured bound, the storefront
      URL, and the derivation record, and runs as a `step` with the loops still held; `--dry-run`
      previews and records no outcome; no registry and no projection state each exit 1 naming
      the reason, constructing no cycle; `--storefront-url` overrides the configured URL; a
      `pool-override set` then `publish` leave the override reported `applied` with no
      accepted-generation table (spec "Publication runs from the command"); the command's
      module imports no database layer (an AST check, as VM's); a missing credential is refused
      before connecting. These replace the in-process composition cases the handoff named.
      **Corrected (check):** the command tests double the cycle (`RecordingCycle`), so they
      prove the command -> typed client -> step route path and the composition the storefront
      hands its cycle, not the cycle itself, whose evidence is `test_http_system.py`'s; the
      override case proved nothing the command did, and the AST check read one module (see
      the check fixes below).
      `tests/test_pool_override_cli.py`'s URL test imports `storefront_url` from `admin_cli`.
      Bare-metal storefront 412 passed (405 before).
- [x] 14.4 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_publication`; no scenario runs the `publish` command.
      Done. No package version moved and no dependency changed, so no lock changed (the
      bare-metal storefront's `arkhai-core-storefront-client>=0.25.0` floor already resolves
      0.26.0, whose `HealthResponse.lifecycle` the tests read). `make test-bare-metal`: domain
      134, storefront 412 (405 before), buyer 11, adapter 40 passed. `make -k test`: every
      suite it ran passed -- core 123 + 134 + 217 (2 skipped) + 62, the kits (config 235,
      capacity-publication 97, storefront 106, pool-overrides 81, alkahest 296 among them),
      provisioning service 675 + 463, bare metal as above, API-credit storefront 153, e2e unit
      38, release tooling 944, the Helm render suites -- and it stopped only at the reinit of
      `kit/policy`, `domains/vms/storefront`, and `domains/vms/buyer` (the PyTorch index is
      refused here, as in 2.6), run frozen: VM storefront, with the rebuilt bare-metal
      storefront wheel reinstalled (it installs the contribution for the combined image), unit
      1087 passed, 1 skipped, integration 447 passed; `kit/policy` 80 passed; VM buyer 202
      passed. `make check-packaging` (architecture rules included), `make
      check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
      (nothing reported), `make check-tasks CHANGE=share-site-projection-state`, and `openspec
      validate --strict` pass. No repository typing target exists. The pipeline was not run
      (the end-to-end reading is in the notes below).

Section 14 notes:

- End-to-end, read from the scenarios' code (the pipeline was not run): every bare-metal-lane
  scenario that reads status (`e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication`'s
  override statuses) now receives `lifecycle` and `publication_derivation` beside what it
  reads, and `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`, and
  `e2e_bare_metal_introduction` step publication, whose cycles record the derivation summary.
  No scenario reads either new section or runs `publish`: those are application-integration
  evidence only. No VM-lane or API-credit-lane scenario reaches this section's code; the VM
  image installs the rebuilt bare-metal contribution, whose registration is unchanged.

Section 14 handoff:

- `runtime.publication_derivation.latest()` is the per-site summary status reports; a new
  site-scoped `hold`, `refuse`, or `report` action a cycle records reaches it with no other
  change. VM's `publication_derivation` keeps its own categories; the two storefronts' keys
  differ by design (`design.md` D6, Section 14).
- `admin_cli.storefront_admin_client` is the one administrator client both bare-metal commands
  use; a further command that calls the running storefront takes it.
- For 17.9: `docs/development/TESTING.md`'s "Bare-metal storefront publication" row ("each pass
  is operator-invoked", "the same pass the `bare-metal-storefront publish` command runs")
  becomes part of the bare-metal loop row, the command a client of the `publication` step;
  `DEPLOYMENT_AND_CONFIG.md` "Per-domain stack composition" and "Storefront listing shapes and
  pool overrides" (the command calls the running storefront, `--dry-run` previews);
  `docs/bare-metal-seller-quickstart.md` (around lines 231 and 290, the `publish` round); the
  permanent spec's scenario "Publication runs from the command" is rewritten by the delta at
  archive; `storefront-publication/architecture.md` "Autonomous publication" (the command is
  a client of the loop; status's `lifecycle` and per-site derivation). `design.md` D6 and C1
  (Section 14) name the decisions.
- For the owner: whether bare metal's `publish` should gain VM's `--abort-all`, and whether VM's
  dry run should stop recording derivation reports (bare metal's preview records none).
  **Decided (2026-10-18):** both yes; the dry-run rule is in the check fixes below, and
  `--abort-all` is blocked on bare metal serving a seller close route (below).
- Also for 17.9 (Section 12's handoff): seeding is at the server's start now, as VM's (12.1's
  amendment).

Section 14 check fixes (fresh-context check of `5eca7dc..2dcebd3`; owner decisions 2026-10-18,
recorded in `design.md` D6, C1, and D14b):

- **A pool resolving no settlement clause is held at compose** (`_hold_pools_without_clauses`,
  beside the lease-bound hold): its override's clauses, else the configured ones, empty holds
  it as `pool_settlement_clauses_missing`, recorded in the derivation. The cycle takes
  `publication_clauses` (required), from the runtime through `build_publication_cycle`; the
  cycle tests' harnesses pass `test_publication_cycle.CONFIGURED_CLAUSES`. Application
  integration
  (`test_http_system.py::test_status_reports_a_pool_resolving_no_settlement_clause_held`):
  status reports the hold, and the cycle neither publishes nor refuses the candidate.
- **The derivation is the last cycle's.** The publication step clears it as each cycle starts
  (timer and step alike), the cycle records it after compose, and a preview does neither.
  `test_a_cycle_failing_in_compose_leaves_no_earlier_derivation_in_status`: a cycle that
  derived, then one failing in `compose`, leaves status's derivation `{}` beside the failed
  outcome. Both new tests fail with their change removed (edited, then restored).
- **Site error text stays** (owner: site URLs are not sensitive, and credentials cannot
  appear, since `SiteAuthorityUrl` refuses them at load); `design.md` D6's "no private URL
  reaches status" is corrected to what is true. Nothing was redacted.
- **"Publication fails every cycle" fails cycles a production way:** another process holding
  the storefront's database under `BEGIN EXCLUSIVE` fails each timer cycle in `compose`
  (`OperationalError`, by type), the loops running; status reports publication `running` with
  the failed timer outcome and no derivation. **Found:** an unreachable registry does not fail
  a cycle -- the cycle records `fail` for the publish and converges later (probed) -- so the
  spec scenario's example ("because a registry cannot be reached") is not a failing cycle for
  bare metal; for the owner or 17.9. The test waits through an injected seam:
  `bare_metal_loop_controller` takes a `logger` in place of the module's, and the test's
  handler sets an event on the controller's failure record, bounded (30 s; the lock's busy
  timeout is 5 s).
- **Command tests:** status, not the controller, is read through the typed client
  (`_publication_status`); the override case is deleted (`pool-override set` refreshes the
  site itself, and no production code creates the accepted-generation table, so it proved
  nothing; status from the held projection is `test_pool_overrides_api.py`'s); the AST check
  is replaced by `test_the_command_loads_none_of_the_storefronts_database_or_runtime`, which
  runs `publish` in a fresh interpreter against a storefront nothing answers for and asserts
  no `sqlite_client`, `runtime`, `publication_composition`, or `migrations` module was loaded
  and no database file created.
- **Owner decisions:** (B) `-a` for `--storefront-url` on `publish` and `pool-override`, as VM's;
  (C) the service peers are seeded at the server's start (12.1's amendment), since
  `redeliver-introduction`, the one command still composing a runtime, reads no site
  (`ServicePeerTrust.reload` over an unseeded database records each site's refusal and raises
  nothing, so composing stays safe); (12) a storefront nothing answers for is reported as
  "Storefront error: no storefront answered at <scheme://host:port> (<error type>)", exit 1,
  no traceback, by bare metal's `admin_cli.reporting_failures` (both commands) and VM's
  `cli_common.storefront_failure_message` and `STOREFRONT_FAILURES` (`publish`,
  `pool-override`). Bare metal now declares `httpx>=0.27`, which `admin_cli` imports. Tests:
  bare metal, through the commands against a closed port (`test_publication_cli.py`,
  `test_pool_override_cli.py`, both flags); VM, CLI unit with the existing client seams
  raising `httpx.ConnectError` (`tests/unit/cli/test_publish_command.py`,
  `tests/unit/cli/test_pool_overrides.py`).
- **VM's preview publishes no derivation report** (owner, 2026-10-18). `arkhai-vms-listings`
  0.6.0: `available_compute_slices`, `current_available_resource_keys`, and
  `stale_open_listing_ids` take `record_reports` (default true, so every existing recorder --
  real cycles, source checks, capacity-event and inline reconciliation -- is unchanged, and
  override feasibility keeps its explicit false), and `available_compute_slices` fills an
  optional `reports` out-parameter. VM's publication cycle passes `record_reports=not
  dry_run` to both derivations and reads its regionless holds from `reports` instead of the
  published `derivation_reports()`, so a preview still reports them. A preview logs none of the
  change-only derivation warnings, which accompany publishing a report. Application
  integration
  (`tests/integration/test_publication_loop.py::test_a_preview_leaves_the_reported_derivation_as_the_last_cycle_left_it`):
  after a cycle reporting a regionless pool, the pool gains its region; a preview reports no
  hold while status still reports the pool, and the next cycle clears it; it fails with the
  preview recording (edited, then restored). VM storefront requires `>=0.6.0`.
- **Not done (A, blocked):** `--abort-all` seller-closes each open listing
  (`StorefrontClient.close_listing`, `POST /api/v1/listings/{listing_id}/close`, seller role),
  which bare metal does not serve, nor the resume a seller re-lists with; the permanent
  spec's "A seller's close is durable" already says a seller MUST be able to reopen what they
  closed. Adding those routes is new API surface beyond this section; for the owner.
- Smaller: `cli.py`'s redundant local `import json` in `redeliver-introduction` goes;
  `test_publication_cycle.py`'s docstring names where the step's composition is tested; the
  over-long seeding comment went with the seeding.
- Locks: `make lock PROJECTS="domains/bare_metal/storefront e2e-tests"` (httpx; the listings
  wheel); VM storefront's and VM buyer's locks hand-edited exactly as uv wrote
  `e2e-tests/uv.lock` (the listings version and wheel name; VM storefront's root specifier
  `>=0.6.0` and the bare-metal storefront's `httpx` dependency line). 16.6 relocks them.
- Evidence: bare-metal storefront 417 passed (412 before); `make -k test`: every suite it ran
  passed (core, the kits, provisioning service 675 + 463, bare metal 134 + 417 + 11 + 40,
  API-credit storefront 153, e2e unit 38, release tooling 944, the Helm render suites), stopping
  only at the reinit of the three PyTorch-index projects, run frozen with the rebuilt
  `arkhai-vms-listings` 0.6.0 and bare-metal storefront wheels reinstalled: VM storefront unit
  1089 passed, 1 skipped (CLI unit among them), integration 448 passed; VM buyer 202 passed;
  `kit/policy` 80 passed. `make check-packaging` (locks and architecture rules included),
  `make check-comment-hygiene`, `make check-doc-citations CHANGE=share-site-projection-state`
  (nothing reported), `make check-tasks`, and `openspec validate --strict` pass. The pipeline
  was not run; end-to-end, every bare-metal-lane scenario's storefront now seeds its peer at
  start (as before, only later), and no scenario runs `publish`, previews VM publication and
  then reads status, or reaches a pool with no clause.

## 15. The API-credit storefront's loops, and the controller's one loop form

Delivers P1 and P2: the API-credit storefront's loops on `run_cycle` and its interval key
renamed, then the kit's old loop forms removed (D6, C4). Touches the API-credit storefront
and `kit/storefront`.

- [ ] 15.1 `src/startup.py` and `src/lifecycle_steps.py`: `negotiation_watchdog`,
      `settlement_servicing`, and `payment_reconciliation` register with `register_loop`;
      the per-site capacity-event pollers keep the per-site lock of 3.4.
- [ ] 15.2 `src/settings.toml`, `src/startup.py`, `src/settlement_composition.py`:
      `settlement_servicing_interval_seconds` replaces `claims_sweep_interval`, which
      refuses startup naming its replacement.
- [ ] 15.3 `kit/storefront/src/market_storefront_kit/lifecycle.py`: remove `start_loop` and
      the step-only `register_step` once no caller remains; bump the version.
- [ ] 15.4 Tests. The API-credit storefront's lifecycle and startup suites: the registered
      loop set, the retired key's refusal. `kit/storefront/tests/unit/test_lifecycle_controller.py`:
      the removed forms' tests go.
- [ ] 15.5 Refresh the locks. Validation: `make test-apicredits`, `make -C kit
      test-storefront`, `make test-storefront`, `make test-bare-metal`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (API-credit lane): `e2e_credits_deal`, `e2e_credits_payment_deal`.

## 16. The bare-metal chart on the storefront chart's agent shape

Delivers the bare-metal chart rendering configuration through unchanged under a generated
schema (D14c, C8; `deployment-state` "Independently deployable bare-metal seller role", "A
storefront's configuration reaches it through its configuration system"; `design.md`
"Validation tiers"). Touches `helm/charts/bare-metal-storefront`, the umbrella, the root
`Makefile`, bare metal's storefront, and `helm/scripts/test-render.sh`.

- [ ] 16.1 `src/values_schema.py` (new, bare metal): its section list and sinks over
      `market_config.values_schema`, writing only
      `helm/charts/bare-metal-storefront/values.schema.json`; the root `Makefile`'s
      `helm-values-schema` also runs it. Drift test `tests/test_values_schema.py`, run by
      `make test`.
- [ ] 16.2 `helm/charts/bare-metal-storefront`: `values.yaml` as one agent's keys at the top
      level (`config` rendered unchanged into `storefront.json` in a ConfigMap, the Secret
      overlay mounted as `storefront.secrets.toml`, the credential Secret, the port the
      container, probes, and Service share, persistence), `XDG_CONFIG_HOME`, and only
      release-known derivations (C8); the old values (`siteBindingsSecret`,
      `settlementConfigSecret`, `chains`, `sellerEvmAddress`, `walletKeySecret`,
      `alkahestAddressBook`, `adminPrincipals`, `publicUrl`, `databasePath`) go;
      `templates/deployment.yaml` sets only `XDG_CONFIG_HOME` and
      `ARKHAI_IDENTITY_CREDENTIAL` in the pod environment; `examples/production-values.yaml`
      follows. The umbrella's `bare-metal-storefront` entry keeps deferring to the
      subchart's schema.
- [ ] 16.3 `helm/charts/bare-metal-storefront/tests/test_render.py`: production values
      render the ConfigMap, the overlay, and their mounts together, asserted in one helper;
      the pod environment carries only the configuration directory and the credential
      (spec scenario "The chart renders a storefront's environment"); the schema refuses a
      misspelled or secret key in `config`, naming it; break a mount once to see the test
      fail. Tier 2: load one rendered `storefront.json` with bare metal's own loader through
      an interpreter `BARE_METAL_STOREFRONT_PYTHON` names, which `test-render.sh` sets when
      bare metal's environment exists, skipping otherwise.
- [ ] 16.4 Validation: `make test-bare-metal`, `make helm-values-schema` with no diff,
      `make -C helm test-render` with both loader interpreters set, `make
      test-deployment-packaging`, `make test`. End-to-end: none in the pipeline, which
      deploys no chart.
- [ ] 16.5 Tier 3, in a local session with a cluster: deploy the umbrella with the
      bare-metal storefront enabled from the example values, confirm it starts, reports
      its loops and both projection families in status, and publishes; record the
      evidence or the blocker here. Not runnable in a cloud session.
- [ ] 16.6 Relock `domains/vms/storefront`, `kit/policy`, and `domains/vms/buyer` with
      `make lock` in an environment that reaches the PyTorch CPU index, and run `make test`
      there unrefreshed; the hand-edited locks should produce no diff. This container's
      network policy blocks that index, so each section that bumps a package one of them
      locks edits that lock by hand, and their suites run in frozen environments.

## 17. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits
documentation only; a part needing code returns the change to implementation.

- [ ] 17.1 **Comment hygiene.** Confirm `make check-comment-hygiene` passes and that no
      comment the change added names a change, a review, or a migration provenance.
- [ ] 17.2 **Import placement.** Confirm the imports each section added are at module level
      unless a recorded reason keeps one local.
- [ ] 17.3 **Documentation compliance.** Re-check D0–D6, D14a–d, C1–C12, P1, and P2 against
      the placement rules in `openspec/README.md`.
- [ ] 17.4 **Narrative compression.** Shorten Sections 2–16's notes to final behavior,
      material evidence, deferred work, and destinations; move any rationale not yet in
      `design.md` there first.
- [ ] 17.5 **Roadmap currency.** `docs/development/ROADMAP.md`: Goal 4's gap row "VM keeps
      its own per-site projection cache" is closed, and Goal 7's current state says bare
      metal holds projections and publishes on a loop, with unbacked supply still
      `unbacked-bare-metal-listings`'. Name the update in the promotion record.
- [ ] 17.6 **Campaign index currency.** `openspec/changes/README.md`: this change's row
      (status, notes) and the graph line `share-site-projection-state (held projections and
      a publication loop for bare metal) ──► unbacked-bare-metal-listings`; other rows'
      `Depends on` are archive cleanup's. Name it in the promotion record.
- [ ] 17.7 **Packaging.** `make check-packaging` and `make check-architecture-change
      CHANGE=share-site-projection-state`, resolving every failure; the change owns no
      exception row.
- [ ] 17.8 **End-to-end pipeline.** Record a passing run of all three lanes on the closeout
      commit and the scenarios exercising this change: `e2e_deal`, `e2e_deal_buyer_cli`,
      `e2e_buy`, `multi_registry`, `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`, `e2e_non_erc20_settlement`,
      `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`, `e2e_credits_deal`, `e2e_credits_payment_deal`; and
      16.5's chart evidence or its blocker.
- [ ] 17.9 **Promotion.** Write the permanent documents and complete the design-promotion
      record below:
      - `docs/development/ARCHITECTURE.md`: "Capacity publication and multi-domain storefront
        composition" (the kit owns per-site projection state; both compute storefronts
        publish on a loop over it, correcting "VM publication reads the kit's site
        projections"); "Storefront capacity boundary"; "Kit areas" (`kit/config`'s
        values-schema generator, `kit/alkahest`'s release-condition derivation); "Package
        and dependency layers" (a domain's tooling never writes another domain's artifact,
        as guidance no check enforces).
      - `openspec/specs/storefront-publication/architecture.md`: "Projection families",
        "Reconciliation", "Storefront pool overrides", "Unknown sites and inline
        reconciliation", "Autonomous publication", "Trusted site routing", "Role and
        service-peer identity", "Settlement option reconciliation".
      - `openspec/specs/market-composition/architecture.md`: "Storefront composition kit"
        (the kit's projection state and the controller's cycle boundary), "Settlement
        configuration registration" (release models a domain declares).
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Kubernetes: ConfigMap and Secret
        mounting" (the configuration-system invariant beside its pod rule); "Storefront
        agents: pass-through configuration" (`settlement_servicing_interval_seconds`, the
        rollback note that an older release ignores it and services at its 30-second
        default, `source_confirmation_seconds`); "Per-domain stack composition"; "Combined
        compute-family storefront"; "Storefront listing shapes and pool overrides" (the
        bare-metal text); "Bare-metal role configuration"; VM's startup refusal and per-site
        trust.
      - `docs/development/TESTING.md`: "Pause the loop, then advance it explicitly" (the
        bare-metal rows, `site-projections` and `publication` among its loops, and the
        API-credit row); "Chart Render Tests" (the generator in `kit/config`, bare metal's
        drift test and loader check).
      - `docs/configuration.md`: "Bare-metal storefront" (the seller chain from
        `[negotiation].policies`, not an environment variable); and
        `docs/attachments/baremetal-dispatch/index.md`: its startup and settlement text naming
        `BARE_METAL_STOREFRONT_SETTLEMENT` and the other retired variables (Section 11's
        handoff).
      - `docs/bare-metal-seller-quickstart.md`: "Configure public bindings", "Start and
        inspect".
      - `openspec/specs/README.md`: no new capability or companion; record that disposition.
      - The `spec.md` files the deltas cover (`storefront-publication`,
        `market-composition`, `deployment-state`, `negotiation-protocol`) are written by the
        archive in 17.11; the record names them.
      - **Amended (round 05/06, 10.17):** `DEPLOYMENT_AND_CONFIG.md` "Storefront agents:
        pass-through configuration" -- the storefront's one retired-key catalogue beside the
        chart's own retired values block (C4's two homes), `enable_registry_discovery` removed
        and refused, and `helm/local-values.yaml` enabling Alkahest on the release's Anvil and
        contact exchange for `deploy-local` while the chart defaults enable none (D6);
        `storefront-publication/architecture.md` "Trusted site routing" -- every site client,
        capacity and fulfillment, on its site's peer, `[provisioning.identity]` only for the
        provisioning-service client, and the stale-trust rule (D14b), and "Unknown sites and
        inline reconciliation" -- a capacity event refreshes its site's buckets first (D4);
        `market-composition/architecture.md` "Storefront composition kit" -- per-site
        capacity-event outcomes through the controller's `record_cycle` (D6). The normative
        halves are in the storefront-publication and market-composition deltas.
      - **Amended (round 08, 10.20, 10.21, 10.24, 10.25, 10.27; superseding the round 05/06
        bullet where they differ):** `DEPLOYMENT_AND_CONFIG.md` "Storefront agents: pass-through
        configuration" -- `storefront.agents` keyed by agent name, a list refused naming the map,
        an overlay stating only what it changes and `null` removing a key or an agent, the
        subchart shipping no agent, and the guidance that a chart value overlays change per
        entry is keyed, not listed; the per-agent `alkahestAddressBook` and the dev-env chart's
        Anvil address-book ConfigMap the local release mounts; the keys `arkhai-bob-runtime`
        must carry for `deploy-local` to sell under Alkahest (10.20's note);
        `[provisioning.identity]` removed and refused, so the section's sentence requiring
        `config.provisioning.identity` is corrected to the site's service peer alone;
        `storefront-publication/architecture.md` "Trusted site routing" -- no
        `[provisioning.identity]` exception, early lease termination at the reservation's site,
        and a failed reload after a change leaving the trust holding nothing until a background
        reload succeeds (in place of the stale-trust rule); `market-composition/architecture.md`
        "Storefront composition kit" -- per-site names declared as the aggregate loop's
        children, following its end, and recorders the controller issues only to them (in place
        of `record_cycle`); `TESTING.md` "Chart Render Tests" -- the storefront chart's
        `STOREFRONT_PYTHON` check runs the startup refusal and derives the local release's
        Alkahest release conditions over its render, beside the loader check.
      - **Amended (Section 12 and its check):** besides Section 12's handoff destinations,
        state that bare metal's identity routes cannot rotate an administrator (refused as not
        registered, its administrators being configuration); that the status read accepts
        every configured site's peer in both storefronts (`DEPLOYMENT_AND_CONFIG.md` and
        `storefront-publication/architecture.md` "Role and service-peer identity"); that a
        restart after a rotation needs configuration naming the replacement; and that the
        site-binding shape is a site, its URL, and its service peer, where
        `docs/bare-metal-seller-quickstart.md` (around line 156, the `authority_principal` in
        `BARE_METAL_STOREFRONT_SITES_JSON`) and `helm/charts/bare-metal-storefront/values.yaml`
        (around line 30, `siteBindingsSecret`'s entry shape, Section 16's) still show a
        principal, and health's `sites` entries now report `service_peer` and
        `authority_principals`.
      - **Amended (round 10, 13.10-13.12):** `docs/development/ARCHITECTURE.md` "Kit areas" --
        `kit/config` holds the setting types storefronts share, `PositiveSeconds` and
        `SiteAuthorityUrl`, beside its values-schema generator; `DEPLOYMENT_AND_CONFIG.md`
        "Storefront agents: pass-through configuration" and "Bare-metal role configuration" --
        bare metal's typed intervals and timeouts and VM's `[capacity].poll_interval` and
        `source_confirmation_seconds` are positive, finite numbers of seconds that can be applied
        to an instant without leaving `datetime`'s range (at most the span from year 1 to the
        epoch) and at least a microsecond, the unstated source-confirmation window (three poll
        intervals) included and refused under `[capacity].poll_interval`; VM's
        `settlement_servicing_interval_seconds` and retention sweep interval are not checked so;
        and every `[capacity.sites]` URL is an HTTP(S) origin, parsed by the WHATWG URL standard
        (pydantic's `AnyHttpUrl`) with no path, credentials, query, or fragment, handed to the
        site client as its normalized origin, refused when the storefront starts under the
        site's key, not by the chart's values schema; a host the standard accepts but nothing
        resolves fails at the first poll (D6 and D14b's round-10 notes). The normative half is the storefront-publication delta's "A
        storefront that cannot publish refuses to start".
- [ ] 17.10 **Documentation citations.** `make check-doc-citations
      CHANGE=share-site-projection-state`, resolving every match, then `bunx
      @fission-ai/openspec@1.14.0 validate share-site-projection-state --strict`.
- [ ] 17.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive share-site-projection-state
      -y`, merging the four deltas; the index row links the archive.
      **Amended (round 05/06, 05 F11; moved here from 17.10 in round 08, 08 F9):** after the
      `archive` command and before the commit, confirm that the requirement
      `domains/vms/storefront/src/market_storefront/startup_refusal.py`'s docstring cites, "A
      storefront that cannot publish refuses to start" in
      `openspec/specs/storefront-publication/spec.md`, exists there; until the archive it is
      only in the change's delta.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| | |
