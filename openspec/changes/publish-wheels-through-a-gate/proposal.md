## Why

This repository publishes from its own CI to five channels, and every one of them
publishes something other than what a deployment validated:

- `publish-pypi.yml` uploads to PyPI on every push to `main`, at whatever version each
  `pyproject.toml` states. Python source often changes without a version bump, and
  PyPI is write-once, so a merge can make a version permanently describe different
  code. It has done so: a kit distribution reached PyPI declaring a dependency PyPI
  did not carry, uninstallable outside this repository and correctable only by a
  further version.
- `publish-npm.yml` does the same for the TypeScript credits middleware.
- `release.yml`, on a `marketplace-v*` tag, builds and pushes a storefront image to
  ghcr and attests it. Image builds are not reproducible, so that attested image is
  not the image production runs; for marketplace v0.3.0 the two differ by digest, from
  one commit and one Dockerfile.
- `release-cli.yml`, on a `market-cli-v*` tag, publishes a tarball of the repository's
  source and a curl installer. The installer builds the buyer CLI from that source,
  bypassing the released wheels, and it has stopped working: it fetches the latest
  GitHub release's `install.sh`, and the latest release is now a marketplace release
  that has none.

The deployment already releases differently, and marketplace v0.3.0 went out that way:
it loads a candidate's artifacts into its development registry with this repository's
publish targets, validates them there, copies them unchanged through pre-production
and production, and only then publishes them. What this repository lacks is a
release that matches: a tag cut before anything was validated cannot name what was
validated, and a merge to `main` cannot be a release, because the release's version
and the artifacts it comprises are not known when the merge happens.

## What Changes

- **CI publishes nothing.** No workflow uploads to PyPI, npm, ghcr, a registry, or a
  GitHub release. `publish-pypi.yml`, `publish-npm.yml`, `release.yml` and
  `release-cli.yml` are deleted, with the release contract
  (`arkhai.marketplace-release.v2`) and its verifier. CI builds and tests, including
  building the wheelhouse and resolving every declared distribution against it.
- **A candidate is a `main` commit; a release is a promoted candidate.** After a change
  merges to `main`, the commit is loaded into a development registry with
  `make push-runtime-artifacts`. The revision names a candidate (`<service>-<rev>`
  image tags, the CLI under its revision); the semver names a release, applied only
  when the candidate is promoted. A candidate that fails validation is fixed on `main`
  and the next commit is loaded; nothing is rebased.
- **The chart names no release.** Its version follows its own semver, its default
  values keep the bare development tags, and a deployment selects images by its own
  values. Which chart version a release uses is recorded in the release's bill of
  materials, so one chart version can serve many releases and the chart a deployment
  validated is the chart it ships.
- **One declaration of what a release comprises.** `manifests/published-distributions.json`
  becomes `manifests/release-components.json`, declaring the distributions (with
  whether each is public), the service images, the chart, the CLI binary and the npm
  package. Every publish target reads it; `push-images` gains the bare-metal
  storefront it omits today.
- **A release is recorded on a release branch, last.** Once a release has been deployed
  to production, `releases/<semver>` is cut from the candidate's commit, one commit
  adds the release's bill of materials (CycloneDX, content identities only: names,
  versions, digests and source revisions, never registry locations), and that commit
  is tagged `marketplace-v<semver>`. Public channels are published after the cut. A
  release that fails before production never gets a branch, a tag, or a public
  artifact.
- **A version must change when its contents change.** `make check-release-versions`
  compares the built wheels and the chart with the previous release's bill of
  materials and refuses any whose version is unchanged but whose contents differ. It
  runs before a candidate is loaded and again at the cut.
- **The curl installer is retired.** `install.sh`, `scripts/install-remote.sh` and
  `scripts/build-installer.sh` are deleted, and `market-cli-v*` tags are no longer made.
  The buyer CLI is installed from PyPI, pinned to the release's versions, or as the
  release's `market` binary from its GitHub release.
- **`docs/development/RELEASING.md` describes this repository's half of the release**:
  candidates, the component declaration, the cut and its bill of materials, the
  version check, and that public channels are reached only by the deployment's
  promotion of artifacts it validated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: CI publishes nothing; a candidate is a default-branch commit
  named by its revision and a release a promoted candidate named by its semver; one
  declaration of release components; the chart names no release; a release is
  recorded by a tagged bill-of-materials commit on its release branch; a version
  whose contents changed is refused.

## Dependencies and Related Changes

- Absorbs `promote-releases-from-infrastructure`, which proposed the same retirement of
  CI publication and the `push-images` repair. Its directory is removed with this
  change's redesign.
- `configure-pypi-trusted-publishing` configured trusted publishers so CI could publish
  each release. CI no longer publishes, so its publisher half has no consumer; its
  remaining value is the reviewed distribution graph and the PyPI-only installation
  proof. Narrow or withdraw it in its own design.
- The bill-of-materials format is defined with the deployment's release inventory,
  outside this repository. This repository fixes only what its own documents and
  checks read from it.
- `sign-multi-language-credits-middleware` names the npm workflow this change deletes;
  its npm publication becomes the deployment's.
- The npm package can only be loaded into a development registry once that registry
  serves npm, which is provisioned outside this repository.

## Non-Goals

- No promotion, publication or deployment tooling here. The deployment validates,
  promotes, deploys and publishes; this repository provides the publish targets that
  load a candidate and the declaration that says what a release comprises.
- No guarantee about what a development registry holds under a tag. Development tags,
  including revision tags and the bare tags shared development releases follow, are
  rewritten as developers iterate; a release is identified by the digests its bill of
  materials records, never by a development tag.
- No change to any distribution's version at promotion. A wheel's version is inside
  it, so promotion accepts or refuses it.
- No reproducible image builds. A release records the image digests that were
  validated and copies those.

## Impact

Deletes `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml` and
`release-cli.yml`; `scripts/verify-marketplace-release.py`; `install.sh`,
`scripts/install-remote.sh` and `scripts/build-installer.sh`; and their tests. Touches
`manifests/` (renamed and widened), `scripts/push-distributions.py`,
`scripts/publish_artifacts.py`, the root `Makefile`'s publish targets and the
bare-metal storefront's build target, `helm/Chart.yaml`, `.github/workflows/tests.yml`,
`docs/development/RELEASING.md`, `docs/buyer-quickstart.md`, `README.md`, and the
`deployment-state` specification. No runtime behavior changes.

**Contributor-workflow break:** merging to `main` publishes nothing, and pushing a
`marketplace-v*` or `market-cli-v*` tag runs nothing. A release is cut only through the
release procedure, after production runs it.

**Consumer-visible break:** the curl installer URL stops being served. It already
returns 404.
