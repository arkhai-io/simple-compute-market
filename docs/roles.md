# Market roles

Simple Compute Market has no canonical platform role. The market is made
from independent userland roles that communicate through signed HTTP,
registry discovery, and on-chain settlement.

```text
Buyer      -> Registry:   discover listings
Storefront -> Registry:   publish and update listings
Buyer      -> Storefront: negotiate and submit settlement
Storefront -> Resource:   fulfill the accepted deal
Buyer      -> Resource:   use the fulfilled service or machine
```

## Registry

A registry is a federated discovery surface. It stores listings, verifies
publisher identity, validates the listing shape configured by the registry
operator, and exposes search/filter APIs to buyers.

A registry is not the seller, not the settlement authority, and not the
market operator for every storefront that publishes to it. Buyers choose
which registries to query. Sellers choose which registries to publish to.
Different registries can curate different publishers, domains, filter
vocabularies, and read/write policies.

## Storefront

A storefront is the seller-operated negotiation and settlement surface.
It owns seller policy, verifies escrow, performs or coordinates
fulfillment, and returns the domain-specific fulfillment result to the
buyer.

Storefronts are not subordinate to registries. A storefront can publish to
one registry, many registries, or a private registry operated by the same
organization. If a registry and storefront run on the same host or Docker
network, that is deployment convenience, not a change in protocol roles.

## Resource service

Many domains have seller-operated infrastructure behind the storefront:
VM provisioning, API-token ledgers, model-serving middleware, storage
allocators, or license servers. This service is part of the seller side of
the flow because fulfillment and settlement require authority over the
resource.

The resource service usually should not be buyer-facing except for the
fulfilled resource itself, such as an issued API token or a provisioned VM.
Administrative callbacks and interruption/settlement hooks should be
authorized as seller/storefront infrastructure.

## Buyer

A buyer chooses registries, discovers listings, negotiates directly with
storefronts, creates escrow, submits settlement, and consumes the
fulfilled resource. Registry selection is part of buyer policy: a buyer
can query public registries, private registries, domain-specific
registries, or several at once.

## Common deployment shapes

These are all valid:

- A public registry lists many independent storefronts.
- A private organization runs a registry for vetted sellers and approved
  buyers.
- A seller runs a private registry next to its storefront for direct
  customers.
- A buyer queries several unrelated registries and deduplicates listings.
- A domain maintainer publishes a standalone domain package consumed by
  multiple registries and storefronts.

The invariant is the role boundary: registries provide discovery,
storefronts provide negotiation and settlement, seller resource services
provide fulfillment, and buyers decide where to discover from.
