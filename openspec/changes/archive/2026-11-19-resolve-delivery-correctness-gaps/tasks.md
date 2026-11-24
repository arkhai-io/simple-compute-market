# Tasks

Sections 1–3 implement item 5 (the teardown rerun and the lease's wait), sections
4–6 items 1 and 2 (the relay guard and the concurrent retries), and sections 7–10
items 3 and 4 (the registry re-read and the bare-metal end). The delta
specifications are complete; no section edits them. Every section places the
imports it adds at module level
([`dependencies-python.md`, "Imports go at module level"](../../../docs/guidance/engineering/dependencies-python.md#imports-go-at-module-level))
and ends by running `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`.

Package bumps follow `docs/guidance/repository/package-versions.md`: one bump per
package per change, a minor bump for an incompatible or additive public change.
`arkhai-compute-provisioning` (`provisioning/compute`) is changed by sections 1, 2
and 5; section 1 owns its bump, and sections 2 and 5 bump it no further (D10).
Each section that bumps a package refreshes the locks that bump requires with
`make lock PROJECTS="<the projects>"` (`docs/guidance/repository/locks.md`).

## 1. A job records when its execution started and when it finished

Delivers `execution_started_at` and `finished_at` on every job, recorded by the
engine, written before a playbook is spawned and on every terminal status, and
shown on the job view (D4, D5's `finished_at`; `physical-provisioning` "A job
records that its execution is starting before it starts", the `finished_at`
sentence of "A teardown that never started is run again under a new job identity,
within a bound"; `compute-provisioning-contract` "A job view shows when its
execution started and when it finished"). Touches `provisioning/compute` (the job
authority), `provisioning/compute/ansible`, `provisioning/compute/contracts`, and
`provisioning/compute/service`'s migration chain.

- [x] 1.1 In `provisioning/compute/src/compute_provisioning/jobs/db.py`, add the
  nullable `execution_started_at` and `finished_at` columns to `JobRecord`. In
  `jobs/migrations.py`, add one additive migration after the baseline adding both
  columns to `ansible_jobs`, with an ID dated for this change, and compose it into
  the service's chain in
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
  after `SSH_CONNECTIONS_VERSION_2`. Existing rows read null in both. Verify with
  1.6's migration case. (D4, D5; `docs/guidance/engineering/migrations.md`.)
  Done: `EXECUTION_INSTANTS` (`20261118_001_ansible_jobs_execution_instants`),
  exported as the package's `MIGRATIONS` and composed after
  `SSH_CONNECTIONS_VERSION_2`. `test_database.py`'s "behind the chain" test builds
  its database with a chain lacking the last migration, since an `ADD COLUMN` is
  not rerunnable; the version-2 migration test admits the new columns reading null.
- [x] 1.2 In `jobs/executor.py`, give `JobRun` a `report_starting()` callback beside
  `report_handle`. In `jobs/engine.py`, `process_job` supplies it: it records the
  instant from the process's time source (`injected_time`, as `created_at` is) in a
  conditional write that succeeds only while the job is `running`, keeps an instant
  an earlier attempt recorded, and raises when the job is no longer `running` or the
  write fails, so the executor spawns nothing and the attempt ends through the
  engine's internal-error path, which leaves a cancelled job cancelled. Verify with
  1.5. (D4's three rules; requirement scenarios "The start cannot be recorded", "A
  job is cancelled before its start is recorded", "A retried job keeps its first
  start".)
  Done: `report_starting` is a required `JobRun` field. It writes through
  `_transition` (expected `running`) with `coalesce(execution_started_at,
  <instant>)` in the one conditional `UPDATE`, so the first instant is kept; a
  refused transition raises `JobNotRunningError`, a failed write the database's
  error. Hand-built `JobRun`s in tests pass `report_starting=lambda: None`.
- [x] 1.3 In `jobs/engine.py`'s `_transition`, stamp `finished_at` from the
  process's time source on every transition to a terminal status (`succeeded`,
  `failed`, `cancelled`), including `_fail` and the conditional `cancel_job` update,
  and never move it once set. `_status` fills the job view's two fields. Verify with
  1.5. (D5; `finished_at` from the process's time source, not `updated_at`.)
  Done: `_transition` and `cancel_job`'s `UPDATE` stamp `finished_at` on every
  terminal transition; every terminal transition expects `queued` or `running`,
  so a job finishes once and needs no guard.
- [x] 1.4 In `provisioning/compute/ansible/src/compute_provisioning_ansible/executor.py`,
  call `run.report_starting()` immediately before `runner.start_playbook`, after the
  codec's preparation and the inventory are written, so a refusal there records no
  start. The mock runner goes through the same executor. In
  `provisioning/compute/contracts/src/compute_provisioning_contracts/jobs.py`, add
  `execution_started_at: datetime | None = None` and `finished_at: datetime | None =
  None` to `JobStatusResponse`, described as the contract requirement states. Verify
  with 1.5 and the ansible executor's unit tests
  (`provisioning/compute/ansible/tests/unit/test_executor.py`): `report_starting` is
  called once before `start_playbook`, and not at all when the codec or inventory
  refuses.
  Done. Unit, `test_executor.py` (the package 190 passed, 4 skipped): the start is
  recorded once, immediately before `start_playbook`; a raising `report_starting`
  spawns nothing; codec, variables-file and inventory refusals record no start.
  Unit, the contracts' `test_jobs.py` (163 passed): absent instants read null.
- [x] 1.5 Library integration
  (`provisioning/compute/tests/integration/test_job_authority.py`): a job refused
  before its executor runs (no host, an unregistered host, an unsupported action)
  records no start and a `finished_at`; a job whose executor reports its start and
  then fails records both; a start that cannot be recorded spawns nothing (a test
  executor asserting it was never asked to start); a job cancelled between its claim
  and its start stays `cancelled` with no start; a retried job keeps its first
  start; a spawned job whose handle write fails keeps its start; a terminal job's
  `finished_at` does not move. Drive the instants with the injected time source.
  Done: library integration, 25 passed (the package 570). Tables are built by the
  package's `BASELINE` and `MIGRATIONS`. The unrecordable start is a real database
  refusal (a SQLite trigger), the failed handle write an unserializable handle,
  and the cancellation case gates the executor before its start.
- [x] 1.6 Library integration of the migration
  (`provisioning/compute/service/tests/integration/test_migration_chain.py`, as
  `docs/guidance/repository/migration-chain-tests.md` gives the chain's cases): a
  database adopted at the v0.3.0 floor gains both columns, its existing jobs reading
  null in both, and a fresh database builds them.
  Done: `test_a_v0_3_0_job_gains_execution_instants_that_read_null`; the chain's
  existing cases cover a fresh database.
- [x] 1.7 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_vms_api.py` or a sibling):
  a job read through the provisioning client carries `execution_started_at` and
  `finished_at` for a job that ran, and null `execution_started_at` with a
  `finished_at` for one refused before its playbook, as the contract's scenarios
  state.
  Done: `test_vms_api.py`'s `test_a_job_that_ran_is_read_with_its_start_and_its_finish`,
  and the refused case on `test_unreadable_host_key_api.py`'s undecryptable-key
  job; presence and order only, the exact instants being 1.5's.
- [x] 1.8 Bump `arkhai-compute-provisioning` (minor, the `JobRun` protocol and the
  job columns), `arkhai-compute-provisioning-ansible` (patch),
  `arkhai-compute-provisioning-contracts` (minor, the job view's fields) and
  `arkhai-compute-provisioning-service` (minor, the migration); raise the lower
  bounds of the packages that need the new fields (the ansible package and the
  service on `arkhai-compute-provisioning`, the service on the contracts); refresh
  the locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-compute-provisioning` 0.28.0 → 0.29.0, `-ansible` 0.8.1 → 0.8.2,
  `-contracts` 0.15.0 → 0.16.0, `-service` 0.26.0 → 0.27.0. Beyond the plan:
  `arkhai-compute-provisioning` requires the contracts `>=0.16.0` (an older model
  would drop the new fields) and the service the ansible package `>=0.8.2` (an
  older executor reports no start). Twelve projects relocked; both checks pass.
- [x] 1.9 Verification: `uv run pytest provisioning/compute/tests
  provisioning/compute/ansible/tests provisioning/compute/contracts/tests
  provisioning/compute/service/tests` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: every lane deal
  that creates and tears down records both instants on the unchanged path —
  `e2e_deal`, `e2e_vm_payment_purchase` and `e2e_bare_metal_mock_deal`; no scenario
  reads the new fields, and none is owed: the application-integration case is their
  evidence.
  Done: compute 570, ansible 190 (4 skipped), contracts 163, the service 634 unit
  and 558 integration, the VM and bare-metal adapters 287 and 138 passed;
  `pre-commit` passed. End-to-end: every lane executor is the `AnsibleJobExecutor`
  over the mock runner, so each lane deal records both instants; none is owed.

Section 1 notes:

- Outside the plan: `DEPLOYMENT_AND_CONFIG.md`'s list of the migrations after the
  v0.3.0 baseline names the new migration.
- No fail-before evidence: `scripts/change-workflow run test-before` runs
  `uv run --no-project`, whose collection fails importing the repository's
  packages; the same holds for sections 4, 7 and 10.

## 2. A teardown that never started is run again, and its lease waits for it

Delivers the rerun predicate, the provider's rerun dispatch, the engine-internal
teardown-job read, and the release status that keeps a lease `releasing` while a
rerun is pending (D3's status rule, D5, D7, D8; `physical-provisioning` "A teardown
that never started is run again under a new job identity, within a bound", "Lease
release delegates to durable fulfillment teardown", "Lease release and fulfillment
teardown have separate retry ownership", and the status rules of "An undelivered
lease is released by what its fulfillment proves"). Touches `provisioning/compute`
only; depends on section 1.

- [x] 2.1 In `provisioning/compute/src/compute_provisioning/jobs/engine.py`, add the
  engine-internal teardown-job read: unpaginated, the reservation's jobs under the
  `teardown` action kind in creation order, each as a compute-owned record carrying
  its status, whether its execution is recorded as never started (D4: `failed`, not
  `cancelled`, no `execution_started_at`, no handle, and a `finished_at`), its
  `finished_at`, and its order. It is not on the wire and not on the paginated
  listing. Verify with 2.6. (D5, 11 F5.)
  Done: `JobEngine.bound_jobs(capacity_reservation_id, action_kind)` returning
  `BoundJob(job_id, status, never_started, finished_at)` oldest first; ties on
  `created_at` are broken by the idempotency key, shorter first, so `rerun-10`
  sorts after `rerun-9`. `finished_at` is aware UTC.
- [x] 2.2 Add a module in `compute_provisioning` beside `release.py` (it is imported
  by both `job_fulfillment.py` and `release.py`, which already imports
  `job_fulfillment`), holding the rerun policy — `teardown_rerun_limit`, refusing a
  negative value with an error naming the setting, and the job retry policy's
  `delay_seconds` — and the one predicate answering `not_rerunnable` (latest job
  started, cancelled, finished before starts were recorded, or reruns disabled),
  `waiting(until)`, `ready(n)`, or `spent(n)` from the teardown-job records and the
  current instant. Export it from `compute_provisioning/__init__.py`. Verify with
  2.5. (D5, D7.)
  Done: `compute_provisioning/teardown_rerun.py` — `TeardownRerunPolicy`
  (exported from the package), `teardown_rerun(jobs, policy, now)` answering
  `NotRerunnable(reason, reruns_spent)`, `RerunWaiting(rerun, until)`,
  `RerunReady(rerun)`, `RerunsSpent(reruns_spent)` or `LatestJobUnsettled(status)`
  (counted as pending; design, "Settled during implementation"), plus
  `rerun_pending` and `never_started_account`.
- [x] 2.3 In `compute_provisioning/job_fulfillment.py`, `JobReader` gains the
  teardown-job read, and `JobFulfillmentProvider` takes the rerun policy.
  `dispatch_teardown` asks the predicate: on `ready(n)` it submits the prepared
  teardown's parameters under `JobActionRequest` identity
  `"{reservation}:teardown:rerun-{n}"`; otherwise it adopts the latest teardown job,
  submitting `"{reservation}:teardown"` only when none exists. The returned metadata
  names the latest job as `teardown_job_id` and `current_job_id`, keeping
  `create_job_id`. Update `job_contract`'s docstring to the restated rule. Verify
  with 2.6. (D5; requirement scenarios "A teardown fails before its playbook
  starts", "Dispatch is repeated after a rerun was submitted", "A compensating
  teardown fails before its playbook starts".)
  Done; `job_contract` gains `rerun=`. The policy arguments are required since
  section 3 composed them.
- [x] 2.4 In `compute_provisioning/release.py`, `FulfillmentReleaseStatusPort` takes
  the rerun policy and the teardown-job read: a `teardown_failed` aggregate whose
  predicate answers `waiting` or `ready` reports `TEARING_DOWN`; `spent` and
  `not_rerunnable` report `FAILED` with reason `teardown_failed`, the message saying,
  for a never-started teardown, that its execution never started and how many reruns
  were spent. `compensable` is unchanged. Update the module docstring. Verify with
  2.6. (D3, D5, D8; "Lease release delegates to durable fulfillment teardown".)
  Done: the port takes `rerun_policy` and `jobs` (a `BoundJobReader`, the
  engine), reads the predicate only for `teardown_failed`, and appends
  `never_started_account` to the failure message for a spent bound or disabled
  reruns.
- [x] 2.5 Unit (`provisioning/compute/tests/unit/`, a module for the predicate):
  one case per outcome — latest job started; cancelled; finished before starts were
  recorded (no `finished_at`, with and without a handle); reruns disabled; waiting
  before the delay; ready at the delay with the right *n*; spent at the limit — and
  the policy refusing a negative limit.
  Done: unit, `tests/unit/test_teardown_rerun.py`, 13 passed. "With and without a
  handle" is the read's classification, shown in 2.6.
- [x] 2.6 Library integration (`provisioning/compute/tests/integration/`, beside the
  existing job-fulfillment and release tests): through a real job engine and a
  test executor refusing before the start, a teardown fails without starting, the
  provider's next dispatch waits until the delay passes, then submits
  `rerun-1`, and the status port reads tearing down throughout; a repeated dispatch
  after an unrecorded submit adopts `rerun-1`; a rerun that succeeds reaches the
  status port's `TORN_DOWN`; a teardown whose execution started is adopted and never
  rerun; a cancelled teardown job is not rerun; the bound spent reports `FAILED`
  with its message; a compensating teardown reruns and keeps `create_compensation`
  (through `kit/fulfillment`'s `begin_compensating_teardown`, as
  `kit/fulfillment/tests/integration/test_compensating_teardown.py` sets one up).
  Done: library integration, `tests/integration/test_teardown_rerun.py`, 10
  passed, over a real `JobEngine`, provider, orchestrator and status port, each
  test making convergence's moves itself (the service's loop is 3.5's). The
  real watchdog keeping `create_compensation` across a rerun is 3.5's.
- [x] 2.7 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane induces a teardown that fails before its playbook
  starts, so no scenario exercises a rerun; the lanes' deals exercise the unchanged
  first-teardown path. None is owed: section 3's application-integration cases are
  the deployed-composition evidence.
  Done: `provisioning/compute` 593 passed; `pre-commit` passed. End-to-end as
  planned; none owed.

## 3. The composition: the rerun setting, the grace's default, and the operator's account

Delivers the rerun policy composed into both domains' providers and the release
status, `teardown_rerun_limit`, the watchdog grace's 3600-second default in the
service and both charts, and the operator handbook's upgrade step (D3, D5, D10's
session-1 scope; the grace sentences and the lease scenarios of "An undelivered
lease is released by what its fulfillment proves"; the release-failure scenarios of
"Allocation-backed lease release" and "Site-backed release lifecycle"). Touches
`provisioning/compute/service`, `domains/vms/provisioning/adapter`,
`domains/bare_metal/provisioning/adapter`, `helm`, two `e2e-tests` comments, and
`docs/operator-handbook.md`; depends on section 2.

- [x] 3.1 In `provisioning/compute/service/src/compute_provisioning_service/settings.toml`,
  add `teardown_rerun_limit = 3` with a comment stating its meaning, and raise
  `lease_watchdog_grace_period_seconds` from 300 to 3600, its comment restated as
  D3 sizes it; restate `relay_grant_expiry_grace_seconds`'s comment over the
  teardown still due, as D3 gives it, its value unchanged. Build the rerun policy
  once from the settings and the job retry policy (`services/job_retry.py`'s
  `retry_policy_from`), so a negative limit refuses startup naming the setting.
  Verify with 3.5. (D3, D5.)
  Done: the container's `teardown_rerun_policy` singleton. Beyond the plan: the
  grace's code-level fallbacks (`lease_lifecycle.py`, `app_runtime.py`) are 3600,
  and `DEFAULT_GRANT_EXPIRY_GRACE`'s comment is restated as the setting's.
- [x] 3.2 Compose the policy and the engine's teardown-job read into
  `FulfillmentReleaseStatusPort` in `compute_provisioning_service/container.py`, and
  into `JobFulfillmentProvider` in
  `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/runtime.py` and
  `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/runtime.py`
  (and their `bundle.py` where it builds the provider), from the one policy the
  service builds. Verify with 3.5. (D5.)
  Done: `build_vm_runtime` and `build_bare_metal_runtime` take
  `teardown_rerun_policy`; neither `bundle.py` builds a provider. The provider's
  and status port's policy arguments are required. Unit,
  `test_authority_composition.py`: one policy reaches both providers and the
  release status, whose job read is the container's one engine.
- [x] 3.3 Set `lease_watchdog_grace_period_seconds: 3600` in
  `helm/charts/provisioning/values.yaml` and `helm/values.yaml`, and bump each
  chart's version, since its packaged values changed
  (`docs/guidance/repository/package-versions.md`, "A version changes when its
  contents change"). Restate the 300-second grace in the comments on the lease
  back-date in `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` and
  `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py` to the
  configured grace, keeping their reasoning. Verify with `make -C helm test-render`
  and `uv run pytest e2e-tests/tests/unit`. (D3, D10.)
  Done: the provisioning chart 0.1.2 → 0.1.3 (and the umbrella's dependency on
  it), the umbrella chart 0.5.0 → 0.5.1; both values files at 3600, the
  provisioning chart's with a comment. `make -C helm test-render` passed;
  `e2e-tests/tests/unit` 956 passed, 1 skipped.
- [x] 3.4 In `docs/operator-handbook.md`, "Upgrading a deployment" — "What the
  upgrade from v0.3.0 changes": state that `lease_watchdog_grace_period_seconds`'s
  default rises to 3600 and that a deployment that pinned 300 should raise it, else
  a teardown that succeeds on a retry is timed out; that an operator who raises
  `teardown_rerun_limit`, the job retries or `ansible_timeout_seconds`, or whose
  teardowns run long, raises both graces with them; that a lease timed out with
  `teardown_timeout` while its teardown went on is released by one retry-release
  once the teardown is torn down; and, in the bullet "Leases left `release_failed`
  on a version-1 host", why those leftovers are not rerun (nothing on their jobs
  proves their playbooks never ran), keeping its manual steps. Verify by reading the
  section against D3 and D4.
  Done: three bullets before the version-1 leftovers — the grace and when to
  raise both graces; reruns, and a lease whose reruns are spent; the
  retry-release of a timed-out lease — and the leftovers' bullet says why they
  are not run again. Read against D3 and D4.
- [x] 3.5 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_ledger_lease_lifecycle.py`
  and `test_fulfillment_convergence.py`), with the injected time source:
  - a releasing VM lease whose teardown is refused before its playbook (the host's
    key made undecryptable, as `test_unreadable_host_key_api.py` does) stays
    `releasing` while a rerun is pending; once the key is restored the rerun
    reaches `torn_down` and the capacity is released, with no operator call
    ("A teardown that never started fails while the lease is releasing", "A rerun
    succeeds");
  - the same for a bare-metal lease (`test_bare_metal_leases_api.py`);
  - a teardown job that fails an attempt and succeeds on its retry within the grace
    releases its lease without an operator ("A teardown succeeds on a job retry
    within the grace period");
  - a lease still `releasing` past the grace goes to `release_failed` with
    `teardown_timeout`, and a retry-release after its teardown reached `torn_down`
    releases it under the same fulfillment, beginning no second teardown ("A
    teardown outlasts the grace period", "A timed-out teardown later succeeds");
  - a `release_failed` lease whose teardown has a rerun pending is retried, waits,
    and is released at `torn_down`, its grace timed from its return to `releasing`
    ("A failed lease's teardown has a rerun pending");
  - a teardown whose playbook ran and failed, or whose job predates `finished_at`,
    puts the lease in `release_failed` with no rerun ("Teardown fails while the
    lease is releasing", "A teardown left by an upgrade");
  - the service refuses to start with a negative `teardown_rerun_limit`, and
    `teardown_rerun_limit = 0` submits no rerun ("The rerun limit is negative",
    "Reruns are disabled").

  Done, in `test_lease_release_api.py` (the module driving release through the
  real app and typed clients) rather than the two modules named, on bare-metal
  leases with the time source injected. Seven cases: a reclaim refused before its
  playbook (a version-1 connection) waits and is released by rerun 1; limit 0
  reaches `release_failed` with no rerun; a refused reclaim with no `finished_at`
  is not rerun; past the grace with a rerun pending, `teardown_timeout`, then a
  retry-release waits for the rerun; a reclaim held past the grace, then one
  retry-release once torn down; a retryable failure after the start retried
  within the grace; a compensating reclaim rerun keeping `create_compensation`
  through the real watchdog. The negative limit is refused at the composition
  root (unit, `test_authority_composition.py`). A playbook that ran and failed is
  held by the existing compensation tests, unchanged. No VM rerun test is owed
  (design, "Settled during implementation").
- [x] 3.6 Bump `arkhai-vm-provisioning-adapter` and
  `arkhai-bare-metal-provisioning-adapter` (or the names their `pyproject.toml`
  states; minor, the provider's new argument) and raise their lower bound on
  `arkhai-compute-provisioning`; the service's bump is section 1's. Refresh the
  locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-vms-provisioning-adapter` 0.19.1 → 0.20.0 and
  `arkhai-bare-metal-provisioning-adapter` 0.13.1 → 0.14.0, both on
  `arkhai-compute-provisioning>=0.29.0`, the service raised to them. Both checks
  pass.
- [x] 3.7 Verification: `uv run pytest provisioning/compute/service/tests
  domains/vms/provisioning/adapter/tests domains/bare_metal/provisioning/adapter/tests`
  passes, `make -C helm test-render` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: the lanes'
  back-dated-lease stages run under the new grace — `e2e_vm_payment_purchase`,
  `e2e_deal_buyer_cli` and `e2e_bare_metal_payment_deal` release their leases
  through the unchanged path; none induces a rerun or a timeout, and none is owed.
  Done: the service 636 unit and 565 integration, the VM adapter 287, the
  bare-metal adapter 138, the compute package 593 passed; `make -C helm
  test-render` and `pre-commit` passed. End-to-end: the lanes run under the
  charts' grace with reruns on; none refuses a teardown before its start, and
  none is owed.

Section 3 notes:

- Outside the plan: the service suite's signed ASGI transport signs with
  `injected_time.now()`, since the service checks timestamps against the injected
  source. Its `/test` routes need the `mock` profile: run it through `make -C
  provisioning/compute/service test`.
- Pre-closeout triage fix (60 F1; design, "Settled during implementation"): a
  teardown that keeps failing to begin reaches the grace. Unit,
  `test_lease_lifecycle.py`'s
  `test_a_transient_failure_to_begin_in_the_releasing_pass_is_retried_within_the_grace`
  (compute 595 passed); application integration, `test_lease_release_api.py`'s
  `test_a_teardown_that_keeps_failing_to_begin_times_out_after_the_grace` (the
  service 636 unit and 568 integration passed); both failed with the fix set
  aside; `pre-commit` passed at `adaf09539`.

## 4. An equivalent acceptance that waited on another returns the first

Delivers acceptance judged from the row its lock returns (D2's acceptance half;
`fulfillment` "An equivalent acceptance that waited on another returns the
first"). Touches `kit/fulfillment` only. A defect found during the change, outside
item 2's stated scope; record it so in this section's task notes
(`docs/guidance/workflow/changes.md`, "Defects found during a change").

- [x] 4.1 In `kit/fulfillment/src/market_fulfillment/settlement_repository.py`,
  `accept_fulfillment`'s locked select takes `populate_existing`. In
  `fulfillment_persistence.py`, `FulfillmentTransaction.accept` drops its unlocked
  pre-read, and `FulfillmentAcceptanceDecision` drops `newly_accepted`; confirm no
  caller reads it (`git grep -n newly_accepted`). Verify with 4.2. (D2, 11 F7.)
  Done: the select takes `populate_existing`; `accept` reads nothing before the
  lock; no caller reads `newly_accepted` (the unit suite's `FakeTransaction`
  drops it).
- [x] 4.2 Library integration
  (`kit/fulfillment/tests/integration/test_fulfillment_acceptance.py`): two sessions
  on one file-backed database — session 2 loads the reservation's row, session 1
  accepts and commits, session 2 accepts an equivalent request and receives session
  1's `fulfillment_id`, the row keeping that identity and its prepared operation,
  with nothing prepared or persisted a second time; and without the fix's
  `populate_existing`, the same steps would accept anew (state the stale read the
  test pins in its docstring). Sequential steps, no threads
  (`docs/guidance/engineering/concurrency-tests.md`).
  Done: library integration,
  `test_an_acceptance_that_read_the_row_before_another_committed_returns_the_first`,
  passes, through a real `begin_fulfillment` over the SQLAlchemy unit of work, the
  second handed the session that read the row first: one fulfillment, one
  prepare, one dispatch. The module's tests build their database from the kits'
  baselines. Fail-before not shown (section 1's notes).
- [x] 4.3 Bump `arkhai-kit-fulfillment` (minor, the exported
  `FulfillmentAcceptanceDecision` loses a field) and refresh the locks it requires.
  Verify with `make check-version-bumps` and `make check-locks`.
  Done: 0.8.0 → 0.9.0; no lower bound moves. Eight projects relocked; both
  checks pass.
- [x] 4.4 Verification: `uv run pytest kit/fulfillment/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: every lane deal accepts its fulfillment once, on the unchanged
  path (`e2e_deal`, `e2e_bare_metal_mock_deal`); no lane overlaps two acceptances,
  and none is owed (design, Open Questions: the PostgreSQL proof).
  Done: `make -C kit/fulfillment test` 213 passed; `pre-commit` passed. End-to-end:
  each lane deal accepts once, none overlaps two acceptances; none is owed.

Section 4 notes:

- A defect found during the change, outside item 2's stated scope (D2;
  `docs/guidance/workflow/changes.md`, "Defects found during a change"), reachable
  wherever two acceptances overlap, as on PostgreSQL.
- The stale read needs pysqlite's default transaction handling: the earlier
  `SELECT` opens no transaction, so only the identity map is stale.
- Deferred: some 25 test modules still build tables with `create_all`, an unowned
  gap row in `openspec/changes/README.md` under Goal 1.

## 5. A concurrent allocation for one owner receives that owner's lease

Delivers the allocator's owner read after the relay lock and again on any
uniqueness conflict (D2's allocator half; `physical-provisioning` "A concurrent
allocation for one owner receives that owner's lease"). Touches
`provisioning/compute/src/compute_provisioning/relays/allocator.py` and its
tests; depends on section 1, which owns `arkhai-compute-provisioning`'s bump, so
this section bumps nothing and refreshes no lock for it.

- [x] 5.1 In `relays/allocator.py`, `allocate_in_session` reads the owner's active
  lease after `db.get(Relay, …, with_for_update=True, populate_existing=True)` and
  before refusing a missing or disabled relay, returning it when held; in the claim
  loop, on `IntegrityError` it reads the owner's active lease again and returns it
  when one exists, moving to the next port only otherwise. Restate the docstring
  and the index comment in `relays/db.py` to the rule. Verify with 5.2.
  Done: one method, `_owner_lease`, after the relay's locked read, in the claim
  loop's `IntegrityError` branch, and in `find_active_lease`; a method so 5.2's
  subclass can stand for a stale read. Docstring and index comment restated.
- [x] 5.2 Library integration
  (`provisioning/compute/tests/integration/test_relay_port_allocator.py`): the
  statement order rendered for the PostgreSQL dialect shows the owner read after the
  relay's `FOR UPDATE`, as `test_the_relay_is_read_for_update_before_a_port_is_claimed`
  does; a test-only allocator subclass whose first owner read misses while the
  owner's lease exists returns that lease and raises no `RelayWindowExhaustedError`;
  a claim conflicting with another owner's port selects another and raises
  exhaustion only when the window is full; an owner holding a lease on a disabled
  relay receives it and no `RelayDisabledError` (the existing drain scenario, kept
  passing).
  Done: library integration, the module 37 passed: the owner read follows
  `relays … FOR UPDATE` as rendered for PostgreSQL; a first owner read made to
  miss returns the owner's lease committed on another relay, with no exhaustion;
  the stale-scan test, on a two-port window, moves to the next free port; the
  drain scenario passes unchanged. A real PostgreSQL interleaving is not shown
  (design, Open Questions).
- [x] 5.3 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane runs a relay-backed pool, so no scenario exercises
  allocation; none is owed.
  Done: `make -C provisioning/compute test` passed; `pre-commit` passed at
  `7bd6ff327`. End-to-end: no lane runs a relay-backed pool; none is owed.

Section 5 notes:

- No package bump (D10). The delta's full-window sentence is scoped to a relay
  that exists, a missing relay refused with the same error (implementation
  review 49's triage, its §5 note).

## 6. A relayed delivery's relay is its declaration's pool's

Delivers the tests holding D1's rule (D1; `physical-provisioning` "A relayed
delivery's relay is its declaration's pool's"). Touches tests only:
`provisioning/compute/iac/tests`, `domains/vms/provisioning/adapter/tests`, and
`provisioning/compute/service/tests`.

- [x] 6.1 Static test of the family roles
  (`provisioning/compute/iac/tests/test_client_baseline.py`, or beside it): the
  `relay-proxy` role's `add.yml` includes `relay-client` before adding the proxy;
  `relay-client` synchronizes the baseline from `frp_server_addr`,
  `frp_server_port` and `frp_auth_token` and notifies the client's restart only on a
  changed baseline; and `client_config.py prepare`, run on a configuration naming
  another relay with a proxy block, rewrites the three fields, reports `changed`, and
  keeps the proxy block ("A proxy is added on a host whose client names another
  relay").
  Done. Static, `test_relay_assets.py`'s
  `test_a_proxy_is_added_only_after_the_client_baseline_names_the_jobs_relay`
  (the include order, the three fields, the restart notified on `changed` and
  flushed). Library integration, `test_client_baseline.py`'s
  `test_a_client_naming_another_relay_is_pointed_at_the_jobs_and_keeps_its_proxies`
  (`client_config.py prepare` as a subprocess: `changed`, fields rewritten, proxy
  block kept, `unchanged` on a rerun). No test runs the role on a host.
- [x] 6.2 Library integration
  (`domains/vms/provisioning/adapter/tests/integration/test_relay_pool_configuration.py`):
  a host placed in a pool on relay R2, and an unplaced host, each with its
  declaration in a pool on R1, are leased a port on R1 by an accepted relayed
  create, whose prepared job carries R1 as its relay ("A host placed under another
  relay delivers through its declaration's", "An unplaced host delivers through its
  declaration's relay").
  Done, at application integration rather than in the VM adapter's file:
  `provisioning/compute/service/tests/integration/test_fulfillment_api.py`'s
  `TestRelayPortLifecycleOverTheApi.test_a_create_is_leased_on_its_declarations_pools_relay`,
  parametrized over a host placed in a pool on R2 and an unplaced host, each
  declared in a pool on R1, all through the canonical clients: R1 holds the
  lease, R2 none, and the job carries R1. Why at this level: design, "Settled
  during implementation".
- [x] 6.3 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_capacity_api.py`): a
  declaration in a pool on R1 whose reservation holds a relay port lease on R1 is
  refused a move to a pool on R2, and stays in its pool ("A declaration holding a
  lease is moved to a pool on another relay").
  Done by the existing `test_capacity_api.py`'s
  `test_a_held_resource_moves_pools_only_once_released`; no relay-specific test
  is owed (design, "Settled during implementation").
- [x] 6.4 Verification: `uv run pytest provisioning/compute/iac/tests
  domains/vms/provisioning/adapter/tests provisioning/compute/service/tests/integration/test_capacity_api.py`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: no lane runs a
  relay-backed pool; none is owed. The real-provisioning modules
  (`e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning`) exercise relayed
  delivery but run in no lane.
  Done: `make -C provisioning/compute/iac test` 35 passed, 19 skipped (native
  Ansible, as before); `test_fulfillment_api.py` and `test_capacity_api.py` 70
  passed; the VM adapter 295 passed; `pre-commit` passed at `5eb9527c4`.
  End-to-end: no lane runs a relay-backed pool; none is owed.

Section 6 notes:

- Tests only; no package bump.
- The delta's "restarting the client only when that baseline changes", and the
  older hardening requirement's "restarted only when its relay baseline changes",
  left out the `relay-client` role's unit-file task, which also notifies the
  restart: the unit names the versioned binary, so a moved frp pin takes effect
  by it. Closeout review 67's triage (F1) amended both permanent requirements to
  admit a restart when the client's service unit changes.

## 7. The descriptor read selects registries, and the policy reads again what failed

Delivers the core storefront's selective descriptor read and the dispute policy's
per-registry read state and re-read (D6's read half; `settlement-configuration` "A
storefront reads again a registry whose recommendations it could not read", its
read scenarios). Touches `core/storefront` and `kit/storefront`.

- [x] 7.1 In `core/storefront/src/core_storefront/multi_registry_client.py`,
  `MultiRegistryClient.get_descriptors` gains an optional selection of registry
  URLs, absent meaning every configured registry as now, reading and returning only
  those selected. Verify with the core storefront's tests for the client: a
  selection reads only the selected registries and an absent one reads all.
  Done: `get_descriptors(registries=None)`, in configured order. Unit,
  `test_multi_registry_descriptors.py`: no selection reads all, a selection only
  those, an empty one none.
- [x] 7.2 In `kit/storefront/src/market_storefront_kit/dispute_configuration.py`,
  `RegistryDisputePolicy` keeps, per registry, whether its last read succeeded and
  when it last failed (the injected time source); `refresh` records them; a new
  re-read reads only the registries whose last read failed, through the selection,
  keeping the others' recommendations; and the policy exposes its unread registries
  with their last failure. Verify with 7.3.
  Done: the policy keeps each registry's recommendations, its unread set and
  last failures (its `clock`, the process's source); `reread()` builds no client
  while none is unread and resolves again only when a registry was read;
  `unread_registries()` returns `UnreadRegistry(url, last_failed_at)`. Beyond the
  plan: `readiness_resources()`, the one projection the three storefronts pass,
  keyed by `DISPUTE_AUTHORITIES_UNREAD`.
- [x] 7.3 Unit (`kit/storefront/tests`, beside the dispute configuration's tests):
  a startup read in which one of two registries fails, then a re-read, reads only
  the failed one and adopts its recommendations while keeping the other's ("One of
  several registries could not be read"); a re-read after every read succeeded
  reads nothing ("A registry was read"); the unread registries are reported with
  their last failure until a read succeeds.
  Done: unit, `kit/storefront/tests/unit/test_dispute_configuration.py`, 5
  passed: the three planned cases, an unopenable client, and a seller opting out.
- [x] 7.4 Bump `core/storefront`'s package (minor, the additive parameter) and
  `kit/storefront`'s (minor), raise `kit/storefront`'s lower bound on the core
  package, and refresh the locks. Verify with `make check-version-bumps` and `make
  check-locks`.
  Done: `arkhai-core-storefront` 0.18.0 → 0.19.0, `arkhai-kit-storefront`
  0.11.0 → 0.12.0 on `arkhai-core-storefront>=0.19.0`. Beyond the plan, for the
  exact pins: `arkhai-kit-capacity-publication` 0.12.0 → 0.12.1, and the three
  storefronts' minor bumps, which 9.3 planned — VM 0.28.0 → 0.29.0, bare metal
  0.28.0 → 0.29.0, API credits 0.21.0 → 0.22.0. Eleven projects relocked; both
  checks pass.
- [x] 7.5 Verification: `uv run pytest core/storefront/tests kit/storefront/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.
  Done: the core storefront 237 and the storefront kit 146 passed; `pre-commit`
  passed at `703750505`. End-to-end: section 9's.
- [x] 7.6 In `MultiRegistryClient.get_descriptors`, refuse a selection naming a URL
  `urls` does not name, and a string passed in place of a collection, with
  `ValueError` naming the problem; an empty selection still reads nothing (D6,
  40 F4). This restores, by the owner's decision, the refusal of an unconfigured
  selection the fresh-context check removed (the notes below). Unit, in
  `core/storefront/tests/unit/test_multi_registry_descriptors.py`: an unknown URL
  and a bare string are refused and read no registry. No bump: 7.4's is unreleased.
  Verify with `make -C core/storefront test`.
  Done: both refusals precede any read; a URL is matched exactly. Unit, new cases
  in `test_multi_registry_descriptors.py` (the core storefront 240 passed). The
  refusal meets "No speculative guard code" (design, "Settled during
  implementation"). Fail-before not shown (section 1's notes).

Section 7 notes:

- Implementation review 49 F1's fix: `RegistryDisputePolicy` holds one lock
  across `refresh()` and `reread()` (design, "Settled during implementation").
  Unit, `test_overlapping_rereads_read_once_and_a_success_stays_read` (the kit
  147 passed), which failed against the unfixed policy in its first draft;
  `pre-commit` passed at `24e786a30`. No bump: the kit's 0.12.0 is unreleased.

## 8. The mechanisms report an unread registry in their public details

Delivers `dispute_authorities_unread` as a public detail of the Alkahest and Arkhai
Payments mechanisms' readiness, with no blocker (D6's report half;
`settlement-configuration` "A storefront reads again a registry whose
recommendations it could not read", its readiness clauses). Touches `kit/alkahest`
and `kit/arkhai-payments`.

- [x] 8.1 In `kit/alkahest/src/market_alkahest/settlement_config.py`, add
  `dispute_authorities_unread` to the registration's public-detail allowlist and copy
  it from the preflight's resources into its public details, as `chain_probe` is,
  adding no blocker. In `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`,
  the registration allowlists the key and `arkhai_payments_preflight` copies it from
  its resources. Verify with 8.2.
  Done: each module names the key once, privately (neither kit may import the
  storefront kit), and each enabled preflight copies a non-empty value with no
  blocker; a disabled mechanism reports none, as before.
- [x] 8.2 Unit (each kit's settlement configuration tests): with
  `dispute_authorities_unread` in its resources, each mechanism's readiness carries
  it in its public details, stays ready with no blocker for it, and passes
  `SettlementConfigurationRegistry`'s public-detail validation; without it, the
  details are as before.
  Done: unit, `test_an_unread_registry_is_a_public_detail_and_no_blocker` in
  `kit/alkahest/tests/unit/test_settlement_config.py` and in
  `kit/arkhai-payments/tests/test_settlement_config.py`, through the registry's
  validation over each real registration.
- [x] 8.3 Bump `kit/alkahest`'s and `kit/arkhai-payments`'s packages (minor) and
  refresh the locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-kit-alkahest` 0.13.0 → 0.14.0, `arkhai-kit-arkhai-payments`
  0.8.0 → 0.9.0. Beyond the plan, for the exact pins on Arkhai Payments: the
  bare-metal buyer 0.8.0 → 0.8.1. Eighteen projects relocked; both checks pass.
- [x] 8.4 Verification: `uv run pytest kit/alkahest/tests kit/arkhai-payments/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.
  Done: `kit/alkahest` 466 and `kit/arkhai-payments` 355 passed. `pre-commit`
  failed only in Compose-rendering release-tooling cases with no Docker daemon
  running, an environmental cause; section 10's `pre-commit` and validation 65's
  local run passed every suite. End-to-end: section 9's.

Section 8 notes:

- The flat `kit/arkhai-payments/tests` is an existing unowned gap row
  (implementation review 49's triage).

## 9. The storefronts read again at publication and pass the unread registries on

Delivers each storefront's publication cycle reading again the registries whose
read failed, and its readiness resources carrying them (D6's composition;
`settlement-configuration` "A storefront reads again a registry whose
recommendations it could not read", its storefront scenarios). Touches
`domains/vms/storefront`, `domains/bare_metal/storefront`, and
`domains/apicredits/storefront`; depends on sections 7 and 8.

- [x] 9.1 In each storefront, the publication cycle's `compose` stage calls the
  policy's re-read before composing options
  (`domains/vms/storefront/src/market_storefront/lifecycle_steps.py`'s publication
  step, and the bare-metal and API-credit storefronts' `lifecycle_steps.py`), and
  the settlement composition passes the policy's unread registries into the
  mechanism readiness resources under `dispute_authorities_unread` wherever
  readiness is computed (`settlement_composition.py` in each), only while
  `use_registry_dispute_authorities` is true. Startup's read is unchanged; `/health`
  reads none of it. Verify with 9.2.
  Done. The re-read: the VM storefront's in `run_publication_cycle_once` after
  its `compose` stage is entered, the bare-metal storefront's in its publication
  step after `enter_stage("compose")`, a preview reading nothing; the API-credit
  storefront, which has no cycle, as the first act of `publication_artifacts`.
  Each composition merges `disputes.readiness_resources()` into every readiness
  it computes. `reread()` takes no argument (design, "Settled during
  implementation").
- [x] 9.2 Application integration (each storefront's tests, with a registry double
  that fails then answers): a storefront whose startup read failed, relying on
  registry recommendations alone, publishes the payments option the recommendations
  allow on the first publication cycle after the registry answers, without a
  restart ("A storefront starts before its registry"); while unread, `settlement
  status` shows `dispute_authorities_unread` on each affected mechanism with no
  blocker and `/health` answers healthy ("A registry is still unread"); a storefront
  with a local `[[Dispute]]` entry publishes its options while its registry is
  unread, the mechanism ready ("A storefront with local authorities whose registry
  is unread"). One storefront carries the full cases; the other two carry the
  restart-free case.
  Done: application integration through each storefront's typed clients, the
  real composition and policy, and a registry double where `MultiRegistryClient`
  wraps the registries; each module `tests/integration/test_registry_dispute_authorities.py`.
  - VM (2 passed): recommendations alone publish nothing while unread, status
    reporting the registries with no blocker; the next cycle after they answer
    publishes the payments option, and a further cycle reads none; a local entry
    publishes while unread.
  - VM real startup (`test_degraded_startup.py`, extended): health answers, and
    status shows `dispute_authorities_unread` beside the existing reachability
    blocker alone.
  - Bare metal (1 passed) and API credits (1 passed): the restart-free case
    through the publication step and a listing creation.
- [x] 9.3 Bump the three storefront packages (minor) with their lower bounds on the
  packages sections 7 and 8 bumped, and refresh the locks (`domains/vms/storefront`
  resolves the PyTorch CPU index, `docs/guidance/repository/locks.md`). Verify with
  `make check-version-bumps` and `make check-locks`.
  Done: the bumps are 7.4's; lower bounds `arkhai-kit-alkahest>=0.14.0` and
  `arkhai-kit-arkhai-payments>=0.9.0` (bare metal pins it, 8.3). Both checks pass.
- [x] 9.4 Verification: `uv run pytest domains/vms/storefront/tests
  domains/bare_metal/storefront/tests domains/apicredits/storefront/tests` passes,
  and `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: the lanes' payment and dispute scenarios publish options from
  a registry that answers at startup — `e2e_vm_payment_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` — exercising the
  unchanged startup read beside the new cycle; no lane starts a storefront before
  its registry, and none is owed.
  Done: the VM storefront 1196 unit (1 skipped) and 615 integration, bare metal
  659, API credits 286 passed. `pre-commit` failed only for section 8's
  environmental cause. End-to-end: the three lanes publish from a registry
  answering at startup, so the re-read reads nothing; none is owed.

Section 9 notes:

- The system status route, not the `settlement status` command, carries the
  report (40 F2), and the API-credit storefront re-reads at listing creation or
  seeding (40 F3); the delta and D6 state both.

## 10. A bare-metal end under a delivery conflict, and the result read while a lease ends

Replanned against the reviewed design after the return to design (D9 as restated,
design review 40 F1).

Delivers a buyer's end under a delivery conflict, not refused and reported as an
ending by the reads after it; the result read answering the recorded result while a
lease is `terminating`; and the dead method's deletion (D9; `storefront-publication`
"A bare-metal delivery that conflicts with its recorded result is refused", its
scenario "A buyer ends a deal while the site reports a different delivery", and "A
bare-metal result read answers the recorded result while its lease ends").
Touches `domains/bare_metal/storefront` only: its `api.py`, its
`fulfillment_service.py` (the deletion, already committed), and
`tests/test_http_settlement.py`.

- [x] 10.1 In `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py`,
  `fulfillment_result` admits `terminating` (the module's `TERMINATING`, from
  `fulfillment_service.py`, rather than a second literal) among the lifecycle
  states its result is answered in, and keeps answering "bare-metal fulfillment
  result is not ready" when no receipt or result is recorded. The read still goes
  through `status` first, so an active lease under a conflict is still refused with
  `delivery_conflict`. Verify with 10.3. (D9, 40 F1; "A bare-metal result read
  answers the recorded result while its lease ends".)
  Done, beyond the plan's file so the route stays thin (`implementation.md`, "Thin
  controllers"): the route calls `BareMetalFulfillmentService.result()`, which
  reads through `status` and answers in `_RESULT_STATES` (`active`, `TERMINATING`,
  the teardown states and `released`), else "not ready". Evidence: 10.3.
- [x] 10.2 Confirm `BareMetalFulfillmentService.converge_teardown` is deleted from
  `fulfillment_service.py` (committed at `1d93f5d5f`) and nothing calls it: `git
  grep -n converge_teardown -- ':!openspec' ':!docs'` names only the provisioning
  service's `converge_teardowns` and the e2e comments naming it. (D9.)
  Done: the grep names nothing in the bare-metal storefront.
- [x] 10.3 Application integration through the storefront's typed clients, in
  `domains/bare_metal/storefront/tests/test_http_settlement.py`:
  - `test_a_delivery_other_than_the_recorded_result_is_a_conflict`, as extended at
    `1d93f5d5f`, restated to the scenario: before the end the status, result and
    access reads answer 409 `delivery_conflict`; the buyer's lifecycle `end` (the
    buyer transport's `teardown`) answers `tearing_down` and calls `terminate_lease`
    once for the reservation; afterwards the status read reports the lease ending
    (its state not `active`), the result read answers the recorded result unchanged,
    and the access read is refused with 409 as outside an active lease, none of
    the three with `delivery_conflict`; the stored result is unchanged. Its
    docstring names the scenario as restated ("A buyer ends a deal while the site
    reports a different delivery").
  - a delivered deal, no conflict, whose lease the buyer ends while the site still
    reports the fulfillment `active` — the provisioning double given a way to leave
    `torn_down` unset on `terminate_lease`, defaulting to today's behaviour so no
    other test changes — so the lease reads `terminating`: the result read answers
    the recorded result and receipt ("A buyer reads the result of a deal whose
    lease is ending");
  - a lease ended before any result is recorded — dispatched or begun, ended
    through the lifecycle `end` before delivery is driven — whose result read
    answers 409 "not ready" ("A lease ends before delivery"). If the module's
    harness cannot end a begun lease before delivery through the typed clients,
    record why in the section's notes and state the case at the lowest level that
    reaches the route.
  Verify with `make -C domains/bare_metal/storefront test`.
  Done: application integration, the real storefront app driven by the
  production buyer's `BareMetalFulfillmentTransport` after a settle through
  `StorefrontClient` (`make -C domains/bare_metal/storefront test` 662 passed):
  - `test_a_delivery_other_than_the_recorded_result_is_a_conflict`, parametrized
    over the site still reporting the other delivery or having torn it down: 409
    `delivery_conflict` before the end; the end terminates the lease once;
    afterwards the lease's state, the recorded result, and access refused as
    outside an active lease, none with `delivery_conflict`.
  - `test_a_result_is_read_as_recorded_while_its_lease_ends`.
  - `test_a_lease_ended_before_delivery_has_no_result`, through the typed
    clients.
  The provisioning double gains `tears_down_on_termination` (default true) and a
  class attribute `state`. Fail-before not shown (section 1's notes).
- [x] 10.4 No package bump: `arkhai-bare-metal-storefront` is at 0.29.0 from 7.4,
  unreleased in this change (D10), and no lock moves. Verify with `make
  check-version-bumps`.
  Done: no bump and no lock moved; `make check-version-bumps` passes.
- [x] 10.5 Verification: `make -C domains/bare_metal/storefront test` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes (Docker running, since `make test`'s `test-release-tooling` renders
  Compose files; sections 8 and 9's notes). Record in the section's notes that
  the result read during `terminating` is a defect found during the change, outside
  item 3's stated scope (`docs/guidance/workflow/changes.md`, "Defects found during
  a change"; D9). End-to-end: `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_payment_deal` and `e2e_bare_metal_deal` end their deals through
  the buyer's teardown with no conflict and read the result only while the lease
  is active (`compute_deal_driver.py`'s `assert_delivery`) and status after the end
  (`released`); they exercise the unchanged path beside the new admitted state. No
  lane plants a conflicting delivery or reads the result while a lease is
  `terminating`, and none is owed: 10.3's application-integration cases are the
  evidence.
  Done: 662 passed; `pre-commit` passed at `195a67c32` with this section's edits,
  every suite of `make test` included. End-to-end: `e2e_bare_metal_mock_deal` and
  `e2e_bare_metal_payment_deal` (the bare-metal lane) read the result while the
  lease is active and status after the end; `e2e_bare_metal_deal` is in no lane,
  since it needs a real host. No lane plants a conflict or reads a result while
  a lease is `terminating`; none is owed.

Section 10 notes:

- The result read answering "not ready" while a lease is `terminating` is a
  defect found during the change, outside item 3's stated scope (D9;
  `docs/guidance/workflow/changes.md`, "Defects found during a change"), fixed
  in 10.1.
- Deferred: the bare-metal storefront's flat `tests/` root, an unowned gap row
  in `openspec/changes/README.md` under Goal 1.
- The stop that returned the change to design (the after-end reads did not
  answer `delivery_conflict`, since a conflict is judged only against a live
  delivery) is D9's context, settled by design review 40.

## 11. Closeout

The closeout task of `docs/guidance/workflow/closeout.md`, its parts in order, with
this repository's parts (`openspec/README.md`, "This repository's closeout parts")
after campaign index currency.

- [x] 11.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the
  comments and docstrings the change added or restated — the job engine's start and
  finish, the rerun predicate, `job_contract`, the release status port, the
  allocator and its index comment, acceptance, the dispute policy, the two
  mechanisms' preflights, the settings' comments and the e2e lease back-date
  comments — state the current system and name no change, review or task. A finding
  returns the change to implementation.
  Confirmed: `make check-comment-hygiene` OK. Every comment line the diff from the
  merge base `033e799a6` adds to source and configuration was read, and every
  added Python line searched for history-relative or change-naming wording; each
  describes the current system and names no change, review or task.
- [x] 11.2 Import placement: confirm every import the change's diff adds sits at
  module level. One that should move returns the change to implementation.
  Confirmed: the diff adds no indented `import` or `from … import` line.
- [x] 11.3 Documentation compliance: re-check each decision's destination below
  against `openspec/README.md`, "Documentation placement", and confirm each
  permanent document written describes the current state.
  Done: each destination in the record below matches the placement table — the
  requirements in the capabilities' `spec.md`, their rationale in the
  companions, the settings in the capabilities' `configuration.md`, the
  cross-system release account in `ARCHITECTURE.md`, the migration in
  `DEPLOYMENT_AND_CONFIG.md`, operator steps in the operator handbook, the gaps
  in the roadmap. Every document written describes the current state. The
  client-restart wording the `relay-client` unit-file task contradicted was
  settled by closeout review 67's triage (F1; section 6's notes); the
  companion's text, that the synchronization restarts the client when the
  baseline changes, needed no edit.
- [x] 11.4 Narrative compression: shorten completed-task notes here to final
  behaviour, evidence, deferred work and destinations, moving any rationale not yet
  in `design.md` there first.
  Done: the notes of sections 1–10 are shortened, and the handoffs between
  sessions removed. What they settled beyond the decisions moved first to
  `design.md`, "Settled during implementation": the unsettled latest job read as
  pending, the begin failure reaching the grace (60 F1), the serialized registry
  reads (49 F1), the re-read keeping its factory, the selection refusal meeting
  "No speculative guard code", the level of D1's relay test, and no VM rerun test
  owed. The stopped session's account of section 10 is D9's context.
- [x] 11.5 Roadmap currency (`docs/development/ROADMAP.md`, "Goal 1 — Consolidate
  physical-resource authority in the provisioning service"): remove the five open-gap
  rows this change owns — the relay-pool mismatch, the startup-only dispute
  authority read, the bare-metal end under a delivery conflict, the false
  `RelayWindowExhaustedError`, and the teardown that failed before its executor ran.
  In the current state, add to the relay paragraph that a delivery is leased on its
  declaration's pool's relay and the proxy-adding job points the host's one client
  at it; and state that a teardown recorded as never started is run again within a
  bound while its lease waits, a teardown whose playbook ran still waiting for an
  operator. Name the update in the design-promotion record.
  Done: the five rows removed; the relay paragraph states a delivery's relay and
  the proxy job's client, and a new paragraph states the teardown rerun and the
  grace's backstop, the concurrent retries, and the storefront's re-read.
- [x] 11.6 Campaign index currency (`openspec/changes/README.md`): this change's row
  to `in closeout` with its archive link once 11.11 runs, and its line in Goal 1's
  dependency graph marked archived. `report-provisioning-failures-to-operators`'s
  `Depends on` entry for this change stays for archive cleanup. Run
  `make check-change-index`.
  Done: the row is `in closeout`, its notes rewritten to the change's outcome,
  and its link points at the archive (11.11). Goal 1's graph marks the change
  `(closeout)`, not archived: its status stays `in closeout` until archive
  cleanup writes `archived` (`closeout.md`, "Campaign index currency"), and the
  graph follows the index's convention for a change in closeout. The dependent's
  `Depends on` is unchanged. `make check-change-index` OK.
- [x] 11.7 Packaging: run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=resolve-delivery-correctness-gaps`. The
  change touches no `.agents/`, `.claude/` or `.codex/` path, so
  `make check-agent-skills` is not owed unless a section did.
  Done: `make check-packaging` passed every check; `make check-architecture-change`
  "owns no architecture row"; both again through `scripts/change-workflow run
  pre-archive`, "passed, exit 0" at `6e201be6c`. The diff from the merge base
  touches no `.agents/`, `.claude/` or `.codex/` path; the skills check runs
  among `pre-commit`'s defaults.
- [x] 11.8 End-to-end pipeline: record the pipeline run at the closeout's code
  (`make run-e2e`, `make fetch-e2e-logs`), its result, and the scenarios that
  exercise the change's paths: `e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_vm_payment_purchase`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_bare_metal_deal` and
  `e2e_credits_payment_deal`. A failed run returns the change to implementation;
  a run that could not be made is recorded as unrun with its cause and owner.
  Done, from validation 65 (`reviews/65-validation.md`), which validated
  `6e201be6c`, the commit closeout starts from; closeout changes no code, so it
  describes the closeout commit's code. Pipeline: `e2e.yml` run 44515028193,
  `success`, lanes `e2e-vm`, `e2e-bare-metal` and `e2e-apicredits`. Local
  (`check-packaging`, `make test`) and Helm passed. The scenarios, by lane
  (`e2e-tests/Makefile`): `e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_vm_payment_purchase` and `e2e_vm_payment_deal` in `e2e-vm`;
  `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal` in
  `e2e-bare-metal`; `e2e_credits_payment_deal` in `e2e-apicredits` — each passed
  with its lane, exercising the unchanged paths beside the change (both job
  instants recorded, one acceptance, the startup read, release under the 3600
  s grace, the result read while active). `e2e_bare_metal_deal` is in no lane,
  since it needs a real host, so it is unrun (validation 65's coverage table
  lists it under the bare-metal lane, which the Makefile does not bear out); no
  section owed it. No lane plants a never-started teardown, a conflicting
  delivery, an overlapping acceptance, a relay-backed pool or an unread
  registry; the unit and integration suites are their evidence. No section owed
  an observation to validation.
- [x] 11.9 Promotion: write the permanent documents and complete the
  design-promotion record below.
  Done: each document below written as listed, the operator handbook's section
  confirmed against the merged settings and routes (3600, `teardown_rerun_limit
  = 3`, `retry-release`), and the record completed. Beyond the list:
  "Proof-driven release" also states the grace as the backstop for a teardown
  that keeps failing to begin (60 F1).
  - `openspec/specs/physical-provisioning/architecture.md`, "Relay sharing and
    containment": a delivery's relay is its declaration's pool's; the proxy-adding
    job points the host's one client at it; the three facts the rule rests on, and
    that a change relaxing one answers for it; why the management-route rule, the
    host pool-change hook and the drain keep reading placement (D1).
  - `openspec/specs/physical-provisioning/architecture.md`, "Proof-driven release":
    rewritten for the rerun of a teardown recorded as never started, its identity,
    bound and spacing, the start and finish the engine records and why a job
    finished before them is never rerun, the lease waiting under the grace's
    backstop and its sizing, a compensating teardown rerunning alike, and the rule
    that a fulfillment's teardown is one job restated; its sentence that only
    VM-backed reservations read the aggregate corrected (D3, D4, D5, D7, D8).
  - `openspec/specs/physical-provisioning/configuration.md`, the paragraph on
    `relay_grant_expiry_grace_seconds` (under "Secrets are named, not carried"): its
    sizing rule restated over the teardown still due; beside it,
    `lease_watchdog_grace_period_seconds`'s meaning and 3600-second default sized
    for teardowns of expected length, and `teardown_rerun_limit` (D3, D5).
  - `openspec/specs/settlement-configuration/configuration.md`, "Dispute authority
    preferences": descriptors are read at storefront startup and, for a registry
    whose read failed, again each time the storefront composes listing options —
    each publication cycle in the VM and bare-metal storefronts, each listing
    created or seeded in API credits — until one succeeds; an unread registry is
    reported in each affected mechanism's public details as
    `dispute_authorities_unread`, not as a blocker, on the storefront's system
    status route (`GET /api/v1/system/status`), not by the `settlement status`
    command (D6, 40 F2, 40 F3).
  - `docs/development/ARCHITECTURE.md`, "Release": the sentence that a compensated
    aggregate's requeue re-observes the same failed teardown job restated, and the
    rerun of a teardown recorded as never started added (D3, D5, D8).
  - `docs/operator-handbook.md`, "Upgrading a deployment", is written in section 3
    (3.4); confirm it against the merged code.
  - The `physical-provisioning`, `fulfillment`, `compute-provisioning-contract`,
    `settlement-configuration` and `storefront-publication` `spec.md` changes are
    written by the archive in 11.11; the record names them.
  - `openspec/specs/README.md` needs no change: no capability or companion is
    added.
- [x] 11.10 Guidance placement: the change adds no guidance under
  `docs/guidance/` or beside a specification; record that, or, if a section added
  some, read it against the layer test and run `make check-guidance`.
  Done: no section touched `docs/guidance/`. Promotion wrote into two guidance
  files beside specifications, `physical-provisioning/configuration.md` (the
  grant grace, the watchdog grace and `teardown_rerun_limit`) and
  `settlement-configuration/configuration.md` (the storefront's re-read and its
  report). Each is this repository's and pertains to its one capability, so
  each sits beside that capability's specification; neither declares an
  exception. `make check-guidance` OK.
- [x] 11.11 Documentation citations and archival: run
  `make check-doc-citations CHANGE=resolve-delivery-correctness-gaps` and resolve
  every match, then `scripts/change-workflow openspec validate
  resolve-delivery-correctness-gaps --strict`; then archive with
  `scripts/change-workflow openspec archive resolve-delivery-correctness-gaps -y`,
  merging the five delta specs into `openspec/specs/`, and read each merged spec's
  diff for every added and modified requirement appearing once as its delta states.
  Done: `scripts/change-workflow run pre-commit` over the promoted state passed —
  its `make check-repository` (documentation citations, decision destinations,
  history wording among its checks) and `openspec validate --strict` ("valid").
  No permanent `spec.md` carried the deltas, so the archive merged them (no
  `--skip-specs`): + 8, ~ 6, - 0, into
  `openspec/changes/archive/2026-11-19-resolve-delivery-correctness-gaps/`. Read
  each merged diff: every added requirement appears once, appended as its delta
  states (`physical-provisioning` 4, the other four 1 each), and the six modified
  requirements (`physical-provisioning` 5, `storefront-publication` 1) change only
  the lines their deltas change; nothing else moved. The index row links the
  archive.

## Design promotion record

Filled during implementation and completed at closeout (11.9), one row per decision
in `design.md` and per destination named in 11.5, 11.6 and 11.9.

| Accepted decision | Permanent location |
|---|---|
| D1 — Item 1 is corrected and guarded, not fixed by a new rule | `openspec/specs/physical-provisioning/spec.md` ("A relayed delivery's relay is its declaration's pool's", by the archive); `openspec/specs/physical-provisioning/architecture.md#relay-sharing-and-containment`; `docs/development/ROADMAP.md` (Goal 1) |
| D2 — Concurrent retries return the first acceptance and the owner's lease | `openspec/specs/physical-provisioning/spec.md` ("A concurrent allocation for one owner receives that owner's lease"); `openspec/specs/fulfillment/spec.md` ("An equivalent acceptance that waited on another returns the first") |
| D3 — A lease waits while its fulfillment still has something to try | `openspec/specs/physical-provisioning/spec.md` ("An undelivered lease is released by what its fulfillment proves"; the release-failure scenarios of "Allocation-backed lease release" and "Site-backed release lifecycle", by the archive); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `openspec/specs/physical-provisioning/configuration.md#secrets-are-named-not-carried`; `docs/development/ARCHITECTURE.md#release`; `docs/operator-handbook.md#upgrading-a-deployment` |
| D4 — A job records that its execution is starting before it starts | `openspec/specs/physical-provisioning/spec.md` ("A job records that its execution is starting before it starts"); `openspec/specs/compute-provisioning-contract/spec.md` ("A job view shows when its execution started and when it finished"); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release` |
| D5 — A rerun is a new job under a key derived from the jobs already bound | `openspec/specs/physical-provisioning/spec.md` ("A teardown that never started is run again under a new job identity, within a bound"; "Lease release delegates to durable fulfillment teardown"); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `openspec/specs/physical-provisioning/configuration.md#secrets-are-named-not-carried`; `docs/development/ARCHITECTURE.md#release` |
| D6 — A storefront reads again a registry it could not read | `openspec/specs/settlement-configuration/spec.md` ("A storefront reads again a registry whose recommendations it could not read"); `openspec/specs/settlement-configuration/configuration.md#dispute-authority-preferences` |
| D7 — A compensating teardown reruns by the same rule | `openspec/specs/physical-provisioning/spec.md` (the rerun requirement's compensating-teardown scenario); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release` |
| D8 — The rule that a fulfillment's teardown is one job is restated in `physical-provisioning` | `openspec/specs/physical-provisioning/spec.md` (the two rerun-related requirements added; "Lease release and fulfillment teardown have separate retry ownership" and "Lease release delegates to durable fulfillment teardown" modified, by the archive); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `docs/development/ARCHITECTURE.md#release` |
| D9 — Item 3 is two requirements' scenarios, a test, a fix to the result read, and a deletion | `openspec/specs/storefront-publication/spec.md` ("A bare-metal delivery that conflicts with its recorded result is refused"; "A bare-metal result read answers the recorded result while its lease ends", by the archive) |
| D10 — One round of three sessions | No permanent destination: the implementation cadence is this change's plan |
| Roadmap currency (11.5) | `docs/development/ROADMAP.md`, Goal 1 |
| Campaign index currency (11.6) | `openspec/changes/README.md`, this change's row and Goal 1's graph |
| Settled during implementation (11.4) | Its points are the code's and the specifications' as merged; the reasons are this change's `design.md`, "Settled during implementation", kept in the archive |
