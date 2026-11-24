# Release handbook

For the owner who releases this repository's packages and artifacts: how a marketplace
release goes, merging `dev` into `main` and describing the release, loading a release
candidate, what the deployment does with it, running the lanes on its images, cutting a
release, deciding a release's migration floor, the
compatibility paths due to retire, the import package renames consumers meet, and diagnosing a load or a cut that fails. It
sits beside the [operator handbook](operator-handbook.md), for whoever runs a
deployment, and the [change workflow handbook](change-workflow-handbook.md), for
operating the workflow. What a change must satisfy for its packages to release — what a
release comprises, the published set, their names and dependencies, how a release is
recorded, and how a version changes — is the repository's guidance:
[`published-packages.md`](guidance/repository/published-packages.md) and
[`package-versions.md`](guidance/repository/package-versions.md). The terms used here —
release candidate, marketplace release, release component, candidate store — are
[`ARCHITECTURE.md`, "Terms"](development/ARCHITECTURE.md#terms).

This repository's continuous integration publishes nothing: merging to `dev` or `main`
publishes nothing, and pushing a tag runs no publishing workflow. A contributor bumps a
package's version where its contents change and merges; this procedure decides when
those bytes ship.

## The release

1. **Change.** Work lands on `dev` and then `main`, through a release pull request that
   describes the release to its users
   ([The release pull request](#the-release-pull-request)). CI builds and tests,
   including building the wheelhouse and resolving every declared distribution against
   it, and publishes nothing.
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
tag and no public artifact.

## The release pull request

`dev` reaches `main` through one pull request per release. It comes from a branch
`release/merge-dev-to-main-<semver>`, cut from `dev`, with `origin/main` merged into it
and any conflict resolved there, so neither long-lived branch changes until the pull
request merges. It merges with a merge commit, which keeps `dev`'s history on `main`.
That merge commit is the commit loaded as the release candidate.

Its description is the release's notes, written for the people who use the release:
sellers running storefronts and buyers using `market`. It summarizes what they can
now do since the last merge to `main`, and is built in this order:

1. **The roadmap's goals.** Each goal's value statement in
   [`ROADMAP.md`](development/ROADMAP.md) says what its delivered work is worth to a
   user. The description is organized by goal and opens each section with that value.
2. **The archived changes.** Every change archived since the last merge to `main` is
   placed under the goal it serves, from its proposal's Why and What Changes.
3. **The merged pull requests.** The pull requests merged into `dev` in that window
   supply the line items, and their count.

The description has these sections, in order:

- a headline paragraph saying what the release brings since the last merge to `main`,
  with how many pull requests and changes it delivers, followed by "It is the first
  release where:" and its few headline features;
- **upgrade notes and breaking changes**: what an operator or a consumer must do or
  expect on upgrading, including each compatibility path the release first carries and
  any migration floor it sets;
- one section per goal with delivered work, opening with the goal's value, then grouped
  line items, each leading with what a user can now do in one or two lines; a goal the
  release completes is marked complete, and work that ships but is not yet switched on
  for users says so;
- **operations and deployment**: what changes for whoever runs a deployment;
- **known limits**: what the release does not do or has not shown, including
  observations its live evidence left unproven;
- **merge notes**: how `main` was merged into the release branch and any conflict
  resolved.

Work on the repository's own change workflow, guidance and agent tooling is not a user
feature; it is mentioned briefly under operations, if at all. Like every description
here, it is public
([`repository-content.md`](guidance/engineering/repository-content.md)): it names
what a user can see, never a private deployment, host or project.

## Loading a release candidate

First, retire every row of [Compatibility to retire](#compatibility-to-retire)
due at this release, or move it. Then fetch the release tags
(`git fetch --tags <remote>`), since the version check compares only the tags the
checkout holds
([`package-versions.md`, "The version check"](guidance/repository/package-versions.md#the-version-check)),
and, at the commit to load:

```bash
make load-candidate AR_PROJECT=<project> AR_LOCATION=<region>
```

The root publishing targets, this one among them, require explicit `AR_PROJECT` and
`AR_LOCATION`, supplied on the make command line or in the environment. `AR_PREFIX`
defaults to `AR_PROJECT` and names the repositories: `<prefix>-docker` for images,
`<prefix>-cli` for the binary, and `<prefix>-candidates`, the candidate store, for the
wheels and the chart package. `AR_CANDIDATES` names another generic repository as the
candidate store. The candidate store is provisioned outside this repository. In one
invocation, in this order, the load (`scripts/load_candidate.py`):

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

Confirm that the version check's summary, which names every tag it compared, names the
newest marketplace release.

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
of built artifacts, read from the same declaration, under the same `AR_PROJECT` and
`AR_LOCATION` — for example, `make push-images AR_PROJECT=<project> AR_LOCATION=<region>`.
No release step names them.

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

What the bill of materials holds is
[`ARCHITECTURE.md`, "The bill of materials"](development/ARCHITECTURE.md#the-bill-of-materials).

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
what ties the lanes to the release candidate.
[`TESTING.md`, "Release-image mode"](development/TESTING.md#release-image-mode)
describes the mode's refusals.

## Cutting a release

Once production runs the release, and the deployment's PyPI read has passed again:

1. Fetch the release tags, and run `make audit-secrets` on the release candidate's
   commit. Remove — and rotate wherever it was used — any credential it lists that is
   not a development fixture.
2. In a fresh worktree at the release candidate's commit, create `releases/<semver>`,
   add the deployment's bill of materials as `manifests/release-bom.cdx.json` in one
   commit changing nothing else, and tag that commit `marketplace-v<semver>`; and on
   `main`, record the release in `First released in` for each row of
   [Compatibility to retire](#compatibility-to-retire) it first carries, and confirm
   no row names this release in `Retires in`.
3. Run `make check-release-record TAG=marketplace-v<semver>`, and confirm its version
   check names the newest marketplace release among the tags it compared.
4. Push the branch and the tag.

What `make check-release-record` refuses is
[`published-packages.md`, "The release record"](guidance/repository/published-packages.md#the-release-record).
A release branch never grows past its record: a fix lands on `main` and ships in the
next release.

`make audit-secrets` reports what gitleaks' rules find in the tracked tree,
including the rules the public-content checks turn off, and refuses
nothing; most of what it lists is the repository's development fixtures
([`market-change-workflow`'s "Public repository content checks"](../openspec/specs/market-change-workflow/README.md#public-repository-content-checks)).

## The migration floor

When a marketplace release is cut, weigh whether it becomes a
new migration floor: each stateful service's chain begins at baselines
reproducing the schema of the floor release, adopts a database that release's
chain built, and refuses an older one
([`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup);
the floor fixtures' rule is
[`migration-chain-tests.md`](guidance/repository/migration-chain-tests.md)).
A new floor replaces each chain's baselines and floor IDs with the new release's,
deletes the migrations it absorbs, regenerates each service's floor fixture from
the release's published packages as the fixtures' READMEs describe, and leaves
deployments older than the new floor to start from a fresh database. Moving the
floor is a decision about which deployments stay upgradeable, so it is made for
each release, not by default.

## Compatibility to retire

Code kept only for older deployments retires at a stated release
([`package-versions.md`, "Compatibility paths retire on a schedule"](guidance/repository/package-versions.md#compatibility-paths-retire-on-a-schedule)).
Before loading a release candidate, retire on `main` every row due at the release
it will become, removing what the row names, or move the row to a later release
with its reason in the row. When the release is cut, record it in `First
released in` for every row it is the first to carry.

| Compatibility path | First released in | Retires in | What retiring removes | A deployment still holding the old form |
|---|---|---|---|---|
| Adoption of hosts registered before host keys were pinned | — | 0.3.3, or the second release after the one first carrying it, whichever is later | The `hosts` row's pending-adoption flag; the `accept-new` path of the check before a job's start and of the connectivity check; readiness's list of pending hosts | Such a host is unpinned: its jobs are refused until an operator captures or states its key. Readiness lists pending hosts before then |
| Convergence of guests created before guest isolation | — | 0.3.3, or the second release after the one first carrying it, whichever is later | The host kit's `arkhai-guest-converge` command and the host-preparation step installing and running it, which set running guests' bridge isolation and filter | A guest it never converged keeps a port that is not isolated until it is torn down. The host kit reports such guests before then |
| Removal of the per-port guest rules hosts were prepared with before the guest policy | — | 0.3.3, or the second release after the one first carrying it, whichever is later | Host preparation's step deleting the old guest port-22 drops and logs, `ufw allow in on virbr0 from 192.168.122.0/24`, and `vm-network-isolation.service` with its script, and that step's tests | The old rules stay on the host, behind the guest policy's first-position jumps, which decide every guest packet first; an operator may delete them by hand |

## Import package renames

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
