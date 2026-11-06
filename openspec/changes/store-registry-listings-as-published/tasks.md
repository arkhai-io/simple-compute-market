# Implementation tasks

## 1. Retained publication contract

Implements D-a, D-c and D-e; registry, neutral client, and schema validation.

- [x] 1.1 Amend proposal and registry delta for whole-document replacement, legacy synthesis, reserved metadata, schema validation, and retained publication/update evidence; record D-a–D-e and the dependency correction in design and campaign index.
- [x] 1.2 Add an additive Alembic revision and model columns in `core/registry` for the document and seller evidence; leave existing carriers for legacy synthesis and storefront startup unchanged.
- [x] 1.3 Update `api/listing_routes.py`, `api/utils.py`, `api/publisher_auth.py`, and validation routes/models so accepted documents survive publication, detail/search use the same view, update evidence is explicit, and full schema validation runs at publish.
- [x] 1.4 Extend `core/registry-client` request models with opaque extra terms and preserve returned evidence in existing response extras.
- [x] 1.5 Run existing registry unit/application-integration and registry-client suites; directly try publish/read/search/republication, seller-proof verification, and legacy synthesis. Exercise fresh/upgrade migration. No existing e2e scenario asserts retained arbitrary fields or seller publication proofs; pipeline compute publication covers wire compatibility only. New permanent coverage needs maintainer approval.

## 2. VM listing-level rates

Implements D-b and supplies D-d's downstream authority/carrier answer.

- [x] 2.1 Wire `domains/vms/storefront` publication loop, terms and listing service/model through `domains/vms/listings` and schema-opaque `core/storefront/registry_publication.py`; correct the listing response comment. Publish current resolved family rates on create, refresh and reopen without moving asking_rate.
- [x] 2.2 Declare the optional top-level rate structure in the compute filter schema; keep registry engine domain-neutral.
- [x] 2.3 Run existing publication-loop/rate-composition application-integration suites, shared publication helpers and VM listing-model suites; try the published rate field through the registry. Existing compute e2e lanes exercise publication, but do not assert this new term. Record exact evidence and limitations here.
- [ ] 2.4 Refresh affected wheel/lock environments with repository tooling; run `make check-packaging`, comment hygiene, scoped citations/check-change and pinned strict OpenSpec validation. Prepare a reproducible first-use recipe. Commit and open PR into dev after updating from origin/dev; promotion waits for review.

## 3. Closeout (post code-review)

Per `openspec/README.md#plan-closeout-requirements`; promotion is deliberately not performed before review.

- [ ] 3.1 Confirm comment hygiene with `make check-comment-hygiene`; any code correction returns to implementation.
- [ ] 3.2 Confirm touched imports are module-level or have demonstrated reasons to remain local.
- [ ] 3.3 Check documentation placement for D-a–D-e against OpenSpec ownership rules.
- [ ] 3.4 Compress completed notes to behavior, evidence, residuals and promotion destinations, preserving design rationale.
- [ ] 3.5 Reconcile `docs/development/ROADMAP.md` registry/compute carrier descriptions where affected, or record no impact explicitly.
- [ ] 3.6 Update this change's campaign row/graph in `openspec/changes/README.md`; dependent release waits for archive cleanup.
- [ ] 3.7 Run `make check-packaging` and `make check-architecture-change CHANGE=store-registry-listings-as-published`; resolve all failures/owned exceptions.
- [ ] 3.8 Record end-to-end pipeline run/result and compute publication scenarios; disclose that retained-field/proof assertions are not covered by current e2e scenarios. Unavailable pipeline is a blocker, not a pass.
- [ ] 3.9 Promote registry delta through archival and rationale to `openspec/specs/registry-discovery/architecture.md`; promote storefront delta through archival and rationale to `openspec/specs/storefront-publication/architecture.md`. Complete design promotion record. Update repository architecture only if review identifies repository-wide knowledge; no new capability/index is introduced.
- [ ] 3.10 Run scoped documentation citations and pinned `openspec validate store-registry-listings-as-published --strict` after promotion.
- [ ] 3.11 Archive last, merging deltas with the pinned OpenSpec CLI and updating campaign link; review the archived documentation before cleanup.

## Validation and handoff notes

Implementation evidence: `docs/attachments/store-registry-listings-as-published/implementation-evidence.md`.

Registry unit/application integration: 267 passed; registry-client: 25 passed;
shared publication/model/persistence: 7 passed; focused VM model/composition/
publication-loop suites: 110 passed. Direct first use verified retained seller
proof, reads/search, whole-document replacement and distinct lifecycle evidence.
A temporary VM wire diagnostic validated an actual rate-bearing publication
against the compute schema, then was removed. Existing assertions/setup follow
the agreed contract; no new permanent tests were added.

Fresh/repeated/populated migration and legacy-synthesis experiments passed.
Base-chain repairs are separate commit `07c095789`: tolerate an already-current
shape name and add missing demands/API-key schema. No existing rows are rewritten.
`make check-packaging`, `make check-change` and pinned strict OpenSpec validation
passed. Reinitialization used repository wheel tooling; no locks changed.

First use: after `make dist` and `make -C core/registry reinit`, run
`(cd core/registry && uv run --find-links ../../.dist python ../../openspec/changes/store-registry-listings-as-published/first-use.py)`.
This is isolated in-process SQLite with deterministic development seller/registry
identities, readiness checked, no credentials or resident services required.

Full suite, PostgreSQL and external end-to-end pipeline are unrun; independent
verification and all post-review closeout remain outstanding. No promotion or
archival claimed. No roadmap goal is declared complete: this is a carrier
prerequisite for downstream resize/open-ended work. The campaign row/graph now
records the accepted carrier policy and dependency correction, without releasing
dependent changes before archival.
