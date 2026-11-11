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

- [x] 3.1 Compute filter specification (`core/registry/src/core_registry/filter-spec.yaml`): add an optional top-level `pricing` with `asking_rate` (its current strict shape) and an optional `rate_structure` (the strict family shape); remove `listing_resource.asking_rate` and the top-level `rate_structure`; repoint the four asking-rate filters to `$.pricing.asking_rate.*`, query names unchanged. Version 9 stays 9.
  `pricing` is closed, both members optional, `rate_structure` not nullable.
  Correction (round 2 triage, 16 F1): a rate in `listing_resource` and a
  top-level `rate_structure` are refused, naming their place in `pricing`.
- [x] 3.2 Publishers write `pricing` through the opaque publication channel: the VM listings model and storefront (`publication_terms` carries `{"pricing": {...}}`), the bare-metal domain and storefront, `resource-pools`, `resource-pools-contracts` and `pool-overrides`.
  VM: `Listing.published_listing_resource()` / `published_pricing()`; bare
  metal: `published_listing_resource`, applied in
  `bare_metal_publication_candidate`, which every publish path, repair
  included, builds from. Correction: the three pool packages needed no change —
  they never place a rate in a listing. Stored views unchanged. E2E rate reads
  moved to `pricing` (`test_bare_metal_publication.py` 05b–05d,
  `introduction_stages.py` 01).
- [x] 3.3 Spec deltas: `registry-discovery` (the `pricing` object and its filters; the legacy-row asking-rate gap), `storefront-publication` (publication of `pricing`; registry repair republishes the domain's candidate, D6), and a new `resource-pool-management` delta.
  Closeout added two MODIFIED requirements correcting statements the change
  made false (design promotion record, "Closeout corrections").
- [x] 3.4 Registry permanent tests at the levels `docs/development/TESTING.md` assigns. Integration: unknown fields kept, whole-document replacement, reserved-name refusal, `PUT` refusal of other keys, schema refusal leaving the stored content unchanged, legacy rebuild with null evidence, update evidence and its reset on republication, and a seller-proof round trip verified at the signed timestamp. Unit: validator error paths and the reserved list.
  `core/registry/tests/integration/test_retained_publications.py` (every case,
  plus the legacy rate-bound case and a forged body failing) and
  `tests/unit/test_listing_validation.py`.
- [x] 3.5 Publisher integration tests proving each in-repository publisher's real payload (VM, bare-metal, API-credit) validates against its registry's schema, including the `pricing` object, on first publication and on registry repair through its `publication_candidate` hook (D6).
  VM `test_publication_loop.py`, bare metal `test_http_publication_rates.py`
  (its settlement option a stand-in builder), API credits
  `test_publish_reconcile.py` (real payments option, no `pricing`); codec unit
  tests in both compute domains. Schema only; reserved and retired names are
  the registry's contract.
- [x] 3.6 Run the registry, registry-client, kit capacity-publication, VM storefront, bare-metal, resource-pool kit and API-credit suites and `make check-packaging`; record each with its level and result.
  See "Validation and handoff notes".

## 4. Closeout (post code-review)

Per `openspec/README.md#plan-closeout-requirements`; promotion is deliberately not performed before review.

- [x] 4.1 Confirm comment hygiene with `make check-comment-hygiene`; any code correction returns to implementation.
  Passed (no change IDs, task numbers or change names). The comments and
  docstrings the change added, read against `origin/dev`'s merge base, state
  current rules; pre-closeout 23 F2's two were reworded in its triage. No code
  correction owed.
- [x] 4.2 Confirm touched imports are module-level or have demonstrated reasons to remain local.
  The change adds no function-local import (its Python diff adds no indented
  `import`); the pre-commit local-imports check passed at `cd0ed8dc4`.
- [x] 4.3 Check documentation placement for D1–D6 against OpenSpec ownership rules.
  Normative behaviour in the three deltas; rationale in the registry and
  storefront companions; one correction in `ARCHITECTURE.md`. Two permanent
  requirements the change made false, which no delta touched, are corrected by
  MODIFIED blocks added to the deltas: the registry's exact-decimal rationale
  ("validates only in its dry run") and the storefront's "no additional
  listing-level field". D5's rollback rule takes one sentence in the registry
  companion. The registry spec's dry-run statement in its asking-rate
  requirement is replaced by the delta already.
- [x] 4.4 Compress completed notes to behavior, evidence, residuals and promotion destinations, preserving design rationale.
  Section 3's notes and the validation notes shortened; declined review
  suggestions moved to `design.md`, "Alternatives declined during
  implementation", before removal. Per-round suite counts and fix narratives
  are reduced to the final run and a pointer to each triage record, which keeps
  them.
- [x] 4.5 Reconcile `docs/development/ROADMAP.md` registry/compute carrier descriptions where affected, or record no impact explicitly.
  "Negotiate full compute capability", current state: family rates are now
  published in the registry listing's `pricing`, not kept from registries. No
  gap row changes; registry productionization is not a roadmap goal.
- [x] 4.6 Update this change's campaign row/graph in `openspec/changes/README.md`; dependent release waits for archive cleanup.
  Row `in closeout`, notes rewritten; both graphs (Registry productionization,
  and Goal 2's decision-input edge) unchanged and still true; no other row
  touched. `scripts/change-workflow check index` passed.
- [x] 4.7 Run `make check-packaging` and `make check-architecture-change CHANGE=store-registry-listings-as-published`; resolve all failures/owned exceptions.
  `scripts/change-workflow run pre-archive` at `cd0ed8dc4`: packaging (locks,
  installs, Python selection, layers, scope, dependencies, kinds) OK; "owns no
  architecture row"; passed, exit 0.
- [x] 4.8 Record end-to-end pipeline run/result and compute and credits publication scenarios; disclose that retained-field/proof assertions are not covered by current e2e scenarios. Unavailable pipeline is a blocker, not a pass.
  Latest passing pipeline: validation 22, run 43028565810 at `758149f21`,
  success on e2e-vm, e2e-bare-metal, e2e-apicredits and native-ansible-gate,
  covering `e2e_bare_metal_publication` (05b–05d bound by and read
  `pricing.asking_rate`), `e2e_vm_introduction` and
  `e2e_bare_metal_unbacked_introduction` (stage 01), `e2e_listing_shapes`
  (07a) and `e2e-apicredits` (the API-credit schema at publication). The
  pre-closeout commit `cd0ed8dc4` (validation 32: local and Helm passed) has
  no pipeline run: run 43039556220 failed at image build on runner DNS
  (`archive.ubuntu.com`), no scenario started, and the owner waived the part
  (workflow log seq 50). Its code diff from `758149f21` is one comment block in
  `filter-spec.yaml` and one docstring in `registry_client/models.py`, checked
  at closeout. No CI was owed. No scenario asserts retained arbitrary fields
  or seller proofs; the registry's integration suite does.
- [x] 4.9 Promote the registry delta through archival, with rationale to `openspec/specs/registry-discovery/architecture.md` — the `publisher_publication` / `publisher_updates` shape as a normative wire contract in `spec.md`; why body bytes are kept and how historical verification and key rotation work; that a refused republication leaves the last stored listing in place. Promote the storefront delta through archival, with rationale (including D6) to `openspec/specs/storefront-publication/architecture.md`, and the `resource-pool-management` delta through archival. Complete the design promotion record. No principle is promoted to repository architecture; no new capability/index is introduced.
  Amended in section 3: also correct `ARCHITECTURE.md`, "Discovery and
  negotiation", which says resolved family rates never reach a registry
  (promotion record row "D3/D4 correction"), and the storefront companion's
  asking-rate paragraph, which names no location.
  Amended in round 2's triage (16 F1): decide whether `docs/operator-handbook.md`
  needs D3's upgrade note — a version 9 registry refuses a version 8
  storefront's rated listings, so the two upgrade together.
  Done: registry companion (retained documents, seller evidence, listing
  pricing and the resize carrier, D5's rollback sentence); storefront companion
  (asking rate in `pricing`, rate structure published, repair through the
  domain's candidate); `ARCHITECTURE.md` and `ROADMAP.md` corrections; evidence
  lines in both specs; the handbook's "Registries and storefronts upgrade
  together", which the owner chose at closeout; the promotion record. The three
  deltas are merged by the archive (4.11), not by hand.
- [x] 4.10 Run scoped documentation citations and pinned `openspec validate store-registry-listings-as-published --strict` after promotion.
  `scripts/change-workflow run pre-commit` after promotion: strict validation
  "is valid"; `check-repository` (citations, comment hygiene, specification
  index, decision destinations, history wording, local imports) passed.
- [x] 4.11 Archive last, merging deltas with the pinned OpenSpec CLI and updating campaign link; review the archived documentation before cleanup.
  Deltas merged, not skipped (the permanent specs held none of them):
  `registry-discovery` +3 ~3, `resource-pool-management` ~1,
  `storefront-publication` +2 ~2; each diff read, every requirement present
  once as its delta states it, nothing else changed. Archived to
  `openspec/changes/archive/2026-11-11-store-registry-listings-as-published/`;
  the index row and the two evidence attachments citing `first-use.py` point
  there.

## Validation and handoff notes

Implementation evidence: `docs/attachments/store-registry-listings-as-published/implementation-evidence.md`
(round 1); stack replay: `docs/attachments/goal8-stack/registry.md`.

First use: after `make dist` and `make -C core/registry reinit`, run this
change's `first-use.py` from `core/registry` with
`uv run --find-links ../../.dist python <path to first-use.py>`: in-process
SQLite, deterministic development identities, no credentials or services.

PR: https://github.com/arkhai-io/simple-compute-market/pull/349 targets dev.

Final suites, from the pre-closeout triage's `scripts/change-workflow run
pre-commit` on the committed HEAD, every one passed: registry unit and
application integration (153 and 160 at round 2); registry-client 25; kit
capacity-publication 136; VM storefront unit 1150 (1 skipped) and application
integration 565; bare-metal storefront 611; bare-metal domain 226;
resource-pool kits 141, 426 and 82; API-credit storefront 275; e2e unit 896.
Hooks `after-functional-change`, `pre-commit-functional` (`make
check-packaging`) and `pre-commit` (index, tasks, skills, strict OpenSpec
validation, comment hygiene, citations, local imports) passed. Migration: fresh,
repeated and populated upgrades and legacy synthesis passed; no row is
rewritten.

Validations: 05 at `7e7e7ca58` failed (V1, V2; fixed in round 1's triage);
12 and 17 superseded; 22 at `758149f21` passed every part; 24 at `cd0ed8dc4`
inconclusive (runner DNS); 32 at `cd0ed8dc4` passed local and Helm, pipeline
waived (4.8).

Fixed outside the plan's sections, recorded in the triage records: round 1 —
the API-credit schema's settlement option (05 V1), repair through the domain's
candidate (05 V2, D6), the client's `storefront_url` docstring (03 F1), the
dated revision name and refusing downgrade (R4); round 2 — refusal of the
earlier price locations (16 F1) and `pricing` limited to listing-level prices
(16 F2); pre-closeout — the delta's buyer obligation narrowed to a consumer's
ability to verify (23 F1) and two comments restated as current rules (23 F2).

Residuals: readers up the stack of a top-level `rate_structure` or
`listing_resource.asking_rate` move to `pricing` in their own changes (D3);
whether and how a buyer verifies seller evidence is the resize change's gate
2.1a (D4); registry write hardening and carrier removal are unowned gaps in
`openspec/changes/README.md`.

Environment: unattended runs may not use `uv run --directory` or
`--find-links`; use `make -C <package> test-unit` / `test-integration` where a
package's environment needs the wheelhouse.
