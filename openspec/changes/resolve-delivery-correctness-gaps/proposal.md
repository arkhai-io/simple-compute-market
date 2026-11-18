# Resolve the correctness gaps left in compute delivery

## Why

Goal 1 of `docs/development/ROADMAP.md` has no active change left: every change in
its campaign is archived, and its open gaps are all unowned. Five of them are
correctness gaps in how a compute delivery is leased, dispatched, offered, or
torn down. None is large. Separate changes would each cost a design, reviews,
validation, and a closeout that a fix this size doesn't repay, so this change takes
all five. Design found two of them misread and one with a half the gap did not
name; each is stated here as it is.

### 1. A declaration's relay port and the relay its host dials

The roadmap's gap says a declaration in a relay-backed pool, naming a host placed
under another relay or none, can be leased a port its host's tunnel client never
dials. That does not happen. A relayed VM create
(`domains/vms/provisioning/adapter/.../vm_fulfillment_plan.py`) and a bare-metal
grant (`domains/bare_metal/provisioning/adapter/.../bare_metal_fulfillment_plan.py`)
lease their port on the relay of the declaration's pool, and the job that adds the
proxy first points the host's one buyer-facing client at that relay
(`relay-proxy`'s `add.yml` includes `relay-client`, whose baseline synchronization
writes the job's relay address, port and token). A host has at most one capacity
declaration, so all its deliveries are leased on one relay. Nothing tests either
fact, so a later change could create the defect unnoticed.
`bring-host-inventory-under-definition-documents` left the question open; this
change answers it.

### 2. A concurrent retry and a false full relay window

`RelayPortAllocator.allocate_in_session`
(`provisioning/compute/src/compute_provisioning/relays/allocator.py`) looks for the
owner's active lease before it locks the relay, then claims the lowest free port and
moves to the next on any `IntegrityError`, including the one the active-owner index
`uq_relay_port_leases_active_owner` raises. A claim for an owner whose lease was
committed meanwhile would run through the window to a false
`RelayWindowExhaustedError`. Today's callers cannot reach it: acceptance locks the
settlement row before preparing, so a concurrent retry of one reservation reaches
the allocator after the first lease committed. The reachable sibling is in
acceptance itself: `FulfillmentTransaction.accept` reads the row unlocked, and the
locked select in `accept_fulfillment` returns that same in-memory object
unrefreshed, so a retry that waited on the lock accepts again under a new
fulfillment ID. Neither can happen in the shipped single-process SQLite
deployment; both can wherever acceptances overlap, as on PostgreSQL.

### 3. Bare-metal teardown under a delivery conflict is unguarded

`resolve-compute-family-findings` (its D12) made a bare-metal status, result, or
access read answer a typed 409 `delivery_conflict` when the site reports a
delivery other than the recorded result. That is `storefront-publication`'s "A
bare-metal delivery that conflicts with its recorded result is refused". Its
closeout found that the buyer's teardown read status first, so under a conflict the
teardown answered that 409 instead of ending the lease.

The Goal 8 lifecycle change (#314) removed that route. A buyer now ends a deal
through the shared lifecycle `end`, which reaches `apply_end` and terminates the
lease without the status read, so a conflict no longer blocks an end. Two things
are left:

- No test shows that an end goes through while a delivery conflict stands, and no
  requirement says it must.
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
cycle until an operator force-releases it. That rule is right for a teardown whose
playbook ran and failed: what it did to the host is unknown. It is wrong for a
teardown that failed before any playbook ran — refused by the engine (no host, an
unregistered host, an unsupported action) or by the executor while preparing it
(its codec, its inventory, an undecryptable host key, a version-1 `ssh`
connection) — where a fresh run would do exactly what the first should have. Every
teardown dispatched to a host stored at `ssh` connection version 1 failed that way
before the upgrade from `marketplace-v0.3.0` repaired those hosts, and the operator
handbook's "Upgrading a deployment" asks an operator to remove the workload by hand
and force-release instead.

The lease has a half of this too. The release status reports `teardown_failed` as
failed, so the lease goes to `release_failed` at once and waits for an operator's
retry-release, and the lease's stalled-teardown timeout marks `release_failed` any
teardown still in progress after 300 seconds — which a teardown job's own retries
exceed, so a teardown that succeeds on a retry strands its lease for an operator.

## What Changes

- **A relayed delivery's relay is stated and guarded** (design D1).
  `physical-provisioning` states that a relayed delivery is leased on its
  declaration's pool's relay and that the proxy-adding job points the host's client
  at it; a static test of the family roles and a compute-provisioning integration
  test, with a host placed under another relay and an unplaced host, hold it. No
  placement rule; the relay rules are unchanged.
- **Concurrent retries return the first acceptance and the owner's lease** (D2).
  The allocator reads the owner's lease after the relay lock and again on any
  uniqueness conflict, so `RelayWindowExhaustedError` means the window is full;
  acceptance judges the row its lock returns, so an equivalent retry receives the
  first fulfillment. Both are proven by deterministic tests on SQLite.
- **A bare-metal end under a delivery conflict is stated and guarded** (D9). A
  `storefront-publication` scenario, a storefront integration test, and
  `converge_teardown` deleted.
- **A storefront reads again a registry it could not read** (D6). Each publication
  cycle re-reads the registries whose last read failed; while one is unread, the
  storefront's settlement readiness reports `dispute_authorities_unread`. No
  restart, and `/health` is unaffected.
- **A teardown that never started runs again without an operator** (D3, D4, D5,
  D7, D8). An executor records that a job's execution is starting before it starts
  anything (`execution_started_at`, shown on the job read). A failed teardown whose
  execution never started is run again under `"{reservation}:teardown:rerun-{n}"`,
  spaced by the job retry policy and bounded by `teardown_rerun_limit` (default 3),
  compensating teardowns included. The lease stays `releasing` while a rerun is
  pending, and the stalled-teardown timeout becomes a counted diagnostic, so
  `release_failed` means only that an operator must act. A teardown whose playbook
  started, or a cancelled one, keeps today's rule. The operator handbook's manual
  steps for leases left `release_failed` on a version-1 host become one
  retry-release per lease.

### Decided by the owner before design

- **One change.** These five correctness gaps are resolved together. Goal 1's
  other gaps are grouped by theme into their own changes and are not this change's
  scope.
- **Item 3 is a regression test and a deletion.** The defect is fixed; this change
  adds what guards it and deletes `converge_teardown`.

Design's decisions are `design.md` D1–D10.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: a relayed delivery's relay (D1); a concurrent
  allocation for one owner (D2); a job's recorded start (D4); rerunning a teardown
  that never started (D5, D7); the lease's release while a rerun is pending, and the
  grace period as a diagnostic (D3, D8).
- `fulfillment`: an equivalent acceptance that waited on another returns the first
  (D2).
- `compute-provisioning-contract`: the job view's `execution_started_at` (D4).
- `settlement-configuration`: reading a registry again after a failed read, and
  the `dispute_authorities_unread` blocker (D6).
- `storefront-publication`: a bare-metal end under a delivery conflict (D9).

### New Capabilities

None.

## Non-Goals

- Goal 1's other gaps, each owned by a themed change: host and guest trust
  (`harden-provisioning-trust-boundaries`), failure reporting
  (`report-provisioning-failures-to-operators`, which owns the operator events for a
  spent rerun bound and a lease held `releasing`), qualification and coverage
  (`complete-real-provisioning-qualification`), and shared relays at scale
  (`harden-shared-relays`).
- A placement rule for capacity declarations, or any change to which relay a
  delivery is leased on (D1).
- A PostgreSQL test lane (design, Open Questions).
- Reading registry recommendations again after a successful read (D6).
- Rerunning a teardown whose playbook started, or a cancelled one. It stays an
  operator's to verify and force-release.
- Moving an existing delivery between relays. A delivery's relay is fixed for its
  lease's life (`physical-provisioning`'s "A relay binding is fixed for a lease's
  life").

## Impact

- `provisioning/compute/src/compute_provisioning/relays/allocator.py` and its
  integration tests; a compute-provisioning integration test of a declaration
  outside its host's pool; a static test of the `relay-proxy` and `relay-client`
  roles.
- `kit/fulfillment/src/market_fulfillment/settlement_repository.py`
  (`accept_fulfillment`) and its tests.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/fulfillment_service.py`
  (`converge_teardown` deleted) and `domains/bare_metal/storefront/tests/test_http_settlement.py`.
- `kit/storefront/src/market_storefront_kit/dispute_configuration.py`, the three
  storefronts' publication cycles and settlement readiness.
- The job engine (`provisioning/compute/src/compute_provisioning/jobs/engine.py`,
  `jobs/executor.py`, `jobs/db.py`, `jobs/migrations.py`), the Ansible executor
  (`provisioning/compute/ansible/src/compute_provisioning_ansible/executor.py`),
  `job_fulfillment.py`, `release.py`, `lease_lifecycle.py`, the compute provisioning
  settings (`teardown_rerun_limit`), and the contracts package's job view.
- `docs/operator-handbook.md` ("Upgrading a deployment").
- One additive compute-provisioning migration (`execution_started_at`). No wire
  form, stored record or configuration key `marketplace-v0.3.0` carries changes
  meaning.

## Dependencies and Related Changes

- None.
- `report-provisioning-failures-to-operators` raises its events from the rerun
  predicate's `spent` outcome and from the lease lifecycle's count of leases
  `releasing` past the grace, both of which this change provides.
- `capacity-reservation-lifecycle-hardening` does not restate the teardown job
  rule; nothing to reconcile.
- `inject-site-pool-authority` is unaffected: D1 adds no site read of pool state.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, `fulfillment`,
  `compute-provisioning-contract`, `settlement-configuration`, and
  `storefront-publication`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `physical-provisioning`'s specification (a relayed delivery's relay is its
  declaration's pool's) and architecture companion (why the host's one client
  follows the lease's relay, and why the management-route rule, the host
  pool-change hook and the drain keep reading placement); `ROADMAP.md`'s Goal 1 gap
  closed.
- D2: `physical-provisioning`'s specification (concurrent allocation for one owner)
  and `fulfillment`'s specification (an equivalent acceptance that waited on
  another).
- D3: `physical-provisioning`'s specification ("An undelivered lease is released by
  what its fulfillment proves") and architecture companion ("Proof-driven
  release"); `ARCHITECTURE.md`, "Release"; `docs/operator-handbook.md`, "Upgrading a
  deployment".
- D4: `physical-provisioning`'s specification (a job's recorded start) and
  `compute-provisioning-contract`'s specification (the job view's
  `execution_started_at`).
- D5: `physical-provisioning`'s specification (rerunning a teardown that never
  started), its architecture companion ("Proof-driven release"), and its
  `configuration.md` (`teardown_rerun_limit`).
- D6: `settlement-configuration`'s specification and `configuration.md` (when a
  storefront reads its registries' recommendations, and the readiness blocker).
- D7: `physical-provisioning`'s specification, in the rerun requirement's
  compensating-teardown scenario.
- D8: `physical-provisioning`'s specification and architecture companion, and
  `ARCHITECTURE.md`, "Release", where the rule that a fulfillment's teardown is one
  job is restated.
- D9: `storefront-publication`'s specification (a bare-metal end under a delivery
  conflict).
- D10: no permanent destination — the implementation cadence is this change's
  plan, not the system's.
