# Tasks

Replanned the original wholly unchecked sections against the reviewed design and
`reviews/14-design.triage.md` after its owner-passed gate. No completed task is
removed or rewritten. All implementation tasks below answer to D1–D9/D11, the
six delta requirements, and the validation/closeout obligations in
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

- [ ] 3.1 Implement one pure stored/proposed comparison for provider and backing,
  returning field-specific problems (D5/D6). Replace the duplicated backing
  comparisons with thin API/document adapters. Preserve backing repair when no
  value is stored, omit-field patch behavior, both problem codes and submitted
  source indices. Unit evidence: provider/backing equal/different combinations,
  repair, stable messages and codes; no database collaborator needed.
- [ ] 3.2 Apply that comparison before any mutation in replace and patch (D1/D3–D7).
  Remove swap/deletion branches from these paths; an equal provider alone must
  perform no config write, while same-provider config edits retain existing
  secret semantics. Document `PoolUpdate.provider`'s restriction. Library
  evidence: complete metadata/config preservation, same-provider edits, provider
  no-op and omitted tags, using a recording injected handler and a real database.
- [ ] 3.3 Apply the same comparison in validate-only and session-scoped import
  before reconciliation application (D1/D5/D6/D8). Remove import's swap/deletion
  branch. Library evidence: indexed `provider_immutable`, both immutable fields
  reported together, no diff, all-or-nothing valid-entry/omitted-pool effects,
  new entries accepted and backing repair preserved. Request/provider-config
  failures keep their existing phase order and import detail text shape.
- [ ] 3.4 Add application-integration cases in `test_pools_api.py` (D1/D3–D8):
  otherwise-valid requests against registered providers receive HTTP 400, preserve
  all state and explain the second-pool path. Cover replace, patch, same-provider
  edit/no-op, document validate/import and unchanged export. Canonical clients own
  route/body/response shapes. Assert no handler write for equal-provider-only patch.
- [ ] 3.5 Extend `test_pool_declaration_startup.py` (service integration with real
  SQLite, mounted file and real startup importer) for a changed-provider document
  (D8). Verify failure names the entry, no entry/config change lands, the prior
  digest is unchanged, another startup retries, and correction can succeed;
  unchanged-document skip stays covered. No new state/digest mechanism is needed.
- [ ] 3.6 Carry the design audit's migration evidence into the implementation note
  (D9), checking no fixture or caller introduced a provider-swap dependency.
  Cite the site-capacity requirement and existing
  `kit/site/tests/integration/test_ledger.py` drain/race tests plus
  `provisioning/compute/service/tests/integration/test_host_pool_moves_api.py`
  for the distinct host hook. Do not add a pool-level guard or duplicate those
  authorities' tests. Verify the refusal says “migrate its members”.
- [ ] 3.7 **Verification checkpoint.** Run unit/shared-comparison tests, library
  pool-service integration and the named application/startup suites, followed by
  `make dist-ci`, `make -C kit/resource-pools-contracts test`,
  `make -C kit/resource-pools test`, `make -C provisioning/compute/service test`
  and `make check-packaging`. Run `make check-comment-hygiene` and inspect imports
  and comments; record evidence before this section is complete.

**Deployed coverage:** no existing pytest marker submits a provider change or
changed-provider startup document. No new system scenario is owed for these
single-authority transactions. `multi_registry`, `e2e_listing_shapes`,
`e2e_deal`, `e2e_vm_introduction`, `e2e_bare_metal_publication` and
`e2e_bare_metal_mock_deal` exercise ordinary pool-backed flows after deployment;
their green result is regression evidence, not direct proof of immutability.

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

- [ ] 4.1 Remove `delete_config` from protocol, both handlers and every test fake;
  remove its direct handler-deletion test (D2). In the same change remove it from
  `_validate_pool_config_handler`'s required hooks (accepted 14-design F1).
  Verify a repository search finds no remaining code requirement/call and
  same-provider replace/read behavior still passes.
- [ ] 4.2 Extend `provisioning/compute/tests/unit/test_composition.py` for F1:
  deletion-free handlers with the remaining hooks compose successfully, while
  missing/non-callable remaining required hooks are still refused. Preserve
  provider identity checks and duplicate registration behavior; do not broaden
  the accepted runtime interface. Unit tests prove the observable composition.
- [ ] 4.3 Verify the real service composes VM and bare-metal adapters after removal
  (D2/F1), using existing service composition/startup and pool application tests;
  retain the disabled-pool configuration read case. Evidence: named handler/pool
  integration suites and `tests/unit/test_authority_composition.py` pass, proving
  the runtime guard accepts actual reduced implementations.
- [ ] 4.4 **Verification checkpoint.** Rebuild with `make dist-ci`; run
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
- [ ] 5.3 **Documentation compliance.** Audit D1–D9/D11, review F1/F2 and all six
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
| Canonical capability documentation index | `openspec/specs/README.md` — existing Resource-pool management row retained; no new capability or companion |
| General validation-order guidance | Pending owner decision at 5.3; explicitly record promotion destination or no-promotion disposition |
