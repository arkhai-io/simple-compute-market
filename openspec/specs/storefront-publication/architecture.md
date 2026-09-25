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
`offering_mode` is projected from this binding, not guessed from a
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

Bare-metal publication derives from the resource-pool projection alone, one candidate per Physical Resource carrying a `bare_metal.v2` publication view. The view is the one the site builds from the capacity declaration admission accounts against, so it cannot name a different machine than admission does; a storefront building its own view from a publication attribute could. Reading pool declarations already means fetching this projection, since the shared declaration reader judges one site generation as a whole, so a resource's pool, that pool's declarations, and the resource's view all come from one document. The capacity projection stays the site's live availability view for VM, API credits, and placement ranking; bare metal loses nothing by not reading it, because the view's availability is built from the same ledger rows at fetch time and bare-metal publication fetches fresh on every run.

Within that document a resource's pool is the pool entry that contains it. The view repeats the pool identifier so it is self-contained, and pool membership decides whether a resource may be published, so the two copies may not disagree: a view naming another pool refuses the whole site generation, as a view naming another Physical Resource does, and the site is held rather than read either way.

Bare-metal publication fetches each site through that site's own client rather than the aggregate capacity client, whose best-effort snapshot omits a site it could not reach and so cannot tell an unreachable site from an empty one.

## Reconciliation

Reconciliation compares desired publication with current seller state and registry state. Capacity events trigger reconciliation regardless of which seller action caused the availability change, because a shared site may serve several storefronts. Deal-scoped outcomes travel through a separate owner-specific route and are not broadcast as capacity deltas.

Two reconciliations run over listings, and they differ in scope:

- **Source publication** applies to every listing, backed or not. A removed or disabled source closes the listings derived from it, and a changed source is reflected according to the identity rule below. Without it an unbacked listing's advertisement would outlive its declaration indefinitely, which is worse than a stale capacity number because no later event corrects it.
- **Capacity availability** applies only to capacity-backed listings, with its close-before-reopen sequencing. An unbacked listing has no availability to track; its quantity is bounded by what its source declares, which is what being inexhaustible means. The availability paths — capacity events, a released reservation, a failed deal — read only listings bound as backed, so an unbacked listing never enters them.

Bare-metal publication keeps the two apart by classifying every resource into exactly one class and building its closes from those disjoint classes: a *candidate* (pool admits bare metal, declaration enabled, machine wholly available) is published, refreshed, or reopened; an *unavailable* resource (as a candidate, but the machine is leased) closes its listing for availability and reopens it when free; a resource in a pool whose declarations do not resolve is *held*; and anything else — a disabled declaration, or a pool that does not admit bare metal — is *withdrawn* and closes as a source withdrawal, as does a listing whose resource is no longer projected under the pool its binding records. Enablement is read from the projected resource, never from the view, because the site builds the view's `available` from the declaration's enablement and whole-resource availability together; reading it would turn a withdrawn declaration into an availability close. Disjointness is also mechanical: the kit runtime refuses a close plan naming one listing twice. Every bare-metal listing is capacity-backed, so a pool declaring itself unbacked yields none; a listing from it could only publish a backing its pool contradicts.

One comparison gates a refresh and every reopen. A listing whose published identity differs from what its source now derives, or whose binding's backing disagrees with its source's, is not refreshed in place and is not reopened by any path, including one a capacity event drives. The same derivation serves the seller's inventory guard, which compares a listing against a fresh derivation of its own source rather than against any matching row, because a field's provenance is decided per listing, not per field.

## Listing identity

A listing's identity is the physical resource it offers: the supply it draws from (site, and pool or Physical Resource), what the resource is (offering mode, resource type and subtype, and categorical attributes such as `gpu_model`), where it is (`region`), and how much one listing offers (the enumerated slice quantity and every other declared dimension it publishes). Everything else — price and pricing hints, settlement options, maximum duration, SLA — is a term of sale.

The line falls there for three reasons. A listing ID is what a buyer saves and negotiates against, and what accepted terms and settlement records reference, so changing what is sold under one ID reinterprets every such reference. Terms of sale are meant to move: a price change that orphaned buyer references would make every repricing a delisting. And the identity fields are the ones admission matches — the capacity claim carries the pool or resource, region, model, and requested dimensions — so what a listing is and what a reservation will look for are one set of fields.

A term change therefore refreshes an open listing in place, and an identity change closes it and, where the source still supports one, publishes a listing under a new derivation identity. A listing commits only to the fields it publishes: reconciliation never adds an identity field a listing did not publish, since that would make a new commitment under an existing identity. Capacity backing sits outside the split. It is not a property of the resource but of whether an admission authority stands behind the listing, and it is fixed on the binding when the listing is created.

A listing is tracked by one key: its common binding's derivation key. For a bare-metal listing that key is built from its site, offering mode, domain binding, pool, and Physical Resource, so a Physical Resource moved to another pool derives a new listing under the new pool's binding and its old listing closes as a withdrawn source. A second, domain-owned key that omitted the pool would find the moved resource's listing and refresh it in place while its binding still recorded the old pool, leaving advertisement authorized by a pool the resource no longer belongs to. A bare-metal binding's source, as the capacity-publication kit sees it, is its Physical Resource: the listing sells that one machine, whereas a fungible VM listing draws from its pool.

## Listing shapes and the storefront's authority

Every VM listing is a listing shape: a family-grouped statement of what one listing offers, in the VM domain's vocabulary. Bare-metal and API-credit publication do not use listing shapes; the family-grouped shape utility and the storefront pool-override kit are market-neutral, so another market can adopt the model. A published dimension is a commitment, not a description. The capacity claim a listing produces requests every quantity the listing publishes, the site reserves each one, and fulfillment builds the resource from what was reserved. Publishing a member's whole memory on a one-GPU slice would therefore reserve and provision all of it for one GPU. So a VM listing publishes exactly the quantities its shape declares and nothing else. A dimension its shape omits is outside the listing's and the reservation's commitment: fulfillment may supply it from the pool's configured VM defaults, where they are set, or leave it to downstream provisioning, and keeping enough capacity for the dimensions a pool's shapes omit is the operator's responsibility.

Shapes are stated or generated, never inferred. A pool's VM shapes come from exactly one source, in order: the storefront's own override for that site and pool, the pool's `listing_shapes` hint for the offering mode, and otherwise the VM domain's default generator. A stated list replaces the lower sources whole. The VM default generator yields, per GPU model among a pool's members, one GPU-only shape per count up to the largest declared; the generator is the domain's seam for other default policies. How many of a shape fit is derived from the site's declarations, never declared or published.

A shape is published only where some source member is resource-feasible for its claim, judged by the site's own predicate against declared capacity, and, for a capacity-backed listing, against current availability. Feasibility is not admission. It does not see the pool provider's host requirement, holds over a lease window, or physical-host conflicts, and the projection deliberately withholds the state that would let it; the site's reservation remains the admission boundary. A stated shape no member is feasible for yields no listing and is reported; it is never shrunk or replaced by another source's shapes.

How much one VM listing offers is its listing shape, and its derivation identity includes the shape's digest, taken over the family-grouped form so that renaming a flat field changes no key. Identity then depends only on what is offered: a site that later states the shape its pool was publishing by default keeps that listing.

### Storefront pool overrides

A storefront is the final authority over what it sells within what a site declares. Its override for one pool at one site, in one offering mode, states shapes, settlement clauses, and its market's commercial terms; it cannot state region or capacity backing, which are the site's, and its offering mode is never defaulted. Pool identifiers are site-local, so an override is keyed by site, pool, and offering mode, and a pool sold in two modes carries an independent override per mode, each wholly one market's.

The capability is a market-neutral storefront kit, `kit/pool-overrides`: the durable store and its reader, a write checked against the site, the status of each stored override, the signed-resource contract, and a typed client over the core client's generic transport. Each market contributes, per offering mode, the judgements only it can make: whether a record's shapes and terms are in its vocabulary, and whether a site's declarations are feasible for each shape. The core client stays universal, and a second market with shape requirements reuses the kit rather than copying it.

A write is checked against the site's resource-pool projection fetched live through the site's authenticated client, not against the storefront's cache, so neither a stale cache nor a stale refusal decides it. A pool the site does not project is refused; an unreachable or unverifiable site is refused as retryable, distinctly; a shape no member is feasible for is accepted and reported, since delisting it is the intended effect. After a write the storefront refreshes that one site's cached resource-pool projection and wakes publication, so the override takes effect promptly without a full reload.

Derivation reads stored overrides itself, through the kit's reader, inside the derivation every structural-key reader runs. An override's shapes change listing keys, so publication and source reconciliation must resolve the same tier or reconciliation would close every listing an override shaped. The VM listings package names the kit in an optional `overrides` extra and imports it only on the projection path, so buyers, which install the package for its listing models, install neither the kit nor the resource-pool kit.

An override outlives its pool. Each stored override is in exactly one state: `inactive` while listings derive from local tables, where no override applies; `site_unconfigured`; `unknown` while its site's projection is not held; `orphaned` while the held projection lacks its pool; and `applied`. An unloaded site is unknown, not absent, so an override is never called orphaned on the strength of an answer the storefront does not have. A legacy home-site override row remains a lower tier, field by field, for as long as its writer, the local resource import, exists; system status names each field it still supplies.

### Unknown sites and inline reconciliation

A configured site whose projection the storefront does not hold is unknown, not empty. Its listings are held — neither closed nor refreshed — rather than read as withdrawn, and a storefront configured to derive from projections never derives from its local tables for want of a loaded one; only configuration selects them. Delisting would cost buyers the listing and registries a close and a reopen for every restart that raced a site; holding costs a buyer only an early refusal at round zero, where the inventory guard already refuses a listing whose site is not held. Holding has no time bound: a site decommissioned without closing its listings leaves them advertised until an operator closes them.

An operation that changes a site's capacity and reconciles inline — an administrator reservation, a fulfillment event, a failure action's release — refreshes that one site's cached projections before reconciling, and reconciles against the same projection publication derives from. Otherwise it would read a projection its own change had just made stale, report nothing, and leave a later operation to report its closes as its own. The refresh belongs to the invoked operation, so a paused storefront stays paused and advances only by invocation.

## Autonomous publication

VM publication runs as a lifecycle loop in the storefront's own process, not on an operator's command; bare-metal publication remains an operator-invoked command over the same publication sources, and each run converges registries as a VM cycle does. A seller declares supply at their site, and the site's projection carries it to every storefront that trusts that site; one storefront can publish for several seller sites whose sellers hold no storefront credential. An operator-run command would leave a site's declaration unpublished until someone ran it.

The loop follows the storefront's lifecycle conventions: the pause holds it with every other loop without affecting trading, one cycle can be run while held, and a dry run reports what that cycle would do and changes nothing. A change in a site's projection generation wakes an unheld loop. Terms come only from durable sources — pool declarations, the storefront's per-pool overrides, and configuration — because a cycle must be reproducible without the arguments of whatever command last ran. The loop builds only the publication sources of the domains it publishes, so a storefront can register another domain whose publication runs elsewhere.

## Durable seller close

Every close records whether its seller or reconciliation made it. A seller's close is enforced at the listing write every reopen passes through, not by each domain's reconciler: a write that would reopen it is refused unless the seller asks, and a later reconciliation close keeps the seller as its reason. Enforcing it once at that write is what keeps a domain that forgets the rule from undoing a seller's decision on its next capacity event.

## Registry convergence

For VM, API-credit, and bare-metal publication, the local listing is the publication decision and registries follow it, through the capacity-publication kit's runtime. A new listing is recorded locally, with its binding, before any registry is told of it, so no registry can hold a listing the storefront has no record of. A close or reopen changes the local listing first, so a registry never holds a state the storefront has not decided, and a local change that fails reaches the caller with no registry told. Each registry's outcome is recorded per listing, and every publication pass resends to any registry whose recorded outcome disagrees with its listing's local status exactly what that status implies, and only to that registry. The records are the repair source, so no separate journal exists, and a registry that stays unreachable remains diverged for the next pass. VM's publication loop and the bare-metal publication command both drive their cycles through the capacity-publication kit's cycle driver and end every pass with its convergence step, so the repair rule and how a pass reaches it have one implementation; each domain keeps only what its cycle derives, closes, and holds.

## Stable subjects and canonical principals

Storefront records distinguish durable market subjects from credentials. Listings retain their listing identity and storefront ownership context; negotiation threads, messages, accepted terms, settlement plans, heartbeat evidence, claims, obligations, and audit records carry the exact canonical buyer, seller, sender, payer, claimant, or actor principal appropriate to the record. Administrator and service-peer records similarly bind a complete principal to a named subject and role.

This separation prevents address-shaped data from silently becoming authorization. An explicitly named EVM recipient or transaction signer belongs only to a tagged chain-mechanism payload. It cannot replace the marketplace principal that owns a listing, participates in negotiation, or authorizes a storefront route. Consequently Ed25519 parties can complete non-EVM storefront paths while an Alkahest adapter can still consume independently configured EVM effect fields.

## Trusted site routing

`site_id` is storefront-owned configuration bound to one exact provisioning authority URL and canonical principal. Authority URLs are excluded from reprs, health, status, logs, and public results; credentials enter only through signer injection. Listing reconciliation freezes the trusted site and Physical Resource in an immutable common binding, and accepted negotiations copy it before agreement artifacts are stored.

Bare-metal fulfillment reloads this binding for every step. Site-targeted capacity reservation, scheduling, fulfillment begin/status/result, teardown, and capacity release use the configured client selected by the recorded site or the durable reservation-to-site map. A buyer assertion, provider response, or opaque artifact cannot replace the site, URL, principal, Physical Resource, machine, or physical-host identity. Restart therefore changes neither authority nor executor, and capacity is released exactly once only after authoritative teardown succeeds.

The result channel is pull-based: the storefront polls the recorded fulfillment and converts its versioned bare-metal envelope to a durable buyer-safe receipt and credential-free access result. Provider payloads, private SSH material, authority URLs, credentials, and connection coordinates are not copied into market state, evidence, listings, or run logs. A separate buyer-authenticated access read re-fetches the active selected-site result and returns only the transient SSH host, port, public tenant user, and lease expiry. It is unavailable after teardown begins and is never persisted by the storefront.

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

## Bare-metal hosted readiness

Bare-metal publication begins with one complete fresh signed selected-site projection and the trusted domain listing derived from it. It then intersects access capability, authoritative availability, exact hosted profile/currency/country/account/condition readiness, offer and funding deadlines, and maximum fulfillment duration. Every ready profile becomes a deterministic independent option; an unready profile becomes a sanitized blocker without suppressing its ready peers. Stale or conflicting site/resource facts close or omit the option, never trigger site fallback or mutate an accepted binding.

The common publication runner carries `settlement_options` independently from legacy `accepted_escrows`. The dedicated publication command authenticates registry mutation with the storefront signer and records the exact derived source only after success.

## API-credit hosted publication

Quota availability and settlement readiness are separate inputs. Publication
first requires an authoritative sellable API-credit resource, then compiles
each complete ready mechanism clause independently. Hosted clauses become
distinct deterministic `SettlementOption` objects; Alkahest entries remain
legacy `accepted_escrows`. The listing schema and registry projections allow an
empty escrow list, so a hosted-only listing does not manufacture a chain
carrier. Accepted negotiation persists the exact selected option and a
quantity-scaled integer amount for later server-authoritative preparation.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Fulfillment](../fulfillment/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
