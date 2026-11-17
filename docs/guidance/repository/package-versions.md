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

## Compatibility is owed to what a release has shipped

A decision made on the development branch and changed again before any release ships
it affects no one, so revising it needs no compatibility path, migration or
deprecation. A change to anything a release has shipped — its API, a wire format, a
configuration key or a hint it reads — is judged under the rules above, so a key a
release accepted keeps the meaning it had, or loses it only with the bump an
incompatible change takes.

Migration and backwards compatibility are engineered only for what has been deployed,
as
[`versioning.md`, "Compatibility is owed to what has been deployed"](../engineering/versioning.md#compatibility-is-owed-to-what-has-been-deployed)
states, and this repository's record of what has been deployed is its release tags. A
marketplace release is tagged `marketplace-v<semver>` only once production runs it, on
`releases/<semver>` with its bill of materials
([the release handbook, "The release"](../../release-handbook.md#the-release);
[`published-packages.md`, "The release record"](published-packages.md#the-release-record));
the tags through `marketplace-v0.3.0` predate that record and sit on `main`. What the
newest tag's release carried is deployed. A step fetches the release tags and reads
them with `git log --tags --no-walk --decorate`, and a design that leaves out a
migration or compatibility path names the tag it read. A form no tagged release
carried — a kind of deal, a record, a key's use — owes no migration path, compatibility
shim or recovery machinery.

## A version changes when its contents change

A contributor bumps a package's version where its contents change, and merges; the
release procedure decides when those bytes ship
([the release handbook](../../release-handbook.md)). A wheel or the chart whose bytes
differ from what an earlier marketplace release recorded at the same version is refused.
The chart's version follows its own semver and changes only when its packaged files do.

Every wheel's build requirements are pinned in `build-constraints.txt`
([`python-version.md`, "Build requirements"](python-version.md#build-requirements)).
The build backend stamps its version into every wheel, so moving a pin changes every
wheel's bytes: a pin move bumps every declared distribution's patch version once, and
the version check enforces that with no special handling.

### The version check

`make check-release-versions` holds every (component, version) pair an earlier
marketplace release recorded to the content identity that record gives it: a wheel's
SHA-256, and the chart's content digest. It reads the bill of materials at every
`marketplace-v*` tag carrying one, except the tag being checked, and refuses a layout
it does not know. A refusal names the component and the release that recorded it, and
means "bump the version"; the check never chooses one. With no earlier record it passes
and says so.

Its subject depends on when it runs:

- **In a load**, the wheelhouse the load built and the chart packaged with the Helm
  `.helm-version` names, which the check refuses to run without.
- **At the cut** (`make check-release-versions TAG=marketplace-v<semver>`), that tag's
  own bill of materials, with no build.

It compares the release tags the checkout holds, and stays offline: at the cut it needs
git alone, and no remote name is common to every checkout. A checkout that has not
fetched since the last cut, or a shallow or single-branch clone, holds fewer records
than were published, and the check passes against what it holds; the release handbook
says how the owner fetches first.

The chart's content digest is computed from a package, never from the source directory,
because Helm rewrites every `Chart.yaml` when packaging:

1. list the package's regular files by archive path, sorted bytewise;
2. for each, write `<sha256 hex of contents>  <archive path>\n`, with two spaces;
3. take the lowercase SHA-256 hex of that text.

A package storing a path more than once is refused, and so is one storing a file Git
ignores under `helm/`: `helm package` reads whatever the directory holds, and
`helm dependency update` leaves a time-stamped `Chart.lock` and subchart archives there.
`helm/.helmignore` names those files. It also names every tracked file under `helm/`
that is not the chart, so none reaches the package: the Makefiles and scripts that
deploy and test it, the release values a deployment layers on it
(`local-values.yaml`, `bare-metal-release-values.yaml`), the validation's capacity
record, and the render tests and their fixtures. An edit to one of those takes no chart
version bump; an edit to anything the package stores — a template, a Helm test pod's
template under `templates/tests/`, a values or schema file, a subchart's files — does. A
file added under `helm/` is packaged unless `.helmignore` names it, and so is an untracked
file Git does not ignore, as an edit of the tree is. A Helm bump edits `.helm-version`
and `tests.yml`'s `azure/setup-helm` version together; a test holds them equal.

The check guards the versions recorded releases name. It is not a complete guard
against PyPI, whose history includes versions no record names. The complete guard is
the deployment's PyPI read
([the release handbook, "The deployment's part"](../../release-handbook.md#the-deployments-part));
this repository reads no package registry, so its checks stay offline and
deterministic.
