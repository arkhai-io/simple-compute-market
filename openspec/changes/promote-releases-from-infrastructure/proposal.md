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

- **This repository's CI publishes to no public channel on its own.** `release.yml`
  stops pushing and attesting a ghcr image, and `publish-pypi.yml` loses its push
  trigger. Its manual dispatch stays for one purpose: creating a new distribution's
  PyPI project. A project exists only once something is uploaded to it, and only a
  trusted-publishing upload against a pending publisher the organization registered
  creates it in the organization; an upload with a person's token creates it under that
  person's account. So a distribution's first version is published by dispatching the
  workflow on the release tag, once the organization has registered its pending
  publisher, and every later version is promoted externally. The wheel builds are
  reproducible (marketplace v0.3.0: twenty-seven wheels the workflow published are
  byte-identical to the deployment's), so the bootstrap publishes the same bytes the
  promotion would.
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
  copies those artifacts without rebuilding them, into PyPI projects the organization
  already owns; and how a new distribution's project is created in the organization (its
  pending publisher, then one dispatch on the release tag).

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
- `configure-pypi-trusted-publishing` (ready for design) configures trusted publishers
  for every distribution so CI can publish each release. Publishing each release is no
  longer CI's; its pending publishers remain needed only to create new projects. Its
  scope narrows to that, or folds into this change; its design decides.

## Non-Goals

- No promotion tooling in this repository.
- No removal of trusted publishing: it remains how a new project is created in the
  organization.
- No change to what the release workflow builds into the wheelhouse, or to versioning.
- Artifacts already published for a release stay as they are; PyPI and ghcr keep them.

## Impact

`.github/workflows/publish-pypi.yml`, `.github/workflows/release.yml`,
`scripts/verify-marketplace-release.py` and its tests, `scripts/publish_artifacts.py` and
the `push-images` target, `scripts/tests/test_publish_matrix.py` and
`test_image_publication_contract.py`, `docs/development/RELEASING.md`, and the
`deployment-state` specification. External: the GitHub `pypi-*` environments and the
organization's pending publishers stay, used only for a new project's first version. No runtime behavior changes.
