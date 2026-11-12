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
2. **Release candidate.** An operator loads `main`'s commit X with
   `make check-release-versions` and then `make push-runtime-artifacts`. That stores
   every release component under X's nine-character revision.
3. **Validation and promotion.** The deployment's release validation runs:
   - the live end-to-end tests against X's revision tags;
   - this repository's local lanes against the same images, pulled by digest
     (`RELEASE_IMAGES=1`).

   The deployment builds the release's bill of materials, refusing it unless the live
   pods, the local run and X's revision tags name the same digests. It then promotes
   the candidate to pre-production and production, aliasing each image to
   `<service>-<semver>`.
4. **Cut.** Once production runs the release, `releases/<semver>` is cut at X, one
   commit adds the bill of materials, `make check-release-record` passes, and that
   commit is tagged `marketplace-v<semver>`.
5. **Publication.** The operator publishes the promoted bytes to PyPI, npm, ghcr and the
   GitHub release, after the cut and all or nothing.

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
- A **release component** is an entry of the declaration (D6).
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
- the `market` binary as generic package `market`, version `<rev9>`, as `push-cli`
  stores it today.

The wheels and the chart go to the repository `<prefix>-candidates`, beside
`<prefix>-cli`, `<prefix>-docker`, `<prefix>-helm` and `<prefix>-python`, all derived from
`AR_PREFIX`. That repository is provisioned outside this repository.

The validated wheels are the candidate's wheelhouse, because images install their wheels
from `.dist` when they are built. A candidate's versions are not unique: the version
check compares only with the previous marketplace release, and the versioning policy
forbids bumping an unreleased version again. So failed candidate A and the next
candidate B routinely carry one wheel version with different bytes. Likewise, a later
candidate or a developer push overwrites a chart's OCI tag, which is its version.
Storing by revision is what makes "the revision names a release candidate" true of every
component rather than of images and the CLI alone.

Reloading a revision first deletes that revision's `wheelhouse` and `chart` versions,
then uploads. The store then always holds exactly one load's declared set, which the
deployment's bill-of-materials builder requires: exactly the declared wheels, each once,
and exactly one chart package whose file name matches its `Chart.yaml`. Development
registries are scratch, every identity in the bill of materials is a content identity,
and validation runs against the last load, so replacing a revision breaks nothing.

Nothing installs from the development Python index, so loading a candidate does not push
to it.

Alternatives considered:
- **Load by version, as before.** Rejected: on a collision the index holds whichever
  upload came last.
- **Load by version, with the candidate replacing a differing file.** Rejected: between
  load and promotion, a later candidate or a developer push can replace the file again,
  and nothing records it.
- **Leave the snapshot to the deployment.** Rejected: the deployment would have to
  reproduce part of this repository's build to know a candidate's bytes.

### D4 — A candidate's revision is nine characters

Every revision tag and store version uses `git rev-parse --short=9`, in the root
Makefile and in `e2e-tests`. The bill of materials tags images `<service>-<rev9>`, and
the local lanes' suffix must equal the revision tags exactly. Git's default abbreviation
grows with the repository: it is nine characters today only by accident.

### D5 — Loading a candidate does not refuse an edited tree

The load targets do not check that the tree is clean. A reload replaces the revision's
stored files (D3), and every identity the bill of materials records is a content
identity. `arkhai:source-revision` therefore rests on the operator's word that the load
came from X.

Alternative rejected: **refuse a tree with uncommitted changes to tracked files**, so the
source revision states which commit produced the bytes. It is not needed for any
identity the record relies on.

### D6 — One declaration of release components

`manifests/published-distributions.json` becomes `manifests/release-components.json`. It
lists only what a release ships, so every entry is released and no `public` flag
exists:

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
  "npm": [{"path": "domains/apicredits/middleware/typescript"}]
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
- **Chart, binaries, npm.** The chart's directory; the binary with its build target and
  output path; the npm package's directory.

Who reads it:
- the publish targets;
- the single-enumeration check (D7);
- the lanes' release-image check (D17);
- the binary build (D18);
- `test_publish_matrix.py`;
- `make check-release-record` (D12);
- the deployment's bill-of-materials builder, which reads `distributions[].dist`,
  `images[].name`, `binaries[].name` and `npm[].path`, and finds the chart from the one
  package stored under the revision.

The Makefile still builds everything. The declaration says what a release comprises, not
how to build it.

### D7 — The single-enumeration and upload-step checks

A check run by `make check-packaging` refuses:
- a list of distributions, images, the chart or the binary in any workflow, publish
  target or lane target, other than the declaration;
- any upload step in a workflow: `pypa/gh-action-pypi-publish`, `npm publish`,
  `docker push`, `docker/build-push-action` with `push: true`,
  `softprops/action-gh-release`, `gh release create`.

No such check exists today, though the task that would have added it is checked off. Two
lists kept in agreement by hand diverge silently, and review alone did not prevent it.

### D8 — Every declared image's build writes its revision tag

With `IMAGE_SUFFIX` empty, every declared image's build writes `arkhai:<local>-<rev9>`
beside its bare tag. `build-bare-metal-storefront` writes none today. A test holds every
declared image to a build target that writes it, extending
`test_image_publication_contract.py`, which covers provisioning only. `push-images`
pushes the declared images through `scripts/publish_artifacts.py`, in place of its four
literal lines, and keeps pushing the bare `arkhai:<name>` tags that shared development
releases follow. No release step reads a bare tag.

### D9 — The chart names no release

A chart's packaged files include its version and its default values. Defaults naming a
release's images would make the chart built at the cut differ from the chart validated,
and would force a new chart version for every release.

- **Version.** `version` follows the chart's own semver and changes only when the chart
  does.
- **Images.** The default values keep the bare development tags with empty digests. A
  deployment names its images in its own values.
- **appVersion.** It means nothing here and is removed from `helm/Chart.yaml` and all
  eight subcharts, with the `app.kubernetes.io/version` block in each `_helpers.tpl`.
  That block is guarded by `if .Chart.AppVersion`, so leaving it would be dead template.
  The removal changes each chart's packaged files, so each chart's version is bumped.

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
  | npm | `library`, group `@arkhai` | the package's | SHA-512 of the tarball; while no development registry holds it, property `arkhai:loaded` = `false` and no hashes |

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
5. it names every declared component;
6. `make check-release-versions` passes against the marketplace release before it.

It shares its reader with the version check.

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
- aliasing images to `<service>-<semver>` at promotion;
- cutting only after production runs the release;
- publishing only after the cut, with promoted bytes, all or nothing, never replacing or
  deleting a version, and wheels only, since no sdist is built at the cut.

A spec states the implemented normative contract. Requirements no part of this
repository implements or can test would be permanent text describing someone else's
internals, and they would go stale silently when the deployment changes.

Alternative rejected: **keep the deployment's acts as normative requirements here.**

### D14 — A version changes when its contents change

`make check-release-versions` reads the bill of materials of the newest
`marketplace-v*` tag that carries one, ordered by semver, and refuses a layout it does
not know. It compares:
- **Wheels:** each `wheel/*` component's version and SHA-256 with the built wheel of the
  same name. It refuses one whose version is unchanged and whose bytes differ.
- **The chart:** the `chart/*` component's version and `arkhai:content-digest` with the
  chart `make dist-helm` packages. It refuses one whose version is unchanged and whose
  digest differs.

The chart's content digest is computed like Go's module dirhash:
1. list the package's regular files by archive path, sorted bytewise;
2. for each, write `<sha256 hex of contents>  <archive path>\n`, with two spaces;
3. take the lowercase SHA-256 hex of that text.

It is computed from a package, never from the source directory, because Helm rewrites
every `Chart.yaml` when packaging and leaves the other files unchanged. `helm package`
archives differ in tar metadata between runs while the files inside are identical. The
rewrite may change between Helm versions, so the check pins Helm.

When no tag carries a bill of materials, the check says so and passes; v0.3.0 carries
none. It runs before a candidate is loaded and again at the cut, and needs only git, the
wheelhouse and the pinned Helm. A refusal means "bump the version"; the check never
chooses one.

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
  `check-python-version` refuses a `[build-system]` backend the declaration does not
  constrain, and a build path that bypasses the export.
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
would change its digest. Wheels, the chart and the npm package keep the versions they
were built with. Images and the binary have no version of their own: they are named by
revision as candidates, and the deployment aliases images to the semver at promotion.
The release semver appears once in the record, on the subject.

### D17 — The local lanes can run a release candidate's images and record them

A release is validated by two suites that must run the same images: this repository's
local lanes, which use test doubles, and the deployment's live end-to-end tests. Images
do not rebuild to the same digest, so a lane that builds its own release images tests
different bytes.

```
make -C e2e-tests test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-07af25d57
```

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

Alternatives rejected:
- **One `CANDIDATE=<rev9>` variable.** A second way to say a suffix.
- **Separate release-image lane targets.** Duplicated recipes drift.

### D18 — The release's `market` binary is PyPI's CLI, built in a pinned image

Today the binary is PyInstaller's freeze of `arkhai_vms_buyer/main.py`, a VM-only app,
built on whatever host runs `make build-buyer`. PyPI's `market` is `core_buyer.cli:main`,
which discovers every buyer domain through `market.buyer_domains` entry points. Two
programs sharing one name is the defect.

- **What gets built.** A `build-market-binary` target freezes `core_buyer.cli:main`
  inside a build image pinned by digest (Debian bookworm, Python 3.13).
- **Which plugins it bundles.** The build installs from `.dist` the declared
  distributions that register `market.buyer_domains` entry points, derived from the
  declaration and never listed in a Dockerfile. It passes `--copy-metadata` for each,
  since discovery reads installed metadata.
- **The smoke test.** The build image checks that `market plugins` lists every bundled
  domain. No validation suite runs the binary, so this is what exercises it.
- **Repeatability.** Pinning the image fixes the Linux floor, not repeatability.
  PyInstaller output is never byte-for-byte repeatable. The binary is identified by the
  SHA-256 of the stored file, and a reload replaces it.
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

### D19 — The npm package is declared but not loaded until a development registry serves npm

The middleware package is declared, built and tested. `push-npm` is added once a
development registry serves npm, which is provisioned outside this repository. Until
then, layout 1 carries it with `arkhai:loaded` = `false`.

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
   deleted); the declaration renamed and reshaped; the single-enumeration and
   upload-step checks.
2. Candidate loading: the candidate store with delete-then-upload, `--short=9`, every
   declared image's revision tag, `push-images` from the declaration; the hatchling pin
   and its check; `appVersion` removed.
3. The layout-1 reader, `make check-release-versions` and `make check-release-record`.
4. The lanes' release-image mode and its record.
5. The binary's build image, and PyInstaller out of `arkhai-vms-buyer`'s runtime
   dependencies.

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
- **The npm package cannot be loaded until a development registry serves npm** (D19).
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
