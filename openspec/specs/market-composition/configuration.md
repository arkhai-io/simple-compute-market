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
ConfigMaps, command arguments, images, or listing bindings.
Startup rejects a contribution that is not installed, duplicate modes or
identities, assertion mismatch, unsupported versions, and incomplete
capabilities. It does not read stored bindings: a record whose binding the
frozen registry cannot resolve fails with a binding error when an operation
next resolves it.

The storefront builds its services for the `vm` registration. A row naming
another installed contribution is validated at startup and reported in system
status, and serves nothing
([`ARCHITECTURE.md`, "Capacity publication and multi-domain storefront composition"](../../../docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition)).

## The storefront's time source

Every storefront reads `[Time] source` from its
`storefront.toml`, `"wall"` when unset or `"injected"`; any other value refuses
startup naming `[Time] source` and the value. The composition root installs the
source through `market_storefront_kit.time_controls` before anything reads the
time. Under `"injected"` the storefront starts frozen at the wall instant it
started, logs that at startup, warns when `[Settlement.arkhai_payments]` declares
`livemode = true`, and mounts `POST /api/v1/admin/time` behind its administrator
authentication; its signed system status carries the time section in either mode.
No chart default, production example or shipped storefront file sets it: only the
lanes' storefront configurations do
([`DEPLOYMENT_AND_CONFIG.md`, "The time source"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#the-time-source);
[injected time](../injected-time/architecture.md)).
