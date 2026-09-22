# Tasks — a pool declares what it advertises and whether it can be admitted against

No blocking dependency. Prerequisite for `unbacked-listing-publication`, which
wires the shared resolver into storefront projection ingestion (its task 4.1b); no
task here touches storefront code.

Acceptance boundary: both declarations exist, are required and validated on every
write path, every existing pool carries both, and one shared resolver exists for
consumers. Observable to operators only; no listing behaviour changes.

Rationale for every decision below is in `design.md`.

## 1. Declarations

- [x] 1.1 `advertisable_modes` shares `deliverable_modes`' shape rule through one
      private helper; `deliverable_modes`' behaviour and messages are unchanged.
- [x] 1.2 An empty advertisable declaration authorizes no mode.
- [x] 1.3 `capacity_backing` accepts `backed` and `unbacked` only; nothing is
      resolved to a default.
- [x] 1.3a Backing is fixed at creation on replace, patch, and document import
      (reported as `capacity_backing_immutable` on validate-only). A stored pool
      with no backing may be given one; that arises only in startup repair.
- [x] 1.3b Both tags are required on every write. Create and replace declare
      `policy_tags` as a required field; patch requires both only when it supplies
      `policy_tags`. Nothing is defaulted, preserved, or merged.
- [x] 1.3c `pool_declaration_problems` is the one owner of the declaration
      invariant — deliverable shape, both declarations, both cross-tag rules — used
      by the models, the service, document validation, the stored-state check, and
      the resolver.
- [x] 1.3d Canonical export emits both tags without export code changing.
- [x] 1.3e Document-import errors name each problem's entry and tag.
- [x] 1.4 Both tags travel create, replace, patch, bulk import, projection, and
      export on the existing policy-tag channel; the projection code is unchanged.
- [x] 1.5 `deliverable_modes` and every execution recheck are untouched.
- [x] 1.6 `market_resource_pools.hints` documents both declarations, both
      cross-tag rules, and why absence is reported rather than defaulted.

## 2. Cross-tag rules and shared resolution

- [x] 2.1 A backed pool's advertisable set is a subset of its deliverable set; a
      write breaking it from either side is refused, never repaired.
- [x] 2.2 `resolve_pool_declarations` returns `PoolDeclarations` or raises
      `PoolDeclarationError`, or `MissingPoolDeclarationError` when every problem
      is absence. Membership exists only as `PoolDeclarations.advertises`; backing
      is typed `CapacityBacking`. No public function reads advertisement from raw
      tags.
- [x] 2.3 An unbacked pool's advertisable set is independent of delivery.
- [x] 2.4 An unbacked pool's deliverable set must be empty; no site-side read was
      added.

## 3. Migration, seeding, and complete emission

- [x] 3.1 Provisioning migration `20260922_001_pool_advertisement_and_backing`
      overwrites both tags on every pool (advertisable = proved deliverable set,
      backing = `backed`), logs each at INFO, and raises `SchemaDriftError` on a
      malformed deliverable set.
- [x] 3.1a API-credits migration `20260922_004_pool_advertisement_and_backing` does
      the same, and its `default` seed writes both tags.
- [x] 3.1b Every administration, seed, and definition-document writer, and every
      test writing pools through those paths, carries both tags, including the e2e
      `register_e2e_pool` helper and the bare-metal seller quickstart. Exempt:
      fixtures constructing `ResourcePool` rows directly to exercise admission,
      scheduling, or fulfillment (chiefly `kit/site/tests/`), which read only
      `deliverable_modes` and cannot reach the startup check.
- [x] 3.2 Provisioning refuses to start, naming each pool, through the
      `verify-pool-declarations` step after the pool document import; a changed
      document lacking the tags is refused with nothing applied. API credits
      applies the same check after its migrations.
- [x] 3.3 Upgrade leaves every pool advertising what it delivered and admissible,
      proven across the `default` pool, a single-mode pool, a pool proving nothing,
      and a pool with opaque prior values.

## 4. Validation

- [x] 4.0 The kit's database-backed service test moved to `tests/integration/`;
      both test directories carry `__init__.py`, and `make test` runs both.
- [x] 4.1 Unit: declaration shape, cross-tag rules, resolver discrimination, and
      the pool models, including a malformed deliverable set.
- [x] 4.1a Library integration: identical validation across administration paths,
      immutability, path-named import errors, stored-state checks, and the
      document-import repair path.
- [x] 4.2 An unbacked pool naming the configuration-free `bare_metal.ansible`
      provider is created through the real administration API.
- [x] 4.3 Through the typed client, every write path round-trips explicit
      declarations, and create, replace, and patch omitting either tag are
      refused with 422 and the pool unchanged (rejection-path: status and state
      only, per `TESTING.md`).
- [x] 4.3a An old-format document fails validation per entry and imports nothing;
      export carries both tags and re-imports unchanged.
- [x] 4.4 A backed pool's widened advertisement and narrowed delivery are each
      refused with 422 and the pool unchanged.
- [x] 4.5 A malformed backing value and an unbacked pool that delivers are each
      refused with 422 and the pool unchanged.
- [x] 4.5a Changing backing through replace, patch, or import is refused with 400,
      the pool keeps its backing, and validate-only reports
      `capacity_backing_immutable`.
- [x] 4.6 Both services' migrations run against real databases written by the
      previous version, from each service's `tests/integration/`.
- [x] 4.6a Both services refuse to start on a pool without valid declarations;
      provisioning's changed-document refusal records no digest, and an unchanged
      document still starts.
- [x] 4.7 Every projected pool carries both declarations and resolves.
- [x] 4.8 The kit, fulfillment, site, provisioning, and API-credits suites pass
      against the rebuilt wheel; `make check-reinit` passes.
- [x] 4.9 Executor-default inventory: the only production reads of either tag are
      the two immutability checks, where an absent stored value permits supplying
      one and never resolves to a backing. No default argument, `or` fallback, or
      defaulted `.get` resolves an absent declaration.

### Review round

A code review was discussed finding by finding. Accepted and applied: required
`policy_tags` on create and replace; one owner of the declaration invariant, closing
a gap where a typed client could build a write with a malformed deliverable set;
membership only on resolved declarations with typed backing; status-only
rejection-path tests; the three real-database test files moved to
`tests/integration/`; the stale permanent Evidence citation corrected. Kept, with
the reason recorded in `design.md`: the missing-backing repair on every write path,
since no running service can hold such a pool. Migrations stay service-local.

### Findings outside this change's boundary

- No Make target runs `domains/apicredits/service/src/tests/`, so
  `test_migrations.py`, `test_keys_service.py`, and `test_api.py` are unrun by
  `make test` and `test-apicredits`. Unowned.
- No CI workflow selects the `e2e_pool_declared_modes` marker, so the deployed
  refusal of an undeclared offering mode never runs in the pipeline. Unowned.
- Provisioning's other real-database migration and startup tests sit under
  `tests/unit/`, contrary to `TESTING.md`'s levels. Unowned.
- `e2e-tests/tests/unit/test_hosted_public_boundary.py::test_buyer_deployment_mounts_separate_profile_state_and_credential`
  fails on `docker-compose.yml`, which this change does not touch. Unowned.
- `kit/site`'s ledger reads `ResourcePool` directly, contrary to
  `ARCHITECTURE.md`'s kit layers. Owned by `inject-site-pool-authority`, created
  at this change's closeout.

## 5. Closeout

- [x] 5.1 **Comment hygiene.** `make check-comment-hygiene` passes; touched
      comments state present rationale only.
- [x] 5.2 **Import placement.** Every import this change added is module-level.
      The one function-level import in a touched file,
      `PoolConfigValidationProblem` in the moved kit service test, is pre-existing
      content carried by the move.
- [x] 5.3 **Documentation compliance.** Normative behaviour went to
      `resource-pool-management/spec.md`; rationale to its companion
      `architecture.md`; the terms, the authority row, the pool paragraph, and the
      kit-layer exception to `ARCHITECTURE.md`; suite ownership to `TESTING.md`;
      operator startup behaviour to `DEPLOYMENT_AND_CONFIG.md` and the bare-metal
      quickstart. The second mode declaration belongs in the permanent map:
      `ARCHITECTURE.md`'s one-name-per-concept paragraph already named it.
- [x] 5.4 **Narrative compression.** This list records final behaviour, evidence,
      and destinations; rationale and alternatives live in `design.md`.
- [x] 5.5 **Roadmap currency** (`docs/development/ROADMAP.md`, Goal 7). This
      change's gap row is removed. The current state says the pool half exists —
      both declarations, required and migrated — while no storefront reads them.
- [x] 5.6 **Campaign index currency** (`openspec/changes/README.md`).
      - This change's row reads complete, awaiting archival.
      - `unbacked-listing-publication` is unblocked and records that it wires the
        shared resolver.
      - The POOLS campaign gains a row for `inject-site-pool-authority`, in design
        phase. One change directory was created and linked from the index and
        `ARCHITECTURE.md`'s kit layers; none was renamed or removed.
      - The dependency graphs are unchanged until archival.
- [x] 5.7 **Promotion.** The delta's four requirements were synced verbatim into
      `openspec/specs/resource-pool-management/spec.md`, each once, and its Evidence
      section lists the new and moved suites. `capacity-backed` and `unbacked` are
      in `ARCHITECTURE.md`'s Terms table at pool level; listing-level statements
      stay with `unbacked-listing-publication`. Promotion review found no passage
      in the permanent spec made stale; the replacement rule for omitted optional
      tags still holds, since both declarations are required rather than optional.
      - **`openspec validate --all --strict`:** 72 passed of 92. The original tree
        also passes 72; every outcome is identical except the new design-phase
        `inject-site-pool-authority`, which has no deltas yet, like the other
        design-phase changes. This change and `resource-pool-management` validate.
- [x] 5.8 **Documentation citations.** The change-scoped check passes for this
      change and for `inject-site-pool-authority`. The unscoped check reports the
      same 17 pre-existing failures as the original tree, none in files this change
      touches.
- [x] 5.9 **End-to-end pipeline.**
      - **Implementation run.** GitHub Actions `e2e` run `96787131769`, commit
        `5d140d6`: 113 passed, 3 skipped, 264 deselected. Provisioning applied
        `20260922_001_pool_advertisement_and_backing` and passed the
        `verify-pool-declarations` step; API credits applied
        `20260922_004_pool_advertisement_and_backing`; six pools were created
        through `register_e2e_pool` with no pool write refused.
      - **Post-review run.** The maintainer reports the pipeline passing on the
        tree carrying the review round.
      - **Not exercised.** `test_pool_declared_offering_modes.py` is deselected by
        marker in both runs; that refusal is proven in-process.

**Validation:**

| Suite | Result |
|---|---|
| `kit/resource-pools` (unit and integration) | 196 passed |
| `kit/fulfillment` | 176 passed |
| `kit/site` | 254 passed |
| Provisioning unit and integration | 931 passed |
| API credits `make test` | 34 passed |
| API credits `src/tests` (unrun by any target) | 32 passed |

`make test` passes on the maintainer's tree. Typing is unrun: no touched package
configures a type checker.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| `capacity-backed` / `unbacked` defined for pools; backing means an admission authority exists, not that hardware does | `docs/development/ARCHITECTURE.md#terms` |
| Pool advertisement authorization and capacity backing as an authority | `docs/development/ARCHITECTURE.md#authority-boundaries` |
| Advertisement is separate from delivery; an unbacked pool is kept out of capacity paths by its empty deliverable set | `docs/development/ARCHITECTURE.md#resource-pools`, `openspec/specs/resource-pool-management/architecture.md#advertisement-delivery-and-backing` |
| Advertisement authorization and delivery authorization are separate declarations | `openspec/specs/resource-pool-management/spec.md#requirement-pool-declared-advertisable-modes` |
| A backed pool's advertisable set is a subset of its deliverable set, enforced from both sides | `openspec/specs/resource-pool-management/spec.md#requirement-pool-declared-advertisable-modes` |
| An unbacked pool's deliverable set is empty, keeping it out of every capacity path without a site-side backing read | `openspec/specs/resource-pool-management/spec.md#requirement-pool-declared-capacity-backing` |
| A malformed backing value fails closed and never resolves to a default | `openspec/specs/resource-pool-management/spec.md#requirement-pool-declared-capacity-backing` |
| Backing is fixed at creation; a pool with no stored backing may be given one, which arises only in startup repair | `openspec/specs/resource-pool-management/spec.md#requirement-pool-declared-capacity-backing` |
| Both declarations are required on every write; create and replace require `policy_tags`; one validation owns delivery shape and both declarations | `openspec/specs/resource-pool-management/spec.md#requirement-required-advertisement-and-backing-declarations` |
| Seeded or stored pools lacking valid declarations stop service load | `openspec/specs/resource-pool-management/spec.md#requirement-required-advertisement-and-backing-declarations`, `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` |
| Readers of projected declarations resolve them through one shared resolver; membership only on resolved declarations | `openspec/specs/resource-pool-management/spec.md#requirement-shared-resolution-of-advertisement-and-backing-declarations` |
| A producer emitting these tags emits them on every pool it projects | `openspec/specs/resource-pool-management/spec.md#requirement-complete-emission-and-upgrade-derivation` |
| Existing pools are migrated to advertisable = proved deliverable set and `backed`, overwriting prior values | `openspec/specs/resource-pool-management/spec.md#requirement-complete-emission-and-upgrade-derivation` |
| Suite ownership for declarations, resolver, migration, and startup refusal | `docs/development/TESTING.md#pool-offering-mode-enforcement` |
| Migrations stay service-local, using kit vocabulary | Recorded in `design.md` (temporary; implementation guidance only) |
| The site ledger's direct pool reads | Handed to `inject-site-pool-authority` (temporary; not promoted) |
| Storefront ingestion wires the resolver | Handed to `unbacked-listing-publication` task 4.1b (temporary; not promoted) |
