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

- Contracts own and export the structural helper; the authority's exports and
  resolver semantics are unchanged. The authority dropped its now-unused direct
  shape dependency. `make lock` regenerated the contracts lock and 23 consumer
  locks; none hand-edited. The two dependency cells in
  `docs/development/RELEASING.md` were corrected to match.
- Evidence: contracts 212 unit tests and authority 121 unit/library tests passed;
  `make test`, `make check-packaging` (architecture clean), hygiene and citations
  passed. Wheels ship the module and `py.typed`; neither project has a typing
  target. Fresh-context compliance review: one index-currency fix, nothing declined.
- Deployed: `e2e_vm_introduction` and `e2e_bare_metal_publication` exercise valid
  rate flows only.

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

- Create/replace and tag-supplying patch models run declarations and all five
  shared hint checks; malformed construction raises before dispatch. The service
  helper and its per-write calls are gone; raw-document validators, provider
  normalization, unknown tags and domain vocabulary keep their behavior.
  Direct-service tests that bypassed model construction were removed (D11).
- Evidence: contracts 375 unit tests (three-model invalid/valid matrix, omitted
  patch tags, opaque and domain-owned values); authority 103 unit/library tests
  (document problems, failed import preserving state); provisioning 675 unit and
  455 integration tests, with rejection-path `model_construct` bodies proving
  HTTP 422 and preserved state, raw documents keeping structured problems and
  HTTP 400, and provider/configuration HTTP 400 retained. `make dist-ci`,
  `make test`, `make check-packaging`, hygiene and citations passed; no typing
  target. Compliance review: no findings.
- Deployed: `e2e_listing_shapes`, `e2e_vm_introduction` and
  `e2e_bare_metal_publication` cover valid hint flows only; none proves HTTP 422.

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
- [x] 3.12 **23 F1 — interrupted bootstrap.** In `db/database.py`, base legacy
  bootstrap/backfill on existing pool or host rows, so schema tables left by an
  interrupted first migration do not claim the default provider. Extend
  `test_pool_declaration_startup.py` with deterministic SQLite interruptions
  before versioned migrations and before pool bootstrap, with and without a
  configured document, plus existing pool/configuration preservation without
  hosts. Retain legacy-host and identity-migration integration coverage, run
  focused and aggregate suites, packaging, hygiene and citations, obtain fresh
  compliance against the recovered base `d1b22e4ce`, and commit for fresh validation.

**Deployed coverage:** no existing pytest marker submits a provider change or
changed-provider startup document. No new system scenario is owed for these
single-authority transactions. `multi_registry`, `e2e_listing_shapes`,
`e2e_deal`, `e2e_vm_introduction`, `e2e_bare_metal_publication` and
`e2e_bare_metal_mock_deal` exercise ordinary pool-backed flows after deployment;
their green result is regression evidence, not direct proof of immutability.

**Section 3 implementation notes:**

- One pure `pool_immutability_problems` comparison returns field, code, values
  and message. Individual writes raise its first problem and documents prefix
  every problem with the submitted entry index. Provider has no repair allowance,
  while missing backing keeps one. Omitted patch fields compare as stored.
  Provider registration and configuration checks stay service-owned and run
  first, and document request problems prevent the stored-state comparison.
  The backing code and message are unchanged. The three production swap call
  sites are gone, and the startup importer needed no change.
- Evidence: authority 124 unit/library tests. They cover the pure matrix, and
  real-SQLite refusal of replace and patch preserving every field and the
  configuration with no handler write. Equal-provider-only and omitted-tag
  patches write nothing. Documents report index 2 with both problems and no diff,
  and validate-only, import and caller-session import all refuse atomically.
  The backing repair still passes. Provisioning `test_pools_api.py` (application
  integration) proves HTTP 400 with the member-migration text, preserved
  responses and export, and a no-op seen by a recording handler.
  `test_pool_declaration_startup.py` (file-backed SQLite with the real importer)
  proves a changed-provider document fails naming `pools[1].provider` and leaves
  state and the digest unchanged; it retries, and a correction applies. The
  provisioning suite ran 675 unit and 460 integration tests. `make test`,
  `make check-packaging`, architecture, hygiene and citations passed; compliance
  review had no findings.
- Migration (D9): a second pool and explicit reassignment. The capacity guard is
  `site-capacity`'s "A capacity resource does not move pools under live
  obligations", covered by `kit/site/tests/integration/test_ledger.py`'s drain,
  lock and race tests. The host hook is covered by
  `provisioning/compute/service/tests/integration/test_host_pool_moves_api.py`.
  No guard or duplicate test was added. The bootstrap caller the audit missed is
  recorded in `design.md` under "Implementation record" and fixed by 3.8–3.11.
- Deployed: `multi_registry`, `e2e_listing_shapes`, `e2e_deal`,
  `e2e_vm_introduction`, `e2e_bare_metal_publication` and
  `e2e_bare_metal_mock_deal` are regression evidence only; none submits a
  provider change.

**Implementation round 1 — 19 V1 / 20 V1:**

- With a configured pool document, a genuinely empty database leaves default
  creation to atomic startup import, after contributed definitions and before
  inventory. Existing databases keep host backfill, and with no document the VM
  default is still seeded. A missing or invalid document fails startup, and a
  later document cannot change the provider. The bare-metal development fixture
  declares `default` as `bare_metal.ansible`.
- VM registration, callers, fixtures and Helm examples use `vm.ansible`. The
  appended migration changes only historical `ansible` provider columns in pools
  and fulfillment records, preserving configuration, membership, IDs, state and
  envelopes. Historical backfill accepts both names, and `vm.ansible.*` operation
  kinds are unchanged. There is no runtime alias. Operator cutover guidance is in
  `docs/seller-quickstart.md`.
- Evidence (real SQLite): fresh startup from the actual bare-metal fixture and a
  VM document, repeated migration creating no implicit pool, digest skip, refused
  later provider changes, and missing or invalid documents creating nothing.
  Existing-schema migration is parametrized with and without a document.
  `test_vm_provider_identity_migration.py` compares complete rows, leaves
  bare-metal rows alone, and proves idempotence; backfill-to-teardown passes under
  the canonical name. Final `make test` passed: provisioning 662 unit and 479
  integration, VM storefront 411 integration, VM adapter 29, contracts 375,
  954 tooling tests and Helm render. `make check-packaging`, architecture,
  hygiene, citations and strict OpenSpec 1.14.0 also passed, and compliance
  review against `a3bd6b1d` had no findings. Test relocations and the
  payment-test race fix are recorded in `design.md`'s "Implementation record".
- Deployed: VM scenarios (`e2e_vm_introduction`, `e2e_deal`,
  `e2e_deal_buyer_cli`, `e2e_listing_shapes`, `multi_registry`) bootstrap
  canonical VM pools. Bare-metal scenarios (`e2e_bare_metal_publication`,
  `e2e_bare_metal_introduction`, `e2e_bare_metal_mock_deal`) start from the
  document-created default. These are regression evidence, not direct migration
  proof.

**Implementation round 2 — 23 F1:**

- Bootstrap and backfill depend on persisted pool or host rows, not on schema
  tables. A configured document therefore still creates the default after an
  interrupted first migration that left only schema and migration records.
  Existing pools and legacy hosts keep VM bootstrap/backfill, and with no
  document the VM default is still seeded.
- Evidence: 25 focused real-SQLite integration tests across
  `test_pool_declaration_startup.py`, `test_database.py` and
  `test_vm_provider_identity_migration.py`. Four new file-backed cases interrupt
  SQL before versioned migrations or before pool bootstrap, with and without a
  document, then resume. A fifth keeps an existing VM pool and its configuration
  with no hosts. On a clean wheelhouse, `make test` passed: provisioning 662 unit
  and 484 integration, VM storefront 1,036 unit and 411 integration, 1,061
  tooling tests and Helm render. `make check-packaging`, hygiene, citations and
  strict OpenSpec also passed. Compliance review against `d1b22e4ce` found one
  evidence-wording overstatement, which was corrected. The recovery and
  wheelhouse narrative is in `design.md`'s "Implementation record".
- Deployed: no marker exercises an interrupted migration; integration tests own
  it. The owner advanced without another implementation review.

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

- `delete_config` is gone from the protocol, both handlers, composition's
  required hooks and every fake; a repository-wide Python search finds none. The
  direct deletion test was removed. Same-provider replacement and both read
  levels are unchanged. Composition unit tests accept a deletion-free handler
  and reject each of the four remaining hooks when absent or non-callable, and
  the identity, pairing and duplicate-registration cases still pass.
- Evidence: pool authority 124; fulfillment 171; compute family 231; VM adapter
  29; bare-metal adapter 40; provisioning service 675 unit and 459 integration.
  These include `tests/unit/test_authority_composition.py`, which composes both
  real adapter bundles, and the disabled-pool GET case, which shows its
  configuration is retained. `make test`, `make check-packaging`, architecture,
  hygiene and citations passed; no project has a typing target. Two compliance
  reviews required the move of 38 database-backed fulfillment tests to
  `integration/` and a deterministic race case. Both were fixed, nothing was
  declined, and the details are in `design.md`'s "Implementation record".
- Deployed: `e2e_deal`, `e2e_deal_buyer_cli` and `e2e_bare_metal_mock_deal`
  start stacks composing these handlers, as regression evidence. No
  deletion-hook scenario is owed.

## 5. Closeout

Confirm and promote the verified design, then archive last; D1–D9/D11 and all
requirements. All eleven parts below follow
`openspec/README.md#plan-closeout-requirements` in order. No code changes occur
here: a needed code/lock fix returns to implementation. General guidance is an
explicit owner question, not a prescribed edit.

- [x] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read
  comments/docstrings added by sections 1–4 for current-system rationale; no
  change IDs, task numbers or migration narration. Record results; needed code
  corrections return to implementation.
  Passed both scans. Read every comment/docstring the seven implementation
  commits added to Python files: each states a current invariant or test intent;
  none names a review, migration, change or task. No return owed.
- [x] 5.2 **Import placement — confirm.** Check imports added/touched by sections
  1–4 are at module level unless a verified cycle or recorded deliberate lazy-load
  reason requires otherwise. Record the inspection, returning code corrections
  to implementation rather than changing them during closeout.
  Every import the seven implementation commits added to Python files is at
  module level; none is function-local. No return owed.
- [x] 5.3 **Documentation compliance.** Audit D1–D9/D11, review F1/F2 and all eight
  requirements against the promotion map below and the actual code. Ask the owner
  whether to promote general validation-order guidance and its wording/home;
  record the decision without presuming an edit. Confirm that subsystem-local
  validation behavior and boundaries are still promoted regardless. Evidence:
  a disposition for every material decision and the deferred guidance question.
  Every decision maps to a destination its placement rule allows: normative
  behavior to the spec via the deltas, rationale to the companion, repository
  shape to `ARCHITECTURE.md`, operator behavior to `DEPLOYMENT_AND_CONFIG.md`,
  test ownership to `TESTING.md`. Checked against code: `pool_immutability_problems`,
  `provider_immutable`, no `delete_config`, contracts' direct shape dependency,
  the pool/host-row bootstrap test in `db/database.py`. Found stale permanent text,
  fixed in 5.9: `ARCHITECTURE.md` says the shape kit arrives only transitively;
  `TESTING.md` and spec Evidence still place the model and asking-rate structure
  tests in `kit/resource-pools`; `site-capacity` still gives `"ansible"` as its
  example. Owner decision on general guidance: option B, a paragraph in
  `ARCHITECTURE.md` under "Route contracts and their HTTP binding", with the
  wording proposed at closeout; recorded in `design.md`.
- [x] 5.4 **Narrative compression.** Preserve final behavior, validation evidence,
  limitations and promotion destinations; move any remaining durable rationale
  into `design.md` before compressing task notes. Verify no implementation history
  or accepted rationale is lost and permanent prose describes current behavior.
  Compressed the notes for sections 1–4 and both rounds to final behavior,
  evidence counts, deployed coverage and destinations. These moved first to the
  new `design.md` "Implementation record": the missed bootstrap caller, the
  test relocations and race-case rewrite, the payment-test race, the session
  interruptions and stash recovery, the contaminated wheelhouse, and the
  environment notes. Handoff and status chatter was dropped as duplicated by the
  index and git history.
- [x] 5.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, Goal 1, remove the
  existing provider-swap gap owned by this change and state the now-immutable
  provider in current-state prose. Record that exact destination; do not claim
  the earlier plan's incorrect “no roadmap gap” disposition.
  Removed the provider-swap row from Goal 1's open-gap table. Added a current-state
  paragraph covering the fixed provider, second-pool migration under the existing
  guards, the document-created default and `vm.ansible`.
- [x] 5.6 **Campaign index currency.** Update this change's Goal 1 row and check its
  independent graph node in `openspec/changes/README.md`; preserve the broadened
  acceptance boundary and record graph changes or an explicit unchanged result.
  Run `make check-change-index`. Leave other rows' dependencies for archive
  cleanup after the closeout gate.
  Row status is `in closeout`, its notes now name the promotion destinations,
  and the acceptance boundary is unchanged. The graph node stays
  `(independent)`: there are no dependencies either way, and `archived` is
  archive cleanup's to write. No other row lists this change in `Depends on`.
  `make check-change-index` passed; it reruns after the archive relinks the row.
- [x] 5.7 **Packaging.** Confirm `make check-packaging` and
  `make check-architecture-change CHANGE=fix-resource-pool-provider-at-creation`
  pass against the latest committed implementation. If this change actually
  touches agent/permission skills later, also run `make check-agent-skills`;
  otherwise record that it did not. Code, dependency or lock failures return to
  implementation. Record checks rather than repairing production code here.
  `make check-packaging` passed: locks, wheels, layout, Python version, and all
  four architecture rules. `make check-architecture-change` reports that the
  change owns no architecture row. The implementation commits touched no
  `.agents/`, `.claude/` or `.codex/` file, so `make check-agent-skills` is not owed.
- [x] 5.8 **End-to-end pipeline.** Confirm the latest validation record's full
  pipeline and Helm evidence match the latest implementation commit, recording
  run/results and actual marker coverage listed in sections 1–4. Distinguish valid
  hint flows and startup regression evidence from the single-service refusal
  evidence; no existing system marker directly proves provider immutability or
  HTTP 422. An unrelated blocker must name cause/owner and leave gated checks
  unrun, never passed. No new system scenario is owed under the level boundaries.
  `reviews/27-validation.md` covers `f890c4793a6f`, the last implementation
  commit and the pre-closeout commit, with no waiver. Pipeline run 39270207076
  succeeded: e2e-vm 134 passed, e2e-bare-metal 51 passed, e2e-apicredits 1
  passed and 3 skipped. Local `make test` and `make check-packaging` passed; on
  Helm, deploy plus `e2e_alkahest_escrow_codecs` passed. Regression coverage for
  this change: `e2e_vm_introduction`, `e2e_deal`, `e2e_deal_buyer_cli`,
  `e2e_listing_shapes` and `multi_registry` (canonical VM bootstrapping, valid
  hint flows), and `e2e_bare_metal_publication`, `e2e_bare_metal_introduction`
  and `e2e_bare_metal_mock_deal` (document-created bare-metal default). All
  passed. None directly proves provider refusal, HTTP 422 or interrupted
  migration; unit and integration tests own those. The skipped API-credit
  payment scenarios and the Helm subset are disclosed limits, not blockers.
  Closeout changes no code, so this run describes the closeout commit's code.
- [x] 5.9 **Promotion.** Write the permanent destinations in the map below after
  implementation verification/review. Hand-edit only the spec Evidence section;
  archive merges normative deltas in 5.11. Confirm existing
  `openspec/specs/README.md` already indexes the unchanged capability/companion,
  recording no index addition. Complete the promotion record with exact locations
  and the owner's guidance disposition; permanent prose states current behavior.
  Written: the companion, `ARCHITECTURE.md` (Resource pools, the authority row,
  thin distributions, and the owner's validation-order paragraph),
  `DEPLOYMENT_AND_CONFIG.md`, `TESTING.md`, and the spec's Evidence section. The
  capability index needs no change. The `site-capacity` projection's
  provider-kind example now reads `"vm.ansible"`. The promotion record lists
  every location.
- [x] 5.10 **Documentation citations.** After promotion run
  `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation`, resolve
  every absent/tombstone citation and validate the change with pinned OpenSpec
  1.14.0 `validate fix-resource-pool-provider-at-creation --strict`. Record results
  as the final checks before archival.
  `make check-doc-citations CHANGE=fix-resource-pool-provider-at-creation`
  passed: every citation in the change's four documents resolves and none is a
  tombstone. Pinned `npx --yes @fission-ai/openspec@1.14.0 validate
  fix-resource-pool-provider-at-creation --strict` reports the change valid.
  Both passed again after the `site-capacity` edit.
- [x] 5.11 **Archival — last.** Once the other ten parts pass, use pinned OpenSpec
  1.14.0 `archive fix-resource-pool-provider-at-creation -y` without `--skip-specs`,
  merging the added requirements once. Point this change's index link at the
  archive, keeping status `in closeout` until its review gate and archive cleanup.
  Run pinned `validate --specs --strict` and `make check-change-index`. Preserve
  review records and other changes' dependencies for archive cleanup.
  The permanent spec held none of the eight added requirements, so the archive
  ran without `--skip-specs`. Pinned 1.14.0 `archive -y` moved the change, with
  its reviews, to `openspec/changes/archive/2026-10-19-fix-resource-pool-provider-at-creation/`.
  The session was interrupted before the command's result was recorded;
  `reviews/34-orchestrator.md` records that interruption, and the archive was
  not run twice. The merged `resource-pool-management/spec.md` diff adds each of
  the eight requirements once, as the delta states them, before Evidence; the
  only other changes are the hand-edited Evidence lines. The index row now links
  the archive with status `in closeout`, and other rows are untouched.

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
| 23 F1; pool/host-row bootstrap boundary and interruption-safe retry | 3.12 | 5.9, default/bootstrap requirement and resource-pool administrative reconciliation; deployment migration guidance |

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
| General validation-order guidance | Owner chose promotion at 5.3 (option B): `docs/development/ARCHITECTURE.md#route-contracts-and-their-http-binding`, the paragraph beginning "A request is checked in the order of what it takes to judge it" |
| 19 V1 / 20 V1: default creation before inventory and canonical VM routing/upgrade | `openspec/specs/resource-pool-management/spec.md`, via archive; its architecture's administrative reconciliation; `docs/development/DEPLOYMENT_AND_CONFIG.md` definition documents/migrations; `docs/development/ARCHITECTURE.md` Resource pools |
| 23 F1: schema-only interrupted initialization retains document-created default bootstrap until pool or host state exists | `openspec/specs/resource-pool-management/spec.md` default/bootstrap requirement, hand-edited after archive (closeout review 36 F1); its architecture's administrative reconciliation; `docs/development/DEPLOYMENT_AND_CONFIG.md` migrations |

### Locations written at closeout

| Accepted knowledge | Permanent location |
|---|---|
| Eight added requirements (D1–D9, D11, D2/F1, default bootstrap, VM identity) | `openspec/specs/resource-pool-management/spec.md`, written by the archive: `#requirement-the-default-pool-is-created-with-its-intended-provider`, `#requirement-vm-provider-identity-is-namespaced`, `#requirement-a-pools-provider-is-fixed-at-creation`, `#requirement-shared-validation-of-pool-immutability`, `#requirement-documents-report-immutable-providers-atomically`, `#requirement-typed-pool-models-validate-policy-hints`, `#requirement-provider-validation-remains-service-owned`, `#requirement-configuration-handlers-follow-the-non-destructive-lifecycle` |
| 23 F1 empty-database criterion (no pool or host row) and the interrupted-migration retry scenario | `openspec/specs/resource-pool-management/spec.md#requirement-the-default-pool-is-created-with-its-intended-provider`, hand-edited after archive (closeout review 36 F1) |
| Evidence | `openspec/specs/resource-pool-management/spec.md#evidence`, edited by hand: contracts model/asking-rate paths, provider refusal, pure comparison, composition, identity migration, startup and API coverage |
| D1/D2/D4/D7 and VM identity rationale | `openspec/specs/resource-pool-management/architecture.md#provider-configuration` |
| D9 separate member guards | `openspec/specs/resource-pool-management/architecture.md#membership-and-draining` |
| D6/D8/D11 validation order, shared comparison, document phases; 19/20 V1 and 23 F1 bootstrap | `openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation` |
| Provider fixed at creation, document-created default, provider names | `docs/development/ARCHITECTURE.md#resource-pools` and its authority-boundaries row |
| Contracts' hint validation, asking-rate checks and direct shape dependency | `docs/development/ARCHITECTURE.md#kit-areas` (thin-distributions paragraph) |
| General validation-order guidance (owner, option B) | `docs/development/ARCHITECTURE.md#route-contracts-and-their-http-binding` |
| Document-created default, interrupted-migration boundary, changed-provider document refusal and digest | `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents` |
| VM identity upgrade and no alias | `docs/development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup`; operator steps already in `docs/seller-quickstart.md#declaring-capacity` |
| Test ownership for hints, immutability, bootstrap and identity | `docs/development/TESTING.md#pool-offering-mode-enforcement` |
| Goal 1 current state; provider-swap gap removed | `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service` |
| Campaign row | `openspec/changes/README.md`, Goal 1 campaign; graph node unchanged |
| Capability index | `openspec/specs/README.md`, existing Resource-pool management row; no addition |
| Canonical provider example in the projection contract | `openspec/specs/site-capacity/spec.md`, the `site_resource_pools` pool-metadata paragraph (`mechanism` example `"vm.ansible"`) |
