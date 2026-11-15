---
tags: [repository, packaging, uv]
---

# The wheelhouse

Where this repository's internal distributions are consumed from, and how a project
reaches them. The build flow it serves is
[`ARCHITECTURE.md`, "Build, packaging, and initialization"](../../development/ARCHITECTURE.md#build-packaging-and-initialization).

## The wheelhouse

The store of built packages internal distributions are consumed from
([`packaging.md`, "Internal packages are consumed as built artifacts"](../engineering/packaging.md#internal-packages-are-consumed-as-built-artifacts))
is the repository wheelhouse, `.dist`, which `make dist` builds; a package is internal to
a project when the project's `uv.lock` resolves it from `.dist`, never through a
`tool.uv.sources` path
([`packaging-uv.md`, "No source path to a sibling"](../engineering/packaging-uv.md#no-source-path-to-a-sibling)),
and `make reinit` refreshes a
project's environment from it without a publish round-trip
([`project-environments.md`](project-environments.md)). A project never declares
the wheelhouse itself: the tools that sync and lock pass it, relative to the project, so
every lock records the same registry path. `make dist` builds the lanes' superset of the
release set `make dist-release` builds, adding the wheels only tests depend on
([`published-packages.md`](published-packages.md)). The publish workflow passes
`--no-sources`, so the only sources a published wheel could record are index pins, such
as the PyTorch CPU index.

`scripts/uv_project.py` derives the internal packages from the lock whenever it runs and
passes each operation the flags a same-version wheel's refresh takes
([`packaging-uv.md`, "Refreshing a same-version wheel"](../engineering/packaging-uv.md#refreshing-a-same-version-wheel)),
so no caller lists them.
