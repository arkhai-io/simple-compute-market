# Package architecture report

Every rule over every project, with no exception row applied.

## Classification

| Project | Path | Layer | Kind | Scope | Plugin | Source |
|---|---|---|---|---|---|---|
| `arkhai-core` | `core` | core | library | — |  | path |
| `arkhai-core-buyer` | `core/buyer` | composition | executable | — |  | override (align-package-paths-with-layers) |
| `arkhai-core-registry` | `core/registry` | composition | executable | — |  | override (align-package-paths-with-layers) |
| `arkhai-core-registry-client` | `core/registry-client` | kit | client | — |  | override (align-package-paths-with-layers) |
| `arkhai-core-storefront` | `core/storefront` | composition | executable | alkahest |  | override (align-package-paths-with-layers) |
| `arkhai-core-storefront-client` | `core/storefront-client` | kit | client | — |  | override (align-package-paths-with-layers) |
| `arkhai-apicredits-domain` | `domains/apicredits` | specialization | library | alkahest, apicredits, arkhai-payments |  | override (align-package-paths-with-layers) |
| `arkhai-apicredits-buyer` | `domains/apicredits/buyer` | composition | executable | alkahest, apicredits, arkhai-payments | yes | path |
| `arkhai-apicredits-middleware` | `domains/apicredits/middleware/python` | specialization | library | apicredits |  | path |
| `arkhai-apicredits-sample-app` | `domains/apicredits/sample-app` | composition | executable | apicredits |  | path |
| `arkhai-apicredits-service` | `domains/apicredits/service` | composition | executable | apicredits |  | path |
| `arkhai-apicredits-storefront` | `domains/apicredits/storefront` | composition | executable | alkahest, apicredits, arkhai-payments |  | path |
| `arkhai-bare-metal` | `domains/bare_metal` | specialization | library | bare_metal, compute |  | path |
| `arkhai-bare-metal-buyer` | `domains/bare_metal/buyer` | composition | executable | alkahest, arkhai-payments, bare_metal, compute, contact-exchange | yes | path |
| `arkhai-bare-metal-provisioning-adapter` | `domains/bare_metal/provisioning/adapter` | specialization | library | bare_metal, compute |  | path |
| `arkhai-bare-metal-storefront` | `domains/bare_metal/storefront` | composition | executable | alkahest, arkhai-payments, bare_metal, compute, contact-exchange | yes | path |
| `arkhai-compute` | `domains/compute` | specialization | library | compute |  | path |
| `arkhai-vms-buyer` | `domains/vms/buyer` | composition | executable | alkahest, arkhai-payments, compute, contact-exchange, vms | yes | path |
| `arkhai-vms` | `domains/vms/domain` | specialization | library | compute, vms |  | path |
| `arkhai-vms-listings` | `domains/vms/listings` | specialization | library | compute, vms |  | path |
| `arkhai-vms-negotiation` | `domains/vms/negotiation` | specialization | library | compute, vms |  | path |
| `arkhai-vms-provisioning-adapter` | `domains/vms/provisioning/adapter` | specialization | library | compute, vms |  | path |
| `arkhai-vms-provisioning-operator-client` | `domains/vms/provisioning/client` | specialization | client | compute, vms |  | path |
| `arkhai-vms-settlement` | `domains/vms/settlement` | specialization | library | alkahest, compute, vms |  | override (align-package-paths-with-layers) |
| `arkhai-vms-storefront` | `domains/vms/storefront` | composition | executable | alkahest, arkhai-payments, compute, contact-exchange, vms | yes | path |
| `arkhai-kit-alkahest` | `kit/alkahest` | kit | library | alkahest |  | path |
| `arkhai-kit-arkhai-payments` | `kit/arkhai-payments` | kit | library | arkhai-payments |  | path |
| `arkhai-kit-capability-pricing` | `kit/capability-pricing` | kit | library | — |  | path |
| `arkhai-kit-capability-shape` | `kit/capability-shape` | kit | library | — |  | path |
| `arkhai-kit-capacity-publication` | `kit/capacity-publication` | kit | library | — |  | path |
| `arkhai-kit-config` | `kit/config` | kit | library | — |  | path |
| `arkhai-kit-contact-exchange` | `kit/contact-exchange` | kit | library | contact-exchange |  | path |
| `arkhai-kit-delivery` | `kit/delivery` | kit | library | — |  | path |
| `arkhai-kit-delivery-apprise` | `kit/delivery-apprise` | kit | library | — | yes | path |
| `arkhai-kit-fulfillment` | `kit/fulfillment` | kit | library | — |  | path |
| `arkhai-kit-identity` | `kit/identity` | kit | library | — |  | path |
| `arkhai-kit-negotiation-runtime` | `kit/negotiation-runtime` | kit | library | — |  | path |
| `arkhai-kit-policy` | `kit/policy` | kit | library | — |  | path |
| `arkhai-kit-pool-overrides` | `kit/pool-overrides` | kit | library | — |  | path |
| `arkhai-kit-resource-pools` | `kit/resource-pools` | kit | library | — |  | path |
| `arkhai-kit-resource-pools-client` | `kit/resource-pools-client` | kit | client | — |  | path |
| `arkhai-kit-resource-pools-contracts` | `kit/resource-pools-contracts` | kit | contracts | — |  | path |
| `arkhai-kit-settlement-runtime` | `kit/settlement-runtime` | kit | library | — |  | path |
| `arkhai-kit-site` | `kit/site` | kit | library | — |  | path |
| `arkhai-kit-site-client` | `kit/site-client` | kit | client | — |  | path |
| `arkhai-kit-storefront` | `kit/storefront` | kit | library | — |  | path |
| `arkhai-compute-provisioning` | `provisioning/compute` | specialization | library | compute |  | override (align-package-paths-with-layers) |
| `arkhai-compute-provisioning-ansible` | `provisioning/compute/ansible` | specialization | library | compute |  | override (align-package-paths-with-layers) |
| `arkhai-compute-provisioning-client` | `provisioning/compute/client` | specialization | client | compute |  | override (align-package-paths-with-layers) |
| `arkhai-compute-provisioning-contracts` | `provisioning/compute/contracts` | specialization | contracts | compute |  | override (align-package-paths-with-layers) |
| `arkhai-compute-provisioning-service` | `provisioning/compute/service` | composition | executable | bare_metal, compute, vms |  | override (align-package-paths-with-layers) |

## Findings

### layer

| Site | Project | Target | Finding | Classification |
|---|---|---|---|---|
| `domains/bare_metal/src/arkhai_bare_metal/storefront_adapter.py:13` +1 | `arkhai-bare-metal` | `arkhai-core-storefront` | a specialization depends on arkhai-core-storefront, a composition | defect, owned by `kit-owned-storefront-auth-and-persistence` |
| `kit/capacity-publication/src/market_capacity_publication/capacity.py:16` +8 | `arkhai-kit-capacity-publication` | `arkhai-core-storefront` | a kit depends on arkhai-core-storefront, a composition | defect, owned by `kit-owned-storefront-auth-and-persistence` |
| `kit/storefront/src/market_storefront_kit/composition.py:16` +7 | `arkhai-kit-storefront` | `arkhai-core-storefront` | a kit depends on arkhai-core-storefront, a composition | defect, owned by `kit-owned-storefront-auth-and-persistence` |
| `domains/vms/domain/src/arkhai_vms/storefront_adapter.py:14` +1 | `arkhai-vms` | `arkhai-core-storefront` | a specialization depends on arkhai-core-storefront, a composition | defect, owned by `kit-owned-storefront-auth-and-persistence` |

### scope

| Site | Project | Target | Finding | Classification |
|---|---|---|---|---|
| `kit/policy/src/market_policy/scalar_policies.py:172` (try) | `arkhai-kit-policy` | `arkhai-kit-alkahest` | depends on arkhai-kit-alkahest, which knows alkahest outside its scope {} | defect, owned by `move-escrow-into-alkahest` |
| `kit/storefront/src/market_storefront_kit/alkahest_clients.py:37` (function) +1 | `arkhai-kit-storefront` | `arkhai-kit-alkahest` | depends on arkhai-kit-alkahest, which knows alkahest outside its scope {} | defect, owned by `move-escrow-into-alkahest` |
| `domains/vms/listings/src/arkhai_vms_listings/buyer_cli.py:71` (function) +6 | `arkhai-vms-listings` | `arkhai-kit-alkahest` | depends on arkhai-kit-alkahest, which knows alkahest outside its scope {compute, vms} | defect, owned by `move-escrow-into-alkahest` |
| `domains/vms/negotiation/src/arkhai_vms_negotiation/policies.py:167` (try) +1 | `arkhai-vms-negotiation` | `arkhai-kit-alkahest` | depends on arkhai-kit-alkahest, which knows alkahest outside its scope {compute, vms} | defect, owned by `move-escrow-into-alkahest` |
| `domains/vms/storefront/pyproject.toml:32` (declaration) | `arkhai-vms-storefront` | `arkhai-bare-metal` | depends on arkhai-bare-metal, which knows bare_metal outside its scope {alkahest, arkhai-payments, compute, contact-exchange, vms} | defect, owned by `kit-owned-storefront-shell` |
| `domains/vms/storefront/pyproject.toml:33` (declaration) | `arkhai-vms-storefront` | `arkhai-bare-metal-storefront` | depends on arkhai-bare-metal-storefront, which knows bare_metal outside its scope {alkahest, arkhai-payments, compute, contact-exchange, vms} | defect, owned by `kit-owned-storefront-shell` |

### vocabulary

| Site | Project | Target | Finding | Classification |
|---|---|---|---|---|
| `core/src/market_core/schemas.py:332` | `arkhai-core` | `alkahest.v1` | names 'alkahest.v1', the identity of alkahest, outside its scope | defect, owned by `move-escrow-into-alkahest` |
| `kit/config/src/market_config/settlement_migration.py:24` | `arkhai-kit-config` | `alkahest.v1` | names 'alkahest.v1', the identity of alkahest, outside its scope | defect, owned by `deduplicate-dynaconf-bootstrap` |

### undeclared_import

| Site | Project | Target | Finding | Classification |
|---|---|---|---|---|
| `core/storefront/src/core_storefront/refund.py:120` (function) | `arkhai-core-storefront` | `arkhai-kit-alkahest` | imports arkhai-kit-alkahest, which its pyproject.toml does not declare | defect, owned by `move-escrow-into-alkahest` |
| `kit/alkahest/src/market_alkahest/aggregation.py:171` (try) | `arkhai-kit-alkahest` | `arkhai-kit-config` | imports arkhai-kit-config, which its pyproject.toml does not declare | defect, owned by `move-escrow-into-alkahest` |
| `kit/policy/src/market_policy/scalar_policies.py:172` (try) | `arkhai-kit-policy` | `arkhai-kit-alkahest` | imports arkhai-kit-alkahest, which its pyproject.toml does not declare | defect, owned by `move-escrow-into-alkahest` |

## Declarations without an import

| Project | Dependency | Reason |
|---|---|---|
| `arkhai-bare-metal-buyer` | `arkhai-kit-alkahest` | Installs Alkahest's named buyer aggregation policies, which the core buyer discovers through market.buyer_aggregation_policies. |
| `arkhai-vms-storefront` | `arkhai-bare-metal` | Registers the bare-metal storefront domain, which the compute-family shell discovers through market.storefront_domains. |

## Resolved in the audit

Findings whose remedy was purely declarative were fixed in this change rather than
seeded as rows. Each changed no edge the rules permit, no behaviour, and no
package's place (`design.md`, "Audit before gate").

| Project | Change | Finding it resolved | Specifier and reason |
|---|---|---|---|
| `arkhai-kit-storefront` | declares `arkhai-core>=0.4.0` | undeclared import | matches `arkhai-core-storefront`, which provided it transitively |
| `arkhai-kit-storefront` | declares `arkhai-kit-identity==0.4.0` | undeclared import | matches the pin `arkhai-core-storefront` carries |
| `arkhai-bare-metal-storefront` | declares `arkhai-core-registry-client>=0.12.1` | undeclared import | matches `arkhai-core-storefront` and `arkhai-kit-capacity-publication` |
| `arkhai-apicredits-buyer` | declares `arkhai-kit-identity==0.4.0` | undeclared import | matches the pin `arkhai-core-buyer` carries |
| `arkhai-bare-metal-buyer` | drops `arkhai-kit-config`, `arkhai-kit-delivery`, `arkhai-kit-policy` | unused declaration ×3 | never imported; the core buyer declares and uses all three |
| `arkhai-core-storefront` | drops `arkhai-kit-policy` | unused declaration | never imported or discovered; every importer of `market_policy` declares it |
| `arkhai-kit-capacity-publication` | drops `arkhai-core-registry-client` | unused declaration | the registry client is injected through a factory, never imported |
| `arkhai-compute-provisioning` | drops `arkhai-kit-identity` | unused declaration | never imported; its contracts declare it |
| `arkhai-vms-buyer` | moves `arkhai-vms-settlement` to its `dev` dependency group | unused declaration | never imported by the package; one of its tests checks escrow selection against the settlement codec |

Two unimported declarations have a runtime reason (above), which each declaring
package now gives in its own `pyproject.toml` under
`[tool.arkhai.architecture.runtime-dependencies]`. Three more install plugins —
`arkhai-kit-delivery-apprise` on both compute storefronts and
`arkhai-bare-metal-storefront` on the VM storefront — and need no reason. The audit found twelve declared-but-unimported internal dependencies across
seven projects, not the thirteen first counted.

`core/storefront`'s other undeclared imports, `web3` and `fastapi`, are third-party
and outside this check; `type-core-packages`' ratchet catches them.

## Reconciliation with "Where the current tree diverges"

| Outline entry | In this baseline |
|---|---|
| The compute family kit and the repository-wide roles and clients sit under directories that say the wrong layer | override rows owned by `align-package-paths-with-layers` |
| The VM storefront is the compute-family shell living under one domain's directory | two scope rows owned by `kit-owned-storefront-shell` |
| `core/storefront` is a composition two kits and both compute vocabulary packages depend on | four layer rows owned by `kit-owned-storefront-auth-and-persistence` |
| `core/storefront` and five other packages import distributions they do not declare | three undeclared-import rows owned by `move-escrow-into-alkahest`; the other four were declared in the audit |
| Declared internal dependencies with no import and no recorded reason | resolved in the audit: seven removed, two reasons recorded, three plugin installs |
| Two foundation kits and the storefront kit depend on `kit/alkahest` | `kit/policy` and `kit/storefront` rows owned by `move-escrow-into-alkahest`. Only one foundation kit imports `kit/alkahest`; `kit/config` names Alkahest's identity, which is the vocabulary row below |
| `kit/alkahest` reads `kit/config` | an undeclared-import row owned by `move-escrow-into-alkahest`; reading a configuration file is a content judgement the rules do not make |
| `kit/config` imports the settlement runtime and carries mechanism identifiers | the import is a legal kit-to-kit edge; the `alkahest.v1` literal is a vocabulary row owned by `deduplicate-dynaconf-bootstrap` |
| `kit/site` imports the pool authority | not visible to the layer and scope rules; `design.md`, "The kit-area order is not encoded" |
| Three read-only pool declaration modules sit in the pool authority rather than its contracts | a placement judgement; not visible to the rules |
| `market_core.schemas` carries Alkahest-shaped escrow fields | the `alkahest.v1` vocabulary row owned by `move-escrow-into-alkahest`; field shapes are not literals |
