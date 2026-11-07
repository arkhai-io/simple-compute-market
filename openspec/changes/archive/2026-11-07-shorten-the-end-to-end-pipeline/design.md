# Design — Shorten the end-to-end pipeline

## Context

The end-to-end pipeline (`.github/workflows/e2e.yml`) runs one job per market domain
lane. The VM lane sets the pipeline's length: in E2E run 42283244737 it took 717 s, of
which 321 s were `make test-provisioning-iac-native` run after the scenarios, and the
bare-metal and API-credit lanes finished in under four minutes.

What the code shows, and what this design rests on:

- **The native Ansible gate needs only the provisioning image.**
  `make test-provisioning-iac-native` makes three `docker run --network none` calls
  against `arkhai:compute-provisioning`: the VM IaC gate, the compute family gate, and
  the image syntax gate. It never reaches the compose stack. The compute family gate
  (`provisioning/compute/iac/scripts/native_ansible_gate.sh`) runs its 19 native tests
  (7 + 3 + 3 + 6 across four modules) serially through one `unittest` suite; the six
  `test_admission_installer` cases each run a real `ansible-playbook` over real virtual
  environments and take 25–45 s. Every test works in its own `TemporaryDirectory`, and
  its HTTP peers bind port 0.
- **Two buy scenarios wait on convergence's timer.** `test_buy_oneshot_buyer_cli` and
  `test_listing_shapes` (two buys) hold only the storefront's loops. Their non-pausing
  mock create job completes at once, but the fulfillment becomes `active` only on
  fulfillment convergence's next cycle (`fulfillment_convergence_watchdog_poll_interval_seconds: 30`),
  so each `market buy` reaches `ready` on a timer tick. Dispatch itself is synchronous
  with settlement: `test_full_deal_buyer_cli` stage 08b observes a fulfillment
  `dispatching` with convergence held.
- **Holds are uneven across the compute lanes.** Five modules hold storefront loops,
  convergence, and the lease watchdog; `test_non_erc20_settlement` holds the first two;
  seven hold only storefront loops; `test_multi_registry` holds Bob's and Alice's
  storefront loops. The lease watchdog's cycle drains the capacity-release outbox
  (`lease_lifecycle.py`), which can add capacity events between a stage's two "same
  answer twice" dry runs.
- **A lane is its marker expression, not its directory.** The lanes select modules by
  `E2E_MODULE` and `E2E_BARE_METAL_MODULE` in `e2e-tests/Makefile`. Four modules in the
  lane directories are in no lane: the two `test_real_provisioning_deal.py` modules and
  `test_bare_metal_deal.py`, which run against real hosts an operator provides, and
  `test_pool_declared_offering_modes.py`, which holds nothing. The existing setup-plan
  check finds its modules by directory.
- **The bare-metal payment status poll is redundant.** The bare-metal storefront's
  fulfillment status (`BareMetalFulfillmentService.status`) reads provisioning's status
  live on every call, so once `advance_fulfillment_to(..., "active")` returns, one read
  answers `active`.
- **The Mailpit poll waits on its own stage's message.** The shared introduction stages
  (`helpers/introduction_stages.py`), run by both `e2e_vm_introduction` and
  `e2e_bare_metal_unbacked_introduction`, poll Mailpit for the seller-side delivery,
  which the reveal request itself schedules (`SellerIntroductionDelivery.__call__`,
  an `asyncio.create_task`). That is the same shape as `wait_for_stage_event`.
- **The retention-sweep stage duplicates integration coverage.**
  `e2e_bare_metal_introduction` stage 04 polls the held `introduction-retention` dry run
  until a 5 s window passes. The bare-metal storefront's
  `test_held_retention_sweep_deletes_what_it_previewed` and VM's
  `tests/integration/test_introduction_retention.py` already hold, preview, and step the
  sweep through the production application and typed client. An `as-of` control on the
  step would conflict with `ARCHITECTURE.md`'s "Operator lifecycle controls" (a manual
  cycle runs exactly the timer's operation), the `contact-exchange-settlement`
  eligibility rule, and `test-compatibility`'s rule that test controls do not become
  production authority.
- **The API-credit wait is the gate's exhaustion cache.** Once the middleware gate finds
  a key exhausted it answers 402 without calling the service until the key's verify
  entry expires (`gate.py`), the conformance trace's "zero calls on known exhaustion".
  The base `domains/apicredits/compose.yml` sets a 3 s TTL for the e2e to poll through.

The principle the decisions apply: an end-to-end test proves a deterministic sequence of
state changes — a sequence diagram run repeatably — never wall-clock time. A timer left
running is an unscripted participant in that diagram; a wait is legitimate only on a
message the stage's own request caused.

## Goals / Non-Goals

**Goals.** The native Ansible gate leaves the VM lane's critical path; no pipeline
scenario waits on a service timer or on time passing; every module a compute pipeline
lane selects holds the timers of the services its stages message, enforced from the
setup plan.

**Non-goals.** Everything `proposal.md` lists, and: no `as-of` control on any lifecycle
route; no change to the API-credit middleware's cache behaviour; no change to the
bare-metal cleanup native gate's placement; no holding of the API-credit lane's loops,
which `apicredits-end-to-end-lane` owns.

## Decisions

### D1 — The native Ansible gate runs as its own E2E job

A new `e2e.yml` job, beside the three domain lanes, builds the provisioning image and
runs `make test-provisioning-iac-native`; the VM lane no longer runs it. The gate keeps
its stance: a skipped test, a missing callback, or an empty run fails it. The job is not
a domain lane — it composes no stack — so `TESTING.md` describes it as a job beside the
lanes.

The VM lane drops to about 6.5 minutes and the gate job to about 4 (about 2 of build,
the rest gate once D2 lands), so the pipeline's length becomes the VM scenarios. The
cost is a duplicated wheel and image build per run, in runner minutes rather than wall
time.

Rejected:

- **Running the gate in the VM job concurrently with the scenarios.** No duplicated
  build, but it competes for the runner's four vCPUs with the VM stack and 153
  scenarios, interleaves output, and does not fit the lane target, which builds and runs
  in one recipe.
- **Moving the gate to the Tests workflow.** Ansible role changes would get evidence
  before merge, at the price of a Docker image build per push and a carve-out from "the
  matrix is `make test`". Not taken: the gate's evidence stays nightly, where it is
  today.
- **Leaving it in the VM job.** Keeps the five-minute tax on every run.

### D2 — The compute family's native tests run one process per test, concurrently

The compute gate discovers its native modules' test ids as it does now and runs each in
its own child interpreter, `os.cpu_count()` at a time from a standard-library thread
pool. Each child reports what it ran, skipped, and failed as a JSON line; when a child
ends, the gate prints its whole buffered output under the test's id, then a summary.
Any failure, any skip, or no test fails the gate, as before. No worker-count override:
nothing needs one.

The three `docker run`s of `test-provisioning-iac-native` stay in sequence, and the VM
IaC gate keeps its serial runner: it has three cheap tests, and
`test_ansible_structure.py` reads its inline Python and `NATIVE` list.

Expected compute gate time is about 70–90 s, bounded by packing six 25–45 s tests onto
four workers, from 273 s; serially the gate job would outlast the VM lane.

Rejected:

- **Threads in one process.** No per-test interpreter, but tests share cwd, environment,
  and umask, and a future test mutating one would corrupt its neighbours undetected.
- **One process per module.** The admission module alone is about 200 s.
- **pytest-xdist in the image.** Adds a test dependency to a runtime image.
- **Overlapping the three `docker run`s.** Saves about 48 s on a job already off the
  critical path, at the cost of interleaved output and CPU contention with the pool.

### D3 — The bare-metal cleanup native gate stays out of this change

`make test-bare-metal-iac-native` runs in no workflow. It stays that way here, and the
gap — the bare-metal working-data helper's native account, filesystem, and IPC tests run
only when someone runs them locally — is recorded as an unowned gap in
`docs/development/ROADMAP.md`. The change keeps its proposed scope.

Rejected: adding it as a step in the new job, with a contingency to remove it if a
hosted runner refused its `SYS_ADMIN`, unconfined-AppArmor container. It has never run
on a hosted runner, and its placement is a decision of its own.

### D4 — The e2e retention-sweep stage is removed

Stage 04 of `e2e_bare_metal_introduction` is removed. The sweep is entirely the
storefront's own logic, and the storefronts' integration tests already prove the held
preview and step through the production application and typed client; `TESTING.md`
keeps system tests to what the levels below cannot prove. Stages 00–03 — disclosure
before commitment, the reveal through the production buyer transport, and operator
deletion — stay, none of them waiting. Stage 00 still checks the deployed window's
disclosure.

Rejected:

- **An `as-of` time on the dry run and step.** The step would no longer be the timer's
  operation, an operator could sweep ahead of the window, and a test control would
  become a production admin parameter — amending `ARCHITECTURE.md`, the
  `contact-exchange-settlement` eligibility rule, and `test-compatibility`'s companion.
  An operator "sweep as of T" would have to be designed as a feature.
- **`as-of` on the dry run only.** The step still deletes only what is eligible now, so
  the wait remains.
- **Keeping the stage with a written exception.** Cheap today, and exactly the pattern a
  later scenario copies.
- **A storefront test control back-dating a reveal.** The storefront has no test surface
  to host it.

### D5 — The API-credit lane runs the gate with no verify cache

The lane's own overlay, `compose.apicredits-lane.yml`, sets the sample app's
`APICREDITS_MIDDLEWARE_VERIFY_TTL_SECONDS` to 0, so every request re-verifies and a
top-up is visible to the next request. `test_credits_deal_buyer_cli` makes one request
after the top-up and expects 200. The first drain still answers 402 through the consume
path. The base `domains/apicredits/compose.yml` keeps its value for the local stack, and
its comment stops claiming the e2e polls through it. The cache's own behaviour stays
proven by the middleware conformance trace in all three ports, which is where a
single-component behaviour belongs.

Holding and stepping the API-credit storefront's loops stays with
`apicredits-end-to-end-lane`; both changes edit the same scenario module, and whichever
lands second merges.

Rejected:

- **A top-up clearing the gate's cached exhaustion.** A production change in three
  middleware ports and the conformance trace, giving up "zero calls on known exhaustion"
  or adding a service-to-gate channel. How long a topped-up key keeps answering 402 in
  production is a product question, not one the e2e tests ask: they test the sequence of
  state changes, not the time between them.
- **Moving the item to `apicredits-end-to-end-lane`.** Delays a lane-value fix behind a
  change with open questions.
- **Keeping the poll.**

### D6 — Every module a compute pipeline lane selects holds its lane's timers

Every scenario module a compute pipeline lane selects holds, for the whole module, its
lane's storefront lifecycle loops, fulfillment convergence, and lease watchdog, through
the lane's existing hold fixtures listed first. Every module the VM lane selects also
holds Alice's storefront loops (`alice_loops_held`), because her publication cycle
writes to registries other modules list. Alice's provisioning authority's timers stay
unheld: no module settles against it, and nothing reaches it except through her held
storefront loops.

A source check reads the resolved fixtures from `pytest --setup-plan`, as
`e2e-tests/tests/unit/test_scenario_cleanup_order.py` already does, of the modules each
lane selects — collected as the lane collects them, over pytest's configured test paths
with the lane's marker expression, taken from `e2e-tests/Makefile`, the one place lane
membership is written — and fails a module whose plan lacks any of its lane's holds,
naming the module and the hold. A module joining a lane, from any directory, comes under
the rule with no second list to update. The existing check refusing a pause outside the
hold fixtures stays.

Modules under `scenarios/core/` are outside the rule (review 17 F1). The VM lane's
expression selects the two there, `e2e_alkahest_escrow_codecs` and
`e2e_alkahest_trusted_oracle`; they reach only the dev chain and message no storefront or
provisioning service, so no timer their lane holds is one they meet, and the lane's hold
fixtures do not resolve outside its own directory. The exemption is by directory, so it
rests on `core/` keeping that meaning, which the package's own docstring states.

A module no lane selects is outside the rule and keeps the holds it has: the two
real-provisioning modules and `test_bare_metal_deal.py` run against real hosts an
operator provides, by hand, where a hold on a storefront the run never uses (Alice's)
would make qualification depend on it; `test_pool_declared_offering_modes.py` gains no
hold. The real modules' hold order stays checked by the cleanup-order check.
Implementation confirms that no module gaining a hold relies on a running convergence or
watchdog; the lanes' cleanup is the storefront's fleet-wide admin release, which needs
neither.

The API-credit lane is left to `apicredits-end-to-end-lane`, whose design adopts this
rule for its lane.

Rejected:

- **Holding by dependency** (the proposal): a module that drives a fulfillment to
  delivery holds convergence and the watchdog, detected from source signals. A heuristic
  a new path to delivery slips past, resting on each author's judgement of which timers
  matter — the judgement behind "a loop with no pause is not paused".
- **Every timer in the lane, Alice's provisioning included.** Fully mechanical, but needs
  two fixtures over timers nothing in the lane can reach, and likely a composite per-lane
  fixture changing the per-kind convention.
- **No check.** Leaves the rule to review alone.
- **Checking every module in the lane directories** (review 09 F1). Requires Alice's
  hold in the real VM module and holds in `test_bare_metal_deal.py`, both outside every
  lane.
- **The lane directories minus a named list of out-of-lane modules.** Simpler and fails
  closed, but the list duplicates the Makefile's lane membership, and a module promoted
  into a lane while still listed would run unchecked.
- **Each lane's directory collected with its expression** (as first implemented; review
  17 F1). Excludes the chain-only modules with no exemption to state, but a module outside
  the lane directory joining the lane runs unchecked.
- **Holding the lane's timers in the chain-only modules too** (review 17 F1). Needs the
  hold fixtures moved to a shared conftest or the modules moved, and makes chain-only
  tests depend on services they never message.

### D7 — Buy scenarios step convergence through one helper

With convergence held, a foreground `market buy` would block. `test_buy_oneshot_buyer_cli`
and both buys of `test_listing_shapes` instead run `market buy` in the background, wait
for its `escrow_created` and `settlement_submitted` run-log events and the storefront's
`provision`/`job_submitted` stage event, read the fulfillment id from the buyer-signed
settle status, drain the mock job queue, advance convergence to `active`, and wait for
`run_ended` with status `ready`. The sequence is one shared helper in the e2e helpers,
following `test_full_deal_buyer_cli`'s stages 08i, 08b, and 09a.

The helper owns each buy's process: on any exit before `run_ended` — a missing event, a
failed assertion, a timeout — it terminates the process with a bounded wait and reaps
it, in a `finally` (`MarketRun.terminate`), so a failed stage leaves no buyer polling the
stack.

Rejected: a pausing create rule, which adds stages these scenarios do not observe;
copying the sequence into each module; shortening convergence's interval in the lane,
which is a non-goal and still races; a module fixture tracking the buys' handles, as
`reap_buyer_settle_subprocess` tracks `market settle`'s (review 09 F2), since a buy
starts and ends within one helper call and never outlives it.

### D8 — The bare-metal payment scenario reads fulfillment status once

After `advance_fulfillment_to(..., "active")`, `test_bare_metal_payment_deal` reads the
storefront's fulfillment status once and requires `active`, because the storefront reads
provisioning's status live. Keeping the poll would hide a read-through regression behind
a 30 s bound.

### D9 — The Mailpit poll stays

The seller-delivery stage waits on a message the stage's own reveal sends, bounded, the
same shape as `wait_for_stage_event`, so it complies with the principle and is
unchanged. Rejected: a storefront stage event for seller delivery (a production change
with the same wait), and dispatching seller delivery inline (contrary to the delivery
kit's rule that a counterparty never waits on the seller's mail server).

### D10 — The gate job's build target and logs

The job is `native-ansible-gate` in `e2e.yml`: checkout, `setup-uv`,
`make build-e2e-native-gate`, then `make test-provisioning-iac-native`. The new root
target runs `init-prerequisites`, `dist`, then `build-provisioning`, building the wheels
first as the `build-e2e-<lane>` targets do because the pipeline runs on a fresh checkout;
it builds no dev chain or test image and needs no foundry. The gate's output goes to the
job log only, with no artifact; `make fetch-e2e-logs` keeps `actions.log`. The VM job
drops its gate step, and the `e2e.yml` header comment says where the gate runs.

## Implementation cadence

One round, two sessions, then closeout:

- **Session 1 — the gate:** the `native-ansible-gate` job and its Make target, the VM
  job's gate step removed, and the compute gate's concurrent runner.
- **Session 2 — the scenarios:** D6's holds and their setup-plan check, D7's helper and
  the three buys, D8's single read, D4's stage removal, and D5's overlay value.

The slices are small and independent; both need one E2E run as evidence, which the
round's validation provides once.

## Risks / Trade-offs

- **A module gaining a hold relied on a running timer.** Implementation checks each
  module gaining convergence or watchdog holds; the end-to-end run is the evidence.
- **Concurrent native tests contend on a four-vCPU runner.** Each admission test runs
  `pip` into its own virtual environment; if contention made one flaky, the worker count
  is the lever, not a return to serial.
- **The gate job duplicates a build.** Runner minutes, not wall time.

## Open Questions

None.

## Implementation findings

What implementation settled beyond the decisions, kept here as the tasks' notes were
compressed at closeout.

- **D2, the runner.** A module that fails to import fails the gate naming it, and each
  module pattern must match a test, not only the run as a whole. The summary ends with
  the gate's wall time. Each child runs unbuffered with the tests directory on its
  `sys.path`, since the native modules import one another by name; the parent finds the
  child's JSON line by searching back from the end, so output at interpreter exit cannot
  hide it, and judges skips, including one raised in a class fixture, from that line.
  Measured: the compute gate took 89.8 s on the pipeline's runner (E2E run 42356524201),
  inside the design's 70–90 s, from 273 s serially; locally, on 28 CPUs, 26.8 s against
  131.9 s serially. The admission tests did not contend.
- **D6, the lane-hold check.** The setup plan runs with skip marks unevaluated
  (`-p no:skipping`): otherwise a module skipped where the check runs would drop out of
  the plan and pass unchecked. Two limits remain. A module skipped at collection
  (`pytest.skip` at module level, `importorskip`) escapes the plan, as it escapes
  collection. The lane variable is read as its first non-empty assignment in
  `e2e-tests/Makefile`, so a later `+=` or conditional assignment would read the lane
  short; each lane variable has one `?=` today. The check imports `module_plans` from
  `test_scenario_cleanup_order.py`, which imports `HOLD_FIXTURE_NAMES` from
  `test_scenario_holds.py`, so moving either parser moves both checks. No module gaining
  convergence or watchdog holds relied on a running timer (the design's risk): each was
  read, and the lanes passed with the holds.
- **D7, the buy helper.** The negotiation id is read from the run log's last
  `negotiation_completed` event with status `agreed`; `escrow_created` carries none, so a
  buyer CLI that stops writing it there breaks the helper at its named step. After
  `run_ended` the helper requires the process to exit 0, as the stages' foreground buys
  did, and each wait has its own bound. `MarketRun.terminate` killed a process that
  outlived SIGTERM without waiting for it; it now waits, bounded, after the kill, so the
  helper's `finally` reaps what it starts, which a unit test over a real child ignoring
  SIGTERM proves (review 17 F2). The helper serves the VM lane only; a bare-metal buy
  would need its own stage-event and settle-status clients and the same sequence.
- **D5, the verify TTL.** With a TTL of 0 the gate's cached verify expires at once, so
  every request re-verifies and a valid verify clears the key's cached exhaustion; the
  first drain still answers 402 through the consume path. The lane run alone cannot
  separate a TTL of 0 from 3, since the top-up's negotiation and settlement likely
  outlast a 3 s cache, so `scripts/tests/test_lane_compose.py` renders both stacks and
  pins the lane's `0` and the full stack's `3`.
- **D4, declined.** The introduction scenario still declares two hosts and reveals two
  introductions, though only the first now feeds a later stage. Dropping to one host is
  a scenario edit the design did not ask for.
- **Defects fixed outside the stated scope** (`openspec/README.md#defects-found-during-a-change`).
  `scripts/tests/test_image_publication_contract.py` failed on the branch point: it
  expected a `docker tag` line that `push-images` no longer prints since it moved onto
  `scripts/publish_artifacts.py`. It now reads the `image` arguments from `push-images`'
  dry-run command line and hands them to `push_image` with a recording runner, so the
  build's tag and the pushed tag must agree. `scripts/tests/test_check_secrets.py`'s
  audit test failed in CI (validation 24 V1): the pinned gitleaks' `generic-api-key` rule
  passes a value holding one of its stop words, which about 1 in 100 of the test's random
  passwords did. The owner chose option A, a draw of a letter then a digit twenty times
  (`wordless_password()`), of which 0 in 50,000 escaped; `market-change-workflow`'s
  README, "Secret scanning", states the audit's limit. Texts describing the removed
  retention stage (the marker in `e2e-tests/pyproject.toml`, comments in
  `storefront.dev.toml` and `config-docker.yml`) and the VM IaC README naming the VM lane
  as the gate's runner were corrected.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — the native Ansible gate runs as its own job beside the lanes | `docs/development/TESTING.md#ansible-syntax-and-native-checks`; the lanes' introduction in `docs/development/TESTING.md#4-system-integration-tests-end-to-end` |
| D2 — the compute gate runs one interpreter per test, concurrently, each test's output whole | `docs/development/TESTING.md#ansible-syntax-and-native-checks` |
| D3 — no workflow runs the bare-metal cleanup native gate | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service`, open-gap row, unowned |
| D4 — the held retention sweep is proven at integration level; the introduction scenario ends with operator deletion | The bare-metal lane's bullet in `docs/development/TESTING.md#4-system-integration-tests-end-to-end`; the ADDED requirement's scenario "A behaviour depends on a window passing", `openspec/specs/test-compatibility/spec.md#requirement-pipeline-scenarios-advance-only-by-their-own-steps` |
| D5 — the API-credit lane runs the sample app with no verify cache; the conformance trace proves the cache | The API-credit lane's bullet in `docs/development/TESTING.md#4-system-integration-tests-end-to-end` |
| D6 — every module a compute pipeline lane selects holds its lane's timers, checked from the setup plan of the lane's marker selection; `scenarios/core/` exempt | `openspec/specs/test-compatibility/spec.md#requirement-scenarios-hold-shared-services-for-the-whole-module` (MODIFIED, written by the archive); the hold rule in `docs/development/TESTING.md#2-integration-tests` ("Pause the loop, then advance it explicitly") |
| D7 — buy scenarios run `market buy` in the background and step convergence through one helper that reaps on failure | The stepping paragraph after the hold rule, `docs/development/TESTING.md#2-integration-tests`; scenario "A buy reaches ready with convergence held" of the ADDED requirement |
| D8 — a single read after a step where a service reads another live | `openspec/specs/test-compatibility/spec.md#requirement-pipeline-scenarios-advance-only-by-their-own-steps` (ADDED, written by the archive); the wait paragraph in `docs/development/TESTING.md#the-discipline-every-scenario-follows` |
| D9 — the Mailpit wait stays, a wait on a message the stage's request sent | Scenario "A stage awaits a message its request sent" of the ADDED requirement; the wait paragraph in `docs/development/TESTING.md#the-discipline-every-scenario-follows` |
| D10 — the gate job's build target and logs | No destination beyond D1's: `build-e2e-native-gate` and the job are named in `TESTING.md#ansible-syntax-and-native-checks` and self-describing in `e2e.yml` and the `Makefile` |
| The principle: an end-to-end test proves a deterministic sequence of state changes, never wall-clock time | `docs/development/TESTING.md#the-discipline-every-scenario-follows`; `docs/development/ARCHITECTURE.md#testing-strategy`; the ADDED requirement |
| Pipeline scenarios no longer carry timing dependencies; real-host scenarios still poll hardware | `openspec/specs/test-compatibility/architecture.md#current-limits` (beyond the plan's list: its sentence on retained timing dependencies no longer held for pipeline scenarios) |
| Roadmap currency | `docs/development/ROADMAP.md`, Goal 1's gap row (D3); no goal's current state otherwise changes |
| Campaign index currency | `openspec/changes/README.md`, this change's row in "Lesser goal — End-to-end harness determinism" (status `in closeout`, linking the archive) and `apicredits-end-to-end-lane`'s note that its loop holding adopts the hold rule; no dependency graph and no `Depends on` changed |

`openspec/specs/README.md` needs no change: no capability or companion is added.
