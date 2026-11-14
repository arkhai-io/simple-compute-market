# Releasing

A marketplace release is the set of bytes a deployment validated, and nothing else
reaches a public channel. This repository's continuous integration builds and tests and
publishes nothing: merging to `dev` or `main` publishes nothing, and pushing a tag runs
no publishing workflow. A contributor bumps a package's version where its contents
change ([Versioning policy](#versioning-policy)) and merges; the release procedure below
decides when those bytes ship.

This document describes this repository's half of a release, and the deployment's part
as the procedure this repository relies on. The normative requirements are in the
[deployment and state specification](../../openspec/specs/deployment-state/spec.md);
the architecture they serve is in
[`ARCHITECTURE.md`, "Build, packaging, and initialization"](ARCHITECTURE.md#build-packaging-and-initialization).

## Terms

- A **release candidate** is a default-branch commit loaded under its nine-character
  revision by `make load-candidate`.
- A **marketplace release** is a release candidate the deployment promoted, named by
  its semver and recorded by its `marketplace-v<semver>` tag.
- A **release component** is an entry of the declaration other than a development
  image: a distribution, a release image, the chart, or the binary.
- The **candidate store** is the set of revision-keyed generic packages a release
  candidate's files are stored in.

This document never says a bare "candidate", nor a bare "release" where a Helm release
could be meant.

## What a release comprises

`manifests/release-components.json` is the one declaration of a release's components,
read through `scripts/release_components.py`:

- `distributions`: every published wheel, by key, source path and distribution name, in
  dependency order;
- `images`: the five release images — `registry`, `storefront`, `provisioning`,
  `bare-metal-storefront`, `frp-grant-admission` — each by its published name, which is
  the tag stem in `arkhai:<name>-<rev9>`, and its local build name (`provisioning` is
  built as `compute-provisioning`);
- `chart`: the deployment chart's directory, `helm/`;
- `binaries`: the `market` binary, with its build target and output path;
- `development_images`: dev-env and the e2e-tests image, which a release candidate's
  validation runs and no release ships.

Every key is required except `npm`. The reader refuses a missing or unknown key, a
duplicated name or distribution, a value of the wrong kind, and an `npm` list present
but empty. The publish targets, the load, the lanes' release-image mode and the binary
build read the declaration, and `make check-release-components` refuses a second list
of components in a workflow, publish target or lane target. The Makefile still says how
each component is built: `build-candidate` names its build targets, and a dry-run test
holds it to the declaration, so a component joins the release with its declaration entry
beside its own build.

The npm package of the credits middleware is built and tested but is not a release
component: a package whose candidate bytes cannot be stored under the revision has no
validated bytes. It joins the declaration as
`"npm": [{"path": "domains/apicredits/middleware/typescript"}]` once a development
registry serves npm and a `push-npm` target loads it; until then no marketplace release
records or publishes it.

## The release

1. **Change.** Work lands on `dev` and then `main`. CI builds and tests, including
   building the wheelhouse and resolving every declared distribution against it, and
   publishes nothing.
2. **Release candidate.** An operator loads `main`'s commit with `make load-candidate`
   ([Loading a release candidate](#loading-a-release-candidate)).
3. **Validation and promotion.** The deployment validates the release candidate, builds
   its bill of materials, and promotes it through pre-production to production
   ([The deployment's part](#the-deployments-part)).
4. **Cut.** Once production runs the release, it is recorded on `releases/<semver>`
   and tagged ([Cutting a release](#cutting-a-release)).
5. **Publication.** The operator publishes the promoted bytes, after the cut and all or
   nothing.

A fault found during validation is fixed on `main`, and a later commit becomes the next
release candidate. A release candidate that fails before production gets no branch, no
tag and no public artifact. There are no patch releases from a release branch: every
marketplace release is cut from a default-branch commit.

## Loading a release candidate

Fetch the release tags first (`git fetch --tags <remote>`), since the version check
compares only the tags the checkout holds ([The version check](#the-version-check)).
Then, at the commit to load:

```bash
make load-candidate AR_PROJECT=<project> AR_LOCATION=<region>
```

`AR_PREFIX` defaults to `AR_PROJECT` and names the repositories:
`<prefix>-docker` for images, `<prefix>-cli` for the binary, and `<prefix>-candidates`,
the candidate store, for the wheels and the chart package. The candidate store is
provisioned outside this repository. In one invocation, in this order, the load
(`scripts/load_candidate.py`):

1. builds the wheelhouse once (`make dist`), runs `make check-release-versions` on it,
   and takes its digest (`scripts/wheelhouse_digest.py`);
2. removes each declared image's and development image's local revision tag, then
   builds the binary, the chart package and every declared image and development image
   from that wheelhouse (`make build-candidate`), each image built from `.dist` labelled
   `org.arkhai.wheelhouse-digest`;
3. refuses, uploading nothing and naming what differs, unless the wheelhouse still has
   the digest step 1 took, every image labelled with a wheelhouse digest carries it,
   and every declared component was built;
4. deletes the revision's stored `wheelhouse`, `chart` and binary versions, all of
   them, before uploading any;
5. uploads the declared wheels as generic package `wheelhouse` and the chart package as
   `chart`, version `<rev9>`, in the candidate store, the binary as package `market` in
   `<prefix>-cli`, and pushes every declared image and development image as
   `arkhai:<name>-<rev9>` beside its bare tag.

A load that cannot remove a revision tag, for example because a container still runs
the image, refuses before building. A generic upload cannot replace a file its version
holds, so the deletes are what let a revision be loaded again: the store then holds
exactly one load's declared set for the revision. A reload that fails after the deletes
leaves the revision incomplete, never mixed, and the deployment refuses it until it is
loaded again. No upload keeps an earlier file.

A release candidate's development images are pushed under the revision too, since the
live topology runs them beside the release images; no bill of materials names them, and
the deployment checks them against their revision tags only.

The load does not refuse an edited tree. Every identity a bill of materials records is a
content identity, so the source revision it states rests on the operator's word that
the load came from that commit. Nothing installs from the development Python index, so
the load does not push to it. Development tags, revision tags and stored revisions are
rewritten as developers and operators iterate; a release is identified by the content
digests its bill of materials records, never by what a registry holds under a name.

The candidate store expires stored revisions after a retention period set where it is
provisioned, so a release candidate is promoted before its revision expires. An expired
release candidate is loaded again; images and binaries do not rebuild to the same
digests, so a reload is new bytes and is validated again from the start.

`push-images`, `push-dev-images`, `push-charts` and `push-cli` remain developer pushes
of built artifacts, read from the same declaration. No release step names them.

## The version check

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

It compares the release tags the checkout holds. A checkout that has not fetched since
the last cut, or a shallow or single-branch clone, holds fewer records than were
published, and the check passes against what it holds. So fetch the release tags before
`make load-candidate` and before the cut, and confirm that the check's summary, which
names every tag it compared, names the newest marketplace release. The check stays
offline: at the cut it needs git alone, and no remote name is common to every checkout.

The chart's content digest is computed from a package, never from the source directory,
because Helm rewrites every `Chart.yaml` when packaging:

1. list the package's regular files by archive path, sorted bytewise;
2. for each, write `<sha256 hex of contents>  <archive path>\n`, with two spaces;
3. take the lowercase SHA-256 hex of that text.

A package storing a path more than once is refused, and so is one storing a file Git
ignores under `helm/`: `helm package` reads whatever the directory holds, and
`helm dependency update` leaves a time-stamped `Chart.lock` and subchart archives there.
`helm/.helmignore` names those files. An untracked file Git does not ignore is packaged,
as an edit of the tree is. The chart package includes `helm/`'s tracked tests and
fixtures, so a test-only edit inside `helm/` takes a chart version bump. A Helm bump
edits `.helm-version` and `tests.yml`'s `azure/setup-helm` version together; a test holds
them equal.

The check guards the versions recorded releases name. It is not a complete guard
against PyPI, whose history includes versions no record names. The complete guard is
the deployment's PyPI read ([The deployment's part](#the-deployments-part)); this
repository reads no package registry, so its checks stay offline and deterministic.

## The deployment's part

The deployment owns validation, the bill of materials, promotion and publication. This
repository relies on it to:

- **validate the release candidate** with its live end-to-end tests against the
  revision tags, and with every one of this repository's local lanes run on the same
  images ([Running the lanes on a release candidate's images](#running-the-lanes-on-a-release-candidates-images)).
  The lanes' records together cover every release image but `frp-grant-admission`,
  which only the live tests run;
- **build the bill of materials**, refusing it unless the live pods, the lanes' records
  and the revision tags name the same digests, and unless the candidate store holds
  exactly the declared wheels, one chart package and one binary for the revision;
- **read PyPI**, publicly and without a token, when it builds the bill of materials and
  again immediately before the cut, refusing a release any of whose wheel versions PyPI
  holds with other bytes. The same read surfaces a declared distribution whose PyPI
  project does not yet exist;
- **promote** the release candidate's bytes unchanged to pre-production and production,
  aliasing each image to `<service>-<semver>`;
- **cut only after production runs the release**;
- **publish only after the cut**, the promoted bytes, all or nothing: the wheels to
  PyPI, the images to ghcr and the binary to the GitHub release. It never replaces or
  deletes a version, skips a wheel PyPI already holds with the same SHA-256, and
  publishes wheels only, since no sdist is built.

The first upload of a new distribution creates its PyPI project under the publishing
operator's account; an owner then moves the project into the organization.

For a short while after the cut, production serves a release whose wheels are not yet
on PyPI; nothing in production installs from PyPI.

## The bill of materials

The deployment builds each release's bill of materials and owns its format, since only
it knows which digests passed. This repository commits it at the cut as
`manifests/release-bom.cdx.json` and reads layout 1 of it (`scripts/release_bom.py`):

- CycloneDX 1.6, with no serial number, timestamp or tools entry, so the document's
  identity is the SHA-256 of its bytes;
- its subject, `marketplace`, carries the release semver, the public vcs link, and the
  properties `arkhai:bom-layout` = `1` and `arkhai:source-revision`, the full commit
  every component was built from;
- each component has bom-ref `<kind>/<name>`: a wheel its version and SHA-256, an image
  its manifest digest, the chart its version and `arkhai:content-digest`, the binary
  its SHA-256 and `arkhai:platform` = `linux/amd64`, and a declared npm package its
  version and the SHA-512 of its tarball;
- no registry host, project or path appears anywhere, purls included.

A product version is distinct from a distribution version. Wheels and the chart keep
the versions they were built with; images and the binary have no version of their own.
The release semver appears once, on the subject. The record holds content identities
only, which is why `AGENTS.md`'s public-repository discipline admits it.

## Running the lanes on a release candidate's images

Images do not rebuild to the same digest, so a lane that builds its own release images
tests different bytes. With `RELEASE_IMAGES=1`, a lane runs a release candidate's
images instead:

```bash
make -C e2e-tests pull-release-images DOCKER_REGISTRY=<registry> IMAGE_SUFFIX=-<rev9>
make -C e2e-tests test-e2e-vm RELEASE_IMAGES=1 IMAGE_SUFFIX=-<rev9>
make -C e2e-tests test-e2e-bare-metal RELEASE_IMAGES=1 IMAGE_SUFFIX=-<rev9>
make -C e2e-tests test-e2e-apicredits RELEASE_IMAGES=1 IMAGE_SUFFIX=-<rev9>
```

`pull-release-images` pulls each declared release image as
`<registry>/arkhai:<name><IMAGE_SUFFIX>` and tags it `arkhai:<local><IMAGE_SUFFIX>`,
the name the lanes' Compose files run. The registry is passed in and never committed.
A lane in this mode builds no release image, checks that each release image its Compose
files run is present under the suffix before it tears down or builds anything, and,
once its stack is up, writes and prints `.snapshot/e2e-release-images-<lane>.json`:

```json
{"lane": "bare-metal", "image_suffix": "-<rev9>",
 "images": {"registry": "sha256:…", "provisioning": "sha256:…", "bare-metal-storefront": "sha256:…"}}
```

Each value is the image's manifest digest, read from its repo digest from a registry,
under the image's published name. That value is the image's own manifest digest under a
registry's name: it shows neither that the image was pulled nor that the registry holds
it. The deployment's comparison of the records with the manifests the load pushed is
what ties the lanes to the release candidate. [`TESTING.md`](TESTING.md#locally-verifiable-and-external-topology-scenarios)
describes the mode's refusals.

## Cutting a release

Once production runs the release, and the deployment's PyPI read has passed again:

1. Fetch the release tags, and run `make audit-secrets` on the release candidate's
   commit. Remove — and rotate wherever it was used — any credential it lists that is
   not a development fixture.
2. In a fresh worktree at the release candidate's commit, create `releases/<semver>`,
   add the deployment's bill of materials as `manifests/release-bom.cdx.json` in one
   commit changing nothing else, and tag that commit `marketplace-v<semver>`.
3. Run `make check-release-record TAG=marketplace-v<semver>`, and confirm its version
   check names the newest marketplace release among the tags it compared.
4. Push the branch and the tag.

`make check-release-record` (`scripts/check_release_record.py`) needs no wheelhouse and
no Helm. It refuses unless:

1. the tag's commit is the tip of `releases/<semver>`, locally and as every
   remote-tracking branch of that name as of the last fetch, and its parent is
   reachable from the default branch;
2. the commit changes exactly one path, adding `manifests/release-bom.cdx.json`;
3. the document is layout 1, carries only layout 1's fields, and has no URL but the
   public vcs link;
4. its source revision is the parent commit, and its subject's version is the tag's
   semver;
5. its components are unique and exactly the release components the declaration at
   the parent commit declares, naming each missing, extra and duplicated one; no
   development image appears;
6. the version check passes with the record as its subject.

A release branch never grows past its record: a fix lands on `main` and ships in the
next release.

When a marketplace release is cut, weigh whether it becomes a new migration floor: each
stateful service's chain begins at baselines reproducing the schema of the floor
release, adopts a database that release's chain built, and refuses an older one
([`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](DEPLOYMENT_AND_CONFIG.md#migrations-at-startup)).
A new floor replaces each chain's baselines and floor IDs with the new release's,
deletes the migrations it absorbs, regenerates each service's floor fixture from the
release's published packages as the fixtures' READMEs describe, and leaves deployments
older than the new floor to start from a fresh database. Moving the floor is a decision
about which deployments stay upgradeable, so it is made for each release, not by
default.

`make audit-secrets` reports what gitleaks' rules find in the tracked tree, including
the rules the public-content checks turn off, and refuses nothing; most of what it lists
is the repository's development fixtures
([`ARCHITECTURE.md`, "Public repository content checks"](ARCHITECTURE.md#public-repository-content-checks)).

## Published packages

Registries, storefronts, provisioning, buyers, and the metering middleware are services
and tools that operators, sellers, and buyers install and run independently. Each of
them is published, along with the libraries and SDK clients they build on. Four other
projects are not: the end-to-end test harness (`arkhai-e2e-tests`), the demo API it
drives (`arkhai-apicredits-sample-app`), the issue-discovery development tool
(`scm-issue-discovery`), and the lane doubles' control contract
(`lane-double-controls`), which only the end-to-end harness and the lane doubles import.

`make dist-release` builds the release's wheel set. It carries no distribution only tests
depend on: `make dist` adds `lane-double-controls` and `arkhai-apicredits-sample-app` for
the lanes, CI and validation, whose images install them from `.dist`.
`scripts/tests/test_init_targets.py` holds that they are exactly what `make dist` builds
beyond the release set.

Distribution names are prefixed `arkhai-`. PyPI does not namespace distribution names
by organization, so the prefix is the project's namespace. Import names and console
scripts (`market`, `market-storefront`) are independent of the distribution name.

"Internal deps" are a package's dependencies on other repository distributions, required
ones first and then those an extra adds. Every one of them is itself in this table: a
published package installs from PyPI alone, so a dependency the table omits leaves it
uninstallable. Each package's version is the one its `pyproject.toml` declares.

| Package | Path | Internal deps |
|---|---|---|
| `arkhai-kit-alkahest` | `kit/alkahest/` | `arkhai-core`, `arkhai-kit-config`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-config` | `kit/config/` | `arkhai-kit-settlement-runtime` |
| `arkhai-kit-identity` | `kit/identity/` | none |
| `arkhai-kit-deal-lifecycle-contracts` | `kit/deal-lifecycle-contracts/` | `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle` | `kit/deal-lifecycle/` | `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle-client` | `kit/deal-lifecycle-client/` | `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-arkhai-mediation` | `kit/arkhai-mediation/` | `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle-buyer` | `kit/deal-lifecycle-buyer/` | `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-arkhai-payments` | `kit/arkhai-payments/` | `arkhai-core`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-deal-servicing` | `kit/deal-servicing/` | `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-policy` | `kit/policy/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-kit-settlement-runtime` | `kit/settlement-runtime/` | `arkhai-core`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-negotiation-runtime` | `kit/negotiation-runtime/` | `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-core` | `core/` | none |
| `arkhai-core-buyer` | `core/buyer/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-delivery`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-core-storefront` | `core/storefront/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-core-storefront-client` | `core/storefront-client/` | `arkhai-kit-identity` |
| `arkhai-core-registry-client` | `core/registry-client/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-core-registry` | `core/registry/` | `arkhai-core`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-site` | `kit/site/` | `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-site-client` | `kit/site-client/` | `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-capability-shape` | `kit/capability-shape/` | none |
| `arkhai-kit-capability-admissibility` | `kit/capability-admissibility/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-capability-pricing` | `kit/capability-pricing/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-schema-migrations` | `kit/schema-migrations/` | none |
| `arkhai-kit-capacity-publication` | `kit/capacity-publication/` | `arkhai-core-storefront`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-site-client` |
| `arkhai-kit-contact-exchange` | `kit/contact-exchange/` | `arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-delivery` | `kit/delivery/` | `arkhai-kit-identity` |
| `arkhai-kit-delivery-apprise` | `kit/delivery-apprise/` | `arkhai-kit-delivery` |
| `arkhai-kit-fulfillment` | `kit/fulfillment/` | `arkhai-core`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |
| `arkhai-kit-pool-overrides` | `kit/pool-overrides/` | `arkhai-kit-identity`, `arkhai-kit-schema-migrations`, `arkhai-kit-site-client` |
| `arkhai-kit-resource-pools` | `kit/resource-pools/` | `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-resource-pools-contracts` | `kit/resource-pools-contracts/` | `arkhai-kit-capability-admissibility`, `arkhai-kit-capability-shape` |
| `arkhai-kit-resource-pools-client` | `kit/resource-pools-client/` | `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-storefront` | `kit/storefront/` | `arkhai-core`, `arkhai-core-storefront`, `arkhai-kit-alkahest`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime` |
| `arkhai-compute` | `domains/compute/` | `arkhai-kit-capability-shape` |
| `arkhai-bare-metal` | `domains/bare_metal/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-shape`, `arkhai-kit-resource-pools-contracts` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-bare-metal-storefront` | `domains/bare_metal/storefront/` | `arkhai-bare-metal`, `arkhai-compute`, `arkhai-compute-delivery`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-bare-metal-buyer` | `domains/bare_metal/buyer/` | `arkhai-bare-metal`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-core-registry-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-buyer`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-bare-metal-provisioning-adapter` | `domains/bare_metal/provisioning/adapter/` | `arkhai-bare-metal`, `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools` |
| `arkhai-vms` | `domains/vms/domain/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-admissibility`, `arkhai-kit-capability-pricing`, `arkhai-kit-capability-shape`, `arkhai-kit-resource-pools-contracts` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-vms-listings` | `domains/vms/listings/` | `arkhai-kit-alkahest`, `arkhai-kit-capability-admissibility`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts`, `arkhai-vms` (`pools` extra: `arkhai-kit-resource-pools`) (`overrides` extra: `arkhai-kit-pool-overrides`) |
| `arkhai-vms-negotiation` | `domains/vms/negotiation/` | `arkhai-core`, `arkhai-kit-alkahest`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-vms`, `arkhai-vms-listings` |
| `arkhai-vms-settlement` | `domains/vms/settlement/` | `arkhai-kit-alkahest`, `arkhai-vms-listings` |
| `arkhai-vms-buyer` | `domains/vms/buyer/` | `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-buyer`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation` |
| `arkhai-vms-provisioning-operator-client` | `domains/vms/provisioning/client/` | `arkhai-compute-provisioning-contracts` |
| `arkhai-vms-provisioning-adapter` | `domains/vms/provisioning/adapter/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools`, `arkhai-kit-schema-migrations`, `arkhai-vms`, `arkhai-vms-provisioning-operator-client` |
| `arkhai-compute-provisioning` | `provisioning/compute/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |
| `arkhai-compute-provisioning-contracts` | `provisioning/compute/contracts/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-compute-delivery` | `domains/compute/delivery/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-capacity-publication`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-identity`, `arkhai-kit-site-client` |
| `arkhai-compute-provisioning-client` | `provisioning/compute/client/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-compute-provisioning-ansible` | `provisioning/compute/ansible/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-config` |
| `arkhai-compute-provisioning-service` | `provisioning/compute/service/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-storefront-client`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` (`adapters` extra: `arkhai-bare-metal-provisioning-adapter`, `arkhai-vms-provisioning-adapter`) |
| `arkhai-vms-storefront` | `domains/vms/storefront/` | `arkhai-bare-metal`, `arkhai-bare-metal-storefront`, `arkhai-compute`, `arkhai-compute-delivery`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capability-admissibility`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site`, `arkhai-kit-site-client`, `arkhai-kit-storefront`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation`, `arkhai-vms-settlement` |
| `arkhai-apicredits-domain` | `domains/apicredits/` | `arkhai-core`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-buyer` | `domains/apicredits/buyer/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-middleware` | `domains/apicredits/middleware/python/` | none (`signed` extra: `arkhai-kit-identity`) |
| `arkhai-apicredits-storefront` | `domains/apicredits/storefront/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-resource-pools`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-apicredits-service` | `domains/apicredits/service/` | `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |

This table is documentation, held to the declaration: `scripts/tests/test_publish_matrix.py`
(run by `make test-release-tooling`; it reads only the tree) fails when this table's
packages, paths or internal deps disagree with `manifests/release-components.json` and
each `pyproject.toml`, when a declared distribution depends on a repository distribution
the declaration omits, and when the declaration is out of dependency order. Adding a
package means one declaration entry and a row here.

No package vendors another's modules. Each package builds exactly one import package
from `src/<package>` (see
[`BUILD_AND_PACKAGING.md`](BUILD_AND_PACKAGING.md#project-layout)), so a module added
there ships without a packaging edit. Code another package needs is its own wheel and a
declared dependency: the VM storefront and buyer depend on `arkhai-vms-listings`,
`arkhai-vms-negotiation`, and `arkhai-vms-settlement` rather than carrying their
sources. Dependencies use lower bounds, so an install resolves however the published
set arrived on PyPI.

## Versioning policy

Each package follows [SemVer](https://semver.org):

- **Major** — incompatible API change (e.g. removing a public function,
  changing a returned shape that consumers index into).
- **Minor** — new public API, backwards compatible.
- **Patch** — bug fix or internal change.

Before a package reaches 1.0.0 its major version stays at zero: an
incompatible change to anything the package publishes — its API, a wire
format it sends or accepts, or the meaning of a configuration key it
reads — takes a **minor** bump in place of a major one, and the other
rules apply unchanged. Its users are expected to update; a consumer that
depends on the incompatible behaviour raises its lower bound to the new
minor version. Moving a package to 1.0.0 is a deliberate decision that
sets its compatibility commitment, not a consequence of shipping an
incompatible change.

A contract that carries its own version — a `VersionedEnvelope`'s
`(kind, schema_version)`, a contract version, a protocol identifier — is
never changed in place, before 1.0.0 or after. An incompatible change
defines a new version, and each party states the versions it accepts and
refuses the others, naming what it supports. Before 1.0.0 the release that
introduces a version may stop accepting the one before, so the parties to
it upgrade, and roll back, together. Persisted state keeps its own
migration rules. Neither pre-1.0 allowance applies at or above 1.0.0.
Incompatibility is signalled by the version numbers and the versioned
contracts alone; no per-release list of incompatible changes is kept.

Compatibility is owed to what a release has shipped. A decision made on the
development branch and changed again before any release ships it affects no
one, so revising it needs no compatibility path, migration or deprecation. A
change to anything a release has shipped — its API, a wire format, a
configuration key or a hint it reads — is judged under the rules above, so a key
a release accepted keeps the meaning it had, or loses it only with the bump an
incompatible change takes.

A change bumps each package it changes at most once, measured against the
package's version on the branch the change merges into: that is the version a
release sees. A package already bumped on the change's branch is bumped again
only when a later edit needs a larger bump than the one it has, such as an
incompatible edit to a package bumped only for a fix, and exact pins on it move
only with that bump. Bumping an unreleased version again changes nothing a
release sees and moves every exact pin on it for nothing.

A version changes whenever its contents change: a wheel or the chart whose bytes
differ from what an earlier marketplace release recorded at the same version is refused
by `make check-release-versions` ([The version check](#the-version-check)). The chart's
version follows its own semver and changes only when its packaged files do.

Every wheel's build requirements are pinned in `build-constraints.txt`, beside
`.python-version` ([`BUILD_AND_PACKAGING.md`, "Checks"](BUILD_AND_PACKAGING.md#checks)).
The build backend stamps its version into every wheel, so moving a pin changes every
wheel's bytes: a pin move bumps every declared distribution's patch version once, and the
version check enforces that with no special handling.

### Import package renames

These releases moved each package to one import package under `src/`. The old
import paths were removed without an alias; consumers change their imports and
raise their lower bound to the version shown.

| Package | Release | Import package before | Import package after |
|---|---|---|---|
| `arkhai-vms-buyer` | 0.4.0 | `domains.vms.buyer` | `arkhai_vms_buyer` |
| `arkhai-vms-listings` | 0.4.0 | `domains.vms.listings` | `arkhai_vms_listings` |
| `arkhai-vms-negotiation` | 0.2.0 | `domains.vms.negotiation` | `arkhai_vms_negotiation` |
| `arkhai-vms-settlement` | 0.2.0 | `domains.vms.settlement` | `arkhai_vms_settlement` |
| `arkhai-apicredits-buyer` | 0.4.0 | `domains.apicredits.buyer` | `arkhai_apicredits_buyer` |
| `arkhai-apicredits-domain` | 0.4.0 | `domains.apicredits` | `arkhai_apicredits` |
| `arkhai-core-registry` | 0.3.0 | top-level `api`, `db`, `services`, `types` | `core_registry` |
| `arkhai-apicredits-service` | 0.4.0 | top-level `controllers`, `db`, `middleware`, `models`, `services` | `apicredits_service` |

`arkhai-vms-storefront` 0.8.0 and `arkhai-apicredits-storefront` 0.5.0 import the
renamed packages and require the releases above. The entry-point group
`domains.vms.buyer.aggregation_policies` keeps its name, so installed plugin
packages continue to register without change.

Cross-package compatibility is enforced via dependency constraints in
`pyproject.toml`. Use `>=X.Y` (lower bound) for forward compatibility,
or `>=X.Y,<X+1` when a breaking major release is anticipated.

## Local development

Projects consume sibling packages as wheels from the repository wheelhouse,
never through `tool.uv.sources` path overrides; `make dist` builds the wheels
and `make reinit` refreshes a project's environment from them without a
publish round-trip ([`BUILD_AND_PACKAGING.md`](BUILD_AND_PACKAGING.md)).

## Troubleshooting

- **The load refuses to remove a revision tag** — a container still runs that image.
  Stop it and load again.
- **The load names an image whose wheelhouse label differs, or a wheelhouse whose digest
  moved** — something rebuilt `.dist` or an image during the load. Load again; nothing
  was uploaded.
- **`make check-release-versions` refuses a wheel or the chart** — its contents changed
  since the release it names recorded that version. Bump the version and load again.
- **The version check's summary does not name the newest marketplace release** — the
  checkout lacks its tag. Fetch the release tags and run it again.
- **`make check-release-record` refuses** — its message names the rule. A component
  missing from, or extra in, the bill of materials means the deployment's record and
  the declaration at the release candidate's commit disagree; the record is the
  deployment's to rebuild.
