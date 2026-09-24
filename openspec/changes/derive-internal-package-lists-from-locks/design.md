# Design — derive internal package lists from locks

## Context

A rebuilt wheel keeps its version, so `uv sync` keeps whatever copy an environment
already holds unless told to replace it. Every project therefore names its internal
packages when it syncs:

- a Makefile's `reinit` target passes `--upgrade-package X --reinstall-package X`
  for each, and `check_reinit.py` fails when one the lock installs is missing;
- a Dockerfile's builder stage passes `--refresh-package X` for each, so its uv
  cache mount does not serve a stale wheel. Nothing checks these lists.

Found while adding three wheels in `unbacked-listing-publication`: the new wheels had
to be added by hand to three `reinit` targets and two Dockerfiles, and the two
Dockerfile edits were caught by reading, not by any check.

## Decisions

**The lock is the only source.** The packages to refresh are exactly those the
project's `uv.lock` resolves from a local wheel registry: a `registry` source that is
a filesystem path, not a URL. That is the rule `check_reinit.py` enforces today.
Packages taken from a public index, from source (editable or path), and the project
itself are excluded, as they are now. A path rather than a fixed `../.dist` string is
the test because Docker builds rewrite the path to `/.dist` before syncing.

**One script, two output forms.** A new script, `internal_package_flags.py <uv.lock>
--form reinit|refresh` prints the flags on one line. The two forms keep today's
semantics exactly: local `reinit` upgrades and reinstalls; an image build only
refreshes, because it installs into a fresh environment. The script uses only the
standard library (`tomllib`), so it runs in any builder image with Python 3.11 or
later, without a project environment.

**Evaluated when the recipe runs.** Makefiles call it through the recipe's shell
(`$$(python3 …)`), not `$(shell …)` at parse time, so a lock rewritten earlier in the
same `make` invocation is read after the rewrite.

**Dockerfiles copy the script beside `.dist`.** The build context is the repository
root, which is how Dockerfiles copy `.dist` today. The script is copied into the
builder and called after the `sed` that rewrites the registry path.

**The check changes meaning, not name.** Once lists are derived they cannot drift from
the lock, so comparing them is pointless. `make check-reinit` instead fails when a
project whose lock installs internal wheels has a `reinit` target, or a Dockerfile
that copies `.dist`, that does not derive its flags through the script. Keeping the
target's name keeps `AGENTS.md`'s workflow step intact.

## Risks

- **A builder image without Python.** Every current builder stage uses a uv Python
  image; each is confirmed during implementation, and one without Python would need
  the script's output passed in instead.
- **Shell differences.** The call is plain command substitution in `/bin/sh`; no
  bash features.

## Findings recorded, not fixed here

`openspec/specs/deployment-state/spec.md` states the internal wheel contract in a
section after `## Evidence`, outside `## Requirements`, so no delta can modify it.
This change adds its requirement inside `## Requirements`; promotion folds the stray
section into it. `openspec/specs/registry-discovery/spec.md` has the same defect,
recorded by `unbacked-listing-publication`.
