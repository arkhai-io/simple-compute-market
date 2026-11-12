## Why

This change makes a release mean the bytes a deployment validated. Today this
repository publishes from its own CI to four channels, and every one of them publishes
something other than what a deployment validated:

- `publish-pypi.yml` uploads to PyPI on every push to `main`, at whatever version each
  `pyproject.toml` states. Python source often changes without a version bump, and PyPI
  is write-once, so a merge can make a version permanently describe different code. It
  has done so: a kit distribution reached PyPI declaring a dependency PyPI did not carry,
  uninstallable outside this repository and correctable only by a further version.
- `publish-npm.yml` does the same for the TypeScript credits middleware.
- `release.yml`, on a `marketplace-v*` tag, builds and pushes a storefront image to ghcr
  and attests it. Image builds are not reproducible, so that attested image is not the
  image production runs.
- `release-cli.yml`, on a `market-cli-v*` tag, publishes a tarball of the repository's
  source and a curl installer to a GitHub release. The installer builds the buyer CLI
  from that source, bypassing the released wheels, and it has stopped working: it
  fetches the latest GitHub release's `install.sh`, and the latest release is now a
  marketplace release that has none.

The deployment already releases differently, and marketplace v0.3.0 went out that way.
It loads a candidate's artifacts into its development registry with this repository's
publish targets, validates them there, copies them unchanged through pre-production and
production, and only then publishes them. What this repository lacks is a release that
matches. A tag cut before anything was validated cannot name what was validated. A merge
to `main` cannot be a release, because the release's version and the artifacts it
comprises are not known when the merge happens.

## What Changes

- **CI publishes nothing.** The four workflows are deleted, with the release contract
  (`arkhai.marketplace-release.v2`) and its verifier. CI builds and tests, including
  building the wheelhouse and resolving every declared distribution against it. A check
  refuses any upload step in a workflow.
- **A release candidate is a `main` commit stored under its revision.** Loading it stores
  every release component under the commit's nine-character revision:
  - images as `arkhai:<name>-<rev9>`;
  - the declared wheels and the chart package as generic packages `wheelhouse` and
    `chart` in a candidate store;
  - the `market` binary as today.

  A reload replaces the revision's stored files. A **marketplace release** is a promoted
  release candidate, named by its semver.
- **One declaration of release components.** `manifests/published-distributions.json`
  becomes `manifests/release-components.json`, declaring the distributions, the five
  service images (each by published and local name), the chart, the `market` binary and
  the npm package. It lists only what a release ships: the API-credit sample app leaves
  it, and there is no `public` flag. Every publish target, the lanes and the binary
  build read it, and a check refuses a second list.
- **The chart names no release.** Its version follows its own semver, its defaults keep
  the bare development tags, and `appVersion` is removed from every chart.
- **Wheels build with a pinned backend.** Hatchling is pinned beside `.python-version`.
  Moving the pin is a release-wide version bump.
- **A version must change when its contents change.** `make check-release-versions`
  compares the built wheels (by SHA-256) and the packaged chart (by a digest of its
  packaged files) with the newest marketplace release's bill of materials, and refuses
  an unchanged version whose contents differ.
- **A marketplace release is recorded last, on a release branch.**
  - Once production runs it, `releases/<semver>` is cut at the candidate's commit, one
    commit adds the bill of materials the deployment built (CycloneDX 1.6, layout 1,
    content identities only), and that commit is tagged `marketplace-v<semver>`.
  - `make check-release-record` checks that shape and the document's fields before the
    tag is pushed.
  - `AGENTS.md`'s public-repository discipline is amended to admit that document.
- **The local lanes can run a candidate's release images.** With `RELEASE_IMAGES=1` and
  `IMAGE_SUFFIX=-<rev9>`, a lane runs existing local release images instead of building
  them, and records each one's manifest digest by published name.
- **The release's `market` binary is PyPI's CLI.** It is built in a pinned image with
  every declared buyer domain's plugin. PyInstaller leaves `arkhai-vms-buyer`'s runtime
  dependencies.
- **The curl installer is retired.** `install.sh`, `scripts/install-remote.sh` and
  `scripts/build-installer.sh` are deleted, and `market-cli-v*` tags are no longer made.
- **`docs/development/RELEASING.md` describes this repository's half of the release,**
  and the deployment's part as the procedure this repository relies on.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`:
  - CI publishes nothing.
  - A release candidate is stored under its revision.
  - One declaration of release components.
  - Declared images write revision tags.
  - The chart names no release.
  - Wheels build with a pinned backend.
  - A version whose contents changed is refused.
  - A marketplace release is recorded by a tagged bill-of-materials commit and checked
    at the cut.
  - The local lanes can run a candidate's release images.
  - The release binary is the full buyer CLI.
  - The orphaned release-verification requirement is removed.

## Dependencies and Related Changes

- Absorbs `promote-releases-from-infrastructure`, which proposed the same retirement of
  CI publication and the `push-images` repair. Its directory was removed with this
  change's redesign.
- `configure-pypi-trusted-publishing` configured trusted publishers so CI could publish
  each release. CI no longer publishes, so its publisher half has no consumer. Its
  remaining value is the reviewed distribution graph and the PyPI-only installation
  proof. Narrow or withdraw it in its own design.
- The bill-of-materials format is the deployment's. This repository commits the
  document and reads layout 1's fields.
- `sign-multi-language-credits-middleware` names the npm workflow this change deletes;
  its npm publication becomes the deployment's.
- External, outside this repository:
  - the candidate store's repository;
  - a development registry serving npm, without which the npm package is declared but
    not loaded.

## Non-Goals

- No promotion, publication or deployment tooling here. The deployment validates,
  builds the bill of materials, promotes, deploys and publishes. This repository
  provides:
  - the publish targets that load a candidate;
  - the declaration;
  - the lanes' release-image mode;
  - the checks on the release record.
- No guarantee about what a development registry holds under a tag or a revision.
  Development tags, revision tags and stored revisions are rewritten as developers and
  operators iterate. A release is identified by the content digests its bill of
  materials records.
- No change to any distribution's version at promotion. A wheel's version is inside it.
- No reproducible image, binary or chart-archive builds. A release records what was
  validated and copies that.
- No patch releases from a release branch.

## Impact

**Deleted:**
- `.github/workflows/publish-pypi.yml`, `publish-npm.yml`, `release.yml` and
  `release-cli.yml`;
- `scripts/verify-marketplace-release.py`;
- `install.sh`, `scripts/install-remote.sh` and `scripts/build-installer.sh`;
- and their tests.

**Touched:**
- `manifests/` (renamed and reshaped);
- `scripts/push-distributions.py` and `scripts/publish_artifacts.py`;
- new scripts for the release-record reader and its two checks, the enumeration and
  upload-step check, and the lanes' image record;
- the root `Makefile`'s publish and build targets and `GIT_SUFFIX`;
- `e2e-tests/Makefile` and the compose files' release-image lines;
- the hatchling pin beside `.python-version` and its packaging check;
- a binary build image;
- `domains/vms/buyer/pyproject.toml`;
- every chart's `Chart.yaml` and `_helpers.tpl`;
- `.github/workflows/tests.yml`;
- the `deployment-state` specification.

No runtime behaviour of any service changes.

**Contributor-workflow break:** merging to `main` publishes nothing, and pushing a
`marketplace-v*` or `market-cli-v*` tag runs nothing. A marketplace release is cut only
through the release procedure, after production runs it.

**Consumer-visible break:** the curl installer URL stops being served; it already
returns 404. `arkhai-vms-buyer` no longer installs PyInstaller.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/deployment-state/spec.md` (CI publishes nothing); `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization" (nothing reaches a public channel except bytes a deployment validated); `docs/development/RELEASING.md`
- D2: `openspec/specs/deployment-state/spec.md` (the terms release candidate, marketplace release, release component, candidate store); `docs/development/RELEASING.md`
- D3: `openspec/specs/deployment-state/spec.md` (the candidate store and the reload); `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization" (every identity in a release record is a content identity; development tags, revisions and registry contents guarantee nothing); `docs/development/RELEASING.md`
- D4: `openspec/specs/deployment-state/spec.md`
- D5: `docs/development/RELEASING.md` (the source revision is the operator's word)
- D6: `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`
- D7: `openspec/specs/deployment-state/spec.md`; `docs/development/BUILD_AND_PACKAGING.md` (the checks `make check-packaging` runs)
- D8: `openspec/specs/deployment-state/spec.md`
- D9: `openspec/specs/deployment-state/spec.md`
- D10: `AGENTS.md`, "Public repository discipline" (the bill of materials admitted); `openspec/specs/deployment-state/spec.md` (the layout-1 fields this repository reads); `docs/development/RELEASING.md`
- D11: `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`, "Cutting a release"
- D12: `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`, "Cutting a release"
- D13: `docs/development/RELEASING.md` (the deployment's part of the release)
- D14: `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`
- D15: `openspec/specs/deployment-state/spec.md`; `docs/development/BUILD_AND_PACKAGING.md`; `docs/development/RELEASING.md`, "Versioning policy" (a pin move is a release-wide bump)
- D16: `openspec/specs/deployment-state/spec.md` (within the release-record requirement)
- D17: `openspec/specs/deployment-state/spec.md`; `docs/development/RELEASING.md`; `docs/development/TESTING.md` (the lanes' release-image mode)
- D18: `openspec/specs/deployment-state/spec.md`; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization" (one program per name); `docs/buyer-quickstart.md`
- D19: `docs/development/RELEASING.md`
- D20: `openspec/specs/deployment-state/spec.md` (removed by the delta)
- D21: `docs/development/RELEASING.md`
- D22: no permanent destination — it concerns the change's own directory name
