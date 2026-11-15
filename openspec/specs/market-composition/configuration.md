---
tags: [repository, configuration, deployment]
---

# Combined storefront configuration

How the combined compute-family storefront is built, configured, and deployed, as
this repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md) and
[`deployment.md`](../../../docs/guidance/engineering/deployment.md). Its listings'
terms are [`storefront-publication`'s](../storefront-publication/configuration.md#listing-bindings-and-storefront-wide-terms-of-sale).

## Combined compute-family storefront

The storefront image installs the shared `arkhai-core-storefront` shell plus
each enabled domain contribution from staged `.dist` wheels. Public
configuration contains a non-empty `storefront_domains` list; every row names
one contribution, exact offering mode, domain identity, and contract version.
Trusted provisioning authorities remain separately configured site bindings.
The Helm chart and Compose profile run one storefront process against one
single-writer SQLite volume; they do not start one container per domain. Under
Helm the list is each agent's `config.storefront_domains`, passed through as
written (see
[`DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration)).

`storefront_domains` is public routing metadata only. Signing credentials,
provider settings, SSH material, tenant credentials, payment-provider objects,
and private domain results remain in service-owned Secret channels and never enter
ConfigMaps, command arguments, images, listing bindings, or migration reports.
Startup rejects missing wheels, duplicate modes/identities, assertion mismatch,
unsupported versions, incomplete capabilities, or recoverable bindings that
the frozen registry cannot resolve.
