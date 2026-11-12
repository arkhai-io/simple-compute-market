## ADDED Requirements

### Requirement: Continuous integration publishes nothing

No workflow MUST upload to a public channel, a package or image registry, or a release
page. Continuous integration builds and tests, including building the wheelhouse and
resolving every declared distribution against it. The packaging check MUST refuse a
workflow containing an upload step.

#### Scenario: A change is merged

- **WHEN** a change merges to the default branch
- **THEN** no workflow publishes anything

#### Scenario: A release tag is pushed

- **WHEN** a `marketplace-v*` tag is pushed
- **THEN** no workflow builds or publishes an artifact for it

#### Scenario: A workflow gains an upload step

- **WHEN** a workflow contains a step that publishes to PyPI, npm, an image registry or a
  GitHub release
- **THEN** the packaging check fails and names the workflow and the step

### Requirement: A release candidate is stored under its revision

A release candidate is a default-branch commit loaded by the publish targets; a
marketplace release is a release candidate the deployment promoted, named by its semver.
Loading MUST store every release component under the commit's nine-character revision:
each declared image as `arkhai:<name>-<rev9>`, and the declared wheels, the chart package
and the `market` binary as revision-versioned packages in the candidate store. Reloading
a revision MUST first remove its stored wheels and chart package.

#### Scenario: A candidate is loaded

- **WHEN** a default-branch commit is loaded
- **THEN** every declared image, wheel, chart package and binary is stored under that
  commit's nine-character revision, and the store holds exactly the declared wheels and
  one chart package for it

#### Scenario: A revision is reloaded after a version changed

- **WHEN** a revision is loaded again with a wheel at a different version
- **THEN** the store holds only the new load's wheels for that revision

### Requirement: One declaration of release components

The distributions, service images, chart, binary and npm package a marketplace release
comprises MUST have exactly one declaration, `manifests/release-components.json`, listing
only what a release ships. Each image MUST be declared by its published name and its
local build name. The publish targets, the lanes' release-image check and the binary
build MUST read it, and the packaging check MUST refuse a second list of components in a
workflow, publish target or lane target.

#### Scenario: A component is added

- **WHEN** a service image or distribution joins the release
- **THEN** one declaration is edited, and every publish target loads it without a second
  edit

#### Scenario: A publish target names its own list

- **WHEN** a publish target or workflow lists distributions, images, the chart or the
  binary itself
- **THEN** the packaging check fails and names it

### Requirement: Every declared image's build writes its revision tag

A build with no image suffix MUST tag each declared image as `arkhai:<local>-<rev9>`
beside its bare tag, where `<rev9>` is the nine-character revision of HEAD.

#### Scenario: A declared image is built

- **WHEN** any declared image is built with no image suffix
- **THEN** its local revision tag exists and names the built image

### Requirement: The chart names no release

The deployment chart's version MUST follow the chart's own semver and change only when
the chart's packaged files change. Its default values MUST NOT name a release version, a
revision-suffixed tag or a digest, and no chart MUST declare an `appVersion`.

#### Scenario: Two releases share an unchanged chart

- **WHEN** two marketplace releases are cut and the chart did not change between them
- **THEN** both bills of materials name the same chart version and content digest

#### Scenario: The chart's defaults are rendered

- **WHEN** the chart is rendered with its default values
- **THEN** no image reference carries a semver-shaped tag, a revision suffix or a digest

### Requirement: Wheels build with a pinned backend

The wheel build backend MUST be pinned exactly in one root declaration beside
`.python-version`, which every build target applies. The packaging check MUST refuse a
project whose build backend that declaration does not constrain.

#### Scenario: A project declares an unconstrained backend

- **WHEN** a project's `[build-system]` names a backend the root declaration does not pin
- **THEN** the packaging check fails and names the project

#### Scenario: The pin moves

- **WHEN** the pinned backend version changes
- **THEN** every declared wheel's bytes change, and the version check refuses each
  distribution whose version was not bumped

### Requirement: A version changes when its contents change

`make check-release-versions` MUST read the bill of materials at the newest
`marketplace-v*` tag carrying one, refuse a layout it does not know, and refuse a built
wheel whose version equals that release's and whose SHA-256 differs, or a chart whose
version equals that release's and whose content digest, computed over its packaged files
with the pinned Helm, differs. With no earlier bill of materials it MUST pass and say so.

#### Scenario: A wheel changed without a version bump

- **WHEN** a built wheel has the previous release's version and different bytes
- **THEN** the check fails and names the wheel

#### Scenario: The chart changed without a version bump

- **WHEN** the packaged chart has the previous release's version and a different content
  digest
- **THEN** the check fails and names the chart

#### Scenario: No earlier release carries a record

- **WHEN** no `marketplace-v*` tag carries a bill of materials
- **THEN** the check passes and says that no earlier record exists

### Requirement: A marketplace release is recorded by a tagged commit on its release branch

A marketplace release MUST be recorded as a `releases/<semver>` branch at a
default-branch commit, one commit on it adding only `manifests/release-bom.cdx.json`, and
a `marketplace-v<semver>` tag on that commit. `make check-release-record` MUST refuse a
record of any other shape, one whose source revision is not the branch point or whose
version is not the tag's, one omitting a declared component, or one failing the version
check.

#### Scenario: A well-formed record is checked

- **WHEN** the tag's commit adds only the bill of materials on a release branch cut at a
  default-branch commit, and the document names every declared component
- **THEN** the record check passes

#### Scenario: The release commit changes another file

- **WHEN** the tag's commit changes any path besides the bill of materials
- **THEN** the record check fails and names the path

### Requirement: The release bill of materials holds content identities only

The bill of materials MUST be CycloneDX 1.6 in layout 1. Its subject carries the release
semver, the layout and the full source revision. Each wheel carries its version and
SHA-256, each image its manifest digest, the chart its version and the content digest of
its packaged files, the binary its SHA-256, the npm package its version. It MUST NOT
name a registry host, project or path; the record check refuses any field or URL layout 1
does not admit.

#### Scenario: A bill of materials names a registry

- **WHEN** the release commit's bill of materials carries a purl with a `repository_url`
  or any URL but the repository's public vcs link
- **THEN** the record check fails and names the component

#### Scenario: A product version is assigned

- **WHEN** a release candidate is promoted under a semver
- **THEN** the bill of materials carries the semver on its subject, and every wheel, the
  chart and the npm package keep the versions they were built with

### Requirement: A local lane can run a release candidate's images

With `RELEASE_IMAGES=1`, a local end-to-end lane MUST build no declared release image,
MUST fail naming each declared release image it runs that is missing locally as
`arkhai:<local><IMAGE_SUFFIX>`, and MUST refuse an empty suffix. After its stack starts it
MUST record each release image it runs by published name and manifest digest, failing an
image without exactly one repo digest.

#### Scenario: A lane runs a candidate's pulled images

- **WHEN** a lane runs with `RELEASE_IMAGES=1` and the candidate's suffix, its release
  images present locally
- **THEN** it builds none of them, and its record names each by published name with the
  manifest digest its container runs

#### Scenario: A release image is missing

- **WHEN** a lane runs with `RELEASE_IMAGES=1` and one of its release images is absent
- **THEN** the lane fails before starting its stack and names the image

### Requirement: The release binary is the buyer CLI with every declared buyer domain

The release's `market` binary MUST freeze the same entry point as the published buyer
CLI, bundling every declared distribution that registers a `market.buyer_domains` entry
point, derived from the declaration. It MUST be built in a build image pinned by digest.
No published distribution MUST depend on the freezing tool at run time.

#### Scenario: The binary is built

- **WHEN** the release binary is built
- **THEN** `market plugins` in the build image lists every declared buyer domain

## REMOVED Requirements

### Requirement: Release verification is a publication-time activity

**Reason**: It governs a verifier of externally produced signed releases, and no such
verifier or signed external release remains in the repository.

**Migration**: None. Externally produced dependencies resolve from a declared index, as
"Externally produced dependencies resolve from a declared index" requires.
