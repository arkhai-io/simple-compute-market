---
tags: [repository, packaging, versioning, python]
---

# Published packages

What a marketplace release of this repository comprises, which of its Python
distributions are released, how they are named, what each depends on, and how a release
is recorded. A marketplace release is the set of bytes a deployment validated, and
nothing else reaches a public channel: this repository's continuous integration builds
and tests and publishes nothing, merging to `dev` or `main` publishes nothing, and
pushing a tag runs no publishing workflow. How a change versions its packages is
[`package-versions.md`](package-versions.md); how the owner loads, cuts, and publishes a
release is [the release handbook](../../release-handbook.md).

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
of components in a workflow, publish target or lane target
([`packaging-checks.md`](packaging-checks.md#checks)). The Makefile still says how each
component is built: `build-candidate` names its build targets, and a dry-run test holds
it to the declaration, so a component joins the release with its declaration entry
beside its own build.

The npm package of the credits middleware is built and tested but is not a release
component: a package whose candidate bytes cannot be stored under the revision has no
validated bytes. It joins the declaration as
`"npm": [{"path": "domains/apicredits/middleware/typescript"}]` once a development
registry serves npm and a `push-npm` target loads it; until then no marketplace release
records or publishes it.

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
| `arkhai-injected-time` | `tools/injected-time/` | none |
| `arkhai-kit-alkahest` | `kit/alkahest/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-config`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-config` | `kit/config/` | `arkhai-kit-settlement-runtime` |
| `arkhai-kit-identity` | `kit/identity/` | `arkhai-injected-time` |
| `arkhai-kit-deal-lifecycle-contracts` | `kit/deal-lifecycle-contracts/` | `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle` | `kit/deal-lifecycle/` | `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle-client` | `kit/deal-lifecycle-client/` | `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-arkhai-mediation` | `kit/arkhai-mediation/` | `arkhai-injected-time`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-deal-lifecycle-buyer` | `kit/deal-lifecycle-buyer/` | `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-arkhai-payments` | `kit/arkhai-payments/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-deal-servicing` | `kit/deal-servicing/` | `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity` |
| `arkhai-kit-policy` | `kit/policy/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-identity` |
| `arkhai-kit-settlement-runtime` | `kit/settlement-runtime/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-negotiation-runtime` | `kit/negotiation-runtime/` | `arkhai-injected-time`, `arkhai-kit-identity`, `arkhai-kit-policy` |
| `arkhai-core` | `core/` | none |
| `arkhai-core-buyer` | `core/buyer/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-kit-config`, `arkhai-kit-delivery`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-core-storefront` | `core/storefront/` | `arkhai-core`, `arkhai-core-registry-client`, `arkhai-injected-time`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-core-storefront-client` | `core/storefront-client/` | `arkhai-kit-identity` |
| `arkhai-core-registry-client` | `core/registry-client/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-core-registry` | `core/registry/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-site` | `kit/site/` | `arkhai-injected-time`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-site-client` | `kit/site-client/` | `arkhai-injected-time`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-capability-shape` | `kit/capability-shape/` | none |
| `arkhai-kit-capability-admissibility` | `kit/capability-admissibility/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-capability-pricing` | `kit/capability-pricing/` | `arkhai-kit-capability-shape` |
| `arkhai-kit-schema-migrations` | `kit/schema-migrations/` | none |
| `arkhai-kit-capacity-publication` | `kit/capacity-publication/` | `arkhai-core-storefront`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-site-client` |
| `arkhai-kit-contact-exchange` | `kit/contact-exchange/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-identity`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime` |
| `arkhai-kit-delivery` | `kit/delivery/` | `arkhai-injected-time`, `arkhai-kit-identity` |
| `arkhai-kit-delivery-apprise` | `kit/delivery-apprise/` | `arkhai-kit-delivery` |
| `arkhai-kit-fulfillment` | `kit/fulfillment/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |
| `arkhai-kit-pool-overrides` | `kit/pool-overrides/` | `arkhai-kit-identity`, `arkhai-kit-schema-migrations`, `arkhai-kit-site-client` |
| `arkhai-kit-resource-pools` | `kit/resource-pools/` | `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations` |
| `arkhai-kit-resource-pools-contracts` | `kit/resource-pools-contracts/` | `arkhai-kit-capability-admissibility`, `arkhai-kit-capability-shape` |
| `arkhai-kit-resource-pools-client` | `kit/resource-pools-client/` | `arkhai-kit-resource-pools-contracts` |
| `arkhai-kit-storefront` | `kit/storefront/` | `arkhai-core`, `arkhai-core-storefront`, `arkhai-injected-time`, `arkhai-kit-alkahest`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime` |
| `arkhai-compute` | `domains/compute/` | `arkhai-kit-capability-shape` |
| `arkhai-bare-metal` | `domains/bare_metal/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-shape`, `arkhai-kit-resource-pools-contracts` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-bare-metal-storefront` | `domains/bare_metal/storefront/` | `arkhai-bare-metal`, `arkhai-compute`, `arkhai-compute-delivery`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-injected-time`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-bare-metal-buyer` | `domains/bare_metal/buyer/` | `arkhai-bare-metal`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-core-registry-client`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-buyer`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime` |
| `arkhai-bare-metal-provisioning-adapter` | `domains/bare_metal/provisioning/adapter/` | `arkhai-bare-metal`, `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools` |
| `arkhai-vms` | `domains/vms/domain/` | `arkhai-compute`, `arkhai-core`, `arkhai-kit-capability-admissibility`, `arkhai-kit-capability-pricing`, `arkhai-kit-capability-shape`, `arkhai-kit-resource-pools-contracts` (`storefront` extra: `arkhai-core-storefront`) |
| `arkhai-vms-listings` | `domains/vms/listings/` | `arkhai-kit-alkahest`, `arkhai-kit-capability-admissibility`, `arkhai-kit-identity`, `arkhai-kit-resource-pools-contracts`, `arkhai-vms` (`pools` extra: `arkhai-kit-resource-pools`) (`overrides` extra: `arkhai-kit-pool-overrides`) |
| `arkhai-vms-negotiation` | `domains/vms/negotiation/` | `arkhai-core`, `arkhai-kit-alkahest`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-vms`, `arkhai-vms-listings` |
| `arkhai-vms-settlement` | `domains/vms/settlement/` | `arkhai-kit-alkahest`, `arkhai-vms-listings` |
| `arkhai-vms-buyer` | `domains/vms/buyer/` | `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-buyer`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation` |
| `arkhai-vms-provisioning-operator-client` | `domains/vms/provisioning/client/` | `arkhai-compute-provisioning-contracts` |
| `arkhai-vms-provisioning-adapter` | `domains/vms/provisioning/adapter/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools`, `arkhai-kit-schema-migrations`, `arkhai-vms`, `arkhai-vms-provisioning-operator-client` |
| `arkhai-compute-provisioning` | `provisioning/compute/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |
| `arkhai-compute-provisioning-contracts` | `provisioning/compute/contracts/` | `arkhai-core`, `arkhai-kit-identity` |
| `arkhai-compute-delivery` | `domains/compute/delivery/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-capacity-publication`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-identity`, `arkhai-kit-site-client` |
| `arkhai-compute-provisioning-client` | `provisioning/compute/client/` | `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-identity` |
| `arkhai-compute-provisioning-ansible` | `provisioning/compute/ansible/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-kit-config` |
| `arkhai-compute-provisioning-service` | `provisioning/compute/service/` | `arkhai-compute-provisioning`, `arkhai-compute-provisioning-ansible`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-storefront-client`, `arkhai-injected-time`, `arkhai-kit-config`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` (`adapters` extra: `arkhai-bare-metal-provisioning-adapter`, `arkhai-vms-provisioning-adapter`) |
| `arkhai-vms-storefront` | `domains/vms/storefront/` | `arkhai-bare-metal`, `arkhai-bare-metal-storefront`, `arkhai-compute`, `arkhai-compute-delivery`, `arkhai-compute-provisioning-client`, `arkhai-compute-provisioning-contracts`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-injected-time`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capability-admissibility`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-contact-exchange`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-deal-lifecycle-client`, `arkhai-kit-deal-lifecycle-contracts`, `arkhai-kit-deal-servicing`, `arkhai-kit-delivery`, `arkhai-kit-delivery-apprise`, `arkhai-kit-fulfillment`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-pool-overrides`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site`, `arkhai-kit-site-client`, `arkhai-kit-storefront`, `arkhai-vms`, `arkhai-vms-listings`, `arkhai-vms-negotiation`, `arkhai-vms-settlement` |
| `arkhai-apicredits-domain` | `domains/apicredits/` | `arkhai-core`, `arkhai-injected-time`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-payments`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-buyer` | `domains/apicredits/buyer/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-config`, `arkhai-kit-deal-lifecycle`, `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-settlement-runtime` |
| `arkhai-apicredits-middleware` | `domains/apicredits/middleware/python/` | `arkhai-injected-time` (`signed` extra: `arkhai-kit-identity`) |
| `arkhai-apicredits-storefront` | `domains/apicredits/storefront/` | `arkhai-apicredits-domain`, `arkhai-core`, `arkhai-core-registry-client`, `arkhai-core-storefront`, `arkhai-core-storefront-client`, `arkhai-injected-time`, `arkhai-kit-alkahest`, `arkhai-kit-arkhai-mediation`, `arkhai-kit-arkhai-payments`, `arkhai-kit-capacity-publication`, `arkhai-kit-config`, `arkhai-kit-identity`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-policy`, `arkhai-kit-resource-pools`, `arkhai-kit-schema-migrations`, `arkhai-kit-settlement-runtime`, `arkhai-kit-site-client`, `arkhai-kit-storefront` |
| `arkhai-apicredits-service` | `domains/apicredits/service/` | `arkhai-injected-time`, `arkhai-kit-identity`, `arkhai-kit-resource-pools`, `arkhai-kit-resource-pools-contracts`, `arkhai-kit-schema-migrations`, `arkhai-kit-site` |

This table is documentation, held to the declaration: `scripts/tests/test_publish_matrix.py`
(run by `make test-release-tooling`; it reads only the tree) fails when this table's
packages, paths or internal deps disagree with `manifests/release-components.json` and
each `pyproject.toml`, when a declared distribution depends on a repository distribution
the declaration omits, and when the declaration is out of dependency order. Adding a
package means one declaration entry and a row here. A new distribution's PyPI project is
created by the deployment's first upload of it
([the release handbook, "The deployment's part"](../../release-handbook.md#the-deployments-part)).

## One import package each

No package vendors another's modules: each publishes its one import package
([`packaging-python.md`, "One import package per distribution"](../engineering/packaging-python.md#one-import-package-per-distribution);
this repository's layout in
[`project-layout.md`](project-layout.md)), so a module added under its `src/<package>`
ships without a packaging edit. Code another package needs is its own wheel and a
declared dependency: the VM storefront and buyer depend on `arkhai-vms-listings`,
`arkhai-vms-negotiation`, and `arkhai-vms-settlement` rather than carrying their
sources. Dependencies use lower bounds, so an install resolves however the published
set arrived on PyPI.

## The release record

A marketplace release is recorded last, by one commit on `releases/<semver>` adding the
deployment's bill of materials as `manifests/release-bom.cdx.json`, tagged
`marketplace-v<semver>`; what the bill of materials holds is
[`ARCHITECTURE.md`, "The bill of materials"](../../development/ARCHITECTURE.md#the-bill-of-materials).
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
6. the version check passes with the record as its subject
   ([`package-versions.md`, "The version check"](package-versions.md#the-version-check)).

A release branch never grows past its record: a fix lands on `main` and ships in the
next release. There are no patch releases from a release branch: every marketplace
release is cut from a default-branch commit.
