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

- [ ] 1.1 In `provisioning/compute/src/compute_provisioning/jobs/db.py`, add the
  nullable `execution_started_at` and `finished_at` columns to `JobRecord`. In
  `jobs/migrations.py`, add one additive migration after the baseline adding both
  columns to `ansible_jobs`, with an ID dated for this change, and compose it into
  the service's chain in
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`
  after `SSH_CONNECTIONS_VERSION_2`. Existing rows read null in both. Verify with
  1.6's migration case. (D4, D5; `docs/guidance/engineering/migrations.md`.)
- [ ] 1.2 In `jobs/executor.py`, give `JobRun` a `report_starting()` callback beside
  `report_handle`. In `jobs/engine.py`, `process_job` supplies it: it records the
  instant from the process's time source (`injected_time`, as `created_at` is) in a
  conditional write that succeeds only while the job is `running`, keeps an instant
  an earlier attempt recorded, and raises when the job is no longer `running` or the
  write fails, so the executor spawns nothing and the attempt ends through the
  engine's internal-error path, which leaves a cancelled job cancelled. Verify with
  1.5. (D4's three rules; requirement scenarios "The start cannot be recorded", "A
  job is cancelled before its start is recorded", "A retried job keeps its first
  start".)
- [ ] 1.3 In `jobs/engine.py`'s `_transition`, stamp `finished_at` from the
  process's time source on every transition to a terminal status (`succeeded`,
  `failed`, `cancelled`), including `_fail` and the conditional `cancel_job` update,
  and never move it once set. `_status` fills the job view's two fields. Verify with
  1.5. (D5; `finished_at` from the process's time source, not `updated_at`.)
- [ ] 1.4 In `provisioning/compute/ansible/src/compute_provisioning_ansible/executor.py`,
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
- [ ] 1.5 Library integration
  (`provisioning/compute/tests/integration/test_job_authority.py`): a job refused
  before its executor runs (no host, an unregistered host, an unsupported action)
  records no start and a `finished_at`; a job whose executor reports its start and
  then fails records both; a start that cannot be recorded spawns nothing (a test
  executor asserting it was never asked to start); a job cancelled between its claim
  and its start stays `cancelled` with no start; a retried job keeps its first
  start; a spawned job whose handle write fails keeps its start; a terminal job's
  `finished_at` does not move. Drive the instants with the injected time source.
- [ ] 1.6 Library integration of the migration
  (`provisioning/compute/service/tests/integration/test_migration_chain.py`, as
  `docs/guidance/repository/migration-chain-tests.md` gives the chain's cases): a
  database adopted at the v0.3.0 floor gains both columns, its existing jobs reading
  null in both, and a fresh database builds them.
- [ ] 1.7 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_vms_api.py` or a sibling):
  a job read through the provisioning client carries `execution_started_at` and
  `finished_at` for a job that ran, and null `execution_started_at` with a
  `finished_at` for one refused before its playbook, as the contract's scenarios
  state.
- [ ] 1.8 Bump `arkhai-compute-provisioning` (minor, the `JobRun` protocol and the
  job columns), `arkhai-compute-provisioning-ansible` (patch),
  `arkhai-compute-provisioning-contracts` (minor, the job view's fields) and
  `arkhai-compute-provisioning-service` (minor, the migration); raise the lower
  bounds of the packages that need the new fields (the ansible package and the
  service on `arkhai-compute-provisioning`, the service on the contracts); refresh
  the locks. Verify with `make check-version-bumps` and `make check-locks`.
- [ ] 1.9 Verification: `uv run pytest provisioning/compute/tests
  provisioning/compute/ansible/tests provisioning/compute/contracts/tests
  provisioning/compute/service/tests` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: every lane deal
  that creates and tears down records both instants on the unchanged path —
  `e2e_deal`, `e2e_vm_payment_purchase` and `e2e_bare_metal_mock_deal`; no scenario
  reads the new fields, and none is owed: the application-integration case is their
  evidence.

## 2. A teardown that never started is run again, and its lease waits for it

Delivers the rerun predicate, the provider's rerun dispatch, the engine-internal
teardown-job read, and the release status that keeps a lease `releasing` while a
rerun is pending (D3's status rule, D5, D7, D8; `physical-provisioning` "A teardown
that never started is run again under a new job identity, within a bound", "Lease
release delegates to durable fulfillment teardown", "Lease release and fulfillment
teardown have separate retry ownership", and the status rules of "An undelivered
lease is released by what its fulfillment proves"). Touches `provisioning/compute`
only; depends on section 1.

- [ ] 2.1 In `provisioning/compute/src/compute_provisioning/jobs/engine.py`, add the
  engine-internal teardown-job read: unpaginated, the reservation's jobs under the
  `teardown` action kind in creation order, each as a compute-owned record carrying
  its status, whether its execution is recorded as never started (D4: `failed`, not
  `cancelled`, no `execution_started_at`, no handle, and a `finished_at`), its
  `finished_at`, and its order. It is not on the wire and not on the paginated
  listing. Verify with 2.6. (D5, 11 F5.)
- [ ] 2.2 Add a module in `compute_provisioning` beside `release.py` (it is imported
  by both `job_fulfillment.py` and `release.py`, which already imports
  `job_fulfillment`), holding the rerun policy — `teardown_rerun_limit`, refusing a
  negative value with an error naming the setting, and the job retry policy's
  `delay_seconds` — and the one predicate answering `not_rerunnable` (latest job
  started, cancelled, finished before starts were recorded, or reruns disabled),
  `waiting(until)`, `ready(n)`, or `spent(n)` from the teardown-job records and the
  current instant. Export it from `compute_provisioning/__init__.py`. Verify with
  2.5. (D5, D7.)
- [ ] 2.3 In `compute_provisioning/job_fulfillment.py`, `JobReader` gains the
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
- [ ] 2.4 In `compute_provisioning/release.py`, `FulfillmentReleaseStatusPort` takes
  the rerun policy and the teardown-job read: a `teardown_failed` aggregate whose
  predicate answers `waiting` or `ready` reports `TEARING_DOWN`; `spent` and
  `not_rerunnable` report `FAILED` with reason `teardown_failed`, the message saying,
  for a never-started teardown, that its execution never started and how many reruns
  were spent. `compensable` is unchanged. Update the module docstring. Verify with
  2.6. (D3, D5, D8; "Lease release delegates to durable fulfillment teardown".)
- [ ] 2.5 Unit (`provisioning/compute/tests/unit/`, a module for the predicate):
  one case per outcome — latest job started; cancelled; finished before starts were
  recorded (no `finished_at`, with and without a handle); reruns disabled; waiting
  before the delay; ready at the delay with the right *n*; spent at the limit — and
  the policy refusing a negative limit.
- [ ] 2.6 Library integration (`provisioning/compute/tests/integration/`, beside the
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
- [ ] 2.7 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane induces a teardown that fails before its playbook
  starts, so no scenario exercises a rerun; the lanes' deals exercise the unchanged
  first-teardown path. None is owed: section 3's application-integration cases are
  the deployed-composition evidence.

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

- [ ] 3.1 In `provisioning/compute/service/src/compute_provisioning_service/settings.toml`,
  add `teardown_rerun_limit = 3` with a comment stating its meaning, and raise
  `lease_watchdog_grace_period_seconds` from 300 to 3600, its comment restated as
  D3 sizes it; restate `relay_grant_expiry_grace_seconds`'s comment over the
  teardown still due, as D3 gives it, its value unchanged. Build the rerun policy
  once from the settings and the job retry policy (`services/job_retry.py`'s
  `retry_policy_from`), so a negative limit refuses startup naming the setting.
  Verify with 3.5. (D3, D5.)
- [ ] 3.2 Compose the policy and the engine's teardown-job read into
  `FulfillmentReleaseStatusPort` in `compute_provisioning_service/container.py`, and
  into `JobFulfillmentProvider` in
  `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/runtime.py` and
  `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/runtime.py`
  (and their `bundle.py` where it builds the provider), from the one policy the
  service builds. Verify with 3.5. (D5.)
- [ ] 3.3 Set `lease_watchdog_grace_period_seconds: 3600` in
  `helm/charts/provisioning/values.yaml` and `helm/values.yaml`, and bump each
  chart's version, since its packaged values changed
  (`docs/guidance/repository/package-versions.md`, "A version changes when its
  contents change"). Restate the 300-second grace in the comments on the lease
  back-date in `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py` and
  `e2e-tests/tests/e2e/roles/scenarios/vms/test_full_deal_buyer_cli.py` to the
  configured grace, keeping their reasoning. Verify with `make -C helm test-render`
  and `uv run pytest e2e-tests/tests/unit`. (D3, D10.)
- [ ] 3.4 In `docs/operator-handbook.md`, "Upgrading a deployment" — "What the
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
- [ ] 3.5 Application integration through the typed client
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
- [ ] 3.6 Bump `arkhai-vm-provisioning-adapter` and
  `arkhai-bare-metal-provisioning-adapter` (or the names their `pyproject.toml`
  states; minor, the provider's new argument) and raise their lower bound on
  `arkhai-compute-provisioning`; the service's bump is section 1's. Refresh the
  locks. Verify with `make check-version-bumps` and `make check-locks`.
- [ ] 3.7 Verification: `uv run pytest provisioning/compute/service/tests
  domains/vms/provisioning/adapter/tests domains/bare_metal/provisioning/adapter/tests`
  passes, `make -C helm test-render` passes, and `scripts/change-workflow run
  pre-commit resolve-delivery-correctness-gaps` passes. End-to-end: the lanes'
  back-dated-lease stages run under the new grace — `e2e_vm_payment_purchase`,
  `e2e_deal_buyer_cli` and `e2e_bare_metal_payment_deal` release their leases
  through the unchanged path; none induces a rerun or a timeout, and none is owed.

## 4. An equivalent acceptance that waited on another returns the first

Delivers acceptance judged from the row its lock returns (D2's acceptance half;
`fulfillment` "An equivalent acceptance that waited on another returns the
first"). Touches `kit/fulfillment` only. A defect found during the change, outside
item 2's stated scope; record it so in this section's task notes
(`docs/guidance/workflow/changes.md`, "Defects found during a change").

- [ ] 4.1 In `kit/fulfillment/src/market_fulfillment/settlement_repository.py`,
  `accept_fulfillment`'s locked select takes `populate_existing`. In
  `fulfillment_persistence.py`, `FulfillmentTransaction.accept` drops its unlocked
  pre-read, and `FulfillmentAcceptanceDecision` drops `newly_accepted`; confirm no
  caller reads it (`git grep -n newly_accepted`). Verify with 4.2. (D2, 11 F7.)
- [ ] 4.2 Library integration
  (`kit/fulfillment/tests/integration/test_fulfillment_acceptance.py`): two sessions
  on one file-backed database — session 2 loads the reservation's row, session 1
  accepts and commits, session 2 accepts an equivalent request and receives session
  1's `fulfillment_id`, the row keeping that identity and its prepared operation,
  with nothing prepared or persisted a second time; and without the fix's
  `populate_existing`, the same steps would accept anew (state the stale read the
  test pins in its docstring). Sequential steps, no threads
  (`docs/guidance/engineering/concurrency-tests.md`).
- [ ] 4.3 Bump `arkhai-kit-fulfillment` (minor, the exported
  `FulfillmentAcceptanceDecision` loses a field) and refresh the locks it requires.
  Verify with `make check-version-bumps` and `make check-locks`.
- [ ] 4.4 Verification: `uv run pytest kit/fulfillment/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: every lane deal accepts its fulfillment once, on the unchanged
  path (`e2e_deal`, `e2e_bare_metal_mock_deal`); no lane overlaps two acceptances,
  and none is owed (design, Open Questions: the PostgreSQL proof).

## 5. A concurrent allocation for one owner receives that owner's lease

Delivers the allocator's owner read after the relay lock and again on any
uniqueness conflict (D2's allocator half; `physical-provisioning` "A concurrent
allocation for one owner receives that owner's lease"). Touches
`provisioning/compute/src/compute_provisioning/relays/allocator.py` and its
tests; depends on section 1, which owns `arkhai-compute-provisioning`'s bump, so
this section bumps nothing and refreshes no lock for it.

- [ ] 5.1 In `relays/allocator.py`, `allocate_in_session` reads the owner's active
  lease after `db.get(Relay, …, with_for_update=True, populate_existing=True)` and
  before refusing a missing or disabled relay, returning it when held; in the claim
  loop, on `IntegrityError` it reads the owner's active lease again and returns it
  when one exists, moving to the next port only otherwise. Restate the docstring
  and the index comment in `relays/db.py` to the rule. Verify with 5.2.
- [ ] 5.2 Library integration
  (`provisioning/compute/tests/integration/test_relay_port_allocator.py`): the
  statement order rendered for the PostgreSQL dialect shows the owner read after the
  relay's `FOR UPDATE`, as `test_the_relay_is_read_for_update_before_a_port_is_claimed`
  does; a test-only allocator subclass whose first owner read misses while the
  owner's lease exists returns that lease and raises no `RelayWindowExhaustedError`;
  a claim conflicting with another owner's port selects another and raises
  exhaustion only when the window is full; an owner holding a lease on a disabled
  relay receives it and no `RelayDisabledError` (the existing drain scenario, kept
  passing).
- [ ] 5.3 Verification: `uv run pytest provisioning/compute/tests` passes, and
  `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: no lane runs a relay-backed pool, so no scenario exercises
  allocation; none is owed.

## 6. A relayed delivery's relay is its declaration's pool's

Delivers the tests holding D1's rule (D1; `physical-provisioning` "A relayed
delivery's relay is its declaration's pool's"). Touches tests only:
`provisioning/compute/iac/tests`, `domains/vms/provisioning/adapter/tests`, and
`provisioning/compute/service/tests`.

- [ ] 6.1 Static test of the family roles
  (`provisioning/compute/iac/tests/test_client_baseline.py`, or beside it): the
  `relay-proxy` role's `add.yml` includes `relay-client` before adding the proxy;
  `relay-client` synchronizes the baseline from `frp_server_addr`,
  `frp_server_port` and `frp_auth_token` and notifies the client's restart only on a
  changed baseline; and `client_config.py prepare`, run on a configuration naming
  another relay with a proxy block, rewrites the three fields, reports `changed`, and
  keeps the proxy block ("A proxy is added on a host whose client names another
  relay").
- [ ] 6.2 Library integration
  (`domains/vms/provisioning/adapter/tests/integration/test_relay_pool_configuration.py`):
  a host placed in a pool on relay R2, and an unplaced host, each with its
  declaration in a pool on R1, are leased a port on R1 by an accepted relayed
  create, whose prepared job carries R1 as its relay ("A host placed under another
  relay delivers through its declaration's", "An unplaced host delivers through its
  declaration's relay").
- [ ] 6.3 Application integration through the typed client
  (`provisioning/compute/service/tests/integration/test_capacity_api.py`): a
  declaration in a pool on R1 whose reservation holds a relay port lease on R1 is
  refused a move to a pool on R2, and stays in its pool ("A declaration holding a
  lease is moved to a pool on another relay").
- [ ] 6.4 Verification: `uv run pytest provisioning/compute/iac/tests
  domains/vms/provisioning/adapter/tests provisioning/compute/service/tests/integration/test_capacity_api.py`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: no lane runs a
  relay-backed pool; none is owed. The real-provisioning modules
  (`e2e_vm_real_provisioning`, `e2e_bare_metal_real_provisioning`) exercise relayed
  delivery but run in no lane.

## 7. The descriptor read selects registries, and the policy reads again what failed

Delivers the core storefront's selective descriptor read and the dispute policy's
per-registry read state and re-read (D6's read half; `settlement-configuration` "A
storefront reads again a registry whose recommendations it could not read", its
read scenarios). Touches `core/storefront` and `kit/storefront`.

- [ ] 7.1 In `core/storefront/src/core_storefront/multi_registry_client.py`,
  `MultiRegistryClient.get_descriptors` gains an optional selection of registry
  URLs, absent meaning every configured registry as now, reading and returning only
  those selected. Verify with the core storefront's tests for the client: a
  selection reads only the selected registries and an absent one reads all.
- [ ] 7.2 In `kit/storefront/src/market_storefront_kit/dispute_configuration.py`,
  `RegistryDisputePolicy` keeps, per registry, whether its last read succeeded and
  when it last failed (the injected time source); `refresh` records them; a new
  re-read reads only the registries whose last read failed, through the selection,
  keeping the others' recommendations; and the policy exposes its unread registries
  with their last failure. Verify with 7.3.
- [ ] 7.3 Unit (`kit/storefront/tests`, beside the dispute configuration's tests):
  a startup read in which one of two registries fails, then a re-read, reads only
  the failed one and adopts its recommendations while keeping the other's ("One of
  several registries could not be read"); a re-read after every read succeeded
  reads nothing ("A registry was read"); the unread registries are reported with
  their last failure until a read succeeds.
- [ ] 7.4 Bump `core/storefront`'s package (minor, the additive parameter) and
  `kit/storefront`'s (minor), raise `kit/storefront`'s lower bound on the core
  package, and refresh the locks. Verify with `make check-version-bumps` and `make
  check-locks`.
- [ ] 7.5 Verification: `uv run pytest core/storefront/tests kit/storefront/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.

## 8. The mechanisms report an unread registry in their public details

Delivers `dispute_authorities_unread` as a public detail of the Alkahest and Arkhai
Payments mechanisms' readiness, with no blocker (D6's report half;
`settlement-configuration` "A storefront reads again a registry whose
recommendations it could not read", its readiness clauses). Touches `kit/alkahest`
and `kit/arkhai-payments`.

- [ ] 8.1 In `kit/alkahest/src/market_alkahest/settlement_config.py`, add
  `dispute_authorities_unread` to the registration's public-detail allowlist and copy
  it from the preflight's resources into its public details, as `chain_probe` is,
  adding no blocker. In `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`,
  the registration allowlists the key and `arkhai_payments_preflight` copies it from
  its resources. Verify with 8.2.
- [ ] 8.2 Unit (each kit's settlement configuration tests): with
  `dispute_authorities_unread` in its resources, each mechanism's readiness carries
  it in its public details, stays ready with no blocker for it, and passes
  `SettlementConfigurationRegistry`'s public-detail validation; without it, the
  details are as before.
- [ ] 8.3 Bump `kit/alkahest`'s and `kit/arkhai-payments`'s packages (minor) and
  refresh the locks. Verify with `make check-version-bumps` and `make check-locks`.
- [ ] 8.4 Verification: `uv run pytest kit/alkahest/tests kit/arkhai-payments/tests`
  passes, and `scripts/change-workflow run pre-commit
  resolve-delivery-correctness-gaps` passes. End-to-end: section 9's.

## 9. The storefronts read again at publication and pass the unread registries on

Delivers each storefront's publication cycle reading again the registries whose
read failed, and its readiness resources carrying them (D6's composition;
`settlement-configuration` "A storefront reads again a registry whose
recommendations it could not read", its storefront scenarios). Touches
`domains/vms/storefront`, `domains/bare_metal/storefront`, and
`domains/apicredits/storefront`; depends on sections 7 and 8.

- [ ] 9.1 In each storefront, the publication cycle's `compose` stage calls the
  policy's re-read before composing options
  (`domains/vms/storefront/src/market_storefront/lifecycle_steps.py`'s publication
  step, and the bare-metal and API-credit storefronts' `lifecycle_steps.py`), and
  the settlement composition passes the policy's unread registries into the
  mechanism readiness resources under `dispute_authorities_unread` wherever
  readiness is computed (`settlement_composition.py` in each), only while
  `use_registry_dispute_authorities` is true. Startup's read is unchanged; `/health`
  reads none of it. Verify with 9.2.
- [ ] 9.2 Application integration (each storefront's tests, with a registry double
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
- [ ] 9.3 Bump the three storefront packages (minor) with their lower bounds on the
  packages sections 7 and 8 bumped, and refresh the locks (`domains/vms/storefront`
  resolves the PyTorch CPU index, `docs/guidance/repository/locks.md`). Verify with
  `make check-version-bumps` and `make check-locks`.
- [ ] 9.4 Verification: `uv run pytest domains/vms/storefront/tests
  domains/bare_metal/storefront/tests domains/apicredits/storefront/tests` passes,
  and `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: the lanes' payment and dispute scenarios publish options from
  a registry that answers at startup — `e2e_vm_payment_deal`,
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` — exercising the
  unchanged startup read beside the new cycle; no lane starts a storefront before
  its registry, and none is owed.

## 10. A bare-metal end under a delivery conflict

Delivers the scenario's test and the dead method's deletion (D9;
`storefront-publication` "A bare-metal delivery that conflicts with its recorded
result is refused", "A buyer ends a deal while the site reports a different
delivery"). Touches `domains/bare_metal/storefront`.

- [ ] 10.1 Extend `test_a_delivery_other_than_the_recorded_result_is_a_conflict`
  in `domains/bare_metal/storefront/tests/test_http_settlement.py`, or add a sibling
  sharing its setup: with the site reporting another delivery, the buyer's lifecycle
  `end` terminates the lease (`terminate_lease` called on the provisioning double
  for the reservation), and the status, result and access reads still answer 409
  `delivery_conflict` with the recorded result unchanged. Application integration
  through the storefront's typed clients.
- [ ] 10.2 Delete `BareMetalFulfillmentService.converge_teardown` from
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`;
  confirm nothing calls it (`git grep -n converge_teardown`, which should then name
  only the provisioning service's `converge_teardowns`).
- [ ] 10.3 Bump the bare-metal storefront package unless section 9 already bumped it
  in this change; refresh the locks if bumped here.
- [ ] 10.4 Verification: `uv run pytest domains/bare_metal/storefront/tests` passes,
  and `scripts/change-workflow run pre-commit resolve-delivery-correctness-gaps`
  passes. End-to-end: `e2e_bare_metal_payment_deal` and `e2e_bare_metal_deal` end
  their deals through the buyer's teardown with no conflict, the unchanged path; no
  lane plants a conflicting delivery, and none is owed.

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
    whose read failed, again at each publication cycle until one succeeds; an unread
    registry is reported in each affected mechanism's public details as
    `dispute_authorities_unread`, not as a blocker (D6).
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
| D9 — Item 3 is a scenario, a test, and a deletion | `openspec/specs/storefront-publication/spec.md` ("A bare-metal delivery that conflicts with its recorded result is refused") |
| D10 — One round of three sessions | No permanent destination: the implementation cadence is this change's plan |
| Roadmap currency (11.5) | `docs/development/ROADMAP.md`, Goal 1 |
| Campaign index currency (11.6) | `openspec/changes/README.md`, this change's row and Goal 1's graph |
