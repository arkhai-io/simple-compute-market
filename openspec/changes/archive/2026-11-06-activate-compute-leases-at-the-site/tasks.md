# Tasks — compute lease activation at the site

Replanned against the reviewed design (D1–D9, with design review 08's F1 and F3); no
task of the earlier draft was checked, so none is preserved. The deadline, its pool
tag, the expiry claim and the lapse cause are `renewable-compute-lease-deadlines`'
tasks; wiring any caller to activate is `unify-compute-delivery-path`'s. No
dependency gates implementation.

Section 1 precedes the kit sections it serves by a real dependency: each service adds
the column before `kit/site` maps it, so every service suite stays green at every
verification point (an unmapped column is ignored by the ORM; a mapped column with no
column is not).

## 1. The `activated_at_utc` column in both ledger-hosting services

Delivers the column, null on every existing reservation, in compute provisioning and
API credits (D6, D9; `site-capacity` "A lease records when it was activated"). Touches
`provisioning/compute/service` and `domains/apicredits/service`.

- [x] 1.1 Add an ordered migration to
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
  dated after the chain's last entry and named `<date>_<n>_reservation_activated_at`,
  that adds `capacity_reservations.activated_at_utc VARCHAR` through
  `_add_column_if_missing`, as `_migrate_reservation_release_requested_at` does. No
  backfill: every existing row stays null (D1, D6). Its docstring says null means no
  activation is recorded, never that a lease was not delivered (08 F3).
  Done as `20261106_001_reservation_activated_at`, last in `MIGRATIONS`.
- [x] 1.2 Add the same migration to
  `domains/apicredits/service/src/apicredits_service/db/migrations.py`, next in its
  numbered chain, guarded by `_table_exists` and `_column_exists` as that service's
  `_migrate_reservation_release_requested_at` is. Its docstring says the service
  takes the column only because it hosts the site ledger, whose row carries a compute
  lease's tail, and never reads or writes it (D6).
  Done as `20261106_007_reservation_activated_at`; the docstring adds that a quota
  grant is an open-ended hold, which activation refuses.
- [x] 1.3 Extend `provisioning/compute/service/tests/integration/test_database.py` and
  `domains/apicredits/service/tests/integration/test_migrations.py` (service
  integration, real database): a database holding leased, releasing and released
  reservations migrates with `activated_at_utc` present and null on each, with state,
  window and other columns unchanged; a rerun changes nothing; a database already
  carrying the column migrates unchanged.
  Migration tests over the real chain and a real in-memory SQLite database: the
  pre-column database is built by migrating, dropping the column and its migration
  record, and inserting the three reservations by SQL; each asserts every row's
  fields unchanged with a null instant, the rerun unchanged, and a pre-existing
  column and value kept. The pinned migration-ID lists gained the new IDs.
  Evidence: `make -C provisioning/compute/service test-integration` 581 passed;
  `make -C domains/apicredits/service test` 81 passed; `make test` passed.

Verification point: `make -C provisioning/compute/service test-integration`;
`make -C domains/apicredits/service test`; `make test`.
End-to-end: no scenario reads the column. `e2e_deal`, `e2e_bare_metal_mock_deal` and
`e2e_credits_deal` show only that each started service records the migration and
starts cleanly on it; a deployed database is fresh and `create_all` makes the column,
so the migration's `ADD COLUMN` is proven only by the two migration tests.
`e2e_bare_metal_deal` needs a real host and no pipeline lane runs it. No `Owed by
validation:` line.

## 2. The activation transition in the site ledger

Delivers the mapped column, its place in the reservation view, and the conditional
transition (D1, D5's refusals, D7, D9; `site-capacity` "A lease records when it was
activated", "Activation records its instant once and changes nothing else",
"Activation is addressed by reservation identity alone"). Touches `kit/site`.

- [x] 2.1 In `kit/site/src/market_site/db.py`, map nullable `activated_at_utc` (ISO-8601
  text, as `release_requested_at`) on `CapacityReservation`, with a comment that it is
  written only by activation and that null means no activation is recorded (D1,
  08 F3). In `kit/site/src/market_site/ledger.py`, add `activated_at_utc` to
  `_reservation_payload`, null or the recorded instant, on every reservation view (D3).
- [x] 2.2 Add `CapacityLedgerService.activate_lease(capacity_reservation_id)` to
  `ledger.py`, under `serialized()` in one session, beside `truncate_lease`:
  - unknown reservation: return `None`, writing nothing;
  - `leased` with a lease end and `activated_at_utc` null: write
    `datetime.now(timezone.utc).isoformat()` once, commit, return the payload (D1, D9);
  - `leased` with `activated_at_utc` set: return the payload unchanged (D1);
  - `leased` with no lease end: raise `CapacityConflictError` saying the reservation
    has no lease tail, writing nothing (D1, D5; 08 F1);
  - any other state: raise `CapacityConflictError` naming the state, writing nothing
    (D1, D5);
  - never change state, window or debit, and record no `CapacityEvent` (D1, D7).
  The method takes no argument but the reservation identity (D1). Its docstring states
  the admissible state, the once-only write, and that activation is a lease-lifecycle
  fact rather than delivery evidence.
  Refusals: "reservation <id> is <state>; cannot activate" and "reservation <id> has
  no lease tail; cannot activate". A retry of an activated lease commits nothing.
- [x] 2.3 Extend `kit/site/tests/integration/test_ledger.py` (library integration: the
  public ledger API over a real embedded database):
  - first activation records an instant from the site's clock and leaves state, start,
    end and the capacity event feed unchanged;
  - a retry returns the same instant, including from a second ledger instance over
    the same database file (restart);
  - truncation before activation: the response carries the truncated end;
  - activate, truncate, activate again: the shorter end and the original instant, the
    end never extended (the lost-acknowledgement case);
  - `releasing` (entered by `begin_releasing` first), `release_failed`, `unmanaged`,
    `released` and `force_released`, each reached through the real transitions:
    `CapacityConflictError` naming the state, nothing written, the release undone in
    none;
  - `reserved`: refused, the hold still uncommitted and unactivated;
  - `leased` committed with no end: refused as having no lease tail,
    `activated_at_utc` still null;
  - unknown reservation: `None`;
  - a new reservation overlapping an activated lease's window is admitted exactly as
    it was before activation.

  Every case is a test through the ledger's public methods over a real SQLite
  database, each released state reached by its real transition; the restart case
  runs two ledger instances over one database file. Evidence: `make -C kit/site
  test` 350 passed; `make dist-ci`, then `make test` passed; `make check-packaging`
  passed.

Verification point: `make -C kit/site test`; `make test`.
End-to-end: no scenario calls the ledger's activation; every reservation view now
carries a null `activated_at_utc`, which no scenario reads. No `Owed by validation:`
line.

## 3. The activation route and the site client

Delivers `POST /api/v1/capacity/reservations/{capacity_reservation_id}/activate-lease`
and `SiteCapacityClient.activate_lease`, with commit's answers (D2, D5;
`site-capacity` "Activation records its instant once and changes nothing else",
"Activation is addressed by reservation identity alone"). Touches `kit/site`,
`kit/site-client`, and the route tables of the two services that mount the router.

- [x] 3.1 In `kit/site/src/market_site/router.py`, add the `activate-lease` route beside
  `truncate-lease`, taking no body fields: `ReservationResponse` on success, 404 when
  the ledger returns `None`, 409 with the conflict's text on `CapacityConflictError`,
  as `commit` answers (D5). Add its `capacity_activate_lease` contract, path resource
  `reservation_id`, seller role, to `CAPACITY_ROUTE_CONTRACTS` in
  `kit/site/src/market_site/auth.py`, ordered as its siblings (D2).
  The route declares no body parameter; the contract follows
  `capacity_truncate_lease` in both tables.
- [x] 3.2 In `kit/site-client/src/market_site_client/client.py`, add the matching
  `CapacityRouteContract` and `activate_lease(*, capacity_reservation_id, request_id=None)`,
  sending no body fields and returning the recorded reservation; a 404 or 409 raises
  `SiteCapacityClientError` with its status, as `commit`'s answers do (D2, D5). Extend
  `kit/site-client/tests/unit/fake_site.py` to answer the route, and
  `kit/site-client/tests/unit/test_client.py` (unit): the operation is in the route
  table, the signed request carries the reservation in its path and no body field,
  and 404 and 409 surface their status. `kit/site/tests/unit/test_auth_route_parity.py`
  holds the two tables in step.
  The client sends no request body at all, so the reservation is bound only by the
  path. A retry's same instant is the site's behaviour, proven in section 2 and 3.3.
  Evidence: `make -C kit/site-client test` 65 passed; `make -C kit/site test` 351
  passed, the parity case among them.
- [x] 3.3 Extend `provisioning/compute/service/tests/integration/test_capacity_api.py`
  (application integration through the typed `SiteCapacityClient` against the
  in-process provisioning app): activation of a committed lease answers 200 with
  `activated_at_utc`; a retry answers the same instant; an unknown reservation 404; a
  released reservation 409 naming its state; an open-ended commit 409 saying it has no
  lease tail; a reservation read afterwards carries the instant. Run the route-table
  tests that read `market_site.auth.CAPACITY_ROUTE_CONTRACTS` —
  `provisioning/compute/service/tests/unit/test_route_table_composition.py` and
  `domains/apicredits/service/tests/unit/test_route_contract_coverage.py` — and extend
  them only where they enumerate the capacity operations.
  `test_a_lease_is_activated_once_through_the_canonical_client` covers every case.
  Neither route-table test enumerates capacity operations, so neither was extended;
  both pass with the new contract. Evidence: `make -C provisioning/compute/service
  test` passed, integration 582; `make -C domains/apicredits/service test` 81
  passed; `make test` passed; `make check-packaging` passed.

Verification point: `make -C kit/site test`; `make -C kit/site-client test`;
`make -C provisioning/compute/service test`; `make -C domains/apicredits/service test`;
`make test`.
End-to-end: no scenario calls `activate-lease`; it is first called by
`unify-compute-delivery-path`'s wired callers. No `Owed by validation:` line.

## 4. Activation through the storefront's guarded capacity effects

Delivers activation on core's `SiteCapacityAuthority` protocol and
`AggregateCapacityClient` and on the kit's `CapacityEffects` and `CapacityRuntime`,
under the binding guard truncation passes (D2; `market-composition` "Kit-owned capacity
and publication lifecycle", `storefront-publication` "A listing's origin site is not
its admission authority"). Touches `core/storefront`, `kit/capacity-publication`, and
storefront test doubles.

- [x] 4.1 In `core/storefront/src/core_storefront/capacity.py`, add
  `activate_lease(*, capacity_reservation_id)` to `SiteCapacityAuthority`, documented as
  returning the reservation as the site recorded it, and name activation in the module
  docstring's list of reservation-lifecycle verbs. In
  `core/storefront/src/core_storefront/aggregation.py`, add
  `AggregateCapacityClient.activate_lease(*, capacity_reservation_id, site_id=None)`,
  routed as `truncate_lease` is: to the named site when given, tagged with it;
  otherwise in route order (D2).
  Route order raises an error when no site activates the reservation, as commit's
  does, rather than swallowing refusals as truncation's does; after review 23 F1 it
  raises the most informative failure, and commit's route order takes the same
  ranking (`design.md`, D10).
- [x] 4.2 In `kit/capacity-publication/src/market_capacity_publication/capacity.py`, add
  `CapacityEffects.activate_lease(binding, *, capacity_reservation_id)`, which calls
  `require_binding(binding, "lease activation")` before any site call and sends the
  effect only to `binding.site_id`, returning `_at_site(...)` as `truncate_lease` does,
  and `CapacityRuntime.activate_lease` delegating to it (D2).
  It also refuses a result tagged with another site, as `reserve` does (`design.md`,
  D10).
- [x] 4.3 Unit tests: `core/storefront/tests/unit/test_aggregation.py` — its fake site
  gains `activate_lease`; activation with `site_id` reaches only that site and is
  tagged; the aggregate still satisfies `CapacityClient`.
  `kit/capacity-publication/tests/unit/test_capacity.py` — activation reaches only the
  binding's site; an unbacked binding is refused as a conflict before any site call
  (`storefront-publication` scenario "A capacity operation receives an unbacked
  listing"); an unconfigured site fails closed with no fan-out (`market-composition`
  scenario "A lease is activated"); a result naming another site is refused. Add
  `activate_lease` to the storefront doubles that stand in for a site authority —
  `domains/vms/storefront/tests/unit/test_interrupt_deal_admin.py`'s and
  `domains/vms/storefront/tests/fake_site.py`'s — so
  `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`'s protocol
  assertions keep holding for both the site client and the aggregate.
  Done as planned for the two unit suites, plus route order over a cold cache:
  the first site's refusal passed and the second activating, and a reservation no
  site holds raising. Corrected from the plan: the VM storefront's two doubles are
  unchanged, since its protocol assertions run against the real site client and
  aggregate, and neither double stands in for a site authority that activates.
  Pre-closeout fix (review 23 F1): `test_aggregation.py` proves the ranking for
  activation and commit (409 then 404, 409 then unreachable, unreachable then 404,
  404 everywhere). Evidence: `make -C core/storefront test` 232 passed;
  `make -C kit/capacity-publication test` 127 passed; `make -C domains/vms/storefront
  test` 525 passed; `make dist-ci`, then `make test` passed; `make check-packaging`
  passed. No typing check is in the plan or `make test`; none was run.

Verification point: `make -C core/storefront test`; `make -C kit/capacity-publication test`;
`make -C domains/vms/storefront test`; `make test`. The route these layers reach is
proven at application level in section 3; a storefront composing the chain over a real
site is `unify-compute-delivery-path`'s application-integration evidence when it wires
the first caller.
End-to-end: no storefront code calls `activate_lease` yet. No `Owed by validation:`
line.

## 5. `activated_at_utc` on the compute lease view

Delivers the instant on `LeaseView`, read-only, with no activation operation on the
compute contract (D3; `compute-provisioning-contract` "A lease view shows when the lease
was activated"). Touches `provisioning/compute/contracts`, `provisioning/compute` and
the provisioning service's tests.

- [x] 5.1 In `provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`,
  add `activated_at_utc: datetime | None = None` to `LeaseView`, its docstring saying
  the site's activation records it and that null means no activation is recorded
  (08 F3); the contract version stays `3.0` (D3). In
  `provisioning/compute/src/compute_provisioning/leases.py`, map it in `lease_view()`
  through `_parsed`, as the window is (D9).
  The class and module docstrings name the site's capacity API among a lease's
  writers.
- [x] 5.2 Unit tests: `provisioning/compute/contracts/tests/unit/test_contracts.py` — a
  view with the instant round-trips; a payload without the field parses with `None`;
  `provisioning/compute/tests/unit/test_lease_route_service.py` — `lease_view()` maps
  a recorded instant and a null.
  Evidence: `make -C provisioning/compute/contracts test` 154 passed;
  `make -C provisioning/compute test` 528 passed.
- [x] 5.3 Extend `provisioning/compute/service/tests/integration/test_leases_api.py`
  (application integration through the typed compute provisioning client and site
  client against the in-process app): a lease activated through the site client reads
  through `get_lease` and `list_leases` with the same instant; an unactivated lease
  reads with `activated_at_utc` null. Confirm in
  `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`,
  or the compute route table's tests, that no compute lease route accepts an
  activation (`compute-provisioning-contract` scenario "A caller looks for an
  activation operation on the contract").
  `test_a_lease_shows_the_instant_the_site_s_activation_recorded`, over `vm` and
  `bare_metal`, activates through the typed site client and reads both leases
  through `get_lease` and `list_leases`. That no lease route activates is pinned by
  `test_route_table_composition.py::test_the_lease_routes_read_and_end_leases_and_none_activates_one`.
  An existing test there that called recording an executor target "activation" now
  says the fulfillment became active, so the word has one meaning. Evidence:
  `make -C provisioning/compute/client test` 86 passed; `make -C
  provisioning/compute/service test` unit 648, integration 584 passed.
- [x] 5.4 Run `make check-packaging` once every suite above passes, and resolve what it
  reports (`AGENTS.md`, "Tests and diagnostics"); no section changes a dependency or a
  lock, so it is expected to pass unchanged.
  Passed unchanged after `make dist-ci` and `make test` on the final tree.

Verification point: `make -C provisioning/compute/contracts test`;
`make -C provisioning/compute test`; `make -C provisioning/compute/client test`;
`make -C provisioning/compute/service test`; `make test`; `make check-packaging`.
End-to-end: every scenario reading `LeaseView` — `e2e_deal`,
`e2e_bare_metal_mock_deal` and the VM lifecycle scenarios — reads the field present
and null, and none asserts on it or activates; `e2e_bare_metal_deal` and the
real-provisioning lanes need a real host, so no pipeline lane runs them. No `Owed by
validation:` line.

## 6. Closeout

Documentation only, after the pre-closeout review; a part needing a code edit returns
the change to implementation. The eleven parts of
`openspec/README.md#plan-closeout-requirements`, in order.

- [x] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`; also read the comments
  and docstrings sections 1–5 added for review or migration provenance (`AGENTS.md`,
  "Python comments and docstrings"). Anything to fix returns the change to
  implementation.
  `make check-comment-hygiene` passed. The comments and docstrings the change added,
  read in its diff against `origin/dev`, state current invariants and name no review,
  migration or change.
- [x] 6.2 **Import placement.** Confirm every import sections 1–5 added or touched is
  module-level, or kept local for a verified cycle or a documented lazy-load reason;
  one that should move returns the change to implementation.
  No production module gained an import; the two the tests added
  (`fake_site.py`, `test_lease_route_service.py`, both `datetime`) are module-level.
- [x] 6.3 **Documentation compliance.** Check D1–D9 against
  `openspec/README.md#documentation-placement`: normative behaviour in the four
  `spec.md` deltas, rationale and limits in the architecture companions, repository-wide
  statements in `ARCHITECTURE.md`; nothing about the deadline is promoted.
  Each decision's normative part is in a delta and its rationale in a companion or
  `ARCHITECTURE.md` (the record below); nothing about the deadline is promoted. Read
  against the code, `physical-provisioning`'s "A lease's executor identity and
  evidence are fixed once recorded" listed a lease's writers without the site's
  activation, which `LeaseView`'s docstring names, and used "activation" for a
  fulfillment becoming active; promotion corrects both by hand, as no delta covers
  that spec. The decisions implementation settled (route order, the site check)
  are recorded as `design.md` D10.
- [x] 6.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
  the validation evidence, deferred work and destinations; move any rationale not
  already in `design.md` there first.
  Section notes shortened to behaviour, evidence and corrections; the route-order
  rationale, the review 23 F1 ranking and the kept site check moved first to
  `design.md` D10. Test-construction detail and the fresh-context checks' narratives
  were dropped as duplicating the tests.
- [x] 6.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 8: rewrite this
  change's gap row ("The site records nothing about whether a lease's resource was ever
  provisioned…") as delivered and archived, as the foundation's row is, and add to
  "Current state" that the site records a lease's activation once, by reservation
  identity, through the storefront's guarded capacity effects, with no caller wired
  until `unify-compute-delivery-path`. Name the edit in the promotion record.
  Done; the row links the archive directory.
- [x] 6.6 **Campaign index currency.** In `openspec/changes/README.md`, update this
  change's row's notes to what is now true and leave the Goal 8 dependency graph and
  other rows' `Depends on` unchanged (dependents are released at archive cleanup); the
  unowned lease-tail gap under "Unowned work found by
  `activate-compute-leases-at-the-site`" stays. Run `make check-change-index`; name the
  edit in the promotion record.
  The row is `in closeout`, its notes state the delivered behaviour, and it links
  the archive directory; the graph, other rows and the unowned gap are unchanged.
  `scripts/change-workflow check index` passed.
- [x] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=activate-compute-leases-at-the-site` — the
  change owns no architecture exception or override row.
  `make check-packaging` passed (locks, installs, Python selection, and the layer,
  scope, dependency and kind rules); `make check-architecture-change` reported that
  the change owns no row. The change touches no `.agents/`, `.claude/` or `.codex/`
  file, so `make check-agent-skills` is not owed.
- [x] 6.8 **End-to-end pipeline.** Record the pipeline run on the change's final commit,
  its result, and that `e2e_deal`, `e2e_bare_metal_mock_deal` and `e2e_credits_deal`
  passed with both services migrated and `LeaseView` carrying the field; record that
  `e2e_bare_metal_deal` needs a real host and was not run, no pipeline lane running
  it (23 F2); record that no scenario activates a lease, activating callers being
  `unify-compute-delivery-path`'s. A pipeline that cannot run for an unrelated reason
  is recorded as a blocker naming its cause and owner, its validations unrun.
  Validation 30 passed on `40eb59ad2`, the merge of `dev` after the pre-closeout
  fix, which the closeout commit's code is: pipeline run 42228485377 succeeded
  (e2e-apicredits 4 passed, e2e-bare-metal 70 passed, e2e-vm 153 passed and 2
  skipped), with local checks and the Helm part passing. `e2e_deal`,
  `e2e_bare_metal_mock_deal` and `e2e_credits_deal` ran in those lanes, which passed
  whole; the record reads lane totals, not per-scenario results. `e2e_bare_metal_deal`
  needs a real host and was not run. No scenario activates a lease. No section owed
  a CI observation.
- [x] 6.9 **Promotion.** Write:
  - `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle": a lease's
    activation is one instant the site records once, from `leased` with a lease end;
    whether a lease is activated is derived from it; null records no activation and is
    not delivery evidence; activation records no capacity event (D1, D7);
  - `openspec/specs/site-capacity/architecture.md`, "Current limits": the lease tail
    shares the reservation row with API credits' quota grants, so a lease column's
    migration lands in API credits too (D6);
  - `openspec/specs/market-composition/architecture.md`, "Storefront composition kit",
    and `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain
    storefront composition": activation in the list of capacity effects passing
    `CapacityEffects` (D2), and, in the companion, activation in the sentence that
    nothing reserves, commits, releases, or truncates through an aggregate directly
    (amended at section 4's implementation);
  - `docs/development/ARCHITECTURE.md`, "Capacity reservation": activation between
    fulfillment and expiry in the flow, recorded by the site and not delivery
    evidence (D1); the closeout review's triage (32 F1) moved it out of the numbered
    flow into the paragraph after it, as an operation the site offers, since no
    delivery path performs it yet;
  - `docs/development/ARCHITECTURE.md`, "Operators": it already states that one business
    deploys and upgrades sites and storefronts together; add that, accordingly, a
    storefront calling an operation its site lacks is unsupported and no compatibility
    path is kept for it (D4).
  The four `spec.md` files the deltas cover — `site-capacity` (D1, D5, D6, D7, D9),
  `compute-provisioning-contract` (D3), `market-composition` and
  `storefront-publication` (D2) — are written by the archive in 6.11. No capability is
  added, so `openspec/specs/README.md` is unchanged. Complete the promotion record below.
  Written as listed. The flow step says no delivery path calls activation yet. Also
  written: the market-composition companion's D10 (route order and the site check),
  and `physical-provisioning/spec.md`'s writer list and its fulfillment "activation"
  (6.3). The record is in `design.md`.
- [x] 6.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=activate-compute-leases-at-the-site` and resolve
  every match, then `openspec validate activate-compute-leases-at-the-site --strict`.
  `make check-change`, which runs both with the pinned validator, passed before the
  archive.
- [x] 6.11 **Archival.** Run `openspec archive activate-compute-leases-at-the-site -y`,
  merging the four spec deltas, and link this change's index row to its archive
  directory.
  Archived with the deltas merged: no permanent spec already carried them. The
  merged requirements were read in the specs' diff; the index row and the roadmap
  link the archive directory.

## Design promotion record

Completed in `design.md`'s "Design promotion record", which names every accepted
decision's permanent location, the roadmap and index edits among them.
