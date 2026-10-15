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
      (`failure_actions.py`) reads the accepted escrow proposal before the buyer's, since
      the buyer's opening may name no condition. The VM buyer's plan check reads the
      selected chain's address book from its `[chains.<name>]`. The empty-wallet question
      (Section 6's handoff) is settled by the fail-closed rule: a recipient condition with
      an empty recipient cannot be encoded, so it refuses as `_unreadable`; derivation and
      publication still emit it (recorded in `design.md` D14d as delivered, with the owner
      question of refusing it at startup).
- [x] 7.3 `kit/policy/src/market_policy/scalar_policies.py`'s `escrow_shape_guard` (and
      `accept_exact_listing`'s same pattern): a listing advertising no condition for the
      proposal's chain rejects with its own reason instead of skipping the check.
      Done: `escrow_shape_guard` rejects `release_condition_not_advertised: …` and
      `accept_exact_listing` `exact_listing:release_condition_not_advertised`. Both still
      pass a proposal carrying no escrow address or the zero placeholder, and a listing
      accepting no escrow, so the status probes' zero-address proposal still decides. The
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
      of the condition. API credits (application integration, the runtime over a real
      database): `test_sync_negotiation.py` gains the refusal of a substituted recipient and
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
      included). Within `make -k test`: `kit/alkahest` 251 passed (unit), bare metal
      134 + 322 + 11 + 40 passed (domain, storefront, buyer, adapter), and
      `make test-apicredits`'s suites all passed (domain 41, service 72, storefront 146,
      buyer 24, sample app 1, middleware 8). `make check-packaging` (architecture rules
      included), `make check-comment-hygiene`, `make check-doc-citations
      CHANGE=share-site-projection-state` (nothing reported), and `openspec validate
      --strict` pass. The pipeline was not run for this section.

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
- Seller verification paths materialize a stored proposal: VM reads the accepted escrow
  proposal (settlement data) first, bare metal's thread pins the authorized proposal at
  the opening, and the API-credit settle path authorizes the stored proposal against the
  current listing — so an API-credit listing whose condition changed between acceptance and
  settle refuses settlement, which is fail-closed but not the committed plan; the
  API-credit storefront rebuilds its plan at settle from current configuration, as before.
- Materialization failures other than a release condition (an unknown escrow contract,
  say) are still recorded as `accepted_escrow_terms_error`; VM and API credits log them at
  debug and accept with no plan, as before this section. Bare metal refuses them.
- Open for the owner, beside Section 6's oracle-gated question: an empty seller wallet still
  derives and publishes a recipient condition with no recipient, which every deal now
  refuses as `release_condition_unreadable`; refusing it at startup would need the wallet
  at composition, which every storefront has.
- `escrow_verification.verify_escrow_for_settlement` still computes an
  `effective_recipient` from the proposal; it now reaches only its injected
  `build_obligation_data_fn` test seam and the legacy no-proposal path, not
  materialization. Left as it is.
- Section 17's promotion should carry D14d's "As delivered (Section 7)" paragraph to the
  negotiation-protocol requirement's explanation (its spec is written by the archive) and
  name `market_alkahest.proposals` as the place the invariant is held.

## 8. VM composes the shared projection state

Delivers VM on one injected `SiteProjectionState` (D2, D3, D4, C2, C7; corrections 3 and 7;
`storefront-publication` "Projection-backed listing candidate derivation"). Touches VM's
storefront only. The largest section by file count: about ten production modules and
fifteen test files, mechanically.

- [ ] 8.1 Composition: `src/server.py` builds the state once over the capacity runtime's
      aggregate client, with `wake_publication_loop` as `on_resource_pool_change`;
      `src/container.py` holds it; `src/startup.py`'s `_load_site_projections` calls
      `poll_once()`. The poller registers as the `site_projection_poller` loop on the
      controller with `register_loop`, interval `[capacity].poll_interval`, replacing
      `site_projection_poller_loop`.
- [ ] 8.2 Consumers take the injected state, never a module: `services/capacity_client.py`
      (`site_pool_projection`, `site_capacity_buckets`, `_reconcile`),
      `services/listing_sources.py`, `services/listing_source_check.py`,
      `services/publication_loop.py`, `negotiation_runtime.py`
      (`lookup_pool_policy_tags`), `failure_actions.py`, `services/system_service.py`
      (projection status from `status()`), `server.py` (`PoolOverrideService`'s
      `projection_source` reads `values(RESOURCE_POOL)` and `refresh_site` calls
      `refresh_site(site_id)`), and `controllers/admin_controller.py`.
- [ ] 8.3 Refresh categories (D4, C7): inline reconciliation in `admin_controller.py`
      (`_close_oversized_compute_listings`, `_reopen_available_compute_listings`) and
      `failure_actions.py` (`_release_capacity`) calls `refresh_site` and never wakes; the
      admin route `POST /api/v1/admin/capacity/projections/refresh` runs `poll_once()` and
      returns `status()`, whether or not the loops are held, keeping its wire contract (D3);
      the override service's wake stays as it is.
- [ ] 8.4 `lifecycle_steps.py`: the `site-projections` step runs `poll_once()` and returns
      `status()` (C2).
- [ ] 8.5 `services/site_projection_cache.py` reduced to
      `listing_cardinality_mode_explanations`, reading the state it is given; `_caches`,
      the loaders, the poller, the refresh functions, and the unused
      `refresh_after_topology_error` go, and so does VM's `_RemoteProjectionClient`, which
      2.2 copied into the kit rather than moved. Rename the module if only explanations remain, and
      fix the docstring in `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`
      that names it. Once the poller registers through `register_loop`, remove
      `SiteProjectionState.run` and its tests unless something else calls it: it reads its
      gate once and can then wait on a family's lock, the gap Section 3 closed for the
      controller's timer and the capacity-event poller.
- [ ] 8.6 Tests build their own state over `tests/fake_site.py`'s fake aggregate and inject
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
- [ ] 8.7 Validation: `make test-storefront`, `make test-vms-domain`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `multi_registry` (which
      calls the admin refresh), `e2e_listing_shapes`, `e2e_compute_dynamic_listings`,
      `e2e_pool_declared_modes`, `e2e_vm_introduction`.

## 9. VM loops on the cycle boundary, freshness, and lifecycle status

Delivers VM's loops on `run_cycle`, the confirmation window for source checks, and the
`lifecycle` status section (D5, D6; `storefront-publication` "The seller's inventory guard
checks a listing against its own source", "Operator-visible acceptance and projection
state"; `market-composition` "A loop records each cycle's outcome with the controller").
Touches VM's storefront, `core/storefront`'s status model, and the VM lane's configuration.

- [ ] 9.1 `src/lifecycle.py` and `src/lifecycle_steps.py`: every VM loop —
      `negotiation_watchdog`, `settlement_servicing`, `fulfillment_resume`, `publication`,
      `introduction_retention`, and the site-projection poller from Section 8 — registers
      its step and interval with `register_loop`; `startup.py` starts none of them as a
      self-gating task. The per-site capacity-event pollers keep their fan-out with the
      per-site lock from 3.4. Publication's cycle (`services/publication_loop.py`) names
      its stages `compose`, `run`, `converge`, and VM's configuration and publication
      errors are the controller's disclosed types.
- [ ] 9.2 Freshness (D5): `services/listing_source_check.py` confirms a listing only when
      every family it reads — resource pools, and the capacity buckets its fungible
      availability uses — is `freshly_confirmed` within `[capacity].source_confirmation_seconds`,
      defaulting to three times `[capacity].poll_interval` when not stated; any other
      condition is `unverifiable` (retryable). Document the key, commented with its default,
      in `src/settings.toml`.
- [ ] 9.3 The VM lane's overlays (`storefront.bob.toml`, `storefront.alice.toml`) widen
      `source_confirmation_seconds` to cover a held scenario's run, with a comment saying
      why, so a scenario that holds the loops and negotiates without stepping
      `site-projections` is not refused.
- [ ] 9.4 Status: `core/storefront/src/core_storefront/models/system_models.py`'s
      `HealthResponse` gains `lifecycle` (each loop's state and last outcome, from the
      controller's snapshot), and `services/system_service.py` fills it. Additive on the
      wire.
- [ ] 9.5 Tests. Unit: `tests/unit/test_listing_source_check.py` — a loaded generation past
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
- [ ] 9.6 Validation: `make test-storefront`, `make test-core`, `make test`.
      End-to-end (VM lane): `e2e_deal`, `e2e_deal_buyer_cli`, `e2e_buy`, `multi_registry`,
      `e2e_listing_shapes`, `e2e_compute_dynamic_listings`, `e2e_vm_introduction`.

## 10. VM startup refusal, per-site trust, and the interval key

Delivers VM's refusal to start without publication, its per-site service-peer trust, and
`settlement_servicing_interval_seconds` (D6, D14b, C4; `storefront-publication` "A storefront
that cannot publish refuses to start", "Site authority principals rotate with bounded
overlap"). Touches VM's storefront, its chart's generated schema, and the VM lane's
configuration.

- [ ] 10.1 Startup refusal (`src/startup.py` or a composition-time check beside it): no
      registry, or a registry without its authority pin while `enable_registry_discovery`
      is true; no enabled settlement mechanism; a configured site with no service peer or
      more than one (through 4.3). Each problem is named, and no loop starts. An empty
      `[pricing].settlements` is not a refusal.
- [ ] 10.2 Per-site trust: `services/capacity_client.py`'s `build_capacity_runtime_for`
      gives each site's `CapacitySite` the provider of that site's peer's active
      principals (4.1, 4.3) instead of the shared `[provisioning.identity]` set, and the
      runtime's cache key stops carrying principals. `[provisioning.identity]` remains
      only for `build_fulfillment_client` and `services/fulfillment_service.py`. The
      provider is read synchronously on the event loop per response, so it must not block
      on SQLite: hold each peer's principal records in memory, loaded at seeding and
      reloaded when an identity rotation, completion, or retirement commits, and evaluate
      `active_principals(now)` over them at each call (still "at verification time", D14b);
      bare metal's 12.2 composes the same provider.
- [ ] 10.3 Interval key (C4): `src/settings.toml`, `src/settlement_composition.py`,
      `src/startup.py`, and the lane overlays use `settlement_servicing_interval_seconds`; a
      configuration stating `claims_sweep_interval` refuses startup naming its replacement;
      VM's section list marks the key retired and `make helm-values-schema` regenerates
      both schemas, so an agent's `config` stating it is refused at render. The charts'
      hand-written `config.allOf` block of retired keys is a second home for retirements:
      decide between them first (Section 5 handoff).
- [ ] 10.4 The VM lane's overlays declare every site's service peer if any does not yet,
      so the lane starts under 10.1.
- [ ] 10.5 Tests. Unit: `tests/unit/test_config_loader.py` — the retired key's refusal.
      Application integration, through the typed client: startup refusals named per
      problem with no loop started; the empty-settlements storefront starts and publishes
      a pool whose override states clauses ("A storefront's terms live in its pools"); a
      site's responses verify against its peer's principals and, after the admin rotation
      routes complete a rotation and its overlap ends, only against the replacement,
      without a restart ("A site's responses follow its rotation"); a principal of one
      site does not verify another's responses. `helm/charts/storefront/tests/test_render.py`
      — `claims_sweep_interval` in an agent's `config` is refused naming the key.
- [ ] 10.6 Validation: `make test-storefront`, `make -C helm test-render` (with
      `STOREFRONT_PYTHON` for the loader check), `make test`. End-to-end (VM lane): every
      VM scenario, since each starts the storefront; and the storefront smoke tests.

## 11. Bare-metal configuration through files

Delivers bare metal on `storefront.toml`, `storefront.json`, and `storefront.secrets.toml`
under VM's keys, with Compose and the lane mounting files (D14, D14a, C4, C9, C10, C11;
`deployment-state` "Independently deployable bare-metal seller role", "A storefront's
configuration reaches it through its configuration system"; `storefront-publication` "A
storefront that cannot publish refuses to start"). Touches bare metal's storefront, the
Compose files, the root `Makefile`, `e2e-tests/`, and `scripts/tests/`. Large: every
environment read changes in one commit so the lane never runs half-converted.

- [ ] 11.1 `src/settings.toml` (new, packaged): defaults under VM's keys and defaults —
      `[Identity]`, `[Settlement]`, `[registry]`, `[capacity]` (`poll_interval = 5`,
      `publication_interval_seconds = 30`), `[pricing]`, `[negotiation]`, `[Delivery]`,
      `[Wallet]`, `[Chains]`, `base_url`, `db_path`, `negotiation_timeout_seconds`,
      `negotiation_watchdog_interval`, `settlement_servicing_interval_seconds`,
      `payment_reconciliation_interval`; and the site list, each site's URL and its service
      peer. `pyproject.toml` packages it and declares `arkhai-kit-config`.
- [ ] 11.2 `src/config.py` (new): the loader over `market_config.storefront_config_files()`
      with the packaged defaults and the loader's documented environment override layer,
      as VM's `utils/config.py` builds it, and typed models for bare metal's sections,
      named for their concepts (D14a). The signing credential stays
      `ARKHAI_IDENTITY_CREDENTIAL` and is never loaded into settings.
- [ ] 11.3 Every environment read moves to configuration, the variables retiring:
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
- [ ] 11.4 C10: a pool whose effective maximum lease duration, through its override and
      then `[pricing].default_max_duration_seconds`, is absent or not positive is held and
      reported in the cycle's per-site report; the absent default is not a startup refusal.
- [ ] 11.5 Startup refusal (D6), at composition: no `[registry].urls` or a registry without
      its authority pin; no enabled settlement mechanism; no configured site. (The
      one-peer-per-site refusal lands with durable trust in Section 12.) Each problem named,
      no loop started.
- [ ] 11.6 CLIs: `pool-override` and `publish` read the storefront's URL and identity from
      the same configuration files; `publish` still runs in-process until Section 14.
- [ ] 11.7 Development and lane files (C9): a committed development `storefront.toml` for
      bare metal (`domains/bare_metal/storefront/storefront.dev.toml`, fixture values
      commented as such) with shortened intervals as VM's overlays have, and a secrets file
      the lane writes; `domains/bare_metal/compose.yml`, `compose.bare-metal.yml`, and
      `compose.bare-metal-local.yml` mount them at `/etc/arkhai/` with `XDG_CONFIG_HOME=/etc`
      and pass only the credential through the environment; the root `Makefile`'s
      `e2e-bare-metal-dev-env` produces only bare-metal files and the variables the
      Compose files still read; `e2e-tests/Makefile` and `e2e-tests/config/config-docker.yml`
      follow.
- [ ] 11.8 Tests. `tests/test_runtime_environment.py` becomes `tests/test_config_loader.py`
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
- [ ] 11.9 Refresh the locks. Validation: `make test-bare-metal`, `make test-e2e-unit`,
      `make check-architecture`, `make check-packaging`, `make test`. End-to-end
      (bare-metal lane): `e2e_bare_metal_publication`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_introduction`.

## 12. Bare-metal durable site trust

Delivers bare metal's sites bound to durable service peers whose active principals verify
responses and callbacks, and reservations that survive a rotation (D14b;
`storefront-publication` "Site authority principals rotate with bounded overlap";
`deployment-state` "Independently deployable bare-metal seller role"). Touches bare metal's
storefront and its development configuration.

- [ ] 12.1 Startup seeds each configured site's service peer into core's durable identity
      state through 4.3, refusing a site with no peer or more than one, naming it.
      Administrators stay on configuration.
- [ ] 12.2 `src/site_clients.py`: `BareMetalSiteBinding` carries the site's peer, not a
      principal; `parse_site_bindings` reads the configuration of 11.1;
      `build_trusted_site_clients` gives each site's `SiteCapacityClient` and
      `ComputeProvisioningClient` the provider of that peer's active principals (4.1, 4.2).
- [ ] 12.3 Callbacks: `src/api.py`'s `capacity_released` and the service-role read of
      system status verify against the selected site's peer's active principals, the same
      set its responses verify against.
- [ ] 12.4 Reservations: `bare_metal_selected_site_bindings` pins the site's peer subject;
      the principal it records is an audit record, so `DurableReservationSiteMap` loads
      after an authorized rotation. Written as fresh schema in `src/migrations.py`, with
      no upgrade or backfill, because bare metal has never been deployed outside the
      development cluster; the immutability trigger keeps the binding unchanged.
- [ ] 12.5 Rotation routes: bare metal serves the identity rotation, completion, status,
      and retirement routes VM serves (`core_storefront.identity_lifecycle`), reached
      through `StorefrontClient`'s `admin_initiate_identity_rotation`,
      `admin_complete_identity_rotation`, and `admin_get_identity_status`.
- [ ] 12.6 The development `storefront.toml` and the lane's site configuration declare the
      site's service peer.
- [ ] 12.7 Tests. `tests/test_site_clients.py`:
      `test_selected_site_binding_survives_restart_and_rejects_authority_rotation` becomes a
      restart after an authorized rotation that keeps the reservation bound ("A bare-metal
      storefront restarts after a rotation"); a site with no peer, or two, refuses startup
      ("A site has no service peer"). Application integration, through the typed client:
      a rotation completed through the routes moves both response verification and
      `capacity_released` callbacks to the replacement once the overlap ends;
      `tests/test_deal_controls.py`'s per-site callback checks pass against peers;
      `tests/test_migrations.py` covers the fresh schema.
- [ ] 12.8 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_mock_deal` (its release callback), `e2e_bare_metal_publication`,
      `e2e_bare_metal_introduction`.

## 13. Bare metal on held projections and a publication loop

Delivers bare-metal publication, recheck, and overrides over the shared state, with every
loop on the cycle boundary and the scenarios holding them (D1, D2, D4, D5, D6, C2, C3, C5,
C6, C7; `storefront-publication` "Publication runs as a controllable storefront lifecycle
loop", "A site whose projection is not held holds its listings", "Bare-metal opening
rechecks its listing against its source", "Bare metal joins the site-scoped pool-override
store"). Touches bare metal's storefront and `e2e-tests/`.

- [ ] 13.1 `src/runtime.py`: builds one `SiteProjectionState` over the sites' aggregate
      client with the publication wake as `on_resource_pool_change`, held by the runtime and
      passed to every consumer; startup loads it with `poll_once()`.
- [ ] 13.2 Loops (`src/lifecycle_steps.py`, `src/server.py`): `site_projections` (step:
      `poll_once()` and `status()`, C2) and `publication` (interval
      `[capacity].publication_interval_seconds`, woken by the state) join
      `negotiation_watchdog`, `settlement_servicing`, `payment_reconciliation`, and
      `introduction_retention`, each registered with `register_loop`; `publication_lock`
      goes. Publication names its stages, and bare metal's configuration and publication
      errors are the controller's disclosed types. Each loop catches its failing cycle.
- [ ] 13.3 `src/publication.py`: `_classify_site` reads `values(RESOURCE_POOL)` and runs
      `trusted_bare_metal_projection` on the held value; a site holding nothing is
      `site_projection_unknown`, a refused generation `site_projection_refused`; the cycle
      fetches no site and records no generation.
- [ ] 13.4 `src/listing_source_check.py`: the recheck reads `view(site, RESOURCE_POOL)`,
      requires `freshly_confirmed` within `[capacity].source_confirmation_seconds`
      (default three poll intervals) and an accepted generation, and calls no site (D5).
- [ ] 13.5 Overrides: `src/runtime.py`'s `pool_override_service()` gives
      `PoolOverrideService` `projection_source` over `values(RESOURCE_POOL)`, `refresh_site`
      over the state's `refresh_site`, and the publication wake; the write's live check is
      unchanged. C3: fresh databases stop creating `bare_metal_accepted_site_generations`,
      migration `bare-metal-storefront-0011` stays in the chain with its ID retired, and
      `record_accepted_generation` and `accepted_site_projection` go.
- [ ] 13.6 C5, C7: `health()`'s `site_projections` comes from `status()` for both families
      and calls no site; `capacity_released` and the administrator reserve refresh nothing.
- [ ] 13.7 C6 (`e2e-tests/`): an opt-in per-module fixture holding the bare-metal loops,
      resumed in a finaliser, taken with `pytest.mark.usefixtures` by
      `test_bare_metal_publication.py`, `test_bare_metal_mock_deal.py`, and
      `test_bare_metal_introduction.py` (whose `held_loops` it replaces); each steps
      `site-projections` wherever a site changed before stepping publication. The
      development `storefront.toml` widens `source_confirmation_seconds` for held
      scenarios, as 9.3 does for VM.
- [ ] 13.8 Tests, application integration through the typed client:
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
- [ ] 13.9 Validation: `make test-bare-metal`, `make test-e2e-unit`, `make test`.
      End-to-end (bare-metal lane): `e2e_bare_metal_publication`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_introduction`.

## 14. Bare-metal status and the publish command

Delivers the bare-metal `lifecycle` and derivation status and the API-client `publish`
command (D6, C1; `storefront-publication` "Operator-visible acceptance and projection
state", "Publication runs as a controllable storefront lifecycle loop"). Touches bare
metal's storefront.

- [ ] 14.1 `src/models.py`'s `BareMetalHealthResponse` and `src/runtime.py`'s `status()`:
      `lifecycle` from the controller's snapshot, and the latest per-site derivation
      summary — each site's holds and their reasons, a refused generation and a pool held
      for missing terms or an unordered or absent lease bound included — as VM's
      `publication_derivation` reports.
- [ ] 14.2 `src/publication_cli.py` and `src/cli.py`'s `publish`: runs one cycle (or a
      preview) through `StorefrontClient.admin_run_lifecycle_cycle` /
      `admin_dry_run_lifecycle_cycle`, signing as the storefront's identity read from the
      configuration files, and opens no database (C1).
- [ ] 14.3 Tests. Application integration, through the typed client: status reports a
      failing cycle with its stage, a refused generation as loaded with the site's hold
      ("A bare-metal site serves a generation bare metal refuses"), and a held pool's
      reason. `tests/test_publication_cli.py`: the command reaches a running in-process app
      through its client and touches no database ("An operator runs the bare-metal
      publication command", "Publication runs from the command").
- [ ] 14.4 Validation: `make test-bare-metal`, `make test`. End-to-end (bare-metal lane):
      `e2e_bare_metal_publication`; no scenario runs the `publish` command.

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
      - `docs/bare-metal-seller-quickstart.md`: "Configure public bindings", "Start and
        inspect".
      - `openspec/specs/README.md`: no new capability or companion; record that disposition.
      - The `spec.md` files the deltas cover (`storefront-publication`,
        `market-composition`, `deployment-state`, `negotiation-protocol`) are written by the
        archive in 17.11; the record names them.
- [ ] 17.10 **Documentation citations.** `make check-doc-citations
      CHANGE=share-site-projection-state`, resolving every match, then `bunx
      @fission-ai/openspec@1.14.0 validate share-site-projection-state --strict`.
- [ ] 17.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive share-site-projection-state
      -y`, merging the four deltas; the index row links the archive.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| | |
