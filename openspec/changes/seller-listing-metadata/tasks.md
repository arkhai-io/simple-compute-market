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
  Done as merge commit `6cd479734` (`origin/dev` at `033e799a6`): the implement step
  may not fetch or merge, so the orchestrating session started the merge on the
  owner's word, resolving the change index, and a merge-resolution run resolved the
  fifteen code files left conflicted as this task directs. The storefront migration is `20261118_001_listing_details`,
  last in `MIGRATIONS`; the registry's detail check runs inside
  `listing_validation_errors`, which publish and dry run share. Checked here:
  `git diff --check origin/dev HEAD` reports nothing, no conflict marker is in
  `core/` or `domains/`, and `git grep -n listing_details core/registry` names only
  the `market_core.listing_details` imports in `api/filter_spec.py` and
  `api/validate_routes.py`. Outside the plan: the re-applied `write_listing_update`
  JSON-encoded `title` and `description`, which the upsert stores as plain text, so
  an update would have stored `"x"` with its quotes; only `metadata` is encoded now.
  Sections 4 and 5 prove the update path.
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
  After `make dist`, each `make -C <package> test` (which runs its `reinit`):
  registry 155 unit and 172 integration passed; registry-client 31; `core` unit
  (`make -C core test-core`) 130; core storefront 234, its library integration
  included; storefront-client 75; VM storefront 1199 unit passed, 1 skipped, and
  632 integration passed; VM domain 60; bare-metal domain 226. VM listings has no
  suite of its own: its reconciler, comparison and models run under the VM
  storefront's unit and integration suites. Three suites failed only on the
  session's SOCKS `ALL_PROXY` (`socksio` not installed): bare-metal storefront 65
  failed, 611 passed; VM storefront integration 2 failed
  (`test_watchdog_buy.py`); API-credit storefront 1 failed
  (`test_lifecycle_status.py`), 284 passed. Every failure's traceback is that
  ImportError. This step's rules do not let a command clear the proxy variables,
  and `run test-before --at origin/dev` cannot collect the API-credit file (its
  `--no-project` environment lacks `injected_time`), so each was rerun with
  `socksio` added instead: `uv run --directory <package> --with socksio pytest`
  (`--find-links ../../../.dist` for the VM storefront) gave bare-metal storefront
  676 passed, API-credit storefront 285 passed, and VM `test_watchdog_buy.py` 2
  passed. `make check-packaging` passes. `scripts/change-workflow run pre-commit
  seller-listing-metadata --base origin/dev` (the change's clone records no landing
  branch, so `{base}` is given) fails two checks, both work the plan gives section 3
  and so outside this section: the strict OpenSpec validation, as the registry
  delta's MODIFIED "Schema-driven listing validation" lacks `dev`'s scenario "A
  schema-invalid publication is submitted" (3.4), and `make check-local-imports` on
  `roundtrip.py:92`, `:109` and `:115` (3.3). Correction: 2.2 asked both checks to
  pass, which its plan's order made impossible before section 3; section 3's
  verification point carries the passing pre-commit. A third failure, the guidance
  check on section 7's preamble citing a "plan closeout requirements" heading
  `openspec/README.md` no longer has, was fixed here, outside the plan: the
  preamble cites `closeout.md` and that README's "This repository's closeout parts"
  instead, and section 7 gains the Guidance placement part `closeout.md` lists
  between Promotion and Documentation citations, which it lacked (7.10; citations
  and archival renumbered 7.11 and 7.12). Correction: the three suites above did not
  pass as 2.2 words it, nor were their failures shown on `origin/dev`; the `socksio`
  reruns stand in for both, since every failure was the proxy's ImportError. 2.2's
  "`AGENTS.md`, "Tests and diagnostics"" names a heading `AGENTS.md` no longer has;
  the wheel rebuild and `reinit` it asks for are
  `docs/guidance/repository/wheelhouse.md` and `project-environments.md`. `core`
  unit ran as `make -C core test-core`, which has no `reinit`; `arkhai-core` has no
  internal dependency to refresh.

Handoff from section 2:

- `core/storefront/pyproject.toml` and `domains/apicredits/storefront/pyproject.toml`
  declare `arkhai-core>=0.4.0`, but both now import `market_core.listing_details`,
  which only `arkhai-core` 0.6.0 has (`versioning-python.md`, "Compatibility is
  declared by lower bounds"). Section 4 raises the core storefront's bound to
  `>=0.6.0` and section 6 the API-credit storefront's, each in its own functional
  commit, with `make lock`. Left here because section 2's commit touches only inert
  paths, and a `pyproject.toml` edit would make it run the whole `make
  validate-local` matrix for a one-line fix those sections carry anyway.
- The session's environment sets a SOCKS `ALL_PROXY` without `socksio`, and the
  implement step may not clear it; every test whose client builds an httpx transport
  then fails at construction. `uv run --directory <package> --with socksio pytest …`
  (`--find-links ../../../.dist` for the VM storefront) runs them; a `make -C
  <package> test` failure whose traceback is that ImportError is environmental.
- `scripts/change-workflow run pre-commit` needs `--base origin/dev`: the clone
  records no landing branch.
- The registry's explicit-null handling sits in `listing_validation_errors`
  (`core/registry/src/core_registry/api/validate_routes.py`): a detail stated as null
  is dropped from the served-schema check, and `ListingDetails` admits it, so 3.2's
  "an explicit null is admitted as unstated and served as sent" exercises that
  branch.

## 3. The registry keeps seller details in the retained document

Delivers and proves the registry side: limits at publish and dry run, details
carried and withdrawn by the retained document, served shape, and metadata
filtering — D1, D2, D3, D5 on the registry client; MODIFIED "Schema-driven listing
validation" and ADDED "Seller details are discoverable through the filter spec".
Touches `core/src/market_core`, `core/registry`, `core/registry-client`, and the
change's `specs/registry-discovery/spec.md`.

- [ ] 3.1 Unit-test the shared model (D2) in `core/tests/unit/test_listing_details.py`:
  each limit at and one past its bound (title 200, description 4000, 50 keys, key
  length 1–40 and its character class, string value 500); finite numbers and
  booleans admitted; null, array, object, NaN and infinity refused as metadata
  values; `supplied_listing_details` drops null and absent fields and keeps an empty
  string and an empty map. Passes under `core`'s unit target.
- [ ] 3.2 Add `core/registry/tests/integration/test_listing_details.py`, through the
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
- [ ] 3.3 Delete `docs/attachments/seller-listing-metadata/` (`roundtrip.py`,
  `roundtrip-output.json`): 3.2 supersedes its round trip at the lowest level that
  proves it, and its function-level imports are the `make check-local-imports`
  failure the validation notes record. Verify: `make check-local-imports` passes.
- [ ] 3.4 Bring the change's registry delta onto `dev`'s specification (D3): the
  MODIFIED "Schema-driven listing validation" in
  `openspec/changes/seller-listing-metadata/specs/registry-discovery/spec.md`
  carries `dev`'s current requirement text and both its scenarios, with the detail
  fields' sentences and scenarios added, so the archive does not revert `dev`'s
  wording; the ADDED "Seller details are discoverable through the filter spec" says
  the details are kept in the listing's retained publication document, replacing
  "envelope columns of their own". Verify:
  `scripts/change-workflow openspec validate seller-listing-metadata --strict`
  passes.
- [ ] 3.5 Verification point: registry unit and integration (`make -C core/registry
  test`), `core` unit, and registry-client suites pass, with 3.1 at unit level and
  3.2 at application-integration level through the typed client;
  `scripts/change-workflow run pre-commit seller-listing-metadata` and
  `make check-packaging` pass.
  End-to-end: no scenario states details. `e2e_bare_metal_publication`, `e2e_deal`
  and `e2e_credits_deal` publish listings stating none through a real registry, so
  the pipeline is evidence for the unchanged path only; no scenario is owed, since
  3.2 proves the stated path against the real registry through its typed client.

## 4. A seller's create request carries details

Delivers the manual compute surface and the storefront's persistence and fan-out —
D4 (VM create request), D5 on the storefront client; ADDED "A seller may state
details beside the listing envelope". Touches `core/storefront`
(`models/listing_models.py`, `sqlite_client.py`, `migrations.py`,
`registry_publication.py`, `publication_runner.py`), `core/storefront-client`
(`client.py`, `models.py`), and `domains/vms/storefront`
(`services/listing_service.py`).

- [ ] 4.1 Core storefront library integration
  (`core/storefront/tests/integration/test_listing_details.py`): the detail
  migration adds the three columns to a database at `dev`'s previous head and is
  part of a fresh chain; a listing saved with details loads them, metadata as a
  map; an update sets and clears each; `publish_listing_to_registries` sends only
  stated fields to every registry (D5).
- [ ] 4.2 VM storefront application integration through
  `StorefrontClient.create_listing` against the in-process app
  (`domains/vms/storefront/tests/integration/`), registries replaced at the client
  wrapper as `test_publication_loop.py`'s `registry_world` does: a create stating
  all three stores them, the listing read returns them, and every registry is sent
  them unchanged; a republication of that listing (term refresh or resume) sends
  them again; a create stating none sends no detail key; a create over a limit is
  refused before a listing row exists (rejection-path raw call).
- [ ] 4.3 Confirm the storefront client's sync/async parity contract test covers
  `create_listing`'s new parameters (`TESTING.md`, "Sync/async client parity"), and
  `StorefrontListingSummary` parsing of stated details in
  `core/storefront-client/tests/`.
- [ ] 4.4 Verification point: core storefront unit and integration,
  storefront-client, and VM storefront unit and integration suites pass, 4.2 being
  the application-integration case; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_deal` creates its VM listing stating no details, evidence for the
  unchanged create path only; no scenario is owed.

## 5. Compute listings take their details from the pool override

Delivers override-sourced details as a term of sale in both compute domains —
D4; ADDED "A compute listing derives its details from the pool override". Touches
`domains/vms/listings` (`models.py`, `reconciler.py`, `listing_comparison.py`),
`domains/vms/storefront` (`models/pool_override_models.py`,
`services/publication_loop.py` or `publication_terms.py`, wherever 2.1 seated it),
`domains/bare_metal` (`storefront_publication.py`), and
`domains/bare_metal/storefront` (`pool_overrides.py`, `publication.py`,
`publication_composition.py`, `settlement_composition.py`, `sqlite_client.py`).

- [ ] 5.1 VM publication-cycle integration in
  `domains/vms/storefront/tests/integration/test_publication_loop.py`, overrides
  written through the storefront's override surface: a pool override stating
  `details` publishes its listing with them; changing them refreshes the same
  `listing_id` in place at every registry; an override that stops stating them
  republishes that `listing_id` with no detail key and leaves the local row's
  columns null (F1, F3). A VM storefront unit test shows `VmPoolOverrideTerms`
  refusing details over a limit.
- [ ] 5.2 Bare-metal publication-cycle integration in
  `domains/bare_metal/storefront/tests/test_publication_cycle.py`, the same add,
  change and withdraw sequence on one listing; a bare-metal storefront unit test
  shows `BareMetalPoolOverrideTerms` refusing details over a limit; the term-field
  projection in `domains/bare_metal/tests/test_storefront_publication.py` holds.
- [ ] 5.3 Verification point: VM listings, VM storefront unit and integration,
  bare-metal domain and bare-metal storefront suites pass, 5.1 and 5.2 being the
  application-integration cases; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_bare_metal_publication` steps publication through the site's
  overrides and a real registry with no details stated, evidence for the unchanged
  path only; no scenario is owed, since withdrawal at the registry is proved by 3.2
  and the storefront's withdrawn payload by 5.1 and 5.2.

## 6. API-credit prose under the shared limit

Delivers the quota-backed publish's seller details and refuses overlong prose
before a listing row exists — D4 (F2); ADDED "An API-credit listing carries its
seller's prose". Touches `domains/apicredits/storefront`
(`listing_publication.py`, `services/listing_service.py`,
`controllers/listings_controller.py`, `cli.py`).

- [ ] 6.1 Type `PublishFromQuotaRequest.description` as the shared
  `ListingDescription` (`listing_publication.py`). A unit test in
  `domains/apicredits/storefront/tests/unit/` shows 4000 characters admitted and
  4001 refused by the request model.
- [ ] 6.2 Application integration through `ApiCreditListingClient.publish_from_quota`
  against the in-process app (`domains/apicredits/storefront/tests/integration/`):
  a publish stating all three sends `title` and `metadata` beside the envelope and
  the description both beside it and, unchanged, inside `listing_resource`; a
  publish stating none sends no envelope detail key; a description over the limit
  is refused 422 and no listing row exists afterwards (rejection-path raw call).
- [ ] 6.3 Verification point: API-credit storefront unit and integration suites
  pass, 6.2 being the application-integration case; `scripts/change-workflow run
  pre-commit seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` publish without a
  description, evidence for the unchanged path only; no scenario is owed.

## 7. Closeout

Documentation only, after the pre-closeout review; a part needing a code edit
returns the change to implementation. The parts, in order: the workflow's
(`docs/guidance/workflow/closeout.md`), with this repository's
(`openspec/README.md#this-repositorys-closeout-parts`) after campaign index
currency.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and confirm the
  comments sections 2–6 added describe current invariants; a needed edit returns the
  change to implementation.
- [ ] 7.2 **Import placement.** Confirm the imports sections 2–6 added are
  module-level (`make check-local-imports`), or keep a verified reason; a move
  returns the change to implementation.
- [ ] 7.3 **Documentation compliance.** Check D1–D5 against
  `openspec/README.md#documentation-placement`: normative behaviour in the two spec
  deltas, rationale in the companions 7.9 names, nothing left only in the change.
- [ ] 7.4 **Narrative compression.** Compress the validation notes below to final
  behaviour, material evidence (the suites and tests of sections 3–6), and
  destinations; drop the superseded round-trip and migration-019 notes.
- [ ] 7.5 **Roadmap currency.** `docs/development/ROADMAP.md` names no goal or gap
  row for seller listing details; confirm that on the merged roadmap and record the
  no-impact disposition in the design promotion record.
- [ ] 7.6 **Campaign index currency.** Update this change's row in
  `openspec/changes/README.md` (status and notes) and run `make check-change-index`;
  record the update in the promotion record.
- [ ] 7.7 **Packaging.** Run `make check-packaging` and
  `make check-architecture-change CHANGE=seller-listing-metadata`; resolve every
  failure, leaving no exception owned by this change.
- [ ] 7.8 **End-to-end pipeline.** Record the passing run the latest validation
  names, its result, and the scenarios that exercise this change's unchanged path
  (`e2e_deal`, `e2e_bare_metal_publication`, `e2e_credits_deal`,
  `e2e_credits_payment_deal`), stating that no scenario states details; or an
  explicit blocker naming its cause and owning change, with the validations it
  gates treated as unrun.
- [ ] 7.9 **Promotion.** Write: `openspec/specs/registry-discovery/architecture.md`,
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
- [ ] 7.10 **Guidance placement.** The change adds and rewrites no guidance file; the
  companions and configuration text 7.9 writes describe their capability. Confirm
  that against the layer test, record it, and run `make check-guidance`.
- [ ] 7.11 **Documentation citations.** Run
  `make check-doc-citations CHANGE=seller-listing-metadata` and resolve every
  match, then `openspec validate seller-listing-metadata --strict`.
- [ ] 7.12 **Archival.** Last: `openspec archive seller-listing-metadata -y`,
  merging both deltas into `openspec/specs/registry-discovery/spec.md` and
  `openspec/specs/storefront-publication/spec.md`; point the index row at the
  archived directory and run `openspec validate --specs --strict`.

## Validation notes

- Returned to planning at the triage of `01-implementation`. The tasks above were implemented on a base older than `dev`'s retained signed document (`published_document`), so the registry columns and migration `019_listing_details` are replaced by that document (F1), the API-credit request takes the shared description limit (F2), and the storefront paths gain focused tests: a typed-client create and republish in each storefront, a compute cycle adding, changing and withdrawing an override's details on one listing, and the API-credit refusal (F3). The replanned work starts by merging `dev`.
- `scripts/change-workflow run pre-commit seller-listing-metadata --base origin/dev` fails one check on the branch as implemented: `make check-local-imports` reports the function-level imports at `docs/attachments/seller-listing-metadata/roundtrip.py:92`, `:109` and `:115`. The replanned work moves them or gives each its reason.

- Registry: 139 unit + 128 integration (full integration directory) passed. Storefront: 182 unit passed. VM storefront: 1215 unit + 530 integration passed, 1 pre-existing skip. Bare metal: 224 domain + 590 storefront passed. API credits: 255 passed. VM buyer: 215 passed. Clients: 25 + 68 passed. Registry-client mypy clean; the VM storefront's mypy reports pre-existing errors (145 on its base) and none in the touched files.
- Signed publish → GET round trip with VM/bare-metal/API-credits resources carrying the fields: `docs/attachments/seller-listing-metadata/roundtrip.py`, output in `roundtrip-output.json` (run from `core/registry`). Covers refusal naming the field, the dry-run route, `$.metadata["acme.tier"]` filtering both by value and on missing, and unchanged reads for listings without the fields.
- Migration 019 exercised by downgrade to 018 and re-upgrade on a stamped database; fresh databases create the columns through `create_all` and stamp head.
- Tests that reach httpx fail on a machine with `ALL_PROXY` set to a SOCKS URL (`socksio` not installed); run suites with the proxy variables unset. Unrelated to this change.
- Environments install internal packages as wheels from `.dist/`, so after editing a package run `make dist` and `make reinit` in every project that installs it before trusting a test run; a stale wheel fails as an extra-forbidden field.
