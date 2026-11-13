## Context

A release used to be whatever CI produced. PyPI and npm received what a push to `main`
built. A `marketplace-v*` tag made CI build a wheelhouse, a manifest, provenance and a
ghcr image, and a `market-cli-v*` tag published a tarball of the source tree with a curl
installer. None of it was what a deployment validated. Images do not rebuild to the
same digest, so the ghcr image a tag produced was never the image production ran, and a
version pushed to PyPI before validation is permanent.

The deployment released marketplace v0.3.0 another way. It loaded the tag's artifacts
into its development registry with this repository's publish targets, validated them,
copied them by digest through pre-production and production, and published from
production's copies. This design makes that the release, and gives this repository the
half it owns:

- CI that publishes nothing;
- one declaration of what a release comprises;
- publish targets that store a release candidate under its revision;
- a chart and wheels whose versions mean their contents;
- a mode in which the local lanes run a candidate's images;
- the release record on a release branch, and the checks that keep that record honest.

The change was first designed as an interim gate, in which merges published to the
development registry and a promotion script here copied to PyPI. Sections 3–6 of
`tasks.md` belonged to that design and are withdrawn.

## Goals / Non-Goals

**Goals:**
- Nothing reaches a public channel except bytes a deployment validated.
- A release names exactly what was validated, in a record anyone can read, by content
  identity.
- One declaration of what a release comprises.
- A version whose contents changed is caught before anything ships.
- One program per name: the release's `market` is PyPI's `market`.

**Non-Goals:**
- Promotion, deployment or publication tooling in this repository.
- Trusting a development tag, a revision tag or a development registry's contents.
- Reproducible images or binaries.
- Enforcing semver beyond "changed contents need a changed version".

## The release, from this repository's side

1. **Change.** Work lands on `dev` and then `main`. CI builds and tests, and publishes
   nothing.
2. **Release candidate.** An operator loads `main`'s commit X with `make load-candidate`
   (D3). In one invocation it builds the wheelhouse, checks its versions, builds the
   images and the binary from it, and stores every release component, and the
   development images its validation runs, under X's nine-character revision.
3. **Validation and promotion.** The deployment's release validation runs:
   - the live end-to-end tests against X's revision tags;
   - every one of this repository's local lanes against the same images, pulled by
     revision tag and aliased to their local names by `pull-release-images`
     (`RELEASE_IMAGES=1`).

   The deployment builds the release's bill of materials, refusing it unless the live
   pods, the local run and X's revision tags name the same digests, and unless PyPI
   holds none of its wheel versions with other bytes (D14). It then promotes
   the candidate to pre-production and production, aliasing each image to
   `<service>-<semver>`.
4. **Cut.** Once production runs the release, and the deployment's PyPI read passes
   again, `releases/<semver>` is cut at X, one commit adds the bill of materials,
   `make check-release-record` passes, and that commit is tagged `marketplace-v<semver>`.
5. **Publication.** The operator publishes the promoted bytes to PyPI, ghcr and the
   GitHub release, after the cut and all or nothing. npm is reached only once the npm
   package is a release component (D19).

A fault found at step 3 is fixed on `main`, and a later commit becomes the next release
candidate. A candidate that fails before production gets no branch, no tag and no
public artifact.

## Decisions

### D1 — Continuous integration publishes nothing

`publish-pypi.yml`, `publish-npm.yml`, `release.yml` and `release-cli.yml` are deleted,
with `scripts/verify-marketplace-release.py`, the release contract
(`arkhai.marketplace-release.v2`) and their tests. CI keeps building and testing. That
includes building the wheelhouse and resolving every declared distribution against it,
which was the one useful thing the publishing workflow checked before it uploaded.

Nothing reaches a public channel except bytes a deployment validated: a public version
is permanent, and only the deployment knows which bytes passed.

Alternatives considered:
- **Keep a trusted-publishing workflow "only to create a new PyPI project".** Rejected.
  The operator publishes with their own credentials, and an owner moves a project first
  uploaded that way into the organization. A workflow kept for one rare step keeps a
  publishing path alive for nothing.
- **A tag-triggered workflow that publishes the promoted bytes.** Deferred, not
  rejected. It would need read access to production's registry from GitHub, or a
  rebuild checked against the bill of materials. If it returns, it publishes promoted
  bytes or nothing, and the cut stays a human act.
- **A merge to `main` publishes to the development registry.** Rejected; this was the
  interim design. Development registries are scratch, and a merge-triggered push is one
  writer among many, guaranteeing nothing about what a tag holds when validation runs.

### D2 — A release candidate is a commit named by its revision; a marketplace release is a promoted candidate named by its semver

- A **release candidate** is a default-branch commit loaded under its revision.
- A **marketplace release** is a release candidate the deployment promoted, named by
  its semver and recorded by its tag.
- A **release component** is an entry of the declaration (D6) other than a development
  image.
- The **candidate store** is the set of revision-keyed generic packages a candidate's
  files are stored in (D3).

These terms are defined in deployment-state. RELEASING.md uses them, and neither
document says a bare "candidate", nor a bare "release" where a Helm release could be
meant. `ARCHITECTURE.md` already uses "candidate" for the publication candidate and for
scheduling, and "release" for lease release and the Helm release.

At merge time the semver is unassigned, and whether X will pass is unknown, so a merge
cannot be a release. For the same reason the release branch is cut last: cut before
validation, it would need rebasing every time validation found a fault.

### D3 — Every component of a release candidate is stored under its revision

Loading a candidate stores:
- each declared image as `arkhai:<name>-<rev9>`;
- the declared wheels as generic package `wheelhouse`, version `<rev9>`, one file per
  declared wheel under its wheel file name;
- the chart package `make dist-helm` builds as generic package `chart`, version
  `<rev9>`, one file `<chart>-<version>.tgz`;
- the `market` binary as generic package `market`, version `<rev9>`, in `<prefix>-cli`,
  where `push-cli` stores it today.

The wheels and the chart go to the repository `<prefix>-candidates`, beside
`<prefix>-cli`, `<prefix>-docker`, `<prefix>-helm` and `<prefix>-python`, all derived from
`AR_PREFIX`. That repository is provisioned outside this repository.

**One load operation binds the wheels to the images** (design review 26 F2).
`make load-candidate`, in one invocation and in this order:
1. builds `.dist` once and runs `make check-release-versions` on it (D14);
2. builds every declared image and development image, and the binary (D18), from that
   `.dist`. Each image whose build installs wheels from `.dist` — the four release
   images other than `frp-grant-admission`, and the e2e-tests image — takes the
   wheelhouse digest as a build argument and records it as the label
   `org.arkhai.wheelhouse-digest`;
3. refuses, naming what differs, unless `.dist`'s wheelhouse digest is still the one it
   built with and every such image carries it;
4. deletes the revision's stored versions and uploads (below).

The wheelhouse digest is computed like the chart's content digest (D14), over the
declared wheels in `.dist`. It replaces the `cksum` fingerprints that two image builds
pass today as a cache key: Podman can reuse cross-stage layers after `.dist` changes, so
an image built after `.dist` could otherwise hold layers from an older wheelhouse. The
validated wheels are therefore the candidate's wheelhouse because one load builds them,
the images and the binary, and uploads nothing unless every image was built from them.
`push-runtime-artifacts` is no longer how a candidate is loaded, and no release step
names it or the individual push targets.

A candidate's versions are not unique: the version
check compares only with the previous marketplace release, and the versioning policy
forbids bumping an unreleased version again. So failed candidate A and the next
candidate B routinely carry one wheel version with different bytes. Likewise, a later
candidate or a developer push overwrites a chart's OCI tag, which is its version.
Storing by revision is what makes "the revision names a release candidate" true of every
component rather than of images and the CLI alone.

**Reloading** (design review 26 F5). Once every component is built and the check in
step 3 passes, the load deletes the revision's `wheelhouse`, `chart` and `market`
versions, all three, before uploading any. The generic-package upload cannot overwrite a
file a version holds — it fails with ALREADY_EXISTS — so without the delete a reload
would fail at the binary after replacing the rest. The load never uses
`--skip-existing`, or any upload mode that keeps an earlier file. The store then always
holds exactly one load's declared set, which the deployment's bill-of-materials builder
requires: exactly the declared wheels, each once, exactly one chart package whose file
name matches its `Chart.yaml`, and exactly one binary file. A load that fails after the
deletes leaves the revision incomplete, never mixed, and the builder refuses it until
the operator loads again. Development registries are scratch, every identity in the bill
of materials is a content identity, and validation runs against the last load, so
replacing a revision breaks nothing; the binary's identity is the SHA-256 of the file the
last complete load stored.

Nothing installs from the development Python index, so loading a candidate does not push
to it.

Loading also pushes each declared development image (D6) as `arkhai:<name>-<rev9>`. The
live topology runs dev-env and the e2e-tests image beside the release images, so a
candidate's validation needs them under its revision. They are not release components:
no bill of materials names them, and the deployment checks them against their revision
tags only. (Design review 14 F2.)

The candidate store expires stored revisions after a retention period set where it is
provisioned, so a candidate must be promoted before its revision expires. An expired
candidate is loaded again; images and binaries do not rebuild to the same digests, so a
reload is new bytes and is validated again from the start. RELEASING.md states this
without the period, which this repository cannot keep true. (Design review 14 F7.)

Alternatives considered:
- **Load by version, as before.** Rejected: on a collision the index holds whichever
  upload came last.
- **Load by version, with the candidate replacing a differing file.** Rejected: between
  load and promotion, a later candidate or a developer push can replace the file again,
  and nothing records it.
- **Leave the snapshot to the deployment.** Rejected: the deployment would have to
  reproduce part of this repository's build to know a candidate's bytes.
- **Separate build and push targets, with the wheelhouse label checked at upload.**
  Rejected (design review 26 F2): it binds across invocations, but leaves the version
  check reading whatever `.dist` holds when it runs.
- **The deployment installs and tests the stored wheelhouse itself.** Rejected: it
  cannot tell which wheelhouse an image installed, and it adds validation work outside
  this repository.
- **Replace the binary in place on reload.** Not available: the generic-package upload
  cannot overwrite a file.
- **A load record written last, which the store must match.** Not adopted: the images'
  labels bind them to the wheelhouse, and a revision tag rewritten after a load is
  accepted in development registries and caught by the deployment's digest agreement.

### D4 — A candidate's revision is nine characters

Every revision tag and store version uses `git rev-parse --short=9`, in every Makefile
that computes `GIT_SUFFIX`: the root, `e2e-tests`, `dev-env`, `core/registry`,
`provisioning/compute/service` and `domains/vms/storefront`. Each subproject Makefile
also runs on its own, so each keeps its own definition. The bill of materials tags
images `<service>-<rev9>`, and the local lanes' suffix must equal the revision tags
exactly. Git's default abbreviation grows with the repository: it is nine characters
today only by accident, so a Makefile left on the default would go wrong only on the
day the abbreviation grows. The packaging check therefore refuses a
`git rev-parse --short` without `=9` in any Makefile. (Design review 14 F3.)

### D5 — Loading a candidate does not refuse an edited tree

The load targets do not check that the tree is clean. A reload replaces the revision's
stored files (D3), and every identity the bill of materials records is a content
identity. `arkhai:source-revision` therefore rests on the operator's word that the load
came from X.

Alternative rejected: **refuse a tree with uncommitted changes to tracked files**, so the
source revision states which commit produced the bytes. It is not needed for any
identity the record relies on.

### D6 — One declaration of release components

`manifests/published-distributions.json` becomes `manifests/release-components.json`. Its
release components are only what a release ships, so every one is released and no
`public` flag exists; the development images a candidate's validation runs are listed
apart:

```json
{
  "distributions": [
    {"key": "kit-schema-migrations", "path": "kit/schema-migrations", "dist": "arkhai-kit-schema-migrations"}
  ],
  "images": [
    {"name": "registry", "local": "registry"},
    {"name": "storefront", "local": "storefront"},
    {"name": "provisioning", "local": "compute-provisioning"},
    {"name": "bare-metal-storefront", "local": "bare-metal-storefront"},
    {"name": "frp-grant-admission", "local": "frp-grant-admission"}
  ],
  "chart": {"path": "helm"},
  "binaries": [{"name": "market", "target": "build-market-binary", "path": ".dist/bin/market"}],
  "development_images": [
    {"name": "dev-env", "local": "dev-env"},
    {"name": "e2e-tests", "local": "e2e-tests"}
  ]
}
```

- **Distributions.** Each keeps its `key`, `path` and `dist`, in dependency order.
  - `arkhai-apicredits-sample-app` leaves. It is test-only: built by `make dist`, not
    `make dist-release`, and never published.
  - `lane-double-controls` was never in the manifest.
  - `wheel_only` is dropped. PyPI receives wheels only, and no project force-includes
    files from outside its own directory.
- **Images.** `name` is the published name, which is the tag stem in
  `arkhai:<name>-<rev9>`. `local` is the image the build writes, since `provisioning` is
  built as `compute-provisioning`. The five images are the release's. The API-credit
  service, storefront and sample-app images are not release components, and the
  API-credit lane builds them from the checkout.
- **Chart, binaries.** The chart's directory; the binary with its build target and
  output path.
- **No npm entry.** The npm package is not a release component until it can be loaded
  and validated (D19). It joins as `"npm": [{"path": "domains/apicredits/middleware/typescript"}]`
  when `push-npm` exists.
- **Development images.** `development_images` lists the images a candidate's
  validation runs that a release does not ship, with `name` and `local` as for
  `images`. The load pushes them under the revision (D3); nothing else treats them as
  release components. They are declared here so that `push-dev-images` reads a list
  rather than naming its own, which the single-enumeration check (D7) would refuse.
  (Design review 14 F2.)
- **Absence.** Every key is required except `npm`, which is absent until the package is
  declared; an empty `npm` list is refused, so "no npm package" has one spelling. Every
  reader refuses a missing required key, an unknown key, a duplicated name or
  distribution, and a value of the wrong kind. (Design review 26 F4.)

Who reads it:
- the publish targets;
- the single-enumeration check (D7);
- the lanes' release-image check and `pull-release-images` (D17);
- the binary build (D18);
- `test_publish_matrix.py`;
- `make check-release-record` (D12);
- the deployment's bill-of-materials builder, which reads `distributions[].dist`,
  `images[].name` and `binaries[].name`, and finds the chart from the one package stored
  under the revision.

The Makefile still builds everything. The declaration says what a release comprises, not
how to build it.

### D7 — The single-enumeration and workflow-credential checks

A check run by `make check-packaging` refuses:
- a list of distributions, images, development images, the chart or the binary in any
  workflow, publish target or lane target, other than the declaration;
- a workflow that could publish, judged by the credentials it holds (design review
  11 F5):
  - no top-level `permissions:`, since a workflow without one gets the repository's
    default token, which may write;
  - `id-token: write` (trusted publishing to PyPI and npm), `packages: write` (ghcr) or
    `attestations: write`, anywhere;
  - `contents: write`, anywhere;
  - a reference to any secret but `GITHUB_TOKEN`;
- a named publishing step in a workflow, so a refusal names the step:
  `pypa/gh-action-pypi-publish`, `npm publish`, `docker push`,
  `docker/build-push-action` with `push: true`, `softprops/action-gh-release`,
  `gh release create`.

A workflow cannot publish without a credential, and the credentials a workflow can hold
are few and visible in its file, so the credential rule is what makes "no workflow
uploads an artifact" a mechanical guarantee. A list of upload commands alone would miss
`uv publish`, `twine upload`, `helm push` or any marketplace action. The named steps stay
for the message, not the guarantee.

The rule has no exception (design review 26 F3). `validate-model-release.yml` held
`contents: write` only to append a validation line to a `model-v*` release's notes, but
that token could also upload release assets and push commits and tags, including a
`marketplace-v*` tag. It drops to `contents: read`, which downloading the release's
assets needs, and loses its note step; the workflow's pass or fail on the tag is the
validation's record.

No such check exists today, though the task that would have added it is checked off. Two
lists kept in agreement by hand diverge silently, and review alone did not prevent it.

Alternatives rejected:
- **The named upload steps alone, with the spec narrowed to them.** Cheaper, but the
  guarantee rests on review.
- **An allowlist of permitted actions and commands.** Strongest, but edited for every new
  CI step.
- **Keep `validate-model-release.yml`'s write token, restricted to its note-edit
  command.** A check parsing one workflow's shell, which a call to the API with the
  same token defeats.
- **Keep the exception and rest that one workflow on review.** Honest, but keeps a
  write-capable token beside what this change protects.

### D8 — Every declared image's build writes its revision tag

With `IMAGE_SUFFIX` empty, every declared image's build writes `arkhai:<local>-<rev9>`
beside its bare tag. `build-bare-metal-storefront` writes none today. A test holds every
declared image to a build target that writes it, extending
`test_image_publication_contract.py`, which covers provisioning only. `push-images`
pushes the declared images through `scripts/publish_artifacts.py`, in place of its four
literal lines, and keeps pushing the bare `arkhai:<name>` tags that shared development
releases follow. `push-dev-images` pushes the declared development images the same way,
and the load (D3) pushes both. No release step reads a bare tag.

### D9 — The chart names no release

A chart's packaged files include its version and its default values. Defaults naming a
release's images would make the chart built at the cut differ from the chart validated,
and would force a new chart version for every release.

- **Version.** `version` follows the chart's own semver and changes only when the chart
  does.
- **Images.** The default values keep the bare development tags with empty digests. A
  deployment names its images in its own values.
- **appVersion.** It means nothing here and is removed from `helm/Chart.yaml` and all
  nine subcharts, with the `app.kubernetes.io/version` block in the umbrella's
  `_helpers.tpl` and the seven subcharts that carry one (the two lane doubles carry
  none). That block is guarded by `if .Chart.AppVersion`, so leaving it would be dead
  template. The label is in no selector, so an upgrade only rolls pods. The removal
  changes each chart's packaged files, so each chart's version is bumped.
- **Subchart pins.** The umbrella pins each subchart by exact version over
  `file://charts/…`, in ten dependency entries (`registry` appears twice, once aliased
  `api-credits-registry`). Every subchart bump updates its entries. A test in `helm/`
  holds each entry's `version` equal to its subchart's `Chart.yaml` version, since
  `dist-helm` runs a bare `helm package` and nothing shows that it refuses a mismatch.
  (Design review 14 F4.)

The bill of materials records which chart version a release uses, so one chart version
can appear in many releases.

### D10 — The deployment builds the bill of materials, in layout 1

The deployment owns the bill-of-materials format and builds the document, because only
it knows which digests passed. This repository commits the document at the cut as
`manifests/release-bom.cdx.json` and reads it in `make check-release-versions` and
`make check-release-record`.

Layout 1 is CycloneDX 1.6:
- **Header.** `bomFormat` `CycloneDX`, `specVersion` `1.6`, `version` 1, and
  `metadata.lifecycles` `[{"phase": "post-build"}]`. There is no serial number,
  timestamp or tools entry: the document's identity is the SHA-256 of its bytes, so the
  same inputs give the same bytes.
- **Subject.** `metadata.component` is the release: type `application`, bom-ref and
  name `marketplace`, version the release semver. It has one external reference, the
  public vcs URL, and two properties: `arkhai:bom-layout` = `1`, and
  `arkhai:source-revision` = X's full 40-hex commit, stated only here because every
  component is built from that one commit.
- **Components.** Each has bom-ref `<kind>/<name>`:

  | Kind | Type | Version | Identity |
  |---|---|---|---|
  | wheel | `library`, named by distribution | the wheel's | SHA-256 of the wheel; purl `pkg:pypi/<name>@<version>?file_name=<wheel file>` |
  | image | `container`, named by service | none | SHA-256 manifest digest; purl `pkg:oci/arkhai@sha256%3A<hex>?tag=<service>-<rev9>`, no `repository_url` |
  | chart | `application`, named by chart | the chart's | property `arkhai:content-digest` (D14); no hashes |
  | binary | `application` `market` | none | SHA-256 of the file; property `arkhai:platform` = `linux/amd64` |
  | npm | `library`, group `@arkhai` | the package's | SHA-512 of the tarball, required; present only once the npm package is declared (D19) |

- **Serialization.**
  - UTF-8 JSON, two-space indent, LF line endings, trailing newline.
  - Keys in the order above; components sorted by bom-ref; properties sorted by name.
  - Hex digests in lowercase, with no algorithm prefix.
  - Readers digest the file as committed and never re-serialize it.
- **No registry location.** No registry host, project or path appears anywhere, purls
  included. Readers refuse a layout they do not know.

`AGENTS.md`'s public-repository discipline forbids run artifacts produced by private
tooling. It is amended to admit a marketplace release's bill of materials holding content
identities only. `make check-release-record` (D12) refuses any field or URL layout 1 does
not admit, so the amendment is enforced, not promised.

Alternative rejected: **this repository builds the document** with a make target, from
the candidate's checkout plus the validated image and binary digests, and owns its
format. The owner chose to keep the format with the party that builds it.

### D11 — A marketplace release is recorded last by a tagged commit on its release branch

At the cut, `releases/<semver>` is created at X, a single commit adds
`manifests/release-bom.cdx.json`, and that commit is tagged `marketplace-v<semver>`.

- **Why a branch.** The repository is public, so the record sits beside the source it
  describes.
- **Why one commit.** A fix lands on `main` and ships in the next release, so a release
  branch never grows past its record. There are no patch releases from a release
  branch: every marketplace release is cut from a default-branch commit.
- **Why last.** The irreversible steps — a public tag, a PyPI version, an npm version —
  come after production runs the release. A release that fails earlier can be destroyed
  entirely by the deployment, and nothing public refers to it.

Alternative deferred: **patch candidates** cherry-picked onto a branch from a released
commit. Revisit the first time production needs a fix that `main` cannot ship promptly.

### D12 — The release record is checked at the cut

The operator runs `make check-release-record TAG=marketplace-v<semver>` before pushing
the tag. It refuses unless:
1. the tag's commit is on `releases/<semver>`, and its parent is reachable from the
   default branch;
2. the commit changes exactly one path, adding `manifests/release-bom.cdx.json`;
3. the bill of materials is layout 1, carries only layout 1's fields, and has no URL but
   the public vcs link;
4. its `arkhai:source-revision` is the parent commit, and its subject's version is the
   tag's semver;
5. its components, by bom-ref `<kind>/<name>`, are unique and are exactly the release
   components the declaration at the parent commit declares — every distribution,
   image, the chart, every binary, and npm only once declared — naming each missing,
   extra and duplicated component; no development image appears (design review 26 F4);
6. `make check-release-versions` passes with the bill of materials itself as its
   subject, against every earlier marketplace release (D14).

It shares its reader with the version check, and needs no wheelhouse or Helm: the cut
runs in a fresh worktree, and the bytes about to be published are the ones the record
names. (Design review 11 F2 / 14 F1.)

Alternative rejected: **a non-publishing workflow on a `marketplace-v*` tag push.** It
can only report a public tag that already exists, and the rule is about what is pushed.

### D13 — This repository's specification states only its own behaviour

The deployment-state delta specifies what this repository does and can prove:
- CI publishes nothing;
- the candidate store;
- the declaration;
- the image revision tags;
- the chart;
- the backend pin;
- the version check;
- the release record and its check;
- the lanes' release-image mode;
- the release binary.

RELEASING.md describes the deployment's part as the procedure this repository relies on:
- validation, and building the bill of materials;
- refusing a release whose wheel versions PyPI holds with other bytes, by a public,
  tokenless read of PyPI when building the bill of materials and again immediately
  before the cut, which also surfaces a new distribution whose PyPI project does not yet
  exist (design review 26 F1);
- running every local lane with `RELEASE_IMAGES=1`, whose records together cover every
  release image but `frp-grant-admission`, which only the live tests run (design
  review 14 F6);
- aliasing images to `<service>-<semver>` at promotion;
- cutting only after production runs the release;
- publishing only after the cut, with promoted bytes, all or nothing, never replacing or
  deleting a version, skipping a wheel PyPI already holds with the same SHA-256, and
  wheels only, since no sdist is built at the cut.

Until this change lands on `main`, `publish-pypi.yml` uploads every version bump merged
there with CI-built bytes. The workflow runs on pushes to `main`, so deleting it on this
change's branch stops it only when the change lands, whichever commit deletes it;
disabling it in the repository's Actions settings closes the window sooner, and is the
owner's call. This is a transition concern, so it is recorded here and in the proposal,
not in RELEASING.md, which describes the release once the change has landed.

A spec states the implemented normative contract. Requirements no part of this
repository implements or can test would be permanent text describing someone else's
internals, and they would go stale silently when the deployment changes.

Alternative rejected: **keep the deployment's acts as normative requirements here.**

### D14 — A version changes when its contents change

`make check-release-versions` reads the bill of materials of every `marketplace-v*` tag
that carries one, except the tag being checked, and refuses a layout it does not know.
Its rule: a (component, version) pair that any earlier record names keeps the content
identity that record gives it. (Design review 11 F2 / 14 F1.)
- **Wheels:** a wheel whose distribution and version an earlier record names must have
  that record's SHA-256.
- **The chart:** a chart whose version an earlier record names must have that record's
  `arkhai:content-digest`.

Its subject depends on when it runs:
- **In a load** (D3), the wheelhouse the load built and the chart `make dist-helm`
  packages.
- **At the cut** (D12), the release's own committed bill of materials: its wheel
  SHA-256s and chart content digest, with no build.

Every earlier record, not only the newest, is read, because a version lowered back to
one released two releases ago would otherwise pass and then fail at PyPI after the
record is public. Reading them all costs one git blob per release and needs no rule
about version order. It also catches a release cut between a candidate's load and its
cut. Excluding the tag being checked matters at the cut, where that tag already exists
locally and is the newest.

The chart's content digest is computed like Go's module dirhash:
1. list the package's regular files by archive path, sorted bytewise;
2. for each, write `<sha256 hex of contents>  <archive path>\n`, with two spaces;
3. take the lowercase SHA-256 hex of that text.

It is computed from a package, never from the source directory, because Helm rewrites
every `Chart.yaml` when packaging and leaves the other files unchanged. `helm package`
archives differ in tar metadata between runs while the files inside are identical. The
rewrite may change between Helm versions, so the check pins Helm.

When no other tag carries a bill of materials, the check says so and passes; v0.3.0
carries none. In a load it needs git, the wheelhouse and the pinned Helm; at the cut,
git alone. A refusal means "bump the version"; the check never chooses one.

**Its scope** (design review 26 F1). The check guards the versions recorded releases
name, offline. It is not a complete guard against PyPI, whose history includes versions
no record names: those CI published before this change, and any it publishes before the
change lands on `main`. PyPI holds v0.3.0's distributions with exactly the bytes the
deployment's record of v0.3.0 gives them. The complete guard is the deployment's: a
public, tokenless PyPI read refusing any wheel version PyPI holds with other bytes, when
it builds the bill of materials and again before the cut (D13). This repository relies
on it and does not read PyPI, so its checks stay offline and deterministic. A collision
is therefore caught after validation rather than before the load, which can cost one
validation run in the narrow cases left: a version lowered to one released before
v0.3.0, or one CI uploaded in the meantime.

Alternatives rejected:
- **Only the newest earlier release, plus a rule that versions never decrease.** Two
  rules where one suffices.
- **A rebuild at the cut.** The cut runs in a fresh worktree, and a rebuild would only
  reproduce what the record says.
- **This repository's check reads PyPI.** Complete, and catches a collision before the
  load, but puts a network read in an offline check for a guard that belongs with
  publication, which is the deployment's.
- **A one-time bump of every distribution before the first recorded release.**
  Unnecessary, since PyPI's bytes match v0.3.0's record, and it leaves older versions
  and CI's interim uploads unguarded.
- **A baseline imported from PyPI or from v0.3.0's record.** A permanent migration
  artifact in a second format, covering only what it captured.

The chart package includes `helm/`'s tests and fixtures, since there is no
`.helmignore`, so a test-only edit inside `helm/` forces a chart version bump. That is
accepted: a bump is cheap, and a missed change is not.

Alternative rejected: **the chart directory's git tree id.** It is tied to the source
layout rather than to what is shipped.

### D15 — The build backend is pinned beside the Python version; moving the pin is a release-wide bump

Every project declares `requires = ["hatchling"]`, and hatchling stamps its own version
into every wheel (`Generator: hatchling 1.33.0` in `WHEEL`). Unpinned, the first
hatchling release after a marketplace release would change every wheel's SHA-256, and
the version check would refuse every unbumped distribution.

- **Where the pin lives.** Hatchling is pinned exactly in one root declaration beside
  `.python-version`. The root Makefile exports it to every build as a uv build
  constraint, as it exports `UV_PYTHON`. A packaging check beside
  `check-python-version` refuses any `[build-system]` requirement the declaration does
  not pin, not only the backend, and a build path that bypasses the export. A build
  plugin such as `hatch-vcs` can change a wheel's bytes as the backend's version does.
  Today every project requires exactly `hatchling`. The declaration pins direct build
  requirements only, not hatchling's own dependencies. (Design review 14 F5.)
- **Moving the pin.** A pin move is a change like any other. It changes every wheel, so
  it bumps every declared distribution's patch version once, and the version check
  enforces that with no special handling. SHA-256 stays the only wheel identity, in
  layout 1, in the version check and in the deployment's publication.

Alternatives rejected:
- **The pin in every project's `[build-system]`.** About sixty copies of one fact.
- **A digest that ignores the build stamp.** It needs a second layout, and weakens "same
  version, same bytes" to "same version, same payload" for the deployment's
  publication.
- **Never moving the pin.** Unrealistic.

### D16 — A product version is distinct from a distribution version

A wheel's version is inside the wheel and cannot be relabelled without a rebuild, which
would change its digest. Wheels and the chart, and the npm package once declared, keep
the versions they were built with. Images and the binary have no version of their own: they are named by
revision as candidates, and the deployment aliases images to the semver at promotion.
The release semver appears once in the record, on the subject.

### D17 — The local lanes can run a release candidate's images and record them

A release is validated by two suites that must run the same images: this repository's
local lanes, which use test doubles, and the deployment's live end-to-end tests. Images
do not rebuild to the same digest, so a lane that builds its own release images tests
different bytes.

```
make -C e2e-tests pull-release-images DOCKER_REGISTRY=<registry> IMAGE_SUFFIX=-07af25d57
make -C e2e-tests test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-07af25d57
```

- **How the images arrive.** `pull-release-images`, given a registry and a suffix,
  pulls each declared release image as `<registry>/arkhai:<name><IMAGE_SUFFIX>` and
  tags it `arkhai:<local><IMAGE_SUFFIX>`, the name the lane's compose files run. The
  name-to-local mapping is applied only here, from the declaration, so the deployment
  never reads `images[].local`. The registry is passed in, as the push targets take it,
  and is never committed. Docker keeps the pulled repo digest across the retag, which
  is what the lane's record reads. The digest check stays with the record and the
  deployment's builder, so the target pulls by revision tag and needs no digests.
  (Design review 11 F4.)
- **What it builds.** With `RELEASE_IMAGES=1`, a lane target builds the wheels, dev-env,
  the test image and the non-release images its stack runs (the lane doubles; the
  API-credit images). It builds no declared release image.
- **What it checks.** First, that each declared release image the lane's compose files
  reference exists locally as `arkhai:<local><IMAGE_SUFFIX>`, failing with every missing
  one named. It refuses `RELEASE_IMAGES=1` with an empty suffix.
- **The compose files.** Each release image is named `arkhai:<local>${IMAGE_SUFFIX:-}`,
  following the bare-metal storefront's existing variable, so one set of files serves
  both modes.
- **What it records.** After the stack is up, the lane writes
  `.snapshot/e2e-release-images-<lane>.json`, and prints it, from the running
  containers:
  ```json
  {"lane": "bare-metal", "image_suffix": "-07af25d57",
   "images": {"registry": "sha256:…", "provisioning": "sha256:…", "bare-metal-storefront": "sha256:…"}}
  ```
  - Keys are published names (D6).
  - Values are the images' manifest digests, from their repo digests, not their local
    image IDs.
  - A release image with no repo digest, or with two different ones, fails the lane:
    choosing between two would need the registry name, which the record never carries.

Each lane records only the release images it runs. No lane runs `frp-grant-admission`.
`e2e.yml` is unchanged: it is a CI check that builds from source, not release
validation.

Release validation runs every lane. Together their records cover every release image
but `frp-grant-admission`, which only the deployment's live tests run (D13).

Alternatives rejected:
- **One `CANDIDATE=<rev9>` variable.** A second way to say a suffix.
- **Separate release-image lane targets.** Duplicated recipes drift.
- **The deployment pulls and retags, reading `images[].local`.** The mapping would be
  applied in a second codebase.
- **Compose takes full registry references in release-image mode.** The lanes'
  interface would carry a registry, which the build mode never needs.

### D18 — The release's `market` binary is PyPI's CLI, built in a pinned image

Today the binary is PyInstaller's freeze of `arkhai_vms_buyer/main.py`, a VM-only app,
built on whatever host runs `make build-buyer`. PyPI's `market` is `core_buyer.cli:main`,
which discovers every buyer domain through `market.buyer_domains` entry points. Two
programs sharing one name is the defect.

- **What gets built.** A `build-market-binary` target freezes `core_buyer.cli:main`
  inside a build image pinned by digest: `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`,
  Debian bookworm with the Python `.python-version` declares, the base every image that
  installs through `scripts/uv_project.py` uses. A Python bump pins a new digest, and the
  build refuses an image whose Python is not the declared one.
- **How it installs.** The binary has a locked virtual project (`[tool.uv] package =
  false`), for example `core/buyer/market-binary/`, whose Dockerfile sits beside it:

  ```toml
  [project]
  name = "arkhai-market-binary"
  version = "0.1.0"
  requires-python = ">=3.13,<3.14"
  dependencies = [
    "arkhai-core-buyer",
    "arkhai-vms-buyer",
    "arkhai-bare-metal-buyer",
    "arkhai-apicredits-buyer",
  ]

  [dependency-groups]
  freeze = ["pyinstaller==6.22.3"]

  [tool.uv]
  package = false
  environments = ["sys_platform == 'linux' and platform_machine == 'x86_64'"]
  ```

  The build image installs its committed lock through `uv_project.py image`, as every
  image installs one (`BUILD_AND_PACKAGING.md`, "Images"). The lock records every
  repository distribution's source as the wheelhouse, so the binary bundles `.dist`'s
  bytes with `.dist`'s dependency sets, and third-party versions, PyInstaller included,
  are decided at lock time and reviewed. `make lock` relocks the project and
  `check-locks` holds it current, like any other. A virtual project is not a package, so
  the architecture and layout checks pass over it.
- **Which plugins it bundles.** Exactly the buyer CLI — the one declared distribution
  defining the `market` console script — and every declared distribution registering a
  `market.buyer_domains` entry point. They are listed once, in the binary project's
  dependencies, and a packaging check holds that list equal to the set derived from the
  declaration, naming each missing and each extra distribution. That is D21's rule: a
  list held equal to the declaration by a check is not a second list. A missing domain
  would make the release's `market` a different program from PyPI's, and so would an
  undeclared one, which PyPI does not serve. The check runs in `make check-packaging`.
- **What is derived.** `scripts/market_binary.py` derives, from the declaration and each
  declared project's `pyproject.toml`, the set the check compares, the entry point the
  binary freezes, and the PyInstaller options: `--copy-metadata` for the CLI and each
  domain, since discovery reads installed metadata, and `--hidden-import` for each module
  a domain's entry point names, since discovery imports it by name. The binary's name
  and output path are read from its `binaries[]` entry, found by its build target; the
  script refuses an entry whose `path` does not end in its `name`. Neither the
  Dockerfile nor the Makefile names a domain, the binary or its path.
- **The smoke test.** The build image runs `market plugins` in the installed environment
  and in the frozen binary, and requires the same stdout from both, one line per
  registered `market.buyer_domains` entry point, and no skipped domain on either stderr.
  No validation suite runs the binary, so this is what exercises it.
- **Repeatability.** Pinning the image and locking the environment fix the binary's
  inputs, not its bytes. PyInstaller output is never byte-for-byte repeatable. The
  binary is identified by the SHA-256 of the stored file. The load builds it from the
  same `.dist` as the stored wheelhouse and the images, and a reload replaces it by D3's
  delete-then-upload rule.
- **The image rule holds without exception.** `check-uv-setup` reads `*.Dockerfile` as
  well as `Dockerfile*`, as `check-python-version` does, and refuses any `pip install`,
  `python -m pip install` or `uv pip install` of the wheelhouse not made through the
  script, which it had not recognised: an unlocked `pip` install from `.dist` passed it.
- **The PyPI defect.** PyInstaller leaves `arkhai-vms-buyer`'s runtime dependencies,
  where it made every PyPI install of the VM plugin pull it in. That is a minor-version
  bump of `arkhai-vms-buyer`.

A customer installs `market` from PyPI on any platform
(`uv tool install arkhai-core-buyer --with arkhai-vms-buyer`, pinned to the release's
versions), or downloads the release's binary on linux/amd64 and checks it against the
bill of materials. The curl installer — `install.sh`, `scripts/install-remote.sh`,
`scripts/build-installer.sh` — is deleted. It built the CLI from a source tarball,
bypassing the released wheels, and it has been broken since a marketplace release became
GitHub's latest. `market-cli-v*` tags are no longer made.

Alternatives rejected:
- **Keep the VM-only binary built on the operator's host.** It keeps two programs under
  one name.
- **The VM-only binary in a pinned image.** It fixes the build host but keeps the two
  programs.
- **Drop the binary.** Layout 1 includes it.
- **An unlocked install, derived from the declaration at build time.** Every declared
  distribution held at its version by constraints, then reinstalled from `.dist` with
  `--no-deps`. If PyPI serves an internal distribution at the version `.dist` holds but
  with other requirements, the resolve can take PyPI's, and the reinstall keeps them;
  third-party versions in a binary customers download are whatever PyPI serves that day.
  It breaks the image rule, which would need an exception.
- **The image rule amended for the binary's build,** installing the internal closure
  from `.dist` with `--no-index --no-deps` first and resolving only third-party packages.
  It closes the requirements hazard, but leaves third-party versions unlocked and makes
  the rule's one exception a downloadable binary.
- **The binary built from `e2e-tests`' lock,** which already covers the CLI and all three
  domains. The binary would bundle the third-party versions the lanes test, but a test
  project would own the release binary's dependency set: a test-only bump relocks what
  customers download, and PyInstaller follows optional imports into packages only tests
  need.
- **The binary project's dependencies written by `make lock` from the declaration.**
  Adding a domain would be one edit, but `make lock` would gain a writer of a
  `pyproject.toml`, unlike any other project, for a list that changes rarely and that
  the check already names when stale.

### D19 — The npm package is not a release component until it can be loaded

The middleware package is built and tested, but it is not in the declaration, and a
marketplace release neither records nor publishes it, until a development registry
serves npm. That registry is provisioned outside this repository. Then `push-npm` is
added, the package joins the declaration, and its layout-1 row, with its SHA-512
required, applies. Layout 1 already defines that row, so its joining needs no new
layout.

An unloaded package has no validated bytes. Recording it by version with no hash would
let a release name, and its publication push, a tarball nobody validated, and npm
versions are permanent. With `publish-npm.yml` deleted (D1), nothing publishes the
package in the meantime. (Design review 11 F1.)

Alternative rejected: **a loaded, digested tarball as a prerequisite of every release.**
It keeps the release complete, but holds every wheel and chart release on
infrastructure this repository does not control.

### D20 — The orphaned release-verification requirement is removed

deployment-state's "Release verification is a publication-time activity" governs a
verifier of externally produced signed releases, which left the tree with hosted
settlement. The delta removes it. "Deployment documentation states how a dependency is
obtained" stays: it still applies.

### D21 — RELEASING.md keeps the anchors other documents cite

RELEASING.md is rewritten from this repository's side. Its "Cutting a release" heading,
which `ARCHITECTURE.md` cites, holds the cut procedure, keeping the `make audit-secrets`
step and the per-release migration-floor judgement. Its "Versioning policy" heading,
which `check_version_bumps.py` cites, stays and gains the pin-move rule. The
published-packages table stays, checked against the declaration by
`test_publish_matrix.py`: a table in a document, held equal by a check, is not a second
list a publish target reads.

### D22 — The change keeps its name

`publish-wheels-through-a-gate` no longer describes the scope. Renaming would move the
clone, the branch, the records and the workflow log for a name the archive keeps only as
history. The proposal states what the change does.

### Implementation cadence

One round of five sessions before closeout:
1. CI publishes nothing (the four workflows, the verifier and the curl installer
   deleted; `validate-model-release.yml` read-only); the declaration renamed and
   reshaped, with `development_images`, no npm entry and its absence rule; the
   single-enumeration and workflow-credential checks.
2. Candidate loading: `make load-candidate`, with the wheelhouse digest as every
   `.dist`-built image's build argument and label and the check before upload; the
   candidate store with delete-then-upload of all three generic versions; `--short=9`
   in every Makefile and its check, every declared image's revision tag, `push-images`
   and `push-dev-images` from the declaration; the build-requirement pin and its check;
   `appVersion` removed, the subchart pins and their test.
3. The layout-1 reader, `make check-release-versions` over every earlier record with its
   two subjects, and `make check-release-record`.
4. The lanes' release-image mode, `pull-release-images`, and the lanes' record.
5. The binary's locked project and build image, the check holding its domains to the
   declaration, `check-uv-setup` reading every Dockerfile and every wheelhouse `pip`
   install, and PyInstaller out of `arkhai-vms-buyer`'s runtime dependencies. This
   session resumes the binary's work already committed, whose retirement of the old
   binary and relock without PyInstaller stand.

Closeout writes RELEASING.md, the buyer quickstart, the `AGENTS.md` amendment and the
`ARCHITECTURE.md` principles, as promotion.

## Risks / Trade-offs

- **A developer push lands in the development registry during validation.** The
  deployment's builder refuses when the live pods, the local run and X's revision tags
  disagree, and the candidate is reloaded.
- **The source revision is the operator's word** (D5). A load from an edited tree would
  be attributed to X.
- **A test-only edit inside `helm/` forces a chart bump** (D14). Accepted.
- **A hatchling pin move bumps every distribution** (D15). It is rare and deliberate.
- **The binary runs on linux/amd64 only.** PyPI covers every platform.
- **The binary's third-party versions are its own lock's** (D18). They may differ from
  those `e2e-tests`' lock gives the `market` the lanes run, as a customer's install from
  PyPI may; the build's smoke test is what exercises the binary.
- **Adding a buyer domain takes a second edit** (D18): the binary project's dependencies,
  which the packaging check names.
- **No marketplace release publishes the npm package until a development registry serves
  npm** (D19).
- **A candidate expires with the store's retention** (D3). It is then loaded and
  validated again.
- **A PyPI collision is caught after validation** (D14). The deployment's PyPI read runs
  when it builds the bill of materials, so a wheel version PyPI holds with other bytes
  costs one validation run. It arises only for a version CI published that no record
  names.
- **A load always rebuilds every image and the binary** (D3). Loads are rare, and the
  rebuild is what binds the stored wheels to the validated images.
- **The release is published after production runs it.** For a short while production
  serves a release whose wheels are not yet on PyPI. Nothing in production installs
  from PyPI.
- **Images, binaries and chart archives are not byte-reproducible.** A release records
  what was validated and copies that.

## Open Questions

- **Byte-reproducible chart packaging.** This is an open gap, not a requirement. If it
  closes, a later layout adds a hashes entry to the chart component. Revisit when
  `helm package` gains reproducible archives or the deployment needs to verify chart
  archives by bytes.
- **A tag-triggered workflow that publishes promoted bytes** (D1). Revisit if publication
  by hand becomes a bottleneck.
- **Patch releases from a release branch** (D11). Revisit the first time production needs
  a fix `main` cannot ship promptly.
