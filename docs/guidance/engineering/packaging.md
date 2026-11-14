---
tags: [engineering, packaging]
---

# Packaging

How a repository's packages get their environments, locks, and images without a list
anyone maintains by hand. Each tool's form of these rules is a file of its own:
[Packaging Python](packaging-python.md), [Packaging with uv](packaging-uv.md),
[Packaging with Hatchling](packaging-hatchling.md), and
[Packaging with Docker](packaging-docker.md).

## Nothing is maintained by hand

Every packaging rule replaces a list someone would otherwise maintain by hand. A
project's manifest declares its own dependencies ([Dependencies](dependencies.md),
"Declare what you import"), and nothing else maintained by hand lists internal
packages: no build script, image definition, or CI workflow names the set of them or
repeats a version a project already declares. Whatever needs that
set derives it from the project's lock when it runs, so no caller lists it
([Packaging with uv](packaging-uv.md), "Refreshing a same-version wheel").

## One declaration of the runtime version

Nothing chooses the runtime version independently. One declaration states it, every
environment and image reads that declaration, and the one copy that cannot read it is
checked against it ([Packaging with uv](packaging-uv.md), "The runtime version reaches
every consumer"; [Packaging with Docker](packaging-docker.md), "One runtime version").

## Internal packages are consumed as built artifacts

Internal distributions are built as artifacts into one store of built packages, and
every project consumes them from there; a project never resolves a sibling through the
sibling's source path. A distribution is *internal* to a project when the project's
lock resolves it from that store. A lock that resolves anything from another local
directory is an error.

## Packaging checks run before a commit

Passing tests prove nothing about the next rebuild: they may have run against an
environment a missing or hand-maintained refresh left stale, and the next environment
built from the locks fails instead. So once the tests covering a piece of work pass,
the packaging checks run, and every failure they report is resolved before the work is
committed.
