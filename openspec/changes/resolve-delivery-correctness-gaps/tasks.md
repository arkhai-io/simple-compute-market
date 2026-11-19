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
  exported as the package's `MIGRATIONS` tuple, as `market_site.migrations` does,
  and composed as `*JOBS_MIGRATIONS` after `SSH_CONNECTIONS_VERSION_2`. Two
  existing service tests assumed the chain's last migration was rerunnable over
  its own effect, which an `ALTER TABLE ADD COLUMN` is not: the "behind the
  chain" test in `test_database.py` now builds its behind database with a chain
  lacking the last migration (an older image's database, schema and ledger
  both), and `test_ssh_connection_version_migration.py`'s "job rows unchanged"
  assertion admits the two new columns reading null.
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
  Done: `report_starting` is a required `JobRun` field (no default: every
  executor is handed it by the engine). It goes through `_transition` (expected
  `running`, status `running`) with `execution_started_at =
  coalesce(execution_started_at, <instant>)` inside the one conditional `UPDATE`,
  so the first instant is kept by the statement itself; a refused transition
  raises the new `JobNotRunningError` (exported from `jobs.engine`), a failed
  write raises the database's error. The instant is `_utcnow()` (the source's
  instant, naive UTC, as `next_retry_at` is stored). Every test that builds a
  `JobRun` by hand gains `report_starting=lambda: None`: `compute/ansible`'s
  `test_mock.py`, and five in the VM and bare-metal adapters' tests (no package
  bump: tests are not packaged).
- [x] 1.3 In `jobs/engine.py`'s `_transition`, stamp `finished_at` from the
  process's time source on every transition to a terminal status (`succeeded`,
  `failed`, `cancelled`), including `_fail` and the conditional `cancel_job` update,
  and never move it once set. `_status` fills the job view's two fields. Verify with
  1.5. (D5; `finished_at` from the process's time source, not `updated_at`.)
  Done: `_transition` adds `finished_at = <instant>` to any terminal transition,
  and `cancel_job`'s own `UPDATE` does the same. It is never moved because every
  terminal transition expects `queued` or `running`, so a job finishes once; no
  `coalesce` guards it (only the start's write needs one, `_first_start`, since a
  retry starts again).
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
  Done. Unit (`test_executor.py`, 190 passed with the package's suite, 4 skipped
  as before): the start is recorded once, immediately before `start_playbook`
  (event order `["starting", "start_playbook"]`); a raising `report_starting`
  spawns nothing and leaves no file; and a codec whose `prepare` refuses (as a
  relay refusal does), the variables file's refusal (an extra variable naming a
  job variable), and the inventory's (a host not over ssh, an undecryptable key)
  record no start. Unit (`provisioning/compute/contracts/tests/unit/test_jobs.py`,
  163 passed with the package's suite): a view without either instant reads null
  in both, and reported instants are read as reported.
- [x] 1.5 Library integration
  (`provisioning/compute/tests/integration/test_job_authority.py`): a job refused
  before its executor runs (no host, an unregistered host, an unsupported action)
  records no start and a `finished_at`; a job whose executor reports its start and
  then fails records both; a start that cannot be recorded spawns nothing (a test
  executor asserting it was never asked to start); a job cancelled between its claim
  and its start stays `cancelled` with no start; a retried job keeps its first
  start; a spawned job whose handle write fails keeps its start; a terminal job's
  `finished_at` does not move. Drive the instants with the injected time source.
  Done: library integration, 25 passed (`test_job_authority.py`; the compute
  package's whole suite, 570 passed). The suite's job tables are built by the
  package's own `BASELINE` and `MIGRATIONS` rather than `create_all`. The fake
  executor reports its start before its handle, as a real one does. A start that
  cannot be recorded is a real database refusal — a SQLite trigger aborting any
  write of `execution_started_at` — not a patched call; the handle write that
  fails is a handle the JSON column cannot serialize, so the write raises before
  anything is stored. The cancellation case gates the executor before its start
  (`_GatedStart`), cancels, then releases it, and asserts it never spawned. The
  "finish does not move" case holds the behaviour (a refused cancel and a second
  `process_job` leave it), which the status guard gives, not a guard of its own.
- [x] 1.6 Library integration of the migration
  (`provisioning/compute/service/tests/integration/test_migration_chain.py`, as
  `docs/guidance/repository/migration-chain-tests.md` gives the chain's cases): a
  database adopted at the v0.3.0 floor gains both columns, its existing jobs reading
  null in both, and a fresh database builds them.
  Done: `test_a_v0_3_0_job_gains_execution_instants_that_read_null`, a failed
  handleless job and a failed job with a handle seeded into the floor's DDL;
  the chain's existing cases (fresh equals adopted, every mapped column created)
  cover the new columns too.
- [x] 1.7 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_vms_api.py` or a sibling):
  a job read through the provisioning client carries `execution_started_at` and
  `finished_at` for a job that ran, and null `execution_started_at` with a
  `finished_at` for one refused before its playbook, as the contract's scenarios
  state.
  Done: `test_vms_api.py`'s `test_a_job_that_ran_is_read_with_its_start_and_its_finish`
  (both instants, start not after finish), and the refused case asserted on the
  existing undecryptable-key job in `test_unreadable_host_key_api.py` (no start,
  a finish, no playbook started). These assert presence and order, not exact
  instants: the service suite installs no time source of its own there; the exact
  instants are 1.5's.
- [x] 1.8 Bump `arkhai-compute-provisioning` (minor, the `JobRun` protocol and the
  job columns), `arkhai-compute-provisioning-ansible` (patch),
  `arkhai-compute-provisioning-contracts` (minor, the job view's fields) and
  `arkhai-compute-provisioning-service` (minor, the migration); raise the lower
  bounds of the packages that need the new fields (the ansible package and the
  service on `arkhai-compute-provisioning`, the service on the contracts); refresh
  the locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-compute-provisioning` 0.28.0 → 0.29.0, `-ansible` 0.8.1 → 0.8.2,
  `-contracts` 0.15.0 → 0.16.0, `-service` 0.26.0 → 0.27.0. Beyond the plan's
  bounds: `arkhai-compute-provisioning` itself now requires the contracts at
  `>=0.16.0` (its `_status` builds the view with the new fields, which an older
  contracts model would silently drop), and the service requires the ansible
  package at `>=0.8.2` (an older executor never reports a start, so a job whose
  handle write failed after its spawn would read as never started). Relocked the
  twelve projects whose locks name any of the four (`make lock PROJECTS=…`:
  `provisioning/compute` and its `ansible`, `contracts`, `client`, `service`; the
  VM adapter, client and storefront; the bare-metal adapter and storefront;
  `domains/compute/delivery`; `e2e-tests`). Both checks pass.
- [x] 1.9 Verification: `uv run pytest provisioning/compute/tests
  provisioning/compute/ansible/tests provisioning/compute/contracts/tests
  provisioning/compute/service/tests` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: every lane deal
  that creates and tears down records both instants on the unchanged path —
  `e2e_deal`, `e2e_vm_payment_purchase` and `e2e_bare_metal_mock_deal`; no scenario
  reads the new fields, and none is owed: the application-integration case is their
  evidence.
  Done: each package's suite run in its own project — compute 570 passed,
  ansible 190 passed (4 skipped), contracts 163 passed, the service (`make -C
  provisioning/compute/service test`) 634 unit and 558 integration passed; the VM
  and bare-metal adapters' suites, whose hand-built `JobRun`s changed, 287 and
  138 passed. `pre-commit` passes (see the section's notes). End-to-end confirmed:
  the three markers exist in `e2e-tests/pyproject.toml` and their lanes in
  `e2e-tests/Makefile`; every lane executor is the `AnsibleJobExecutor` over the
  mock runner, so each deal records both instants; no scenario reads them, and
  none is owed.

Section 1 notes (handoff):

- Outside the plan: `docs/development/DEPLOYMENT_AND_CONFIG.md`'s list of the
  migrations after the v0.3.0 baseline gains the new migration, since that list
  describes the chain and would otherwise be stale.
- `JobNotRunningError` and the start's `coalesce` live in `jobs/engine.py`. A
  never-started classification is not implemented here: it is section 2's
  teardown-job read, from `status`, `execution_started_at`, `execution_handle`
  and `finished_at` as D4 states it.
- An executor double in another package's tests that never calls
  `report_starting` still runs, and its jobs then record no start; a test of the
  rerun predicate must use a double that reports its start where it means a
  started execution (section 2's executor refusing before the start is the
  opposite case).
- The service suite's `fake_ansible` goes through the real `AnsibleJobExecutor`,
  so application-integration jobs record their start; the instants are naive
  UTC as SQLite returns them.
- `scripts/change-workflow run test-before … --at 81e3efa2a` was run on
  `test_job_authority.py` and the Ansible `test_executor.py` and showed nothing:
  it runs `uv run --no-project --with pytest`, so collection fails importing
  `injected_time` and `compute_provisioning_contracts` before any test runs. No
  fail-before evidence exists for this section's tests; the new ones read fields
  and a callback the base commit lacks, so they would fail there at attribute
  access or construction, not at their assertions.

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
  `BoundJob(job_id, status, never_started, finished_at)` records, oldest first
  (the order is the tuple's). Generic in the action kind, so the engine names no
  contract action; callers pass `"teardown"`. Ties on `created_at` (the source
  ticks in seconds) are broken by the idempotency key, shorter first, so
  `…:teardown:rerun-10` sorts after `…:rerun-9` (2.6's case inserts `rerun-10`,
  `rerun-9`, `rerun-2` and the first under one held instant, which alphabetical
  order would misread). `finished_at` is returned aware UTC (SQLite stores it
  naive).
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
  `RerunReady(rerun)` or `RerunsSpent(reruns_spent)`, plus `rerun_pending` and
  `never_started_account` (the operator's sentence for a spent bound or disabled
  reruns). Two outcomes the plan's list left implicit: `NotRerunnable`'s
  `no_teardown_job`, and `LatestJobUnsettled(status)` for a latest job queued,
  running or succeeded, which `rerun_pending` counts as pending — the teardown
  is still to be observed, so a lease waiting on it keeps waiting, as D3 has the
  port report failed only when nothing is pending. Dispatch adopts that job.
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
  Done. Deviation: the provider's `rerun_policy` keyword defaults to `None`
  (no reruns: every dispatch submits, or finds, the one `…:teardown` job, as
  before), and so do the status port's `rerun_policy` and `jobs`. Required
  arguments would break the VM and bare-metal runtimes and the service
  container, which compose them only in section 3, and this commit must pass
  every suite. Section 3 composes both and makes the arguments required (see
  the section notes). `job_contract` gains `rerun=`.
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
  Done: unit, `tests/unit/test_teardown_rerun.py`, 13 passed — each outcome
  (no job, a latest job not failed, started, cancelled, finished before starts
  were recorded, disabled, waiting, ready with its *n*, spent), the latest job
  deciding, the spent bound's message, and the refused negative limit. "With and
  without a handle" is the job authority's classification, not the predicate's
  input, so it is shown at the read, in 2.6's last case.
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
  passed. One file-backed database holds the pools, jobs and fulfillment
  tables, built by their packages' baselines and the jobs migration; a real
  `JobEngine`, `JobFulfillmentProvider`, `FulfillmentOrchestrator` (for the
  ordinary and compensating teardown's begin) and status port. Convergence is
  the service's, which this package cannot import, so each test makes the
  watchdog's moves itself through `SettlementRepository.transition` — dispatch,
  poll (keeping a compensation's reason, as `_apply_teardown_failure` does), and
  requeue; the full loop through the service is section 3's. "A rerun that
  succeeds" is shown as far as the provider's status reading `succeeded` and the
  port reading `TORN_DOWN` once the row is `torn_down`. The compensating case
  shows the rerun submitted for a compensating teardown and dispatch leaving
  `create_compensation` as it was; that the reason survives a failed attempt is
  the test helper's copy of the watchdog's rule, so the real watchdog's keeping
  of it across a rerun is section 3's to show. The last two cases show the
  read's order of rows created in one instant, and its classification of a job
  with no `finished_at` (handle or none) and of one recording its finish.
- [x] 2.7 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane induces a teardown that fails before its playbook
  starts, so no scenario exercises a rerun; the lanes' deals exercise the unchanged
  first-teardown path. None is owed: section 3's application-integration cases are
  the deployed-composition evidence.
  Done: `provisioning/compute` 593 passed; `pre-commit` passes (section notes).
  End-to-end confirmed as planned: until section 3 composes the policy, the
  lanes run with reruns off, the first-teardown path exactly.

Section 2 notes (handoff):

- Section 3 must compose one `TeardownRerunPolicy` into the provider (both
  runtimes, and the service suite's `conftest.py` constructions) and into the
  status port (with `jobs=` the job engine), then remove the `None` defaults
  from `JobFulfillmentProvider.__init__`'s `rerun_policy` and
  `FulfillmentReleaseStatusPort.__init__`'s `rerun_policy`/`jobs`, with the
  provider's `if self._rerun_policy is None` branch and the port's matching one.
  Every test constructing either then passes a policy: the compute package's
  `tests/unit/test_job_fulfillment.py` (its fake `_Jobs` then needs
  `bound_jobs`), `tests/integration/test_release.py`'s `_status_port`, the
  bare-metal adapter's `test_bare_metal_fulfillment_plan.py`, and the service's
  `conftest.py`, `test_lease_release_api.py` and `test_ledger_lease_lifecycle.py`.
- The status port reads `teardown_rerun` only for a `teardown_failed` aggregate.
  It reads the aggregate and the jobs in separate transactions, so a requeue and
  rerun dispatch landing between the two can show a latest job still queued or
  running; that reads as tearing down (`LatestJobUnsettled`), not failed.
- Section 3 also owns showing, through the real watchdog, that a compensating
  teardown's rerun keeps `create_compensation` across a failed attempt.
- The provider's dispatch adopts the latest teardown job by reading it, rather
  than resubmitting `…:teardown` to find it; the job authority's contract
  identity still collapses concurrent dispatches of one rerun.

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
  Done: the container's `teardown_rerun_policy` singleton
  (`_make_teardown_rerun_policy`). Beyond the plan: the two code-level fallbacks
  for the grace (`lease_lifecycle.py`'s `getattr(…, 300)` and `app_runtime.py`'s
  startup log) now fall back to 3600, matching the default, and the comment on
  `DEFAULT_GRANT_EXPIRY_GRACE` in `relays/allocator.py` is restated over the
  teardown still due, as the setting's is.
- [x] 3.2 Compose the policy and the engine's teardown-job read into
  `FulfillmentReleaseStatusPort` in `compute_provisioning_service/container.py`, and
  into `JobFulfillmentProvider` in
  `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/runtime.py` and
  `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/runtime.py`
  (and their `bundle.py` where it builds the provider), from the one policy the
  service builds. Verify with 3.5. (D5.)
  Done: `build_vm_runtime` and `build_bare_metal_runtime` take
  `teardown_rerun_policy` (the VM runtime keeps it as a field); neither
  `bundle.py` builds a provider. Section 2's `None` defaults and branches are
  removed: `JobFulfillmentProvider`'s `rerun_policy` and the status port's
  `rerun_policy` and `jobs` are required, and every construction passes them
  (the tests section 2's notes list, plus `test_vm_fulfillment_plan.py` and
  `test_test_controller.py`, which pass `None` to a runtime that dispatches no
  teardown). Unit (`tests/unit/test_authority_composition.py`, the container
  over an in-memory database): one policy reaches both providers and the release
  status, whose job read is the container's one engine.
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
  Done: three bullets added before the version-1 leftovers — the grace's default
  and when to raise both graces; teardowns that never started being run again,
  with what to do for a lease whose reruns are spent (its workload is still on
  the host: the version-1 steps apply); and the retry-release of a lease timed
  out while its teardown went on or with a rerun pending — and the leftovers'
  bullet now says why they are not run again; its manual steps are unchanged.
  Read against D3 and D4.
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

  Done, with deviations. Application integration through the typed clients, in
  `test_lease_release_api.py` — the module already driving a lease's release
  through the real app, convergence stepped by `advance-cycle` and the watchdog
  by `check-leases` — not the two modules the plan names, which drive the
  lifecycle and the watchdog directly with doubles rather than through the
  client. Seven cases, all on bare-metal leases set up through scheduling and
  `begin`, the time source injected and moved forward:
  - a reclaim refused before its playbook (the host's stored connection set to
    version 1, which the executor's inventory refuses — the refusal the version-1
    leftovers met; an undecryptable key needs a real runner the bare-metal mock
    does not take) records no start and a finish; the lease stays `releasing`
    while the rerun waits; once the host is repaired rerun 1 runs under
    `…:teardown:rerun-1`, the aggregate reaches `torn_down`, and the lease is
    released, no operator call;
  - `teardown_rerun_limit = 0` (the fixture overridden by parametrization): the
    lease reaches `release_failed` / `teardown_failed`, and no rerun is submitted
    a day later;
  - the refused reclaim with its `finished_at` cleared, as an earlier release
    left its jobs: `release_failed`, no rerun;
  - past the harness's 300-second grace with a rerun pending: `release_failed` /
    `teardown_timeout`; a retry-release returns it to `releasing` under the same
    fulfillment, the next check does not time it out again, and the rerun
    releases it;
  - a reclaim held running past the grace: `teardown_timeout`; once it succeeds
    and the aggregate is `torn_down`, one retry-release releases the lease, with
    one teardown job (the hold released in a `finally`, its `waiting` count
    asserted zero);
  - a reclaim failing retryably after its start (`fail_with`, its
    `execution_started_at` recorded) is retried by the job engine and succeeds;
    the lease is `releasing` while the retry waits and is then released;
  - a failed create's compensating reclaim refused before its playbook: the real
    watchdog records the failure keeping `create_compensation`, the lease waits,
    and the rerun tears the aggregate down still carrying it.
  The negative limit is shown at the composition root (unit,
  `test_authority_composition.py`): the container refuses to build the policy,
  and so the release status, naming the setting; startup builds both, but no test
  starts the app with the negative setting, since that refusal has no client
  surface and comes after the database check. Not shown at this level: the VM
  lease's rerun — the VM runtime's provider holds the same policy (the
  composition test) and the provider and predicate are domain-neutral, but no
  VM lease is driven through a rerun; a teardown whose playbook ran and failed is
  the existing `test_a_failing_compensation_leaves_the_lease_for_an_operator`
  and `test_a_delivered_teardown_that_fails_once_is_not_read_as_compensated`,
  which pass with no change to their assertions (the second's docstring is
  restated). The VM rerun at this level is left for the round's triage to judge:
  it needs a VM fulfillment driven through `begin` in this module, which the
  bare-metal helpers do not give.
- [x] 3.6 Bump `arkhai-vm-provisioning-adapter` and
  `arkhai-bare-metal-provisioning-adapter` (or the names their `pyproject.toml`
  states; minor, the provider's new argument) and raise their lower bound on
  `arkhai-compute-provisioning`; the service's bump is section 1's. Refresh the
  locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-vms-provisioning-adapter` 0.19.1 → 0.20.0 and
  `arkhai-bare-metal-provisioning-adapter` 0.13.1 → 0.14.0, both on
  `arkhai-compute-provisioning>=0.29.0`; the service's `adapters` extra and dev
  group raised to them. Relocked the two adapters and the service. Both checks
  pass.
- [x] 3.7 Verification: `uv run pytest provisioning/compute/service/tests
  domains/vms/provisioning/adapter/tests domains/bare_metal/provisioning/adapter/tests`
  passes, `make -C helm test-render` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: the lanes'
  back-dated-lease stages run under the new grace — `e2e_vm_payment_purchase`,
  `e2e_deal_buyer_cli` and `e2e_bare_metal_payment_deal` release their leases
  through the unchanged path; none induces a rerun or a timeout, and none is owed.
  Done: the service (`make -C provisioning/compute/service test`, which sets the
  `mock` profile its test routes need) 636 unit and 565 integration passed; the
  VM adapter 287 and the bare-metal adapter 138 passed; the compute package 593;
  `make -C helm test-render` passed; `pre-commit` passes (section notes).
  End-to-end, reasoned and not run (the lanes run at validation): the lanes take
  the charts' 3600-second grace and run with reruns on, but no lane refuses a
  teardown before its start.

Section 3 notes (handoff):

- The service suite's `client_and_queue` takes a `teardown_rerun_limit` fixture
  (3), which a test overrides by parametrizing it; its harness grace stays 300.
- Outside the plan: the service suite's signed ASGI transport stamped requests
  with `time.time()` while the service checks them against the injected source,
  so a test moving the source past the timestamp window had its signed calls
  refused. It now signs with `injected_time.now()`.
- The service's `/test` routes exist only under the `mock` profile: run the
  service suite through `make -C provisioning/compute/service test`, not a bare
  `uv run pytest`.

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
  Done: the select takes `.execution_options(populate_existing=True)`, its
  docstring stating why; `accept` reads nothing before the lock. `git grep -n
  newly_accepted` names only the change's documents and an archived change's
  tasks; the one other construction of the decision, the unit suite's
  `FakeTransaction` in `kit/fulfillment/tests/unit/test_fulfillment.py`, drops
  the field.
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
  passes (the module's 2). Both acceptances go through a real
  `FulfillmentOrchestrator.begin_fulfillment` over `SqlAlchemyFulfillmentUnitOfWork`;
  the second's unit of work is handed the session that read the row first, so
  its locked select meets the identity-mapped object. It asserts the retry's
  `fulfillment_id` is the first's, the provider's `prepare_create` called once and
  `dispatch_create` awaited once across both, and the row's identity, prepared
  operation and `dispatching` state as the first left them. Both tests of the
  module now build their database from the pools and fulfillment kits'
  baselines, not `create_all`, and share the pool handler the first test held
  inline (`docs/guidance/repository/migration-chain-tests.md`). The docstring states
  the stale read (`fulfillment_id is None`, `assigned`) the fix prevents.
  Fail-before not shown: `scripts/change-workflow run test-before` runs only a
  test file as `HEAD` holds it, and section 1's notes record that its
  `--no-project` environment fails collecting a kit suite importing
  `injected_time`, as this package's `conftest.py` does.
- [x] 4.3 Bump `arkhai-kit-fulfillment` (minor, the exported
  `FulfillmentAcceptanceDecision` loses a field) and refresh the locks it requires.
  Verify with `make check-version-bumps` and `make check-locks`.
  Done: 0.8.0 → 0.9.0. No dependent's lower bound moves, since none reads the
  removed field. Relocked the eight projects whose locks name it (`make lock
  PROJECTS=…`: `kit/fulfillment`, `provisioning/compute` and its `ansible` and
  `service`, the VM and bare-metal adapters, `domains/vms/storefront`,
  `e2e-tests`); each lock moves only that version. Both checks pass.
- [x] 4.4 Verification: `uv run pytest kit/fulfillment/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: every lane deal accepts its fulfillment once, on the unchanged
  path (`e2e_deal`, `e2e_bare_metal_mock_deal`); no lane overlaps two acceptances,
  and none is owed (design, Open Questions: the PostgreSQL proof).
  Done: `make -C kit/fulfillment test` 213 passed; `pre-commit` passed, every
  suite with it (`pre-commit-functional` and `pre-commit` at `f3e4949ab`), before
  the second test's move to the baselines, after which the package's suite was
  run again and passed, and `make check-change-index`, `make check-tasks` and
  `make check-repository` passed over the notes and the change index's new gap.
  End-to-end, reasoned and not run (the lanes run at
  validation): both markers exist in `e2e-tests/pyproject.toml` and their lanes in
  `e2e-tests/Makefile`; each accepts its fulfillment once, neither overlaps two
  acceptances, and none is owed.

Section 4 notes (handoff):

- Outside item 2's stated scope, as D2 records: the stale read is a defect found
  during the change (`docs/guidance/workflow/changes.md`, "Defects found during a
  change"), reachable wherever two acceptances of one reservation overlap, as on
  PostgreSQL; the shipped single-process SQLite deployment cannot overlap them.
- The stale read needs pysqlite's default transaction handling: the earlier
  `SELECT` opens no SQLite transaction, so the later `BEGIN IMMEDIATE` succeeds
  and reads committed rows, and only the identity map is stale. A test that
  opens a real read transaction first would test something else.
- Left as it is, and recorded as an unowned gap in `openspec/changes/README.md`
  (under Goal 1, after `project-capacity-resources-without-hosts`'s item): seven
  other `kit/fulfillment` test modules, and some 25 across the kits and compute
  provisioning, still build their tables with `create_all`; only the module this
  section touched moved to the baselines.
- The fresh-context check's findings were taken: the first test's `create_all`,
  and two evidence claims (end-to-end "confirmed", and a pre-commit result not
  recorded), now worded as above.

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
  Done: the owner read is one method, `_owner_lease`, called after the relay's
  locked read and again in the claim loop's `IntegrityError` branch, and by
  `find_active_lease`, whose copy of the query it replaces. It is a method of
  the allocator so that 5.2's test-only subclass can stand for a read taken
  before another claim committed, the simulation D2 names. The docstring
  states that the relay's lock serializes allocations on one relay and the
  constraints decide the rest, why the two constraints are told apart by the
  read, and that a relay that does not exist is refused with the same
  `RelayWindowExhaustedError`; the `uq_relay_port_leases_active_owner` comment
  states what the allocator does on its failure.
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
  Done: library integration, 37 passed (the module). Two new, in
  `TestAConcurrentAllocationForOneOwner`: the owner read, matched by its
  `owner_id =` predicate as rendered for PostgreSQL, comes after `relays … FOR
  UPDATE`; with the owner's lease committed on relay B and a first owner read
  made to miss, an allocation on relay A's two-port window returns that lease,
  claims nothing on A, and raises no exhaustion (its claim fails the
  one-active-lease index, so without the second read it would run the window to
  `RelayWindowExhaustedError`). The existing
  `test_a_stale_port_read_retries_without_rolling_back_the_caller` now runs on a
  two-port window: its stale scan naming another owner's port moves to the
  next free one, and only the window full then refuses. The drain scenario,
  `test_an_owner_holding_a_lease_receives_it_again`, passes unchanged. Not
  shown: a real interleaving on PostgreSQL (design, Open Questions); the
  subclass simulates the missed read in one session, since every caller holds
  SQLite's writer slot and so serializes the claims. The module's schema,
  the active-owner index the second test relies on included, is built from the
  ORM metadata by `tests/integration/conftest.py`, not the relays' migration
  chain (which creates the same index): the unowned gap section 4 recorded.
- [x] 5.3 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane runs a relay-backed pool, so no scenario exercises
  allocation; none is owed.
  Done: `make -C provisioning/compute test` 596 passed before the fresh-context
  fixes (a third new test then folded into an existing one; the module 37
  after); `pre-commit` passed over the fixed tree, every suite with it
  (`after-functional-change`, `pre-commit-functional` and `pre-commit` at
  `7bd6ff327`). End-to-end confirmed as planned: no lane runs a relay-backed pool
  (`e2e_vm_real_provisioning` and `e2e_bare_metal_real_provisioning` exercise
  relayed delivery and run in no lane); none is owed.

Section 5 notes (handoff):

- No package bump: `arkhai-compute-provisioning` is at 0.29.0 from section 1,
  and the change bumps it once (D10); no lock moves.
- The reordering changes no outcome for an owner already holding a lease: it
  is returned before the relay's absence or disablement is judged, as the
  earlier unlocked read returned it.
- For triage or closeout: the delta's "A concurrent allocation for one owner
  receives that owner's lease" says `RelayWindowExhaustedError` MUST be raised
  only when every port in the window is held or quarantined, while the
  allocator also raises it for a relay that does not exist
  (`test_allocating_against_an_absent_relay_fails`). The section changes no
  specification; the wording is the round's to settle.
- The fresh-context check's findings were taken: the docstring's race
  sentence and the missing-relay case, a test docstring's "Today's", a third
  new test that repeated the stale-scan test (folded into it), the conftest's
  metadata schema (recorded above), and three evidence claims.

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
  Done, in two files. Static, `test_relay_assets.py`'s
  `test_a_proxy_is_added_only_after_the_client_baseline_names_the_jobs_relay`:
  `add.yml` includes `relay-client` before its `blockinfile` and its reload; the
  synchronize task's stdin maps `serverAddr`, `serverPort` and `auth.token` from
  the three job variables, it is `changed` only on the command printing
  `changed`, notifies `restart frpc-buyers` (a `restarted` systemd handler), and
  a `meta: flush_handlers` task follows it. Library integration of the shipped
  editor, `test_client_baseline.py`'s
  `test_a_client_naming_another_relay_is_pointed_at_the_jobs_and_keeps_its_proxies`:
  `client_config.py prepare` run as a subprocess with the job's values on stdin,
  as the role runs it, over a baseline naming another relay with a proxy block,
  prints `changed`, rewrites address, port and token, keeps the block, and
  prints `unchanged` on a rerun; the in-process rewrite of address and token
  over a proxy block was already the module's first test's. Neither runs
  Ansible, and no test runs `relay-client` or its handler on a host: the
  native gate runs only `add.yml`'s wait task (`test_frp_proxy_wait.py`), and
  the real-provisioning modules, in no lane, never meet a client naming
  another relay.
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
  declared in a pool on R1. Relays, pools, host, declaration, reservation (its
  lease end set by commit), scheduling and acceptance all go through the
  canonical clients, over the real acceptance path (the fulfillment kit reading
  the settlement record's pool, the VM plan, the real allocator). Read back
  through the clients: R1's holdings show the reservation's active lease, R2's
  none, and the dispatched job's parameters carry R1, the leased port and the
  host. Moved
  because the fresh-context check showed a plan-level test in the VM adapter
  could not fail: the VM plan and the allocator read no host row, and the test
  handed the plan the declaration's pool configuration itself, so the choice
  under test was the test's. Here, acceptance choosing the host's pool would
  lease on R2 or on no relay, and fail.
- [x] 6.3 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_capacity_api.py`): a
  declaration in a pool on R1 whose reservation holds a relay port lease on R1 is
  refused a move to a pool on R2, and stays in its pool ("A declaration holding a
  lease is moved to a pool on another relay").
  Done by the existing test, with no new one: the refusal is the site's refusal
  to move a declaration a reservation holds capacity against, which reads no
  relay and no lease, and `test_capacity_api.py`'s
  `test_a_held_resource_moves_pools_only_once_released` already holds it
  through the typed clients (409, the declaration staying in its pool, and the
  move going through once released). A relay port lease is only ever held by a
  reservation's fulfillment, so a declaration holding one is a declaration
  under that rule. Two drafts were withdrawn after the fresh-context checks: a
  new test seeding the lease as a row, unjustified where the typed client
  reaches acceptance, and the move asserted inside 6.2's test, which repeated
  the existing test's assertions once per parametrization. The round's triage
  may judge whether the scenario wants a relay-specific test of its own.
- [x] 6.4 Verification: `uv run pytest provisioning/compute/iac/tests
  domains/vms/provisioning/adapter/tests provisioning/compute/service/tests/integration/test_capacity_api.py`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: no lane runs a
  relay-backed pool; none is owed. The real-provisioning modules
  (`e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning`) exercise relayed
  delivery but run in no lane.
  Done: `make -C provisioning/compute/iac test` 35 passed, 19 skipped (the native
  Ansible tests, which skip without supported Ansible, as before);
  `test_fulfillment_api.py` and `test_capacity_api.py` 70 passed together; the
  VM adapter's suite (`make -C domains/vms/provisioning/adapter test`) 295
  passed, its files unchanged by the section; `pre-commit` passed over the
  final tree, every suite with it (`after-functional-change`,
  `pre-commit-functional` and `pre-commit` at `5eb9527c4`).
  End-to-end confirmed as planned: no lane runs a relay-backed pool, and the
  two real-provisioning markers are in no lane (`e2e-tests/Makefile`); none is
  owed.

Section 6 notes (handoff):

- Tests only; no package bump (`provisioning/compute/iac` is a virtual project,
  and tests are not packaged).
- Deviation from the plan's files: 6.2 is an application-integration test in
  `test_fulfillment_api.py`, 6.3 the existing capacity test, and neither
  `domains/vms/provisioning/adapter/tests/integration/test_relay_pool_configuration.py`
  nor `test_capacity_api.py` changes (see 6.2 and 6.3). The verification
  command's VM adapter and capacity paths still pass.
- `test_fulfillment_api.py`'s container outlives a test, so the new test's
  relays (`site-r1`, `site-r2`, windows 6400 and 6500) are created once and its
  pools, host and declaration carry a per-run suffix, as the module's other
  relay tests do. A pool a relayed declaration is reserved in must declare `vm`
  among its `deliverable_modes`, and a relayed create needs its reservation to
  state a lease end, which the site's commit sets.
- Two fresh-context checks ran; their findings were taken: the level of 6.2,
  its setup and reads moved onto the typed clients, the seeded lease and the
  repeated refusal of 6.3, the CLI test narrowed to what it adds, the flush
  asserted as a flush, the restart wording, fixture comments, and the
  evidence claims.
  The delta's "restarting the client only when that baseline changes" reads
  as if nothing else restarts it; the unit-file task also notifies the
  restart. The section changes no specification; the wording is the round's.

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
  Done: `get_descriptors(registries=None)`, a selection named as `urls` names
  the registries, returned in configured order. Unit, the new
  `core/storefront/tests/unit/test_multi_registry_descriptors.py`, 3 passed:
  no selection reads every registry and keeps a failure apart as `None`; a
  selection reads and returns only the selected registries (the other's
  client counts no read); an empty selection reads nothing.
- [x] 7.2 In `kit/storefront/src/market_storefront_kit/dispute_configuration.py`,
  `RegistryDisputePolicy` keeps, per registry, whether its last read succeeded and
  when it last failed (the injected time source); `refresh` records them; a new
  re-read reads only the registries whose last read failed, through the selection,
  keeping the others' recommendations; and the policy exposes its unread registries
  with their last failure. Verify with 7.3.
  Done: the policy keeps each registry's recommendations, the registries whose
  last read failed, and each one's last failure, stamped by its `clock` (the
  process's source, `injected_time.now_datetime`, by default). `refresh` reads
  every registry as before and records each outcome, a client that cannot be
  opened leaving every registry unread; `reread(client_factory)` builds no
  client while none is unread, reads only the unread ones through the
  selection, and resolves the authorities again only when one of them was
  read, so a registry still down repeats no "No dispute authority" warning.
  `unread_registries()` returns `UnreadRegistry(url, last_failed_at)` records.
  Beyond the plan, so the three storefronts compose one projection rather
  than three: `readiness_resources()`, the mechanism readiness resource
  section 9 passes, `{"dispute_authorities_unread": [{"registry",
  "last_failed_at"}]}` (ISO 8601) or `{}`, keyed by the exported
  `DISPUTE_AUTHORITIES_UNREAD`. With `use_registry_dispute_authorities` false
  nothing is read, so nothing is unread. The startup read passes every
  registry as its selection, so both reads go through one call.
- [x] 7.3 Unit (`kit/storefront/tests`, beside the dispute configuration's tests):
  a startup read in which one of two registries fails, then a re-read, reads only
  the failed one and adopts its recommendations while keeping the other's ("One of
  several registries could not be read"); a re-read after every read succeeded
  reads nothing ("A registry was read"); the unread registries are reported with
  their last failure until a read succeeds.
  Done: unit, the new `kit/storefront/tests/unit/test_dispute_configuration.py`
  (the kit had no test of the policy), 5 passed. The registries are a double
  of the cross-registry client the policy's factory builds, recording each
  selection it is asked to read (the core client's own selection is 7.1's),
  and the policy's clock is passed to its constructor. The three planned
  cases — the unread registry's case also asserting that a re-read failing
  again logs no second "No dispute authority" warning — plus a client that
  cannot be opened leaving both registries unread, and a seller opting out of
  recommendations reading and reporting nothing.
- [x] 7.4 Bump `core/storefront`'s package (minor, the additive parameter) and
  `kit/storefront`'s (minor), raise `kit/storefront`'s lower bound on the core
  package, and refresh the locks. Verify with `make check-version-bumps` and `make
  check-locks`.
  Done: `arkhai-core-storefront` 0.18.0 → 0.19.0, `arkhai-kit-storefront`
  0.11.0 → 0.12.0 on `arkhai-core-storefront>=0.19.0`. Beyond the plan, the
  exact pins the two bumps move: `arkhai-kit-capacity-publication` pins the
  core package (`==0.19.0`), so it takes a patch bump, 0.12.0 → 0.12.1, and
  its pin moves in the provisioning service (already bumped by section 1);
  the three storefronts pin the storefront kit and capacity publication, and
  the VM storefront the bare-metal storefront, so the three storefronts' minor
  bumps, which 9.3 planned, are taken here — `arkhai-vms-storefront` 0.28.0 →
  0.29.0, `arkhai-bare-metal-storefront` 0.28.0 → 0.29.0,
  `arkhai-apicredits-storefront` 0.21.0 → 0.22.0. Relocked the eleven
  projects whose locks name any of them (`make lock PROJECTS=…`:
  `core/storefront`, `kit/storefront`, `kit/capacity-publication`, the three
  storefronts, `domains/bare_metal`, `domains/compute/delivery`,
  `domains/vms/domain`, `e2e-tests`, `provisioning/compute/service`). Both
  checks pass.
- [x] 7.5 Verification: `uv run pytest core/storefront/tests kit/storefront/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.
  Done: `make -C core/storefront test` and `make -C kit/storefront test` pass
  (237 and 146 after the fresh-context fixes); `pre-commit` passed, every suite
  with it (`after-functional-change`, `pre-commit-functional` and `pre-commit`
  at `703750505`), before those fixes and again after them (section notes).
  End-to-end: section 9's, as planned.
- [x] 7.6 In `MultiRegistryClient.get_descriptors`, refuse a selection naming a URL
  `urls` does not name, and a string passed in place of a collection, with
  `ValueError` naming the problem; an empty selection still reads nothing (D6,
  40 F4). This restores, by the owner's decision, the refusal of an unconfigured
  selection the fresh-context check removed (the notes below). Unit, in
  `core/storefront/tests/unit/test_multi_registry_descriptors.py`: an unknown URL
  and a bare string are refused and read no registry. No bump: 7.4's is unreleased.
  Verify with `make -C core/storefront test`.
  Done: both refusals are checked before any registry is read; a URL is
  matched exactly as `urls` names it, and the refusal names the unconfigured
  URLs. Unit, new cases in `test_multi_registry_descriptors.py` (the module 6
  passed; `make -C core/storefront test` 240 passed): a selection naming a
  configured registry beside an unconfigured one — another registry, or a
  configured one with a trailing slash `urls` does not give it — is refused
  naming the unconfigured one, and a configured URL given as a bare string is
  refused, none reading any registry. The one caller, the dispute policy,
  passes the client's own `urls` (read from the code; the kit's tests use a
  double of the client, and `make -C kit/storefront test` 146 passed).
  Fail-before not shown: `scripts/change-workflow run test-before` fails
  collecting the module in its `--no-project` environment (`No module named
  'market_identity'`), as section 1's notes record for other packages.

Section 7 notes (handoff):

- Section 9's bumps are taken: the three storefronts are at their new minor
  versions (7.4), so 9.3 raises lower bounds and relocks, and bumps nothing.
  The exact pins section 8 will move are `arkhai-kit-arkhai-payments==0.8.0`
  in the bare-metal storefront; check `git grep '"arkhai-kit-alkahest=='` too.
- Section 9 composes `disputes.readiness_resources()` into the mechanism
  readiness resources and calls `disputes.reread(<the registry client
  factory>)` at publication's compose stage; the factory is the one each
  server already hands `refresh` at startup.
- A registry's client that cannot be opened (`MultiRegistryClient.__aenter__`
  raising) leaves every selected registry unread, as one failing read does.
- The fresh-context check's findings were taken: an undeclared test import
  (`registry_client`) and the core client wrapped in the kit's unit test,
  replaced by a double of the cross-registry client; the clock set by
  assignment, now passed to the constructor; a refusal of an unconfigured
  selection no caller could reach, removed with its test; a comment naming a
  public detail section 8 has not yet added, and a docstring stating the
  design's open assumption as fact, both restated; `_read`'s selection flag;
  and three evidence claims (the warning claim, now asserted; the pre-commit
  record; the readiness projection marked beyond the plan).
- 7.6, in the session that completes the round: `pre-commit` at `825bac9e9`
  over 7.6's edits — `after-functional-change` and the closing `pre-commit`
  hook passed; `pre-commit-functional` failed in `make test`'s first target,
  `test-domains`, on the one test section 10's work in progress left failing
  at `1d93f5d5f` (`test_a_delivery_other_than_the_recorded_result_is_a_conflict`,
  1 failed, 658 passed), which section 10 completes; `make test` stopped
  there, so the core storefront and storefront kit suites were run on their
  own (7.6's note). Section 10's `pre-commit` runs every suite over both.
- 7.6's fresh-context check: its docstring misstated what a bare string would
  read (every configured URL inside it, not fewer), restated; and the exact
  match was untested against a configured URL spelled otherwise, now a case.
  It also observed that the refusal is reachable by no integration test — the
  one caller passes the client's own `urls` and catches every exception — which
  `implementation.md`'s "No speculative guard code" rules against, and which is
  why section 7's first check removed it. The owner restored it (40 F4, D6),
  so it stays; whether that wants an exception declared under `rules.md` is
  the round's triage's to settle.

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
  Done: each module names the key once (`_DISPUTE_AUTHORITIES_UNREAD`, private:
  neither kit may import the storefront kit's constant, and nothing else needs
  theirs), and each preflight copies a non-empty value into the enabled
  readiness's public details and adds no blocker; each docstring names the
  resource. Read from the code, not tested: a disabled mechanism's preflight
  returns before it reads the resource and reports no public details, as
  before, so the report is an enabled mechanism's.
- [x] 8.2 Unit (each kit's settlement configuration tests): with
  `dispute_authorities_unread` in its resources, each mechanism's readiness carries
  it in its public details, stays ready with no blocker for it, and passes
  `SettlementConfigurationRegistry`'s public-detail validation; without it, the
  details are as before.
  Done: unit, `test_an_unread_registry_is_a_public_detail_and_no_blocker` in
  `kit/alkahest/tests/unit/test_settlement_config.py` and in
  `kit/arkhai-payments/tests/test_settlement_config.py`, each through
  `SettlementConfigurationRegistry.ordered_readiness` over the mechanism's real
  registration (whose validation refuses a public detail not allowlisted): the
  readiness is ready with no blocker and carries the value as given; without
  the resource, Alkahest's details are the same less that key, and Arkhai
  Payments' are empty.
- [x] 8.3 Bump `kit/alkahest`'s and `kit/arkhai-payments`'s packages (minor) and
  refresh the locks. Verify with `make check-version-bumps` and `make check-locks`.
  Done: `arkhai-kit-alkahest` 0.13.0 → 0.14.0, `arkhai-kit-arkhai-payments`
  0.8.0 → 0.9.0. Beyond the plan, the exact pins on Arkhai Payments move: the
  bare-metal storefront's (already bumped in 7.4) and the bare-metal buyer's,
  which takes a patch bump, 0.8.0 → 0.8.1. Relocked the eighteen projects
  whose locks name any of the three (`make lock PROJECTS=…`: both kits,
  `kit/arkhai-mediation`, `kit/deal-servicing`, `kit/storefront`, the bare-metal
  buyer and storefront, the VM buyer and storefront, `domains/apicredits` and
  its buyer, service and storefront, `domains/compute/delivery`,
  `core/buyer/market-binary`, the two lane doubles, `e2e-tests`). Both checks
  pass.
- [x] 8.4 Verification: `uv run pytest kit/alkahest/tests kit/arkhai-payments/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.
  Done: `make -C kit/alkahest test` 466 passed and `make -C kit/arkhai-payments
  test` 355 passed (with its typecheck, vector and model checks); `pre-commit`
  did not pass, for an environmental cause recorded in the section's notes.
  End-to-end: section 9's, as planned.

Section 8 notes (handoff):

- `pre-commit` at `e4f207b2e`, run after the machine rebooted:
  `after-functional-change` and the closing `pre-commit` hook passed;
  `pre-commit-functional` failed in `make test`'s `test-release-tooling` alone,
  50 of 3201 `scripts/tests` cases, every one rendering a Compose file with
  `docker compose config`, with no Docker daemon running (no `/var/run/docker.sock`
  after the reboot). The section changes no Compose file or stack configuration,
  and those cases passed in section 7's runs before the reboot. `make test`
  stopped there, so the suites after it did not run; of those, the two lane
  doubles' locks moved here, and `make -C tools/payments-lane-double test` (93
  passed) and `make -C tools/mediation-lane-double test` (78 passed) were run
  on their own. The rest (`helm test-render`, `tools/frp-grant-admission`,
  `tools/injected-time`, `tools/lane-double-controls`) is untouched by the
  section and unrun at this commit. Validation's full run is the evidence.
- The fresh-context check found no breach of guidance; its two evidence
  findings were taken (the pre-commit record, above, and 8.1's disabled
  mechanism stated as read from the code). It also observed that
  `kit/arkhai-payments/tests` is flat, not split into `unit/` and
  `integration/` as `test-placement.md` asks: older than this change, and
  left for the round's triage to record.

- Section 9 raises the storefronts' lower bounds to `arkhai-kit-alkahest>=0.14.0`
  and `arkhai-kit-arkhai-payments>=0.9.0` where they declare them (the
  bare-metal storefront pins Arkhai Payments exactly, already moved): an older
  mechanism ignores the resource, so the storefront's report would reach no
  public detail.

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
  Done, with deviations. The re-read's places: the VM storefront's in
  `run_publication_cycle_once` (`services/publication_loop.py`), right after
  its `compose` stage is entered, which the publication step and timer run;
  the bare-metal storefront's in its publication step
  (`lifecycle_steps.py`), after `enter_stage("compose")`; a preview reads
  nothing in either, since it changes nothing. The API-credit storefront has
  no publication cycle: it composes a listing's options when the listing is
  created or seeded (`ListingService.publish_from_quota`, through the
  composition's `publication_artifacts`), so its re-read is the first act of
  `publication_artifacts` — before composing listing options, as the
  requirement states it, though the plan named a cycle that storefront does
  not have; the round's triage may judge the delta's "each publication cycle"
  wording against it. Readiness: each composition merges
  `disputes.readiness_resources()` into the resources of every readiness it
  computes (VM `readiness()` and `publication_artifacts`; bare metal
  `readiness()`, which publication and status both call; API credits
  `readiness()` and `publication_artifacts`); the policy reads registries
  only while `use_registry_dispute_authorities` is true, so the resource is
  empty otherwise. Amended in the kit (7.2): `refresh` keeps the client
  factory it was given and `reread()` takes no argument, so no storefront
  plumbs a registry client factory into its publication step; the kit is
  unreleased at 0.12.0 in this change, so it takes no further bump.
  Startup's read is unchanged.
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
  real settlement composition and dispute policy, and a registry double
  standing where `MultiRegistryClient` wraps the registries, whose descriptor
  read answers `None` until a test gives a registry a real
  `RegistryDescriptor`, recording each read's selection (the VM and bare-metal
  storefronts' existing recording doubles gain that read; the API-credit test
  has a double of its own). In the bare-metal and API-credit tests startup's
  read is the app's lifespan's; the VM publication harness has no lifespan, so
  its test calls `refresh` with the factory the server's startup hands it
  (`_make_registry_client`) and installs the composition in the container as
  the composition root does — the VM's lifespan read is the degraded-startup
  test's below.
  - VM (`tests/integration/test_registry_dispute_authorities.py`, 2 passed):
    relying on two registries' recommendations alone, the first cycle opens no
    listing (the pool's one clause, a payments clause, composes no option)
    and status shows Arkhai Payments ready, no blocker, reporting both
    registries unread; once both answer, the next
    cycle publishes the payments option naming their authority, status drops
    the report, and a further cycle reads no registry ("A registry was read").
    With a local `[[Dispute]]` entry, the payments option publishes while both
    are unread, the mechanism ready and reporting them.
  - VM, `/health` and real startup (`test_degraded_startup.py`, extended): the
    real app and lifespan, its registry refusing connections, answers its
    health check (its database check `ok`, as before; no assertion reads its
    overall status), and status shows Alkahest's `dispute_authorities_unread`
    naming the registry beside its existing reachability blocker alone. That
    `/health` reads nothing of the report is read from the code.
  - Bare metal (`tests/integration/test_registry_dispute_authorities.py`, 1
    passed): over `recurring_world`, given `registry_recommendations` (no
    local entry), the listing publishes its Alkahest option alone while
    unread, status reports the registry on Arkhai Payments with no blocker,
    and the step after the registry answers adds the payments option; the
    registry is read at startup and at both steps.
  - API credits (`tests/integration/test_registry_dispute_authorities.py`, 1
    passed): payments beside Alkahest, no local entry, registry discovery on: a
    payments-clause create is refused 400 while unread, status reports the
    registry on Arkhai Payments with no blocker, and the create after the
    registry answers succeeds with the payments option naming its authority.
- [x] 9.3 Bump the three storefront packages (minor) with their lower bounds on the
  packages sections 7 and 8 bumped, and refresh the locks (`domains/vms/storefront`
  resolves the PyTorch CPU index, `docs/guidance/repository/locks.md`). Verify with
  `make check-version-bumps` and `make check-locks`.
  Done: the three bumps were taken in 7.4. Here the lower bounds move to
  `arkhai-kit-alkahest>=0.14.0` in all three and `arkhai-kit-arkhai-payments>=0.9.0`
  in the VM and API-credit storefronts (the bare-metal one pins it, moved in
  8.3); the storefront kit's pin is 7.4's. Relocked `kit/storefront`, the three
  storefronts and `e2e-tests` (only the storefronts' locks moved). Both checks
  pass.
- [x] 9.4 Verification: `uv run pytest domains/vms/storefront/tests
  domains/bare_metal/storefront/tests domains/apicredits/storefront/tests` passes,
  and `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: the lanes' payment and dispute scenarios publish options from
  a registry that answers at startup — `e2e_vm_payment_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` — exercising the
  unchanged startup read beside the new cycle; no lane starts a storefront before
  its registry, and none is owed.
  Done: `make -C domains/vms/storefront test` (unit 1196 passed, 1 skipped;
  integration 615 passed, again after the degraded-startup extension), `make -C domains/bare_metal/storefront test` 659 passed, `make -C
  domains/apicredits/storefront test` 286 passed, `kit/storefront`'s unit
  test 5 passed after 9.1's amendment; the three storefront suites again after
  the fresh-context fixes. `pre-commit` did not pass, for section 8's
  environmental cause (the section's notes). End-to-end, reasoned and not run
  (the lanes run at validation): the three markers' lanes publish from a
  registry answering at startup, so the first cycle's re-read finds nothing
  unread and reads nothing; none is owed.

Section 9 notes (handoff):

- `pre-commit` at `5549f6b7e`: `after-functional-change` and the closing
  `pre-commit` hook passed; `pre-commit-functional` failed in `make test`'s
  `test-release-tooling` alone, the same 50 Compose render cases as section 8,
  with no Docker daemon running; every suite `make test` runs before that
  target passed, the three storefronts' and the storefront kit's among them.
  The suites after it (`helm test-render`, the frps plugin, `injected-time`,
  `lane-double-controls`, the two lane doubles) are untouched by the section
  and unrun at this commit.
- For the round's triage: "settlement status" in the delta's "A registry is
  still unread" and in D6 is shown through the status route (`GET
  /api/v1/system/status`, `settlement`), which reads the running
  composition. The VM storefront's `market-storefront settlement status`
  command computes readiness in its own process with no dispute policy
  (`groups/settlement.py`), so it never shows `dispute_authorities_unread`;
  whether the requirement means that command too is the round's to settle.
- For the round's triage and closeout's promotion (11.9): the API-credit
  storefront reads again when a listing's options are composed, at its
  creation or seeding, since it runs no publication cycle; the delta and the
  promotion text say "each publication cycle".
- The fresh-context check's findings were taken: the bare-metal test moved
  into `tests/integration/`, three inaccurate comments (the API-credit
  double's publication, the bare-metal world's `registries` in its served
  branch, "signed descriptor"), the bare-metal test asserting the Alkahest
  option and the VM test that no listing opens while unread, and the evidence
  claims above. Declined: replacing `MultiRegistryClient` on the core module
  in the API-credit test, which `testing-python.md` warns against for a
  command module's factories. The storefront's startup takes its factory by
  name (`server.py` imports `_make_registry_client`), so no seam the
  storefront owns reaches startup's read, and the VM harness replaces the same
  name for its publication tests.

## 10. A bare-metal end under a delivery conflict, and the result read while a lease ends

Replanned against the reviewed design after the return to design (D9 as restated,
design review 40 F1): the unchecked tasks 10.1–10.4 are replaced; the notes below
record the stop that returned the change, and the task numbers they cite are the
replaced tasks'.

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
  Done, the rule moved out of the route. Beyond the plan's file, so the HTTP
  binding stays thin (`implementation.md`, "Thin controllers"), as the sibling
  access read already is: the route calls a new
  `BareMetalFulfillmentService.result()` in `fulfillment_service.py`, which
  reads through `status`, answers in `_RESULT_STATES` — `active`,
  `TERMINATING`, the module's `_TEARDOWN_STATES` and `released`, with no
  literal repeated — and still answers "bare-metal fulfillment result is not
  ready" while no receipt or result is recorded; its docstring states the
  rule and cites the requirement. The route's answers, its messages and its
  refusals are unchanged but for `terminating`. Evidence: 10.3.
- [x] 10.2 Confirm `BareMetalFulfillmentService.converge_teardown` is deleted from
  `fulfillment_service.py` (committed at `1d93f5d5f`) and nothing calls it: `git
  grep -n converge_teardown -- ':!openspec' ':!docs'` names only the provisioning
  service's `converge_teardowns` and the e2e comments naming it. (D9.)
  Done: the grep names only the provisioning service's `converge_teardowns`
  (and its private `_converge_teardown_record`), that service's tests calling
  `converge_teardowns`, and the two e2e comments; nothing in the bare-metal
  storefront.
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
  Done: application integration, the real storefront app served on a loopback
  port, driven by the production buyer's fulfillment transport
  (`BareMetalFulfillmentTransport`: status, result, access, and `teardown`, the
  lifecycle `end`) after a settle through `StorefrontClient`, with the capacity
  and provisioning doubles at the site boundary. `make -C
  domains/bare_metal/storefront test` 662 passed (the three tests below, four
  cases with the parametrization), and again after the fresh-context fixes.
  - `test_a_delivery_other_than_the_recorded_result_is_a_conflict`, restated
    and parametrized over the site after the termination: still reporting the
    other delivery (not having begun the teardown) or having torn it down.
    Before the end the three reads answer 409 `delivery_conflict`; the end
    answers `tearing_down` and terminates the lease once; afterwards status
    answers the lease's state (`terminating`, or `torn_down`), the result read
    answers exactly what it answered before the conflict, receipt and result,
    and access answers 409 "bare-metal access is unavailable outside an active
    lease" (a plain detail, no error code); the stored result is unchanged.
    The first case shows that the reads after an end make no comparison even
    while the site still reports the other delivery.
  - `test_a_result_is_read_as_recorded_while_its_lease_ends`: delivered, no
    conflict, the lease ended while the site still reports the fulfillment
    `active`; status answers `terminating` and the result read answers the
    recorded result and receipt.
  - `test_a_lease_ended_before_delivery_has_no_result`: the site reports the
    fulfillment `dispatch_pending` through the settle, so no result is
    recorded; the end terminates the begun lease (one begin, one termination),
    status answers `terminating`, and the result read answers 409 "bare-metal
    fulfillment result is not ready", no receipt or result stored. It reaches
    the route through the typed clients, so no lower-level case was needed.
  The provisioning double gains `tears_down_on_termination` (default true,
  today's behaviour) and a class attribute `state` (default `active`), the
  state reported before any teardown; it is a class attribute because two
  subclasses in `test_deal_controls.py` already set one of that name, which an
  instance attribute would shadow. No other test changes. Fail-before not
  shown: `scripts/change-workflow run test-before … --at 195a67c32` fails
  loading the package's `conftest.py` in its `--no-project` environment (`No
  module named 'injected_time'`). Reasoned: at that commit the route did not
  admit `terminating`, so the conflict test's first parametrization and the
  ending-lease test fail at their result read with 409 "not ready", as the
  stopped session's notes below record of the route. The before-delivery test
  passes there too, but by the state check refusing `terminating`, with the
  same message; only with the fix does its read reach the missing-receipt
  clause, so it cannot tell the two refusals apart.
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
  Done: `make -C domains/bare_metal/storefront test` 662 passed. `pre-commit`
  passed over the section's final code (`after-functional-change`,
  `pre-commit-functional` — every suite of `make test`, `test-release-tooling`
  with its Compose renders included, so sections 8 and 9's environmental
  failure did not recur — and `pre-commit`, at `195a67c32`, task 7.6's
  commit, with this section's edits); after it, only a docstring's wording in
  `result()` and the gap row's count changed. The defect is recorded in the
  section's notes. End-to-end, reasoned and not run (the lanes run at
  validation): `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal`
  are in the bare-metal lane (`e2e-tests/Makefile`), `e2e_bare_metal_deal` in
  none, since it needs a real host; their result reads
  (`scenarios/bare_metal/compute_deal_driver.py`'s and `purchase_driver.py`'s
  `assert_delivery`, and the payment deal's re-drive) come while the lease is
  active, before the buyer's teardown, so they exercise the unchanged path; no
  lane plants a conflicting delivery or reads a result while a lease is
  `terminating`, and none is owed.

Section 10 notes (completed in the session that completes the round):

- Outside item 3's stated scope: the result read answering "not ready" while
  a lease is `terminating`, though its receipt and result stood before and
  after, is a defect found during the change (`docs/guidance/workflow/changes.md`,
  "Defects found during a change"; D9), fixed here (10.1).
- Beyond the plan's file: the result read's rule now lives in
  `BareMetalFulfillmentService.result()`, as the access read's does, and the
  route only calls it (10.1). The section touches `api.py`,
  `fulfillment_service.py` and `test_http_settlement.py`.
- The provisioning double in `test_http_settlement.py` is shared:
  `test_deal_controls.py` imports it and subclasses it with a class attribute
  `state`, so the double's own `state` is a class attribute too (10.3).
- Recorded as an unowned gap in `openspec/changes/README.md`: the
  bare-metal storefront's flat `tests/` root, `test_http_settlement.py` among
  its modules.
- Two fresh-context checks ran. Taken: the result rule moved out of the
  route, with no state literal repeated; the flat test root recorded as a gap;
  the double's `terminate_lease` docstring and a helper's name (`_accepted_deal`,
  the deal accepted, not settled); a docstring's "until the lease is released",
  now "through"; the gap row's module count; and two evidence claims in 10.3
  (the case count, and why the before-delivery case passes at the base).
  Declined: nothing. The `result()` docstring cites the added requirement's
  heading, which reaches `openspec/specs/storefront-publication/spec.md` when
  closeout archives the change.
- The round is complete with this section: validation and the implementation
  review follow, then the round's triage.

Section 10 notes from the earlier session (stopped; the change returned to
design, and the task numbers they cite are the replaced tasks'):

- What the code shows. The planned scenario (D9; the `storefront-publication`
  delta's "A buyer ends a deal while the site reports a different delivery";
  10.1) has the status, result and access reads "still answer 409
  `delivery_conflict`" after the buyer's end. They do not, and the code says
  why: `BareMetalFulfillmentService.status` judges a conflict
  (`_refuse_conflicting_delivery`) only while the site reports the
  fulfillment `active`. Once the lifecycle `end` reaches `apply_end`, which
  calls `terminate_lease` and records the lease `terminating`, a status read
  returns the ending as it stands — `terminating` while the site has not begun
  the teardown, then the teardown state it reports — with no comparison; the
  access read refuses as outside any active lease (409, "bare-metal access is
  unavailable outside an active lease", no `delivery_conflict`); and the
  result route answers "not ready" (409) while `terminating`, and the recorded
  result once a teardown state is reported. So the scenario's first half
  holds — the end is not refused for the conflict, and terminates the lease —
  and its "still answer 409 `delivery_conflict`" after the end does not.
- Evidence. `test_a_delivery_other_than_the_recorded_result_is_a_conflict`,
  extended as 10.1 plans: before the end the three reads answer 409
  `delivery_conflict`; the production buyer's teardown (its `end_delivery`,
  the lifecycle `end`) is answered `tearing_down`; then the first read after
  the end, status, does not raise (`make -C domains/bare_metal/storefront
  test`: that test failed, 658 others passed). The provisioning double's
  `terminate_lease` reports the fulfillment torn down at once; a real site
  reports it `active` or tearing down first, and either way the status read
  makes no comparison after the end.
- The decision design owes. Either the scenario is restated to what the code
  does — the end terminates the lease and is not refused; reads made while the
  delivery is active answer 409 `delivery_conflict`, the recorded result
  standing; once the lease is ending, the reads report the ending as for any
  ended lease — which the recommendation is, since a conflict is a
  disagreement about a live delivery and an ending lease has none to serve;
  or the storefront is to keep refusing the reads with `delivery_conflict`
  after an end, a behaviour change design would have to motivate. Either way
  the delta (written whole at design, and not edited by implementation) and
  D9 change, and 10.1 with them.
- Done and committed here, no task checked: `converge_teardown` deleted from
  `fulfillment_service.py` (10.2's edit; `git grep -n converge_teardown`
  outside `openspec/` and `docs/` names only the provisioning service's
  `converge_teardowns` and two e2e comments naming it), and the test extended
  as 10.1 plans, failing at its after-end reads. 10.3 needs no bump: the
  bare-metal storefront was bumped in 7.4. Not run: `pre-commit` and the
  fresh-context check, which follow the design's answer.

## 11. Closeout

The closeout task of `docs/guidance/workflow/closeout.md`, its parts in order, with
this repository's parts (`openspec/README.md`, "This repository's closeout parts")
after campaign index currency.

- [ ] 11.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the
  comments and docstrings the change added or restated — the job engine's start and
  finish, the rerun predicate, `job_contract`, the release status port, the
  allocator and its index comment, acceptance, the dispute policy, the two
  mechanisms' preflights, the settings' comments and the e2e lease back-date
  comments — state the current system and name no change, review or task. A finding
  returns the change to implementation.
- [ ] 11.2 Import placement: confirm every import the change's diff adds sits at
  module level. One that should move returns the change to implementation.
- [ ] 11.3 Documentation compliance: re-check each decision's destination below
  against `openspec/README.md`, "Documentation placement", and confirm each
  permanent document written describes the current state.
- [ ] 11.4 Narrative compression: shorten completed-task notes here to final
  behaviour, evidence, deferred work and destinations, moving any rationale not yet
  in `design.md` there first.
- [ ] 11.5 Roadmap currency (`docs/development/ROADMAP.md`, "Goal 1 — Consolidate
  physical-resource authority in the provisioning service"): remove the five open-gap
  rows this change owns — the relay-pool mismatch, the startup-only dispute
  authority read, the bare-metal end under a delivery conflict, the false
  `RelayWindowExhaustedError`, and the teardown that failed before its executor ran.
  In the current state, add to the relay paragraph that a delivery is leased on its
  declaration's pool's relay and the proxy-adding job points the host's one client
  at it; and state that a teardown recorded as never started is run again within a
  bound while its lease waits, a teardown whose playbook ran still waiting for an
  operator. Name the update in the design-promotion record.
- [ ] 11.6 Campaign index currency (`openspec/changes/README.md`): this change's row
  to `in closeout` with its archive link once 11.11 runs, and its line in Goal 1's
  dependency graph marked archived. `report-provisioning-failures-to-operators`'s
  `Depends on` entry for this change stays for archive cleanup. Run
  `make check-change-index`.
- [ ] 11.7 Packaging: run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=resolve-delivery-correctness-gaps`. The
  change touches no `.agents/`, `.claude/` or `.codex/` path, so
  `make check-agent-skills` is not owed unless a section did.
- [ ] 11.8 End-to-end pipeline: record the pipeline run at the closeout's code
  (`make run-e2e`, `make fetch-e2e-logs`), its result, and the scenarios that
  exercise the change's paths: `e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_vm_payment_purchase`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_bare_metal_deal` and
  `e2e_credits_payment_deal`. A failed run returns the change to implementation;
  a run that could not be made is recorded as unrun with its cause and owner.
- [ ] 11.9 Promotion: write the permanent documents and complete the
  design-promotion record below.
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
- [ ] 11.10 Guidance placement: the change adds no guidance under
  `docs/guidance/` or beside a specification; record that, or, if a section added
  some, read it against the layer test and run `make check-guidance`.
- [ ] 11.11 Documentation citations and archival: run
  `make check-doc-citations CHANGE=resolve-delivery-correctness-gaps` and resolve
  every match, then `scripts/change-workflow openspec validate
  resolve-delivery-correctness-gaps --strict`; then archive with
  `scripts/change-workflow openspec archive resolve-delivery-correctness-gaps -y`,
  merging the five delta specs into `openspec/specs/`, and read each merged spec's
  diff for every added and modified requirement appearing once as its delta states.

## Design promotion record

Filled during implementation and completed at closeout (11.9), one row per decision
in `design.md` and per destination named in 11.5, 11.6 and 11.9.

| Accepted decision | Permanent location |
|---|---|
| D1 — Item 1 is corrected and guarded, not fixed by a new rule | `openspec/specs/physical-provisioning/spec.md` ("A relayed delivery's relay is its declaration's pool's", by the archive); `openspec/specs/physical-provisioning/architecture.md#relay-sharing-and-containment`; `docs/development/ROADMAP.md` (Goal 1) |
| D2 — Concurrent retries return the first acceptance and the owner's lease | `openspec/specs/physical-provisioning/spec.md` ("A concurrent allocation for one owner receives that owner's lease"); `openspec/specs/fulfillment/spec.md` ("An equivalent acceptance that waited on another returns the first") |
| D3 — A lease waits while its fulfillment still has something to try | `openspec/specs/physical-provisioning/spec.md` ("An undelivered lease is released by what its fulfillment proves"); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `openspec/specs/physical-provisioning/configuration.md`; `docs/development/ARCHITECTURE.md#release`; `docs/operator-handbook.md#upgrading-a-deployment` |
| D4 — A job records that its execution is starting before it starts | `openspec/specs/physical-provisioning/spec.md` ("A job records that its execution is starting before it starts"); `openspec/specs/compute-provisioning-contract/spec.md` ("A job view shows when its execution started and when it finished"); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release` |
| D5 — A rerun is a new job under a key derived from the jobs already bound | `openspec/specs/physical-provisioning/spec.md` ("A teardown that never started is run again under a new job identity, within a bound"; "Lease release delegates to durable fulfillment teardown"); `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `openspec/specs/physical-provisioning/configuration.md` |
| D6 — A storefront reads again a registry it could not read | `openspec/specs/settlement-configuration/spec.md` ("A storefront reads again a registry whose recommendations it could not read"); `openspec/specs/settlement-configuration/configuration.md#dispute-authority-preferences` |
| D7 — A compensating teardown reruns by the same rule | `openspec/specs/physical-provisioning/spec.md` (the rerun requirement's compensating-teardown scenario) |
| D8 — The rule that a fulfillment's teardown is one job is restated in `physical-provisioning` | `openspec/specs/physical-provisioning/spec.md`; `openspec/specs/physical-provisioning/architecture.md#proof-driven-release`; `docs/development/ARCHITECTURE.md#release` |
| D9 — Item 3 is two requirements' scenarios, a test, a fix to the result read, and a deletion | `openspec/specs/storefront-publication/spec.md` ("A bare-metal delivery that conflicts with its recorded result is refused"; "A bare-metal result read answers the recorded result while its lease ends", by the archive) |
| D10 — One round of three sessions | No permanent destination: the implementation cadence is this change's plan |
| Roadmap currency (11.5) | `docs/development/ROADMAP.md`, Goal 1 |
| Campaign index currency (11.6) | `openspec/changes/README.md`, this change's row and Goal 1's graph |
