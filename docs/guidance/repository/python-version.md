---
tags: [repository, packaging, python, uv, docker]
---

# One Python version

Where this repository declares its Python version, and how every environment, image,
and CI job reads it. Here a project's manifest is its `pyproject.toml`
([`packaging.md`, "Nothing is maintained by hand"](../engineering/packaging.md#nothing-is-maintained-by-hand)),
and the runtime version's one declaration is the root `.python-version`, the one copy
that cannot read it being a Dockerfile's `ARG PYTHON_VERSION` default
([`packaging.md`, "One declaration of the runtime version"](../engineering/packaging.md#one-declaration-of-the-runtime-version)).

## One Python version

The root `.python-version` declares the version every environment and image uses, and
each consumer reads it explicitly
([`packaging-uv.md`, "The runtime version reaches every consumer"](../engineering/packaging-uv.md#the-runtime-version-reaches-every-consumer);
[`packaging-docker.md`, "One runtime version"](../engineering/packaging-docker.md#one-runtime-version)):

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

A change of the version edits `.python-version` and the Dockerfile defaults together,
and `make check-python-version` holds every consumer to the declaration. The `market`
binary's build image is pinned by digest, so a Python bump also pins a new digest for it
([`images.md`, "The `market` binary"](images.md#the-market-binary)).

## Build requirements

`build-constraints.txt`, beside `.python-version`, pins every wheel's build requirements
exactly. The root Makefile exports it as `UV_BUILD_CONSTRAINT`, as it exports
`UV_PYTHON`, and so does every subproject Makefile that runs `uv build`, since each also
runs on its own. The build backend stamps its version into every wheel, so moving a pin
changes every wheel's bytes and bumps every published distribution
([`package-versions.md`, "A version changes when its contents change"](package-versions.md#a-version-changes-when-its-contents-change)).
`make check-build-requirements` holds it ([`packaging-checks.md`](packaging-checks.md#checks)).
