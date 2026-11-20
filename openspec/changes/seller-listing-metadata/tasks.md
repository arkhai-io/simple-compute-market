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
  Correction (section 3): `origin/dev`'s `arkhai-core` 0.6.0 has no
  `market_core.listing_details` (`git show origin/dev:core/src/market_core/listing_details.py`
  fails); the module exists only on this branch, which has not bumped
  `arkhai-core`, so a `>=0.6.0` bound admits a published 0.6.0 without it. Section
  3's handoff names the bump this needs.
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

- [x] 3.1 Unit-test the shared model (D2) in `core/tests/unit/test_listing_details.py`:
  each limit at and one past its bound (title 200, description 4000, 50 keys, key
  length 1–40 and its character class, string value 500); finite numbers and
  booleans admitted; null, array, object, NaN and infinity refused as metadata
  values; `supplied_listing_details` drops null and absent fields and keeps an empty
  string and an empty map. Passes under `core`'s unit target.
  Unit, `make -C core test-core`: 161 passed, the file's 31 among them. The
  file also holds the metadata JSON Schema closed (`additionalProperties: false`),
  the fix recorded under 3.2.
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
  Application integration, `make -C core/registry test`: 162 unit and 181
  integration passed. The integration file runs the registry app in process over
  `ASGITransport` with its real SQLite storage, every call through the canonical
  `RegistryClient` signing as the maker; its 9 cases cover the round trip on
  detail and search reads and inside the decoded `publisher_publication` body;
  add, change and withdraw on one `listing_id` under a compute specification
  extended with `$.metadata["acme.tier"]` (`on_missing: fail`), the withdrawn
  listing then excluded and found again under `strict.acme_tier=false`; one
  refusal (a null metadata value), 422 with the field named in its body, no
  listing afterwards, and the dry run reporting errors that name the field and
  each appear in the publication's refusal; a refused republication leaving the
  stored details, evidence and `updated_at`; explicit nulls, admitted by the dry
  run and publication and kept as nulls in the retained body (the typed client
  reads a served null and an absent field alike, so the served null itself is not
  asserted); the served `listing_shape` on both the compute and the API-credit
  specification, each detail equal to the shared model's schema less its null and
  the metadata object closed; and a listing stating none. No call is raw: the
  typed client carries the details as plain values and leaves their limits to the
  registry, so it builds every refused body itself, and an explicit null travels
  in `ListingRequest.extra`, since the client omits an unstated detail.
  Correction: 3.2 asks for each limit violation at this level, which
  `test-levels.md`'s "Coverage between the levels" puts at unit level only; the
  limits are 3.1's, and the registry's unit `tests/unit/test_listing_validation.py`
  gains 7 cases for what `listing_validation_errors` adds — both its sources name
  the field for a prose, key and value refusal, NaN and infinity refused though the
  served schema admits them, and stated or null details reporting nothing.
  Registry-client unit, `make -C core/registry-client test`: 37 passed,
  `tests/test_listing_details.py`'s 6 among them. Outside the plan: pydantic
  renders the metadata key's character class as `patternProperties`, which alone
  admits a key outside the class with any value, so the served schema admitted
  keys the publish boundary refuses; `ListingMetadata` in
  `core/src/market_core/listing_details.py` now closes the object
  (`json_schema_extra={"additionalProperties": False}`). What publication and the
  dry run admit is unchanged; a key outside the class now also draws the served
  schema's error beside the model's, and the served specification's ETag changes
  with its `listing_shape`. The schema the registry served before the fix, read in
  this session's first run of the served-shape case, had `patternProperties` and
  no `additionalProperties`; `run test-before` cannot rerun that case at
  `9fc81bbed`, as its `--no-project` environment has no `sqlalchemy` and
  collection fails.
- [x] 3.3 Delete `docs/attachments/seller-listing-metadata/` (`roundtrip.py`,
  `roundtrip-output.json`): 3.2 supersedes its round trip at the lowest level that
  proves it, and its function-level imports are the `make check-local-imports`
  failure the validation notes record. Verify: `make check-local-imports` passes.
  Removed with `git rm`; nothing else cited it but this change's notes.
  `make check-local-imports` passes.
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
  The MODIFIED requirement keeps `dev`'s paragraph and both its scenarios word for
  word; the details follow as a second paragraph, which now also requires the dry
  run to refuse and says the served shape declares the details with their limits,
  whatever specification is loaded, refusing all publication refuses but a
  non-finite number (the closed metadata object of 3.2). Its detail scenarios read the seller's retained
  publication, replace "no listing row is written" with `dev`'s "leaves prior
  listing content unchanged", and add the dry run's matching errors and "A detail
  is stated as null". The ADDED requirement keeps the details in the retained
  publication document and gains "A seller withdraws its details by
  republication". 3.2 exercises every scenario the change adds, "A listing without
  seller details" by its parsed fields and its retained body. Strict validation
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
  After `make dist`: registry 162 unit and 181 integration passed; `core` unit
  (`make -C core test-core`) 161; registry-client 37. `scripts/change-workflow run
  pre-commit seller-listing-metadata --base origin/dev`: its `pre-commit` hook
  passes (index, tasks, skills, strict OpenSpec validation, `make
  check-repository` with the citations and local-import checks), its `make lock`
  rewrote no lock, and its `make validate-local` passes `make check-packaging`
  and fails `make test` on two tests of `make test-release-tooling` only, neither
  this change's: `scripts/tests/test_multi_storefront_compose.py::test_storefront_authorities_are_isolated`,
  as this session has no `docker` on its `PATH`, and
  `scripts/tests/test_change_workflow_assumptions.py::test_every_target_and_path_the_step_table_and_the_fragment_name_is_provided_here`,
  as `.claude/change-steps.toml` names `scripts/openspec` and
  `openspec/specs/market-change-workflow/README.md`'s "How this repository
  provides the workflow's roles" does not list it. That test was not run on
  `origin/dev`; every file it reads is identical there (`033e799a6`, its workflow
  maintenance), so, reading only the tree, it would fail there the same way. The
  step table is the orchestrator's to edit. `make test`
  stops at that target, so the targets after it ran on their own, all passing:
  `make -C helm test-render`, and `make test-frp-grant-admission` (203 passed, 15
  skipped), `test-injected-time` (81), `test-lane-double-controls` (149),
  `test-payments-lane-double` (101) and `test-mediation-lane-double` (78).
  Correction: 3.5 asks pre-commit to pass, which these two failures prevent here.
  Outside the plan: two earlier runs failed only on
  `e2e-tests/tests/unit/test_in_process_buyer.py::test_one_release_advances_the_clock_one_interval_and_lets_one_wait_return`,
  at its final `assert run.exited`, and passed alone and in `make -C e2e-tests
  test-unit` (1024 passed). The cause is read from the code, not reproduced: the
  harness's `_settle` (`e2e-tests/tests/e2e/roles/helpers/in_process_buyer.py`)
  returns once the command sets `ended`, which its thread does in its last
  statements before finishing, so a caller can read `exited` false while the thread
  unwinds, and `_streams_kept`, which reads `exited` too, can skip restoring the
  streams. `_settle` now joins the ended thread. The run after the fix passed the
  e2e unit target inside `make test`; one passing run is all that shows. This
  branch changed nothing else under `e2e-tests`. End-to-end confirmed: no
  committed scenario, stack configuration or storefront configuration states a
  listing detail, so the three scenarios above publish none.
  Correction (section 6): both API-credit storefront configurations' `[seed]`
  state a `description`, which the seed publishes beside the envelope, so
  `e2e_credits_deal` publishes one detail through a real registry; 6.3 records it.

Handoff from section 3:

- `arkhai-core` needs its once-per-change bump, and the plan has no task for it.
  `origin/dev` and this branch both hold 0.6.0, and only this branch has
  `market_core.listing_details` (`versioning.md`, "One bump per unit of work";
  `package-versions.md`, "A version changes when its contents change"), so the
  `>=0.6.0` bound sections 4 and 6 plan cannot exclude a 0.6.0 without the module.
  The bump is not small: `core/registry`, `core/registry-client`, `kit/alkahest`,
  `kit/arkhai-payments`, `kit/contact-exchange`, `kit/policy` and
  `kit/settlement-runtime` pin `arkhai-core==0.6.0`, so each pin moves, and each of
  those packages bumps, with its own exact pinners (`core/buyer` and
  `domains/bare_metal/buyer` pin `arkhai-core-registry-client==0.13.0`), then a
  relock of every project. `core/registry` (0.6.1) and `core/registry-client`
  (0.13.0) changed on this branch too and are unbumped. Left for the round's
  triage to plan, since it reaches packages outside every section; once
  `arkhai-core` is bumped, sections 4–6 raise their consumers' bounds to the bumped
  version rather than `>=0.6.0`.
- `ListingDetails`' JSON Schema closes the metadata object
  (`additionalProperties: false`). A storefront or pool-override model that renders
  the shared types into a schema of its own now carries that too; sections 4–6
  touch those models and may see it in a generated schema or an OpenAPI snapshot.
  Every registry's served filter specification changes with it, so its ETag does,
  and a buyer holding the old ETag gets one `412` before it rereads the spec.
- The typed `RegistryClient` reads a served `null` detail and an absent one alike
  (`ListingSummary.from_dict`), so no typed-client test can tell them apart; the
  retained `publisher_publication` body is where a test sees what was sent.
- Do not edit the worktree while `scripts/change-workflow run pre-commit` runs: its
  `make validate-local` validates one tree and fails when the tree changes under it.

## 4. A seller's create request carries details

Delivers the manual compute surface and the storefront's persistence and fan-out —
D4 (VM create request), D5 on the storefront client; ADDED "A seller may state
details beside the listing envelope". Touches `core/storefront`
(`models/listing_models.py`, `sqlite_client.py`, `migrations.py`,
`registry_publication.py`, `publication_runner.py`), `core/storefront-client`
(`client.py`, `models.py`), and `domains/vms/storefront`
(`services/listing_service.py`).

Correction (the owner's direction at section 4's start, on section 3's handoff):
before 4.1 the change makes its once-per-change version bump, which no task
planned (`versioning.md`, "One bump per unit of work"; `package-versions.md`, "A
version changes when its contents change"). Each version is one step from
`origin/dev`'s:

- Minor, for every package whose contents the change alters, since each gains the
  details as public API and sections 5 and 6 add within that: `arkhai-core`
  0.7.0, `arkhai-core-registry` 0.7.0, `arkhai-core-registry-client` 0.14.0,
  `arkhai-core-storefront` 0.19.0, `arkhai-core-storefront-client` 0.31.0 (its
  README's package line with it), `arkhai-vms-listings` 0.10.0,
  `arkhai-vms-storefront` 0.30.0, `arkhai-bare-metal` 0.17.0,
  `arkhai-bare-metal-storefront` 0.30.0, `arkhai-apicredits-storefront` 0.22.0.
- Patch, for every package whose one change is a moved exact pin, followed to
  their own exact pinners: `arkhai-kit-alkahest` 0.13.1, `arkhai-kit-policy`
  0.7.1, `arkhai-kit-settlement-runtime` 0.8.2, `arkhai-kit-arkhai-payments`
  0.9.1, `arkhai-kit-contact-exchange` 0.5.2, `arkhai-kit-config` 0.6.2,
  `arkhai-kit-negotiation-runtime` 0.6.1, `arkhai-kit-capacity-publication`
  0.12.1, `arkhai-core-buyer` 0.8.1, `arkhai-bare-metal-buyer` 0.9.1,
  `arkhai-vms-buyer` 0.13.1, `arkhai-compute-provisioning-service` 0.26.1.
- Lower bounds raised to the first version holding what each consumer uses:
  `arkhai-core>=0.7.0` in the core, API-credit, bare-metal and VM storefronts,
  which import `market_core.listing_details` (the bound sections 4 and 6 planned
  as `>=0.6.0`); `arkhai-core-registry-client>=0.14.0` in the core storefront,
  whose fan-out passes the details to `ListingRequest`, and in the registry's dev
  group; `arkhai-core-storefront>=0.19.0` in the three domain storefronts;
  `arkhai-bare-metal>=0.17.0` in the bare-metal storefront;
  `arkhai-vms-listings>=0.10.0` in the VM storefront.

Outside the direction, which named `arkhai-core`, the registry and its client:
the other packages the change alters are bumped here too, as the same rule asks,
in the one relock, so sections 5 and 6 bump nothing; raising the core storefront's
bound changes its wheel in any case. `make check-version-bumps
CHANGE_BASE=origin/dev` passes, `make lock` rewrote 43 locks, and `make
check-locks` passes.

- [x] 4.1 Core storefront library integration
  (`core/storefront/tests/integration/test_listing_details.py`): the detail
  migration adds the three columns to a database at `dev`'s previous head and is
  part of a fresh chain; a listing saved with details loads them, metadata as a
  map; an update sets and clears each; `publish_listing_to_registries` sends only
  stated fields to every registry (D5).
  Library integration, `make -C core/storefront test`: 244 passed, the file's 5
  among them, each against a real SQLite database migrated through core's chain.
  The migration case stops the chain before `20261118_001_listing_details`,
  inserts a listing, migrates on, and reads the columns null; a load and a list
  read the details back with metadata as a map; updates set all three, change one
  leaving the others, and clear all three; the fan-out case loads each stored
  listing and publishes it through `publish_listing_to_registries` with the real
  `registry_client.ListingRequest`, the registry client injected, and every
  registry's body carries all three, only the title, or no detail key, as stored.
  `run test-before` cannot run the file at the round's base: its `--no-project`
  environment has no `market_identity`, and collection fails.
- [x] 4.2 VM storefront application integration through
  `StorefrontClient.create_listing` against the in-process app
  (`domains/vms/storefront/tests/integration/`), registries replaced at the client
  wrapper as `test_publication_loop.py`'s `registry_world` does: a create stating
  all three stores them, the listing read returns them, and every registry is sent
  them unchanged; a republication of that listing (term refresh or resume) sends
  them again; a create stating none sends no detail key; a create over a limit is
  refused before a listing row exists (rejection-path raw call).
  Application integration, `TestCreateListingDetails` in
  `tests/integration/test_listings_api.py`: the listings router with the real
  listing service, seller and administrator auth, and `recorded_registries()`
  standing where `MultiRegistryClient` wraps the two registries, as
  `publication_app` places it. A seller's typed-client create stating all three is
  read back by `get_listing` and sent unchanged to both registries; the
  administrator's pause and resume republish it from the stored row, and both
  registries are sent the three again; a create stating none reads none and sends
  no detail key; a description over its limit is refused 422 with no listing row
  and nothing sent. Correction: no call is raw. The typed client carries the
  details as plain values and leaves their limits to the storefront, so it sends
  the refused body itself, as section 3 found for the registry. Which limit each
  field carries is request-model validation, unit level only (`test-levels.md`,
  "Coverage between the levels"): `core/storefront/tests/unit/test_listing_models.py`
  shows `CreateListingRequest`, which the VM request extends, admitting all three
  at their limits, stating none by default, and refusing each one past its limit
  with the error on that field. The republication is the resume, since the plan
  admits either; a term refresh of an override-sourced listing is 5.1's.
  `make -C domains/vms/storefront test` before the refusal cases moved: 1199 unit
  passed, 1 skipped, and 639 integration passed; the class now holds 3 cases,
  which pass.
- [x] 4.3 Confirm the storefront client's sync/async parity contract test covers
  `create_listing`'s new parameters (`TESTING.md`, "Sync/async client parity"), and
  `StorefrontListingSummary` parsing of stated details in
  `core/storefront-client/tests/`.
  Confirmed: `domains/vms/storefront/tests/unit/test_storefront_client_parity.py`
  compares every public method's resolved signature on `StorefrontClient` and
  `SyncStorefrontClient`, `create_listing`'s `title`, `description` and `metadata`
  among them, and passes in the VM storefront's unit run. A signature guard sends
  nothing, so `core/storefront-client/tests/test_lifecycle_auth.py` gains a
  create stating all three through both clients, whose bodies carry them and are
  byte-equal; its existing create case shows both omitting an unstated detail
  (D5). The parsed model is `storefront_client.models.ListingSummary`; unit,
  `core/storefront-client/tests/test_listing_details.py` (3 cases): stated details
  read into their fields and out of `extra`, unstated ones read as `None`, and a
  listing list reads each listing's. `make -C core/storefront-client test`: 79
  passed. `run test-before` cannot run the new client file at the round's base: its
  `--no-project` environment has no `market_identity`, and collection fails.
  Correction: `TESTING.md` has no "Sync/async client parity"; the rule is
  `docs/guidance/engineering/integration-tests.md`, "Sync and async client parity".
- [x] 4.4 Verification point: core storefront unit and integration,
  storefront-client, and VM storefront unit and integration suites pass, 4.2 being
  the application-integration case; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_deal` creates its VM listing stating no details, evidence for the
  unchanged create path only; no scenario is owed.
  `scripts/change-workflow run pre-commit seller-listing-metadata --base origin/dev`
  passes every hook: its `make lock`, its `make validate-local` (`make
  check-packaging` and the whole `make test`, `docker` now on the `PATH`, so
  `test_multi_storefront_compose.py` ran and passed), and the `pre-commit` checks,
  version bumps among them. In that `make test`: core storefront 244 passed,
  storefront-client 79, VM storefront 1199 unit passed with 1 skipped and 637
  integration; beside them the bump's other consumers, among them registry 162
  unit and 181 integration, registry-client 37, bare-metal storefront 676 and
  API-credit storefront 285. End-to-end confirmed: no committed VM scenario's
  `create_listing` states a detail.

Handoff from section 4:

- The version bump is done for the whole change: every package sections 5 and 6
  touch is already one step from `origin/dev`, so neither bumps, moves a pin, or
  raises the `arkhai-core` bound section 2's handoff gave them; a later edit
  needing a larger step than its package has is the only reason to bump again.
  The VM storefront's `arkhai-core-storefront-client>=0.30.0` stays: its code
  uses none of 0.31.0's additions, which only its tests call, against the locked
  0.31.0.
- The `ALL_PROXY` failures sections 2 and 3 worked around are gone with the
  variable: every suite here ran as `make -C <package> test`, VM
  `test_watchdog_buy.py` included.
- `tests/integration/test_listings_api.py`'s `publishing_clients` fixture is the
  listings router with seller and administrator clients over
  `recorded_registries()`; `_accepted_escrow_listing_service` builds the real
  listing service it and `_full_client` share.
- The typed storefront client sends a detail over its limit as stated, so a
  storefront refusal test needs no raw call.

## 5. Compute listings take their details from the pool override

Delivers override-sourced details as a term of sale in both compute domains —
D4; ADDED "A compute listing derives its details from the pool override". Touches
`domains/vms/listings` (`models.py`, `reconciler.py`, `listing_comparison.py`),
`domains/vms/storefront` (`models/pool_override_models.py`,
`services/publication_loop.py` or `publication_terms.py`, wherever 2.1 seated it),
`domains/bare_metal` (`storefront_publication.py`), and
`domains/bare_metal/storefront` (`pool_overrides.py`, `publication.py`,
`publication_composition.py`, `settlement_composition.py`, `sqlite_client.py`).

- [x] 5.1 VM publication-cycle integration in
  `domains/vms/storefront/tests/integration/test_publication_loop.py`, overrides
  written through the storefront's override surface: a pool override stating
  `details` publishes its listing with them; changing them refreshes the same
  `listing_id` in place at every registry; an override that stops stating them
  republishes that `listing_id` with no detail key and leaves the local row's
  columns null (F1, F3). A VM storefront unit test shows `VmPoolOverrideTerms`
  refusing details over a limit.
  Application integration,
  `test_an_overrides_details_publish_refresh_in_place_and_clear_when_withdrawn`:
  the app `tests.publication_app` builds, its real routers and container, each
  override written through the typed `PoolOverrideClient` over the storefront
  client, each cycle the `publication` lifecycle step after `site-projections`,
  and the two registries replaced where `MultiRegistryClient` wraps them. One
  unbacked listing publishes the three details to both registries and reads them
  back through `get_listing`; a changed title is one `refresh`, republished to
  both with no status update; the override replaced with none is another
  `refresh`, again with no status update, both registries sent no detail key,
  and `get_listing` reads the three as null. That read is the local row: the
  storefront serves its listing from it, and its client reads a null and an
  absent detail alike. The override must state something (the pool-override kit
  refuses an empty one, 422), so each version keeps `max_duration_seconds: 7200`.
  Unit, `tests/unit/test_vm_pool_override_contribution.py`: the contribution's
  `vocabulary_problems`, which validates through `VmPoolOverrideTerms`, reads
  stated details beside the other terms and names a description far past its
  limit under `terms.details.description` and a null metadata value under
  `terms.details.metadata.acme.tier`. Correction: those two show the term is the
  shared model; each limit's edges stay 3.1's alone, so a limit changed in
  `market_core` changes one suite (`test-levels.md`, "Coverage between the
  levels"). `make -C domains/vms/storefront test`: 1201 unit passed, 1 skipped,
  and 638 integration passed.
- [x] 5.2 Bare-metal publication-cycle integration in
  `domains/bare_metal/storefront/tests/test_publication_cycle.py`, the same add,
  change and withdraw sequence on one listing; a bare-metal storefront unit test
  shows `BareMetalPoolOverrideTerms` refusing details over a limit; the term-field
  projection in `domains/bare_metal/tests/test_storefront_publication.py` holds.
  Correction: the case is a new `tests/integration/test_pool_override_details.py`,
  not `test_publication_cycle.py`, whose docstring says its tests prove
  orchestration and persistence and are not integration evidence; there it is
  application integration, as 5.3 calls it, and it imports the flat root's site
  double and runtime as the other integration modules do. Application
  integration,
  `test_an_overrides_details_publish_refresh_in_place_and_clear_when_withdrawn`:
  the running app over `test_http_system.py`'s `_derivation_runtime`, each cycle
  composed as production composes it under the real Alkahest composition, each
  override written through the typed `PoolOverrideClient` over the
  administrator's `StorefrontClient`, each cycle the `publication` step, and the
  site and registry doubled where this codebase wraps them. The add, change
  (`refresh` naming `listing.title`) and withdraw (`refresh` naming the three)
  sequence on one `listing_id`, each cycle a single publish and no status update,
  read back through `get_listing` after each, open each time: the three stated,
  the changed title, then all three null, the withdrawn body carrying no detail
  key. Unit, `tests/test_pool_override_terms.py`: the model admits stated details
  and refuses the same two as 5.1, each error located under its field; the module
  stays in the flat root the unowned gap below records. The term-field projection
  holds: `make -C domains/bare_metal test`, 226 passed. `make -C
  domains/bare_metal/storefront test`: 680 passed.
- [x] 5.3 Verification point: VM listings, VM storefront unit and integration,
  bare-metal domain and bare-metal storefront suites pass, 5.1 and 5.2 being the
  application-integration cases; `scripts/change-workflow run pre-commit
  seller-listing-metadata` and `make check-packaging` pass.
  End-to-end: `e2e_bare_metal_publication` steps publication through the site's
  overrides and a real registry with no details stated, evidence for the unchanged
  path only; no scenario is owed, since withdrawal at the registry is proved by 3.2
  and the storefront's withdrawn payload by 5.1 and 5.2.
  `scripts/change-workflow run pre-commit seller-listing-metadata --base
  origin/dev` passes every hook: its `make lock` rewrote no lock, its `make
  validate-local` passed `make check-packaging` and the whole `make test`, and
  the `pre-commit` checks passed. That `make test` gave the counts above.
  VM listings has no suite of its own; its reconciler and comparison run under the
  VM storefront's. `run test-before` cannot collect the new terms test at the
  round's base: its `--no-project` environment has no `pydantic`. End-to-end
  confirmed: no scenario states `details`; every scenario and driver writing a
  pool override (`e2e_bare_metal_publication`, the VM lane's `e2e_listing_shapes`
  and `e2e_compute_dynamic_listings`, both domains' introduction drivers, the
  bare-metal purchase driver) states none, evidence for the unchanged path only.

Handoff from section 5:

- Section 5 changed no behaviour: sections 1 and 2 had already carried the
  override's `details` through both cycles, and every new test passed on the code
  as it stood once the test itself was right.
- `uv run --directory <package> pytest …` fails to resolve until `make dist`
  rebuilds the wheelhouse with section 4's versions; the VM and bare-metal
  storefronts need `--find-links ../../../.dist` beside it. `make -C <package>
  test` reinstalls from the wheelhouse without rebuilding it, so it too reads the
  wheels `make dist` last built.
- The bare-metal cycle's report names a refreshed term as `listing.<field>`; the
  VM report's counts are what 5.1 asserts.
- The bare-metal storefront's application-integration harness for publication
  is `test_http_system.py`'s `_derivation_runtime` (production cycle composition,
  Alkahest, a recorded registry at `runtime.registry_configuration.recording`);
  a new integration module goes in `tests/integration/` and imports it and the
  flat root's doubles by name. `test_publication_cycle.py` builds the cycle by
  hand and is not integration evidence. An override write judged against the
  site's live hints needs `capacity_client=_Sites(site)`.
- Outside the plan: the bare-metal `pool_overrides.py` module and
  `BareMetalPoolOverrideTerms` docstrings named only the lease bounds and the
  other terms, missing `details`, which sections 1 and 2 added; both now name
  it. The bare-metal storefront's flat test root is recorded as an unowned gap in
  `openspec/changes/README.md`, "Unowned work with no campaign".

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
  Unit, `tests/unit/test_publish_from_quota_request.py` (2 cases): 4000
  characters admitted, 4001 refused with its one error on `description`. Outside
  the task's text, in a file the section names: the `publish` command
  (`cli.py`) builds the request model before it reads the credential or opens a
  storefront, so a request the model refuses fails as a usage error (exit 2)
  with the model's errors, where the sync client's validation had raised a
  traceback; unit, `tests/unit/test_listing_publication_entry_points.py`'s
  `test_a_description_past_its_limit_fails_as_usage_before_any_storefront_is_opened`,
  replacing only the command module's own `_open_storefront`, shows a description
  far past the limit exiting 2, `description` named, and no storefront opened.
  That one case is the evidence; a title or metadata the model refuses takes the
  same branch, untested here.
- [x] 6.2 Application integration through `ApiCreditListingClient.publish_from_quota`
  against the in-process app (`domains/apicredits/storefront/tests/integration/`):
  a publish stating all three sends `title` and `metadata` beside the envelope and
  the description both beside it and, unchanged, inside `listing_resource`; a
  publish stating none sends no envelope detail key; a description over the limit
  is refused 422 and no listing row exists afterwards (rejection-path raw call).
  Application integration, `tests/integration/test_listing_details.py` (4 cases):
  the real app and lifespan on `test_alkahest_release_conditions`' harness (its
  `storefront` fixture and `_started`), registry discovery enabled with two
  pinned registries replaced where `MultiRegistryClient` wraps them, at
  `_make_registry_client`: both its bindings, the publication service's and the
  one `server.py` imports for startup's dispute-authority read, so no call
  leaves the process. A seller's typed-client publish stating all three answers
  `published` after startup read the double's recommendations once,
  `get_listing` reads the three back, and
  both registries are sent them beside the envelope with the description,
  unchanged, in `listing_resource`; a publish stating none sends neither registry
  a detail key, and the resource's description is null; a description far past
  the limit is refused 422, `list_listings` then reads no listing, and neither
  registry was sent anything. Correction: the refusal is no raw HTTP call. It is
  still a rejection-path test, commented so and asserting only the status: the
  typed client validates its request model and so refuses to build the body, so
  the test builds it with `PublishFromQuotaRequest.model_construct`, which the
  client sends unvalidated through its own route, signing and operation.
  Outside the plan: the credits lane's `[seed]` passes its configured
  description to `ListingService.publish_from_quota` without the request model,
  so a seed description past the limit would have written a listing row every
  registry refuses. The service now validates the three details through
  `ListingDetails` before it reads the resource or writes anything. Application
  integration, the same module's
  `test_a_seed_description_past_the_envelope_limit_gives_the_seed_up_with_no_listing`:
  the started app seeded as `test_alkahest_release_conditions`' seed cases seed
  it, with a description far past the limit, its quota registration replaced on
  the composed seed; the administrator's first `listing-seed` cycle fails, the
  next reports the seed `given_up` for a `ValidationError`, `list_listings`
  reads no listing, and neither registry was sent anything. Only 6.1's unit test holds the limit's edges, as the plan
  asks; every other new case states a description far past it, so a limit
  changed in `market_core` changes only that test here (`test-levels.md`,
  "Coverage between the levels").
  `run test-before` cannot collect either new test file at `HEAD`: its
  `--no-project` environment has no `injected_time`, which the package's
  `conftest.py` imports.
- [x] 6.3 Verification point: API-credit storefront unit and integration suites
  pass, 6.2 being the application-integration case; `scripts/change-workflow run
  pre-commit seller-listing-metadata` and `make check-packaging` pass.
  `scripts/change-workflow run pre-commit seller-listing-metadata --base
  origin/dev` passes every hook: its `make lock` rewrote no lock, its `make
  validate-local` passed `make check-packaging` and the whole `make test`, and
  the `pre-commit` checks passed. In that `make test` the API-credit storefront
  ran 292 passed, unit and integration: 285 before this section and its 7 new
  cases.
  End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` discover the
  listing the API-credit lane's storefront seeds (`storefront.credits.lane.toml`, `[seed]`, as
  `storefront.credits.toml` does for the full local stack), and the seed states
  `description = "Prepaid weather-API credits"`. They therefore publish that
  description beside the envelope and inside `listing_resource` through a real
  API-credit registry, which is evidence that a real registry admits a stated
  description on the seed's path. They state no title or metadata, and the seed
  calls the listing service directly, so the seller's route and request model
  are proven by 6.1 and 6.2 alone. No scenario is owed.

Handoff from section 6:

- With registry discovery enabled, the API-credit storefront's startup reads
  every registry's descriptor through `_make_registry_client`, which `server.py`
  imports by name from `publication_service`. A test that doubles the registries
  replaces both bindings, or startup reaches the configured URLs for real and
  logs the failure while the test still passes: each case took about 5 seconds
  until it did. `ApiCreditCompositionSeams` offers no registry seam; adding one
  means threading a factory through the publication service's module-level
  runtime construction, which this section declined as outside its scope. The
  fresh-context check raised it as patching around a seam.
- `run test-before` cannot collect any API-credit storefront test: its
  `--no-project` environment lacks `injected_time`, which the package's
  `conftest.py` imports. No new test here was shown failing at the round's base.
- A request the typed `ApiCreditListingClient` refuses can still be sent for a
  rejection-path test as `PublishFromQuotaRequest.model_construct(...)`: the
  client's `model_validate` returns an existing instance unvalidated.
- Both API-credit storefront configurations' `[seed]` state a `description`, the
  one detail any committed end-to-end scenario publishes.

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
  names, its result, and the coverage as it is: `e2e_credits_deal` and
  `e2e_credits_payment_deal` publish the API-credit seed's `description` beside the
  envelope and inside `listing_resource` through a real registry; `e2e_deal` and
  `e2e_bare_metal_publication` state no details and cover the unchanged path only;
  `title`, `metadata`, an override's `details`, and the seller's create route are
  proven at the integration and application-integration levels by the tests of
  sections 3–6. Or an
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
- `scripts/change-workflow run pre-commit seller-listing-metadata --base origin/dev` fails one check on the branch as implemented: `make check-local-imports` reports the function-level imports at lines 92, 109 and 115 of the round-trip script under `docs/attachments/`. The replanned work moves them or gives each its reason. Correction: 3.3 deleted the script instead, and the check passes.

- Registry: 139 unit + 128 integration (full integration directory) passed. Storefront: 182 unit passed. VM storefront: 1215 unit + 530 integration passed, 1 pre-existing skip. Bare metal: 224 domain + 590 storefront passed. API credits: 255 passed. VM buyer: 215 passed. Clients: 25 + 68 passed. Registry-client mypy clean; the VM storefront's mypy reports pre-existing errors (145 on its base) and none in the touched files.
- Signed publish → GET round trip with VM/bare-metal/API-credits resources carrying the fields: a round-trip script and its output under `docs/attachments/`, run from `core/registry`; 3.3 deleted both, and 3.2's `core/registry/tests/integration/test_listing_details.py` supersedes them. Covers refusal naming the field, the dry-run route, `$.metadata["acme.tier"]` filtering both by value and on missing, and unchanged reads for listings without the fields.
- Migration 019 exercised by downgrade to 018 and re-upgrade on a stamped database; fresh databases create the columns through `create_all` and stamp head.
- Tests that reach httpx fail on a machine with `ALL_PROXY` set to a SOCKS URL (`socksio` not installed); run suites with the proxy variables unset. Unrelated to this change.
- Environments install internal packages as wheels from `.dist/`, so after editing a package run `make dist` and `make reinit` in every project that installs it before trusting a test run; a stale wheel fails as an extra-forbidden field.
