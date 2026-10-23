# Implementation Tasks

Sections are ordered by the dependencies `design.md` D13 fixes: the pins and
baselines first, then each layer before the layer composing it. Every section
deletes the API-credits implementation it replaces in the same section, leaves
API credits green on its suites and its recorded baselines, and keeps
`make check-packaging` green. Decisions are cited as `D<n>` from `design.md`;
requirements as the delta that states them (`api-family`, `api-credits`,
`market-composition`).

Every section that adds or moves a project: declare every imported distribution
in its `pyproject.toml` with `packages = ["src/<package>"]`; lock it once with
`uv lock --find-links ../../.dist` (or the matching depth), then relock with
`python3 scripts/uv_project.py lock <project>` and `reinit`; add its
`dist-<name>` and `test-<name>` targets to `domains/Makefile` and the root
`Makefile`'s aggregate `dist` and `test`, and a row to `.github/workflows/tests.yml`'s
matrix; add its row to `docs/development/RELEASING.md`'s published-packages table
and the matching filter and `PACKAGES` entries in
`.github/workflows/publish-pypi.yml`. `make check-packaging` holds all of it. A
moved module counts toward a section's reviewable size; lock files do not.

The change's pull request is in the main repository, so continuous integration
runs on every push; two jobs, the bare-metal and VM storefront suites, fail on
the `dev` base itself and are inherited, not this change's. Each section records
its suites' results locally as well; the end-to-end lanes are reported by
validation and the pipeline, not run on the implementing machine.

**Dependencies.** None. The change stands on `dev`; the inference domain binds
the vocabulary and composes the kit in its own campaign's changes.

## 1. Pins and compatibility baselines

Delivers the record every later section is proven against: the digest pins
(D8, `api-family` "Issuance digests are label-parameterized and byte-identical")
and the compatibility baselines (D9, D14, `api-credits` "A baseline is
diffed"). Tests and fixtures only; no production code changes. Touches
`domains/apicredits/tests/`, `domains/apicredits/service/tests/`,
`domains/apicredits/storefront/tests/`, and `e2e-tests/`.

- [x] 1.1 Confirm by inspection, before writing anything, that `design.md`'s
      "What exists" still holds on the base branch: the digest strings are
      literal in both `arkhai_apicredits/settlement/credits_client.py` and
      `apicredits_service/models/keys_model.py`; `db/database.py` seeds
      provider and modes `api_credits`; `keys_service.py` refuses other
      offering modes; the issuance-evidence router is unmounted. Record drift in
      `design.md` rather than working around it.
      *Done 2026-10-22.* All four hold on `dev` at `9720ac596`: the four
      schema strings and the `api-credits` digest domain are literal in both
      `credits_client.py` and `keys_model.py`; `db/database.py` seeds the
      default pool's provider, deliverable, and advertisable modes as
      `api_credits`; `keys_service.py`'s `_commit_quota` refuses a reservation
      whose offering mode is not `api_credits`; `make_issuance_evidence_router`
      is defined and referenced nowhere, and `server.py` mounts nine routers
      without it. No drift; `design.md` unchanged.
- [x] 1.2 `domains/apicredits/tests/test_issuance_pins.py` with fixtures under
      `domains/apicredits/tests/fixtures/pins/`: for a fixed input set of
      issuance requests (new key, existing key, several quantities and owners),
      record the request digest, the fulfillment identity, the evidence digest,
      the signed evidence bytes, and the portable fulfillment reference the
      domain produces today, and assert them byte for byte. The fixture is
      written once by a generator flagged `--write` and never rewritten by a
      passing run. (D8.)
      *Done.* Five cases (new and existing keys, quantities 1–250, two eip191
      and two ed25519 owners, two services); the fixture records the inputs
      beside the expected values so a changed input set is seen too. Written
      by `python tests/test_issuance_pins.py --write`, which refuses to
      overwrite. A fourth test proves the storefront's evidence path
      (`prepare_credit_issuance_request`) yields the pinned identity and
      digest. Unit, 4 passed. The storefront suite adds
      `tests/unit/test_issuance_pins.py`, which builds each case's evidence
      through the production `settlement_evidence` from an accepted
      Agreement and asserts the same identity and digest (unit, 5 passed),
      after the owner's review asked that the producer itself be covered.
- [x] 1.3 `domains/apicredits/service/tests/integration/test_compat_baseline.py`
      with fixtures under `service/tests/fixtures/baseline/`: the route surface
      (every route's method and path, and the served OpenAPI document with
      volatile fields normalized); each route's admitted roles and signed
      operation name; the status code and error body of each refusal the
      contracts name (unauthenticated, forbidden, insufficient credits,
      conflict); the `/api/v1/system/version` response; the environment
      variables and settings keys the service reads, by prefix. Application
      integration through the service's test client. (D9.)
      *Done.* Six records: `routes` (method, path, name), `openapi` (served,
      no volatile field today), `route_contracts` (both tables field for
      field, plus the unsigned paths), `refusals` (nineteen: unauthenticated,
      unknown route, role, trust, changed reuse, exact-retry refusal, and every
      issuance, key, and consumption refusal the controllers map to a status,
      with a 422's pydantic echo dropped; issuance to a revoked existing key
      is not among them), `version` (shape and distribution name; the number is asserted
      against the installed distribution, not recorded), and `configuration`
      (settings.toml keys plus each `settings.get`/attribute read in the
      source, and the environment variables that select them). The app is
      loaded fresh by `tests/integration/signed_service.py` with seller and
      service trust and no admin, as the deployed stack is configured; the
      fixtures are written by `python -m tests.integration.test_compat_baseline
      --write`. Application integration through the real app over
      `ASGITransport`, state set up through `CreditsServiceClient`,
      `SiteCapacityAdminClient`, and the gated `TokensClient`, refusals
      hand-signed as rejection paths, with the first half of each reused
      request identity also hand-signed since no client can fix one.
      `tests/__init__.py` was added so test modules import the helper. The
      bodies the refusal record diffs are what D9 asks for; `TESTING.md`'s
      rejection-path rule asserts status only, and closeout records the
      baseline as that rule's one exception (promotion record).
- [x] 1.4 `domains/apicredits/service/tests/unit/test_schema_baseline.py`: the
      tables, columns, and indexes a freshly migrated database holds, and the
      recorded migration identifiers in order, against a fixture. (D9.)
      *Done.* Nine tables (the credits tables, the site ledger's, the pool
      table, `schema_migrations`) with columns, indexes, and foreign keys as
      SQLite reports them, each table's and index's DDL and triggers, and the
      five migration identifiers in applied order. Placed at `tests/integration/test_schema_baseline.py`, not the
      `unit/` path this task names: it runs the migrations against a real
      SQLite database, which `TESTING.md` places in `integration/`. Library
      integration, 1 passed.
- [x] 1.5 `domains/apicredits/storefront/tests/integration/test_compat_baseline.py`
      and `tests/unit/test_schema_baseline.py`: the same five baselines for the
      storefront, including its `api_credit_*` tables and migration identifiers.
      (D9.)
      *Done.* Six records for the storefront plus `schema`: `routes`,
      `openapi`, `authentication` (every mounted route's bound operation,
      bound resource, and admitted role), `refusals` (unauthenticated, untrusted,
      wrong role, invalid signature, exact retry, changed reuse, unknown
      lifecycle loop), `health` (the storefront has no version route), and
      `configuration` under the `APICREDITS_STOREFRONT` prefix. The bound
      operation and resource are observed, not transcribed: every
      authenticated route binds them before trust is decided, so an unsigned
      probe reads them from the request state through an outermost test
      middleware; the one route that resolves state first, the settlement
      status read, is recorded from the canonical client's contract. The
      admitted role is observed too: each bound route is then called signed
      as admin, seller, and buyer over the observed operation and resource,
      and the one role not refused is recorded and asserted equal to the role
      the test states for the route; the status read is the one route whose
      role is stated only. The app is the storefront's own factory over a
      fresh SQLite file, with the container holding what the probed routes
      resolve before they authenticate: the database, the signer, a
      negotiation service, the system service, a loop controller with every
      step registered and no loop started, and a placeholder negotiation
      runtime no probe reaches; application integration, with the refusals
      hand-signed as rejection paths. The schema record, at
      `tests/integration/test_schema_baseline.py` for the reason 1.4 gives,
      holds twenty-seven tables with their DDL, indexes (partial predicates
      included), and nineteen triggers, and nineteen migration identifiers
      across the core, settlement-runtime, and `api_credit_*` chains. The two schema
      modules share a forty-line SQLite introspection helper by duplication,
      since the two packages share no test code.
- [x] 1.6 `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_service_upgrade_rollback.py`,
      marker `e2e_credits_service_rollback` registered in
      `e2e-tests/pyproject.toml`: with the lane's database volume retained,
      start the current API-credits service image over a copy of a database the
      pre-kit image wrote, then the pre-kit image over a database the current
      image wrote, and in each direction serve the route surface and read every
      grant. The pre-kit image is tagged `arkhai:apicredits-service-prekit` by a
      new `build-apicredits-service-prekit` target that builds
      `domains/apicredits/service` from the pinned commit
      `9720ac59697a132f48913b91448c8224ece35cde`, the `dev` base this change
      stands on, in a temporary worktree; `build-e2e-apicredits` depends on it,
      so the lane's image build fails, rather than the scenario skipping, when
      the pre-kit image cannot be built. `e2e_credits_service_rollback` joins
      `E2E_APICREDITS_MODULE` in `e2e-tests/Makefile` so the lane runs it, and
      the scenario fails, never skips, when the tag is absent. The pipeline's
      checkout fetches only the head commit, so the target fetches the pinned
      commit itself (`git fetch --depth 1 origin <sha>`) before building, and
      `.github/workflows/e2e.yml` needs no change. Not run locally;
      validation's lane and the pipeline run it. (D14, `api-credits` "Upgrade
      and rollback against a retained database".)
      *Done, not run locally.* The scenario drives the lane host's Docker
      engine through the `docker` SDK (added to `e2e-tests`, relocked) over
      the socket `test-e2e-apicredits` now mounts into the test container
      (`BUYER_MACHINE_DOCKER_SOCKET`, empty for the other lanes). Rollback:
      the lane's service volume is mounted read-only into a copying
      container, which copies the database through SQLite's backup API so a
      live writer cannot leave the copy inconsistent, and never into a probe,
      and the current image then the previous release's start over the copy; upgrade: the previous release
      starts over a fresh volume, registers a quota, issues a new-key
      grant and a top-up, then the current image starts over it, reads both
      back, and an exact retry of the first issuance converges on the
      recorded grant. Both directions compare each probe's `/openapi.json`
      path and method set with the lane's live service's and read every key
      and grant, and the issuance of every grant carrying a fulfillment
      identity (every issued grant does), through `CreditsServiceClient`. Probe services run
      behind the shared-secret gate (`APICREDITS_STOREFRONT_ADMIN_KEY`, the
      committed development value), since no credential file can be mounted
      from inside the test container; the quota is declared through the
      capacity route with the gate's header, a raw call the scenario marks,
      since the typed capacity client only signs. Images, volume, network,
      and engine are each required and fail the scenario by name. At this
      commit both images are built from trees that differ only in tests and
      documents, so a pass proves the harness; the compatibility evidence
      accrues from section 3 on, when the images first differ in code. The
      lane's volume is copied while its service runs, through the backup
      API. Lane settings
      (`api_credits.service_image`, `service_prekit_image`, `lane_network`,
      `service_volume`, `admin_key`) are in `config-docker.yml`.
      `build-apicredits-service-prekit` checks the pinned commit out under
      `.worktrees/` (gitignored and dockerignored), fetching it at depth one
      when absent, builds that commit's whole wheelhouse with its own `make
      dist`, builds the service image from that worktree as
      `arkhai:apicredits-service-prekit`, and removes the worktree whether or
      not the build succeeded; `build-e2e-apicredits` depends on it.
      `e2e-tests` declares `arkhai-apicredits-domain`, which the scenario
      imports directly. Declined from the fresh-context check: a mounted
      signing identity for the probes, which would need the development seed
      written into a volume from inside the test container (the lane's own
      service exercises the signed posture); and declaring `starlette`, which
      both baselines import under `fastapi` as the service's existing
      route-coverage test does. The
      marker joins `E2E_APICREDITS_MODULE` last, after the deal scenarios
      whose grants the rollback direction reads.
- [x] 1.7 Verification: `make -C domains/apicredits test-domain` (unit),
      `make -C domains/apicredits/service test` (unit and application
      integration), `make -C domains/apicredits/storefront test` (unit and
      application integration), `make test`. End-to-end: `e2e_credits_deal` and
      `e2e_credits_payment_deal` are unaffected; `e2e_credits_service_rollback`
      is new and owed to validation. Record each suite's level and result here.
      *Done 2026-10-22.* Domain library 45 passed (41 before; unit, the pins
      a fourth of which is library integration through the evidence path).
      Service 79 passed (72 before; unit, library integration, application
      integration). Storefront 196 passed (184 before; unit, application
      integration). `make test`: every other suite passed except, all on the
      `dev` base and outside this section's files, one provisioning-service
      unit test (`test_config.py`, the dotenv layering characterization,
      untouched since #263), the VM storefront's two Alkahest toolchain tests
      the plan already lists, three release-tooling `test_publish_matrix`
      cases over `RELEASING.md` rows for packages this section does not
      touch, two release-tooling whole-tree checks and
      `make check-comment-hygiene` that trip on another session's stale
      worktree under `.claude/worktrees/` (both pass on a copy of this tree
      without it), and one release-tooling case needing GNU make 4's
      `--eval`, which the macOS make 3.81 here lacks. Helm is not installed
      here, so `test-deployment-packaging`'s render checks are unrun.
      `make check-packaging` passes on the copy (uv setup, locks, Python
      version, layout, all four architecture parts); `make check-change`
      reports only the two `api-family` citations closeout creates. The e2e
      unit suite passes (80) and the new scenario collects (2). Reinit under
      the local uv 0.10.9 rewrites several locks' markers; those rewrites are
      reverted, and only `e2e-tests/uv.lock` changes. End-to-end: the three
      scenarios are owed to validation; a pass of the rollback scenario at
      this commit proves the harness (1.6).
      **Handoff.** The service's `tests/__init__.py` makes `tests` a package;
      the baseline generators run as `python -m tests.<dir>.<module> --write`
      from each project and refuse to overwrite. Later sections diff against
      the fixtures as committed; a section that changes a recorded value has
      changed behaviour. The stale worktree under `.claude/worktrees/` belongs
      to another session and was left alone. Section 1 is committed on
      `feat/compose-api-family-kit-s1-baselines`, stacked on the planning
      branch; the owner asked for one PR per section, each stacked on the
      last.

## 2. Vocabulary and contracts

Delivers `domains/api` (`arkhai_api`) and `domains/api/contracts`
(`arkhai_api_contracts`), the family rows in `ARCHITECTURE.toml`, and both
domains binding the purchase shape (D1, D2, D3, D4; `api-family` "The api
family shares one vocabulary and one kit", "Route declarations are plain data
adapted by the authority"; `market-composition` "The api family shares one
access vocabulary and kit"). Touches the two new projects,
`docs/development/ARCHITECTURE.toml`, `domains/apicredits/src/arkhai_apicredits/negotiation/terms.py`,
the domain library's `pyproject.toml`, the Make, CI, and publish wiring named
above.

- [x] 2.1 `domains/api/pyproject.toml` (`arkhai-api` 0.1.0, dependencies
      `pydantic` and `arkhai-kit-identity`, `[tool.arkhai.architecture]
      allowed-dependencies` naming exactly those), `Makefile` on the kit
      template, `src/arkhai_api/`, `tests/`. (D3.)
      *Done 2026-10-22.* As named; `requires-python` is the domain library's
      (`>=3.12,<3.14`). `__init__.py` is a docstring: the modules are the API,
      so binding the purchase shape does not import the issuance models.
- [x] 2.2 `src/arkhai_api/purchase.py`: the key disposition and purchase payload
      models and a `provision_terms_model(kind)` factory returning the
      `ProvisionTerms` class bound to a kind literal, byte-identical in payload
      validation to `ApiCreditsProvisionTerms` today; `src/arkhai_api/labels.py`:
      the `IssuanceLabel` type and its validation, naming no value. (D3.)
      *Done.* `purchase.py`: `KeyIntent` and `PurchasePayload` (today's
      `ApiCreditsKeyIntent` and `ApiCreditsProvisionPayload`), the
      `ProvisionTerms` base whose `payload` validates through `PurchasePayload`
      and dumps `exclude_none`, `ProvisionTerms.purchase(...)` (today's
      `make_api_credits_provision_terms`), the four payload accessors, and
      `provision_terms_model(kind)`, a cached `create_model` subclass binding
      `kind` to the literal, so equal kinds yield one class; the bound class is
      named `ProvisionTerms`, so pydantic error headers no longer read
      `ApiCreditsProvisionTerms` (`ApiCreditsMessage`, which subclasses it,
      keeps its name). `labels.py`:
      `IssuanceLabel`, a frozen dataclass of the label `name` (lowercase words
      joined by hyphens) and a `fulfillment_id_prefix` derived as
      `<name>-fulfillment.v1` unless given, with properties spelling the
      request, result, evidence, capability, and portable-reference schema
      strings. The prefix is a second field because the recorded API-credits
      identity prefix is `api-credit-fulfillment.v1`, singular, which no rule
      derives from `api-credits`; the API-credits binding passes both.
- [x] 2.3 `src/arkhai_api/issuance.py`: `IssuanceRequest` and `IssuanceResult`
      models, `fulfillment_id(label, negotiation_id)`, and
      `issuance_request_digest(label, request)`, moved from
      `credits_client.py` with the schema strings and digest domain taken from
      the label parameter so that `api-credits` reproduces today's bytes.
      `src/arkhai_api/evidence.py`: the issuance evidence body, sign, verify,
      digest, encode, decode, and the portable fulfillment reference, moved from
      `issuance_evidence.py` the same way. (D3, D8.)
      *Done.* `issuance.py`: `KeyDisposition` (the wire name the service's
      OpenAPI document records; the purchase-side intent is `KeyIntent`), the
      label-agnostic `IssuanceRequest` and `IssuanceResult` bases with `schema`
      a pattern-constrained string, `fulfillment_id`, `issuance_request_digest`,
      `issuance_request(label, ...)` building a request with its identity and
      digest, and `issuance_request_model(label)` and
      `issuance_result_model(label)`: cached `create_model` subclasses binding
      `schema` to the label's literal with that default and validating identity
      and digest under the label, so a bound model refuses another label's
      request and the service's OpenAPI keeps `const` and `default` on
      `schema`. `create_model` rather than a class statement because a class
      defined inside the factory cannot name the base it shadows.
      `IssuanceRequest` keeps the service's field order (`fulfillment_id`
      before `negotiation_id`) and docstring ("Complete immutable command for
      one credits grant."), since both enter the served document's `required`
      list and `description`; the storefront client's order differed only in
      that pair, which no digest or signature reads. `evidence.py`:
      `IssuanceEvidenceBodyV1` requires `domain` and spells `protocol` and
      `capability` from it, refusing a body whose explicit spelling disagrees;
      `SignedIssuanceEvidenceV1`, `ExpectedIssuanceEvidenceV1`,
      `PortableFulfillmentRefV1`; and the sign, digest, decode, verify, and
      portable-reference functions, each taking the label and refusing a body
      or reference under another. Nothing is deleted from
      `arkhai_apicredits/settlement/` here: section 3 deletes
      `credits_client.py` and section 5 touches `issuance_evidence.py`, as the
      plan's touch lists say, so the domain's copies stand until their callers
      are rewired.
- [x] 2.4 Vocabulary tests, unit: the purchase shape under two kinds; every
      pin fixture of 1.2 replayed through the vocabulary under `api-credits`
      and matching byte for byte; the same inputs under `inference` differing;
      a distribution test on the `conftest_wheels.py` pattern that the wheel
      installs and imports with no core, storefront, or runtime package present.
      *Done.* `test_purchase.py` (two kinds through one payload validation,
      refusals, the purchase builder, the accessors), `test_labels.py`
      (spelling, validation, one class per label, no domain name under
      `src/`), `test_issuance_pins.py` (the five pin cases read from
      `domains/apicredits/tests/fixtures/pins/issuance_pins.json`: every
      recorded value byte-identical under `api-credits`, every value different
      under `inference`, each label's bound request and result models
      refusing the other's, a recorded evidence decoding under `api-credits`
      only), `test_evidence.py` (round trip, label refusals, canonical and size
      bounds, tamper, trust, expiry, skew, the portable reference).
      `test_distribution.py` builds the vocabulary and identity wheels, asserts
      the wheel requires `arkhai-kit-identity` and `pydantic` alone, installs
      it into a fresh environment, and imports every module with no core,
      storefront, settlement-runtime, negotiation-runtime, site, or API-credits
      package findable. 53 passed: `tests/unit/` unit, `tests/integration/`
      (the distribution test, which builds, installs, and imports in a
      subprocess) library integration.
- [x] 2.5 `domains/api/contracts/` (`arkhai-api-contracts` 0.1.0; dependencies
      `pydantic`, `arkhai-core`, `arkhai-kit-identity`, `arkhai-api`):
      `src/arkhai_api_contracts/models.py`, the authority's wire models moved
      from `keys_model.py` without its digest helpers;
      `src/arkhai_api_contracts/routes.py`, every authority route as plain data
      — method, path pattern, signed operation, roles, path resource — on the
      `kit/resource-pools-contracts` form, with a `route(operation)` lookup;
      `operations.py`, the operation-name constants. Unit tests: every route
      the service mounts today appears exactly once; the declarations match
      `route_contracts.py`'s table field for field. (D4.)
      *Done.* `models.py` holds the wire models as `keys_model.py` defines
      them, re-exporting the vocabulary's `KeyDisposition`, `IssuanceRequest`,
      and `issuance_request_model` and adding `IssuanceResponse` with
      `issuance_response_model(label)` on the same pattern; `routes.py`
      declares the eleven signed routes as plain data (`method`, `path`,
      `operation`, `roles`, and `path_resource`, `body_resource`,
      `optional_body_resource`, `exact_retry_safe` where they differ from the
      site kit's defaults) with `route(operation)`; `operations.py` the eleven
      names, which keep their `credits_` spelling because the signed operation
      is wire. Dependencies are `arkhai-api`, `arkhai-kit-identity`, and
      `pydantic`, which are also its allowlist; `arkhai-core`, which this task
      lists, is neither imported nor needed, so it is not declared. Unit:
      `test_routes.py` compares the declarations to the recorded credits
      table in the service baseline's `route_contracts.json` field for field
      (the recording the service's own baseline test holds equal to
      `route_contracts.py`), resolves every mounted `/api/v1/issuance` and
      `/api/v1/keys` route recorded in `routes.json` to exactly one
      declaration and no unsigned path to any, and checks each operation is
      declared once; `test_models.py` compares each wire model's
      JSON schema, under the `api-credits` label and with null defaults
      dropped as FastAPI drops them, to the baseline `openapi.json` component
      of the same name, and checks the bound response carries the secret and
      refuses another label. 16 passed.
- [x] 2.6 `docs/development/ARCHITECTURE.toml`: the `[[families]]` row for
      `api` (`directory = "domains/api"`, `vocabulary = "arkhai-api"`) and
      `family = "api"` on the `apicredits` row; the comment saying API credits
      has no family is removed. `make check-architecture` classifies both new
      projects from their paths with no override row. (D1, D14.)
      *Done.* As named, and the domain library's override row gains `api` in
      its scope: an override replaces the path reading entirely, so without it
      the library's dependency on the vocabulary fails the scope rule. All
      four architecture parts pass with both new projects classified from
      their paths, run on a copy of the tree without the other session's stale
      `.claude/worktrees/` checkout that fails `check-architecture` in place
      (1.7).
- [x] 2.7 API credits binds the purchase shape: `arkhai_apicredits/negotiation/terms.py`
      becomes a binding of `provision_terms_model` under `api_credits.v1`, the
      domain library's `pyproject.toml` declaring `arkhai-api`; its existing
      terms tests pass unchanged. A vocabulary test binds a second kind literal
      and proves the payload validation identical. (D3, `api-family` "Two kind
      literals bind the purchase shape".)
      *Done.* `terms.py` is the binding: `ApiCreditsProvisionTerms =
      provision_terms_model(API_CREDITS_PROVISION_KIND)`,
      `make_api_credits_provision_terms = ApiCreditsProvisionTerms.purchase`,
      the accessors re-exported. Three names the module published are gone,
      `API_CREDITS_PROVISION_VERSION`, `ApiCreditsKeyIntent`, and
      `ApiCreditsProvisionPayload`, none with a consumer in the repository,
      and `ApiCreditsProvisionTerms` now names a generated class called
      `ProvisionTerms`, which changes pydantic error headers only; the
      domain library's import surface is not a compatibility boundary (D14),
      so no alias is kept. The domain library declares `arkhai-api>=0.1.0`
      and bumps to 0.7.0, the minor bump the versioning policy gives a
      pre-1.0 incompatible change. The terms
      consumers' tests are the storefront's and buyer's, which pass unchanged:
      storefront 196, buyer 27, service 79 (unit and application integration),
      1.3–1.5's baselines among them; domain library 45 (unit; the install
      tests library integration), the pins among them. The two-kind test is
      2.4's: one accepted payload and five refusals under both kinds, and the
      consumers' suites are the evidence the API-credits binding is
      unchanged.
- [x] 2.8 Wiring: `dist-api`, `dist-api-contracts`, `test-api` in
      `domains/Makefile` and the root `Makefile`; rows in `tests.yml`;
      published-package rows and `publish-pypi.yml` entries; locks.
      *Done.* Both Makefiles gain the three targets, in `dist`, `dist-ci`, and
      `test`, with `dist-apicredits-domain` depending on `dist-api`;
      `tests.yml` two matrix rows (the root `dist` and `dist-ci` reach the two
      wheels through `dist-domains`, as every domain wheel, and the root
      `dist-api-contracts` and `dist-apicredits-domain` declare only their
      cross-directory prerequisites, since `domains/Makefile` already orders
      the vocabulary before them: a dry run builds `arkhai-api` once per
      target); `publish-pypi.yml` the push path, two
      filters, and two `PACKAGES` entries; `manifests/published-distributions.json`
      both, after the identity kit; `RELEASING.md` two rows and `arkhai-api`
      on the domain library's. Locks: the two new projects, and the domain,
      storefront, buyer, service, and `e2e-tests` locks, which record the
      domain wheel, relocked through `scripts/uv_project.py lock` under uv
      0.11.17, the release `tests.yml` pins, run through `uvx`. The storefront
      lock's diff is large because its committed lock predates uv intersecting
      each dependency's marker with the project's `[tool.uv] environments`;
      0.10.9 and 0.11.17 rewrite it identically, and beyond the markers its
      hunks are the `arkhai-api` entry and the domain's version.
      `domains/apicredits/tests/conftest_wheels.py` builds the vocabulary
      wheel so the domain's install tests resolve it, and
      `test_distribution.py` expects the domain wheel to require it.
- [x] 2.9 Verification: `make test-api` (unit), `make -C domains/apicredits
      test-domain` (unit), `make test`, `make check-packaging`. End-to-end: `e2e_credits_deal` exercises the
      bound purchase shape once deployed.
      *Done 2026-10-22.* `make test-api`: vocabulary 53, contracts 16 (unit;
      the distribution test library integration against a fresh environment).
      `make -C domains/apicredits test-domain` 45 (unit and library
      integration). `make test`: every suite passed except, all inherited
      from the `dev` base and recorded by 1.7, the provisioning service's
      dotenv-layering unit test, the VM storefront's two Alkahest toolchain
      tests, the release-tooling whole-tree checks and four
      `test_publish_matrix` release-table cases that read the other session's
      stale `.claude/worktrees/` checkout as part of the tree (the
      `apicredits-domain` case now among them, since that checkout's domain
      declares no `arkhai-api`; all pass on a copy without it), the
      `--eval` case the macOS make 3.81 lacks, and one docker-credential-helper
      timing case; Helm is not installed, so the render checks are unrun.
      `make check-packaging` passes on the copy: uv setup, locks (the seven
      relocked), Python version, layout, all four architecture parts.
      `make check-change` on the copy reports only the two `api-family`
      citations closeout creates; its agent-skills part fails there only
      because the copy omits `.claude/`, and passes in place. End-to-end: owed
      to validation; `e2e_credits_deal` negotiates through the bound purchase
      shape and `e2e_credits_service_rollback` first compares images that
      differ in code (the domain wheel) at this commit.
      **Handoff.** The API-credits label is
      `IssuanceLabel("api-credits", "api-credit-fulfillment.v1")`, so far
      only in tests: section 3 binds it in the storefront client and the
      service, and section 4's capacity profile carries it. The service's
      wire `IssuanceRequest` and `IssuanceResponse` must be the bound classes
      `issuance_request_model(label)` and `issuance_response_model(label)`,
      built where the service root knows its label, for the OpenAPI
      baseline's `const` and `default` on `schema` to hold; their docstrings
      and field order are OpenAPI surface too. The signed-header constants
      the client needs are left to 3.1, as planned. `credits_client.py` and
      `issuance_evidence.py` still hold the domain's copies of the moved
      code until sections 3 and 5 rewire their callers. Relock under uv
      0.11.17 with `uvx uv@0.11.17` behind a `uv` shim on `PATH`, and run
      the whole-tree checks on a copy excluding `.claude/`, until the stale
      worktree is removed by the session that owns it. The fresh-context
      check accepted: shorter module docstrings, the redundant Makefile
      comment, the two wheels built twice by the root `dist`, the unit and
      integration split of the new suites, a development-value comment on a
      test address, and the promotion rows for the two `ARCHITECTURE.md`
      sentences the family row falsifies. Declined: a comment stating the
      route declarations' order matters, since every pair is disjoint under
      full-path match and method and the route test proves one match per
      mounted route; and moving the pins and baselines into a shipped fixture
      package, since they are section 1's recordings, owned by the domain's
      tests by design and read by path. Section 2 is committed on
      `feat/compose-api-family-kit-s2-vocabulary`, stacked on section 1's
      branch, the review's fixes as a second commit.

## 3. The typed client and one digest implementation

Delivers `domains/api/client` (`arkhai_api_client`) and removes the service's
duplicate digest (D4, D8; `api-family` "The authority's dependencies are
read", "Issuance digests are label-parameterized and byte-identical"). Touches
the new project, `arkhai_apicredits/settlement/credits_client.py`,
`apicredits_storefront/services/credits_service_client.py` and `keys_lookup.py`,
`apicredits_service/models/keys_model.py` and `services/keys_service.py`.

- [x] 3.1 `domains/api/client/` (`arkhai-api-client` 0.1.0; dependencies
      `arkhai-api-contracts`, `arkhai-core`, `arkhai-kit-identity`, `httpx`):
      `src/arkhai_api_client/client.py`, the sync and async typed client moved
      from `CreditsServiceClient`, each method looking its route up by operation
      name from `contracts` and binding the request from it; the signed-header
      constants come from `contracts`. Unit tests on the client's request
      shaping; the `test_credits_client_http.py` cases move here as library
      integration against a scripted authority. (D4.)
      *Done 2026-10-23.* `arkhai-api-client` 0.1.0: `client.py` holds
      `AuthorityClient` (async) and `SyncAuthorityClient` (sync) with the same
      nine methods — `submit_issuance`, `get_issuance`, `get_key`, `list_keys`,
      `list_key_grants`, `list_key_usage`, `revoke_key`, `adjust_key_balance`,
      `rollback_issuance` — each built as one call bound from
      `arkhai_api_contracts.routes.route(operation)`: the method, the path
      with the declaration's named groups substituted and required to match
      it again, and the signed resource from `path_resource` or the optional
      body `fulfillment_id`. The envelope, header, response verification,
      shared-secret fallback, and rollback logic are the storefront client's,
      moved; the result is validated under `issuance_result_model(label)`, so
      the client takes the label. The two issuance methods drop the `credit_`
      spelling since the class serves any label; the verify route admits the
      seller but spending and checking a key is the gate's, so it has no
      method, as before. `contracts` gains `headers.py` (the seven signed
      header names) and re-exports `IssuanceLabel`, `IssuanceResult`, and
      `issuance_result_model`: the result is the wire shape the authority
      answers with, and contracts already publishes the vocabulary's request
      model and key disposition the same way, so the client, whose kind
      allowlist admits contracts and the identity kit, reads every wire
      model from one package. Declared and
      allowlisted: `arkhai-api-contracts`, `arkhai-kit-identity`, `httpx`;
      `arkhai-core`, which this task lists, is neither imported nor needed and
      is not declared, as 2.5 did for contracts. Tests:
      `tests/unit/test_request_binding.py` (unit, 10) — every seller route has
      a call bound from its declaration with the resource it names, a path
      parameter that does not bind is refused, the signed envelope is rebuilt
      from the headers and verified by the identity kit over the bound
      operation and resource and the canonical bytes sent, the bodyless hash,
      the shared-secret header, refusal mapping, both classes' "together"
      refusal, and the rollback that makes no call;
      `tests/integration/test_scripted_authority.py` (12; integration
      against a well-defined mock of the HTTP boundary, where `TESTING.md`
      places a client's final call — not library integration in its
      database sense, which this task's "library integration" wording
      overstates) — the `test_credits_client_http.py` and
      `test_credits_client.py` cases, for both clients, against a scripted
      authority: an httpx transport that matches each request to the
      contracts' declaration,
      verifies the seller's envelope over the resource that declaration
      binds, answers a script, and signs its answer; issuance under the shared
      secret, a result under another label refused, the refusal reason,
      unknown key and issuance as None, administration paths, queries, and
      bodies, rollback order and the spared existing key, a refused adjustment
      reported, signed calls verified on both sides, a signed 404 read as
      None, an untrusted seller refused by the authority, an unsigned or
      impostor answer refused by the client. 22 passed. The sync/async parity
      contract is the service's test (3.3), where `TESTING.md` places it.
      Wiring: `dist-api-client` and `test-api-client` in both Makefiles,
      `test-api` running the client too, the `tests.yml` row, the
      `publish-pypi.yml` filter and `PACKAGES` entry, the manifest entry after
      contracts, the `RELEASING.md` row; locked with `uv lock --find-links`,
      then `scripts/uv_project.py lock` and `reinit`, under uv 0.11.17;
      `arkhai-api` is in its dev group, since only the tests build requests
      from the vocabulary. D4 once described the client as "over any
      transport exposing `authenticated_request`", the resource-pools
      client's shape; the owner's review of this section amended D4 to the
      shape built and this task's text fixed: sync and async clients that
      own their httpx transport lifecycle, derive method, path, operation,
      and signed resource from the shared declarations, sign and verify
      themselves, and do not depend on the site client's abstraction.

- [x] 3.2 The storefront composes the family client: `credits_service_client.py`
      constructs `arkhai_api_client`'s client once at the composition boundary;
      `keys_lookup.py` and every settlement caller use it;
      `arkhai_apicredits/settlement/credits_client.py` is deleted and the
      domain library's `settlement/__init__.py` re-exports nothing of it.
      (D4, D13.)
      *Done.* `credits_service_client.py` constructs `AuthorityClient` once,
      under `API_CREDITS_LABEL`, which `arkhai_apicredits/label.py` now
      defines as `IssuanceLabel("api-credits", "api-credit-fulfillment.v1")`
      — the one place the domain library spells its label (the service,
      which may not import the domain, spells its own in 3.3; this section's
      touch list names `keys_lookup.py`, which needed no edit). `keys_lookup.py` and
      `fulfillment_service.py` already read the composed client; the payment
      service and the Alkahest stage reach it through the composition, which
      types it `AuthorityClient`. `credits_client.py` is deleted with its two
      test modules, and `settlement/__init__.py` exports nothing of it.
      `fulfillment.py` builds the command through
      `issuance_request(API_CREDITS_LABEL, ...)` and catches `AuthorityError`;
      its `service_url`/`admin_key` fallback, which built a client outside the
      composition, is gone: `credits_client` is required, and every production
      caller already passed it. The domain library declares
      `arkhai-api-client` and bumps to 0.8.0 (the client and its models leave
      its import surface, D14); the storefront declares `arkhai-api-client`,
      raises the domain bound, and bumps to 0.11.0; `e2e-tests` declares
      `arkhai-api` and `arkhai-api-client`, since the rollback scenario now
      drives its probes through `AuthorityClient` and builds its issuances
      from the vocabulary under the domain's label. The domain library's
      new edge to `arkhai-api-client` is interim: the `api-family` delta has
      only `selling` and `buying` depend on the client, and `fulfillment.py`
      holds the issuance call until section 5 moves it into `selling`.
      Tests: the domain's
      `test_issuance_pins.py` builds every pin through the vocabulary under
      the label and matches byte for byte; `test_distribution.py` expects the
      client dependency and no `credits_client.py` in the wheel;
      `conftest_wheels.py` builds the contracts and client wheels so the
      install tests resolve them. Storefront: `test_keys_lookup.py`
      overwrites the composition module's client cache with a client over a
      mock transport instead of patching the class's constructor, and adds a
      test that the composition builds one client from patched
      configuration readers; `test_settlement_fulfillment.py` injects a
      scripted fake client where it patched the class;
      `test_payment_recovery.py` returns the label-bound result; the
      storefront's dev group declares `arkhai-api`, which only these tests
      import. Domain 32
      passed (45 before: the 13 client tests moved to the client project;
      unit, the install tests library integration); storefront 197 passed (196
      before; unit and application integration, 1.5's baselines and the pins
      unchanged); buyer 27 passed (unchanged). Two documentation
      attachments import the deleted client module: `api_credit_smoke.py`,
      which also calls `fulfill_api_credits_obligation` with a signature it
      lost before this change, and `first_use.py`, which imports it from a
      path that predates the package rename; both are documents, left for
      closeout.

- [x] 3.3 The service composes the vocabulary's digest: `keys_model.py` keeps
      only what `contracts` does not define and imports the wire models from
      `arkhai_api_contracts`; `derive_credit_fulfillment_id` and
      `issuance_request_digest` are deleted and `keys_service.py` calls
      `arkhai_api.issuance` under the label the service is configured with
      (`api-credits` here; the capacity profile of section 4 carries it
      later). The service declares `arkhai-api` and `arkhai-api-contracts` and
      never `arkhai-api-client`. (D4, D8.)
      *Done.* `keys_model.py` is the binding: `ISSUANCE_LABEL =
      IssuanceLabel("api-credits", "api-credit-fulfillment.v1")`,
      `IssuanceRequest = issuance_request_model(ISSUANCE_LABEL)`,
      `IssuanceResponse = issuance_response_model(ISSUANCE_LABEL)`, the other
      wire models re-exported from `arkhai_api_contracts.models`.
      `derive_credit_fulfillment_id` and `issuance_request_digest` are
      deleted; `keys_service.py` validates each command through the bound
      model, which recomputes identity and digest under the label, and spells
      the result schema from the label. The service may not import the
      domain, so it spells the label itself until section 4's capacity
      profile carries it. The service declares `arkhai-api` and
      `arkhai-api-contracts` and bumps to 0.7.0; `arkhai-api-client` enters
      its dev group only, in place of the domain library, because its
      integration tests drive the real family client as they drove the
      domain's, and the architecture check reads no dev group. Tests:
      `test_keys_service.py` builds its commands through the vocabulary;
      `test_signed_authority.py`, `test_compat_baseline.py`, and
      `test_credits_signed_roundtrip.py` drive `AuthorityClient` under the
      service's label; `test_credits_route_parity.py` compares the contracts'
      declarations field for field with the service's `CREDITS_ROUTE_CONTRACTS`
      table as imported (a table comparison, in the `integration/` module
      that holds the middleware's table cases too), replacing the three cases
      that read the storefront client's constants;
      `tests/unit/test_client_parity.py` holds the two clients' public
      methods identical. 79 passed (79 before; unit, library integration,
      application integration): 1.3's and 1.4's baselines unchanged — the
      recorded OpenAPI document, which carries `const` and `default` on
      `schema`, and the recorded refusal bodies diff to zero against the
      service composed over the bound models; no new assertion is made.

- [x] 3.4 Verification: `make test-api-client` (unit, library integration),
      `make -C domains/apicredits/service test` and `make -C
      domains/apicredits/storefront test` (application integration; the pins
      of 1.2 and the baselines of 1.3–1.5 unchanged), `make test`, `make
      check-packaging`. End-to-end: `e2e_credits_deal`.
      *Done 2026-10-23.* `make test-api-client` 22 passed (`tests/unit/`
      unit, `tests/integration/` library integration against the scripted
      authority). `make -C domains/apicredits/service test` 79 passed and
      `make -C domains/apicredits/storefront test` 197 passed (unit,
      library integration, and application integration through the real
      apps over `ASGITransport`; 1.2's pins and 1.3–1.5's baselines
      unchanged, the schema and refusal records included); the domain
      library 32 and the buyer 27 besides. `make test`: every suite passed
      except, all outside this section's files and recorded by 1.7 and 2.9,
      the provisioning service's dotenv-layering unit test, the VM
      storefront's two Alkahest toolchain tests (no `node`), the
      release-tooling whole-tree checks and `test_publish_matrix` release-
      table cases that read the other session's stale `.claude/worktrees/`
      checkout (its pyprojects declare the old dependency sets; the three
      API-credits rows are among them, and all pass on a copy without it),
      the `--eval` case the macOS make 3.81 lacks, and one docker-image
      contract case; three provisioning IaC relay-teardown shell tests fail
      on this macOS shell and touch nothing this section changed. Helm is
      not installed, so the render checks are unrun; the three middleware
      toolchains passed. `make check-packaging` passes on the copy: uv setup,
      locks (the client's new lock and the domain, service, storefront,
      buyer, and `e2e-tests` locks relocked under uv 0.11.17; the service's
      lock shrinks by the domain library's dependency closure, which left
      its dev group), Python version, layout, and all four architecture
      parts, which also pass in place for layers, scope, and kinds; each api
      wheel builds once per aggregate target. `make check-change` reports
      only the two `api-family` citations closeout creates; its comment
      hygiene passes on the copy and fails in place only on the stale
      worktree. End-to-end: owed to validation; `e2e_credits_deal` issues
      through the family client, and `e2e_credits_service_rollback` first
      compares images that differ in the service's code (the bound wire
      models and the vocabulary's digest) at this commit.
      **Handoff.** The API-credits label is spelled twice by design:
      `arkhai_apicredits/label.py` for the storefront, buyer, and
      `e2e-tests`, and `apicredits_service/models/keys_model.py` for the
      service, which may not import the domain; section 4's capacity profile
      carries the service's, and section 5 reads the domain's when it moves
      `issuance_evidence.py`. The storefront's client is `AuthorityClient`
      from `arkhai_api_client`, keyed to the label; a later section composing
      `selling` passes the same object. `KeysService.get_credit_issuance`
      keeps its name until section 4 moves the service. The two documentation
      attachments under `docs/attachments/` naming the deleted client call
      `fulfill_api_credits_obligation` with a signature it lost before this
      change and are left for closeout, as is the client's path named in
      `openspec/specs/api-credits/architecture.md#implementation-composition`
      (promotion row added). The fresh-context check found no wiring,
      packaging, or documentation-placement breach; accepted from it: the
      `dev` declarations of `arkhai-api` in the client and storefront
      projects, the two label comments rephrased as the current invariant,
      a divider comment and a history sentence removed, and the note
      wordings corrected above (the scripted-authority level, the client
      cache, the attachments, the parity table, the baseline evidence).
      Declined: widening the client kind's allowlist to the vocabulary or
      moving the result model into contracts, since contracts already
      publishes the vocabulary's wire models and the re-export keeps the
      client on one package; moving `test_credits_route_parity.py` to
      `unit/`, since the module's middleware cases are untouched and the
      service's suite does not split that file. Section 3 is committed
      on `feat/compose-api-family-kit-s3-client`, stacked on section 2's
      branch.
      **Review round (2026-10-23).** The owner's review of the section's
      pull request found what the passing suites did not; its fixes are a
      second commit. Accepted: contracts bumps to 0.2.0, since the headers
      module and the result-model re-exports are new public API an index
      could otherwise resolve away from a client requiring `>=0.1.0`, and
      the client and service require `>=0.2.0`; the client binds an
      outgoing issuance request through `issuance_request_model(label)`
      before anything is sent, so another label's command never reaches
      the authority (unit test: refused with no call; scripted authority:
      no request recorded); each client owns one HTTP client for its
      lifetime and offers `close()`, because closing a per-call client
      closed the transport the caller supplied with it, which the moved
      storefront client had done too (a caller-owned transport that refuses
      to serve once closed now serves two calls and closes only with the
      client); `api_credit_smoke.py` constructs the family client under the
      domain's label, its call into fulfillment still carrying the
      signature it lost before this change. Client 25 passed; contracts 16;
      service 79, storefront 197, domain 32, buyer 27 unchanged; the six
      locks recording contracts relocked; `make check-packaging` and
      comment hygiene pass on the copy. The owner confirmed the D4
      amendment recorded under 3.1. For the owner: PR checks do not run
      against a feature-branch base, so the lanes' evidence comes from
      validation's pipeline run.

## 4. The authority kit and the API-credits service root

Delivers `domains/api/authority` (`arkhai_api_authority`) and shrinks
`domains/apicredits/service` to a composition root (D4, D6, D11, D12;
`api-family` "Each domain composes the authority kit in its own service root",
"Route services are kit-owned and bindings are composition-owned";
`api-credits` "API credits composes the api family kit"). Touches the new
project and every module under `domains/apicredits/service/src/apicredits_service/`.

- [x] 4.1 `domains/api/authority/` (`arkhai-api-authority` 0.1.0; dependencies
      `arkhai-api`, `arkhai-api-contracts`, `arkhai-kit-identity`,
      `arkhai-kit-site`, `arkhai-kit-resource-pools`,
      `arkhai-kit-resource-pools-contracts`, `sqlalchemy`; never
      `arkhai-api-client`). `src/arkhai_api_authority/profile.py`: the frozen,
      validated `CapacityProfile` — offering mode, seeded pool provider,
      identity and label, deliverable and advertisable modes, backing, capacity
      resource type — and the `AuthorityConfig` carrying it with the issuance
      label, database URL, and key namespace. (D6.)
      *Done 2026-10-23.* `arkhai-api-authority` 0.1.0 declares exactly the
      seven distributions this task names and never the client.
      `profile.py`: `CapacityProfile`, a frozen dataclass validated in
      `__post_init__` — offering mode, pool provider, pool id and label,
      deliverable and advertisable modes, backing, resource type; the
      offering mode must be deliverable and a pool advertises only what it
      delivers — with `pool_policy_tags()` spelling the seeded pool's
      declarations as the resolver reads them. `AuthorityConfig` carries
      the label, the profile, the database URL, the key namespace as
      `key_prefix` (the `ak` of every key id; required, so two roots never
      share one by omission), and `distribution`, the name the version route
      reports, which D14 keeps unchanged for API credits. Both are plain
      dataclasses, so the library imports no pydantic of its own.

- [x] 4.2 `models.py`, `migrations.py`, and `database.py` moved from the
      service: the SQLAlchemy models, the migration chain with its identifiers
      unchanged, and `create_all`; `initialization.py`: the pool seed and
      `load_pool_directory`, run at startup from the profile rather than inside
      the migration chain, idempotent, reading every `api_credits` value from
      the profile. `keys_service.py`
      moved: the key service and the ledger, the reservation check comparing
      the profile's offering mode, the issuance path calling the vocabulary's
      digest under the configured label. Unit tests for the profile's
      validation and for each place a profile value replaces a literal, with an
      `inference` profile admitting an `inference` reservation and refusing an
      `api_credits` one (`api-family` "A reservation under another offering
      mode"). (D6.)
      *Done.* `models.py`, `migrations.py`, and `keys_service.py` moved
      with `git mv`; the migration identifiers are unchanged and
      `migrations.py`'s messages no longer name a domain. `database.py`
      keeps the engine, the session factory, and `run_migrations`
      (`create_all` over the credits, pool, and site metadata, then the
      chain); the pool seed leaves it for `initialization.py`'s
      `initialize(engine, profile)`, which seeds the profile's pool when
      absent, with the profile's provider, label, and declarations, keeps a
      stored pool as it is, and then refuses any stored pool without valid
      declarations — the check `run_migrations` used to make;
      `load_pool_directory` moved beside it. `KeysService` takes
      `config: AuthorityConfig`: it validates each command through
      `issuance_request_model(config.label)`, spells the result schema from
      the label, derives key ids in the configured namespace
      (`derive_key_id(key_prefix, fulfillment_id)`), and compares and claims
      the profile's offering mode where `api_credits` was literal; the
      profile's `resource_type` is carried for the root and read by nothing
      in the kit today, since the ledger's reservations do not filter by
      type. Tests: `tests/unit/test_profile.py` (unit, 12: every
      validation rule, immutability, the declarations' spelling, the
      configuration's own rules). The literal replacements are proven in
      `tests/integration/test_keys_service.py` against in-memory SQLite,
      library integration rather than the unit tests this task names,
      because the offering-mode check lives inside the ledger's admission:
      under an `inference` profile the ledger admits an `inference` hold
      and the key service commits it; an `api_credits` claim is refused at
      the site ledger's admission as undeclared by the pool the profile
      seeded, which is the only path a foreign mode has, since the key
      service claims the profile's mode itself; a purchase conflicts with a
      hold under another mode; a fresh reservation carries the profile's
      mode; the result carries the configured label's schema and key
      prefix. The moved key-service and pool-declaration suites run under a
      neutral `example` profile and label from
      `tests/integration/profiles.py`, with the seed, the kept stored pool,
      and the declaration refusal exercised through `initialize`; the
      migration suite needs no profile and moved with its imports alone.

- [x] 4.3 `route_services.py`: a framework-free route service per authority
      route — issuance, issuance lookup, consume, consume batch, verify, key
      list, key get, revoke, adjust, grants, usage, system version — each
      validating and performing the route over the key service and reporting a
      refusal as an error with status code and detail; `declarations.py`: the
      adapter from `contracts`' plain declarations to `SiteRouteContract`
      objects, in declaration order. Unit tests for every refusal's code and
      body against the 1.3 fixtures; a test that the adapted contracts equal
      the service's former table. (D4, D11.)
      *Done.* `route_services.py`: `AuthorityRouteService`, one method per
      authority route over the key service — `issue`, `get_issuance`,
      `consume`, `consume_batch`, `verify`, `list_keys`, `get_key`,
      `revoke`, `adjust`, `list_grants`, `list_usage` — each raising
      `RouteRefusal(status_code, body)` with the status and body the
      controllers served, and `SystemRouteService(distribution).version()`;
      one class rather than one per route, since every route shares the
      one collaborator. `declarations.py`: `site_route_contracts()` adapts
      the contracts' declarations to `SiteRouteContract` objects in
      declaration order. Unit tests: `test_route_services.py` (13) replays
      every refusal the 1.3 fixture records for the route services — the
      four issuance refusals, the three consumption refusals, the three
      not-found cases, the adjustment below zero; the recorded
      `issuance_invalid` 422 is the bound request model's, raised before
      any route service — over a scripted key service and asserts status
      and body equal to the record, plus the 422 detail, the
      pass-throughs, the list totals, and the version route;
      `test_declarations.py` (2) holds the adapted contracts equal to the
      declarations field for field, admitting `admin`, and equal to the
      service's recorded `route_contracts.json` table, which is the
      service's former table as 1.3 recorded it.

- [x] 4.4 `domains/apicredits/service` becomes the root: `config.py` builds
      the `AuthorityConfig` and the API-credits `CapacityProfile` from its
      unchanged `APICREDITS_*` settings; `container.py` constructs the kit's
      engine, sessions, and key service; `main.py` creates the app, installs
      `SiteAuthMiddleware` over the adapted declarations and the admin-key
      middleware, mounts the health, system, keys, and capacity routers, and
      runs the migration chain; `controllers/keys_controller.py` and
      `system_controller.py` become bindings that map each route to its route
      service and its error to a response; `middleware/route_contracts.py`,
      `models/keys_model.py`, `services/keys_service.py`, and `db/` are
      deleted. The distribution name, image, entry point, and version response
      are unchanged. (D6, D11, D12, D13.)
      *Done.* `config.py` keeps every settings read it had and adds the
      label, the API-credits `CapacityProfile` (`api_credits` mode and
      provider, the `default` pool, `api.credits` resource type, backed),
      and `authority_config`; `container.py` creates the engine from it,
      `bootstrap`s (migrations, then `initialize` under the profile), and
      wires the ledger, the key service, the route service, and the system
      service; `main.py` adapts the declarations once
      (`CREDITS_ROUTE_CONTRACTS = site_route_contracts()`), installs
      `SiteAuthMiddleware` over them and the admin-key middleware as
      before, and mounts the health, system, keys, and capacity routers.
      `keys_controller.py` and `system_controller.py` keep every decorator,
      summary, docstring, and response model, so the served OpenAPI
      document is unchanged, and each handler maps its route to the route
      service and a `RouteRefusal` to a `JSONResponse`; the bound request
      and response models come from `issuance_request_model` and
      `issuance_response_model` under the configured label.
      `middleware/route_contracts.py`, `models/`, `services/`, and `db/`
      are deleted; `middleware/auth.py`, `identity.py`, and `settings.toml`
      stay. The service declares `arkhai-api-authority`, states the
      runtime reason its identity-kit pin now needs (nothing in the root
      imports it), and bumps to 0.8.0. Its suite keeps 41 tests (unit and
      application integration): the three library suites moved to the
      authority with their 41; `test_schema_baseline` bootstraps through
      the root's `container.bootstrap`, `test_route_contract_coverage`,
      the baseline, and the parity test read the adapted table from
      `main`, the signed round-trip takes it from the adapter, and each
      takes the label from `config`. 41 passed with every 1.3 and 1.4
      record diffing to zero; the version record holds the response's
      shape and service identity, the number itself being the installed
      distribution's, now 0.8.0. The owner's review asked for coverage of
      issuance onto a revoked existing key, which 1.3 left out of the
      refusal record: the route service maps it to the 409
      `{"error": "key_revoked", "detail": ...}` the controller served
      (unit), the key service refuses the top-up with no grant, balance, or
      quota change (library integration), and the served refusal reaches
      the family client as status, reason, and detail (application
      integration, `test_signed_authority.py`).

- [x] 4.5 Verification: `make test-api-authority` (unit, library integration
      against SQLite), `make -C domains/apicredits/service test` (application
      integration: every baseline of 1.3 and 1.4 diffs to zero, the pins hold),
      `make test`, `make check-packaging` (the domain library's override row
      still stands until section 8; `check-architecture` reports no new
      finding). End-to-end: `e2e_credits_deal`, `e2e_credits_payment_deal`,
      `e2e_credits_service_rollback` once validation builds the image at this
      commit.
      *Done 2026-10-23.* `make test-api-authority` 68 passed (`tests/unit/`
      27, unit; `tests/integration/` 41, library integration against
      in-memory SQLite). `make -C domains/apicredits/service test` 41 passed
      (application integration through the real app over `ASGITransport`;
      the baselines of 1.3 and 1.4 and the pins unchanged). The storefront,
      domain library, buyer, client, and contracts suites are untouched by
      this section's code and pass under `make test`. `make test` at this
      commit: every suite passed except, all inherited and recorded by
      1.7, 2.9, and 3.4, the provisioning dotenv-layering unit test, the
      VM storefront's two Alkahest toolchain tests, the three provisioning
      IaC relay-teardown shell tests, the release-tooling whole-tree
      checks and `test_publish_matrix` rows that read the stale
      `.claude/worktrees/` checkout, and the `--eval` case; and one
      failure this section caused, the domain library's install test of
      the service wheel, which imported the service's former `db.models`
      and built no authority wheel to resolve the service against — it
      now builds the authority wheel and imports the root's `container`
      and the authority's `models` from site-packages (10 passed). Helm is
      not installed, so the render checks are unrun; the three middleware
      toolchains passed. `make check-packaging` passes on the copy: uv
      setup, locks (the authority's new lock and the service's relocked),
      Python version, layout, all four architecture parts; hygiene too.
      `make check-architecture` in place reports only the stale
      `.claude/worktrees/` checkout; each api wheel, the authority's
      included, builds once per aggregate target. End-to-end: owed to
      validation; the three scenarios are the first to run the service as
      a composition root, and `e2e_credits_service_rollback` compares a
      pre-kit image with one whose service is the authority library. The
      fresh-context check found no layering, scope, packaging, or wiring
      breach; accepted from it: the root's configuration imports moved to
      module level and the key namespace passed explicitly (and made
      required), the migration docstrings describing a deployment with a
      separate migration step rather than a plan, the declarations test
      comparing every field to the declarations, the version test over an
      installed distribution that is not the authority, and the counts
      and wordings corrected above. Declined: the family tests' path
      coupling to the service's recorded fixtures, which 4.3 prescribes as
      2.5's contracts tests did; and the service pyproject's
      runtime-reason comment, which every project with such a table
      carries. Noted for later sections: the profile's `resource_type`
      (`api.credits`) is read by nothing in the kit, and the storefront
      registers quota as `api_credits` while the service's tests and the
      lane register `api.credits`, a spelling the storefront sections
      should settle; `SchemaDriftError`'s messages no longer name API
      credits, operator-facing text outside every baseline.
      **Handoff.** The service root spells its label and profile in
      `config.py`; a sibling domain's root passes its own. The route
      services are one class over the key service; a domain contributing a
      route binds it beside the authority's routers in its own root
      (`api-family` "A domain contributes a route"). The key service still
      names its lookup `get_credit_issuance`. The authority's tests build
      everything under a neutral `example` profile, so no domain value
      enters the family tree; the service's suite is the application
      integration of the API-credits deployment. Section 4 is committed on
      `feat/compose-api-family-kit-s4-authority`, stacked on section 3's
      branch.

## 5. Selling, part one: issuance, settlement persistence, and the bundle

Delivers `domains/api/selling` (`arkhai_api_selling`) with the storefront's
issuance orchestration, settlement persistence, evidence services, and
`SellingContributions`, and the carriers in `domains/api/contracts` (D3, D7,
D11, D12; `api-family` "A domain contributes through one typed bundle per
side", "The issuance projection reads the accepted listing"). Touches the new project,
`arkhai_apicredits/settlement/fulfillment.py` and `issuance_evidence.py`,
`arkhai_apicredits/schema.py`, and under `apicredits_storefront/`:
`settlement_repository.py`, `settlement_models.py`, `settlement_composition.py`,
`domain_runtime.py`, `services/issuance_evidence.py`,
`services/fulfillment_service.py`, `listing_binding.py`,
`listing_source_check.py`, and `arkhai_apicredits/listings/reconciler.py`.
Amended at implementation: the carriers' move also touches
`domains/api/contracts`; rewiring the moved modules' callers touches
`apicredits_storefront/` `container.py`, `server.py`, `negotiation_runtime.py`,
`settlement_stages.py`, `utils/sqlite_client.py`, `controllers/settle_controller.py`
and `issuance_evidence_controller.py`, and `services/listing_service.py`,
`publication_service.py`, and `payment_settlement_service.py`; and the new
project's wiring touches both Makefiles, `tests.yml`, `publish-pypi.yml`,
`manifests/published-distributions.json`, `RELEASING.md`, and, for the
selling library's core-storefront edge, `ARCHITECTURE.toml`.

- [x] 5.1 `domains/api/selling/` (`arkhai-api-selling` 0.1.0; dependencies
      `arkhai-api`, `arkhai-api-contracts`, `arkhai-api-client`, `arkhai-core`,
      `arkhai-core-storefront`, `arkhai-kit-identity`,
      `arkhai-kit-settlement-runtime`, `arkhai-kit-negotiation-runtime`,
      `arkhai-kit-capacity-publication`, `arkhai-kit-resource-pools`,
      `arkhai-kit-site-client`, `arkhai-kit-policy`, `arkhai-kit-storefront`;
      no mechanism kit). `src/arkhai_api_selling/contributions.py`:
      `SellingContributions`, frozen, with the issuance label, kind literals and
      schema identity, listing schema and publication mapping, the
      `IssuanceProjection` callable type, optional publication guards, optional
      acceptance hook, optional public-result extension, and the consumption
      rule, each typed against the package that defines it. (D7.)
      *Done 2026-10-23.* `arkhai-api-selling` 0.1.0 declares what its source
      imports: `arkhai-api`, `arkhai-api-client`, `arkhai-core`,
      `arkhai-core-storefront`, `arkhai-kit-capacity-publication`,
      `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`,
      `arkhai-kit-policy`, `arkhai-kit-resource-pools`,
      `arkhai-kit-settlement-runtime`, `httpx` (the failure webhook), and
      `pydantic`; no mechanism kit. Of this task's list, `arkhai-api-contracts`
      (reached through the client), `arkhai-kit-site-client`, and
      `arkhai-kit-storefront` are imported by nothing yet and are left for the
      sections that import them; `arkhai-kit-resource-pools-contracts` is in
      the dev group for the tests' backing labels. `contributions.py`:
      `SellingContributions`, a frozen dataclass of the label, the `kind`
      literal (`<schema>.v1`), `offering_mode`, `contribution_id`,
      `table_prefix`, `listing_schema` (a pydantic model carrying
      `listing_resource`), `publication_mapping`, `issuance_projection`,
      `consumption_rule`, and the optional `publication_guards`,
      `acceptance_hook` (typed against `market_negotiation_runtime.Acceptance`),
      and `public_result_extension`, validated at construction. The
      settlement-evidence kind, listing-source kind, table names, and
      credentials-reference prefix are spelled from `kind` and `table_prefix`,
      which for API credits reproduces `api_credits.settlement-evidence.v1`,
      `api_credits.quota-listing.v1`, `api_credit_*`, and
      `api-credit-credential.v1`. The projection maps a `listing_resource` to
      an `IssuanceSubject` (service, quota resource, endpoint); the library
      adds the quantity and key from the accepted terms, which are the
      vocabulary's purchase shape and the same for every domain, so the
      projection can also be applied at publication, where there are no
      terms. The consumption rule is the rule's kind, `FIXED_PER_REQUEST`,
      not an amount: the per-request amount is the gate's setting, the
      storefront reads none, and adding one would change the configuration
      baseline (owner told at this section's start). `selling` depends on the
      core storefront, a composition, for its domain registry; the owner chose
      an exception row owned by `kit-owned-storefront-auth-and-persistence`
      beside the four of the same shape, and D2 and D14 say so.
- [x] 5.2 `domains/api/contracts/src/arkhai_api_contracts/carriers.py`: the
      message, terms, materialization, receipt, and result base classes bound
      to a kind literal, moved from `arkhai_apicredits/schema.py`; the
      API-credits schema module becomes bindings of them plus
      `ApiCreditsListing`. `contracts`, not `selling`, because the domain's
      codecs bind them and its buyer installs those codecs (D3, amended at
      this section's start by the owner's decision). (D3.)
      *Done.* `carriers.py`: the `Message` (over the vocabulary's
      `ProvisionTerms`), `Materialization`, `Receipt`, and `Result` bases and
      cached `message_model`, `terms_model`, `materialization_model(kind,
      listing_resource)`, `receipt_model`, and `result_model` factories; the
      materialization takes the domain's listing-resource model, its one
      domain-typed field. `contracts` declares `arkhai-core` (the message's
      `SettlementSelection`), allowlisted, and bumps to 0.3.0. `schema.py`
      binds the five and keeps `ApiCreditsListing`; the five bound classes'
      field order and JSON schema, title and description aside, were compared
      with the classes they replace before those were deleted and are
      identical. Their class names are now `Message` and the like, which
      changes the JSON-schema title, the repr, and pydantic error headers; no
      recorded OpenAPI document names them, so nothing on the wire changes,
      as section 2 accepted for the terms. Unit: `test_carriers.py` (21)
      validates each of the five carriers under each of two kinds and refuses
      the same payload under the other kind, refuses three invalid purchases,
      and carries a domain resource model in the materialization.
- [x] 5.3 `issuance.py`: the delivery orchestration moved from
      `fulfillment.py`, taking the issuance command from the bundle's
      projection applied to the accepted listing and terms recorded on the
      thread, never the current listing; refusing before publication and before
      acceptance a quota-backed listing with no quota resource; the
      compensating rollback. `evidence_store.py` and `settlement_store.py`:
      the issuance-evidence service, private-result repository, and settlement
      and progress repository moved from the storefront, their tables and
      labels parameterized by the bundle's prefix so API credits keeps
      `api_credit_*`. `failure_policy.py` from `fulfillment_service.py`. (D7,
      D12, D13.)
      *Done.* `issuance.py`: `issuance_subject` (the projection, refusing a
      listing that names no service or quota resource with
      `MissingQuotaResource` naming the listing), `delivery` (the evidence
      envelope under the bundle's kind), `settlement_evidence`,
      `prepare_issuance_request`, `connection_payload`, `fulfill`,
      `fulfill_from_hold` (the hold lookup the storefront's hook made), and the
      mechanism-neutral helpers the stages and payment service share,
      `accepted_agreement`, `persist_delivery`, `project_progress`,
      `progress_result`, `SettleResult`, and `SettlementRefusal`, moved from
      `settlement_stages.py` because they consume `delivery` and the stores.
      The compensating rollback is the Alkahest continuation's and stays with
      the stage for section 8. "The accepted listing and terms recorded on the
      thread": no storefront table holds a copy of the accepted listing, and
      adding one would change the schema baseline. The Agreement pins the
      listing's ID, every settlement path loads the listing by that ID, the
      storefront writes a listing's resource once at creation, and
      republishing creates another listing, so evidence is recorded from the
      listing the buyer accepted; the source check (5.4) also refuses a
      listing whose stored resource differs from the one its immutable binding
      pinned (owner told at this section's start). A service identity
      rewritten in place would not be caught, so the write-once rule is stated
      in D7 and the `api-family` delta as every composing storefront's
      obligation; no storefront path rewrites a listing's resource today.
      The Agreement's `listing_hash` cannot stand in for a recorded copy: it
      covers the whole stored row, status and timestamps included, which
      change after acceptance. The selling library decodes a stored
      `listing_resource` kept as JSON text itself
      (`stored_listing_resource`) rather than relying on a domain schema that
      parses it. The refusal before
      publication is in `quota_listing.prepare_listing_binding`, which the
      listing service calls before it writes; before acceptance, in the source
      check the runtime runs before every acceptance. `fulfill`'s
      `issuance_input_invalid` branch is gone: `delivery` refused the same
      input first, so it was unreachable. A public-result extension rides in
      the result and `persist_delivery` merges it beside the connection payload,
      refusing a key that is private or already public. `evidence_store.py`:
      `IssuanceEvidenceRepository`, `PrivateResultRepository`, and
      `IssuanceEvidenceService` over the vocabulary's label-parameterized
      evidence, their tables from the prefix; `IssuanceEvidenceService.body`
      builds a body under its label. `settlement_store.py`: `SettlementRepository`,
      tables from the prefix; a second unreachable branch, after a `raise`,
      was dropped in the move. `failure_policy.py`: `build_failure_policy` with
      the release-capacity, emit-event, webhook, and refund actions over
      injected collaborators (capacity runtime, reopen pass, webhook target,
      stage table, composition, stage-event log). `arkhai_apicredits/settlement/fulfillment.py`
      and `issuance_evidence.py` are deleted; `settlement/__init__.py` exports
      only the payer validator section 8 moves.
- [x] 5.4 `quota_listing.py`: the listing binding, source check, and quota
      reconciler moved from `listing_binding.py`, `listing_source_check.py`, and
      `reconciler.py`, with the offering mode, contribution identifier, and
      source kind read from the bundle. `settlement_composition.py`: the
      seller stage table construction and settlement registry over injected
      stage entries, mechanism-neutral. (D7.)
      *Done.* `quota_listing.py`: `quota_pool`, `registration`,
      `prepare_listing_binding` (taking the listing's resource and recording
      the projected quota resource), `listing_binding`, `listing_source`,
      `build_listing_source_check`, and the reconciler's
      `QuotaListingSource`, `stale_open_listing_ids`, and
      `reopenable_listing_ids`, each reading the offering mode, contribution
      identifier, and source kind from the bundle. The reconciler's
      `listing_quota_resource_id`, used by no production code, is not moved:
      the projection replaces it. `settlement_composition.py`:
      `build_settlement_registry`, `enabled_mechanism_clients`, the frozen
      `SellingSettlementComposition` (bundle, stage table, and the runtime
      parts; `accepted_settlement_artifacts`, `readiness`,
      `accepted_obligation_dispatch`, `publication_artifacts`), and the
      coordinator's `prepare_settlement`, `reserve_settlement`,
      `fulfill_settlement`, and `persist_settlement_outcome` over the injected
      table. The storefront's `ApiCreditsSettlementComposition` subclasses it
      with the Alkahest release conditions and the payment service, which are
      mechanism-specific and move in section 8.
- [x] 5.5 The API-credits storefront composes part one: its `container.py`
      fills `SellingContributions` (projection from `service_name` and
      `resource_id`, fixed amount, no guard, no hook, no extension) and passes
      it; the moved modules are deleted from the storefront and the domain
      library; `domain_runtime.py` keeps only the contract and the bundle. Unit
      tests for the projection's accepted-listing rule and the missing-resource
      refusal; the storefront's existing settlement integration tests pass
      against the kit. (D13.)
      *Done.* `container.py` holds `SELLING_CONTRIBUTIONS` (label, `api_credits.v1`,
      `api_credits`, `apicredits`, `api_credit`, `ApiCreditsListing`, the
      named-service mapping, the projection from `service_name`,
      `resource_id`, and `base_url`, `FIXED_PER_REQUEST`, no guard, hook, or
      extension). It is there rather than in `domain_runtime.py` because the
      stages, the payment service, and the SQLite client read it, and
      `domain_runtime.py` imports the stage table, so a bundle there would
      import in a cycle; `domain_runtime.py` keeps only the contract. Its
      coordinator hooks moved to `settlement_composition`, and the two
      `serialize_api_credit_settlement*` functions, which nothing called, are
      dropped. Deleted from the storefront: `settlement_repository.py`,
      `services/issuance_evidence.py`, `listing_binding.py`,
      `listing_source_check.py`; `settlement_models.py` is unchanged, since
      `ApiCreditsSettleRequest` is a component of the recorded OpenAPI document
      and its binding is section 7's. Deleted from the domain library:
      `listings/reconciler.py` besides 5.3's two; it now depends on
      `arkhai-api-contracts>=0.3.0` and no longer on the client, and bumps to
      0.9.0. The storefront declares `arkhai-api-selling`, makes `arkhai-api`
      a runtime dependency (the unmounted evidence controller imports it),
      moves `arkhai-kit-resource-pools` to its dev group (only its tests import
      it now), and bumps to 0.12.0. Tests moved to `selling` with the code:
      the generic issuance, hold, and retry cases from
      `test_settlement_fulfillment.py`, the reconciler cases from
      `test_concept_modules.py`, and `test_issuance_evidence_repository.py`;
      the domain's `test_issuance_evidence.py` is deleted with its module; the
      vocabulary's `test_evidence.py` gains the field-by-field mismatch cases
      it had and the vocabulary lacked (condition anchor, obligation, service,
      resource, key id and mode, claimant, request digest), and its pin
      test's storefront-path case is the storefront's `test_issuance_pins.py`.
      Selling's suite runs under a neutral `example` bundle whose listing names
      its fields differently from API credits, and its tests name no domain
      value. What is unit-tested in `selling`: that issuance reads the listing
      recorded in the evidence, the evidence records the listing the
      Agreement names (`test_issuance.py`); the missing-resource refusal
      before publication (`test_quota_listing.py`) and before acceptance
      through the source check, with the resource-mismatch refusal
      (`test_quota_listing.py`, over a fake repository and site); dispatch to
      the accepted mechanism's stage (`test_settlement_composition.py`).
      That a settlement loads the listing by the Agreement's ID is the
      stages' and payment service's existing code, exercised by the
      storefront's settlement tests; no test republishes a listing and
      settles, since no storefront path rewrites one. The storefront tests
      API credits' projection (`test_settlement_fulfillment.py`) and the
      resource-mismatch refusal against its real repository
      (`test_listing_source_check.py`, application integration).
- [x] 5.6 Verification: `make test-api-selling` (unit, library integration),
      `make -C domains/apicredits/storefront test` (application integration:
      1.5's baselines diff to zero), `make test`, `make check-packaging`.
      End-to-end: `e2e_credits_deal`, `e2e_credits_payment_deal`.
      *Done 2026-10-23.* `make test-api-selling` 53 passed (`tests/unit/` 43,
      unit, over fakes; `tests/integration/` 10, library integration of the
      three stores, the open-deal query, and a delivery's private secret and
      public extension through `persist_delivery` and `progress_result`,
      against real SQLite under the `example` prefix, in tables
      `tests/bundles.py` creates with the storefront's DDL until section 7
      moves the migrations; both directories are packages, so each runs on
      its own). `domains/api/contracts` 37 (unit; 21 new for the carriers);
      the vocabulary 61 (unit; 8 new evidence mismatch cases). `make -C
      domains/apicredits/storefront test` 187 passed (unit and application
      integration; 197 before: 12 cases moved to `selling` with their code, 2
      added), with 1.5's route, OpenAPI, authentication, refusal, health,
      configuration, and schema baselines and the storefront pins
      unchanged. The domain library 19 (unit and library integration; 32
      before: the 12 evidence cases left with their module, which the
      vocabulary's suite covers, and the storefront-path pin case is the
      storefront's), client 25, authority 70, service 42,
      buyer 27, e2e unit 80. `make test`: every suite passed except, all
      inherited and recorded by 1.7 to 4.5, the provisioning dotenv-layering
      unit test, the VM storefront's two Alkahest toolchain tests, the three
      provisioning IaC relay-teardown shell tests, the release-tooling cases
      that read the stale `.claude/worktrees/` checkout (the
      `test_publish_matrix` release-table rows, the three API-credits rows
      among them, and the whole-tree uv-setup and Python-version checks, all
      passing on a copy without it), and the `--eval` case the macOS make
      3.81 lacks; Helm is not installed, so the render checks are unrun.
      `make check-packaging` passes on the copy: uv setup, locks (the new
      selling lock and the contracts, client, authority, domain, service,
      buyer, storefront, and `e2e-tests` locks relocked under uv 0.11.17),
      Python version, layout, and all four architecture parts with the new
      exception row; in place they report only the stale checkout. Comment
      hygiene reports only the stale checkout. `make check-change` reports
      only the two `api-family` citations closeout creates; its agent-skills
      part fails on the copy only because the copy omits `.claude/`, and
      passes in place. End-to-end: owed to validation. `e2e_credits_deal`
      (Alkahest) and `e2e_credits_payment_deal` (payments) exercise the
      storefront's issuance, evidence, settlement stores, binding, and source
      check through `selling` once deployed; `e2e_credits_service_rollback`
      compares images whose service differs in the relocked contracts.
      **Handoff.** The bundle is `container.SELLING_CONTRIBUTIONS`; section 6
      reads its `publication_mapping` and `publication_guards` in the listing
      service and publication (today the listing service builds the
      named-service resource itself and calls `prepare_listing_binding`, which
      refuses a resource-less listing) and applies `acceptance_hook` in the
      negotiation runtime; `consumption_rule` is read by nothing yet. The
      storefront's `ApiCreditsSettlementComposition` subclasses
      `SellingSettlementComposition` with the Alkahest release conditions and
      the payment service, which section 8 moves; the stages, the payment
      service, and the SQLite client read the bundle from the container, and
      the stages' payment and Alkahest helpers read `composition.contributions`
      where they hold a composition. `tests/bundles.py` copies the storefront's
      table DDL until section 7 moves the migrations into `persistence.py`,
      when it should create the tables through them. The unmounted
      issuance-evidence controller now imports the vocabulary, so the
      storefront declares `arkhai-api` until section 7 drops the router.
      The fresh-context check's accepted findings are fixed above: the
      unreachable branch, the family code's citation of the API-credits spec,
      the stored listing resource the kit relied on a domain schema to
      decode, the function-local imports the storefront tests gained, the
      domain values in selling's tests, the missing source-check, composition,
      open-deal, refund, and delivery-projection tests, the discriminating
      carrier test, the evidence mismatch cases, an extension test with a
      secret present, and every note wording above; D7 and the `api-family`
      delta now state the projection's split, the pin, the write-once rule,
      the source check's resource refusal, the consumption rule's kind, and the
      bundle's naming fields. Declined, with the reason: the exception row's
      shape against `ARCHITECTURE.md`'s no-new-edge sentence is the owner's
      decision (D2); `kit-owned-storefront-auth-and-persistence`'s own design
      does not yet name `arkhai-api-selling` among the edges it retires,
      another change's document this section does not edit, so the owner is
      told. The connection payload's keys, the fulfilled message, and the
      `credit` wording are the family's prepaid-credit delivery shape and
      recorded bytes D14 holds fixed, now stated in D7. `selling`'s
      `arkhai-kit-resource-pools` dependency for the pool-declaration reader
      is 5.1's planned edge, and the reader's placement is the divergence
      `ARCHITECTURE.md` already names. The storefront's binding tests patch
      that module's own collaborator functions, as the file's existing tests
      do, because the fulfillment hook's signature is fixed by core; the
      failure actions' order is the selling library's dispatch and is tested
      there.

## 6. Selling, part two: negotiation, publication, and lifecycle

Delivers the negotiation adapters, publication and listing services, and
lifecycle steps in `selling` (D7, D12; `api-family` "A domain contributes
through one typed bundle per side"). Touches `arkhai_apicredits/negotiation/`
(`policies.py`, `storefront_round.py`), `arkhai_apicredits/listings/pricing.py`,
and under `apicredits_storefront/`: `negotiation_runtime.py`,
`lifecycle_steps.py`, `startup.py`, `listing_publication.py`,
`services/listing_service.py`, `services/publication_service.py`,
`services/capacity_client.py`, `services/system_service.py`.

- [ ] 6.1 `negotiation.py`: the negotiation runtime builder, the seller-round
      hook, and the round-zero, quota, and key-ownership guards moved from the
      storefront and the domain library, with the kind literal, refusal codes,
      and guard names read from the bundle; the escrow-specific guard leaves
      for section 8. `pricing.py`: the per-credit pricing helpers from
      `listings/pricing.py`. (D7.)
- [ ] 6.2 `publication.py` and `listings.py`: the publication hooks, runtime,
      publish, close, converge, and the listing service, the publication
      mapping and guards taken from the bundle; `capacity.py` from
      `capacity_client.py`; `lifecycle.py` from `lifecycle_steps.py`, with its
      per-cycle outcomes, and the background-task and seed parts of
      `startup.py`, the seed reading its listing from the bundle's mapping;
      `system.py` from `system_service.py`, serving the administrator's signed
      status read with every loop's state; `publish_route.py` from
      `listing_publication.py`, the publish-from-quota route's contract and
      typed clients, already in the route-contract form. (D7.)
- [ ] 6.3 The API-credits storefront composes part two and deletes the moved
      modules; its `startup.py` keeps only the preflight that is wiring. The
      three omitted guard tests and the negotiation integration tests pass
      against the kit. (D13.)
- [ ] 6.4 Verification: `make test-api-selling` (unit, library integration),
      `make -C domains/apicredits/storefront test` (application integration,
      baselines zero), `make test`, `make check-packaging`. End-to-end:
      `e2e_credits_deal`.

## 7. Selling, part three: route services, authentication, persistence client, and bindings

Delivers the storefront's route services and persistence in `selling` and
leaves the API-credits storefront as bindings over them (D11, D12;
`api-family` "Route services are kit-owned and bindings are composition-owned",
scenario "A storefront binds the negotiate route"). Touches
`apicredits_storefront/controllers/`, `middleware/`, `utils/`, `server.py`,
`cli.py`, `container.py`.

- [ ] 7.1 `route_services.py`: a framework-free route service for each
      storefront route the controllers serve today — listings and publish from
      quota, negotiate new and continue, negotiations list, get, advance, and
      force-accept, settle and status, admin settle wait, refund, system status
      and events — moved out of the controllers; the issuance-evidence router is
      dropped. `auth.py`: the admin, buyer, seller, and response authentication
      moved from `middleware/`. `persistence.py`: the SQLite client subclass and
      the `api_credit_*` migrations with identifiers unchanged, the table prefix
      from the bundle. (D11, D12.)
- [ ] 7.2 The API-credits storefront's controllers become bindings of a few
      lines each; `server.py` and `cli.py` keep app assembly and the admin
      commands; `utils/config.py` keeps the `APICREDITS_STOREFRONT_*` settings
      and builds the bundle's configured values; `startup_refusal.py` and
      `retired_settings.py` stay, as the root's own configuration refusal;
      `middleware/` and `utils/migrations.py` and `utils/sqlite_client.py` are
      deleted. (D11, D13.)
- [ ] 7.3 Verification: `make test-api-selling` (unit), `make -C
      domains/apicredits/storefront test` (application integration through the
      typed storefront client: every route's baseline diffs to zero, the
      startup refusal of a listing without a binding holds), `make test`,
      `make check-packaging`. End-to-end: `e2e_credits_deal`,
      `e2e_credits_payment_deal`.

## 8. The selling-side mechanism distributions

Delivers `domains/api/selling-alkahest` and `domains/api/selling-arkhai-payments`
and retires the domain library's override row (D2, D5, D12; `api-family`
"Family kit distributions exist only where a rule forces them", scenario "An
Alkahest-only storefront is installed"). Touches the two new projects,
`apicredits_storefront/settlement_stages.py`,
`services/payment_settlement_service.py`, `arkhai_apicredits/settlement/payments.py`,
the escrow guard in `arkhai_apicredits/negotiation/policies.py`,
`docs/development/ARCHITECTURE.toml`, and (amended at section 5) the
storefront's `settlement_composition.py`, whose `ApiCreditsSettlementComposition`
keeps the Alkahest release conditions and the payment service until the two
distributions own them.

- [ ] 8.1 `domains/api/selling-alkahest/` (`arkhai-api-selling-alkahest`
      0.1.0; dependencies `arkhai-api-selling`, `arkhai-kit-alkahest`): the
      seller Alkahest stage, the accepted escrow artifacts builder, and the
      escrow negotiation guard, each taking its collaborators — delivery
      callable, evidence and private-result stores, capacity runtime, chain
      client factory, settings values — as constructor arguments. Unit tests
      with injected fakes replacing the former reads of the storefront's
      container and settings. (D5.)
- [ ] 8.2 `domains/api/selling-arkhai-payments/`
      (`arkhai-api-selling-arkhai-payments` 0.1.0; dependencies
      `arkhai-api-selling`, `arkhai-kit-arkhai-payments`): the seller payments
      stage, the receipt-gated issuance service, and the payer and clause
      validators, injected the same way. (D5.)
- [ ] 8.3 The API-credits storefront's seller table composes the two entries
      from the new distributions; `settlement_stages.py`,
      `payment_settlement_service.py`, and `settlement/payments.py` are deleted;
      the domain library drops `arkhai-kit-alkahest` and
      `arkhai-kit-arkhai-payments`; its override row in `ARCHITECTURE.toml` is
      removed and `make check-architecture` reports nothing for it. A packaging
      test that a storefront environment composing only `alkahest.v1` installs
      no payments distribution. (D2, D12, D13.)
- [ ] 8.4 Verification: `make test-api-selling-alkahest` and
      `make test-api-selling-arkhai-payments` (unit, library integration),
      `make -C domains/apicredits/storefront test` (application integration,
      baselines zero), `make test`, `make check-packaging`. End-to-end:
      `e2e_credits_deal` (Alkahest), `e2e_credits_payment_deal` (payments).

## 9. The gate

Delivers `domains/api/gate` (`arkhai_api_gate`), retires
`arkhai-apicredits-middleware`, and migrates every consumer (D10, D14;
`api-family` "The bearer gate is one published family package"; `api-credits`
"A middleware consumer is sought"). Touches the new project,
`domains/apicredits/middleware/python/` (deleted),
`domains/apicredits/sample-app/`, the service's integration tests, the
conformance runner, the three middleware READMEs, `docs/cookbooks/vllm-apicredits-seller.md`,
`dev-env/identities/README.md`, `.github/workflows/publish-pypi.yml`,
`publish-npm.yml`, `tests.yml`, `domains/apicredits/compose.yml`, the root
and domains Makefiles, `docs/development/RELEASING.md`.

- [ ] 9.1 `domains/api/gate/` (`arkhai-api-gate` 0.1.0; dependencies `httpx`;
      optional extra `signed` = `arkhai-kit-identity`; dev group adds
      `arkhai-api-contracts` for 9.3): `gate.py`, `asgi.py`, `config.py`,
      `client.py`, `signing.py` moved from `apicredits_middleware`, the
      environment prefix and the label parameters of `GateConfig` with
      `APICREDITS_MIDDLEWARE_` the value the API-credits deployments pass, so
      no compose file or secret path changes. (D10.)
- [ ] 9.2 The Python conformance runner moves to `domains/api/gate/tests/` and
      replays `domains/apicredits/middleware/conformance/session.json`, which
      stays where it is; `test_gate.py` and `test_config.py` move with it.
      (D10.)
- [ ] 9.3 `domains/api/gate/tests/test_contract_parity.py`: for each route the
      gate calls, its method, path, signed operation name, request and
      response fields, and error codes equal `arkhai_api_contracts`'
      declaration; a packaging test that the gate's runtime dependency set is
      httpx alone. (D10, `api-family` "The gate's spelling drifts".)
- [ ] 9.4 Consumers migrate: the sample app and its tests import
      `arkhai_api_gate` and declare `arkhai-api-gate`; the service's
      integration tests do the same; `domains/apicredits/middleware/python/` is
      deleted and `test-apicredits-middleware` becomes `test-api-gate` with the
      TypeScript and Rust checks kept under the domain target; the three
      middleware READMEs, the cookbook, and the identities README name the
      gate; `publish-pypi.yml` and `RELEASING.md` replace the middleware's row
      and filter with the gate's; `tests.yml` replaces the matrix row;
      `publish-npm.yml` is unaffected, watching only the TypeScript directory.
      (D10, D14.)
- [ ] 9.5 Verification: `make test-api-gate` (unit, the conformance replay,
      the parity test), `make -C domains/apicredits test-sample-app` and the
      service's integration suite (application integration), `make
      test-apicredits-middleware`'s TypeScript and Rust halves unchanged, `make
      test`, `make check-packaging`, `make test-release-tooling`. End-to-end:
      `e2e_credits_deal` consumes through the gated sample app.

## 10. Buying and the buying-side mechanism distributions

Delivers `domains/api/buying` (`arkhai_api_buying`), `domains/api/buying-alkahest`,
and `domains/api/buying-arkhai-payments`, and leaves the API-credits buyer
plugin as its registrations (D2, D5, D7, D12; `api-family` scenario "A buyer
plugin is installed"). Touches the three new projects and every module under
`domains/apicredits/buyer/src/arkhai_apicredits_buyer/`, and
`arkhai_apicredits/negotiation/buyer_policies.py`.

- [ ] 10.1 `domains/api/buying/` (`arkhai-api-buying` 0.1.0; dependencies
      `arkhai-api`, `arkhai-api-contracts`, `arkhai-api-client`, `arkhai-core`,
      `arkhai-core-buyer`, `arkhai-kit-identity`, `arkhai-kit-config`,
      `arkhai-kit-policy`, `arkhai-kit-settlement-runtime`; no mechanism kit):
      `contributions.py` with `BuyingContributions` — schema identity, filters,
      rendering, command names; `buy.py`, `negotiate.py`, `settle.py`,
      `listing.py`, `common.py`, `deal.py` moved from the buyer plugin with the
      schema identity and rendering taken from the bundle; the buyer guards
      from `buyer_policies.py`; `settlement_composition.py` over injected
      entries. (D7.)
- [ ] 10.2 `domains/api/buying-alkahest/` (dependencies `arkhai-api-buying`,
      `arkhai-kit-alkahest`): the buyer Alkahest stage, escrow selection, and
      the escrow client helpers; `domains/api/buying-arkhai-payments/`
      (dependencies `arkhai-api-buying`, `arkhai-kit-arkhai-payments`): the
      buyer payments stage and payer selection. (D5.)
- [ ] 10.3 The API-credits buyer plugin keeps `cli.py`'s registration under
      `market.buyer_domains`, fills `BuyingContributions`, composes its two
      entries, and deletes every moved module; its existing tests pass against
      the kit, the three deselected `test_plugin_export.py` cases included or
      their deselection carried with its reason. A packaging test that a buyer
      environment installs no selling or authority distribution. (D12, D13.)
- [ ] 10.4 Verification: `make test-api-buying`, `make test-api-buying-alkahest`,
      `make test-api-buying-arkhai-payments` (unit, library integration),
      `make -C domains/apicredits test-buyer` (application integration through
      the buyer CLI), `make test`, `make check-packaging`. End-to-end:
      `e2e_credits_deal`, `e2e_credits_payment_deal`.

## 11. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only; a part needing a code edit returns the
change to implementation.

- [ ] 11.1 **Comment hygiene.** `make check-comment-hygiene` passes; the
      comments and docstrings sections 2–10 added describe the current system,
      with the pre-closeout review's triage having fixed any that did not.
- [ ] 11.2 **Import placement.** Confirm the imports sections 2–10 added or
      moved are module-level where safe, per the diff of each section, with the
      reasons for any that stay local recorded in their task notes.
- [ ] 11.3 **Documentation compliance.** Re-check D1–D14 against
      `openspec/README.md`'s placement rules and the promotion record below.
- [ ] 11.4 **Narrative compression.** Shorten sections 1–10's notes to final
      behaviour, evidence, deferrals, and destinations, moving rationale into
      `design.md` first.
- [ ] 11.5 **Roadmap currency.** Update Goal 8's current state and its gap
      row for this change in `docs/development/ROADMAP.md`, and record it in
      the promotion record.
- [ ] 11.6 **Campaign index currency.** Update this change's row and the
      Goal 4 campaign graph in `openspec/changes/README.md`; any change that
      depends on this one is released by archive cleanup, not here.
- [ ] 11.7 **Packaging.** `make check-packaging`, then
      `make check-architecture-change CHANGE=compose-api-family-kit`: the change
      owns no override or exception row (the domain library's row was removed
      in 8.3), and every `domains/api` project classifies from its path.
- [ ] 11.8 **End-to-end pipeline.** Record the lane run, its result, and that
      `e2e_credits_deal`, `e2e_credits_payment_deal`, and
      `e2e_credits_service_rollback` exercised this change, from validation's
      record; a pipeline that cannot run names the cause and its owner.
- [ ] 11.9 **Promotion.** Write the permanent documents the record below
      names: `docs/development/ARCHITECTURE.md` "Family kits" (the `api` family,
      its eleven distributions and the rule each exists for, the
      split-only-where-forced rule with its deferred-split trigger) and its
      runtime service map and authority-boundaries row; `docs/development/RELEASING.md`'s
      table; `openspec/specs/api-family/architecture.md` (the contribution
      bundles and what each domain supplies, the capacity profile, the issuance
      projection, the deferred ledger-free split); `openspec/specs/api-credits/architecture.md`
      "Implementation composition" and "Idempotency boundaries" citing the
      vocabulary and the service root; `openspec/specs/README.md` gaining the
      `api-family` capability. Complete the promotion record.
- [ ] 11.10 **Documentation citations.** `make check-doc-citations
      CHANGE=compose-api-family-kit` resolves every path after promotion; then
      `openspec validate compose-api-family-kit --strict`.
- [ ] 11.11 **Archival.** `openspec archive compose-api-family-kit -y`, which
      merges the `api-family`, `api-credits`, and `market-composition` deltas
      into `openspec/specs/`; the index row then links the archive.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1, D2 — the `api` family, its root, and the rule-derived distribution set | `docs/development/ARCHITECTURE.md#family-kits` |
| D1 — API credits has a family: the `#scope` sentence naming it as the domain with none, and the `#repository-layers` sentence presenting `domains/compute` as the family vocabulary, name both families | `docs/development/ARCHITECTURE.md#scope`; `docs/development/ARCHITECTURE.md#repository-layers` |
| D2 — a family's distributions split only where a rule or dependency weight forces it; an anticipated split is recorded with its trigger | `docs/development/ARCHITECTURE.md#family-kits` |
| D3, D8 — the vocabulary's contents and label-parameterized digests | `openspec/specs/api-family/spec.md`; `openspec/specs/api-credits/architecture.md#idempotency-boundaries` |
| D4 — plain-data route declarations adapted by the authority | `openspec/specs/api-family/spec.md` |
| D3 — the negotiation and delivery carriers live in `contracts`, so a buyer installs no selling machinery | `openspec/specs/api-family/spec.md`; `openspec/specs/api-family/architecture.md` |
| D2 — `selling`'s dependency on the core storefront, an exception row owned by `kit-owned-storefront-auth-and-persistence` | `docs/development/ARCHITECTURE.toml` (exception row); `docs/development/ARCHITECTURE.md#family-kits` |
| D7 — the projection's split, the pin as the Agreement's listing ID with write-once listing resources, the bundle's naming fields | `openspec/specs/api-family/spec.md`; `openspec/specs/api-family/architecture.md` |
| D5 — side-split mechanism distributions | `openspec/specs/api-family/spec.md`; `docs/development/ARCHITECTURE.md#family-kits` |
| D6 — per-domain service roots, the capacity profile | `openspec/specs/api-family/spec.md`; `openspec/specs/api-family/architecture.md`; `docs/development/ARCHITECTURE.md#runtime-service-map` and `#authority-boundaries` |
| D6 — the authority's startup: the migration chain, then the profile's pool seeded in initialization and every stored pool's declarations checked; the API-credits service's in-process migrations are the library's | `openspec/specs/api-credits/architecture.md#implementation-composition`; `docs/development/DEPLOYMENT_AND_CONFIG.md` (migrations at startup) |
| D7 — the contribution bundles and the issuance projection | `openspec/specs/api-family/spec.md`; `openspec/specs/api-family/architecture.md` |
| D9, D14 — the compatibility baselines and rollback directions | `openspec/specs/api-credits/spec.md` |
| D9 — the baselines' refusal records diff bodies, the one exception to the rejection-path status-only rule; the API-credit lane mounts the engine socket and runs the upgrade/rollback scenario | `docs/development/TESTING.md` (rejection paths; the API-credit lane) |
| D14 — `build-apicredits-service-prekit`, `.worktrees/`, and `BUYER_MACHINE_DOCKER_SOCKET` | `docs/development/BUILD_AND_PACKAGING.md` (images); `e2e-tests/README.md` |
| D10 — the gate, its parity test, the middleware's retirement | `openspec/specs/api-family/spec.md`; `docs/development/RELEASING.md` |
| D4 — the storefront composes the family client once at its composition boundary; the authority binds the contracts' wire models to its label and keeps no digest of its own | `openspec/specs/api-credits/architecture.md#implementation-composition` |
| D11 — route services in the kit, bindings in the compositions | `openspec/specs/api-family/spec.md`; `openspec/specs/api-credits/architecture.md#implementation-composition` |
| Open: the ledger-free split and inference's projection values | `openspec/specs/api-family/architecture.md` (current limits) |
| New capability | `openspec/specs/README.md` |
