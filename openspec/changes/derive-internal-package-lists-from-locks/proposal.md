## Why

Every project that installs internal wheels from `.dist` lists them by hand, twice
over: once in its Makefile's `reinit` target (`--upgrade-package X
--reinstall-package X`) and, for projects with an image, again in the Dockerfile's
`uv sync` (`--refresh-package X`). There are 34 `reinit` targets and 7 Dockerfiles
with such lists. `make check-reinit` verifies the Makefile lists against each
project's `uv.lock`; nothing verifies the Dockerfile lists. Adding one internal
wheel means editing every list that should contain it, and a Dockerfile list that
misses one keeps serving a stale cached copy of a wheel whose version did not change.

Both lists are fully determined by the lock: they are exactly the packages the lock
resolves from a local wheel registry. The lists can be derived instead of maintained.

## What Changes

- Add one script that reads a `uv.lock` and prints the flags for its internal
  packages, in either form: `reinit` (`--upgrade-package X --reinstall-package X`)
  or `refresh` (`--refresh-package X`). Its selection rule is the one
  `check_reinit.py` already enforces.
- Every `reinit` target calls the script instead of listing packages.
- Every Dockerfile that installs from `.dist` copies the script into its builder
  and calls it the same way, after the step that rewrites the lock's registry path.
- `make check-reinit` stops comparing lists, which can no longer drift, and checks
  instead that every project whose lock installs internal wheels derives its flags
  through the script, in its Makefile and, where it has one, its Dockerfile.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: the internal packages a project refreshes are derived from its
  lock, in local development and in image builds alike.

## Non-Goals

- Changing which packages are internal, or how they are built into `.dist`.
- Changing any `uv sync` flag other than the package lists.
- Publication to PyPI.

## Impact

- `scripts/` gains the flag script; `scripts/check_reinit.py` is rewritten.
- The 34 Makefiles with a `reinit` target and the 7 Dockerfiles with a
  `--refresh-package` list.
- `AGENTS.md` (the `check-reinit` rule), `docs/development/ARCHITECTURE.md`
  (build, packaging, and initialization), and `openspec/specs/deployment-state`.

## Dependencies

None. Not started while `unbacked-listing-publication` is open, because that change
edits several of the same Makefiles and Dockerfiles.
