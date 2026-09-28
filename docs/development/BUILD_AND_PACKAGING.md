# Build and packaging

How Python projects in this repository get their environments, locks, and images, and
which check enforces each convention. The normative requirements live in the
[deployment and state specification](../../openspec/specs/deployment-state/spec.md);
the architecture they serve is in
[`ARCHITECTURE.md`](ARCHITECTURE.md#build-packaging-and-initialization).

Every rule here replaces a list someone used to maintain by hand. Nothing in a Makefile,
Dockerfile, `pyproject.toml`, or workflow names an internal package or repeats a version the
project already declares, and nothing chooses the Python version independently: each
consumer reads the root declaration, and the one copy that cannot — a Dockerfile's
`ARG PYTHON_VERSION` default — is checked against it.

## The wheelhouse

Internal distributions are built as wheels into the repository wheelhouse, `.dist`, by
`make dist`, and every project consumes them from there. A project never resolves a
sibling through a source path, and never declares the wheelhouse itself: the tools that
sync and lock pass it, relative to the project, so every lock records the same registry
path.

A package is *internal* to a project when the project's `uv.lock` resolves it from the
wheelhouse. A lock that resolves anything from another local directory is an error.

A rebuilt wheel keeps its version, and uv keeps what it already has for a version it has
seen. Two flags undo that, and both are needed:

| Flag | Effect on a same-version wheel |
|---|---|
| `--reinstall-package` | replaces the installed code |
| `--upgrade-package` | re-reads the wheel's metadata and rewrites the dependencies the lock records for it |

Reinstalling alone installs new code without a dependency the rebuilt wheel gained, and
`uv sync --locked` succeeds in that state. `scripts/uv_project.py` derives the internal
packages from the lock whenever it runs and passes the flags each operation needs, so no
caller lists them.

## One Python version

The root `.python-version` declares the version every environment and image uses. uv does
not read that file from a nested project, so each consumer reads it explicitly:

- `scripts/uv_project.py reinit` passes it as `--python`. `lock` needs no interpreter
  choice and `image` takes the image's own interpreter, which the base image fixes.
- Every Makefile that runs uv exports it, by a path relative to the Makefile:

  ```make
  export UV_PYTHON := $(or $(shell cat ../../.python-version 2>/dev/null),$(error ../../.python-version not found))
  ```

  uv honours `UV_PYTHON` wherever it would honour `--python`, so a target that creates an
  environment without `reinit` still creates it on the declared version.
- Every CI job that runs uv sets it in a step after checkout that runs under the same
  `if:` condition as checkout:
  `echo "UV_PYTHON=$(cat .python-version)" >> "$GITHUB_ENV"`. A step that reads the file
  where checkout did not run fails; one that skips where checkout ran leaves uv on the
  runner's default.
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

`make lock` relocks every project against a freshly built wheelhouse and installs
nothing; `make lock PROJECTS="kit/site core/buyer"` narrows it. It upgrades every internal
package and every other repository distribution a lock names, so a distribution that has
drifted to a package index returns to the wheelhouse. It relocks unconditionally, because
no lock check can see a same-version wheel's changed requirements; relocking a current
project changes nothing. Run it after editing a project's dependencies or bumping an
internal version, instead of reaching for `make test` to do it.

Relocking needs the indexes each lock resolves from. `kit/policy`, `domains/vms/buyer`,
and `domains/vms/storefront` declare the PyTorch CPU index, so relocking them needs
`download.pytorch.org`; resolution fetches metadata only, not the wheels.

## Images

An image installs the committed lock exactly as it is, and never relocks. The lock's
wheelhouse path is relative, so the image copies the project's `pyproject.toml` and
`uv.lock` to the same depth below an image root as below the repository root, with the
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

- `image -- <uv sync options>` syncs with `--locked` and reinstalls every internal
  package, so a persistent uv cache cannot supply a previous build of a same-version
  wheel. The Dockerfile chooses groups and extras; the script chooses the packages. Do
  not pass `--no-sources`: a lock resolved with index sources is not current without
  them.
- `install-wheel` installs the project's own distribution at the version its
  `pyproject.toml` declares, from the wheelhouse only (`--no-index`), into
  `UV_PROJECT_ENVIRONMENT`. Every other repository distribution comes from the lock.
- The script is copied into builder stages only. The runtime stage copies the finished
  environment and never the wheelhouse.
- A Dockerfile with a deny-all ignore file admits `scripts/uv_project.py` explicitly.

A project one level deep can use `/app` itself with the wheelhouse at `/.dist`, which
keeps an editable install of the project valid in the runtime stage; `e2e-tests` does.

## Checks

`make check-packaging` builds the wheelhouse and runs every check. Each is also its own
target. None resolves dependencies, relocks, or contacts a package index; building the
wheelhouse fetches only the build backends each project declares. Every change runs it at
closeout ([plan-closeout requirements](../../openspec/README.md#plan-closeout-requirements)).

| Target | Fails on |
|---|---|
| `check-uv-setup` | a literal `--upgrade-package`, `--reinstall-package`, or `--refresh-package` in a Makefile or Dockerfile; a Makefile recipe running `uv sync` itself; a `reinit` recipe other than the script call by a path that resolves; a project with tests and wheelhouse packages but no `reinit`; a Dockerfile that rewrites a lock, spells a repository distribution's version, installs from the wheelhouse without the script, calls the script where its stage did not copy it, or copies the wheelhouse into the runtime stage |
| `check-locks` | a lock `uv lock --check --offline` rejects; a lock pinning an internal version the tree does not build; a lock whose record of an internal package disagrees with that wheel's metadata (a requirement added or removed, unconditionally or under an extra in use, or a locked version its specifier no longer admits); a version check it cannot evaluate; a repository distribution resolved from an index or from a local registry other than `.dist` |
| `check-python-version` | a `.python-version` other than the root one; a literal `--python` version in a Makefile, shell script, or tool phase configuration; a Makefile running uv without exporting `UV_PYTHON` from the root declaration; a CI job running uv without it, setting it before checkout or under a different `if:` than checkout, or a setup pin of another minor version; a Dockerfile `FROM` naming a Python version, using `${PYTHON_VERSION}` without an `ARG` default before the first `FROM`, or a default other than the declared one |

uv records no section for an empty extra, and no extra on the consumer's dependency edge
either, so `check-locks` derives the extras in use from every place that can request one:
the lock's dependency edges, each locked project's `requires-dist`, and the requirements of
the wheels the lock installs. It compares environment markers only to decide which extra a
requirement belongs to, so a same-version wheel that changes nothing but a marker is not
seen; `make lock` followed by an unchanged tree is the stronger proof. It needs `.dist`
built first, which `check-packaging` does.
