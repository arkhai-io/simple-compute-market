## Why

The VM e2e scenario suite (`e2e-tests/tests/e2e/roles/scenarios/vms/`) predates
POOLS-7's storefront fulfillment cutover in several places and still asserts on
the legacy direct-executor-dispatch path's vocabulary (`provisioning_job_id`,
raw Ansible job polling) where the durable fulfillment path
(`capacity_reservation_id` → `schedule_resource` → `begin_fulfillment` →
`fulfillment_id`) has replaced it. `pools-7-storefront-fulfillment-cutover`
task 10.14 already did detailed static analysis of the teardown-phase
staleness (stages 10-11) and deferred fixing it to "the final POOLS-7 review
loop." That analysis is not repeated here; this change consumes it directly
for Section 2.

Separately, `domains/vms/storefront/tests/cross_service/test_capacity_fulfillment_boundary.py`
solves a real dependency-loop problem (proving `RemoteCapacityClient` against
a real `compute-provisioning-service` ASGI app without either production
package depending on the other) with a bespoke test tier -- a special
directory, a dedicated make target, and a PYTHONPATH trick to run a
storefront-owned test file inside the provisioning service's environment.
This doesn't match the repository's unit/integration/e2e pattern anywhere
else, and its purpose splits cleanly into two pieces that each fit an
existing tier.

## What This Change Covers

### Section 1 (implemented, 2026-07-29): provisioning-phase `fulfillment_id` fix

Independent of, and upstream of, POOLS-7 task 10.14's teardown scope: the VM
e2e scenarios' *provisioning* phase (not just teardown) asserted on
`provisioning_job_id`, which is permanently `None` for a fulfillment on the
durable path (`core_storefront.models.settle_models.SettleStatusResponse`'s
own docstring says so). This wasn't previously tracked anywhere.

Fixed in `test_full_deal.py`, `test_full_deal_buyer_cli.py`, and
`test_non_erc20_settlement.py`:

- Stage 08b (or its equivalent) now captures `fulfillment_id` from
  settle-status instead of the always-empty `provisioning_job_id`, and
  confirms dispatch via `get_fulfillment_status(fulfillment_id)` reporting
  `dispatching`, rather than polling a raw Ansible job by id it no longer has.
- Stage 09a (provisioning completion) redesigned: the durable path doesn't
  expose a raw job id to `wait_for_job(<id>)` the legacy way. Deterministic
  convergence now uses `resume_rule` (already rule-id-based, unaffected) →
  `drain()` (waits for every outstanding test job to reach a terminal state,
  without needing a specific job id -- equivalent in this single-deal,
  single-job scenario) → `run_fulfillment_convergence_cycle()` (already-existing
  test control, advances the durable fulfillment record the same way the
  production convergence watchdog would) → `get_fulfillment_status` asserting
  `active`.
- Stage 09c (lease registration) confirms placement through the admin-only
  `DealLease` view instead of expecting resource identity pre-populated from
  a buyer-facing stage event -- the buyer-facing reservation response is
  intentionally opaque (`openspec/specs/site-capacity/spec.md`), and stage
  08b's resource-id assertion against that opaque source was already broken
  independent of this change (confirmed: `resource_id` has been stripped from
  the reservation response since before this change existed). The admin lease
  view is a legitimate, separate introspection channel, not a way around that
  opacity guarantee -- see that stage's docstring. As implemented, the lease
  reports the executor (`host_id`) and a null `resource_id`, so 09c asserts
  placement against the host the deal was admitted on and assigns
  `reserved_resource_id` from the scenario's own declared resource (the
  domain driver's constant in the shared stage, the module's constant in the
  buyer CLI scenario); the identifier is never read from the lease or the
  buyer-facing path.
- `DealState.provisioning_job_id`/`reserved_resource_id` fields reworked:
  `fulfillment_id` (already existed, previously teardown-only) is now the
  identity captured at settlement for stages 08b–09c; the teardown stages
  read the fulfillment identity from the lease at 10b (the shared stages
  keep it as a separate `teardown_fulfillment_id`) and never assert it equal
  to the settlement capture; `reserved_resource_id` is populated at 09c, not
  treated as available earlier.

No `compute-provisioning-service` or `kit/fulfillment` changes were needed --
`get_fulfillment_status`, `run_fulfillment_convergence_cycle`, and `drain`
already existed as test/production client methods.

### Section 2 (finding: already implemented, 2026-07-29): teardown-phase rewrite

Expected to consume `pools-7-storefront-fulfillment-cutover` task 10.14's
static analysis and implement its proposed five-stage sequence. On
inspection, `test_full_deal.py`/`test_full_deal_buyer_cli.py` stages 10a-11b
already implement that exact sequence -- word-for-word identical between the
two files. The real gap was upstream: stage 08b's `provisioning_job_id`
assertion failed outright on the durable path, so every stage after it,
teardown included, never ran -- masking that the teardown rewrite already
existed. Section 1's fix is what makes these already-correct stages
reachable. `pools-7` task 10.14's stale "deferred" status corrected to match.
See `design.md`'s Section 2 for the full trace.

### Section 3 (implemented, 2026-07-29): inter-service test split

- **E2E half:** no new scenario needed. `test_full_deal.py` already exercises
  the real `reserve`/`commit`/`schedule_resource`/`begin_fulfillment` path
  against two real, running services -- exactly what the e2e suite's stated
  scope is for, and Section 1 just hardened its assertions around this same
  boundary. A second dedicated scenario would duplicate that coverage.
- **Fast half:** `core/storefront/tests/integration/test_capacity_and_fulfillment_client_opacity.py`,
  driving `RemoteCapacityClient` and `ComputeProvisioningClient` against a
  shared `httpx.MockTransport` -- both classes already declared a `transport`
  test seam for exactly this. Zero cross-package dependency, uses the same
  shared typed contract models (`compute_provisioning.contracts`) a real
  server validates against. Verified it catches a real regression
  (temporarily reintroduced a placement field, confirmed the test failed,
  reverted).
- Retired `domains/vms/storefront/tests/cross_service/` (test file and its
  now-dead PYTHONPATH-trick `conftest.py`) and the `test-vm-capacity-boundary`
  make target entirely, in the same pass -- no staging needed once the e2e
  half turned out to require no new coverage to wait on.

### Section 4 (implemented, 2026-07-29): light review pass

Both `test_multi_registry.py` and `test_buy_oneshot_buyer_cli.py` read in
full: no legacy vocabulary, no dependency on how Sections 1-3 changed the
other scenario files' use of `DealState`. No changes needed.

## Non-Goals

- Redesigning negotiation-driven capacity resize's e2e coverage
  (`negotiation-driven-capacity-resize` Section 2+ isn't built yet; nothing
  to cover here).
- Building the CI matrix out for `kit/fulfillment`/`kit/resource-pools`/the
  VM adapter (separate, parked decision -- see `fix-vm-fulfillment-capacity-boundary`'s
  audit).
- Any change to production `compute-provisioning-service`/`kit/fulfillment`
  code. Section 1 needed none; if Section 2 or 3 finds it needs one, that's
  new evidence to open here, not assumed up front.

## Permanent documentation impact

- [x] No permanent documentation change. Section 1 is test-suite maintenance
      matching already-shipped production behavior; Section 2 found the
      teardown stages already implemented; Section 3 relocated a test tier and
      added a mock-transport test, with its rationale in that test's own module
      docstring; Section 4 changed nothing. Every destination is an existing
      permanent heading or an in-code docstring; see the design-promotion
      record in `design.md`.

### Knowledge to promote

- `fulfillment_id`, not `provisioning_job_id`, is the identity a scenario
  captures at settlement and reuses through teardown — already stated by
  `docs/development/ARCHITECTURE.md#identifiers` and
  `core_storefront.models.settle_models.SettleStatusResponse`'s docstring.
- Draining the mock executor and advancing fulfillment convergence are two
  separately driven facts — the shared stage 09a docstring in
  `e2e-tests/tests/e2e/roles/helpers/compute_deal_stages.py`.
- Placement is confirmed through admin introspection at stage 09c, never
  inferred from the buyer-facing path; the scenario's resource identifier is
  its own declared value, assigned there — the shared stage 09c docstring and
  `openspec/specs/site-capacity/spec.md`'s "Capacity accounting is private to
  the site authority".
- A client's `transport` seam is how a boundary-opacity proof is written —
  `docs/development/TESTING.md#2-integration-tests` and the module docstrings
  of the two opacity tests.

## Dependencies and Related Changes

- Section 2 consumes `pools-7-storefront-fulfillment-cutover` task 10.14's
  analysis directly; does not redo it.
- Related to `fix-vm-fulfillment-capacity-boundary`'s audit (2026-07-29),
  which first surfaced the CI-matrix and cross-service-test-layer questions
  this change's Section 3 resolves for the latter.
