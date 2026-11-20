# Tasks

Sections 1–7 convert every read of the time of the world to one process source,
with every process still on wall time; sections 8–17 add the settings, the controls
and lane time, and put the lanes on it; section 18 is the closeout. Decisions are
`design.md`'s; requirements are the change's deltas under `specs/`.

A read is classified once (D20): a value stored, signed, sent to another party, or
compared with an instant another party knows is lane time and reads the process
source; a value only subtracted from another reading in the same process is elapsed
work and reads `time.monotonic()`. A database time production logic reads — a column
a query orders, filters or expires by, or a decision compares — is supplied from the
process source; an audit-only `created_at`/`updated_at` nothing reads keeps its SQL
default (D13). Each section's task note lists the columns it judged read and those it
left as audit-only.

## 1. The time component

Delivers the standalone component (D6) with frozen injected time and its value rule
(D11). Implements `injected-time`'s "Injected time is frozen at the instant last set
and moves only forward", "Lane time is an integer of Unix seconds read by one rule",
"The component is standalone", and the source half of "Each process reads the time of
the world from one source". Touches a new project, `tools/injected-time/`
(distribution `arkhai-injected-time`, import `injected_time`), the root `Makefile`,
`.github/workflows/tests.yml`, the release declaration
(`manifests/release-components.json`), and `docs/development/ARCHITECTURE.toml`.

- [x] 1.1 Create `tools/injected-time/` as a standalone component, laid out as
  `tools/frp-grant-admission/` is (`README.md`, `LICENSE`, `pyproject.toml`,
  `Makefile`, `src/injected_time/`, `tests/unit/`), standard library only (D6).
  - Verify: `make -C tools/injected-time build` builds its wheel.
  - Done: distribution `arkhai-injected-time` 0.1.0, import `injected_time`, MIT,
    `requires-python >=3.10` (set in section 3: `kit/identity` and other dependents
    declare `>=3.10`; the source uses nothing 3.11 added, read not run; the structure
    test's `tomllib` needs 3.11 for the suite), no runtime dependency; dev group
    `pytest`, `mypy`. `make test` runs `mypy src --strict` then the suite; `make
    build` writes `dist/` unless given `DIST_DIR`. The README is the interface.
    Locked with `make lock PROJECTS=tools/injected-time` (12 packages, PyPI only).
  - Evidence: built through the root's `dist-injected-time` under `make
    check-packaging` (`arkhai_injected_time-0.1.0-py3-none-any.whl` into `.dist`);
    the default `dist/` output was not exercised.
- [x] 1.2 The process source: `now()` returning Unix seconds; wall by default; an
  injected form frozen at the instant last set, starting at the wall instant it was
  installed; installation from a configured source value, `"wall"` or `"injected"`,
  refusing any other value naming the setting and the value; the forward-only set,
  refusing an earlier instant as `time_moves_forward` and changing nothing (D11, D4).
  - Verify: unit tests: wall reads follow the wall clock; an injected source returns
    the set instant until the next set while real time passes; a backward set is
    refused and the instant is unchanged; `"injectd"` is refused naming it.
  - Done: `injected_time.source` — `WallTime`, `InjectedTime(start=None)` with
    `set(instant)` (a lock makes the forward check and the assignment one step;
    setting the current instant again succeeds), `source_for(value, setting=…)`
    (`InvalidTimeSource` naming both), `install`/`installed`/`now`, `now_datetime()`
    (added in section 3: the instant as an aware UTC `datetime`), and
    `TimeMovesForward` carrying both instants. Both sources take the wall clock
    through their constructor (`wall`, `time.time` by default). "While real time
    passes" is driven by a fake wall clock, not spent (`test-determinism.md`).
  - Evidence: `tests/unit/test_source.py` passes; `make -C tools/injected-time
    test`: 81 passed, mypy clean.
- [x] 1.3 The value rule: one parser for `{"now": <value>}` — a JSON integer from 0 to
  253402300799, never a boolean, float or string, no missing `now`, no other member —
  reporting `invalid_time` (D11).
  - Verify: unit tests for each invalid form (`true`, `1794821400.5`,
    `"1794821400"`, `-1`, `253402300800`, `{}`, an extra member) and the two bounds.
  - Done: `injected_time.value` — `parse_time(raw)` for a JSON body,
    `read_time(document)` for a parsed one, `check_instant(value)` for a bare value,
    all one rule, plus `time_document(instant)`. It also refuses `1794821400.0`,
    `null`, a duplicate member, a non-object, non-JSON, and bytes that are not strict
    UTF-8 (so UTF-16/32 documents too). `tests/unit/test_value.py` passes.
- [x] 1.4 The lane-time file's reader and writer: the writer writes `{"now": …}`
  atomically (a temporary file in the same directory, then a rename); the reader reads
  it on every call through 1.3's parser and raises, naming the file, on a missing,
  unreadable or invalid file (D19).
  - Verify: unit tests: a reader sees each write at its next read; every invalid file
    raises naming its path; a reader never observes a partial write.
  - Done: `injected_time.time_file.TimeFile(path)` — `now()` reads on every call
    (`TimeFileError` naming the path), `write(instant)` writes a temporary file
    beside the target, fsyncs it and `os.replace`s it, removing it on any failure.
    A `TimeFile` is itself a source (`name` `injected`), which the buyer installs.
  - Evidence: library integration `tests/integration/test_time_file.py` passes (in
    `integration/`, not `unit/` as planned, since it uses real files). For "never a
    partial write" it shows an earlier handle still reads the whole previous
    document, nothing is left beside the file, and a failed rename leaves the target
    untouched; the rename's atomicity itself is `os.replace`'s, not shown.
- [x] 1.5 The framework-free route service: a setting request answered
  `{"source": "injected", "now": …}`, refused `409 time_moves_forward` or
  `422 invalid_time` with nothing changed; the status section, `{"source": "injected",
  "now": …}` or `{"source": "wall"}` (D5, D6).
  - Verify: unit tests for each answer and refusal and both status forms.
  - Done: `injected_time.routes.TimeRouteService(source)` — `status()`,
    `set_time(body)` raising `TimeRouteError(status_code, code, detail)`, and
    `settable`, true only for an `InjectedTime` (a binding mounts the setting route
    only then). `set_time` takes the raw body, so non-JSON is 422 `invalid_time` on
    every service. `tests/unit/test_routes.py` passes.
- [x] 1.6 The structure test holding the boundary: no import of a repository package or
  a third-party distribution (`injected-time`'s "The component is standalone").
  - Verify: the structure test passes, and fails on a planted import of `httpx` and of
    `market_identity`.
  - Done: `tests/unit/test_structure.py` passes; the planted imports (`import httpx`,
    `from market_identity import …`, a function-local import) are found in a source
    tree the test writes. It also holds no declared dependency and a PyPI-only lock.
- [x] 1.7 Put the component in the release set and the wheelhouse: declare it in
  `manifests/release-components.json` so `make dist` and `make dist-release` build it;
  add `make test-injected-time` to the root `test` target and the Tests workflow's
  matrix; admit a dependency on it from every architecture layer in
  `docs/development/ARCHITECTURE.toml` (D6).
  - Verify: `make dist` puts its wheel in `.dist`; `make test-injected-time` passes;
    `make check-packaging` passes.
  - Done: first entry of the release declaration; the root's `dist-injected-time` is
    in `dist-release-set` and `dist-ci`; `test-injected-time` follows
    `test-frp-grant-admission` in `test` and `tests.yml`'s matrix. Outside the plan:
    `published-packages.md` gains the component's row now, since
    `test_publish_matrix.py` fails a declared distribution with none.
  - Correction to the plan: no `ARCHITECTURE.toml` edit — `make check-architecture`
    skips `tools/`; instead each package with `allowed-dependencies` lists
    `arkhai-injected-time` there when it declares it (design.md, Implementation
    record). D6 carries the correction (closeout); no such allowance is promoted.
  - Evidence: `make test-injected-time` 80 passed, mypy clean; `make
    check-packaging` passes with the wheel; `make test-release-tooling` 3126 passed.
- [x] 1.8 Section verification.
  - Unit: `make test-injected-time`.
  - `make check-packaging`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`, whose functional checks pass.
  - End-to-end: none; nothing depends on the component yet.
  - Owed by validation: `tests.yml`, job `test · test-injected-time` — the job exists
    and passes.
  - Confirmed: no end-to-end marker exercises the component; the owed job is in a
    workflow `scripts/ci_evidence.py` lists. Pre-commit: functional suites, default
    checks and strict OpenSpec validation passed; only the citations check failed,
    on files sections 2 and 18 create. Against the round's base the new tests fail
    at collection only.

## 2. The wall-time read check and its guidance

Delivers the check and the engineering rule (D20). Implements the check half of
`injected-time`'s "Each process reads the time of the world from one source". Touches
`scripts/check_time_reads.py`, `scripts/tests/`, the root `Makefile`, and
`docs/guidance/engineering/implementation.md`.

- [x] 2.1 Write `scripts/check_time_reads.py`: an AST scan of every project's `src/`
  under `core/`, `kit/`, `domains/`, `provisioning/`, and of the lane doubles under
  `tools/payments-lane-double/`, `tools/mediation-lane-double/` and
  `tools/lane-double-controls/`, refusing `time.time`, `time.time_ns`,
  `datetime.now`, `datetime.utcnow`, `datetime.today`, `date.today`, and
  argument-free `time.gmtime()` and `time.localtime()`, by any import form, naming the
  file and line; `time.monotonic()` and `perf_counter()` are permitted; the
  component's own source is outside its scope (D20). It is runnable as
  `make check-time-reads` and is not yet part of any aggregate target (7.6 joins it).
  - Verify: unit tests in `scripts/tests/test_check_time_reads.py` over synthetic
    sources: each refused form under each import form (`import time`, `from time
    import time`, `from datetime import datetime`, an alias), the permitted forms, and a
    clean file. Run it on the tree and record the count of findings per project in the
    task note, the round's work list.
  - Done: names resolve from every import, function-local ones included; a refused
    read counts called or passed as a value (`clock=time.time`), except
    `gmtime`/`localtime`, refused only with no argument or `None`. Scope: each
    `pyproject.toml` project's `src/` under the four roots (nested projects are their
    own) and the three doubles; `tools/injected-time`, other standalone components
    (the relay plugin runs on wall time, D16), tests and environments are outside.
    Prints `path:line: <form>`, then counts per project, exit 1 on any.
  - Evidence: `scripts/tests/test_check_time_reads.py`, 53 tests over every form,
    import form and alias, the permitted forms, scope and output, passes in `make
    test-release-tooling`. Not caught, none present in scope: star imports, a local
    rebinding, `.now()` on a subclass or instance, uncalled `gmtime`/`localtime` as a
    factory; `time.ctime()`, `time.asctime()`, one-argument `time.strftime` are
    outside the design's list and absent.
  - The round's work list: 207 findings in 37 projects (the design's "about 221"
    counted by text): `core/buyer` 6, `core/registry` 26, `core/registry-client` 3,
    `core/storefront` 31, `core/storefront-client` 4, `domains/apicredits` 2,
    `domains/apicredits/buyer` 2, `domains/apicredits/middleware/python` 2,
    `domains/apicredits/service` 1, `domains/apicredits/storefront` 8,
    `domains/bare_metal/buyer` 1, `domains/bare_metal/provisioning/adapter` 1,
    `domains/bare_metal/storefront` 12, `domains/vms/buyer` 5,
    `domains/vms/negotiation` 1, `domains/vms/provisioning/adapter` 1,
    `domains/vms/storefront` 27, `tools/lane-double-controls` 1, `kit/alkahest` 3,
    `kit/arkhai-mediation` 1, `kit/arkhai-payments` 1, `kit/contact-exchange` 1,
    `kit/deal-lifecycle-buyer` 4, `kit/deal-lifecycle-client` 3, `kit/delivery` 1,
    `kit/fulfillment` 4, `kit/identity` 2, `kit/negotiation-runtime` 1, `kit/policy`
    1, `kit/settlement-runtime` 5, `kit/site` 14, `kit/site-client` 2,
    `kit/storefront` 2, `provisioning/compute` 13, `provisioning/compute/ansible` 2,
    `provisioning/compute/client` 1, `provisioning/compute/service` 12. None in
    `kit/deal-servicing` (its clock parameters have no
    default), `domains/compute/delivery`, `kit/capacity-publication`,
    `kit/pool-overrides`, `kit/resource-pools` or the payments and mediation doubles.
- [x] 2.2 Write the engineering rule in `docs/guidance/engineering/implementation.md`,
  a new section "One time source per process": a process reads the time of the world
  from one time source and nothing else; a duration of its own activity — a timeout,
  a backoff, an interval — is measured on the monotonic clock, which neither stops
  when time is held nor jumps when it is set (D20). Neutral example, no market
  concept.
  - Verify: `make check-guidance` passes.
  - Done: the section sits before "Operator lifecycle controls" (example: a billing
    service's invoice stamp and retry bound) and says a clock parameter defaults to
    the process source for the time of the world and to the monotonic clock for a
    duration; the file's opening, the `implementation` tag's description in
    `docs/guidance/engineering/README.md` and the `check-time-reads` target's comment
    name it. `make check-guidance` passes.
- [x] 2.3 Section verification.
  - Unit: `make test-release-tooling` (the check's tests).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: none; the check reads source only.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `scripts/tests/test_check_time_reads.py` runs and passes.
  - Evidence: `make test-release-tooling` 3179 passed; `make check-guidance` passes;
    `make check-time-reads` reports the work list (exit 1 until 7.5). Pre-commit's
    functional suites passed; only the citations check failed, on a file closeout
    writes (18.9).
  - Confirmed: no end-to-end marker exercises the check; the owed job's
    `test-release-tooling` collects `scripts/tests/`.

## 3. Storefront-side kits and core read the process source

Delivers the conversion (D3) and the read database times (D13) in the shared
libraries the storefronts compose. Implements "Each process reads the time of the
world from one source" and "Database times production logic reads come from the
source" for: `core/storefront` (`sqlite_client.py`, `auth.py`, `heartbeats.py`,
`site_projections.py`, `service_peers.py`, `stage_log.py`), `kit/storefront`
(`lifecycle.py`, `negotiation_watchdog.py`), `kit/deal-servicing` (`diagnostics.py`,
and the `clock` defaults of `EndService`, `DealWatch`, `DeliveryIngress`,
`SellerServicing`, `RespondentPoller`), `kit/settlement-runtime`, `kit/negotiation-runtime`,
`kit/policy`, `kit/delivery`, `kit/contact-exchange`, `kit/fulfillment` (its
scheduler, repository and database defaults), `kit/alkahest`, `kit/arkhai-payments`
(`adapter.py`, `client.py`, the `RateParts` clock default), `kit/arkhai-mediation`
(the adapter's clock default), `kit/identity` (`profiles.py`), and
`domains/compute/delivery` (its clock default).

- [x] 3.1 Each package declares `arkhai-injected-time` and is relocked; each clock
  default (`lambda: int(time.time())` and its kind) becomes the process source, so a
  unit test injecting its own clock keeps working (D3).
  - Verify: each package's unit suite passes unchanged.
  - Done: twelve packages import the component and declare `arkhai-injected-time>=0.1.0`:
    `core/storefront`, `kit/storefront`, `kit/settlement-runtime`,
    `kit/negotiation-runtime`, `kit/policy`, `kit/delivery`, `kit/contact-exchange`,
    `kit/fulfillment`, `kit/alkahest`, `kit/arkhai-payments`, `kit/arkhai-mediation`,
    `kit/identity`; the three with `allowed-dependencies` (`kit/identity`,
    `kit/settlement-runtime`, `kit/contact-exchange`) list it and map `injected_time
    = "arkhai-injected-time"` under `[tool.arkhai.architecture.import-roots]`; every
    `published-packages.md` row names it. `kit/identity` gains the `reinit` target
    `make check-uv-setup` requires; the API-credits wheel-install tests' wheel set
    (`domains/apicredits/tests/conftest_wheels.py`) builds the component. Relocked with `make lock`. Defaults
    now the source: `SettlementRuntime`'s and `AlkahestConditionalEscrowClient`'s
    `clock`, `ClausePublication.clock`, `NegotiationRuntime`'s `now`,
    `IntroductionRetentionService`'s and `AlkahestChainProbe`'s `clock`,
    `StorefrontLoopController`'s outcome stamp, `ServicePeerTrust`'s `clock`, the
    payments adapter's `clock` (the one `RateParts` is given) and the mediation
    adapter's `clock`.
  - Correction to the plan: `kit/deal-servicing` and `domains/compute/delivery` are
    untouched; their clock parameters have no default, so their reads are their
    compositions' (section 4). `kit/arkhai-payments`' `client.py` holds no wall read.
  - "Unchanged" does not hold for eight tests that compared a whole-second source
    read with a sub-second wall read or expected two stamps to differ without time
    moving (design.md, Implementation record); they now drive an injected source:
    three in `core/storefront`'s `test_site_projections.py` (plus a ninth,
    `test_fetched_at_unchanged_on_failed_poll`, which never ran its coroutine and now
    does), four in `kit/settlement-runtime`'s `test_servicing.py`, and `kit/fulfillment`'s
    diagnostics test, moved as a real-database test to
    `tests/integration/test_injected_time.py::test_recovery_diagnostics_count_claims_and_age_rows_against_the_source`.
    The VM and bare-metal storefronts' projection-step tests take an
    `injected_source` fixture in a new `tests/conftest.py` each, 120 s behind wall.
    `kit/fulfillment`'s import-boundary test admits `injected_time`.
  - Versions, outside the plan: `kit/delivery` 0.2.2 and `kit/delivery-apprise` 0.1.2,
    pins moved in `core/buyer` and the VM and bare-metal storefronts; the others were
    already bumped since `marketplace-v0.3.0`. `kit/identity` (0.4.0) and
    `kit/storefront` (0.10.0) take their one minor bump in sections 8 and 9.
- [x] 3.2 Convert every direct read 2.1 lists in these packages: time-of-the-world
  reads to the process source, elapsed-work reads to `time.monotonic()` (D20). Record
  each elapsed-work conversion in the task note.
  - Verify: `make check-time-reads` reports none of these packages.
  - Done: all 53 reads were the time of the world; none became monotonic. Aware
    UTC reads use `now_datetime()`. `core/storefront`'s store stamps text columns
    through public `store_timestamp()` (UTC, no offset, as the stale-negotiation
    sweep already parsed it; the old `datetime.now()` wrote local time);
    `kit/policy`'s message timestamp likewise. Stored leases are lane time (D20):
    the fulfillment claim and poll interval, settlement servicing's retry, the
    storefront's escrow and delivery convergence leases.
  - Outside the plan: queries ordering by a store-written timestamp break ties by
    insertion (`core/storefront`'s escrow, credential, listing and thread lists by
    `rowid`; stage events by `id`); `kit/fulfillment`'s claim order was already whole
    seconds.
  - Evidence: `make check-time-reads` lists none of these packages (154 left).
- [x] 3.3 Supply the read database times in `kit/fulfillment` and in
  `core/storefront`'s `sqlite_client.py` from the process source: ORM `func.now()`
  defaults on read columns become Python `default=`/`onupdate=` callables, raw SQL
  passes the time (D13).
  - Verify: library integration tests, one per store, with an injected source set to
    1794821400: every read column holds that instant, never the database's clock
    (`injected-time`'s "A row is written under injected time").
  - Columns judged read: `kit/fulfillment`'s `settlement_records.created_at`
    (recovery claims oldest first; diagnostics age the oldest row) and
    `provisioned_resources.created_at` (listed in creation order) now default to
    `now_datetime`, beside their kept `server_default`; `claim_expires_at` was
    already supplied by the repository, now from the source. Audit-only, keeping
    `func.now()`: every `updated_at` there and `scheduling_cursors.created_at`.
    `core/storefront`'s store had no SQL time default; its read columns —
    `escrows.created_at`/`updated_at`, `negotiation_threads.created_at`/`updated_at`
    (the sweep compares the latter), `credentials.created_at`,
    `stage_events.ts`, the replay reservation's `lease_until` and a publication's
    `published_at` — are passed by the application, now from the source.
  - Evidence, library integration at 1794821400:
    `kit/fulfillment/tests/integration/test_injected_time.py` (2 tests: both
    `created_at` columns and the claim and progress leases hold the instant;
    diagnostics age rows and lapse claims against the source set an hour forward)
    and `core/storefront/tests/integration/test_injected_time.py` (escrow
    `created_at`/`updated_at`, thread `updated_at`, credential `created_at`, stage
    event `ts`, and the stored text form). Not asserted under injected time:
    `negotiation_threads.created_at` (needs a domain binding), the replay
    reservation's `lease_until`, a publication's `published_at`. `make -C
    kit/fulfillment test` 212 passed; `make -C core/storefront test` 232 passed.
    Against the round's base both fail at collection only.
  - Round-1 triage fix (33 F1): `kit/contact-exchange`'s
    `contact_introductions.created_at`, which the retention sweep filters and orders
    by, is read: `insert_introduction` writes it from the source
    (`format_introduction_timestamp`); the DDL default stays (the v0.3.0 baseline is
    frozen). Audit-only: `contact_introduction_seller_dispatches.claimed_at`.
    Evidence: `kit/contact-exchange/tests/integration/test_injected_time.py` (the
    insert holds the instant; retention keeps the row a second before the window's
    end and redacts it at the end); `make -C kit/contact-exchange test` 147 passed;
    with the insert's `created_at` withdrawn the test fails on the wall instant.
- [x] 3.4 Section verification.
  - Unit and library integration: `make test-kits`, `make test-core`, and
    `domains/compute/delivery`'s suite.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' existing scenarios run these libraries at wall time,
    unchanged in behaviour; no new scenario is owed.
  - Evidence: `make test-kits` passes (`kit/settlement-runtime` 302, `kit/fulfillment`
    212). Pre-commit over sections 3 and 4 together: `make lock`, `make
    check-packaging` and `make test` (every suite) passed; only the citations check
    failed, on a file closeout writes (18.9).
  - Confirmed: no new end-to-end marker; no owed CI evidence (existing jobs).

## 4. The storefronts read the process source

Delivers the conversion (D3, D13) in the three storefront compositions, still on wall
time. Touches `domains/vms/storefront` (`admin_controller.py`, `payment_settlement.py`,
`delivery_lifecycle.py`, `settlement_composition.py`, `utils/sqlite_client.py`,
`utils/zerotier.py`, `middleware/admin_identity.py`, `middleware/service_peer_auth.py`,
`deal_lifecycle.py`, `delivery_records.py`, `publication_binding.py`,
`payment_repository.py`, `failure_actions.py`, `services/listing_source_check.py`,
`services/listing_service.py`, `services/listing_identity_carryover.py`,
`services/fulfillment_resume_runtime.py`), `domains/bare_metal/storefront`
(`runtime.py`, `api.py`, `publication.py`, `negotiation_runtime.py`,
`listing_source_check.py`), `domains/apicredits/storefront` (`listing_binding.py`,
`services/issuance_evidence.py`, `settlement_repository.py`,
`services/listing_service.py`, `utils/sqlite_client.py`), and `domains/apicredits`'
shared package where the storefront reads it.

- [x] 4.1 Each storefront declares `arkhai-injected-time`, relocked; every direct
  read converted as 3.2; the VM storefront's wall-time `EndService` constructions
  (`settlement_composition.py`'s terminal-settlement truncation, `failure_actions.py`'s
  fallback) and `request_delivery_end`'s default read the process source (D3).
  - Verify: `make check-time-reads` reports none of the three storefronts; each
    storefront's suite passes.
  - Done: the three declare `arkhai-injected-time>=0.1.0` (with their
    `published-packages.md` rows), relocked. All 47 reads were the time of the world
    (VM 27, bare metal 12, API credits 8). The VM's two `EndService` constructions,
    `request_delivery_end`'s default and `VmDealLifecycle`'s clock read
    `injected_time.now`; the bare-metal `lifecycle_clock` and
    `source_confirmation_clock` defaults, both listing-source check clocks and the
    API-credits issuance evidence clock are the source. Each writer keeps its text
    form: naive stamps via `store_timestamp()`, aware via `now_datetime()` (a
    listing's columns held both forms before and still do; they sort together).
    `utils/zerotier.py` holds no wall read, untouched. No version bump (all bumped
    since the release; `arkhai-core-storefront>=0.18.0` adds `store_timestamp`).
  - Outside the plan: `vm_delivery_records`' convergence list orders by
    `updated_at, rowid`. `domains/apicredits`' `credits_client.py` is section 6's.
  - Evidence: `make check-time-reads` lists none of the three (107 left);
    `make -C domains/vms/storefront test` 1194 unit (1 skipped) and 606 integration
    passed; `make -C domains/bare_metal/storefront test` 647 passed;
    `make -C domains/apicredits/storefront test` 276 passed.
- [x] 4.2 Supply the read database times in each storefront's stores from the process
  source (D13).
  - Verify: an application-integration test per storefront, through its typed client,
    with the process source injected at 1794821400 for the test: a deal or listing it
    writes holds 1794821400 in every read column.
  - Columns judged read: a listing's `created_at`/`updated_at` (core's lists order
    by the first) and its binding's `last_reconciled_at`, which each storefront's own
    code writes; the VM store's `vm_delivery_records.created_at`/`updated_at` (the
    resume pass orders by the latter) and `processing_lease_until` (its claim
    compares the lease with the store's time); escrows, threads and stage events are
    core's store (3.3). Audit-only or read for presence alone: the API-credits
    issuance progress's `created_at`/`updated_at` and `delivery_started_at` (a refund
    reads only whether it is set), and its issuance evidence's stamps.
  - Correction to the plan: the instant is the wall clock less 120 s, not
    1794821400, since the canonical client still signed on wall time until section 7
    (each suite's `conftest.py` `injected_source` fixture).
  - Evidence, through `StorefrontClient` over ASGI, application integration:
    bare-metal `test_http_publication_settlement.py::test_a_published_listing_holds_the_injected_instant`
    and API-credits `test_alkahest_release_conditions.py::test_a_published_listing_holds_the_injected_instant`;
    narrower for the VM (the listings router over a real `ListingService`, not the
    composed app): `test_listings_api.py::TestCreateListing::test_a_created_listing_holds_the_injected_instant`.
    Each finds the instant in the listing's two columns and `last_reconciled_at`. VM
    store library integration: `tests/integration/test_delivery_record_times.py`
    (stamps and convergence lease follow the source; another worker's claim waits
    until the source passes the lease). A deal's escrow, thread and stage-event
    columns are core's (3.3).
- [x] 4.3 Section verification.
  - Unit and application integration: `make test-domains` (the three storefronts).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' scenarios run the storefronts at wall time; no new
    scenario is owed.
  - Evidence: the suites (4.1); `make test-domains` and pre-commit over sections 3
    and 4 together (3.4): every functional hook passed, only the citations check
    failed, on a file closeout writes.
  - Confirmed: no new end-to-end marker; no owed CI evidence.

## 5. The site and provisioning read the process source

Delivers the conversion (D3, D13) in the site and the provisioning service. Implements
`site-capacity`'s "The site decides by its process's time source" at library level.
Touches `kit/site` (`ledger.py`, `auth.py`, `db.py`, `migrations.py`'s read columns
through the ORM only), `kit/resource-pools` (`db.py`), `kit/site-client`,
`provisioning/compute` (`lease_lifecycle.py`, `jobs/engine.py`, `jobs/db.py`,
`hosts/db.py`, `relays/service.py`, `relays/allocator.py`, `relays/db.py`),
`provisioning/compute/ansible` (`runner.py`), `provisioning/compute/service`
(`services/principal_authority.py`, `services/lease_end_reports.py`,
`services/deal_event_sink.py`, `middleware/rate_limit.py`, `middleware/auth.py`,
`db/models.py`), `provisioning/compute/client`, and the two provisioning adapters'
`services/mock_output.py`.

- [x] 5.1 Each package declares `arkhai-injected-time`, relocked; every direct read
  converted as 3.2. `rate_limit.py`'s window is elapsed work (monotonic); the lease
  watchdog's due check, expiry context and `terminate_lease`'s effective instant read
  the process source (D3).
  - Verify: `make check-time-reads` reports none of these packages.
  - Done: seven packages declare `arkhai-injected-time>=0.1.0`, with their
    `published-packages.md` rows: `kit/site`, `kit/site-client`,
    `provisioning/compute`, `provisioning/compute/client` (its allowlist lists it,
    with the `import-roots` entry section 3 describes), `provisioning/compute/service`
    and the VM and bare-metal provisioning adapters; relocked. 46 reads converted:
    44 time of the world (the ledger's stamps and availability instant; the lease
    watchdog's due check, expiry context, stalled-release grace and
    `terminate_lease`'s effective instant; the job engine's retry time; the relay
    allocator's and service's lease and key stamps; the principal authority; the
    provisioning and site middlewares' verification, response stamp and replay
    lease; the outboxes' attempts and `occurred_at`; both clients' request
    timestamps and freshness reference; the mock outputs), 2 elapsed work (the
    Ansible runner's log-flush interval, now `time.monotonic()`).
  - Correction to the plan: `rate_limit.py` was already monotonic, untouched;
    `kit/resource-pools` holds no wall read (it declares the component since the
    round-1 triage, 5.2); `provisioning/compute/ansible` declares nothing;
    `relays/db.py` and the migrations are untouched.
  - Outside the plan: a retired relay grant key's `grants_valid_until` now counts a
    lease allocated in the retirement's second (`relays/service.py`, `<=`), never
    cutting a grant short (design.md, Implementation record);
    `test_relay_administration.py` holds both sides. Round-1 triage (33 relay-key):
    the change carries the MODIFIED delta in `specs/physical-provisioning/spec.md`,
    "Each relay holds its own grant-signing key", with a same-second scenario.
  - Tests moved to an injected source: `kit/site`'s
    `test_a_first_activation_records_the_site_s_instant_and_moves_nothing` (shared
    `source` fixture in a new `tests/integration/conftest.py`), `kit/site-client`'s
    exact-retry test, five in `provisioning/compute/service`'s
    `test_fulfillment_convergence.py` (a section 3 defect, failing past half a wall
    second). The bare-metal `test_publication_cycle.py` breaks a same-second tie by
    `rowid` (a section 4 defect).
  - Versions: patch bumps `provisioning/compute/ansible` 0.8.1, `kit/site-client`
    0.13.1, bare-metal provisioning adapter 0.13.1; `provisioning/compute/client`
    takes its minor bump in section 10.
  - Evidence: `make check-time-reads` lists none of these packages (61 left).
- [x] 5.2 Supply the read database times — hold expiry, lease end and activation, job
  scheduling and retry timing, relay grant expiry — from the process source (D13);
  audit-only columns keep their DDL default.
  - Verify: library integration tests in `kit/site` with an injected source: a hold
    expiring at 1794822300 lapses on the sweep after the source is set to 1794822300
    and not before (`site-capacity`'s "A hold expires at the set instant"); a lease due
    at an instant is listed due only once the source reaches it.
  - Columns judged read, now defaulting from the source beside their kept
    `server_default`: `kit/site`'s `capacity_buckets.updated_at` (declarations are
    listed in that order) and `capacity_reservations.created_at` (reservations
    listed, and an escrow's latest held one found, in that order); the job
    authority's `ansible_jobs.created_at` (the job list sorts by it); and both
    provisioning outboxes' `created_at` (delivered in that order). Already
    written by the application, now from the source: the ledger's text stamps
    (`hold_expires_at`, `lease_start_utc`, `released_at`, `release_requested_at`,
    `activated_at_utc`), relay leases' `created_at`/`released_at`, keys'
    `retired_at`/`grant_key_activated_at`, `next_retry_at`, the replay
    `dispatch_lease_expires_at`/`completed_at`, a principal's `valid_until`, and the
    outboxes' attempt and delivery stamps. Audit-only, keeping the database
    default: `capacity_buckets.created_at`, `capacity_reservations.updated_at`, the
    debits' two, `ansible_jobs.updated_at`, `credentials.created_at`, `relays`' two,
    the replay reservation's and trusted principal's `created_at`, the rotation
    audit's `applied_at`, the definition imports' `imported_at`. Reported to
    another party, so lane time by `injected-time`'s first requirement (an instant
    sent to another party) though nothing decides by them, now defaulting from the
    source beside their kept `server_default` (round-1 triage fix, 33 F2):
    `capacity_events.occurred_at` (on the capacity feed),
    `hosts.created_at`/`updated_at` (on a host's view) and `resource_pools`' two (on
    a pool's view, `PoolResponse`).
  - Ties: no tie-break added (the lease-end outbox breaks ties by `event_id`; the
    other tables have no insertion-ordered key, and PostgreSQL has no `rowid`); they
    tied by the second under `CURRENT_TIMESTAMP` already.
  - Evidence, library integration, `kit/site/tests/integration/test_injected_time.py`:
    a hold expiring at 1794822300 is kept at 1794822299 and lapsed at 1794822300; a
    lease's start, activation, release request and lease-ended report hold the
    source's instants; a reservation's `created_at` and a declaration's `updated_at`
    too. Correction to the plan: the lease-due test is
    `provisioning/compute/service`'s
    `test_ledger_lease_lifecycle.py::test_a_lease_is_due_only_once_the_process_s_time_reaches_its_end`
    (`list_lease_due` takes its caller's instant): left leased at 1794822299, ended
    by expiry at 1794822300; it failed against the pre-change wheels, as it should.
  - Evidence for the provisioning stores, library integration: `provisioning/compute`'s
    `test_job_authority.py::test_a_job_s_creation_and_retry_are_the_process_source_s_instants`,
    two tests in `test_relay_administration.py` (lease and key stamps; reconciliation
    only past creation plus grace), and
    `provisioning/compute/service/tests/integration/test_injected_time.py` (the
    release-callback outbox's stamps; a replay dispatch lease reclaimed at its expiry,
    not a second before). Not asserted under injected time: the lease-end report
    outbox's stamps, a principal's `valid_until`, a key's `grant_key_activated_at`.
  - Round-1 triage fix (33 F2), evidence, library integration:
    `kit/site/tests/integration/test_injected_time.py::test_the_capacity_feed_reports_the_source_s_instants`,
    `provisioning/compute/tests/integration/test_host_authority.py::test_a_host_s_view_reports_the_process_source_s_instants`
    and `kit/resource-pools/tests/integration/test_injected_time.py` (`PoolResponse`);
    each fails on the database's clock with its source default withdrawn.
    `kit/resource-pools` declares the component, relocked, no bump. The pool columns
    were first left audit-only; the fresh-context check found `PoolResponse`
    carries them, and the disposition gave them the same fix.
  - Outside the plan, on the owner's word (fresh-context D2): `kit/pool-overrides`'
    `created_at`/`updated_at`, returned in `PoolOverride`, are written by `replace`
    from the source in the table's millisecond text form; DDL defaults stay; the kit
    declares the component, relocked, no bump. Evidence:
    `kit/pool-overrides/tests/integration/test_store.py::test_an_override_s_times_are_the_process_source_s_instants`
    (fails on the database clock with the stamps withdrawn);
    `test_replacement_clears_unset_fields_and_keeps_created_at` now moves the source
    a second before replacing.
  - Round-1 triage fix verification (33 F1, 33 F2, 33 relay-key, fresh-context D2):
    `kit/contact-exchange` 147, `kit/site` 370, `provisioning/compute` 536,
    `kit/resource-pools` 142, `kit/pool-overrides` 83 passed; pre-commit passed but
    the citations check (closeout's file, 18.9). Two fresh-context checks: findings
    fixed as above plus nits; declined naming the time source in
    `kit/pool-overrides`' partial dependency header comment.
- [x] 5.3 Section verification.
  - Unit and library integration: `make test-kits` (`kit/site`, `kit/resource-pools`,
    `kit/site-client`), `make test-compute-provisioning`,
    `make test-compute-provisioning-ansible`, `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the lanes' lease and teardown stages run this code at wall time; no
    new scenario is owed.
  - Evidence: `kit/site` 369, `kit/site-client` 65, `provisioning/compute` 535,
    `provisioning/compute/client` 86, `provisioning/compute/ansible` 187 (4 skipped),
    `provisioning/compute/service` 622 unit and 541 integration (its two store tests
    pass on their own), VM adapter 292, bare-metal adapter 137. Pre-commit: every
    functional suite passed; only the citations check failed (18.9).
  - Fresh-context check: its findings (relay wording, untested read columns,
    evidence wording, classification of reported-only columns, a `create_all`
    schema, a stale docstring) were fixed. Declined: moving the lease-due test out of
    the service suite, whose file holds the lifecycle's library integration tests.
    `domains/vms/negotiation`'s `time.localtime()` was left to 7.5.
  - Confirmed: no new end-to-end marker; no owed CI evidence.

## 6. The registry and the API-credits service read the process source

Delivers the conversion (D3, D13) in the registry, the API-credits service and the
metering middleware. Touches `core/registry` (`api/listing_routes.py`,
`api/api_key_auth.py`, `api/utils.py`, `api/publisher_auth.py`,
`api/publisher_routes.py`), `domains/apicredits/service` (`db/models.py` and the site
ledger it hosts), `domains/apicredits/src/arkhai_apicredits/settlement/credits_client.py`,
and `domains/apicredits/middleware/python` (`signing.py`, `gate.py`).

- [x] 6.1 Each package declares `arkhai-injected-time`, relocked; every direct read
  converted as 3.2; the middleware reads the process source its host installs for
  every timestamp it signs and every response it verifies, with no control of its own
  (D18).
  - Verify: `make check-time-reads` reports none of these packages; their suites pass.
  - Done: four packages declare `arkhai-injected-time>=0.1.0`, with their
    `published-packages.md` rows: `core/registry`, `domains/apicredits` (the
    credits client's package), `domains/apicredits/service`, and the Python
    middleware as a base dependency (its signing module is on every path; the
    component is standard library only). Relocked. 31 reads, all the time of the
    world: the registry's 26 (request verification, response stamp, replay lease,
    rotation proofs and deadlines, status comparisons, API keys' stamps, a listing's
    `updated_at`, every model default, now `core_registry.db.models.utcnow`, naive
    UTC); the credits client's and the middleware's two each; the credits service's
    model default. Status comparisons go through `api/utils.py`'s
    `instant_comparable_with`, keeping the stored deadline's naive or aware form. The
    hosted site ledger reads the source through `kit/site`.
  - Outside the plan, ties broken: the registry's listings by `listing_id`,
    publishers by `publisher_id`, API keys by `id`; the credits service's keys by
    `key_id`.
  - Versions: the middleware 0.1.2 (patch); `domains/apicredits` takes its minor bump
    in section 11; the registry and credits service were already bumped.
  - Evidence: `make check-time-reads` lists none of these packages (30 left).
- [x] 6.2 Supply the read database times in the registry and the credits service from
  the process source (D13).
  - Verify: an application-integration test in each, with the source injected: a
    listing the registry stores, and a grant the credits service issues, hold the
    injected instant in every read column.
  - Columns: neither store has an SQL time default; every time was already written
    by the application, and now comes from the source. Read: the registry's
    `listings.created_at` (listings are ordered by it), `publishers.created_at`
    (likewise), `identities.created_at` (active principals sorted by it), a replay
    reservation's `lease_expires_at` (compared), a rotation's `retire_at` and an
    identity's `active_until` (compared), `api_keys.created_at` (ordered); the
    credits service's `api_keys.created_at` (ordered). Reported or audit, supplied
    alike: the registry's `updated_at`s, `completed_at`, `applied_at`,
    `retired_at`, `revoked_at`; the credits service's `updated_at`, `granted_at`
    and `occurred_at`.
  - Evidence, application integration: `core/registry/tests/integration/test_injected_time.py`,
    the running registry through `RegistryClient` (source 120 s behind wall; schema
    from ORM metadata, no SQL default in play): a listing's, publisher's, identity
    binding's and replay reservation's stamps hold the instant, and a republish moves
    only `updated_at`; a rotation stores `applied_at`, and `retire_at`/`active_until`
    300 s later, the identity in overlap a second before and retired at it; API keys
    minted and revoked through the store hold the instant. Not asserted: the replay
    lease, cleared on completion. `domains/apicredits/service`'s
    `test_signed_authority.py::test_a_grant_and_its_spending_hold_the_injected_instant`
    at 1794821400 (hours from wall, so it also shows the credits client and the
    middleware sign and verify by the source): `granted_at`, the key's stamps and a
    consumption's `occurred_at`.
- [x] 6.3 Section verification.
  - Unit and application integration: `make test-registry`, and `make test-domains`
    (the API-credits service and the Python middleware).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the API-credits lane's purchase runs this code at wall time; no new
    scenario is owed.
  - Evidence: `make -C core/registry test` 153 unit, 164 integration; `make -C
    domains/apicredits test` (domain 41, service 81, storefront 276, buyer 35, sample
    app 1, Python middleware 8, TypeScript 5, Rust 6). Pre-commit: every functional
    suite passed; only the citations check failed (18.9). `run test-before` not run
    (the new tests would fail at collection only).
  - Fresh-context check: its findings (untested registry columns, placeholder
    evidence, an overbroad claim, two docstrings) were fixed. Declined: bumping
    `domains/apicredits` now, left to section 11.
  - Confirmed: no new end-to-end marker; no owed CI evidence.

## 7. The buyer side and the signing clients read the process source; the check is on

Delivers the conversion (D3) in the buyer and the signing clients, converts the
doubles' direct reads with their behaviour unchanged, and switches the check on
(D20). Touches `core/buyer` (`negotiation_client.py`, `orchestration.py`,
`run_log.py`, `profile_service.py`), `kit/deal-lifecycle-buyer` (`watchdog.py`,
`commands.py`, `lifecycle.py`), the domain buyers (`domains/vms/buyer`'s
`arkhai_payments.py`, `service_cli.py`, `negotiate_cli.py`, `introduction_cli.py`,
`buy_cli.py`; `domains/bare_metal/buyer`'s `cli.py`; `domains/apicredits/buyer`'s
`negotiate_cli.py`, `buy_cli.py`), the signing clients (`core/storefront-client`'s
`auth.py`, `client.py`; `core/registry-client`'s `auth.py`, `client.py`;
`kit/deal-lifecycle-client`'s `client.py`),
`tools/lane-double-controls`' `lane_double_controls.clock` (removed by section 13),
the doubles' direct reads, the root `Makefile`, and
`docs/guidance/repository/packaging-checks.md`.

- [x] 7.1 Each buyer package and client declares `arkhai-injected-time`, relocked;
  every direct read converted as 3.2; the watchdog's probe staleness is lane time, its
  probe interval and timeouts elapsed work (D3, D20).
  - Verify: `make check-time-reads` reports none of these packages; `make test-core`,
    `make test-kits` and the buyers' suites pass.
  - Done: nine packages declare `arkhai-injected-time>=0.1.0`, with their
    `published-packages.md` rows: `core/buyer`, `core/storefront-client`,
    `core/registry-client`, `kit/deal-lifecycle-buyer` and
    `kit/deal-lifecycle-client` (both list it and map `injected_time` under
    `import-roots`), the VM, bare-metal and API-credits buyers, and, outside the
    plan, `domains/vms/negotiation`. Relocked. 29 reads, all the time of the world:
    request timestamps and response freshness references, rotation intents' expiry,
    every proposed `expiration_unix`, the heartbeat loop's expiry check and sleep,
    the run log's stamp, the buyer lifecycle's and evidence pruning's clocks, the
    watchdog's probe and stop stamps, and the RL strategy's time-of-day feature
    (`time.localtime(injected_time.now())`). The watchdog's interval, timeout and
    stop retry were already monotonic; its staleness compares lane-time
    `last_probe_at` with the lifecycle's clock, now the source. A response's
    freshness reference and its capture's `verified_at` are now one read.
  - Versions: `kit/deal-lifecycle-client` 0.1.1 (patch); `core/storefront-client`
    takes its minor bump in section 9; the others were already bumped.
  - Tests that patched a module's `time.time` now install an injected source:
    `core/buyer`'s `test_identity_http.py`, `core/storefront-client`'s admin,
    lifecycle, negotiate and close-listing tests (a `held_time` fixture); the
    close-listing fake storefront signs at the request's timestamp.
  - Evidence: `kit/deal-lifecycle-buyer`'s
    `test_watchdog.py::test_probes_are_stamped_from_the_process_source_and_scheduled_while_it_is_held`
    (unit) and, library integration over the SQLite evidence file,
    `test_watchdog_journal.py::test_the_loop_journals_its_probes_and_stop_at_the_process_source_s_instant`
    and `test_watchdog_journal.py::test_the_read_judges_a_probe_s_staleness_at_the_process_source_s_instant`.
    `make check-time-reads` lists none of these packages; `kit/deal-lifecycle-buyer`
    52, `core/buyer` 172, VM buyer 334, bare-metal buyer 84, API-credits buyer 35
    passed. The RL strategy's line is read, not run (its test skips without `torch`).
- [x] 7.2 The signing clients take every request timestamp and every response
  freshness reference from the process source (`marketplace-identity`'s "Signing and
  verification read the process source").
  - Verify: unit tests in `core/storefront-client`, `core/registry-client` and
    `kit/deal-lifecycle-client` with an injected source at 1794822300: a signed
    request carries 1794822300, and a response stamped 1794822300 verifies.
  - Done: unit, `test_process_time_source.py` in each of the three: with the source
    held at 1794822300 (far behind the wall clock), a request carries it (envelope
    and header; header only for the lifecycle client, via `end_delivery` over
    `httpx.MockTransport`), a response stamped then verifies with no reference, and
    is refused `timestamp_skew` once the source is 301 s past it. `core/storefront-client`
    71, `core/registry-client` 28, `kit/deal-lifecycle-client` 4 passed; against the
    base they fail at collection only.
- [x] 7.3 Supply the buyer's read database or file times (its run log and buyer state)
  from the process source (D13).
  - Verify: a buyer test under an injected source finds the injected instant in the
    run log's read fields.
  - Done: the run log's `ts` (reported by `list_runs` as `started_at` and
    `last_event_ts`) is the source's instant, aware UTC ISO, no fraction. `list_runs`
    keeps ordering by file modification time, which carries no instant out (its
    docstring says why). No buyer store has an SQL time default. Read: the watchdog
    journal's probe instants (asserted by 7.1's integration tests). Not asserted
    under injected time: the end journal's `observed_at` and the evidence store's
    `recorded_at`, both now the source by default.
  - Evidence: library integration, `core/buyer/tests/integration/test_run_log_times.py`
    (instants at 1794821400 and 60 s on), in `make -C core/buyer test` (172).
  - Outside the plan: `core/buyer`'s `make test` and `testpaths` now run
    `tests/integration` too, which had never run.
- [x] 7.4 The doubles' direct reads go through the component's wall source:
  `lane_double_controls.clock`'s `wall_clock` and any direct read in the two
  doubles; their offset clocks stay until section 13.
  - Verify: `make test-lane-double-controls`, `make test-payments-lane-double` and
    `make test-mediation-lane-double` pass unchanged.
  - Done: `wall_clock` reads a module-level `injected_time.WallTime` (explicitly
    wall, not the installed source); `tools/lane-double-controls` declares the
    component (unpublished, no row) and the doubles are relocked. The doubles held no
    direct read of their own. Tests unchanged: `make test-lane-double-controls` 120
    (mypy strict clean), `make test-payments-lane-double` 84, `make
    test-mediation-lane-double` 73.
- [x] 7.5 Make sure nothing is left: run `make check-time-reads` on the tree.
  - Verify: it reports no finding.
  - Done: `make check-time-reads` prints "OK: no direct wall-clock read in production
    source or the lane doubles."
- [x] 7.6 Switch the check on: `make check-packaging` runs `check-time-reads`, and
  `docs/guidance/repository/packaging-checks.md`'s "Checks" table gains its row (D20).
  - Verify: `make check-packaging` passes, and fails on a planted `time.time()` in a
    kit.
  - Done: `check-time-reads` is the last check `check-packaging` runs; the table's
    row names what it refuses, its scope and what passes, citing
    `implementation.md`. No CI workflow runs `check-packaging`: the check runs in the
    pre-commit hook and closeout's packaging part.
  - Evidence: a planted `time.time()` in `kit/deal-lifecycle-buyer`'s `commands.py`
    failed `make check-packaging` at `check-time-reads`, naming file, line and
    project; removed. The passing run is 7.7's.
- [x] 7.7 Section verification.
  - Unit and integration: `make test`.
  - `make check-packaging`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes, every module at wall time, as regression evidence
    for round one; no new scenario is owed.
  - Evidence: pre-commit on the final tree: `make lock`, `make check-packaging` (its
    `check-time-reads` "OK") and `make test` passed; only the citations check
    failed (18.9).
  - Confirmed: no end-to-end marker new or changed; validation's lane run is the
    round's regression evidence. No owed CI evidence.
  - Fresh-context check: its findings (test comments on "hours from the wall
    clock", a watchdog docstring, an untested journal store, four overbroad evidence
    claims) were fixed or reworded. Declined: moving `kit/deal-lifecycle-client`'s
    test into `unit/` (its tests sit in a flat `tests/`; a change-index row if the
    owner wants it). Permanent-documentation destination: closeout (18.9) restates
    `openspec/specs/buyer-orchestration/architecture.md`'s watchdog paragraphs
    (probe stamps and staleness "on the wall clock") in the process source's terms.

## 8. The time-setting operation's freshness exemption

Delivers D14. Implements `marketplace-identity`'s "The time-setting operation is
exempt from request freshness" and the modified "Body-bound authenticated request and
response version". Touches `kit/identity` (`verification.py`), and the signed
administrator surfaces that will mount the setting route: `core/storefront`
(`auth.py`), `domains/vms/storefront` (`middleware/admin_identity.py`), the bare-metal
storefront's authentication in `api.py`, `provisioning/compute/service`
(`middleware/auth.py`), and `kit/site` (`auth.py`, the API-credits service's
middleware).

- [x] 8.1 `market_identity` verifies a request without the timestamp's freshness only
  when its caller names the operation as the time-setting one; signature, principal,
  context, body hash and the request-id reservation are verified as for every request
  (D14).
  - Verify: unit tests: a setting request 900 s off the verifier's instant verifies;
    the same skew on any other operation is refused `TIMESTAMP_SKEW`; a changed body,
    a wrong principal or a reused request id is refused on the setting operation.
  - Done: `verify_request(..., time_setting_operation=None)` skips the skew check
    only when the named operation equals `expected_operation` (the context check
    already holds the signed operation to the route's); everything else is
    unchanged. Unit, `kit/identity/tests/unit/test_envelopes.py`:
    `test_the_time_setting_operation_alone_is_verified_without_freshness` and
    `test_the_time_setting_operation_is_otherwise_verified_as_every_request`.
    `make -C kit/identity test` 168 passed (at the base the keyword does not exist).
  - Versions: `kit/identity` 0.5.0, its 26 exact pins moved, `kit/site`'s lower
    bound 0.5.0. Taking their one minor bump here, as their pins moved:
    `core/storefront-client` 0.30.0, `kit/storefront` 0.11.0,
    `provisioning/compute/client` 0.11.0, `domains/apicredits` 0.10.0 (sections
    9–11 add APIs within them). Relocked; `make check-version-bumps` passes.
    `core/storefront-client/README.md`'s pins name 0.30.0 and 0.5.0.
  - Round 2 triage (O1), revised by round 3 (61 O1), outside the plan: the identity
    wheel's version is no longer copied by hand; `dist-identity` calls
    `kit/identity`'s own `build` like every other wheel target (no
    `IDENTITY_VERSION`/`IDENTITY_WHEEL`); `scripts/package-review-wheelhouse.sh`
    reads the version from `kit/identity/pyproject.toml`, refusing one missing, and
    its test follows a changed version. Evidence under 15.4's round 3 note.
- [x] 8.2 Each signed administrator surface above applies the exemption to its
  time-setting operation alone — the storefronts' `admin_time`, provisioning's and the
  credits service's setting operation — and to no other route (D14).
  - Verify: unit tests per middleware: the setting operation is admitted skewed; the
    pause operation skewed by the same amount is refused.
  - Done: `core_storefront.auth` defines `ADMIN_TIME_OPERATION = "admin_time"`,
    `ADMIN_TIME_RESOURCE = "time"`, passes `time_setting_operation` through
    `authenticate_request`, and offers `admin_time_setting_operation()`: `admin_time`
    while the installed source is settable (D12), else `None`. The VM administrator
    middleware binds `POST /api/v1/admin/time` to that contract; the bare-metal
    `_admin` and the API-credits `authenticate_admin` pass the helper's answer on
    every administrator request. `ProvisioningAuthMiddleware` and `kit/site`'s
    `SiteAuthMiddleware` take `time_setting_operation` in their constructor and,
    since section 10, exempt it only while the installed source is settable, so a
    wall-time process exempts nothing.
  - Evidence. Unit: `core/storefront`'s `test_auth.py`. Provisioning
    `tests/unit/middleware/test_auth.py` (the real middleware over in-memory SQLite;
    placement predates the section): named and injected, the setting is admitted
    at ±900 s and the lease-watchdog pause refused for skew; unnamed, or under wall
    time, refused. Library integration: `kit/site`'s `test_site_auth_middleware.py`.
    Storefronts, in-process over the real administrator authentication with raw
    requests built by `build_authenticated_request` (the client cannot sign
    skewed), statuses only: VM `tests/integration/test_admin_api.py`, bare metal
    `tests/test_http_system.py` (since section 9 through the real route: 900 s
    ahead 200, 900 s behind 409, trading left open; the stand-in only under wall
    time), API credits `tests/integration/test_trading_pause_api.py`. Section 8's
    suites: `kit/site` 373, `core/storefront` 232 (+ its unit tests), provisioning
    middleware 56, VM 609 integration and unit, bare metal 650, API credits 279.
- [x] 8.3 Section verification.
  - Unit: `make test-kits` (`kit/identity`, `kit/site`), `make test-core`, the
    storefronts' and `make test-provisioning`'s middleware tests.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: exercised by section 15's fixture once the lanes run injected
    (section 16).
  - Evidence: the suites in 8.1 and 8.2; pre-commit on the final tree: every
    functional suite passed; only the citations check failed (18.9).
  - Confirmed: no end-to-end marker exercises the exemption yet; section 15's
    fixture is its first caller. No owed CI evidence.
  - Fresh-context check: its findings (unexplained raw requests, test-level
    naming, comments ahead of section 9, trading-open unchecked, stale README pins,
    the two exemption forms unexplained) were fixed. Declined: defining the
    operation name where the client can import it (administrator operations are
    spelled in each storefront and the client today); moving the provisioning
    middleware tests out of `tests/unit/`; the bare-metal stand-in calling private
    `_admin` (section 9's real route supersedes it).

## 9. The storefronts' setting, route, status and warning

Delivers D2, D5, D12 for the storefronts. Implements `market-composition`'s
"Storefront time is configured and set through one kit route service" and
`injected-time`'s "An injected process announces its time" and "An instance's time is
changed only under injected time". Touches `kit/storefront` (a time route service
beside `trading_pause.py`), `core/storefront` (`models/system_models.py`, the system
status), the three storefronts' configuration models, composition roots and admin
bindings (`domains/vms/storefront`'s `controllers/admin_controller.py`,
`middleware/admin_identity.py`; `domains/bare_metal/storefront`'s `config.py`,
`api.py`; `domains/apicredits/storefront`), their generated values schemas
(`values_schema.py` and the charts' schemas it writes), and `core/storefront-client`.

- [x] 9.1 Each storefront reads `[Time] source`, `"wall"` by default, refusing any
  other value naming it, and installs the process source at its composition root
  before anything reads time (D2).
  - Verify: unit tests per storefront configuration; an application-integration test
    that a storefront started with `"injectd"` refuses to start naming it.
  - Done: `kit/storefront`'s new `time_controls` module holds what the three share:
    `TIME_SOURCE_SETTING = "[Time] source"`, `install_time_source(value)`,
    `TimeSourceSetting` (a pydantic `Literal["wall", "injected"]` refusing other
    values with the component's message; the kit declares `pydantic>=2.7`), and
    `configured_time_source(settings)`, reading the raw setting in any key case;
    each storefront passes it its own settings. Each installs the source at module
    level in `server.py` before the `app` is built; a misspelled value raises
    `InvalidTimeSource` at import. The bare-metal typed settings gain `time:
    TimeSettings`, the VM a `TimeConfigDeclaration`; the API-credit storefront has
    no chart or typed model.
  - Evidence. Unit: `kit/storefront`'s `tests/unit/test_time_controls.py`, VM
    `tests/unit/test_config_loader.py`, bare metal `tests/test_config_loader.py`,
    API credits `tests/unit/test_time_settings.py`. The refused start: each
    storefront's `test_time_controls.py` imports its `server` in a subprocess with
    `"injectd"` through the override layer and finds a non-zero exit naming setting
    and value — a process start before any app exists, so not application
    integration as the plan named.
- [x] 9.2 `kit/storefront` gains the framework-free time route service over the
  component's (1.5); each storefront binds it at `POST /api/v1/admin/time` behind its
  administrator authentication, mounted only under injected time (D5, D12).
  - Verify: application-integration tests per storefront through the canonical
    client: set to 1794822300 answers source `injected` and now 1794822300 and the
    storefront's signed responses then carry 1794822300; an earlier instant answers
    `409 time_moves_forward`; `{"now": true}` answers `422 invalid_time`; a wall-time
    storefront serves no such route.
  - Done: `StorefrontTimeRouteService(source=None)` over the component's
    `TimeRouteService` (`mounted`, `status()`, `set_time(body)`), and
    `time_refusal_body(error)` (`{"code", "detail"}`). Each storefront mounts its
    own router only when `mounted`: VM `admin_controller.time_router` behind the
    administrator middleware, bare metal `api.time_router` through `_admin`, API
    credits `controllers/time_controller.py` through `authenticate_admin`. The raw
    body goes to the route service; the response middleware signs the answer at
    the new instant.
  - Evidence, application integration, each storefront's `test_time_controls.py`
    over its composed app through `StorefrontClient`, source injected at
    1794822300: `set_time(1794823200)` answers and is signed at 1794823200 (moved
    past the plan's instant to show the move); 1794822300 raises 409; `True` raises
    422, instant unchanged; wall source 404. Bare metal and API credits also refuse
    an untrusted principal 403 (the VM's middleware trust is held by section 8's
    and existing tests).
- [x] 9.3 The signed system status, `GET /api/v1/system/status`, carries the time
  section in both modes; the canonical client's `get_system_status` reads it and gains
  `set_time` (D5).
  - Verify: application-integration tests for both modes through the client, for the
    VM and the bare-metal storefront at the same path and shape (`market-composition`'s
    "Both compute storefronts bind one route").
  - Done: `core_storefront`'s `HealthResponse` and `BareMetalHealthResponse` gain
    `time: dict | None`, set on system status (not liveness). The client's
    `HealthResponse` reads it; `StorefrontClient.set_time(now)` and the sync one
    post `{"now"}` signed `admin_time`/`time`, returning `TimeSettingResponse`.
  - Evidence: unit, `core/storefront-client`'s `test_health_response.py` and
    `test_time_setting.py`; the VM's `test_storefront_client_parity.py` holds sync
    and async signatures. Application integration, the three storefronts' tests
    above: status in both modes, before and after a set; VM and bare metal read the
    same path and shapes.
- [x] 9.4 Startup announcement and warning: an injected storefront logs its source at
  startup; one with an Arkhai payments section whose `livemode` is `true` logs a
  warning naming both settings, and starts (D2).
  - Verify: application-integration tests capture both log lines.
  - Done: `announce_time_source(source, payments_livemode=..., logger=...)` logs
    nothing for wall time; for injected time an INFO line naming `[Time] source`
    and the held instant, and, with live payments, a WARNING naming `[Time]
    source` and `[Settlement.arkhai_payments] livemode`. Each storefront calls it
    in its lifespan's start with its payments mode, read by
    `market_arkhai_payments.payments_livemode(settlement)` (`True` only for a
    payments section stating `livemode = true`); bare metal stores it in a new
    runtime field `payments_livemode`. Lower bounds raised: API credits on
    `kit/arkhai-payments` 0.8.0, the three on the client 0.30.0.
  - Evidence: unit, the kit's tests and `kit/arkhai-payments`'
    `test_settlement_config.py`. Application integration, each storefront's
    `test_time_controls.py`: started injected with live payments, `caplog` holds
    both lines and status serves. Bare metal builds its runtime with
    `payments_livemode=True`; its builder's read is shown by
    `test_config_loader.py`, the builder's call itself not run by a test.
- [x] 9.5 Regenerate the storefronts' values schemas so the charts admit `[Time]`.
  - Verify: `make -C helm test-render` passes.
  - Done: `make helm-values-schema` wrote `helm/values.schema.json`,
    `helm/charts/storefront/values.schema.json` and
    `helm/charts/bare-metal-storefront/values.schema.json`, each admitting
    `time.source` as `"wall"` or `"injected"` (any case, `null` accepted as
    everywhere). The umbrella and both storefront charts move 0.4.1 → 0.5.0 with the
    umbrella's pins. Each storefront chart's render test gains
    `test_the_time_source_is_admitted_as_wall_or_injected_and_refused_otherwise`.
    `make -C helm test-render` passes; the drift tests (`test_values_schema.py`)
    pass.
- [x] 9.6 Section verification.
  - Unit and application integration: `make test-kits` (`kit/storefront`),
    `make test-core` (`core/storefront`, `core/storefront-client`),
    `make test-domains` (the three storefronts).
  - `make -C helm test-render`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets every storefront through this route once
    section 16 puts the lanes on injected time.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
    chart render tests pass with the regenerated schemas.
  - Evidence: `kit/storefront` 141, `kit/arkhai-payments` 354,
    `core/storefront-client` passed, VM 1196 unit (1 skipped) and 613 integration,
    bare metal 658, API credits 285, `make -C helm test-render` passed. Pre-commit on
    the final tree: functional suites passed; the citations check failed (18.9), and
    the local-imports check flagged the payments test's import, now at module level
    (`make check-local-imports CHANGE_BASE=dev` passes).
  - Confirmed: no end-to-end marker exercises the route yet; the owed job runs
    `make -C helm test-render`.
  - Fresh-context check: its findings (untested route authentication, overstated
    claims, a duplicate parity test, repeated rule tests, the `livemode` and
    `[Time] source` reads written three ways, low client bounds, no render test)
    were fixed. Declined: spelling the operation, resource and path once (the
    client cannot depend on the storefronts' core, nor the reverse).

## 10. Provisioning's setting, route and status

Delivers D2, D5, D12 for the provisioning service. Implements `physical-provisioning`'s
"Provisioning time is configured and set on its system surface" and, at application
level, `site-capacity`'s "The site decides by its process's time source". Touches
`provisioning/compute/service` (`config.py`, `main.py`, `app_runtime.py`,
`controllers/system_controller.py`, the system status), and
`provisioning/compute/client`.

- [x] 10.1 The service reads `time.source`, `"wall"` by default, refusing any other
  value naming it, installs the source at startup, logs it when injected, and mounts
  `POST /api/v1/system/time` behind its administrator authentication only under
  injected time; `GET /api/v1/system/status` carries the time section (D2, D5, D12).
  - Verify: application-integration tests through the provisioning client: set,
    `409 time_moves_forward`, `422 invalid_time`, status in both modes, no route under
    wall time, `"injectd"` refused.
  - Done: `Settings.configured_time_source` reads `time.source` (keys in any case;
    a non-table `time` states none); `main.py` installs it at module level before
    the app is built (a misspelled value refuses the import) and mounts
    `make_time_router()` (`controllers/system_controller.py`) only under injected
    time; the lifespan calls `announce_time_source` (no payments section, no
    warning). The family contracts declare `PROVISIONING_TIME_OPERATION`
    (`provisioning_system_time`), administrator only, `TimeSettingResponse` and
    `SystemStatusResponse.time`; the middleware exempts it only while injected.
    Under wall time the contract stays in the table, so a signed request finds no
    route, a signed 404; the handler guards 404 over an unsettable source.
  - Evidence. Unit, `tests/unit/test_time_source.py`; `test_route_binding.py`
    counts the time router as mounted. Application integration,
    `tests/integration/test_system_time.py` through `ComputeProvisioningClient`
    (router mounted on the shared app via `mount_unless_served`): status, set, 409
    with its detail, 422, and under wall time `{"source": "wall"}` and 404 (the
    guard's here; routing's in production). Process starts: `"injectd"` exits with
    the component's exact refusal, and (added in section 11)
    `test_the_composition_mounts_the_time_route_only_under_injected_time` reads the
    OpenAPI document under each source. Not asserted: the answer's signed
    timestamp exactly, the refusal `code` (the client does not surface it). `make
    -C provisioning/compute/service test-integration` 550 passed.
- [x] 10.2 The lease watchdog and the site follow injected time: a lease truncated to
  1794822300, the watchdog paused, the service set to 1794822300 and one watchdog cycle
  stepped, ends by expiry with effective instant and claimed deadline 1794822300; a
  termination under injected time states the injected effective instant
  (`physical-provisioning`'s scenarios).
  - Verify: application-integration tests through the provisioning client, mock
    executor.
  - Done, application integration, `test_system_time.py`: a lease committed
    through the ledger (no route commits one), truncated to 1794822300 through the
    site client, the source at 1794822240 and the watchdog paused; a step releases
    nothing; after `set_time(1794822300)` the next step releases it, and the
    seller-signed lease read returns one verified lease-ended report, cause
    `expiry`, effective instant and claimed deadline 1794822300. A seller
    termination after the set reports `termination` at 1794822300. 5.2's library
    test stays.
- [x] 10.3 The client gains `set_time` and the status time section.
  - Verify: `make test-compute-provisioning-client`.
  - Done: `ComputeProvisioningClient.set_time(now)` and the sync form, and
    `get_system_status` parsing the section; contracts bound 0.14.0. Unit,
    `tests/unit/test_client.py::test_the_time_setting_answers_its_model`; `make -C
    provisioning/compute/client test` 88 passed.
- [x] 10.4 Section verification.
  - Application integration: `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets provisioning once section 16 puts the lanes
    on injected time; serve-running's funds-exhausted rows exercise 10.2's path.
  - Evidence: `provisioning/compute/service` 634 unit and 548 integration,
    `provisioning/compute/client` 88, `provisioning/compute/contracts` 157,
    `kit/site` 374, `kit/storefront` 141. Pre-commit on the final tree: functional
    suites passed; only the citations check failed (18.9).
  - Confirmed: no end-to-end marker exercises the route yet; no owed CI evidence.
  - Fresh-context check: its findings (route mounted in both modes against the
    delta, now injected only; a scalar `time` read as the source, here and in the
    kit; untested reads; test placement; refusal assertions; the lease truncated
    straight in the ledger; contracts exports; wall tests on the default source)
    were fixed. Declined: moving the middleware tests out of `tests/unit/`; writing
    the "exempt only while injected" rule once (one expression per package over
    `TimeRouteService(...).settable`, no shared dependency but the component);
    importing `_committed` and `seller` from `test_leases_api`.

## 11. The registry's and the API-credits service's setting, route and status

Delivers D2, D5, D12 for the registry and the credits service. Implements
`registry-discovery`'s "Registry time is configured and set on its administrator
surface" and `api-credits`' "Credits service time is configured and set by its
administrator". Touches `core/registry` (`config.py`, `api/admin_routes.py`, its app
assembly), `core/registry-client`, `domains/apicredits/service` (`config.py`,
`main.py`, its route contracts), and the credits service's client
(`domains/apicredits/src/arkhai_apicredits/settlement/credits_client.py`).

- [x] 11.1 The registry reads `TIME_SOURCE`, `"wall"` by default, refusing any other
  value naming it; installs the source and logs it when injected; serves
  `GET /admin/status` with the time
  section in both modes and, under injected time only, `POST /admin/time`, both behind
  `REGISTRY_ADMIN_API_KEY` as its other `/admin` routes are (D2, D5).
  - Verify: application-integration tests through the registry client: set, 409, 422,
    a missing or wrong key refused `401` with the time unchanged, status in both modes,
    no setting route under wall time; a storefront publication signed at the injected
    instant is accepted after both are set 1800 s forward.
  - Done: `Settings.time_source` (`TIME_SOURCE`); `main.py` installs it at module
    level before the app is built, mounts `admin_routes.make_time_router()` (`POST
    /admin/time`) only under injected time, and announces it in the lifespan.
    `admin_routes.status_router` serves `GET /admin/status` in either mode; both
    sit behind `require_admin_api_key`, unsigned, refusals `{"code", "detail"}`;
    the time route guards 404 over an unsettable source. The registry chart is
    untouched (wall default; the lanes are Compose stacks).
  - Evidence. Unit, `core/registry/tests/unit/test_time_source.py`. Application
    integration, `tests/integration/test_admin_time.py` through `RegistryClient`
    with the key: status, `set_time(T + 1800)`, 409 and 422 with their codes, an
    empty or wrong key 401 with the source unchanged, wall-time status and 404; a
    seller-signed `publish_listing` at T + 1800 is accepted, `created_at` T + 1800.
    Process starts: `TIME_SOURCE` `injected` serves the route, `wall` does not;
    `injectd` exits with the exact refusal. `make -C core/registry test` 155 unit,
    172 integration.
- [x] 11.2 The credits service reads `time.source`, refusing any other value naming
  it, installs the source, logs it when injected, so the site ledger it hosts follows
  injected time (`site-capacity`'s "The site decides by its process's time source"),
  and serves
  `GET /api/v1/system/status` (signed, `admin`) in both modes and, under injected time
  only, `POST /api/v1/system/time` (signed, `admin` only), both with route contracts
  beside its others (D2, D5, D14).
  - Verify: application-integration tests through the credits service's client: set
    from 1794822300 to 1794823200 answers signed at 1794823200 and the status agrees; a
    `service`-role setting request is refused unauthorized with the time unchanged; 409
    and 422.
  - Done: `Settings.configured_time_source` (`time.source`); `main.py` installs it
    at module level, mounts `system_controller.make_time_router()` only under
    injected time, announces it, and gives `SiteAuthMiddleware` the time
    operation. Contracts `credits_system_status` and `credits_system_time` admit
    only `admin` (an empty role set). The hosted site ledger reads the source.
  - Evidence, application integration,
    `domains/apicredits/service/tests/integration/test_system_time.py`, the real
    `main.app` composed fresh, through `CreditsServiceClient` as `admin`: status,
    `set_time(1794823200)` signed at that instant, 409 and 422 with their reasons;
    the `service` role refused 403, time unchanged; wall-time status and 404; the
    composed exemption (an operator setting 900 s ahead admitted, a status read
    signed there 403; raw requests); the announcement; the misspelled source's
    refused start; route parity with the contracts. Unit,
    `tests/unit/test_time_source.py`. `make -C domains/apicredits test`: service 90,
    the domain's other suites pass. Not shown at this level: the hosted ledger
    deciding by injected time (5.2 and 10.2 show the same ledger).
  - Outside the plan: section 6's grant test now installs its source after
    composing, since composition installs the configured one.
- [x] 11.3 The registry client and the credits service's client gain the setting call
  and the status read; the registry client sends the administrator key.
  - Verify: `make test-registry-client`; the credits client's suite.
  - Done: `RegistryClient.get_admin_status(admin_key=...)` and `set_time(now,
    admin_key=...)`, sync forms too, send the administrator key unsigned and parse
    `AdminStatusResponse`/`TimeSettingResponse`; non-2xx raises
    `RegistryClientError`. `CreditsServiceClient` gains `caller_role` (`seller` by
    default, `admin` for an operator), `get_system_status()` and `set_time(now)`,
    raising `CreditsServiceError` with a time refusal's `code` as reason. Dev bounds:
    the registry on its client 0.13.0, the credits service on the domain 0.10.0.
  - Evidence: unit, `core/registry-client/tests/test_admin_time.py`; `make -C
    core/registry-client test` 31 passed. The credits client runs against the real
    service above; its domain suite (41) passes.
- [x] 11.4 Section verification.
  - Application integration: `make test-registry`, `make test-registry-client`,
    `make test-domains` (the API-credits service).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets both once section 16 puts the lanes on
    injected time.
  - Evidence: the suites in 11.1–11.3 and 10.1's process-start test. Pre-commit on
    the final tree: functional suites passed; only the citations check failed
    (18.9).
  - Confirmed: no end-to-end marker exercises these routes yet; no owed CI evidence.
  - Fresh-context check: its findings (a comment on the status operation's
    freshness, an unreachable credits 404 guard, removed; the composed exemption
    and `configured_time_source` untested; injected compositions never run; stale
    comments; the sync `set_time` unexercised) were fixed. Declined:
    application-level evidence of the hosted ledger; one `configured_time_source`
    for three packages sharing only the component; dropping the registry client's
    unit refusal test; a registry client parity test (a prior gap); surfacing the
    registry refusal's `code` (its error carries the body, as every route's).

## 12. Committed configuration outside the lanes never injects time

Delivers D2's static check and D17. Implements `deployment-state`'s "Committed
configuration outside the lanes never injects time". Touches `scripts/tests/` (a
static configuration test) and, read only, the charts' defaults,
`helm/local-values.yaml`, the charts' production examples, and the shipped presets.

- [x] 12.1 A static configuration test reads every committed configuration outside the
  lanes' own — chart defaults, `helm/local-values.yaml`, each chart's
  `examples/*values*.yaml`, the shipped storefront and buyer presets — the way their
  consumers read them, and fails naming the file and the party where any sets the time
  source to `"injected"`
  (`docs/guidance/repository/static-configuration-tests.md`).
  - Verify: it passes on the tree, and fails on a planted `[Time] source = "injected"`
    in `helm/charts/bare-metal-storefront/examples/production-values.yaml`.
  - Done: `scripts/tests/test_committed_time_sources.py`, beside
    `test_committed_stack_values.py` (it spans charts, Compose stacks and packaged
    settings). It reads every chart's and the umbrella's `values.yaml`, both local
    releases' values (`helm/local-values.yaml`,
    `helm/bare-metal-release-values.yaml`), every chart's `examples/*values*.yaml`,
    `compose/seller.yml`, `compose/registry.yml`, `config.registry.env.example`,
    each service's packaged `settings.toml`, provisioning's packaged `config/*.yml`,
    and `storefront.bob.toml`/`storefront.credits.toml`; parses each as its
    consumer does (keys in any case) and refuses `time.source`, `TIME_SOURCE`,
    `*_TIME__SOURCE` or (since 13.4) `*_TIME_SOURCE` set to `"injected"` in a mapping
    or Compose `KEY=VALUE` list, naming file and dotted path. A missing listed file
    or an empty glob fails.
  - Correction to the plan's list: no buyer preset ships. Left out as the lanes'
    own: their Compose files, `dev-env/`, `storefront.*.lane.toml`,
    `storefront.alice.toml`, `storefront.dev.toml` (with
    `dev-env/bare-metal/buyer.toml`), the runner's profiles and `helm/fixtures/`.
    It reads files, not renders, so it refuses even keys a chart would drop.
  - Evidence, static configuration: `make test-release-tooling` 3184 passed: the
    tree test, the files-and-families test, and planted cases over temporary
    copies (the bare-metal production example's `config.Time.source`,
    provisioning's `config-seller.yml`, a Compose `PROVISIONING_TIME__SOURCE`, an env
    file's `TIME_SOURCE` refused; `wall` passes).
- [x] 12.2 Section verification.
  - `make test-release-tooling`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: pre-review validation's scenarios against the local Helm release run in
    wall mode (`deployment-state`'s "The local release is validated"), shown once
    section 15's wall mode exists.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
    static configuration test runs and passes.
  - Confirmed: no end-to-end marker exercises the check; the local release's
    status read is section 15's wall mode's. The owed job collects `scripts/tests/`.
  - Evidence: pre-commit on the final tree: functional suites passed; only the
    citations check failed (18.9).
  - Fresh-context check: its findings (provisioning profiles, production stacks,
    the env example and two storefront files outside the check; the `TIME_SOURCE`
    form matched nowhere it is read; docstring wording; globs unasserted) were
    fixed. Declined: moving the test to `helm/tests/` (it reads more than charts);
    rendering with Helm and Compose (drops keys, gates on both tools).

## 13. The doubles and the sample app take injected time

Delivers D18 and the doubles' part of D21. Implements `test-compatibility`'s "Each
lane double reads injected time the scenario sets" and "The sample app follows lane
time through a test control", and removes "Each lane double reads a perceived clock
the scenario advances". Touches `tools/lane-double-controls` (`clock.py`,
`routes.py`, `models.py`, `client.py`, `README.md`), `tools/payments-lane-double`
(`app.py`), `tools/mediation-lane-double` (`app.py`), and
`domains/apicredits/sample-app` (`app.py`).

- [x] 13.1 `lane-double-controls`: `PerceivedClock`, `CLOCK_ADVANCE` and `CLOCK_RESET`
  give way to the component's injected source and one `TIME` route,
  `POST /test/time {"now"}`, answering as D5 does with the same refusals; the status
  reports `{"source", "now"}`; the typed client gains `set_time` and loses
  `advance_clock` and `reset_clock` (D18).
  - Verify: `make test-lane-double-controls`.
  - Done: the clock module and its test are removed; `time_control.TimeControl(source)`
    wraps the component's `TimeRouteService` (`settable`, `view()`,
    `set_time(raw body)`, refusals as `ControlError` with new `ControlCode`s
    `time_moves_forward` 409 and `invalid_time` 422). `TimeView` (`source`, `now`
    via `check_instant`, present exactly when injected) replaces the clock models;
    `Status` is `{"time", "contracts"}`, the services' shape. `TIME = POST
    /test/time` replaces the clock routes; routes carry `parties:
    frozenset[ControlParty]`, adding `"sample-app"` (`TIME` and `STATUS` only);
    `routes_for(party, *, time_settable)`. The client gains `set_time(now)` (sent
    as given) and loses the clock methods. README updated.
  - Evidence: `make test-lane-double-controls` 133 passed, mypy strict clean
    (`test_time_control.py`, `test_models.py`, `test_routes.py`, `test_client.py`).
- [x] 13.2 Both doubles read the shared injected source, install it from a time-source
  setting in their configuration (`"injected"` in every lane), and serve the new route
  and status behind their control bearer token (D18).
  - Verify: `make test-payments-lane-double` and `make test-mediation-lane-double`,
    including: a once part's hold pays out at the next read after time is set past its
    release instant, with no background work.
  - Done: each double's `create_app(..., source=None)` uses the given or installed
    source, gives its engine `source.now`, registers `TIME` only while settable,
    and reports `time` in status. Settings: `PAYMENTS_LANE_DOUBLE_TIME_SOURCE`,
    `MEDIATION_LANE_DOUBLE_TIME_SOURCE`, `"wall"` by default (the local Helm release
    stays wall, D17), other values refused naming the variable;
    `settings.install_time_source(settings)`, called by `__main__` after logging is
    configured and before the app, installs process-wide and logs an injected
    source. Both declare the component, relocked; READMEs updated;
    `PaymentsDouble`'s clock default is `injected_time.now`.
  - Evidence, unit and application integration (in process through the control
    client and the kits' clients): `make test-payments-lane-double` 93 —
    `test_controls.py`,
    `test_double.py::test_a_once_hold_pays_out_at_the_next_read_once_time_is_set_to_its_release`
    (no background work), rate cases set through the control,
    `tests/unit/test_settings.py`; `make test-mediation-lane-double` 78 —
    `test_controls.py::test_the_time_and_status`, `test_mechanics.py`'s once hold
    `paid_out` after a set, `test_settings.py` (one `InjectedTime` shared with the
    payments engine). `__main__`'s uvicorn serving is run by no test.
- [x] 13.3 The sample app installs its source from `APICREDITS_SAMPLE_APP_TIME_SOURCE`
  and, under injected time, serves `POST /test/time` and its status behind a control
  bearer token from its environment, through `lane-double-controls`' models and client,
  excluded from the metering gate (D18).
  - Verify: application-integration tests in the sample app's suite: the control sets
    the app's instant and is neither charged nor refused by the gate; after a set 3600 s
    forward with the credits service set alike, a metered call's consume request is
    accepted (`test-compatibility`'s "Metered calls continue after an advance").
  - Done: `configured_app()` installs the source from
    `APICREDITS_SAMPLE_APP_TIME_SOURCE` (`"wall"` default, others refused), logs an
    injected one, and builds the app; the console script serves it via uvicorn's
    factory form, so no app is built at import. `create_app(..., source=None,
    control_token=None)` serves `TIME` and `STATUS` through `TimeControl` only when
    injected, behind `APICREDITS_SAMPLE_APP_CONTROL_TOKEN`, excluded from the gate;
    injected with no token refuses to build. The app declares the component and
    `lane-double-controls` (both in the wheelhouse its image installs from),
    `arkhai-kit-identity` in its dev group; relocked. The token is an environment
    variable as D18 states: a public development value guarding a control only an
    injected app serves, not a credential, so `configuration.md`'s secret-file rule
    does not bear on it.
  - Evidence, application integration, `domains/apicredits/sample-app/tests/test_time_control.py`
    (the real app; the gate signing to a verifying stand-in credits service): the
    control sets the instant with no call reaching the credits service; 409, 422
    and a wrong token change nothing; with the stand-in an hour ahead a metered
    call fails on `TIMESTAMP_SKEW`, and after the control sets the app an hour
    forward it answers 200, one credit spent; on a wall-time app `set_time` meets
    the gate, not a control; `configured_app()` under each setting. `make -C
    domains/apicredits/sample-app test` 11 passed. Correction to the plan: the
    credits service is a stand-in; the real service is section 6's
    `test_signed_authority.py`.
  - Deferred: the sample app's flat `tests/` layout (with section 7's
    `kit/deal-lifecycle-client`) is a row under "Unowned work found by
    `drive-the-storefront-clock-in-lanes`" in `openspec/changes/README.md`.
- [x] 13.4 Section verification.
  - Unit and application integration: `make test-lane-double-controls`,
    `make test-payments-lane-double`, `make test-mediation-lane-double`,
    `make test-domains` (the sample app).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes.
  - Owed by validation: `tests.yml`, jobs `test · test-lane-double-controls`,
    `test · test-payments-lane-double` and `test · test-mediation-lane-double` — each
    passes with the new route.
  - Outside the plan, pulled forward since this section removes the routes it
    called: the e2e harness's `LaneDoubleClock`, `clocks_reset_after` and
    `lane_double_clock` (in `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`,
    its `roles/conftest.py` re-export, three unit tests) are removed (15.5);
    `test_lane_doubles_evidence.py` builds the new `Status`; `test_hold_passed.py`
    was bridged with a module fixture setting both doubles' time (16.2 moved it to
    the lane-time fixture); `e2e-tests/README.md` updated.
  - Outside the plan, from the fresh-context check: the static check also matches
    `*_TIME_SOURCE` (the doubles' and sample app's variables), in a mapping or
    Compose list; a Kubernetes `name:`/`value:` list is not read (neither double's
    chart takes environment values). The controls package's descriptions in
    `published-packages.md`, the root `Makefile`, `tools/README.md`, `TESTING.md`
    and its `pyproject.toml` name the sample app and the time control.
  - Citations: design.md's Context and section 7 name the removed module as
    `lane_double_controls.clock`, not by path.
  - Evidence: `make test-lane-double-controls` 133, `make test-payments-lane-double`
    93, `make test-mediation-lane-double` 78, sample app 11, `make
    test-release-tooling` 3184; `make test-e2e-unit` 908 (1 skipped). Pre-commit on
    the final tree: functional suites passed; only the citations check failed
    (18.9). Against the base the new tests fail at collection only.
  - End-to-end, none run by the section: from section 16, `e2e_vm_dispute_hold_passed`
    sets the doubles' time and every lane module runs them. The owed jobs are in
    `tests.yml`'s matrix.
  - Fresh-context checks (two): their findings (unrecorded e2e work, no startup
    announcement, a wall-time test passing by luck and asserting a raw body, the
    static check missing the new settings, `TimeView` restating the value rule,
    stale descriptions, an undeclared test import, an unreachable guard, naming and
    overstated claims) were fixed. Declined: moving the sample app's tests (a
    change-index row) and a secret file for the control token (D18).

## 14. The buyer's injected time

Delivers D19's buyer half. Implements `buyer-orchestration`'s "The buyer reads injected
time from a lane-time file". Touches `core/buyer` (its profile configuration and CLI
entry) and the domain buyers' entry where they install anything at startup.

- [x] 14.1 The buyer reads `[time] source` and `[time] file`; under `"injected"` it
  installs a source reading the file through the component's reader on every read;
  `"injected"` without `file`, or a missing, unreadable or invalid file at startup,
  refuses to start naming the setting or the file; a later failed read fails the
  command naming the file and never falls back to wall time (D19). A buyer whose
  Arkhai payments section has `livemode = true` logs a warning when its time is
  injected (D2).
  - Verify: unit tests of the configuration; CLI integration tests: the livemode
    warning is logged; a missing file
    refuses naming it; `{"now": "1794821400"}` written during a run fails the next read
    naming the file.
  - Done: `core_buyer.time_source` — `configured_time_source(config)` reads
    `[time]`: no `source` keeps wall time; `"wall"` a `WallTime`; other values
    refused by `source_for`; `"injected"` needs `file` (else
    `TimeConfigurationError`) and returns `TimeFile(file)` after one read
    (`TimeFileError` naming it). `install_configured_time_source(config)` installs
    it. The `market` callback runs it on `load_user_config()` before any command,
    turns a refusal into `[market] <reason>` on stderr and exit 2, and prints the
    announcement and a warning per table stating `livemode = true` on stderr (the
    buyer configures no logging). `run(app, args)`, the console entry, turns a
    later `TimeFileError` into the same exit, no fallback. The livemode check reads
    every table (`live_sections`), since core names no domain's layout
    (`[Settlement.arkhai_payments]`, `[bare_metal.arkhai_payments]`). The domain
    buyers are unchanged (every command runs through the callback); a command's own
    `--config` does not choose the process's time, and the lanes pass one file as
    both. No version bump.
  - Evidence. Unit, `core/buyer/tests/unit/test_time_source.py`. Application
    integration of the CLI, `core/buyer/tests/integration/test_injected_time_cli.py`
    (the `market` app from an explicit domain list, through Typer's runner and
    `run`): the configured `TimeFile` installed, announcement and livemode warning
    on stderr, wall time silent, a missing file or no `file` exits 2 naming it
    before the command, a write between two reads seen, and `{"now": "1794821400"}`
    written mid-command exits 2 naming the file. `make -C core/buyer test` 188
    passed.
- [x] 14.2 A running `buy` with the watchdog sees a later instant at its next read.
  - Verify: an integration test in the buyer's suite drives the watchdog's staleness
    judgement across a file write, with no wall-time wait
    (`buyer-orchestration`'s "A running purchase sees an advance").
  - Done, library integration, in `kit/deal-lifecycle-buyer`'s suite (where the
    watchdog lives), `tests/integration/test_watchdog_journal.py`, the source a
    `TimeFile` the test rewrites:
    `test_a_running_watch_stamps_each_probe_from_the_lane_time_file_as_it_is_rewritten`
    (fake monotonic time and sleep; probes and stop stamped at the instants
    written, no wall wait) and
    `test_the_staleness_judgement_follows_a_lane_time_file_write`. `make -C
    kit/deal-lifecycle-buyer test` 54 passed. Neither runs `market buy` itself;
    14.1's CLI test shows a command sees a write at its next read.
- [x] 14.3 Section verification.
  - Unit and integration: `make test-core` (`core/buyer`), `make test-kits`
    (`kit/deal-lifecycle-buyer`), the domain buyers' suites in `make test-domains`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes run every buyer stage on the lane-time file.
  - Evidence: `core/buyer` 188, `kit/deal-lifecycle-buyer` 54. Pre-commit on the
    final tree: functional suites passed; only the citations check failed (18.9).
    Against the base the new tests fail at collection only.
  - End-to-end, none run by the section: from section 16 every buyer stage runs
    on the file. No owed CI evidence.
  - Outside the plan: 18.9's promotion list gains
    `openspec/specs/buyer-orchestration/architecture.md` (the watchdog paragraphs
    and the buyer's lane-time file).
  - Fresh-context check: its findings (livemode blind to
    `[bare_metal.arkhai_payments]`, an invisible INFO announcement, the console
    test patching discovery, the 18.9 gap, five overbroad claims) were fixed.
    Declined: reading `[time]` from a command's own `--config` (the process's time
    is the buyer configuration's); the loader's pre-existing silence on a missing
    `market --config` file.

## 15. The lane-time fixture, the chain and the run modes

Delivers D4, D7, D15, D16 and D19's harness half. Implements `test-compatibility`'s
"Every party in a lane shares one lane time the scenario sets", "The chain follows
lane time" and "A run uses one time source throughout". Touches
`e2e-tests/tests/e2e/roles/helpers/` (a new `lane_time.py` replacing
`lane_doubles.py`'s clock half, `compute_deal_stages.py`'s `wait_until`), the e2e
conftests, the runner profiles `e2e-tests/config/config-*.yml`, and
`e2e-tests/tests/unit/`.

- [x] 15.1 The harness installs an injected source in its own process for an injected
  run; its signing clients read it (D19).
  - Verify: e2e unit tests: a client built in the harness signs at the harness's
    instant.
  - Done: `e2e-tests/tests/e2e/roles/helpers/lane_time.py`. `lane_time_of(section)`
    installs an `InjectedTime` at the session's wall instant before any client is
    built; the autouse session fixture `lane_time` (re-exported by
    `roles/conftest.py`) restores the previous source at the end. The harness's
    own 29 reads in 19 files (escrow expiries, back-dated lease ends, filing
    instants, forward-deal starts, the reapply snapshot, hand-built signed
    requests) read the process source. `e2e-tests` declares the component and
    `arkhai-apicredits-domain`, raises its storefront client floor to 0.30.0 and
    provisioning client to 0.11.0; relocked.
  - Evidence, unit, `e2e-tests/tests/unit/test_lane_time.py::test_a_client_built_in_an_injected_run_signs_at_the_harness_s_instant`
    and `test_a_wall_run_installs_no_injected_source`.
- [x] 15.2 The runner profile names the run's mode, `injected` or `wall`, and every
  party: each storefront, provisioning service, registry, the credits service and the
  sample app where the lane runs them, both doubles, the chain, and the buyer's file
  path (D7, D16).
  - Verify: e2e unit tests: a profile naming a party it cannot reach fails setup
    naming it, never skips.
  - Done: each lane profile (`config-vms-lane.yml`, `config-bare-metal-lane.yml`,
    `config-apicredits-lane.yml`) gains `lane_time`: `mode`, a `target` for a
    blocked skip, and `parties`, each a `name`, a `kind` (`storefront`,
    `provisioning`, `registry`, `credits`, `control`, `chain`, `buyer`) and what its
    client needs, restated from the lane's committed configuration. `parties_from`
    builds each over its typed client, refusing an unknown kind or missing field by
    name. (Section 16 flipped `mode` to injected and added the sample app.) Added
    for the reads: an administrator key on four lane registries
    (`dev-env/registry/config-{registry-a,bare-metal-registry,api-credits-registry,compute-registry}.env`,
    registry-b's development value) and an `admin` principal on the credits
    service (Anvil 9, in `compose.apicredits-lane.yml`). The generated buyer
    configuration (`buyer_cli.py`) gains `[time]` in an injected run only
    (`buyer_time_file`).
  - Evidence, unit, `test_lane_time.py`: an unreachable party fails naming it
    (`LaneTimeError`, an `AssertionError` the fixture turns into `pytest.fail`,
    never a skip); unknown kind and missing field refused; the buyer's `[time]`
    only when injected. Static configuration, `test_lane_time_profiles.py`: each
    lane's parties build over their typed clients, and every restated value is held
    to its source (registry profiles, double fixtures, `config-docker.yml`,
    `compose.apicredits-lane.yml`, the sample app's authority pin).
- [x] 15.3 `lane_time.set(T)`: moves the harness's own source, then each service
  through its typed client's `set_time`, then both doubles and the sample app through
  `lane-double-controls`' client, then the chain (`evm_setNextBlockTimestamp` and a
  mined block, and its block time frozen with `anvil_setBlockTimestampInterval` if
  Anvil admits it — record which in the task note), then the buyer's file through the
  component's writer; then reads every status and fails naming any party not at T, a
  status without a time section among them; refuses a backward T naming the party and
  both instants (D4, D7, D15).
  - Verify: e2e unit tests over fake parties: the order of calls; a party left behind
    fails naming it and its instant; an older image's status without a time section
    fails naming it; a backward set fails.
  - Done: `LaneTime.set(T)` refuses a T before the harness's instant (naming both),
    sets the harness, then each party in `SET_ORDER` (storefronts, provisioning,
    registries, credits, controls, chain, buyer file), failing on a refusal by
    name, then `confirm(T)` reads every status, failing by name on no time
    section, another source or another instant. The chain is
    `evm_setNextBlockTimestamp(T)` then `evm_mine`, after
    `anvil_setBlockTimestampInterval(0)` since 16.3, which freezes the chain
    between sets.
  - Evidence, unit, `test_lane_time.py` over recording fakes: call order with the
    harness already at T; a party behind, a missing section, a float instant
    (`check_instant`), a backward set (no party called) and a refusal each fail by
    name; the chain's RPC calls; the buyer file through the component.
- [x] 15.4 Session start: in an injected run, set every party to the wall instant at
  the session's start; in any run, read every status and fail naming a mix of sources
  (D11, D16).
  - Verify: e2e unit tests: a mix fails naming the wall-time party.
  - Done: `LaneTime.start(wall)` sets every party to the session's wall instant (or
    later, below) in an injected run; in either mode `check_one_source()` fails
    naming each party whose status names another source or none (the chain and
    buyer file are read for their instant only).
  - Evidence, unit: the start sets every party; a mix fails naming the odd party
    in either mode.
  - Round 2 triage fix (45 F1), closing the gap this section first left (no
    wall-mode check on the local Helm release): its validation names its
    storefront, provisioning service and registry on wall time, so the session
    reads each status and fails naming any not wall, and blocked skips name the
    target. The e2e-tests chart gains `config`, passed whole as its own
    `e2e-tests` profile ConfigMap (`templates/configmap.yaml`), layered
    `helm,e2e-tests,e2e-secret` by the deal and scenario pods only (own profile on
    the owner's word, design.md, Implementation record); chart 0.2.0 with the
    umbrella's pin. `helm/local-values.yaml` states `e2e-tests.config.lane_time`
    (`mode: wall`, `target: "the local Helm release"`, the three parties keyed by
    name; `parties_from` takes a mapping too). Credentials are named by their
    `e2e-secret` key through `<field>_setting` fields, which `parties_from`
    resolves from the run's settings, failing by name on one unset. The registry's
    administrator key reaches the release via `topology-secrets.sh` into
    `arkhai-registry-runtime`'s `config-admin.env` (mounted by
    `registry.secretProfile`) and `registry.admin_key` in `config-e2e-secret.yml`.
    The release's doubles are not named (their token is in no mounted Secret). The
    delta reads every party a profile names (a hosted profile names none) and has a
    blocked skip and an injected-service scenario for the release; `TESTING.md`,
    `DEPLOYMENT_AND_CONFIG.md` and D7 describe it.
  - Evidence for the round 2 fixes (45 F1, F2, session-start, O1, chart package):
    `make -C helm test-render` passed (config only on the e2e pods, a credential key
    refused, the release's three parties); `make test-e2e-unit` 952 passed, 1
    skipped; `make test-release-tooling` 3189 passed; `run test-before` at
    `41dc2a7bc` fails each tooling test. System, 45 F2: `make -C e2e-tests
    test-e2e-apicredits` 4 passed (calls after the hour's advance 200, 200, 402).
    The Helm wall-mode check runs first in validation's Helm part. Pre-commit:
    only the citations check failed (18.9). Two fresh-context checks: findings
    fixed (the shared-profile merge on the owner's choice, wording, a schema guard,
    four subchart bumps, keyed parties, a docstring).
  - Round 3 triage fixes (60 F1; the owner's 61 O2, O3, O4; O1 under 8.1):
    - 60 F1: the `config` schema refuses a key ending `credential`, `_key`,
      `token` or `secret` in any letter case (character classes); render test
      with mixed-case keys at three depths.
    - O2: the Helm parties state no topology: each URL and pin is a
      `<field>_setting` naming the shared `helm` profile's setting; the umbrella's
      profile gains `seller.publisher_scheme`/`seller.publisher_identifier`; the
      render test holds each setting to a value the profile or
      `config-e2e-secret.yml` holds.
    - O3: the umbrella's ConfigMap is `<release>-helm-profile`
      (`helm/templates/tests/helm-profile.yaml`, volume `helm-profile`), the
      e2e-tests chart's `<release>-e2e-tests-profile`; the e2e pods mount
      `helm-profile`, `e2e-tests-profile`, `e2e-secret-profile`, their headers
      saying why. validate-contracts 0.1.2 with the umbrella's pin.
    - O4: `topology-secrets.sh` derives the registry's administrator key from the
      mnemonic at `DEV_ACCOUNT_REGISTRY_ADMIN` (6, unused by any principal),
      passed by `helm/Makefile`, written with a heredoc.
  - Evidence for the round 3 fixes: `make -C helm test-render` and `make
    test-release-tooling` 3189 passed (through the new `dist-identity`); `run
    test-before` at `5e0f28afc` fails the refusal and topology tests. Pre-commit:
    only the citations check failed (18.9). Fresh-context check: four text defects
    fixed; declined: a Kelvin-sign key passing the ASCII pattern (only a crafted
    key reaches it).
  - Pre-closeout triage fix (72 F1, the owner's choice C): `LaneTime.start` first
    reads the parties reached with no signed timestamp (`_UNSIGNED`: the
    registry's bearer administrator route, the controls, the chain, the buyer's
    file), moves the harness to the latest instant they hold or the wall instant,
    then reads the signed services and sets every party to the latest, so a stack
    left ahead past the skew starts. A signed service still past the skew holds
    none: one restarted behind is moved forward by the exempt set; one left ahead
    of the chain refuses the set and fails the start by name (D7; the delta,
    `TESTING.md`). No lane target reaches the path (each brings its stack down);
    a session by hand against a stack left up does.
  - Evidence for 72 F1: `make test-e2e-unit` 955 passed, 1 skipped, over a signed
    fake: a stack a day ahead starts at its instant; a restarted service moves
    forward; a service ahead of every unsigned party fails by name. With the old
    start put back for one run, the first fails `bob-storefront cannot be read:
    401 stale_timestamp`. Pre-commit: only the citations check failed (18.9). The
    live path runs in no validation. Fresh-context check: the first form failed a
    restarted service and the docs were silent on a service left ahead; fixed.
  - Round 17a triage fix (82 F1, the owner's choice of a test through the real
    client): one e2e unit test starts a session on a stack a day ahead through the
    real `SyncStorefrontClient` (built via `lane_time_of`'s `parties` seam) over
    `WireStorefront`, a transport verifying each request with `verify_request` at
    the storefront's instant (300 s skew, setting exempt) and signing answers
    there; it asserts the start reaches the stack's instant with every request
    signed there. The service half stays with each service's integration tests;
    no production code changed.
  - Evidence for 82 F1: `make test-e2e-unit` 956 passed, 1 skipped; with the start
    before 72 F1 put back, the test fails `HTTP 401: missing
    X-Market-Signature-Version header`. Pre-commit: only the citations check
    failed (18.9). Fresh-context check: findings (patching an imported name, per
    `test-seams.md`; a duplicate seed; the double's docstring; a vacuous
    assertion) fixed.
- [x] 15.5 The helper shared stages use to reach an instant: in an injected run it
  sets lane time; in a wall run it waits for an instant the Agreement fixes, and any
  other instant is a blocked skip naming the wall-time target. `wait_until` callers move
  to it; `lane_double_clock` and `clocks_reset_after` are removed (D8, D16).
  - Verify: e2e unit tests for both modes and the blocked skip
    (`test-compatibility`'s "A time-driven module against a hosted target").
  - Done: `LaneTime.reach(instant, fixed_by_agreement=…)` sets lane time (or leaves
    it when past) in an injected run; in a wall run it waits for an
    Agreement-fixed instant through `wait_until` (moved here from
    `compute_deal_stages.py`) and is a blocked skip naming the profile's `target`
    for any other. `compute_deal_stages.reach_agreement_instant` serves stage 08b's
    late settlement and the forward deal's start (`delivery_timing_deal.py`, 13b),
    each taking the `lane_time` fixture; with no lane time it waits as before.
  - Evidence, unit: both modes, the blocked skip, the moved `wait_until` tests, and
    `test_vm_deal_dispatch.py`'s stage-08b test with no lane time.
- [x] 15.6 Section verification.
  - Unit: `make test-e2e-unit`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes.
  - Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the
    fixture's tests.
  - Evidence: `make test-e2e-unit` 943 passed (1 skipped). Pre-commit on the final
    tree: functional suites passed; only the citations check failed (18.9). Against
    the base the new tests fail at collection only.
  - End-to-end, none run by the section: every lane module starts the session
    fixture; 08b and 13b reach their instants through it. The owed job is in
    `tests.yml`.
  - Fresh-context check: its findings (restated values untested, now
    `test_lane_time_profiles.py`; doc wording; the Anvil freeze and profile flip
    unowned, given to section 16; client floors; the credits instant unparsed;
    docstrings; import grouping; seven overbroad claims) were fixed.

## 16. Every Compose lane on injected time

Delivers D21 and D17's lane half. Implements the lane scenarios of
`test-compatibility`'s requirements. Touches the lanes' Compose files
(`compose.vms-lane.yml`, the bare-metal and API-credits lane files) and the
configuration they mount for every party, the e2e runner profiles,
`e2e-tests/tests/e2e/roles/scenarios/vms/dispute/test_hold_passed.py`, and the stages
that advanced the doubles.

- [x] 16.1 Each lane's committed configuration sets the injected source for every
  party: each storefront's `[Time] source`, provisioning's and the credits service's
  `time.source`, each registry's `TIME_SOURCE`, the sample app's
  `APICREDITS_SAMPLE_APP_TIME_SOURCE` and control token, both doubles, and the buyer
  profile's `[time]` section with the file path the harness writes (D21, D19).
  - Verify: the e2e unit tests' stack checks read each lane's Compose configuration and
    find every party injected.
  - Done: each setting is in the party's own configuration form, in files only the
    lanes load, so the full local stack stays on wall time (`configuration.md`,
    "Application settings stay out of the environment"): registries' `TIME_SOURCE`
    in `dev-env/registry/config-payments-lane.env` (via `ACTIVE_PROFILES`);
    provisioning's `time.source` in a new `dev-env/provisioning/config-lane-time.yml`
    (`ACTIVE_PROFILES=docker,<site>,lane-time,<mode>`); storefronts' `[Time] source`
    in `storefront.bob.lane.toml`, `storefront.credits.lane.toml`, the bare-metal
    lane's `storefront.dev.toml`, and a new `storefront.alice.lane.toml` mounted by
    `compose.vms-lane.yml`; in the environment, in the lanes' own overlays, the
    credits service's `APICREDITS_TIME__SOURCE`, the sample app's source and token,
    and both doubles' sources (`compose.apicredits-lane.yml`,
    `compose.payments-double.yml`). Each lane profile's mode is `injected`; the
    API-credit lane names the sample app (`kind: control`). The buyer's `[time]`
    names `/tmp/arkhai-lane-time/now.json` in the runner. Static tests:
    `scripts/tests/test_lane_compose.py` (VM provisioning's `lane-time` profile and
    mount; new `test_the_full_local_stack_runs_wall_time`),
    `test_bare_metal_compose.py`, `test_committed_stack_values.py`, and
    `e2e-tests`' `test_domain_stack_configuration.py`.
  - Evidence, static configuration, `e2e-tests/tests/unit/test_lane_time_profiles.py`:
    every service party of each lane runs `injected` by its lane configuration,
    read in its own form as committed; Alice's lane file differs only in `[Time]`;
    each mode is `injected`; the sample app's token matches. `make test-e2e-unit`
    950 passed; `make test-release-tooling` 3185.
- [x] 16.2 `test_hold_passed.py` sets lane time past the part's terms end and release
  instant instead of advancing the doubles (D18).
  - Verify: `make -C e2e-tests` runs the VM lane's `e2e_vm_dispute_hold_passed` module
    locally and it passes.
  - Done: stages 20 and 21 set every party's time a second past the terms end, then
    past the release, through `lane_time.reach(…, fixed_by_agreement=False)`; on a
    wall run stage 20 is a blocked skip and 21–22 skip after it. Section 13's
    bridge fixture is gone; the marker, Makefile comment and e2e README say a later
    module starts days later.
  - Evidence, system: passed in 16.3's VM lane run, every stage.
- [x] 16.3 Run each lane locally (`make -C e2e-tests test-e2e`).
  - Verify: the three lanes pass, every module on injected time, the session fixture
    confirming every party; record each lane's pass counts in the task note.
  - Evidence, system, on the final configuration: `make -C e2e-tests test-e2e`
    (the three lanes in turn), every module on injected time with the session
    fixture setting and confirming every party: VM 310 passed (nothing failed or
    skipped), bare metal 115 passed, API credits 4 passed
    (`test_credits_full_deal` and the payment deal's three tests).
  - Found by the first VM run (08b failed, 20 dependants skipped): the chain had
    run ahead of lane time between sets (design.md, Implementation record). Fixed:
    `ChainParty` calls `anvil_setBlockTimestampInterval(0)` before each set, which
    the lane's Anvil admits, freezing the chain between sets (D15's freeze,
    adopted); `LaneTime.start` starts at the latest instant any injected party
    holds (the chain's block included) or the wall instant if later (D4); a fresh
    run's missing buyer file holds no instant until the first set. Unit tests for
    each.
  - Round 2 triage (45 session-start): the delta and D7 now say the start sets
    every party "to the wall instant at that moment, or to the latest instant a
    party already holds when that is later, so the start never sets a party back".
  - Round 2 triage fix (45 F2): `test_credits_full_deal` proves metered calls
    across an advance on the live lane: 3 credits bought, one consumed,
    `lane_time.reach(now + 3600, fixed_by_agreement=False)`, then 200, 200, 402
    `insufficient_credits` through the real credits service; on a wall run the
    step after the advance is a blocked skip.
  - Owed by validation: none new; the pipeline's three lane jobs (`e2e.yml`, run
    by validation's pipeline part) run every module on injected time.
- [x] 16.4 Section verification.
  - System: the three lanes locally, 16.3.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: every module of the three lanes, the hold-passed module
    (`e2e_vm_dispute_hold_passed`) the one that moves time; pre-review validation's
    Helm scenarios (`contracts`, `e2e_alkahest_escrow_codecs`,
    `e2e_alkahest_trusted_oracle`) in wall mode.
  - Evidence: 16.3's lane runs; `make test-e2e-unit` 950, `make
    test-release-tooling` 3185; pre-commit over sections 16 and 17 under 17.3.
  - Confirmed end-to-end: every lane module ran injected locally (16.3); the Helm
    scenarios run in wall mode in validation's Helm part (its parties per 15.4's
    45 F1 fix).
  - Fresh-context check: its findings (time sources as container environment
    variables against `configuration.md`, moved into lane-owned files; loosened
    full-stack tests, reverted; the start described as the wall instant;
    `system-tests.md`'s wait bullet, undefined terms and drift claim, and the
    proxy taken out of the ladder; `deal-scenarios.md` trimmed to rules; stages
    21–22 failing on a wall run; overbroad claims) were fixed. Kept: the static
    check reading overlays raw (rendered stacks are `test_lane_compose.py`'s).
    Permanent-documentation destination: `DEPLOYMENT_AND_CONFIG.md`'s overlay
    table, added to 18.9's list.

## 17. The scenario rule restated

Delivers D8 and D16's ladder. Touches `docs/guidance/engineering/system-tests.md`,
`docs/guidance/repository/deal-scenarios.md`, and `docs/development/TESTING.md`.

- [x] 17.1 `system-tests.md`, "A scenario is a sequence of state changes": the clock
  bullet becomes reaching an instant by setting the time every party perceives,
  together, back-dating admitted below it and discouraged; a new section "Time a test
  does not control" states D16's ladder, neutrally (D8, D16).
  - Verify: `make check-guidance` passes.
  - Done: the bullet reaches an instant by setting every participant's time
    together, never by waiting or moving one alone (with the reason), back-dating
    admitted below it and discouraged; the wait bullet is scoped to a wall-clock
    run. "Time a test does not control" states the ladder (a rewriting proxy set
    apart as serving only unexercised times), one source per run, and one helper
    for shared stages; example a billing service and card processor. `make
    check-guidance` passes.
- [x] 17.2 `deal-scenarios.md`, "The discipline every scenario follows", and
  `TESTING.md`, "4. System Integration Tests (End-to-End)": lane time across every
  party, the lane-time fixture and its order, never reset, the chain, the two run
  modes, the buyer's file; the doubles' perceived-clock text and `lane_double_clock`
  removed (D4, D7, D8, D15, D16, D19, D21).
  - Verify: `make check-doc-citations CHANGE=drive-the-storefront-clock-in-lanes`
    passes.
  - Done: `deal-scenarios.md`'s paragraph on `wait_until` and the perceived clock
    gives way to lane time's rules (every Compose lane injected and confirmed,
    setting not waiting, forward only, a missing party failing setup, wall-run
    waits and blocked skips through one helper, one source per run), linking
    `TESTING.md`'s new "Lane time" under section 4 (parties and lane-owned
    configuration, the profile section, the start, set order with the chain
    frozen, confirmation, the buyer's file, the run modes, the hold-passed
    module); the back-dated VM lease end is kept below lane time.
  - Evidence: `make check-guidance` passes; `make check-doc-citations
    CHANGE=drive-the-storefront-clock-in-lanes` reports only closeout's
    `openspec/specs/injected-time/architecture.md` (18.9). No permanent document
    but the specification and companion (archive, 18.9) and `ROADMAP.md` (18.5)
    names the perceived clock, `lane_double_clock` or the clock routes.
- [x] 17.3 Section verification.
  - `make check-guidance`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: none; documentation only.
  - Evidence: `make check-guidance` passes; pre-commit over sections 16 and 17 on
    the final tree: functional suites passed; only the citations check failed
    (18.9). The fresh-context check's findings are under 16.4.
  - Permanent-documentation destinations: 18.9's list holds
    `buyer-orchestration`'s companion (14.3) and `DEPLOYMENT_AND_CONFIG.md`'s
    overlay table (16.4).
  - Round 2 triage fix, outside the plan (45 F1's discussion): `helm/.helmignore`
    excludes `/Makefile`, `charts/*/Makefile`, `/scripts/`, `/tests/`,
    `charts/*/tests/`, `/fixtures/`, `/local-values.yaml`,
    `/bare-metal-release-values.yaml`, `/validation-capacity.toml` from the chart
    package, keeping templates, `templates/tests/`, values, schemas and subchart
    files, so those edits no longer change a chart's digest;
    `package-versions.md` says which edits take a chart version. Registry,
    provisioning, payments-lane-double and mediation-lane-double take 0.1.2 with
    the umbrella's pins.

## 17a. A test docstring names no design decision

Delivers the fix closeout's return names (18.1's note): a docstring the change added
cites a design decision by id, which code may not
(`docs/guidance/workflow/change-references.md`). Touches
`domains/apicredits/service/tests/integration/test_system_time.py` only.

- [x] 17a.1 Reword the docstring of
  `test_the_composed_service_admits_the_time_setting_alone_outside_the_skew` so it
  says what the test checks without naming `D14`: the time-setting operation, the one
  request admitted outside the signing skew, as the composition wires it — a setting
  signed 900 s ahead of the service is admitted and moves it, and a status read signed
  there is refused.
  - Verify: no comment or docstring the change added names a decision, section, task
    or review id — a search of the change's added Python lines for `D[0-9]+` and
    section numbers finds none; `make check-comment-hygiene` passes.
  - Done: the docstring opens "The time-setting operation, the one request
    admitted outside the signing skew, as the composition wires it:"; code
    unchanged.
  - Evidence: a search of the Python lines `git diff dd86e550f` adds for decision,
    section, task or finding ids finds only four `# noqa: F401` lint codes; `make
    check-comment-hygiene` passes.
- [x] 17a.2 Section verification.
  - Application integration: the API-credits service's suite in `make test-domains`
    passes, `test_system_time.py` among it.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`,
    whose functional checks pass and whose citations check names only closeout's
    `openspec/specs/injected-time/architecture.md`.
  - End-to-end: none; a docstring changes no behaviour, and none is owed.
  - Evidence: `make -C domains/apicredits/service test` 90 passed, alone and in
    `make test`. Pre-commit: functional suites, index, tasks and skills checks and
    strict OpenSpec validation passed; only the citations check failed (18.9).
  - Confirmed: no end-to-end scenario exercises a docstring; nothing owed.
  - Fresh-context check: no findings.
  - For closeout: it runs again from 18.1; 18.7 is run again in its place. The
    round's triage then added one e2e unit test (82 F1, 15.4); no production
    source changed.

## 18. Closeout

The workflow's parts (`docs/guidance/workflow/closeout.md`) in order, the
repository's own at their position (`openspec/README.md`, "This repository's closeout
parts"). Closeout changes only the inert paths, the change's records and the
archive's writes; a part needing any other edit returns the change to implementation.

- [x] 18.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
  the comments sections 1–17 added — in the component, the converted modules, the
  routes, the doubles and the harness — for any naming this change, a task or a
  review, or calling the conversion new.
  - First pass, at `e846e92e0`: one violation returned the change to
    implementation — the docstring of
    `test_the_composed_service_admits_the_time_setting_alone_outside_the_skew`
    (`domains/apicredits/service/tests/integration/test_system_time.py`) named
    decision D14 (`change-references.md`); section 17a fixed it. No comment
    narrates history; `storefront.alice.lane.toml`'s "the pre-list spelling" is
    copied from `storefront.alice.toml` and stands as in the other storefront files.
  - Closeout, 2026-11-17, at `0e8427c09`: `make check-comment-hygiene` passes. The
    comments and docstrings added since the first pass (`e846e92e0..573ecac5f`:
    17a's reworded docstring and 82 F1's `WireStorefront` test double and test in
    `e2e-tests/tests/unit/test_lane_time.py`) describe present behaviour and name no
    decision, section, task or review.
- [x] 18.2 **Import placement — confirm.** Check the imports sections 1–17 added,
  every `injected_time` import among them, for any left local without a recorded
  reason.
  - Closeout, 2026-11-17, at `e846e92e0`: no import the diff from `dd86e550f`
    added sits in a function, method or class body; the indented matches are
    multi-line import continuations, unchanged context, or source text inside
    test strings. The diff moved two local imports to module level (the sample
    app's `os`, `torch_arkhai_strategy.py`'s `time`).
  - Re-checked at `0e8427c09`: the imports added since (`test_lane_time.py`'s
    `json`, `market_identity` and `storefront_client` names) are at module level.
- [x] 18.3 **Documentation compliance.** Re-check D1–D21 against
  `openspec/README.md`'s placement table; confirm each document 18.9 writes describes
  the current state; confirm no permanent document still describes the doubles'
  perceived clock, `lane_double_clock`, `/test/clock/advance` or `/test/clock/reset`,
  or a storefront step forbidden after an advance.
  - D1–D21 placed as the promotion record below gives them: normative rules in the
    capability specs (by the deltas), rationale in the `injected-time`,
    `test-compatibility`, `buyer-orchestration`, `marketplace-identity` and
    `site-capacity` companions, cross-system description in `ARCHITECTURE.md`,
    `TESTING.md` and `DEPLOYMENT_AND_CONFIG.md`, rules in the engineering and
    repository guidance, the operator's procedure in the operator handbook; D10 has
    no permanent destination. Each document written describes the current state.
  - A search of every permanent document for the perceived clock,
    `lane_double_clock`, `/test/clock/*` and a clock advance found, beyond the
    `test-compatibility` requirement the delta removes, the companion's section
    (rewritten, 18.9), two lines of `test-compatibility/spec.md` the deltas do not
    carry — the controls-scenarios requirement's "a clock advance past a hold" and
    the payments double's scenario "when the perceived clock reaches it" — and the
    roadmap's same phrase; each now names lane time, by hand beside the deltas.
- [x] 18.4 **Narrative compression.** Shorten the task notes to final behaviour,
  evidence and deferred work.
  - Sections 1–17a's notes shortened to final behaviour, evidence, dispositions,
    deferrals and destinations (the file from 3170 to about 1890 lines); each
    `Owed by validation:` line and each section's read and audit-only column lists
    kept. Alternatives and findings the decisions did not hold moved to `design.md`,
    "Implementation record" (18 items, sections 1, 3, 5, 8, 9, 11, 12, 15 and 16).
- [x] 18.5 **Roadmap currency.** `docs/development/ROADMAP.md`, Goal 8: the open-gap
  row "No storefront step can follow a lane double's clock advance…" removed as closed;
  the deferred row "A perceived clock for the site and the buyer half…" removed as
  closed by lane time; the current-state paragraph's account of the doubles' perceived
  clock rewritten to lane time across every party (D9).
  - Done as listed; the current state also drops "a storefront clock a lane can
    move" from what remains for the earliest form, and the gap table's lead says the
    first two rows are the MVP changes.
- [x] 18.6 **Campaign index currency.** `openspec/changes/README.md`: this change's
  row; `converge-ongoing-compute-leases`' row and task 4.1a and
  `serve-running-rate-deals`' open question noted as answered where their rows name
  them; the unowned entries under "Unowned work found by
  `drive-the-storefront-clock-in-lanes`" kept (D9). Run `make check-change-index`.
  - The row is `in closeout`, its notes describing closeout, and its link points at
    the archive (18.12); the Goal 8 lead describes the change as lane time across
    every party. Neither `converge-ongoing-compute-leases`' row nor
    `serve-running-rate-deals`' names task 4.1a or the open question, so nothing is
    noted there; `serve-running-rate-deals`' "funds-exhausted rows wait for" note,
    the graph's dotted edge and every `Depends on` are left for archive cleanup. The
    three unowned rows are kept. `scripts/change-workflow check index` passes.
- [x] 18.7 **Packaging.** `make check-packaging`, `check-time-reads` among it, and
  `make check-architecture-change CHANGE=drive-the-storefront-clock-in-lanes`;
  resolve every failure.
  - Run ahead of its place on 2026-11-17 at `e846e92e0`, to find every code edit
    before returning the change: `make check-packaging` passes (`check-time-reads`
    among it: no direct wall-clock read in production source or the lane
    doubles); `make check-architecture-change` passes (the change owns no
    architecture row). To be run again in its place after the fix round.
  - In its place, at `0e8427c09`: `scripts/change-workflow run pre-archive
    drive-the-storefront-clock-in-lanes` passed — `make check-packaging` (every
    check OK, `check-time-reads` among them) and `make check-architecture-change`
    (the change owns no architecture row). The change touched no `.agents/`,
    `.claude/` or `.codex/` path.
- [x] 18.8 **End-to-end pipeline.** Dispatch `make run-e2e` at the closeout's code,
  collect with `make fetch-e2e-logs`, and record the run, its result, and the scenarios
  exercising the change: every module of the three lanes on injected time, the
  hold-passed module the one moving time. A failed run returns the change to
  implementation.
  - Recorded from validation 88 rather than dispatched again: closeout changes no
    code, and 88 ran at `573ecac5f`, the pre-closeout review's commit, which differs
    from closeout's base `0e8427c09` only in the change index. `e2e.yml` run
    44118864375 succeeded: e2e-vm 310 passed, e2e-bare-metal 115, e2e-apicredits 4,
    every module on injected lane time; `e2e_vm_dispute_hold_passed` the module
    moving lane time days ahead, and `e2e_alkahest_escrow_codecs` and
    `e2e_alkahest_trusted_oracle` among the lanes' modules. Helm validation's served
    scenarios passed on wall time.
  - Owed by validation, from 88's `## CI` (`tests.yml` run 44118876025, success):
    `test · test-injected-time` passed (§1); `test · test-deployment-packaging`
    passed, the time-read check's, chart render and static configuration tests
    among it (§2, §9, §12); `test · test-lane-double-controls`,
    `test-payments-lane-double` and `test-mediation-lane-double` passed (§13);
    `test · test-e2e-unit` passed (§15). No job failed; `dev`'s baseline was
    `tests.yml` run 44060014201 at `dd86e550f`.
- [x] 18.9 **Promotion.** Write, and complete the design-promotion record below:
  - `openspec/specs/injected-time/architecture.md`, new: "One source per process"
    (D3), "The component" (D6), "Frozen injected time" (D11), "No live change" (D12),
    "Database times" (D13); `openspec/specs/README.md` gains its row;
  - `docs/development/ARCHITECTURE.md`: "Authenticated service boundaries" — lane time
    and why freshness needs every party on one time (D1); "Composition from above and
    below" — each root installs its process source (D3); "Operator lifecycle controls"
    — the setting routes exist only under injected time (D5, D12);
  - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Profile-based configuration", a new
    subsection "The time source" — each party's setting, its default, the announcement
    and warning (D2); "Release topology" — the local Helm release on wall time (D17);
    the overlay table's rows for the lanes' time settings (the registries' and
    provisioning services' lane profiles, the storefronts' lane configuration, the
    credits service's, sample app's and doubles' environment; 16.1);
  - `docs/guidance/engineering/configuration.md`: a new section "A test control the
    production image carries is off by default" — off by default, omitted from
    production configuration, never refused (D2);
  - `openspec/specs/test-compatibility/architecture.md`: "The doubles' controls and
    perceived clocks", renamed "Lane time and the doubles' controls" (D1, D4, D7, D15,
    D16, D18, D21);
  - `openspec/specs/buyer-orchestration/architecture.md`: the watchdog's probe
    stamps and staleness on the process time source, not the wall clock, and the
    buyer's `[time]` table and lane-time file (D3, D19; 7.7's and 14.3's
    handoffs);
  - `openspec/specs/market-composition/configuration.md`,
    `openspec/specs/physical-provisioning/configuration.md`,
    `openspec/specs/registry-discovery/configuration.md`: each party's `time.source`
    setting (D2);
  - `docs/operator-handbook.md`: a new section "Injected time" — the setting routes,
    the status section, that a production deployment never sets it, and reproducing an
    incident on a copy (D5, D12);
  - `tools/README.md`, "Standalone infrastructure components": an `injected-time/`
    entry; "`lane-double-controls/`": the injected-time control (D6, D18);
    `tools/lane-double-controls/README.md` (D18);
    `docs/guidance/repository/published-packages.md`, "Published packages": the
    component (D6);
  - the specifications the archive writes from the deltas: `injected-time`,
    `market-composition`, `physical-provisioning`, `site-capacity`,
    `registry-discovery`, `api-credits`, `buyer-orchestration`,
    `marketplace-identity`, `test-compatibility`, `deployment-state`.
  - Run `make check-spec-index CHANGE=drive-the-storefront-clock-in-lanes` and
    `make check-capability-index`.
  - Written as listed. Beyond the list: `docs/development/ARCHITECTURE.md`'s
    passages link the new companion; `marketplace-identity/architecture.md` gains
    the exemption's rationale (D14) and `site-capacity/architecture.md` the site's
    clock as its host's source (D13); `tools/README.md`'s `injected-time/` entry
    names the root targets; the `market-composition`, `physical-provisioning` and
    `registry-discovery` configuration companions each gain a time-source section;
    `test-compatibility/spec.md`'s two stale phrases and the roadmap's (18.3). The
    `tools/` READMEs, `TESTING.md`, `e2e-tests/README.md`, `published-packages.md`
    and the guidance were written in implementation and checked here. No touched
    capability has an `index.md`. `make check-spec-index` passes; `make
    check-capability-index` fails before the archive only because the index's new
    `injected-time` row links the `spec.md` the archive writes, and passes after it
    (18.12).
- [x] 18.10 **Guidance placement.** Read the guidance sections sections 2, 17 and 18.9
  wrote — `implementation.md`'s "One time source per process", `configuration.md`'s
  new section, `system-tests.md`'s rewritten bullet and "Time a test does not
  control", `deal-scenarios.md`, `packaging-checks.md`'s row — against the layer test;
  run `make check-guidance`.
  - Each holds where it is: `implementation.md`'s section, `configuration.md`'s "A
    test control the production image carries is off by default" and
    `system-tests.md`'s bullet and section hold without the workflow or this
    repository, each with a neutral example (a billing service, a service whose
    clock a test can set, a billing scenario); `deal-scenarios.md`, the
    `packaging-checks.md` row, `published-packages.md`'s rows and
    `package-versions.md`'s `.helmignore` paragraph are this repository's
    cross-system rules, in `docs/guidance/repository/`. No exception was added.
    Nothing needs a decision. `make check-guidance` passes (104 files).
- [x] 18.11 **Documentation citations.** Run `make check-doc-citations
  CHANGE=drive-the-storefront-clock-in-lanes` and resolve every match; then
  `scripts/change-workflow openspec validate drive-the-storefront-clock-in-lanes
  --strict`.
  - `make check-doc-citations CHANGE=drive-the-storefront-clock-in-lanes`: every
    cited path resolves (13 documents). `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` before the archive: the index, tasks and
    skills checks pass, and `openspec validate --strict` reports the change valid;
    of `check-repository`'s nine checks only the capability index fails, on the
    `injected-time` row whose `spec.md` the archive writes (18.9).
- [x] 18.12 **Archival.** `scripts/change-workflow openspec archive
  drive-the-storefront-clock-in-lanes -y`, merging the deltas into `openspec/specs/`.
  - Merged, not `--skip-specs`: no permanent spec held the deltas' text, and both
    MODIFIED requirements' permanent text matched the delta's base. Archived as
    `openspec/changes/archive/2026-11-17-drive-the-storefront-clock-in-lanes/`:
    `injected-time` created (7 requirements, its Purpose written after),
    `test-compatibility` +5 −1, `marketplace-identity` +2 ~1,
    `physical-provisioning` +1 ~1, and one added each to `api-credits`,
    `buyer-orchestration`, `deployment-state`, `market-composition`,
    `registry-discovery` and `site-capacity`. Each spec's diff read: every added or
    modified requirement is there once as the delta states it, the removed one is
    gone, and nothing else changed but 18.3's two phrases. The index row links the
    archive. `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` after the archive passes: the index, tasks
    and skills checks, `openspec validate --specs --strict` (28 passed, 0 failed),
    and every `check-repository` check, the capability index and citations among
    them.

## Design promotion record

Completed at closeout (18.9). The ten capability specifications are written by the
archive from the deltas (18.12); each row names the requirement it carries.

| Accepted decision | Permanent location |
|---|---|
| D1 — One lane time, shared by every party | `openspec/specs/test-compatibility/spec.md#requirement-every-party-in-a-lane-shares-one-lane-time-the-scenario-sets`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls`; `docs/development/ARCHITECTURE.md#authenticated-service-boundaries` |
| D2 — Injected time is off by default and announced, never refused | `openspec/specs/injected-time/spec.md#requirement-each-process-reads-the-time-of-the-world-from-one-source`, `#requirement-an-injected-process-announces-its-time`; each party's setting in the `market-composition`, `physical-provisioning`, `registry-discovery`, `api-credits` and `buyer-orchestration` specs; `openspec/specs/deployment-state/spec.md#requirement-committed-configuration-outside-the-lanes-never-injects-time`; `openspec/specs/injected-time/architecture.md#configured-announced-never-refused`; `docs/development/DEPLOYMENT_AND_CONFIG.md#the-time-source`; `docs/guidance/engineering/configuration.md#a-test-control-the-production-image-carries-is-off-by-default`; `openspec/specs/market-composition/configuration.md#the-storefronts-time-source`, `openspec/specs/physical-provisioning/configuration.md#the-services-time-source`, `openspec/specs/registry-discovery/configuration.md#the-registrys-time-source` |
| D3 — One explicit time source per process | `openspec/specs/injected-time/spec.md#requirement-each-process-reads-the-time-of-the-world-from-one-source`; `openspec/specs/injected-time/architecture.md#one-source-per-process`; `docs/development/ARCHITECTURE.md#composition-from-above-and-below`; `openspec/specs/marketplace-identity/spec.md#requirement-signing-and-verification-read-the-process-time-source` |
| D4 — Lane time moves only forward and is never reset | `openspec/specs/injected-time/spec.md#requirement-injected-time-is-frozen-at-the-instant-last-set-and-moves-only-forward`; `openspec/specs/test-compatibility/spec.md#requirement-every-party-in-a-lane-shares-one-lane-time-the-scenario-sets`; `openspec/specs/injected-time/architecture.md#frozen-injected-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| D5 — The time controls sit on each service's operator surface | the setting requirements of `market-composition`, `physical-provisioning`, `api-credits` and `registry-discovery` (`spec.md`); `openspec/specs/injected-time/architecture.md#the-component`; `docs/development/ARCHITECTURE.md#operator-lifecycle-controls`; `docs/operator-handbook.md#injected-time` |
| D6 — The time source is a standalone component | `openspec/specs/injected-time/spec.md#requirement-the-component-is-standalone`; `openspec/specs/injected-time/architecture.md#the-component`; `tools/injected-time/README.md`; `tools/README.md#injected-time`; `docs/guidance/repository/published-packages.md#published-packages` |
| D7 — One lane-time fixture sets every party | `openspec/specs/test-compatibility/spec.md#requirement-every-party-in-a-lane-shares-one-lane-time-the-scenario-sets`; `docs/development/TESTING.md#lane-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| D8 — The scenario rule restated | `docs/guidance/engineering/system-tests.md#a-scenario-is-a-sequence-of-state-changes`; `docs/guidance/repository/deal-scenarios.md#the-discipline-every-scenario-follows`; `docs/development/TESTING.md#lane-time`; the back-dating rewrite as unowned work in `openspec/changes/README.md`, "Unowned work found by `drive-the-storefront-clock-in-lanes`" |
| D9 — The change's name, its capabilities and the roadmap | `docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops` (both perceived-clock rows closed, the current state rewritten); `openspec/changes/README.md`, the change's row and its unowned rows |
| D10 — Implementation cadence | no permanent destination: it governed this change's rounds only |
| D11 — Injected time is frozen at an absolute instant | `openspec/specs/injected-time/spec.md#requirement-injected-time-is-frozen-at-the-instant-last-set-and-moves-only-forward`, `#requirement-lane-time-is-an-integer-of-unix-seconds-read-by-one-rule`; `openspec/specs/injected-time/architecture.md#frozen-injected-time`; `tools/injected-time/README.md` |
| D12 — An instance's time is never changed live | `openspec/specs/injected-time/spec.md#requirement-an-instances-time-is-changed-only-under-injected-time`; `openspec/specs/injected-time/architecture.md#no-live-change`; `docs/operator-handbook.md#injected-time`; `docs/development/ARCHITECTURE.md#operator-lifecycle-controls` |
| D13 — Database times are supplied where production logic reads them | `openspec/specs/injected-time/spec.md#requirement-database-times-production-logic-reads-come-from-the-source`; `openspec/specs/site-capacity/spec.md#requirement-the-site-decides-by-its-processs-time-source`; `openspec/specs/injected-time/architecture.md#database-times`; `openspec/specs/site-capacity/architecture.md` |
| D14 — The time-setting operation is exempt from request freshness | `openspec/specs/marketplace-identity/spec.md#requirement-the-time-setting-operation-is-exempt-from-request-freshness` and its modified "Body-bound authenticated request and response version"; `openspec/specs/marketplace-identity/architecture.md`; `docs/development/ARCHITECTURE.md#authenticated-service-boundaries` |
| D15 — The chain follows lane time | `openspec/specs/test-compatibility/spec.md#requirement-the-chain-follows-lane-time`; `docs/development/TESTING.md#lane-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| D16 — One time source per run | `openspec/specs/test-compatibility/spec.md#requirement-a-run-uses-one-time-source-throughout`; `docs/guidance/engineering/system-tests.md#time-a-test-does-not-control`; `docs/development/TESTING.md#lane-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| D17 — The local Helm release stays on wall time | `openspec/specs/deployment-state/spec.md#requirement-committed-configuration-outside-the-lanes-never-injects-time`; `docs/development/DEPLOYMENT_AND_CONFIG.md#release-topology` |
| D18 — The doubles take injected time | `openspec/specs/test-compatibility/spec.md#requirement-each-lane-double-reads-injected-time-the-scenario-sets`, `#requirement-the-sample-app-follows-lane-time-through-a-test-control`; `tools/lane-double-controls/README.md`; `tools/README.md#lane-double-controls`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| D19 — The harness and the buyer | `openspec/specs/buyer-orchestration/spec.md#requirement-the-buyer-reads-injected-time-from-a-lane-time-file`; `openspec/specs/buyer-orchestration/architecture.md#the-buyers-time`; `docs/development/TESTING.md#lane-time` |
| D20 — The check and the guidance | `docs/guidance/engineering/implementation.md#one-time-source-per-process`; `openspec/specs/injected-time/spec.md#requirement-each-process-reads-the-time-of-the-world-from-one-source`; `docs/guidance/repository/packaging-checks.md#checks`; `openspec/specs/injected-time/architecture.md#elapsed-work-is-measured-on-the-monotonic-clock` |
| D21 — Every Compose lane runs injected time | `openspec/specs/test-compatibility/spec.md#requirement-every-party-in-a-lane-shares-one-lane-time-the-scenario-sets`; `docs/development/TESTING.md#lane-time`; `openspec/specs/test-compatibility/architecture.md#lane-time-and-the-doubles-controls` |
| Roadmap currency | `docs/development/ROADMAP.md`, Goal 8 (18.5) |
| Campaign index currency | `openspec/changes/README.md`, the change's row and the Goal 8 lead (18.6) |
