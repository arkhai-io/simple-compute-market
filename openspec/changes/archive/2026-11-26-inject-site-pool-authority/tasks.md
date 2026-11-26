# Tasks

Promotion of every permanent document happens in the closeout section, after the code's
last review, as the workflow's guidance ("Plan") asks; each implementation section lands
the tests its own work calls for and the code comments and docstrings it changes.

## 1. Move the declaration and asking-rate readers into the contracts package

Delivers D6, and the modified `resource-pool-management` requirement "The pool wire
contract and client are thin distributions": a site's projected pool declarations and a
listing's asking rate resolve through `kit/resource-pools-contracts`, and the four
readers stop installing the pool authority. Touches `kit/resource-pools-contracts`,
`kit/resource-pools`, `domains/vms/storefront`, `domains/bare_metal/storefront`,
`domains/apicredits/storefront`, `domains/vms/listings`, and their locks.

- [x] 1.1 Move `kit/resource-pools/src/market_resource_pools/site_declarations.py` to
  `kit/resource-pools-contracts/src/market_resource_pools_contracts/site_declarations.py`,
  its imports made package-relative, and export `POOL_ENABLEMENT_UNDECLARED`,
  `ResolvedPool`, `SiteDeclarations` and `read_site_declarations` from
  `market_resource_pools_contracts`. Move
  `kit/resource-pools/tests/unit/test_site_declarations.py` to
  `kit/resource-pools-contracts/tests/unit/test_site_declarations.py`. (D6.) Verify:
  `make -C kit/resource-pools-contracts test` passes, unit level, with the moved cases
  unchanged in what they assert.
  Done: moved with `git mv`, the moved test changed only in its imports. Unit, 503
  passed.
- [x] 1.2 Move the asking-rate declaration resolution from
  `kit/resource-pools/src/market_resource_pools/asking_rates.py` into the contracts
  package's existing `market_resource_pools_contracts/asking_rates.py`, beside the
  structural checks it already imports from there (D6, as recorded in `design.md`), and
  export `ACCEPTED_ASKING_RATE_PERIODS`, the three `ASKING_RATE_SOURCE_*` constants,
  `AskingRate`, `AskingRateResolution`, `NOT_STATED`, `raw_asking_rates` and
  `resolve_asking_rates` from `market_resource_pools_contracts`. Move
  `kit/resource-pools/tests/unit/test_asking_rates.py` to
  `kit/resource-pools-contracts/tests/unit/test_asking_rate_resolution.py`. Confirm the
  module stays within the package allowlist in
  `kit/resource-pools-contracts/pyproject.toml` (`pydantic`, admissibility, shape). Verify:
  `make -C kit/resource-pools-contracts test` passes, unit level; `make
  check-architecture` passes.
  Done: the resolution joins the contracts package's `asking_rates.py` below the
  structural checks, adding only standard-library imports, within the allowlist. Unit,
  503 passed; `make check-architecture` passed.
- [x] 1.3 Delete the two modules from `kit/resource-pools` and their exports from
  `market_resource_pools/__init__.py`, re-exporting neither (D6); keep the existing
  re-exports of the contracts package's asking-rate structural checks, which predate the
  move. Verify: `make -C kit/resource-pools test` passes, unit and library integration;
  `grep -rn "site_declarations\|resolve_asking_rates" kit/resource-pools/src` finds
  nothing.
  Done: unit and library integration, 117 passed; the grep finds nothing.
- [x] 1.4 Switch the readers to the contracts package (D6):
  `domains/vms/storefront/src/market_storefront/services/listing_sources.py`,
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/site_reading.py`,
  `domains/apicredits/storefront/src/apicredits_storefront/listing_binding.py`,
  `domains/vms/listings/src/arkhai_vms_listings/asking_rates.py` and
  `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`; and their tests that
  import a moved name — `domains/vms/storefront/tests/unit/test_asking_rate_period_parity.py`,
  `domains/vms/storefront/tests/_reconciler_cases.py`,
  `domains/apicredits/storefront/tests/listing_bindings.py`. Imports stay at module level
  where they are now (the engineering guidance's section "Imports go at module level").
  Verify: `grep -rn "market_resource_pools\b" <each package>/src` finds no import of the
  authority.
  Done; the grep finds no authority import in the four packages' `src`. The VM listings
  package's local imports moved to module level (`design.md`, "Judgements made in
  implementation"). Three further tests importing a moved name switched too:
  `domains/apicredits/service/tests/integration/test_default_pool.py`,
  `test_signed_authority.py`, and
  `provisioning/compute/service/tests/integration/test_capacity_api.py`.
- [x] 1.5 Packaging (D6, D11, `versioning.md` "Before 1.0.0", `locks.md`): bump
  `arkhai-kit-resource-pools-contracts` to 0.5.0 and `arkhai-kit-resource-pools` to 0.11.0
  (the bump also covering what section 2 adds to it); in the VM and bare-metal storefronts
  and `domains/vms/listings`, raise `arkhai-kit-resource-pools-contracts` to `>=0.5.0`, and
  in the API-credit storefront add it at `>=0.5.0`; remove `arkhai-kit-resource-pools`
  from each of the four's runtime dependencies, moving it to the `dev` group only where a
  test still imports `market_resource_pools.db` to seed a pool row; bump each of the four
  as `make check-version-bumps` requires; relock with `make lock PROJECTS="..."` naming
  every project whose lock installs a changed package. Verify: `make check-version-bumps`
  and `make check-packaging` pass.
  Done. Contracts 0.4.0 → 0.5.0, the authority 0.10.1 → 0.11.0, `arkhai-vms-listings`
  0.9.0 → 0.10.0 (its `pools` extra removed), the VM and bare-metal storefronts 0.29.0 →
  0.29.1, the API-credit storefront 0.23.0 → 0.23.1; the API-credit service (0.8.1) and
  the provisioning service (0.28.1) raise their contracts floor to `>=0.5.0` for their
  tests. The VM and bare-metal storefronts keep the authority in `dev` for seeded pool
  rows. `published-packages.md`'s internal-dependency table updated. `make
  check-version-bumps`, `make check-locks`, `make check-packaging`: passed.
- [x] 1.6 Verification point. Focused suites: `make -C kit/resource-pools-contracts test`
  (unit), `make -C kit/resource-pools test` (unit, library integration), and the suites
  of the four readers — `make -C domains/vms/storefront test`, `make -C
  domains/bare_metal/storefront test`, `make -C domains/apicredits/storefront test`,
  `make -C domains/vms/listings test` (unit, library integration, and application
  integration through each storefront's typed client, including the asking-rate cases of
  `domains/vms/storefront/tests/integration/test_pool_overrides_api.py` and
  `domains/bare_metal/storefront/tests/test_http_publication_rates.py`); then
  `change-workflow run pre-commit inject-site-pool-authority`.
  End-to-end: `e2e_bare_metal_publication` (publication from pool declarations and asking
  rates, stages 05b–05d), `e2e_compute_dynamic_listings` (VM publication from the site's
  projected declarations), and `e2e_credits_deal` (the API-credit listing's pool read).
  No CI evidence is owed: `tests.yml`'s targets are those `make validate-local` runs.
  Done. Focused suites passed: contracts 503; the authority 117; VM storefront 1199 +
  653; bare-metal storefront 694; API-credit storefront 298; API-credit service 91;
  provisioning service 639 + 579. The asking-rate cases ran through each storefront's
  app and typed clients. `domains/vms/listings` has no suite of its own; its cases run
  in the VM storefront's. `change-workflow run pre-commit inject-site-pool-authority`:
  passed. End-to-end left to validation (validation 30, below).

Section 1 notes: the VM storefront still installs the authority through
`arkhai-kit-fulfillment`, which depends on it by design.

## 2. Add the pool-facts port, the site's host-delivery module, and the pool authority's reader

Delivers the additive half of D4 and D5, and the `resource-pool-management` requirement
"The pool authority answers the site's pool facts": the site's protocols and predicate,
and `ResourcePoolFacts`, exist and are proven on their own, with nothing yet wired to
them. Touches `kit/site`, `kit/resource-pools`, and the provisioning service's unit
tests.

- [x] 2.1 Add `kit/site/src/market_site/pool_facts.py` with the protocols `PoolFacts`
  (read-only properties `exists`, `enabled`, `deliverable_modes`, `needs_host`) and
  `PoolFactsReader` (`pool_facts(self, db: Session, pool_id: str) -> PoolFacts`), each
  docstring stating the session the read takes and the missing-pool report (D4), and
  export both from `market_site`. Verify: `make -C kit/site test` passes.
  Done: `make -C kit/site test`, 384 passed.
- [x] 2.2 Add `kit/site/src/market_site/deliverable_hosts.py` with the `DeliverableHosts`
  protocol and `declaration_has_usable_host(host_id, *, needs_host, backed, deliverable)`,
  with the behaviour of the authority's predicate given `needs_host` (D5), exported from
  `market_site`; add `kit/site/tests/unit/test_deliverable_hosts.py` with the predicate's
  cases now listed in `openspec/specs/site-capacity/testing.md`, "Host Requirement
  Enforcement" (a host in the report, a host absent from it, no host named, an empty
  report, an unbacked pool, a pool needing no host, and named hosts usable with no report).
  Verify: `make -C kit/site test` passes, unit level.
  Done: the seven cases in `test_deliverable_hosts.py` pass.
- [x] 2.3 Add `kit/resource-pools/src/market_resource_pools/pool_facts.py` with the frozen
  dataclass `StoredPoolFacts` and `ResourcePoolFacts(host_requirement: HostRequirement |
  None = None)`, whose `pool_facts(db, pool_id)` reads the `ResourcePool` row in the
  caller's session and reports: `exists`; `enabled`; `deliverable_modes` from
  `declared_deliverable_modes`, `None` when it raises; `needs_host` from `pool_needs_host`
  over the pool's provider; and, for a missing pool, `exists=False`, `enabled=False`,
  `deliverable_modes=None`, `needs_host` true exactly when a requirement is supplied (D4,
  the `resource-pool-management` requirement's scenarios). It imports nothing from
  `market_site`. Export both from `market_resource_pools`. Add
  `kit/resource-pools/tests/integration/test_pool_facts.py`: a pool whose provider needs
  a host, no requirement supplied, a provider the requirement does not name, a missing
  pool with and without a requirement, an unreadable deliverable declaration, and a
  read seeing the caller's own uncommitted write in its session. Verify: `make -C
  kit/resource-pools test` passes, library integration level.
  Done: `ResourcePoolFacts` keeps the requirement as `host_requirement`.
  `test_pool_facts.py` builds its table with the pool baseline migration and adds a
  disabled pool, a provider needing no host, and a pool declaring no mode. Unit and
  library integration, 128 passed.
- [x] 2.4 Add the conformance test to
  `provisioning/compute/service/tests/unit/test_authority_composition.py` (D4, 10 F2):
  every member `typing.get_protocol_members(PoolFacts)` returns is a field of
  `StoredPoolFacts`, and `ResourcePoolFacts.pool_facts` has `PoolFactsReader.pool_facts`'
  parameters. Verify: `make -C provisioning/compute/service test-unit` passes, and the
  test fails when a member is added to `PoolFacts` alone (checked by hand, not
  committed).
  Done: the test compares parameter names and kinds, not annotations, which differ by
  design; unit, 640 passed, and a member added to the installed `PoolFacts` alone failed
  it. The service's floors rose to `arkhai-kit-site>=0.15.0` and
  `arkhai-kit-resource-pools>=0.11.0` here.
- [x] 2.5 Bump `arkhai-kit-site` to 0.15.0 (D11); `arkhai-kit-resource-pools` is already
  at 0.11.0 from task 1.5. Verify: `make check-version-bumps` passes.
  Done: `make check-version-bumps` passed; the eleven projects installing
  `arkhai-kit-site` relocked.
- [x] 2.6 Verification point. Focused suites: `make -C kit/site test` (unit, library
  integration), `make -C kit/resource-pools test` (unit, library integration), `make -C
  provisioning/compute/service test-unit` (unit); then `change-workflow run pre-commit
  inject-site-pool-authority`. End-to-end: none — nothing deployed reaches the new code
  until section 3 wires it, and none is owed. No CI evidence is owed.
  Done. `kit/site` 384, `kit/resource-pools` 128, provisioning service unit 640, all
  passed; `change-workflow run pre-commit inject-site-pool-authority`: passed. No
  end-to-end owed.

## 3. Cut the site ledger over to the port and the site-owned predicate

Delivers the rest of D3, D4, D5, D9 and D10, and the `site-capacity` requirement "The
site authority reads pool facts through an injected port": the ledger decides through
`PoolFactsReader`, `kit/site` imports and declares neither pool distribution, and every
refusal and projected `enabled` is unchanged. Touches `kit/site`, `kit/resource-pools`,
`kit/fulfillment`, `provisioning/compute`, the provisioning service, the API-credit
service, and the storefront tests that construct a ledger. The constructor change
reaches every caller at once, so this section crosses the layers in one slice: no
caller can be left on the old constructor at a commit the functional checks pass.

- [x] 3.1 Rewire `kit/site/src/market_site/ledger.py` (D4): the constructor takes a
  required keyword `pool_facts: PoolFactsReader` and loses `host_requirement`; replace
  `_pool_declares_mode`, `_pool_provider` and `_pool_delivers` with one per-decision read
  of `pool_facts` per pool, used as `design.md` D4's table gives (registration `exists`;
  admission and rebind `enabled` and the mode in `deliverable_modes`, then the predicate
  with `needs_host`, judged backed; the offered read judging backed by `deliverable_modes
  is None or bool(deliverable_modes)`); call `market_site.deliverable_hosts`' predicate;
  keep the poolless-row skip before any port read (D7); update the constructor docstring
  and every docstring naming `market_resource_pools`. Remove every `market_resource_pools`
  and `market_resource_pools_contracts` import from `kit/site/src`. Verify: `grep -rn
  "market_resource_pools" kit/site/src` finds nothing.
  Done; the grep finds nothing. `pool_facts` is a required keyword argument; each
  decision caches one `PoolFacts` per pool. The lazy report read, the poolless row in
  the offered read, and the refusal of an unreadable declaration are recorded in
  `design.md`, "Judgements made in implementation".
- [x] 3.2 Give `kit/site`'s tests their own reader double (D9): a mapping from pool id to
  a test record, in `kit/site/tests/integration/conftest.py` and a unit-level fixture
  where the unit tests need one, replacing the `ResourcePool` rows and
  `market_resource_pools` imports in `test_ledger.py`, `test_ledger_host_requirement.py`,
  `test_settlement_assignment.py`, `test_injected_time.py`, `test_capacity_definitions.py`
  and `test_projection_router.py`. Keep every case's assertion; the host-requirement
  cases express the requirement as each pool's `needs_host`. Add cases for the two
  missing-pool scenarios of the `site-capacity` delta (registration refused; the offered
  read judging the declaration as backed and needing a host, with and without a report).
  Verify: `make -C kit/site test` passes, unit and library integration, including the
  one-report-read-per-decision and file-backed write-held-off cases.
  Done, with the double as one shared module, `kit/site/tests/pool_facts_double.py`
  (`design.md`, "Judgements made in implementation"). The missing-pool cases,
  per-decision read counts, and a poolless row read for nothing are added. `make -C
  kit/site test`: 394 passed.
- [x] 3.3 Add `kit/site/tests/unit/test_import_boundaries.py` forbidding
  `market_resource_pools` and `market_resource_pools_contracts` in every module of
  `kit/site/src`, and `kit/resource-pools/tests/unit/test_import_boundaries.py`
  forbidding `market_site` in `kit/resource-pools/src` (D10), each walking every import
  form as `kit/fulfillment/tests/unit/test_import_boundaries.py` does; drop
  `arkhai-kit-resource-pools` and `arkhai-kit-resource-pools-contracts` from
  `kit/site/pyproject.toml`'s runtime dependencies, keeping either in its `dev` group
  only if a test still needs it (D4, D10). Verify: both boundary tests pass, and each
  fails against a planted import (checked by hand, not committed).
  Done: both tests walk every module and import node; neither distribution stays in
  `kit/site`'s `dev`. Each failed against a planted import, and the site test failed at
  the section's starting commit (`change-workflow run test-before`).
- [x] 3.4 Narrow `kit/resource-pools/src/market_resource_pools/host_requirement.py` to
  `HostRequirement` and `pool_needs_host`, deleting `DeliverableHosts` and
  `declaration_has_usable_host` and their exports, and moving their docstring's account of
  the usable-host rule to `market_site.deliverable_hosts` (D5); trim
  `kit/resource-pools/tests/unit/test_host_requirement.py` to `pool_needs_host`'s cases.
  Verify: `make -C kit/resource-pools test` passes; the module imports no SQLAlchemy.
  Done: the module imports only `collections.abc`. Unit and library integration, 115
  passed.
- [x] 3.5 Switch `kit/fulfillment/src/market_fulfillment/scheduler.py` to call
  `market_site`'s predicate with `needs_host=pool_needs_host(pool.provider,
  requirement)`, and `scheduling_persistence.py` to take `DeliverableHosts` from
  `market_site`; give the three ledger-constructing tests
  (`kit/fulfillment/tests/integration/test_fulfillment_persistence.py`,
  `test_scheduler.py`, `test_scheduler_host_requirement.py`) the real `ResourcePoolFacts`
  over their seeded pools, passing the host requirement to it rather than to the ledger
  (D5, D9). Raise `arkhai-kit-site` to `>=0.15.0` and `arkhai-kit-resource-pools` to
  `>=0.11.0` in `kit/fulfillment/pyproject.toml`, and bump it as `make
  check-version-bumps` requires (D11). Verify: `make -C kit/fulfillment test` passes,
  unit and library integration, its placement cases unchanged.
  Done; the five ledger constructions get `ResourcePoolFacts()` with no requirement
  (`design.md`, "Judgements made in implementation"). `kit/fulfillment` 0.9.0 → 0.9.1.
  213 passed.
- [x] 3.6 Switch `provisioning/compute/src/compute_provisioning/relays/deliverability.py`
  to take `DeliverableHosts` from `market_site`; give
  `provisioning/compute/tests/integration/test_release.py` the real `ResourcePoolFacts`;
  raise `arkhai-kit-site` to `>=0.15.0` in `provisioning/compute/pyproject.toml` and bump
  it as required (D5, D11). Verify: `make -C provisioning/compute test` passes.
  Done; `provisioning/compute` 0.30.0 → 0.30.1, its `arkhai-kit-resource-pools` floor
  raised to `>=0.11.0` too. 605 passed.
- [x] 3.7 Wire the provisioning service (D4, D11):
  `provisioning/compute/service/src/compute_provisioning_service/container.py` builds a
  `ResourcePoolFacts` provider from the merged host requirement and passes it to
  `CapacityLedgerService` as `pool_facts`, no longer passing `host_requirement` to the
  ledger; the scheduler keeps its own. Update
  `provisioning/compute/service/tests/integration/conftest.py`,
  `test_capacity_definitions_startup.py`, `test_lease_target_reconciliation.py`,
  `test_ledger_lease_lifecycle.py` and `provisioning/compute/service/examples/lease_end_first_use.py`.
  In `tests/unit/test_authority_composition.py`, assert the ledger receives the
  container's one `ResourcePoolFacts` and that it carries the merged requirement
  (`test-seams.md`, "Composition boundaries"). Raise `arkhai-kit-site` to `>=0.15.0` and
  `arkhai-kit-resource-pools` to `>=0.11.0` in its `pyproject.toml`; bump as required.
  Verify: `make -C provisioning/compute/service test` passes, unit and application
  integration through the typed clients, including `test_capacity_api.py` (a registration
  naming an unknown pool refused, the claim's offering mode, the projection),
  `test_host_requirement_api.py`, `test_deliverable_hosts_api.py` and
  `test_relay_drain_api.py`; add to `test_capacity_api.py` a reserve through the typed
  client refused because its pool does not declare the claim's mode, if no case there
  does.
  Done: the container's `pool_facts` is a `ResourcePoolFacts` over the merged
  requirement the scheduler also takes; a reserve refused for a pool declaring no mode
  was added to `test_capacity_api.py`; `test_authority_composition.py` asserts the
  ledger holds the container's one reader with the merged requirement. Unit 641,
  application integration 580, passed.
- [x] 3.8 Wire the API-credit service (D3, D11):
  `domains/apicredits/service/src/apicredits_service/container.py` passes
  `ResourcePoolFacts()` — no host requirement — as `pool_facts`; update
  `domains/apicredits/service/tests/integration/test_keys_service.py`; add a unit test
  that the container's ledger receives a `ResourcePoolFacts` with no requirement. Raise
  `arkhai-kit-site` to `>=0.15.0` and `arkhai-kit-resource-pools` to `>=0.11.0` in its
  `pyproject.toml`; bump as required. The table, the seed and `load_pool_directory` stay
  unchanged. Verify: `make -C domains/apicredits/service test` passes, unit and
  application integration, including `test_default_pool.py` and `test_migrations.py`.
  Done, through a module-level `build_capacity_ledger` seam;
  `tests/unit/test_composition.py` checks the reader carries no requirement. 92 passed.
- [x] 3.9 Give the storefront tests that construct a ledger the real `ResourcePoolFacts`
  (D9): `domains/vms/storefront/tests/integration/test_capacity_reservation_boundary.py`,
  `domains/vms/storefront/tests/integration/test_shape_feasibility.py`,
  `domains/bare_metal/storefront/tests/integration/test_site_reservation.py`, with
  `arkhai-kit-resource-pools` in each storefront's `dev` group where task 1.5 did not
  already keep it. Verify: those suites pass.
  Done; both storefronts' `arkhai-kit-site` floor rises to `>=0.15.0`. VM storefront
  1199 + 653, bare-metal storefront 694, passed.
- [x] 3.10 Relock every project whose lock installs `arkhai-kit-site`,
  `arkhai-kit-resource-pools` or `kit/fulfillment` (`make lock PROJECTS="..."`), and
  check that no comment or docstring the section touched names `market_resource_pools`
  where it now means `market_site` (`grep -rn "market_resource_pools.declaration_has_usable_host\|market_resource_pools.host_requirement" --include=*.py .`
  outside virtual environments finds none). Verify: `make check-version-bumps` and
  `make check-packaging` pass.
  Done: twelve projects relocked; the grep finds none; `published-packages.md`'s
  `arkhai-kit-site` row drops both pool distributions. `make check-version-bumps`, `make
  check-locks`, `make check-packaging`: passed.
- [x] 3.11 Verification point. Focused suites: `make -C kit/site test`, `make -C
  kit/resource-pools test`, `make -C kit/fulfillment test` (unit, library integration),
  `make -C provisioning/compute test`, `make -C provisioning/compute/service test` and
  `make -C domains/apicredits/service test` (unit, application integration through the
  typed clients), and the VM and bare-metal storefront suites; then `change-workflow run
  pre-commit inject-site-pool-authority`.
  End-to-end: `e2e_pool_declared_modes` (the deployed site refusing an undeclared mode
  before reservation, now through the port), `e2e_buy` and `e2e_deal` (VM admission and
  commit), `e2e_bare_metal_publication` (a disabled host's close and reopen, through the
  offered read's host rule), `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal`
  (bare-metal admission and commit), and `e2e_credits_deal` (the API-credit ledger with no
  host requirement). No CI evidence is owed.
  Done. Every focused suite above passed, and `change-workflow run pre-commit
  inject-site-pool-authority` passed. The round's triage (20 A2/A3) added
  `e2e_pool_declared_modes` to the VM lane and named the bare-metal lane's deals in
  place of `e2e_bare_metal_deal`, which is in no lane (`design.md`, "Judgements made in
  implementation"). End-to-end evidence: validation 30, pipeline run 45877829599, all
  three lanes passed (4.7).

## 4. Closeout

Ends the change as the workflow guidance's section "Closeout" and this repository's own
closeout parts (`openspec/README.md`, "This repository's closeout parts") order it.

- [x] 4.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the comments and
  docstrings the change added in `kit/site`, `kit/resource-pools`,
  `kit/resource-pools-contracts`, `kit/fulfillment`, `compute_provisioning` and both
  service roots describe the current system and name no change, task or change document.
  Anything to fix returns the change to implementation.
  Done: `make check-comment-hygiene` passed. The comments and docstrings the change
  added — `market_site.pool_facts`, `market_site.deliverable_hosts`, the ledger,
  `market_resource_pools.pool_facts` and `host_requirement`, the scheduler, both roots —
  describe the current system and name no change, task or change document.
- [x] 4.2 Import placement: confirm every import the change added sits at module level
  (the engineering guidance's section "Imports go at module level"); one that should move
  returns the change to implementation.
  Done: every import the change added is at module level; it removed four function-local
  imports and added none (`make check-local-imports` passed).
- [x] 4.3 Documentation compliance: re-check D1–D11 against the workflow's placement
  rules and `openspec/README.md`, "Documentation placement", and confirm each permanent
  document written in 4.8 describes the current state with no wording relative to the
  change.
  Done: D1–D11 checked against the placement tables; each decision's destination is the
  design-promotion record in `design.md`, every one a capability companion,
  `testing.md`, a delta-covered `spec.md`, `ARCHITECTURE.md`, or the repository or
  engineering guidance as its kind requires. Each document 4.8 wrote describes the
  current state with no wording relative to the change.
- [x] 4.4 Narrative compression: shorten completed task notes in this file to final
  behaviour, material validation evidence and destinations, moving anything else into
  `design.md` first.
  Done: completed notes shortened to results, evidence and destinations; the
  implementation's judgements, alternatives declined, and the round triage's lane change
  moved to `design.md`, "Judgements made in implementation".
- [x] 4.5 Roadmap currency: record in the design-promotion record that
  `docs/development/ROADMAP.md` owes nothing — the change serves the POOLS lesser goal,
  which the roadmap does not carry, and closes no goal's gap row.
  Done: `docs/development/ROADMAP.md` owes nothing, recorded in the design-promotion
  record.
- [x] 4.6 Campaign index currency: in `openspec/changes/README.md`, set this change's
  row under "Lesser goal — POOLS capacity and fulfillment foundation" to what is true at
  closeout, and correct the third sequence's paragraph under "Lesser goal — Package and
  release readiness" whose sentence says `kit/site`'s own boundary test guards the edge,
  to say the edge is gone and `kit/site`'s boundary test now forbids it; leave
  `renewable-compute-lease-deadlines`' `Depends on` for archive cleanup. Run `make
  check-change-index`. Name both updates in the design-promotion record.
  Done: the row set to `in closeout` with closeout-true notes, and the third sequence's
  paragraph corrected; `renewable-compute-lease-deadlines`' `Depends on` left for
  archive cleanup. `make check-change-index` passed. Both named in the design-promotion
  record.
- [x] 4.7 This repository's own closeout parts, as `openspec/README.md` gives them:
  - **Packaging:** run `make check-packaging` and resolve every failure; run `make
    check-architecture-change CHANGE=inject-site-pool-authority` (the change owns no row);
    `make check-agent-skills` is not owed, as the change touches no agent directory.
  - **End-to-end pipeline:** record the pipeline run the latest passing validation
    gathered, its result, and the scenarios that exercise the change —
    `e2e_pool_declared_modes`, `e2e_buy`, `e2e_deal`, `e2e_bare_metal_publication`,
    `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`,
    `e2e_compute_dynamic_listings`, `e2e_credits_deal` — from that validation's record.
    `e2e_bare_metal_deal` is in no lane, as `e2e-tests/Makefile` says.
  Done. **Packaging:** `change-workflow run pre-archive inject-site-pool-authority`
  passed at `4845f2bfa`: `make check-packaging` (locks, wheelhouse, layers, scope,
  dependencies and kinds among it) and `make check-architecture-change` ("owns no
  architecture row"); `make check-agent-skills` not owed, no agent directory touched.
  **End-to-end pipeline:** validation 30 (`reviews/30-validation.md`) at `4845f2bfa`,
  the commit this closeout builds on, closeout changing no code: `e2e.yml` run
  45877829599, success — VM lane 514 passed, bare-metal 249, API-credit 4. The VM lane
  selects `e2e_pool_declared_modes`, `e2e_buy`, `e2e_deal` and
  `e2e_compute_dynamic_listings`; the bare-metal lane `e2e_bare_metal_publication`,
  `e2e_bare_metal_mock_deal` and `e2e_bare_metal_payment_deal`; the API-credit lane
  `e2e_credits_deal`. Per-scenario results are inferred from the lanes' selection and
  totals, the output being quiet; `e2e_pool_declared_modes`' own `PASSED` line was read
  in run 45873966406 at the pre-merge commit (26 triage). The helm lane passed but
  serves none of these scenarios. `e2e_bare_metal_deal` is in no lane. No section owed
  an observation by validation.
- [x] 4.8 Promotion: write the design-promotion record in this file, and the permanent
  documents:
  - D1, D3, D4, D5, D10: `openspec/specs/site-capacity/architecture.md`, "Declared
    capacity and connection identity" — the ledger reads pool facts through the injected
    `PoolFactsReader` in its decision session, the composition supplying
    `ResourcePoolFacts` (API credits with no requirement), the usable-host predicate and
    `DeliverableHosts` in `market_site.deliverable_hosts`, the pool's provider mapping
    resolved into `needs_host` by the reader, and `kit/site`'s boundary test; the
    paragraph's "the site takes no new read of pool state while its edge into the pool
    authority stands" and its `market_resource_pools.host_requirement` citation are
    rewritten.
  - D5, D9: `openspec/specs/site-capacity/testing.md`, "Host Requirement Enforcement" —
    the predicate's unit tests in `kit/site`, `pool_needs_host`'s in `kit/resource-pools`,
    the reader's in `kit/resource-pools` library integration tests, the ledger's tests
    against their own double, and the conformance test in the provisioning service's unit
    tests.
  - D2, D4, D6, D10: `openspec/specs/resource-pool-management/architecture.md`,
    "Ownership boundary" — the authority is provider-neutral and repository-wide,
    answers the site's pool-facts port structurally, and imports no site authority, which
    its boundary test holds; and "Advertisement, delivery, and backing" — the projection's
    declaration reader and the asking-rate resolution are in the contracts distribution.
  - D2, D5, D6: `docs/development/ARCHITECTURE.md`, "Kit areas" — remove the paragraph
    beginning "One edge does not match this order", name the declaration reader and the
    asking-rate resolution in the `kit/resource-pools-contracts` paragraph; and "Resource
    pools" — replace "Both the requirement and the report live in `kit/resource-pools`
    beside the predicate that applies them" with the report and predicate in `kit/site`
    and the requirement in `kit/resource-pools`.
  - D1 (principle P1), D6: `docs/guidance/repository/package-layers.md`, "Where the
    current tree diverges" — remove the `kit/site` edge and the read-only pool modules
    from its list of divergences review holds, and state that a kit-to-kit edge the
    kit-area order forbids is removed, by moving code or injecting a port, rather than
    sanctioned by amending the order.
  - D4 (principle P2): `docs/guidance/engineering/dependencies.md`, a new section "A port
    is satisfied structurally" — a port a lower component defines is satisfied
    structurally, the values it returns included, so the implementing component never
    imports the port's owner; stated with a neutral example, as engineering guidance.
  - Evidence citations of moved tests: `openspec/specs/storefront-publication/spec.md`,
    "Evidence" (the asking-rate resolution and joint declaration-reading lines),
    `openspec/specs/resource-pool-management/spec.md`, "Evidence" (the asking-rate
    resolution line), and `openspec/specs/api-credits/architecture.md` where it names
    `read_site_declarations`' package.
  - The two delta specs merge into `openspec/specs/site-capacity/spec.md` and
    `openspec/specs/resource-pool-management/spec.md` at archival; neither capability has
    an `index.md`, so no index entries are owed. D7, D8 and D11 have no permanent
    destination, as the proposal records.
  Done: the design-promotion record is in `design.md`, as the closeout skill places it,
  rather than here. Written: the `site-capacity` companion ("Declared capacity and
  connection identity": the port, the readers, the boundary test, the predicate's owner,
  the lazy report read, the poolless row in the offered read) and its `testing.md`; the
  `resource-pool-management` companion ("Ownership boundary", "Advertisement, delivery,
  and backing") and its Evidence; `ARCHITECTURE.md` ("Kit areas", the contracts
  paragraph, "Resource pools") and the kit-areas diagram, whose `kit/site` box loses the
  dashed divergence border; `package-layers.md` and `dependencies.md`; the moved tests'
  citations in `storefront-publication/spec.md` and the reader's package in
  `api-credits/architecture.md`. Beyond the plan's list:
  `physical-provisioning/architecture.md`, whose reason for not checking declarations at
  write cited the removed edge, now cites the port's lack of backing. Both deltas merge
  at archive; neither capability has an `index.md`.
- [x] 4.9 Guidance placement: read the sections 4.8 added or rewrote in
  `package-layers.md` and `dependencies.md` against the layer test — the principle in
  `dependencies.md` must hold in any repository and name nothing of this one, with
  `engineering` and `dependencies` tags only — and run `make check-guidance`.
  Done: `dependencies.md`'s new section holds in any repository, names nothing of this
  one, with a prose example and the file's existing `engineering` and `dependencies`
  tags; `package-layers.md`'s principle is repository guidance spanning its kits, beside
  the rule it qualifies. `make check-guidance` passed.
- [x] 4.10 Documentation citations: run `make check-doc-citations
  CHANGE=inject-site-pool-authority` and resolve every match; then
  `change-workflow openspec validate inject-site-pool-authority --strict`.
  Done: `make check-doc-citations CHANGE=inject-site-pool-authority` passed; the `kit/`
  and `provisioning/` paths the promoted documents cite, which the check does not
  resolve, were confirmed to exist by hand. `change-workflow openspec validate
  inject-site-pool-authority --strict`: valid.
- [x] 4.11 Archival: `change-workflow openspec archive inject-site-pool-authority -y`,
  merging both deltas (no `--skip-specs`: neither `spec.md` was edited by hand for a
  requirement the deltas cover; the Evidence edits in 4.8 sit outside them).
  Done: archived as `openspec/changes/archive/2026-11-26-inject-site-pool-authority/`,
  merging both deltas: `resource-pool-management` one added and one modified requirement,
  `site-capacity` one added; each merged diff read and holds exactly the delta.
