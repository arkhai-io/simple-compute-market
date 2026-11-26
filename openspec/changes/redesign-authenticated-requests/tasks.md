# Tasks

Planned against the design as design review 35's triage left it (decisions D1–D20).
Section 1 holds the design phase's decision gates, each settled in `design.md`.
Sections 2–5 build the foundations and change no authority; sections 6–16 move every
authority and client onto them; the version 3 cutover is atomic (D9), so no
end-to-end lane passes until section 16 lands, and an `End-to-end:` line below is
evidence for its section only on a commit holding every section through 16.

Every section bumps each package it changes once against `dev`
(`docs/guidance/engineering/versioning.md`, "One bump per unit of work"; held by
`make check-version-bumps`), and the after-functional-change hook relocks.

## 1. Decision gates

- [x] 1.1 Decide where the shared replay contract and store implementation live.
      Settled by design D4: a standalone component under `tools/`,
      `kit/authenticated-requests` over it, and `kit/identity` for the profile and
      vocabulary.
- [x] 1.2 Decide how a route declares exact-retry resolution, its default, and its
      proof. Settled by D5 (required `RERUN`/`RECORDED`, no default, a double-dispatch
      harness with an interleaved write) and D6 (which routes record).
- [x] 1.3 Decide the reservation horizon and pruning. Settled by D7 (bounds from the
      origin, the lease floor, expired rows treated as absent, a periodic sweep the core
      owns).
- [x] 1.4 Decide how long a retained outcome lives and what a retry receives after.
      Settled by D8 (a configurable retention, 24 h by default; a signed 410) and D7
      (`exact_retry_outcome_unknown`, the renewed `RECORDED` lease).
- [x] 1.5 Decide the migration of existing rows. Settled by D9 (the 0.4.0 tables
      dropped in the version 3 release, SQLite compacted).
- [x] 1.6 Decide the restated `marketplace-identity` requirement. Settled by D14 and the
      delta specifications; `unify-compute-delivery-path` is archived and its clause is
      carried in the modified requirement.
- [x] 1.7 Decide the disposition of `retain-authenticated-request-outcomes`. Settled by
      D18: superseded, its row deferred, archived at this change's closeout.

## 2. The version 3 profile in `kit/identity`

Delivers the version 3 RFC 9421 request and response profile, its wire names, the
exact-retry vocabulary and the version 2 evidence reader (D2, D5, D10, D10a, D11's
codes, D12, D13, D17), beside the version 2 request code the authorities still use
until their sections move them. Touches `kit/identity` (`src/market_identity/`,
`pyproject.toml`, `tests/unit/`) and the `arkhai-kit-identity` bound of every
dependent.

- [ ] 2.1 Gate (D2): prove Ed25519 and EIP-191 signing and verification of an RFC 9421
      request and response through `http-message-signatures`' algorithm interface,
      `alg` omitted and the scheme selected from `keyid`, and that a small ASGI adapter
      can read the signature base from a Starlette request. Record the result in this
      task's note. If the interface cannot take a scheme-dispatched algorithm,
      `kit/identity` implements the profile's signature base itself and the library
      becomes an interoperability test oracle in `tests/` (D2's stated fallback).
- [ ] 2.2 Add the profile (D2): sign and verify request parts (method, covered
      `Market-*` fields, `Content-Digest` over the body bytes, `created`, `keyid`,
      `tag` `arkhai.market-request.v3`) and response parts (`@status`,
      `content-digest`, and the request's method, operation, resource and request ID
      under `;req`, tag `arkhai.market-response.v3`); `Market-Request-Origin` covered
      and part of the request hash (D8); `Market-Audience` a structured list of
      principals (D10); a signed delivery covering `@target-uri` in place of the audience
      (D10a). Add `http-message-signatures` and `http-sf` to the package allowlist
      (`[tool.arkhai.architecture]`) and dependencies. Verify by unit tests over one
      fixture matrix under both schemes (`openspec/specs/marketplace-identity/testing.md`):
      byte-identical vectors, field-by-field tamper rejection (every covered field and
      `created`), a response verified against its request, and the library oracle
      agreeing where 2.1 fell back.
- [ ] 2.3 Own the wire names (D13): every version 3 field name, both tags, the refusal
      codes `operation_not_served`, `operation_mismatch`, `audience_mismatch`,
      `unsupported_protocol`, and `exact_retry_expired`, `exact_retry_outcome_unknown`,
      exported from one module. Verify by a unit test that the exports are the complete
      set the delta names.
- [ ] 2.4 Add the exact-retry vocabulary as data (D5): `ExactRetry.RERUN` and
      `ExactRetry.RECORDED`, importable by contracts packages under their kind allowlist.
      Verify by a unit test, and by `make check-architecture`.
- [ ] 2.5 Keep version 2 verifiable as an evidence format (D12): the version 2 response
      and request verifiers stay importable for retained evidence, separated from
      version 2 signing so section 15 can remove signing alone. Verify by a unit test
      verifying a captured version 2 signed response vector
      (marketplace-identity "Version 2 evidence is verified").
- [ ] 2.6 Bump `arkhai-kit-identity` to 0.6.0 and move every dependent's bound to it in
      the form it uses today, exact or lower bound (D17). Verify by `make lock` and
      `make check-packaging`.
- [ ] 2.7 Verify the section: `kit/identity` unit suite; `make check-architecture`;
      `make check-packaging`.
      End-to-end: none — no authority speaks version 3 yet; the lanes run on version 2
      until section 16.

## 3. The standalone replay component

Delivers the generic replay and exactly-once machinery (D4, D5's harness, D7):
reserve, lease, renew, resolve (`RERUN`/`RECORDED`), record, expire and sweep over an
opaque key and hash, with `sqlite3` and SQLAlchemy stores, its DDL as published
statements, and ASGI and dependency wrappers. A new project, `tools/request-replay`
(distribution `request-replay`), following `tools/frp-grant-admission`'s layout, with
its `Makefile`, `README.md`, `pyproject.toml`, `uv.lock`, `src/`, `tests/unit/` and
`tests/integration/`; the root `Makefile`'s `test` target and
`.github/workflows/tests.yml`'s matrix gain `test-request-replay`.

- [ ] 3.1 Implement the store contract and both stores (D7): a row keyed by opaque
      principal and request ID, holding the request hash, kind, `expires_at`, lease
      deadline and owner, and on `RECORDED` the outcome; `expires_at` the later of the
      bound (`RERUN`: origin + 2 × skew; `RECORDED`: origin + max(retention + skew,
      2 × skew)) and the lease deadline, raised on reclaim and renewal; an expired row
      treated as absent and replaced by a reservation under its key; a lease reclaimed
      only on `RERUN`; on `RECORDED` with no outcome, in progress while the lease is
      held and outcome-unknown after; the first-use origin rule and the
      retention-expired answer for `RECORDED` (D7, D8). The component names no market
      concept. Verify by unit tests per rule against an injected clock, and library
      integration tests running the same cases on the `sqlite3` store and on the
      SQLAlchemy store over SQLite.
- [ ] 3.2 Implement lease renewal (D7): a renewal operation extending a held lease and
      raising `expires_at`, and a wrapper that renews every third of the lease period
      while a wrapped awaitable runs and stops when it returns or raises; renewal writes
      nothing for an attempt shorter than a third of its lease. Verify by library
      integration tests: a handler running past its lease is renewed and its concurrent
      retry refused as in progress, then answered with the recorded outcome; a renewal
      racing the handler's record leaves the outcome recorded and the lease cleared.
- [ ] 3.3 Implement the sweep (D7): delete expired rows through an index on
      `expires_at` in bounded batches, each its own transaction, idempotent under
      concurrent sweepers. Verify by library integration tests: a backlog swept in
      batches, a running old-origin `RERUN` attempt's row kept by its lease floor, two
      concurrent sweeps.
- [ ] 3.4 Publish the DDL (D4, D9 support): the table and index statements per dialect
      as data the market kit wraps into migrations, the component issuing no DDL when a
      store opens. Verify by a unit test that opening a store changes no schema.
- [ ] 3.5 Implement the double-dispatch harness (D5): a case is a request, a later
      write to the same resource, and the first request's exact retry re-signed;
      the harness asserts the domain state after the retry equals the state before it,
      replay table excluded, and that the retry's answer is the route's current answer;
      a completeness helper fails for a `RERUN` operation with no case. Verify by unit
      tests over a toy application with one convergent and one non-convergent route,
      the latter failing the harness.
- [ ] 3.6 Hold the standalone boundary: a structure test that the project imports and
      declares no internal distribution and names no market concept, as
      `tools/frp-grant-admission` does (`tools/README.md`, "Standalone infrastructure
      components"); `make test-request-replay` runs its unit and integration suites;
      the root `test` target and the CI matrix include it. Verify by running the target
      and `make test` resolving it.
- [ ] 3.7 Verify the section: `make test-request-replay` (unit and library
      integration).
      End-to-end: none — nothing deployed uses it yet.
      Owed by validation (ci tests.yml): the job `test · test-request-replay` runs and
      passes on a clean runner, showing the component's suites in CI.

## 4. The admission core, `kit/authenticated-requests`

Delivers the market layer over the component (D3, D4, D7, D8, D11): version 3
verification through `kit/identity`, audience, trust, the stated-operation check,
signed refusals and 500s, the outcome-unknown 409 and the 410, the signed-outcome
hook, the middleware and dependency forms, the unmatched-request fallback, the route
inventory, lease renewal around `RECORDED` handlers, the sweep's lifespan task, its
settings, and its migrations. A new foundation kit, `kit/authenticated-requests`
(distribution `arkhai-kit-authenticated-requests`), with a package allowlist;
`docs/development/ARCHITECTURE.toml`'s `[kit_areas] foundation` gains it.

- [ ] 4.1 Gate (D3): confirm the framework's route table can tell a route admitted
      through the dependency form from one that is not, and that the dependency form can
      hold a renewal task for the handler's whole run. Record the result in this task's
      note. Where the route table cannot tell, the dependency form registers each
      declaration in an explicit table at import and the inventory reads that (D3's
      stated fallback); where the dependency form cannot hold the task, stop: that is a
      design question (35 F3's trigger), and the change returns to design.
- [ ] 4.2 Implement admission (D3, D10, D11): verify signature, freshness on `created`,
      the origin's future bound, audience containing the authority's own signing
      principal, role and principal against an injected trust provider, stated operation
      and resource against the route's; reserve; resolve to `dispatch`, `rerun` (with
      `exact_retry`), `answered` or `in progress`; the time-setting operation mounted
      under injected time exempt from both `created`'s and the origin's bounds, every
      other check kept (D8, 35 F1). Verify by library integration tests over a Starlette
      application in each form: one case per refusal row of D11's table with its status,
      code and binding; a request with no request identity answered unsigned; a version 2
      request answered unsigned `unsupported_protocol`; a request under an unknown
      profile carrying the version 3 fields refused signed; a rotated authority accepted
      by an audience holding both principals; a reused request ID with a changed body,
      operation, role, principal or origin refused as changed reuse before dispatch.
- [ ] 4.3 Implement answers (D3, D7, D8): a signed 500 with a fixed detail for a handler
      that raises, logged, recorded on a `RECORDED` route and not on `RERUN`; a signed
      409 `exact_retry_outcome_unknown` for an ended attempt with no outcome; a signed
      410 `exact_retry_expired`; the signed-outcome hook handing the signed response's
      raw body and headers to the caller. Verify by library integration tests for each
      answer, and for the hook receiving the exact bytes and headers sent.
- [ ] 4.4 Implement renewal around `RECORDED` handlers in both forms (D7), through 3.2's
      wrapper. Verify by library integration tests in each form: a crash after a domain
      write and before the outcome is recorded answered `exact_retry_outcome_unknown`,
      never dispatched again; a handler running past its lease renewed, its retry in
      progress then answered with the outcome; a write that commits and then raises
      answered with a recorded 500 whose retry dispatches nothing.
- [ ] 4.5 Implement the unmatched-request fallback and the route inventory (D3): an
      application-level fallback the core installs, answering a request carrying request
      identity that no route admitted with D11's signed refusal; the inventory, checked
      when the core is constructed, refusing to start naming any route with neither a
      declaration nor an explicit unauthenticated mark (health, the OpenAPI document,
      and an unsigned time route). Verify by library integration tests: an unmatched path
      in the dependency form answered signed 404; a route with no declaration refusing
      startup by name; a signed time-setting route declared `RERUN` passing
      (marketplace-identity "A signed time-setting route in the inventory").
- [ ] 4.6 Implement the sweep's lifespan task and the settings (D7):
      `authenticated_requests.recorded_outcome_retention_seconds` and
      `authenticated_requests.replay_prune_interval_seconds`, positive integers defaulting
      to 86400 when absent, as a settings model each authority composes into its own; the
      sweep run at startup then every interval from the lifespan the authority already
      composes. Verify by unit tests of the settings model's bounds and defaults
      (marketplace-identity "The retention is not configured", "The sweep's interval is
      not configured") and a library integration test of the startup sweep.
- [ ] 4.7 Wrap the component's DDL into `kit/schema-migrations` migrations for the
      `sqlite3` and SQLAlchemy adapters, exported for each service's chain to compose,
      and the DDL the registry's Alembic revision mirrors (deployment-state "The
      authenticated-request replay table belongs to its kit"). Verify by a library
      integration test applying the migration to an empty database of each adapter.
- [ ] 4.8 Verify the section: the kit's unit and library integration suites;
      `make check-architecture`; `make check-packaging`.
      End-to-end: none — no authority composes the core yet.

## 5. Space-freeing migrations in `kit/schema-migrations`

Delivers a migration's declaration that it frees space, and the migrate command's
`VACUUM` after a chain that applied one (D9; deployment-state "A migration that frees
space is followed by compaction"). Touches `kit/schema-migrations`
(`src/market_schema_migrations/engine.py`, `sqlite.py`, the command's entry, tests).

- [ ] 5.1 Let a `Migration` declare that it frees space, and have the migrate command
      run `VACUUM` on a SQLite connection after the chain, outside any transaction, when
      a migration so declared was applied in that run; the SQLAlchemy adapter on a
      non-SQLite dialect does nothing. Verify by library integration tests: a chain
      dropping a populated table leaves a smaller file; a chain with no such migration
      does not vacuum.
- [ ] 5.2 Keep the check mode read-only: `--check` lists the pending space-freeing
      migration and neither drops nor compacts (deployment-state "An operator previews
      the upgrade"). Verify by a library integration test.
- [ ] 5.3 Verify the section: `kit/schema-migrations` unit and integration suites.
      End-to-end: none — no chain declares such a migration until sections 7 and 10.

## 6. The registry on the admission core

Moves the registry onto the core in the dependency form, with its typed client (D3,
D5, D6, D7, D9; registry-discovery "Durable replay reservation"). Touches
`core/registry/src/core_registry/api/` (`publisher_auth.py` and every route calling
it, `main.py`'s unsigned-error path), `db/models.py`, a new Alembic revision under
`alembic/versions/`, `config.py`, the registry chart's values and schema, and
`core/registry-client/src/registry_client/`.

- [ ] 6.1 Classify every authenticated registry route against D6's criterion and declare
      it; record the table in this task's note. Listing publish, update and delete are
      `RECORDED`; reads, validate and identity rotation and retirement follow the
      criterion. A route whose classification differs from the design's table, or a
      `RECORDED` route whose caller could not learn by reading whether its write
      applied, stops the section: it is a design question, and the change returns to
      design (D6, D7).
- [ ] 6.2 Authenticate every route through the core's dependency form, the store bound to
      the registry's database through the SQLAlchemy store, and remove
      `publisher_auth.py`'s own reservation, caching and completion. Verify by
      application integration tests through the typed client: a delayed retry of a
      publish after a later update answered with the recorded outcome and the update
      kept; a delete retried after the listing was republished answered with the
      recorded outcome, the republished listing kept (registry-discovery scenarios); an
      unmatched path answered signed.
- [ ] 6.3 Add the Alembic revision creating the replay table from 4.7's DDL and dropping
      `publisher_replay_reservations` (D9). Verify by the registry's migration test from
      its v0.3.0 baseline and from a database holding the 0.4.0 table with rows.
- [ ] 6.4 Move `core/registry-client` to version 3 signing and response verification,
      sending its expected-authority set as the audience. Verify by the client's unit
      suite and 6.2's application integration tests.
- [ ] 6.5 Add the retention and sweep-interval settings to the registry's settings and
      chart values schema. Verify by the registry's configuration tests and its chart
      render test.
- [ ] 6.6 Verify the section: `make test-registry`, `make test-registry-client`.
      End-to-end: `registry`, `multi_registry`, `roles_layer_registry` — evidence once
      section 16 lands.

## 7. The provisioning service and its hosted site on the admission core

Moves the provisioning service, the site it hosts, and its typed client onto the core
in the middleware form (D3, D5, D6, D7, D9; physical-provisioning "Service calls use
the shared version 3 identity contract", "A failure after authentication is answered
signed"; compute-provisioning-contract "Deal-scoped lifecycle events"). Touches
`provisioning/compute/service/src/compute_provisioning_service/` (`middleware/auth.py`,
`container.py`, `main.py`, `db/models.py`, `db/migrations.py`, settings),
`provisioning/compute/contracts/` route declarations,
`provisioning/compute/client/src/compute_provisioning_client/` (`base.py`,
`client.py`), the provisioning chart, and
`domains/vms/provisioning/` route declarations it serves.

- [ ] 7.1 Classify every authenticated provisioning and hosted-site route against D6's
      criterion and declare it in its contract; record the table in this task's note.
      `POST relays`, relay `token` rotation, relay `grant-keys/stage`, host and pool
      upserts and deletes, the VM-domain job routes but `reset-password`, and the
      `check-leases`, convergence `run-cycle` and `advance-cycle` routes are `RECORDED`;
      confirm `reset-password` `RERUN` as a keyed operation (D6, 27 F4). A difference
      from the design's table, or a `RECORDED` route whose caller could not learn by
      reading, stops the section as in 6.1.
- [ ] 7.2 Replace `ProvisioningAuthMiddleware` and `SqlAlchemyProvisioningReplayStore`
      with the core's middleware form over provisioning's database. Verify by
      application integration tests through the typed client: an exact `terminate`
      retry re-run converging; an exact `POST relays` retry with no relay ID answered
      with the recorded outcome and no second relay; a relay token rotation retried after
      a later rotation answered with the recorded outcome, the later token kept; a
      grant-key staging retried after a later staging answered with the recorded outcome,
      the later key kept (physical-provisioning and marketplace-identity scenarios); a
      route raising after authentication answered with a signed 500, recorded on a
      `RECORDED` route and re-run on a `RERUN` route; a double-dispatch case per `RERUN`
      mutation and the completeness test.
- [ ] 7.3 Add to provisioning's chain the kit's replay-table migration and a
      space-freeing migration dropping `provisioning_replay_reservations` (D9). Verify by
      the provisioning migration-chain test from its floor fixture and from a database
      holding the 0.4.0 table with rows, the file compacted after.
- [ ] 7.4 Move the provisioning client to version 3, and record each capacity-released
      notification's origin beside its request identity in provisioning's callback
      outbox (a column added by 7.3's migration), so every resend carries the same
      identity and origin. The callbacks themselves are sent through
      `core/storefront-client`, which moves to version 3 in section 10; the resent
      notification's end-to-end behaviour is proven in 11.3. Verify by the client's unit
      suite and the outbox's unit tests.
- [ ] 7.5 Add the retention and sweep-interval settings to provisioning's settings and
      chart values schema. Verify by its configuration tests and chart render test.
- [ ] 7.6 Verify the section: `make test-compute-provisioning`,
      `make test-compute-provisioning-client`, `make test-compute-provisioning-contracts`,
      `make test-provisioning`.
      End-to-end: `provisioning`, `provisioning_readonly`, `provisioning_security`,
      `e2e_compute_dynamic_listings` — evidence once section 16 lands.

## 8. The site kit and the API-credits service on the admission core

Moves `kit/site`'s middleware and the API-credits service onto the core, with the
credits clients (D3, D5, D6, D7; api-credits "Online bearer consumption";
marketplace-identity "A recorded route's attempt is lost after its domain write",
"A recorded route's handler runs longer than its lease period", "A recorded route
raises after its domain write commits", "An issuance answer is lost"). Touches
`kit/site/src/market_site/` (`auth.py`, `identity.py`, `router.py`),
`kit/site-client/src/market_site_client/client.py`,
`domains/apicredits/service/src/apicredits_service/` (`main.py`,
`middleware/route_contracts.py`, `models/keys_model.py`, settings, migrations),
`domains/apicredits/src/arkhai_apicredits/settlement/credits_client.py`,
`domains/apicredits/middleware/python/src/apicredits_middleware/` (`client.py`,
`signing.py`), and the API-credits service chart.

- [ ] 8.1 Classify every authenticated site and API-credits route against D6's
      criterion and declare it, replacing `SiteRouteContract.exact_retry_safe`;
      `credits_key_adjust` is `RECORDED`, consume and issuance `RERUN`; record the table
      in this task's note; a difference stops the section as in 6.1.
- [ ] 8.2 Replace `SiteAuthMiddleware` and `InMemoryReplayStore` with the core's
      middleware form, the store bound to each hosting service's database; no in-memory
      store remains outside tests (D7). Verify by `kit/site`'s integration suite and an
      application integration test that a replay inside the skew across a restart is
      refused (marketplace-identity "An authority restarts").
- [ ] 8.3 Require `idempotency_key` on consume and consume-batch in the version 3 wire
      models; the Python middleware client mints one where its caller gives none
      (api-credits "Consumption omits its idempotency key"). Verify by application
      integration tests: a consume without the key refused before charging; an exact
      consume retry re-run, charged once.
- [ ] 8.4 Prove adjust's crash boundary, renewal and post-commit failure through the API
      (D7): a crash after `KeysService.adjust` commits and before the outcome is recorded,
      its exact retry answered `exact_retry_outcome_unknown` and the balance adjusted
      once, then a read showing the final balance; a handler held past its lease, its
      retry in progress then answered with the recorded outcome; adjust raising after it
      commits, a recorded 500 whose retry dispatches nothing and the balance adjusted
      once; an exact adjust retry whose origin is older than the retention answered with a
      signed 410 `exact_retry_expired` and no adjustment (marketplace-identity "A recorded
      outcome expires"); an issuance answer lost and its retry rotating the unused key's secret, no
      secret in the replay store. Verify as application integration tests through the
      typed client, with a double-dispatch case per `RERUN` mutation and the completeness
      test.
- [ ] 8.5 Move `kit/site-client`, the settlement credits client and the Python middleware
      client to version 3 signing and response verification. Verify by their unit suites
      and 8.3–8.4's integration tests.
- [ ] 8.6 Add the kit's replay-table migration to the API-credits service's chain, and the
      retention and sweep-interval settings to its settings and chart values schema.
      Verify by its migration-chain test, configuration tests and chart render test.
- [ ] 8.7 Verify the section: `kit/site` and `kit/site-client` suites (via
      `make test-kits`); the API-credits service, domain and Python middleware suites
      (via `make test-domains`); the cross-language conformance session of the credits
      middleware, `domains/apicredits/middleware/conformance/session.json`, still passing
      for the Python port.
      End-to-end: `e2e_credits_deal`, `e2e_credits_payment_deal` — evidence once section
      16 lands.

## 9. The deal-lifecycle routes on the admission core

Moves `kit/deal-servicing`'s lifecycle routes and the deal-lifecycle client onto the
core in the dependency form, giving them the reservation they lack and removing their
invented refusal identity (D3; findings). Touches
`kit/deal-servicing/src/market_deal_servicing/routes.py`, `ingress.py`,
`kit/deal-lifecycle-contracts/` route declarations, and
`kit/deal-lifecycle-client/src/market_deal_lifecycle_client/client.py`.

- [ ] 9.1 Declare each lifecycle route against D6's criterion (submit and peer keyed by
      `operation_key`, reads `RERUN`); record it in this task's note; a difference stops
      the section as in 6.1.
- [ ] 9.2 Authenticate through the core's dependency form, the router taking the
      admission core its storefront composes (the storefronts compose it in sections
      10–12, over the replay table 10.2 adds); capture `lifecycle_response` evidence through the
      signed-outcome hook; a refusal for a request with no request ID answered unsigned.
      Verify by `kit/deal-servicing`'s integration suite, binding a core over a test
      database migrated with 4.7's migration: a replayed lifecycle request
      inside the skew refused by its reservation; the evidence holding the exact signed
      bytes and headers; a double-dispatch case per `RERUN` mutation.
- [ ] 9.3 Move the deal-lifecycle client to version 3. Verify by its unit suite.
- [ ] 9.4 Verify the section: `kit/deal-servicing`, `kit/deal-lifecycle-contracts`,
      `kit/deal-lifecycle-client` suites (via `make test-kits`).
      End-to-end: `e2e_vm_payment_deal`, `e2e_vm_dispute_ruled_end` — evidence once
      section 16 lands.

## 10. The core storefront and its client on the admission core

Moves core's storefront authentication and the storefront client onto the core, drops
core's replay table, and binds the kit route services (D3, D7, D9; storefront-publication
"Scheme-neutral storefront authorization"). Touches
`core/storefront/src/core_storefront/` (`auth.py`, `sqlite_client.py`'s replay methods,
`migrations.py`, `identity_authority.py` callers, settings),
`core/storefront-client/src/storefront_client/` (`auth.py`, `client.py`),
`kit/storefront/src/market_storefront_kit/deal_control_routes.py`, and
`kit/pool-overrides` route binding.

- [ ] 10.1 Replace `core_storefront.auth`'s request authentication, `ReplayStore` and the
      SQLite client's `claim_replay` and `record_replay_outcome` with the core, its store
      on the storefront's database through the `sqlite3` store; give every storefront the
      sweep from its lifespan. Verify by `core/storefront`'s integration suite, including a
      storefront route raising after authentication answered with a signed 500 its typed
      client verifies (marketplace-identity "A storefront route raises after
      authentication").
- [ ] 10.2 Add to core storefront's chain the kit's replay-table migration and a
      space-freeing migration dropping `auth_replay_reservations` (D9). Verify by each
      storefront's migration-chain test from its floor fixture and from a database holding
      the 0.4.0 table with rows, the file compacted after (deployment-state "A storefront
      upgrades from marketplace 0.4.0").
- [ ] 10.3 Move `core/storefront-client` to version 3, sending its expected-authority set
      as the audience, and replace its "reuse `request_id`" guidance with the declared
      resolution. Verify by its unit suite.
- [ ] 10.4 Declare and bind the shared route services' operations (deal-control routes,
      pool overrides) against D6's criterion: trading and listing pause and resume,
      force-accept, admin reserve and release, run-cycle and projection refresh `RECORDED`
      (D6). Record them in this task's note; a difference stops the section as in 6.1.
      Verify by `kit/storefront` and `kit/pool-overrides` suites, and an application
      integration test through the storefront client: a delayed exact retry of a listing
      pause after a later resume answered with the recorded outcome, the listing left
      resumed (marketplace-identity "A delayed retry of an absolute setter follows a later
      write"; storefront-publication "Exact retry of an administrator setter").
- [ ] 10.5 Add the retention and sweep-interval settings to core storefront's settings,
      through `kit/config`'s values-schema generator into each storefront chart's schema.
      Verify by the configuration tests and the generated-schema test.
- [ ] 10.6 Verify the section: `make test-core`; `kit/storefront`, `kit/pool-overrides`,
      `kit/config` suites (via `make test-kits`).
      End-to-end: `storefront` — evidence once section 16 lands.

## 11. The VM storefront on the admission core

Moves the VM storefront's middlewares and controllers onto the core and signs its
callback refusals (D3, D5, D6, D15). Touches
`domains/vms/storefront/src/market_storefront/middleware/` (`seller_auth.py`,
`admin_identity.py`, `buyer_auth.py`, `service_peer_auth.py`), `controllers/`
(`negotiate_controller.py`, `deals_controller.py`, `settle_controller.py`,
`introductions_controller.py`, `admin_controller.py`, `listings_controller.py`),
`settlement_stages.py`, and its tests.

- [ ] 11.1 Classify every VM storefront route against D6's criterion and declare it; the
      `RECORDED` set is negotiate new and continue, advance, force-accept, admin reserve
      and release, run-cycle, projection refresh, pause and resume, `refund_listing` and
      `arbitrate_listing`; credential-capable routes `RERUN` recording no body; record the
      table in this task's note; a difference stops the section as in 6.1.
- [ ] 11.2 Replace the four middlewares and every controller's `recorded_outcome`
      handling with the core; handlers needing to know a retry read `exact_retry`
      (`settle_controller`'s `refuse_after_end`); negotiation evidence captured through
      the signed-outcome hook. Verify by application integration tests through the typed
      client: a `negotiate_new` retry answered with the recorded outcome and no second
      negotiation; a credential-capable read retried after an end refused and no body
      recorded (marketplace-identity scenarios); a double-dispatch case per `RERUN`
      mutation and the completeness test.
- [ ] 11.3 Sign the service-peer callback's refusals (D15), and prove the resent
      capacity-released notification: provisioning's sender, through the version 3
      storefront client, resends a notification hours later under the same request
      identity and origin, re-signed, and the storefront dispatches it again, converging
      on the released reservation (compute-provisioning-contract "The storefront's
      acknowledgement is lost"; marketplace-identity "A notification is retried after its
      reservation expired"). Verify by application integration tests: a malformed
      callback answered with a signed refusal; the resent notification.
- [ ] 11.4 Verify the section: the VM storefront's unit and integration suites (via
      `make test-domains`).
      End-to-end: `e2e_deal`, `e2e_vm_payment_purchase`, `e2e_vm_introduction` —
      evidence once section 16 lands.

## 12. The bare-metal storefront on the admission core

Moves the bare-metal storefront onto the core (D3, D5, D6). Touches
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` (`api.py`,
`response_auth.py`, `runtime.py`) and its tests.

- [ ] 12.1 Classify every bare-metal storefront route against D6's criterion and declare
      it, replacing `CREDENTIAL_CAPABLE_ROUTES` and `without_access_material` with
      `RERUN` declarations that record no body; record the table in this task's note; a
      difference stops the section as in 6.1.
- [ ] 12.2 Replace `response_auth.py` and `api.py`'s authentication with the core;
      seller-response evidence captured through the signed-outcome hook. Verify by
      application integration tests through the typed client: the fulfillment access
      route retried after an end refused with no body recorded; the evidence holding the
      exact signed bytes and headers; a double-dispatch case per `RERUN` mutation and the
      completeness test.
- [ ] 12.3 Verify the section: the bare-metal storefront's suites (via
      `make test-domains`).
      End-to-end: `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal` — evidence once section 16 lands.

## 13. The API-credits storefront on the admission core

Moves the API-credits storefront onto the core (D3, D5, D6). Touches
`domains/apicredits/storefront/src/apicredits_storefront/middleware/` (`admin_auth.py`,
`seller_auth.py`, `buyer_auth.py`, `response_auth.py`), `controllers/` and its tests.

- [ ] 13.1 Classify every API-credits storefront route against D6's criterion and declare
      it; `publish-from-quota` and the shared `RECORDED` routes are `RECORDED`; record the
      table in this task's note; a difference stops the section as in 6.1.
- [ ] 13.2 Replace the four middlewares and `negotiate_controller`'s `recorded_outcome`
      handling with the core. Verify by application integration tests through the typed
      client: a `publish-from-quota` retry answered with the recorded outcome and no
      second listing; a double-dispatch case per `RERUN` mutation and the completeness
      test.
- [ ] 13.3 Verify the section: the API-credits storefront's suites (via
      `make test-domains`).
      End-to-end: `e2e_credits_deal` — evidence once section 16 lands.

## 14. Introduction starts re-run

Makes the introduction start `RERUN`, so an exact replay of a failed start completes it
and no contact is recorded (D6; introduction-delivery "Delivery fires once per reveal and
re-delivery is explicit"). Touches
`kit/contact-exchange/src/market_contact_exchange/introduction_routes.py` and its tests,
and the storefronts' introduction route declarations.

- [ ] 14.1 Declare the introduction start, reads and reveal `RERUN`, and remove the
      start's recorded-outcome path, its failed-start answer still saying a new start
      completes it. Verify by `kit/contact-exchange`'s integration suite: a failed start
      replayed exactly completes the reveal and dispatches the seller's side once; a
      completed start replayed dispatches nothing; no replay row holds a response body
      (introduction-delivery scenarios).
- [ ] 14.2 Verify the section: `kit/contact-exchange` suites (via `make test-kits`) and
      the VM and bare-metal storefronts' introduction integration tests.
      End-to-end: `e2e_vm_introduction`, `e2e_bare_metal_introduction`,
      `e2e_bare_metal_unbacked_introduction` — evidence once section 16 lands.

## 15. Buyers, the harness, signed deliveries and the end of version 2 signing

Moves every remaining signer onto version 3, binds signed webhook deliveries to their
endpoint, proves a typed client's time advance beyond the skew, and removes version 2
request signing, leaving the version 2 evidence reader (D2, D8, D9, D10a, D12). Touches
`core/buyer/src/core_buyer/` (`negotiation_client.py`, `run_log.py`), the buyer plugins
under `domains/vms/buyer`, `domains/bare_metal/buyer`, `domains/apicredits/buyer`,
`kit/delivery/src/market_delivery/builtin/webhook_sink.py`,
`e2e-tests/src/e2e_harness/` signing clients, and `kit/identity`.

- [ ] 15.1 Move `core_buyer`'s negotiation client and every buyer plugin to version 3,
      the audience from `expected_response_principals`; the run log records version 3
      request identities for recovery. Verify by the buyer suites, including run-log
      recovery.
- [ ] 15.2 Bind signed webhook deliveries to their endpoint by covering `@target-uri`
      (D10a). Verify by `kit/delivery`'s suite: a receiver verifies a delivery made for
      its endpoint and refuses one made for another (introduction-delivery "A signed
      delivery is sent to another receiver").
- [ ] 15.3 Prove a typed client's time advance beyond the skew through the core (D8,
      35 F1): a storefront at 1794822300 accepts a version 3 time-set signed with
      `created` and origin at 1794823200, moves, and answers signed at the new instant,
      while another operation 900 s skewed is refused (marketplace-identity "The harness
      advances past the skew", "Another operation arrives skewed"). Verify as an
      application integration test through the storefront client.
- [ ] 15.4 Move the end-to-end harness's signing clients to version 3. Verify by
      `make test-e2e-unit`.
- [ ] 15.5 Remove version 2 request signing and acceptance from `kit/identity`, keeping
      the version 2 verifiers for evidence (D9, D12), and confirm no package outside the
      evidence readers imports version 2 request code. Verify by the `kit/identity` unit
      suite, a repository search, and `make test`.
- [ ] 15.6 Verify the section: the buyer, `kit/delivery`, `core/storefront` and
      `kit/identity` suites; `make test-e2e-unit`; `make test`.
      End-to-end: `e2e_deal_buyer_cli`, `e2e_buy`, `e2e_vm_payment_purchase`,
      `e2e_bare_metal_payment_deal` — evidence once section 16 lands.

## 16. The cutover proven end to end

Confirms the atomic cutover across the lanes (D9) and that every authority's route
inventory is complete. Touches no production code unless a lane exposes a defect, which
its fix and test land here.

- [ ] 16.1 Run `make test` and `make check-packaging` on the whole tree: every
      authority's application-startup tests construct its admission core over its whole
      route table, so an incomplete route inventory fails them (D3). Verify by the
      commands' results, recorded in this task's note.
- [ ] 16.2 Confirm the 0.4.0 upgrade path once more: a storefront, provisioning and
      registry database from the `marketplace-v0.4.0` floor fixtures migrate, the replay
      tables gone and the SQLite files compacted. Verify by the migration-chain tests
      named in 6.3, 7.3 and 10.2 run together.
- [ ] 16.3 Verify the section: the full local suites through the pre-commit functional
      checks.
      End-to-end: every lane's scenarios — `e2e_deal`, `e2e_buy`, `e2e_deal_buyer_cli`,
      `e2e_credits_deal`, `e2e_credits_payment_deal`, `e2e_bare_metal_deal`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`,
      `e2e_vm_payment_deal`, `e2e_vm_payment_purchase`, `e2e_vm_introduction`,
      `e2e_bare_metal_introduction`, `e2e_compute_dynamic_listings`, `registry`,
      `storefront`, `provisioning`, `provisioning_security`, `multi_registry` — the
      first commit on which they are evidence for the change.

## 17. Closeout

- [ ] 17.1 Comment hygiene: run `make check-comment-hygiene`; any finding, or a comment
      the change added naming a review, decision or change, returns the change to
      implementation.
- [ ] 17.2 Import placement: check the imports the change added (`git diff dev...` over
      `*.py`); a local import that should move returns the change to implementation.
- [ ] 17.3 Documentation compliance: re-check D1–D20 against
      `openspec/README.md`, "Documentation placement", and confirm every permanent
      document this closeout writes describes the current state with no wording relative
      to the change.
- [ ] 17.4 Narrative compression: shorten section 1–16 notes to final behaviour,
      validation evidence, deferred work and destinations; move any rationale not in
      `design.md` there first.
- [ ] 17.5 Roadmap currency: in `docs/development/ROADMAP.md`, Goal 6's gap table,
      remove the row "Recorded responses kept for exact retry … are never bounded",
      now closed; the retention disclosure's scope in `contact-exchange-settlement` is
      unchanged and stays accurate. Record the update in the design-promotion record.
- [ ] 17.6 Campaign index currency: set this change's row in `openspec/changes/README.md`
      to `in closeout`, then `archived` as the archive leaves it; archive
      `retain-authenticated-request-outcomes` as superseded
      (`change-workflow openspec archive retain-authenticated-request-outcomes --skip-specs -y`)
      and move its row to "Archived and superseded" with a line naming D18; update the
      "Service-to-service trust and event delivery" graph; run `make check-change-index`.
      Record the update in the design-promotion record.
- [ ] 17.7 Packaging: run `make check-packaging`; `make check-architecture-change
      CHANGE=redesign-authenticated-requests`, which must find no exception or override
      row this change owns; the change touches no `.agents/`, `.claude/` or `.codex/`
      path, so `make check-agent-skills` is not owed.
- [ ] 17.8 End-to-end pipeline: record the pipeline run the latest passing validation
      gathered, its result, and the scenarios of 16.3 with their lanes, from that
      validation's record.
- [ ] 17.9 Promotion: write and complete the design-promotion record in `design.md`:
      - `openspec/specs/marketplace-identity/architecture.md`: "Canonical version 2
        proofs" rewritten as the version 3 RFC 9421 profile, with audience, stated
        operation, origin, wire names owned by `kit/identity` and version 2 as an evidence
        format (D2, D10, D12, D13); a new section on the admission core, its two forms,
        the fallback and the route inventory (D3); a new section on exact-retry
        resolution, which routes record, and secrets never recorded (D5, D6); a new
        section on the replay state's bounds, the lease floor and renewal, expired rows
        treated as absent, and the sweep (D7);
      - `openspec/specs/marketplace-identity/configuration.md`: a settings table for
        `authenticated_requests.recorded_outcome_retention_seconds` and
        `authenticated_requests.replay_prune_interval_seconds` (D7);
      - `openspec/specs/marketplace-identity/testing.md`, "Marketplace Identity
        Verification": the double-dispatch harness with its interleaved write, the
        completeness test, and the crash-boundary cases (D5, D7);
      - `openspec/specs/deployment-state/architecture.md`, "One engine, one contract":
        space-freeing migrations and the command's `VACUUM`, and the replay table a kit
        contributes to every authority's chain (D9);
      - `docs/development/ARCHITECTURE.md`: "Marketplace identity" for the version 3
        profile and the admission core (D2, D3); "Kit areas" for
        `kit/authenticated-requests` in the foundation area, with
        `docs/development/diagrams/kit-areas.drawio` and its SVG export (D4);
        "Authenticated service boundaries" reduced to this repository's instance — the
        300 s skew, lane time, the time-setting exemption — citing the engineering
        messaging file (D11);
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Stateful service persistence" for
        the replay table in each authority's own database and its two settings (D7);
        "Migrations at startup" for the 0.4.0 replay tables dropped and SQLite compacted
        in the version 3 release (D9);
      - `tools/README.md`, "Standalone infrastructure components": the replay
        component's entry (D4);
      - `docs/guidance/engineering/implementation.md`, "Route contracts and their HTTP
        binding": the route contract's exact-retry resolution, required with no default,
        a run-again declaration proven by a test dispatching the same request twice (D5);
      - a new `messaging.md` in `docs/guidance/engineering/`, tags
        `[engineering, messaging]`, with a `messaging` topic row in
        `docs/guidance/engineering/README.md`'s tag table: both directions signed; trust
        from configured public principals, never from the payload, a token or access to a
        signer; a standard signature format over a bespoke frame; the audience bound; each
        response bound to its request; every refusal bound to a request signed; a
        timestamp a claim checked within a tolerance, citing `implementation.md`'s "One
        time source per process"; and a message carrying a secret never stored or logged
        as it stands, stripped before any persistence (D2, D6, D10, D11);
      - `docs/release-handbook.md`, "Compatibility to retire": no row — D9 builds no
        compatibility path, and D12's evidence reader is current behaviour;
      - the delta specifications' `spec.md` files are written by the archive and named
        in the record (D14).
      Run `make check-spec-index CHANGE=redesign-authenticated-requests`.
- [ ] 17.10 Guidance placement: read the new `messaging.md`, the `implementation.md`
      section and the moved `ARCHITECTURE.md` text against the layer test — the
      engineering text names no market concept and holds with neutral examples, the
      repository's instance stays in `ARCHITECTURE.md` and `marketplace-identity` — and
      run `make check-guidance`.
- [ ] 17.11 Documentation citations: run
      `make check-doc-citations CHANGE=redesign-authenticated-requests` and resolve every
      match; then `change-workflow openspec validate redesign-authenticated-requests
      --strict`.
- [ ] 17.12 Archival: `change-workflow openspec archive redesign-authenticated-requests -y`,
      merging the deltas into `marketplace-identity`, `physical-provisioning`,
      `registry-discovery`, `storefront-publication`, `introduction-delivery`,
      `compute-provisioning-contract`, `api-credits` and `deployment-state`; no
      `--skip-specs`, since no `spec.md` was edited by hand.
