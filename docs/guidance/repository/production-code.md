---
tags: [repository, implementation]
---

# Production code

How this repository's production code applies
[`implementation.md`](../engineering/implementation.md): its services' layering, where
each piece of a capability's HTTP routes lives, and the libraries it chose.

## Services

Within a service, controllers stay thin ([`implementation.md`, "Thin controllers"](../engineering/implementation.md#thin-controllers)). A per-service breakdown of its own layers belongs in that subsystem's `architecture.md`, not in the architecture document.

## Route contracts and their HTTP binding

A capability that serves HTTP routes is split into the five pieces of [`implementation.md`, "Route contracts and their HTTP binding"](../engineering/implementation.md#route-contracts-and-their-http-binding): typed client, route contract, wire models, HTTP binding, and route service. Here, the package that owns the capability owns the wire models, the route contract, and the route service; its wire models, in the contracts package, are pydantic models; and the HTTP binding belongs to whatever composes the process: a storefront for storefront capabilities, the provisioning service for the compute family kit's routes, and a domain package for the routes that domain contributes. The resource-pool capability is the worked instance of the order in which a request is checked, a document and an individual write sharing one comparison of stored and proposed state; see its [administrative reconciliation](../../../openspec/specs/resource-pool-management/architecture.md#administrative-reconciliation).

A domain that contributes routes to a service it does not compose declares their contracts in its own package and supplies its router as a factory taking accessors for its collaborators, so no route reaches into the composing service's module state. Because a binding repeats its contract's path, the provisioning service, which assembles its route table from contributions, tests that every route it mounts resolves to exactly one contract and that every contract resolves to a mounted route. When it composes its table, before it accepts traffic, it refuses two contracts of different contributions that one method and path could both match; within one contribution the first matching contract decides, in the order its owner gave. Overlap is decidable because a contract's pattern is restricted to literal segments, `[^/]+` named captures, alternations of literal segments, and an optional trailing `/?`, and building a contract refuses any other pattern. A route that needs more adopts an established path-template grammar rather than widening this one. A request that matches no contract is answered unsigned by what failed to match — 404 for an unknown path, 405 with `Allow` for a known path under another method, 400 for a route whose body resource cannot be bound — as the provisioning service and `kit/site`'s middleware both answer it; see [`physical-provisioning`](../../../openspec/specs/physical-provisioning/spec.md) and [`site-capacity`](../../../openspec/specs/site-capacity/spec.md).

`kit/pool-overrides` is the reference instance. `kit/site` predates the pattern and ships its own FastAPI router.

## Libraries

Production code follows [`implementation.md`](../engineering/implementation.md), among its rules no speculative guard code and preferring an existing library. The relay's grant-admission plugin ([`frp-grant-admission`](../../../openspec/specs/frp-grant-admission/spec.md)) is the repository's own because no library met its requirements; the secret scan uses gitleaks rather than a scanner of our own.
