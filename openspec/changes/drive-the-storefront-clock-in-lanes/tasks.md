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
`tools/lane-double-controls/src/lane_double_controls/clock.py`,
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
  `lane_double_controls/clock.py`'s `wall_clock` and any direct read in the two
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
