# Market Composition Architecture

The [normative contract](spec.md) defines enforceable dependency and composition boundaries. This document explains why those boundaries exist and how the role packages form a market without making the shared core understand a concrete market schema.

## Composition from above and below

Arkhai separates invariant control flow from market meaning:

```text
composition root
    ├── core role machinery
    ├── domain vocabulary and deterministic interpretation
    └── kit mechanisms and authorities
```

Core is valuable as a stable control skeleton: signed transport, round sequencing, persistence mechanics, lifecycle transitions, and typed handoffs. It does not become a collection of interchangeable callbacks or acquire domain vocabulary merely because one shipped market needs it.

Domain packages define what is bought and sold: listing fields, provision intent, deterministic validation, terms interpretation, fulfillment requirements, and domain result vocabulary. Kit packages supply reusable mechanisms such as identity, policy middleware, settlement codecs, site capacity, resource pools, and fulfillment scheduling. Composition roots select concrete implementations and are therefore allowed to depend on all lower layers.

## Typed phase boundaries

A conceptual market flow is:

```text
messages → Terms → SettlementPlan → servicing and fulfillment
```

A phase remains separate when core-owned machinery or a typed invariant lies between it and the next phase. That separation gives each role a stable handoff, lets persistence and recovery refer to a durable carrier, and prevents a domain implementation from bypassing shared lifecycle rules. Hooks may be combined when no shared behavior or meaningful carrier exists between them.

These carriers are intentionally less expressive than every domain model. Domain-specific meaning travels in validated, versioned envelopes and is interpreted only by the owning domain or mechanism codec.

## Package ownership

Dependency direction protects substitutability and testability:

- core packages do not import domain implementations;
- kit authorities do not import deployed services or higher kit layers;
- domain concept modules do not become service bundles containing databases, operator policy, provider SDKs, or infrastructure wiring;
- composition roots own registration and configuration of concrete plugins and adapters.

Type-only imports still couple packages and therefore obey the same direction.

## Executable ownership

The buyer CLI and registry executable are core-owned because their control flow is schema-opaque and extended through domain entry points or configuration. Storefront executables remain domain-owned composition roots where domain adapters and seller policy are wired into shared storefront machinery. A package move does not alter these authority boundaries.

## Current limits

The composition contract covers the shipped role protocols and versioned domain contracts; it is not a claim that every possible market shape fits the current phases. Auctions, sealed-bid protocols, arbitrary settlement plans, and a universal storefront executable require explicit changes rather than inference from the extension points.

## Related contracts

- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
