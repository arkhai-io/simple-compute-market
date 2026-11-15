---
tags: [repository, packaging, docker]
---

# Images

How this repository's images install the committed lock and its internal wheels, as
[`packaging-docker.md`](../engineering/packaging-docker.md) gives it.

## Images

To install the committed lock
([`packaging-docker.md`, "An image installs the committed lock"](../engineering/packaging-docker.md#an-image-installs-the-committed-lock)),
whose wheelhouse path is relative, an image copies the project's
`pyproject.toml` and `uv.lock` to the same depth below an image root as below the repository root, with the
wheelhouse at `<image root>/.dist`. uv will not resolve a path above `/`, so the depth
must match:

```dockerfile
ARG WHEELHOUSE_DIGEST
COPY .dist/ /repo/.dist/
COPY scripts/uv_project.py /repo/scripts/uv_project.py
COPY domains/vms/storefront/pyproject.toml domains/vms/storefront/uv.lock /repo/domains/vms/storefront/
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    python3 /repo/scripts/uv_project.py image --project /repo/domains/vms/storefront -- --no-dev --no-install-project && \
    python3 /repo/scripts/uv_project.py install-wheel --project /repo/domains/vms/storefront
```

- `image -- <uv sync options>` runs the sync an image owes
  ([`packaging-uv.md`, "The sync an image runs"](../engineering/packaging-uv.md#the-sync-an-image-runs)).
  The Dockerfile chooses groups and extras; the script chooses the packages.
- `install-wheel` installs the project's own distribution at the version its
  `pyproject.toml` declares, from the wheelhouse only (`--no-index`), into
  `UV_PROJECT_ENVIRONMENT`. Every other repository distribution comes from the lock.
- The script is copied into builder stages only, and the wheelhouse never reaches the
  runtime stage
  ([`packaging-docker.md`, "Builder and runtime stages"](../engineering/packaging-docker.md#builder-and-runtime-stages)),
  so a runtime image never resolves editable sibling source.
- A Dockerfile with a deny-all ignore file admits `scripts/uv_project.py` explicitly.
- The provisioning service's `Dockerfile.dockerignore` admits both IaC trees it
  copies whole, so it states their exclusions itself
  ([`packaging-docker.md`, "A Dockerfile's own ignore file"](../engineering/packaging-docker.md#a-dockerfiles-own-ignore-file)),
  Ansible's logs and retry files, an operator's inventories, and Terraform's state and
  variables among them.
- An image built from the wheelhouse records which wheelhouse it was built from. Its
  build target runs `scripts/wheelhouse_digest.py` before `docker build` and passes the
  digest as `WHEELHOUSE_DIGEST`. The Dockerfile declares the argument before copying
  `.dist/` in its builder stage, so the install's cache keys on it, and records it as
  the label `org.arkhai.wheelhouse-digest` in its final stage, before the cross-stage
  copies. The digest is a dirhash of the declared wheels in `.dist` and refuses a
  missing one, naming `make dist`. A release candidate's load uploads nothing unless
  every labelled image carries the digest of the wheelhouse it stores
  ([the release handbook, "Loading a release candidate"](../../release-handbook.md#loading-a-release-candidate)).

A project one level deep can use `/app` itself with the wheelhouse at `/.dist`, which
keeps an editable install of the project valid in the runtime stage; `e2e-tests` does.
A deeper project whose wheel no image installs from the wheelhouse keeps its editable
install the same way at its mirrored path: `tools/payments-lane-double`'s image installs
the project editable at `/repo/tools/payments-lane-double` from its source, skipping
`install-wheel`, and its runtime stage copies the environment and `src/` to that same
path.

## The `market` binary

The release's `market` binary is built like an image and exported as a file.
`core/buyer/market-binary/` is a locked virtual project (`[tool.uv] package = false`)
depending on the buyer CLI and every declared buyer domain, with PyInstaller in its
`freeze` group and linux/amd64 as its only environment. Its Dockerfile, beside it,
builds on `ghcr.io/astral-sh/uv:python<version>-bookworm-slim` pinned by digest, refuses
an image whose Python is not the declared one, installs the committed lock through
`uv_project.py image` with no `install-wheel`, since a virtual project builds no wheel,
freezes the CLI's entry point, runs `market plugins` installed and frozen and requires
the same output from both, and exports the binary from a `scratch` stage.
`make build-market-binary` derives its name, output path, entry point and PyInstaller
options from the declaration (`scripts/market_binary.py`), so neither the Makefile nor
the Dockerfile names a domain. A Python bump pins a new digest; the build refuses a
stale one. Pinning the image and locking the environment fix the binary's inputs, not
its bytes: it is identified by the SHA-256 of the stored file.
