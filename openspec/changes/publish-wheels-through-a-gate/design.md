## Context

Before this design, a release was whatever CI produced. PyPI and npm received
whatever a push to `main` built, and a `marketplace-v*` tag made CI build a
wheelhouse, a manifest, provenance and a ghcr image. None of it was what a deployment
validated. Images are not reproducible, so the ghcr image a tag produced was never
the image production ran. A version pushed to PyPI before validation is permanent.

The deployment released marketplace v0.3.0 another way. It loaded the tag's artifacts
into its development registry with this repository's publish targets, validated
them, copied them by digest through pre-production and production, and published to
PyPI and ghcr from production's copies. This redesign makes that the release, and
gives this repository the half it owns.

The change was first designed as an interim gate: merges would publish to the
development registry and a promotion script here would copy to PyPI until an external
promotion existed. That promotion now exists. Sections 3–6 of `tasks.md` belonged to
the interim design and are withdrawn. The decisions it got right (one enumeration,
copy without rebuilding, a version fixed at build time) carry forward below.

## Goals / Non-Goals

**Goals:**
- Nothing reaches a public channel except bytes a deployment validated.
- A release names exactly what was validated, in a record anyone can read.
- One declaration of what a release comprises.
- A version that changed meaning is caught before anything ships.
- No release-specific facts are written by hand in more than one place.

**Non-Goals:**
- Promotion, deployment or publication tooling in this repository.
- Trusting a development tag.
- Reproducible images.
- Enforcing semver beyond "changed contents need a changed version".

## The release, from this repository's side

1. **Change.** Work lands on `dev` and then `main`. CI builds and tests; it publishes
   nothing.
2. **Candidate.** After a merge, `main`'s commit X is loaded into a development
   registry from a clean checkout of X, with `make check-release-versions` first and
   then `make push-runtime-artifacts`. The deployment's operator runs this, usually
   through an agent session.
3. **Validation and promotion.** The deployment validates X. It records the release's
   bill of materials from what actually ran, promotes it to pre-production and
   production, and deploys it. None of this is this repository's.
4. **Cut.** Once production runs the release, `releases/<semver>` is cut at X. One
   commit adds the bill of materials, and that commit is tagged
   `marketplace-v<semver>`.
5. **Publication.** PyPI, npm, ghcr, and the GitHub release (with the `market` binary
   and the bill of materials) receive the promoted artifacts. The operator does this,
   not CI.

A fault found at step 3 is fixed on `main`, and the next commit becomes the
candidate. A candidate that fails before production gets no branch, no tag and no
public artifact. A failed release does not appear in the record.

## Decisions

### D1. CI publishes nothing

Every workflow that uploads is deleted: `publish-pypi.yml`, `publish-npm.yml`,
`release.yml` and `release-cli.yml`. CI keeps building and testing. That includes
building the wheelhouse and resolving every declared distribution against it, which
was the one useful thing the publishing workflow checked before it uploaded.

A trusted-publishing workflow kept "only to create a new PyPI project" was
considered and rejected. The operator publishes with their own credentials, and a
project first uploaded that way is moved into the organization by an owner. Keeping a
workflow for one rare step would keep a publishing path alive for nothing.

A tag-triggered workflow that publishes the promoted bytes was also considered. It
would need either read access to production's registry from GitHub, or a rebuild
checked against the bill of materials. It is deferred, not rejected. If it returns, it
publishes promoted bytes or nothing, and the cut stays a human act.

**Alternative rejected: merge to `main` publishes to the development registry.** That
was this change's interim design (former D1). Development registries are scratch:
developers push uncommitted builds to them to test on a cluster. A merge-triggered
push would be one writer among many, guaranteeing nothing about what a tag holds when
validation runs.

### D2. The revision names a candidate; the semver names a release

A candidate is a `main` commit. Its images are `<service>-<rev>`, its CLI is stored
under `<rev>`, and its wheels and chart carry their own versions. The release's
semver does not exist until the candidate is promoted. Promotion aliases each image
as `<service>-<semver>` on the same digest and binds the set in the bill of materials.

This is why a merge cannot be a release. At merge time the semver is unassigned, and
whether X will pass is unknown. It is also why the release branch is cut last. Cut
before validation, it would need rebasing every time validation found a fault.

### D3. The chart names no release

A chart's bytes include its version and its default values. Chart defaults that named
a release's images would cause two failures. The chart built at the cut would differ
from the chart the deployment validated. And two releases with an unchanged chart
would need two chart versions, coupling the chart's version to the product's.

So the chart carries no release facts:
- **Version.** `version` follows the chart's own semver and changes only when the
  chart does.
- **Images.** The default values keep the bare development tags, so development
  workflows need no edits. A deployment names its images in its own values.
- **appVersion.** It has no meaning here and is removed, so it cannot become a third
  version number that drifts.

The bill of materials records which chart version a release uses. One chart version
can then appear in many releases.

### D4. One declaration of what a release comprises

`manifests/published-distributions.json` becomes `manifests/release-components.json`.
It is renamed because it no longer lists only distributions. It declares:
- **distributions:** each one's key, source path and distribution name, as today,
  plus `public`, whether it goes to PyPI. The demo API and the lane doubles' contract
  are built and loaded but not public. Today the deployment keeps that exclusion as a
  second list.
- **images:** each service image's published name and the local image its build
  writes.
- **chart:** the chart's directory.
- **binaries:** the `market` CLI and the target that builds it.
- **npm:** the middleware package's directory.

The publish targets read the declaration, and so do the deployment's bill-of-materials
builder and promotion. The Makefile still builds everything; the declaration says
what is published, not how to build it. A check fails on any second list of
components in a workflow or publish target (the existing single-enumeration check,
widened).

`push-images` reads the declaration, which fixes its omission of the bare-metal
storefront. That storefront's build gains the local `-<rev>` tag its siblings
already write.

`push-images` keeps pushing the bare `arkhai:<service>` tags beside the revision tags.
Shared development releases follow those tags, and that is how a developer's build
reaches the development cluster. No release step reads a bare tag; promotion copies
by digest and writes none.

### D5. A release is recorded by a tagged commit on its release branch

At the cut, `releases/<semver>` is created at the candidate's commit X. A single commit
adds `manifests/release-bom.cdx.json`, and that commit is tagged `marketplace-v<semver>`.

- **Why a branch.** The repository is public, so the record sits beside the source it
  describes, readable by every consumer.
- **Why one commit.** Hotfixes that should carry forward land on `main` and ship in
  the next release, so a release branch never grows past its record. The tag marks
  the record, and the record names X as its source revision.
- **Why the deployment builds it.** Only the deployment knows which image digests
  passed validation. It reads them from what its validated environments ran, so the
  bill of materials is built there and committed here.
- **What it contains.** Content identities only:
  - each component's name and version;
  - its content digest;
  - its source revision;
  - for the chart, the git tree id of its directory at X.

  It never holds a registry host, project or path. Those belong to the deployment,
  and a public record that named them would leak them.
- **Its format.** CycloneDX. The format is defined with the deployment's release
  inventory; this repository relies only on the fields above.

The release branch and tag are made only after production runs the release. Public
channels are published only after the cut. The irreversible steps (a public tag, a
PyPI version, an npm version) therefore come last. A release that fails earlier can
be destroyed entirely by the deployment, and nothing public refers to it.

### D6. A version must change when its contents change

`make check-release-versions` reads the bill of materials at the latest
`marketplace-v*` tag and compares it with the candidate:

- **Wheels.** A wheel whose version equals the previous release's but whose SHA-256
  differs is refused. Wheels build reproducibly (the build backend fixes timestamps),
  so equal source gives equal bytes, and any difference is a real change.
- **The chart.** If `helm/Chart.yaml`'s version equals the previous release's but the
  chart directory's git tree id differs, it is refused. `helm package` is not
  byte-reproducible, so the tree id stands in for content.

It runs before a candidate is loaded and again at the cut, and needs only git and the
wheelhouse. A refusal means "bump the version". The check never chooses a version
itself.

This is the version guard this change originally left out of scope, because nothing
recorded what the previous release contained. The bill of materials now records it.

### D7. A product version is distinct from a distribution version

Carried forward from the interim design. A wheel's version is inside the wheel and
cannot be relabelled without a rebuild, which would change its digest. Wheels,
binaries and charts are promoted at the version they were built with. Images are
aliased to the product version, because an image's tag is outside it. The bill of
materials binds the product version to the set.

### D8. Public channels receive promoted bytes, all or nothing

Carried forward, restated for an external promoter. Bytes reach PyPI and npm
unchanged from what was promoted. Before uploading anything, the publisher checks
every distribution against the index. If any version already holds different bytes,
the whole publication fails before the first upload. The publisher never replaces or
deletes a version.

With D6 in place this refusal should never fire, since a changed wheel cannot keep its
version through the cut. It remains the last line of defence.

PyPI receives wheels only. A source distribution is not built at the cut, so there is
nothing promoted to copy. This resolves the interim design's open sdist question.

### D9. The buyer CLI ships as the promoted binary and from PyPI

The curl installer is deleted. It built the CLI from a source tarball, which bypassed
the released wheels, and it has been broken since a marketplace release became
GitHub's latest. A customer installs the CLI one of two ways:
- **From PyPI,** `uv tool install arkhai-core-buyer --with arkhai-vms-buyer`, pinned to
  the versions the release notes give. This works on every platform.
- **As the release's `market` binary,** downloaded from its GitHub release and checked
  against the SHA-256 in the bill of materials. The binary is a single-file build made
  when the candidate is loaded, so it runs on linux x86_64 only. Other platforms use
  PyPI.

## Risks / Trade-offs

- **A developer push lands in the development registry during validation.** The
  deployment detects this, not this repository: its bill-of-materials builder refuses
  when the running digests disagree with X's revision tags. The candidate is reloaded.
- **A change that only adds tests inside a chart directory forces a chart version
  bump.** The tree id cannot tell tests from templates. Accepted: a version bump is
  cheap, and a missed change is not.
- **The binary is linux x86_64 only.** Accepted for now. PyPI covers every platform.
- **The npm package cannot be loaded into a development registry until one serves
  npm.** Until then it is built and validated, but promotion has nothing to copy.
  Tracked as an external blocker in `tasks.md`.
- **The release is published after production runs it.** For a short while production
  serves a release whose wheels are not yet on PyPI. Nothing in production installs
  from PyPI.

## Open Questions

None. The bill-of-materials fields this repository reads are fixed in D5. The rest of
the format is the deployment's.

## Permanent Documentation Promotion

- **`openspec/specs/deployment-state/spec.md`** (via the spec delta at archive): the
  requirements in this change's delta.
- **`docs/development/RELEASING.md`:**
  - the release from this repository's side;
  - "the revision names a candidate, the semver names a release";
  - the component declaration;
  - the cut and its record;
  - `make check-release-versions`;
  - that public channels are the deployment's.
- **`docs/buyer-quickstart.md`:** installing the CLI.

Registry coordinates and credentials are never recorded in this repository.
