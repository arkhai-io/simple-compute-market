## Why

The end-to-end pipeline (`.github/workflows/e2e.yml`) takes about twelve minutes,
and the VM lane alone sets that figure: the bare-metal and API-credit lanes finish in
under four. E2E run 42283244737 spent the VM lane's 717 seconds as follows:

| Phase | Time |
|---|---|
| Runner setup, wheels, dev-env and test images, service images | 2m21s |
| `compose up --wait` and the payments check | 35s |
| VM scenarios, 153 in series | 3m15s |
| VM IaC native Ansible gate | 5m21s |
| Logs, upload, teardown | 16s |

Two causes are not inherent to what the pipeline proves.

**The native Ansible gate sits on the VM lane's critical path without needing its
stack.** `make test-provisioning-iac-native` runs in the built provisioning image
with `--network none` and never reaches the compose stack, yet it runs after the
scenarios, in their job. Of its 321 seconds, 273 are the compute family's 19 native
tests, run in series by `unittest`: each `test_admission_installer` case drives a
real `ansible-playbook` that builds real virtual environments, taking 25–45 seconds.
They work in their own temporary directories and touch no shared path.

**Some scenarios advance on timers or on time passing, against `TESTING.md`.** An
end-to-end test proves a deterministic sequence of state changes — a sequence diagram
run repeatably — never wall-clock time; `TESTING.md` allows a stage to wait only on a
request it made. Three places in the pipeline's lanes do otherwise, and a fourth polls
where one read suffices:

- `test_buy_oneshot_buyer_cli` and `test_listing_shapes` hold the storefront's loops
  but not provisioning's fulfillment convergence or lease watchdog. Their
  `market buy` reaches `ready` only when convergence's 30-second timer next fires:
  in the run above, every such buy completed on a timer tick, about 40 seconds of
  waiting in all. This is the trap `TESTING.md` records as "A loop with no pause is
  not paused". Holds are uneven across the compute lanes generally: several modules
  hold only the storefront's loops.
- The bare-metal introduction scenario polls the held `introduction-retention` dry run
  until the retention window has passed in real time, duplicating the storefronts'
  integration tests of the held sweep.
- The API-credit buyer scenario polls through the sample app's 3-second verify cache
  after a top-up.
- The bare-metal payment scenario, having advanced provisioning to `active`, polls the
  storefront's fulfillment status for up to 30 seconds, though that status reads
  provisioning live.

Each wait costs little today, but each new scenario that copies one adds its
own, and a timer-bound scenario's duration is set by the timer rather than by
the work it does.

## What Changes

- **The native Ansible gate becomes a job of its own.** A new `e2e.yml` job,
  `native-ansible-gate`, builds the wheels and the provisioning image
  (`make build-e2e-native-gate`) and runs `make test-provisioning-iac-native`; the VM
  lane no longer runs it. The gate keeps its stance: a skipped test or an empty run
  fails it.
- **The compute family's native tests run concurrently,** one process per test,
  `os.cpu_count()` at a time, each test's output printed whole under its id, so the new
  job stays off the pipeline's critical path. The VM IaC gate keeps its serial runner.
- **Every scenario module a compute pipeline lane selects holds its lane's timers:** the
  storefront's lifecycle loops, fulfillment convergence, and the lease watchdog, and in
  the VM lane Alice's storefront loops. A source check reads the resolved fixtures of the
  modules each lane's marker expression selects and fails one missing a hold; modules no
  lane selects, such as the real-host ones, keep the holds they have, and the chain-only
  modules under `scenarios/core/` take none.
- **Buy scenarios step convergence.** `test_buy_oneshot_buyer_cli` and
  `test_listing_shapes` run `market buy` in the background and advance convergence once
  the job is submitted, through one shared helper.
- **The e2e retention-sweep stage is removed;** the storefronts' integration tests own
  the held sweep.
- **The API-credit lane runs the sample app with no verify cache,** so a top-up is
  visible to the next request.
- **The bare-metal payment scenario reads fulfillment status once** after advancing it
  to `active`.
- State: **design settled.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: "Scenarios hold shared services for the whole module" requires
  every module a compute pipeline lane selects to hold its lane's timers, enforced from
  each such module's resolved fixtures; a new requirement states that pipeline scenarios advance only by
  their own steps and wait only on effects of their own requests.

## Non-Goals

- Do not cache image layers across runs, build images once for every lane, or shard a
  lane's scenarios across several stacks. Those are the next step for scaling the
  scenario count; several stacks on one host is `isolate-end-to-end-lane-stacks`.
- Do not run a lane's scenarios in parallel within one stack: the holds are global to
  a service, and stages within a module are ordered.
- Do not add a source check rejecting `sleep` in scenario code.
- Do not change the real-host helpers (`real_provisioning`, `ssh_access`,
  `bare_metal_access`, the real compute deal driver, working-data qualification),
  which poll real hardware outside any pipeline lane.
- Do not change the refund retry in payment-compensation cleanup, which runs only
  after a scenario has failed and already takes an injected clock and sleep.
- Do not change the provisioning service's convergence interval.
- Do not add an `as-of` control to any lifecycle route, or change the API-credit
  middleware's cache behaviour.
- Do not move the bare-metal cleanup native gate (`make test-bare-metal-iac-native`)
  into a workflow; that it runs in none is recorded as an unowned roadmap gap.
- Do not hold the API-credit lane's loops; `apicredits-end-to-end-lane` owns that.
- Do not change the introduction stages' Mailpit wait, which waits on a message the
  stage's own reveal sends.

## Dependencies and Related Changes

- `apicredits-end-to-end-lane` (in design) holds and steps the API-credit storefront's
  loops and edits the same API-credit scenario module; it adopts this change's hold rule
  for its lane. Neither waits for the other; whichever lands second merges.
- `isolate-end-to-end-lane-stacks` makes several lane stacks able to share a host,
  which the deferred sharding step would build on. Neither waits for the other.
- `extract-e2e-project` (deferred) would move the harness this change edits.

## Impact

`.github/workflows/e2e.yml` (the `native-ansible-gate` job; the VM job's gate step
removed); the root `Makefile` (`build-e2e-native-gate`);
`provisioning/compute/iac/scripts/native_ansible_gate.sh`; the VM and bare-metal scenario
modules gaining holds, `test_buy_oneshot_buyer_cli.py`, `test_listing_shapes.py`,
`test_bare_metal_introduction.py`, `test_bare_metal_payment_deal.py`, and
`test_credits_deal_buyer_cli.py`; a buy helper under `e2e-tests/tests/e2e/roles/helpers/`;
`e2e-tests/tests/unit/test_scenario_holds.py` or its sibling setup-plan check;
`compose.apicredits-lane.yml` and the comment in `domains/apicredits/compose.yml`;
`TESTING.md`; `ROADMAP.md`. No runtime behaviour, wire format, persistence, or
deployment changes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — one line of the testing principle
- [x] Existing subsystem specification — `openspec/specs/test-compatibility/spec.md`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: the native Ansible gate runs as its own E2E job beside the domain lanes —
  `docs/development/TESTING.md` ("Ansible Syntax and Native Checks" and the lane list).
- D2: the compute gate runs one process per test, concurrently, each test's output
  whole — `docs/development/TESTING.md` ("Ansible Syntax and Native Checks").
- D3: no workflow runs the bare-metal cleanup native gate — an unowned gap in
  `docs/development/ROADMAP.md`.
- D4: the held retention sweep is proven at integration level, not end to end —
  `docs/development/TESTING.md` (the bare-metal lane's description).
- D5: the API-credit lane runs the gate with no verify cache, and the cache is proven by
  the conformance trace — `docs/development/TESTING.md` (the API-credit lane's
  description).
- D6: every module a compute pipeline lane selects holds its lane's timers, checked from
  the setup plan of the lane's marker selection —
  `openspec/specs/test-compatibility/spec.md` ("Scenarios hold shared services for the
  whole module") and `docs/development/TESTING.md` (the hold rule).
- D7: buy scenarios run `market buy` in the background and step convergence through one
  helper, which terminates and reaps each buy it started on any failure — `docs/development/TESTING.md` (the hold rule's paragraph on stepping).
- D8: no permanent destination — a scenario's single read after a step is what the new
  `test-compatibility` requirement already states.
- D9: no permanent destination — the Mailpit wait is unchanged, and the new
  `test-compatibility` requirement states why it complies.
- D10: no permanent destination beyond D1's — the job's name and Make target are
  self-describing in `e2e.yml` and the `Makefile`.
- The principle that an end-to-end test proves a deterministic sequence of state
  changes, never wall-clock time — `docs/development/TESTING.md` ("The discipline every
  scenario follows"), one line in `docs/development/ARCHITECTURE.md` ("Testing
  strategy"), and `openspec/specs/test-compatibility/spec.md` (the new requirement).
