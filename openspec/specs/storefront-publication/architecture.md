# Storefront Publication Architecture

The [normative contract](spec.md) defines seller publication behavior. This document explains why storefront market state is separate from physical capacity authority.

## Seller-owned market state

A storefront is the seller's market-facing authority. It composes domain codecs, seller policy, publication, negotiation, settlement hooks, and operator-visible deal state. Registries hold discoverable copies; buyers hold received views; neither replaces storefront ownership of the listing and deal lifecycle.

The storefront may publish to multiple registries, but each publication remains derived from seller state and signed under the complete canonical publisher principal expected by that registry. The listing ID and storefront URL remain stable commercial subjects; changing an authorized credential does not manufacture a new listing or transfer ownership implicitly.

## Immutable domain ownership and publication

The common storefront validates every explicitly configured contribution at
its application root and freezes each exact contract. Bare metal exports one
validated contract builder through `market.storefront_contributions`; its
standalone executable composes that same contribution with bare-metal seller
policy and provisioning adapters. A shared shell can therefore select it
without importing VM services or replacing domain-owned codecs and lifecycle
semantics.

Every derived listing persists one common binding containing trusted site,
offering mode, exact domain identity/version, public source envelope, and
collision-safe pool or Physical Resource provenance. Public
`virtualization_type` is projected from this binding, not guessed from a
listing payload. One pool may therefore produce distinct VM and bare-metal
listings without creating competing domain-specific mapping authorities.
Negotiation and artifact bindings copy the frozen selection, and repository
rehydration resolves it only through the installed contribution registry;
neither a singleton, optional default, payload-shape guess, nor domain-name
branch may replace it.

Publication runners are built from the configured registry once. Disabling a
contribution removes its source and wait path; withdrawing a pool mode closes
new listings for only that mode. Accepted records retain their binding.
Mapped capacity traffic pins the selected site and never falls back to another
authority on refusal or outage.

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

## Stable subjects and canonical principals

Storefront records distinguish durable market subjects from credentials. Listings retain their listing identity and storefront ownership context; negotiation threads, messages, accepted terms, settlement plans, heartbeat evidence, claims, obligations, and audit records carry the exact canonical buyer, seller, sender, payer, claimant, or actor principal appropriate to the record. Administrator and service-peer records similarly bind a complete principal to a named subject and role.

This separation prevents address-shaped data from silently becoming authorization. An explicitly named EVM recipient or transaction signer belongs only to a tagged chain-mechanism payload. It cannot replace the marketplace principal that owns a listing, participates in negotiation, or authorizes a storefront route. Consequently Ed25519 parties can complete non-EVM storefront paths while an Alkahest adapter can still consume independently configured EVM effect fields.

## Trusted site routing

`site_id` is storefront-owned configuration bound to one exact provisioning authority URL and canonical principal. Authority URLs are excluded from reprs, health, status, logs, and public results; credentials enter only through signer injection. Listing reconciliation freezes the trusted site and Physical Resource in an immutable common binding, and accepted negotiations copy it before agreement artifacts are stored.

Bare-metal fulfillment reloads this binding for every step. Site-targeted capacity reservation, scheduling, fulfillment begin/status/result, teardown, and capacity release use the configured client selected by the recorded site or the durable reservation-to-site map. A buyer assertion, provider response, or opaque artifact cannot replace the site, URL, principal, Physical Resource, machine, or physical-host identity. Restart therefore changes neither authority nor executor, and capacity is released exactly once only after authoritative teardown succeeds.

The result channel is pull-based: the storefront polls the recorded fulfillment and converts its versioned bare-metal envelope to a buyer-safe receipt and access result. Provider payloads, private SSH material, authority URLs, and credentials are not copied into market state or responses.

## Role and service-peer identity

The storefront authenticates publisher, buyer, administrator, and service-peer traffic through the shared version 2 identity contract, then authorizes the complete principal against an explicit role and durable subject binding. A missing or invalid proof never falls back to an address, administrator key, private-key field, query value, listing field, or negotiation record.

At the route boundary, storefront code supplies the expected role, semantic operation, stable resource, and exact principal or active principal set from trusted context. The proof binds those values with the caller principal, method, request ID, timestamp, and canonical body hash. This makes reverse-proxy paths and untrusted body fields irrelevant to trust selection and prevents mutable request content from escaping the signature.

Replay reservation is authority-owned persistence, not an in-memory timestamp check. After cryptographic verification and before handler dispatch, the storefront atomically claims the complete principal and request ID with the semantic request hash and a bounded execution lease. Changed reuse fails closed. An exact retry can recover a completed outcome or observe an in-flight reservation without dispatching a conflicting mutation, including after a process restart.

Administrator and service-peer configuration contains public trust pins, but durable storefront state owns authorization after initialization. Configuration may create a subject only when it supplies one initial primary principal; later startup checks that configuration covers the durable primary and any active overlap rather than overwriting them. A subject keeps one role, a service peer also keeps one operator-owned `site_id`, and one principal cannot be active for two subjects at the same authority.

Provisioning and other service-peer connections are therefore pinned by both the active principals of a stable peer subject and the storefront-owned `site_id` binding. Signed requests, responses, and callbacks must match those exact pins before their contents affect routing, capacity, fulfillment, or settlement state. A peer cannot self-assert a different site through a body field, and matching identifier text under another scheme is not equivalent.

A seller may deliberately reuse one public principal for registry publication, storefront ownership, hosted account ownership, negotiation, and settlement. That does not merge authority roles: every receiving service enforces its own binding and receives only a signer operation or signed proof. Storefront rows and projections carry the public principal and opaque provider references, never a private credential or provider identity.

Site trust is resolved through a registry interface that returns the site identifier, URL, and complete scheme-tagged principal. Configuration is the current registry source, but callers depend on the interface so durable storage can replace it without changing authentication or routing consumers. Every site has its own trust pin; a principal registered for one site cannot authenticate another.

Storefront clients verify version 2 mutation responses before accepting an acknowledgement. The response proof binds the expected authority principal, originating request identity, status, timestamp, and canonical body, so a valid response from a different authority or an altered transport body fails closed. The storefront applies the same contract when it signs administrator and service-peer mutation responses, allowing callers to authenticate the acknowledgement rather than trusting transport success.

Rotation preserves the stable authority subject. A site authority, storefront administrator, or service peer changes principal only when the active and replacement principals sign the same bounded canonical intent. The storefront applies identical intents idempotently, records primary, overlap, retired, disabled, and audit state, and accepts both credentials only during the overlap. Retirement is tied to the recorded rotation and old principal; expiry or explicit retirement removes old-principal authority, while disablement can stop a credential but cannot manufacture replacement ownership.

## Atomic storefront identity state

The storefront validates and migrates listing sellers, negotiation parties and messages, accepted settlement plans, heartbeat parties, obligation parties, administrators, service peers, replay reservations, stage events, claims, and audit actors as one service-local transaction. It cross-checks listing ownership, storefront URL, party relations, embedded principals, and uniqueness of active bindings before retiring address-only columns. Stable listing, negotiation, obligation, fulfillment, service-peer, rotation, and operation identities survive the conversion. A malformed or partial identity, conflict, duplicate binding, or referential gap rolls the whole population back rather than leaving a mixed authorization boundary.

## Settlement option reconciliation

The storefront owns seller settlement status and administration because it is the authority that turns mechanism readiness and seller intent into market-visible options. It preflights every enabled installed registration and passes complete typed publication clauses only to their owning ready builders. Options follow configured mechanism priority and source-clause order. A sanitized blocker suppresses only its unready mechanism; ready peers with valid clauses remain publishable. An enabled mechanism with no clause publishes nothing, and one clause's scalar price never supplies another mechanism.

Command defaults, CSV resource rows, projected reconciliation records, and direct listing requests converge on the same typed clause model before builders run. A resource's clause list replaces command defaults as a whole. Rates are human decimal asset quantities at input and are normalized exactly once by the owning mechanism to currency minor units or token base units; non-exact conversion fails rather than rounding. Legacy publication config and CSV input use an explicit preview/write/backup migration and ambiguous multi-mechanism scalar pricing requires manual resolution.

Readiness recovery may add a deterministic option without changing listing identity. Loss of readiness may remove that option from future offers, but accepted Terms remain pinned. Seller operations live under `market-storefront settlement`: the common status command is observational, while mechanism-owned subcommands expose genuine differences such as hosted onboarding or an Alkahest check without creating separate publication paths. Normal `publish` accepts only mechanism-neutral clauses.

## Exact hosted alternatives and accepted authorization

Hosted publication treats every complete ready profile clause as an independent option. The option and accepted plan bind the exact profile alongside money, destination account, condition, parties, and expiry policy. Readiness is evaluated per clause and per profile, so adding or losing one rail does not rewrite another option or an already accepted agreement.

The buyer obtains its operation-scoped funding authorization only after accepted terms are durable. Storefront start accepts the accepted negotiation and obligation identities plus that safe reference, then reloads all commercial inputs from seller-owned state. Payer profiles, saved instruments, buyer automation policy, and provider data never enter listings, accepted terms, storefront persistence, or evidence.

Historical card-only plans are classified from persisted state and decoded only for recovery. New config, publication, negotiation, and start accept the explicit `card.v1` profile; there is no public legacy alias that could generate a second identity for the same old plan.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
