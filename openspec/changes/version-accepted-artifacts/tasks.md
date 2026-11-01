# Tasks

The reviewed design is commit `112cc32306e2d6cc6e628a8ec3eadaaa6f695c2e`;
`reviews/01-design-external.triage.md` records the finding-free advance. No
implementation task was previously completed. D1–D5 mean the five numbered
decisions in `design.md`. The requirement names below refer to this change's
`specs/deployment-state/spec.md` and `specs/storefront-publication/spec.md`.
There are no implementation prerequisites.
Section commits are staging points: do not deploy them until sections 1–3 and
their integrated validation pass. Each section still satisfies its own focused
checks and packaging before commit.

## 1. Domain documents and evidence client contracts

Deliver immutable evidence/result documents, original-body serialization, and
compatible field reads (D1–D3; proof representation, signed wire contract, and
field-style usability requirements).

Files: `domains/bare_metal/src/arkhai_bare_metal/evidence.py`,
`evidence_routes.py`, and `__init__.py`; domain tests `test_evidence.py` and
`test_evidence_routes.py`; domain package metadata and the actual affected
consumer metadata/locks described in 1.5. No core or kit ownership changes.

- [x] 1.1 Implement the concrete immutable evidence/result documents and separate
  validated views in `evidence.py` (D1; proof-representation requirement). Retain
  canonical UTF-8 bytes, verify the expected outer digest and original result
  JSON's nested digest before view conversion, and expose `canonical_bytes`,
  `evidence_digest`, `result_digest`, `canonical_json()`, `to_wire()`, and `value`.
  Verify with unit cases for fixed v1 golden bytes/digests, changed view defaults,
  nested/outer tampering, unknown kinds/fields, and immutable retained data after
  a caller mutates a fresh `to_wire()` result.
- [x] 1.2 Keep new production and binding/fulfillment identity derivation on the
  fixed current-v1 representations (D1–D2). Extend the builder and its helpers to
  produce one snapshot without a new kind, algorithm, wrapper, or binding table.
  Verify existing identity fixtures and strict principal, resource-selection,
  timestamp, and credential-exclusion cases; pin that current v1 production has
  unchanged fields, null/omission rules, and canonical encoding.
- [x] 1.3 Update `evidence_routes.py`'s framework-free service and named signed
  carrier to sign retained bytes and serialize the original evidence object
  (D2–D3; signed-wire requirement). Preserve the existing field-style evidence
  and nested-result reads with explicit read-only properties and export the
  public document types from the domain package. Verify all existing field
  reads, byte-derived digest/canonical methods, reader roles, signature input,
  and the four unchanged envelope fields in domain unit tests.
- [x] 1.4 Make the shared async/sync response parsing retain original evidence
  JSON and match the requested digest before returning the validated document
  (D2–D3; client digest-matching scenarios). Preserve method signatures and the
  named signed-response return carrier. Verify both clients accept fixed v1
  responses, refuse another otherwise-valid document's digest and malformed
  content, and retain signature/role/resource behavior using recording transports.
- [x] 1.5 Version the new public types with the next minor release from
  `arkhai-bare-metal` 0.14.0, following D3 and
  `docs/development/RELEASING.md#versioning-policy`. Raise the minimum of
  consumers importing the document API, inventory every lock resolving the
  distribution, rebuild `.dist`, and refresh with shared `make lock`/`reinit`
  tooling rather than hand-editing lock records. Inspect the bare-metal
  storefront, buyer, provisioning adapter, VM storefront composition,
  provisioning-service adapter extra, and e2e harness; change only the metadata
  that needs the new API and locks resolving the changed distribution. Verify
  installed exports, wheel contents, and `make check-packaging` before this
  section's commit, so later new imports cannot depend on stale metadata.
- [x] 1.6 Verify this domain slice (D5; `docs/development/TESTING.md` and
  `openspec/config.yaml`): rebuild the domain wheel, refresh its environment,
  run unit-focused `test_evidence.py` and `test_evidence_routes.py`, then
  `make -C domains/bare_metal test` and `make check-packaging`; record exact commands/results and the
  exported annotation/serialization checks. End-to-end: existing
  `e2e_bare_metal_mock_deal` consumes these contracts after the storefront slice;
  no new system scenario is owed for codec permutations. No dedicated domain
  type-check target currently exists; disclose that and verify annotations and
  both typed-client signatures rather than claiming an unrun static check.

### Section 1 evidence and handoff

- Concrete frozen documents retain canonical bytes, verified identities, separate
  strict views and explicit read-only field properties. The signed carrier uses
  the original JSON for serialization in both schema modes; clients compare the
  requested digest before decoding. Golden content and all four identities were
  compared with the starting implementation, not regenerated as expectations.
- Unit checks: `domains/bare_metal/.venv/bin/python -m pytest
  domains/bare_metal/tests/test_evidence.py
  domains/bare_metal/tests/test_evidence_routes.py -q` — **30 passed**;
  `make -C domains/bare_metal test` — **210 passed**. Coverage includes defaults
  on evolved inputs, retained omitted defaults/explicit nulls/timestamp spelling,
  outer and nested tampering, strict validation, mutation isolation, all facade
  fields, client digest refusal, and the existing four-field signed envelope.
- Package release is `arkhai-bare-metal` **0.15.0**. Storefront alone imports the
  new document API and raises its minimum to 0.15.0. Buyer, provisioning adapter,
  VM composition, provisioning-service adapter extra, and e2e need no new API
  minimum. All seven locks resolving the distribution were refreshed using
  `make lock PROJECTS='domains/bare_metal domains/bare_metal/storefront
  domains/bare_metal/buyer domains/bare_metal/provisioning/adapter
  domains/vms/storefront provisioning/compute/service e2e-tests'`.
- The concrete Pydantic serialization adapter directly imports `pydantic-core`;
  it is declared. Its JSON-schema input API requires core 2.33/Pydantic 2.11,
  so those floors replace the previous Pydantic floor. The locked versions
  already satisfy them; no unrelated third-party upgrade was introduced.
- `make check-packaging` — **passed** after the final metadata/lock refresh;
  `make check-change CHANGE=version-accepted-artifacts` — **passed**;
  `git diff --check` — **passed**. An earlier packaging attempt correctly
  rejected the domain lock while the direct dependency was being declared;
  the shared lock refresh resolved it.
- `make -C domains/bare_metal/storefront reinit` and an installed-wheel check
  through that environment verified both exported document types, the signed
  carrier annotation, matching async/sync method signatures, both JSON schema
  modes and wheel module contents. There is no dedicated domain type-check
  target or existing domain `py.typed` marker; no static typing pass is claimed.
- Per the authorized round cadence, root `make test` and the independent diff
  review run once over sections 1–3 together; neither is claimed for this staging
  commit. The parent session arranges the independent review. No push or pipeline
  execution occurs in implementation. End-to-end remains
  `e2e_bare_metal_mock_deal` after the storefront slice; no extra system scenario
  or workflow-only job is owed. Owed by validation: none beyond ordinary validation.
- Next section must replace persistence's current-model parse with document
  verification and keep the worker from rebuilding a partially present/corrupt
  stored document. Intermediate source is deliberately not deployable.

## 2. Verified persistence, publication, and authenticated resolution

Deliver the running storefront's retained-byte path (D1–D3; persistence,
publication, signed-resolution, and client requirements).

Files: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py`,
`alkahest_lifecycle.py`, and `api.py`; extend
`domains/bare_metal/storefront/tests/test_alkahest_lifecycle.py` and relevant
persistence cases. Add focused real-SQLite coverage in
`domains/bare_metal/storefront/tests/integration/test_evidence_persistence.py`
if the existing tests cannot express the document boundary cleanly.

- [ ] 2.1 Make evidence load hash the existing canonical TEXT's UTF-8 bytes
  against its requested digest before returning a document; make first-write-wins
  save return the verified stored winner (D2; persistence requirement). Add real
  SQLite library-boundary integration cases for initial save, changed-candidate
  retry, absent row, process/repository restart, malformed/empty stored content,
  nested mismatch, and outer mismatch with a valid nested result. Assert original
  stored text and digest remain unchanged, including on refusal; add no migration.
- [ ] 2.2 Carry the verified document through `_lease_ready_evidence`, intent
  recording, and Alkahest publication (D2; restart-publication scenario). Extend
  existing application/lifecycle integration tests with the controlled chain
  boundary to observe the same retained digest before and after restart and
  assert corrupted stored evidence causes no submission. Keep unknown-outcome
  parking, attestation reuse, first-write-wins intent, and collection regression
  cases passing without adding a parallel recovery path.
- [ ] 2.3 Bind the document-aware signed carrier in `api.py` without allowing
  FastAPI/Pydantic serialization to replace retained evidence with a view dump
  (D2–D3; resolution and attribute scenarios). Exercise the real application and
  SQLite through the canonical async client and the sync client through a served
  loopback boundary where required. Verify retained-body proof bytes and JSON,
  requested-digest matching, nested field usability, successful buyer/claimant/admin
  reads, and unchanged stranger/unsigned/malformed-request refusals. Use raw HTTP
  only for invalid requests the typed client cannot construct, per the rejection
  exception in `docs/development/TESTING.md`.
- [ ] 2.4 Verify this storefront slice (D5): rebuild affected wheels and refresh
  the storefront environment; run the real-SQLite evidence cases, the evidence
  resolution/publication cases in `test_alkahest_lifecycle.py`, then
  `make -C domains/bare_metal/storefront test`. Record unit versus application
  integration evidence accurately and confirm no test-only production hooks or
  sleeps were introduced. End-to-end: `e2e_bare_metal_mock_deal`, including
  publication, authenticated evidence resolution, and subsequent collection;
  update its attribute reads only if needed for the reviewed facade, without
  changing its hold/step discipline. Pipeline execution is validation evidence,
  not a local test claimed here.
  Run `make check-packaging` before commit; rerun lock/build work from 1.5 only
  if this section actually changes dependencies or exposes a stale environment.

## 3. Consumer and regression validation

Deliver installable public types and complete local verification (D3–D5;
field-style usability and repository packaging/testing obligations).

Files: actual affected consumer tests and existing buyer/storefront regression
tests if their assertions require adaptation. Package metadata/locks are already
refreshed in 1.5; this section verifies their consumers rather than deferring an
API-required refresh to final cleanup.

- [ ] 3.1 Verify the installed consumers from 1.5 against the completed document
  path (D3): imports, public exports, matching client signatures, wheel contents,
  and `make check-packaging`. Record the precise consumer set exercised and
  confirm no old nested Pydantic-type assumption survives in a changed caller.
  Do not repeat lock refresh unless dependencies, locks, or wheel metadata changed.
- [ ] 3.2 Run the existing buyer payment-run producer/consumer regression
  `domains/bare_metal/buyer/tests/test_run_log_recovery.py` and
  `make -C domains/bare_metal/buyer test` (D2–D4). Run affected consumer suites
  from the metadata inventory, plus existing payment settlement, identity, and
  unknown-publication outcome regressions where this change touches their
  boundaries. Verify exact Agreement bytes, mandate/transaction identity,
  reader privileges, previous-wire refusal, and existing deletion contracts are
  not changed; do not add cross-domain conversion or a live purchase.
- [ ] 3.3 Complete local validation (D5; `AGENTS.md` and
  `openspec/README.md#implementation-completion-checklist`): run root `make test`,
  `make check-comment-hygiene`, `make check-architecture`,
  `make check-packaging`, and `make check-change CHANGE=version-accepted-artifacts`.
  Check only imports/comments added or touched by this change for placement and
  current-state rationale. Record results and any unrun typing checks, without
  replacing behavioral evidence with source-shape tests. End-to-end:
  `e2e_bare_metal_mock_deal` in the bare-metal pipeline lane; other pipeline lanes
  are composition regressions. Ordinary pre-review validation must report its
  local, Helm, pipeline, and supported CI results against the committed source;
  no additional workflow-only job is owed by this bounded change.
- [ ] 3.4 Maintain a design-promotion record in this task file mapping D1–D4 to
  the exact permanent destinations in 4.9, and D5 to the validation evidence
  (repository documentation ownership obligations). Classify the cross-domain
  inventory and hypothetical retirement machinery as deferred, not implemented.
  Verify every design decision and delta requirement is covered before requesting
  pre-closeout review; permanent document edits remain with closeout.

## 4. Closeout

Complete the eleven parts of
`openspec/README.md#plan-closeout-requirements` in order after the reviewed code
and required validation are complete (D4–D5 and repository obligations). This
section changes documentation only; a needed code fix returns to implementation.

- [ ] 4.1 **Comment hygiene:** confirm implementation already removed temporary
  history/change/task references and run `make check-comment-hygiene`. A failure
  returns to implementation; do not edit production comments at closeout.
- [ ] 4.2 **Import placement:** inspect imports this change added or touched and
  confirm module placement or a verified existing cycle/lazy-load rationale.
  A needed import move returns to implementation.
- [ ] 4.3 **Documentation compliance:** reconcile D1–D5, both delta specs, and
  proposal promotion entries with the planned permanent homes; verify the
  resulting claims concern the concrete bare-metal path and bounded evolution
  obligations, not universal artifact coverage or new retirement tooling.
- [ ] 4.4 **Narrative compression:** retain final behavior, exact validation,
  deferred work, and promotion destinations in task notes; move any necessary
  duplicated alternatives to the existing design and remove redundant chronology.
- [ ] 4.5 **Roadmap currency:** update
  `docs/development/ROADMAP.md#goal-1--consolidate-physical-resource-authority-in-the-provisioning-service`
  with the bounded accepted-evidence correction where applicable. No existing
  accepted-artifact gap row is present to remove. Record that fact and any
  remaining inventory disposition without inventing cross-domain completion;
  retain the payment-qualification boundary and claim no new live purchase evidence.
- [ ] 4.6 **Campaign index currency:** reconcile this change's row in
  `openspec/changes/README.md` and the Goal 1 dependency graph, retaining the
  actual closeout status and bounded acceptance description. Record whether
  the graph needs an edit; do not release dependents, which archive cleanup owns.
- [ ] 4.7 **Packaging:** confirm `make check-packaging` and
  `make check-architecture-change CHANGE=version-accepted-artifacts` pass and no
  exception row is owned by this change. Record `make check-agent-skills` as
  unnecessary unless implementation actually touched agent instructions.
- [ ] 4.8 **End-to-end pipeline:** confirm and record the exact committed-source
  validation run/result and the bare-metal `e2e_bare_metal_mock_deal` evidence for
  evidence publication, resolution, and collection. Preserve explicit blocked or
  unrun status for unavailable evidence; passing unrelated lanes is not a
  substitute. Confirm the normal local/Helm/CI validation record too.
- [ ] 4.9 **Promotion:** complete the design-promotion record. Promote D1–D4 to
  `docs/development/ARCHITECTURE.md#build-packaging-and-initialization`, adding
  an accepted-representation/view subsection without weakening existing explicit
  compatibility floors; to
  `openspec/specs/deployment-state/architecture.md#compatibility-posture`; and
  to a new `Retained bare-metal evidence` section in
  `openspec/specs/storefront-publication/architecture.md` beside its selected-site
  lifecycle explanation. Name both permanent `spec.md` destinations and the
  delta requirement headings in the record; archive merges their deltas in 4.11,
  rather than hand-editing normative specs here. Record the roadmap/index work
  from 4.5–4.6. Existing capability and companion index entries already exist in
  `openspec/specs/README.md`; confirm no new entry is owed. Write only current
  behavior and preserve deletion/tombstoning and unsupported-mandate boundaries.
- [ ] 4.10 **Documentation citations:** after promotion run
  `make check-doc-citations CHANGE=version-accepted-artifacts` and pinned strict
  OpenSpec validation; resolve every absent or tombstoned citation before archive.
  Check the permanent documents written here against actual branch paths and
  implemented behavior, not only the active change's links.
- [ ] 4.11 **Archival:** archive `version-accepted-artifacts` last with spec
  synchronization enabled, merging both delta specs into their permanent homes;
  update its index link to the resulting dated archive. Verify archive validation
  and citations, retain review/triage evidence, and hand off to closeout review.
