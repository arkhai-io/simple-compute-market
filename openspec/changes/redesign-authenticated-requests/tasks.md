# Tasks

Planned against the design as design review 35's triage left it (decisions D1–D20).
Section 1 holds the design phase's decision gates, each settled in `design.md`.
Sections 2–5 build the foundations and change no authority; sections 6–16 move every
authority and client onto them; the version 3 cutover is atomic (D9), so no
end-to-end lane passes until section 16 lands, and an `End-to-end:` line below is
evidence for its section only on a commit holding every section through 16.

*Amended 2026-11-27* against the design as design review 61's triage left it
(D21–D23, with D2, D7, D9, D11–D14 and D20 amended). Section 6 stopped before its
first task because retained evidence of signed messages was undesigned. Sections
5a–5c amend the foundations: `kit/identity`, the replay component and the admission
core. Sections 6, 9, 10, 11, 12, 15, 16 and 17 were replanned against the reviewed
design, and so were the route-declaration tasks of 7, 8 and 13. Sections 2–4 stay as
done, with correction notes.

*Amended again 2026-11-27* against the design as design review 85's triage left it
(D24–D29, with D2, D3, D11, D14, D20 and D21 amended). Section 6 stopped a second time,
before its first task: the registry's descriptor bootstrap could not name an audience,
and the profile signed no query values. Sections 5d and 5e amend the foundations again
(`kit/identity`, then the admission core). Section 6 was replanned against the reviewed
design. Tasks in 7–13 and 15 that move a client or declare routes now also carry the
query rule below; 9 and 10 move the storefronts' replay-table migration so that section
9 can be committed alone. Sections 2, 4, 5a and 5c stay as done, with correction notes.

Every section that declares routes declares, for each operation, whether it acts on a
target object. `Market-Resource` is sent only for one that does (D2, D21). Every
classification task's note names the declaration. Each authority here runs SQLite, so
every classification also names any `RECORDED` route that holds a write transaction
near its lease period or writes in more than one transaction (D7, design review 61 F1).
Such a route is a defect the section fixes, or, where the fix is a design question, the
change returns to design.

Every request's query is covered by `@query` (D25). So every section that moves an
authority or a client removes the query values that version 2 folded into a signed
body or a resource: the registry's `canonical_query_body`, the site kit's and
provisioning's canonical query forms, and the storefronts' negotiation-list and
stage-event resources. Such a query travels as the query, and the resource names only
the object the operation acts on, or is absent (D2, D28). Each typed client builds the
query it signs and sends from `kit/identity`'s one query encoding (5d.3). Each
authority's section proves a read whose query was altered after signing is refused.

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

- [x] 2.1 Gate (D2): prove Ed25519 and EIP-191 signing and verification of an RFC 9421
      request and response through `http-message-signatures`' algorithm interface,
      `alg` omitted and the scheme selected from `keyid`, and that a small ASGI adapter
      can read the signature base from a Starlette request. Record the result in this
      task's note. If the interface cannot take a scheme-dispatched algorithm,
      `kit/identity` implements the profile's signature base itself and the library
      becomes an interoperability test oracle in `tests/` (D2's stated fallback).
      **Passed; no fallback.** `http-message-signatures` 3.0.0 instantiates the
      configured `HTTPSignatureAlgorithm` class with whatever the key resolver returns,
      so the resolver hands it the caller's `Signer` (signing) or the `Identity` parsed
      from `keyid` (verifying), and one algorithm dispatches through the identity scheme
      registry for both schemes, `alg` omitted (`_PrincipalAlgorithm` in
      `http_profile.py`). No adapter code is needed for Starlette: `request.headers` (a
      mapping that keeps repeated field lines) and `await request.body()` pass straight
      in (unit tests `test_a_request_read_through_starlette_verifies` and
      `test_a_repeated_covered_field_line_is_malformed_through_starlette`). Two library
      behaviours are worked around: it judges `created` against the wall clock, so
      `_Verifier` checks presence only and the caller judges freshness against its own
      time source; and it parses a URL for every request message, so an audience-bound
      request and a response's bound request carry the reserved
      `https://market.invalid/`, which no signature base reads.
- [x] 2.2 Add the profile (D2): sign and verify request parts (method, covered
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
      Delivered as `market_identity.http_profile`: `sign_market_request` /
      `verify_market_request`, `sign_market_response` / `verify_market_response`,
      `MarketRequest`, `RequestBinding`, `VerifiedRequest` (`request_hash`, `fresh`,
      `addressed_to`, `binding`) and `stated_request_binding`; the audience is a
      structured list of `<scheme>:<identifier>` tokens. Unit:
      `tests/unit/test_http_profile.py`, every case under both schemes (conftest's
      `signer` matrix) — 311 passed with the rest of the suite. It covers byte-identical
      request and response vectors (`tests/unit/vectors/market_v3.json`, generated by
      this code, so a regression pin: RFC 9421 conformance rests on the library), both
      vectors verified without re-signing, request tamper on every covered `Market-*`
      field, the method, `created`, the digest, the `keyid` and the body, response tamper
      on the status, the body, `created`, the digest, the `keyid` and each bound request
      part, a response verified against a verified request, trust overlap, skew, a
      delivery refused at another endpoint, and the profile's structure (exact
      parameters `created`, `keyid`, `tag`; exact coverage; one signature per tag). The
      library oracle is not owed, since 2.1 did not fall back.
      Choices the design leaves open, for the round's review: the request hash covers
      the profile, principal, role, method, operation, resource, origin and the body's
      SHA-256, and excludes `created`, the request ID and the audience or target, so a
      retry re-sent after the caller's trust set rotated still resolves as an exact
      retry (D8 says only that the origin is included). `verify_market_request` answers
      `unsupported_version` for any request without a profile signature — version 2
      headers, another tag, or none — which section 4 maps to `unsupported_protocol`.
      `stated_request_binding` takes any stated value a signature base can hold, not
      only well-formed tokens, since the delta's request identity is the fields being
      carried. Freshness (`created` within the skew, the origin no later than now plus
      the skew) is `VerifiedRequest.fresh`; exempting the time-setting operation is the
      admission core's.
- [x] 2.3 Own the wire names (D13): every version 3 field name, both tags, the refusal
      codes `operation_not_served`, `operation_mismatch`, `audience_mismatch`,
      `unsupported_protocol`, and `exact_retry_expired`, `exact_retry_outcome_unknown`,
      exported from one module. Verify by a unit test that the exports are the complete
      set the delta names.
      `market_identity.wire`: the field names, `REQUEST_PROFILE`, `RESPONSE_PROFILE`,
      `SIGNATURE_LABEL` and `RefusalCode`. Unit: `tests/unit/test_wire.py` holds
      `wire.__all__`, the covered fields, the tags and the six codes to exactly the
      delta's; passed.
- [x] 2.4 Add the exact-retry vocabulary as data (D5): `ExactRetry.RERUN` and
      `ExactRetry.RECORDED`, importable by contracts packages under their kind allowlist.
      Verify by a unit test, and by `make check-architecture`.
      `market_identity.exact_retry.ExactRetry`, re-exported from `market_identity`. Unit:
      `test_exact_retry_declares_rerun_or_recorded_and_nothing_else`; passed.
      `make check-architecture`: passed. No contracts package imports it yet (sections 6
      onward), so the check shows only that `kit/identity` stays within its allowlist,
      which every contracts kind already admits.
- [x] 2.5 Keep version 2 verifiable as an evidence format (D12): the version 2 response
      and request verifiers stay importable for retained evidence, separated from
      version 2 signing so section 15 can remove signing alone. Verify by a unit test
      verifying a captured version 2 signed response vector
      (marketplace-identity "Version 2 evidence is verified").
      Version 2 signing (`sign_request`, `sign_response`) moved from `canonical.py` to
      `market_identity/v2_signing.py`, still re-exported from `market_identity`, so
      today's version 2 signers are unchanged; `verify_request` and `verify_response`
      stay in `verification.py`, which imports nothing from `v2_signing`. Unit:
      `tests/unit/test_v2_evidence.py` verifies captured version 2 responses under both
      schemes (`tests/unit/vectors/market_response_v2.json`) through `verify_response`
      alone, and a changed one fails; passed. No version 2 request vector is captured,
      as the task asks for the response.
- [x] 2.6 Bump `arkhai-kit-identity` to 0.6.0 and move every dependent's bound to it in
      the form it uses today, exact or lower bound (D17). Verify by `make lock` and
      `make check-packaging`.
      42 dependents moved their bound in its existing form (`==0.6.0`, or `>=0.6.0`
      from `>=0.4.0`/`>=0.5.0`) and are each patch-bumped once against `dev`; the exact
      pins on those bumped packages moved with them. The API-credits middleware's
      `signed` extra names `arkhai-kit-identity` with no bound, so it is unchanged and
      not bumped. `core/storefront-client/README.md` named the old exact pin and now
      names 0.6.0. `make lock`: passed, adding `http-message-signatures` 3.0.0 and
      `http-sf` 1.5.0 to every lock that installs `kit/identity`. `make check-packaging`:
      passed.
- [x] 2.7 Verify the section: `kit/identity` unit suite; `make check-architecture`;
      `make check-packaging`.
      End-to-end: none — no authority speaks version 3 yet; the lanes run on version 2
      until section 16.
      `make -C kit/identity test`: 311 passed (unit). `make check-architecture`: passed.
      `make check-packaging`: passed. `make test` over every project passed with the
      moved bounds; the pre-commit functional checks ran it again on the committed tree.
      End-to-end confirmed: none.

Notes (section 2):

- Correction (plan amended again 2026-11-27; D24, D25): section 5d changes what 2.2
  delivered. Every request covers `@query` second in both coverage lists, and
  verification takes the raw query string; the request hash covers the query.
  `kit/identity` gains one query encoding and a public request builder.
- Correction (plan amended 2026-11-27; D2, D13, D21, D22): section 5a changes what
  2.2, 2.3 and 2.5 delivered. The tags become `arkhai.market-request-signature.v3` and
  `arkhai.market-response-signature.v3`. The profile accepts one spelling of what it
  signs, and `Market-Resource` is present only when an operation has a target.
  `admission_unavailable` joins the wire names. Version 2 evidence is read through the
  evidence verifiers beside version 3 records, and a version 2 request vector is
  captured, which 2.5 lacked.
- Outside the plan: `kit/identity/tests/unit/conftest.py` now says its two keys are
  well-known development values, as `repository-content.md` asks of a fixture key the
  committed vectors are signed with.
- For section 4: verify with `verify_market_request(method=, headers=, body=)`, map its
  `VerificationCode`, and sign every answer with `sign_market_response(request=…)`,
  passing the verified request's `binding`, the route's binding, or
  `stated_request_binding(...)` for a request that failed before verifying; `None`
  from it means the answer is unsigned. `VerifiedRequest.request_hash` is the
  reservation's hash, `.fresh(now=, max_skew=)` the freshness check, and
  `.addressed_to(own principal)` the audience check.
- The vectors sit under `tests/unit/vectors/`, which no consumer can import. When a
  typed client's tests in sections 6–15 need a signed version 3 message, they obtain it
  from a producer fixture in `kit/identity`'s `src/` (`contract-fixtures.md`, "Signed
  protocol messages come from the producer's fixture"), which that section adds.
- Every dependent bumped here by a patch is bumped again to the next minor, one step
  from `dev`, by the section that moves it to version 3, and its exact pins move again
  then.
- `tests/unit/test_http_profile.py` reads requests through Starlette, a dev-group
  dependency of `kit/identity`; the package itself imports no HTTP framework.
- The suite's `PytestConfigWarning` about `asyncio_mode` predates this section.

## 3. The standalone replay component

Delivers the generic replay and exactly-once machinery (D4, D5's harness, D7):
reserve, lease, renew, resolve (`RERUN`/`RECORDED`), record, expire and sweep over an
opaque key and hash, with `sqlite3` and SQLAlchemy stores, its DDL as published
statements, and ASGI and dependency wrappers. A new project, `tools/request-replay`
(distribution `request-replay`), following `tools/frp-grant-admission`'s layout, with
its `Makefile`, `README.md`, `pyproject.toml`, `uv.lock`, `src/`, `tests/unit/` and
`tests/integration/`; the root `Makefile`'s `test` target and
`.github/workflows/tests.yml`'s matrix gain `test-request-replay`.

- [x] 3.1 Implement the store contract and both stores (D7): a row keyed by opaque
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
      `request_replay.store` (`ReplayStore`, `Entry`, `Row`, `Outcome`),
      `request_replay.policy` (`Resolution`, `Policy`), `request_replay.guard`
      (`RequestReplay.admit` answering `Dispatch(attempt, exact_retry)`, `Answered`,
      `InProgress`, `ChangedReuse`, `OutcomeUnknown`, `Expired`; `complete`, `renew`,
      `sweep`), `SqliteReplayStore` (a connection per step, each `BEGIN IMMEDIATE`)
      and `sqlalchemy_store.SqlAlchemyReplayStore` (insert, a key conflict read as
      held; every other step one conditional statement). The rules are one module,
      `tests/rules.py`, of 18 cases against a `ManualClock`: unit
      (`tests/unit/test_rules.py`, against the in-memory double in
      `tests/support.py`) and library integration (`tests/integration/test_store_rules.py`,
      the same 18 on each store over a real SQLite file migrated from the published
      DDL); passed. `tests/unit/test_policy.py` holds the bounds' arithmetic (unit);
      passed. A `RECORDED` request whose origin is older than the skew is never
      claimed: only its row can answer it, and with none it is `Expired`. A `RERUN`
      request claimed with an origin older than the skew is a retry whose row has
      gone, so it is dispatched with `exact_retry` true. Library integration,
      `tests/integration/test_concurrency.py` on both stores: two first uses racing,
      the competitor's claim run inside the other's through a test-only adapter, end
      one dispatched and one in progress (the SQLAlchemy store through a real key
      conflict); two retries racing for an ended `RERUN` lease end one reclaiming and
      one in progress; a `sqlite3` step finding the write lock held is refused with no
      busy timeout; and the SQLAlchemy claim whose conflicting row vanished before the
      read claims again, giving up after three; passed.
- [x] 3.2 Implement lease renewal (D7): a renewal operation extending a held lease and
      raising `expires_at`, and a wrapper that renews every third of the lease period
      while a wrapped awaitable runs and stops when it returns or raises; renewal writes
      nothing for an attempt shorter than a third of its lease. Verify by library
      integration tests: a handler running past its lease is renewed and its concurrent
      retry refused as in progress, then answered with the recorded outcome; a renewal
      racing the handler's record leaves the outcome recorded and the lease cleared.
      `RequestReplay.renew` and `renewing(replay, attempt, sleep=asyncio.sleep)`, an
      async context manager; a renewal extends only a lease its owner still holds,
      so an ended lease is not revived (rule case `test_an_ended_lease_is_not_renewed`).
      Library integration, `tests/integration/test_renewal.py` on both stores: the
      handler past its lease (the waits stepped by the test, never slept), the short
      attempt writing no renewal, renewal stopping when the handler raises, and the
      race in both orders (renew after record, renew then record), and a renewal
      failing once with "database is locked" tried again before the lease ends;
      passed. The race is shown as the two orders of the store's steps, not as two
      threads.
- [x] 3.3 Implement the sweep (D7): delete expired rows through an index on
      `expires_at` in bounded batches, each its own transaction, idempotent under
      concurrent sweepers. Verify by library integration tests: a backlog swept in
      batches, a running old-origin `RERUN` attempt's row kept by its lease floor, two
      concurrent sweeps.
      `RequestReplay.sweep(batch_size=500)` over `ReplayStore.sweep_batch`. Library
      integration, `tests/integration/test_sweep.py` on both stores: 250 expired rows
      swept as batches of 100, 100 and 50; an old-origin `RERUN` attempt's row kept
      and its retry in progress; two stores over one database alternating batches
      deleting each of 120 rows once; passed. SQLite serializes writers on its write
      lock, so two sweepers' batches interleave rather than overlap; the test drives
      that interleaving batch by batch, and shows idempotence, not overlapping
      transactions.
- [x] 3.4 Publish the DDL (D4, D9 support): the table and index statements per dialect
      as data the market kit wraps into migrations, the component issuing no DDL when a
      store opens. Verify by a unit test that opening a store changes no schema.
      `request_replay.ddl.statements(dialect, table=)` for `sqlite` and `postgresql`,
      default table `request_replay`, and `replay_table()` describing it for
      SQLAlchemy without creating it. Unit: `tests/unit/test_ddl.py`; passed.
      Correction to the plan's level: the store-open proof needs a real database, so
      it is library integration, `tests/integration/test_store_open.py` on both stores
      — opening and using a store leaves `sqlite_master` unchanged, a store over a
      database without its table fails with "no such table" and creates nothing, and a
      recorded response outlives the store that recorded it; passed. The PostgreSQL
      statements are rendered and unit-tested as text only; nothing in this section
      runs them.
- [x] 3.5 Implement the double-dispatch harness (D5): a case is a request, a later
      write to the same resource, and the first request's exact retry re-signed;
      the harness asserts the domain state after the retry equals the state before it,
      replay table excluded, and that the retry's answer is the route's current answer;
      a completeness helper fails for a `RERUN` operation with no case. Verify by unit
      tests over a toy application with one convergent and one non-convergent route,
      the latter failing the harness.
      `request_replay.harness`: `DoubleDispatchCase`, `run_double_dispatch(case,
      snapshot=)`, `assert_complete`, `DoubleDispatchFailure` (an `AssertionError`), and
      `sqlite_snapshot`; `sqlalchemy_store.table_snapshot` for SQLAlchemy databases.
      The route's current answer is the case's own `current_answer` callable. Unit:
      `tests/unit/test_harness.py` over a toy of two async methods — `raise_to` passes,
      `set_to` fails on the state, a stale answer fails on the answer, completeness
      names the missing operations; passed. Library integration:
      `tests/integration/test_snapshots.py`, both snapshots over a real SQLite file,
      the excluded table's writes unseen; passed. The toy is plain async functions, not an
      HTTP application: the harness drives whatever callables a case supplies.
- [x] 3.6 Hold the standalone boundary: a structure test that the project imports and
      declares no internal distribution and names no market concept, as
      `tools/frp-grant-admission` does (`tools/README.md`, "Standalone infrastructure
      components"); `make test-request-replay` runs its unit and integration suites;
      the root `test` target and the CI matrix include it. Verify by running the target
      and `make test` resolving it.
      Unit: `tests/unit/test_structure.py` — imports only the standard library, itself,
      and SQLAlchemy in `sqlalchemy_store.py` alone; declares no runtime dependency and
      only the `sqlalchemy` extra; its lock resolves nothing from the wheelhouse; and
      no source token names a marketplace word (`host` and `site` among them); the
      import and marketplace-word checks are each also shown finding a planted
      violation, the declaration and lock checks are not; passed. `make test-request-replay`: passed; `make -n test` runs it.
      The root `Makefile` gains `test-request-replay` and `dist-request-replay` (in
      `dist-release-set` and `dist-ci`), and `tests.yml`'s matrix
      `test-request-replay`. `make test-release-tooling` over `test_publish_matrix.py`,
      `test_init_targets.py`, `test_tests_workflow.py` and `test_release_components.py`:
      223 passed.
- [x] 3.7 Verify the section: `make test-request-replay` (unit and library
      integration).
      End-to-end: none — nothing deployed uses it yet.
      Owed by validation (ci tests.yml): the job `test · test-request-replay` runs and
      passes on a clean runner, showing the component's suites in CI.
      `make test-request-replay`: mypy strict clean; 67 unit and 67 library-integration
      tests passed. End-to-end confirmed: none. The owed line is confirmed as written.

Notes (section 3):

- Outside the plan: the distribution is `arkhai-request-replay`, not `request-replay`
  as the section's heading named it, because a released package's name takes the
  `arkhai-` prefix (`published-packages.md`, "Published packages") and the admission
  core's wheel will depend on it. The directory is `tools/request-replay` and the
  import `request_replay`. Being a runtime dependency of released services from
  section 6 on, it is declared in `manifests/release-components.json` and in
  `published-packages.md`'s table now, beside `arkhai-injected-time`, whose layout
  (a library with `make build DIST_DIR=`) it follows rather than
  `frp-grant-admission`'s image layout.
- For section 4: the component's resolution vocabulary is its own
  `request_replay.Resolution` (`"rerun"`, `"recorded"`), since it may not import
  `kit/identity`; the kit maps `ExactRetry` onto it by value. The entry's
  `principal` is an opaque string — the kit passes `principal_text(identity)` — and
  `request_hash` is `VerifiedRequest.request_hash`. `RequestReplay` takes the time
  source as `clock` (integer seconds); pass `injected_time.now`.
- For section 4: `complete(attempt, outcome)` records only on `RECORDED`; on `RERUN`
  it releases the lease, so the next exact retry reclaims at once rather than waiting
  out the lease. Hold a `RECORDED` handler inside `renewing(...)`.
- Outside the plan, for section 4: D4 places "ASGI and dependency wrappers" in this
  component, and this section built only their framework-free parts —
  `request_replay.asgi` (`read_body`, `replayed_receive`, `capture`,
  `send_response`) and `renewing`. The wrappers that admit, dispatch, record and
  answer are built in section 4 beside the kit's two forms, once its gate (4.1) has
  settled what the dependency form can hold; their generic part lands here, in
  `request_replay`, and only the market's verification and signing in the kit. The
  kit's migrations wrap `ddl.statements(...)`, choosing their table name (the default
  is `request_replay`).
- For closeout: `tools/README.md`'s "Standalone infrastructure components" says a
  component names no "lease"; it means a compute lease. This component's central
  concept is the dispatch lease an attempt holds on its request, so the entry 17.9
  writes for it reconciles that wording.
- Declined from the fresh-context check: running the renewal's store step on a
  thread (`asyncio.to_thread`). Every store step is one short transaction, as the
  admission's own steps are on the same loop; a lock held past the busy timeout
  fails the step, which renewal now retries at its next interval.
- The sweep's default batch is 500 rows (`DEFAULT_SWEEP_BATCH`).
- No test-before run: every test imports what only this project adds, so each would
  fail at collection against the base, which shows nothing more.

## 4. The admission core, `kit/authenticated-requests`

Delivers the market layer over the component (D3, D4, D7, D8, D11): version 3
verification through `kit/identity`, audience, trust, the stated-operation check,
signed refusals and 500s, the outcome-unknown 409 and the 410, the signed-outcome
hook, the middleware and dependency forms, the unmatched-request fallback, the route
inventory, lease renewal around `RECORDED` handlers, the sweep's lifespan task, its
settings, and its migrations. A new foundation kit, `kit/authenticated-requests`
(distribution `arkhai-kit-authenticated-requests`), with a package allowlist;
`docs/development/ARCHITECTURE.toml`'s `[kit_areas] foundation` gains it.

- [x] 4.1 Gate (D3): confirm the framework's route table can tell a route admitted
      through the dependency form from one that is not, and that the dependency form can
      hold a renewal task for the handler's whole run. Record the result in this task's
      note. Where the route table cannot tell, the dependency form registers each
      declaration in an explicit table at import and the inventory reads that (D3's
      stated fallback); where the dependency form cannot hold the task, stop: that is a
      design question (35 F3's trigger), and the change returns to design.
      **Passed; no fallback.** FastAPI's route table tells an admitted route from one
      that is not: each `APIRoute`'s `dependant` tree holds the declaration's callable
      (a `RouteAdmission` instance), which the inventory walks. The dependency form
      holds the renewal for the handler's whole run without relying on how a
      dependency with `yield` exits: the dependency starts a `Renewal` when it admits,
      and the core's application wrapper, which runs around the whole application in
      both forms, stops it once the handler's response is complete. Shown on FastAPI
      0.162.0 (`kit/deal-servicing`'s lock) and 0.115.14 (the VM storefront's) by a
      scratch script: a task started in a dependency is still running when the
      wrapper regains control after the response, and `scope["state"]` written by the
      wrapper is the route's `request.state`. The kit declares `fastapi>=0.115`; the
      0.115.14 observation is that scratch run, and the committed suite runs only the
      kit's locked FastAPI, where the dependency-form renewal and cancellation tests
      reproduce the gate.
- [x] 4.2 Implement admission (D3, D10, D11): verify signature, freshness on `created`,
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
      `market_authenticated_requests`: `AdmissionCore` (`verify`, `admit`,
      `refuse_unserved`, `refuse_unbound`, `finish`, `fail`, `answer`), the
      middleware form through `install(app, core, routes=<RouteTable>)` and the
      dependency form through `Depends(RouteAdmission(core, operation=, roles=,
      exact_retry=, resource=))`, both wrapped by `AuthenticatedApplication`. Checks in
      order: route, signature, stated operation and resource, audience, freshness,
      role, trust, then the reservation; a proof failing on a route is refused signed
      over the route's operation and resource and the stated request ID. Library
      integration, `tests/integration/test_admission.py`, under both caller schemes and,
      but where a case names one form, in both forms (70 passed): a signed first use; 404 and 405 with `Allow`
      `operation_not_served` over the stated fields; 400 `operation_mismatch` for a
      stated operation and for a stated resource, bound over the route; 421
      `audience_mismatch`; a signed 400 `unsupported_protocol` for a request whose tag
      names another profile; an unsigned `unsupported_protocol` for a real version 2
      request; unsigned answers for requests carrying no identity; a rotated authority
      accepted by an audience holding both principals; changed reuse of body, role,
      origin and operation refused 409 before dispatch, and a principal swapped into
      the proof refused 401; wrong role and untrusted principal 403; `created` and
      origin outside the skew 401; the time-setting operation 900 s ahead accepted and
      answered signed at the new instant while another operation as far ahead is
      refused; a body holding no resource a signed 400; a broken proof on a route a
      signed 401 bound over the route; and, in the dependency form, a declared route
      whose earlier dependency refuses first answering signed over the stated fields;
      and a request failing before its admission (a body the route cannot parse)
      answered a 500 signed over its stated fields, in both forms. The "changed
      principal"
      reuse is a proof whose `keyid` was altered: a different principal re-signing is a
      different reservation key, not a reuse.
- [x] 4.3 Implement answers (D3, D7, D8): a signed 500 with a fixed detail for a handler
      that raises, logged, recorded on a `RECORDED` route and not on `RERUN`; a signed
      409 `exact_retry_outcome_unknown` for an ended attempt with no outcome; a signed
      410 `exact_retry_expired`; the signed-outcome hook handing the signed response's
      raw body and headers to the caller. Verify by library integration tests for each
      answer, and for the hook receiving the exact bytes and headers sent.
      Library integration, `tests/integration/test_answers.py` in both forms and
      schemes: a recorded route's exact retry answered with the same status and body
      under a fresh signature after a later write; a re-run route's retry run again,
      told it is a retry; a recorded route raising after its write answered a signed
      500 with the fixed detail, the error logged, its retry the same 500 with one
      dispatch; a re-run route raising answered a signed 500 and its retry dispatched
      again; a recorded retry past the retention a signed 410 `exact_retry_expired`;
      the hook receiving the status, the headers in order and the body sent; and a
      reservation
      the store fails answered a signed 500 with nothing dispatched; passed. The
      hook, `on_signed_outcome`, receives every signed answer to a request that
      verified, refusals after verification included; a consumer filters by the
      request's operation. The outcome-unknown 409 is 4.4's.
- [x] 4.4 Implement renewal around `RECORDED` handlers in both forms (D7), through 3.2's
      wrapper. Verify by library integration tests in each form: a crash after a domain
      write and before the outcome is recorded answered `exact_retry_outcome_unknown`,
      never dispatched again; a handler running past its lease renewed, its retry in
      progress then answered with the outcome; a write that commits and then raises
      answered with a recorded 500 whose retry dispatches nothing.
      Library integration in both forms, `tests/integration/test_answers.py`: an
      attempt whose outcome never lands after its write (a store wrapper whose
      `record` raises; the handler's answer is still sent signed) answered
      `exact_retry_outcome_unknown` once its lease ends, never dispatched again, a
      read then showing the write; a handler held past its lease, renewed every third
      of it (the waits stepped by the test and their durations asserted), its retry
      refused in progress, then answered with the outcome once it returns; a handler
      cancelled mid-run leaving no task behind, its renewal stopped with it; and a
      write that commits and then raises answered with a recorded
      500 whose retry dispatches nothing (the `/fail` case of 4.3); passed. The
      process stopping between commit and record is modelled by the failing record,
      not by stopping a process. The core starts renewal for every
      `RECORDED` admission and stops it in `finish`; a `RERUN` attempt holds a fixed
      lease that its retry may reclaim.
- [x] 4.5 Implement the unmatched-request fallback and the route inventory (D3): an
      application-level fallback the core installs, answering a request carrying request
      identity that no route admitted with D11's signed refusal; the inventory, checked
      when the core is constructed, refusing to start naming any route with neither a
      declaration nor an explicit unauthenticated mark (health, the OpenAPI document,
      and an unsigned time route). Verify by library integration tests: an unmatched path
      in the dependency form answered signed 404; a route with no declaration refusing
      startup by name; a signed time-setting route declared `RERUN` passing
      (marketplace-identity "A signed time-setting route in the inventory").
      The fallback is part of `AuthenticatedApplication`: before the application runs,
      it matches the request against the application's own routes, and a request
      carrying a request identity that none serves is verified and answered 404 or 405
      signed, in either form; a request carrying none goes on to the application
      unchanged. `install` checks the inventory (`undeclared_routes`) and raises
      `RouteInventoryError` naming each route that neither takes a `RouteAdmission`,
      nor is bound by the middleware form's table (`RouteTable.declares`), nor is
      marked by `Unauthenticated` (health and the OpenAPI document by default). Library
      integration: the unmatched path signed 404 in the dependency form (and the
      middleware form) in `test_admission.py`; the toy authority installing in both
      forms with its signed time route declared `RERUN`. Unit,
      `tests/unit/test_inventory.py` over applications whose routes never reach a
      store: a dependency-form route with no declaration refusing startup by name, a
      middleware table missing a route refusing it, a route admitting through a
      dependency in the middleware form refused, an unsigned time route passing once
      marked and a signed one declared `RERUN` passing, a declaration with no
      resolution failing where it is declared, a route served without the wrapper
      refusing to run, and a caller leaving before its body is whole answered nothing;
      passed. A mounted application is one route by its mount's path, declared or
      marked whole, in the inventory and at request time alike; no test mounts one,
      and no authority mounts an application today.
- [x] 4.6 Implement the sweep's lifespan task and the settings (D7):
      `authenticated_requests.recorded_outcome_retention_seconds` and
      `authenticated_requests.replay_prune_interval_seconds`, positive integers defaulting
      to 86400 when absent, as a settings model each authority composes into its own; the
      sweep run at startup then every interval from the lifespan the authority already
      composes. Verify by unit tests of the settings model's bounds and defaults
      (marketplace-identity "The retention is not configured", "The sweep's interval is
      not configured") and a library integration test of the startup sweep.
      `AuthenticatedRequestsSettings` (strict positive integers, 86400 when absent,
      unknown keys refused) and `AdmissionCore.sweeping()`, an async context manager
      for the authority's lifespan sweeping at startup and every interval, each sweep
      in a worker thread. Unit: `tests/unit/test_settings.py`; passed. Library
      integration: `tests/integration/test_sweep.py`, the startup sweep deleting
      expired rows and a second sweep, after the test steps the wait, deleting a later
      one, each wait asked for `replay_prune_interval_seconds`; and a sweep the store
      fails logged and the next one sweeping; passed. That the
      default is a day rests on the settings unit test.
- [x] 4.7 Wrap the component's DDL into `kit/schema-migrations` migrations for the
      `sqlite3` and SQLAlchemy adapters, exported for each service's chain to compose,
      and the DDL the registry's Alembic revision mirrors (deployment-state "The
      authenticated-request replay table belongs to its kit"). Verify by a library
      integration test applying the migration to an empty database of each adapter.
      `SQLITE_REPLAY_TABLE_MIGRATION` (in `migrations`) and
      `SQLALCHEMY_REPLAY_TABLE_MIGRATION` (in `sqlalchemy_support`, the `sqlalchemy`
      extra), both id `authenticated_requests_0001_replay_table`, creating
      `authenticated_request_replay` and its expiry index from the component's
      statements; `replay_table_statements(dialect)` for the registry's Alembic
      revision; `sqlite_replay_store` and `sqlalchemy_replay_store` over that table.
      Library integration: `tests/integration/test_migrations.py`, each migration
      applied by the engine to an empty SQLite database, the table and index present,
      a store admitting over it, and using the store leaving the schema snapshot
      unchanged, for both adapters; passed. Unit: the kit's statements are the
      component's for its table; passed. The toy authority every
      other integration test uses is migrated by a chain composing the sqlite3
      migration.
- [x] 4.8 Verify the section: the kit's unit and library integration suites;
      `make check-architecture`; `make check-packaging`.
      End-to-end: none — no authority composes the core yet.
      `make -C kit/authenticated-requests test`: 26 unit and 116 library-integration
      tests passed. `make -C tools/request-replay test`: 67 unit and 71
      library-integration tests passed, `Renewal.start`, `stop` and `cancel` among
      them. `make check-architecture`: passed. `make check-packaging`: passed
      in the pre-commit functional checks. End-to-end confirmed: none.

Notes (section 4):

- Correction (plan amended again 2026-11-27; D3, D11, D24, D25; design review 85 F1):
  section 5e changes what 4.2 and 4.5 delivered. Admission verifies against the raw
  query string in both forms. The route inventory admits a third mark, a public
  operation, answered signed with nothing reserved. The fallback answers an unmatched
  request that states a request identity and carries no signature field with the signed
  404 or 405 over its stated identity, without verifying it.
- Correction (plan amended 2026-11-27; D3, D7, D11, D23): section 5c changes what
  4.2–4.4 delivered.
  - A replay-store failure while admitting, resolving or concluding a request is a
    signed 503 `admission_unavailable`, not the signed 500 4.3 answers.
  - An ended attempt's retry concludes it before it is answered outcome-unknown.
  - The signed-outcome hook hands over records rather than raw headers, and the
    admission carries the request's record and body.
  - A resource stated for an operation with no target is an `operation_mismatch`.
- Outside the plan: the kit is `kit/authenticated-requests` (distribution
  `arkhai-kit-authenticated-requests`, import `market_authenticated_requests`),
  declared in `manifests/release-components.json` and `published-packages.md`'s table
  after `arkhai-kit-identity`, in `ARCHITECTURE.toml`'s foundation area, and in
  `kit/Makefile`'s `test`, `dist` and `dist-ci`. Its package allowlist names the
  identity, migration and time components, the replay component, FastAPI, Starlette,
  pydantic and SQLAlchemy.
- Correction to section 3's handoff: the generic part of the wrappers that landed in
  `request_replay` is `Renewal` (start where a request is admitted, stop where its
  response completes) beside `asgi.capture` and `replayed_receive`. Admission,
  dispatch, recording and answering stay in the kit's `AuthenticatedApplication`,
  since each step is interleaved with verification or signing.
- For sections 6–15, composing the core: build `AdmissionCore(signer=, trust=,
  store=, settings=, time_setting_operation=)` — `signer` and `trust` are callables,
  so a rotation or a reloaded trust set is read per request — and wrap the
  application last with `install(app, core, routes=..., unauthenticated=...)`, after
  every route is added; the inventory reads the routes then. The middleware form's
  route table implements `resolve(method, path, body)` raising `RouteNotServed` or
  `ResourceUnbound`, and `declares(method, path_template)`. A middleware-form handler
  reads the admission from `request.state.authenticated_request`; a dependency-form
  route receives it from its `RouteAdmission`. `Admitted.exact_retry` is the retry
  flag. Compose `core.sweeping()` into the lifespan, and the kit's migration into the
  chain.
- A refusal in the dependency form raises Starlette's `HTTPException` with the
  answer's status so no handler runs; the wrapper sends the signed answer in place of
  what the framework rendered. A request-validation 422 after admission is the
  route's answer, recorded on a `RECORDED` route.
- Every response the wrapper sends is held whole before it is sent, unauthenticated
  routes' included; no authenticated route streams today.
- The verification failures other than D11's rows keep the `{"detail": ...}` bodies
  the authorities answer today (`Invalid request proof`, `Request timestamp is outside
  the allowed skew`, `Request principal is not trusted`, `Marketplace role is not
  authorized`), so a typed client's error handling reads them as before.
- An application in the middleware form admits every unmarked request through its
  table, so `install` refuses one whose routes also take a `RouteAdmission`: a route
  admitted twice would find its own lease held.
- A route's HEAD is not implied by its GET: a route table or a mark names it.
- A replay-store failure after authentication is answered signed: a failed
  reservation is a signed 500 with nothing dispatched; a failed record still sends the
  handler's answer signed, and the request's exact retry is outcome-unknown once its
  lease ends.
- For closeout: D4 places "ASGI and dependency wrappers" in the standalone component;
  admission, dispatch, recording and answering live in the kit's
  `AuthenticatedApplication` and `RouteAdmission`, and the component holds `Renewal`
  and the framework-free ASGI plumbing. The promotion in 17.9 describes them where
  they are.
- No test-before run: every test imports what only this kit adds.
- Fix from implementation review 45, F1 (D7's third case): a lease that ended under a
  live `RECORDED` handler, its store refusing every renewal for the whole period, was
  only retried or ended in silence. An `Attempt` now carries the `lease_until` it was
  admitted with; `RequestReplay.renew` answers the lease's new end, or `None` once
  the attempt no longer holds it (it answered a bool); `RequestReplay.now()` is added.
  A `Renewal` tracks the lease's end from those, and logs one error naming the
  request, saying its retry is told the outcome is unknown while the attempt can still
  commit, when a failed renewal finds the lease ended, a renewal finds it no longer
  held, or its holder stops it after the lease ended between renewals; it then stops
  renewing. The handler is not stopped (the owner's choice over cancelling it). 6.1
  and 7.1 name SQLite authorities' `RECORDED` routes holding a write transaction near
  the lease period.
- The fix's evidence. Library integration, `tools/request-replay` `make test` (mypy
  strict, unit 67 passed, integration 77 passed): on both stores, a store refusing
  every renewal lets the lease end under the live handler, its retry `OutcomeUnknown`,
  one loss logged at error naming the request; a lease ending between renewals is
  logged when the handler returns; a renewal finding its lease ended (a stalled loop
  or a moved time source) logs it; the rule cases assert the admitted and renewed
  lease ends. Library integration through the kit, `kit/authenticated-requests` `make
  test` against the rebuilt wheel, 146 passed:
  `test_a_recorded_handler_whose_renewals_all_fail_loses_its_lease_while_it_runs`, in
  each form and scheme, renewals refused past the lease, the exact retry answered a
  signed 409 `exact_retry_outcome_unknown`, the loss logged once at error, the handler
  still running, then its answer recorded and a later retry receiving it, one
  dispatch. `change-workflow run test-before` at `01b2f4434` on `test_renewal.py`: the
  three loss tests fail there (no error logged), and the two record-race tests fail
  only on `renew`'s new answer; the kit test's sequence but its log passes there,
  since answering outcome-unknown is unchanged. The fresh-context check found the
  deadline comment backwards, the deadline read after the renewal trailing the
  lease's written end (now `renew`'s answer), a "retrying" log on the final failure,
  tests not checking the level and request, a loss between renewals going unlogged,
  and this note's missing evidence; all fixed. Its question whether 6.1 and 7.1's
  route check is in scope: it is, part of the option the owner chose. A second
  fresh-context check of the revised `Renewal` found it sound, and found the final
  failure logged twice at error, the finds-ended test passing on its stop alone, no
  test that renewal stops after a loss or that a renewed attempt logs none, and the
  README's retry sentence unqualified; all fixed. The pre-commit history-wording check
  refused "no longer" in `renew`'s docstring; reworded. Then `change-workflow run
  pre-commit`: "after-functional-change at 01b2f4434…: passed, exit 0", local
  evidence PASSED (`make test` passed in 470.9 s), "pre-commit-functional at
  01b2f4434…: passed, exit 0", "pre-commit at 01b2f4434…: passed, exit 0".

## 5. Space-freeing migrations in `kit/schema-migrations`

Delivers a migration's declaration that it frees space, and the migrate command's
`VACUUM` after a chain that applied one (D9; deployment-state "A migration that frees
space is followed by compaction"). Touches `kit/schema-migrations`
(`src/market_schema_migrations/engine.py`, `sqlite.py`, the command's entry, tests).

- [x] 5.1 Let a `Migration` declare that it frees space, and have the migrate command
      run `VACUUM` on a SQLite connection after the chain, outside any transaction, when
      a migration so declared was applied in that run; the SQLAlchemy adapter on a
      non-SQLite dialect does nothing. Verify by library integration tests: a chain
      dropping a populated table leaves a smaller file; a chain with no such migration
      does not vacuum.
      `Migration(..., frees_space=True)`. Applying such a migration records, in its
      own transaction, that the database owes a compaction
      (`MigrationConnection.owe_compaction`; on SQLite the header's `user_version`);
      every run of `migrate` then performs an owed compaction once, after its last
      migration (`compact`: `VACUUM`, outside any transaction, then the record
      cleared), so a compaction that fails — `CompactionFailed`, naming the command —
      is performed by the next run, even one applying nothing. The SQLAlchemy
      adapter runs it through the SQLite driver connection, leaving the connection's
      isolation level as it was, and owes nothing on any other dialect.
      `MigrateReport.compacted` says whether the run compacted. Library integration,
      `kit/schema-migrations/tests/integration/test_compaction.py`, over real SQLite
      files through the SQLAlchemy adapter and the `sqlite3` adapter under each of its
      three transaction controls: a chain dropping a populated table that frees space
      leaves a file smaller by more than half the table's bytes, its free list empty;
      the same chain not declaring it leaves the pages on the free list; a rerun
      owing nothing does not compact; a compaction failing once (a test subclass of
      each adapter) leaves the migrations recorded and the compaction owed, and the
      next run performs it; and the SQLAlchemy driver connection's isolation level is
      unchanged after, for the default and for an `AUTOCOMMIT` engine; passed. Unit,
      `tests/unit/test_sqlalchemy_compaction.py`: on a non-SQLite dialect the adapter
      issues nothing to its connection — a `MagicMock` standing in for a database
      this suite does not have; passed. `test-before` against the round's base: every
      test of `test_compaction.py` failed there on `Migration` refusing
      `frees_space` — the declaration is absent, which shows less than a behaviour
      failing.
- [x] 5.2 Keep the check mode read-only: `--check` lists the pending space-freeing
      migration and neither drops nor compacts (deployment-state "An operator previews
      the upgrade"). Verify by a library integration test.
      The check is unchanged: it runs no migration, so it neither drops nor compacts.
      Library integration, `test_compaction.py`: `check_sqlite_file` over a database
      whose space-freeing migration is pending reports it behind with that migration
      pending, the file byte-for-byte unchanged and the table still present; passed.
      This is the engine's check, which every service's `--check` reports; a service's
      own command entry is proven by its chain tests in sections 7 and 10.
- [x] 5.3 Verify the section: `kit/schema-migrations` unit and integration suites.
      End-to-end: none — no chain declares such a migration until sections 7 and 10.
      `make -C kit/schema-migrations test`: 79 passed (unit and library integration).
      End-to-end confirmed: none.

Notes (section 5):

- `arkhai-kit-schema-migrations` is bumped 0.1.0 to 0.2.0 (new public API); every
  dependent declares a lower bound `>=0.1.0`, so none moves here, and the
  after-functional-change hook relocked every lock installing it.
- For sections 7 and 10: a space-freeing migration is declared
  `Migration("<id>", <drop>, frees_space=True)` in the service's chain after the kit's
  replay-table migration, and the service raises its lower bound on
  `arkhai-kit-schema-migrations` to `>=0.2.0`. The engine logs the compaction; the
  commands log only `report.applied` today, so a command reports `compacted` only if
  its section adds it. The VACUUM needs free space of about the database's remaining
  size while it rewrites the file.
- For section 6, a premise to settle: D9 says the registry's PostgreSQL returns the
  space on `DROP TABLE`, but the registry runs SQLite today
  (`helm/charts/registry/values.yaml`, `databaseUrl: sqlite:///…`) and migrates
  through Alembic, not this engine, so 6.3's Alembic revision dropping
  `publisher_replay_reservations` compacts nothing as planned. Section 6 decides
  whether `registry-migrate` compacts after Alembic, or returns the question to the
  owner.
- The SQLite adapter takes the database header's `user_version` as its record of an
  owed compaction; no service's database uses it otherwise.

## 5a. The version 3 profile amended, and evidence records, in `kit/identity`

Amends the profile and adds the evidence records, their verifiers and the version 3
capture seam (D2, D11's codes, D13, D21, D22, D23; marketplace-identity "Body-bound
authenticated request and response version", "A signed message retained as evidence
verifies offline as a record"). Touches `kit/identity`
(`src/market_identity/http_profile.py`, `wire.py`, `capture.py`, a new evidence module,
`__init__.py`, `tests/unit/`). `arkhai-kit-identity` 0.6.0 is unreleased and already
bumped against `dev` by 2.6, so this section bumps nothing.

- [x] 5a.1 Rename the tags to `arkhai.market-request-signature.v3` and
      `arkhai.market-response-signature.v3`. Add `admission_unavailable` to the wire
      names beside the other refusal codes (D2, D7, D13). Regenerate the version 3
      vectors. Verify by `tests/unit/test_wire.py` holding the exports to the delta's set,
      and the vector tests.
      `wire.REQUEST_PROFILE`/`RESPONSE_PROFILE` renamed;
      `RefusalCode.ADMISSION_UNAVAILABLE`. `tests/unit/vectors/market_v3.json`
      regenerated by this code (still a regression pin), and gains
      `targetless_request_headers` and `targetless_response_headers`, the second
      coverage list. Unit: `test_wire.py` (exports, tags, the seven codes) and the
      vector tests in `test_http_profile.py`, both schemes; passed.
- [x] 5a.2 Accept one spelling of everything the profile signs (D2):
      - the covered components in the profile's order;
      - the signature parameters in the order `created`, `keyid`, `tag`;
      - `Market-Audience` equal to its canonical list serialization;
      - one `sha-256` member in `Content-Digest`, in canonical form.

      Refuse any other spelling as malformed. Verify by unit tests under both schemes:
      a request whose parameters, components, audience spacing or digest members are
      spelled otherwise refused, though its RFC 9421 signature verifies
      (marketplace-identity "A request signs its parameters in another order").
      `_select` compares the covered components and the parameters as ordered
      tuples; `_audience` and `_require_canonical_digest` compare the field value
      with its re-serialization (one `sha-256` member, no parameters), on requests
      and responses; a principal in `keyid` or the audience must be written as
      `principal_text` writes it. Unit, `test_http_profile.py`, both schemes: each
      misspelling is re-signed by `http-message-signatures`' own signer (its base
      builder, for a parameter order its public `sign` does not write), and a
      test-local oracle (the library's verifier over the public scheme registry)
      verifies it, then the profile refuses it as malformed —
      parameters `keyid, created, tag`, two components swapped, an audience without
      the space after its comma, a digest with a second member, a parameter, or
      another algorithm; a response re-signed the same way with its parameters or
      components reordered or a digest parameter is malformed; an EIP-191 address
      in upper case as a request's or a response's `keyid`, or as an audience member,
      is malformed; the oracle accepts the profile's own spelling of each; passed.
- [x] 5a.3 Send `Market-Resource` only for an operation with a target (D2, D11). A
      request with no resource omits the field and its component. A response to it omits
      `"market-resource";req`, so each of request and response has two coverage lists.
      `RequestBinding`, `MarketRequest` and `stated_request_binding` carry an absent
      resource as absent, not as an empty string. The request hash tells absent from
      present. Verify by unit tests under both schemes:
      - a targetless request and its response sign and verify;
      - adding or removing the field after signing fails;
      - a response bound with the other coverage list fails.

      `RequestBinding.resource` is `str | None`, defaulting to `None`; a present
      resource is non-empty. Verification picks the coverage list by whether the
      request carries the field; `stated_request_binding` needs only
      `Market-Operation` and `Market-Request-ID`. The request hash frames
      `("absent",)` or `("present", resource)`. Unit, `test_http_profile.py`, both
      schemes: the four cases above, the targetless vectors, a binding without the
      resource failing against a targeted response, the hash differing for an
      absent resource and one named `"absent"`, and an empty resource refused;
      passed.
- [x] 5a.4 Add the evidence records (D21, D13). The request record holds `protocol`,
      `principal` as one string, `role`, `method`, `operation`, `resource` only when the
      request carried one, `request_id`, `timestamp`, `origin`, `audience` as strings,
      and `proof` as the signature value. The response record holds `protocol`,
      `principal`, `status`, `timestamp`, `proof`, and the answered request's `method`,
      `operation`, `resource` where present and `request_id`.
      - Neither keeps a digest or a header.
      - Signing and verifying produce the record, so no caller builds one.
      - A delivery bound by `@target-uri` produces none (design review 61 F3).
      - The field names are wire names exported with the rest.

      Verify by unit tests under both schemes:
      - the record from signing equals the record from verifying;
      - a record survives a JSON round trip;
      - a targetless request's record has no `resource` key.

      `market_identity.records`: `RequestRecord`, `ResponseRecord` (strict, frozen;
      `principal` and `audience` members must be written as `keyid` writes them;
      `proof` is the signature in its scheme's canonical encoding, as `SignatureProof`
      writes it; a `None` resource is left out when serialized; a response record's
      answered-request values are bounded only by what a header carries, since a
      refusal binds what its request stated). `wire.RecordField`
      names their keys. `sign_market_request` and `sign_market_response` now return
      `SignedRequest`/`SignedResponse` (`headers`, `record`); `VerifiedRequest`
      gains `proof` and `record`; `ResponseVerification` gains `record`. A delivery
      bound by `@target-uri` produces `record=None`. Unit, `test_records.py`, both
      schemes, targeted and targetless: the three cases above, no digest or header
      key in either record, and a request or response record holding what no
      signature carries refused; `test_http_profile.py` a refusal over a 200-character
      stated operation signed, its record and verification equal; `test_wire.py`
      holds the record models' fields to `RecordField`; `test_http_profile.py` a
      delivery with no record; passed.
- [x] 5a.5 Add the two evidence verifiers (D22). The request verifier takes a record,
      the body, the trusted principals, and the expected role, operation and resource.
      The response verifier takes the same but no role (design review 61 F4).
      - Each reads a version 3 record or a stored version 2 envelope by its `protocol`.
      - Each rebuilds the signature base, computes the digest from the body, checks the
        proof and the principal, and applies no freshness and no audience check.
      - Each returns one view: principal, timestamp, operation, resource, request ID,
        and the role or the status.
      - A version 2 response's signed role is not checked.

      Capture a version 2 request vector beside 2.5's response vector. Verify by unit
      tests under both schemes (marketplace-identity "A buyer verifies a seller's
      publication long after it was signed", "A retained record is altered", "A version
      2 record and a version 3 record are verified alike", "An end acknowledgement's
      response is verified without a role", "Version 2 evidence is verified"):
      - sign, record, store as JSON and verify days later with no freshness;
      - every altered field and an altered body fail;
      - the version 2 request and response vectors verify through the same verifiers
        into the same view.

      `market_identity.evidence`: `verify_request_evidence(retained, body=,
      trusted=, expected_role=, expected_operation=, expected_resource=)` and
      `verify_response_evidence` (no role), answering
      `RequestEvidenceVerification`/`ResponseEvidenceVerification` with a
      `RequestEvidence`/`ResponseEvidence` view. A version 3 record is verified by
      rebuilding its headers (`http_profile.rebuild_request_headers`,
      `rebuild_response_headers`) and running the profile's own verifier without
      freshness (`check_market_response` is `verify_market_response` less the skew);
      a version 2 envelope through its canonical bytes and its canonical body hash.
      `expected_resource` defaults to unchecked, and `None` expects none; a version 2
      empty resource reads as `None`. Captured: `tests/unit/vectors/market_request_v2.json`
      and `market_request_v2_targetless.json`, signed by version 2 signing with
      conftest's keys. Unit, `test_evidence.py`, both schemes: a publication record
      stored as JSON verifying with no clock anywhere; each altered request field
      (role, method, operation, resource added or removed, request ID, timestamp,
      origin, audience, proof) and response field (status, timestamp, method,
      operation, resource, request ID, proof) and an altered body failing; another
      principal of the signer's own scheme failing the proof (`invalid_proof`) for
      each; an end acknowledgement verified by the seller alone with no role; for
      each verifier, an untrusted principal, each unmet expectation, an unknown
      protocol and a malformed record refused; the version 2 request and response
      vectors (the response's signed role unread) verifying into the same view
      types as version 3 records, each version 2 view equal to its envelope's
      values, a changed version 2 body or field failing for each, and a
      version 2 empty resource read as `None`; passed. 2.5's
      `test_v2_evidence.py` still passes.
- [x] 5a.6 Carry records in the client-side capture seam (D23). `CapturedEnvelope` holds a
      version 3 record, its body and the expected principals. The version 2 form stays
      until section 15 removes version 2 signing, since clients move section by section.
      `capture_envelope` checks the body against the record's digest. Verify by unit tests:
      a captured version 3 response and request whose records verify through 5a.5; a body
      differing from the signed one refused before the sink runs.
      `capture_envelope(sink, envelope=<record>, raw_body=, verified_at=,
      expected_principals=)` verifies the record against the body and the expected
      principals through 5a.5 before the sink runs (a record keeps no digest, so the
      check is the record's own verification), and hands the sink a
      `CapturedEnvelope` whose `envelope` is the record and whose `headers` are
      empty; a record given headers is refused. The version 2 form and the
      dataclass's positional fields are unchanged. Unit, `test_capture.py`, both
      schemes: the two captures verifying, a changed body and another principal set
      refused with the sink not run, and headers refused; passed.
- [x] 5a.7 Add a producer fixture to `kit/identity`'s `src/`: signed version 3 requests
      and responses, and their records under both schemes. Later sections' consumer tests
      draw their messages from it (`contract-fixtures.md`, "Signed protocol messages come
      from the producer's fixture"; section 2's notes). Verify by a unit test that every
      fixture message verifies and every record verifies through 5a.5.
      `market_identity.fixtures.messages`: `build_signed_request`,
      `build_signed_response`, `build_market_request`, `development_signer`,
      `development_authority`, `validate_request_record`,
      `validate_response_record`. Its keys are derived by SHA-256 from fixed labels,
      so no key literal is committed. Unit, `test_fixtures.py`, both schemes,
      targeted and targetless: every request and response verifying live (the record
      verification produces equal to the fixture's) and as evidence from its JSON,
      the validators accepting them and refusing a resource that should be absent,
      and the development signers distinct and deterministic; passed.
- [x] 5a.8 Verify the section: `make -C kit/identity test` (unit); `make
      check-architecture`; `make check-packaging`.
      End-to-end: none — no authority speaks version 3 until section 16.
      `make -C kit/identity test`: 477 passed (unit). `make -C
      kit/authenticated-requests test` against the rebuilt wheel: 146 passed (unit
      and library integration). `make check-architecture`: passed. `make
      check-packaging`: passed. End-to-end confirmed: none.

Notes (section 5a):

- Correction (plan amended again 2026-11-27; D21, D25): section 5d adds `query` to the
  request record 5a.4 defined, `?` where the request had no query, and regenerates
  5a.7's fixture with a request carrying a query.
- Outside the plan: the new API reaches `kit/authenticated-requests`, which this
  commit adapts only so its suite passes: it reads `.headers` from
  `sign_market_response`, and treats a route resource `""` as none (`or None` in
  `AdmissionCore.verify` and `admit`), since `RequestBinding` now refuses an empty
  resource; its tests send `resource=None` by default and expect the renamed tag.
  Section 5c replaces the `or None` with a route's declaration that its operation
  has no target. An `operation_mismatch` body therefore names a targetless
  route's resource as `null` where it named `""`.
- The targetless `operation_mismatch` body's `null` is proven by 5c.2's tests,
  where the route's declaration lands.
- Fixed from the fresh-context check: a response record capped the stated values a
  refusal binds, so signing a refusal over a long stated operation raised; a request
  record capped the audience and `timestamp` a verified request may carry; the
  profile's record-rebuilding and freshness-free response check were public
  (`_check_market_response`, `_rebuild_request_headers`, `_rebuild_response_headers`
  and `_record_binding` now, imported by the evidence module alone); one test was
  weakened to accept either code; the response verifier's refusals, the response
  record's validation, the response spelling cases, a changed version 2 response
  body, the response validator's refusal and the sink left unrun on a principal
  mismatch were untested; test keys lacked their development-value comment. A
  second check found the profile accepting an EIP-191 principal in another case,
  whose record could not rebuild its base and whose response record raised (now
  malformed); the tests building RFC 9421 bases by hand (now the library's own
  signer, so no framing is the test's); an unreachable comparison in the request
  evidence verifier; a docstring naming readers that do not yet exist; a `method`
  in the evidence view, which D22 does not list (dropped); and altered-principal
  cases that failed at parsing rather than at the proof under one scheme, an
  untested response proof change, and version 2 views compared by type alone.
- `VerificationCode` moved to `market_identity.codes`, re-exported from
  `market_identity.verification` and the package: the capture seam verifies records
  through the evidence verifiers, and `verification.py` imports the capture seam, so
  the codes could not stay there without an import cycle.
- A record's `resource` may be given as `None` on construction, which reads as
  absent; serialization leaves the key out.
- `test-before` at `f4af51435` on `tests/unit/test_http_profile.py`: 143 failed, 23
  passed — most on `sign_market_request(...).headers`, which the base lacks; that
  shows less than a behavioural failure. The other new test files import what only
  this section adds, so they fail at collection there.
- For sections 6–15: sign with `sign_market_request(...)` and read `.headers` and
  `.record`; the admission's verified request carries `.record`; verify retained
  evidence only through `verify_request_evidence`/`verify_response_evidence`;
  consumer tests draw messages from `market_identity.fixtures.messages`. A response
  record's method, operation, resource and request ID are whatever its signature
  bound, which for a refusal of an unverified request are the stated values, so they
  are held only to what a header can carry.

## 5b. The replay component concludes an ended attempt

Makes an exact retry conclude an ended `RECORDED` attempt by a write before it is told
the outcome is unknown, so that answer cannot overtake a transaction the attempt still
holds (D7, design review 61 F1; marketplace-identity "Each route declares how an exact
retry is resolved"). Touches `tools/request-replay` (`store.py`, `guard.py`,
`sqlite_store.py`, `sqlalchemy_store.py`, `tests/support.py`, `tests/rules.py`,
`tests/integration/`). The component is new in this change, so nothing is bumped.

- [x] 5b.1 Add the concluding step to the store contract and both stores. One
      conditional write marks a `RECORDED` row concluded where it has no outcome and its
      lease has ended. It keeps the row's owner, so the attempt's own later `complete`
      still records its outcome. `RequestReplay.admit` answers `OutcomeUnknown` only when
      that write applied, or the row was already concluded, and never from a read. A store
      refusing or timing out on any step surfaces as one distinct store-unavailable
      failure, which the kit maps to its 503. Verify by new rule cases in `tests/rules.py`,
      as unit tests against the in-memory double and library integration on both stores:
      - a retry after the lease ends concludes the attempt and is `OutcomeUnknown`;
      - the attempt's later `complete` records, and a later retry receives the outcome;
      - a renewal after conclusion revives nothing;
      - a store refusing the concluding write surfaces store-unavailable.

      `ReplayStore.conclude(principal, request_id, *, now)`: one transaction that
      clears a live `RECORDED` row's lease end where it has no outcome and its lease
      has ended, keeping the owner, then reads the row — `None` when no live row holds
      the key. A concluded row is no lease end, an owner, no outcome; no other row has
      that shape, so it needs no column. `SqliteReplayStore` runs it under `BEGIN
      IMMEDIATE`; `SqlAlchemyReplayStore` as an `UPDATE` then a read in one
      transaction, the update taking SQLite's write lock even when it matches nothing
      (5b.2's second test). `RequestReplay._resolve` answers a `RECORDED` row with no
      outcome and an ended lease only from `conclude`'s row: `Answered` if recorded
      meanwhile, `OutcomeUnknown` only if that row is concluded (`Row.concluded`),
      `Expired` if gone, else `InProgress`. `StoreUnavailable` (exported) is raised,
      chained, for any failure of any store step in `admit`, `renew`, `complete` and
      `sweep`. Rule cases in `tests/rules.py`, unit against the in-memory double
      (which gains `conclude`) and library integration on both stores over real
      SQLite files: the first three cases above (the conclusion keeping the owner
      and a second retry still `OutcomeUnknown`), and an outcome recorded between
      the retry's read and its concluding write (a test adapter recording first)
      answered `Answered`; passed. Unit, `tests/unit/test_store_failures.py`,
      against the double behind an adapter failing the named step: the concluding
      write refused surfacing `StoreUnavailable` chained to the store's error with
      the row not concluded, and every other step refused (`claim`, `get`,
      `release`, `record`, `renew`, `sweep_batch`, `reclaim`) surfacing it, each
      chained; passed. The task asked for the refused concluding write as a rule case
      on both stores too; the adapter raises before any store is reached, so a real
      store adds nothing there, and a real lock refusing the concluding write is
      5b.2's SQLAlchemy cases. Existing integration tests now expect `StoreUnavailable`:
      two chained to the driver's error, one ("kept changing") to the SQLAlchemy
      store's own `RuntimeError`.
- [x] 5b.2 Prove the ordering against a real database. Library integration on both
      stores over one SQLite file the "handler" also writes. The handler holds its own
      write transaction past its lease; its exact retry is not answered `OutcomeUnknown`
      while that transaction is open. It is answered store-unavailable, or waits, as the
      store's lock handling gives. After the handler commits, the retry concludes the
      attempt. A read then shows the handler's write, and a replacement write is not
      overwritten. Cover the SQLAlchemy store's retry older than the skew, which read
      plainly before (D7's 61 F1 note).
      Library integration, `tests/integration/test_conclusion_order.py`, on both
      stores, each meeting the held lock with no busy timeout, for a retry within the
      skew and one older than it: the handler's connection holds `BEGIN IMMEDIATE`
      and an insert past the lease; the retry raises `StoreUnavailable` and the row's
      lease end is untouched; after the handler commits, the retry is
      `OutcomeUnknown`, a read shows the handler's write, the caller's replacement
      write stands after the attempt's late `complete`, and a later retry receives
      the recorded outcome; passed (4 cases). Which step meets the lock: the claim
      within the skew on both stores, the `sqlite3` store's `get` (under `BEGIN
      IMMEDIATE`) older than it, and only on the SQLAlchemy store older than the
      skew the concluding write itself, after a plain read. The replacement check
      shows that the late `complete` touches no domain row; the handler writes once,
      so nothing of its could overwrite it. A second test, both stores: a concluded
      attempt's retry older than the skew is still refused while a transaction holds
      the lock, then `OutcomeUnknown`; passed (2 cases). Only on the SQLAlchemy store
      is that refusal the matchless concluding write's; the `sqlite3` store's read
      already takes the lock.
      `change-workflow run test-before` at `f4af51435` on a scratch copy expecting any
      exception (so it imports nothing new): only the SQLAlchemy store's retry older
      than the skew fails there, answered `OutcomeUnknown` from the read (`DID NOT
      RAISE`); the `sqlite3` store already ordered it, and the SQLAlchemy claim met
      the lock. The scratch copy was deleted.
- [x] 5b.3 Verify the section: `make test-request-replay` (unit and library
      integration).
      End-to-end: none — nothing deployed uses it until section 16.
      `make test-request-replay`: mypy strict clean; 73 unit and 91
      library-integration tests passed. `make -C kit/authenticated-requests test`
      against the rebuilt wheel: 146 passed. End-to-end confirmed: none.

Notes (section 5b):

- For section 5c: catch `StoreUnavailable` from `RequestReplay.admit` for the 503;
  `complete` raises it too, which `AdmissionCore.finish` already logs and survives.
  A store wrapper in a test refuses a step by raising anything — the guard wraps it.
- The README's admission table, its stores section, the renewal module's docstring
  and its loss log now say a retry concludes the attempt before `OutcomeUnknown`, and
  that a handler holding its own SQLite database's write lock loses its lease but
  keeps the guarantee.
- For the round's review and the authority sections: the ordering holds on SQLite
  alone, where the concluding write waits for the database's one write lock. On
  PostgreSQL, which the stores and the DDL support and the registry may run, a
  handler's transaction on its own tables does not conflict with the replay row, so
  `OutcomeUnknown` may precede its commit. D7 states the guarantee for SQLite, but
  the delta's requirement ("Each route declares how an exact retry is resolved")
  says it without that scope; the docstrings and README here say SQLite. No
  authority runs a `RECORDED` route on PostgreSQL in this change's tests; whether the
  requirement is narrowed or PostgreSQL needs its own ordering is the owner's.
- `RequestReplay._step` maps every exception a store step raises to
  `StoreUnavailable`, a store's own defect included, as the delta's "a failure of the
  authority's replay store" reads; the caller retries the same request.
- Fixed from the fresh-context check: the ordering claims, stated for any database,
  now name SQLite; `OutcomeUnknown` after `conclude` required no concluded row
  (`Row.concluded` now); an unreachable re-raise in `_step` and a redundant
  `lease_until IS NOT NULL` were removed; the conclude/record race, a refused
  `record`, the chained cause in the refusal cases and a non-matching concluding
  write against a held lock were untested; the refusal cases ran at both levels
  though the adapter never reaches a store (now unit only, the adapter in
  `tests/support.py`); the ordering test left connections open and its comment
  misdescribed the `sqlite3` store's read; the renewal's loss log said a retry is
  told the outcome is unknown where SQLite's lock orders it. Declined: a
  `MagicMock(wraps=...)` in place of the adapters, which `testing-python.md` names
  for injected collaborators; the package's existing tests interleave and refuse
  steps through small adapters (`CompetingFirst`, `VanishingConflicts`), which
  `concurrency-tests.md` admits, and these follow them.
- A second fresh-context check found the second ordering test's claim and comment
  stated for both stores where only the SQLAlchemy store's concluding write meets the
  lock (reworded), the two branches after `conclude` reachable only across processes
  uncommented (each now names its case), and wording nits; fixed. It repeated the
  PostgreSQL scope and the broad `StoreUnavailable` mapping, both recorded above for
  the owner. The section's "Touches" line omits the README, `renewal.py`,
  `__init__.py` and `tests/unit/`, which it also changed.
- Fix from implementation review 71 F1 (triage of round 2): `conclude` took only the
  key, so a retry whose row expired between its read and its concluding write, its key
  then claimed by another request, was answered that request's recorded outcome, or
  told it was in progress. `ReplayStore.conclude` now takes the retry's `Entry`; both
  stores condition the concluding update on its hash and origin and answer `None` when
  the row under the key holds another request (`store.same_request`), and the guard
  rechecks the returned row, so the retry is `Expired`. The in-memory double and the
  README follow. Proven by three rule cases, each run on the in-memory double (unit)
  and both stores over real SQLite (library integration): a retry meeting a
  replacement recorded, and one still running, is `Expired` and leaves the
  replacement's row as it was; and `conclude` called directly once the replacement's
  own lease has ended answers `None` and leaves its row, proving the stores' condition
  apart from the guard. A unit case proves the guard's recheck against a store
  answering another request's row.
  Evidence: `make test-request-replay` — mypy strict clean; 77 unit and 97
  library-integration tests passed. `make -C kit/authenticated-requests test` against
  the rebuilt wheel: 199 passed (unit and library integration). `change-workflow run
  test-before` at `528a5a945` over `tests/rules.py`, `tests/support.py` and
  `tests/integration/test_store_rules.py`: 6 failed, 44 passed — the two retry cases
  on both stores on `admission == Expired()`, and the direct `conclude` case, whose
  signature is new; the unit cases cannot run there, the double's `conclude` taking
  the new signature. A scratch mutation confirmed each half alone is proven: without
  the guard's recheck the unit case fails, and without the stores' identity check the
  direct case fails on both stores. End-to-end: none — nothing deployed uses it until
  section 16.
  `change-workflow run pre-commit`: `after-functional-change at 528a5a945: passed,
  exit 0`; `pre-commit-functional at 528a5a945: passed, exit 0`; `pre-commit at
  528a5a945: passed, exit 0`.
  The fresh-context check found no correctness defect; it found that neither half of
  the fix was proven alone (the direct `conclude` case and the guard's unit case were
  added), the proposal's two statements of the order unscoped to SQLite, D7's opening
  sentence unscoped, the decision recorded inline rather than as a history paragraph,
  the `Expired` wording in the guard's docstring and the README conflating cases, the
  guard's recheck uncommented, and a blank line at the end of `tests/rules.py`; all
  fixed.
- The owner's direction in that triage: the delta requirement "Each route declares how
  an exact retry is resolved" is narrowed to promise the conclusion's order only where
  the replay store is on the authority's own SQLite database, PostgreSQL getting no
  such order; D7 records it. That settles the PostgreSQL scope recorded above.

## 5c. The admission core amended

Answers a failed admission with a signed 503, concludes an ended attempt through 5b, and
checks a targetless operation's absent resource. It also hands records to evidence
capture (D3, D7, D11, D13, D23; marketplace-identity "The replay store fails while a
request is admitted", "A retry arrives while the handler holds the authority's
database", "A recorded route's store refuses every renewal while its handler runs", "A
request for an operation with no target states a resource"). Touches
`kit/authenticated-requests/src/market_authenticated_requests/` (`core.py`, the two
forms, the route table and `RouteAdmission`) and its tests. The kit is new in this
change, so nothing is bumped.

- [x] 5c.1 Answer a replay-store failure to reserve, resolve or conclude a request with
      a signed 503 whose body code is `admission_unavailable`, on either route kind, with
      nothing dispatched. Keep the signed 500 for a route raising after admission alone
      (D3, D7). Verify by library integration tests in both forms and schemes, over both
      stores where the case names a store:
      - a reservation the store refuses answered the 503, not the 500;
      - a store refusing every renewal and then every write: the retry answered the 503,
        the loss logged at error naming the request, then the outcome recorded once the
        store accepts writes and a later retry receiving it;
      - a `RECORDED` handler holding the database's write lock past its lease: its retry
        not answered `exact_retry_outcome_unknown` before the handler commits, then a
        read showing the write and a replacement write not overwritten.

      `AdmissionCore.admit` catches the component's `StoreUnavailable` and answers a
      signed 503 `{"code": "admission_unavailable", "detail":
      ADMISSION_UNAVAILABLE_DETAIL}`, logged at error, nothing dispatched; a
      replay-store failure no longer reaches the 500. Library integration,
      `tests/integration/test_answers.py`, in both forms and schemes: a refused
      reservation answered the 503 on a `RECORDED` and a `RERUN` route, nothing
      dispatched, the failure logged at error naming the request; a store refusing
      every renewal, then every write while the test holds it closed — the retry
      after the lease answered the 503, the loss logged once at error naming the
      request, then, the store open again, the handler's outcome recorded and a
      later retry receiving it, one dispatch; and, over the `sqlite3` and the
      SQLAlchemy store each with no busy timeout and the renewal's waits never
      stepped, a `POST /hold` handler holding `BEGIN IMMEDIATE` and a write on the
      toy's database past its lease: its retry answered the 503, then after the
      handler commits answered 409 `exact_retry_outcome_unknown`, a read showing
      the write, a replacement set answered 200 and standing after the handler
      returns, and a later retry receiving the recorded outcome; passed. The last
      two each run with the retry within the skew, meeting the store at its claim,
      and older than it: then the closed store refuses the concluding write, and on
      the SQLAlchemy store the held lock meets the concluding write after a plain
      read, the case design review 61 F1 named — which step meets it was confirmed
      by hand from the logged tracebacks; the tests assert the answers, 503 then 409.
      Under the `sqlite3` store the older retry's read already takes the lock. The
      loss is asserted logged once over the whole attempt, its stop included. The
      existing renewal-loss test, renewal refused but writes accepted, still answers
      outcome-unknown: the case D7 names of a store unwritable for a whole lease,
      after which the retry concludes the attempt. A trust that raises while
      admitting is a signed 500 with nothing dispatched, in both forms (library
      integration); passed.
- [x] 5c.2 Let a route declare that its operation has no target (D2, D11). In either form,
      a request stating a resource for such a route, or stating none for a route with a
      target, is answered a signed 400 `operation_mismatch`. A targetless route's answers
      bind no resource. Verify by library integration tests in both forms: the delta's
      scenario, the reverse case, and a targetless request admitted and answered signed.
      `RouteBinding.resource` is `str | None`, `None` for an operation with no target
      (an empty string refused where it is declared); a `RouteAdmission` given no
      `resource=` declares no target; `fixed_resource` takes its value. `admit`
      compares the stated operation and resource with the route's, so either
      direction is an `operation_mismatch` whose body names `null` for the side with
      none. 5a's `or None` stopgap is gone. Library integration,
      `test_admission.py`, both forms and schemes: a resource stated for the
      targetless `POST /items` answered 400 with `bound.resource` `null`, nothing
      dispatched; none stated for `POST /items/{item}/set` answered 400 with
      `stated.resource` `null`; a targetless publish admitted and answered signed
      over a binding without the resource, its `Signature-Input` covering no
      `market-resource`; passed. Unit, `tests/unit/test_routes.py`: a binding of
      `""` and `fixed_resource("")` refused where they are declared, `None`
      accepted; passed. The toy's time route is now targetless; the "body holds
      no resource" and "fails before its admission" cases moved to `POST /claims`,
      whose resource is the body's `item`.
- [x] 5c.3 Hand records to evidence capture (D23):
      - the admission (`Admitted`) carries the verified request's record and body bytes,
        for a handler that keeps the request before it answers;
      - `SignedOutcome` carries the request's and the response's records with both
        bodies, in place of the response's raw headers.

      Verify by library integration tests in both forms: a dependency-form handler and a
      middleware-form handler each reading the admission's record; the hook's records
      verifying through `kit/identity`'s evidence verifiers with the authority's and the
      caller's principals.
      `AdmissionCore.verify` answers `Verified(request, body)`, which `admit`,
      `refuse_unserved` and `refuse_unbound` take; `Admitted` gains `record` and
      `body`; `SignedOutcome` is now `request`, `request_body`, `response`,
      `response_body` (the two records and bodies), its status in the response record.
      Library integration, both forms and schemes: `test_admission.py`, the publish
      handler keeping its `Admitted`, whose body is the bytes sent and whose record,
      from JSON, verifies through `verify_request_evidence` with the caller's
      principal, role, operation and no resource; `test_answers.py`, each hooked
      outcome's request record verifying with the caller's principal and its response
      record with the authority's, both bodies the bytes exchanged; passed.
- [x] 5c.4 Verify the section: `make -C kit/authenticated-requests test` (unit and
      library integration) against 5a's and 5b's builds; `make check-architecture`.
      End-to-end: none — no authority composes the core until section 6.
      `make -C kit/authenticated-requests test` against the rebuilt identity and
      replay wheels: 27 unit and 172 library-integration tests passed. `make
      check-architecture`: passed. End-to-end confirmed: none.

Notes (section 5c):

- Correction (plan amended again 2026-11-27): section 5e builds on 5c.2's targetless
  declaration for the public operation, which has no target (D24, D28).
- For sections 6–15: a route whose operation has a target passes `resource=`
  (`path_resource`, a body-derived `ResourceOf`, or `fixed_resource(value)`); one
  with none passes nothing, and a middleware-form table returns `resource=None`.
  A handler keeping the request reads `admitted.record` and `admitted.body`; a
  signed-outcome hook reads `outcome.request`/`request_body` and
  `outcome.response`/`response_body`, filtering by `outcome.request.operation`.
  A caller answered 503 `admission_unavailable` retries the same request.
- A body the route cannot bind (`ResourceUnbound`) applies only to a route with a
  target; a targetless route refuses a bad body in its handler.
- `change-workflow run test-before` at the round's base `f4af51435` shows nothing:
  that kit code predates 5a and fails against the new identity wheel on every test.
  At 5c's starting commit (`--at dc3dc1003`): `test_answers.py` fails at collection
  (`ADMISSION_UNAVAILABLE_DETAIL`); `test_admission.py` 24 failed, 66 passed — the
  new cases fail with 404, since the base's toy lacks `/items` and `/claims`,
  which shows less than a behavioural failure; the reverse mismatch case passes
  there, 5a having made an absent stated resource differ from a route's. 5b's
  test-before shows the ordering defect at the component.
- `AdmissionCore.admit` catches only `StoreUnavailable`, for the 503; any other
  error while admitting — the authority's trust or signer raising — reaches the
  wrapper, which answers it a signed 500 through `fail_unadmitted` in either form
  (the middleware form now catches it around `admit`, as the dependency form's
  wrapper already did).
- Fixed from the fresh-context check: every 503 case met the store at its claim, so
  none drove the concluding write through the core (now the older-than-skew
  variants); the hold test renewed on real time, so a slow run could renew after
  the commit (now a never-stepped sleep); the 503's log was unasserted;
  `fixed_resource("")` passed declaration (now refused there); the test-before note
  was wrong (now run, above); wrapping nits. A second check found the middleware
  form answering a non-store error while admitting unsigned (now a signed 500, with
  a test), the core's docstring saying a 500 means only a route raised, a test name
  describing a wait the test never makes, the loss's single log asserted before the
  renewal stopped, an unneeded yield, and a misnumbered D7 case; all fixed. The
  section's "Touches" line omits `__init__.py`, which it also changed.

## 5d. Query coverage and the public request in `kit/identity`

Covers `@query` in the profile, the request record and the request hash, and adds the
one query encoding and the public request builder (D2, D21, D24, D25, D28;
marketplace-identity "Body-bound authenticated request and response version", its
`@query` sentences and "A read's query is changed in transit"; "A signed message
retained as evidence verifies offline as a record"; "A public operation is answered
signed without request authentication"). Touches `kit/identity/src/market_identity/`
(`http_profile.py`, `records.py`, `wire.py`, `evidence.py`, `fixtures/`,
`__init__.py`) and its unit tests. `arkhai-kit-identity` is already at 0.6.0 against
`dev` (2.6), so nothing is bumped. `kit/authenticated-requests`' suite must still pass
against this build: a verification given no query reads `?` until 5e passes the raw
one.

- [x] 5d.1 Cover `@query` (D2, D25). `sign_market_request` takes the request's encoded
      query string and signs it as `@query`, the string with its leading `?`, or `?`
      alone where there is none. It sits second in both request coverage lists, after
      `@method`, and the delivery shape (D10a) covers it too. `verify_market_request`
      takes the raw query string the authority received and verifies against it,
      never a re-encoding. `VerifiedRequest.request_hash` frames the query. The response
      coverage is unchanged. Verify by unit tests, `test_http_profile.py`:
      - a request signed for `?limit=50&offset=0&status=open` verifies against that
        raw string;
      - the same request verified against `?limit=50&offset=0&status=closed` fails as
        an invalid proof (the delta's "A read's query is changed in transit");
      - a request with no query covers `?`, and verifies with no query or an empty one;
      - a query signed with `%20` fails against the same query spelled with `+`;
      - two requests differing only in their query have different request hashes;
      - 2.1's interoperability oracle, `http-message-signatures`, agrees on a base
        covering `@query`;
      - a delivery covering `@target-uri` covers its query too.

      `sign_market_request` and `verify_market_request` take `query`, the target's
      query suffix: empty for none, else `?` and the query, as `encode_query` builds
      it; the authority passes `?` and the raw received query. `""` and `?` both cover
      `?`. A suffix not starting with `?` is a `ValueError`; a received query outside
      RFC 3986's grammar is `malformed_envelope` (the library parses every URL to it).
      A delivery's query is its target URI's, so passing both is a `ValueError`.
      `VerifiedRequest.query` is the covered value; `request_hash` frames the query's
      SHA-256, since `frame_fields` caps a field at 4096 bytes. The published vectors
      `tests/unit/vectors/market_v3.json` were regenerated (request vectors changed,
      response vectors byte-identical, asserted while regenerating) and gained a
      `query_request_headers` vector for `GET ?limit=50&offset=0&status=open`. Unit,
      `test_http_profile.py`, both schemes: each listed case, plus the query vector
      byte-identical, an uncovered `@query` malformed, a query longer than a framed
      field still hashing, suffixes outside the grammar refused for signing; passed.
- [x] 5d.2 Carry `query` in the request record (D21, D25). `RequestRecord.query` is
      required, `?` where the request had no query. Its wire name is `RecordField`'s,
      and the evidence verifier rebuilds the signature base with it. A version 2 record
      is unaffected. Regenerate 5a.7's producer fixture with a request carrying a query.
      Verify by unit tests, `test_records.py`, `test_evidence.py`, `test_wire.py`,
      `test_fixtures.py`:
      - a record round trip under both schemes, with a non-empty query and with `?`;
      - a record whose query is altered refused by the request evidence verifier;
      - a publish record with `query` `?` verifying;
      - the version 2 evidence vectors still verifying;
      - the record's fields held to `RecordField`.

      `RecordField.QUERY` sits after `method`, so a record serializes in the
      design's order (`protocol`, `principal`, `role`, `method`, `query`, …).
      `RequestRecord.query` is required and only a covered value (`?…`, never `""`).
      `market_identity.fixtures.messages.build_signed_request` takes `query`, which
      `FixtureRequest.query` carries for the consumer to append to its path, and
      `READ_QUERY` gives a read's query; `validate_response_record` refuses `query`.
      Unit, both schemes: `test_records.py`, a round trip with a query and with
      none, its JSON order, an empty, unprefixed, spaced or bad-escape query refused,
      a missing query refused; `test_evidence.py`, a publish record's query `?` and
      it verifying, an altered query among the altered fields, a queried record
      verifying and failing as `invalid_proof` once its query is altered, the version
      2 vectors unchanged and verifying; `test_wire.py`, the fields held to
      `RecordField`; `test_fixtures.py`, every fixture request with and without a
      query verifying live and as evidence; passed.
- [x] 5d.3 Add the one query encoding (D25). One `kit/identity` function encodes an
      ordered sequence of query items into the exact string a typed client signs and
      sends: RFC 3986 percent-encoding with spaces as `%20`, repeated keys kept in their
      given order, with the leading `?` added only for a non-empty query. Typed clients
      build both the signed value and the request URL from it, never through `httpx`'s
      `params=`. Verify by unit tests:
      - the encoding is deterministic for a given item sequence;
      - repeated keys and reserved characters encode as stated;
      - a URL built from the encoded string and sent through `httpx`'s mock transport
        arrives with a byte-identical query, so the authority verifies what was signed.

      `encode_query(items)` in `http_profile.py`: `urllib.parse.quote(…, safe="")`
      on each key and value, so only unreserved characters stay literal. It takes
      `(str, str)` pairs; a typed client converts its integers. `httpx` joins
      `kit/identity`'s dev group for the transport test (relocked). Unit,
      `test_http_profile.py`: deterministic and empty for no items; repeated keys,
      reserved characters, `+`, `~` and non-ASCII as stated; a URL sent through
      `httpx.MockTransport` arriving with the signed query and verifying; passed.
- [x] 5d.4 Add the public request builder and the public-shape check (D24, D28). The
      builder takes the method and operation, a targetless operation stating no resource,
      and returns the headers — `Market-Operation` and a fresh 128-bit
      `Market-Request-ID`, nothing else the profile adds — with the `RequestBinding`
      its answer is verified against through `verify_market_response`. The check tells an
      authority whether a request is public-shaped: it states a request identity and
      carries no `Signature` or `Signature-Input` field. Verify by unit tests:
      - the builder's headers carry no `Signature`, `Signature-Input`, `Market-Audience`,
        `Market-Request-Origin` or `Content-Digest`, and two builds differ in their
        request ID;
      - a response signed over the binding verifies, and one signed over another
        request ID fails (registry-discovery "A replayed descriptor is offered to a
        bootstrap", at its unit);
      - the check holds for the builder's request and fails for a signed one, or for one
        missing `Market-Operation` or `Market-Request-ID`.

      `build_public_request(method=, operation=)` answers `PublicRequest(headers,
      binding)`, its request ID `secrets.token_hex(16)`; `is_public_request(headers)`
      reads the fields case-insensitively and checks presence only: whether the stated
      values can be signed over is `stated_request_binding`'s, as for every refusal.
      Unit, `test_http_profile.py`: each listed case, the binding equal to what
      `stated_request_binding` reads from the headers, the check holding for
      lower-cased names and failing for either signature field alone; passed.
- [x] 5d.5 Verify the section: `make -C kit/identity test` (unit); `make -C
      kit/authenticated-requests test` against this build, still passing; `make
      check-architecture`.
      End-to-end: none — no authority composes the core until section 6.
      `make -C kit/identity test`: 538 passed (unit). `make -C
      kit/authenticated-requests test` against the rebuilt identity wheel: 199 passed
      (unit and library integration), its verification covering `?`. `make
      check-architecture`: passed. End-to-end confirmed: none.

Notes (section 5d):

- Corrected by implementation review 92 F1 (triage of round 3, recorded in 5e's
  notes): 5d.4's check tested only the signature fields, short of the delta's public
  request; `is_public_request` is now the strict shape, and the fallback's rule is
  `carries_signature_fields`.
- For 5e and sections 6–15: an authority passes `query="?" + raw` where the ASGI
  `query_string` is non-empty, else nothing; a typed client signs and sends
  `encode_query(items)` appended to its path, never `params=`. The public request's
  answer verifies through `verify_market_response(request=public.binding, …)`.
- `change-workflow run test-before` for `test_evidence.py` at the round's base
  (`2744f8d1c`): 34 failed, 24 passed — the base's `sign_market_request` takes no
  `query`, so every case signing through the helper fails with a `TypeError`, which
  shows the API is new more than a behavioural failure. `test_http_profile.py` fails
  there at collection, importing `encode_query`.
- `query` defaults to `""` on signing and verifying, so the core's suite passes until
  5e hands it the raw query. An authority verifying outside the core with no query
  would cover `?` while its URL carries one; every authority verifies through the
  core (D3), which passes it from 5e.
- Fixed from the fresh-context check: the received-query grammar check was tested
  only with a character the library refuses anyway (now also a `#`, which a URL
  parser would read as a fragment, covering less than the verified request states);
  docstring wrapping; `_UNCOVERED_TARGET` renamed `_PLACEHOLDER_URL`, since its query
  is covered; the fixture's usage example now imports `READ_QUERY` and sends a GET;
  the change index row's "Planning next" sentence, stale since the re-plan. Declined:
  making the fixture sign a query by default — consumers opt in with `query=`, and
  the default request, a POST reservation, has none.

## 5e. The admission core: raw query, public operations and unmatched public requests

Hands the raw query to verification, adds the public route mark and answers unmatched
public requests signed (D3, D11, D24, D25; design review 85 F1; marketplace-identity "A
public operation is answered signed without request authentication" and its four
scenarios, "Each route declares how an exact retry is resolved", its inventory sentence,
and "Body-bound authenticated request and response version", the authority verifying
the raw query). Touches `kit/authenticated-requests/src/market_authenticated_requests/`
(`core.py`, `application.py`, `dependency.py`, `routes.py`, `inventory.py`,
`__init__.py`) and its tests. The kit is new in this change, so nothing is bumped.

- [x] 5e.1 Hand the raw query to verification in both forms (D25). Each form reads the
      ASGI scope's `query_string` and passes it, decoded as received, to
      `verify_market_request`; the reservation keys on 5d.1's request hash. Verify by
      library integration tests in both forms and schemes:
      - a read whose query was altered after signing refused as an invalid proof, signed
        over its stated identity, nothing dispatched;
      - an exact retry with the same query resolved as its route declares;
      - a request ID reused with a changed query refused as changed reuse.

      `received_query(scope)` (`application.py`) answers `?` and the
      `query_string` decoded as Latin-1, so a byte no query may hold fails as
      malformed, or `""`; `AdmissionCore.verify` now requires `query=`, which the
      wrapper and `RouteAdmission` pass, and which the unmatched-request fallback
      passes too. Library integration, `test_admission.py`, both forms and schemes:
      a read and a re-run write whose query was changed after signing each a signed
      401 `Invalid request proof` bound over the route, nothing dispatched, and the
      same read with its signed query then served (before this the core covered `?`
      for every request, so that read would have been refused too); a recorded and a
      re-run route's exact retries with the same query answered the recorded outcome
      and re-run told it is a retry; a request ID reused with a changed query, or
      none, a signed 409 changed reuse; a raw `\xe9` query byte, sent through the
      application's ASGI scope since an HTTP client percent-encodes it, a signed 401
      `Malformed request proof` bound over the route; passed.
- [x] 5e.2 Add the public route mark (D3, D24). A route admission declares a public
      operation: its operation, and no target. The core answers its request with the
      version 3 response signed over the stated binding, through the route's handler, and
      reserves nothing. A request to it carrying signature fields is refused as
      malformed, signed over its stated identity. One stating another operation, or a
      resource, is answered `operation_mismatch`. The route inventory accepts the public
      mark beside a declaration and the unauthenticated mark. Verify by library
      integration tests in both forms (marketplace-identity "A client reads a public
      operation knowing no principal", "A public operation's request is signed"):
      - a public read answered 200 signed, verifying through 5d.4's binding, with no
        replay row written;
      - a signed request to it refused as malformed;
      - another operation, or a stated resource, answered `operation_mismatch`.

      Add a unit test, `test_inventory.py`: a public-marked route passes the inventory,
      and a route with no mark still fails it naming the route.

      The mark is `PublicBinding(operation)` (`routes.py`), which a middleware-form
      table's `resolve` returns and its `declares` covers, and
      `PublicAdmission(core, operation=)` (`dependency.py`) in the dependency form;
      the handler receives `PublicAdmitted(binding)`. `AdmissionCore.admit_public`
      refuses a request carrying `Signature` or `Signature-Input` with a 400 signed
      over its stated identity, answers `operation_mismatch` signed over the route's
      operation and the stated request ID, and answers a request stating no request
      identity unsigned; `finish_public` signs the handler's answer over the
      binding, `fail_public` a 500, and neither reserves, records, nor calls the
      signed-outcome hook, which carries a verified request's record. Library
      integration, `test_public.py`, both forms and schemes: the public read 200,
      verifying through 5d.4's binding and not another's, no replay row and no hooked
      outcome; a signed request, and one carrying either signature field alone,
      refused 400 signed; another operation and a stated resource each a signed
      `operation_mismatch`; no identity unsigned; a raising public handler a signed
      500 whose log holds the error. The caller's scheme varies only the signed
      request's case: a public request carries no caller signature, and the toy
      authority signs under Ed25519. Unit: `test_inventory.py`, a public route
      passing the inventory in either form, a route with no mark beside it still
      refusing startup naming it, a public route outside the core's wrapper refusing
      to serve; `test_routes.py`, an empty public operation refused; passed.
- [x] 5e.3 Answer unmatched public requests (D3, D11, design review 85 F1). The fallback
      answers an unmatched request that states a request identity and carries no
      signature field with the signed 404, or 405 with `Allow`, `operation_not_served`,
      over its stated identity and unverified. One carrying signature fields is verified
      first, as now. Verify by library integration tests in both forms
      (marketplace-identity "A public request names a path no route serves", "A public
      request uses a method its path does not serve"):
      - a public-shaped request on a mistyped path answered a signed 404;
      - a public-shaped POST to a GET-only public path answered a signed 405 with
        `Allow: GET`;
      - a signed request under an unknown profile tag on an unmatched path still
        answered `unsupported_protocol` (D16);
      - a forged signature on an unmatched path still refused as an invalid proof.

      The wrapper's `_refuse_unserved`, which both forms' unmatched paths reach,
      answers a request whose identity `stated_request_binding` reads and which
      `is_public_request` holds through `AdmissionCore.refuse_unserved_public`,
      unverified; any other is verified first, as before. Library integration,
      `test_public.py`, both forms: each listed case, every answer verifying over the
      stated identity; the caller's scheme varies the unknown-profile and forged
      cases alone; passed.
- [x] 5e.4 Verify the section: `make -C kit/authenticated-requests test` (unit and
      library integration) against 5d's build; `make check-architecture`.
      End-to-end: none — no authority composes the core until section 6.
      `make -C kit/authenticated-requests test` against 5d's rebuilt identity wheel:
      31 unit and 224 library-integration tests passed. `make check-architecture`:
      passed. End-to-end confirmed: none.

Notes (section 5e):

- For sections 6–15: a middleware-form table returns `PublicBinding(operation)` for
  a public route and declares it; a dependency-form route takes
  `Depends(PublicAdmission(core, operation=...))`. The registry's descriptor read
  is the only public operation (D24). A handler wanting the query reads it from the
  framework as usual; only verification needs it raw, which the core reads itself.
- `change-workflow run test-before` copies only the named file into the earlier
  commit, and 5e's tests rest on `support.py`'s new public route and query
  parameter, so it would show only their absence: not run.
- `verify_market_request`'s `query` stays optional (5d's notes): the core now
  always passes it, and the evidence verifier passes the record's.
- Fixed from the fresh-context check: two docstrings left unwrapped, one
  ungrammatical, and `routes.py`'s not naming `PublicAdmission`; the public
  binding's test moved to `test_routes.py`; `PublicAdmission`'s missing-wrapper
  guard untested (now tested); `received_query` exported with no consumer (no longer
  exported); the 404/405 body and the unsigned 400 built twice (now one helper, and
  `answer(None, …)`); the claims of both schemes for public cases, and of a
  malformed query byte through the core, overstated (now reworded, and the byte
  tested); the stated-resource mismatch's code unasserted (now asserted).
- Fix from implementation review 92 F1 (triage of round 3): one predicate,
  `is_public_request`, served both the public route and the unmatched fallback, and
  checked only that `Signature` and `Signature-Input` were absent, as 5d.4 planned,
  so a descriptor request carrying `Market-Audience`, `Market-Request-Origin` or
  `Content-Digest` without a signature was dispatched and answered 200, though the
  delta's public request carries none of them. `is_public_request` is now that
  shape, the builder's: both identity fields and none of the five a signed request
  carries; `admit_public` refuses any other request stating an identity with the
  signed 400, its detail naming the five. The unmatched fallback keeps the delta's
  broader rule through the new `carries_signature_fields` (`kit/identity`): an
  identity stated and no signature field, whatever else it carries, is answered the
  signed 404/405 unverified, so review 85 F1's disposition stands. Docstrings of the
  profile, `PublicBinding`, `PublicAdmission` and the fallback follow. Unit,
  `test_http_profile.py`: each of the five fields, in either case, defeats the public
  shape, and only the two signature fields set `carries_signature_fields`. Library
  integration, `test_public.py`, both forms and schemes: audience, origin and digest
  each sent unsigned to the descriptor is a signed 400 bound over the stated
  identity, the handler not answering and no replay row; each on a mistyped path is
  still the signed 404, no replay row.
  Evidence: `make -C kit/identity test`: 545 passed (unit). `make -C
  kit/authenticated-requests test` against the rebuilt identity wheel: 279 passed
  (31 unit, 248 library integration). `make check-architecture`: passed.
  `change-workflow run test-before --at 38ba2876a` (`TEST_BEFORE_DIST=dist-identity`)
  over `test_public.py`: 16 failed, 44 passed — the twelve matched-route cases
  answered 200, and the signed-request case's four on the detail now naming five
  fields; the mistyped-path cases pass there, as the fallback was already this broad.
  Over `test_http_profile.py`: a collection error, `carries_signature_fields` being
  new. End-to-end: none — no authority composes the core until section 6.
  The fresh-context check found no correctness defect. Fixed from it: the profile's
  module docstring, `PublicBinding`'s and `PublicAdmission`'s, and the test module's
  heading still describing the signature-only shape; `_SIGNED_ONLY` moved beside
  the module's other constants with a `#` comment; the origin test value given its
  wire form, integer seconds; a repeated signature-field assertion folded; the
  mistyped-path cases now assert no replay row. Declined: exporting the refusal's
  detail as the neighbouring `ROUTE_FAILURE_DETAIL` is, which would add to the kit's
  interface for a test's literal; a 405 case with an extra field, which runs the
  404's code.
  `change-workflow run pre-commit` (local validation of tree `844658931`): `after-functional-change
  at 38ba2876a: passed, exit 0`; `pre-commit-functional at 38ba2876a: passed, exit
  0`; `pre-commit at 38ba2876a: passed, exit 0`.

## 6. The registry on the admission core

*Replanned 2026-11-27 against the reviewed design:* 6.1–6.6 were superseded before any
was started; the section stopped at 6.1, as its notes record. *Replanned again
2026-11-27* (D24–D28, design review 85): the section stopped a second time before 6.1,
and its tasks were replaced; none had started.

Moves the registry onto the core in the dependency form, with its typed client. Keeps
its publication evidence as records, serves its descriptor as a public read, signs its
query values, and answers late rotation retries (D3, D5, D6, D7, D9, D21, D23, D24, D25,
D26, D27, D28). Requirements: registry-discovery "Durable replay reservation", "Seller
publication evidence is independently verifiable", "Body-bound registry
authentication", "Filter-spec consistency", "Resource query compilation preserves
filter-spec authority", "Publisher principal rotation", "Registry self-description is
authority-authenticated"; marketplace-identity "A public operation is answered signed
without request authentication". Touches:
- `core/registry/src/core_registry/api/`: `publisher_auth.py` and every route calling
  it, `listing_routes.py`, `publisher_routes.py`, `descriptor_routes.py`,
  `filter_spec.py`, `system_routes.py`, `utils.py`, `validate_routes.py`, and
  `main.py`'s unsigned-error path;
- `core/registry/src/core_registry/`: `db/models.py`, a new Alembic revision under
  `alembic/versions/`, the migrate command, `config.py`;
- the registry chart's values and schema;
- `core/registry-client/src/registry_client/`: `auth.py`, `client.py`, `models.py`,
  `query.py`;
- `core/buyer/src/core_buyer/orchestrator.py`, where it passes the ETag;
- the VM storefront's `tests/unit/test_registry_client_contract.py`, which doubles
  the registry's wire against the installed client;
- `kit/authenticated-requests`, where its `trust` becomes a protocol (the notes'
  choices).

- [x] 6.1 Classify every authenticated registry route against D6's criterion and declare
      it, naming whether each operation has a target. Record the table in this task's
      note.
      - Listing publish, update and delete are `RECORDED`.
      - Publish, the listing and publisher collection reads, validate, the filter spec,
        health and stats have no target (D28).
      - The descriptor read is public (D24).
      - Identity rotation and retirement are `RERUN`, keyed by the rotation's nonce
        (D6, D27). Every other read follows the criterion.

      A route whose classification differs from the design's table, or a `RECORDED` route
      whose caller could not learn by reading whether its write applied, stops the
      section: it is a design question, and the change returns to design (D6, D7). The
      table names any `RECORDED` route holding a write transaction near the lease period
      or writing in more than one transaction (the plan's preamble).

      *Done:* every route is declared in the dependency form, in
      `core/registry/src/core_registry/api/` beside its handler; the inventory at
      `install` refuses any route with no declaration or mark, and the registry starts.

      | Operation | Route | Exact retry | Target | Roles |
      |---|---|---|---|---|
      | `listing.publish` | `POST /listings` | `RECORDED` | none | seller |
      | `listing.list` | `GET /listings` | `RERUN` | none | buyer, seller, service |
      | `listing.get` | `GET /listings/{listing_id}` | `RERUN` | the listing | buyer, seller, service |
      | `listing.update` | `PUT /listings/{listing_id}` | `RECORDED` | the listing | seller |
      | `listing.delete` | `DELETE /listings/{listing_id}` | `RECORDED` | the listing | seller |
      | `listing.validate` | `POST /api/v1/listings/validate-publish` | `RERUN` | none | buyer, seller, service |
      | `filter.get` | `GET /filter-spec` | `RERUN` | none | buyer, seller, service |
      | `health.read` | `GET /api/v1/system/health` | `RERUN` | none | buyer, seller, service |
      | `system.stats.read` | `GET /api/v1/system/stats` | `RERUN` | none | buyer, seller, service |
      | `publisher.list` | `GET /publishers` | `RERUN` | none | buyer, seller, service |
      | `publisher.get` | `GET /publishers/{publisher_id}` | `RERUN` | the publisher | buyer, seller, service |
      | `publisher.identity.rotate` | `POST /publishers/{publisher_id}/identity-rotations` | `RERUN`, keyed by nonce | the publisher | seller |
      | `publisher.identity.rotation.read` | `GET /publishers/{publisher_id}/identity-rotations/{nonce}` | `RERUN` | `<publisher>:<nonce>` | buyer, seller, service |
      | `publisher.identity.retire` | `POST …/identity-rotations/{nonce}/retire` | `RERUN`, keyed by nonce | `<publisher>:<nonce>` | seller |
      | `registry.descriptor.read` | `GET /.well-known/arkhai/registry-descriptor.json` | public | none | none |

      Unauthenticated: `/health`, the OpenAPI document, and the administrator routes
      (`/admin/api-keys`, `/admin/api-keys/{key_id}`, `/admin/status`, `/admin/time`),
      which take the shared administrator key, not a signature. Matches D6's table.
      `listing.validate` writes nothing, so it is a read for D6 and needs no outcome;
      as a non-GET `RERUN` route it still has a double-dispatch case (6.7). Each
      `RECORDED` route (publish, update, delete) writes in one transaction, committed
      once at its end, and holds no write transaction near the 30 s lease: no route
      calls another service, and a refusal before the commit rolls back with the
      request's session. Each caller learns by reading whether its write applied
      (`listing.get`). No difference from the design.
- [x] 6.2 Authenticate every route through the core's dependency form. Its store is bound
      to the registry's database through the SQLAlchemy store, on an engine of its own
      (the notes' choices). Its trust admits any verified principal, the routes checking
      ownership, so the kit's `trust` parameter becomes a protocol. Remove
      `publisher_auth.py`'s own reservation, caching and completion. Verify by
      application integration tests through the typed client (registry-discovery
      scenarios):
      - a delayed retry of a publish after a later update answered with the recorded
        outcome, the update kept;
      - a delete retried after the listing was republished answered with the recorded
        outcome, the republished listing kept;
      - an unmatched path answered signed;
      - a request stating a resource on publish refused `operation_mismatch`.

      Re-run `kit/authenticated-requests`' suite for the trust protocol.

      *Done:* `core_registry/api/admission.py` builds `registry_core` as the routes
      import; startup binds its signer and a `SqlAlchemyReplayStore` over an engine of
      its own on the registry's database (`admission.bind`), and the lifespan runs
      `registry_core.sweeping()`. `main.py` serves `app = install(api, registry_core,
      unauthenticated=…)`, the FastAPI application being `api`; its unsigned-error
      handler is gone, so every answer naming a request is signed by the core.
      `publisher_auth.py` is removed (`git rm`). The kit's `trust` is a `Trust`
      protocol of `allows` (`kit/authenticated-requests/…/core.py`), and the
      registry's admits any verified principal. Application integration
      (`core/registry/tests/integration/test_identity_publish.py`, through the typed
      client; raw requests only on the rejection paths): a delayed publish retry after
      a later update answered with the recorded 201, the listing still `closed`; a
      delete retried after a republication, its recorded 204 row held and the
      republished listing kept; `/listingz` answered a 404 signed over the operation
      it stated; a publish stating `Market-Resource` refused 400, signed over the
      route's operation with no resource, nothing written; plus a recorded refusal
      (404) and a recorded signed 500 whose retry is not dispatched (the route's
      collaborator replaced in the module to raise, as the earlier lease test did:
      the registry's routes inject no collaborator to double). The rejection-path
      tests assert the status and the signature only, as `integration-tests.md`
      asks. Library integration in the
      kit: a trust rule admitting a principal no set lists
      (`test_admission.py::test_a_trust_rule_admits_a_principal_no_configured_set_lists`).
      `make -C kit/authenticated-requests test`: 283 passed.
- [x] 6.3 Keep publication evidence as records (D21, D23). Publish and update store the
      seller's request record and body from the admission as `publication`, and in
      `updates` per changed field. The listing read returns both. A row retained under
      version 2 is returned as stored. `publication`, `updates`, `publisher_publication`
      and `publisher_updates` join the reserved listing fields, refused by name at
      publication (design review 61 F2). Verify by application integration tests through
      the typed client (registry-discovery "A consumer verifies a listing's commercial
      term", "A seller publishes a term named like the evidence", "A listing published
      before the cutover is read", "A seller changes status or oracle after
      publication"):
      - a publication's record, its `query` `?`, verifying through `kit/identity`'s
        request evidence verifier with the listing's publisher principals;
      - a seller term named `publication` refused by name;
      - a listing migrated from a 0.4.0 database read with its version 2 evidence intact;
      - an update adding its entry under `updates`, the publication unchanged.

      *Done:* publish and update keep `{"body_base64", "request": <record>}` from the
      admission (`listing_routes.publication_evidence`), as `publication` and per field
      in `updates`; `RESERVED_LISTING_FIELDS` holds all four names. Application
      integration (`test_retained_publications.py`, typed client): the publication's
      record, its `query` `?`, validated by `validate_request_record` and verified by
      `verify_request_evidence` with the listing's `publisher_principals`, a forged
      body refused (`invalid_proof`: the verifier computes the digest from the body,
      so the proof fails rather than a separate digest check); an update's record
      naming its listing; each of the four names refused by name at publication; a
      row whose evidence is a version 2 envelope read as stored (inserted as the
      migration leaves it, the migration itself proven in 6.4); an update adding its
      `updates` entry with the publication unchanged (the existing evidence test).
- [x] 6.4 Add the Alembic revision, refusing to downgrade, as the evidence columns'
      revision does. It creates the replay table from 4.7's DDL, renames the evidence
      columns to `publication` and `updates`, and drops `publisher_replay_reservations`
      (D9, D21). The registry's migrate command runs `VACUUM` on SQLite after an upgrade
      that applied the drop, outside any transaction, and only then (D9). Verify by the
      registry's migration tests:
      - from its v0.3.0 baseline;
      - from a database holding the 0.4.0 table with rows and version 2 evidence: the
        file compacted, the evidence carried under the new names;
      - a rerun not compacting.

      *Done:* `alembic/versions/20261127_001_registry_replay_table.py` creates the
      replay table from `replay_table_statements(dialect)`, renames the two columns
      with `ALTER TABLE … RENAME COLUMN`, drops `publisher_replay_reservations`, and on
      SQLite marks the header's `user_version` owed a compaction, as
      `kit/schema-migrations` marks its chains'; `migrate_database` then runs `VACUUM`
      outside any transaction and clears the mark (`db/migrations.py`,
      `_compact_if_owed`); a failing `VACUUM` raises `CompactionFailed` and leaves the
      mark, which no test here forces (it needs a held lock waiting out SQLite's busy
      timeout; the kit's engine proves the same order for the other chains);
      `registry-migrate` logs the compaction. Library integration
      (`test_migrations.py`): the floor fixture adopted through both later revisions,
      equal to a fresh chain; a 0.4.0 database, built from the floor fixture's DDL
      and brought to the 0.4.0 revision, with 2,000 replay rows and version 2
      evidence, compacted to under a quarter of its size, the evidence carried under
      the new names, the table gone and the snapshot equal to a fresh chain's; a rerun
      changing no byte and compacting nothing; `--check` naming the revision and
      dropping and compacting nothing (deployment-state "An operator previews the
      upgrade"); the command reporting the compaction. 23 passed.
- [x] 6.5 Serve the descriptor as a public read, and rebuild the bootstrap on it (D24,
      design review 85 F2). The route carries 5e.2's public mark.
      `bootstrap_registry_descriptor`, async and sync:
      - drops `signer` and `caller_role` and gains `allow_insecure_http`;
      - refuses a URL whose scheme is not `https`, before sending, unless opted in;
      - sends 5d.4's public request;
      - verifies the signed answer's binding and its signer against the descriptor's
        principals;
      - refuses a descriptor whose base URL is not the URL it bootstrapped from.

      `get_registry_descriptor` sends the same public request and verifies against the
      configured registries. Verify by application integration tests through the typed
      client:
      - registry-discovery "Client inspects a public registry", "Registry reads require a
        key", "Descriptor is used as a trust bootstrap" and "A descriptor claims another
        base URL";
      - "A replayed descriptor is offered to a bootstrap", by a transport that returns
        another request's signed answer;
      - marketplace-identity's public-operation scenarios through the registry's
        application: a key-less read, a signed request refused as malformed, a mistyped
        descriptor path answered a signed 404, a POST answered a signed 405 with
        `Allow: GET`.

      Add unit tests: "A bootstrap is given a plain-HTTP URL" refused naming the scheme,
      no request sent (a transport that fails if called); the async and sync signatures
      equal.

      *Done:* `descriptor_routes.py` takes `PublicAdmission(registry_core,
      operation="registry.descriptor.read")` and reads no key. Both bootstraps drop
      `signer` and `caller_role`, take `allow_insecure_http`, refuse a scheme other
      than `https` before sending, send `build_public_request`, verify the answer's
      binding and signer against the descriptor's principals, and refuse a descriptor
      whose base URL is not the one bootstrapped from; `get_registry_descriptor()`
      sends the same request and verifies against the configured registries
      (`registry_client/client.py`). Application integration
      (`test_registry_descriptor.py`): the typed read; both bootstraps; a signer
      outside the descriptor refused, a descriptor naming another base URL refused,
      and another request's signed answer, replayed by a transport, refused as
      `invalid_proof` (each through the async client); the descriptor read without
      the read key a gated registry requires (the read gate set, the filter-spec read
      refused 401 beside it); a key-less client reading it twice through the typed
      client, which verifies each answer, the replay table empty; a request carrying
      signature fields refused 400, signed over its stated identity; a mistyped path
      and a POST answered 404 and 405 `Allow: GET`, each signed over the stated
      identity. Unit (`core/registry-client/tests/test_auth.py`): `http` and `ftp`
      URLs refused naming the scheme through a transport that fails if called (the
      sync client), `http` by the async one. The signature parity test is a unit test
      in the registry's suite (`tests/unit/test_client_parity.py`), moved there from
      the integration tests.
- [x] 6.6 Sign the registry's query values and move the filter-spec ETag (D25, D26, D28).
      - Remove `canonical_query_body` and the client's `_query_body`. Every read's query
        travels as its query, built through 5d.3's encoding.
      - `listing.list` reads the `filter_spec_etag` parameter, 412 on a stale value, and
        refuses an `If-Match` header as malformed, naming it.
      - `list_listings(etag=…)` sends the parameter, and the query compiler and
        `core_buyer`'s orchestrator keep passing the ETag.
      - The filter-spec route's documentation names the parameter.

      Verify by application integration tests through the typed client:
      - registry-discovery "Cached filter spec is stale", "A listing query sends the
        ETag as `If-Match`" and "Filter specification changes during query
        construction";
      - a listing read whose query an intermediary changed, by a transport rewriting
        the URL, refused as an invalid proof.

      *Done:* `canonical_query_body` and `_query_body` are gone; the client builds every
      query with `encode_query` and sends exactly the signed suffix
      (`registry_client/auth.py`, `sign_registry_request`). `listing.list` reads
      `filter_spec_etag` (412 when stale) and refuses `If-Match` with a 400 naming it;
      the compiler reserves the parameter's name; `core_buyer`'s orchestrator passes
      the ETag unchanged (`etag=`), so it needed no edit, only its exact client pin.
      Application integration: a stale ETag refused 412 naming the current one and the
      current one passing (`test_listings_filtering.py`, typed client); `If-Match`
      refused naming it (raw, rejection path); a query compiled under a replaced spec
      refused 412, and a read whose `limit` a rewriting transport changed refused 401
      (`test_filter_spec.py`). Unit (`core/registry-client/tests/test_query.py`): both
      clients send `filter_spec_etag`, and no `If-Match`, through a signed mock
      registry; the ETag tests no longer patch the clients' private `_request`.
- [x] 6.7 Answer an applied rotation or retirement first (D27). Rotation answers an
      applied intent with the same nonce and intent hash, to the principal it names,
      before its proof-expiry, primary and overlap checks. Retirement answers an already
      retired rotation, to its replacement, before its primary check. Verify by
      application integration tests through the typed client (registry-discovery "A
      rotation is retried after its intent expired", "A retirement is retried after a
      later rotation", "Rotation is retried"). Each route's double-dispatch case sends
      its retry after the intent's expiry and after a later write, and the completeness
      test covers both.

      *Done:* rotation answers an existing rotation with the same nonce and intent
      hash, after the caller is checked as the intent's current principal and before
      the overlap bound, the proofs' expiry and the primary and overlap checks;
      retirement answers a retired rotation, to its replacement, before the primary
      check (`publisher_routes.py`). Application integration
      (`test_publisher_rotation.py`, typed client, through
      `request_replay.harness.run_double_dispatch`): a rotation's exact retry after a
      later rotation and past its intent's expiry, and a retirement's after a later
      rotation, each changing no table but the replay table and answering what the
      rotation read answers; the existing idempotent-rotation test ("Rotation is
      retried"); `listing.validate`'s case; and the completeness test, reading the
      non-GET `RERUN` routes from the application's route table. An exact retry
      re-sends the same signed intent by passing the first attempt's nonce and
      expiry, both schemes signing deterministically. `change-workflow run
      test-before` on the file: fails at the base at collection, since it imports what
      the change adds (`RouteAdmission`, `request_replay.harness`); that shows the
      cases cannot run before the change, not that the reordered checks fail there.
- [x] 6.8 Move `core/registry-client` to version 3 signing and response verification,
      sending its expected-authority set as the audience, and reading `publication` and
      `updates` in `ListingSummary`. Move the VM storefront's
      `tests/unit/test_registry_client_contract.py` to the version 3 wire. Bump
      `core/registry-client` and `core/registry` once against `dev`. Verify by:
      - the client's unit suite, with its messages from 5a.7's fixture;
      - the contract test;
      - 6.2–6.7's application integration tests.

      *Done:* `core/registry-client` 0.13.0 → 0.14.0 and `core/registry` 0.6.1 →
      0.7.0, each one minor step from the merge base (`dev` has since moved the
      registry to 0.7.0 itself, and `core/buyer` 0.8.1, the bare-metal buyer 0.9.1
      and `e2e-tests` 0.3.2 for other content too, so the merge bumps each of the
      four again). `ListingSummary` reads
      `publication` and `updates` as fields. Retries pass `request_id` and `origin` in
      place of `timestamp`. Every bound on the client moves to 0.14.0, exact pins in
      `core/buyer` and the bare-metal buyer, lower bounds in `core/storefront`, the
      three storefronts and `e2e-tests`; each package was already bumped on the branch.
      The VM storefront's `test_registry_client_contract.py` signs its mock registry's
      answers with `build_signed_response` and verifies the request with
      `verify_market_request`; the bare-metal storefront's `test_registry_bearer.py`
      looks for `Signature`. Suites: `make test-registry-client` 49 passed (unit, its
      messages from 5a.7's fixture); the contract test and the multi-registry test, 35
      passed; `test_registry_bearer.py` 5 passed; 6.2–6.7's application integration
      tests in `make test-registry`.
- [x] 6.9 Add the retention and sweep-interval settings to the registry's settings and
      chart values schema. Verify by the registry's configuration tests and its chart
      render test.

      *Done:* `Settings.authenticated_requests` (`config.py`), read from a profile env
      file as `AUTHENTICATED_REQUESTS__RECORDED_OUTCOME_RETENTION_SECONDS` and
      `…__REPLAY_PRUNE_INTERVAL_SECONDS` (`env_nested_delimiter="__"`), positive
      integers defaulting to 86400, held to the kit's model by `registry_core`. The
      chart renders them from `config.authenticatedRequests` only where stated, and the
      umbrella schema's `registryInstance` refuses anything but a positive integer.
      Unit (`test_config_profiles.py`): defaults, a profile's values, `0`, `-1` and
      `a-day` refused naming the key, for each key. Chart render
      (`helm/charts/registry/tests/test_render.py`, run by `test-render.sh`): the lines
      render only where stated, a stated `0` renders for the registry to refuse; the
      schema refuses `0` and `a-day` for each key, naming it. The rendered lines are
      not parsed with the registry's loader here; the release topology test loads the
      registry's rendered profile without them. The registry chart is 0.2.0 and the
      umbrella 0.6.0.
- [x] 6.10 Verify the section: `make test-registry`, `make test-registry-client`, `make
      -C kit/authenticated-requests test`, the VM storefront's unit suite (via `make
      test-domains`) for its contract test, and `core/buyer`'s suite for the ETag's
      caller.
      End-to-end: `registry`, `multi_registry`, `roles_layer_registry` — evidence once
      section 16 lands. No end-to-end scenario runs the URL bootstrap; none is owed,
      since no deployed role calls it (D24).
      *Done:* `make test-registry` (unit and application integration, 362 passed);
      `make test-registry-client` (unit, 49 passed); `make -C kit/authenticated-requests
      test` (unit and library integration, 283 passed); the VM storefront's contract and
      multi-registry unit tests (35 passed) and the bare-metal storefront's
      `test_registry_bearer.py` (5 passed) run focused; `core/buyer`'s suite (190
      passed). `change-workflow run pre-commit`: passed, its `make validate-local` over
      the tree running `check-packaging` and `make test` (every suite, the domains'
      and the chart render tests included), then the repository's checks.
      End-to-end: confirmed as planned — `registry`, `multi_registry`,
      `roles_layer_registry`, evidence once section 16 lands; none runs the bootstrap.

Notes (section 6):

- **Stopped before 6.1; the change returns to design.** 6.2 replaces
  `publisher_auth.py`, and that file does more than reserve and sign: it keeps the
  publisher's version 2 request envelope as retained evidence. Nothing in the design
  or the delta specifications says what the registry keeps in its place once
  publishers sign version 3. The evidence:
  - `retained_request_evidence` (`core/registry/src/core_registry/api/publisher_auth.py`)
    stores `{"body_base64": …, "request": <the version 2 AuthenticatedRequest>}` in
    `listings.publisher_publication` on publish and in each `publisher_updates` entry
    on update (`listing_routes.py`), and the registry serves both in every listing
    read (`api/utils.py`, `order_to_dict`).
  - Registry-discovery's permanent requirement "Seller publication evidence is
    independently verifiable" requires "the authenticated v2 request envelope
    including its seller proof". The change's registry-discovery delta modifies only
    "Durable replay reservation", so the requirement still names version 2.
  - A consumer verifies that evidence offline, at its own signed time:
    `verified_pricing_publication`
    (`domains/vms/buyer/src/arkhai_vms_buyer/pricing_record.py`) parses
    `publisher_publication["request"]` as a version 2 `AuthenticatedRequest` and calls
    `verify_request`, which binds the VM buyer's accepted pricing to the seller's
    signed terms.
  - D2 says the non-HTTP signed artifacts, "pricing records" among them, keep
    `kit/identity`'s own framing, and D12 keeps version 2 readable for evidence
    already retained. Neither covers new evidence that is itself an authenticated HTTP
    request. A version 3 publication carries no version 2 envelope to keep. What it
    has instead is an RFC 9421 message: the covered `Market-*` fields,
    `Content-Digest`, `Signature-Input` and `Signature`, plus the body bytes.
- Section 9 has the same gap, found while checking this one; it was not started.
  `SignedEndDeliveryReceipt`
  (`kit/deal-lifecycle-contracts/src/market_deal_lifecycle_contracts/models.py`) is a
  wire model carrying a version 2 `AuthenticatedRequest` and `AuthenticatedResponse`.
  Deal-servicing builds it on `end_delivery` (`routes.py`), the deal-lifecycle client
  keeps it (`client.py`, `end_receipt`), and the buyer verifies it offline through
  `verify_end_acknowledgement` (`kit/deal-lifecycle/src/market_deal_lifecycle/acknowledgements.py`,
  called from `kit/deal-lifecycle-buyer/…/ending.py`). Deal-servicing's ingress also
  keeps the buyer's version 2 end envelope as `buyer-end-envelope:` evidence
  (`ingress.py`), and the deal-lifecycle buyer's store captures version 2 envelopes as
  `signed_request` and `signed_response` items (`store.py`). Sections 11 and 15 meet
  it as well: `verify_recovered_pricing` in the same `pricing_record.py` verifies VM
  negotiation evidence items as version 2 envelopes. Sections 7 and 8 use version 2
  envelopes only for live authentication, so this gap does not touch them.
- The decision the design owes, with the recommendation here. Give version 3 one
  evidence form, owned by `kit/identity` beside the profile: a captured request
  (method, the covered field lines, the body bytes) and a captured response (status,
  its field lines, the body bytes, and the request it binds). Add an offline verifier
  that checks the signature and the principal against a trust set at the message's
  own `created`, without freshness, as the version 2 readers do today with
  `max_skew=0`. The registry's publication and update evidence, the end-delivery
  receipt, deal-servicing's end envelope and the buyer's captured items would carry
  that form. Each consumer would verify version 3 evidence and keep the version 2
  reader for records already retained (D12). This needs delta specifications: at
  least registry-discovery's "Seller publication evidence is independently
  verifiable", and the deal-lifecycle requirement that defines the end-delivery
  receipt. It also needs tasks in sections 6, 9, 11 and 15, plus the `kit/identity`
  form, which section 2 did not build. The alternative is for sellers and buyers to
  sign a separate non-HTTP artifact in `kit/identity`'s own framing inside the body,
  as D2 has for pricing records. That changes every publisher's and buyer's payload,
  and the transport signature would still be what the authority checks.
- Nothing of section 6 was implemented, and no task is checked. This commit holds
  only these notes.
- **Stopped again before 6.1 (2026-11-27); the change returns to design.** The
  registry's descriptor read cannot be served under version 3 as designed. The
  evidence:
  - `GET /.well-known/arkhai/registry-descriptor.json` is a trust bootstrap.
    `RegistryClient.bootstrap_registry_descriptor` and `_descriptor_bootstrap_request`
    (`core/registry-client/src/registry_client/client.py`) sign the request knowing no
    registry principal, then verify the signed response against the principal set
    the descriptor itself names. Registry-discovery's permanent "Registry
    self-description is authority-authenticated" requires this ("A bootstrap client
    MUST verify the signed response against the principal set carried in the
    validated descriptor"; scenario "Descriptor is used as a trust bootstrap"). It
    still names version 2, and the change's deltas do not modify it.
  - Under version 3 every request carries `Market-Audience`, "the principals the
    caller would accept the answer from", and "an authority MUST accept a request
    only when its own signing principal is listed" (the marketplace-identity delta;
    D10). `AdmissionCore.admit` answers any other request a signed 421
    `audience_mismatch`. A bootstrap client has no principal to list, so every
    bootstrap is refused, unless the route is served outside the requirement. Neither
    the design nor the deltas mention the descriptor.
  - Today only the registry's own tests call the bootstrap
    (`core/registry/tests/integration/test_registry_descriptor.py`), but it is public
    client API.
- The decision the design owes, with the recommendation here:
  - (a), recommended: the descriptor read is exempt from the audience check, as
    the time-setting operation is exempt from freshness. This is a route declaration
    the core honours. The read is `RERUN` and writes nothing, every other check is
    kept, and the bootstrap client verifies the signed answer against the
    descriptor's principals. It needs a marketplace-identity delta for the exemption,
    and registry-discovery's descriptor requirement restated for version 3.
  - (b) Retire the bootstrap. The descriptor becomes an ordinary audience-bound read
    by a client configured with the registry's principal, and the bootstrap
    scenario and client method go. This is cheaper, but removes a public client
    capability and the requirement's trust bootstrap.
  - (c) The bootstrap request carries an empty audience, learns the principal from
    the signed 421, and re-sends. This makes a refusal part of the protocol.
  - (d) The descriptor route is unauthenticated and its body self-signed under
    `kit/identity`'s own framing. This changes the descriptor's wire.
- Also for the design to confirm while it is open: a read's query values. The
  marketplace-identity delta says "Behavior-affecting query values MUST be
  represented in the signed semantic body", and `Content-Digest` covers the bytes
  sent. So a registry read would send the canonical query document that version 2
  hashed without sending (`_query_body`: the sorted query items, and a normalized
  `If-Match`) as a GET body, and the registry would refuse a read whose body differs
  from its URL's document. A GET with a body is unusual; whether the deployed
  ingress passes it is untested.
- Found while checking, for planning (not design questions):
  - Section 9 cannot pass a functional commit's checks alone. `create_lifecycle_router`
    is composed by the bare-metal storefront (`server.py`) and by the VM storefront's
    integration tests (`tests/recurring_world.py`, `test_spot_notice.py`,
    `test_vm_delivery_path.py`, `test_payment_settlement.py`). 9.2 makes it take the
    admission core, which the storefronts compose only in 10–12, and
    `pre-commit-functional` runs every suite. Either section 9 composes a core where
    those callers build the router, or it moves with 11–12.
  - Section 6 also breaks the VM storefront's
    `tests/unit/test_registry_client_contract.py`, which doubles the registry's
    version 2 wire against the installed client; 6.5 does not name it.
- Choices made reading the code, for the replanned section (nothing implemented):
  - Trust: the registry admits any verified principal; version 2 trusted the
    claimed principal, and the routes check ownership. The core's `trust` is typed
    `TrustedIdentitySet`, so the kit's parameter becomes a protocol of `allows`.
  - Store: the registry's SQLite engine uses `StaticPool`, one shared connection.
    The replay store needs its own engine on the same file, or its transactions
    interleave with the request session's.
  - Rotation and retirement pass D6 as keyed by nonce: a re-run after a later write
    changes nothing. But each reaches an applied rotation only after its proof-expiry
    or primary check, so a late retry is answered 401 or 403 rather than with the
    rotation. The section would answer an existing rotation for the same intent
    first.
  - The singletons with no identifier (descriptor, filter spec, health, stats) have
    no target.
- Nothing of section 6 was implemented by this session, and no task is checked.
  Sections 7–9 were not started: a section stopped for a design question ends the
  session's sections.
- **Implemented (2026-11-27), round 4's first session.** Handoff for the sections
  after it:
  - The registry is composed as `api` (the FastAPI application) wrapped by the core
    as `app`; `uvicorn core_registry.main:app` serves the wrapped one. A test reaching
    FastAPI's own attributes (`dependency_overrides`, `state`, `routes`) uses `api`,
    and one sending requests uses `app`. The registry's signer and replay store are
    bound at startup (`admission.bind`), since the core is built as the routes import
    and the database is opened only after its compatibility check.
  - The registry's integration suite runs each test over a database the migration
    chain built (`registry_database`, a file named `served-registry.db` so it never
    collides with a test's own `registry.db`), each request on its own session as in
    production, and binds the replay store to that file. Its autouse fixture signs a
    test's raw request under version 3 as a seller, over the exact bytes sent, so the
    raw-call tests kept their shape; a request already carrying a request identity,
    or marked `X-Test-Unsigned`, passes as it is. New tests use the typed client.
  - Outside the plan, fixed here: `kit/authenticated-requests`' `dependency.py`
    postponed its annotations, so FastAPI 0.123, which the registry's lock resolves,
    read `RouteAdmission.__call__`'s `request: Request` as a query parameter and
    answered every route 422; the kit's own lock resolves 0.165.0 (beside a 0.162.5
    entry), which resolves them. The
    module now evaluates its annotations as it is defined, with the reason in its
    docstring. Every authority on an older FastAPI meets the same, so sections 7–13
    should not reintroduce the future import there.
  - FastAPI closes a request's yield dependencies before the wrapped application
    returns, so a `RECORDED` route that flushed and then refused has rolled back
    before the core records its outcome: checked with a 403 after a new publisher's
    flush, recorded at once (a probe, not kept as a test).
  - The registry chart is 0.2.0 and the umbrella 0.6.0, for the retention keys.
  - Still version 2, for later sections: `e2e-tests/tests/e2e/roles/scenarios/vms/
    conftest.py`'s `signed_listing_read_headers` signs a raw registry read under
    version 2 (section 15's harness and the end of version 2 signing); the VM buyer's
    `pricing_record.py` reads `publisher_publication` (section 15). No in-process
    suite runs either against the registry.
  - The fresh-context check found, and this section fixed: the registry's bound on
    `kit/schema-migrations` (now `>=0.2.0`, for `CompactionFailed` and the report's
    `compacted`); the registry's README still describing version 2; rejection-path
    tests asserting body fields (now the status and the signature); the key-less
    descriptor read sent raw (now the typed client); the rotation retry needing the
    client's private `_rotation_body` (the `body=` parameter is gone: the same nonce
    and expiry re-sign the same intent); the parity test among the integration tests
    (now `tests/unit/test_client_parity.py`); the 0.4.0 test database not built from
    the floor fixture; no test of `--check` on a 0.4.0 database; the chart dropping a
    stated `0`; the sweep key's refusals untested; a history-worded comment and an
    unwrapped docstring; and notes claiming more than their tests showed.
  - Declined from it: the raw ETag-header read in `test_filter_spec.py`, since the
    typed client exposes no response header and the existing test of the shipped
    spec reads it the same way; the module-level replacement in the recorded-500
    test, since the routes inject no collaborator to double and the test it
    replaces did the same; a test of a failing `VACUUM`, which needs a held lock
    waiting out SQLite's busy timeout (the kit's engine proves that order for the
    other chains); parsing the chart's two new lines with the registry's loader in
    the release topology test, left to whoever next touches that test.

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
      criterion and declare it in its contract, naming whether each operation has a
      target (the plan's preamble); record the table in this task's note.
      `POST relays`, relay `token` rotation, relay `grant-keys/stage`, host and pool
      upserts and deletes, the VM-domain job routes but `reset-password`, and the
      `check-leases`, convergence `run-cycle` and `advance-cycle` routes are `RECORDED`;
      confirm `reset-password` `RERUN` as a keyed operation (D6, 27 F4). A difference
      from the design's table, or a `RECORDED` route whose caller could not learn by
      reading, stops the section as in 6.1. The provisioning service runs SQLite, so
      the table names any `RECORDED` route holding a write transaction near the lease
      period or writing in more than one transaction, as 6.1's does (D7, 45 F1, 61 F1).
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
      notification's end-to-end behaviour is proven in 11.3. Remove the family's
      canonical query form (`compute_provisioning_contracts/routes.py`): the
      client builds every query through 5d.3's encoding, and `@query` covers it (D25,
      the plan's preamble). Verify by:
      - the client's unit suite and the outbox's unit tests;
      - an application integration test: a job-list read whose query an intermediary
        changed refused as an invalid proof.
- [ ] 7.5 Add the retention and sweep-interval settings to provisioning's settings and
      chart values schema. Verify by its configuration tests and chart render test.
- [ ] 7.6 Verify the section: `make test-compute-provisioning`,
      `make test-compute-provisioning-client`, `make test-compute-provisioning-contracts`,
      `make test-provisioning`.
      End-to-end: `provisioning`, `provisioning_readonly`, `provisioning_security`,
      `e2e_compute_dynamic_listings` — evidence once section 16 lands.

Notes (section 7):

- **Stopped before 7.1 (2026-11-27); the change returns to planning.** Section 7
  cannot be committed apart from section 8: one typed client, `kit/site-client`,
  signs the requests of both sections' authorities, and the admission core accepts
  version 3 alone. The evidence:
  - The provisioning service hosts the site's capacity and capacity-definition
    routes (`compute_provisioning_service/route_table.py`, `site_route_contracts`
    over `market_site.auth`'s `CAPACITY_ROUTE_CONTRACTS` and
    `CAPACITY_DEFINITION_ROUTE_CONTRACTS`). 7.2 puts every route of the service
    behind the core, the hosted site's included, so they answer only version 3.
  - Provisioning's own suite reaches those routes through `kit/site-client`'s typed
    clients: the integration conftest's `provisioning_clients` builds
    `SiteCapacityClient` and `SiteCapacityAdminClient`, and 11 integration modules
    call them (68 calls; `test_capacity_api.py`, `test_capacity_definitions_api.py`,
    `test_deliverable_hosts_api.py`, `test_relay_drain_api.py`,
    `test_leases_api.py`, `test_fulfillment_api.py`, among others).
    `kit/site-client` signs version 2 until 8.5, so 7.6's `make
    test-compute-provisioning` cannot pass after 7.2 with the typed clients.
  - Moving `kit/site-client` in section 7 breaks the other authority it calls: the
    API-credits service behind `kit/site`'s `SiteAuthMiddleware`, version 2 until
    8.2 (`kit/site`'s integration suite, the API-credits service's suite). A typed
    client never sends version 2 (D9), so no order of 7 and 8 lets either commit
    pass `pre-commit-functional`, which runs every suite.
  - Reaching the hosted site in section 7 through a test-side version 3 signer in
    place of the typed client would be a workaround the plan does not give, and
    7.2 asks for the typed client.
- Also for planning, found while checking (none started):
  - Neither section names the suites outside its packages that double the
    provisioning or site wire against the installed clients, the omission 6.5 had
    for the VM storefront's registry contract test. 7.4 removes
    `canonical_provisioning_request_body`, which
    `domains/vms/storefront/tests/integration/test_site_trust.py`,
    `domains/bare_metal/storefront/tests/signed_sites.py` (used by its
    `test_site_clients.py`, `test_site_trust.py` and `test_app_composition.py`),
    `domains/apicredits/service/tests/integration/test_signed_authority.py` and
    `e2e-tests/src/e2e_harness/provisioning_test_client.py` import; each signs or
    verifies the version 2 wire too, as do `domains/vms/storefront/tests/fake_site.py`
    and `domains/bare_metal/storefront/tests/integration/test_site_reservation.py`
    for the site. Section 15 owns the e2e harness, but `make test-e2e-unit` is in
    `make test`.
  - 7.1 classifies the hosted site's routes, but their declarations live in
    `kit/site`'s `SiteRouteContract`, whose `exact_retry_safe` 8.1 replaces; the
    plan should say which section adds the field the provisioning service reads.
- Recommendation: one section moving together the
  provisioning service and its hosted site, `kit/site`'s middleware and the
  API-credits service, and their clients (`compute_provisioning_client`,
  `kit/site-client`, the settlement credits client, the Python middleware client),
  naming the suites above. That unit is large beside sections 6–7 as planned
  (the provisioning service alone has 47 integration modules); the cadence's
  session for it is planning's to size, since the workflow commits a section
  whole and the owner's direction for this round was one fresh session per
  section.
- Nothing of section 7 was implemented, and no task is checked. This commit holds
  only these notes. Sections 8 and 9 were not given to this session.

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
      criterion and declare it, naming whether each operation has a target (the plan's
      preamble), replacing `SiteRouteContract.exact_retry_safe`;
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
      client to version 3 signing and response verification. Remove the site kit's
      canonical query form (`kit/site/src/market_site/auth.py`, the signed body of the
      reservation and projection reads). The site client builds those queries through
      5d.3's encoding, and `@query` covers them (D25, the plan's preamble). Verify by:
      - their unit suites and 8.3–8.4's integration tests;
      - an application integration test: a projection read whose `after` an
        intermediary changed refused as an invalid proof.
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

*Replanned 2026-11-27 against the reviewed design* (D21–D23); no task had been started.

Moves `kit/deal-servicing`'s lifecycle routes and the deal-lifecycle client onto the
core in the dependency form. This gives them the reservation they lack and removes their
invented refusal identity. Lifecycle evidence and the end-delivery receipt become
records (D3, D21, D22, D23; findings; deal-lifecycle "The end-delivery acknowledgement
is signed by the Agreement's seller"). Touches:
- `kit/deal-servicing/src/market_deal_servicing/` (`routes.py`, `ingress.py`);
- `kit/deal-lifecycle-contracts/` (route declarations, `models.py`'s
  `SignedEndDeliveryReceipt`);
- `kit/deal-lifecycle/src/market_deal_lifecycle/acknowledgements.py`;
- `kit/deal-lifecycle-client/src/market_deal_lifecycle_client/client.py`.

- [ ] 9.1 Declare each lifecycle route against D6's criterion and record it in this task's
      note: submit and peer keyed by `operation_key`, reads `RERUN`. Each names its
      negotiation as its target, but `lifecycle_list`, a collection read with no
      target, whose filters `dispatch` folds into its resource today: they travel as
      the query, covered by `@query` (D25, D28). A difference stops the section as in
      6.1.
- [ ] 9.2 Authenticate through the core's dependency form, the router taking the admission
      core its storefront composes. So that this section passes a functional commit's
      checks alone, it composes that core wherever `create_lifecycle_router` is built
      today:
      - the bare-metal and VM storefronts' `server.py`;
      - the VM storefront's integration tests (`tests/recurring_world.py`,
        `test_spot_notice.py`, `test_vm_delivery_path.py`, `test_payment_settlement.py`);
      - `domains/vms/storefront/examples/payment_smoke.py`;
      - `kit/deal-servicing`'s examples and integration tests;
      - `docs/attachments/lifecycle-routes/end_first_use.py`.

      Each core is over the storefront's database, through the `sqlite3` store, with
      the replay table this section adds to core storefront's chain (the kit's
      replay-table migration, moved here from 10.2). Until 11 and 12 declare every
      storefront route, the storefronts admit only the lifecycle routes through it. The
      core's application-level fallback and route inventory are installed over a
      storefront once 11 and 12 extend that core to every route. Evidence is kept as
      records (D23):
      - `lifecycle_response` from the signed outcome;
      - the buyer's end request (`buyer-end-envelope:`) from the admission, in the
        ingress's transaction;
      - no headers in either.

      A refusal for a request with no request identity is answered unsigned. Verify by
      `kit/deal-servicing`'s integration suite, binding a core over a test database
      migrated with 4.7's migration:
      - a replayed lifecycle request inside the skew refused by its reservation;
      - a `lifecycle_list` read stating no resource admitted, and one whose query an
        intermediary changed refused as an invalid proof;
      - each evidence item's record verifying through the evidence verifiers with the
        Agreement's parties;
      - a double-dispatch case per `RERUN` mutation.
- [ ] 9.3 Make the end-delivery receipt records (D21, D22). `SignedEndDeliveryReceipt` holds
      a request record with its body and a response record with its body. A receipt
      stored under version 2, in a buyer's end journal or as an `end_delivery_receipt`
      item, still decodes by its `protocol`. `verify_end_acknowledgement` verifies both
      parts through `kit/identity`'s evidence verifiers, the response with no role, the
      Agreement's seller binding it. Deal-servicing's self-check calls it unchanged.
      Verify by unit tests (deal-lifecycle "A case export carries an acknowledgement", "A
      receipt kept before the cutover is verified"; marketplace-identity "An end
      acknowledgement's response is verified without a role"):
      - a version 3 receipt verified against the Agreement;
      - a 0.4.0 receipt's JSON decoded and verified;
      - a receipt whose response a principal other than the seller signed refused.
- [ ] 9.4 Move the deal-lifecycle client to version 3. Its captures pass records through
      the seam (5a.6), and it builds the end receipt from the records of what it sent and
      verified. Verify by its unit suite, its messages from 5a.7's fixture.
- [ ] 9.5 Verify the section: `kit/deal-servicing`, `kit/deal-lifecycle-contracts`,
      `kit/deal-lifecycle`, `kit/deal-lifecycle-client` and `kit/deal-lifecycle-buyer`
      suites (via `make test-kits`). The buyer kit is run because its ending verifies the
      receipt. Also run the VM and bare-metal storefronts' suites (via `make
      test-domains`) and `make test-core`, for the composition and the moved migration's
      chain tests.
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
      on the storefront's database through the `sqlite3` store. The storefront's evidence
      capture takes records from the admission and the signed outcome, not headers (D23).
      Give every storefront the sweep from its lifespan. Verify by `core/storefront`'s
      integration suite:
      - a storefront route raising after authentication answered with a signed 500 its
        typed client verifies (marketplace-identity "A storefront route raises after
        authentication");
      - a captured negotiation message whose record verifies through the evidence
        verifiers.
- [ ] 10.2 Add to core storefront's chain a space-freeing migration dropping
      `auth_replay_reservations` (D9); the kit's replay-table migration moved to 9.2,
      which first composes a storefront's core. Verify by each
      storefront's migration-chain test from its floor fixture and from a database holding
      the 0.4.0 table with rows, the file compacted after (deployment-state "A storefront
      upgrades from marketplace 0.4.0").
- [ ] 10.3 Move `core/storefront-client` to version 3, sending its expected-authority set
      as the audience; its captures pass records through the seam (5a.6); replace its
      "reuse `request_id`" guidance with the declared resolution, and tell a caller
      answered `admission_unavailable` to retry the same request (D7). It builds every
      query through 5d.3's encoding, `@query` covering it (D25). Verify by its unit
      suite, its messages from 5a.7's fixture.
- [ ] 10.4 Declare and bind the shared route services' operations (deal-control routes,
      pool overrides) against D6's criterion: trading and listing pause and resume,
      force-accept, admin reserve and release, run-cycle and projection refresh `RECORDED`
      (D6), each naming whether it has a target (the plan's preamble). Record them in this
      task's note; a difference stops the section as in 6.1.
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
      `arbitrate_listing`; credential-capable routes `RERUN` recording no body; each
      operation names whether it has a target (the plan's preamble). The negotiation
      list names its listing alone. The stage-event read names none. Their filters,
      folded into the resource today (`admin_identity.py`'s
      `_negotiation_list_resource`, `StageEventRouteService.signed_resource`), travel
      as the query (D25, D28). Record the table in this task's note; a difference stops
      the section as in 6.1.
- [ ] 11.2 Replace the four middlewares and every controller's `recorded_outcome`
      handling with the core; handlers needing to know a retry read `exact_retry`
      (`settle_controller`'s `refuse_after_end`); negotiation evidence
      (`buyer-envelope:`, `seller-envelope:`) captured as records through the
      signed-outcome hook, no headers kept (D23). Verify by application integration tests
      through the typed client: the kept buyer request's and seller response's records
      verifying through the evidence verifiers (deal-lifecycle "A storefront keeps the
      buyer's signed opening"); a `negotiate_new` retry answered with the recorded outcome and no second
      negotiation; a credential-capable read retried after an end refused and no body
      recorded (marketplace-identity scenarios); a negotiation-list read whose buyer
      filter an intermediary changed refused as an invalid proof (D25); a double-dispatch
      case per `RERUN` mutation and the completeness test.
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
      it, naming whether each operation has a target (the plan's preamble), replacing `CREDENTIAL_CAPABLE_ROUTES` and `without_access_material` with
      `RERUN` declarations that record no body. The negotiation list names its listing
      alone and the stage-event read none, their filters (`api.py`'s
      `_negotiation_list_resource` and stage-event resource) travelling as the query
      (D25, D28). Record the table in this task's note; a difference stops the section
      as in 6.1.
- [ ] 12.2 Replace `response_auth.py` and `api.py`'s authentication with the core;
      seller-response evidence captured as a record through the signed-outcome hook, no
      headers kept (D23). Verify by application integration tests through the typed
      client: the fulfillment access route retried after an end refused with no body
      recorded; the `seller-response:` item's record verifying through the evidence
      verifiers with the seller's principal; a stage-event read whose query an
      intermediary changed refused as an invalid proof (D25); a double-dispatch case per
      `RERUN` mutation and the completeness test.
- [ ] 12.3 Verify the section: the bare-metal storefront's suites (via
      `make test-domains`).
      End-to-end: `e2e_bare_metal_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal` — evidence once section 16 lands.

## 13. The API-credits storefront on the admission core

Moves the API-credits storefront onto the core (D3, D5, D6). Touches
`domains/apicredits/storefront/src/apicredits_storefront/middleware/` (`admin_auth.py`,
`seller_auth.py`, `buyer_auth.py`, `response_auth.py`), `controllers/` and its tests.

- [ ] 13.1 Classify every API-credits storefront route against D6's criterion and declare
      it, naming whether each operation has a target (the plan's preamble); `publish-from-quota` and the shared `RECORDED` routes are `RECORDED`. The
      negotiation list names its listing alone, its buyer filter
      (`admin_auth.py`'s `negotiation_list_resource`) travelling as the query (D25,
      D28). Record the table in this task's note; a difference stops the section as in
      6.1.
- [ ] 13.2 Replace the four middlewares and `negotiate_controller`'s `recorded_outcome`
      handling with the core. Verify by application integration tests through the typed
      client: a `publish-from-quota` retry answered with the recorded outcome and no
      second listing; a negotiation-list read whose buyer filter an intermediary changed
      refused as an invalid proof (D25); a double-dispatch case per `RERUN` mutation and
      the completeness test.
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

*Replanned 2026-11-27 against the reviewed design* (D21–D23); no task had been started.
15.2–15.6 are the former tasks, renumbered.

Moves every remaining signer onto version 3, and the buyers' evidence onto records. It
binds signed webhook deliveries to their endpoint and proves a typed client's time
advance beyond the skew. It removes version 2 request signing, leaving version 2
readable through the evidence verifiers (D2, D8, D9, D10a, D12, D21, D22, D23). Touches:
- `core/buyer/src/core_buyer/` (`negotiation_client.py`, `run_log.py`);
- the buyer plugins under `domains/vms/buyer`, `domains/bare_metal/buyer` and
  `domains/apicredits/buyer`, the VM buyer's `pricing_record.py` among them;
- `kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/store.py`;
- `kit/delivery/src/market_delivery/builtin/webhook_sink.py`;
- `e2e-tests/src/e2e_harness/` signing clients;
- `kit/identity`.

- [ ] 15.1 Move `core_buyer`'s negotiation client and every buyer plugin to version 3, the
      audience from `expected_response_principals`. Captures pass records through the seam
      (5a.6). The run log records version 3 request identities for recovery. Any query
      is built through 5d.3's encoding (D25). Verify by the buyer suites, including
      run-log recovery.
- [ ] 15.2 Keep the buyer's evidence as records (D23). The buyer store captures a record,
      its body and the expected principals, and keeps no headers. Its acceptance lookup
      and case export read version 3 records and stored version 2 items alike. Verify by
      `kit/deal-lifecycle-buyer`'s suites (deal-lifecycle "A buyer accepts", "The buyer's
      transport verifies an acceptance"):
      - a version 3 acceptance captured and found as the commitment's acceptance;
      - a 0.4.0 evidence record's version 2 items still found and exported;
      - a case export's items verifying through the evidence verifiers.
- [ ] 15.3 Verify the VM buyer's pricing through the evidence verifiers (D21, D22). The
      retained pricing record copies `publication` and `updates`. The publication check
      reads `publication`, or `publisher_publication` in a record retained before the
      cutover, with the request verifier and the listing's publisher principals. The
      recovered-pricing check reads the buyer store's version 2 and version 3 items with
      both verifiers and the Agreement's parties. Verify by the VM buyer's integration
      tests:
      - an acceptance against a version 3 publication read through the registry client;
      - an acceptance against a pricing record retained under version 2 with the old key;
      - recovered pricing over a version 3 negotiation's evidence;
      - a publication record altered after signing refused.
- [ ] 15.4 Bind signed webhook deliveries to their endpoint by covering `@target-uri`
      (D10a). Verify by `kit/delivery`'s suite: a receiver verifies a delivery made for
      its endpoint and refuses one made for another (introduction-delivery "A signed
      delivery is sent to another receiver").
- [ ] 15.5 Prove a typed client's time advance beyond the skew through the core (D8,
      35 F1): a storefront at 1794822300 accepts a version 3 time-set signed with
      `created` and origin at 1794823200, moves, and answers signed at the new instant,
      while another operation 900 s skewed is refused (marketplace-identity "The harness
      advances past the skew", "Another operation arrives skewed"). Verify as an
      application integration test through the storefront client.
- [ ] 15.6 Move the end-to-end harness's signing clients to version 3, building any query
      through 5d.3's encoding (D25). Verify by `make test-e2e-unit`.
- [ ] 15.7 Remove version 2 request signing and acceptance from `kit/identity`, and the
      version 2 form of the capture seam. Keep version 2 verification inside the evidence
      verifiers (D9, D12). Confirm no package outside them imports version 2 request code.
      Verify by the `kit/identity` unit suite, a repository search, and `make test`.
- [ ] 15.8 Verify the section: the buyer, `kit/deal-lifecycle-buyer`, `kit/delivery`,
      `core/storefront` and `kit/identity` suites; `make test-e2e-unit`; `make test`.
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
- [ ] 16.2 Confirm the 0.4.0 upgrade path once more. A storefront, provisioning and
      registry database from the `marketplace-v0.4.0` floor fixtures migrate, the replay
      tables gone and the SQLite files compacted. The registry's version 2 publication
      evidence is carried under `publication` and still verifies. Verify by the
      migration-chain tests named in 6.4, 7.3 and 10.2 run together.
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
- [ ] 17.3 Documentation compliance: re-check D1–D29 against
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
        format, the profile's tags, its one accepted spelling, `Market-Resource` only
        where an operation has a target, and `@query` covered on every request with the
        raw query verified (D2, D10, D12, D13, D25, D28); a new section on the
        admission core, its two forms, the fallback (unmatched public requests answered
        signed unverified), the route inventory and its three marks, the public
        operation answered signed with nothing reserved, the signed 503
        `admission_unavailable`, and the records it hands to evidence capture (D3, D7,
        D23, D24); a new section, "Signed messages retained as evidence", on the record of a
        message's signed values, its scope to authority-bound messages, and the two
        evidence verifiers reading either version (D21, D22); a new section on exact-retry
        resolution, which routes record, and secrets never recorded (D5, D6); a new
        section on the replay state's bounds, the lease floor and renewal, the concluding
        write before `exact_retry_outcome_unknown`, expired rows treated as absent, and the
        sweep (D7);
      - `openspec/specs/marketplace-identity/configuration.md`: a settings table for
        `authenticated_requests.recorded_outcome_retention_seconds` and
        `authenticated_requests.replay_prune_interval_seconds` (D7);
      - `openspec/specs/marketplace-identity/testing.md`, "Marketplace Identity
        Verification": the double-dispatch harness with its interleaved write, the
        completeness test, and the crash-boundary cases (D5, D7);
      - `openspec/specs/registry-discovery/architecture.md`, "Seller publication
        evidence": `publication` and `updates` as the seller's request record beside the
        body, a version 2 row returned as stored, and the four reserved names (D21);
        "Self-description boundary": the descriptor a public read whose signed answer,
        bound to the client's fresh request ID, proves possession; the bootstrap's HTTPS
        precondition and base-URL check; trust on first use kept for adding a registry
        by URL, a directory's countersignature a separate layer (D24);
      - `openspec/specs/deal-lifecycle/architecture.md`, "Buyer surrender and cases": the
        end-delivery receipt as a request record and a response record with their bodies,
        verified through the evidence verifiers, a version 2 receipt still read (D21, D22,
        D23);
      - `openspec/specs/deployment-state/architecture.md`, "One engine, one contract":
        space-freeing migrations and the command's `VACUUM`, the registry's migrate
        command compacting after Alembic under the same rule, and the replay table a kit
        contributes to every authority's chain (D9);
      - `docs/development/ARCHITECTURE.md`: "Marketplace identity" for the version 3
        profile and the admission core (D2, D3); "Registry self-description" for the
        descriptor's public read and the bootstrap's trust on first use (D24); "Kit areas" for
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
        as it stands, stripped before any persistence; and a signature covering every
        request input that changes behaviour, the query included (D2, D6, D10, D11,
        D25); and the two
        principles the owner stated with D21 — each kind of message carries exactly the
        fields some message of that kind needs, presence fixed by the kind and never by
        one message's values; and a retained signed message is stored as its signed
        values, readable as data, not as its transport form (D21);
      - `docs/release-handbook.md`, "Compatibility to retire": no row — D9 builds no
        compatibility path, and D12's evidence reader is current behaviour;
      - the delta specifications' `spec.md` files are written by the archive and named
        in the record (D14), carrying D26's filter-spec parameter and D27's rotation
        retries; D28 and D29 have no destination beyond them and the plan.
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
      `compute-provisioning-contract`, `api-credits`, `deployment-state` and
      `deal-lifecycle`; no `--skip-specs`, since no `spec.md` was edited by hand.
