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

Domain packages define what is bought and sold: listing fields, provision intent, deterministic validation, terms interpretation, fulfillment requirements, and domain result vocabulary. Kit packages supply reusable mechanisms and authorities such as identity, policy middleware, obligation servicing and stateless payment clients, site capacity, resource pools, and fulfillment scheduling. Composition roots select concrete implementations and are therefore allowed to depend on all lower layers.

## Typed phase boundaries

A conceptual market flow is:

```text
messages → Agreement → selected settlement evidence → domain provisioning
```

A phase remains separate when core-owned machinery or a typed invariant lies between it and the next phase. That separation gives each role a stable handoff, lets persistence and recovery refer to a durable carrier, and prevents a domain implementation from bypassing shared lifecycle rules. Hooks may be combined when no shared behavior or meaningful carrier exists between them.

These carriers are intentionally less expressive than every domain model. Domain-specific meaning travels in validated, versioned envelopes and is interpreted only by the owning domain or mechanism codec.

`market_core.settlement` owns `SettlementStageTable[StageT]` and
`SettlementEvidence`, exported by the dependency-light carrier wheel. The table
is an immutable mapping of canonical mechanism IDs to opaque domain-owned
values, with no callable bound or required stage methods. A settlement
capability declares independent `buyer_stages` and `seller_stages`; startup
validates non-empty support for its supplied roles, not mechanism payloads.
Escrow plan builders are explicitly injected helpers, not universal capability
methods.

Evidence carries only negotiation ID, mechanism, optional opaque settlement
reference, non-empty domain status and a domain-owned payload mapping. Carrier
fields and the copied mapping are immutable; nested payload values remain
opaque. Core checks identity continuity without defining a financial state
machine. Pending evidence can lack a reference. The seller's selected stage,
not buyer-local progress, owns the protected delivery gate.

The arrows describe handoffs, not an actor schedule. Seller-first, buyer-first
and fused settlement/delivery stages are equally valid. The selected domain
stage owns source revalidation and any post-delivery attestation, claim binding
or compensation. Core does not serialize continuations or choose them from
current priority.

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

For mechanisms using the obligation runtime, it owns materialize, status, check, collect, and reclaim transitions. Arkhai payments bypasses that API and owns no servicing worker. Mechanism clients may keep opaque durable state, but they cannot
introduce a second scheduler or persistence authority. Domain-private delivery
data remains in the domain's existing response channel and never becomes
generic settlement state.

A verified-only domain may register and adopt a pre-materialized obligation
without installing a servicing worker. Full servicing begins only after the
composition can bind a real immutable fulfillment reference; a no-op executor
would falsely advertise collectability.

Each domain composes independent buyer and seller role tables. Registrations
control fresh admission; accepted work resolves its recorded Agreement through
the table even when publication is disabled. VM and API-credit tables bind
Alkahest and payments; bare-metal purchase binds payments while its seller also
binds Alkahest and fused contact exchange. Delivery consumes validated source
and domain facts, not the mechanism ID or an escrow-shaped progress row.

Compatible kits may opt into a stage convention, but no shared convention or
adapter is required or implemented. Its package is chosen when concrete reuse
justifies implementation: a kit, never core or either mechanism package. Contact,
seller-first and fused stages need no adapter. The obligation runtime is not an
assumed home for a convention consumed by non-escrow mechanisms.

## Settlement configuration registration

Composition roots register installed settlement mechanisms explicitly. Each registration contributes its canonical ID, typed configuration, role applicability, preflight, client factory, listing-option builder, buyer compatibility, and optional command group. Core roles consume only ordered registrations and common readiness; they neither branch on mechanism IDs nor import concrete configuration models.

Registration controls construction, not lifecycle ownership. A composition injects the marketplace signer, wallet, chains, or other shared resources only into mechanisms that declare them, then composes only the lifecycle the selected mechanism uses. An Arkhai-payment-only VM composition starts without EVM resources. Its mandate and receipt feed the existing selected-site fulfillment stage, not the obligation journal.

## Frozen storefront registry and executable ownership

The compute-family storefront executable is core-owned, schema-opaque role
machinery extended from below. Installed domain packages publish one validated
`StorefrontDomainContribution` through the canonical
`market.storefront_contributions` entry group. Public configuration selects an
exact contribution/mode/domain/version set; startup validates it and freezes
one registry before state or network effects. Each registry value retains the
exact contract object plus its publication and legacy-migration hooks.

Application, persistence, publication, negotiation, settlement, fulfillment,
recovery, result, and teardown layers receive that same registry. Every listing
binding freezes its selected contribution identity, contract version, Resource
Pool offering mode, trusted site, and Physical Resource; negotiation copies the
immutable binding before storing a domain artifact. Durable bindings resolve
only to their pre-registered exact objects, and schema-opaque payloads are
validated only by the selected contract. A one-domain storefront uses these
same carriers with one explicit registration, never a separate executable or
default, so adding a shared shell changes neither persistence nor routing.

## Storefront composition kit

`arkhai-kit-storefront`, imported as `market_storefront_kit`, is the reusable
role-composition layer between the common schema-opaque storefront executable
and the lower core storefront shell. A composition supplies the frozen
`StorefrontDomainRegistry`, one selected durable binding, the exact registered
`MarketDomainContract`, immutable service/container lifecycle callbacks, and
an ordered route and middleware contribution. The kit places the registry in
application state, builds the lifespan-owned container against the selected
contract, and rejects even an equal contract reconstructed outside the
registry. Domain codecs, negotiation policy, settlement, fulfillment, and
publication semantics remain behind registered hooks; the kit never looks them
up globally or interprets their payloads.

The kit also owns storefront mechanisms whose control flow is common across
domains. Alkahest client construction receives an immutable tuple of chain
name, RPC URL, address-config path, private-key readiness, and missing
requirements. The negotiation watchdog receives an existing repository plus
timeout, interval, terminal-state, and event hooks. These inputs preserve
operator and domain configuration without copying the factory or sweep loop.
Per-chain construction failures remain isolated, and stale-thread write or
event failures do not stop later threads or later sweeps.

Multi-site capacity publication follows the same inversion. The capacity kit
owns exact site projection, event reconciliation, registry fan-out, durable
publication results, and close-before-reopen ordering. A domain contributes
schema-opaque candidates, codecs, and durable binding hooks. Each candidate
carries one exact `CapacityBinding(site_id, offering_mode, source_id)` whose
mode is declared by the selected Resource Pool and matches the public offer.
Commit, release, fulfillment, and restart use the recorded site and never
default a mode or fan out to another authority.
Seller-authenticated creation carries the capacity source separately from the
public resource. The storefront checks that source against the configured site
topology and the parsed offer, then writes the listing projection and immutable
binding in one SQLite transaction before publishing. This prevents a visible
listing from existing without the authority route required by negotiation,
reservation, fulfillment, and recovery.

Settlement servicing keeps a domain-neutral
`StorefrontSettlementFulfillmentInput` with the accepted thread binding, buyer
principal, opaque domain input, and optional fulfillment anchor. At delivery,
core constructs `StorefrontFulfillmentContext` by adding the selected stage's
evidence and caller-owned authority ports, resolves the exact contract from the
same frozen registry, invokes only that contract's fulfillment hook, and
rejects a result that changes the negotiation, settlement reference, or site
identity. The VM hook translates the opaque input into VM executor arguments; core and kit
own lifecycle and dispatch, while the domain owns interpretation and the
concrete effect.

The buyer CLI and registry executable remain core-owned for the same
schema-opaque reason. Each domain package exports one validated contribution
while retaining its market meaning, codecs, publication semantics, seller
policy,
route and service contributions, and concrete fulfillment behavior. A
one-domain executable or shared shell owns process configuration. The
bare-metal contribution uses shared lifecycle contexts with its own
site/capacity/fulfillment adapters and never imports VM services. The
compute-family shell gives VM and bare metal the shared frozen-registry
lifecycle, while API credits composes the same kit mechanisms at its own
non-physical storefront boundary. No topology gains a default domain, global
selector, or no-op fulfillment implementation.

## Agreement-based payment composition

Core defines shared-reader carriers: public settlement options, accepted Agreements, role tables and settlement evidence. Mechanism status, refunds and provisioning translation stay in the supporting domain/kit composition. `make_settle_hook` looks up `Agreement.settlement.mechanism` in the injected buyer table and passes the exact negotiation to its domain-owned invoker. Missing entries fail before effects. `make_escrow_settle_hook` is an explicit helper for an applicable entry, never a default.

Acceptance fixes exact Agreement bytes and puts the seller-derived mandate in opaque `settlement_data`; both are committed together in `negotiation_threads` and carried in responses and outcomes. VM, bare-metal, and API-credit sellers load the mandate by negotiation ID, poll its deterministic transaction ID, verify the signed receipt, and only then provision or issue. Pending evidence is retryable, completed calls are idempotent, and nonterminal domain work is re-driven. Receipt evidence and physical/grant progress remain domain-owned.

## Identity composition

Marketplace identity is a foundation kit alongside the generic settlement lifecycle. It owns canonical principals, signer/verifier dispatch, authenticated request and response envelopes, replay handling, and rotation primitives. The dependency is deliberately one way: roles, domains, settlement adapters, and their composition roots may depend downward on these interfaces, while the identity kit imports no role, domain, settlement mechanism, hosted provider, or chain runtime.

Composition roots resolve public identity and secret credential material separately, construct one scheme-neutral signer, and inject it into registry, negotiation, service-peer, and settlement clients. Core orchestration carries the complete principal and signer ports opaquely; it neither branches on scheme or private-key shape nor treats an identifier as a wallet address, provider account, or mechanism setting. Scheme plugins own identifier interpretation, while provider account references remain resources rather than credentials. A domain can therefore compose Ed25519 marketplace identity without an EVM package.

Chain and provider dependencies enter only after a composition root selects a concrete mechanism. The selected domain or settlement adapter owns wallet derivation, chain preflight, RPC clients, and provider SDKs; a no-wallet Arkhai payment composition consequently does not instantiate an Alkahest client or import those dependencies into scheme-neutral orchestration.

Arkhai payment authentication is independent of marketplace request signing: headless calls use owner-scoped WorkOS API keys, and receipts use the service's Ed25519 `arkhai.payments.receipt.v1` framing. Generated wire models and identity-kit verification preserve the published service boundary without importing service code.



## Current limits

The composition contract covers the shipped role protocols and versioned domain contracts; it is not a claim that every possible market shape fits the current phases. Auctions, sealed-bid protocols, arbitrary settlement plans, and a universal storefront executable require explicit changes rather than inference from the extension points.

API-credit standalone negotiation still constructs Alkahest prerequisites and
proposals directly. This surface does not establish the same-table admission
contract.

The frozen-registry, binding, and dispatch seams have deterministic repository
evidence, but complete live VM/bare-metal restart, teardown, and
capacity-restoration proof requires deployment against an external production
site authority, provider, and the selected-site POOLS-7 lifecycle. The shipped
bare-metal contribution and its exact hooks do not by themselves prove live
hardware access or revocation. A no-op hook, synthetic result, or common-shell
success cannot stand in for that proof.


## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Registry discovery](../registry-discovery/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
