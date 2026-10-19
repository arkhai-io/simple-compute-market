# Tasks

Replanned the original wholly unchecked sections against the reviewed design and
`reviews/14-design.triage.md` after its owner-passed gate. No completed task is
removed or rewritten. All implementation tasks below answer to D1–D9/D11, the
eight delta requirements, and the validation/closeout obligations in
`openspec/README.md#plan-closeout-requirements`, `openspec/config.yaml`, and
`docs/development/TESTING.md`. D10 is documentation placement, not a further gate.

Order: 1 → 2 → 3 → 4 → 5. There is no unlanded change dependency. Do not edit
permanent documentation before behavior is verified and closeout begins.

## 1. Put asking-rate structure in contracts

Deliver the contracts-owned structural checks and explicit lightweight dependency
(D11; “Provider validation remains service-owned”), preserving resolver behavior.
This section does not yet add model refusals or change HTTP statuses.

Files: add `kit/resource-pools-contracts/src/market_resource_pools_contracts/asking_rates.py`;
update that package's `__init__.py`, `pyproject.toml` and generated locks; adapt
`kit/resource-pools/src/market_resource_pools/asking_rates.py`, `__init__.py` and
`service.py`; split structural coverage from `kit/resource-pools/tests/unit/test_asking_rates.py`
into `kit/resource-pools-contracts/tests/unit/test_asking_rates.py`.

- [x] 1.1 Move `ASKING_RATES_POLICY_TAG`, `asking_rate_entry_problems`,
  `validate_asking_rates` and their structural helpers to contracts. Declare
  `arkhai-kit-capability-shape` in dependencies and the package allowlist (D11).
  Verify absent/empty declarations, malformed fields and accepted opaque periods
  through contracts unit tests, with no authority/provider imports.
- [x] 1.2 Point the authority's service, resolver and existing exports at the shared
  implementation (D11); retain one definition and the existing resolution API.
  Keep domain callbacks, accepted publication periods, precedence and rate carriers
  in the authority. Verify the authority's resolver unit tests still prove exact
  matching, override precedence and unreadable-input behavior.
- [x] 1.3 Refresh wheels and generated locks using `make lock`, as required by
  `docs/development/BUILD_AND_PACKAGING.md`; do not hand-edit locks or source-share
  siblings. Review changes to the contracts lock and every lock resolving its
  wheel: `core/storefront`; `domains/apicredits/{service,storefront}`;
  `domains/bare_metal`, its buyer, provisioning adapter and storefront;
  `domains/vms/{buyer,domain,storefront,provisioning/adapter}`; `e2e-tests`;
  `kit/{capacity-publication,fulfillment,pool-overrides,resource-pools,resource-pools-client,resource-pools-contracts,site,site-client,storefront}`;
  and `provisioning/compute`, its ansible distribution and service. Evidence:
  generated lock diffs, successful refreshed imports and `make check-packaging`.
- [x] 1.4 **Verification checkpoint.** Unit: contracts `test_asking_rates.py` and
  authority `test_asking_rates.py`. Library integration: existing
  `kit/resource-pools/tests/integration/test_resource_pool_service.py` exercises
  raw-document checks using the relocated implementation. Run
  `make -C kit/resource-pools-contracts test`, `make -C kit/resource-pools test`,
  `make check-architecture` and `make check-packaging`; record results. Keep
  `py.typed` and wheel exports intact and run any existing typing check exposed by
  these projects, or disclose that neither project defines one. Run
  `make check-comment-hygiene` and review added imports/comments before completion.

**Deployed coverage:** existing `e2e_vm_introduction` and
`e2e_bare_metal_publication` exercise valid asking-rate declaration/resolution and
publication. They do not prove structural rejection or module placement. No new
system scenario is owed for this pure relocation; unit and library evidence own it.

**Section 1 implementation notes:**

- Contracts own the structural helper and export it; authority root/module exports
  remain supported and resolver semantics are unchanged. Contracts unit suite:
  212 passed, including the relocated structure matrix. Authority unit/library
  suite: 121 passed, including real-SQLite document validation and resolver tests.
- Removed the authority's newly unused direct shape dependency as required by
  dependency discipline; source and tests no longer import that distribution.
  `make lock` regenerated the contracts lock and 23 consumer locks, relocating this metadata without
  introducing a new installed distribution. No lock was hand-edited.
  Full tests exposed two release-guide dependency-table drift failures; corrected
  only the two package dependency cells in `docs/development/RELEASING.md`.
  This keeps release metadata accurate; behavior/rationale promotion stays in 5.
- Wheel inspection confirms contracts ship the structural module and `py.typed`;
  refreshed imports identify one contracts-owned helper through all exports.
  Neither project's Makefile/pyproject exposes a typing check.
- Final `make check-packaging` passed, including architecture with zero warnings.
  `make test` passed all aggregate targets, including 954 release-tooling tests
  and Helm rendering/loader checks; the rerun resolved both release-guide
  failures. It retains existing suite skips/warnings, not new skipped checks.
  Focused package targets passed (contracts 212 unit; authority 121 unit/library
  integration). Comment hygiene, scoped citations, change index and whitespace
  checks passed. No agent skill files changed.
- Fresh-context compliance review found one workflow issue: the index still
  carried its pre-implementation phase and round-agreement note. Corrected both;
  the reviewer confirmed no remaining guidance violations or overstated evidence.
  No findings were declined. The reviewer did not independently rerun suites.
- Handoff: model validation/HTTP status changes remain in section 2; provider
  immutability and handler deletion remain in sections 3/4. Permanent promotion
  remains in section 5. Existing deployed markers were confirmed in e2e tests:
  `e2e_vm_introduction` and `e2e_bare_metal_publication` exercise valid flows,
  not structural rejection or module placement. They have not run locally.

## 2. Reject malformed hints in typed models and API bodies

Deliver model-owned hint checks and HTTP 422 rejection (D6/D11; “Typed pool models
validate policy hints” and “Provider validation remains service-owned”). The
models are the lower-level change; service and API tests verify their integration.

Files: `kit/resource-pools-contracts/src/market_resource_pools_contracts/pools.py`
and its existing `tests/unit/test_pool_models.py`; authority `service.py` and
`tests/integration/test_resource_pool_service.py`; provisioning service
`tests/integration/test_pools_api.py`. Shared hint definitions stay in contracts.

- [x] 2.1 Extend the existing model validators to call declarations plus all five
  shared hint checks (D11). Check tags on create/replace and only when supplied
  on patch. Extend contracts unit tests with the complete invalid/valid hint
  matrix, omitted patch tags, opaque unknown tags and structurally valid
  domain-specific values. Verify construction fails before any transport call.
- [x] 2.2 Remove `_require_valid_policy_tag_hints` and its duplicate calls from
  individual service methods (D6/D11). Keep raw-document validators, stable codes
  and paths, handler-registry validation and provider-config normalization.
  Update affected library tests to put exhaustive model refusals at model level
  while retaining document/state evidence. Verify invalid YAML hints remain
  structured validate-only problems and HTTP 400 import refusals.
- [x] 2.3 Update provisioning API tests for the accepted status change (D11).
  Through canonical clients, exercise representative rejection on create, replace
  and tag-supplying patch using deliberately malformed construction per
  `docs/development/TESTING.md`'s rejection-path exception. Assert HTTP 422 and
  unchanged stored state, not validation-response field names. Keep valid hint
  round trips and provider/configuration HTTP 400 refusals covered. Evidence:
  `provisioning/compute/service/tests/integration/test_pools_api.py` passes.
- [x] 2.4 **Verification checkpoint.** Unit: contracts model/hint suites.
  Library integration: pool service against real SQLite. Application integration:
  `test_pools_api.py` through canonical clients and the real app. Run
  `make dist-ci`, `make -C kit/resource-pools-contracts test`,
  `make -C kit/resource-pools test`, `make -C provisioning/compute/service test`
  and `make check-packaging`. Run `make check-comment-hygiene` and review touched
  imports/comments; record all results and any unavailable typing target.

**Deployed coverage:** `e2e_listing_shapes`, `e2e_vm_introduction` and
`e2e_bare_metal_publication` exercise valid shape/pricing/rate hint flows. No
existing marker proves malformed-hint HTTP 422. No new system test is owed:
request-model rules and a single-service error boundary belong to unit and
application integration tests, not duplicated cross-service scenarios.

**Section 2 implementation notes:**

- Create/replace and tag-supplying patch validate declarations and all five
  shared hint checks in contracts. The full contracts unit target passed:
  375 tests, including the invalid/valid three-model matrix, aggregate problems,
  omitted patch tags, opaque tags and domain-owned shape/period/pricing values.
  Ordinary malformed construction raises before a caller can dispatch the model.
- Removed the service helper and its individual-write calls. Raw document
  validators and provider normalization are unchanged. Authority unit/library
  target passed: 103 tests, including real-SQLite document problems and failed
  import preserving metadata/configuration and an omitted pool's enabled state.
  Prior direct-service tests bypassing model construction were removed; that
  unsupported path no longer receives duplicate model checks (D11).
- Provisioning service target passed: 675 unit and 455 application integration
  tests. Its pool API tests use canonical clients and explicit rejection-path
  `model_construct` bodies for create, replace and patch: HTTP 422 and preserved
  state. Valid five-hint writes round-trip; malformed raw documents retain
  structured validate-only problems and HTTP 400 on import. Unknown-provider
  and invalid provider-configuration HTTP 400 coverage stays in the suite.
- `make dist-ci` and final `make check-packaging` passed, including architecture
  with zero warnings. Full `make test` passed all aggregate targets, including
  954 release-tooling tests and Helm rendering/loader checks; existing suite
  skips/warnings remain disclosed in its output. Comment hygiene, scoped
  citations and whitespace passed. No dependencies/locks or skill files changed
  in this section; none of the three projects exposes a typing target.
- Fresh-context compliance review found no guidance violations or overstated
  evidence; no fixes or declined findings. The reviewer did not rerun suites.
- Handoff: source/helper validators deliberately retain their accepted semantics,
  including arbitrary domain vocabulary and unknown tags. No new provider or
  backing comparison is introduced here; section 3 owns stored-state refusal,
  and section 4 owns handler cleanup. Existing deployed markers
  `e2e_listing_shapes`, `e2e_vm_introduction` and `e2e_bare_metal_publication`
  cover valid hint flows only; they have not run locally and prove no HTTP 422.
  Permanent promotion remains in section 5.

## 3. Enforce immutable provider across API and document administration

Deliver shared provider/backing comparisons, preserved state on refusal, no-op
provider patches and atomic document/startup rejection (D1/D3–D9; “A pool's provider
is fixed at creation”, “Shared validation of pool immutability” and “Documents
report immutable providers atomically”). Depends on the validated models in 2.

Files: authority `service.py`, new
`kit/resource-pools/tests/unit/test_pool_immutability.py`, and
`kit/resource-pools/tests/integration/test_resource_pool_service.py`; contracts
`pools.py` for the patch field description; provisioning service
`tests/integration/test_pools_api.py` and `test_pool_declaration_startup.py`.
Production startup importer/controller semantics remain unchanged unless wiring
needed to use the shared refusal is demonstrated by these tests.

- [x] 3.1 Implement one pure stored/proposed comparison for provider and backing,
  returning field-specific problems (D5/D6). Replace the duplicated backing
  comparisons with thin API/document adapters. Preserve backing repair when no
  value is stored, omit-field patch behavior, both problem codes and submitted
  source indices. Unit evidence: provider/backing equal/different combinations,
  repair, stable messages and codes; no database collaborator needed.
- [x] 3.2 Apply that comparison before any mutation in replace and patch (D1/D3–D7).
  Remove swap/deletion branches from these paths; an equal provider alone must
  perform no config write, while same-provider config edits retain existing
  secret semantics. Document `PoolUpdate.provider`'s restriction. Library
  evidence: complete metadata/config preservation, same-provider edits, provider
  no-op and omitted tags, using a recording injected handler and a real database.
- [x] 3.3 Apply the same comparison in validate-only and session-scoped import
  before reconciliation application (D1/D5/D6/D8). Remove import's swap/deletion
  branch. Library evidence: indexed `provider_immutable`, both immutable fields
  reported together, no diff, all-or-nothing valid-entry/omitted-pool effects,
  new entries accepted and backing repair preserved. Request/provider-config
  failures keep their existing phase order and import detail text shape.
- [x] 3.4 Add application-integration cases in `test_pools_api.py` (D1/D3–D8):
  otherwise-valid requests against registered providers receive HTTP 400, preserve
  all state and explain the second-pool path. Cover replace, patch, same-provider
  edit/no-op, document validate/import and unchanged export. Canonical clients own
  route/body/response shapes. Assert no handler write for equal-provider-only patch.
- [x] 3.5 Extend `test_pool_declaration_startup.py` (service integration with real
  SQLite, mounted file and real startup importer) for a changed-provider document
  (D8). Verify failure names the entry, no entry/config change lands, the prior
  digest is unchanged, another startup retries, and correction can succeed;
  unchanged-document skip stays covered. No new state/digest mechanism is needed.
- [x] 3.6 Carry the design audit's migration evidence into the implementation note
  (D9), checking no fixture or caller introduced a provider-swap dependency.
  Cite the site-capacity requirement and existing
  `kit/site/tests/integration/test_ledger.py` drain/race tests plus
  `provisioning/compute/service/tests/integration/test_host_pool_moves_api.py`
  for the distinct host hook. Do not add a pool-level guard or duplicate those
  authorities' tests. Verify the refusal says “migrate its members”.
- [x] 3.7 **Verification checkpoint.** Run unit/shared-comparison tests, library
  pool-service integration and the named application/startup suites, followed by
  `make dist-ci`, `make -C kit/resource-pools-contracts test`,
  `make -C kit/resource-pools test`, `make -C provisioning/compute/service test`
  and `make check-packaging`. Run `make check-comment-hygiene` and inspect imports
  and comments; record evidence before this section is complete.

- [x] 3.8 **19 V1 / 20 V1 — document-created default.** In provisioning service
  `db/database.py`, `db/migrate.py` and `db/migrations.py`, distinguish a genuinely
  empty database from an existing schema. With a configured pool document, defer
  the empty database's default creation to ordinary atomic startup import before
  inventory. Preserve existing host backfill and no-document VM bootstrap. Update
  the bare-metal fixture's explanation. No provider-swap exemption is allowed.
- [x] 3.9 **19 V1 / 20 V1 — VM identity.** Register `vm.ansible` in the VM bundle
  and handler; update current VM callers, API fixtures and Helm examples. Append
  a migration of old pool/fulfillment provider columns, preserving configuration,
  members, state, IDs and accepted envelopes. Keep historical backfill usable for
  both spellings. Update `docs/seller-quickstart.md` operator guidance; no runtime
  alias is required. The Ansible tool/readiness component retains its own name.
- [x] 3.10 **19 V1 / 20 V1 — regression evidence.** Extend
  `test_pool_declaration_startup.py` with real mounted-fixture/file-backed SQLite
  creation, repeat migration/startup and refused later provider changes. Add
  `tests/integration/test_vm_provider_identity_migration.py` for existing VM state
  preservation, unaffected bare-metal rows and idempotence. Keep real legacy
  backfill-to-teardown coverage passing under the canonical identity. Existing
  legacy-host migration evidence must remain green with a configured document.
- [x] 3.11 **19 V1 / 20 V1 — verification and handoff.** Rebuild wheels; run VM
  adapter, provisioning service, affected e2e unit/configuration and chart targets,
  `make test`, packaging, architecture, hygiene, citations, index, task and strict
  OpenSpec checks. Record a fresh-context compliance review against `a3bd6b1d`,
  commit the accepted fixes without pushing, and require fresh deployed validation.

**Deployed coverage:** no existing pytest marker submits a provider change or
changed-provider startup document. No new system scenario is owed for these
single-authority transactions. `multi_registry`, `e2e_listing_shapes`,
`e2e_deal`, `e2e_vm_introduction`, `e2e_bare_metal_publication` and
`e2e_bare_metal_mock_deal` exercise ordinary pool-backed flows after deployment;
their green result is regression evidence, not direct proof of immutability.

**Section 3 implementation notes:**

- One pure `pool_immutability_problems` comparison returns relative fields, codes,
  stored/supplied values and messages. Individual writes raise its first message;
  documents prefix all problems with submitted entry indices. Provider has no
  repair allowance; missing backing retains its repair allowance. Omitted patch
  fields compare using stored values. Provider registration/configuration checks
  remain service-owned and precede provider comparison; document request problems
  still prevent stored-state comparison. The backing problem code/message remains
  unchanged. Contracts describe the retained patch provider restriction.
- Authority unit/library target passed: 124 tests. The new pure unit matrix
  covers both fields independently/together, missing backing repair, removal and
  exact messages. Real-SQLite library integration, with recording injected
  handlers, proves refused replace/patch preserve all pool fields (including
  timestamps) and configuration without handler writes; equal-provider-only and
  omitted-tag patches write no configuration. Same-provider edits still succeed.
  Document tests cover source index 2, both problems/no diff, ordinary,
  validate-only and caller-session import refusal before valid-entry creation,
  mutable updates or omitted-pool disablement; new-provider entries and the
  existing backing repair tests pass. Unknown-provider/configuration precedence
  remains covered. Injected fake configurations are in memory; the database is
  real, and refusal must occur before any handler write.
- Focused `test_pools_api.py` and `test_pool_declaration_startup.py` passed
  55 tests together. The API cases are application integration; canonical clients prove
  registered-provider replace/patch HTTP 400, explanatory member-migration text,
  complete preserved responses/export, document problems/import atomicity and
  same-provider edit/no-op behavior. A recording real Ansible handler injected
  through the controller's resolved-service seam proves the no-op does not write.
  Full provisioning target passed: 675 unit and 460 integration tests.
- Startup evidence is service integration against file-backed SQLite, a mounted
  temporary document and the real importer, not a running application. A changed
  provider document fails twice naming `pools[1].provider`, leaves every pool and
  configuration plus the prior digest unchanged, and creates no valid preceding
  entry. A correction succeeds and records its digest; unchanged-document skip
  and the existing declaration/startup-order tests remain green. No startup or
  controller production change was needed.
- Migration audit: the supported route is a second pool and explicit member
  reassignment. `openspec/specs/site-capacity/spec.md`'s “A capacity resource does
  not move pools under live obligations” owns the capacity guard. Existing
  `kit/site/tests/integration/test_ledger.py` tests
  `test_a_held_resource_cannot_change_pool_until_it_is_drained`,
  `test_the_lock_is_held_from_the_obligation_check_through_the_commit` and
  `test_a_reservation_racing_a_pool_move_never_survives_against_the_moved_resource`
  cover drain and serialization. Separately,
  `provisioning/compute/service/tests/integration/test_host_pool_moves_api.py`
  proves the host hook refuses a relay-changing move under tunnel leases and
  permits a drained host move. A host move preserving its relay is not the
  capacity-resource move. No guard or duplicate member tests were added.
  The initial source/caller audit missed the bare-metal bootstrap fixture;
  validation 19/20 corrected that conclusion, and appended tasks 3.8–3.11 own
  its remedy. The old kit swap test now proves refusal. The refusal explicitly
  says “migrate its members”.
- Deployed coverage confirmed in `e2e-tests/pyproject.toml` and scenario callers:
  `multi_registry`, `e2e_listing_shapes`, `e2e_deal`, `e2e_vm_introduction`,
  `e2e_bare_metal_publication` and `e2e_bare_metal_mock_deal` exercise ordinary
  pool-backed flows, not provider refusal. None submits a provider change or
  changed-provider startup document. No new system scenario is owed under the
  test-level boundary; deployed/Helm pipeline evidence remains for validation.
- `make dist-ci`, contracts (375 unit), pool (124 unit/library) and provisioning
  service targets passed. Comment hygiene, scoped documentation citations,
  change index, task structure and whitespace checks passed. Full `make test`
  passed every aggregate target, including 954 release-tooling tests and Helm
  render/loader checks, retaining existing suite skips/warnings. Final
  `make check-packaging` and standalone `make check-architecture` passed all
  four architecture checks with no warnings. No dependency/lock or skill files
  changed; the three affected projects expose no typing target.
- Fresh-context compliance review found no guidance violations or overstated
  evidence. No findings were fixed or declined. The reviewer did not rerun
  suites. Imports added/touched are at module level and comments describe
  current invariants. The campaign row remains in implementation, with section 4
  next; its independent dependency node is unchanged. Deployed scenarios have
  not run locally and are not counted as provider-refusal proof.
- Handoff: section 4 removes the still-present deletion protocol, handler/fake
  methods, direct deletion test and composition required hook together. This
  section removes only the three production call sites. Configuration writes
  remain provider-owned and same-provider semantics are unchanged. Permanent
  behavior/rationale promotion remains in section 5; no member authority changed.

**Implementation round 1 — 19 V1 / 20 V1:**

- The owner accepted document-created defaults and the canonical VM identity.
  A genuinely empty database with a configured pool document now defers default
  creation to atomic startup import, after contributed definitions and before
  inventory. Existing databases retain host backfill, and no-document bootstrap
  retains the configured VM default. A missing or invalid document fails startup;
  a later document cannot change the provider. The actual bare-metal development
  fixture remains inert and uses `bare_metal.ansible` without a VM playbook.
- VM bundle/handler registration, current service/API/e2e callers and Helm
  examples use `vm.ansible`. The appended migration changes only historical
  `ansible` provider columns in pools and fulfillment records. Configuration,
  host membership, IDs, state, and operation envelopes remain unchanged. The
  historical compiler accepts both names and preserves the candidate identity;
  existing historical migrations still recognize their original inputs.
  Current operation kinds already use `vm.ansible.*` and are unchanged. No
  runtime alias or compatibility promise for old VM definition files is added.
- Library/service integration evidence uses real SQLite: fresh startup reads
  the actual bare-metal mounted fixture and a VM document, repeated migration
  before first startup creates no implicit pool, and repeated startup skips the
  unchanged digest. Subsequent provider changes are refused with state/digest
  preservation; missing/invalid documents create neither default nor digest.
  Existing-schema migration is parametrized with/without a configured document
  and retains legacy host membership and VM configuration. A targeted upgrade
  test compares complete pool/configuration/host/fulfillment rows, changing only
  VM provider names, leaving bare-metal rows alone and proving idempotence.
  The existing backfill-to-teardown test also runs the identity migration before
  consuming the result through the canonical provider registration.
- The touched database and backfill-convergence tests moved from `unit/` to
  `integration/`, with their permanent evidence citations updated. This is test
  placement correction, not behavior promotion. The VM adapter focused target
  passed 29 unit tests. Provisioning's first successful focused run passed
  662 unit and 476 integration tests before the final missing/invalid-document
  cases and legacy-host parameterization; the aggregate run below includes them.
- Deployed coverage: `e2e_vm_introduction`, `e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_listing_shapes` and `multi_registry` exercise canonical VM pool creation
  or bootstrapping; `e2e_bare_metal_publication`,
  `e2e_bare_metal_introduction` and `e2e_bare_metal_mock_deal` start from the
  bare-metal document-created default. These scenarios await validation of the
  fix commit. None is counted as direct migration or provider-refusal proof.
- The aggregate exposed the previously recorded payment-settlement test race:
  the delivery fake could reach `ready` before the response asserted
  `provisioning`. The test now uses its existing started/release events, with a
  bounded wait and unconditional release, to hold the intended observable
  state. Production payment behavior is unchanged. The focused payment
  application-integration suite passed all 22 tests; the final aggregate rerun
  includes that correction.
- Final `make test` passed all aggregate targets: provisioning 662 unit and
  479 integration tests, VM storefront 411 application integration tests, e2e
  unit/configuration targets, 954 tooling tests and Helm render/loader checks.
  Existing aggregate skips/warnings remain (two core tests and one storefront
  collection skip); they are not new passes. VM adapter's focused unit target
  passed 29 tests. Contracts' final focused unit target passed 375 after the
  user-facing provider example changed; no contract shape or semantics changed.
- `make dist-ci`, final `make check-packaging` and standalone architecture checks
  passed, with zero architecture warnings. Hygiene, scoped citations, change
  index, task structure, whitespace and pinned OpenSpec 1.14.0 strict validation
  passed. The offline npm launcher lacked its registry cache entry; the verified
  cached 1.14.0 executable passed directly. A normal sandbox build could not
  write the shared uv cache; approved ordinary escalation ran the same build
  successfully. No call was denied. No dependencies changed, so no lock refresh
  was needed; no skill files changed and affected packages expose no typing
  target.
- Fresh-context compliance checked the complete diff against `a3bd6b1d`, including
  untracked tests, migration ordering, test placement, documentation ownership
  and evidence claims. It found no guidance violations or overstated evidence;
  no findings were declined. The reviewer did not rerun behavioral suites.
  Its reminder about the adjacent site-capacity provider example is now named
  in the promotion map. All 13 existing test functions in the two relocated
  modules are preserved without loss or duplication.
- Handoff: the accepted fix is committed without pushing. Fresh validation must
  run the full pipeline and served Helm scenarios against that fix; prior run
  39129737284 is failure evidence for its parent, not evidence for this fix.
  Another independent implementation review is recommended because bootstrap
  and provider identity changed centrally. The owner has not passed the gate.
  Permanent bootstrap/provider rationale joins the resource-pool spec and
  architecture, repository Resource pools, and deployment definition-document/
  migration guidance at closeout. Current operator cutover guidance is already
  in `docs/seller-quickstart.md`; broader architecture promotion is deferred.

## 4. Remove configuration deletion from handlers and runtime composition

Deliver the reduced handler contract end to end (D2/F1; “Configuration handlers
follow the non-destructive lifecycle”). Depends on section 3 eliminating every
production deletion call; remaining changes are one mechanical interface slice.

Files: `kit/resource-pools/src/market_resource_pools/pool_config_handler.py`;
VM adapter `services/ansible_pool_config_handler.py`; bare-metal adapter
`services/bare_metal_pool_config_handler.py`; family kit `composition.py`;
`provisioning/compute/tests/unit/test_composition.py`; service
`tests/integration/test_ansible_pool_config_handler.py`; fakes in
`kit/resource-pools/tests/integration/test_resource_pool_service.py`,
`kit/fulfillment/tests/integration/test_scheduler_host_requirement.py`,
`kit/fulfillment/tests/unit/{test_fulfillment,test_fulfillment_persistence,test_scheduler}.py`.

- [x] 4.1 Remove `delete_config` from protocol, both handlers and every test fake;
  remove its direct handler-deletion test (D2). In the same change remove it from
  `_validate_pool_config_handler`'s required hooks (accepted 14-design F1).
  Verify a repository search finds no remaining code requirement/call and
  same-provider replace/read behavior still passes.
- [x] 4.2 Extend `provisioning/compute/tests/unit/test_composition.py` for F1:
  deletion-free handlers with the remaining hooks compose successfully, while
  missing/non-callable remaining required hooks are still refused. Preserve
  provider identity checks and duplicate registration behavior; do not broaden
  the accepted runtime interface. Unit tests prove the observable composition.
- [x] 4.3 Verify the real service composes VM and bare-metal adapters after removal
  (D2/F1), using existing service composition/startup and pool application tests;
  retain the disabled-pool configuration read case. Evidence: named handler/pool
  integration suites and `tests/unit/test_authority_composition.py` pass, proving
  the runtime guard accepts actual reduced implementations.
- [x] 4.4 **Verification checkpoint.** Rebuild with `make dist-ci`; run
  `make -C kit/resource-pools test`, `make -C kit/fulfillment test`,
  `make -C provisioning/compute test`,
  `make -C domains/vms/provisioning/adapter test`,
  `make -C domains/bare_metal/provisioning/adapter test`, and
  `make -C provisioning/compute/service test`. These cover units, real-database
  library/handler integration and real-app pool administration. Run
  `make check-architecture`, `make check-comment-hygiene`, and
  `make check-packaging`; inspect every touched local import/comment before the
  pre-closeout review, resolving code issues here rather than at closeout.

**Deployed coverage:** `e2e_deal`/`e2e_deal_buyer_cli` and
`e2e_bare_metal_mock_deal` run VM/bare-metal stacks whose startup composes these
handlers; they expose a retained deletion-hook requirement. No dedicated
`delete_config` marker exists or is owed. Full pipeline/Helm evidence is obtained
by validation, and closeout confirms it against the latest committed code.

**Section 4 implementation notes:**

- Removed the standalone deletion operation from the protocol, both real
  handlers, runtime composition's required hooks and every fake. Removed the
  direct Ansible deletion test and the recording fake's obsolete deletion
  bookkeeping/assertions from section 3. Its refused-write tests still compare
  complete pool/configuration snapshots and replacement calls. A repository-wide
  Python search finds no remaining `delete_config` declaration, call or
  requirement. Same-provider replacement and both read levels remain unchanged.
- Family composition unit tests accept the deletion-free fake by object
  identity and reject each of the four remaining required hooks when absent or
  non-callable (eight cases). Existing provider identity, provider/handler pairing
  and duplicate-registration cases remain green. The runtime required-hook set
  otherwise stays unchanged; execution reads remain on the protocol and handlers.
- Focused targets passed: pool authority 124 unit/library integration;
  fulfillment 171 tests; compute family 231 tests; VM adapter 29 unit tests
  (including its inventory-view suite); bare-metal adapter 40 tests; provisioning
  service 675 unit and 459 integration tests. Fulfillment and compute include
  real-database library integration. Correction after fresh-context review:
  the 38 touched database-backed fulfillment cases now live in `integration/`
  (34 scheduler, three ledger persistence, one acceptance concurrency), with their
  fixtures/helpers. The two isolated mocked persistence cases retain unit
  placement, dropping only their unused real-database fixture dependency.
  Other cases in the mixed unit modules are unchanged.
- The service target includes `tests/unit/test_authority_composition.py`, whose
  real container composes both adapter bundles, plus the handler persistence,
  startup and pool API integration suites. Handler persistence/startup cases
  exercise real SQLite without a running app; pool API cases use canonical
  clients against the real app. The existing disabled-pool GET case now also
  asserts its returned configuration and playbook remain available. No new
  startup or persistence mechanism was needed.
- `make dist-ci` and final `make check-packaging` passed, including all four
  architecture checks; standalone `make check-architecture` also passed without
  warnings. Full `make test` passed every aggregate target, including 954
  release-tooling tests and Helm render/loader checks. The aggregate retains
  existing skips (two core tests and one storefront collection skip) and
  warnings; deployed scenarios and cluster Helm tests are separate and unrun.
  Comment hygiene, scoped documentation citations, task structure, change-index
  and whitespace checks passed. No dependency, lock or skill file changed;
  none of the six focused projects exposes a typing target.
- Deployed marker coverage confirmed in `e2e-tests/pyproject.toml` and scenario
  modules: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal` start
  stacks composing these handlers. They are startup/regression evidence once
  deployed; none is a dedicated deletion-hook scenario. No new system scenario
  is owed for this interface removal. Deployed pipeline and cluster Helm tests
  have not run locally and remain validation's responsibility.
- Fresh-context review found the explicit requirement to move touched
  real-database library tests out of `unit/`. Fixed the 38 cases above, moved
  their imports to module level and rewrote historical comments/docstrings in
  the moved regions as current constraints. Only scheduler evidence paths in
  the fulfillment and site-capacity permanent specs changed; behavior promotion
  remains at closeout. The relocated provider fake initially failed because its
  host requirement must be a class-level boolean; the explicit mock subclass
  fixes that setup, and the focused fulfillment rerun passes all 171 tests.
  A second fresh-context review identified inherited future-work narration
  and timing/order assumptions in the moved scheduler race case. Replaced the
  prose with its current invariant and the race controls with explicit
  transaction-attempt/open events, a commit event set inside serialization,
  bounded futures and durable pool/backing assertions. Its 171-test focused
  rerun passed; the reviewer confirmed all findings resolved, with no remaining
  guidance violations or evidence overstatements. None was declined. Test-name
  inspection confirms all 79 functions across the three original modules are
  preserved without duplication. The reviewers did not rerun behavioral suites.
- The repeated aggregate initially failed in the unchanged VM storefront test
  `test_settlement_is_pending_until_a_verified_receipt_then_delivers_once`:
  expected `provisioning`, observed `ready`. Its delivery fake completes without
  using its available event gates, while the coordinator starts delivery before
  awaiting the response's database read; fast completion can precede that read.
  The normal-permission focused rerun passed (one test); no unrelated source or
  test change was made. A sandboxed diagnostic attempt stalled during fixture
  setup and was explicitly interrupted; it is not counted as a passed test.
  The final stable-tree `make test` passed, including that test and all 411
  VM storefront integration tests, all remaining aggregate targets, 954
  release-tooling tests and Helm render/loader checks. Final
  `make check-packaging` and standalone `make check-architecture` passed;
  hygiene, scoped citations, task structure, change-index and whitespace checks
  passed again. Existing aggregate skips/warnings remain as disclosed above.
- The owner checkpointed the section's code and preliminary notes in
  `0f8232cf` ("Section 4 pre-verification") during the session interruption.
  Recovery verified the exact diff and the completed full-test process's zero
  exit status, preserving that checkpoint. The section-completion commit records
  final verification and the handoff without amending the owner's commit.
- Handoff: sections 1–4 are ready for the agreed single implementation round.
  Permanent behavior/rationale and Evidence promotion remain in section 5 after
  review; no member authority, provider registration semantics, dependency or
  configuration schema changed. The campaign stays in implementation and its
  independent dependency node is unchanged.

## 5. Closeout

Confirm and promote the verified design, then archive last; D1–D9/D11 and all
requirements. All eleven parts below follow
`openspec/README.md#plan-closeout-requirements` in order. No code changes occur
here: a needed code/lock fix returns to implementation. General guidance is an
explicit owner question, not a prescribed edit.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read
  comments/docstrings added by sections 1–4 for current-system rationale; no
  change IDs, task numbers or migration narration. Record results; needed code
  corrections return to implementation.
- [ ] 5.2 **Import placement — confirm.** Check imports added/touched by sections
  1–4 are at module level unless a verified cycle or recorded deliberate lazy-load
  reason requires otherwise. Record the inspection, returning code corrections
  to implementation rather than changing them during closeout.
- [ ] 5.3 **Documentation compliance.** Audit D1–D9/D11, review F1/F2 and all eight
  requirements against the promotion map below and the actual code. Ask the owner
  whether to promote general validation-order guidance and its wording/home;
  record the decision without presuming an edit. Confirm that subsystem-local
  validation behavior and boundaries are still promoted regardless. Evidence:
  a disposition for every material decision and the deferred guidance question.
- [ ] 5.4 **Narrative compression.** Preserve final behavior, validation evidence,
  limitations and promotion destinations; move any remaining durable rationale
  into `design.md` before compressing task notes. Verify no implementation history
  or accepted rationale is lost and permanent prose describes current behavior.
- [ ] 5.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1, remove the
  existing provider-swap gap owned by this change and state the now-immutable
  provider in current-state prose. Record that exact destination; do not claim
  the earlier plan's incorrect “no roadmap gap” disposition.
- [ ] 5.6 **Campaign index currency.** Update this change's Goal 1 row and check its
  independent graph node in `openspec/changes/README.md`; preserve the broadened
  acceptance boundary and record graph changes or an explicit unchanged result.
  Run `make check-change-index`. Leave other rows' dependencies for archive
  cleanup after the closeout gate.
- [ ] 5.7 **Packaging.** Confirm `make check-packaging` and
  `make check-architecture-change CHANGE=fix-resource-pool-provider-at-creation`
  pass against the latest committed implementation. If this change actually
  touches agent/permission skills later, also run `make check-agent-skills`;
  otherwise record that it did not. Code, dependency or lock failures return to
  implementation. Record checks rather than repairing production code here.
- [ ] 5.8 **End-to-end pipeline.** Confirm the latest validation record's full
  pipeline and Helm evidence match the latest implementation commit, recording
  run/results and actual marker coverage listed in sections 1–4. Distinguish valid
  hint flows and startup regression evidence from the single-service refusal
  evidence; no existing system marker directly proves provider immutability or
  HTTP 422. An unrelated blocker must name cause/owner and leave gated checks
  unrun, never passed. No new system scenario is owed under the level boundaries.
- [ ] 5.9 **Promotion.** Write the permanent destinations in the map below after
  implementation verification/review. Hand-edit only the spec Evidence section;
  archive merges normative deltas in 5.11. Confirm existing
  `openspec/specs/README.md` already indexes the unchanged capability/companion,
  recording no index addition. Complete the promotion record with exact locations
  and the owner's guidance disposition; permanent prose states current behavior.
- [ ] 5.10 **Documentation citations.** After promotion run
  `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation`, resolve
  every absent/tombstone citation and validate the change with pinned OpenSpec
  1.14.0 `validate fix-resource-pool-provider-at-creation --strict`. Record results
  as the final checks before archival.
- [ ] 5.11 **Archival — last.** Once the other ten parts pass, use pinned OpenSpec
  1.14.0 `archive fix-resource-pool-provider-at-creation -y` without `--skip-specs`,
  merging the added requirements once. Point this change's index link at the
  archive, keeping status `in closeout` until its review gate and archive cleanup.
  Run pinned `validate --specs --strict` and `make check-change-index`. Preserve
  review records and other changes' dependencies for archive cleanup.

**Closeout verification:** the eleven recorded outcomes, valid synchronized specs,
resolvable promoted citations and index. This documentation section adds no new
deployed behavior; it confirms the section-specific pipeline markers above.

## Decision-to-section map

| Decision / requirement | Implementation | Permanent promotion |
|---|---|---|
| D1/D4/D5; immutable provider/status/message | 3 | 5.9, spec provider requirement |
| D2/F1; reduced handler and runtime composition | 4 | 5.9, spec handler requirement and provider architecture |
| D3/D7; retained patch field and config no-op | 3 | 5.9, spec provider requirement |
| D6; request-first/shared comparison | 2 and 3 | 5.3/5.9, spec shared-validation and provider-validation requirements |
| D8; structured documents/atomic import/digest | 3 | 5.9, spec document requirement and deployment guidance |
| D9; existing resource/host migration guards | 3 | 5.9, spec provider migration scenario and companion rationale |
| D11; structural helper ownership | 1 | 5.9, spec provider-validation requirement and thin dependency description |
| D11; model hints/HTTP 422 | 2 | 5.9, spec typed-model requirement and testing ownership |
| D10; provisional documentation destinations | 5 | Map below; no separate decision gate |
| General guidance question | 5.3 owner decision | Destination only if owner chooses promotion |
| 19 V1 / 20 V1; document-created default and canonical VM identity | 3.8–3.11 | 5.9, new default/bootstrap and VM identity spec requirements; resource-pool architecture and deployment guidance |

## Design promotion record

Destinations are settled by this plan; implementation/closeout fills the evidence
and final headings, preserving any owner-deferred guidance disposition.

| Accepted knowledge | Permanent destination and required edit |
|---|---|
| D1/D3–D9: provider immutability, same-provider config/patch, migration | `openspec/specs/resource-pool-management/spec.md` — new “A pool's provider is fixed at creation” requirement, via archive |
| D6: shared immutability and backing repair | Same spec — “Shared validation of pool immutability”, via archive |
| D8: indexed document problems, atomic refusal and startup digest | Same spec — “Documents report immutable providers atomically”, via archive |
| D11: model hint validation and HTTP 422 | Same spec — “Typed pool models validate policy hints”, via archive |
| D6/D11: composed-provider validation and structural helper ownership | Same spec — “Provider validation remains service-owned”, via archive |
| D2/F1: non-destructive handler interface | Same spec — “Configuration handlers follow the non-destructive lifecycle”, via archive |
| Evidence: provider-refusal tests, contracts model/structural suites, API and startup coverage | Same spec — existing “Evidence”, explicit hand edit before archival; models already reside in contracts |
| D1/D2/D9: stable routing/provider lifetime and separate member guards | `openspec/specs/resource-pool-management/architecture.md` — existing “Provider configuration” and “Membership and draining” |
| D6/D8/D11: local model/service boundary and document phases | Same companion — existing “Administrative reconciliation”; do not add general repository guidance without 5.3's owner decision |
| Immutable provider/backing and contracts' direct shape dependency | `docs/development/ARCHITECTURE.md` — “Resource pools” and the thin-distributions paragraph under “Kit areas” |
| Document provider refusal, all-or-nothing apply and unchanged digest | `docs/development/DEPLOYMENT_AND_CONFIG.md` — “Definition documents” / “Reconciliation follows the document, not the process” |
| Model/structural unit ownership and library/app integration responsibilities | `docs/development/TESTING.md` — “Pool Offering-Mode Enforcement” |
| Goal 1 current state and removal of its provider-swap gap | `docs/development/ROADMAP.md` — “Goal 1 — Consolidate physical-resource authority in the provisioning service” |
| Campaign status/acceptance and independent graph node | `openspec/changes/README.md` — Goal 1 campaign |
| Canonical provider example in adjacent projection contract | `openspec/specs/site-capacity/spec.md` — replace its generic `ansible` example with `vm.ansible` during promotion |
| Canonical capability documentation index | `openspec/specs/README.md` — existing Resource-pool management row retained; no new capability or companion |
| General validation-order guidance | Pending owner decision at 5.3; explicitly record promotion destination or no-promotion disposition |
| 19 V1 / 20 V1: default creation before inventory and canonical VM routing/upgrade | `openspec/specs/resource-pool-management/spec.md`, via archive; its architecture's administrative reconciliation; `docs/development/DEPLOYMENT_AND_CONFIG.md` definition documents/migrations; `docs/development/ARCHITECTURE.md` Resource pools |
