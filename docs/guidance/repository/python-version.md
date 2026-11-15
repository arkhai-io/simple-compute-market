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

To change the version, edit `.python-version` and the Dockerfile defaults, then run
`make check-python-version`.
