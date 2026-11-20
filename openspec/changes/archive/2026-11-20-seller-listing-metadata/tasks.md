# Tasks

## 1. First implementation

Implemented before the change entered review, on a base older than `dev`'s retained
signed document. Replanned against the reviewed design at the triage of
`01-implementation`: sections 2–6 carry it onto `dev` and correct it, and section 7
replaces the unchecked closeout line this section held.

- [x] 1.1 Add common envelope fields in `core/src/market_core`, registry schema, migration and signed routes in `core/registry`, and registry request/read models in `core/registry-client`.
  Correction (D3, F1): the registry's detail columns and migration `019_listing_details` are replaced by `dev`'s retained `published_document` in section 2, and proved in section 3.
- [x] 1.2 Wire seller inputs, persistence and publication through `core/storefront`, `core/storefront-client` and the VM, bare-metal and API-credits publications and seller CLI paths.
  Correction (D4, F2): the API-credit request's `description` takes the shared limit in section 6.
- [x] 1.3 Run existing focused suites for those boundaries and exercise signed publish, GET, validation and filtering.
  Correction (F3): this evidence is registry-level only; sections 3–6 add the storefront-level cases.

## 2. Merge `dev` and carry the change onto it

Delivers the implemented change on `dev`'s code, with no new behaviour: the
registry's details live in the retained document (D3) and the storefront's columns
join `dev`'s migration chain. Touches `core/registry`, `core/registry-client`,
`core/src/market_core`, `core/storefront`, `core/storefront-client`,
`domains/vms/listings`, `domains/vms/storefront`, `domains/bare_metal`,
`domains/bare_metal/storefront`, `domains/apicredits/storefront`.

- [x] 2.1 Merge `origin/dev` into the branch and resolve every conflict (D3, F1).
  Registry: keep `dev`'s publish path, which stores `dict(body)` as
  `published_document` and serves it through `order_to_dict`
  (`core/registry/src/core_registry/api/listing_routes.py`, `api/utils.py`,
  `db/models.py`); drop the branch's three detail columns and their reads and
  writes, and delete `core/registry/alembic/versions/019_listing_details.py` (that
  directory is gone on `dev`, whose revisions live under
  `core/registry/src/core_registry/alembic/versions/`) with no replacement
  revision. Keep the served-shape injection in `api/filter_spec.py` and re-seat the
  detail checks in `dev`'s `validate_listing_publication` and `validate_publish`
  (`api/validate_routes.py`, `api/validate_model.py`) so publish and dry run both
  refuse a stated value over a limit. Core storefront: `dev` deleted
  `sqlite_migrations.py`; the listing's `title`, `description` and `metadata`
  columns become a migration appended to `MIGRATIONS` in
  `core/storefront/src/core_storefront/migrations.py` (never an edit to
  `BASELINE`), and the column reads and writes are re-applied to `dev`'s
  `sqlite_client.py`. Domains: re-apply the override-sourced path onto `dev`'s
  reshaped modules, following the path `dev`'s `available_until_utc` override term
  takes (`domains/vms/storefront/src/market_storefront/services/publication_terms.py`,
  `publication_loop.py`, `domains/vms/listings/src/arkhai_vms_listings/reconciler.py`,
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`,
  `pool_overrides.py`). Verify: `git diff --check` reports no conflict marker and
  `git grep -n "listing_details" core/registry` names no column or revision.
  Merge commit `6cd479734` (`origin/dev` at `033e799a6`), started by the
  orchestrating session on the owner's word. The storefront migration is
  `20261118_001_listing_details`, last in `MIGRATIONS`; the registry's detail check
  runs in `listing_validation_errors`, which publish and dry run share. Both checks
  hold. Outside the plan: `write_listing_update` JSON-encodes only `metadata`, as the
  upsert stores `title` and `description` as plain text.
- [x] 2.2 Verify the merge (repository obligation: `AGENTS.md`, "Tests and
  diagnostics"). Rebuild the wheels (`make dist`, then `make reinit` in each touched
  project) and run, with proxy variables unset: registry unit and integration,
  registry-client, `core` unit, core storefront unit and integration,
  storefront-client, VM listings, VM storefront unit and integration, bare-metal
  domain and storefront, and API-credit storefront suites. Each passes, or a failure
  is shown to fail identically on `origin/dev` and named. Then run
  `scripts/change-workflow run pre-commit seller-listing-metadata` and
  `make check-packaging`; both pass.
  End-to-end: none new; validation's pipeline run on the merge commit is evidence
  that the merged stack still publishes and deals, through every lane's existing
  scenarios.
  Every named suite passes; VM listings' code runs under the VM storefront's
  suites. `make check-packaging` passes; the passing pre-commit is section 3's
  verification point, which carries the strict OpenSpec validation and
  `make check-local-imports` (3.3, 3.4).

## 3. The registry keeps seller details in the retained document

Delivers and proves the registry side: limits at publish and dry run, details
carried and withdrawn by the retained document, served shape, and metadata
filtering — D1, D2, D3, D5 on the registry client; MODIFIED "Schema-driven listing
validation" and ADDED "Seller details are discoverable through the filter spec".
Touches `core/src/market_core`, `core/registry`, `core/registry-client`, and the
change's `specs/registry-discovery/spec.md`.

- [x] 3.1 Unit-test the shared model (D2) in `core/tests/unit/test_listing_details.py`:
  each limit at and one past its bound (title 200, description 4000, 50 keys, key
  length 1–40 and its character class, string value 500); finite numbers and
  booleans admitted; null, array, object, NaN and infinity refused as metadata
  values; `supplied_listing_details` drops null and absent fields and keeps an empty
  string and an empty map. Passes under `core`'s unit target.
  `make -C core test-core`: 161 passed, the file's 31 among them, including the
  closed metadata schema (`design.md`, "Settled during implementation").
- [x] 3.2 Add `core/registry/tests/integration/test_listing_details.py`, through the
  canonical `RegistryClient` against the in-process registry (D1, D3, D5; both
  registry requirements): a listing stating all three reads back unchanged on
  `GET /listings` and `GET /listings/{id}` and inside its retained seller
  publication; the same `listing_id` republished with changed details reads the
  new values, and republished stating none reads none and no longer matches a
  declared `$.metadata["<key>"]` filter, which then decides it by its `on_missing`
  rule (F1); each limit violation, and a null, array or object metadata value, is
  refused naming the field with no listing content written, sent as a
  rejection-path raw call wherever the client refuses to build the body
  (`TESTING.md`, "no raw calls"); an explicit null is admitted as unstated and served
  as sent, as "Accepted listing content is retained" keeps it; the dry-run route
  reports the same errors; the served `listing_shape` declares all three fields; a
  listing stating none publishes and reads exactly as before. Registry-client unit
  tests (`core/registry-client/tests/`) show `ListingRequest.to_dict` and
  `ValidatePublishRequest.to_dict` omit unstated fields and `ListingSummary` parses
  stated ones.
  `make -C core/registry test`: 162 unit and 181 integration passed; the file's 9
  cases run the app in process with real SQLite storage, every call through the
  typed client, and the retained body is where an explicit null is asserted.
  Registry-client: 37 passed, `tests/test_listing_details.py`'s 6 among them.
  Correction: no call is raw, since the typed client builds every refused body;
  each limit's edges are 3.1's alone (`test-levels.md`, "Coverage between the
  levels"), and `tests/unit/test_listing_validation.py` gains 7 cases for what
  publication validation adds. Outside the plan: the closed metadata object.
- [x] 3.3 Delete `docs/attachments/seller-listing-metadata/` (`roundtrip.py`,
  `roundtrip-output.json`): 3.2 supersedes its round trip at the lowest level that
  proves it, and its function-level imports are the `make check-local-imports`
  failure the validation notes record. Verify: `make check-local-imports` passes.
  Removed; `make check-local-imports` passes.
- [x] 3.4 Bring the change's registry delta onto `dev`'s specification (D3): the
  MODIFIED "Schema-driven listing validation" in
  `openspec/changes/seller-listing-metadata/specs/registry-discovery/spec.md`
  carries `dev`'s current requirement text and both its scenarios, with the detail
  fields' sentences and scenarios added, so the archive does not revert `dev`'s
  wording; the ADDED "Seller details are discoverable through the filter spec" says
  the details are kept in the listing's retained publication document, replacing
  "envelope columns of their own". Verify:
  `scripts/change-workflow openspec validate seller-listing-metadata --strict`
  passes.
  `dev`'s paragraph and scenarios are kept word for word, the details a second
  paragraph with the dry run's refusal, the served shape's limits, and "A detail is
  stated as null"; the ADDED requirement gains "A seller withdraws its details by
  republication". 3.2 exercises every scenario the change adds. Strict validation
  passes.
- [x] 3.5 Verification point: registry unit and integration (`make -C core/registry
  test`), `core` unit, and registry-client suites pass, with 3.1 at unit level and
  3.2 at application-integration level through the typed client;
  `scripts/change-workflow run pre-commit seller-listing-metadata` and
  `make check-packaging` pass.
  End-to-end: `e2e_bare_metal_publication` and `e2e_deal` publish listings stating
  no details through a real registry, evidence for the unchanged path only;
  `e2e_credits_deal` publishes the API-credit seed's `description` (6.3). No
  scenario is owed, since 3.2 proves the stated path against the real registry
  through its typed client.
  The three suites pass, with the counts above. Correction: pre-commit failed only
  two `make test-release-tooling` tests, neither this change's — the multi-storefront
  compose test with no `docker` on the session's `PATH` (it passed at 4.4), and the
  workflow-assumption test on `scripts/openspec`, fixed on `dev` by `421f32a31`;
  every later target passed run alone. Outside the plan: the e2e
  harness's `_settle` (`e2e-tests/tests/e2e/roles/helpers/in_process_buyer.py`)
  joins the ended command thread, since `exited` could read false while it unwound
  and fail `test_one_release_advances_the_clock_one_interval_and_lets_one_wait_return`;
  read from the code, and passing since.

## 4. A seller's create request carries details

Delivers the manual compute surface and the storefront's persistence and fan-out —
D4 (VM create request), D5 on the storefront client; ADDED "A seller may state
details beside the listing envelope". Touches `core/storefront`
(`models/listing_models.py`, `sqlite_client.py`, `migrations.py`,
`registry_publication.py`, `publication_runner.py`), `core/storefront-client`
(`client.py`, `models.py`), and `domains/vms/storefront`
(`services/listing_service.py`).

Correction (the owner's direction at section 4's start): before 4.1 the change made
its once-per-change version bump, which no task planned (`versioning.md`, "One bump
per unit of work"), each version one step from `origin/dev`'s: minor for every
package whose contents changed (`arkhai-core` 0.7.0, the registry 0.7.0, its client
0.14.0, the core storefront 0.19.0, its client 0.31.0, VM listings 0.10.0, VM
storefront 0.30.0, bare metal 0.17.0, its storefront 0.30.0, the API-credit
storefront 0.22.0); patch for every package whose one change is a moved exact pin;
and lower bounds raised to the first version holding what each consumer imports.
The VM storefront's `arkhai-core-storefront-client>=0.30.0` stays, since only its
tests call 0.31.0's additions. `make check-version-bumps CHANGE_BASE=origin/dev` and
`make check-locks` pass.

- [x] 4.1 Core storefront library integration
  (`core/storefront/tests/integration/test_listing_details.py`): the detail
  migration adds the three columns to a database at `dev`'s previous head and is
  part of a fresh chain; a listing saved with details loads them, metadata as a
  map; an update sets and clears each; `publish_listing_to_registries` sends only
  stated fields to every registry (D5).
  `make -C core/storefront test`: 244 passed, the file's 5 among them, each against
  real SQLite migrated through core's chain.
- [x] 4.2 VM storefront application integration through
  `StorefrontClient.create_listing` against the in-process app
  (`domains/vms/storefront/tests/integration/`), registries replaced at the client
  wrapper as `test_publication_loop.py`'s `registry_world` does: a create stating
  all three stores them, the listing read returns them, and every registry is sent
  them unchanged; a republication of that listing (term refresh or resume) sends
  them again; a create stating none sends no detail key; a create over a limit is
  refused before a listing row exists (rejection-path raw call).
  `TestCreateListingDetails` in `tests/integration/test_listings_api.py`, 3 cases;
  the republication is the administrator's pause and resume. Correction: no call is
  raw, since the typed client sends the refused body itself; which limit each field
  carries is `core/storefront/tests/unit/test_listing_models.py`'s. `make -C
  domains/vms/storefront test` passes.
- [x] 4.3 Confirm the storefront client's sync/async parity contract test covers
  `create_listing`'s new parameters (`TESTING.md`, "Sync/async client parity"), and
  `StorefrontListingSummary` parsing of stated details in
  `core/storefront-client/tests/`.
  Confirmed: `domains/vms/storefront/tests/unit/test_storefront_client_parity.py`
  compares both clients' signatures; `core/storefront-client/tests/test_lifecycle_auth.py`
  gains a create stating all three through both clients, byte-equal, and the parsed
  model, `storefront_client.models.ListingSummary`, is
  `tests/test_listing_details.py`'s (3 cases). `make -C core/storefront-client
  test`: 79 passed. Correction: the parity rule is
  `docs/guidance/engineering/integration-tests.md`, "Sync and async client parity".
- [x] 4.4 Verification point: core storefront unit and integration,
  storefront-client, and VM storefront unit and integration suites pass, 4.2 being
  the application-integration case; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_deal` creates its VM listing stating no details, evidence for the
  unchanged create path only; no scenario is owed.
  Pre-commit passes every hook, its `make validate-local` running `make
  check-packaging` and the whole `make test`.

## 5. Compute listings take their details from the pool override

Delivers override-sourced details as a term of sale in both compute domains —
D4; ADDED "A compute listing derives its details from the pool override". Touches
`domains/vms/listings` (`models.py`, `reconciler.py`, `listing_comparison.py`),
`domains/vms/storefront` (`models/pool_override_models.py`,
`services/publication_loop.py` or `publication_terms.py`, wherever 2.1 seated it),
`domains/bare_metal` (`storefront_publication.py`), and
`domains/bare_metal/storefront` (`pool_overrides.py`, `publication.py`,
`publication_composition.py`, `settlement_composition.py`, `sqlite_client.py`).

Sections 1 and 2 had already carried the override's `details` through both cycles;
this section added proof and no behaviour.

- [x] 5.1 VM publication-cycle integration in
  `domains/vms/storefront/tests/integration/test_publication_loop.py`, overrides
  written through the storefront's override surface: a pool override stating
  `details` publishes its listing with them; changing them refreshes the same
  `listing_id` in place at every registry; an override that stops stating them
  republishes that `listing_id` with no detail key and leaves the local row's
  columns null (F1, F3). A VM storefront unit test shows `VmPoolOverrideTerms`
  refusing details over a limit.
  `test_an_overrides_details_publish_refresh_in_place_and_clear_when_withdrawn`
  through `tests.publication_app`'s app and the typed `PoolOverrideClient`: add,
  then two `refresh`es with no status update, the withdrawn body carrying no detail
  key. Unit, `tests/unit/test_vm_pool_override_contribution.py`: two refusals
  located under `terms.details`. `make -C domains/vms/storefront test` passes.
- [x] 5.2 Bare-metal publication-cycle integration in
  `domains/bare_metal/storefront/tests/test_publication_cycle.py`, the same add,
  change and withdraw sequence on one listing; a bare-metal storefront unit test
  shows `BareMetalPoolOverrideTerms` refusing details over a limit; the term-field
  projection in `domains/bare_metal/tests/test_storefront_publication.py` holds.
  Correction: the case is application integration in a new
  `tests/integration/test_pool_override_details.py`, over `test_http_system.py`'s
  `_derivation_runtime`, since `test_publication_cycle.py` builds the cycle by hand.
  Unit, `tests/test_pool_override_terms.py`. `make -C domains/bare_metal test`: 226
  passed; `make -C domains/bare_metal/storefront test`: 680 passed. Outside the
  plan: the `pool_overrides.py` docstrings name `details`. The storefront's flat
  test root is an unowned gap in `openspec/changes/README.md`.
- [x] 5.3 Verification point: VM listings, VM storefront unit and integration,
  bare-metal domain and bare-metal storefront suites pass, 5.1 and 5.2 being the
  application-integration cases; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_bare_metal_publication` steps publication through the site's
  overrides and a real registry with no details stated, evidence for the unchanged
  path only; no scenario is owed, since withdrawal at the registry is proved by 3.2
  and the storefront's withdrawn payload by 5.1 and 5.2.
  Pre-commit passes every hook. No committed scenario or driver writing a pool
  override states `details`.

## 6. API-credit prose under the shared limit

Delivers the quota-backed publish's seller details and refuses overlong prose
before a listing row exists — D4 (F2); ADDED "An API-credit listing carries its
seller's prose". Touches `domains/apicredits/storefront`
(`listing_publication.py`, `services/listing_service.py`,
`controllers/listings_controller.py`, `cli.py`).

- [x] 6.1 Type `PublishFromQuotaRequest.description` as the shared
  `ListingDescription` (`listing_publication.py`). A unit test in
  `domains/apicredits/storefront/tests/unit/` shows 4000 characters admitted and
  4001 refused by the request model.
  `tests/unit/test_publish_from_quota_request.py` (2 cases). Outside the task's
  text: the `publish` command refuses as a usage error (`design.md`, "Settled during
  implementation"), shown by
  `tests/unit/test_listing_publication_entry_points.py`'s
  `test_a_description_past_its_limit_fails_as_usage_before_any_storefront_is_opened`.
- [x] 6.2 Application integration through `ApiCreditListingClient.publish_from_quota`
  against the in-process app (`domains/apicredits/storefront/tests/integration/`):
  a publish stating all three sends `title` and `metadata` beside the envelope and
  the description both beside it and, unchanged, inside `listing_resource`; a
  publish stating none sends no envelope detail key; a description over the limit
  is refused 422 and no listing row exists afterwards (rejection-path raw call).
  `tests/integration/test_listing_details.py` (4 cases), the real app and lifespan
  with two registries replaced at both bindings of `_make_registry_client`.
  Correction: the refusal builds its body with `PublishFromQuotaRequest.model_construct`
  and sends it through the typed client. Outside the plan: the listing service
  checks the details itself for the seed's path (`design.md`, "Settled during
  implementation"), shown by
  `test_a_seed_description_past_the_envelope_limit_gives_the_seed_up_with_no_listing`.
  Deferred: the composition offers no registry seam, so the test replaces the
  module-level factory; recorded as an unowned gap in `openspec/changes/README.md`.
- [x] 6.3 Verification point: API-credit storefront unit and integration suites
  pass, 6.2 being the application-integration case; `scripts/change-workflow run
  pre-commit seller-listing-metadata` and `make check-packaging` pass.
  Pre-commit passes every hook; the API-credit storefront ran 292 passed.
  End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` discover the
  listing the API-credit lane's storefront seeds (`storefront.credits.lane.toml`, `[seed]`, as
  `storefront.credits.toml` does for the full local stack), and the seed states
  `description = "Prepaid weather-API credits"`. They therefore publish that
  description beside the envelope and inside `listing_resource` through a real
  API-credit registry, which is evidence that a real registry admits a stated
  description on the seed's path. They state no title or metadata, and the seed
  calls the listing service directly, so the seller's route and request model
  are proven by 6.1 and 6.2 alone. No scenario is owed.

## 7. Closeout

Documentation only, after the pre-closeout review; a part needing a code edit
returns the change to implementation. The parts, in order: the workflow's
(`docs/guidance/workflow/closeout.md`), with this repository's
(`openspec/README.md#this-repositorys-closeout-parts`) after campaign index
currency.

- [x] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and confirm the
  comments sections 2–6 added describe current invariants; a needed edit returns the
  change to implementation.
  The check passes. Every comment and docstring the change added since `dev` was
  read: each states a current invariant or reason, and none names a change, task,
  review, or migration.
- [x] 7.2 **Import placement.** Confirm the imports sections 2–6 added are
  module-level (`make check-local-imports`), or keep a verified reason; a move
  returns the change to implementation.
  `make check-local-imports` passes: every import added inside a function gives its
  reason.
- [x] 7.3 **Documentation compliance.** Check D1–D5 against
  `openspec/README.md#documentation-placement`: normative behaviour in the two spec
  deltas, rationale in the companions 7.9 names, nothing left only in the change.
  Each decision's normative part is in a delta and its rationale in a companion
  (`design.md`, "Design promotion record"). Three delta lines worded relative to
  history were rewritten: the registry's "A listing without seller details" now
  says its reads carry none of the three, and the API-credit requirement and
  scenario no longer appeal to what consumers "always" or "already" read.
- [x] 7.4 **Narrative compression.** Compress the validation notes below to final
  behaviour, material evidence (the suites and tests of sections 3–6), and
  destinations; drop the superseded round-trip and migration-019 notes.
  Notes in sections 2–6 compressed and the section handoffs dropped: what they held
  is final behaviour, now in the notes, the companions, or "Settled during
  implementation" in `design.md`; or session guidance (proxy, wheelhouse, base
  branch) superseded by later sections. The round-trip, migration-019 and
  first-implementation suite notes are dropped.
- [x] 7.5 **Roadmap currency.** `docs/development/ROADMAP.md` names no goal or gap
  row for seller listing details; confirm that on the merged roadmap and record the
  no-impact disposition in the design promotion record.
  Confirmed on the merged roadmap; recorded.
- [x] 7.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md` (status and notes) and run `make check-change-index`;
  record the update in the promotion record.
  The row reads `in closeout` with current notes; no row depends on this change,
  and it has no campaign. The API-credit registry seam gap (6.2) gained a row under
  "Unowned work with no campaign". `scripts/change-workflow check index` passes.
- [x] 7.7 **Packaging.** Run `make check-packaging` and
  `make check-architecture-change CHANGE=seller-listing-metadata`; resolve every
  failure, leaving no exception owned by this change.
  Both pass, through `scripts/change-workflow run pre-archive
  seller-listing-metadata` at `8a5b7e349`. The change touched no `.agents/`,
  `.claude/` or `.codex/` path.
- [x] 7.8 **End-to-end pipeline.** Record the passing run the latest validation
  names, its result, and the coverage as it is: `e2e_credits_deal` and
  `e2e_credits_payment_deal` publish the API-credit seed's `description` beside the
  envelope and inside `listing_resource` through a real registry; `e2e_deal` and
  `e2e_bare_metal_publication` state no details and cover the unchanged path only;
  `title`, `metadata`, an override's `details`, and the seller's create route are
  proven at the integration and application-integration levels by the tests of
  sections 3–6. Or an
  explicit blocker naming its cause and owning change, with the validations it
  gates treated as unrun.
  `22-validation` at `8a5b7e349`, the commit closeout builds on: pipeline run
  44744814677 (`e2e.yml`) succeeded, e2e-vm 444, e2e-bare-metal 249 and
  e2e-apicredits 4 passed, read at lane level; local and Helm passed, Helm serving
  none of the four scenarios. Coverage is as this task states it: the credits
  scenarios publish the seeded `description` through a real registry, the other two
  the unchanged path. `18-validation`'s contrary account carries its own correction
  (`19-pre-closeout` F1). No `Owed by validation:` line.
- [x] 7.9 **Promotion.** Write: `openspec/specs/registry-discovery/architecture.md`,
  a new "Seller-authored listing details" section after "Retained publication
  documents" — D1's placement and its rejected alternatives, D2's single source of
  limits, D3's storage in the retained document and served-shape injection;
  `openspec/specs/storefront-publication/architecture.md` "Storefront pool
  overrides" — `details` as a term of sale, refreshed and cleared like the others
  (D4); `openspec/specs/storefront-publication/configuration.md` "Storefront listing
  shapes and pool overrides" — `details` among the override terms an operator may
  state, with its limits; the `## Evidence` lists of
  `openspec/specs/registry-discovery/spec.md` and
  `openspec/specs/storefront-publication/spec.md` — the tests of sections 3–6. The
  two `spec.md` requirement sets are written by the archive in 7.12. Complete the
  design promotion record in `design.md` with each destination.
  Written as named. Beyond the list, D4's manual surfaces and API-credit prose and
  D5 take a "Seller-authored listing details" section in
  `storefront-publication/architecture.md`, after "Compute terms of sale"; the
  registry section carries D5 and the closed metadata object too. Neither
  capability has an `index.md`. Promotion record completed.
- [x] 7.10 **Guidance placement.** The change adds and rewrites no guidance file; the
  companions and configuration text 7.9 writes describe their capability. Confirm
  that against the layer test, record it, and run `make check-guidance`.
  Confirmed: the change touched no file under `docs/guidance/`, `AGENTS.md`, or
  `openspec/README.md`; `configuration.md` is the capability's own guidance and its
  new bullet describes that capability's override terms alone. `make
  check-guidance` passes.
- [x] 7.11 **Documentation citations.** Run
  `make check-doc-citations CHANGE=seller-listing-metadata` and resolve every
  match, then `openspec validate seller-listing-metadata --strict`.
  Both pass, and `scripts/change-workflow run pre-commit seller-listing-metadata
  --base origin/dev` passes every check (`{base}` given, as the hook names it).
- [x] 7.12 **Archival.** Last: `openspec archive seller-listing-metadata -y`,
  merging both deltas into `openspec/specs/registry-discovery/spec.md` and
  `openspec/specs/storefront-publication/spec.md`; point the index row at the
  archived directory and run `openspec validate --specs --strict`.
  Archived as `openspec/changes/archive/2026-11-20-seller-listing-metadata/`: the
  registry delta's MODIFIED requirement and ADDED one and the storefront delta's
  three ADDED ones merged, each once as stated, nothing else touched; no
  `--skip-specs`, since neither spec held the deltas' text. The index row links the
  archived directory, and `scripts/change-workflow run pre-commit` passes, every
  specification validating strictly.

## Validation notes

- Final validation: `reviews/22-validation.md` at `8a5b7e349`, local, pipeline
  (run 44744814677) and Helm passed; the end-to-end coverage is 7.8's.
