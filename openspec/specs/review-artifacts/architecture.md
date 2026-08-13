# Review Artifacts Architecture

The [normative contract](spec.md) defines the portable review dependency bundle. This document explains why the artifact is dependency-only, why metadata normalization happens on copies, and why the workflow targets one Python ABI at a time.

## Role of the artifact

A review wheelhouse transfers the dependency state required to validate a change on another host. It is not a source snapshot, test runner, or proof that tests passed. The matching repository checkout remains the authority for source and tests, while the artifact supplies:

- current repository-built wheels;
- external locked artifacts in a uv cache;
- portable copies of selected project manifests and lockfiles;
- the interpreter version and recreation instructions.

Separating dependency transfer from test execution is essential when the reason for requesting the artifact is that the producing checkout currently has failing tests.

## Scope model

`REVIEW_PROJECTS` names the Python project environments whose locked development dependencies are needed for a review. Scope is project-based rather than file-based because uv resolves from project manifests and lockfiles.

The bundle records the selected paths so the consumer can recreate each environment independently. It does not infer that every repository package or test suite must be included.

## Clean repository wheel input

Repository-owned dependencies are consumed as wheels from `.dist`, matching the repository's ordinary package-boundary discipline. The make target cleans and rebuilds `.dist` before packaging so the wheelhouse represents one current version of each distribution rather than whatever historical artifacts happen to be present on the producer's machine.

## One interpreter ABI

Compiled dependencies such as Pydantic Core and SQLAlchemy are interpreter- and platform-sensitive. A cache populated under CPython 3.14 cannot be assumed to recreate a CPython 3.13 environment. The workflow therefore selects one explicit `REVIEW_PYTHON` version and uses it for both dependency resolution and helper scripts.

Bundling every supported interpreter would multiply artifact size and is outside this capability's purpose. A different interpreter requires a separately generated artifact.

## Copy-only metadata normalization

Local development lockfiles may legitimately contain absolute `.dist` registry locations or editable/directory references to sibling repository packages. Those paths describe the producer's checkout and are not portable.

The workflow copies `pyproject.toml` and `uv.lock` for each selected project, then normalizes only those copies:

1. copied `[tool.uv.sources]` overrides are removed;
2. repository `.dist` registry references become archive-relative wheelhouse references;
3. non-root editable or directory package records become exact wheel-backed records;
4. the selected project may remain local because recreation uses `--no-install-project`.

The source checkout is never rewritten as a side effect of producing a review artifact.

## Clean cache population

Copying an arbitrary existing uv cache is insufficient. An already-populated `.venv` can allow `uv sync` to succeed without downloading every artifact needed to recreate the environment elsewhere.

Each selected project therefore synchronizes into a fresh temporary environment while sharing the bundle cache. This forces the cache to contain the dependency closure needed by a clean consumer without executing tests.

## Dependency-only recreation

The project copies in the artifact contain manifests and lockfiles, not source packages. Their purpose is dependency resolution, so the documented command includes `--no-install-project`. After dependency recreation, validation runs against the matching repository checkout using its normal Makefile targets.

This avoids duplicating source code in the artifact and avoids isolated build-backend failures caused by trying to install a manifest-only project copy.

## Tar rather than ZIP

uv's cache uses links between index entries and extracted package content. ZIP archives do not preserve that structure and can materialize the same cache contents twice. Tar-based packaging preserves the relevant links and keeps the compressed artifact substantially smaller.

A flat third-party wheel directory could be another portable representation, but the current design retains uv's native cache so locked synchronization can recreate full development environments without inventing a second dependency-resolution format.

## Failure behavior

Packaging fails early when:

- no projects are selected;
- a selected project lacks its manifest or lockfile;
- `.dist` was not prepared through the make target;
- a repository-local package cannot be matched to exactly one bundled wheel.

These checks favor an explicit unusable-artifact failure over producing a bundle that later reaches outside the archive or resolves an ambiguous wheel.

## Related contracts

- [Testing and compatibility](../test-compatibility/spec.md)
- [Repository engineering guidance](../../../AGENTS.md)
- [Repository architecture](../../../docs/development/ARCHITECTURE.md)
