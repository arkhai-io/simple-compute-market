# Release handbook

For the owner who publishes this repository's packages and artifacts: how the
publish workflow works, setting up a package for PyPI, cutting a release, deciding a
release's migration floor, the import package renames consumers meet, where artifacts
are pushed, and diagnosing a publish that fails. It sits beside the
[operator handbook](operator-handbook.md), for whoever runs a deployment, and the
[change workflow handbook](change-workflow-handbook.md), for operating the workflow.
What a change must satisfy for its packages to publish — the published set, their
names and dependencies, and how they are versioned — is the repository's guidance:
[`published-packages.md`](guidance/repository/published-packages.md) and
[`package-versions.md`](guidance/repository/package-versions.md).
`.github/workflows/publish-pypi.yml` publishes the Python packages to PyPI.

## How the publish workflow works

- A push to `main` that touches a package's directory selects the changed
  packages (via `dorny/paths-filter`) and builds a job matrix from them.
- `workflow_dispatch` considers every package in the workflow's `PACKAGES` table,
  whose set [`published-packages.md`](guidance/repository/published-packages.md)
  states.
- Each job checks whether the package's current `version` is already on
  PyPI and skips if so, so a version bump publishes and other commits do
  not.
- Each job builds with `uv build --no-sources` and publishes via OIDC
  trusted publishing.

Most packages publish an sdist and a wheel. Packages marked `wheel_only`
in the workflow's table (the two buyer plugins and the VM storefront) are built with
`uv build --wheel` and publish a wheel only.

Build order is not constrained. `uv build --no-sources` builds in an
isolated environment that installs only the build backend, never the
package's own `arkhai-*` dependencies, so no sibling needs to be on PyPI
first. A `workflow_dispatch` run publishes the whole set together; any
brief interval where a dependent wheel is published ahead of its
dependency closes once the run completes, and dependencies use lower
bounds so installs resolve normally afterward.

## One-time setup for a package

Each package needs a trusted-publishing configuration before its first
release, once it has its row in
[`published-packages.md`](guidance/repository/published-packages.md#published-packages):

1. Create the project on PyPI (first publish requires the name to exist).
   Either configure a
   [pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
   (trusted publishing creates the project on the first run), or run
   `uv build --no-sources` locally and `uv publish --token <TOKEN>` once
   with a manually issued token, then switch to trusted publishing.
2. At `https://pypi.org/manage/project/<dist>/settings/publishing/`, add a
   "GitHub Actions" trusted publisher with:
   - **Owner**: `arkhai-io`
   - **Repository**: `simple-compute-market`
   - **Workflow**: `publish-pypi.yml`
   - **Environment**: `pypi-<dist>` — e.g. `pypi-arkhai-core-storefront-client`,
     matching `environment.name` in the workflow (`pypi-${{ matrix.dist }}`).
3. Create the matching environment under the repository's
   Settings → Environments. Default settings are sufficient.

## Cutting a release

1. Run `make audit-secrets` on the commit to be released, and remove — and
   rotate wherever it was used — any credential it lists that is not a
   development fixture.
2. Bump the package's `version` field in its `pyproject.toml`, as
   [`package-versions.md`](guidance/repository/package-versions.md) says.
3. Commit and push to `main` (or merge a PR that touches the package).
4. The workflow detects the path change, rebuilds, and publishes via OIDC
   trusted publishing.

`make audit-secrets` reports what gitleaks' rules find in the tracked tree,
including the rules the public-content checks turn off, and refuses
nothing; most of what it lists is the repository's development fixtures
([`market-change-workflow`'s "Public repository content checks"](../openspec/specs/market-change-workflow/README.md#public-repository-content-checks)).

`workflow_dispatch` forces a publish attempt for every package whose
current version is not yet on PyPI — useful for bringing up the whole set
at once.

## The migration floor

When an official marketplace release is promoted, weigh whether it becomes a
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

## Where artifacts are pushed

Root publishing targets require explicit `AR_PROJECT` and `AR_LOCATION`, supplied
on the make command line or in the environment. `AR_PREFIX` defaults to
`AR_PROJECT`; it selects the repository-name prefix. For example,
`make push-images AR_PROJECT=<project> AR_LOCATION=<region>`.

## Troubleshooting

- **403 from PyPI** — trusted publishing is not configured for the
  package, or the environment name does not match. Check both
  `pypi.org/manage/project/<dist>/settings/publishing` and the workflow's
  `environment.name` (`pypi-<dist>`).
- **400 "version already exists"** — the version-skip check should have
  prevented this. If the PyPI cache was stale, the next push retries.
- **Workflow runs but nothing publishes** — confirm the path filter
  matched, or use `workflow_dispatch`. Files outside `<path>/**` do not
  trigger a publish for that package.
- **Wheel records a workspace path** — `uv build` ran without
  `--no-sources`. The workflow always passes it; locally, run
  `uv build --no-sources` to reproduce the published wheel.
