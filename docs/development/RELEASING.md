# Releasing Python packages

`.github/workflows/publish-pypi.yml` publishes the project's Python
packages to PyPI.

Registries, storefronts, provisioning, buyers, and the metering
middleware are roles that operators, sellers, and buyers install and run
independently. Each of those roles is published, along with the
libraries and SDK clients they build on. Three packages are not roles
and are not published: the end-to-end test harness (`arkhai-e2e-tests`),
the demo API it drives (`arkhai-apitokens-sample-app`), and the
issue-discovery development tool (`scm-issue-discovery`).

Distribution names are prefixed `arkhai-`. PyPI does not namespace
distribution names by organization, so the prefix is the project's
namespace. Import names and console scripts (`market`,
`market-storefront`, `market-policy`) are independent of the
distribution name.

## Published packages

"Internal deps" are dependencies on other packages in this table,
constrained with lower bounds (see Versioning policy).

| Package | Path | Version | Internal deps |
|---|---|---|---|
| `arkhai-core` | `core/` | 0.1.0 | none |
| `arkhai-core-buyer` | `core/buyer/` | 0.1.0 | `arkhai-core`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-kit-policy` |
| `arkhai-core-storefront` | `core/storefront/` | 0.1.0 | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-core-storefront-client` | `core/storefront-client/` | 0.15.0 | none |
| `arkhai-core-registry-client` | `core/registry-client/` | 0.10.0 | none |
| `arkhai-core-registry` | `core/registry/` | 0.1.0 | `arkhai-kit-identity` |
| `arkhai-core-site` | `core/site/` | 0.1.0 | none |
| `arkhai-kit-identity` | `kit/identity/` | 0.1.0 | none |
| `arkhai-kit-policy` | `kit/policy/` | 0.1.0 | none |
| `arkhai-kit-alkahest` | `kit/alkahest/` | 0.1.0 | none |
| `arkhai-kit-config` | `kit/config/` | 0.1.0 | `arkhai-kit-alkahest` |
| `arkhai-vms-buyer` | `domains/vms/buyer/` | 0.1.0 | `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-kit-policy` |
| `arkhai-vms-storefront` | `domains/vms/storefront/` | 0.1.0 | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-vms-provisioning` |
| `arkhai-vms-provisioning` | `domains/vms/provisioning/service/` | 0.5.0 | `arkhai-core-site`, `arkhai-core-storefront-client` |
| `arkhai-apitokens-buyer` | `domains/apitokens/buyer/` | 0.1.0 | `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-kit-policy` |
| `arkhai-apitokens-storefront` | `domains/apitokens/storefront/` | 0.1.0 | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-apitokens-service` | `domains/apitokens/service/` | 0.1.0 | `arkhai-core-site` |
| `arkhai-apitokens-middleware` | `domains/apitokens/middleware/python/` | 0.1.0 | none |

This set is defined once, by the `PACKAGES` table in the workflow's
`detect-changes` job and the per-package path filters beside it. Adding a
package means one table row, one filter, and the one-time PyPI setup
below.

## How the workflow works

- A push to `main` that touches a package's directory selects the changed
  packages (via `dorny/paths-filter`) and builds a job matrix from them.
- `workflow_dispatch` considers every package in the table.
- Each job checks whether the package's current `version` is already on
  PyPI and skips if so, so a version bump publishes and other commits do
  not.
- Each job builds with `uv build --no-sources` and publishes via OIDC
  trusted publishing.

Most packages publish an sdist and a wheel. The two buyer plugins
(`arkhai-vms-buyer`, `arkhai-apitokens-buyer`) publish a wheel only: they
vendor sibling concept modules (`listings`, `negotiation`) through `../`
force-includes that an sdist cannot carry. They are marked `wheel_only`
in the table and built with `uv build --wheel`.

Build order is not constrained. `uv build --no-sources` builds in an
isolated environment that installs only the build backend, never the
package's own `arkhai-*` dependencies, so no sibling needs to be on PyPI
first. A `workflow_dispatch` run publishes the whole set together; any
brief interval where a dependent wheel is published ahead of its
dependency closes once the run completes, and dependencies use lower
bounds so installs resolve normally afterward.

## One-time setup (per package)

Each package needs a trusted-publishing configuration before its first
release:

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

1. Bump the package's `version` field in its `pyproject.toml`.
2. Commit and push to `main` (or merge a PR that touches the package).
3. The workflow detects the path change, rebuilds, and publishes via OIDC
   trusted publishing.

`workflow_dispatch` forces a publish attempt for every package whose
current version is not yet on PyPI — useful for bringing up the whole set
at once.

## Versioning policy

Each package follows [SemVer](https://semver.org):

- **Major** — incompatible API change (e.g. removing a public function,
  changing a returned shape that consumers index into).
- **Minor** — new public API, backwards compatible.
- **Patch** — bug fix or internal change.

Cross-package compatibility is enforced via dependency constraints in
`pyproject.toml`. Use `>=X.Y` (lower bound) for forward compatibility,
or `>=X.Y,<X+1` when a breaking major release is anticipated.

## Local development

`tool.uv.sources` workspace path overrides stay in `pyproject.toml` for
local development — they let `uv sync` pick up sibling-package changes
without a publish round-trip. `uv build --no-sources` strips those
overrides so the built wheel records plain PyPI dependencies; the publish
workflow always passes `--no-sources`.

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
