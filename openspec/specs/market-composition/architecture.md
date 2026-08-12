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

Domain packages define what is bought and sold: listing fields, provision intent, deterministic validation, terms interpretation, fulfillment requirements, and domain result vocabulary. Kit packages supply reusable mechanisms and authorities such as identity, policy middleware, the commercial-settlement runtime and mechanism clients, site capacity, resource pools, and fulfillment scheduling. Composition roots select concrete implementations and are therefore allowed to depend on all lower layers.

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

## Settlement runtime composition

`market_settlement_runtime` is a foundation kit because its obligation and
operation lifecycle is reusable across storefront roles and market domains. It
depends only on generic carriers and its own injected ports. A composition root
provides the SQLite repository path, conditional-escrow clients, accepted-plan
and fulfillment callables, status projection, and real failure actions.

The same runtime owns every materialize, status, check, collect, and reclaim
transition. Mechanism clients may keep opaque durable state, but they cannot
introduce a second scheduler or persistence authority. Domain-private delivery
data remains in the domain's existing response channel and never becomes
generic settlement state.

A verified-only domain may register and adopt a pre-materialized obligation
without installing a servicing worker. Full servicing begins only after the
composition can bind a real immutable fulfillment reference; a no-op executor
would falsely advertise collectability.

## Executable ownership

The buyer CLI and registry executable are core-owned because their control flow is schema-opaque and extended through domain entry points or configuration. Storefront executables remain domain-owned composition roots where domain adapters and seller policy are wired into shared storefront machinery. A package move does not alter these authority boundaries.

## Identity composition

Marketplace identity is a foundation kit alongside the generic settlement lifecycle. It owns canonical principals, signer/verifier dispatch, authenticated request and response envelopes, replay handling, and rotation primitives. The dependency is deliberately one way: roles, domains, settlement adapters, and their composition roots may depend downward on these interfaces, while the identity kit imports no role, domain, settlement mechanism, hosted provider, or chain runtime.

Composition roots resolve public identity and secret credential material separately, construct one scheme-neutral signer, and inject it into registry, negotiation, service-peer, and settlement clients. Core orchestration carries the complete principal and signer ports opaquely; it neither branches on scheme or private-key shape nor treats an identifier as a wallet address, provider account, or mechanism setting. Scheme plugins own identifier interpretation, while provider account references remain resources rather than credentials. A domain can therefore compose Ed25519 marketplace identity without an EVM package.

Chain and provider dependencies enter only after a composition root selects a concrete mechanism. The selected domain or settlement adapter owns wallet derivation, chain preflight, RPC clients, and provider SDKs; a no-wallet hosted-fiat composition consequently does not instantiate an Alkahest client or import those dependencies into scheme-neutral orchestration.

Hosted authentication remains a separately released protocol even when it uses the same marketplace signer and cryptographic scheme. The thin hosted adapter presents that signer through the exact manifest-pinned `hosted-settlement-client`, verifies that the manifest advertises the required identity contract before publishing fiat, and lets the client own hosted principal models, canonical bytes, headers, proofs, and response verification. This preserves each protocol's domain separation and prevents marketplace packages from copying or translating hosted wire logic.

## Current limits

The composition contract covers the shipped role protocols and versioned domain contracts; it is not a claim that every possible market shape fits the current phases. Auctions, sealed-bid protocols, arbitrary settlement plans, and a universal storefront executable require explicit changes rather than inference from the extension points.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
