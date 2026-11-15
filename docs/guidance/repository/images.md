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

A project one level deep can use `/app` itself with the wheelhouse at `/.dist`, which
keeps an editable install of the project valid in the runtime stage; `e2e-tests` does.
A deeper project whose wheel no image installs from the wheelhouse keeps its editable
install the same way at its mirrored path: `tools/payments-lane-double`'s image installs
the project editable at `/repo/tools/payments-lane-double` from its source, skipping
`install-wheel`, and its runtime stage copies the environment and `src/` to that same
path.
