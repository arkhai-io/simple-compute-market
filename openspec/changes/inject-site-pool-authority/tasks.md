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
  Done: moved with `git mv`; `.backing` and `.hints` imported relatively; the moved test's
  diff is its import lines alone. `make -C kit/resource-pools-contracts test`: unit, 503
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
  Done: the contracts module now carries the authority module's docstring (declaration,
  contract and resolution) and its resolution below the structural checks; it adds only
  standard-library imports (`Callable`, `Iterable`, `dataclass`, `field`), within the
  allowlist. The moved test's diff is its one import line. Unit, 503 passed (with 1.1);
  `make check-architecture`: layers, scope, dependencies and kinds hold.
- [x] 1.3 Delete the two modules from `kit/resource-pools` and their exports from
  `market_resource_pools/__init__.py`, re-exporting neither (D6); keep the existing
  re-exports of the contracts package's asking-rate structural checks, which predate the
  move. Verify: `make -C kit/resource-pools test` passes, unit and library integration;
  `grep -rn "site_declarations\|resolve_asking_rates" kit/resource-pools/src` finds
  nothing.
  Done: `make -C kit/resource-pools test`: unit and library integration, 117 passed; the
  grep finds nothing.
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
  Done, the grep finding none in the four packages' `src`. Differing from the plan: the
  VM listings package's two function-local imports and its `TYPE_CHECKING` import of
  `ResolvedPool` now sit at module level, as does `_reconciler_cases.py`'s local import.
  Their recorded reason was that buyers install the listings package without the pool
  authority; the contracts package is a runtime dependency of it, so that reason is gone,
  and `resolve_vm_asking_rates` now declares `AskingRateResolution` as its return type
  rather than `Any`. Outside the plan's list, three more tests imported a moved name from
  the authority and now take it from the contracts package:
  `domains/apicredits/service/tests/integration/test_default_pool.py`,
  `domains/apicredits/service/tests/integration/test_signed_authority.py` and
  `provisioning/compute/service/tests/integration/test_capacity_api.py`; both services
  raise their contracts floor for them (1.5). The bare-metal storefront's
  `site_reading.py` docstring and `_policy_tags` comment now name the contracts package's
  reader rather than the resource-pool kit's.
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
  Done. Versions: contracts 0.4.0 → 0.5.0, the authority 0.10.1 → 0.11.0, the listings
  package 0.9.0 → 0.10.0 (minor: its `pools` extra is removed), and the three storefronts
  by a patch, their change being internal: VM and bare-metal 0.29.0 → 0.29.1, API credits
  0.23.0 → 0.23.1. The VM storefront's exact pin on the bare-metal storefront moves to
  `==0.29.1`, and its listings requirement becomes `arkhai-vms-listings[overrides]>=0.10.0`.
  The VM and bare-metal storefronts keep `arkhai-kit-resource-pools>=0.11.0` in `dev`
  for the pool rows their ledger tests seed; the API-credit storefront and the listings
  package keep it nowhere. Outside the plan: the API-credit service (0.8.0 → 0.8.1) and
  the provisioning service (0.28.0 → 0.28.1) raise `arkhai-kit-resource-pools-contracts`
  to `>=0.5.0`, the first version exporting the reader their tests now import (1.4); a
  patch, since neither's runtime changes, which section 3's bump of each may supersede
  with a larger one. The authority keeps its contracts floor at `>=0.4.0`: it imports
  nothing 0.5.0 adds. `docs/guidance/repository/published-packages.md`'s table of
  internal dependencies is updated for the four readers, as
  `scripts/tests/test_publish_matrix.py` requires. Relocked with `make lock
  PROJECTS="..."` over the 26 projects whose lock names a changed package, then the two
  services again for their bump. `make check-version-bumps`, `make check-locks`: passed.
  `make check-packaging`: passed, in the pre-commit run 1.6 records.
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
  Done. `make -C kit/resource-pools-contracts test`: unit, 503 passed. `make -C
  kit/resource-pools test`: unit and library integration, 117 passed. `make -C
  domains/vms/storefront test`: unit 1199 passed, 1 skipped; integration 653 passed.
  `make -C domains/bare_metal/storefront test`: 694 passed. `make -C
  domains/apicredits/storefront test`: 298 passed. The asking-rate cases ran through each
  storefront's app and its typed clients (`StorefrontClient`, `PoolOverrideClient`):
  `test_http_publication_rates.py`, whose 12 cases hold the bare-metal asking-rate cases
  among others, all passed, and `test_pool_overrides_api.py -k rate`, 8 passed. `make -C domains/vms/listings test` does not exist: the listings package has no
  Makefile, tests or lock of its own, and its derivation and asking-rate cases run in the
  VM storefront's suite. For the three tests outside the plan (1.4): `make -C
  domains/apicredits/service test`, 91 passed, and `make -C provisioning/compute/service
  test`, unit 639 and integration 579 passed. `change-workflow run pre-commit
  inject-site-pool-authority`: its first run failed on four cases of
  `scripts/tests/test_publish_matrix.py` (the published-packages table, fixed in 1.5) and
  on the history-wording check (a `pyproject.toml` comment, since removed), every other
  suite and `make check-packaging` passing; the run after the fixes is recorded in the
  section's notes.
  End-to-end, as the plan names them: `e2e_bare_metal_publication`,
  `e2e_compute_dynamic_listings` and `e2e_credits_deal` reach the moved readers once
  deployed; none was run in this section, and validation runs them. No CI evidence is
  owed.

Section 1 notes: the move is mechanical and every assertion is unchanged. Section 2
finds `kit/resource-pools` already at 0.11.0, and the contracts package at 0.5.0; section
3 finds the API-credit service at 0.8.1 and the provisioning service at 0.28.1, each
bumped once already. Correction to the section's opening paragraph: the authority left
each reader's direct runtime dependencies, but the VM storefront still installs it,
through `arkhai-kit-fulfillment`, which depends on it by design, and through
`arkhai-kit-site` until section 3 drops that edge. Left as it is:
`domains/vms/listings/src/arkhai_vms_listings/listing_shapes.py` keeps an older
function-local import of the contracts package whose comment says buyers install the
listings package without the pool kit; the section did not touch that import, so it is
not moved here. The citations of the moved
tests in `openspec/specs/storefront-publication/spec.md` and
`openspec/specs/resource-pool-management/spec.md`, "Evidence", still name their old paths
until closeout's 4.8 rewrites them; the citations check resolves only `openspec/`,
`docs/`, `tools/`, `scripts/`, `e2e-tests/` and `.agents/` paths, so it cannot report
these `kit/` paths, and 4.8 must find them itself. After the fresh-context check's fixes,
`change-workflow run pre-commit inject-site-pool-authority` passed: `make validate-local`
(`check-packaging` and `make test`, every suite) and `make check-repository` (comment
hygiene, documentation citations, history wording, version bumps, local imports,
capability index, guidance).

## 2. Add the pool-facts port, the site's host-delivery module, and the pool authority's reader

Delivers the additive half of D4 and D5, and the `resource-pool-management` requirement
"The pool authority answers the site's pool facts": the site's protocols and predicate,
and `ResourcePoolFacts`, exist and are proven on their own, with nothing yet wired to
them. Touches `kit/site`, `kit/resource-pools`, and the provisioning service's unit
tests.

- [ ] 2.1 Add `kit/site/src/market_site/pool_facts.py` with the protocols `PoolFacts`
  (read-only properties `exists`, `enabled`, `deliverable_modes`, `needs_host`) and
  `PoolFactsReader` (`pool_facts(self, db: Session, pool_id: str) -> PoolFacts`), each
  docstring stating the session the read takes and the missing-pool report (D4), and
  export both from `market_site`. Verify: `make -C kit/site test` passes.
- [ ] 2.2 Add `kit/site/src/market_site/deliverable_hosts.py` with the `DeliverableHosts`
  protocol and `declaration_has_usable_host(host_id, *, needs_host, backed, deliverable)`,
  with the behaviour of the authority's predicate given `needs_host` (D5), exported from
  `market_site`; add `kit/site/tests/unit/test_deliverable_hosts.py` with the predicate's
  cases now listed in `openspec/specs/site-capacity/testing.md`, "Host Requirement
  Enforcement" (a host in the report, a host absent from it, no host named, an empty
  report, an unbacked pool, a pool needing no host, and named hosts usable with no report).
  Verify: `make -C kit/site test` passes, unit level.
- [ ] 2.3 Add `kit/resource-pools/src/market_resource_pools/pool_facts.py` with the frozen
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
- [ ] 2.4 Add the conformance test to
  `provisioning/compute/service/tests/unit/test_authority_composition.py` (D4, 10 F2):
  every member `typing.get_protocol_members(PoolFacts)` returns is a field of
  `StoredPoolFacts`, and `ResourcePoolFacts.pool_facts` has `PoolFactsReader.pool_facts`'
  parameters. Verify: `make -C provisioning/compute/service test-unit` passes, and the
  test fails when a member is added to `PoolFacts` alone (checked by hand, not
  committed).
- [ ] 2.5 Bump `arkhai-kit-site` to 0.15.0 (D11); `arkhai-kit-resource-pools` is already
  at 0.11.0 from task 1.5. Verify: `make check-version-bumps` passes.
- [ ] 2.6 Verification point. Focused suites: `make -C kit/site test` (unit, library
  integration), `make -C kit/resource-pools test` (unit, library integration), `make -C
  provisioning/compute/service test-unit` (unit); then `change-workflow run pre-commit
  inject-site-pool-authority`. End-to-end: none — nothing deployed reaches the new code
  until section 3 wires it, and none is owed. No CI evidence is owed.

## 3. Cut the site ledger over to the port and the site-owned predicate

Delivers the rest of D3, D4, D5, D9 and D10, and the `site-capacity` requirement "The
site authority reads pool facts through an injected port": the ledger decides through
`PoolFactsReader`, `kit/site` imports and declares neither pool distribution, and every
refusal and projected `enabled` is unchanged. Touches `kit/site`, `kit/resource-pools`,
`kit/fulfillment`, `provisioning/compute`, the provisioning service, the API-credit
service, and the storefront tests that construct a ledger. The constructor change
reaches every caller at once, so this section crosses the layers in one slice: no
caller can be left on the old constructor at a commit the functional checks pass.

- [ ] 3.1 Rewire `kit/site/src/market_site/ledger.py` (D4): the constructor takes a
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
- [ ] 3.2 Give `kit/site`'s tests their own reader double (D9): a mapping from pool id to
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
- [ ] 3.3 Add `kit/site/tests/unit/test_import_boundaries.py` forbidding
  `market_resource_pools` and `market_resource_pools_contracts` in every module of
  `kit/site/src`, and `kit/resource-pools/tests/unit/test_import_boundaries.py`
  forbidding `market_site` in `kit/resource-pools/src` (D10), each walking every import
  form as `kit/fulfillment/tests/unit/test_import_boundaries.py` does; drop
  `arkhai-kit-resource-pools` and `arkhai-kit-resource-pools-contracts` from
  `kit/site/pyproject.toml`'s runtime dependencies, keeping either in its `dev` group
  only if a test still needs it (D4, D10). Verify: both boundary tests pass, and each
  fails against a planted import (checked by hand, not committed).
- [ ] 3.4 Narrow `kit/resource-pools/src/market_resource_pools/host_requirement.py` to
  `HostRequirement` and `pool_needs_host`, deleting `DeliverableHosts` and
  `declaration_has_usable_host` and their exports, and moving their docstring's account of
  the usable-host rule to `market_site.deliverable_hosts` (D5); trim
  `kit/resource-pools/tests/unit/test_host_requirement.py` to `pool_needs_host`'s cases.
  Verify: `make -C kit/resource-pools test` passes; the module imports no SQLAlchemy.
- [ ] 3.5 Switch `kit/fulfillment/src/market_fulfillment/scheduler.py` to call
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
- [ ] 3.6 Switch `provisioning/compute/src/compute_provisioning/relays/deliverability.py`
  to take `DeliverableHosts` from `market_site`; give
  `provisioning/compute/tests/integration/test_release.py` the real `ResourcePoolFacts`;
  raise `arkhai-kit-site` to `>=0.15.0` in `provisioning/compute/pyproject.toml` and bump
  it as required (D5, D11). Verify: `make -C provisioning/compute test` passes.
- [ ] 3.7 Wire the provisioning service (D4, D11):
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
- [ ] 3.8 Wire the API-credit service (D3, D11):
  `domains/apicredits/service/src/apicredits_service/container.py` passes
  `ResourcePoolFacts()` — no host requirement — as `pool_facts`; update
  `domains/apicredits/service/tests/integration/test_keys_service.py`; add a unit test
  that the container's ledger receives a `ResourcePoolFacts` with no requirement. Raise
  `arkhai-kit-site` to `>=0.15.0` and `arkhai-kit-resource-pools` to `>=0.11.0` in its
  `pyproject.toml`; bump as required. The table, the seed and `load_pool_directory` stay
  unchanged. Verify: `make -C domains/apicredits/service test` passes, unit and
  application integration, including `test_default_pool.py` and `test_migrations.py`.
- [ ] 3.9 Give the storefront tests that construct a ledger the real `ResourcePoolFacts`
  (D9): `domains/vms/storefront/tests/integration/test_capacity_reservation_boundary.py`,
  `domains/vms/storefront/tests/integration/test_shape_feasibility.py`,
  `domains/bare_metal/storefront/tests/integration/test_site_reservation.py`, with
  `arkhai-kit-resource-pools` in each storefront's `dev` group where task 1.5 did not
  already keep it. Verify: those suites pass.
- [ ] 3.10 Relock every project whose lock installs `arkhai-kit-site`,
  `arkhai-kit-resource-pools` or `kit/fulfillment` (`make lock PROJECTS="..."`), and
  check that no comment or docstring the section touched names `market_resource_pools`
  where it now means `market_site` (`grep -rn "market_resource_pools.declaration_has_usable_host\|market_resource_pools.host_requirement" --include=*.py .`
  outside virtual environments finds none). Verify: `make check-version-bumps` and
  `make check-packaging` pass.
- [ ] 3.11 Verification point. Focused suites: `make -C kit/site test`, `make -C
  kit/resource-pools test`, `make -C kit/fulfillment test` (unit, library integration),
  `make -C provisioning/compute test`, `make -C provisioning/compute/service test` and
  `make -C domains/apicredits/service test` (unit, application integration through the
  typed clients), and the VM and bare-metal storefront suites; then `change-workflow run
  pre-commit inject-site-pool-authority`.
  End-to-end: `e2e_pool_declared_modes` (the deployed site refusing an undeclared mode
  before reservation, now through the port), `e2e_buy` and `e2e_deal` (VM admission and
  commit), `e2e_bare_metal_publication` (a disabled host's close and reopen, through the
  offered read's host rule), `e2e_bare_metal_deal`, and `e2e_credits_deal` (the API-credit
  ledger with no host requirement). No CI evidence is owed.

## 4. Closeout

Ends the change as the workflow guidance's section "Closeout" and this repository's own
closeout parts (`openspec/README.md`, "This repository's closeout parts") order it.

- [ ] 4.1 Comment hygiene: run `make check-comment-hygiene`, and confirm the comments and
  docstrings the change added in `kit/site`, `kit/resource-pools`,
  `kit/resource-pools-contracts`, `kit/fulfillment`, `compute_provisioning` and both
  service roots describe the current system and name no change, task or change document.
  Anything to fix returns the change to implementation.
- [ ] 4.2 Import placement: confirm every import the change added sits at module level
  (the engineering guidance's section "Imports go at module level"); one that should move
  returns the change to implementation.
- [ ] 4.3 Documentation compliance: re-check D1–D11 against the workflow's placement
  rules and `openspec/README.md`, "Documentation placement", and confirm each permanent
  document written in 4.8 describes the current state with no wording relative to the
  change.
- [ ] 4.4 Narrative compression: shorten completed task notes in this file to final
  behaviour, material validation evidence and destinations, moving anything else into
  `design.md` first.
- [ ] 4.5 Roadmap currency: record in the design-promotion record that
  `docs/development/ROADMAP.md` owes nothing — the change serves the POOLS lesser goal,
  which the roadmap does not carry, and closes no goal's gap row.
- [ ] 4.6 Campaign index currency: in `openspec/changes/README.md`, set this change's
  row under "Lesser goal — POOLS capacity and fulfillment foundation" to what is true at
  closeout, and correct the third sequence's paragraph under "Lesser goal — Package and
  release readiness" whose sentence says `kit/site`'s own boundary test guards the edge,
  to say the edge is gone and `kit/site`'s boundary test now forbids it; leave
  `renewable-compute-lease-deadlines`' `Depends on` for archive cleanup. Run `make
  check-change-index`. Name both updates in the design-promotion record.
- [ ] 4.7 This repository's own closeout parts, as `openspec/README.md` gives them:
  - **Packaging:** run `make check-packaging` and resolve every failure; run `make
    check-architecture-change CHANGE=inject-site-pool-authority` (the change owns no row);
    `make check-agent-skills` is not owed, as the change touches no agent directory.
  - **End-to-end pipeline:** record the pipeline run the latest passing validation
    gathered, its result, and the scenarios that exercise the change —
    `e2e_pool_declared_modes`, `e2e_buy`, `e2e_deal`, `e2e_bare_metal_publication`,
    `e2e_bare_metal_deal`, `e2e_compute_dynamic_listings`, `e2e_credits_deal` — from that
    validation's record.
- [ ] 4.8 Promotion: write the design-promotion record in this file, and the permanent
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
- [ ] 4.9 Guidance placement: read the sections 4.8 added or rewrote in
  `package-layers.md` and `dependencies.md` against the layer test — the principle in
  `dependencies.md` must hold in any repository and name nothing of this one, with
  `engineering` and `dependencies` tags only — and run `make check-guidance`.
- [ ] 4.10 Documentation citations: run `make check-doc-citations
  CHANGE=inject-site-pool-authority` and resolve every match; then
  `change-workflow openspec validate inject-site-pool-authority --strict`.
- [ ] 4.11 Archival: `change-workflow openspec archive inject-site-pool-authority -y`,
  merging both deltas (no `--skip-specs`: neither `spec.md` was edited by hand for a
  requirement the deltas cover; the Evidence edits in 4.8 sit outside them).
