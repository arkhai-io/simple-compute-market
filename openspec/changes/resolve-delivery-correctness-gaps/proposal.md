# Resolve the correctness gaps left in compute delivery

## Why

Goal 1 of `docs/development/ROADMAP.md` has no active change left: every change in
its campaign is archived, and its open gaps are all unowned. Five of them are
correctness gaps in how a compute delivery is leased, dispatched, offered, or
torn down. Four are defects that give a wrong answer or strand work that should
finish. The fifth, a bare-metal teardown under a delivery conflict, has since been
fixed in passing, but no test guards the fix and it left dead code behind. None
is large. Separate changes would each cost a design,
reviews, validation, and a closeout that a fix this size doesn't repay, so this
change takes all five.

### 1. A declaration's relay port can sit on a relay its host does not dial

A capacity declaration need not sit in its host's pool. A relayed VM create
(`domains/vms/provisioning/adapter/.../vm_fulfillment_plan.py`) and a bare-metal
grant (`domains/bare_metal/provisioning/adapter/.../bare_metal_fulfillment_plan.py`)
both lease their remote port on the relay of the *declaration's* pool. The relay
pool-change hook (`provisioning/compute/src/compute_provisioning/relays/rebinding.py`)
keeps a host's relay uniform by the *host's* pool. So a declaration in a
relay-backed pool, naming a host placed under another relay or under none, can be
leased a port the host's tunnel client never dials. The buyer is handed a
connection string that leads nowhere. No lane runs a declaration in a pool other
than its host's, so this has never been shown end to end.
`bring-host-inventory-under-definition-documents` left the question open
("Open Questions"), waiting for `prove-relay-provisioning` and
`admit-relay-proxies-by-grant`. Both have landed without settling it.

### 2. A concurrent dispatch retry can fail as a full relay window

`RelayPortAllocator.allocate_in_session`
(`provisioning/compute/src/compute_provisioning/relays/allocator.py`) first looks
for the owner's active lease. If it finds none, it claims the lowest free port in a
savepoint and retries the next port on any `IntegrityError`. Two constraints can
raise that error: the port's uniqueness on its relay, which the retry is for, and
the partial unique index on one active lease per owner,
`uq_relay_port_leases_active_owner`. If a concurrent retry of the same fulfillment
commits its lease first, every later claim hits the owner index. The loop then
runs through the window and raises `RelayWindowExhaustedError`. The fulfillment
fails with a false "every port is leased" when its lease already exists. This can
happen only where claims really run concurrently, as on PostgreSQL. On SQLite the
caller holds the database's one writer slot.

### 3. Bare-metal teardown under a delivery conflict is unguarded

`resolve-compute-family-findings` (its D12) made a bare-metal status, result, or
access read answer a typed 409 `delivery_conflict` when the site reports a
delivery other than the recorded result. That is `storefront-publication`'s "A
bare-metal delivery that conflicts with its recorded result is refused". Its
closeout found that the buyer's teardown read status first: `POST
/api/v1/fulfillments/{negotiation_id}/teardown` called
`BareMetalFulfillmentService.status()`, so under a conflict the teardown answered
that 409 instead of ending the lease.

The Goal 8 lifecycle change (#314) removed that route. A buyer now ends a deal
through the shared lifecycle `end`: the `end_delivery` message drives
`apply_end`, which reads the fulfillment's row from the storefront's database and
terminates the lease, and the buyer's follow-up read is the lifecycle's
`delivery_read`. Neither reaches `status()`, so a conflict no longer blocks an
end. Two things are left:

- No test shows that an end goes through while a delivery conflict stands, so a
  later change routing the end through the status read would bring the defect
  back unnoticed.
- `BareMetalFulfillmentService.converge_teardown`, which only wrapped the status
  read for the removed route, is dead: nothing calls it, not even a test.

### 4. A storefront that starts before its registry never offers payments

Each storefront reads its registry's recommended dispute authorities once, at
startup: `settlement_composition.disputes.refresh(...)` in the VM, bare-metal, and
API-credit storefronts' server startup, through
`kit/storefront/src/market_storefront_kit/dispute_configuration.py`. A failed read
contributes no recommendations. A storefront that starts before its registry
serves therefore holds no authority, offers no payments option, and refuses a
payments listing with "no settlement option it may publish" until someone
restarts it. Nothing reports why, beyond a warning at startup.

### 5. A teardown that failed before its executor ran is recovered by hand

A fulfillment's teardown is one job: `job_contract`
(`provisioning/compute/src/compute_provisioning/job_fulfillment.py`) keys it on
`"{reservation}:teardown"`, for every domain. When convergence requeues a
`teardown_failed` row, the resubmission matches that key and the job engine
returns the same failed job, so the row goes back to `teardown_failed` on every
cycle until an operator force-releases it (`physical-provisioning`'s architecture
companion, "Proof-driven release"). That rule is right for a teardown whose executor ran and failed: what it
did to the host is unknown, and an operator must check. It's wrong for a teardown
that failed before any playbook ran. There, nothing touched the host, and a fresh
run would do exactly what the first should have done. Every teardown dispatched to
a host stored at `ssh` connection version 1 failed that way before the upgrade
repaired those hosts, and the operator handbook's "Upgrading a deployment" asks an
operator to remove the workload by hand and force-release instead. The same holds
for any job the engine refuses before running it (no host, an unregistered host,
an unsupported action) and any the executor refuses while preparing it (its codec,
its inventory, or a host key that can't be decrypted).

Such a job is already told apart by what it leaves. The Ansible executor reports a
job's cancellation handle, `execution_handle`, only once `start_playbook` has
returned, and a job retry does not clear it. A failed job with no handle is one
where no attempt ever started a playbook. So this needs nothing from the real
runner's structured failure evidence, which is about classifying failures after a
playbook ran.

## What Changes

- **A relay port is leased on the relay the host dials.** Whichever rule design
  picks (see below), a relayed delivery never leases a port on a relay other than
  the one its host's tunnel client dials. Either a declaration that would cause
  that is refused when it's written, or the lease follows the host. A lane or
  integration test runs a declaration in a pool other than its host's.
- **A concurrent retry of one owner's allocation gets that owner's lease, or a
  named conflict, never exhaustion.** An `IntegrityError` from the active-owner
  index is told apart from a port conflict. `RelayWindowExhaustedError` is raised
  only when the window is really full. A concurrency test on PostgreSQL shows the
  race.
- **A test guards a bare-metal end under a delivery conflict.** It shows a
  buyer's end terminating the lease while the site reports a delivery other than
  the recorded result, and the status, result, and access reads still answering
  409 with the recorded result unchanged. `BareMetalFulfillmentService.converge_teardown`
  is deleted.
- **A storefront picks up its registry's recommendations once the registry
  answers.** Either the recommendations are read again when a refresh found the
  registry unreachable, or the storefront isn't ready until it has read them.
  Either way, no restart is needed.
- **A teardown that never reached its executor runs again without an operator.**
  A failed teardown job that never started a playbook is told apart from one that
  did, and the first kind is run again under a new job identity, within a bound,
  so a cause that persists doesn't create a job every cycle. A
  teardown whose executor ran keeps today's rule: it stays failed, and its capacity
  is held, until an operator verifies the host and force-releases it. The operator
  handbook's manual steps for leases left `release_failed` on a version-1 host
  shrink to what the automatic rerun doesn't cover.

### Decided by the owner

- **D1: one change.** These five correctness gaps are resolved together. Goal 1's
  other gaps are grouped by theme into their own changes and are not this
  change's scope.
- **D2: item 3 is a regression test and a deletion.** The defect is fixed; this
  change adds the test that guards it and deletes `converge_teardown`.

### Open for design, not decided here

- **The relay rule (item 1).** The options:
  - Require a declaration naming a host to sit in a pool whose relay is the host's
    pool's relay, or in the host's own pool. This is checked at the declaration's
    write and at a host's pool change, and in the definition documents.
  - Lease the port on the host's relay rather than the declaration's pool's.
  - Make a host's pool authoritative for its declarations.

  Design also covers what happens to a declaration already standing that breaks the
  chosen rule, and whether a host placed in no pool may back a declaration in a
  relay-backed pool.
- **The retry's answer (item 2).** Whether an owner-index conflict re-reads and
  returns the owner's lease, as allocation's idempotence suggests, or refuses as a
  named conflict that the dispatch retry handles. Also how the two constraint
  violations are told apart portably across SQLite and PostgreSQL.
- **Re-read or refuse readiness (item 4).** Re-reading lets a storefront that came
  up early sell without a restart. Refusing readiness makes the cause visible to the
  deployment and its orchestrator. Design picks one, or both. It also decides how
  often a re-read runs, and whether a registry later dropping a recommendation
  changes what is already published.
- **The rerun (item 5).** Whether the missing `execution_handle` is the signal
  as it stands, or the engine records "never started" explicitly. Whether the
  signal holds for every executor, the mock runner included, and for a
  `start_playbook` that starts a process and then raises before the handle is
  reported. The rerun's bound or backoff, and what an operator sees once it's
  spent. The new job's identity, how the fulfillment's teardown metadata and the
  reservation's `release_job_id` follow it, and how `physical-provisioning`'s
  rule that one fulfillment's teardown is one job is restated. Whether a failed
  compensating teardown after a failed create reruns the same way.
- **Whether a gap should leave the change.** If design finds one of the five
  needs a design of its own, it can split it back out to the roadmap as unowned.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `physical-provisioning`: the relay a delivery's port is leased on (item 1), the
  allocation retry (item 2), and rerunning a teardown that never reached its
  executor (item 5).
- `site-capacity` or `resource-pool-management`: where a declaration naming a host
  may sit, if design picks a placement rule (item 1).
- `storefront-publication`: a scenario for a bare-metal end under a delivery
  conflict (item 3), if design judges the requirement should state it.
- `settlement-configuration`: when a storefront reads its registry's recommended
  dispute authorities (item 4).
- `fulfillment`: a teardown's job identity, if item 5 changes it.

### New Capabilities

None.

## Non-Goals

- Goal 1's other gaps, each owned by a themed change: host and guest trust
  (`harden-provisioning-trust-boundaries`), failure reporting
  (`report-provisioning-failures-to-operators`), qualification and coverage
  (`complete-real-provisioning-qualification`), and shared relays at scale
  (`harden-shared-relays`).
- Rerunning a teardown whose executor ran. It stays an operator's to verify and
  force-release.
- Moving an existing delivery between relays. A delivery's relay is fixed for its
  lease's life (`physical-provisioning`'s "A relay binding is fixed for a lease's
  life").

## Impact

- `provisioning/compute/src/compute_provisioning/relays/allocator.py` and
  `relays/rebinding.py`, with their integration tests.
- `domains/vms/provisioning/adapter/.../vm_fulfillment_plan.py` and
  `domains/bare_metal/provisioning/adapter/.../bare_metal_fulfillment_plan.py`.
- Capacity declaration writes and the definition documents' reconciliation in
  `provisioning/compute/service`, if a placement rule is chosen.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`
  (`converge_teardown` deleted) and a bare-metal storefront test of an end under a
  delivery conflict.
- `kit/storefront/src/market_storefront_kit/dispute_configuration.py` and the three
  storefronts' startup and readiness.
- Teardown dispatch and fulfillment convergence in
  `provisioning/compute/service/.../fulfillment_convergence.py`,
  `provisioning/compute/src/compute_provisioning/job_fulfillment.py`, and the job
  engine in `provisioning/compute/src/compute_provisioning/jobs/engine.py`.
- An end-to-end lane stage or integration test for a declaration outside its
  host's pool, and a PostgreSQL concurrency test for the allocation race.
- `docs/operator-handbook.md` ("Upgrading a deployment").

## Dependencies and Related Changes

- None.
- `capacity-reservation-lifecycle-hardening` also touches reservation release.
  Design checks that the two don't both restate the teardown job rule.
- `inject-site-pool-authority` is changing how the site reaches pools. Design checks
  whether a placement rule for item 1 belongs behind that port.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`,
  `storefront-publication`, `settlement-configuration`, and, as design settles,
  `site-capacity`, `resource-pool-management`, and `fulfillment`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations:
- `physical-provisioning`'s specification and architecture companion, for the relay
  rule, the allocation retry, and the teardown rerun ("Proof-driven release").
- `storefront-publication`, for an end under a conflict, if a scenario is added.
- `settlement-configuration`, for when recommendations are read.
- `docs/operator-handbook.md` and `docs/development/ROADMAP.md`'s Goal 1 current
  state.
