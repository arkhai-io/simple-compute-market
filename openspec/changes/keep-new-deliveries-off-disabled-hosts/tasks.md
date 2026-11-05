# Tasks

The rule every section applies, from `design.md` D3/D12: where a declaration's
pool is backed and the pool's provider needs a host, the declaration has a usable
host only when it names a host that is registered and enabled; a declaration
without one is neither admitted, placed, nor projected enabled. The rule does not
apply in an unbacked pool, nor where the provider needs no host.

## 1. The usable-host rule and the deliverable-host seam

Delivers the one statement of the rule and the seam every layer reads it
through (D6, D7; site-capacity "Admission applies the pool provider's host
requirement", fulfillment "A provider declares whether its delivery needs a
host"). Touches `kit/resource-pools` only.

- [x] 1.1 In `kit/resource-pools/src/market_resource_pools/host_requirement.py`,
  beside `HostRequirement` and `pool_needs_host`, add the `DeliverableHosts`
  protocol (`deliverable_host_ids(db: Session) -> frozenset[str]`, the registered,
  enabled hosts read in the caller's session) and
  `declaration_has_usable_host(host_id, provider, backed, host_requirement,
  deliverable) -> bool`, exactly as D6 shows. The function answers true when no
  requirement is supplied, when `backed` is false, or when `pool_needs_host`
  says the provider needs none; otherwise it needs a non-empty `host_id`, and,
  when `deliverable` is supplied, that `host_id` in it; with `deliverable` absent
  any named host is usable (D7). Export both from
  `market_resource_pools/__init__.py`, and extend the module docstring with the
  rule and its link to `openspec/specs/site-capacity/spec.md#requirement-admission-applies-the-pool-providers-host-requirement`.
  Verify with 1.2.
  *Done:* as D6 shows; `sqlalchemy.orm.Session` is imported at module level
  (the package already depends on SQLAlchemy). An empty-string `host_id` is
  treated as naming no host, as the existing no-host checks treat it. The
  docstrings claim only that the report is read in the caller's transaction,
  not that no disable can commit meanwhile: that is a property of the caller's
  transaction (one SQLite database), not of the protocol. *Beyond the plan:*
  two new public names take a minor bump under `RELEASING.md`'s versioning
  policy, so `arkhai-kit-resource-pools` is 0.9.0 and every lock was refreshed
  (`make dist`, `make lock`); sections 2 and 3 raise `kit/site`'s and
  `kit/fulfillment`'s lower bounds on it to `>=0.9.0` when they import the
  names.
- [x] 1.2 Unit (`kit/resource-pools/tests/unit/test_host_requirement.py`): one
  case per row of D3/D12's table — registered and enabled, disabled (absent from
  the set), unregistered (absent from the set), no host — plus an unbacked pool,
  a provider needing no host, a provider the requirement does not name, no
  requirement supplied, and a requirement with no deliverable set (D7).
  *Done:* every case listed, plus an empty report (no host usable). The
  disabled and unregistered cases are one case to this function — an id absent
  from the report; that the host authority leaves both out of its report is
  section 4's evidence (4.1).
- [x] 1.3 Verification: the unit suite of `kit/resource-pools` passes
  (`uv run pytest kit/resource-pools/tests/unit`). No end-to-end scenario
  exercises this section on its own; section 5's do.
  *Done:* run from `kit/resource-pools` (the root environment has no pytest):
  unit, `uv run pytest tests/unit` — 54 passed; the whole suite (unit and
  library integration) — 141 passed. `make check-packaging` passed (locks,
  layers, scope, kinds); `make test` passed; `make check-change` passed.
  End-to-end: none on its own, confirmed — nothing deployed calls the rule
  until sections 2–4 wire it in; then `e2e_bare_metal_publication` and
  `e2e_bare_metal_introduction` (section 5) exercise it. Nothing is owed by
  validation.
  *Handoff:* `make test` reinstalls internal packages from `.dist` but does
  not build them, so run `make dist` after changing a kit and before
  `make test`, or consumers test the previous wheel.

## 2. The site ledger: admission, the rebind recheck, and the offered read

Delivers admission and rebind refusal of a declaration with no usable host, and
the one ledger read stating each declaration's offered `enabled` that the
capacity-bucket projection and the snapshot are built from (D2, D3/D12, D5, D7,
D8, D9, 11 F2; site-capacity "Admission applies the pool provider's host
requirement", "Projected inventory is internally consistent", "The resource-pool
projection is built from capacity declarations and offers only a usable host",
"Every capacity surface offers only a declaration with a usable host"). Touches
`kit/site` only.

- [x] 2.1 `CapacityLedgerService.__init__` (`kit/site/src/market_site/ledger.py`)
  accepts `deliverable_hosts: DeliverableHosts | None = None` beside
  `host_requirement`, documented in its docstring as D2 and D7 state.
  `_find_candidate` (probe, reserve, resize) reads the deliverable set once per
  call in its session and replaces its no-host check with
  `declaration_has_usable_host`, cached per pool as the provider decision is
  today; a candidate is treated as backed, since it has passed the
  deliverable-mode check an unbacked pool never passes (D8). An ineligible
  candidate does not match, so the claim falls through or receives the ordinary
  no-capacity answer. Rewrite the comment at the existing check to state the
  generalised invariant. Verify with 2.4.
  *Done:* the per-pool cache now holds the pool's provider (the rule needs
  the host too, so caching the pool's bool would restate the rule beside the
  function). `_pool_needs_host` is replaced by `_pool_provider` and
  `_deliverable_host_ids`, shared by 2.1–2.3; admission and the rebind read
  only the provider, never the backing (D8).
- [x] 2.2 `assign_settlement_resource_in_session` applies the same rule to its
  destination, read in the caller's session, refusing with
  `CapacityConflictError` as its host-requirement check does (D8). Verify with
  2.4.
  *Done:* the message names why — "names no host", or "names host X, which is
  not taking new delivery"; it is internal to scheduling's transaction and
  never reaches a storefront.
- [x] 2.3 Add the offered read (11 F2): one method, `list_offered_resources()`,
  returning `list_resources()`'s payload for every declaration with `enabled`
  replaced by its offered state — the declaration's own `enabled` and
  `declaration_has_usable_host`, judged with the pool's provider, the pool's
  backing resolved through `market_resource_pools_contracts`'
  `resolve_pool_declarations`, the host requirement, and the deliverable set,
  all read in one session. A pool whose declarations do not resolve is judged as
  backed, so a malformed pool never offers what admission would refuse.
  `snapshot()` and `SiteProjectionService.capacity_buckets`
  (`kit/site/src/market_site/projections.py`) are built from it;
  `list_resources()`, which the administrative `GET /capacity/resources` serves,
  keeps the stored `enabled`. Nothing here records a capacity event or advances
  the capacity version (D9). Verify with 2.4 and 2.5.
  *Done:* `SiteProjectionService`'s default `resource_inventory` is the
  offered read too, so a composition that supplies none (API credits) builds
  its resource-pool projection from it; with no host requirement the offered
  read equals `list_resources()`, and the read skips the pool and report reads
  entirely. The resolved `CapacityBacking` decides whether the host rule is
  consulted through `judge`, the rule as its availability step (it bounds
  only admitted supply), so `declaration_has_usable_host` is called with
  `backed=True` there: the delegate exposes no flag and callers are not to
  compare its label. A missing or unresolvable pool resolves to `BACKED`.
  *Tension to note for review:* `ARCHITECTURE.md` ("Kit areas") asks that no
  new site read of pool state be added while the ledger's pool-authority edge
  stands; the backing read in the offered read is one, prescribed by 11 F2 and
  D8, from the same `ResourcePool` row the ledger already reads for provider
  and modes. *Beyond the plan:* `arkhai-kit-site` takes a minor
  bump to 0.13.0 (new constructor parameter and method), raising its bounds to
  `arkhai-kit-resource-pools>=0.9.0` and
  `arkhai-kit-resource-pools-contracts>=0.3.0`; locks refreshed.
  *Round fix (21 F2, the owner's choice C):* the offered read no longer
  resolves a pool's backing. It applies the rule where the pool declares a
  deliverable offering mode (`declared_deliverable_modes`, the fact admission
  reads), since an unbacked pool must deliver nothing; a missing pool, or one
  whose modes do not parse, is judged to deliver, so the read still fails
  closed. `_pool_backing` became `_pool_delivers`, and `resolve_pool_declarations`,
  `BACKED`, and `CapacityBacking` left the ledger. Design 11 F2 and D8 are
  amended and "21 F2" records the decision; the site-capacity delta's
  projection requirement says a pool delivering no mode is judged unbacked,
  with a scenario for it.
  *Round fix (21 F1):* the ledger's own-session decision paths — probe,
  reserve, `resize_reservation`, `assign_settlement_resource`, and
  `list_offered_resources` — now begin `BEGIN IMMEDIATE` on SQLite through a
  module-private `_begin_decision_transaction`, after `_expire_stale_holds`
  (which commits what it lapses) and before any read the decision rests on, so
  a host disabled through another session commits only after the decision
  ends. The SQLite driver otherwise begins a transaction only at the first
  write, and the host authority's writes do not take the ledger's lock. The
  helper is a private copy of `kit/fulfillment`'s, which `kit/site` cannot
  import. It skips a connection already in a transaction, which has written
  and holds the writer slot. Read paths take the writer slot too, because
  `_expire_stale_holds` can write in them; the cost is that a projection read
  waits behind another writer, within the 30-second busy timeout.
  *Evidence:* library integration (`test_ledger_host_requirement.py`, 34
  passed): on a file-backed database as the service's engine is, a report
  that tries a write from another connection at each read finds it locked for
  all five paths, and again after a lapsed hold's commit; a write proceeds
  once a decision ends. Each test failed with the helper disabled, or with
  reserve's helper moved ahead of the lapse. The offered-read cases now cover a
  pool judged by its modes, unparseable modes failing closed, and a backed
  pool delivering no mode keeping its own `enabled`. `kit/site` 337 passed;
  the root `make test`, `make check-packaging`, `make check-comment-hygiene`,
  and `make check-change` passed after `make dist`.
  The fresh-context check found no defect. Taken from it: the lapse-ordering
  test, the helper docstring's account of when the guard fires, the
  missing-pool case in D8, and the delta scenario. Declined: correcting the
  constructor's older comment that the service engine is a StaticPool, which
  this change neither wrote nor relies on.
- [x] 2.4 Library integration (`kit/site/tests/integration/test_ledger_host_requirement.py`,
  with a fake `DeliverableHosts` over a fixed set): probe, reserve, and resize
  refuse a declaration naming a disabled host and one naming an unregistered
  host, falling through to a declaration with a usable host; a host returned to
  the set is matched again, while a declaration that is itself disabled stays
  unmatched and not offered; the rebind recheck refuses a destination with no
  usable host and leaves the debit unchanged; with no `deliverable_hosts`, a
  named host is admitted as today; with no requirement, nothing is refused; an
  unbacked pool's declaration keeps its own `enabled` in the offered read; the
  offered read and the snapshot report a declaration with no usable host as not
  enabled, `list_resources()` reports its stored `enabled`, and the capacity
  version is unchanged.
  *Done:* library integration — the real ledger on in-memory SQLite with a
  fake report over a mutable set — 29 passed, covering every case listed plus:
  one report read per admission call, each in a session of its own; resize
  refusing, and falling through past, a disabled or unregistered host's
  declaration; the rebind refusal leaving the capacity version unchanged; the
  offered read differing from the stored one only in `enabled`; a pool whose
  declarations do not resolve judged backed; no requirement refusing nothing
  with a report supplied and making the two reads equal; and, through
  `SiteProjectionService` over the real ledger, both projections' revisions
  advancing when a host leaves the report. That no capacity event is recorded
  is true by construction here (the report is read, never written); a host
  write recording none is 4.4's evidence. The existing cases that read
  availability through `snapshot()` now read `list_resources()`, since the
  snapshot leaves out a declaration with no usable host; the case asserting an
  unregistered host is admitted now asserts it only with no report supplied
  (D7). Two provisioning integration tests read a no-host declaration's
  availability through the snapshot for the same reason and now read the
  operator's listing (`test_capacity_api.py`,
  `test_host_requirement_api.py`).
- [x] 2.5 Unit (`kit/site/tests/unit/test_projections.py`): the capacity-bucket
  projection is built from the offered read, leaving out a declaration it
  reports as not enabled, and its revision and digest advance when only that
  state changes.
  *Done:* with a fake ledger whose stored and offered reads differ; also the
  default resource-pool inventory is the offered read.
- [x] 2.6 Verification: `uv run pytest kit/site/tests` passes. No end-to-end
  scenario exercises this section on its own; section 5's do.
  *Done:* run from `kit/site` after `make reinit`: unit and library
  integration, 332 passed. After `make dist`: `make test` passed (its first
  run failed the two provisioning tests repaired above), `make
  check-packaging` passed, `make check-change` passed. End-to-end: none on
  its own, confirmed; once
  section 4 wires the report, `e2e_bare_metal_publication` (its host disable
  and enable stages) exercises the offered read through the deployed
  projections. Nothing is owed by validation.
  *Handoff:* the docstrings of `list_offered_resources` and
  `SiteProjectionService` say every projection is built from the offered
  read; that holds for the compute service only once 4.2 passes
  `list_offered_resources()` to its resource-pool builder.

## 3. The scheduler's candidate filter

Delivers placement that never uses a host that cannot take delivery, including a
reservation's own backing, while an existing assignment keeps its host (D2, D4,
D8; fulfillment "Scheduling applies the pool provider's host requirement").
Touches `kit/fulfillment` only.

- [x] 3.1 `SchedulingTransaction` (`kit/fulfillment/src/market_fulfillment/scheduling_persistence.py`)
  gains `deliverable_host_ids() -> frozenset[str] | None`;
  `SqlAlchemySchedulingUnitOfWork` accepts `deliverable_hosts:
  DeliverableHosts | None = None` and its transaction answers it in the
  transaction's session (`None` with none supplied). Verify with 3.3.
  *Done:* the unit of work passes the report to its transaction as the
  keyword `deliverable_hosts`; every test subclass of
  `SqlAlchemySchedulingTransaction` forwards `**kwargs`, so none needed
  changing. *Beyond the plan:* `arkhai-kit-fulfillment` takes a minor bump to
  0.7.0 and raises `arkhai-kit-resource-pools` to `>=0.9.0`; locks refreshed.
- [x] 3.2 `PhysicalSettlementScheduler._eligible_candidates_in_transaction`
  (`kit/fulfillment/src/market_fulfillment/scheduler.py`) reads the deliverable
  set once and replaces its no-host check with `declaration_has_usable_host`,
  the candidate treated as backed (D8), before policy selection, rebind, cursor
  advance, or assignment, on the automatic and constrained paths alike, with no
  exception for the reservation's own backing (D4). The existing-assignment path
  is unchanged. Rewrite the comment at the check to state the generalised
  invariant. Verify with 3.3.
  *Done:* the existing-assignment path still uses `pool_needs_host` for its
  refusal of an assignment recording no host, unchanged (D4, D8). With no
  host requirement the report is not read, as in the ledger.
- [x] 3.3 Library integration (`kit/fulfillment/tests/integration/test_scheduler_host_requirement.py`):
  automatic selection never picks a candidate naming a disabled host; a
  constrained request naming a disabled or unregistered host's declaration
  raises `NoEligibleSettlementResourceError` without advancing the cursor or
  rebinding; a pool-scoped hold whose own backing's host was disabled after
  admission is placed on another eligible declaration, its capacity rebound;
  with no other eligible candidate it is refused; an existing assignment whose
  host was disabled is returned unchanged; with no `deliverable_hosts`, placement
  behaves as today.
  *Done:* library integration — the real scheduler, unit of work, ledger, and
  pool service on in-memory SQLite, with a fake report over a mutable set and
  a ledger supplying neither requirement nor report, so only the scheduler's
  own filter refuses — every case listed, plus: one report read per
  scheduling transaction, in that transaction's own session (a recording
  transaction subclass compares the sessions by identity); and no read at all
  with no requirement. A "disabled" or "unregistered" host here is an id the
  fake report leaves out — one case to the scheduler; that the host authority
  leaves both out is 4.1's evidence. The hold re-placed elsewhere is checked
  by its backing resource and both declarations' availability; the refusals
  by no assignment, no cursor, and the backing unchanged.
- [x] 3.4 Verification: `uv run pytest kit/fulfillment/tests` passes. No
  end-to-end scenario exercises this section on its own; section 5's do.
  *Done:* run from `kit/fulfillment` after `make reinit`: unit and library
  integration, 211 passed. `make check-packaging` passed after `make lock`;
  `make test` passed. End-to-end: none on its own, confirmed; no section 5
  stage schedules onto a disabled host (the publication stages stop at the
  listing), so placement's refusal rests on 3.3 and, once written, 4.4, not
  on the pipeline. Nothing is owed by validation.
  *Handoff:* the unit of work's docstring says the composition supplies it
  the report it gives the ledger; that holds once 4.2 wires the container.
  When 4.2 passes `deliverable_hosts=` to `CapacityLedgerService` and
  `SqlAlchemySchedulingUnitOfWork`, raise
  `provisioning/compute/service/pyproject.toml`'s bounds to
  `arkhai-kit-site>=0.13.0` and `arkhai-kit-fulfillment>=0.7.0` (and
  `arkhai-kit-resource-pools>=0.9.0` where it imports `DeliverableHosts`), and
  give `compute-provisioning` the same for the host authority, then
  `make lock`.

## 4. The compute composition

Delivers the host authority's report of hosts taking new delivery, wired to the
ledger, the scheduler, and the resource-pool projection builder's input, and the
running service's behaviour through its typed clients (D2, D5, D7, D9, D11, 11 F1,
11 F2; physical-provisioning "Disabling a host keeps new deliveries off it" and
"Host inventory is connection identity"; fulfillment "A provider declares whether
its delivery needs a host"). Touches `provisioning/compute` and its service.

- [x] 4.1 `HostAuthority` (`provisioning/compute/src/compute_provisioning/hosts/service.py`)
  implements `DeliverableHosts`: `deliverable_host_ids(db)` returns the ids of
  hosts whose `enabled` is true, read in the given session, so a host with no
  record never appears. Library integration
  (`provisioning/compute/tests/integration/test_host_authority.py`): a disabled
  host leaves the set and an enabled one returns; an unregistered id is never in
  it.
  *Done:* structurally, without importing the protocol, so
  `compute-provisioning` gains no bound for it; `disable_host`'s docstring
  says what disabling now does. Library integration (the real authority on
  SQLite) covers the cases listed, plus a second test on file-backed SQLite
  showing the report reads the caller's own uncommitted disable while another
  session still sees the host. `provisioning/compute`: 527 passed.
  *Beyond the plan:* `arkhai-compute-provisioning` takes a minor bump to
  0.25.0 for the new public method.
- [x] 4.2 The container (`provisioning/compute/service/src/compute_provisioning_service/container.py`)
  passes `host_authority` as `deliverable_hosts` to `CapacityLedgerService` and
  to `SqlAlchemySchedulingUnitOfWork`, the same object to both (D2).
  `_capacity_resource_inventory` (`provisioning/compute/service/src/compute_provisioning_service/main.py`)
  passes `ledger.list_offered_resources()` in place of `ledger.list_resources()`
  to `load_capacity_resource_inventory`, so the projected `enabled` and every
  domain view built from the declaration, the bare-metal view's `available`
  among them, follow the offered state (11 F2); `capacity_inventory.py` reads no
  host, and its module docstring is restated to say what the projection now
  learns of hosts. Unit (`provisioning/compute/service/tests/unit/services/test_provider_registry.py`,
  beside the existing host-requirement wiring test): the ledger and the
  scheduling unit of work receive the same `deliverable_hosts`, the host
  authority (D7).
  *Done:* the host authority and its codecs are declared ahead of the ledger
  in the container, which they do not depend on. *Correction:* the wiring
  test is in `tests/unit/test_authority_composition.py`, where the
  container's other identity-of-collaborator tests are; `test_provider_registry.py`
  holds no container test. It asserts, on a real container, that the ledger's
  report and the scheduling unit of work's are the host authority, that the
  scheduler uses that unit of work, and that both hold the same requirement.
  The integration conftest composes its own ledger and scheduler mirroring the
  container, so it now passes the host authority to both as well; without
  that, 4.4 would not exercise the production wiring. *Beyond the plan:*
  `arkhai-compute-provisioning-service` takes a minor bump to 0.23.0 and
  raises its bounds to `arkhai-kit-site>=0.13.0`,
  `arkhai-kit-fulfillment>=0.7.0`, and `arkhai-compute-provisioning>=0.25.0`;
  locks refreshed. Its code imports neither `DeliverableHosts` nor any
  resource-pools name newly, so that bound stays.
- [x] 4.3 Unit (`provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`):
  a declaration handed in not enabled projects not enabled, and its
  `bare_metal.v2` view reports itself unavailable.
  *Done:* beside the enabled case; the module docstring now says the builder
  is handed the offered read.
- [x] 4.4 Application integration through the typed clients
  (`provisioning/compute/service/tests/integration/test_host_requirement_api.py`,
  extended, or a sibling `test_deliverable_hosts_api.py`), in a backed bare-metal
  or VM pool whose provider needs a host: disabling a host through the family
  client makes `SiteCapacityClient` probe and reserve answer no capacity, makes
  `POST /fulfillment/schedule` constrained to its resource answer 422
  `no_eligible_resource` with the executor boundary never reached, projects its
  declaration not enabled in `site-resource-pools` (and its `bare_metal.v2` view
  unavailable), omits it from `site-capacity-buckets` and the snapshot, keeps
  `GET /capacity/resources` reporting the declaration's own `enabled`, and leaves
  the capacity version unchanged; enabling the host restores each; a
  declaration naming an unregistered host is likewise refused and projected not
  enabled; a declaration in an unbacked pool naming a disabled host keeps its own
  `enabled`; an existing assignment on a host disabled after scheduling is
  returned by an equivalent schedule retry and its create is refused at dispatch.
  *Done:* a sibling, `test_deliverable_hosts_api.py`, application integration
  through the family, pool, site-admin, site, and compute clients against the
  in-process app, five tests: in a backed VM pool, disabling the host makes
  probe and reserve answer no capacity, makes the constrained schedule of the
  hold admission had already placed there answer 422 `no_eligible_resource`
  (scheduling reaches no executor in any case, so that status is the
  evidence), projects the declaration not enabled in
  `site-resource-pools`, leaves it out of `site-capacity-buckets` and the
  snapshot, keeps the operator's listing at its own `enabled`, and leaves the
  capacity version unchanged; enabling restores each, and the hold is then
  placed. A bare-metal declaration's `bare_metal.v2` view reports itself
  unavailable while its host is disabled and available again on enable. A
  declaration naming an unregistered host is refused by probe and reserve,
  projected not enabled, left out of the buckets and the snapshot, and refused
  as a constrained schedule target for a hold on a usable declaration, until
  the host is registered, when the hold is placed on it. An unbacked pool's
  declaration naming a disabled host keeps its own `enabled`. An assignment
  whose host is disabled after scheduling is returned unchanged by a retry;
  its `begin_fulfillment` answers `dispatch_pending` with no job recorded;
  and once the host is enabled one convergence cycle submits the create (one
  job), so the disabled host was what refused it.
- [x] 4.5 Run the provisioning suites (`uv run pytest provisioning/compute/tests
  provisioning/compute/service/tests`). Where a test through the real container
  declares backed, host-requiring capacity naming a host it never registers and
  so now sees that capacity refused or projected not enabled, register the host
  in the test's own setup — never weaken an assertion or drop the seam — and
  list each file so repaired in the section's handoff.
  *Done:* once the conftest was wired (4.2), 33 integration tests and the two
  real-container composition tests declared capacity naming hosts they never
  registered. Each now registers its hosts in its own setup, at a
  documentation-range address, with no assertion weakened. Files repaired:
  `test_capacity_api.py` (a `register_hosts` helper on its `CapacityApi`,
  called in nine tests), `test_capacity_definitions_api.py`,
  `test_compute_contract_api.py`, `test_host_requirement_api.py` (its
  fixture's usable declaration), `test_leases_api.py` (its `_seeded` helper,
  which `test_lease_end_reports.py` also uses),
  `test_provisioning_client_endpoint_coverage.py`,
  `test_site_projection_state.py`, and `test_scheduling_composition.py`
  (which also had to create the `hosts` table).
- [x] 4.6 Verification: `uv run pytest provisioning/compute/tests
  provisioning/compute/service/tests` and `make test` pass. End-to-end: section
  5's scenarios.
  *Done:* run per project (`make test` in each, which reinstalls from
  `.dist`): `provisioning/compute` unit and library integration, 527 passed;
  `provisioning/compute/service` unit 644 passed, application integration 579
  passed. After `make lock`: `make check-packaging` passed and the root
  `make test` passed. The review fixes that followed touched only the
  service's tests (rerun: 644 and 579 passed) and one docstring in
  `hosts/service.py`; the root `make test` was not run again after them.
  End-to-end: `e2e_bare_metal_publication` (section 5's host disable and
  enable stages) exercises the wired report through the deployed projections
  and publication; `e2e_bare_metal_introduction` and the VM lane exercise the
  path for registered, enabled hosts. Nothing is owed by validation.
  *Handoff:* the composition scenario's "absent in the next transaction that
  reads it" rests on 4.1's test of the authority alone and, wired, on 4.4
  passing through the in-process app; no test reads the report through the
  container in two transactions directly. The helpers in
  `test_compute_contract_api.py`, `test_leases_api.py`, and
  `test_provisioning_client_endpoint_coverage.py` register hosts through the
  container's host authority rather than the family client, matching the
  direct ledger seeding those synchronous helpers already do.

## 5. End-to-end evidence

Delivers the deployed proof that a storefront closes a disabled host's listing
and reopens it under its original identity on re-enable, and keeps the lanes
whose bare-metal declarations name hosts they never registered passing under
D3/D12 (D5, D11, D12). Touches `e2e-tests` only.

- [x] 5.1 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`
  (`e2e_bare_metal_publication`) and
  `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_introduction.py`
  (`e2e_bare_metal_introduction`) declare whole-host capacity in backed
  `bare_metal.ansible` pools naming `machine-<resource>` hosts they never
  register. Register each named host in its pool before declaring, with a
  placeholder connection nothing connects to under the mock profile, as the VM
  lane's `register_e2e_host` (`vms/host_registry.py`) does; reuse a shared helper
  rather than a second copy. Check every other scenario that declares capacity
  for the same omission (`git grep -n "register_resource" e2e-tests/tests/e2e`)
  and repair any found the same way. Verify by the scenarios' unchanged stage
  assertions passing in validation's pipeline run.
  *Done:* the VM lane's `register_e2e_host`, its placeholder connection (now
  public as `PLACEHOLDER_CONNECTION`), and its connection comparison moved into
  a shared helper, `e2e-tests/tests/e2e/roles/helpers/hosts.py`, which
  `vms/host_registry.py` now imports, so `provision_e2e_executor` is
  unchanged. The helper also enables a host an earlier run left disabled, so
  a scenario rerun after a failed 05f is not refused for it; a unit test in
  `tests/unit/test_real_vm_lane.py` covers that. Both bare-metal scenarios
  register each `machine-<resource>` host in its declaration's pool before
  declaring. The check found one more:
  `e2e_bare_metal_unbacked_introduction`'s driver
  (`bare_metal/introduction_driver.py`) declares its backed and rateless
  machines on `host-<resource>` hosts it never registered; it now registers
  them through a `provisioning` field its fixture fills with the lane's
  `provisioning_client`, the unbacked machine still naming none. The other
  scenarios declaring capacity already register their hosts first: the VM
  lane's through `provision_e2e_executor`, its unbacked introduction pool
  needing none, and bare metal's mock and real deal drivers. The repaired
  stages' assertions are unchanged; validation's pipeline run is their
  evidence.
- [x] 5.2 Add stages to `e2e_bare_metal_publication`, after the reinstatement
  stages: disabling the advertised resource's host through the provisioning
  client closes its listing as a withdrawn source after one site-projection
  cycle and one publication cycle; enabling the host reopens the same listing
  id. Follow the module's stepped, `require_state`-gated stage pattern.
  *Done:* `TestStage05f_DisableTheHost` and `TestStage05g_EnableTheHost`,
  placed after the pricing and GPU-less stages (still after reinstatement) so
  the pricing stages' refresh assertions see an untouched listing. The close
  asserts reason `source_gone`: the storefront classifies a resource the
  projection reports not enabled as withdrawn
  (`arkhai_bare_metal/storefront_publication.py`, `_classify`). 05f also
  asserts the operator's listing still reports the declaration enabled. The
  reopen asserts no second listing is published for the resource, as stage 05
  does. Like stages 04 and 05, the new stages step publication without a dry
  run first, and no finaliser re-enables the host if 05f fails after the
  disable: its host name is unique to the run, and `register_e2e_host`
  restores a disabled host on a rerun that reuses one. The marker's
  description in `e2e-tests/pyproject.toml` names the new stages.
- [x] 5.3 Verification: `uv run pytest e2e-tests/tests/unit` passes and the new
  and repaired stages collect (`uv run pytest e2e-tests/tests/e2e --collect-only
  -m "e2e_bare_metal_publication or e2e_bare_metal_introduction"`).
  End-to-end: `e2e_bare_metal_publication` (the disable and enable stages) and
  `e2e_bare_metal_introduction`; the VM lane's scenarios register their hosts
  already and exercise the unchanged path for an enabled host. Validation's
  pipeline run is the evidence for both bare-metal scenarios; no CI workflow is
  owed.
  *Done:* run from `e2e-tests`: the e2e unit suite, 507 passed; collection
  with the markers above plus `e2e_bare_metal_unbacked_introduction` and
  `e2e_bare_metal_mock_deal`, 67 selected, the two new stages among them. No
  scenario was run here: the lanes need the compose stacks. The root
  `make test` passed before the review fixes, which touched only `e2e-tests`
  (unit suite rerun: 507 passed). End-to-end, confirmed:
  `e2e_bare_metal_publication` (its host disable and enable stages, and its
  repaired declarations), `e2e_bare_metal_introduction`, and
  `e2e_bare_metal_unbacked_introduction` (whose backed machines' hosts are now
  registered) on the bare-metal lane; the VM lane's scenarios exercise the
  rule passing for registered, enabled hosts. Nothing is owed by validation.
  *Handoff:* the reason `source_gone` and the reopen's shape are read from the
  storefront's code, not observed; validation's pipeline run is the first to
  observe them. A failure in 05f or 05g may lie in parts no earlier stage
  covers: `disable_host` through the family client, the site building its
  projection from the hosts taking new delivery, or the lane's images not
  carrying section 4; stage 05's withdraw-and-reinstate shares only the
  storefront half.

## 6. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, its parts in
order.

- [ ] 6.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the
  comments the change added at the rule's checks, in the seam's docstrings, and
  in `capacity_inventory.py` state the current invariant without naming the
  change. A finding returns the change to implementation.
- [ ] 6.2 Import placement: confirm the imports the change added
  (`DeliverableHosts`, `declaration_has_usable_host`,
  `declared_deliverable_modes` in `ledger.py`, `sqlite3` in
  `test_ledger_host_requirement.py`) sit at module level. One that
  should move returns the change to implementation.
- [ ] 6.3 Documentation compliance: re-check each decision's destination below
  against `openspec/README.md#documentation-placement`.
- [ ] 6.4 Narrative compression: shorten completed-task notes in this file to
  final behaviour, evidence, and destinations.
- [ ] 6.5 Roadmap currency (`docs/development/ROADMAP.md`, Goal 1): remove the
  open-gap row "Site admission and scheduling never read a host record's enabled
  flag"; restate the current-state sentence "Host records are used only where a
  connection is made" to say a host record is joined to a declaration for its
  connection only at dispatch, and that admission, scheduling, and projection
  learn only which hosts take new delivery; add that a backed declaration whose
  provider needs a host is offered only with a registered, enabled host. Name
  the update in the design-promotion record.
- [ ] 6.6 Campaign index currency (`openspec/changes/README.md`): this change's
  row to `in closeout` with its archive link, and its line in the Goal 1
  dependency graph marked archived; and, per D1, remove from
  `pools-6-fair-scheduling-policy`'s row the sentence "Also owns refusing new
  admission and placement against a disabled host while honouring existing
  assignments and teardown, handed over by `project-capacity-resources-without-hosts`",
  from its `proposal.md` the What Changes bullet and the Dependencies bullet on
  the disabled-host rule, and from its `design.md` the section "Disabled hosts
  stop new admission and placement, not existing work". Run
  `make check-change-index`.
- [ ] 6.7 Packaging: run `make check-packaging` and resolve every failure, then
  `make check-architecture-change CHANGE=keep-new-deliveries-off-disabled-hosts`.
- [ ] 6.8 End-to-end pipeline: record the passing run, its result, and the
  scenarios exercising this change — `e2e_bare_metal_publication` with its
  host-disable and re-enable stages, and `e2e_bare_metal_introduction`.
- [ ] 6.9 Promotion: write the permanent documents and complete the
  design-promotion record below.
  - `openspec/specs/site-capacity/architecture.md`, "Declared capacity and
    connection identity": the principle that a listing whose delivery has no
    usable host is the same as a listing with no host and neither appears; why
    projected `enabled` follows admission; the deliverable-host seam read in the
    caller's session; the ledger's offered read every projection is built from,
    with the owner's reservation that a ledger would better be a raw data
    structure (D2, D5, D6, D7, D12, 11 F2). Restate its sentences "every
    declaration projects, whether or not it names a host and whether or not that
    host is registered" and "A host record is joined to a declaration only where
    its connection is used, at dispatch" to match.
  - `openspec/specs/site-capacity/architecture.md`, "Event privacy and
    convergence": a change of host state emits no capacity event; storefronts
    see it at their next projection poll (D9).
  - `docs/development/ARCHITECTURE.md`, "Resource pools", the paragraph "A
    pool's provider also decides whether declarations in the pool must name a
    host": restated as the usable-host rule, rechecked at admission, scheduling,
    and projection through the composition-supplied report (D2, D3/D12).
  - `openspec/specs/physical-provisioning/architecture.md`, "Hosts are a
    reconciled declaration": the retention paragraph restated on its remaining
    reason, that hosts registered through the API must coexist with the document
    (D10).
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "What a document does to
    entries it stops naming": the host retention paragraph restated on the same
    reason, dropping "disabling a host does not stop its capacity declarations
    selling" (D10, D11).
  - `docs/operator-handbook.md`, "Host definitions", the bullet "A host the
    document does not name is left as it is": replace "Disabling a host does not
    stop its capacity declarations selling" with what disabling does (D11).
  - `docs/development/TESTING.md`, "Host Requirement Enforcement": the layers'
    proofs restated for the usable-host rule, the offered read, and the
    bare-metal publication stages.
  - The `site-capacity`, `fulfillment`, and `physical-provisioning` `spec.md`
    changes are written by the archive in 6.11; the record names them.
  - `openspec/specs/README.md` needs no change: no capability or companion is
    added.
- [ ] 6.10 Documentation citations: run
  `make check-doc-citations CHANGE=keep-new-deliveries-off-disabled-hosts` and
  resolve every match — including the proposal's citation of the removed
  requirement "The resource-pool projection is built from capacity
  declarations" — then
  `openspec validate keep-new-deliveries-off-disabled-hosts --strict`.
- [ ] 6.11 Archival: `openspec archive keep-new-deliveries-off-disabled-hosts -y`,
  merging the three delta specs into `openspec/specs/`.

## Design promotion record

Filled during implementation and completed at closeout (6.9), one row per
decision in `design.md` and per destination named in 6.5, 6.6, and 6.9.

| Accepted decision | Permanent location |
|---|---|
