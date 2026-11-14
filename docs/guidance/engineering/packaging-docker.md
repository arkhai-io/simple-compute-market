---
tags: [engineering, packaging, docker]
---

# Packaging with Docker

The Docker forms of the packaging rules ([Packaging](packaging.md)): the runtime
version an image builds on, what an image installs, its stages, and its ignore file.

## One runtime version

A Dockerfile declares the runtime version as an `ARG` with the declared version as its
default, before its first `FROM`, and uses it in each `FROM`:

```dockerfile
ARG RUNTIME_VERSION=<declared>
FROM example/runtime:${RUNTIME_VERSION} AS builder
```

That default is the one copy of the version that cannot read the declaration, so it is
checked against it ([Packaging](packaging.md), "One declaration of the runtime
version").

## An image installs the committed lock

An image installs the committed lock exactly as it is, and never relocks.

## Builder and runtime stages

The build tooling is copied into builder stages only. The runtime stage copies the
finished environment and never the store of built packages.

## A Dockerfile's own ignore file

An ignore file beside a Dockerfile (`<name>.dockerignore`) replaces the root
`.dockerignore` for that image, so none of the root's exclusions apply there. One that
admits a tree whole states that tree's exclusions itself: a checkout's environments,
caches, logs, and retry files, and what the tree's own `.gitignore` ignores, such as
an operator's credentials, keys, and variable files and an infrastructure tool's state.
