# Storefront Publication Architecture

The [normative contract](spec.md) defines seller publication behavior. This document explains why storefront market state is separate from physical capacity authority.

## Seller-owned market state

A storefront is the seller's market-facing authority. It composes domain codecs, seller policy, publication, negotiation, settlement hooks, and operator-visible deal state. Registries hold discoverable copies; buyers hold received views; neither replaces storefront ownership of the listing and deal lifecycle.

The storefront may publish to multiple registries, but each publication remains derived from seller state and signed under the publisher identity expected by that registry.

## Advisory publication, authoritative admission

A listing is an offer based on the seller's latest complete capacity view. It is not a physical reservation.

```text
site projections → storefront cache → listing reconciliation → registry
       │
       └──────── authoritative reservation occurs at the site
```

Publication must be feasibility-based rather than derived solely from aggregate totals. An unavailable site is not authoritative evidence of zero capacity, so refresh failure retains the last complete cached generation and records staleness instead of closing listings destructively.

## Projection families

Individual-resource and grouped-capacity listings need different inputs:

- resource-pool projections expose allowlisted facts for resources the seller intentionally offers individually;
- capacity-bucket projections group identical available shapes into deterministic criteria and counts without exposing backing resource identities.

The families have independent revisions and digests. A storefront replaces each cached generation atomically, preventing readers from observing a partially refreshed projection. Grouped projection rows are publication hints, not allocation targets.

## Reconciliation

Reconciliation compares desired publication with current seller state and registry state. Capacity events trigger reconciliation regardless of which seller action caused the availability change, because a shared site may serve several storefronts. Deal-scoped outcomes travel through a separate owner-specific route and are not broadcast as capacity deltas.

## Trusted site routing

`site_id` is storefront-owned configuration bound to a provisioning connection. It is not accepted as an untrusted routing assertion from a counterparty or remote projection. This keeps market-visible location choice separate from authority selection and prevents opaque identifiers from encoding credentials or endpoints.

## Related contracts

- [Registry discovery](../registry-discovery/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
