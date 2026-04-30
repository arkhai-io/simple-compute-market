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

**Slice 3 — Registry wire** ✅ committed
Registry routes `/orders` → `/listings`, `/agents/{id}/orders` →
`/agents/{id}/listings`, `/orders/{id}` → `/listings/{id}`.
arkhai-registry-client SDK methods + types (`OrderRequest`/`OrderSummary`/
`OrderListResponse`/`UpdateOrderRequest` → `ListingRequest`/`ListingSummary`/
`ListingListResponse`/`UpdateListingRequest`; `publish_order`/`list_orders`/
`get_order`/`update_order`/`delete_order`/`get_agent_orders` → ...listing).
JSON wire keys: `order_id` → `listing_id`, `order_maker` → `seller`,
`order_taker` → `buyer`, `maker_attestation` → `seller_attestation`,
`taker_attestation` → `buyer_attestation`. Wrapper `{"order": ...}`
→ `{"listing": ...}`. EIP-191 op strings: `create_order`/`update_order`/
`delete_order` → `create_listing`/`update_listing`/`delete_listing`.
AttestationStats fields: `settled_order_count`/`maker_attestation_count`/
`taker_attestation_count` → `settled_listing_count`/`seller_attestation_count`/
`buyer_attestation_count`. Buyer CLI `market order list/show` →
`market listing list/show` (file renamed `groups/order.py` →
`groups/listing.py`). Translation at the FastAPI boundary keeps the DB
columns on the legacy `order_*`/`*_attestation` names; `_listing_body_to_columns`
flips inbound, `order_to_dict` flips outbound.

**Slice 4 — DB (registry)** ✅ committed
Alembic migration `008_rename_orders_to_listings`: table
`market_orders` → `listings`; columns `order_id` → `listing_id`,
`order_maker` → `seller`, `order_taker` → `buyer`,
`maker_attestation` → `seller_attestation`, `taker_attestation` →
`buyer_attestation`; indexes renamed; Postgres enum
`orderstatusenum` → `liststatusenum`. SQLAlchemy model + API code +
tests updated to use the new column names directly. Wire-translation
helpers (`_listing_body_to_columns`, `order_to_dict`) deleted now that
the DB matches the wire.

**Slice 4b — DB (storefront SQLite)** ⏳ deferred
The storefront's local SQLite has the same schema rename pending.
Has high blast radius (~2500 lines of `sqlite_client.py` + ~30
internal callers passing kwargs like `order_id`/`order_maker`). The
wire-translation shims added in Slice 2 (`_row_to_wire`/`_wire_in`/
`_wire_out` in `agent.py` and `listings_controller.py`) keep the
storefront wire on the listings vocabulary while the SQLite columns
stay legacy. Migration block scaffolding exists; full rewrite
deferred to a follow-up commit.

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
