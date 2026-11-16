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
    `requires-python >=3.11`, no runtime dependency; dev group `pytest` and `mypy`.
    Its `make test` runs `mypy src --strict` then the unit suite, as
    `tools/lane-double-controls` does; `make build` writes to its own `dist/` unless
    given `DIST_DIR`. The README is the component's interface (value, sources, time
    file, route service). Locked with `make lock PROJECTS=tools/injected-time`
    (12 packages, all from PyPI); a direct `python3 scripts/uv_project.py lock` was
    denied in this unattended run, and the make target runs the same command after
    `make dist`. The build evidence is the same `make build` reached through the
    root's `dist-injected-time` (`make -C tools/injected-time build` was denied:
    only `make -C <package> test` is admitted): `make dist`, run by `make
    check-packaging`, printed `cd tools/injected-time && make build
    DIST_DIR=…/.dist` and built `arkhai_injected_time-0.1.0-py3-none-any.whl`. The
    default `dist/` output, with no `DIST_DIR`, was not exercised.
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
    (`InvalidTimeSource` naming both), `install`/`installed`/`now`, and
    `TimeMovesForward` carrying both instants. Both sources take the wall clock
    through their constructor (`wall`, `time.time` by default), the seam a test
    moves. Unit, `tests/unit/test_source.py`, passes. "While real time passes" is
    driven in fake time, not spent (`test-determinism.md`): with a fake wall clock
    moved an hour and a day between reads, an injected source still reads the
    instant it started at or was last set to, while a wall source follows every
    move in whole seconds; the real wall instant a default source starts at is
    bracketed by two real wall reads.
- [x] 1.3 The value rule: one parser for `{"now": <value>}` — a JSON integer from 0 to
  253402300799, never a boolean, float or string, no missing `now`, no other member —
  reporting `invalid_time` (D11).
  - Verify: unit tests for each invalid form (`true`, `1794821400.5`,
    `"1794821400"`, `-1`, `253402300800`, `{}`, an extra member) and the two bounds.
  - Done: `injected_time.value` — `parse_time(raw)` for a JSON body,
    `read_time(document)` for a parsed one, `check_instant(value)` for a bare value,
    all one rule, plus `time_document(instant)`. Beyond the listed forms it also
    refuses `1794821400.0`, `null`, a member stated twice (the json module would keep
    the last), a non-object, and a body that is not JSON. Bytes are decoded as
    strict UTF-8 first, since `json.loads` would detect UTF-16 and UTF-32: invalid
    UTF-8 and a valid document encoded as UTF-16 or UTF-32 are refused. Unit,
    `tests/unit/test_value.py`, passes.
- [x] 1.4 The lane-time file's reader and writer: the writer writes `{"now": …}`
  atomically (a temporary file in the same directory, then a rename); the reader reads
  it on every call through 1.3's parser and raises, naming the file, on a missing,
  unreadable or invalid file (D19).
  - Verify: unit tests: a reader sees each write at its next read; every invalid file
    raises naming its path; a reader never observes a partial write.
  - Done: `injected_time.time_file.TimeFile(path)` — `now()` reads on every call
    (`TimeFileError` naming the path), `write(instant)` writes a temporary file
    beside the target, fsyncs it and `os.replace`s it, removing it on any failure.
    The component calls it a time file: the lane is this repository's use, and the
    component names none. A `TimeFile` is itself a source (`name` `injected`), so the
    buyer (section 14) installs `TimeFile(path)` directly. Library integration (the
    public API over real files in a temporary directory, so in
    `tests/integration/`, not `unit/` as the plan said),
    `tests/integration/test_time_file.py`, passes. What it shows of "never a partial
    write": a handle opened before a write still reads the whole previous document
    (the file is replaced, never written into), a write leaves nothing beside the
    file, and a write whose rename fails leaves the target untouched. It does not
    show the rename's atomicity, which is `os.replace`'s within one directory, nor
    tell a rename from a delete-then-create; the code does the former.
- [x] 1.5 The framework-free route service: a setting request answered
  `{"source": "injected", "now": …}`, refused `409 time_moves_forward` or
  `422 invalid_time` with nothing changed; the status section, `{"source": "injected",
  "now": …}` or `{"source": "wall"}` (D5, D6).
  - Verify: unit tests for each answer and refusal and both status forms.
  - Done: `injected_time.routes.TimeRouteService(source)` — `status()`,
    `set_time(body)` raising `TimeRouteError(status_code, code, detail)`, and
    `settable`, true only for an `InjectedTime`, which a binding reads to mount the
    setting route only under injected time. `set_time` takes the raw body, so a body
    that is not JSON is 422 `invalid_time` on every service rather than whatever its
    framework answers. Unit, `tests/unit/test_routes.py`, passes.
- [x] 1.6 The structure test holding the boundary: no import of a repository package or
  a third-party distribution (`injected-time`'s "The component is standalone").
  - Verify: the structure test passes, and fails on a planted import of `httpx` and of
    `market_identity`.
  - Done: `tests/unit/test_structure.py` passes. The planted imports are shown
    without editing the tree: the same check run over a source tree the test writes
    finds `import httpx`, `from market_identity import …` and a function-local
    `import httpx`. It also holds that `pyproject.toml` declares no dependency and
    that the lock resolves nothing but the component and PyPI.
- [x] 1.7 Put the component in the release set and the wheelhouse: declare it in
  `manifests/release-components.json` so `make dist` and `make dist-release` build it;
  add `make test-injected-time` to the root `test` target and the Tests workflow's
  matrix; admit a dependency on it from every architecture layer in
  `docs/development/ARCHITECTURE.toml` (D6).
  - Verify: `make dist` puts its wheel in `.dist`; `make test-injected-time` passes;
    `make check-packaging` passes.
  - Done: the declaration's first entry, since it depends on nothing and everything
    will depend on it; the root's `dist-injected-time` is in `dist-release-set`
    (so `dist` and `dist-release` build it) and in `dist-ci`; `test-injected-time`
    follows `test-frp-grant-admission` in `test` and in `tests.yml`'s matrix, which
    `scripts/tests/test_tests_workflow.py` holds in order. Outside the plan:
    `docs/guidance/repository/published-packages.md` gains the component's table row
    now, not at closeout, because `scripts/tests/test_publish_matrix.py` fails a
    declared distribution with no row.
  - Correction to the plan, no edit to `ARCHITECTURE.toml`: `make check-architecture`
    skips `tools/` (`[conventions] skip`), so `arkhai-injected-time` is not a project
    in its model, and a package declaring or importing it forms no internal edge —
    the layer, scope, dependency and kind-allowlist rules never see it, and naming it
    in a kind allowlist would fail the check's configuration rule, which refuses a
    distribution that is not a project. The one rule that sees it is a package's own
    allowlist: it counts as a third-party distribution, so each package with
    `allowed-dependencies` adds `arkhai-injected-time` to them in its own
    `pyproject.toml` when its section declares it, as `package-layers.md` places
    that list. D6's intent, every package may depend on it, holds with no rules-file
    row; its wording, "`make check-architecture` gains the allowance", is the
    round's triage's to amend, and closeout's promotion promises no such allowance.
  - Evidence: `make test-injected-time` (unit and library integration, 80 passed,
    mypy clean); `make
    check-packaging` passes, its wheelhouse holding the wheel; `make
    test-release-tooling` (the scripts' unit and static configuration tests, the
    publish table, the wheel-set dry runs and the matrix among them) 3126 passed.
- [x] 1.8 Section verification.
  - Unit: `make test-injected-time`.
  - `make check-packaging`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`, whose functional checks pass.
  - End-to-end: none; nothing depends on the component yet.
  - Owed by validation: `tests.yml`, job `test · test-injected-time` — the job exists
    and passes.
  - Confirmed: no end-to-end marker exercises the component; the owed job is in
    `tests.yml`'s matrix, a workflow `scripts/ci_evidence.py` lists.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`:
    `after-functional-change` and `pre-commit-functional` (every suite) passed;
    `pre-commit`'s default checks and strict OpenSpec validation passed, and of
    `check-repository` only the citations check failed, on
    `openspec/specs/injected-time/architecture.md` (written at closeout, 18.9) and
    `scripts/check_time_reads.py` with its test, which section 2 creates.
  - The component's tests import only what the section adds, so against the round's
    base each fails at collection, which shows less than a behavioural failure.
  - Handoff for sections 3–7. `injected_time.now` is the default a clock parameter
    takes; it reads the installed source at each call, so a test passing its own
    clock is unaffected. The source returns whole seconds, wall included: a read
    converted from `time.time()` or `datetime.now(...)` loses its fraction, which
    matters only where something ordered or compared sub-second instants, judged per
    read. A `datetime` is `datetime.fromtimestamp(injected_time.now(),
    timezone.utc)`; if that repeats widely, a helper may join the component (still
    0.1.0, unreleased). A package declaring the component needs `make dist` before
    its relock, its row's internal deps in `published-packages.md` gain
    `arkhai-injected-time` (`test_publish_matrix.py` holds them), and, if it has
    `allowed-dependencies`, that list gains it too: `core`, `domains/compute`,
    `kit/identity`, `kit/settlement-runtime`, `kit/schema-migrations`,
    `kit/deal-servicing`, `kit/deal-lifecycle`, `kit/deal-lifecycle-contracts`,
    `kit/deal-lifecycle-client`, `kit/deal-lifecycle-buyer`, `kit/contact-exchange`,
    `kit/capability-shape`, `kit/capability-pricing`, `kit/capability-admissibility`,
    `kit/resource-pools-contracts`, `kit/resource-pools-client`,
    `provisioning/compute/contracts` and `provisioning/compute/client`.

## 2. The wall-time read check and its guidance

Delivers the check and the engineering rule (D20). Implements the check half of
`injected-time`'s "Each process reads the time of the world from one source". Touches
`scripts/check_time_reads.py`, `scripts/tests/`, the root `Makefile`, and
`docs/guidance/engineering/implementation.md`.

- [ ] 2.1 Write `scripts/check_time_reads.py`: an AST scan of every project's `src/`
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
- [ ] 2.2 Write the engineering rule in `docs/guidance/engineering/implementation.md`,
  a new section "One time source per process": a process reads the time of the world
  from one time source and nothing else; a duration of its own activity — a timeout,
  a backoff, an interval — is measured on the monotonic clock, which neither stops
  when time is held nor jumps when it is set (D20). Neutral example, no market
  concept.
  - Verify: `make check-guidance` passes.
- [ ] 2.3 Section verification.
  - Unit: `make test-release-tooling` (the check's tests).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: none; the check reads source only.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `scripts/tests/test_check_time_reads.py` runs and passes.

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

- [ ] 3.1 Each package declares `arkhai-injected-time` and is relocked; each clock
  default (`lambda: int(time.time())` and its kind) becomes the process source, so a
  unit test injecting its own clock keeps working (D3).
  - Verify: each package's unit suite passes unchanged.
- [ ] 3.2 Convert every direct read 2.1 lists in these packages: time-of-the-world
  reads to the process source, elapsed-work reads to `time.monotonic()` (D20). Record
  each elapsed-work conversion in the task note.
  - Verify: `make check-time-reads` reports none of these packages.
- [ ] 3.3 Supply the read database times in `kit/fulfillment` and in
  `core/storefront`'s `sqlite_client.py` from the process source: ORM `func.now()`
  defaults on read columns become Python `default=`/`onupdate=` callables, raw SQL
  passes the time (D13).
  - Verify: library integration tests, one per store, with an injected source set to
    1794821400: every read column holds that instant, never the database's clock
    (`injected-time`'s "A row is written under injected time").
- [ ] 3.4 Section verification.
  - Unit and library integration: `make test-kits`, `make test-core`, and
    `domains/compute/delivery`'s suite.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' existing scenarios run these libraries at wall time,
    unchanged in behaviour; no new scenario is owed.

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

- [ ] 4.1 Each storefront declares `arkhai-injected-time`, relocked; every direct
  read converted as 3.2; the VM storefront's wall-time `EndService` constructions
  (`settlement_composition.py`'s terminal-settlement truncation, `failure_actions.py`'s
  fallback) and `request_delivery_end`'s default read the process source (D3).
  - Verify: `make check-time-reads` reports none of the three storefronts; each
    storefront's suite passes.
- [ ] 4.2 Supply the read database times in each storefront's stores from the process
  source (D13).
  - Verify: an application-integration test per storefront, through its typed client,
    with the process source injected at 1794821400 for the test: a deal or listing it
    writes holds 1794821400 in every read column.
- [ ] 4.3 Section verification.
  - Unit and application integration: `make test-domains` (the three storefronts).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' scenarios run the storefronts at wall time; no new
    scenario is owed.

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

- [ ] 5.1 Each package declares `arkhai-injected-time`, relocked; every direct read
  converted as 3.2. `rate_limit.py`'s window is elapsed work (monotonic); the lease
  watchdog's due check, expiry context and `terminate_lease`'s effective instant read
  the process source (D3).
  - Verify: `make check-time-reads` reports none of these packages.
- [ ] 5.2 Supply the read database times — hold expiry, lease end and activation, job
  scheduling and retry timing, relay grant expiry — from the process source (D13);
  audit-only columns keep their DDL default.
  - Verify: library integration tests in `kit/site` with an injected source: a hold
    expiring at 1794822300 lapses on the sweep after the source is set to 1794822300
    and not before (`site-capacity`'s "A hold expires at the set instant"); a lease due
    at an instant is listed due only once the source reaches it.
- [ ] 5.3 Section verification.
  - Unit and library integration: `make test-kits` (`kit/site`, `kit/resource-pools`,
    `kit/site-client`), `make test-compute-provisioning`,
    `make test-compute-provisioning-ansible`, `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the lanes' lease and teardown stages run this code at wall time; no
    new scenario is owed.

## 6. The registry and the API-credits service read the process source

Delivers the conversion (D3, D13) in the registry, the API-credits service and the
metering middleware. Touches `core/registry` (`api/listing_routes.py`,
`api/api_key_auth.py`, `api/utils.py`, `api/publisher_auth.py`,
`api/publisher_routes.py`), `domains/apicredits/service` (`db/models.py` and the site
ledger it hosts), `domains/apicredits/src/arkhai_apicredits/settlement/credits_client.py`,
and `domains/apicredits/middleware/python` (`signing.py`, `gate.py`).

- [ ] 6.1 Each package declares `arkhai-injected-time`, relocked; every direct read
  converted as 3.2; the middleware reads the process source its host installs for
  every timestamp it signs and every response it verifies, with no control of its own
  (D18).
  - Verify: `make check-time-reads` reports none of these packages; their suites pass.
- [ ] 6.2 Supply the read database times in the registry and the credits service from
  the process source (D13).
  - Verify: an application-integration test in each, with the source injected: a
    listing the registry stores, and a grant the credits service issues, hold the
    injected instant in every read column.
- [ ] 6.3 Section verification.
  - Unit and application integration: `make test-registry`, and `make test-domains`
    (the API-credits service and the Python middleware).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the API-credits lane's purchase runs this code at wall time; no new
    scenario is owed.

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
`tools/lane-double-controls/src/lane_double_controls/clock.py`,
the doubles' direct reads, the root `Makefile`, and
`docs/guidance/repository/packaging-checks.md`.

- [ ] 7.1 Each buyer package and client declares `arkhai-injected-time`, relocked;
  every direct read converted as 3.2; the watchdog's probe staleness is lane time, its
  probe interval and timeouts elapsed work (D3, D20).
  - Verify: `make check-time-reads` reports none of these packages; `make test-core`,
    `make test-kits` and the buyers' suites pass.
- [ ] 7.2 The signing clients take every request timestamp and every response
  freshness reference from the process source (`marketplace-identity`'s "Signing and
  verification read the process source").
  - Verify: unit tests in `core/storefront-client`, `core/registry-client` and
    `kit/deal-lifecycle-client` with an injected source at 1794822300: a signed
    request carries 1794822300, and a response stamped 1794822300 verifies.
- [ ] 7.3 Supply the buyer's read database or file times (its run log and buyer state)
  from the process source (D13).
  - Verify: a buyer test under an injected source finds the injected instant in the
    run log's read fields.
- [ ] 7.4 The doubles' direct reads go through the component's wall source:
  `lane_double_controls/clock.py`'s `wall_clock` and any direct read in the two
  doubles; their offset clocks stay until section 13.
  - Verify: `make test-lane-double-controls`, `make test-payments-lane-double` and
    `make test-mediation-lane-double` pass unchanged.
- [ ] 7.5 Make sure nothing is left: run `make check-time-reads` on the tree.
  - Verify: it reports no finding.
- [ ] 7.6 Switch the check on: `make check-packaging` runs `check-time-reads`, and
  `docs/guidance/repository/packaging-checks.md`'s "Checks" table gains its row (D20).
  - Verify: `make check-packaging` passes, and fails on a planted `time.time()` in a
    kit.
- [ ] 7.7 Section verification.
  - Unit and integration: `make test`.
  - `make check-packaging`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes, every module at wall time, as regression evidence
    for round one; no new scenario is owed.

## 8. The time-setting operation's freshness exemption

Delivers D14. Implements `marketplace-identity`'s "The time-setting operation is
exempt from request freshness" and the modified "Body-bound authenticated request and
response version". Touches `kit/identity` (`verification.py`), and the signed
administrator surfaces that will mount the setting route: `core/storefront`
(`auth.py`), `domains/vms/storefront` (`middleware/admin_identity.py`), the bare-metal
storefront's authentication in `api.py`, `provisioning/compute/service`
(`middleware/auth.py`), and `kit/site` (`auth.py`, the API-credits service's
middleware).

- [ ] 8.1 `market_identity` verifies a request without the timestamp's freshness only
  when its caller names the operation as the time-setting one; signature, principal,
  context, body hash and the request-id reservation are verified as for every request
  (D14).
  - Verify: unit tests: a setting request 900 s off the verifier's instant verifies;
    the same skew on any other operation is refused `TIMESTAMP_SKEW`; a changed body,
    a wrong principal or a reused request id is refused on the setting operation.
- [ ] 8.2 Each signed administrator surface above applies the exemption to its
  time-setting operation alone — the storefronts' `admin_time`, provisioning's and the
  credits service's setting operation — and to no other route (D14).
  - Verify: unit tests per middleware: the setting operation is admitted skewed; the
    pause operation skewed by the same amount is refused.
- [ ] 8.3 Section verification.
  - Unit: `make test-kits` (`kit/identity`, `kit/site`), `make test-core`, the
    storefronts' and `make test-provisioning`'s middleware tests.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: exercised by section 15's fixture once the lanes run injected
    (section 16).

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

- [ ] 9.1 Each storefront reads `[Time] source`, `"wall"` by default, refusing any
  other value naming it, and installs the process source at its composition root
  before anything reads time (D2).
  - Verify: unit tests per storefront configuration; an application-integration test
    that a storefront started with `"injectd"` refuses to start naming it.
- [ ] 9.2 `kit/storefront` gains the framework-free time route service over the
  component's (1.5); each storefront binds it at `POST /api/v1/admin/time` behind its
  administrator authentication, mounted only under injected time (D5, D12).
  - Verify: application-integration tests per storefront through the canonical
    client: set to 1794822300 answers source `injected` and now 1794822300 and the
    storefront's signed responses then carry 1794822300; an earlier instant answers
    `409 time_moves_forward`; `{"now": true}` answers `422 invalid_time`; a wall-time
    storefront serves no such route.
- [ ] 9.3 The signed system status, `GET /api/v1/system/status`, carries the time
  section in both modes; the canonical client's `get_system_status` reads it and gains
  `set_time` (D5).
  - Verify: application-integration tests for both modes through the client, for the
    VM and the bare-metal storefront at the same path and shape (`market-composition`'s
    "Both compute storefronts bind one route").
- [ ] 9.4 Startup announcement and warning: an injected storefront logs its source at
  startup; one with an Arkhai payments section whose `livemode` is `true` logs a
  warning naming both settings, and starts (D2).
  - Verify: application-integration tests capture both log lines.
- [ ] 9.5 Regenerate the storefronts' values schemas so the charts admit `[Time]`.
  - Verify: `make -C helm test-render` passes.
- [ ] 9.6 Section verification.
  - Unit and application integration: `make test-kits` (`kit/storefront`),
    `make test-core` (`core/storefront`, `core/storefront-client`),
    `make test-domains` (the three storefronts).
  - `make -C helm test-render`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets every storefront through this route once
    section 16 puts the lanes on injected time.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
    chart render tests pass with the regenerated schemas.

## 10. Provisioning's setting, route and status

Delivers D2, D5, D12 for the provisioning service. Implements `physical-provisioning`'s
"Provisioning time is configured and set on its system surface" and, at application
level, `site-capacity`'s "The site decides by its process's time source". Touches
`provisioning/compute/service` (`config.py`, `main.py`, `app_runtime.py`,
`controllers/system_controller.py`, the system status), and
`provisioning/compute/client`.

- [ ] 10.1 The service reads `time.source`, `"wall"` by default, refusing any other
  value naming it, installs the source at startup, logs it when injected, and mounts
  `POST /api/v1/system/time` behind its administrator authentication only under
  injected time; `GET /api/v1/system/status` carries the time section (D2, D5, D12).
  - Verify: application-integration tests through the provisioning client: set,
    `409 time_moves_forward`, `422 invalid_time`, status in both modes, no route under
    wall time, `"injectd"` refused.
- [ ] 10.2 The lease watchdog and the site follow injected time: a lease truncated to
  1794822300, the watchdog paused, the service set to 1794822300 and one watchdog cycle
  stepped, ends by expiry with effective instant and claimed deadline 1794822300; a
  termination under injected time states the injected effective instant
  (`physical-provisioning`'s scenarios).
  - Verify: application-integration tests through the provisioning client, mock
    executor.
- [ ] 10.3 The client gains `set_time` and the status time section.
  - Verify: `make test-compute-provisioning-client`.
- [ ] 10.4 Section verification.
  - Application integration: `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets provisioning once section 16 puts the lanes
    on injected time; serve-running's funds-exhausted rows exercise 10.2's path.

## 11. The registry's and the API-credits service's setting, route and status

Delivers D2, D5, D12 for the registry and the credits service. Implements
`registry-discovery`'s "Registry time is configured and set on its administrator
surface" and `api-credits`' "Credits service time is configured and set by its
administrator". Touches `core/registry` (`config.py`, `api/admin_routes.py`, its app
assembly), `core/registry-client`, `domains/apicredits/service` (`config.py`,
`main.py`, its route contracts), and the credits service's client
(`domains/apicredits/src/arkhai_apicredits/settlement/credits_client.py`).

- [ ] 11.1 The registry reads `TIME_SOURCE`, `"wall"` by default, refusing any other
  value naming it; installs the source and logs it when injected; serves
  `GET /admin/status` with the time
  section in both modes and, under injected time only, `POST /admin/time`, both behind
  `REGISTRY_ADMIN_API_KEY` as its other `/admin` routes are (D2, D5).
  - Verify: application-integration tests through the registry client: set, 409, 422,
    a missing or wrong key refused `401` with the time unchanged, status in both modes,
    no setting route under wall time; a storefront publication signed at the injected
    instant is accepted after both are set 1800 s forward.
- [ ] 11.2 The credits service reads `time.source`, refusing any other value naming
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
- [ ] 11.3 The registry client and the credits service's client gain the setting call
  and the status read; the registry client sends the administrator key.
  - Verify: `make test-registry-client`; the credits client's suite.
- [ ] 11.4 Section verification.
  - Application integration: `make test-registry`, `make test-registry-client`,
    `make test-domains` (the API-credits service).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets both once section 16 puts the lanes on
    injected time.

## 12. Committed configuration outside the lanes never injects time

Delivers D2's static check and D17. Implements `deployment-state`'s "Committed
configuration outside the lanes never injects time". Touches `scripts/tests/` (a
static configuration test) and, read only, the charts' defaults,
`helm/local-values.yaml`, the charts' production examples, and the shipped presets.

- [ ] 12.1 A static configuration test reads every committed configuration outside the
  lanes' own — chart defaults, `helm/local-values.yaml`, each chart's
  `examples/*values*.yaml`, the shipped storefront and buyer presets — the way their
  consumers read them, and fails naming the file and the party where any sets the time
  source to `"injected"`
  (`docs/guidance/repository/static-configuration-tests.md`).
  - Verify: it passes on the tree, and fails on a planted `[Time] source = "injected"`
    in `helm/charts/bare-metal-storefront/examples/production-values.yaml`.
- [ ] 12.2 Section verification.
  - `make test-release-tooling`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: pre-review validation's scenarios against the local Helm release run in
    wall mode (`deployment-state`'s "The local release is validated"), shown once
    section 15's wall mode exists.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
    static configuration test runs and passes.

## 13. The doubles and the sample app take injected time

Delivers D18 and the doubles' part of D21. Implements `test-compatibility`'s "Each
lane double reads injected time the scenario sets" and "The sample app follows lane
time through a test control", and removes "Each lane double reads a perceived clock
the scenario advances". Touches `tools/lane-double-controls` (`clock.py`,
`routes.py`, `models.py`, `client.py`, `README.md`), `tools/payments-lane-double`
(`app.py`), `tools/mediation-lane-double` (`app.py`), and
`domains/apicredits/sample-app` (`app.py`).

- [ ] 13.1 `lane-double-controls`: `PerceivedClock`, `CLOCK_ADVANCE` and `CLOCK_RESET`
  give way to the component's injected source and one `TIME` route,
  `POST /test/time {"now"}`, answering as D5 does with the same refusals; the status
  reports `{"source", "now"}`; the typed client gains `set_time` and loses
  `advance_clock` and `reset_clock` (D18).
  - Verify: `make test-lane-double-controls`.
- [ ] 13.2 Both doubles read the shared injected source, install it from a time-source
  setting in their configuration (`"injected"` in every lane), and serve the new route
  and status behind their control bearer token (D18).
  - Verify: `make test-payments-lane-double` and `make test-mediation-lane-double`,
    including: a once part's hold pays out at the next read after time is set past its
    release instant, with no background work.
- [ ] 13.3 The sample app installs its source from `APICREDITS_SAMPLE_APP_TIME_SOURCE`
  and, under injected time, serves `POST /test/time` and its status behind a control
  bearer token from its environment, through `lane-double-controls`' models and client,
  excluded from the metering gate (D18).
  - Verify: application-integration tests in the sample app's suite: the control sets
    the app's instant and is neither charged nor refused by the gate; after a set 3600 s
    forward with the credits service set alike, a metered call's consume request is
    accepted (`test-compatibility`'s "Metered calls continue after an advance").
- [ ] 13.4 Section verification.
  - Unit and application integration: `make test-lane-double-controls`,
    `make test-payments-lane-double`, `make test-mediation-lane-double`,
    `make test-domains` (the sample app).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes.
  - Owed by validation: `tests.yml`, jobs `test · test-lane-double-controls`,
    `test · test-payments-lane-double` and `test · test-mediation-lane-double` — each
    passes with the new route.

## 14. The buyer's injected time

Delivers D19's buyer half. Implements `buyer-orchestration`'s "The buyer reads injected
time from a lane-time file". Touches `core/buyer` (its profile configuration and CLI
entry) and the domain buyers' entry where they install anything at startup.

- [ ] 14.1 The buyer reads `[time] source` and `[time] file`; under `"injected"` it
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
- [ ] 14.2 A running `buy` with the watchdog sees a later instant at its next read.
  - Verify: an integration test in the buyer's suite drives the watchdog's staleness
    judgement across a file write, with no wall-time wait
    (`buyer-orchestration`'s "A running purchase sees an advance").
- [ ] 14.3 Section verification.
  - Unit and integration: `make test-core` (`core/buyer`), `make test-kits`
    (`kit/deal-lifecycle-buyer`), the domain buyers' suites in `make test-domains`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes run every buyer stage on the lane-time file.

## 15. The lane-time fixture, the chain and the run modes

Delivers D4, D7, D15, D16 and D19's harness half. Implements `test-compatibility`'s
"Every party in a lane shares one lane time the scenario sets", "The chain follows
lane time" and "A run uses one time source throughout". Touches
`e2e-tests/tests/e2e/roles/helpers/` (a new `lane_time.py` replacing
`lane_doubles.py`'s clock half, `compute_deal_stages.py`'s `wait_until`), the e2e
conftests, the runner profiles `e2e-tests/config/config-*.yml`, and
`e2e-tests/tests/unit/`.

- [ ] 15.1 The harness installs an injected source in its own process for an injected
  run; its signing clients read it (D19).
  - Verify: e2e unit tests: a client built in the harness signs at the harness's
    instant.
- [ ] 15.2 The runner profile names the run's mode, `injected` or `wall`, and every
  party: each storefront, provisioning service, registry, the credits service and the
  sample app where the lane runs them, both doubles, the chain, and the buyer's file
  path (D7, D16).
  - Verify: e2e unit tests: a profile naming a party it cannot reach fails setup
    naming it, never skips.
- [ ] 15.3 `lane_time.set(T)`: moves the harness's own source, then each service
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
- [ ] 15.4 Session start: in an injected run, set every party to the wall instant at
  the session's start; in any run, read every status and fail naming a mix of sources
  (D11, D16).
  - Verify: e2e unit tests: a mix fails naming the wall-time party.
- [ ] 15.5 The helper shared stages use to reach an instant: in an injected run it
  sets lane time; in a wall run it waits for an instant the Agreement fixes, and any
  other instant is a blocked skip naming the wall-time target. `wait_until` callers move
  to it; `lane_double_clock` and `clocks_reset_after` are removed (D8, D16).
  - Verify: e2e unit tests for both modes and the blocked skip
    (`test-compatibility`'s "A time-driven module against a hosted target").
- [ ] 15.6 Section verification.
  - Unit: `make test-e2e-unit`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes.
  - Owed by validation: `tests.yml`, job `test · test-e2e-unit` — passes with the
    fixture's tests.

## 16. Every Compose lane on injected time

Delivers D21 and D17's lane half. Implements the lane scenarios of
`test-compatibility`'s requirements. Touches the lanes' Compose files
(`compose.vms-lane.yml`, the bare-metal and API-credits lane files) and the
configuration they mount for every party, the e2e runner profiles,
`e2e-tests/tests/e2e/roles/scenarios/vms/dispute/test_hold_passed.py`, and the stages
that advanced the doubles.

- [ ] 16.1 Each lane's committed configuration sets the injected source for every
  party: each storefront's `[Time] source`, provisioning's and the credits service's
  `time.source`, each registry's `TIME_SOURCE`, the sample app's
  `APICREDITS_SAMPLE_APP_TIME_SOURCE` and control token, both doubles, and the buyer
  profile's `[time]` section with the file path the harness writes (D21, D19).
  - Verify: the e2e unit tests' stack checks read each lane's Compose configuration and
    find every party injected.
- [ ] 16.2 `test_hold_passed.py` sets lane time past the part's terms end and release
  instant instead of advancing the doubles (D18).
  - Verify: `make -C e2e-tests` runs the VM lane's `e2e_vm_dispute_hold_passed` module
    locally and it passes.
- [ ] 16.3 Run each lane locally (`make -C e2e-tests test-e2e`).
  - Verify: the three lanes pass, every module on injected time, the session fixture
    confirming every party; record each lane's pass counts in the task note.
- [ ] 16.4 Section verification.
  - System: the three lanes locally, 16.3.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: every module of the three lanes, the hold-passed module
    (`e2e_vm_dispute_hold_passed`) the one that moves time; pre-review validation's
    Helm scenarios (`contracts`, `e2e_alkahest_escrow_codecs`,
    `e2e_alkahest_trusted_oracle`) in wall mode.

## 17. The scenario rule restated

Delivers D8 and D16's ladder. Touches `docs/guidance/engineering/system-tests.md`,
`docs/guidance/repository/deal-scenarios.md`, and `docs/development/TESTING.md`.

- [ ] 17.1 `system-tests.md`, "A scenario is a sequence of state changes": the clock
  bullet becomes reaching an instant by setting the time every party perceives,
  together, back-dating admitted below it and discouraged; a new section "Time a test
  does not control" states D16's ladder, neutrally (D8, D16).
  - Verify: `make check-guidance` passes.
- [ ] 17.2 `deal-scenarios.md`, "The discipline every scenario follows", and
  `TESTING.md`, "4. System Integration Tests (End-to-End)": lane time across every
  party, the lane-time fixture and its order, never reset, the chain, the two run
  modes, the buyer's file; the doubles' perceived-clock text and `lane_double_clock`
  removed (D4, D7, D8, D15, D16, D19, D21).
  - Verify: `make check-doc-citations CHANGE=drive-the-storefront-clock-in-lanes`
    passes.
- [ ] 17.3 Section verification.
  - `make check-guidance`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: none; documentation only.

## 18. Closeout

The workflow's parts (`docs/guidance/workflow/closeout.md`) in order, the
repository's own at their position (`openspec/README.md`, "This repository's closeout
parts"). Closeout changes only the inert paths, the change's records and the
archive's writes; a part needing any other edit returns the change to implementation.

- [ ] 18.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
  the comments sections 1–17 added — in the component, the converted modules, the
  routes, the doubles and the harness — for any naming this change, a task or a
  review, or calling the conversion new.
- [ ] 18.2 **Import placement — confirm.** Check the imports sections 1–17 added,
  every `injected_time` import among them, for any left local without a recorded
  reason.
- [ ] 18.3 **Documentation compliance.** Re-check D1–D21 against
  `openspec/README.md`'s placement table; confirm each document 18.9 writes describes
  the current state; confirm no permanent document still describes the doubles'
  perceived clock, `lane_double_clock`, `/test/clock/advance` or `/test/clock/reset`,
  or a storefront step forbidden after an advance.
- [ ] 18.4 **Narrative compression.** Shorten the task notes to final behaviour,
  evidence and deferred work.
- [ ] 18.5 **Roadmap currency.** `docs/development/ROADMAP.md`, Goal 8: the open-gap
  row "No storefront step can follow a lane double's clock advance…" removed as closed;
  the deferred row "A perceived clock for the site and the buyer half…" removed as
  closed by lane time; the current-state paragraph's account of the doubles' perceived
  clock rewritten to lane time across every party (D9).
- [ ] 18.6 **Campaign index currency.** `openspec/changes/README.md`: this change's
  row; `converge-ongoing-compute-leases`' row and task 4.1a and
  `serve-running-rate-deals`' open question noted as answered where their rows name
  them; the unowned entries under "Unowned work found by
  `drive-the-storefront-clock-in-lanes`" kept (D9). Run `make check-change-index`.
- [ ] 18.7 **Packaging.** `make check-packaging`, `check-time-reads` among it, and
  `make check-architecture-change CHANGE=drive-the-storefront-clock-in-lanes`;
  resolve every failure.
- [ ] 18.8 **End-to-end pipeline.** Dispatch `make run-e2e` at the closeout's code,
  collect with `make fetch-e2e-logs`, and record the run, its result, and the scenarios
  exercising the change: every module of the three lanes on injected time, the
  hold-passed module the one moving time. A failed run returns the change to
  implementation.
- [ ] 18.9 **Promotion.** Write, and complete the design-promotion record below:
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
  - `docs/guidance/engineering/configuration.md`: a new section "A test control the
    production image carries is off by default" — off by default, omitted from
    production configuration, never refused (D2);
  - `openspec/specs/test-compatibility/architecture.md`: "The doubles' controls and
    perceived clocks", renamed "Lane time and the doubles' controls" (D1, D4, D7, D15,
    D16, D18, D21);
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
- [ ] 18.10 **Guidance placement.** Read the guidance sections sections 2, 17 and 18.9
  wrote — `implementation.md`'s "One time source per process", `configuration.md`'s
  new section, `system-tests.md`'s rewritten bullet and "Time a test does not
  control", `deal-scenarios.md`, `packaging-checks.md`'s row — against the layer test;
  run `make check-guidance`.
- [ ] 18.11 **Documentation citations.** Run `make check-doc-citations
  CHANGE=drive-the-storefront-clock-in-lanes` and resolve every match; then
  `scripts/change-workflow openspec validate drive-the-storefront-clock-in-lanes
  --strict`.
- [ ] 18.12 **Archival.** `scripts/change-workflow openspec archive
  drive-the-storefront-clock-in-lanes -y`, merging the deltas into `openspec/specs/`.

## Design promotion record

Completed at closeout (18.9).
