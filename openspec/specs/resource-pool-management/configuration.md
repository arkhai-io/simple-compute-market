---
tags: [repository, configuration, deployment]
---

# Pool configuration

How the provisioning service is given the pools this capability declares, and what
it refuses of them at startup, as this repository's instance of
[`definition-documents.md`](../../../docs/guidance/engineering/definition-documents.md)
and [`deployment.md`](../../../docs/guidance/engineering/deployment.md). The method
the provisioning service's documents follow, and the order startup imports them in,
are
[`physical-provisioning`'s "Definition documents"](../physical-provisioning/configuration.md#definition-documents).

## A stored pool the service cannot serve refuses startup

A service refuses to start on its own incoherent state, never on a dependency
([`deployment.md`](../../../docs/guidance/engineering/deployment.md#a-service-refuses-to-start-on-its-own-incoherent-state-never-on-a-dependency)).
The provisioning service refuses to start while a
stored resource pool lacks valid advertisement and backing declarations, or names a
provider no handler in its build serves, naming each pool and provider: handlers are
fixed by the build and every write refuses an unknown provider, so such a row comes
from outside the service's write paths, and no pool document can repair it.

## Pool definitions

`pool_definitions_path` names the pool document, a top-level `pools` list; the
provisioning chart sets it from `definitions.pools`. A site that configures none
and stores no pool is seeded once from the document `pool_seed_path` names,
packaged as `seed/pools.yaml` beside the service's `settings.toml`; under Helm
another seed is supplied through `configFiles`. The contract is
[resource-pool management](spec.md);
the format, the seed, and the steps for moving a pool's members to another
provider are in the operator handbook's
["Pool definitions"](../../../docs/operator-handbook.md#pool-definitions).

A pool absent from the document is **disabled**: the document declares what the
deployment offers, and a pool it does not name should not be scheduled
([`definition-documents.md`, "What a document does to entries it stops naming"](../../../docs/guidance/engineering/definition-documents.md#what-a-document-does-to-entries-it-stops-naming)).
