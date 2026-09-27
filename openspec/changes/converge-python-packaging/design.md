# Design — converge Python packaging

## Context

A rebuilt wheel keeps its version, so `uv sync` keeps whatever copy and whatever
recorded dependencies an environment already holds unless told otherwise. The
repository answered that with hand-maintained lists in every place that syncs, and
with per-project exceptions wherever a project did not fit the wheelhouse pattern.
This change replaces the lists with derivations and the exceptions with one layout,
and makes both checkable at closeout.

The change was proposed as `derive-internal-package-lists-from-locks`, scoped to
`reinit` targets and Dockerfile refresh lists. Discussion widened it to the
build process generally, and it was renamed.

## Findings from the current tree

These were established by reading the tree and by running uv directly; they motivate
the decisions below.

**Hand lists have drifted, and the existing check missed one.** In
`domains/apicredits/service/Makefile`, `reinit`'s rule line ends with a `##` help
comment and a backslash; Make continues the comment onto the next line, so
`--upgrade-package arkhai-kit-capability-shape` is never passed (`make -n reinit`
confirms). `scripts/check_reinit.py` matches only the first rule line and counts the
continued line as recipe text, so it passes. `domains/vms/provisioning/adapter` has no
`tests/` directory, so the check skips it; its list is missing `arkhai-compute` and
`arkhai-kit-capability-shape`. Dockerfile lists are unchecked and further behind:
compared with what each lock resolves from `.dist`, `e2e-tests` misses 12,
`apicredits/service` 8, `compute/service` 7, `vms/storefront` 6.

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

**Images do not all install from their lock.** `apicredits/sample-app`,
`compute/service`, and `bare_metal/storefront` `uv pip install` top-level wheels; the
first two refresh their own wheel, which their locks record as editable, and the third
resolves third-party versions freshly on each build. Every lock-based image refreshes
with `--refresh-package` only, so a rebuilt wheel that gained a dependency installs
without it — the fourth row above.

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

**Every package any lock resolves from a local registry is declared by a repository
project** (40 names). That matches `deployment-state`'s rule that `.dist` holds only
repository-built artifacts, so derivation needs no repository-wide name list.

## Decisions

### D1. The lock is the only source of the internal-package set

The internal packages a project refreshes are exactly those its `uv.lock` resolves
from a local wheel registry — a `registry` source that is a filesystem path, relative
or absolute. Index-served packages, source packages, and the project itself are
excluded. The set is computed when the command runs, so a lock rewritten earlier in
the same invocation is read after the rewrite.

*Rejected: deriving image refreshes from the wheelhouse contents.* It was proposed
while three images did not install from their lock. Once they converge (D5), the lock
is what `make test` exercised and is what an image should build.

### D2. One script owns every uv invocation that touches the wheelhouse

`scripts/uv_project.py`, standard library only, run from the project directory:

- `reinit` — `uv sync --python <declared> --find-links <relative .dist>` plus, per
  internal package, `--upgrade-package X --reinstall-package X`.
- `image -- <uv sync options>` — `uv sync` with the options the Dockerfile passes
  (groups, extras, `--no-install-project`) plus the same per-package pair. The
  Dockerfile states what to install; the script states which packages are internal.
- `install-wheel` — `uv pip install --no-deps --reinstall` of the project's own
  distribution at the version its `pyproject.toml` declares, from the wheelhouse,
  into `UV_PROJECT_ENVIRONMENT`.
- `lock [project …]` — `uv lock --find-links <relative .dist>` plus
  `--upgrade-package X` per internal package, for every named project or every
  project; installs nothing.

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
the ones to commit.

### D4. An image installs its lock exactly as `reinit` does

`image` passes the same `--upgrade-package X --reinstall-package X` pair (reinstall
implies refresh, which is what the persistent uv cache mount needs). An image is
therefore the committed lock relocked for internal packages the same way `reinit`
relocked it before `make test`. This also closes the defect where today's images
install a rebuilt wheel without a dependency it gained.

Images copy the project's `pyproject.toml` and `uv.lock` and the wheelhouse to the
same relative positions they hold in the repository (under a fixed image root such as
`/repo`) and set `UV_PROJECT_ENVIRONMENT` to the runtime venv path, so the lock is used
unmodified. The script is copied into builder stages only. The two deny-all
per-Dockerfile ignore files admit it; a missing admission fails the `COPY` loudly.

### D5. The three outlier images converge first

Slice 1 begins by moving `apicredits/sample-app`, `compute/service` (with
`--extra adapters`, already declared and locked), and `bare_metal/storefront` onto
lock-synced dependencies plus own-wheel install, so D4 applies to every image
uniformly. `bare_metal/storefront` thereby gains locked third-party versions.

### D6. The project's own version comes from its `pyproject.toml`

`install-wheel` reads name and version from `pyproject.toml`, removing the
`name==version` literals from Dockerfiles. `scripts/tests/test_storefront_image_pins.py`
exists only to catch drift in those literals and is removed.

### D7. `make lock` relocks unconditionally and installs nothing

It depends on `dist`, because a consumer's lock records its internal dependencies'
metadata from the wheels. Because `uv lock --check` cannot detect a same-version
wheel's changed dependencies, `lock` does not skip projects it judges current; relocking
a current project is fast and changes nothing. It replaces
`scripts/refresh-review-locks.py`, and `make review-locks` calls it with the review
scope's projects.

### D8. One Python version, declared once

A root `.python-version` holds `3.13`, matching the CI pin. `uv_project.py` reads it and
passes `--python` explicitly, so no project relies on uv's discovery reaching a parent
directory. Makefiles stop passing `--python` and drop `PYTHON_VERSION` used only for
syncing. Dockerfile `PYTHON_VERSION` defaults become `3.13`; the four images on 3.12 move
(the locked `alkahest_py` release ships `cp313` wheels). The script itself uses only the
standard library and runs under the host `python3`.

### D9. No project declares the wheelhouse

The ten `[tool.uv] find-links` declarations are removed. The script supplies
`--find-links`, and test targets keep supplying it on `uv run`, so the repository layout
is stated only by the tool that depends on it.

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

`make check-packaging` runs each; each is also its own target.

| Target | Fails on |
|---|---|
| `check-uv-setup` | a project with tests whose lock installs internal wheels and has no `reinit`; a `reinit` recipe other than the script call; a Dockerfile uv install from the wheelhouse not made through the script; any literal `--upgrade-package`, `--reinstall-package`, or `--refresh-package`; a lock registry rewrite; a repository distribution's `name==version` in a Dockerfile |
| `check-locks` | a lock that fails `uv lock --check`, or that pins an internal package at a version the tree does not build |
| `check-python-version` | a `--python` value, `.python-version` file, or Dockerfile `PYTHON_VERSION` default other than the root declaration |
| `check-project-layout` | a wheel target that is not one package under `src/`; `[tool.uv] find-links`; `cache-keys`; a relative `[tool.uv.sources]` path; `UV_NO_EDITABLE`, `--no-editable`, or `no_editable` outside image builds |

Makefiles are parsed with Make's rules — backslash continuation, and comments on rule
lines — so the defect in the Findings cannot recur. Dockerfiles are parsed per stage and
per instruction with continuation. `check-locks` runs after `dist`; it needs no network
when locks are current. `check-uv-setup` absorbs `check_reinit.py`; `check-locks` absorbs
`check_internal_locks.py`.

`check-locks` does not detect a same-version wheel's changed dependencies; `reinit`,
`lock`, and image builds all repair that state, and the end-to-end pipeline builds images
with the same flags.

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

## Slices

1. **Environments** — D1–D9, D12 without `check-project-layout`, D13, D14 for what the
   slice makes true. Order: outlier images (D5), Python declaration (D8), script and
   callers (D2–D4, D6, D7, D9), checks, documentation.
2. **Layout** — D10, D11, `check-project-layout`, and the layout sections of
   `BUILD_AND_PACKAGING.md`.

Slice 1 leaves `UV_NO_EDITABLE` and `cache-keys` in place for the six projects; the
script's uv commands inherit the environment, so their behavior is unchanged until
slice 2.

## Risks

- **Mirrored layout in images.** Verified with uv locally; each image's build and its
  existing import smoke checks confirm it.
- **PyTorch index access.** `make lock` and `reinit` for the three projects that declare
  the index need it; an environment that blocks it cannot relock them. Reported as a
  uv resolution failure naming the package.
- **Import rename.** Mechanical but wide; each renamed project's suite, every consumer's
  suite, wheel-content inspection, and the end-to-end pipeline cover it.
- **3.12 → 3.13 images.** Covered by image builds and the end-to-end pipeline.

## Rollback

No persisted state or wire contract changes; reverting the change restores the prior
build. The import rename is a public API break for anyone importing the six packages
outside this repository; reverting it restores the old paths.

## Open questions

None.
