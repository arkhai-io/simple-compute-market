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
  - Correction (section 3): `requires-python` is now `>=3.10`. `kit/identity`,
    `kit/settlement-runtime`, `kit/policy`, `kit/alkahest` and `kit/arkhai-payments`
    declare `>=3.10`, and a dependency must admit a dependent's whole range; the
    package's source uses nothing 3.11 added (read, not run on 3.10). Its own
    structure test reads `pyproject.toml` with `tomllib`, so the suite needs 3.11,
    as the repository's 3.13 gives it. The README says 3.10.
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
  - Amendment (section 3): `now_datetime()` joins the module, the installed
    source's instant as an aware UTC `datetime` (microsecond 0), since the aware
    form replaces dozens of `datetime.now(timezone.utc)` reads across sections
    3–7; README and a unit
    test (`test_the_installed_instant_reads_as_an_aware_utc_datetime`) with it.
    `make -C tools/injected-time test`: 81 passed, mypy clean.
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
  - Done: names are resolved from every import in the module, wherever it sits
    (an import inside a function binds too); a refused read counts whether called
    or passed as a value (`clock=time.time`, `default_factory=datetime.now`), except
    `gmtime`/`localtime`, refused only when called with no argument or with `None`
    (which also converts the current instant; outside the design's wording, inside
    its intent). Each read counts, two of one form on one line included. Scope:
    each directory under the four roots holding a `pyproject.toml`, its `src/`
    alone (nested projects, such as `core/buyer` under `core`, are their own), and
    the three doubles; `tools/injected-time`, the other standalone components (the
    relay's grant-admission plugin takes its clock as a constructor argument
    defaulting to the wall clock, depends on no internal package, and runs on wall
    time, D16), tests and environments are outside it, as the script's docstring
    says. It prints each finding as `path:line: <form> …`, then the count per
    project, and exits 1 on any. `make check-time-reads`, in no aggregate target.
    Unit, `scripts/tests/test_check_time_reads.py` (53 tests: every refused form
    under `import time`, `from time import …`, `import datetime` and `from datetime
    import …`, and under an alias of the module and of the function or class; the
    `None` forms; reads passed as values; the permitted forms — `monotonic`,
    `perf_counter`, `sleep`, `gmtime`/`localtime` with an instant or uncalled,
    `fromtimestamp`, a method or function merely named `now` or `time`; a clean
    module; two reads of one form on one line; the scope over a written tree; the
    command's output and exit), passes in `make test-release-tooling`. Each test
    imports the module only this section adds, so against the round's base it
    fails at collection. Not caught, none present in scope: star imports, a name
    rebound locally (`DT = datetime.datetime`), `.now()` on a subclass or an
    instance, and `gmtime`/`localtime` passed uncalled as a factory; a local named
    like an imported module in the same module would be read as it.
  - The tree, the round's work list: 207 findings in 37 projects (the design's
    "about 221" counted by text):

    | Findings | Project | Findings | Project |
    |---|---|---|---|
    | 6 | `core/buyer` | 3 | `kit/alkahest` |
    | 26 | `core/registry` | 1 | `kit/arkhai-mediation` |
    | 3 | `core/registry-client` | 1 | `kit/arkhai-payments` |
    | 31 | `core/storefront` | 1 | `kit/contact-exchange` |
    | 4 | `core/storefront-client` | 4 | `kit/deal-lifecycle-buyer` |
    | 2 | `domains/apicredits` | 3 | `kit/deal-lifecycle-client` |
    | 2 | `domains/apicredits/buyer` | 1 | `kit/delivery` |
    | 2 | `domains/apicredits/middleware/python` | 4 | `kit/fulfillment` |
    | 1 | `domains/apicredits/service` | 2 | `kit/identity` |
    | 8 | `domains/apicredits/storefront` | 1 | `kit/negotiation-runtime` |
    | 1 | `domains/bare_metal/buyer` | 1 | `kit/policy` |
    | 1 | `domains/bare_metal/provisioning/adapter` | 5 | `kit/settlement-runtime` |
    | 12 | `domains/bare_metal/storefront` | 14 | `kit/site` |
    | 5 | `domains/vms/buyer` | 2 | `kit/site-client` |
    | 1 | `domains/vms/negotiation` | 2 | `kit/storefront` |
    | 1 | `domains/vms/provisioning/adapter` | 13 | `provisioning/compute` |
    | 27 | `domains/vms/storefront` | 2 | `provisioning/compute/ansible` |
    | 1 | `tools/lane-double-controls` | 1 | `provisioning/compute/client` |
    | | | 12 | `provisioning/compute/service` |

    `make check-time-reads` lists each by file and line. Projects the plan names
    that report none: `kit/deal-servicing` (its `EndService`, `DealWatch`,
    `DeliveryIngress`, `SellerServicing` and `RespondentPoller` take `clock` with
    no default, so their wall reads are their compositions'), and
    `domains/compute/delivery`,
    `kit/capacity-publication`, `kit/pool-overrides`, `kit/resource-pools` and the
    payments and mediation doubles hold none. No `time.ctime()`, `time.asctime()`
    or one-argument `time.strftime(...)`, which also read the wall clock and are
    outside the design's list, appears in scope.
- [x] 2.2 Write the engineering rule in `docs/guidance/engineering/implementation.md`,
  a new section "One time source per process": a process reads the time of the world
  from one time source and nothing else; a duration of its own activity — a timeout,
  a backoff, an interval — is measured on the monotonic clock, which neither stops
  when time is held nor jumps when it is set (D20). Neutral example, no market
  concept.
  - Verify: `make check-guidance` passes.
  - Done: the section sits before "Operator lifecycle controls", with a billing
    service's invoice stamp and its retry bound as the example, and says a
    function taking a clock defaults it to the process's source for the time of the
    world and to the monotonic clock for a duration; the file's opening
    and the `implementation` tag's description in `docs/guidance/engineering/README.md`
    name the new subject. `make check-guidance` passes. The `check-time-reads`
    target's comment cites the section.
- [x] 2.3 Section verification.
  - Unit: `make test-release-tooling` (the check's tests).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: none; the check reads source only.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` —
    `scripts/tests/test_check_time_reads.py` runs and passes.
  - Evidence: `make test-release-tooling` 3179 passed; `make check-guidance`
    passes; `make check-time-reads` runs and reports the work list above (exit 1,
    expected until section 7.5). `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`: `after-functional-change` and
    `pre-commit-functional` (every suite) passed; of `pre-commit`, only the
    citations check failed, on `openspec/specs/injected-time/architecture.md`, which
    closeout's promotion writes (18.9).
  - Confirmed: no end-to-end marker exercises the check; the owed job runs
    `make test-deployment-packaging`, whose `test-release-tooling` collects
    `scripts/tests/`.
  - Handoff for sections 3–7: run `make check-time-reads` for the exact list; its
    counts are per project, so a section converts the projects it names until they
    drop out of the summary. A read passed as a value (a clock default) is a
    finding, so a `clock: Callable = time.time` default converts to
    `injected_time.now`, and a `time.monotonic` default stays.

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
    `kit/settlement-runtime`, `kit/contact-exchange`) list it and map its import
    name to it under `[tool.arkhai.architecture.import-roots]` (`injected_time =
    "arkhai-injected-time"`; without it `make check-architecture` reads the import
    as a distribution `injected-time` the allowlist does not name), and every
    `published-packages.md` row names it. `kit/identity`, whose lock now installs
    a wheelhouse package, gains the `reinit` target `make check-uv-setup` requires
    (`project-environments.md`). The API-credits domain's wheel-install tests
    build their own wheel set (`domains/apicredits/tests/conftest_wheels.py`), which
    now builds the component too. Relocked with `make lock` (full). Defaults
    now the source: `SettlementRuntime`'s and `AlkahestConditionalEscrowClient`'s
    `clock` (`injected_time.now`), `ClausePublication.clock`, `NegotiationRuntime`'s
    `now`, `IntroductionRetentionService`'s and `AlkahestChainProbe`'s `clock`,
    `StorefrontLoopController`'s outcome stamp (`now_datetime`),
    `ServicePeerTrust`'s `clock`, the payments adapter's `clock` (the one `RateParts`
    is given) and the mediation adapter's `clock`.
  - Correction to the plan: `kit/deal-servicing` and `domains/compute/delivery` are
    untouched and declare nothing. Their `EndService`, `DealWatch`,
    `DeliveryIngress`, `SellerServicing`, `RespondentPoller` and the delivery path
    take `clock` with no default (2.1's note), so their reads are their
    compositions' (section 4 converts the VM ones); `diagnostics.py` already
    measures a step on `time.monotonic`. `kit/arkhai-payments`' `client.py` holds no
    wall read (its poll deadline is already monotonic).
  - "Unchanged" does not hold for eight tests, each of which compared a whole-second
    source read with a sub-second wall read, or relied on real time passing between
    two stamps: in `core/storefront`'s `test_site_projections.py`, three take an
    injected source (`test_fetched_at_set_on_successful_load` asserts the source's
    instant; the advance and failing-version-check tests move it between loads);
    `kit/settlement-runtime`'s `test_servicing.py`, four, unit and integration
    (`before = int(time.time())`); and `kit/fulfillment`'s
    `test_recovery_diagnostics_reports_per_state_counts_and_ages`, a real-database
    test that sat under `unit/`, so touching it moved it (`test-levels.md`,
    "Integration tests"): it is now
    `tests/integration/test_injected_time.py::test_recovery_diagnostics_count_claims_and_age_rows_against_the_source`,
    on the baseline schema and driven by the source. A ninth, outside the plan:
    `test_fetched_at_unchanged_on_failed_poll` never ran its coroutine; it now does,
    with the source moved before the failed poll. Two storefront tests broke on
    core's whole-second `fetched_at`, each expecting a projection poll's stamp to grow
    between two polls without time moving: the VM storefront's
    `test_a_round_past_the_window_is_retryable_until_the_projection_is_stepped` and
    the bare-metal `test_an_expired_confirmation_refuses_until_a_poll_confirms_the_site`.
    Both take an `injected_source` fixture, in a new `tests/conftest.py` of each
    storefront (120 s behind the wall clock: the canonical client still signs on the
    wall clock, and a signed hop allows 300 s), and set it a second past the first
    poll before stepping. `kit/fulfillment`'s import-boundary
    test admits `injected_time` in `scheduler.py`, `db.py` and
    `settlement_repository.py`.
  - Versions, outside the plan: `kit/delivery` 0.2.2 and `kit/delivery-apprise` 0.1.2
    (its exact pin moved), with their exact pins in `core/buyer` and the VM and
    bare-metal storefronts; every other package here was already bumped on `dev`
    since `marketplace-v0.3.0`, the newest release. `kit/identity` (0.4.0) and
    `kit/storefront` (0.10.0) carry released versions and are owed one bump each by
    this change: section 8's freshness exemption changes `kit/identity`'s API and
    section 9 adds `kit/storefront`'s time route service, so each takes its minor
    bump there and moves its exact pins once (`versioning.md`, "One bump per unit of
    work").
- [x] 3.2 Convert every direct read 2.1 lists in these packages: time-of-the-world
  reads to the process source, elapsed-work reads to `time.monotonic()` (D20). Record
  each elapsed-work conversion in the task note.
  - Verify: `make check-time-reads` reports none of these packages.
  - Done: all 53 reads in these packages were the time of the world (stamped,
    signed, or compared with another party's instant, or stored and compared
    later), so none became monotonic. Aware UTC reads use `now_datetime()` (the
    component's, see 1.2's amendment). `core/storefront`'s store stamps its text
    columns through `store_timestamp()`, public so the storefronts' stores share it
    (section 4): UTC with no offset, which is what the stale-negotiation sweep
    (`parse_timestamp`) already read it as, where the old `datetime.now()` wrote
    local time. `kit/policy`'s message timestamp takes the same form. Stored leases
    count as lane time by D20's rule (stored, compared later): the fulfillment
    convergence claim and its poll interval (`claim_expires_at`), settlement
    servicing's retry schedule, the storefront's escrow and delivery convergence
    leases.
  - Outside the plan, ties: the source is whole seconds and, injected, holds one
    instant across many writes, so every query here that orders by a timestamp the
    store writes breaks ties by insertion: `core/storefront`'s escrow, credential,
    listing and thread lists (`rowid`) and a negotiation's stage events (`id`).
    `kit/fulfillment`'s claim order ties as it did under `CURRENT_TIMESTAMP`, which
    was whole seconds already.
  - Evidence: `make check-time-reads` lists none of these packages (154 findings
    left, all in later sections' packages).
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
  - Evidence, library integration, both at 1794821400:
    `kit/fulfillment/tests/integration/test_injected_time.py` (2 tests on the
    baseline migration's schema, fixtures in that directory's `conftest.py`: both
    `created_at` columns and the claim and progress leases hold the injected
    instant; diagnostics count active and lapsed claims and age the oldest row
    against the source as it is set forward an hour — the expiry the spec's scenario
    names) and `core/storefront/tests/integration/test_injected_time.py` (four tests
    over the migrated database — an escrow's `created_at` and `updated_at`, a thread's
    `updated_at` after a terminal update, a credential's `created_at`, three stage
    events' `ts` — and one that checks the stored text form denotes the instant).
    Not asserted under injected time: `negotiation_threads.created_at` (written only
    when a thread is created, which needs a domain binding the test does not build),
    the replay reservation's `lease_until` (the caller's `now` plus the lease; the
    storefront's authentication now passes the source) and a publication's
    `published_at` (the source when the caller gives none). `make -C kit/fulfillment
    test` 212 passed; `make -C core/storefront test` 232 passed. Against the round's
    base the core test fails at collection (`ModuleNotFoundError: injected_time`,
    `run test-before`), which shows less than a behavioural failure; the fulfillment
    test likewise imports only what the change adds.
  - Round-1 triage fix (33 F1): the list above missed `kit/contact-exchange`'s
    `contact_introductions.created_at`, the reveal time the retention sweep filters
    and orders by, which an insert left to SQLite's `strftime(…,'now')` default
    while the sweep's cutoff read the source. `insert_introduction` now writes it
    from the source in the table's text form (`format_introduction_timestamp`); the
    DDL default stays, since the v0.3.0 baseline is frozen and dropping it would
    take a migration D13 does not ask for, and the redaction trigger, which only
    keeps `created_at` unchanged, is untouched. Audit-only, keeping its default:
    `contact_introduction_seller_dispatches.claimed_at`, which nothing reads.
    Evidence, library integration,
    `kit/contact-exchange/tests/integration/test_injected_time.py` (the baseline
    schema over a real SQLite file, the source injected at 1794821400): a normal
    insert holds the source's instant, and the retention service on its default
    clock keeps the introduction one second before the window ends and redacts it
    at the window's end, `payloads_deleted_at` that instant. `make -C
    kit/contact-exchange test` 147 passed. With the insert's `created_at`
    withdrawn the test fails, the row holding the wall clock's instant; `run
    test-before` at `b44ba08b4` fails only at collection (`injected_time` absent
    from its project-less environment).
- [x] 3.4 Section verification.
  - Unit and library integration: `make test-kits`, `make test-core`, and
    `domains/compute/delivery`'s suite.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' existing scenarios run these libraries at wall time,
    unchanged in behaviour; no new scenario is owed.
  - Evidence: `make test-kits` passes (every kit, `kit/settlement-runtime` 302 among
    them; `kit/fulfillment` 212 after its moved test). `scripts/change-workflow run
    pre-commit drive-the-storefront-clock-in-lanes`, run once over sections 3 and 4
    together before they were committed apart: `after-functional-change` (`make
    lock`) and `pre-commit-functional` (`make dist-clean`, `make check-packaging`,
    `make test` — every suite, `make test-core`, `make test-domains` and
    `domains/compute/delivery`'s among them) passed; of `pre-commit`, only the
    citations check failed, on `openspec/specs/injected-time/architecture.md`, which
    closeout's promotion writes (18.9). The first two runs failed on what this
    section then fixed: `check-uv-setup` (`kit/identity`'s `reinit`),
    `check-architecture` (the `import-roots` entries) and the API-credits domain's
    wheel-install tests (their wheel set).
  - Confirmed: no new end-to-end marker; every lane module runs these libraries,
    still at wall time. No owed CI evidence: the suites run in the workflows' existing
    jobs.
  - Handoff. The process source returns whole seconds, so a test comparing a source
    read with `time.time()` or expecting two stamps to differ without moving time
    fails; drive an injected source instead (`InjectedTime(start=…)`, installed and
    restored by a fixture). A signed test through a client still on wall time
    (sections 7's clients) must inject an instant within 300 s of the wall clock.
    Stored leases on lane time — fulfillment convergence's claim and poll interval,
    settlement servicing's retry, the storefronts' convergence leases — do not lapse
    while injected time is held: section 16's lanes may need a stage to set time past
    a retry or a step through the loop's control (D13, D20 classify them so).

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
  - Done: the three storefronts declare `arkhai-injected-time>=0.1.0` (and their
    `published-packages.md` rows), relocked with `make lock`. All 47 reads were the
    time of the world, none elapsed work: VM 27, bare metal 12, API credits 8. The VM
    storefront's two wall-time `EndService` constructions, `request_delivery_end`'s
    default and `VmDealLifecycle`'s clock read `injected_time.now`; the bare-metal
    runtime's `lifecycle_clock` and `source_confirmation_clock` defaults are the
    source (its private wall helpers removed), as are both storefronts'
    listing-source check clocks and the API-credits issuance evidence clock. Each
    writer keeps the text form it wrote: the naive stamps (the VM and API-credits
    listing services, the escrow obligation binding) use core's
    `store_timestamp()`, the aware ones `now_datetime()`. A listing's columns held
    both forms before this change (core's updates naive, the bare-metal publication
    and the VM carryover aware), and still do; they sort together, sharing their
    first nineteen characters. `utils/zerotier.py`, which the plan names, holds no
    wall read (its waits are already monotonic) and is untouched.
    No version bump: all three storefronts were bumped on `dev` since the last
    release, and `arkhai-core-storefront>=0.18.0`, which they already require, is
    the unreleased version that adds `store_timestamp`.
  - Outside the plan: `vm_delivery_records`' convergence list orders by
    `updated_at, rowid` (3.2's ties). `domains/apicredits`' `credits_client.py` keeps
    its two reads for section 6, which names it.
  - Evidence: `make check-time-reads` lists none of the three (107 findings left);
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
    1794821400. The canonical client signs and checks responses on the wall clock
    until section 7 converts it, so an instant hours from now fails the 300 s skew on
    the signed hop; 120 s behind keeps every hop valid while each stamp is told apart
    from a wall read. Each suite's `conftest.py` holds the `injected_source` fixture
    (the VM and bare-metal ones came with section 3, the API-credits one here).
  - Evidence, through `StorefrontClient` over ASGI: bare-metal
    `test_http_publication_settlement.py::test_a_published_listing_holds_the_injected_instant`
    (the administrator's publication step on the composed app) and API-credits
    `test_alkahest_release_conditions.py::test_a_published_listing_holds_the_injected_instant`
    (the started app, a seller's quota publication) are application integration.
    The VM `test_listings_api.py::TestCreateListing::test_a_created_listing_holds_the_injected_instant`
    is narrower: a FastAPI app holding only the listings router, its seller
    middleware and a real `ListingService` over the migrated database, the existing
    suite's fixture, not the composed storefront. Each reads the listing's two
    columns and its binding's `last_reconciled_at` from the database and finds the
    injected instant in its stored form. Library integration for the VM store:
    `tests/integration/test_delivery_record_times.py` (a delivery record's
    `created_at`/`updated_at` and convergence lease hold the source's instant as it is
    set forward, and another worker's claim is refused until the source passes the
    lease). They pass in the suites above. A deal's escrow, thread and stage-event
    columns are core's store, asserted by 3.3's test, not through a storefront.
- [x] 4.3 Section verification.
  - Unit and application integration: `make test-domains` (the three storefronts).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes' scenarios run the storefronts at wall time; no new
    scenario is owed.
  - Evidence: the three storefronts' suites (4.1); `make test-domains` and the
    pre-commit run, once over sections 3 and 4 together, as 3.4 records: every
    functional hook passed, and of `pre-commit` only the citations check failed, on
    closeout's `openspec/specs/injected-time/architecture.md`. After section 3 was
    committed apart, the three storefronts were relocked with their declarations
    (`make lock PROJECTS=…`), restoring the tree the run checked.
  - Confirmed: no new end-to-end marker; the lanes run these storefronts at wall
    time. No owed CI evidence.
  - Handoff for sections 5–7: a storefront's store writes its text timestamps through
    `core_storefront.sqlite_client.store_timestamp()`. A test through the canonical
    client takes the suite's `injected_source` fixture, 120 s behind the wall clock,
    until section 7 converts the clients; once it does, a test may inject any instant,
    1794821400 included, since client and server then read one source. The session
    that implemented sections 3 and 4 grew large; sections 5–7 are better started
    fresh.

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
    and the VM and bare-metal provisioning adapters. Relocked with `make lock` (full).
    46 reads converted: 44 time of the world, 2 elapsed work — the Ansible runner's
    log-flush interval (`runner.py`) is now `time.monotonic()`. Time of the world:
    the ledger's window start, hold expiry, release, activation and release-request
    stamps, a lease end's default effective instant and the instant availability is
    judged at; the lease watchdog's due check, expiry context, stalled-release grace
    and `terminate_lease`'s effective instant; the job engine's retry time (naive
    UTC, as stored, through its `_utcnow`); the relay allocator's lease stamp,
    release, reconciliation cutoff and reuse quarantine, and the relay service's key
    activation and retirement; the principal authority's validity check and rotation
    verification; the provisioning and site middlewares' request verification,
    response stamp and replay dispatch lease; both outboxes' attempt stamps and the
    capacity-released lifecycle event's `occurred_at`; the site and provisioning clients'
    request timestamps and response freshness reference (the provisioning client's
    `_unix_time` seam stays, reading the source); both mock outputs' timestamps.
  - Correction to the plan: `rate_limit.py` was already monotonic and is untouched;
    `kit/resource-pools` holds no wall read (it declares `arkhai-injected-time`
    since the round-1 triage, for its reported times, 5.2);
    `provisioning/compute/ansible` declares nothing, its two reads being elapsed
    work; `relays/db.py` and the migrations are untouched (5.2).
  - Outside the plan, a defect the whole-second source exposes: a retired relay
    grant key's `grants_valid_until` counted only leases created strictly before the
    retirement, which sub-second stamps used to order. In one second the order is
    lost, so a lease allocated in the retirement's second now counts
    (`relays/service.py`, `<=`): the bound may be later than needed, never earlier
    than a grant in use. `test_relay_administration.py` holds both sides under an
    injected source (a lease a second later does not extend the key; one in the same
    second does). For the round's triage: `physical-provisioning`'s requirement
    (its spec, the retired key's validity) counts leases "allocated before the key
    was retired"; whole-second times cannot tell before from after within one
    second, so the code takes the reading that never cuts a grant short, and the
    requirement wants a MODIFIED delta ("before, or in the same second as, its
    retirement"). Round-1 triage (33 relay-key): the change now carries it,
    `specs/physical-provisioning/spec.md`'s MODIFIED "Each relay holds its own
    grant-signing key", with a same-second scenario; the code is unchanged.
  - Tests that compared a whole-second source stamp with a sub-second wall read now
    take an injected source: `kit/site`'s
    `test_a_first_activation_records_the_site_s_instant_and_moves_nothing` (a
    shared `source` fixture in a new `tests/integration/conftest.py`);
    `kit/site-client`'s exact-retry test, which patched the module's `time.time`;
    and, a defect left by section 3's fulfillment-claim conversion that failed
    whenever the wall clock's fraction passed half a second, five tests in
    `provisioning/compute/service`'s `test_fulfillment_convergence.py` (the backoff
    deltas are now exact, and `_claim` measures a claim against the source). A
    defect left by section 4, failing when two listings fell in one second: the
    bare-metal storefront's `test_publication_cycle.py` read bindings ordered by a
    listing's `created_at` then its random id; it now breaks the tie by `rowid`.
  - Versions: `provisioning/compute/ansible` 0.8.1, `kit/site-client` 0.13.1 and the
    bare-metal provisioning adapter 0.13.1 take patch bumps (each carried the
    `marketplace-v0.3.0` version; no exact pins on them); `provisioning/compute/client`
    (0.10.0, released) is left for section 10, whose `set_time` takes its minor
    bump. The others were already bumped on `dev` since that release.
  - Evidence: `make check-time-reads` lists none of these packages (61 findings
    left, all in sections 6 and 7's packages but one, below).
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
  - Ties: a list ordered by one of these columns ties at one injected instant, as
    it already tied by the second under SQLite's `CURRENT_TIMESTAMP`; no tie-break
    was added (the lease-end outbox already breaks ties by `event_id`; the other
    tables have no insertion-ordered key, and the service may run on PostgreSQL,
    which has no `rowid`).
  - Evidence, library integration, `kit/site/tests/integration/test_injected_time.py`
    (the ledger over a real SQLite database its migration chain built, the source
    injected): a hold expiring at 1794822300 is kept by the sweep at 1794822299 and
    lapsed at 1794822300, its `released_at` that instant; a lease's start,
    activation, release request and its lease-ended report's effective instant are
    the source's instants; a reservation's `created_at` and a declaration's
    `updated_at` hold the source's instant on insert, and the latter again on
    update. Correction to the plan: the lease-due test is in
    `provisioning/compute/service`'s
    `test_ledger_lease_lifecycle.py::test_a_lease_is_due_only_once_the_process_s_time_reaches_its_end`,
    not `kit/site`, because `list_lease_due` takes its instant from its caller; the
    read is the lease lifecycle's. Library integration too (the lifecycle service
    over the real ledger and fulfillment tables, no application, beside that file's
    other tests): a lease ending at 1794822300 is left leased by a cycle at
    1794822299 and ended by expiry at 1794822300. It shows the due check and the
    expiry classification read the source; the recorded effective instant and
    claimed deadline are the stored end, whatever clock is read. Run against the
    pre-change wheels, before the wheelhouse was rebuilt, it failed as it should:
    the wall clock is past 1794822300, so the first cycle released the lease.
    `run test-before` of `kit/site`'s new test at the section's starting commit
    fails at collection (`injected_time` is absent from that environment), which
    shows less than a behavioural failure.
  - Evidence for the provisioning stores, library integration, each with the source
    injected and held: `provisioning/compute`'s
    `test_job_authority.py::test_a_job_s_creation_and_retry_are_the_process_source_s_instants`
    (a job's `created_at` and the `next_retry_at` a retryable failure schedules are
    the source's instants, and the retry sweep finds it due at that instant and not
    a second before) and two tests in `test_relay_administration.py` (a lease's
    `created_at` and `released_at` and a key's `retired_at`; the reconciliation
    releases a lease only once the source passes its creation plus the grace); and
    `provisioning/compute/service/tests/integration/test_injected_time.py` on the
    service's migrated database (the release-callback outbox's `created_at`,
    attempt and delivery stamps; a replay reservation's dispatch lease, claimed
    again at its expiry and not a second before, and its `completed_at`). Not
    asserted under injected time: the lease-end report outbox's stamps (written as
    the release-callback outbox's are), a principal's `valid_until`, and a key's
    `grant_key_activated_at`.
  - Round-1 triage fix (33 F2), evidence, library integration, each with the source
    injected: `kit/site/tests/integration/test_injected_time.py::test_the_capacity_feed_reports_the_source_s_instants`
    (a hold's `reserved` event and its expiry's `released` event, read back through
    `events_after`, carry the source's two instants) and
    `provisioning/compute/tests/integration/test_host_authority.py::test_a_host_s_view_reports_the_process_source_s_instants`
    (a registered host's view holds the source's instant in both columns; updated a
    minute later, its `updated_at` moves and `created_at` stays) and
    `kit/resource-pools/tests/integration/test_injected_time.py` (the same for a
    pool's `PoolResponse`, through the pool service over a real SQLite database).
    `kit/resource-pools` declares `arkhai-injected-time` (its
    `published-packages.md` row names it) and is relocked; it needs no version
    bump, 0.10.0 having been bumped since `marketplace-v0.3.0`'s 0.9.0. `make -C
    kit/site test` 370 passed; `make -C provisioning/compute test` 536 passed;
    `make -C kit/resource-pools test` 142 passed. With each column's source
    default withdrawn, its test fails on the database's clock. The triage had
    first left the pool columns audit-only on the premise that no response carried
    them; the fresh-context check found `PoolResponse` does, which the triage's
    disposition gave the same fix.
  - Outside the plan, found by the round-1 triage's fresh-context check and fixed on
    the owner's word (fresh-context D2): `kit/pool-overrides`' `pool_overrides`
    stamped `created_at` and `updated_at` with SQLite's `STRFTIME(…,'now')`, and both
    are returned to the operator's client (`PoolOverride`). The store's `replace` now
    writes both from the source on insert and `updated_at` on conflict, in the
    table's millisecond text form (`….000Z` for a whole-second instant); the DDL
    defaults stay. The kit declares `arkhai-injected-time` (its
    `published-packages.md` row names it) and is relocked; 0.3.0 already postdates
    `marketplace-v0.3.0`'s 0.2.1, so no bump. Evidence, library integration,
    `kit/pool-overrides/tests/integration/test_store.py::test_an_override_s_times_are_the_process_source_s_instants`
    (the baseline schema over a real SQLite file, the source injected: an override
    holds the source's instant in both times; replaced a minute later, `updated_at`
    moves and `created_at` stays); `make -C kit/pool-overrides test` 83 passed; with
    the insert's stamps withdrawn the test fails on the database's clock. The
    existing `test_replacement_clears_unset_fields_and_keeps_created_at` now takes
    the source and sets it a second on before replacing, since two whole-second
    stamps in one second could not show `created_at` kept rather than rewritten.
  - Round-1 triage fix verification (33 F1, 33 F2, 33 relay-key, fresh-context
    D2). Library integration suites: `kit/contact-exchange` 147, `kit/site` 370,
    `provisioning/compute` 536, `kit/resource-pools` 142, `kit/pool-overrides` 83,
    each passed; each new test failed with its fix withdrawn (above and 3.3).
    `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`
    on the final tree: `after-functional-change` (`make lock`) and
    `pre-commit-functional` (`make dist-clean`, `make check-packaging`, `make
    test`, every suite) passed; of `pre-commit`, the index, tasks and skills
    checks and `openspec validate --strict` passed, and only the citations check
    failed, on closeout's `openspec/specs/injected-time/architecture.md` (18.9).
    Fresh-context checks of the diff against `b44ba08b4`, run twice: the first
    found the pool columns carried by `PoolResponse` (fixed above),
    `kit/pool-overrides`' reported times (fixed on the owner's word), and three
    nits (a comment's wrap, the contact-exchange note's reason for keeping the DDL
    default, a test helper's place), all fixed; the second, over the pool fixes,
    found no defect, and its nits on a line's wrap and the replacement test's
    `created_at` assertion were fixed. Declined: naming the time source in
    `kit/pool-overrides`' dependency header comment, which already lists only
    some of its dependencies.
- [x] 5.3 Section verification.
  - Unit and library integration: `make test-kits` (`kit/site`, `kit/resource-pools`,
    `kit/site-client`), `make test-compute-provisioning`,
    `make test-compute-provisioning-ansible`, `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the lanes' lease and teardown stages run this code at wall time; no
    new scenario is owed.
  - Evidence: `make -C kit/site test` 369 passed; `kit/site-client` 65;
    `provisioning/compute` 535; `provisioning/compute/client` 86;
    `provisioning/compute/ansible` 187 (4 skipped); `provisioning/compute/service`
    622 unit and 541 integration before its two store tests were added (they pass
    on their own); the VM provisioning adapter 292; the bare-metal one 137.
    `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`
    on the final tree: `after-functional-change` (`make lock`) and
    `pre-commit-functional` (`make check-packaging` and `make test`, every suite —
    `make test-kits`, `make test-provisioning`, `make test-domains` with the three
    storefronts, the API-credits service and the consumers whose locks moved)
    passed; of `pre-commit`, only the citations check failed, on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9). Two earlier runs failed
    on the convergence and publication-cycle tests the notes above describe.
  - Fresh-context check: it found the relay requirement's wording (recorded above
    for triage), stores with read columns no test held under injected time (the
    job, relay, outbox and replay tests above were added), placeholder evidence, an
    inconsistent classification of reported-only columns (now audit-only by one
    rule), two overstated evidence claims (reworded), the lease-ended report's
    instant untested (added), a schema built with `create_all` (the new kit/site
    test now uses the migration chain), and a stale docstring (fixed). Declined:
    moving the lease-due test out of the service suite, whose file already holds
    the lifecycle's library integration tests the same way (section 10.2's
    application test may make it redundant); and editing section 7's plan for
    `domains/vms/negotiation`, left to the handoff below and 7.5.
  - Confirmed: no new end-to-end marker; the lanes run this code at wall time. No
    owed CI evidence.
  - Handoff. A service suite installs its internal dependencies as wheels from
    `.dist`, so after editing a kit or `provisioning/compute` run `make dist` (or
    `make lock`) before that suite, or it tests the old code. `domains/vms/negotiation`'s
    `time.localtime()` (`torch_arkhai_strategy.py`) is in no section's plan; 7.5
    needs it gone.

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
    middleware, as a base dependency: its signing module is imported on every path,
    and the component is standard library only, so an unsigned deployment's set
    stays light (its `pyproject.toml` and module docstring say so). Relocked with
    `make lock` (full). 31 reads converted, all the time of the world, none elapsed
    work (the gate's batching interval was already monotonic): the registry's 26 —
    request verification and the response stamp, the replay lease and its
    completion, rotation-proof verification, an overlap's deadline and the
    retirement stamps, the identity and rotation status comparisons, API keys'
    creation and revocation (aware, the form that store already wrote), a listing's
    `updated_at`, and every model default, now `core_registry.db.models.utcnow`
    (naive UTC, the form the defaults and deadlines take); the
    credits client's and the middleware's request timestamp and response
    freshness reference, two each; the credits service's model default. The
    registry's status comparisons go through `api/utils.py`'s
    `instant_comparable_with`, which keeps the stored deadline's form (naive as
    SQLite returns it, aware if the database returns it so), as the code it
    replaces did. The credits service's hosted site ledger reads the source
    through `kit/site` (section 5).
  - Outside the plan, ties: a list ordered newest or oldest first by a whole-second
    stamp now breaks ties — the registry's listings by `listing_id`, its
    publishers by `publisher_id` and its API keys by `id` (both autoincrement,
    insertion order), the credits service's keys by `key_id`.
  - Versions: the middleware 0.1.2 (a patch: a new runtime dependency, no API
    change; it carried the `marketplace-v0.3.0` version, and nothing pins it
    exactly); `domains/apicredits` (0.9.0, released) is left for section 11, whose
    credits client gains its setting call and takes the minor bump; the registry
    and the credits service were already bumped on `dev` since that release.
  - Evidence: `make check-time-reads` lists none of these packages (30 findings
    left, all section 7's but `domains/vms/negotiation`'s, 5.3's handoff).
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
  - Evidence, application integration. `core/registry/tests/integration/test_injected_time.py`,
    the running registry through `RegistryClient`, the source 120 s behind the wall
    clock (the client still signs on it, 4.2's correction), on the suite's shared
    database fixture, whose schema comes from the ORM metadata, not the migration
    chain (the application supplies every time, so no SQL default is in play): a
    published listing's `created_at` and `updated_at`, its new publisher's and
    identity binding's `created_at`, and the replay reservation's `created_at` and
    `completed_at` hold the injected instant; republished 60 s later, the listing
    keeps its `created_at` and its `updated_at` moves. A rotation through the client
    stores `applied_at` at the source's instant and `retire_at` and the outgoing
    identity's `active_until` 300 s later, and that identity reads as in overlap a
    second before the deadline and retired at it. An API key minted and revoked
    through its store's functions (no client route reaches them here) holds the
    source's instants. Not asserted: the replay lease, which a completed request
    clears. `domains/apicredits/service`'s
    `test_signed_authority.py::test_a_grant_and_its_spending_hold_the_injected_instant`,
    the real application through the seller's `CreditsServiceClient` and the gated
    app's `TokensClient`, at 1794821400: a grant's `granted_at` and its key's
    `created_at`/`updated_at` hold the instant; a consumption 60 s later stamps
    `occurred_at` and moves `updated_at`. Every party in that process reads the
    source, hours from the wall clock, so the test also shows the credits client and
    the middleware sign and verify by the source: on the wall clock every hop would
    fail the 300 s skew.
- [x] 6.3 Section verification.
  - Unit and application integration: `make test-registry`, and `make test-domains`
    (the API-credits service and the Python middleware).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: the API-credits lane's purchase runs this code at wall time; no new
    scenario is owed.
  - Evidence: `make -C core/registry test` 153 unit and 164 integration passed;
    `make -C domains/apicredits test` — the domain 41, the service 81, the
    storefront 276, the buyer 35, the sample app 1, the Python middleware 8, the
    TypeScript port 5 and the Rust port 6. `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` on the final tree:
    `after-functional-change` (`make lock`) and `pre-commit-functional`
    (`make check-packaging` and `make test`, every suite, `make test-registry` and
    `make test-domains` among them) passed; of `pre-commit`, only the citations
    check failed, on closeout's `openspec/specs/injected-time/architecture.md`
    (18.9).
  - Both new tests import `injected_time`, which `run test-before`'s environment
    lacks, so against the section's starting commit they would fail at collection,
    as 5.2's did; not run, since that shows nothing about the change.
  - Fresh-context check: it found registry read columns no test held (the rotation
    and API-key tests above were added), a placeholder for this evidence, a claim
    broader than its assertion and two docstrings naming one stored form where API
    keys keep another (all corrected), and the ORM-built schema (now stated above).
    Declined: bumping `domains/apicredits` now, which section 11's minor bump
    covers, as section 3 left `kit/identity` and `kit/storefront` for their later
    sections.
  - Confirmed: no new end-to-end marker; the API-credits lane runs this code at wall
    time. No owed CI evidence.
  - Handoff for section 7: the registry's signed hops are converted on the server
    side only; until `core/registry-client` reads the source, a registry test through
    the client injects an instant within 300 s of the wall clock, as
    `test_injected_time.py` does. The credits client and the middleware already read
    the source, so the credits service's tests may inject any instant.

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
    `kit/deal-lifecycle-client` (both with `allowed-dependencies`, so each lists it
    and maps `injected_time` under `[tool.arkhai.architecture.import-roots]`, as
    section 3 describes), the VM, bare-metal and API-credits buyers, and, outside the
    plan, `domains/vms/negotiation` (5.3's handoff). Relocked with `make lock`
    (full). 29 reads converted, all the time of the world, none elapsed work: the
    buyer's request timestamps and response freshness references (core's
    `_authenticated_json` and settlement submission, the three clients), the rotation
    intents' expiry (the profile service's and the registry client's), every escrow
    and selection `expiration_unix` the buyers propose, the heartbeat loop's expiry
    check and its sleep toward the escrow's expiration, the run log's stamp (7.3),
    the buyer lifecycle's and evidence pruning's clocks, the watchdog's probe and
    stop stamps (`WaitClock.now`, `watch_deal`'s `clock`), and the RL strategy's
    time-of-day feature (`time.localtime(injected_time.now())`, an instant given, so
    the check admits it). The watchdog's probe interval, probe timeout and stop
    retry were already elapsed work on `monotonic`/`asyncio.wait_for`; its staleness
    judgement compares the lane-time `last_probe_at` with the lifecycle's clock, now
    the source. A response's freshness reference and its capture's `verified_at`
    are now one read, where two wall reads made them.
  - Versions: `kit/deal-lifecycle-client` 0.1.1 (a patch: a new runtime dependency,
    no API change; it carried the `marketplace-v0.3.0` version, and nothing pins it
    exactly). `core/storefront-client` (0.29.0, released, pinned exactly by the
    provisioning service) is left for section 9, whose `set_time` takes its minor
    bump and moves that pin once, as section 3 left `kit/storefront`. The others were
    already bumped on `dev` since that release; `tools/lane-double-controls` is
    unpublished and new since it.
  - Tests that patched a module's `time.time`, which the module no longer imports,
    now install an injected source: `core/buyer`'s `test_identity_http.py` (an
    autouse fixture at its signing instant) and `core/storefront-client`'s
    admin, lifecycle, negotiate and close-listing tests (a `held_time` fixture in
    `tests/conftest.py`). The close-listing retry test moves the source a second
    between the two calls where it fed a sequence of patched reads, and its fake
    storefront now signs at the request's timestamp rather than the wall clock.
  - Evidence: unit and library integration, `kit/deal-lifecycle-buyer`'s
    `test_watchdog.py::test_probes_are_stamped_from_the_process_source_and_scheduled_while_it_is_held`
    (unit: with no clock given and the source held, three probes and the stop carry
    the one injected instant, while the fake monotonic schedule runs all three), and
    two library integration tests in `test_watchdog_journal.py` over the SQLite
    evidence file: `test_the_loop_journals_its_probes_and_stop_at_the_process_source_s_instant`
    (the loop given no clock, the stop's dispatch alone stood in for: the journal,
    reopened, holds the last probe, the stop's decision and both probe observations
    at the injected instant) and
    `test_the_read_judges_a_probe_s_staleness_at_the_process_source_s_instant` (a
    lifecycle given no clock reads a journaled probe as monitored at its freshness
    bound by the source and unmonitored a second past it). `make check-time-reads`
    lists none of these packages; `make -C kit/deal-lifecycle-buyer test` 52 passed,
    `make -C core/buyer test` 172, `make -C domains/vms/buyer test` 334,
    `make -C domains/bare_metal/buyer test` 84, `make -C domains/apicredits/buyer
    test` 35; `make test-core` and `make test-kits` passed within 7.7's `make test`.
    The RL strategy's converted line is exercised by no suite: it runs only once
    `torch` is imported, which no package depends on, and its one test
    (`domains/vms/storefront`'s `test_rl_middleware.py`) skips without it; the
    conversion is read, not run.
- [x] 7.2 The signing clients take every request timestamp and every response
  freshness reference from the process source (`marketplace-identity`'s "Signing and
  verification read the process source").
  - Verify: unit tests in `core/storefront-client`, `core/registry-client` and
    `kit/deal-lifecycle-client` with an injected source at 1794822300: a signed
    request carries 1794822300, and a response stamped 1794822300 verifies.
  - Done: unit, `test_process_time_source.py` in each of the three: with the source
    held at 1794822300 (2026-11-16 09:45 UTC, which the wall clock had left hours
    behind when they ran, and leaves further behind since), a request built with no
    timestamp carries 1794822300 — in its envelope and header for the storefront and
    registry clients, in its header for the lifecycle client — and a response
    stamped 1794822300 verifies with no reference given, which a wall-clock
    reference would refuse for skew; and the same response is refused
    `timestamp_skew` once the source is set 301 s past it, so the reference follows
    the source as it moves. The storefront and registry clients' tests call their
    `auth` module's request builder and response verifier directly; the lifecycle
    client's runs `end_delivery` over an `httpx.MockTransport`.
    `make -C core/storefront-client test` 71 passed, `make -C core/registry-client
    test` 28, `make -C kit/deal-lifecycle-client test` 4. Against the round's base the
    storefront client's test fails at collection (`ModuleNotFoundError:
    injected_time`, `run test-before`), which shows less than a behavioural failure;
    the other two import the same module.
- [x] 7.3 Supply the buyer's read database or file times (its run log and buyer state)
  from the process source (D13).
  - Verify: a buyer test under an injected source finds the injected instant in the
    run log's read fields.
  - Done: the run log's `ts`, which `list_runs` reports as a run's `started_at` and
    `last_event_ts`, is the source's instant as an aware UTC ISO string, now with no
    fraction (`market logs` already cut one off). `list_runs` orders runs by their
    files' modification time, the order they were last written in, which a source
    moving only forward cannot contradict and which carries no instant out; it is
    left as it is (its docstring says why). The buyer's state is otherwise the
    watchdog and end journals and the evidence store, whose instants their callers
    pass from the clocks 7.1 converted; no buyer store has an SQL time default. Read:
    the watchdog journal's probe instants (the staleness judgement compares them),
    asserted under injected time by 7.1's two integration tests. Not asserted under
    injected time: the end journal's `observed_at` (written from the lifecycle's
    clock and reported) and the evidence store's `recorded_at` (retention compares it
    with the prune command's clock), each now the source by default.
  - Evidence: library integration, `core/buyer/tests/integration/test_run_log_times.py`
    (a run log over real files under a temporary state directory, the source at
    1794821400 then set 60 s on: each event's `ts`, and the summary's `started_at`
    and `last_event_ts`, hold those instants), in `make -C core/buyer test` (172).
  - Outside the plan: `core/buyer`'s `make test` ran `tests/unit` alone, so its
    existing `tests/integration` suite (one test, passing) never ran; the Makefile and
    `pytest`'s `testpaths` now name both directories.
- [x] 7.4 The doubles' direct reads go through the component's wall source:
  `lane_double_controls.clock`'s `wall_clock` and any direct read in the two
  doubles; their offset clocks stay until section 13.
  - Verify: `make test-lane-double-controls`, `make test-payments-lane-double` and
    `make test-mediation-lane-double` pass unchanged.
  - Done: `wall_clock` reads a module-level `injected_time.WallTime`, explicitly the
    wall source rather than the installed one, so the doubles stay on wall time until
    section 13 gives them injected time; `tools/lane-double-controls` declares
    `arkhai-injected-time` (it has no `published-packages.md` row: it is not
    published) and the two doubles are relocked with it. The doubles held no direct
    read of their own: both take `wall_clock` as their clocks' default. Their tests
    are unchanged: `make test-lane-double-controls` 120 passed (mypy strict clean),
    `make test-payments-lane-double` 84, `make test-mediation-lane-double` 73, run
    after `make dist` rebuilt the controls' wheel.
- [x] 7.5 Make sure nothing is left: run `make check-time-reads` on the tree.
  - Verify: it reports no finding.
  - Done: `make check-time-reads` prints "OK: no direct wall-clock read in production
    source or the lane doubles."
- [x] 7.6 Switch the check on: `make check-packaging` runs `check-time-reads`, and
  `docs/guidance/repository/packaging-checks.md`'s "Checks" table gains its row (D20).
  - Verify: `make check-packaging` passes, and fails on a planted `time.time()` in a
    kit.
  - Done: `check-time-reads` is the last check `check-packaging` runs, and its
    Makefile comment says so; the table's row names what it refuses, its scope and
    what passes, and cites `implementation.md`'s section. No CI workflow runs
    `check-packaging`, so the check runs where it already runs: the pre-commit hook's
    functional checks and closeout's packaging part.
  - Evidence: with `_PLANTED_WALL_READ = time.time()` added to
    `kit/deal-lifecycle-buyer`'s `commands.py`, `make check-packaging` failed (exit 2)
    at `check-time-reads`, naming `commands.py:28` and the project, after every other
    check passed; the plant was then removed. The passing run is 7.7's pre-commit.
- [x] 7.7 Section verification.
  - Unit and integration: `make test`.
  - `make check-packaging`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: the three lanes, every module at wall time, as regression evidence
    for round one; no new scenario is owed.
  - Evidence: `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` on the final tree:
    `after-functional-change` (`make lock`) and `pre-commit-functional` (`make
    dist-clean`, `make check-packaging` — its `check-time-reads` printing "OK: no
    direct wall-clock read" — and `make test`, every suite, `make test-core` and
    `make test-kits` among them) passed; of `pre-commit`, only the citations check
    failed, on closeout's `openspec/specs/injected-time/architecture.md` (18.9).
  - Confirmed: no end-to-end marker is new or changed; every lane module runs the
    buyer, the signing clients and the doubles at wall time, so validation's lane run
    is the round's regression evidence. No owed CI evidence: no workflow runs
    `check-packaging`, and the suites run in the workflows' existing jobs.
  - Fresh-context check: it found test comments calling 1794822300 "hours from the
    wall clock", true only of the day they ran (reworded: an instant the wall clock
    has left behind by far more than the skew), an unwrapped watchdog docstring that
    called `clock` the source where only its default is (fixed), no test of the real
    watchdog journal storing a source-stamped probe (the loop test above was added),
    and four evidence claims broader than their tests — the lifecycle client's
    envelope, the RL strategy's line as run, the skew test as telling the source from
    the wall clock, and 7.1 and 7.6 resting on this run before it was recorded (all
    reworded or recorded here). Declined: moving
    `kit/deal-lifecycle-client`'s new test into a `unit/` directory, since its
    existing tests sit in a flat `tests/` and reorganizing them is outside this
    change (`test-placement.md`'s split; a row for the change index if the owner
    wants it); and editing `openspec/specs/buyer-orchestration/architecture.md`,
    whose watchdog paragraphs (its probe stamps and staleness on "the wall clock",
    near lines 220–237) closeout's promotion must restate in the process source's
    terms — a permanent companion this change updates at closeout, not mid-round.
  - Handoff for section 8 and later. Round one's conversion is complete and the
    check is on: a new direct wall read anywhere in scope fails `make
    check-packaging`, and with it the pre-commit hook. Every signing client now reads
    the process source, so a test through a client may inject any instant, as long
    as the service it calls reads the same process's source (4.2's 120 s-behind
    fixtures may now move to fixed instants, but need not). A test that patched a
    module's `time.time` to fix a timestamp now installs an `InjectedTime` and
    restores the previous source; `core/storefront-client`'s `held_time` fixture
    holds 1000. The doubles' `wall_clock` reads `WallTime()` explicitly, so
    installing an injected source in a double's process does not move it until
    section 13 replaces the offset clock. `core/storefront-client` owes its minor
    bump to section 9. Closeout's 18.9 must also cover `buyer-orchestration`'s
    architecture companion (above). This session grew large; section 8 is better
    started fresh.

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
  - Done: `verify_request(..., time_setting_operation=None)`. The skew check is
    skipped only when the caller names an operation and it equals
    `expected_operation`, the route's own; the context check before it already
    holds the signed operation to the route's, so a request signed for another
    operation never reaches it. Principal, context, body hash, proof and replay
    classification are unchanged. Unit, `kit/identity/tests/unit/test_envelopes.py`:
    `test_the_time_setting_operation_alone_is_verified_without_freshness` (±900 s
    verifies when named, `TIMESTAMP_SKEW` when not, and naming another operation
    exempts nothing) and
    `test_the_time_setting_operation_is_otherwise_verified_as_every_request` (a
    changed body, a wrong principal, a forged timestamp, an exact retry and a
    changed reuse, each on the named operation 900 s off). `make -C kit/identity
    test` 168 passed. `run test-before` at `9491d9719` fails at collection
    (`rfc8785` absent from its project-less environment), which shows nothing; at
    the base the keyword does not exist, so each test would fail with a
    `TypeError`.
  - Versions: `kit/identity` 0.5.0 (new API; 3.1's note owed it here), with its 26
    exact pins moved and `kit/site`'s lower bound raised to 0.5.0, since its
    middleware passes the keyword. Four packages that still carried their
    `marketplace-v0.3.0` versions change content with the moved pins, and each was
    owed its minor bump by a later section of this round, so each takes it here
    instead, once: `core/storefront-client` 0.30.0 (its exact pin in the
    provisioning service moved), `kit/storefront` 0.11.0 (its exact pins in the
    three storefronts moved), `provisioning/compute/client` 0.11.0 and
    `domains/apicredits` 0.10.0. Sections 9–11 add their APIs within those
    versions. Relocked with `make lock` (full); `make check-version-bumps` passes.
    Outside the plan: the identity wheel's version is copied by hand into the root
    `Makefile` (`IDENTITY_WHEEL`, which `dist-identity` checks) and into
    `scripts/package-review-wheelhouse.sh` and its test; each now names 0.5.0,
    which the first pre-commit run found (`dist-identity` refused the missing
    0.4.0 wheel). `core/storefront-client/README.md`'s two pins, one stale before
    this section, name 0.30.0 and 0.5.0.
- [x] 8.2 Each signed administrator surface above applies the exemption to its
  time-setting operation alone — the storefronts' `admin_time`, provisioning's and the
  credits service's setting operation — and to no other route (D14).
  - Verify: unit tests per middleware: the setting operation is admitted skewed; the
    pause operation skewed by the same amount is refused.
  - Done: `core_storefront.auth` names the storefronts' setting operation,
    `ADMIN_TIME_OPERATION = "admin_time"` with resource `ADMIN_TIME_RESOURCE =
    "time"`, passes `time_setting_operation` through `authenticate_request`, and
    offers `admin_time_setting_operation()`: `admin_time` while the installed source
    is settable (`TimeRouteService(installed()).settable`, the same test that mounts
    the route, D12), else `None`. The VM administrator middleware binds `POST
    /api/v1/admin/time` to that contract and passes the helper's answer; the
    bare-metal `_admin` and the API-credits `authenticate_admin` pass it on every
    administrator request, which exempts only a request whose route is
    `admin_time`. `ProvisioningAuthMiddleware` and `kit/site`'s `SiteAuthMiddleware`
    take `time_setting_operation` in their constructor, `None` by default; sections
    10 and 11 pass their operation from their composition under injected time. The
    two forms differ because the storefronts authenticate in module functions with
    no object their composition builds, so they read the installed source per
    request, while the provisioning and site middlewares are constructed by a
    composition that knows its source.
  - Evidence. Unit: `core/storefront`'s `test_auth.py` (the helper under wall and
    injected time; `authenticate_request` admits a named operation 900 s off and
    refuses an unnamed one). The provisioning middleware, in its existing suite
    under `tests/unit/middleware/test_auth.py`, which runs the real middleware over
    an in-memory SQLite replay store (so narrower than application integration and
    wider than a unit; the file's placement predates this section): over a route
    table with a stand-in `provisioning_system_time` contract, named, the setting
    is admitted at ±900 s and the lease-watchdog pause refused for skew; unnamed,
    the setting is refused. Library integration, `kit/site`'s
    `test_site_auth_middleware.py` (the same pair over the real middleware with a
    stand-in `system_time` contract, the setting's response signed). The
    storefronts', each an in-process app over the real administrator
    authentication with a stand-in time route counting its calls: VM
    `tests/integration/test_admin_api.py` (the admin router and middleware), bare
    metal `tests/test_http_system.py` (the composed app, the stand-in calling the
    module's `_admin`, which no public function wraps), API credits
    `tests/integration/test_trading_pause_api.py` (the pause and system routers
    with the response middleware). Their requests are raw, built by the canonical
    client's `build_authenticated_request` at a chosen instant, since the client
    signs at the process's own and cannot send a skewed one, and as a
    rejection-path test's, only statuses are asserted: under injected time
    `admin_time` is admitted at ±900 s with a signed response, the pause refused
    and trading left open; under wall time `admin_time` is refused. Section 9's
    application-integration tests set time through the client on the real route.
    Suites: `make -C kit/site test` 373, `make -C core/storefront test` 232
    (before its two unit tests; 9 in `test_auth.py` after), provisioning
    middleware 56, `make -C domains/vms/storefront test` 609 integration and its
    unit suite, `make -C domains/bare_metal/storefront test` 650, `make -C
    domains/apicredits/storefront test` 279.
  - Correction (section 9): the bare-metal test runs the composed application,
    which under injected time now mounts the real time route ahead of the
    stand-in, so its injected case sets time through the real route (900 s ahead
    answers 200 and moves the source; 900 s behind answers 409, not the skew's
    403, and leaves the source, so it passed authentication and was refused as an
    earlier instant), the pause is sent before the setting, and the stand-in is
    added only under wall time, where no route is mounted. The suite counts above
    are section 8's; section 9's are in its notes.
  - Correction (section 10): `ProvisioningAuthMiddleware` and `SiteAuthMiddleware`
    now exempt the operation their constructor names only while the installed
    source is settable, the storefronts' rule, so a composition names its
    operation in either mode and a wall-time process exempts nothing (the
    provisioning service's app and route table are built once at import, and
    its tests share them). Their tests install an injected source for the
    exempt case and add one with the operation named under wall time, refused
    for skew; the provisioning test's stand-in moved to its own path and
    operation, since the family's contracts now declare `/api/v1/system/time`.
    Section 10's notes hold the suites' counts after it.
- [x] 8.3 Section verification.
  - Unit: `make test-kits` (`kit/identity`, `kit/site`), `make test-core`, the
    storefronts' and `make test-provisioning`'s middleware tests.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: exercised by section 15's fixture once the lanes run injected
    (section 16).
  - Evidence: the suites in 8.1 and 8.2. `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` on the final tree: `after-functional-change`
    (`make lock`) and `pre-commit-functional` (`make dist-clean`, `make
    check-packaging`, `make test`, every suite, `make test-kits`, `make test-core`,
    `make test-provisioning`, `make test-domains` and `make test-release-tooling`
    among them) passed; of `pre-commit`, only the citations check failed, on
    closeout's `openspec/specs/injected-time/architecture.md` (18.9). The first run
    failed at `dist-identity` (the hand-kept version, 8.1's note).
  - Confirmed: no end-to-end marker exercises the exemption yet; the lanes run on
    wall time until section 16, and section 15's fixture is the first caller to
    set time skewed. No owed CI evidence: the suites run in the workflows' existing
    jobs.
  - Fresh-context check: it found the storefront tests' raw requests unexplained
    and asserting a refusal's body (now stated as rejection-path requests, the
    client unable to sign at another instant, asserting statuses only), the
    provisioning tests named unit though they run the middleware over SQLite
    (the evidence note now says what they run), comments in `core_storefront.auth`
    describing a route and a client method section 9 adds (reworded to what this
    section holds), the bare-metal test not checking trading stayed open (added),
    `core/storefront-client/README.md`'s stale pins (fixed), and the storefronts'
    and services' different exemption forms unexplained (the reason is in 8.2's
    note). Declined: the operation name defined in `core_storefront.auth` where the
    client cannot import it, as `admin_pause` and the other administrator
    operations are spelled in each storefront and the client today; moving the
    provisioning middleware tests out of `tests/unit/`, whose file predates the
    section; and the bare-metal stand-in route calling the module's private
    `_admin`, the only path to its administrator authentication, which section 9's
    real route makes testable through the client.
  - Handoff for sections 9–11. The exemption is wired: a storefront's admin
    authentication exempts `admin_time` whenever the installed source is an
    `InjectedTime`, so section 9 needs only to bind `POST /api/v1/admin/time` to
    the `ADMIN_TIME_OPERATION`/`ADMIN_TIME_RESOURCE` contract (the VM middleware
    already maps the path) and have the canonical client sign the same pair.
    Sections 10 and 11 pass their operation's name as `time_setting_operation` to
    `ProvisioningAuthMiddleware` and `SiteAuthMiddleware` when their composition
    installs an injected source. The four packages bumped here (8.1) need no
    further bump for those sections' APIs. Any further change to `kit/identity`'s
    version must move the `Makefile`'s `IDENTITY_WHEEL` and the review-wheelhouse
    script with it.

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
    `TIME_SOURCE_SETTING = "[Time] source"`, `install_time_source(value)` (the
    component's `source_for` naming that setting, `"wall"` when unset, then
    `install`), and `TimeSourceSetting`, a pydantic `Literal["wall", "injected"]`
    whose before-validator refuses any other value with the component's message,
    naming the setting and the value; the kit now declares `pydantic>=2.7`, which
    it had only transitively. The kit's `configured_time_source(settings)` reads
    the raw `[Time] source` from a loader's merged settings, keys in any case, and
    each storefront's `configured_time_source()` passes it its own (the VM's and
    the API credits' Dynaconf `settings`, the bare-metal `settings_source()`).
    Each installs it at
    module level in its `server.py`, immediately before the module-level `app` is
    built, so the source is in place before anything reads the time and before the
    application decides whether to mount the route. A misspelled value raises
    `injected_time.InvalidTimeSource` at import, so the process does not start.
    The bare-metal typed settings gain `time: TimeSettings` and the VM a
    `TimeConfigDeclaration` for its values schema, each typed with
    `TimeSourceSetting`; the API-credit storefront has no chart and no typed
    model.
  - Evidence. Unit: `kit/storefront`'s `tests/unit/test_time_controls.py`
    (installation: unset → wall, `"injected"` → an injected source installed,
    `"injectd"` refused naming both and leaving the installed source; the typed
    setting; the raw read in any case), VM `tests/unit/test_config_loader.py`
    (the raw read; the declaration), bare metal `tests/test_config_loader.py`
    (unset → wall, `[Time] SOURCE = "injected"` read through the files,
    `"injectd"` refused by the typed load naming both), API credits
    `tests/unit/test_time_settings.py`. The refused start: each storefront's
    `test_time_controls.py` starts its composition root in a process of its own
    (`python -c "import <storefront>.server"`, the test's interpreter) with
    `[Time] source = "injectd"` through the loader's override layer
    (`STOREFRONT_TIME__SOURCE`, `APICREDITS_STOREFRONT_TIME__SOURCE`) and finds it
    exits non-zero with `InvalidTimeSource` naming the setting and the value. That
    is a process starting the module as `serve` imports it, before any
    application exists, so it is not application integration, which the plan
    named; no application can be driven, since none is built.
- [x] 9.2 `kit/storefront` gains the framework-free time route service over the
  component's (1.5); each storefront binds it at `POST /api/v1/admin/time` behind its
  administrator authentication, mounted only under injected time (D5, D12).
  - Verify: application-integration tests per storefront through the canonical
    client: set to 1794822300 answers source `injected` and now 1794822300 and the
    storefront's signed responses then carry 1794822300; an earlier instant answers
    `409 time_moves_forward`; `{"now": true}` answers `422 invalid_time`; a wall-time
    storefront serves no such route.
  - Done: `StorefrontTimeRouteService(source=None)` over the component's
    `TimeRouteService`, the installed source by default: `mounted`, `status()` and
    `set_time(body)`, which raises the component's `TimeRouteError`;
    `time_refusal_body(error)` is the refusal's body, `{"code", "detail"}`. Each
    storefront binds it on a router of its own, mounted by its app builder only
    when `StorefrontTimeRouteService().mounted` (the installed source is
    injected): VM `admin_controller.time_router` behind the administrator
    middleware (section 8 mapped the path), bare metal `api.time_router` through
    `_admin`, API credits `controllers/time_controller.py` through
    `authenticate_admin`. The handler passes the raw body to the route service, so
    the value rule is the component's alone, and each storefront's response
    middleware signs the answer after the set, at the new instant.
  - Evidence, application integration, each storefront's `test_time_controls.py`
    over its composed application and lifespan (VM and API credits from
    configuration as their startup tests compose them, bare metal over a runtime
    the test builds), through `StorefrontClient`: with the source injected at
    1794822300 before the app is built, `set_time(1794823200)` answers
    `injected`/1794823200 and the response, read through a recording transport,
    is signed at 1794823200; `set_time(1794822300)` raises 409; `set_time(True)`
    (the client sends the value as given) raises 422, and the instant stays
    1794823200; with a wall source the same call raises 404. On bare metal and
    API credits, whose time routes authenticate in the handler, a client signing
    as a principal the storefront does not trust is refused 403 and the time is
    unchanged (the VM's route sits behind the administrator middleware, whose
    trust section 8's and the existing administrator tests hold). The plan's instant
    is used: the client and the storefront read one process source (section 7).
    Correction to the plan's example: the setting moves from 1794822300 to
    1794823200, since a set to the instant already held would not show the move.
- [x] 9.3 The signed system status, `GET /api/v1/system/status`, carries the time
  section in both modes; the canonical client's `get_system_status` reads it and gains
  `set_time` (D5).
  - Verify: application-integration tests for both modes through the client, for the
    VM and the bare-metal storefront at the same path and shape (`market-composition`'s
    "Both compute storefronts bind one route").
  - Done: `core_storefront`'s `HealthResponse` and the bare-metal
    `BareMetalHealthResponse` gain `time: dict | None`, set on system status from
    `StorefrontTimeRouteService().status()` by each storefront's status route
    (absent from the liveness probes). The client's `HealthResponse` reads `time`;
    `StorefrontClient.set_time(now)` and `SyncStorefrontClient.set_time(now)` post
    `{"now": now}` signed as `admin_time`/`time` and return `TimeSettingResponse`
    (`source`, `now`); the client names the pair itself, as it does every
    administrator operation, since it cannot import the storefronts' core.
  - Evidence: unit, `core/storefront-client`'s `test_health_response.py` (the
    section in both modes) and `test_time_setting.py` (over an
    `httpx.MockTransport`: the request is signed as `admin_time`/`time` at the
    process's instant and verifies; 409 and 422 raise with their status); the VM
    storefront's existing `tests/unit/test_storefront_client_parity.py` holds the
    sync and async `set_time` to one signature. Application integration, the
    three storefronts' tests above: status reads `{"source": "injected", "now":
    1794822300}`, then 1794823200 after the set, and `{"source": "wall"}` under
    wall time; the VM and bare-metal tests drive the same client methods at the
    same path and read the same shapes.
- [x] 9.4 Startup announcement and warning: an injected storefront logs its source at
  startup; one with an Arkhai payments section whose `livemode` is `true` logs a
  warning naming both settings, and starts (D2).
  - Verify: application-integration tests capture both log lines.
  - Done: `announce_time_source(source, payments_livemode=..., logger=...)` logs
    nothing for wall time; for injected time an INFO line naming `[Time] source`
    and the held instant, and, with live payments, a WARNING naming `[Time]
    source` and `[Settlement.arkhai_payments] livemode`. Each storefront calls it
    in its lifespan's start (VM `_start_vm_services`, bare metal `_start_runtime`,
    API credits `_start_api_credit_services`) with its payments mode, read by one
    function the payments kit now offers beside the section it owns,
    `market_arkhai_payments.payments_livemode(settlement)` (the raw `[Settlement]`
    table, keys in any case, `True` only for a payments section stating
    `livemode = true`): the VM and the API credits pass their settlement table;
    bare metal's configuration builder stores it in a new runtime field,
    `payments_livemode`. `kit/arkhai-payments` 0.8.0 already postdates the
    release; the API-credit storefront's lower bound on it rises to 0.8.0, and the
    three storefronts' on the client to 0.30.0, whose `set_time` their tests use.
  - Evidence: unit, the kit's tests (wall silent; injected INFO; WARNING beside
    live payments) and `kit/arkhai-payments`' `test_settlement_config.py` (the
    read: absent, false, a string, a non-table and a live section in other
    case). Application integration, each storefront's `test_time_controls.py`:
    started injected with live payments, `caplog` holds both lines and the
    storefront serves its status. VM and API credits state a disabled
    `arkhai_payments` section with `livemode = true` in their configuration; bare
    metal builds its runtime with `payments_livemode=True`, and its builder's
    read is shown instead by `test_config_loader.py`, where the files' settlement
    table gives `payments_livemode` the mode the composed payments stage holds;
    the builder's call itself is not run by a test.
- [x] 9.5 Regenerate the storefronts' values schemas so the charts admit `[Time]`.
  - Verify: `make -C helm test-render` passes.
  - Done: `make helm-values-schema` wrote `helm/values.schema.json`,
    `helm/charts/storefront/values.schema.json` and
    `helm/charts/bare-metal-storefront/values.schema.json`, each admitting
    `time.source` as `"wall"` or `"injected"` (any case, `null` accepted as
    everywhere). The charts' packaged files changed, so the umbrella and both
    storefront charts move from 0.4.1 (bumped on `dev` since `marketplace-v0.3.0`'s
    0.4.0) to 0.5.0, a minor step for an admitted key, and the umbrella's two
    dependency pins with them. Each storefront chart's render test gains
    `test_the_time_source_is_admitted_as_wall_or_injected_and_refused_otherwise`
    (static configuration: both sources render, `"injectd"` is refused naming
    `config.Time.source`, through the umbrella for the VM agent). `make -C helm
    test-render` passes, its loader checks among it; the storefronts' drift tests
    (`test_values_schema.py`) pass in their suites.
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
  - Evidence: `make -C kit/storefront test` 141, `make -C kit/arkhai-payments
    test` 354, `make -C core/storefront-client test` passed, `make -C
    domains/vms/storefront test` 1196 unit (1 skipped) and 613 integration, `make
    -C domains/bare_metal/storefront test` 658, `make -C
    domains/apicredits/storefront test` 285, `make -C helm test-render` passed.
    `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`,
    before the fresh-context fixes: `after-functional-change` and
    `pre-commit-functional` (every suite) passed, and of `pre-commit` only the
    citations check failed, on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9). On the tree with the
    fresh-context fixes: `after-functional-change` (`make lock`) and
    `pre-commit-functional` (`make dist-clean`, `make check-packaging`, `make
    test`, every suite) passed; of `pre-commit`, the citations check failed as
    before, and the local-imports check on the payments kit test's import, which
    now sits at module level: `make check-local-imports CHANGE_BASE=dev` passes,
    the file's 37 tests pass, and `make check-repository` fails only on the
    citation.
  - Confirmed: no end-to-end marker exercises the route yet (sections 15 and 16).
    The owed job is right: `test-deployment-packaging` runs `make -C helm
    test-render`, the regenerated schemas and the new render tests among it.
  - Fresh-context check: it found the bare-metal and API-credit time routes'
    authentication untested (a test of an untrusted principal added to each), the
    9.4 claim that every storefront started from a live payments section (bare
    metal sets its runtime field; reworded, and the builder's read shown through
    the configuration test), section 8's correction placed among its counts and
    naming a code its test does not check (reworded), a sync/async parity test
    duplicating the VM storefront's (removed), the kit test repeating the
    component's value and forward rules (trimmed to what the kit adds), the
    `livemode` read and the `[Time] source` read written three ways (one each now:
    `market_arkhai_payments.payments_livemode`, beside the section it reads, and
    the kit's `configured_time_source`), the storefronts' client lower bounds
    below the version their tests use (raised to 0.30.0), no render test of the
    schema's new entry (added to both charts), and the misspelled-source test
    called application integration (reworded). Declined: the route's operation,
    resource and path spelled both in `core_storefront.auth` and the client, as
    section 8 declined for `admin_time` (the client cannot depend on the
    storefronts' core, and moving the pair into the client would make
    `core_storefront` depend on the client).
  - Handoff for sections 10–11. The storefronts' pattern carries over: install
    the configured source at the composition root before the app is built, mount
    the setting route only when `TimeRouteService(installed()).settable`, put
    the component's `status()` on the status route, sign the answer after the
    set, and announce in startup with the payments mode. A composed app reads the
    source at build time, so a test installs its source before building the app
    and restores it after. A storefront test that also wants its own stand-in at
    `/api/v1/admin/time` under injected time is shadowed by the real route.

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
  - Done: `Settings.configured_time_source` reads `time.source` as stated (keys in
    any case; a `time` that is not a table states none); `main.py` installs
    `source_for(..., setting="time.source")` at module level, before the app is
    built, so a misspelled value refuses the import naming the setting and the
    value, and mounts `make_time_router()` (`POST /api/v1/system/time`, in
    `controllers/system_controller.py`) only when that source is injected; the
    lifespan calls `announce_time_source`, an INFO line under injected time (the
    service has no payments section, so no warning). The family contracts declare
    the route as `PROVISIONING_TIME_OPERATION` (`provisioning_system_time`),
    administrator only, with `TimeSettingResponse` and `SystemStatusResponse.time`;
    the status service fills the section from the component's route service; the
    middleware is given the operation and exempts it only while the source is
    injected (8.2's correction). Under wall time the contract stays in the table,
    so a signed request is authenticated and then finds no route, a signed 404, as
    a wall-time VM storefront answers its unmounted route. The route also refuses
    404 should it be mounted over a source that cannot be set, which only this
    suite does (below).
  - Evidence. Unit, `tests/unit/test_time_source.py`: `configured_time_source`
    unset, a scalar `time`, keys in any case, a misspelled value returned as
    stated; `announce_time_source` logs once for an injected source, naming
    `time.source` and the instant, and nothing for wall. `tests/unit/test_route_binding.py`
    counts the time router as mounted, since this wall-time process does not
    mount it. Application integration, `tests/integration/test_system_time.py`
    through `ComputeProvisioningClient` as the administrator, the source injected
    at 1794822240 and the time router mounted on the suite's shared app as the
    service mounts it (`mount_unless_served`, as the suite mounts the mock
    profile's routers): status reads 1794822240, `set_time(T)` answers
    `injected`/T and status follows, `set_time(T - 60)` raises 409 with the
    refusal's "moves only forward" detail, `set_time(True)` raises 422, status
    still T; under wall time, installed explicitly, status reads `{"source":
    "wall"}` and `set_time` raises 404 (from the guard, the router being mounted
    on the shared app by then; the production 404 is routing's). The misspelled
    source: the composition root started in a process of its own (`python -c
    "import compute_provisioning_service.main"`, `PROVISIONING_TIME__SOURCE=injectd`)
    exits with the component's exact refusal, `time.source is "wall" or
    "injected", not 'injectd'`, a process start, not application integration.
    Not asserted: the answer's signed timestamp, which the client verifies within
    its skew of the same source (the storefronts' tests read it exactly, through
    the same signing at response time), and the refusal bodies' `code`, which
    the client does not surface.
  - Amendment (section 11): `test_the_composition_mounts_the_time_route_only_under_injected_time`
    starts the composition root in a process of its own with
    `PROVISIONING_TIME__SOURCE` `injected` and `wall` and reads its OpenAPI
    document: the route is served under injected time and not under wall time.
    `make -C provisioning/compute/service test-integration` 550 passed.
- [x] 10.2 The lease watchdog and the site follow injected time: a lease truncated to
  1794822300, the watchdog paused, the service set to 1794822300 and one watchdog cycle
  stepped, ends by expiry with effective instant and claimed deadline 1794822300; a
  termination under injected time states the injected effective instant
  (`physical-provisioning`'s scenarios).
  - Verify: application-integration tests through the provisioning client, mock
    executor.
  - Done, application integration, `test_system_time.py`: a lease committed
    through the ledger, as the lease suites' `_committed` does (no route commits a
    lease), then truncated to 1794822300 through the site client's
    `truncate_lease`, with the source at 1794822240 and the watchdog paused
    through the client; a `check_leases` step releases nothing;
    `set_time(1794822300)`; the next step releases it, and the seller-signed lease
    read returns one signed lease-ended report, verified against the service's
    principal, with cause `expiry` and effective instant and claimed deadline
    1794822300. A lease terminated by the seller after `set_time(1794822300)`
    reports cause `termination` at 1794822300. `test_ledger_lease_lifecycle.py`'s
    library test (5.2) stays: it holds the lifecycle's classification without the
    application.
- [x] 10.3 The client gains `set_time` and the status time section.
  - Verify: `make test-compute-provisioning-client`.
  - Done: `ComputeProvisioningClient.set_time(now)` and the sync form post
    `{"now": now}` signed as the contract's operation and parse
    `TimeSettingResponse`; `get_system_status` parses the section through the
    contracts' model. The client's contracts bound rises to 0.14.0, the unreleased
    version that adds them. Unit, `tests/unit/test_client.py::test_the_time_setting_answers_its_model`
    (both forms, the request verified against the family route table's contract);
    `make -C provisioning/compute/client test` 88 passed.
- [x] 10.4 Section verification.
  - Application integration: `make test-provisioning`,
    `make test-compute-provisioning-client`.
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets provisioning once section 16 puts the lanes
    on injected time; serve-running's funds-exhausted rows exercise 10.2's path.
  - Evidence: `make -C provisioning/compute/service test` 634 unit and 548
    integration, `make -C provisioning/compute/client test` 88, `make -C
    provisioning/compute/contracts test` 157, `make -C kit/site test` 374, `make -C
    kit/storefront test` 141, each passed after the fresh-context fixes.
    `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`
    before those fixes: `after-functional-change` and `pre-commit-functional`
    (every suite) passed, and of `pre-commit` only the citations check failed, on
    closeout's `openspec/specs/injected-time/architecture.md` (18.9). On the
    final tree, the same: `after-functional-change` (`make lock`) and
    `pre-commit-functional` (`make dist-clean`, `make check-packaging`, `make
    test`, every suite) passed, and of `pre-commit` only the citations check
    failed, on that document.
  - Confirmed: no end-to-end marker exercises the route yet (sections 15 and 16).
    No owed CI evidence: the suites run in the workflows' existing jobs.
  - Fresh-context check: it found the route bound in both modes against the
    delta's "mounted only on an instance configured for injected time" (it is now
    mounted only under injected time, the tests mounting it as the service
    does), comments calling the wall-time 404 an unrouted path's (reworded),
    `configured_time_source` reading a scalar `time` as the source, here and in
    the kit (it now states none) and untested (unit tests added), the
    announcement test under `integration/` (moved to `unit/`), section 8's
    counts reading as this section's (moved back into 8.2's evidence), the
    refusal codes unasserted (the 409's detail is asserted; the client surfaces
    no code, said above) and the misspelled-source test matching any line naming
    the setting (it now matches the component's whole refusal), the lease end
    written straight to the ledger where the site route can truncate it (the
    test truncates through the site client), the contracts module's `__all__` and
    docstring missing the time model (added), and the wall-time tests relying on
    the default source (they install wall time). Declined: moving the
    provisioning middleware tests out of `tests/unit/`, whose file predates the
    change, as section 8 declined; writing the "exempt only while injected" rule
    once rather than in `core_storefront.auth`, the provisioning middleware and
    the site middleware, since each is one expression over the component's own
    `TimeRouteService(...).settable`, in packages with no shared dependency but
    the component; and importing `_committed` and the `seller` fixture from
    `test_leases_api`, as `test_lease_end_reports` does.
  - Handoff for section 11. The provisioning pattern fits a service whose app
    is built once at import: install at module level, mount the time router
    only when injected, keep the contract in the authentication table, guard the
    handler, and let tests mount the router on the shared app. The credits
    service hosts the site, so `SiteAuthMiddleware`'s `time_setting_operation`
    is its seam; the registry's bearer route needs no exemption (D14).

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
  - Done: `Settings.time_source` (`TIME_SOURCE`, unset by default); `main.py`
    installs `source_for(..., setting="TIME_SOURCE")` at module level before the
    app is built, mounts `admin_routes.make_time_router()` (`POST /admin/time`)
    only when that source is injected, and announces an injected source in its
    lifespan. `admin_routes.status_router` serves `GET /admin/status`,
    `{"time": {...}}`, in either mode; both routes sit behind
    `require_admin_api_key` and answer unsigned, as the other `/admin` routes do,
    the refusals `{"code", "detail"}`; the time route guards 404 should it be
    mounted over a source that cannot be set. The registry chart is untouched: a
    wall-time default needs no value, and the lanes that set `TIME_SOURCE` are
    Compose stacks (section 16).
  - Evidence. Unit, `core/registry/tests/unit/test_time_source.py` (the setting
    unset and stated; the announcement once for injected, nothing for wall).
    Application integration, `tests/integration/test_admin_time.py` through
    `RegistryClient` with the administrator key, the source injected at
    1794822300 and the time route mounted on the suite's shared app as an injected
    registry mounts it: status reads T, `set_time(T + 1800)` answers it and status
    follows, `set_time(T)` raises 409 with `"code":"time_moves_forward"` in the
    body, `set_time(True)` 422 with `"code":"invalid_time"`; an empty or wrong
    key is refused 401 on both routes and the source stays at T; under wall time,
    installed explicitly, status reads `{"source": "wall"}` and `set_time` 404
    (the guard's when an earlier test has mounted the route on the shared app,
    routing's when the test runs alone); the composition root started in a
    process of its own with `TIME_SOURCE` `injected` serves `POST /admin/time`,
    and with `wall` does not; after
    `set_time(T + 1800)` the seller-signed `publish_listing`, signed at T + 1800,
    is accepted and the listing's `created_at` is T + 1800. The misspelled source:
    the composition root started in a process of its own with
    `TIME_SOURCE=injectd` exits with the component's exact refusal, a process
    start, not application integration. `make -C core/registry test` 155 unit
    and 172 integration.
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
  - Done: `Settings.configured_time_source` (`time.source`, keys in any case);
    `main.py` installs it at module level before the app is built, mounts
    `system_controller.make_time_router()` only when it is injected, announces it
    in the lifespan, and gives `SiteAuthMiddleware` the time operation. The
    contracts `credits_system_status` (`GET /api/v1/system/status`) and
    `credits_system_time` (`POST /api/v1/system/time`) sit beside the others,
    admitting only `admin` (an empty role set, which `permits` reads as the
    administrator alone); the status route answers `{"time": {...}}`. The hosted
    site ledger reads the installed source (section 5).
  - Evidence, application integration,
    `domains/apicredits/service/tests/integration/test_system_time.py`: the real
    `main.app` composed fresh from configuration with `time.source` stated through
    the loader's override layer, as `test_signed_authority` composes it, through
    `CreditsServiceClient` signed as the operator's `admin`. Composed injected,
    with the scenario's source at 1794822300 installed in place of the one the
    composition installed: status reads it; `set_time(1794823200)` answers it,
    its signed answer verifying against the client's source at that instant;
    status agrees; `set_time(1794822300)` raises 409 with reason
    `time_moves_forward`, `set_time(True)` 422 with `invalid_time`. A client
    signed as the gated application's `service` is refused 403 on both routes and
    the time is unchanged. Composed under wall time, status reads `{"source":
    "wall"}` and `set_time` raises 404 (the route unmounted, the request
    authenticated against its contract first). The composed exemption (D14):
    with the service at 1794822300, a setting signed by the operator 900 s ahead,
    built by hand since the client signs at the process's instant, is admitted
    and moves the source, and a status read signed there is refused 403 (raw
    requests, statuses only). Composed injected, the lifespan logs the
    announcement. The misspelled source refuses the composition root's start (a
    process of its own, the exact refusal). The route parity test holds the
    client's two operations to the contracts, the administrator alone admitted.
    Unit, `tests/unit/test_time_source.py`: `configured_time_source` unset, a
    scalar `time`, keys in any case. `make -C domains/apicredits test`: the
    service 90, every other suite of the domain passing. Not shown at this
    service's level: its hosted site ledger deciding by the injected instant,
    which `kit/site`'s library tests (5.2) and provisioning's application test
    (10.2) show for the same ledger over the process source.
  - Outside the plan: composing the service now installs its configured source,
    so section 6's `test_a_grant_and_its_spending_hold_the_injected_instant`,
    whose fixture installed its source before composing, had it replaced by the
    composition's wall source; its fixture now installs after the composition.
- [x] 11.3 The registry client and the credits service's client gain the setting call
  and the status read; the registry client sends the administrator key.
  - Verify: `make test-registry-client`; the credits client's suite.
  - Done: `RegistryClient.get_admin_status(admin_key=...)` and
    `set_time(now, admin_key=...)`, and their sync forms, send the
    administrator key in place of any read key the client carries, unsigned, and
    parse `AdminStatusResponse` and `TimeSettingResponse` (exported); a non-2xx
    answer raises `RegistryClientError` with the status and body.
    `CreditsServiceClient` gains `caller_role` (the storefront's `seller` by
    default, `admin` for an operator), `get_system_status()` and `set_time(now)`,
    raising `CreditsServiceError` with the status and, from a time route's
    refusal, its `code` as the reason (the key routes' `error` stays first). The
    registry's dev bound on its client rises to 0.13.0 and the credits service's
    on the domain package to 0.10.0, the unreleased versions that add them.
  - Evidence: unit, `core/registry-client/tests/test_admin_time.py` (over an
    `httpx.MockTransport`: the setting posts `{"now"}` with the administrator key
    alone and no signature; the sync status read and setting; a refusal's status
    and body); `make -C core/registry-client test` 31 passed. The credits client
    is exercised against the real service above; its domain suite (41) passes.
- [x] 11.4 Section verification.
  - Application integration: `make test-registry`, `make test-registry-client`,
    `make test-domains` (the API-credits service).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 15's fixture sets both once section 16 puts the lanes on
    injected time.
  - Evidence: the suites in 11.1–11.3 and 10.1's amendment, after the
    fresh-context fixes. `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` before them: `after-functional-change`
    and `pre-commit-functional` (every suite) passed; of `pre-commit` the
    citations check failed on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9), and the local-imports
    check on the parity test's new import (now at module level). On the final
    tree: `after-functional-change` (`make lock`) and `pre-commit-functional`
    (`make dist-clean`, `make check-packaging`, `make test`, every suite) passed,
    and of `pre-commit` only the citations check failed, on that document.
  - Confirmed: no end-to-end marker exercises these routes yet (sections 15 and
    16). No owed CI evidence: the suites run in the workflows' existing jobs.
  - Fresh-context check: it found a comment claiming the status operation is
    verified without freshness (reworded: the time operation alone), the credits
    time route's 404 guard unreachable there, since every test composes the
    service fresh (removed; the registry's and provisioning's stay, their suites
    sharing one app reach them), the composed exemption untested (the skewed
    test above), `configured_time_source` untested here (unit tests added), the
    registry's and provisioning's injected composition never run (a
    process-start test of each, the route served injected and not under wall),
    the wall-time 404's source in the registry depending on test order
    (reworded), stale comments on the credits client's fixed `seller` role, the
    contracts module's scope and the OpenAPI tag (fixed), and the sync
    `set_time` unexercised (added). Declined: application-level evidence of the
    credits service's hosted ledger (above, shown for the same ledger by 5.2 and
    10.2); one `configured_time_source` for the two services and the storefront
    kit, three packages with no shared dependency but the time component, which
    names no configuration layout; the registry client's unit refusal test
    beside the integration one, since it holds the client's own error
    construction; a sync/async parity test for the registry client, a gap
    before this section; and reading the registry refusal's `code` through the
    client, whose error carries the body alone, as every registry route's does.
  - Handoff for section 12 and later. Every service now installs at its
    composition root and mounts its route only under injected time: the
    storefronts by `[Time] source`, provisioning and the credits service by
    `time.source`, the registry by `TIME_SOURCE`. The static check (section 12)
    reads exactly those keys. Section 15's fixture reaches them through
    `StorefrontClient.set_time`, `ComputeProvisioningClient.set_time`,
    `RegistryClient.set_time(admin_key=...)` and `CreditsServiceClient(...,
    caller_role="admin").set_time`, each with its status read; composing a
    service in a test after installing a source replaces it with the
    configured one.

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
  - Done: `scripts/tests/test_committed_time_sources.py`, a static configuration
    test in the scripts' suite, beside `test_committed_stack_values.py`, since it
    spans charts, Compose stacks and packaged service settings. It reads the
    umbrella's and every chart's `values.yaml`; both local releases' values
    (`helm/local-values.yaml`, `helm/bare-metal-release-values.yaml`); the
    production examples — every chart's `examples/*values*.yaml`, the seller's
    and the registry's production Compose stacks (`compose/seller.yml`,
    `compose/registry.yml`) and `config.registry.env.example`; and the shipped
    presets — each service's packaged `settings.toml`, provisioning's packaged
    profiles (`config/*.yml`, which its image loads by default), and the
    storefront files committed for an operator that no lane mounts
    (`storefront.bob.toml`, `storefront.credits.toml`). Each is parsed as its
    consumer parses it (YAML, TOML, or `KEY=VALUE` lines), keys in any case, and
    searched for `time.source` under any spelling of its section, `TIME_SOURCE`,
    or an override variable ending `_TIME__SOURCE`, in a mapping or a Compose
    `KEY=VALUE` list; each refusal names the file and the setting's dotted path,
    which names the party. A listed file that is missing fails, and so does a
    glob that stops finding the bare-metal production example or provisioning's
    `config.yml` and `config-seller.yml`.
  - Correction to the plan's list: no buyer preset ships (the buyer is a binary
    with no packaged configuration), so none is read. Left out as the lanes'
    own: their Compose files, `dev-env/`, `storefront.*.lane.toml`, and the
    storefront files the lanes share with the full local stack,
    `storefront.alice.toml` (the VM lane) and `storefront.dev.toml` (the
    bare-metal lane, with `dev-env/bare-metal/buyer.toml`); the end-to-end
    runner's profiles, which configure no party; and `helm/fixtures/`, the
    charts' render fixtures. The search reads the files rather than what Helm or
    Compose would render, so it refuses a setting even where a chart would drop
    it (the registry chart renders a fixed list of keys), stricter than a render
    and with no tool gate.
  - Evidence, static configuration: `make test-release-tooling` 3184 passed,
    among them the tree test (no refusal), the files-and-families test, and the
    planted cases over copies under a temporary root, the committed tree never
    edited: the bare-metal production example with `config.Time.source` or
    `config.time.source` set to `"injected"` is refused naming that file and
    path; provisioning's packaged `config-seller.yml` with `time.source`, a
    Compose service with `PROVISIONING_TIME__SOURCE=injected` in its
    environment list, and an env file with `TIME_SOURCE=injected` are refused, a
    `wall` source is not.
- [x] 12.2 Section verification.
  - `make test-release-tooling`; `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes`.
  - End-to-end: pre-review validation's scenarios against the local Helm release run in
    wall mode (`deployment-state`'s "The local release is validated"), shown once
    section 15's wall mode exists.
  - Owed by validation: `tests.yml`, job `test · test-deployment-packaging` — the
    static configuration test runs and passes.
  - Confirmed: no end-to-end marker exercises the check. The local Helm
    release's values set no time source, so every party defaults to wall time;
    no test reads each party's status there yet, which section 15's wall mode
    owes ("The local release is validated"). The owed job is right:
    `test-deployment-packaging` runs `make test-release-tooling`, which collects
    `scripts/tests/`.
  - Evidence: `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` on the first form of the test:
    `after-functional-change` and `pre-commit-functional` (every suite) passed,
    and of `pre-commit` only the citations check failed, on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9). On the final tree, the
    same: `after-functional-change` (`make lock`) and `pre-commit-functional`
    (`make dist-clean`, `make check-packaging`, `make test`, every suite) passed,
    and of `pre-commit` only the citations check failed, on that document.
  - Fresh-context check: it found packaged provisioning profiles, the production
    Compose stacks and the registry's env example outside the check, and
    `storefront.bob.toml` and `storefront.credits.toml` wrongly called the
    lanes' own (all now read); the `TIME_SOURCE` form matched in no file its
    consumer reads (it now reads the env example and Compose environments,
    where it is read); the docstring calling every lane injected and the
    runner's profiles the lanes' (reworded), `helm/fixtures/` unnamed (named),
    the glob's results unasserted (asserted), and the local release's wall time
    claimed from defaults (reworded). Declined: moving the test to
    `helm/tests/`, since it reads Compose stacks and packaged service settings
    too, as `test_committed_stack_values.py` does from this suite; and rendering
    with Helm and Compose, which would drop keys the files state and gate the
    test on both tools, where a parse refuses more and needs neither.
  - Handoff for section 16: `storefront.alice.toml` and `storefront.dev.toml`
    (with `dev-env/bare-metal/buyer.toml`) are mounted both by a lane and by the
    full local stack, so setting injected time in them puts the full local stack
    on injected time too, a mode D16, D17 and D21 do not name for it. Section 16
    either gives each lane an overlay of its own for those parties, as Bob's
    `storefront.bob.lane.toml` is, or settles the full local stack's mode.

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
  - Done: `clock.py` (`PerceivedClock`, `wall_clock`) and its test are removed; a
    new `time_control.TimeControl(source)` wraps the component's
    `TimeRouteService` for a party's handlers — `settable`, `view()` and
    `set_time(raw body)`, the component's refusals raised as `ControlError`
    (`409 time_moves_forward`, `422 invalid_time`, both new `ControlCode`s, the
    message the component's detail); it is served only where `settable` holds.
    Models: `ClockAdvance`/`ClockView` give way to `TimeView`
    (`source` `wall`|`injected`, `now` a strict integer read by the component's
    `check_instant`, stated exactly when injected); `Status` is `{"time": TimeView, "contracts"}`,
    the services' status shape, so the fixture reads every party's `time` alike.
    Routes: `TIME = POST /test/time` replaces the two clock routes; a route's
    `doubles` is now `parties: frozenset[ControlParty]`, `ControlParty` adding
    `"sample-app"`, which serves `TIME` and `STATUS` alone;
    `routes_for(party, *, time_settable)` leaves `TIME` out for a wall-time party.
    The client gains `set_time(now)`, which sends `{"now": now}` as given (so a
    test can send a boolean), and loses the two clock methods. README updated:
    the parties, the time control, its refusals.
  - Evidence, unit and library integration: `make test-lane-double-controls`,
    133 passed, mypy strict clean — `test_time_control.py` (unit: injected
    viewed and set; wall viewed without an instant and not settable; each refusal
    changes nothing), `test_models.py` (`TimeView`'s two forms and seven refused
    ones), `test_routes.py` (each party's routes; no `TIME` for a wall-time
    party), and `test_client.py` (the stand-in surface: `set_time` sends
    `POST /test/time {"now"}`, status parses the time section, the new codes
    raise as `ControlError`).
- [x] 13.2 Both doubles read the shared injected source, install it from a time-source
  setting in their configuration (`"injected"` in every lane), and serve the new route
  and status behind their control bearer token (D18).
  - Verify: `make test-payments-lane-double` and `make test-mediation-lane-double`,
    including: a once part's hold pays out at the next read after time is set past its
    release instant, with no background work.
  - Done: each double's `create_app(..., source=None)` reads the given source or
    the process's installed one, gives its engine or service `source.now`, and
    registers `TIME` only while the source is settable (the handler-set check
    takes `routes_for(..., time_settable=...)`); status reports `time` beside the
    contract hashes. The setting is an environment variable, the doubles'
    configuration form: `PAYMENTS_LANE_DOUBLE_TIME_SOURCE`,
    `MEDIATION_LANE_DOUBLE_TIME_SOURCE`, `"wall"` by default (the local Helm
    release runs both doubles and stays on wall time, D17); `Settings` refuses any
    other value through the component's `source_for`, naming the variable, and
    `settings.install_time_source(settings)`, which `__main__` calls before
    building the app, installs the source process-wide (so the payments kit's own
    `injected_time.now` defaults read it too) and logs an injected one at INFO;
    `__main__` configures logging first so the line shows. Section 16 sets
    `"injected"` in the lanes. Both declare `arkhai-injected-time` and are
    relocked; READMEs updated. `PaymentsDouble`'s clock default is
    `injected_time.now`.
  - Evidence, unit and application integration (the doubles' apps in process
    through the typed control client and the kits' real clients):
    `make test-payments-lane-double` 93 passed — `test_controls.py` (status at
    the injected instant; a set held, a repeat of the instant accepted; 409 and
    422 change nothing; a wall-time double reports `wall` and answers the route
    404; admission refuses a mandate expired at the set instant),
    `test_double.py::test_a_once_hold_pays_out_at_the_next_read_once_time_is_set_to_its_release`
    (held a second before the release, released at the first read after the
    set; the double has no background work to do it otherwise), the rate cases
    now set time through the control, and `tests/unit/test_settings.py` (the
    variable: unset → wall, `injected`, `injectd` refused naming it; the install
    helper installs and announces injected time and installs wall time
    silently); `make test-mediation-lane-double` 78 passed —
    `test_controls.py::test_the_time_and_status` (set, status, 409, 422), records
    dated at the set instant, `test_mechanics.py`'s once hold reported `paid_out`
    after a set, and its own `test_settings.py`, the same cases. The mediation
    suite shares one `InjectedTime` between the double and the payments engine it
    calls, as one lane time. `__main__` itself (uvicorn serving) is run by no
    test; its install is the helper above.
- [x] 13.3 The sample app installs its source from `APICREDITS_SAMPLE_APP_TIME_SOURCE`
  and, under injected time, serves `POST /test/time` and its status behind a control
  bearer token from its environment, through `lane-double-controls`' models and client,
  excluded from the metering gate (D18).
  - Verify: application-integration tests in the sample app's suite: the control sets
    the app's instant and is neither charged nor refused by the gate; after a set 3600 s
    forward with the credits service set alike, a metered call's consume request is
    accepted (`test-compatibility`'s "Metered calls continue after an advance").
  - Done: `configured_app()` installs the source from
    `APICREDITS_SAMPLE_APP_TIME_SOURCE` (`"wall"` by default, any other value
    refused naming it), logs an injected one at INFO, and builds the app; the
    console script serves it through uvicorn's factory form after configuring
    logging, so the module no longer builds an app at import (nothing else
    imported `apicredits_sample_app.app:app`);
    `create_app(..., source=None, control_token=None)` serves `TIME` and `STATUS`
    through `TimeControl` only when the source is injected, behind
    `APICREDITS_SAMPLE_APP_CONTROL_TOKEN` (`lane_double_controls.routes.authorize`),
    and adds both paths to the gate's `exclude_paths`; an injected app with no
    token refuses to build, naming the variable. A wall-time app serves neither
    route. The app declares `arkhai-injected-time` and `lane-double-controls`
    (both in the wheelhouse `make dist` builds, which the sample app's image
    installs from), and `arkhai-kit-identity` in its dev group for the suite's
    stand-in, and is relocked. Section 16 sets both variables in the lane. The
    control token is an environment variable, as D18 states: like the doubles'
    control tokens, committed in their fixture files, it is a public development
    value guarding a control only an injected app serves, not a credential, so
    `configuration.md`'s secret-file rule does not bear on it.
  - Evidence, application integration, `domains/apicredits/sample-app/tests/test_time_control.py`
    (the real app in process; the control through `ControlClient`; the gate
    signing with `AuthoritySigning` to a stand-in credits service holding one
    key, which verifies each signed call with `market_identity.verify_request` at
    a time of its own and signs its answers): the control sets the app's instant
    and status follows, with no call reaching the credits service; 409 and 422
    and a wrong token change nothing; with the stand-in an hour ahead, a metered
    call is refused 401 because the gate's verification is refused
    `TIMESTAMP_SKEW` and the call answers 401 (whose answer the gate then
    refuses too, signed an hour ahead), and after the control sets the app an
    hour forward the call answers 200, its verification and consume both
    `VERIFIED` and one credit spent; on a wall-time app (gate and stand-in both on
    wall time) the typed client's `set_time` meets the gate, not a control — a
    401 that is no control error — the stand-in having verified the gate's call
    and answered the control token 404 as an unknown key, nothing spent; an
    injected app without a token refuses to build. `configured_app()`, in process
    with its environment patched: injected installs a new source, logs the
    announcement and mounts the route; unset installs wall time, logs nothing and
    mounts neither control route; `injectd` is refused naming the variable and
    installs nothing. `make -C domains/apicredits/sample-app test` 11 passed. The
    new file sits flat in `tests/` beside the suite's one existing file; moving
    both into `unit/`/`integration/` is outside this change, and is a row under
    "Unowned work found by `drive-the-storefront-clock-in-lanes`" in
    `openspec/changes/README.md`, with section 7's `kit/deal-lifecycle-client`. Correction to the
    plan's wording: the credits service is a verifying stand-in, not the real
    service; the real service against the same middleware signing at an
    injected instant is section 6's `test_signed_authority.py` test.
- [x] 13.4 Section verification.
  - Unit and application integration: `make test-lane-double-controls`,
    `make test-payments-lane-double`, `make test-mediation-lane-double`,
    `make test-domains` (the sample app).
  - `scripts/change-workflow run pre-commit drive-the-storefront-clock-in-lanes`.
  - End-to-end: section 16's lanes.
  - Owed by validation: `tests.yml`, jobs `test · test-lane-double-controls`,
    `test · test-payments-lane-double` and `test · test-mediation-lane-double` — each
    passes with the new route.
  - Outside the plan, pulled forward because this section removes the routes it
    called: the e2e harness's doubles' clock half — `LaneDoubleClock`,
    `clocks_reset_after` and the `lane_double_clock` fixture in
    `e2e-tests/tests/e2e/roles/helpers/lane_doubles.py`, its re-export in
    `roles/conftest.py`, and their three unit tests in
    `tests/unit/test_lane_doubles_fixtures.py` — is removed (15.5's removal);
    `test_lane_doubles_evidence.py` builds the new `Status`; and
    `test_hold_passed.py` is bridged — `tests/unit/test_scenario_cleanup_order.py`
    plans every scenario's fixtures, so a module naming a removed fixture fails
    the unit suite — with a module fixture of both doubles' control clients
    setting each double's time past the terms end and the release (16.2 moves it
    to the lane-time fixture). Until section 16 sets the doubles' time source in
    the lanes, that module fails in a lane run: the doubles start on wall time and
    serve no time route. `e2e-tests/README.md`'s hold-passed row and module-order
    paragraph say what the module now does. `docs/guidance/repository/deal-scenarios.md`
    and `docs/guidance/engineering/system-tests.md` still name `lane_double_clock`
    until section 17 restates them.
  - Outside the plan, found by the fresh-context check: section 12's static
    check (`scripts/tests/test_committed_time_sources.py`) matched `TIME_SOURCE`
    and `*_TIME__SOURCE` only, missing this section's
    `PAYMENTS_LANE_DOUBLE_TIME_SOURCE`, `MEDIATION_LANE_DOUBLE_TIME_SOURCE` and
    `APICREDITS_SAMPLE_APP_TIME_SOURCE`; it now matches `*_TIME_SOURCE` too, a
    planted mapping value of the double's variable refused and a stated `wall`
    passed. That shows the name is matched in a mapping or a Compose `KEY=VALUE`
    list; neither double's chart takes environment values today, and a
    Kubernetes `name:`/`value:` list is not read. The stale descriptions of the
    controls package — `published-packages.md`'s unpublished projects, the root
    `Makefile`'s `dist` comment, `tools/README.md`'s entry (18.9 adds the
    component's own entry), `TESTING.md`'s controls paragraph and the package's
    `pyproject.toml` — name the sample app and the time control.
  - Citations: design.md's Context and tasks 7's plan and 7.4 cited the removed
    clock module by its file path; they now name the module,
    `lane_double_controls.clock`, which the citation check does not read as a
    path, their meaning unchanged.
  - Evidence: `make test-lane-double-controls` 133, `make test-payments-lane-double`
    93, `make test-mediation-lane-double` 78, `make -C domains/apicredits/sample-app
    test` 11, `make test-release-tooling` 3184 (the static check among them),
    each after the fresh-context fixes; `make test-e2e-unit` 908 passed (1
    skipped) before them. `scripts/change-workflow run pre-commit
    drive-the-storefront-clock-in-lanes` before the fixes:
    `after-functional-change` and `pre-commit-functional` (every suite) passed;
    of `pre-commit`, the citations check failed on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9) and on the removed clock
    module (resolved above). On the fixed tree: `after-functional-change` (`make
    lock`) and `pre-commit-functional` (`make dist-clean`, `make
    check-packaging`, `make test`, every suite, `make test-e2e-unit` among them)
    passed; of `pre-commit`, the citations check failed on closeout's document
    and on this note's own citation of the removed path, since reworded. On the
    final tree, after the second check's fixes: `after-functional-change` and
    `pre-commit-functional` (every suite) passed, and of `pre-commit` only the
    citations check failed, on closeout's
    `openspec/specs/injected-time/architecture.md` (18.9).
  - Each new test imports what only this change adds (`injected_time`,
    `TimeView`, `TimeControl`), so against the round's base each fails at
    collection, which shows less than a behavioural failure.
  - End-to-end scenarios covering the section, none run by it: once section 16
    puts the lanes on injected time, `e2e_vm_dispute_hold_passed` sets the
    doubles' time, every lane module runs both doubles, and the API-credits
    lane's modules the sample app. The owed jobs are right: each runs in
    `tests.yml`'s matrix, a workflow `scripts/ci_evidence.py` lists.
  - Fresh-context check: it found the e2e work and its broken module
    unrecorded (recorded above), no startup announcement in the doubles or the
    sample app (added, with tests), the sample app's wall-time test passing only
    because the wall clock was far from its fixed instant and asserting a raw
    call's body (the stand-in now holds one key and runs on wall time with the
    gate, and the test asserts the status and the stand-in's record), "no lane
    publishes its port" untrue of the sample app (reworded in `routes.py` and the
    README), the static check missing the new settings (fixed), `TimeView`
    restating the value rule (it now calls `check_instant`), the stale package
    descriptions (fixed), the undeclared `market_identity` test import (added to
    the dev group), a subprocess test where an in-process call proves the same
    (now in process), an unreachable guard in `TimeControl.set_time` (removed),
    a misnamed token test (renamed), and three overstated claims (reworded).
    Declined: moving the sample app's tests into `integration/` (above), and the
    control token's environment variable (D18 states it; above). A second check,
    over the fixes, found the wall-time test still sending a raw call (it now
    uses the typed client), a comment on `TimeView`'s strict mode and a client
    message naming only the doubles (fixed), a docstring claiming an injected
    source (fixed), no test of a wall-time app leaving the route unmounted
    (added), two unwrapped docstrings (wrapped), and three claims broader than
    their tests (the static check, the skewed and wall-time cases, the
    end-to-end line; reworded). It repeated the flat layout, now recorded as a
    change-index row, and the control token, declined for the reason above.

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
