# Build and packaging

How Python projects in this repository get their environments, locks, and images, and
which check enforces each convention. The normative requirements live in the
[deployment and state specification](../../openspec/specs/deployment-state/spec.md);
the architecture they serve is in
[`ARCHITECTURE.md`](ARCHITECTURE.md#build-packaging-and-initialization). The rules these
conventions apply are the engineering packaging guidance:
[`packaging.md`](../guidance/engineering/packaging.md) and its tool forms,
[`packaging-python.md`](../guidance/engineering/packaging-python.md),
[`packaging-uv.md`](../guidance/engineering/packaging-uv.md),
[`packaging-hatchling.md`](../guidance/engineering/packaging-hatchling.md), and
[`packaging-docker.md`](../guidance/engineering/packaging-docker.md).

Nothing here is maintained by hand
([`packaging.md`, "Nothing is maintained by hand"](../guidance/engineering/packaging.md#nothing-is-maintained-by-hand)):
no Makefile, Dockerfile, `pyproject.toml`, or workflow names an internal package or
repeats a version the project already declares. Nothing chooses the Python version
independently: each consumer reads the root declaration, and the one copy that cannot — a
Dockerfile's `ARG PYTHON_VERSION` default — is checked against it
([`packaging.md`, "One declaration of the runtime version"](../guidance/engineering/packaging.md#one-declaration-of-the-runtime-version)).

## Project layout

Every distribution builds its wheel with Hatchling, from one import package at
`src/<package>` with nothing remapped
([`packaging-python.md`](../guidance/engineering/packaging-python.md); the Hatchling form
in [`packaging-hatchling.md`](../guidance/engineering/packaging-hatchling.md)):

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/arkhai_vms_listings"]
```

Every project environment installs its own project editable
([`packaging-uv.md`, "Every project installs itself editable"](../guidance/engineering/packaging-uv.md#every-project-installs-itself-editable)).
Data files a package loads, such as the VM negotiation models, live inside the package
directory
([`packaging-python.md`, "Data files live inside the package"](../guidance/engineering/packaging-python.md#data-files-live-inside-the-package)).

## The wheelhouse

The store of built packages internal distributions are consumed from
([`packaging.md`, "Internal packages are consumed as built artifacts"](../guidance/engineering/packaging.md#internal-packages-are-consumed-as-built-artifacts))
is the repository wheelhouse, `.dist`, which `make dist` builds; a package is internal to
a project when the project's `uv.lock` resolves it from `.dist`. A project never declares
the wheelhouse itself: the tools that sync and lock pass it, relative to the project, so
every lock records the same registry path. `make dist` builds the lanes' superset of the
release set `make dist-release` builds, adding the wheels only tests depend on
([`RELEASING.md`](RELEASING.md)).

A rebuilt wheel keeps its version, so refreshing one takes both `--reinstall-package` and
`--upgrade-package`
([`packaging-uv.md`, "Refreshing a same-version wheel"](../guidance/engineering/packaging-uv.md#refreshing-a-same-version-wheel)).
`scripts/uv_project.py` derives the internal packages from the lock whenever it runs and
passes the flags each operation needs, so no caller lists them.

## One Python version

The root `.python-version` declares the version every environment and image uses, and
each consumer reads it explicitly
([`packaging-uv.md`, "The runtime version reaches every consumer"](../guidance/engineering/packaging-uv.md#the-runtime-version-reaches-every-consumer);
[`packaging-docker.md`, "One runtime version"](../guidance/engineering/packaging-docker.md#one-runtime-version)):

- `scripts/uv_project.py reinit` passes it as `--python`. `lock` needs no interpreter
  choice and `image` takes the image's own interpreter, which the base image fixes.
- Every Makefile that runs uv exports it as `UV_PYTHON`, by a path relative to the
  Makefile, so a target that creates an environment without `reinit` still creates it on
  the declared version:

  ```make
  export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
  ```

- Every CI job that runs uv sets it in a step after checkout that runs under the same
  `if:` condition as checkout:
  `echo "UV_PYTHON=$(cat .python-version)" >> "$GITHUB_ENV"`.
- Every Dockerfile declares `ARG PYTHON_VERSION=<declared>` before its first `FROM` and
  uses it in each `FROM`.

To change the version, edit `.python-version` and the Dockerfile defaults, then run
`make check-python-version`.

## Project environments

A project's `reinit` target is one line:

```make
reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../scripts/uv_project.py reinit
```

It syncs the environment and upgrades and reinstalls every internal package. It may
rewrite `uv.lock` when an internal wheel's requirements changed without a version bump;
commit that rewrite. `init` and `install` targets depend on `reinit` rather than syncing
themselves; test and service targets use `uv run --find-links $(DIST_DIR)` against the
environment `reinit` built. A project with tests whose lock installs anything from the
wheelhouse must have a `reinit` target.

## Locks

`make lock` is the relock
([`packaging-uv.md`, "Relock against fresh artifacts"](../guidance/engineering/packaging-uv.md#relock-against-fresh-artifacts)):
it relocks every project against a freshly built wheelhouse, unconditionally, and installs
nothing; `make lock PROJECTS="kit/site core/buyer"` narrows it. `check-locks` compares
names and specifiers but not markers, so it does not stand in for the relock. Run it
after editing a project's dependencies or bumping an internal version, instead of
reaching for `make test` to do it.

Locks are written by uv 0.12.22 or newer, the first release that writes lock revision 5,
the revision every committed lock carries
([`packaging-uv.md`, "Locks are written by a stated minimum uv"](../guidance/engineering/packaging-uv.md#locks-are-written-by-a-stated-minimum-uv)).
Two checks hold the locks steady between uv releases:

- `scripts/uv_project.py` refuses a uv older than the minimum, naming both versions,
  before its `lock` and `reinit` commands run uv, so the repository's relock and
  environment refresh — `make lock`, `make review-locks`, and each package's `make
  reinit` and `make init` — refuse before writing. `make lock` also runs `make
  check-uv-version` first, so it refuses before building the wheelhouse; change
  validation runs it before building anything. A plain `uv run` that relocks a changed
  project is not guarded.
- `check-locks` fails on a lock carrying any revision but 5, naming the lock and both
  revisions.

The minimum is `MINIMUM` in `scripts/check_uv_version.py`, and the revision
`LOCK_REVISION` in `scripts/check_locks.py`; CI's `tests.yml` and `e2e.yml` install the
minimum, uv 0.12.22. uv rewrites a lock only when something in it changes, so relocking
a current project leaves its revision as it was, and `make lock` upgrades nothing in a lock that names no internal package. To bring such
a lock to the running uv's revision, relock it in its project with `uv lock
--upgrade-package <its own distribution>`, after `make check-uv-version`; this moves no
dependency's version, though the rewrite may restate a marker as the running uv writes
it. A lock that names internal packages takes `make lock PROJECTS=<its project>`, which
rewrites it.

Relocking needs the indexes each lock resolves from. `domains/vms/buyer` and
`domains/vms/storefront` declare the PyTorch CPU index, so relocking them needs
`download.pytorch.org`; resolution fetches metadata only, not the wheels.

## Images

An image installs the committed lock exactly as it is
([`packaging-docker.md`, "An image installs the committed lock"](../guidance/engineering/packaging-docker.md#an-image-installs-the-committed-lock)).
The lock's wheelhouse path is relative, so the image copies the project's
`pyproject.toml` and `uv.lock` to the same depth below an image root as below the repository root, with the
wheelhouse at `<image root>/.dist`. uv will not resolve a path above `/`, so the depth
must match:

```dockerfile
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/vms/storefront/pyproject.toml domains/vms/storefront/uv.lock /repo/domains/vms/storefront/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/vms/storefront -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/vms/storefront
```

- `image -- <uv sync options>` runs the sync an image owes — `--locked`, every internal
  package reinstalled, never `--no-sources`
  ([`packaging-uv.md`, "The sync an image runs"](../guidance/engineering/packaging-uv.md#the-sync-an-image-runs)).
  The Dockerfile chooses groups and extras; the script chooses the packages.
- `install-wheel` installs the project's own distribution at the version its
  `pyproject.toml` declares, from the wheelhouse only (`--no-index`), into
  `UV_PROJECT_ENVIRONMENT`. Every other repository distribution comes from the lock.
- The script is copied into builder stages only, and the runtime stage copies the
  finished environment and never the wheelhouse
  ([`packaging-docker.md`, "Builder and runtime stages"](../guidance/engineering/packaging-docker.md#builder-and-runtime-stages)).
- A Dockerfile with a deny-all ignore file admits `scripts/uv_project.py` explicitly.
- An ignore file beside a Dockerfile that admits a tree whole states that tree's
  exclusions itself
  ([`packaging-docker.md`, "A Dockerfile's own ignore file"](../guidance/engineering/packaging-docker.md#a-dockerfiles-own-ignore-file)).
  The provisioning service's `Dockerfile.dockerignore` does this for both IaC trees it
  copies, Ansible's logs and retry files, an operator's inventories, and Terraform's
  state and variables among them.

A project one level deep can use `/app` itself with the wheelhouse at `/.dist`, which
keeps an editable install of the project valid in the runtime stage; `e2e-tests` does.
A deeper project whose wheel no image installs from the wheelhouse keeps its editable
install the same way at its mirrored path: `tools/payments-lane-double`'s image installs
the project editable at `/repo/tools/payments-lane-double` from its source, skipping
`install-wheel`, and its runtime stage copies the environment and `src/` to that same
path.

## Checks

`make check-packaging` builds the wheelhouse and runs every check, including the package architecture check whose rules [`ARCHITECTURE.md`](ARCHITECTURE.md#package-and-dependency-layers) states and [`ARCHITECTURE.toml`](ARCHITECTURE.toml) encodes. Each is also its own
target. None resolves dependencies, relocks, or contacts a package index; building the
wheelhouse fetches only the build backends each project declares. Every change runs it at
closeout ([this repository's closeout parts, "Packaging"](../../openspec/README.md#packaging)).

| Target | Fails on |
|---|---|
| `check-uv-setup` | a literal `--upgrade-package`, `--reinstall-package`, or `--refresh-package` in a Makefile or Dockerfile; a Makefile recipe running `uv sync` itself; a `reinit` recipe other than the script call by a path that resolves; a project with tests and wheelhouse packages but no `reinit`; a Dockerfile that rewrites a lock, spells a repository distribution's version, installs from the wheelhouse without the script, calls the script where its stage did not copy it, or copies the wheelhouse into the runtime stage |
| `check-locks` | a lock `uv lock --check --offline` rejects; a lock pinning an internal version the tree does not build; a lock whose record of an internal package disagrees with that wheel's metadata (a requirement added or removed, unconditionally or under an extra in use, or a locked version its specifier no longer admits); a version check it cannot evaluate; a repository distribution resolved from an index or from a local registry other than `.dist`; a lock carrying a lock revision other than 5, the one the repository's minimum uv writes |
| `check-uv-version` | an installed uv older than the minimum that writes the repository's locks, or one whose version cannot be read; `make lock` runs it, and `check-packaging` does not, since it reads the locks without writing them |
| `check-project-layout` | a distribution whose wheel target is not exactly `packages = ["src/<package>"]` with that package present, or that builds with another backend or other build settings; a `[tool.uv]` `find-links` or `cache-keys`; a `[tool.uv.sources]` entry naming a path; `UV_NO_EDITABLE`, `--no-editable`, or `no_editable` in a Makefile, shell script, or workflow |
| `check-architecture` | any of the four parts below failing; it reads only the tree, so it needs no wheelhouse, and it also runs on every push in CI |
| `check-architecture-layers` | a dependency, imported or declared, on a higher layer; packages of one layer depending on each other; a scope its layer may not hold; a project that is unclassified, that does not build exactly one package under `src/`, or whose override row no longer describes it; a rules file or package table naming something that does not exist, a duplicate row, or an owner that is not an open change |
| `check-architecture-scope` | a dependency whose scope is not a subset of the package's own; an identity literal outside a core or kit package's scope (a warning elsewhere) |
| `check-architecture-dependencies` | an internal distribution imported and not declared; a runtime reason for a dependency no longer declared, or now imported (a declaration without an import or a reason is a warning) |
| `check-architecture-kinds` | a contracts or client package depending on something its kind allowlist does not name; a declaration or import outside a package allowlist, the `allowed-dependencies` in a package's own `pyproject.toml`, or a third-party import such a package does not declare; any import of a plugin |
| `check-python-version` | a `.python-version` other than the root one; a literal `--python` version in a Makefile, shell script, or tool phase configuration; a Makefile running uv without exporting `UV_PYTHON` from the root declaration; a CI job running uv without it, setting it before checkout or under a different `if:` than checkout, or a setup pin of another minor version; a Dockerfile `FROM` naming a Python version, using `${PYTHON_VERSION}` without an `ARG` default before the first `FROM`, or a default other than the declared one |

uv records no section for an empty extra, and no extra on the consumer's dependency edge
either, so `check-locks` derives the extras in use from every place that can request one:
the lock's dependency edges, each locked project's `requires-dist`, and the requirements of
the wheels the lock installs. It compares environment markers only to decide which extra a
requirement belongs to, so a same-version wheel that changes nothing but a marker is not
seen; `make lock` followed by an unchanged tree is the stronger proof. It needs `.dist`
built first, which `check-packaging` does.
