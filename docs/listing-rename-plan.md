# Listing rename plan-of-record

Rename `order` → `listing` everywhere it refers to the seller-posted
offering, and tighten attestation field names from `maker`/`taker` to
`seller`/`buyer`. Cold-cut: no backwards-compat aliases, since we're
mid-refactor and aliases would bloat the surface.

## Term mappings

| Old | New |
|---|---|
| order (seller-posted offering) | **listing** |
| order_id | listing_id |
| seller_order_id | listing_id |
| MarketOrder (ORM class) | Listing |
| `market_orders` (DB table) | `listings` |
| OrderCreateEvent / OrderCloseEvent | ListingCreatedEvent / ListingClosedEvent |
| `event_type = "ORDER_CREATE"` | `event_type = "LISTING_CREATED"` |
| `/orders/...` (registry + storefront routes) | `/listings/...` |
| `/api/v1/orders/{id}/negotiations/...` (admin) | `/api/v1/listings/{id}/negotiations/...` |
| maker_attestation | seller_attestation |
| taker_attestation | buyer_attestation |
| `market order list/show` | `market listing list/show` |
| `market-storefront provide` | `market-storefront publish` |

Negotiation / `negotiation_id` / `/negotiate/...` /
`negotiation_strategy` / `negotiation_thread` / the four pausability
admin endpoints — all stay. The asymmetry that needed fixing was
order→listing; negotiation is already the right word.

## Slices

Each slice ships green tests + green smoke; cold-cut at slice boundaries.

**Slice 1 — ORM model + event class names** ✅ committed (`9511ce2`)
Lowest-blast-radius rename: ORM class + top-level pydantic event
classes only. Wire surface (route paths, JSON keys, DB column
names, event_type strings) all unchanged. Pure Python identifier
rename. After this, the codebase reads as "Listing" internally
even though the wire still says "order".

**Slice 1b — Storefront CLI verb rename** ✅ committed
`market-storefront provide` → `market-storefront publish`. Pure CLI
verb rename, no wire change. File renamed cli_provide.py →
cli_publish.py via git mv.

**Slice 1c — agent → storefront CLI flag** ✅ committed
`--agent-url` → `--storefront-url` on the `escrow claim` /
`escrow refund` / `publish` commands. Helper `resolve_agent_url` →
`resolve_storefront_url`. ERC-8004-protocol-flavored "agent"
mentions left alone (agent_card, register_onchain, AgentRegistered,
etc.).

**Slice 2 — Storefront wire** ✅ committed
Storefront server routes `/orders/...` → `/listings/...`,
`/api/v1/orders/{id}/negotiations/...` →
`/api/v1/listings/{id}/negotiations/...`. arkhai-storefront-client
SDK methods + types renamed (`create_order`/`StorefrontOrderCreateResponse`
→ `create_listing`/`StorefrontListingCreateResponse`, etc).
JSON wire keys: `order_id` → `listing_id`, `order_request` →
`listing_request`, `seller_order_id` → `listing_id` in
`/negotiate/new` body, `our_order_id` → `our_listing_id` in
negotiation responses, `their_order_id` → `their_listing_id` in
discover matches, `open_orders`/`paused_orders` →
`open_listings`/`paused_listings` in admin status. EIP-191 signed
operation strings renamed (`create_order`→`create_listing`, etc).
Buyer-side `seller_order_id` field flipped to `listing_id`
across run-log, DealContext, AgreedTerms, CLI flag (`--listing-id`),
and orchestrator. SQLite table inside the storefront keeps
`orders`/`order_id` columns for now (Slice 4); translation happens
at the controller boundary.

**Slice 3 — Registry wire**
Registry routes `/orders` → `/listings`, `/agents/{id}/orders` →
`/agents/{id}/listings`. arkhai-registry-client SDK rename.
`market order list/show` → `market listing list/show`. JSON
response field `order_id` → `listing_id` (and the maker/taker rename
is bundled here).

**Slice 4 — DB**
Alembic migration renaming `market_orders` → `listings` and
`maker_attestation` → `seller_attestation`,
`taker_attestation` → `buyer_attestation`. Both repositories'
SQLite local DBs migrated.

**Slice 5 — Docs + helm**
ARCHITECTURE.md, READMEs, helm values comments,
cli-redesign-plan.md, integration-test fixture names.

## agent → storefront (parallel pass, smaller)

Selective rename of seller-runtime occurrences of "agent" that are
*not* ERC-8004 protocol terms. ERC-8004 explicitly defines the
identity surface as "agents" — those references stay.

| Status | Term | Notes |
|---|---|---|
| Rename | `agent_db_path` | seller-runtime config |
| Rename | `agent_url` (CLI flag) | per-storefront pointer |
| Rename | `agent.py` (file) | the storefront server module |
| Rename | `AGENT_DB_PATH` (env if any) | seller-runtime |
| Rename | `agent_settings` (test fixtures, config sections) | seller-runtime |
| Keep | `register_onchain` / canonical_agent_id | ERC-8004 |
| Keep | `agent_card` | ERC-8004 |
| Keep | `agent_id` (when it's the on-chain ERC-8004 numeric ID) | ERC-8004 |
| Keep | `IdentityRegistry`, `AgentRegistered` | ERC-8004 |
| Keep | `agent_heartbeat` | ERC-8004 discovery — protocol surface |

Specifically: any place where "agent" means "the seller's runtime
process" → storefront. Any place where "agent" means "an entity
registered under ERC-8004" → keep.

## Coordination

Coworker just landed pausability + e2e scaffold on
`negotiations_controller.py` at `/api/v1/orders/{id}/negotiations`.
Slice 2 is the one that hits his code (renames the route prefix);
the rest of his work is unaffected. Slices 1 / 3 / 4 / 5 don't
touch his hot files.
