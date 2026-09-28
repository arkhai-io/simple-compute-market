## Why

Every project that installs internal wheels from `.dist` repeats, by hand, facts its
own lock and `pyproject.toml` already state:

- 37 `reinit` targets list `--upgrade-package X --reinstall-package X` per internal
  package; 7 Dockerfiles list `--refresh-package X`; 4 Dockerfiles carry 7
  repository-distribution version literals; 5 Dockerfiles rewrite the lock's registry
  path with `sed`;
  10 `pyproject.toml` files declare a relative `find-links` path; 3 declare
  `cache-keys` globs; 3 Makefiles and 2 CI matrix entries disable editable installs;
  16 `reinit` targets choose a Python version, 21 let uv choose.
- The lists have drifted. `make check-reinit` passes while the
  `domains/apicredits/service` `reinit` omits a package: Make reads the flag line as
  part of a help comment continued with a backslash. Nothing checks Dockerfile lists,
  and every one with a lock-based install misses packages its lock resolves from
  `.dist` — up to 12 of 35 for `e2e-tests`.
- Three images (`domains/apicredits/sample-app`, `provisioning/compute/service`,
  `domains/bare_metal/storefront`) do not install from their lock at all; the
  bare-metal storefront resolves third-party versions afresh on every build.
- Six projects (`domains/vms/buyer`, `listings`, `negotiation`, `settlement`,
  `domains/apicredits/buyer`, and the `domains/apicredits` domain) keep their modules
  at the project root and map the directory onto a nested `domains.*` import path.
  Hatch cannot install that mapping as editable, which is why editable installs are
  disabled for them and why `cache-keys` globs exist.
- Relocking is only available through `reinit` or `make test`, which also installs
  every dependency, including torch: a dependency edit to a torch-bearing project
  costs about fifteen minutes to refresh a lock.

Every one of these facts is derivable: from the lock, from `pyproject.toml`, or from
one repository-wide declaration.

## What Changes

The work lands in two implementation slices under this one change.

**Slice 1 — one way to build an environment.**

- The three outlier images converge on the convention the other images follow:
  dependencies synced from the committed lock, then the project's own wheel installed
  from `.dist`.
- One script, `scripts/uv_project.py`, owns the operations that mutate an environment
  or a lock against the wheelhouse: `reinit` (a project environment), `image` and
  `install-wheel` (image builds), and `lock` (relock without installing).
  Internal-package flags are derived from the lock when the command runs.
- Every `reinit` target is one call to that script. Every image install goes through
  it: dependencies from the committed lock with `--locked`, used unmodified from a
  layout that mirrors the repository, and the image's own wheel by the version its
  `pyproject.toml` declares, from the wheelhouse only.
- A root `make lock` relocks projects against current wheels and installs nothing.
  It replaces `refresh-review-locks.py`.
- Python 3.13 is declared once, in a root `.python-version`; environments and images
  use it. The four images on 3.12 move to 3.13.
- `[tool.uv] find-links` declarations are removed; the script supplies the wheelhouse.
- `make check-packaging` runs four focused checks — `check-uv-setup`, `check-locks`,
  `check-python-version`, and (from slice 2) `check-project-layout` — replacing
  `check-reinit` and `check-internal-locks`. The target builds `.dist` first; the
  checks themselves never resolve, relock, or contact an index. `check-locks` proves that each
  lock matches its project, that each internal wheel's requirements match what the lock
  recorded for it, and that every repository distribution resolves from the wheelhouse. The plan-closeout requirements, and the
  closeout task of every active change whose closeout is not yet complete, call it.
- `docs/development/BUILD_AND_PACKAGING.md` becomes the permanent home of these
  conventions and names the check that enforces each.

**Slice 2 — one project layout.**

- Nine projects move to one flat import package under `src/`: the six nested-import
  projects (`arkhai_vms_buyer`, `arkhai_vms_listings`, `arkhai_vms_negotiation`,
  `arkhai_vms_settlement`, `arkhai_apicredits_buyer`, `arkhai_apicredits`) and, found
  at planning, `core/registry` (`core_registry`), the API-credits service
  (`apicredits_service`), and `e2e-tests` (`e2e_harness`). Every import, entry point,
  test patch target, warning filter, image start command, and smoke import is renamed.
- Every project installs editable. `UV_NO_EDITABLE`, the CI `no_editable` flag, and
  `cache-keys` are removed.
- `domains/bare_metal/provisioning/adapter` stops resolving siblings through relative
  editable sources and installs them from `.dist`.
- Every distribution whose wheel contents change bumps its minor version, pins and
  locks follow, and the publication workflow's path filters move with the directories,
  so PyPI publishes the renamed code rather than skipping an existing version.
- `check-project-layout` joins `check-packaging`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: internal distributions are one flat import package under `src/`
  installed from the wheelhouse; project environments, images, and locks derive their
  internal-package flags from the lock; one Python version; packaging conventions are
  checked mechanically; the stray internal-wheel section is folded into
  requirements; hosted-client updates move the pin and relock.
- `planning-governance`: every change's closeout runs the packaging check.

## Non-Goals

- Changing which packages are internal, how `.dist` is built, or the `==` pins between
  internal packages. `reinit` reinstalls every internal wheel regardless of version, and
  `lock` upgrades internal pins, so exact pins cost an edit only at a version bump.
- The publication mechanism or the distribution inventory. Slice 2 changes versions,
  pins, and path filters so the existing workflow publishes the renamed packages;
  `publish-wheels-through-a-gate` owns the mechanism.
- How `registry`, `apicredits/service`, and `e2e-tests` images provide their own
  project (copied source, or an editable install); only their dependency installs change.
- How CI runs test suites, beyond removing the `no_editable` flag.

## Breaking changes

- **Public import paths.** Eight published distributions change their import package:
  `domains.vms.buyer` → `arkhai_vms_buyer`, `domains.vms.listings` →
  `arkhai_vms_listings`, `domains.vms.negotiation` → `arkhai_vms_negotiation`,
  `domains.vms.settlement` → `arkhai_vms_settlement`, `domains.apicredits.buyer` →
  `arkhai_apicredits_buyer`, `domains.apicredits` → `arkhai_apicredits`, the registry's
  top-level `api`/`db`/`services`/`types` → `core_registry`, and the API-credits
  service's top-level `controllers`/`db`/`middleware`/`models`/`services` →
  `apicredits_service`. `e2e-tests` also changes (`src` → `e2e_harness`) but is not
  published. No alias is kept. Each renamed distribution, and each published distribution whose source
  follows the rename, releases under a new minor version.
  `docs/configuration.md` documents one of these paths to hook authors.
- **Contributor workflow.** `make check-packaging` replaces `make check-reinit` and
  `make check-internal-locks`; `make lock` is the way to refresh locks. Every project
  environment uses Python 3.13, which uv installs when absent.
- **Deployment.** Four images move from Python 3.12 to 3.13.

No wire, database, or configuration contract changes.

## Impact

- `scripts/`: `uv_project.py` and four check scripts added; `check_reinit.py`,
  `check_internal_locks.py`, `refresh-review-locks.py`, and
  `tests/test_storefront_image_pins.py` removed.
- Every Makefile with a `reinit` target; the root `Makefile` (`lock`,
  `check-packaging`, review-lock targets); every Dockerfile that copies `.dist` and
  the two per-Dockerfile ignore files; `.python-version`; ten `pyproject.toml`
  `find-links` declarations.
- Slice 2: the nine projects' files, their `pyproject.toml` build targets, the
  registry's and service's image start commands and Alembic path, and about 150
  importing files across `domains/`, `e2e-tests/`, and kit boundary tests; the
  version, `==` pins, and locks of every distribution whose wheel contents change;
  `.github/workflows/tests.yml` and `.github/workflows/publish-pypi.yml`;
  `docs/development/RELEASING.md`.
- `AGENTS.md`, `docs/prompts/implementation.md`, `openspec/README.md`,
  `docs/development/ARCHITECTURE.md`, `docs/configuration.md`, the new
  `docs/development/BUILD_AND_PACKAGING.md`, and the closeout task of each active
  change whose closeout is incomplete.

## Dependencies

- `unbacked-listing-publication`, which edited the same files, was archived on
  2026-09-24.
- This change absorbs the open work of `remove-relative-uv-sources` (its sections 1–3):
  the path-source guard becomes `check-project-layout`, the remaining relative sources
  are removed in slice 2, and "which projects are owed a `reinit`" is answered by the
  rule `check-uv-setup` enforces. Its completed section 4 is unaffected.
- Relocking a project that declares the PyTorch index needs that index's metadata.
  An environment that blocks `download.pytorch.org` cannot relock those projects by
  any means; this change does not work around that.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Packaging and environment conventions, and the check enforcing each →
  `docs/development/BUILD_AND_PACKAGING.md` (new), linked from
  `ARCHITECTURE.md#build-packaging-and-initialization`, `AGENTS.md`, and the placement
  table in `openspec/README.md`.
- Normative packaging requirements → `openspec/specs/deployment-state/spec.md`.
- Why derivation reads the lock, why internal packages are both upgraded and
  reinstalled, why images mirror the repository layout →
  `openspec/specs/deployment-state/architecture.md#artifact-and-package-boundary`.
- Why lock currency is checked against wheel metadata, and what it cannot see → the
  same architecture section.
- Closeout runs `make check-packaging` → `openspec/README.md#plan-closeout-requirements`
  and `openspec/specs/planning-governance/spec.md`.
