---
tags: [repository, packaging, versioning, python]
---

# Published packages

Which of this repository's Python distributions are published to PyPI, how they are
named, and what each depends on. How the owner publishes them is
[the release handbook](../../release-handbook.md).

Registries, storefronts, provisioning, buyers, and the metering
middleware are services and tools that operators, sellers, and buyers
install and run independently. Each of them is published, along with the
libraries and SDK clients they build on. Three other packages are not
published: the end-to-end test harness (`arkhai-e2e-tests`),
the demo API it drives (`arkhai-apicredits-sample-app`), and the
issue-discovery development tool (`scm-issue-discovery`). Nor is the lane
doubles' control contract (`lane-double-controls`), which only the end-to-end
harness and the lane doubles import.

The release workflow (`.github/workflows/release.yml`) also attaches a
wheelhouse archive, `marketplace-wheelhouse.tar.gz`, built by `make
dist-release`. The release wheelhouse carries no distribution only tests
depend on: `make dist-release` builds every internal wheel but
`lane-double-controls` and `arkhai-apicredits-sample-app`, and `make dist`
adds those two for the lanes, CI and validation, whose images install them
from `.dist`. `scripts/tests/test_init_targets.py` holds that they are
exactly what `make dist` builds beyond the release set.

Distribution names are prefixed `arkhai-`. PyPI does not namespace
distribution names by organization, so the prefix is the project's
namespace. Import names and console scripts (`market`,
`market-storefront`) are independent of the distribution name.

## Published packages

"Internal deps" are a package's dependencies on other repository
distributions, required ones first and then those an extra adds. Every one of
them is itself in this table: a published package installs from PyPI alone, so
a dependency the table omits leaves it uninstallable. Each package's version is
the one its `pyproject.toml` declares.

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
| `arkhai-vms` | `domains/vms/domain/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-admissibility`, `arkhai-kit-capability-pricing`, `arkhai-kit-capability-shape` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-vms-listings` | `domains/vms/listings/` | `arkhai-kit-alkahest`, `arkhai-kit-capability-admissibility`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts`, `arkhai-vms` (`pools` extra: `arkhai-kit-resource-pools`) (`overrides` extra: `arkhai-kit-pool-overrides`) |
| `arkhai-vms-negotiation` | `domains/vms/negotiation/` | `arkhai-kit-alkahest`, `arkhai-kit-policy`, `arkhai-vms-listings` |
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

This set is defined once, by the `PACKAGES` table in the workflow's
`detect-changes` job and the per-package path filters beside it. Adding a
package means one table row, one filter, a row here, and the owner's one-time PyPI
setup ([the release handbook, "One-time setup for a package"](../../release-handbook.md#one-time-setup-for-a-package));
a package outside every directory the workflow's `push.paths`
names needs an entry there too. `scripts/tests/test_publish_matrix.py` (run by
`make test-release-tooling`; it reads only the tree) fails when a
published package depends on a repository distribution the table omits, when a
package has no filter or push trigger watching its `pyproject.toml`, or when
this table's packages, paths, or internal deps disagree with the workflow and
each `pyproject.toml`.

## One import package each

No package vendors another's modules: each publishes its one import package
([`packaging-python.md`, "One import package per distribution"](../engineering/packaging-python.md#one-import-package-per-distribution);
this repository's layout in
[`project-layout.md`](project-layout.md)). Code
another package needs is its own wheel and a declared dependency: the VM storefront and buyer depend on
`arkhai-vms-listings`, `arkhai-vms-negotiation`, and `arkhai-vms-settlement`
rather than carrying their sources.
