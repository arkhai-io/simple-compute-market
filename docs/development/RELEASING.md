# Releasing Python packages

`.github/workflows/publish-pypi.yml` publishes the project's Python
packages to PyPI.

Registries, storefronts, provisioning, buyers, and the metering
middleware are roles that operators, sellers, and buyers install and run
independently. Each of those roles is published, along with the
libraries and SDK clients they build on. Three packages are not roles
and are not published: the end-to-end test harness (`arkhai-e2e-tests`),
the demo API it drives (`arkhai-apicredits-sample-app`), and the
issue-discovery development tool (`scm-issue-discovery`).

Distribution names are prefixed `arkhai-`. PyPI does not namespace
distribution names by organization, so the prefix is the project's
namespace. Import names and console scripts (`market`,
`market-storefront`, `market-policy`) are independent of the
distribution name.

## Published packages

"Internal deps" are a package's dependencies on other repository
distributions, required ones first and then those an extra adds. Every one of
them is itself in this table: a published package installs from PyPI alone, so
a dependency the table omits leaves it uninstallable. Each package's version is
the one its `pyproject.toml` declares.

| Package | Path | Internal deps |
|---|---|---|
| `arkhai-kit-alkahest` | `kit/alkahest/` | `arkhai-kit-settlement-runtime` |
| `arkhai-kit-config` | `kit/config/` | `arkhai-kit-settlement-runtime` |
| `arkhai-kit-identity` | `kit/identity/` | none |
| `arkhai-kit-arkhai-payments` | `kit/arkhai-payments/` | `arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-policy` | `kit/policy/` | `arkhai-kit-identity` |
| `arkhai-kit-settlement-runtime` | `kit/settlement-runtime/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-kit-negotiation-runtime` | `kit/negotiation-runtime/` | `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-core` | `core/` | none |
| `arkhai-core-buyer` | `core/buyer/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-delivery`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-core-storefront` | `core/storefront/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-core-storefront-client` | `core/storefront-client/` | `arkhai-kit-identity` |
| `arkhai-core-registry-client` | `core/registry-client/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-core-registry` | `core/registry/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-kit-site` | `kit/site/` | `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-site-client` | `kit/site-client/` | `arkhai-kit-identity` |
| `arkhai-kit-capability-shape` | `kit/capability-shape/` | none |
| `arkhai-kit-capability-pricing` | `kit/capability-pricing/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-capacity-publication` | `kit/capacity-publication/` | `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-kit-site-client` |
| `arkhai-kit-contact-exchange` | `kit/contact-exchange/` | `arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-delivery` | `kit/delivery/` | `arkhai-kit-identity` |
| `arkhai-kit-delivery-apprise` | `kit/delivery-apprise/` | `arkhai-kit-delivery` |
| `arkhai-kit-fulfillment` | `kit/fulfillment/` | `arkhai-core`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-site` |
| `arkhai-kit-pool-overrides` | `kit/pool-overrides/` | `arkhai-kit-identity`, `arkhai-kit-site-client` |
| `arkhai-kit-resource-pools` | `kit/resource-pools/` | `arkhai-kit-capability-shape`, `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-resource-pools-contracts` | `kit/resource-pools-contracts/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-resource-pools-client` | `kit/resource-pools-client/` | `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-storefront` | `kit/storefront/` | `arkhai-core-storefront`, `arkhai-kit-alkahest`, `arkhai-kit-negotiation-runtime` |
| `arkhai-compute` | `domains/compute/` | `arkhai-kit-capability-shape` |
| `arkhai-bare-metal` | `domains/bare_metal/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-shape` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-bare-metal-storefront` | `domains/bare_metal/storefront/` | `arkhai-bare-metal`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-contact-exchange`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-bare-metal-buyer` | `domains/bare_metal/buyer/` | `arkhai-bare-metal`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-core-registry-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-delivery`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-bare-metal-provisioning-adapter` | `domains/bare_metal/provisioning/adapter/` | `arkhai-bare-metal`, `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools` |
| `arkhai-vms` | `domains/vms/domain/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-pricing`, `arkhai-kit-capability-shape` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-vms-listings` | `domains/vms/listings/` | `arkhai-kit-alkahest`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime`, `arkhai-vms` (`pools` extra: `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`) (`overrides` extra: `arkhai-kit-pool-overrides`) |
| `arkhai-vms-negotiation` | `domains/vms/negotiation/` | `arkhai-kit-alkahest`, `arkhai-kit-policy`, `arkhai-vms-listings` |
| `arkhai-vms-settlement` | `domains/vms/settlement/` | `arkhai-kit-alkahest`, `arkhai-vms-listings` |
| `arkhai-vms-buyer` | `domains/vms/buyer/` | `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation`, `arkhai-vms-settlement` |
| `arkhai-vms-provisioning-operator-client` | `domains/vms/provisioning/client/` | `arkhai-compute-provisioning-contracts` |
| `arkhai-vms-provisioning-adapter` | `domains/vms/provisioning/adapter/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools`, `arkhai-vms`, `arkhai-vms-provisioning-operator-client` |
| `arkhai-compute-provisioning` | `provisioning/compute/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-site` |
| `arkhai-compute-provisioning-contracts` | `provisioning/compute/contracts/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-compute-provisioning-client` | `provisioning/compute/client/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-compute-provisioning-ansible` | `provisioning/compute/ansible/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-config`, `arkhai-kit-resource-pools` |
| `arkhai-compute-provisioning-service` | `provisioning/compute/service/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-storefront-client`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-site` (`adapters` extra: `arkhai-bare-metal-provisioning-adapter`, `arkhai-vms-provisioning-adapter`) |
| `arkhai-vms-storefront` | `domains/vms/storefront/` | `arkhai-bare-metal`, `arkhai-bare-metal-storefront`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site`, `arkhai-kit-site-client`, `arkhai-kit-storefront`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation`, `arkhai-vms-settlement` |
| `arkhai-apicredits-domain` | `domains/apicredits/` | `arkhai-core`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-buyer` | `domains/apicredits/buyer/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-middleware` | `domains/apicredits/middleware/python/` | none (`signed` extra: `arkhai-kit-identity`) |
| `arkhai-apicredits-storefront` | `domains/apicredits/storefront/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-apicredits-service` | `domains/apicredits/service/` | `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-site` |

This set is defined once, by the `PACKAGES` table in the workflow's
`detect-changes` job and the per-package path filters beside it. Adding a
package means one table row, one filter, a row here, and the one-time PyPI
setup below; a package outside every directory the workflow's `push.paths`
names needs an entry there too. `scripts/tests/test_publish_matrix.py` (run by
`make test-release-tooling`; it reads only the tree) fails when a
published package depends on a repository distribution the table omits, when a
package has no filter or push trigger watching its `pyproject.toml`, or when
this table's packages, paths, or internal deps disagree with the workflow and
each `pyproject.toml`.

## How the workflow works

- A push to `main` that touches a package's directory selects the changed
  packages (via `dorny/paths-filter`) and builds a job matrix from them.
- `workflow_dispatch` considers every package in the table.
- Each job checks whether the package's current `version` is already on
  PyPI and skips if so, so a version bump publishes and other commits do
  not.
- Each job builds with `uv build --no-sources` and publishes via OIDC
  trusted publishing.

Most packages publish an sdist and a wheel. Packages marked `wheel_only`
in the table (the two buyer plugins and the VM storefront) are built with
`uv build --wheel` and publish a wheel only.

No package vendors another's modules. Each package builds exactly one import
package from `src/<package>` (see
[`BUILD_AND_PACKAGING.md`](BUILD_AND_PACKAGING.md#project-layout)), so a module
added there ships without a packaging edit. Code another package needs is its
own wheel and a declared dependency: the VM storefront and buyer depend on
`arkhai-vms-listings`, `arkhai-vms-negotiation`, and `arkhai-vms-settlement`
rather than carrying their sources.

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

Before a package reaches 1.0.0 its major version stays at zero: an
incompatible change takes a **minor** bump in place of a major one, and
the other rules apply unchanged. A consumer that depends on the
incompatible behaviour raises its lower bound to the new minor version.
Moving a package to 1.0.0 is a deliberate decision that sets its
compatibility commitment, not a consequence of shipping an incompatible
change.

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
publish round-trip ([`BUILD_AND_PACKAGING.md`](BUILD_AND_PACKAGING.md)). The
publish workflow passes `--no-sources`, so the only sources a published wheel
could record are index pins, such as the PyTorch CPU index.


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
