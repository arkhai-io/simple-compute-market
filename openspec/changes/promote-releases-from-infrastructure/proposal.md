## Why

This repository publishes to two public channels from its own CI, and both have
produced artifacts that differ from what the deployment validated:

- `release.yml` builds and pushes the storefront image to
  `ghcr.io/arkhai-io/simple-compute-market` and attests it. The deployment builds every
  service image itself from the same tag and promotes those, by digest, through its
  development, pre-production and production registries. Image builds are not
  reproducible, so the attested ghcr image of a release is not the image production
  serves (marketplace v0.3.0: ghcr's storefront and production's differ by digest, from
  one commit and one Dockerfile).
- `publish-pypi.yml` publishes on every push to `main`. Its trusted publishing needs a
  per-project PyPI configuration the workflow cannot create, so a release with new
  distributions fails part-way (v0.3.0: thirty of fifty-seven failed with
  `invalid-publisher`), and whatever a push publishes first is permanent.

The deployment now promotes each release from one build: it loads its development
registry from the release tag with this repository's publish targets, copies the
artifacts unchanged through pre-production and production, and from there publishes
the wheels to PyPI and mirrors the images to ghcr, byte for byte. Publication to a
public channel is that external, human-approved promotion's last step, not this
repository's CI.

## What Changes

- **This repository's CI publishes to no public channel.** `publish-pypi.yml` stops
  publishing (its push trigger, and its publishing job, go), and `release.yml` stops
  pushing and attesting a ghcr image.
- **The release contract no longer names an image.** `release.yml`'s manifest
  (`arkhai.marketplace-release.v2`) carries `service_image`, the ghcr digest; a new
  contract version omits it, or names the image only as a reference the promotion
  fills, and `scripts/verify-marketplace-release.py` and its tests follow. The
  wheelhouse, manifest and provenance remain the release's attested artifacts.
- **`push-images` writes revision tags only and covers every service image.** Today it
  also moves the bare `arkhai:<service>` tags, which shared releases pull, and omits
  the bare-metal storefront; the publish targets become the one way a release is
  loaded into a development registry.
- **`docs/development/RELEASING.md` describes the release as built, loaded and promoted**:
  what this repository produces (a tagged release, its wheelhouse, its publish
  targets), and that public channels are reached only by an external promotion that
  copies those artifacts without rebuilding them. The per-package trusted-publishing
  setup is retired from it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: public publication is an external promotion of artifacts this
  repository built and loaded, never a CI side effect; the release contract and the
  publish targets' tagging follow.

## Dependencies and Related Changes

- `publish-wheels-through-a-gate` (in implementation) owns stopping automated PyPI
  publication and the single distribution enumeration, and plans a promotion step
  here (its Section 4) "conditional on no promotion pipeline consuming these
  artifacts". An external promotion now consumes them, so that section is no longer
  needed. **Design question:** fold this change into it (adding the ghcr, contract,
  tagging and documentation work, and dropping Section 4), or keep this change for
  that work and narrow the other to Sections 1–3. Recommended: fold, since both
  retire the same CI publication path and share `RELEASING.md`.
- `configure-pypi-trusted-publishing` (ready for design) configures the CI trusted
  publishers this change retires; it is superseded.

## Non-Goals

- No promotion tooling in this repository.
- No change to what the release workflow builds into the wheelhouse, or to versioning.
- Artifacts already published for a release stay as they are; PyPI and ghcr keep them.

## Impact

`.github/workflows/publish-pypi.yml`, `.github/workflows/release.yml`,
`scripts/verify-marketplace-release.py` and its tests, `scripts/publish_artifacts.py` and
the `push-images` target, `scripts/tests/test_publish_matrix.py` and
`test_image_publication_contract.py`, `docs/development/RELEASING.md`, and the
`deployment-state` specification. External: PyPI pending publishers and the GitHub
`pypi-*` environments become unused; removing them is the owner's, after no workflow
references them. No runtime behavior changes.
