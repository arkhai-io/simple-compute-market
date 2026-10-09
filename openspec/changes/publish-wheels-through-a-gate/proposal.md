## Why

This repository has two publication paths and they share nothing.

`push-runtime-artifacts` sends three images, three client wheels, charts, and
the CLI to Artifact Registry. It is run by a human and its artifacts are
promoted between environments by copying.

`publish-pypi.yml` sends twenty-eight distributions to public PyPI on every push
to `main`, versioned by whatever each `pyproject.toml` says, with no gate, no
prior deployment, and no promotion. Python source frequently changes without a
corresponding semver bump, so a merge can publish a distribution whose version
already describes different code — and PyPI is write-once, so the mistake is
permanent and correctable only by another version.

That path already published a broken artifact. `arkhai-kit-hosted-settlement`
0.1.4 is live on PyPI declaring a dependency on
`arkhai-hosted-settlement-client==0.4.2`, which PyPI does not carry. Installing
it fails for everyone outside this repository, and has since it was published,
because inside the repository `.dist` always had the wheel.

Promotion is eventually owned by a pipeline maintained outside this repository,
which does not exist yet. Waiting for it means continuing to publish ungated;
building a parallel permanent mechanism here means building something destined
for deletion. The available move is to isolate the concern: put
publication behind a deliberate step in this repository, shaped like the
promotion model that will replace it.

## What Changes

- **Automated publication to PyPI stops.** Merging to `main` no longer
  publishes to a public index.
- Merge to `main` publishes to the development Artifact Registry instead, via
  `push-runtime-artifacts`, and that path carries all twenty-eight
  distributions rather than three.
- The set of distributions published is read from the release inventory. The
  hardcoded list in `push-wheels` and the `packages.json` matrix in
  `publish-pypi.yml` are both replaced by it; neither survives as a second
  enumeration.
- All twenty-eight are published, not the three the registry path names today.
  The kit is composable functionality other teams are meant to build
  marketplaces from, so importing a piece of it individually is the point; a
  distribution that exists and is unpublished cannot be imported at all.
- A promotion step, human-invoked, copies artifacts from Artifact Registry to
  PyPI. It never rebuilds. Before uploading anything it compares every
  distribution's bytes against what PyPI already holds, and **fails the whole
  promotion** if any version exists on PyPI with different content. A version
  already present with identical bytes is skipped, not an error.
- The promotion step lives in a section of this repository documented as
  conditional on no promotion pipeline consuming these artifacts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: publication to a public index is a deliberate,
  byte-verified promotion of artifacts already published to a development
  registry, rather than a side effect of merging. The set of published
  distributions is derived from the release inventory rather than enumerated
  per publication path.

## Dependencies and Related Changes

- Requires the cross-repository release inventory format, which is defined
  outside this repository. Until it exists, the single package list can be a
  plain manifest both paths read; the inventory replaces it without reopening
  the decision.
- Requires a writer identity for CI against the development registry, granted
  outside this repository.
- Follows `resolve-hosted-client-from-an-index`, which is what makes the
  published graph installable from a public index at all.
- Anticipated by `configure-pypi-trusted-publishing`, which this change's
  byte-verification and inventory-derived matrix subsume in part. Reconcile the
  two before either is archived.
- Superseded in full by the promotion pipeline that will consume these
  artifacts. The condition for its removal is recorded in `design.md`.

## Non-Goals

- Do not build a durable promotion system here. This is an interim mechanism
  with a stated removal condition.
- Do not implement automatic deployment or triggered promotion. Promotion is
  human-invoked, which is what lets it coexist with a harness runtime whose
  guarantee depends on no trigger mechanism existing.
- Do not rebuild artifacts at promotion. Bytes are copied.
- Do not attempt to clobber or delete on PyPI. Neither is possible and neither
  is wanted; a conflict is a failure, not something to overwrite.
- Do not change any distribution's version as part of promotion. Wheel versions
  are fixed at build time and the gate may only accept or reject them.
- Do not add a semver-bump enforcement mechanism. The absence of one is why
  automated publication stops; supplying one is separate work.

## Impact

Touches `push-wheels` and `push-runtime-artifacts` in the root `Makefile`, a new
promotion script under `scripts/`, `.github/workflows/publish-pypi.yml`
(publication removed), a merge-to-`main` workflow publishing to Artifact
Registry, and `docs/development/RELEASING.md`.

**Contributor-workflow break:** merging no longer publishes to PyPI. Anyone
depending on that behaviour must invoke promotion deliberately.

**Externally visible break already present:** `arkhai-kit-hosted-settlement`
0.1.4 on PyPI is uninstallable and cannot be corrected in place. It requires a
version bump once its dependency is publicly resolvable, and that is a
consequence of this work rather than a task within it.
