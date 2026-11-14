---
tags: [engineering, packaging, uv]
---

# Packaging with uv

The uv forms of the packaging rules ([Packaging](packaging.md)): editable installs,
refreshing a rebuilt wheel, the Python version, locks, and the sync an image runs.

## Every project installs itself editable

Every project environment installs its own project editable, so an edited module is
live without a sync. Nothing disables editable installs, and no project declares
`cache-keys`: both serve only a package whose directory does not match its import
path, which the project layout rules out ([Packaging Python](packaging-python.md)). A
virtual project (`[tool.uv] package = false`) builds no wheel and is outside this
rule.

## No source path to a sibling

A project consumes a sibling as a built wheel, never through a `[tool.uv.sources]`
entry naming the sibling's path ([Packaging](packaging.md), "Internal packages are
consumed as built artifacts").

## Refreshing a same-version wheel

A rebuilt wheel keeps its version, and uv keeps what it already has for a version it
has seen. Two flags undo that, and both are needed:

| Flag | Effect on a same-version wheel |
|---|---|
| `--reinstall-package` | replaces the installed code |
| `--upgrade-package` | re-reads the wheel's metadata and rewrites the dependencies the lock records for it |

Reinstalling alone installs new code without a dependency the rebuilt wheel gained,
and `uv sync --locked` succeeds in that state. Whatever passes the flags derives the
internal packages from the project's lock when it runs, so no caller lists them
([Packaging](packaging.md), "Nothing is maintained by hand").

## The runtime version reaches every consumer

uv does not read `.python-version` from a nested project, so each consumer reads the
one declaration explicitly ([Packaging](packaging.md), "One declaration of the runtime
version"):

- A command that creates an environment passes it as `--python`.
- Every Makefile that runs uv exports `UV_PYTHON` read from the declaration, by a path
  relative to the Makefile. uv honours `UV_PYTHON` wherever it would honour
  `--python`, so a target that creates an environment by another route still creates
  it on the declared version.
- Every CI job that runs uv sets `UV_PYTHON` from the declaration in a step after
  checkout that runs under the same condition as checkout. A step that reads the file
  where checkout did not run fails; one that skips where checkout ran leaves uv on the
  runner's default.

## Relock against fresh artifacts

After editing a project's dependencies or bumping an internal version, relock the
project against freshly built wheels. The relock upgrades every internal package and
every other distribution of the repository the lock names, so one that has drifted to
a package index returns to the store of built wheels. It relocks unconditionally,
because `uv lock --check` cannot see a same-version wheel's changed requirements;
relocking a current project changes nothing. A lock is current only when it agrees
with its project, with the metadata of the wheels the tree builds, and with that
store, every distribution of the repository resolved from there.

## Locks are written by a stated minimum uv

uv releases write `uv.lock` differently, and whenever one rewrites a lock it writes its
own lock revision: a newer uv raises an older one's lock, and an older uv lowers a
newer one's back, as surely. `uv lock --check` asks only whether a lock satisfies its
project, so it passes a lock at any revision. A repository therefore states a minimum
uv, the first release that writes the revision every committed lock carries, and holds
the locks to it twice:

- The commands that relock or refresh an environment refuse an older uv before running
  it, naming both versions.
- A check fails on a lock carrying any other revision, naming the lock and both
  revisions, so a rewrite by any release and any command is seen before it lands.

The minimum is not an exact pin: a newer uv still runs, and the revision check stops
its rewrite landing unseen.

## The sync an image runs

An image syncs with `uv sync --locked` and reinstalls every internal package, so a
persistent uv cache cannot supply a previous build of a same-version wheel. It never
passes `--no-sources`: a lock resolved with index sources is not current without them.
The image's own rules are [Packaging with Docker](packaging-docker.md).
