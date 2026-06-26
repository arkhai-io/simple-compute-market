# Implementing market domains

A market domain defines what a listing means, what a buyer can negotiate
for, and how a storefront fulfills and settles the agreement. Domains are
not required to live in this repository. They can be registry-maintainer
packages, private organization-specific packages, or in-tree reference
implementations under `domains/<name>/`.

The core market services intentionally stay generic:

- A registry stores and filters listings. It verifies publisher identity
  and validates listing shape, but it does not negotiate or settle.
- A storefront owns settlement, fulfillment, and seller-side policy. It is
  usually operated by the same party as the resource being sold.
- Buyer tooling discovers listings from one or more registries, negotiates
  with storefronts, escrows payment, and consumes the fulfillment result.
- A domain package gives those roles a shared vocabulary for listings,
  negotiation terms, settlement demands, and fulfillment results.

This repository includes two useful references:

- `domains/apitokens/` is a small service-access domain: listings describe
  an API service, fulfillment issues or reuses an API token, and middleware
  gates requests against token balance.
- `domains/vms/` is a larger resource-lifecycle domain: listings describe
  compute slices, negotiation includes lease/provisioning terms, fulfillment
  provisions machines, and settlement may coordinate with lease lifecycle.

Treat those as examples of the contract surfaces, not as a required hosting
model.

## Distribution models

Domains can be distributed in several ways.

An in-tree reference domain can use this shape:

```text
domains/<domain>/
  listings/
  negotiation/
  settlement/
  buyer/
  storefront/
  registry/
  service/          # optional resource or middleware service
  common/           # optional shared package
  compose.yml       # optional demo/dev stack
```

A standalone package might be flatter:

```text
my_org_market_domain/
  listings.py
  negotiation.py
  settlement.py
  registry.py
  storefront.py
  buyer.py
```

Or it may be split by audience:

```text
my-domain-common       # schemas, codecs, validation helpers
my-domain-buyer        # buyer CLI/plugin and buyer policies
my-domain-storefront   # storefront policy, settlement, fulfillment
my-domain-registry     # filter specs and validation schema
```

Use whatever package layout makes distribution and ownership clear. The
important part is that each deployed role imports compatible versions of
the same domain semantics.

## Required contract surfaces

Most domains need the surfaces below. Some can be small wrappers around
shared helpers; others may need dedicated packages and services.

### Listing resource schema

The listing's `offer_resource` is domain-defined. The registry stores it as
JSON and treats it as opaque except where the registry operator has enabled
domain-specific validation and filtering.

Define:

- a stable resource kind, usually versioned, such as `api_tokens.v1`
- a typed model for the `offer_resource` payload
- coercion helpers for JSON loaded from registry/storefront storage
- filterable fields and their validation rules

Examples:

- `domains/apitokens/listings/models.py`
- `domains/vms/listings/models.py`

### Registry validation and filters

Registry operators decide which domains they accept. A registry-scoped
domain should provide the validation and filter metadata a registry needs
to reject malformed listings and expose useful discovery queries.

Define:

- required fields for `offer_resource`
- allowed field types and operators
- any local vocabulary constraints, such as regions or service kinds
- migration/deprecation rules for old listing schemas

The registry still remains independent from storefronts. A listing's
publisher identity and storefront URL come from the signed publish flow;
the registry does not become the seller.

### Accepted settlement choices

Listings describe what the seller is willing to accept on chain. In the
current Alkahest-backed flow this is carried by fields such as:

- `accepted_escrows`: allowed escrow shapes and payment constraints
- `demands`: listing-level allowed arbiter demands

`demands[]` is listing-level choice. If a seller allows several possible
demands, the buyer chooses one concrete demand in the proposal. Multiple
simultaneous subconditions should be represented as a single logical
arbiter demand, such as an `AllArbiter` demand, not as multiple proposal
demands.

Proposal-level `demands[]` is deprecated compatibility surface. New domain
code should concretize to one selected demand.

### Negotiation terms

Round 0 includes two generic carriers:

- `ProvisionTerms`: what the buyer wants delivered
- `EscrowProposal`: the selected payment/settlement tuple

`ProvisionTerms.kind` should identify the domain and version. Its payload
is domain-defined.

Examples:

- API tokens use `api_tokens.v1` with payload fields such as `quantity`
  and key disposition.
- VMs use provision terms for start/end lease intent and machine access
  requirements.

Domain authors should define:

- how a buyer constructs initial provision terms from CLI/API input
- which fields are fixed at round 0 and cannot be mutated by the seller
- which scalar fields are negotiable, such as price or quantity
- validation that the proposal still matches the listing's accepted
  escrows and selected demand

Shared negotiation middleware can handle scalar price bargaining, but the
domain owns the interpretation of its provision payload.

### Storefront policy

The storefront decides whether to reject, counter, accept, or exit a
negotiation round. A domain storefront policy usually checks:

- the listing still exists and is available
- the requested provision terms are fulfillable
- the proposal matches one accepted escrow shape
- the selected demand is one of the listing-level allowed demands
- the buyer has not changed pinned fields between rounds
- any resource-specific capacity or quota is available

For scarce resources, keep the boundary explicit. Storefront policy may
consult an inventory, quota service, or provisioning service, but the
domain should document which component is authoritative for availability.

### Settlement and fulfillment

Settlement turns an accepted negotiation into an executable outcome. The
generic carrier is `SettlementPlan`; the domain decides how fulfillment is
performed and what result is returned to the buyer.

Define:

- how escrow creation is verified
- which Alkahest demand/arbiter data is expected
- what the seller attests or claims on fulfillment
- how fulfillment credentials are returned
- how failure, refund, revocation, interruption, or expiration work
- which admin endpoints or hooks are allowed to settle or interrupt a deal

For example, the API-tokens domain issues credentials and relies on
middleware to meter usage. The VM domain may reserve capacity, provision a
machine, and later shut it down on lease end or interruption.

### Buyer integration

A domain can be usable without a full CLI, but buyers need enough package
surface to:

- display and filter listings
- construct initial `ProvisionTerms`
- choose an accepted escrow and selected demand
- run negotiation policy
- create escrow
- call the storefront settlement endpoint
- parse the fulfillment result

If the domain ships a plugin for the shared buyer CLI, document its entry
point and which extra dependencies it installs.

### Optional resource service

Some domains need a seller-operated service behind the storefront:

- VM provisioning service
- API key or quota ledger
- model-serving middleware
- storage allocator
- license server

Keep this service role separate from the registry. It is seller
infrastructure, even when it is reusable across sellers.

Document:

- which storefront endpoints call it
- which admin credentials it needs
- what state it owns
- which callbacks it may make to the storefront
- how it behaves on retry or partial failure

## End-to-end lifecycle

A typical domain flow is:

1. The seller publishes a signed listing to one or more registries.
2. The registry validates and indexes the listing.
3. The buyer queries chosen registries and selects a listing.
4. The buyer starts negotiation with `ProvisionTerms` and one
   `EscrowProposal`.
5. The storefront validates the listing, terms, escrow shape, and selected
   demand.
6. Buyer and storefront negotiate until accept, reject, or exit.
7. The buyer creates the on-chain escrow for the accepted proposal.
8. The buyer submits settlement to the storefront.
9. The storefront verifies escrow, performs fulfillment, and returns the
   domain fulfillment result.
10. The seller claims, refunds, or otherwise settles according to the
    negotiated demand and domain lifecycle.

The registry is involved in steps 1-3 only. Negotiation and settlement are
peer-to-peer between buyer tooling and the seller storefront.

## Versioning and compatibility

Domain schemas are public wire contracts once listings are published.
Version domain kinds and be explicit about breaking changes.

Recommended practices:

- Put a version in resource and provision-term kinds, such as
  `my_domain.v1`.
- Treat `offer_resource`, `ProvisionTerms.payload`, fulfillment results,
  and settlement demand data as independently versioned if they may evolve
  separately.
- Add deprecation notes in code and docs before removing fields.
- Prefer additive changes for listings that may remain published.
- For breaking escrow or ABI changes, assume old listings are incompatible
  unless the new SDK still distributes the old addresses and codecs.
- Keep registry filter specs aligned with the fields the buyer actually
  searches.

## Testing expectations

A domain should have tests at the same boundaries users will rely on:

- model and codec tests for listing resources, provision terms, demands,
  settlement plans, and fulfillment results
- registry validation and filtering tests
- buyer tests for listing selection, proposal construction, and resume
  behavior
- storefront tests for negotiation guards and settlement verification
- service tests for optional resource/provisioning behavior
- one compose or e2e happy path showing the deployed roles together

Failure-path coverage should scale with risk. Domains that allocate scarce
resources, hold funds, or issue credentials should test retries, expired
deals, refunds, and unauthorized admin actions.

## Author checklist

Before publishing a domain package, verify that:

- The domain has a stable name and versioned resource kind.
- The registry can validate listings for the domain.
- Buyers can discover and display listings without storefront-specific
  code.
- Listings express all allowed escrow and demand choices.
- Proposals select exactly one concrete settlement demand.
- Storefront policy rejects unfulfillable or mutated terms.
- Fulfillment results are typed and documented.
- Settlement, refund, expiration, and interruption semantics are clear.
- Any seller-operated service is documented as seller infrastructure.
- Packages declare which versions of the core clients and Alkahest SDK they
  support.
- At least one happy-path e2e or compose demo exists.
