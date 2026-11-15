---
tags: [repository, versioning]
---

# Package versions

How this repository's packages and versioned contracts are versioned, as
[`versioning.md`](../engineering/versioning.md) describes. Why the pre-1.0 rules suit
this repository is
[`ARCHITECTURE.md`, "Operators"](../../development/ARCHITECTURE.md#operators).

## Before 1.0.0

Sites and storefronts are deployed and upgraded together by one business, so until
the first major release a package's incompatible change takes a minor version, as
[`versioning.md`, "Before 1.0.0"](../engineering/versioning.md#before-100)
allows, and a contract that carries its own version is versioned rather than changed
in place; the rule lapses at 1.0.0. Before a package reaches 1.0.0, the meaning of a
configuration key it reads may change incompatibly in a minor release too.

## Versioning policy

This repository's packages follow
[`versioning.md`](../engineering/versioning.md), and `make
check-version-bumps` holds its one bump per change against the branch the change
merges into. A `VersionedEnvelope`'s `(kind, schema_version)` is a versioned
contract. Dependencies
between its packages declare lower bounds in `pyproject.toml`
([`versioning-python.md`](../engineering/versioning-python.md)).
