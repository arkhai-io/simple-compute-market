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

- [ ] 1.1 Add an ordered migration to
  `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
  dated after the chain's last entry and named `<date>_<n>_reservation_activated_at`,
  that adds `capacity_reservations.activated_at_utc VARCHAR` through
  `_add_column_if_missing`, as `_migrate_reservation_release_requested_at` does. No
  backfill: every existing row stays null (D1, D6). Its docstring says null means no
  activation is recorded, never that a lease was not delivered (08 F3).
- [ ] 1.2 Add the same migration to
  `domains/apicredits/service/src/apicredits_service/db/migrations.py`, next in its
  numbered chain, guarded by `_table_exists` and `_column_exists` as that service's
  `_migrate_reservation_release_requested_at` is. Its docstring says the service
  takes the column only because it hosts the site ledger, whose row carries a compute
  lease's tail, and never reads or writes it (D6).
- [ ] 1.3 Extend `provisioning/compute/service/tests/integration/test_database.py` and
  `domains/apicredits/service/tests/integration/test_migrations.py` (service
  integration, real database): a database holding leased, releasing and released
  reservations migrates with `activated_at_utc` present and null on each, with state,
  window and other columns unchanged; a rerun changes nothing; a database already
  carrying the column migrates unchanged.

Verification point: `make -C provisioning/compute/service test-integration`;
`make -C domains/apicredits/service test`; `make test`.
End-to-end: no scenario reads the column; every deployed scenario runs both services'
migrations at startup, so `e2e_deal`, `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`
and `e2e_credits_deal` passing shows the migration applies to a started service. None
is owed.

## 2. The activation transition in the site ledger

Delivers the mapped column, its place in the reservation view, and the conditional
transition (D1, D5's refusals, D7, D9; `site-capacity` "A lease records when it was
activated", "Activation records its instant once and changes nothing else",
"Activation is addressed by reservation identity alone"). Touches `kit/site`.

- [ ] 2.1 In `kit/site/src/market_site/db.py`, map nullable `activated_at_utc` (ISO-8601
  text, as `release_requested_at`) on `CapacityReservation`, with a comment that it is
  written only by activation and that null means no activation is recorded (D1,
  08 F3). In `kit/site/src/market_site/ledger.py`, add `activated_at_utc` to
  `_reservation_payload`, null or the recorded instant, on every reservation view (D3).
- [ ] 2.2 Add `CapacityLedgerService.activate_lease(capacity_reservation_id)` to
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
- [ ] 2.3 Extend `kit/site/tests/integration/test_ledger.py` (library integration: the
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

Verification point: `make -C kit/site test`; `make test`.
End-to-end: none activates a lease; activating callers are `unify-compute-delivery-path`'s
scenarios. None is owed here.

## 3. The activation route and the site client

Delivers `POST /api/v1/capacity/reservations/{capacity_reservation_id}/activate-lease`
and `SiteCapacityClient.activate_lease`, with commit's answers (D2, D5;
`site-capacity` "Activation records its instant once and changes nothing else",
"Activation is addressed by reservation identity alone"). Touches `kit/site`,
`kit/site-client`, and the route tables of the two services that mount the router.

- [ ] 3.1 In `kit/site/src/market_site/router.py`, add the `activate-lease` route beside
  `truncate-lease`, taking no body fields: `ReservationResponse` on success, 404 when
  the ledger returns `None`, 409 with the conflict's text on `CapacityConflictError`,
  as `commit` answers (D5). Add its `capacity_activate_lease` contract, path resource
  `reservation_id`, seller role, to `CAPACITY_ROUTE_CONTRACTS` in
  `kit/site/src/market_site/auth.py`, ordered as its siblings (D2).
- [ ] 3.2 In `kit/site-client/src/market_site_client/client.py`, add the matching
  `CapacityRouteContract` and `activate_lease(*, capacity_reservation_id, request_id=None)`,
  sending no body fields and returning the recorded reservation; a 404 or 409 raises
  `SiteCapacityClientError` with its status, as `commit`'s answers do (D2, D5). Extend
  `kit/site-client/tests/unit/fake_site.py` to answer the route, and
  `kit/site-client/tests/unit/test_client.py` (unit): the operation is in the route
  table, the signed request carries the reservation in its path and no body field,
  and 404 and 409 surface their status. `kit/site/tests/unit/test_auth_route_parity.py`
  holds the two tables in step.
- [ ] 3.3 Extend `provisioning/compute/service/tests/integration/test_capacity_api.py`
  (application integration through the typed `SiteCapacityClient` against the
  in-process provisioning app): activation of a committed lease answers 200 with
  `activated_at_utc`; a retry answers the same instant; an unknown reservation 404; a
  released reservation 409 naming its state; an open-ended commit 409 saying it has no
  lease tail; a reservation read afterwards carries the instant. Run the route-table
  tests that read `market_site.auth.CAPACITY_ROUTE_CONTRACTS` —
  `provisioning/compute/service/tests/unit/test_route_table_composition.py` and
  `domains/apicredits/service/tests/unit/test_route_contract_coverage.py` — and extend
  them only where they enumerate the capacity operations.

Verification point: `make -C kit/site test`; `make -C kit/site-client test`;
`make -C provisioning/compute/service test`; `make -C domains/apicredits/service test`;
`make test`.
End-to-end: none calls the route; it is first called by `unify-compute-delivery-path`'s
wired callers. None is owed here.

## 4. Activation through the storefront's guarded capacity effects

Delivers activation on core's `SiteCapacityAuthority` protocol and
`AggregateCapacityClient` and on the kit's `CapacityEffects` and `CapacityRuntime`,
under the binding guard truncation passes (D2; `market-composition` "Kit-owned capacity
and publication lifecycle", `storefront-publication` "A listing's origin site is not
its admission authority"). Touches `core/storefront`, `kit/capacity-publication`, and
storefront test doubles.

- [ ] 4.1 In `core/storefront/src/core_storefront/capacity.py`, add
  `activate_lease(*, capacity_reservation_id)` to `SiteCapacityAuthority`, documented as
  returning the reservation as the site recorded it, and name activation in the module
  docstring's list of reservation-lifecycle verbs. In
  `core/storefront/src/core_storefront/aggregation.py`, add
  `AggregateCapacityClient.activate_lease(*, capacity_reservation_id, site_id=None)`,
  routed as `truncate_lease` is: to the named site when given, tagged with it;
  otherwise in route order (D2).
- [ ] 4.2 In `kit/capacity-publication/src/market_capacity_publication/capacity.py`, add
  `CapacityEffects.activate_lease(binding, *, capacity_reservation_id)`, which calls
  `require_binding(binding, "lease activation")` before any site call and sends the
  effect only to `binding.site_id`, returning `_at_site(...)` as `truncate_lease` does,
  and `CapacityRuntime.activate_lease` delegating to it (D2).
- [ ] 4.3 Unit tests: `core/storefront/tests/unit/test_aggregation.py` — its fake site
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

Verification point: `make -C core/storefront test`; `make -C kit/capacity-publication test`;
`make -C domains/vms/storefront test`; `make test`. The route these layers reach is
proven at application level in section 3; a storefront composing the chain over a real
site is `unify-compute-delivery-path`'s application-integration evidence when it wires
the first caller.
End-to-end: none activates a lease. None is owed here.

## 5. `activated_at_utc` on the compute lease view

Delivers the instant on `LeaseView`, read-only, with no activation operation on the
compute contract (D3; `compute-provisioning-contract` "A lease view shows when the lease
was activated"). Touches `provisioning/compute/contracts`, `provisioning/compute` and
the provisioning service's tests.

- [ ] 5.1 In `provisioning/compute/contracts/src/compute_provisioning_contracts/contracts.py`,
  add `activated_at_utc: datetime | None = None` to `LeaseView`, its docstring saying
  the site's activation records it and that null means no activation is recorded
  (08 F3); the contract version stays `3.0` (D3). In
  `provisioning/compute/src/compute_provisioning/leases.py`, map it in `lease_view()`
  through `_parsed`, as the window is (D9).
- [ ] 5.2 Unit tests: `provisioning/compute/contracts/tests/unit/test_contracts.py` — a
  view with the instant round-trips; a payload without the field parses with `None`;
  `provisioning/compute/tests/unit/test_lease_route_service.py` — `lease_view()` maps
  a recorded instant and a null.
- [ ] 5.3 Extend `provisioning/compute/service/tests/integration/test_leases_api.py`
  (application integration through the typed compute provisioning client and site
  client against the in-process app): a lease activated through the site client reads
  through `get_lease` and `list_leases` with the same instant; an unactivated lease
  reads with `activated_at_utc` null. Confirm in
  `provisioning/compute/service/tests/integration/test_provisioning_client_endpoint_coverage.py`,
  or the compute route table's tests, that no compute lease route accepts an
  activation (`compute-provisioning-contract` scenario "A caller looks for an
  activation operation on the contract").
- [ ] 5.4 Run `make check-packaging` once every suite above passes, and resolve what it
  reports (`AGENTS.md`, "Tests and diagnostics"); no section changes a dependency or a
  lock, so it is expected to pass unchanged.

Verification point: `make -C provisioning/compute/contracts test`;
`make -C provisioning/compute test`; `make -C provisioning/compute/client test`;
`make -C provisioning/compute/service test`; `make test`; `make check-packaging`.
End-to-end: `e2e_deal`, `e2e_bare_metal_deal` and `e2e_bare_metal_mock_deal` read
`LeaseView` for end reports during recovery and keep passing with the optional field
present and null; none activates. None is owed.

## 6. Closeout

Documentation only, after the pre-closeout review; a part needing a code edit returns
the change to implementation. The eleven parts of
`openspec/README.md#plan-closeout-requirements`, in order.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`; also read the comments
  and docstrings sections 1–5 added for review or migration provenance (`AGENTS.md`,
  "Python comments and docstrings"). Anything to fix returns the change to
  implementation.
- [ ] 6.2 **Import placement.** Confirm every import sections 1–5 added or touched is
  module-level, or kept local for a verified cycle or a documented lazy-load reason;
  one that should move returns the change to implementation.
- [ ] 6.3 **Documentation compliance.** Check D1–D9 against
  `openspec/README.md#documentation-placement`: normative behaviour in the four
  `spec.md` deltas, rationale and limits in the architecture companions, repository-wide
  statements in `ARCHITECTURE.md`; nothing about the deadline is promoted.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final behaviour,
  the validation evidence, deferred work and destinations; move any rationale not
  already in `design.md` there first.
- [ ] 6.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 8: rewrite this
  change's gap row ("The site records nothing about whether a lease's resource was ever
  provisioned…") as delivered and archived, as the foundation's row is, and add to
  "Current state" that the site records a lease's activation once, by reservation
  identity, through the storefront's guarded capacity effects, with no caller wired
  until `unify-compute-delivery-path`. Name the edit in the promotion record.
- [ ] 6.6 **Campaign index currency.** In `openspec/changes/README.md`, update this
  change's row's notes to what is now true and leave the Goal 8 dependency graph and
  other rows' `Depends on` unchanged (dependents are released at archive cleanup); the
  unowned lease-tail gap under "Unowned work found by
  `activate-compute-leases-at-the-site`" stays. Run `make check-change-index`; name the
  edit in the promotion record.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure; run
  `make check-architecture-change CHANGE=activate-compute-leases-at-the-site` — the
  change owns no architecture exception or override row.
- [ ] 6.8 **End-to-end pipeline.** Record the pipeline run on the change's final commit,
  its result, and that `e2e_deal`, `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`
  and `e2e_credits_deal` passed with both services migrated and `LeaseView` carrying
  the field; record that no scenario activates a lease, activating callers being
  `unify-compute-delivery-path`'s. A pipeline that cannot run for an unrelated reason
  is recorded as a blocker naming its cause and owner, its validations unrun.
- [ ] 6.9 **Promotion.** Write:
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
    `CapacityEffects` (D2);
  - `docs/development/ARCHITECTURE.md`, "Capacity reservation": activation between
    fulfillment and expiry in the flow, recorded by the site and not delivery
    evidence (D1);
  - `docs/development/ARCHITECTURE.md`, "Operators": it already states that one business
    deploys and upgrades sites and storefronts together; add that, accordingly, a
    storefront calling an operation its site lacks is unsupported and no compatibility
    path is kept for it (D4).
  The four `spec.md` files the deltas cover — `site-capacity` (D1, D5, D6, D7, D9),
  `compute-provisioning-contract` (D3), `market-composition` and
  `storefront-publication` (D2) — are written by the archive in 6.11. No capability is
  added, so `openspec/specs/README.md` is unchanged. Complete the promotion record below.
- [ ] 6.10 **Documentation citations.** Run
  `make check-doc-citations CHANGE=activate-compute-leases-at-the-site` and resolve
  every match, then `openspec validate activate-compute-leases-at-the-site --strict`.
- [ ] 6.11 **Archival.** Run `openspec archive activate-compute-leases-at-the-site -y`,
  merging the four spec deltas, and link this change's index row to its archive
  directory.

## Design promotion record

No promotion yet.

| Accepted decision | Permanent location after implementation |
|---|---|
| D1 the instant, the transition, the derived phase | `openspec/specs/site-capacity/spec.md` (archive); `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle"; `docs/development/ARCHITECTURE.md`, "Capacity reservation" |
| D2 the write path | `openspec/specs/market-composition/spec.md` and `openspec/specs/storefront-publication/spec.md` (archive); `openspec/specs/market-composition/architecture.md`, "Storefront composition kit"; `docs/development/ARCHITECTURE.md`, "Capacity publication and multi-domain storefront composition" |
| D3 both views | `openspec/specs/compute-provisioning-contract/spec.md` (archive) |
| D4 deployed together | `docs/development/ARCHITECTURE.md`, "Operators" |
| D5 the answers | `openspec/specs/site-capacity/spec.md` (archive) |
| D6 both migrations | `openspec/specs/site-capacity/spec.md` (archive); `openspec/specs/site-capacity/architecture.md`, "Current limits" |
| D7 no event, no push | `openspec/specs/site-capacity/spec.md` (archive); `openspec/specs/site-capacity/architecture.md`, "Reservation lifecycle" |
| D8 cadence | no permanent destination |
| D9 the instant's representation | `openspec/specs/site-capacity/spec.md` (archive) |
| Campaign status | Goal 8 in `docs/development/ROADMAP.md`; this change's row in `openspec/changes/README.md` |
