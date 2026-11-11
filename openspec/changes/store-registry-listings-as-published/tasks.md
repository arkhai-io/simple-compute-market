# Implementation tasks

## 1. Retained publication contract

Implements D1, D2 and D5; registry, neutral client, and schema validation.

- [x] 1.1 Amend proposal and registry delta for whole-document replacement, legacy synthesis, reserved metadata, schema validation, and retained publication/update evidence; record D-a–D-e and the dependency correction in design and campaign index.
- [x] 1.2 Add an additive Alembic revision and model columns in `core/registry` for the document and seller evidence; leave existing carriers for legacy synthesis and storefront startup unchanged.
- [x] 1.3 Update `api/listing_routes.py`, `api/utils.py`, `api/publisher_auth.py`, and validation routes/models so accepted documents survive publication, detail/search use the same view, update evidence is explicit, and full schema validation runs at publish.
- [x] 1.4 Extend `core/registry-client` request models with opaque extra terms and preserve returned evidence in existing response extras.
- [x] 1.5 Run existing registry unit/application-integration and registry-client suites; directly try publish/read/search/republication, seller-proof verification, and legacy synthesis. Exercise fresh/upgrade migration. No existing e2e scenario asserts retained arbitrary fields or seller publication proofs; pipeline compute publication covers wire compatibility only.

## 2. VM listing-level rates

Implements D3's intermediate state (a top-level `rate_structure`) and supplies D4's downstream authority/carrier answer.

- [x] 2.1 Wire `domains/vms/storefront` publication loop, terms and listing service/model through `domains/vms/listings` and schema-opaque `core/storefront/registry_publication.py`; correct the listing response comment. Publish current resolved family rates on create, refresh and reopen without moving asking_rate.
- [x] 2.2 Declare the optional top-level rate structure in the compute filter schema; keep registry engine domain-neutral.
- [x] 2.3 Run existing publication-loop/rate-composition application-integration suites, shared publication helpers and VM listing-model suites; try the published rate field through the registry. Existing compute e2e lanes exercise publication, but do not assert this new term. Record exact evidence and limitations here.
- [x] 2.4 Refresh affected wheel/lock environments with repository tooling; run `make check-packaging`, comment hygiene, scoped citations/check-change and pinned strict OpenSpec validation. Prepare a reproducible first-use recipe. Commit and open PR into dev after updating from origin/dev; promotion waits for review.

## 3. Listing pricing object and permanent tests

Implements D3's `pricing` object and the permanent coverage the owner accepted (round 1 owner record R10, R2, R18). Reviewed as round 2.

- [ ] 3.1 Compute filter specification (`core/registry/src/core_registry/filter-spec.yaml`): add an optional top-level `pricing` with `asking_rate` (its current strict shape) and an optional `rate_structure` (the strict family shape); remove `listing_resource.asking_rate` and the top-level `rate_structure`; repoint the four asking-rate filters to `$.pricing.asking_rate.*`, query names unchanged. Version 9 stays 9.
- [ ] 3.2 Publishers write `pricing` through the opaque publication channel: the VM listings model and storefront (`publication_terms` carries `{"pricing": {...}}`), the bare-metal domain and storefront, `resource-pools`, `resource-pools-contracts` and `pool-overrides`.
- [ ] 3.3 Spec deltas: `registry-discovery` (the `pricing` object and its filters; the legacy-row asking-rate gap), `storefront-publication` (publication of `pricing`; registry repair republishes the domain's candidate, D6), and a new `resource-pool-management` delta.
- [ ] 3.4 Registry permanent tests at the levels `docs/development/TESTING.md` assigns. Integration: unknown fields kept, whole-document replacement, reserved-name refusal, `PUT` refusal of other keys, schema refusal leaving the stored content unchanged, legacy rebuild with null evidence, update evidence and its reset on republication, and a seller-proof round trip verified at the signed timestamp. Unit: validator error paths and the reserved list.
- [ ] 3.5 Publisher integration tests proving each in-repository publisher's real payload (VM, bare-metal, API-credit) validates against its registry's schema, including the `pricing` object, on first publication and on registry repair through its `publication_candidate` hook (D6).
- [ ] 3.6 Run the registry, registry-client, kit capacity-publication, VM storefront, bare-metal, resource-pool kit and API-credit suites and `make check-packaging`; record each with its level and result.

## 4. Closeout (post code-review)

Per `openspec/README.md#plan-closeout-requirements`; promotion is deliberately not performed before review.

- [ ] 4.1 Confirm comment hygiene with `make check-comment-hygiene`; any code correction returns to implementation.
- [ ] 4.2 Confirm touched imports are module-level or have demonstrated reasons to remain local.
- [ ] 4.3 Check documentation placement for D1–D6 against OpenSpec ownership rules.
- [ ] 4.4 Compress completed notes to behavior, evidence, residuals and promotion destinations, preserving design rationale.
- [ ] 4.5 Reconcile `docs/development/ROADMAP.md` registry/compute carrier descriptions where affected, or record no impact explicitly.
- [ ] 4.6 Update this change's campaign row/graph in `openspec/changes/README.md`; dependent release waits for archive cleanup.
- [ ] 4.7 Run `make check-packaging` and `make check-architecture-change CHANGE=store-registry-listings-as-published`; resolve all failures/owned exceptions.
- [ ] 4.8 Record end-to-end pipeline run/result and compute and credits publication scenarios; disclose that retained-field/proof assertions are not covered by current e2e scenarios. Unavailable pipeline is a blocker, not a pass.
- [ ] 4.9 Promote the registry delta through archival, with rationale to `openspec/specs/registry-discovery/architecture.md` — the `publisher_publication` / `publisher_updates` shape as a normative wire contract in `spec.md`; why body bytes are kept and how historical verification and key rotation work; that a refused republication leaves the last stored listing in place. Promote the storefront delta through archival, with rationale (including D6) to `openspec/specs/storefront-publication/architecture.md`, and the `resource-pool-management` delta through archival. Complete the design promotion record. No principle is promoted to repository architecture; no new capability/index is introduced.
- [ ] 4.10 Run scoped documentation citations and pinned `openspec validate store-registry-listings-as-published --strict` after promotion.
- [ ] 4.11 Archive last, merging deltas with the pinned OpenSpec CLI and updating campaign link; review the archived documentation before cleanup.

## Validation and handoff notes

Implementation evidence: `docs/attachments/store-registry-listings-as-published/implementation-evidence.md`;
stack replay: `docs/attachments/goal8-stack/registry.md`.

Round 1 (sections 1 and 2): registry unit/application integration 267 passed;
registry-client 25; shared publication/model/persistence 7; focused VM
model/composition/publication-loop suites 110. Direct first use verified retained
seller proof, reads/search, whole-document replacement and distinct lifecycle
evidence. A temporary VM wire diagnostic validated an actual rate-bearing
publication against the compute schema, then was removed. Fresh, repeated and
populated migration and legacy-synthesis experiments passed; no existing rows are
rewritten. The registry revision follows the packaged `v0_3_0_baseline`; no
pre-floor repair revision is needed. `make check-packaging`, `make check-change`
and pinned strict OpenSpec validation passed. Reinitialization used repository
wheel tooling; no locks changed.

First use: after `make dist` and `make -C core/registry reinit`, run
`(cd core/registry && uv run --find-links ../../.dist python ../../openspec/changes/store-registry-listings-as-published/first-use.py)`.
This is isolated in-process SQLite with deterministic development seller/registry
identities, readiness checked, no credentials or resident services required.

PR: https://github.com/arkhai-io/simple-compute-market/pull/349 targets dev.

Validation 05 at `7e7e7ca58`: local (check-packaging and all suites) and Helm
passed; the pipeline failed in e2e-apicredits (V1) and e2e-vm stage 12a (V2),
both caused by the commit; e2e-bare-metal and the native gate passed. VM
storefront typing belongs to `type-core-packages`; PostgreSQL does not apply.

### Round 1 triage fixes

Fixed in round 1's triage, outside the plan's sections:

- 05 V1 — `domains/apicredits/registry/filter-spec.yaml` declares the market's
  settlement option (`option_id`, `settlement`, optional `price` and `lifecycle`),
  version 5; full validation at publication had refused every API-credit
  listing against its never-enforced flat shape. Registry integration test
  `test_a_credits_listing_with_a_market_settlement_option_is_admitted`.
- 05 V2 — registry repair republishes the domain's candidate (D6): the kit's
  `PublicationDomainHooks` requires `publication_candidate(listing)`, implemented
  by the VM, bare-metal and API-credit hooks; `_converge_one` validates and
  republishes it to the diverged registries only. VM repair had sent JSON-null
  capacity attributes, refused at stage 12a, and would have dropped
  `rate_structure`. Kit unit test
  `test_a_repair_republishes_the_domain_candidate_not_the_stored_row`. The schema
  fix and the VM half of the repair came from the stack's commit `49ca2d9ed`, made
  here by hand; its optional `candidate_factory` became the required hook, so
  bare-metal and API-credit repair use their candidates too.
- 03 F1 — `ListingSummary` describes `storefront_url` as the listing's signed URL,
  or the publisher record's for a legacy row.
- Owner record R4 — the revision is `20261106_001_registry_retained_publications`,
  the dated convention, and its downgrade refuses ("restore a backup instead").
  No revision up the stack names the old ID, so the rename carries up when the
  stack merges.

Evidence: registry suite (unit and application integration) 286 passed;
registry-client (unit) 25; kit capacity-publication (unit) 136; VM
publication-loop (application integration) 72; bare-metal publication and
restart recovery 82; API-credit publication and convergence 18. `make
check-packaging` passed. `scripts/change-workflow run pre-commit`, which
reinitialized every environment from fresh wheels and ran every suite:
`after-functional-change … passed, exit 0`, `pre-commit-functional … passed,
exit 0`, `pre-commit … passed, exit 0` (comment hygiene, citations, change
checks included). A fresh-context compliance check found no blocking defect;
fixed from it: the kit's stale `converge` docstring, D6's wording (where a
domain's candidate is its stored row, repair sends it; repair now checks the
binding first), D6's API-credit half given a promotion row, and task 3.5 widened
to each domain's repair path, which only a fake codec proves today. Declined: a
test of the refusing downgrade, which the baseline's refusal also lacks. The
e2e lanes are not rerun here; the fix commit's validation reruns them.
