# Design — converge Python packaging

## Context

A rebuilt wheel keeps its version, so `uv sync` keeps whatever copy and whatever
recorded dependencies an environment already holds unless told otherwise. The
repository answered that with hand-maintained lists in every place that syncs, and
with per-project exceptions wherever a project did not fit the wheelhouse pattern.
This change replaces the lists with derivations and the exceptions with one layout,
and makes both checkable at closeout.

The change was proposed as `derive-internal-package-lists-from-locks`, scoped to
`reinit` targets and Dockerfile refresh lists. Discussion widened it to the build
process generally, and it was renamed. A design review then tightened the image lock
contract, the lock-currency proof, the definition of an internal package, the script's
scope, and the inventory, and added the version bumps the import renames require; see
"Review resolution".

## Findings from the current tree

These were established by reading the tree and by running uv directly; they motivate
the decisions below.

**Hand lists have drifted, and the existing check missed one.** In
`domains/apicredits/service/Makefile`, `reinit`'s rule line ends with a `##` help
comment and a backslash; Make continues the comment onto the next line, so
`--upgrade-package arkhai-kit-capability-shape` is never passed (`make -n reinit`
confirms). `check_reinit.py` matches only the first rule line and counts the
continued line as recipe text, so it passes. `domains/vms/provisioning/adapter` has no
`tests/` directory, so the check skips it; its list is missing `arkhai-compute` and
`arkhai-kit-capability-shape`. Dockerfile lists are unchecked and further behind:
compared with what each lock resolves from `.dist`, `e2e-tests` misses 12,
`apicredits/service` 8, `compute/service` 7, `vms/storefront` 6.

**Four Dockerfiles carry seven version literals.** Four name the image's own
distribution (`compute/service`, `vms/storefront`, `bare_metal/storefront`,
`apicredits/storefront`). `compute/service` also names both provisioning adapters, which
its `adapters` extra already declares and locks. `vms/storefront` also names
`arkhai-bare-metal-storefront`, a base dependency its builder stage already installs
from the lock; its runtime stage copies `.dist` only to install these two wheels.

**Both reinit flags are needed, for different reasons.** Rebuilding a wheel at the
same version and syncing a consumer:

| Wheel rebuilt with | Flags | Outcome |
|---|---|---|
| new code | none | old code kept |
| new code | `--reinstall-package` | new code |
| new code | `--upgrade-package` only | old code kept |
| a new dependency | `--reinstall-package` (with or without `--locked`) | new code, dependency missing, exit 0 |
| a new dependency | `--upgrade-package` | lock rewritten, dependency installed |

`--reinstall-package` replaces installed code; `--upgrade-package` makes uv re-read the
wheel's metadata and rewrite the dependencies the lock records for it. `uv lock
--check` and `--locked` cannot see a same-version wheel's changed dependencies.

**A lock goes stale against a same-version wheel only through metadata.** A lock
records a local wheel by filename, with no hash, and records the names (and extras) of
its dependencies. New code in a same-version wheel therefore never makes a lock stale;
changed requirements do, and both sides of that comparison are readable offline: the
wheel's `METADATA` in `.dist`, and the lock's record.

**Images do not all install from their lock.** `apicredits/sample-app`,
`compute/service`, and `bare_metal/storefront` `uv pip install` top-level wheels; the
first two refresh their own wheel, which their locks record as editable, and the third
resolves third-party versions freshly on each build.

**A committed lock works unmodified from a mirrored layout.** With the project and the
wheelhouse at the same relative positions as in the repository, `uv sync --locked`
resolves the lock's relative registry path with no `--find-links`, and
`UV_PROJECT_ENVIRONMENT` places the venv anywhere. The `sed` rewrite is unnecessary.

**Relocking is fast and metadata-only, except where the PyTorch index is
unreachable.** `uv lock --check` on `kit/policy` completes in under a second with no
network. A relock of `kit/policy` — even one upgrading only an internal package —
re-resolves every platform split and needs `download.pytorch.org`.

**The editable exceptions come from one layout.** Six projects map their root
directory onto a nested `domains.*` import path. Hatch has no editable form for that
mapping, so they install from a wheel (`UV_NO_EDITABLE` in three Makefiles and two CI
matrix entries) and rebuild through `cache-keys` globs in three `pyproject.toml` files.
Every other project is `src/<import package>` and editable. About 140 Python files
import the six paths. No configuration, persisted state, or model file names them; the
RL models load by file path, and policies are referenced by registered name.
`docs/configuration.md` shows hook authors one of the paths.

**Publication skips a version that already exists.** `.github/workflows/publish-pypi.yml`
runs on pushes to `main` that touch a published package's paths, and skips any
distribution whose declared version PyPI already has. All six renamed distributions
are in its matrix. Its `apicredits-domain` path filter already names a `src/` tree the
project does not have yet.

**Every package any lock resolves from a local registry is declared by a repository
project** (40 names), and every such registry is the repository wheelhouse.

**uv does not read a `.python-version` above the project.** A project nested below a
directory holding `.python-version` gets the host's default interpreter from both
`uv run` and `uv sync`. Of 75 Make targets that run uv in a project with a `reinit`
target, 40 do not depend on `reinit`, and 27 `init` or `install` targets run their own
`uv sync`; any of them can create an environment on whatever interpreter the host has.
(Found at planning.)

## Decisions

### D1. An internal package is one the lock resolves from the repository wheelhouse

For refresh derivation, the internal packages of a project are exactly those its
`uv.lock` resolves from the repository wheelhouse: a `registry` source whose path,
resolved against the project directory, is the canonical `.dist`. Any other local
registry path is an error, not an internal package. Index-served packages, source
packages, and the project itself are excluded. The set is computed when the command
runs, so a lock rewritten earlier in the same invocation is read after the rewrite.

This definition needs only the project and the wheelhouse, so it works inside an image.
It cannot on its own notice a repository distribution that has started resolving from
an index; the repository-wide inventory in D12 does.

*Rejected: deriving image refreshes from the wheelhouse contents.* It was proposed
while three images did not install from their lock. Once they converge (D5), the lock
is what `make test` exercised and is what an image should build.

### D2. One script owns environment sync, lock generation, and image installs

`scripts/uv_project.py`, standard library only, run from the project directory, owns
the operations that mutate an environment or a lock against the wheelhouse:

- `reinit` — `uv sync --python <declared> --find-links <relative .dist>` plus, per
  internal package, `--upgrade-package X --reinstall-package X`.
- `image -- <uv sync options>` — `uv sync --locked` with the options the Dockerfile
  passes (groups, extras, `--no-install-project`) plus `--reinstall-package X` per
  internal package. The Dockerfile states what to install; the script states which
  packages are internal.
- `install-wheel` — `uv pip install --no-deps --no-index --reinstall --find-links
  <.dist>` of the project's own distribution at the version its `pyproject.toml`
  declares, into `UV_PROJECT_ENVIRONMENT`. `--no-index` keeps it from falling through to
  an index when the wheel is missing: `--find-links` adds candidates rather than
  replacing the index.
- `lock [project …]` — `uv lock --find-links <relative .dist>` plus
  `--upgrade-package X` per internal package, for every named project or every
  project; installs nothing.

Every Makefile `uv sync` goes through it: `init` and `install` targets that sync depend
on `reinit` instead, and an aggregate Makefile that syncs another project calls the
script with `--project <dir>`. Read-only uses of the wheelhouse stay outside it: test and
service targets' `uv run --find-links` executes against the project environment, on the
interpreter D8 fixes.

The script runs the command rather than printing flags for a caller to splice in.
The originally accepted design had Makefiles call `$$(python3 …)` inside the `uv sync`
arguments; a failing command substitution expands to nothing with exit status 0, so a
missing or unreadable lock would sync with no package refreshed — the failure this
change exists to remove. A failed derivation exits non-zero before any uv command runs.

The wheelhouse path is passed relative to the project so every lock records one
canonical registry path.

### D3. `reinit` upgrades and reinstalls, and never uses `--locked`

Per the findings table, reinstall alone installs new code without a dependency the
rebuilt wheel gained, and `--locked` succeeds in that state. Iterating on a wheel
without bumping its version therefore legitimately rewrites the consumer lock's
recorded dependencies, and `reinit` must be allowed to do so. Those lock changes are
committed; `check-locks` (D12) fails until they are.

### D4. An image installs the committed lock and never relocks

`image` syncs with `--locked` and `--reinstall-package X` per internal package. The
reinstall flag implies a refresh, which is what the persistent uv cache mount needs to
drop a previous build of a same-version wheel. Nothing in an image build rewrites the
lock, so the image contains the lock the project's tests ran against, as committed.

`--locked` rejects a lock that no longer matches its `pyproject.toml`, but not one that
recorded a same-version wheel's old requirements; `check-locks` (D12) is what keeps such
a lock from being committed. The image contract therefore rests on the closeout gate,
not on the build detecting it.

Images copy the project's `pyproject.toml` and `uv.lock` and the wheelhouse to the
same relative positions they hold in the repository: the project at its repository
depth below an image root, the wheelhouse at `<image root>/.dist`. Most images use
`/repo/<path>`; `e2e-tests`, one level deep, keeps `/app` with `/.dist`, so its editable
project install stays valid in the runtime stage. uv refuses to normalise a path above
`/`, so the depth must match exactly. Image syncs drop `--no-sources`, which contradicts
`--locked` for a lock resolved with index sources and set `UV_PROJECT_ENVIRONMENT` to the runtime venv path, so the lock is used
unmodified. The script is copied into builder stages only. The two deny-all
per-Dockerfile ignore files admit it; a missing admission fails the `COPY` loudly.

### D5. The three outlier images converge first

Slice 1 begins by moving `apicredits/sample-app`, `compute/service` (with
`--extra adapters`, already declared and locked), and `bare_metal/storefront` onto
lock-synced dependencies plus own-wheel install, so D4 applies to every image
uniformly. `bare_metal/storefront` thereby gains locked third-party versions.

### D6. An image installs only its own distribution by version, in the builder stage

`install-wheel` reads the name and version from `pyproject.toml`, so no Dockerfile
spells a version. Every other repository distribution an image needs comes from the
lock sync: the adapter literals in `compute/service` disappear with its `adapters`
extra, and the second wheel in the VM storefront's runtime stage is dropped because the
builder already installs it. The own-wheel install runs in the builder stage; runtime
stages copy the finished venv and do not copy the wheelhouse.
`test_storefront_image_pins.py` exists only to catch drift in version
literals and is removed.

### D7. `make lock` relocks unconditionally and installs nothing

It depends on `dist`, because a consumer's lock records its internal dependencies'
metadata from the wheels. It upgrades every internal package and every other
repository distribution the lock names, so a distribution that drifted to an index
returns to the wheelhouse; implementation found two locks installing
`arkhai-kit-config` 0.1.0 from PyPI instead of the tree's 0.1.2. It relocks every project it is given rather than skipping any
a check reports current: relocking a current project is fast and changes nothing. A
relock that leaves the tree unchanged is the strongest available proof of lock currency,
and needs the network, including the PyPI and PyTorch indexes. It replaces
`refresh-review-locks.py`, and `make review-locks` calls it with the review
scope's projects.

### D8. One Python version, declared once

A root `.python-version` holds `3.13`, matching the CI pin. uv does not discover it from
a nested project, so every consumer reads it explicitly:

- `uv_project.py` passes `--python` with it.
- Every Makefile that runs uv exports `UV_PYTHON` read from it by relative path, which uv
  honors wherever it would honor `--python`; `uv run` targets that create an environment
  therefore create it on the declared version. `--python` flags and `PYTHON_VERSION`
  variables are removed.
- CI jobs that run uv in a project set `UV_PYTHON` from it; the `python-version: 3.13.7`
  setup pins agree at minor precision.
- `REVIEW_PYTHON` defaults to it.
- Dockerfiles declare `ARG PYTHON_VERSION=3.13` and use it in every `FROM`; the four
  images on 3.12, three of which hard-code the tag, move (the locked `alkahest_py`
  release ships `cp313` wheels).

The script itself uses only the standard library and runs under the host `python3`.

*Rejected: a `.python-version` in each project* — 44 copies of one fact. *Rejected:
capping each project's `requires-python`* — it changes what published wheels admit.

### D9. No project declares the wheelhouse

The ten `[tool.uv] find-links` declarations are removed. The script supplies
`--find-links`, and test targets keep supplying it on `uv run`, so the repository layout
is stated only by the tools that depend on it.

### D10. Every distribution is one flat import package under `src/`, installed editable

This is the repository layout the wheelhouse pattern assumes: each project builds a
wheel of `src/<import package>`, and consumers import it from `.dist`. The six
nested-import projects move to that layout with flat names following the domain-package
precedent (`arkhai_vms`, `arkhai_bare_metal`, `arkhai_compute`):

| Distribution | From | To |
|---|---|---|
| `arkhai-vms-buyer` | `domains.vms.buyer` | `arkhai_vms_buyer` |
| `arkhai-vms-listings` | `domains.vms.listings` | `arkhai_vms_listings` |
| `arkhai-vms-negotiation` | `domains.vms.negotiation` | `arkhai_vms_negotiation` |
| `arkhai-vms-settlement` | `domains.vms.settlement` | `arkhai_vms_settlement` |
| `arkhai-apicredits-buyer` | `domains.apicredits.buyer` | `arkhai_apicredits_buyer` |
| `arkhai-apicredits-domain` | `domains.apicredits` | `arkhai_apicredits` |
| `arkhai-core-registry` | `src.*` from source; wheel ships `types`, `services`, `api`, `db` | `core_registry` |
| `arkhai-apicredits-service` | `db`, `models`, `services`, … on `PYTHONPATH`; wheel ships six generic packages including `tests` | `apicredits_service` |
| `arkhai-e2e-tests` | `src.*` (the wheel's package is named `src`) | `e2e_harness` |

The last three were found at planning, when every project's wheel target was checked
against the rule. The two published ones are broken as wheels, not only inconsistent:
the registry's code imports `src.api` while its wheel installs top-level `api` and a
`types` package the standard library shadows, and the service's wheel ships its own
`tests` and generic `db`, `models`, and `services` packages. All three work only because
they run from source. Both move to hatchling with a single package. Two other findings
need no rename: `core` and `core/registry-client` use `force-include` only for their own
`py.typed`, which hatch already includes, so the setting is dropped with wheel contents
unchanged; and `domains/vms/provisioning/iac` is a virtual project that builds no wheel,
so the rule, which is about distributions, does not reach it.

No alias is kept. Every project then installs editable, and `UV_NO_EDITABLE`, the CI
`no_editable` flag, and `cache-keys` have no remaining reason to exist. `domains` and
`domains.vms` cease to be import packages.

*Rejected: `src/domains/vms/buyer/…` preserving import names.* It installs editable,
but repeats the directory path inside itself and keeps an import path that no other
project follows. *Rejected: every project non-editable.* It needs `cache-keys` globs,
a hand list, and leaves `.venv/bin/pytest` running stale code between syncs.

### D11. Relative sources are removed with the layout

`domains/bare_metal/provisioning/adapter` resolves seven siblings through relative
editable `[tool.uv.sources]`. They move to `.dist` resolution in slice 2, which completes
`remove-relative-uv-sources`' remaining cutover.

### D12. Packaging conventions are checked by four focused scripts

`make check-packaging` depends on `dist` and then runs each; each is also its own
target. The checks read the committed tree and the built wheelhouse, and never resolve
dependencies, relock, or contact a package index. Building the wheelhouse is a
prerequisite with its own needs: `uv build` isolates each build and fetches the
project's declared build backend (`hatchling`, or `setuptools` and `wheel`), so from a
clean cache `dist` needs the index that serves them. What closeout never needs is the
indexes the locks resolve from — in particular the PyTorch index. With a cold cache and
the network disabled, `uv lock --check` on `kit/policy` passes while `uv build` fails.

*Rejected: wheel builds without network, by disabling build isolation against a shared,
pre-provisioned build environment.* That environment would be a new hand-maintained list
of build backends and versions, and would make wheel contents depend on it rather than on
each project's `build-system.requires`. Every place closeout runs can reach the index
that serves build backends. *Rejected: dropping the no-index property for the checks.*
It is true, testable, and is what lets closeout run where the PyTorch index is blocked.

| Target | Fails on |
|---|---|
| `check-uv-setup` | a project with tests whose lock installs internal wheels and has no `reinit`; a `reinit` recipe other than the script call; a Dockerfile uv install from the wheelhouse not made through the script; any literal `--upgrade-package`, `--reinstall-package`, or `--refresh-package`; a lock registry rewrite; a repository distribution's `name==version` in a Dockerfile; a runtime stage that copies the wheelhouse |
| `check-locks` | see below |
| `check-python-version` | a `.python-version` file other than the root one; a `--python` literal in a Makefile, shell script, or tool phase configuration; a Makefile that runs uv without exporting `UV_PYTHON` from the root declaration by a path that resolves; a CI job that runs uv without `UV_PYTHON` from it, or whose `UV_PYTHON` step precedes checkout or carries a different `if:` than checkout; a Dockerfile `FROM` with a hard-coded Python tag, a `FROM` using `${PYTHON_VERSION}` without an `ARG PYTHON_VERSION` default before the first `FROM`, or a default other than the root declaration |
| `check-project-layout` | a wheel target that is not one package under `src/`; `[tool.uv] find-links`; `cache-keys`; a relative `[tool.uv.sources]` path; `UV_NO_EDITABLE`, `--no-editable`, or `no_editable` outside image builds |

`check-locks` proves lock currency on three axes:

1. **Against the project.** `uv lock --check`, which catches a lock that no longer
   satisfies its `pyproject.toml`.
2. **Against the wheels.** For each package a lock resolves from the wheelhouse, the
   locked version is one the tree builds, and the wheel of that version in `.dist`
   agrees with the lock's record: the names of its unconditional requirements equal the
   lock's recorded dependencies, and the names under each extra in use equal that extra's
   recorded dependencies, a missing section counting as empty. An extra is in use when a
   lock dependency edge, a locked project's `requires-dist`, or a locked wheel's
   `Requires-Dist` requests it; uv records no section for an empty extra and, when the
   extra is empty, no extra on the consumer's edge either. Each locked dependency version
   must satisfy the wheel's specifier for it, checked against the version uv records on
   the dependency edge when the resolution forks; a specifier or version the check cannot
   evaluate is a problem, not a pass. This catches a same-version wheel whose requirements changed
   after the consumer was last locked.
3. **Against the repository inventory.** The set of repository distributions is derived
   from every project `pyproject.toml`. Any lock that resolves one of them from anywhere
   but the wheelhouse — an index, or another local path — fails, and so does any lock
   whose wheelhouse registry is not the canonical `.dist`.

Environment markers are not compared beyond deciding which extra a requirement belongs
to: uv simplifies markers against `requires-python` when it locks, so a textual
comparison would report differences that are not staleness. A same-version wheel that
changes only a requirement's platform or version marker is the residual this check does
not see; `make lock` followed by an unchanged tree covers it.

Makefiles are parsed with Make's rules — backslash continuation, and comments on rule
lines — so the defect in the Findings cannot recur. Dockerfiles are parsed per stage and
per instruction with continuation. `check-uv-setup` absorbs `check_reinit.py`;
`check-locks` absorbs `check_internal_locks.py`.

### D13. Closeout runs `make check-packaging`

`openspec/README.md#plan-closeout-requirements` gains a packaging part, and
`planning-governance` states it normatively. `AGENTS.md` and
`docs/prompts/implementation.md` name `make check-packaging` wherever they name
`make check-reinit`. The closeout task of every active change whose closeout is not yet
complete gains the step; completed closeout tasks are left as recorded.

### D14. `BUILD_AND_PACKAGING.md` is the permanent guide

`docs/development/BUILD_AND_PACKAGING.md` owns the layout rule, wheelhouse consumption,
the `reinit`/`image`/`lock` workflow, the Python declaration, and a table mapping each
rule to the check enforcing it. `ARCHITECTURE.md` keeps a short build section linking
to it; `openspec/README.md`'s placement table gains its row. Each slice adds only what
it has made true.

### D15. The stray `deployment-state` section is folded into requirements

"Internal wheel development contract" sits after `## Evidence`, where no delta can
modify it. This change's delta adds its content as requirements; promotion deletes the
section. The existing "Packaging preserves provider separation" requirement still
describes the hosted client as a staged wheel to "rebuild, upgrade, and reinstall"; it
is modified to "move the pin and relock", since the client is index-served and pinned
exactly.

### D16. Slice 2 bumps the version of every distribution whose wheel contents change

The publication workflow skips a version PyPI already has, so renamed code published
under an unchanged version would never reach PyPI, and the next consumer release pinned
to that version would install the old import paths. Every distribution whose built wheel
contents change in slice 2 therefore bumps its version: the eight renamed published
distributions, and every other published distribution whose source changes to follow the
renamed imports. A breaking import change in a 0.x release takes a minor bump; any other
changed wheel takes the bump `RELEASING.md`'s versioning policy gives it, as the
middleware's comment-only change took a patch bump (13.4).
Every `==` pin on a bumped distribution moves with it, and the affected locks are
relocked with `make lock`. Planning enumerates the distributions from ownership of the
changed sites — imports, entry points, test patch targets, and warning filters — keeping
those whose changed files ship in the wheel. Implementation confirms the enumeration by
comparing each distribution's wheel contents before and after the rename; a distribution
whose contents changed but was not bumped fails that comparison.

`publish-pypi.yml`'s path filters are updated to the moved directories, and
`docs/development/RELEASING.md` records the import migration for the bumped releases.
The publication mechanism is otherwise unchanged; `publish-wheels-through-a-gate` owns
it.

## Slices

1. **Environments** — D1–D9, D12 without `check-project-layout`, D13, D14 for what the
   slice makes true. Order: outlier images (D5), Python declaration (D8), script and
   callers (D2–D4, D6, D7, D9), checks, documentation.
2. **Layout** — D10, D11, D16, `check-project-layout`, and the layout sections of
   `BUILD_AND_PACKAGING.md`.

Slice 1 leaves `UV_NO_EDITABLE` and `cache-keys` in place for the six projects; the
script's uv commands inherit the environment, so their behavior is unchanged until
slice 2.

## Review resolution

A design review raised eight findings; each is resolved as follows.

1. *Image lock contract contradictory* — images use `--locked` and never relock (D4).
2. *Closeout gate cannot prove lock currency* — `check-locks` compares wheel metadata
   with lock records offline, with its residual stated (D12); `make lock` is the
   network-dependent stronger proof (D7).
3. *Import renames not technically necessary* — the flat layout is kept as decided (D10).
4. *Renames lack a versioning story* — slice 2 bumps every changed distribution (D16).
5. *Internal-package definition too loose* — canonical wheelhouse in the script (D1),
   repository inventory in `check-locks` (D12).
6. *Script ownership overstated; `install-wheel` not fail-closed* — scope narrowed to
   mutating operations, and `install-wheel` uses `--no-index` (D2).
7. *Inventory miscounted* — four Dockerfiles, seven literals (Findings, D6).
8. *Not yet planned* — the file-level plan and closeout task are the planning phase.

A second review found one further contradiction, resolved as follows.

9. *The packaging target promised to run without network, but its `dist` prerequisite
   fetches build backends* — the target builds the wheelhouse first, and the no-network
   promise is narrowed to the checks, which never resolve, relock, or contact an index
   (D12). Wheel production stays isolated.
10. *Distributions to bump cannot be enumerated by comparing wheels before planning* —
    planning enumerates from ownership of changed sites; wheel comparison validates at
    implementation (D16).

Planning found one further gap, resolved without changing any decision's intent:
uv ignores a parent `.python-version`, so D8 now exports `UV_PYTHON` from the
declaration in every Makefile and CI job that runs uv, and D2 routes every Makefile
`uv sync` through `reinit`.

## Implementation review resolution

A review of the implemented slice 1 raised four corrections, planned as section 12.

- **R1 — A CI step that reads `.python-version` ran where checkout did not.** In
  `hosted-stripe-test.yml`, checkout is gated on `env.SELECTED`, the added `UV_PYTHON` step
  was not, and unselected matrix rows would fail reading a file that was never checked out.
  `check-python-version` proved only that the step existed. The step now carries
  checkout's condition, and the check requires, in every job, that the step follow
  checkout and carry the same `if:`. A general rule was chosen over a test of the one
  workflow, so every gated job is covered.
- **R2 — `check-locks` missed a requirement added to an empty extra.** Reproduced with real
  uv: when a consumer requests `pkg[client]` and `client` is empty, uv records no
  `optional-dependencies` section for it and no extra on the consumer's edge — only the
  consumer's `requires-dist` names it. After a same-version rebuild gives `client` a
  requirement, `uv lock --check --offline` passes and the check, which compared only
  recorded sections, did too. The extras in use are now derived from every place that can
  request one, and the lock-shape tests now run the real `uv` rather than hand-written
  lock data, because uv's serialisation is the boundary under test.
- **R3 — A Dockerfile using `${PYTHON_VERSION}` without declaring it passed.** The check
  now requires the `ARG` default.
- **R4 — `check-locks` passed what it could not evaluate.** Unparseable specifiers or
  versions, and dependencies locked at several versions, were skipped. Forked resolutions
  now use the version uv records on the dependency edge; anything still unprovable is a
  reported problem. Today's tree has no such case.

The review also corrected overstated status: 4.2 claimed a real-uv lock it did not use, 4.6
said a suite passed that has two failures present at the checkpoint, 3.7 claimed an
unverified second `make lock` run, and `BUILD_AND_PACKAGING.md` said no file states the
Python version although Dockerfile `ARG` defaults do. The image builds and pipeline it
counted as unrun have since passed in CI run 36409616543.

## Slice 2 review resolution

A review of the implemented slice 2 found four issues, corrected in section 13.

- **The VM buyer computed the repository root at a fixed depth** (`parents[3]`), which the
  move to `src/` broke; the network commands pointed at a nonexistent `scripts/zerotier`.
  Fixed depth was only ever right from a source checkout, so the root is now found by its
  markers (the root `.python-version`, which `check-python-version` keeps unique, and the
  VM storefront).
- **The review-scope manifest named moved or absent test roots.** A test now requires every
  path it names to exist.
- **Moved tests kept a wrong tier.** Tests running a real app or database are integration
  under `TESTING.md` and moved when touched; integration happy paths go through canonical
  typed clients, so the three key-administration reads with no client method gained one
  rather than staying raw requests.
- **The proposal and several comments still described the six-project scope and old source
  paths.** The citation check scans documentation, not code comments or Helm values, which
  is how the path references survived.

## Risks

- **Mirrored layout in images.** Verified with uv locally; each image's build and its
  existing import smoke checks confirm it.
- **Metadata comparison noise.** `check-locks` compares requirement names and
  specifiers, not markers; its tests include a lock uv produced for a wheel with
  platform-marked and extra-scoped requirements, so a correct lock is shown to pass.
- **PyTorch index access.** `make lock` and `reinit` for the three projects that declare
  the index need it; an environment that blocks it cannot relock them. Reported as a
  uv resolution failure naming the package.
- **Import rename and publication.** Mechanical but wide; each renamed project's suite,
  every consumer's suite, wheel-content inspection, and the end-to-end pipeline cover
  the rename, and D16 keeps PyPI consistent with it.
- **3.12 → 3.13 images.** Covered by image builds and the end-to-end pipeline.

## Rollback

No persisted state or wire contract changes; reverting the change restores the prior
build. The import rename is a public API break for anyone importing the eight renamed
published packages outside this repository; versions already published under the new paths remain on
PyPI, and a revert would publish further bumped versions restoring the old paths.

## Open questions

None.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 An internal package is one the lock resolves from the repository wheelhouse | `openspec/specs/deployment-state/spec.md` — "A project environment refreshes exactly the internal packages its lock installs"; `docs/development/BUILD_AND_PACKAGING.md#the-wheelhouse` |
| D2 One script owns environment sync, lock generation, and image installs | `docs/development/BUILD_AND_PACKAGING.md#project-environments`, `#locks`, `#images`; `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` |
| D3 `reinit` upgrades and reinstalls and never uses `--locked` | `openspec/specs/deployment-state/spec.md` — "A project environment refreshes exactly the internal packages its lock installs"; `openspec/specs/deployment-state/architecture.md#artifact-and-package-boundary` |
| D4 An image installs the committed lock and never relocks, from a layout at the project's repository depth | `openspec/specs/deployment-state/spec.md` — "An image installs the committed lock"; `openspec/specs/deployment-state/architecture.md#artifact-and-package-boundary`; `docs/development/BUILD_AND_PACKAGING.md#images` |
| D5 The outlier images converge on lock sync plus own wheel | `openspec/specs/deployment-state/spec.md` — "An image installs the committed lock" |
| D6 An image installs only its own distribution by version, in the builder stage | `openspec/specs/deployment-state/spec.md` — "An image installs the committed lock"; `docs/development/BUILD_AND_PACKAGING.md#images` |
| D7 `make lock` relocks unconditionally, upgrading internal and repository distributions, and installs nothing | `openspec/specs/deployment-state/spec.md` — "Locks are refreshed without installing"; `docs/development/BUILD_AND_PACKAGING.md#locks` |
| D8 One Python version, declared once and read explicitly everywhere | `openspec/specs/deployment-state/spec.md` — "One Python version is declared for the repository"; `docs/development/BUILD_AND_PACKAGING.md#one-python-version` |
| D9 No project declares the wheelhouse | `openspec/specs/deployment-state/spec.md` — "Internal distributions are consumed as wheels from the repository wheelhouse"; `docs/development/BUILD_AND_PACKAGING.md#the-wheelhouse` |
| D12 Packaging checks (`check-uv-setup`, `check-locks`, `check-python-version`) | `openspec/specs/deployment-state/spec.md` — "Packaging conventions are checked mechanically"; `docs/development/BUILD_AND_PACKAGING.md#checks` |
| D13 Closeout runs `make check-packaging` | `openspec/specs/planning-governance/spec.md` — "Packaging check at change closeout"; `openspec/README.md#plan-closeout-requirements`, part 8; `AGENTS.md` |
| D14 `BUILD_AND_PACKAGING.md` is the permanent guide | `docs/development/BUILD_AND_PACKAGING.md`; `openspec/README.md` documentation placement table |
| D15 Stray internal-wheel section folded into requirements; hosted-client updates move the pin and relock | `openspec/specs/deployment-state/spec.md` — "Internal distributions are consumed as wheels…", "Aggregate kit tests cover every kit", "Packaging preserves provider separation" |
| R1 A CI step reading the declaration shares checkout's `if:` and follows it | `openspec/specs/deployment-state/spec.md` — "One Python version is declared for the repository" (scenario "A CI job checks out conditionally"); `docs/development/BUILD_AND_PACKAGING.md#one-python-version` |
| R2 Lock currency derives the extras in use from edges, `requires-dist`, and wheel requirements | `openspec/specs/deployment-state/spec.md` — "Packaging conventions are checked mechanically" (scenario "An empty extra a consumer requests gains a requirement"); `docs/development/BUILD_AND_PACKAGING.md#checks` |
| R3 A Dockerfile using `${PYTHON_VERSION}` declares its default before the first `FROM` | `docs/development/BUILD_AND_PACKAGING.md#one-python-version`, `#checks` |
| R4 Unprovable version checks fail; forked locks use the edge version | `docs/development/BUILD_AND_PACKAGING.md#checks`; this change's D12 |
| D10 Every distribution is one flat import package under `src/`, installed editable | `openspec/specs/deployment-state/spec.md` — "Each distribution is one flat import package under src"; `docs/development/BUILD_AND_PACKAGING.md#project-layout` |
| D11 Relative sources removed | `openspec/specs/deployment-state/spec.md` — "Internal distributions are consumed as wheels from the repository wheelhouse" (scenario "A project declares a sibling source"); `docs/development/RELEASING.md#local-development` |
| D16 Changed distributions bump their version | `docs/development/RELEASING.md#import-package-renames`, and the versioning policy there |
| `check-project-layout` | `openspec/specs/deployment-state/spec.md` — "Packaging conventions are checked mechanically"; `docs/development/BUILD_AND_PACKAGING.md#checks` |

Slice 1's requirements are already in the owning specs, so archive must not add them again: prune them from this change's delta, or archive without spec sync, once slice 2 has promoted the rest.
