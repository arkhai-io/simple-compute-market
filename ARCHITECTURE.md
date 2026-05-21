# Arkhai Market Stack — Architecture Reference

> **Purpose:** This document is intended to initialize AI-assisted development sessions with accurate, up-to-date context about the repository structure, service responsibilities, data flows, and known problem areas. Treat it as a living document — update it as understanding deepens.

---

## Repository Overview

**Simple Market Service (SMS)** is a reference implementation of an agent-driven compute marketplace. Autonomous buyer and seller agents discover each other, negotiate prices, and settle agreements on-chain using Alkahest smart contracts. Physical compute (VMs) is provisioned post-settlement via Ansible.

The stack is designed so that in production, multiple independent seller nodes each run their own agent + provisioning stack, while buyers can be ephemeral (a CLI invocation or a long-running agent). The `test-env` component exists only for local development.

### Technology Anchors

| Concern | Technology |
|---|---|
| On-chain settlement / escrow | [Alkahest](https://github.com/arkhai-io/alkahest) contracts |
| Agent identity & discovery | [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) (ERC-721-based agent registry) |
| Buyer ↔ seller protocol | Plain HTTP request/response, EIP-191-signed bodies |
| Seller server framework | FastAPI / Starlette + uvicorn |
| Buyer | Pure HTTP client — `market` CLI, no server |
| VM automation | Ansible (via `compute-provisioning-iac` submodule) |
| Job queue | In-process `asyncio.Queue` (no external queue dependency) |
| Overlay networking (optional) | ZeroTier |
| Local dev chain | Anvil (Foundry) |

---

## Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EVM Chain (Alkahest)                         │
│   IdentityRegistry · ReputationRegistry · ValidationRegistry       │
│   Alkahest escrow contracts                                         │
└──────────────────┬──────────────────────┬───────────────────────────┘
                   │ events / txns         │ events / txns
         ┌─────────▼──────────┐   ┌───────▼─────────────────┐
         │  registry-service  │   │  storefront             │
         │  :8080             │   │  :8001 (seller only)    │
         │  FastAPI indexer   │◄──┤  FastAPI                │
         │  SQLite/Postgres   │   │  market-storefront serve│
         └─────────▲──────────┘   └────────────┬────────────┘
                   │  GET /listings            │ HTTP (provisioning API)
                   │  signed reqs    ┌─────────▼───────────────┐
                   │                 │ provisioning-service    │
         ┌─────────┴──────────┐      │   API  :8081  (FastAPI) │
         │  buyer (`market`)  ├─────▶│   Job loop (in-process) │
         │  pure HTTP client  │ HTTP └────────┬────────────────┘
         │  no server         │ buyer→seller  │ asyncio.Queue
         │  signed bodies     │      ┌────────▼────────────────┐
         └────────────────────┘      │  Ansible playbooks      │
                                     │  (compute-provisioning- │
                                     │   iac submodule)        │
                                     └─────────────────────────┘

 ┌──────────────┐   ┌────────────────────────────────────────┐
 │  test-env    │   │  Operator CLIs                         │
 │  Anvil node  │   │   market           — buyer runtime     │
 │  (dev only)  │   │   market-storefront — seller runtime   │
 └──────────────┘   │   market-policy    — train/eval/export │
                    │   market-infra     — chain/registry/zt │
                    └────────────────────────────────────────┘
```

Negotiation flow: the buyer's `market buy`/`market negotiate`
discovers seller orders from `registry-service`, then issues
synchronous signed POSTs against the seller's storefront
(`/negotiate`, `/listings/...`, `/settle/{escrow_uid}`). The seller's
storefront evaluates each request through the policy engine, decides
counter/accept/exit, and returns the next round inline. There are no
push messages and no symmetric agent-to-agent protocol — the buyer
drives every round.

---

## Component Summaries

### `test-env`

**Role:** Local development chain fixture.

An Anvil (Foundry) instance with Alkahest contracts pre-deployed and chain state saved to `test-env/state/state.json`. The Dockerfile loads this snapshot at startup, giving a deterministic chain for every dev session. Restarting the container resets chain state.

In production this component is absent — the agent and registry configs point to a live RPC endpoint (e.g., Base Sepolia or mainnet).

**Key facts:**
- Default port: `8545`
- State is generated by the root `build-anvil-state` Makefile target, which runs the `market-contract-deployer` image against a fresh Anvil and dumps the resulting state
- Contract addresses from the baked state are written to `shared-env/.env`, which buyer/seller agent containers source at runtime

> **TODO:** Document the exact set of Alkahest contracts deployed and their addresses in the baked state.

---

### `registry-service`

**Role:** Off-chain indexer and discovery service for on-chain agent/order state.

FastAPI service that watches the EVM chain for ERC-8004 events (`AgentRegistered`, `MetadataSet`, `UriUpdated`) and maintains a queryable local database. Also serves the **Orders API** — agents publish open orders here so counterparties can discover them.

**Ports:** `8080` (default)

**Databases:**
- Dev: SQLite (`registry.db`)
- Prod: PostgreSQL

**Key APIs:**
- `GET /agents` — discover registered agents
- `GET /agents/{agentId}` — agent detail + health status
- `POST /agents/{agentId}/heartbeat` — agents POST signed heartbeats to stay "healthy"
- `POST /agents/{agentId}/listings` — publish/update an order
- `GET /listings` — global order book query; query params are **spec-driven** (resolved against `filter-spec.yaml` — see below), not a hardcoded signature
- `PUT /listings/{listing_id}` — update order status (e.g., mark accepted/closed)
- `POST /api/v1/listings/validate-publish` — JSON Schema dry-run check of a publish candidate against `filter-spec.yaml`'s `listing_shape` (Draft 2020-12); used by the buyer/seller pre-publish path
- `GET /api/v1/filter-spec` — current filter spec; ETag-tagged for client caching

**Indexer-maintained schema — registry owns the filter vocabulary:**

A series of refactors in May (a1b-1 through a1b-6, then `cce58f0`) moved the
filter vocabulary from being implicit (hardcoded in routes / shared with the
storefront and clients via enums and per-axis kwargs) to being **registry-
maintained, schema-driven, and self-describing** via `filter-spec.yaml`. The
practical effect: adding a new discovery filter is a YAML edit, not a route
signature change in the registry, and not a code change in the storefront or
any client wheel.

What the spec carries:

- `listing_shape` — JSON Schema for what a valid publish candidate looks like
  (offer-side resource axes, escrow shape requirements, required fields).
  This is what `validate-publish` runs Draft 2020-12 against.
- `filters` — declarative list of supported `GET /listings` query parameters.
  Each declaration names the parameter, the JSONPath it resolves against on
  listing dicts, the operator (`equals`, `in`, `lower_bound`, `upper_bound`,
  `contains`, …), and an optional `on_missing` policy.
- Enums like `gpu_model` (Blackwell back to Volta + workstation + consumer
  cards) live here. The storefront field types dropped the closed
  `GPUModel`/`Region` enums in `cce58f0` (now plain `str`) — the registry is
  the single enforcement point so sellers can list any hardware string but
  discovery is gated centrally.

What the cutover replaced:

- `registry-service/src/api/utils.py::matches_resource_filters` — a
  23-parameter signature that took every supported filter as a kwarg —
  along with `get_resource_type` and `resources_match` were deleted in a1b-3.
  Replaced by the generic evaluator in `src/api/filter_eval.py`: `build_criteria(spec, params)`
  compiles the spec + request params into parsed JSONPath criteria;
  `evaluate_all(criteria, listing)` returns the matching listings. Array-
  projection paths (`accepted_escrows[*]...`) are supported via jsonpath-ng.
- The storefront's `GET /api/v1/listings` (a1b-4) shed all discovery
  filters — it's now a slim local-enumeration view (`status`, `paused`,
  `limit`, `offset`). Discovery goes through the registry; the storefront
  is the seller's local state surface.
- `arkhai-registry-client` 0.6.0 and `arkhai-storefront-client` 0.9.0 (a1b-5)
  dropped the per-axis kwargs from their `list_listings()` signatures —
  callers compose the filter param dict themselves now.

**ETag protocol for spec-vs-query consistency:** `GET /filter-spec` returns
an `ETag` header that's a sha256 over the canonical JSON of the loaded YAML.
Buyers cache the spec by URL+ETag and pass `If-Match: <etag>` on
`GET /listings`. On ETag mismatch the registry returns **412 Precondition
Failed** rather than silently honouring a query built against a stale spec.
`If-Match` is optional — clients that don't care about spec drift can omit
it.

**Where the YAML lives and how it ships:** `registry-service/filter-spec.yaml`
in source, copied into both build stages of the registry Docker image
(`a1b-6` fix — the original add only had it in the source tree, causing
`FileNotFoundError` on the first `/listings` call in compose). Loaded once
at import via `lru_cache`; path overridable via `REGISTRY_FILTER_SPEC_PATH`
env var. To rotate the spec without rebuilding the image, mount the new
YAML over the baked one and restart the registry; buyers detect the change
via the ETag on the next `/filter-spec` fetch.

**Agent identity format (ERC-8004 canonical):**
```
eip155:{chainId}:{identityRegistryAddress}:{numericAgentId}
```
Example: `eip155:1337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:22`

The agent id for a seller/storefront can be found in the status endpoint.

**Source layout:**
```
registry-service/src/
├── api/             # FastAPI routes (agent_routes, order_routes)
├── contracts/       # ABI + web3.py interaction layer
├── db/              # SQLAlchemy models + Alembic migrations (7 versions so far)
├── services/        # event_sync.py (chain watcher), health_check.py
├── types/
└── main.py
```

> **TODO:** Document the event sync polling interval and any known lag or missed-event issues.

> **TODO:** Document the symmetric order concept visible in the test suite (`test_symmetric_orders.py`).

---

### `storefront` (Seller-side server)

**Role:** The seller's HTTP server. Hosts the `/listings/...`,
`/negotiate`, `/settle/{escrow_uid}`, `/alerts/resource`, and
`.well-known/erc-8004-registration.json` endpoints that buyers and the
provisioning service call. Runs as `market-storefront serve` (uvicorn,
FastAPI/Starlette). Internally it uses Alkahest for on-chain escrow
operations.

**Ports:** `8001` (default seller port; `seller.port` in config.toml).

**Startup sequence:** `entrypoint.sh` starts the ZeroTier daemon,
then `exec market-storefront serve`. On `@app.on_event("startup")` the
server joins the configured ZeroTier network if any, then runs
`_ensure_agent_identity()`:

- If `seller.onchain_agent_id` is set in config (fast path) — use that
  ID directly, no chain interaction.
- If `seller.auto_register = true` (default) and no ID is set — call
  `perform_registration()`, hold the resolved numeric ID in the
  module-level `_AGENT_ID` for the process lifetime, and log a hint to
  pin it in config.
- If `seller.auto_register = false` and no ID is set — raise
  `RuntimeError` immediately. The pod crashes with a clear message
  rather than silently minting a new on-chain identity.

After identity is resolved, the heartbeat sender, resource poller, and
negotiation watchdog are started as background tasks.

The `market-storefront register` console verb still exists and works
identically to before — operators can run it manually to inspect or
update registration. It now delegates to the shared `perform_registration()`
helper extracted from the same module.

**Key source layout:**
```
storefront/src/market_storefront/
├── cli.py                  # `market-storefront` console-script entry
├── commands/
│   └── register.py         # in-process port of the legacy register_onchain.py
├── server.py               # FastAPI app, lifespan, run_serve() (publish loop removed)
├── container.py            # Resolved service singletons (populated in lifespan)
├── agent.py                # Startup/background-task helpers only:
│                           #   _startup_tasks, _ensure_agent_identity, _start_heartbeat,
│                           #   _preflight_provisioning, process_queued_events
│                           #   TraderAgent class (kept for _RootAgentShim; see planned rework)
├── controllers/
│   ├── listings_controller.py     # GET/POST /api/v1/listings/* + /listings/create|close|refund|…
│   ├── negotiations_controller.py # GET/POST /api/v1/listings/*/negotiations/*
│   ├── negotiate_controller.py    # POST /negotiate/new, /negotiate/{neg_id}
│   ├── settle_controller.py       # POST /settle/{uid}, GET /settle/{uid}/status
│   ├── system_controller.py       # GET /health, /api/v1/system/*, /admin/policy/*
│   ├── admin_controller.py        # POST /admin/pause|resume
│   ├── alerts_controller.py       # POST /alerts/resource
│   └── identity_controller.py     # GET /.well-known/*
├── middleware/
│   ├── admin_auth.py       # AdminAuthMiddleware (X-Admin-Key enforcement)
│   ├── buyer_auth.py       # Depends() factories for EIP-191 buyer signature verification
│   └── seller_auth.py      # Depends() factory for EIP-191 seller signature verification
├── models/
│   ├── domain_models.py      # Domain types: ComputeResource, Listing, DomainEvent, etc.
│   ├── listing_models.py     # HTTP shapes: ListingFilterParams, CreateListingRequest, …
│   ├── negotiation_models.py # HTTP shapes: NegotiateNewRequest, ForceAcceptRequest, …
│   ├── settle_models.py      # HTTP shapes: SettleRequest, SettleStatusResponse
│   ├── alert_models.py       # HTTP shapes: ResourceAlertResponse
│   └── system_models.py      # HTTP shapes: PolicyEvaluateRequest, HealthResponse, …
├── services/
│   ├── listing_service.py         # ListingService: create/close/refund/claim/reclaim/…
│   ├── policy_service.py          # PolicyService: policy negotiation + infra
│   ├── alkahest_service.py        # build_client(): AlkahestClient factory
│   ├── negotiation_service.py     # NegotiationService: advance/force-accept/list/get
│   └── system_service.py          # SystemService: health/seed/evaluate + registry checks
├── groups/                 # CLI groups: config, escrow, network
├── cli_publish.py, cli_portfolio.py, cli_logs.py, cli_common.py
├── negotiation_watchdog.py, agent_heartbeat.py
├── policy/seeding.py
├── utils/
│   ├── config.py, sqlite_client.py, action_executor.py
│   ├── sync_negotiation.py, settlement_jobs.py, serializer.py
│   └── …
└── data/                   # Alkahest address registry + sample resource CSVs
                            # (Token symbol/decimals resolve on-chain; cached
                            # at $XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json)
```

**Storefront component diagram:**
```
┌─────────────────────────────────────────────────────────────────────┐
│                        Storefront Process                           │
│                                                                     │
│  HTTP (FastAPI / controllers/)                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │  listings   │ │ negotiations │ │    system    │ │   admin    │ │
│  │ controller  │ │  controller  │ │  controller  │ │  (agent.py)│ │
│  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └─────┬──────┘ │
│         │               │                │               │        │
│  ┌──────▼───────────────▼────────────────▼───────────────▼──────┐ │
│  │                   SQLiteClient                                │ │
│  │  listings · negotiation_threads · negotiation_messages        │ │
│  │  stage_events · policy_config · resource_portfolio            │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              sync_negotiation.py  (request-scoped)            │ │
│  │                                                               │ │
│  │  start_sync_negotiation()   continue_sync_negotiation()       │ │
│  │         │                            │                        │ │
│  │         └──────────┬─────────────────┘                        │ │
│  │                    ▼                                           │ │
│  │         _load_storefront_strategy()                           │ │
│  │              │                                                │ │
│  │    ┌─────────┴──────────┐                                     │ │
│  │    │  NegotiationStrategy (market_policy)                     │ │
│  │    │  • BisectionStrategy  ← default; no ML deps              │ │
│  │    │  • TorchArkhaiStrategy ← opt-in; requires torch          │ │
│  │    └─────────┬──────────┘                                     │ │
│  │              ▼                                                 │ │
│  │    NegotiationDecision {action, price, reason}                │ │
│  │              │                                                │ │
│  │    stage_event("negotiation","round_decided",                  │ │
│  │               decision, decision_reason)  ──► stage_events DB │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  Background tasks                                                   │
│  ┌─────────────────────┐  ┌───────────────┐                        │
│  │ negotiation_watchdog│  │agent_heartbeat│                        │
│  └─────────────────────┘  └───────────────┘                        │
│                                                                     │
│  Resource lifecycle now owned by provisioning service LeaseWatchdog │
│  which calls PATCH /api/v1/admin/portfolio/resources/{id} on expiry │
│                                                                     │
│  Outbound                                                           │
│  ┌─────────────────────┐  ┌──────────────────┐                     │
│  │   RegistryClient    │  │ProvisioningClient│                     │
│  │ (arkhai-registry-   │  │(provisioning-    │                     │
│  │  client wheel)      │  │ service wheel)   │                     │
│  └─────────────────────┘  └──────────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Listing payment model — `accepted_escrows` + `ProvisionTerms` + `EscrowProposal`:**

The old model put the price on the listing as a `demand_resource` of type
`TokenResource` (i.e. a hard-coded `(token, amount)` tuple). That was retired
across a series of refactors in May; the current model splits **what the seller
will deliver** from **what gates the payment**, and expresses the latter as
on-chain escrow calldata rather than as a typed `TokenResource`.

**Listing-side advertisement — `accepted_escrows`:** Each listing carries a
JSON column `accepted_escrows: list[AcceptedEscrow]`. One entry pins the
`(chain_name, escrow_address)` tuple plus a partial advertisement of the
on-chain `ObligationData` struct via a `fields` map. The seller is saying "I
will accept payment via *these* escrow contracts on *these* chains, with
*these* field values pinned." Multiple entries allow multi-chain or
multi-contract offers (e.g. mainnet ERC20 + a Base Sepolia ERC20 alongside a
hypothetical ERC721 escrow). Each entry also carries a `price_per_hour` —
**this** is the price column the negotiation strategy reads as the seller's
floor; the listing no longer carries a top-level `(token, amount)`.

`fields` is **shape-only** — present keys are advertised values; absent keys
are open for the buyer to propose. Whether an advertised value is a hard
constraint or a negotiable default is the seller's negotiation policy's
concern, not protocol infrastructure. `amount` is never in `fields`: the
on-chain `ObligationData.amount` is derived at settlement from
`price_per_hour × duration_seconds / 3600` after the negotiation agrees a rate
and duration.

**Round-0 wire shape:** `POST /api/v1/negotiate/new` carries two structured
fields:

- `provision_terms: ProvisionTerms` — `{duration_seconds, ssh_public_key,
  compute_resource}`. What the seller will deliver off-chain. Read by the
  seller's settlement/provisioning pipeline as the single source of truth for
  what to provision.
- `escrow_proposal: EscrowProposal` — `{chain_name, escrow_address, fields,
  expiration_unix}`. The buyer picks one of the listing's `accepted_escrows`
  by `(chain_name, escrow_address)` and supplies the buyer-committable
  `ObligationData` keys in `fields`. `amount` is intentionally **not** on the
  proposal — it's derived at settlement.

The seller validates the proposal in `_validate_escrow_proposal`: match the
`(chain_name, escrow_address)` against an entry in the listing's
`accepted_escrows`, then field-equality-check every seller-advertised value
on the matched entry. On non-rejection paths, `NegotiateNewResponse` echoes
both as `accepted_provision_terms` and `accepted_escrow_proposal` — settlement
code on both sides reconstructs the same on-chain `obligation_data` from
those echoed values.

**Settlement is a byte-compare, not a dispatch:** `EscrowTerms`
(`service.schemas.EscrowTerms`) is the negotiated artifact — a flat mirror of
the alkahest `ObligationData` struct: `{maker, escrow_contract,
obligation_data, expiration_unix}`. The settlement verifier reads the
on-chain obligation by UID and byte-compares against the negotiated
`EscrowTerms.obligation_data`. New escrow kinds (ERC721, native, bundle,
attestation) add no code: they only change which keys appear in
`obligation_data`. The alkahest **slot lookup** (address-to-kind reverse
map, configured per chain) replaces the old `escrow_kind` discriminator
string — adding a new escrow contract is a config change, not a code change.

A negotiation produces `list[EscrowTerms]` so multi-escrow designs (payment
+ seller penalty deposit, block-by-block schedules) are expressible without
a wrapper type. Today every list is length-1 (single buyer-made ERC20
escrow); the rest is forward shape.

**Where `demand_resource` still appears:** the legacy column itself is gone
in any DB that's been started by current code — `sqlite_client.py` runs a
one-shot startup migration that backfills `accepted_escrows` from
`demand_resource` (via `synthesize_accepted_escrows_from_demand`) and then
does `ALTER TABLE listings DROP COLUMN demand_resource`. But `demand_resource`
survives as the **request-input shape** for creating a listing:
`CreateListingRequest.demand` is still the field clients POST; the storefront
parses it into a typed `TokenResource`, runs it through the policy chain
(`evaluate_create_listing_policy_from_raw(offer_raw, demand_raw, …)`), then
synthesizes the `accepted_escrows` row at the write boundary. So the on-disk
model is `accepted_escrows` end-to-end, but the API still takes
`{offer, demand}` and translates inward — a wider buyer-facing API redesign
hasn't happened yet. The `_extract_initial_price_from_order` "fallback to
`demand_resource`" branch in `action_executor.py` is reachable only for
pre-migration listings whose synthesis failed at startup (e.g. anvil without
an alkahest override JSON resolving the escrow address); after the column
drop those rows can't read it either, so the branch is effectively dead and
should come out when the request-input format is also migrated.

---

**Negotiation strategy selection — critical runtime behaviour:**

`sync_negotiation.py` does **not** use the `@policy_callable` domain policy chain for deciding what to do in a negotiation round. It uses the `market_policy.negotiation_strategy` module directly via `_load_storefront_strategy()`. The two systems are parallel and independent:

- The `@policy_callable` chain (in `domain/compute/agent/app/policy/store.py`) handles listing-level decisions: whether to accept an order, what price floor to set, whether to pause. Many of these callables are currently no-ops (`if True: return None`) because the events they depended on (`NegotiationEvent`, `AcceptOfferEvent`) were removed when the rename happened.
- The `NegotiationStrategy` (`market_policy.negotiation_strategy`) handles round-by-round decisions during an active negotiation: accept, counter at midpoint, or exit. This is what actually fires at each `/negotiate/new` and `/negotiations/{id}/advance` call.

`_load_storefront_strategy()` resolves the strategy as follows:
1. Read `CONFIG.negotiation_policy_mode` (from `seller.negotiation.policy_mode` in TOML; default `"bisection"`)
2. If `"rl"`: register `TorchArkhaiStrategy` (requires torch + pufferlib + model file); if torch is absent, `TorchArkhaiStrategy.decide()` returns `exit(reason="torch_unavailable")` every round — silent failure
3. Call `load_strategy(name)` from the in-process strategy registry
4. Return the strategy instance

**Negotiation direction:** determined by `determine_strategy_from_resources()` in `utils/validation.py`. Since the `demand_resource` cutover, listings carry only an `offer_resource` (the payment side moved into `accepted_escrows` — see the section above). Seller offering `ComputeResource` → direction `"maximize"` (the seller wants the highest price the buyer will pay). The buyer's CLI runs in `"minimize"` direction from the opposite side of the same protocol.

**BisectionStrategy convergence (maximize direction):**
- Accept if `their_price >= our_price * (1 - CONVERGENCE_RATIO)` (default ratio ≈ 0.01, so accept within 1%)
- Counter at `(our_price + their_price) // 2` if `their_price >= our_price / 1.5`
- Exit with `reason="price_unreasonable"` otherwise

`our_price` is extracted from `accepted_escrows[0].price_per_hour` via `_extract_initial_price_from_order()` in `action_executor.py`. This is the seller's price floor — the buyer's opening offer must be at or above this value for the seller to counter rather than exit immediately.

**`checks.negotiation_strategy` in system status:** `GET /api/v1/system/status` now includes a `negotiation_strategy` check that instantiates the configured strategy and runs a synthetic maximize probe. If the strategy would exit on the probe (e.g. `"TorchArkhaiStrategy (exit_on_probe: torch_unavailable)"`), the check surfaces this before any negotiation is attempted. The smoke test (`test_negotiation_strategy_viable`) and e2e stage 00d both assert on this field.

**`checks` degraded-status evaluation:** Each check value is evaluated by `_check_is_healthy(key, value)` in `system_service.py` rather than against a fixed set of `"ok"` literals. This is because `negotiation_strategy` returns a human-readable strategy name (e.g. `"bisection"`) on success rather than the literal `"ok"`. The `_check_is_healthy` function treats the `negotiation_strategy` key specially: healthy unless the value contains `"exit_on_probe"` or starts with `"unknown:"` / `"error:"`. All other check keys use the literal set `{"ok", "unconfigured", "agent_not_found", "indexing"}`. When adding a new check to `get_status()` whose success value is not `"ok"`, either: (a) return `"ok"` on success and put the diagnostic name in a separate top-level fact field, or (b) add a key-specific rule to `_check_is_healthy`.

The legacy `core/agent/app/` tree is gone. Files that lived there
either moved into `storefront/src/market_storefront/` (server,
resource poller, watchdog, action executor) or into the standalone
`market-policy` package (policy store, manager, registry, evaluator,
composite, negotiation thread, action builders).

**Policy system:** lives in `market-policy` (package: `policy/`,
import: `market_policy`). Policies are named callables registered
with `@policy_callable("name")` and stored in a `PolicyStore`. When a
negotiation request hits the storefront, the evaluator runs the
registered chain until one returns an action
(`accept` / `reject` / `counter` / `exit`). The seller seeds its
default policies at server startup via
`market_storefront.policy.seeding.ComputePolicySeeder`. The buyer
side imports the same engine at CLI invocation time but does not run a
server.

**Critical policy wiring detail:** `PolicyStore.__init__` creates an **empty** `self._registry = {}`. The `@policy_callable` decorators populate the module-level `CALLABLE_REGISTRY` dict in `market_policy.registry`. These two are only connected by an explicit call to `policy_store.register_callables(CALLABLE_REGISTRY)`. `PolicyManager.initialize()` does this wiring at startup. Any code that creates a fresh `PolicyStore` instance (controllers, tests, seed endpoints) **must** call `register_callables` before evaluating policies, or `evaluate_policy` will always return `None` despite callables being registered in `CALLABLE_REGISTRY`.

**Orchestration over Event-Driven for Request-Path Operations:** The storefront request path uses a **synchronous orchestrator pattern**, not an event-driven pipeline. This decision was made after examining the existing code and the e2e test requirements.

**What "event-driven" meant in the original code:** The policy dispatch layer required domain events as its input format — `PolicyStore.evaluate_policy` receives a `DecisionContext` whose `event` field is a typed `DomainEvent` subclass (e.g. `ListingCreatedEvent`). This was preserved. What was removed was the awkward choreography that surrounded it: `process_event()` returning a human-readable string while storing structured results as side effects in `_last_action_outcomes`, and callers doing `pop_outcome()` to retrieve them.

**What "orchestration" means here:** Each public service method is a named sequence of private steps:

```python
async def create_listing(self, request: CreateListingRequest, policy_svc) -> CreateListingResponse:
    offer, demand = self._parse_offer_demand(request)          # step 1: validate inputs
    action = await policy_svc.evaluate_create_listing_policy(  # step 2: consult policy
        offer, demand, request.max_duration_seconds, request.paused
    )
    if action != "make_offer":
        return CreateListingResponse(status="no_action")
    listing_id = await policy_svc.execute_create_listing(      # step 3: execute
        offer, demand, request.max_duration_seconds, request.paused
    )
    return CreateListingResponse(status="created", listing_id=listing_id)
```

Each step is independently callable from an admin endpoint for diagnosis — see the `evaluate-create` and `evaluate-close` admin endpoints.

**Why not pure event-driven:** The buyer CLI and e2e test expect `listing_id` synchronously in the create-listing response. There is no queue consumer process. `is_event_queue_enabled()` always returns `False` in normal operation (the redis path is a dead branch). The event-flavoured naming added indirection without adding capability.

**The thin untested wrapper:** A future pure event-driven architecture would look like:

```python
def create_listing(request: CreateListingRequest) -> CreateListingResponse:
    event_id = self._write_to_queue(request)           # write first event
    result = await self._listen_for_result(event_id)   # await completion
    return result
```

The synchronous orchestrator tests everything except this two-line wrapper, which is correct by inspection.

**The in-memory event queue** (`enable_event_queue`, `enable_redis_ingest`, `is_event_queue_enabled()`) is dead code. See `## Storefront — Planned Rework` item 2 for the removal plan.

`PolicyService` class exposes only named domain-language methods. Domain event construction is fully private. Callers (`ListingService`, `AlertsController`) never construct domain events themselves. The word "event" does not appear in any public method name. Event construction (`_build_listing_created_event`, `_build_listing_closed_event`) is private.

**`domain/` package — not installed, on sys.path:** `domain/compute/agent/app/policy/store.py` contains the actual `@policy_callable` decorated functions the storefront uses. The `domain/` tree is not a pip-installable package — it is copied into the Docker image at `/app/domain/` and requires `/app` to be on `sys.path`. The Dockerfile sets `ENV PYTHONPATH="/app"` to ensure this. The `POST /admin/policy/seed` endpoint also does a defensive `sys.path` check as a fallback. `domain.compute.agent.app.policy.arkhai_common` always fails to import (requires `gymnasium`) — this is expected and non-fatal; the module we actually need is `store.py`, which has no ML dependencies.

**Local state — SQLite:** the storefront maintains a SQLite database
(`seller.db_path`) containing policy configuration, order history,
negotiation threads, and the resource portfolio. This is a known area
of complexity — see Known Issues below.

**Docker build pattern — two-phase uv install:**

The storefront Dockerfile uses a two-stage build to cache the heavy
dependency install separately from the volatile project source:

1. **Builder stage** — runs `uv sync --no-install-project` to populate
   `.venv` with all third-party and internal-wheel dependencies. The
   project package itself is deliberately excluded so this layer is
   only invalidated when `pyproject.toml` or `uv.lock` change.

2. **Runtime stage** — copies the pre-built `.venv` from the builder,
   then copies the project source, then runs a completing
   `uv sync --no-dev --find-links /dist` (without `--no-install-project`)
   to install the project package and write the `market-storefront`
   console script to `.venv/bin/`.

Omitting the completing `uv sync` in the runtime stage means
`market-storefront` is absent from `.venv/bin/` and `entrypoint.sh`
exits 127. Both stages must be present for the console script to work.

**Critical: `/dist/` must be sourced from the build context in both stages.**

The runtime stage's completing `uv sync` must `COPY .dist/ /dist/`
directly from the build context — **not** `COPY --from=builder /dist /dist`.
The builder's `/dist/` layer is cached independently of `.dist/` on disk:
if `pyproject.toml` and `uv.lock` are unchanged, Docker reuses the builder
cache and the runtime stage receives whatever wheels were baked at the last
full rebuild, silently ignoring any `make dist` runs since. Sourcing from
the build context ensures the runtime layer invalidates whenever `.dist/`
changes, keeping installed internal packages in sync with the host.

**BuildKit context cache and when to use `make build-no-cache`:**

BuildKit caches the build context transfer keyed on file contents. If
`.dist/` was excluded from the context during earlier builds (e.g., by a
stale `.dockerignore`), BuildKit's cached context snapshot will not contain
the wheels even after the ignore file is corrected — subsequent `make build`
runs serve the poisoned snapshot. `make build-no-cache` passes `--no-cache`
to `docker build`, which forces BuildKit to re-evaluate the context from disk
and invalidates all layer cache. Use it when:

- A `.dockerignore` change is not being reflected in the context transfer size
- A `make dist` run is not being picked up despite the correct Dockerfile setup
- Any situation where the build completes without error but the wrong package
  version ends up in the container

Under normal operation (`.dist/` correctly in context, no ignore file issues),
`make build` is sufficient — BuildKit will invalidate the `COPY .dist/ /dist/`
layer whenever wheel file contents change.

> **TODO (tracked):** Document Alkahest escrow mechanics — what on-chain calls are made at which points in the negotiation lifecycle (escrow lock, attestation submission, release).
> **TODO (tracked):** Document the SQLite schema — table definitions, index strategy, and known statefulness/concurrency constraints (single-writer SQLite, negotiation message ordering).
> **TODO (tracked):** Document `negotiation_watchdog` — what staleness threshold triggers it, what it writes to the DB, and how it interacts with in-flight `/advance` calls.
> **TODO (next session):** Negotiation refactor — restore the `NegotiationEvent` model and rewire the `@policy_callable` domain callables so round-by-round decisions flow through the callable chain rather than bypassing it via `_load_storefront_strategy()`. Goal: testability via the existing policy dry-run infrastructure, visibility via the existing stage events stream.

#### Storefront API Surface (`controllers/`)

The storefront exposes a structured REST API via a `controllers/` package,
mirroring the provisioning service's controller pattern. All controllers are
mounted in `server.py` alongside the legacy `a2a_app` routes.

**System controller** (`controllers/system_controller.py`) — HTTP layer only; all logic in `services/system_service.py`:
```
GET  /health                            Kubernetes liveness/readiness probe (DB ping only — no outbound calls)
GET  /api/v1/system/health              Versioned alias
GET  /api/v1/system/status              Diagnostic snapshot: DB health + registry connectivity check + global pause state
GET  /api/v1/system/events              Stage event log — historical JSON query or live SSE tail (admin key required)
POST /admin/policy/seed                 Discover @policy_callable decorators + seed default DB rows (admin key)
GET  /api/v1/system/policy              Callable registry + seeded policies with components_resolvable flag
POST /api/v1/system/policy/evaluate     Dry-run a synthetic order_create event through the policy engine (no writes)
```

**`/health` vs `/api/v1/system/status`:** `/health` performs only a fast SQLite ping — no outbound HTTP calls, safe as a Kubernetes liveness probe. `/api/v1/system/status` additionally probes `CONFIG.indexer_url/health` with a 2-second timeout and reports the result as `checks.registry` (`"ok"` | `"unreachable"` | `"timeout"` | `"unconfigured"` | `"http_<N>"`). A `checks.registry != "ok"` result means `resume_listing` will silently return `registry_status="error"` — this is the first thing to check when stage 04 or 05 of the e2e test fails.

**`GET /api/v1/system/events`** — admin-key required. Serves the `stage_events` SQLite table as either a historical JSON query or a live Server-Sent Events stream. All significant storefront transitions (listing published, negotiation started, settlement fulfilled, etc.) are written to this table via `stage_event()` in `stage_log.py`. Query parameters:

| Parameter | Default | Description |
|---|---|---|
| `since_id` | `0` | Return only rows with `id > since_id`; use last seen `id` as cursor |
| `limit` | `100` (max 500) | Max rows for historical queries |
| `stream` | `false` | If `true`, hold connection open and push rows as SSE (`text/event-stream`) |
| `stage` | — | Filter by stage column (`discovery`, `negotiation`, `settlement`, `provision`) |
| `listing_id` | — | Filter by listing_id |
| `negotiation_id` | — | Filter by negotiation_id |

SSE format: `id: <row_id>\ndata: <json>\n\n`. Reconnect with `Last-Event-ID` header to resume without gaps. The SSE stream polls the SQLite table every 200ms — no pub/sub bus required. This endpoint is the foundation for operator dashboards and alerting; the e2e test suite uses it via `SyncStorefrontClient.wait_for_stage_event()` to avoid polling loops at stages 14 and 16.

**Listings controller** (`controllers/listings_controller.py`):
```
GET  /api/v1/listings                      List the seller's own local listings (status, paused, limit, offset)
GET  /api/v1/listings/{listing_id}         Single listing detail (includes paused flag)
POST /api/v1/listings/{listing_id}/pause   Take listing off market — admin key required
POST /api/v1/listings/{listing_id}/resume  Unpause + publish to registry — admin key required
```

Note: this is a **local enumeration view**, not a discovery API. Since a1b-4
the storefront no longer carries discovery filters (`gpu_model`, `region`,
`ram_gb_min`, `token`, etc.) — those moved to the registry's spec-driven
filter evaluator. Buyer-side discovery queries `GET /listings` on a registry
with `filter-spec.yaml`-declared parameters; the storefront's listings
endpoint is for the seller looking at their own state.

`resume_listing` calls `publish_order_to_registry(row)` after clearing the paused flag. This is idempotent if the listing was already published, and is the **required step** to push a listing that was created with `paused=True`. The response includes `registry_status`: `"published"` on success, `"error"` if the registry call failed, `"disabled"` if `enable_registry_discovery=false`. Stage 04 of the e2e test asserts `registry_status == "published"` — a failure here is always a registry connectivity or configuration issue, not a storefront bug. Run `GET /api/v1/system/status` and check `checks.registry` to diagnose.

**Negotiations controller** (`controllers/negotiations_controller.py`):
```
GET  /api/v1/listings/{listing_id}/negotiations                        List threads (filter: terminal_state, buyer_address)
GET  /api/v1/listings/{listing_id}/negotiations/{neg_id}               Full detail: thread + messages + stage_events
POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/advance       Admin: drive one round — admin key required
POST /api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept  Admin: commit terminal-success — admin key required

**Negotiation process flow:**
```
Buyer                    Storefront (/negotiate/new)         SQLite
  │                              │                              │
  │── POST /negotiate/new ───────►│                              │
  │   {listing_id, buyer_address, │                              │
  │    initial_price, duration,   │                              │
  │    signature, timestamp}      │                              │
  │                              │── verify EIP-191 sig ────────►│
  │                              │◄─ ok ────────────────────────│
  │                              │── check global pause ─────────►│
  │                              │◄─ not paused ─────────────────│
  │                              │── load listing ───────────────►│
  │                              │◄─ listing row ────────────────│
  │                              │                              │
  │                              │  _load_storefront_strategy() │
  │                              │  determine_direction()        │
  │                              │  strategy.decide(round_input) │
  │                              │  → NegotiationDecision        │
  │                              │                              │
  │                              │── INSERT negotiation_thread ──►│
  │                              │── INSERT negotiation_message──►│
  │                              │   (round=0, sender=buyer,     │
  │                              │    action=make_offer)         │
  │                              │── INSERT negotiation_message──►│
  │                              │   (round=1, sender=seller,    │
  │                              │    action=decision.action)    │
  │                              │── stage_event(round_decided,  │
  │                              │   decision, decision_reason)──►│
  │                              │                              │
  │◄─ 200 {neg_id, action,───────│                              │
  │        proposed_price}       │                              │
  │                              │                              │
  │  [if action == "counter"]    │                              │
  │── POST /negotiations/{id}    │                              │
  │       /advance ──────────────►│                              │
  │   {buyer_price, signature}   │  continue_sync_negotiation() │
  │                              │  strategy.decide(round_input) │
  │                              │── INSERT negotiation_message──►│
  │                              │── stage_event(round_decided)──►│
  │◄─ 200 {action, price} ───────│                              │
  │                              │                              │
  │  [or admin force-accepts]    │                              │
  │── POST /force-accept ─────────►│                              │
  │                              │── UPDATE thread terminal ─────►│
  │◄─ 200 {action=accept, price}─│                              │
```

**Negotiation lifecycle phases (stage events emitted):**

All negotiation events are written to `stage_events` with `stage="negotiation"` and are queryable via `GET /api/v1/system/events?stage=negotiation&negotiation_id=<id>`.

| Event | Trigger | Key data fields |
|---|---|---|
| `negotiation_started` | `/negotiate/new` accepted (sig valid, not paused) | `listing_id`, `buyer_address`, `initial_price` |
| `round_decided` | Seller strategy returns a decision (every round) | `round`, `our_price`, `their_price`, `decision` (`accept`/`counter`/`exit`), `decision_price`, `decision_reason` |
| `negotiation_accepted` | Decision is `accept` or admin `force-accept` | `agreed_price`, `neg_id` |
| `negotiation_exited` | Decision is `exit` | `decision_reason` (e.g. `price_unreasonable`, `torch_unavailable`) |

**`decision_reason` values:**

| Reason | Strategy | Meaning |
|---|---|---|
| `convergence` | Bisection | Buyer price within 1% of seller floor — accepted |
| `price_unreasonable` | Bisection | Buyer price below `our_price / 1.5` — too far to counter |
| `torch_unavailable` | RL | torch import failed; strategy exits every round |
| `model_missing` | RL | Model file not found at configured path |
| `price_unreasonable` | RL | RL policy evaluated and rejected the offer |

**Key invariants:**
- `our_price` in every `round_decided` event equals `accepted_escrows[0].price_per_hour` from the listing (the seller's floor; stored in uint256-domain base units — decimal-scaled at advertisement time, not at read time)
- A `round_decided` with `decision=exit` means the negotiation is already in terminal `failure` state — `force-accept` will return 409
- The `round` field in messages is 0-indexed for the buyer's initial offer; the seller's response is round 1, subsequent buyer counters are round 2, etc.
```

**Admin controller** (`controllers/admin_controller.py`):
```
POST  /api/v1/admin/pause    Set globally paused = True — admin key required
POST  /api/v1/admin/resume   Set globally paused = False — admin key required
GET   /api/v1/admin/status   Live counts: active_negotiations, open_orders, paused_orders
PATCH /api/v1/admin/portfolio/resources/{resource_id}
      Partial update of a resource row — admin key required.
      Body: { state?, attributes? } — only non-None fields written.
      Primary use: lease expiry release by the provisioning LeaseWatchdog:
        { "state": "available", "attributes": { "lease_end_utc": null } }
      Also used for operator recovery and test state manipulation.
      Returns: full updated row + updated=true/false (idempotent flag).
      404 if resource_id does not exist.
POST  /api/v1/admin/portfolio/release-reservations
      Bulk-release all held (reserved or leased) resources — admin key required.
      Sledgehammer; prefer PATCH above for targeted single-row release.
```

Note: legacy redirect aliases `/admin/pause` and `/admin/resume` (without `/api/v1` prefix) are registered in `server.py` for backwards compatibility with existing scripts.

#### Admin API Key

A global admin API key gates all admin-only endpoints. Read from
`CONFIG.admin_api_key` (`[seller].admin_api_key` in config.toml, or injected
via the Helm secrets profile as a `config-storefront-secrets.yml` entry).
Enforced by `AdminAuthMiddleware` via the `X-Admin-Key` header. When
`admin_api_key` is `None` (local dev default), the middleware is a no-op.

Protected paths: any route under `/admin/`, and any route ending in `/pause`,
`/resume`, `/advance`, or `/force-accept`.

**`global.adminApiKey`:** `values.yaml` carries `global.adminApiKey` (default `"test-api-key"` for the test cluster). The `agentConfigToml` helper renders it as `[seller] admin_api_key` in the mounted `config.toml`. The per-agent secret profile (`config-{component}-secret.yml`) also carries it under `{component}.admin_api_key` so the e2e test pod can read it via dynaconf without a separate secret mount.

#### Global Pause and Per-Order Pause

**Global pause** (`_GLOBALLY_PAUSED` flag in `server.py`): when `True`, all
`POST /negotiate/new` requests return 503 with machine-readable body
`{"error": "paused", "reason": "global", "hint": "..."}`. In-flight
negotiations are not interrupted. Toggled via `POST /admin/pause|resume`.

**Per-listing pause** (`paused` INTEGER column on the `listings` table, default 0):
when set for a specific listing, `POST /negotiate/new` against that listing returns
503 with `{"reason": "order:<listing_id>"}`. Toggled via
`POST /api/v1/listings/{id}/pause|resume`.

Listings can be **created already-paused** by passing `"paused": true` in the
`POST /orders/create` body. This threads through the policy pipeline:
`agent.py` reads the flag from the request body → adds it to `OrderCreateEvent.data["paused"]`
→ `oc_action_make_offer_from_order_create` in `domain/compute/agent/app/policy/store.py`
propagates it into `action.parameters["paused"]`
→ `action_executor.py` MAKE_OFFER handler writes the listing to SQLite with `paused=1`
and **skips** `publish_order_to_registry`.
The listing is invisible to buyers until `POST /api/v1/listings/{id}/resume` is called,
which clears `paused=0` and calls `publish_order_to_registry`. This is the mechanism
used in the e2e test to assert registry non-visibility (stage 03) before controlled
publication (stage 04).

Both flags are checked at the top of `start_sync_negotiation()` in
`sync_negotiation.py`, raising `StorefrontPausedError` which the negotiate
endpoint converts to HTTP 503.

#### Negotiation Detail Response Shape

`GET /api/v1/listings/{listing_id}/negotiations/{neg_id}` returns the full
buyer↔seller conversation in one call (no DB access required from callers):

```json
{
  "negotiation_id": "neg_abc",
  "our_listing_id": "listing_xyz",
  "their_agent_id": "0xBuyerAddress",
  "terminal_state": "success",
  "agreed_price": 9000,
  "round_count": 4,
  "messages": [
    {"round": 0, "sender": "0xBuyer", "action_taken": "make_offer", "proposed_price": 7000},
    {"round": 1, "sender": "http://seller:8001", "action_taken": "counter_offer", "proposed_price": 9500},
    {"round": 2, "sender": "0xBuyer", "action_taken": "counter_offer", "proposed_price": 8500},
    {"round": 3, "sender": "http://seller:8001", "action_taken": "accept_offer", "proposed_price": 9000}
  ],
  "stage_events": [...]
}
```

No new DB state — reads `negotiation_threads`, `negotiation_messages`, and
`stage_events` tables.

---

### `buyer` (Pure HTTP client)

**Role:** The buyer side of the market. There is no buyer server, no
agent runtime, no SQLite database — only the `market` console script
(package: `buyer/`, import: `market_buyer`).

`market buy` is a one-shot orchestrator: it queries
`registry-service` for matching seller orders, runs synchronous
negotiations against each candidate seller's storefront (POST
`/negotiate`, signed bodies), and on agreement creates the on-chain
escrow via `alkahest_py` directly from the CLI process before POSTing
`/settle/{escrow_uid}` and polling for fulfillment. `market negotiate`
is the same loop bound to a single known seller; both share
`buy_orchestrator`.

The negotiation policy used by the buyer is the same `market-policy`
engine the seller runs — both sides import a `BisectionStrategy` (or,
behind the `[rl]` extra, the trained Arkhai pufferlib checkpoint)
through `market_policy.negotiation_strategy`. Round-by-round events
land in a per-run JSONL log under
`$XDG_STATE_HOME/arkhai/buy-runs/<run_id>.jsonl` rather than a
database.

**Key source layout:**
```
buyer/market_buyer/
├── cli.py                  # `market` console-script entry
├── groups/                 # buy, negotiate, settle, listing, escrow, chain,
│                           # network, config, logs (+ _deal/_cli_helpers shared)
├── buy_orchestrator.py     # the one-shot buy flow
├── buyer_client.py         # signed HTTP client for /negotiate, /api/v1/settle
├── escrow_client.py        # alkahest-py escrow create/reclaim
├── run_log.py              # JSONL run logs under XDG_STATE_HOME
└── common.py               # config-resolution + REPO_ROOT helpers
```

`market settle --from <run_id>` is the post-agreement half of the flow: it
reads the agreed terms from the run-log JSONL, creates the on-chain escrow
under the buyer's wallet via `make_create_escrow_fn`, then POSTs
`/api/v1/settle/{uid}` (note the `/api/v1` prefix — earlier releases POSTed
to bare `/settle/{uid}` and 404'd) and polls for fulfillment. The buyer's
negotiation strategy is selected via `[buyer.negotiation].policy_mode` in the
TOML, mirroring the seller's `[seller.negotiation].policy_mode` — default
`bisection`; `rl` requires torch + a checkpoint.

---

### `policy` (`market-policy`)

Domain-agnostic strategy engine + training tool. Two surfaces:

- **Library**: `market_policy.{store, manager, registry, evaluator,
  composite, negotiation_thread, negotiation_strategy,
  action_builders, identity}` — imported by both runtimes.
- **CLI**: `market-policy train / eval / export` — invoked by
  policy authors to produce strategy artifacts (RL checkpoints) that
  buyers and sellers load at runtime through
  `market_policy.negotiation_strategy.load_strategy()`.

The CLI lives here (not in either runtime) because policy authoring
is a tooling concern separate from the buyer or seller process.

---

### `provisioning-service`

**Role:** Physical settlement layer. Converts completed on-chain agreements into running VMs.

A unified single-process service: the FastAPI app and the background job processing loop run together in one uvicorn process.

```
Agent ──HTTP──▶ Provisioning API :8081
                      │         │
                      │    asyncio.Queue (in-process)
                      │         │
                      └── job DB (SQLite/Postgres)
                                │
                         Job Processing Loop
                                │
                         ansible-playbook──▶ KVM host
```

Long-running Ansible playbooks (up to `ANSIBLE_TIMEOUT_SECONDS=1800`) are launched as non-blocking subprocesses via `asyncio.create_task`. The event loop stays responsive to new requests while playbooks run. Up to `max_concurrent_jobs` (default 5) jobs run in parallel, controlled by an `asyncio.Semaphore`. The in-process `asyncio.Queue` replaces the former Redis queue; the service has no external queue dependency.

#### Service layer architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Controllers (FastAPI layer)                                │
│  VmController, HostController, JobController (read-only)    │
│  Accepts typed per-operation requests                       │
│  Returns job_id; OpenAPI docs describe polling pattern      │
└─────────────────────────┬───────────────────────────────────┘
                          │ AnsibleJobParams (internal DTO)
┌─────────────────────────▼───────────────────────────────────┐
│  AnsibleJobService                                          │
│  - submit(AnsibleJobParams, agent_id, job_queue) → job_id   │
│  - list/get/cancel/credentials/logs (read ops)              │
│  - _process_job(job_id) — handler passed to AsyncJobQueue   │
└──────────────┬──────────────────┬──────────────────────────┘
               │ handler dispatch │ direct call
┌──────────────▼──────┐  ┌───────▼──────────────────────────┐
│  AsyncJobQueue      │  │  AnsibleService                  │
│  (queue mgmt only)  │  │  - start_playbook()              │
│  - enqueue(job_id)  │  │  - wait_for_playbook()           │
│  - start(handler)   │  │  - build_vars_file()  ← absorbed │
│  - is_alive()       │  │  - parse_playbook_result() ←     │
│  No Ansible/DB      │  │  - _inject_golden_image_creds()  │
│  knowledge          │  │  - parse_inventory()             │
└─────────────────────┘  │  - lookup_host_ip()              │
                         │  - check_connectivity()          │
                         └──────────────────────────────────┘
```

---

#### Job Lifecycle

Jobs are tracked in the `ansible_jobs` database table. Status transitions:

```
queued ──▶ running ──▶ succeeded
                  └──▶ failed (retryable) ──▶ queued (re-enqueued with backoff)
                  └──▶ failed (permanent, or max retries exceeded)
queued ──▶ cancelled  (by API call before worker picks it up)
running ──▶ cancelled (SIGTERM sent to ansible-playbook PID, stored in job.process_id)
```

**Retry behavior:** Failed jobs are retried with exponential backoff (`initial=60s`, `multiplier=2x`, `max=3600s`) up to `max_retries` (default 3, caller-overridable per job up to 10). Certain errors are non-retryable and short-circuit immediately: SSH auth failures, host unreachable, domain not found, disk image lock conflicts, and others defined in `config.non_retryable_errors`.

**Job DB fields of operational interest:**

| Field | Meaning |
|---|---|
| `status` | `queued / running / succeeded / failed / cancelled` |
| `params` | Full JSON of the original `ProvisionRequest` |
| `result` | Structured JSON from Ansible on success (SSH info, VM name, GPU, FRP, resources, etc.) |
| `error` | Error string on failure, including retry scheduling info |
| `logs` | Raw Ansible stdout+stderr, updated every ~2s while running; credentials redacted |
| `process_id` | PID of the running `ansible-playbook` subprocess — useful for host-level inspection |
| `retry_count / max_retries / next_retry_at` | Retry state |
| `agent_id` | ERC-8004 ID of the seller who submitted the job |
| `buyer_agent_id` | ERC-8004 ID of the buyer (tenant) — controls credential visibility |

**Credentials** are stored separately in the `credentials` table (joined to job by `job_id`), split by role:
- `root` — granted to seller only; includes root password and SSH key path on host
- `tenant` — granted to both seller and buyer; includes tenant password and SSH commands (internal + external via FRP)

---

#### VM Actions (all routed through a single playbook: `vm-operations.yaml`)

All actions are submitted as `ProvisionRequest` jobs with a `vm_action` field. The single Ansible playbook dispatches to action-specific task files based on the `vm_action` variable.

| `vm_action` | What it does | Notable behavior |
|---|---|---|
| `create` | Provision a new KVM VM | Writes a cleanup script to `/usr/local/bin/cleanup_vm_<name>.sh` on the host; configures FRP tunnel; optionally attaches GPU passthrough |
| `list` | List all VMs on the host | No `vm_target` required |
| `start` | Start a stopped VM | |
| `shutdown` | Graceful ACPI shutdown | |
| `destroy` | Force-kill a running VM | Does not remove storage or definition |
| `reboot` | Reboot a running VM | |
| `undefine` | Remove VM definition from libvirt | Typically paired with storage cleanup |
| `monitor` | Collect CPU/memory/disk/network stats | See details below |
| `reset_password` | Reset the tenant user password | |
| `lease_end` | Schedule VM destruction at a future UTC datetime | Uses the host's `at` daemon — **the timer runs on the KVM host, not in the provisioning service** |
| `lease_remove` | Cancel a previously scheduled `lease_end` | Finds and removes `at` jobs tagged `LEASE:<vm_name>` |
| `check` | Report host capacity (total/allocated/available vCPUs, RAM, GPUs) | No `vm_target` required |

---

#### Lease Lifecycle — DB-driven watchdog

The provisioning service owns lease lifecycle via the `vm_leases` table and the `LeaseWatchdog` background task. When the storefront provisions a VM, it registers a lease with the provisioning service via `POST /api/v1/leases` after the create-VM job succeeds. The legacy `lease_end` scheduling job is best-effort and must not block settlement readiness; the `LeaseWatchdog` is the authoritative release path and calls back to the storefront's `PATCH /api/v1/admin/portfolio/resources/{resource_id}` when leases expire.

**`vm_leases` table:**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | Internal lease ID |
| `resource_id` | TEXT | Storefront-assigned resource identifier (e.g. `compute-ww1-001`). Application-level FK — unvalidated by the provisioning service. |
| `escrow_uid` | TEXT UNIQUE | On-chain escrow UID. One deal = one lease. |
| `vm_host` | TEXT | KVM host alias (Ansible inventory name) |
| `vm_target` | TEXT | Libvirt domain name of the provisioned VM |
| `lease_start_utc` | DATETIME nullable | Null = lease active immediately on creation |
| `lease_end_utc` | DATETIME | When the lease expires |
| `status` | TEXT | See `LeaseStatus` enum below |
| `create_job_id` | TEXT nullable | Provisioning job_id of the VM creation job. Allows tracing from lease back to the original create job. |
| `check_job_id` | TEXT nullable | Provisioning job_id for the most recent watchdog check job (set during `releasing` phase) |

**`LeaseStatus` values:**

| Status | Meaning |
|---|---|
| `pending` | `lease_start_utc` is in the future; VM may not yet be running |
| `active` | Lease is running; `lease_end_utc` is in the future |
| `releasing` | `lease_end_utc` passed; watchdog submitted a check job to confirm VM cleanup |
| `released` | Storefront `PATCH /resources/{id}` called successfully; resource is available again |
| `forced` | Grace period elapsed; storefront patched without VM confirmation |
| `cancelled` | Lease cancelled before expiry |

**Lease flow:**

```
Storefront (after provisioning succeeds)
  │
  └── POST /api/v1/leases  →  vm_leases row created (status=active or pending)

LeaseWatchdog (every 60s, or on-demand via POST /api/v1/system/check-leases)
  │
  ├── list_pending_to_activate(now)  →  advance pending leases whose start has passed
  ├── list_due(now)  →  active leases with lease_end_utc < now
  │
  ├── For each due lease:
  │   ├── Submit check Ansible job (vm_action=check, vm_host, vm_target)
  │   └── begin_releasing(check_job_id) → status=releasing
  │
  ├── list_releasing()  →  leases with check jobs in flight
  │   ├── Poll check job status
  │   ├── On succeeded / failed+past-grace:
  │   │   ├── PATCH {settings.storefront_url}/api/v1/admin/portfolio/resources/{resource_id}
  │   │   │     body: { state: "available", attributes: { lease_end_utc: null } }
  │   │   │     headers: X-Admin-Key: {settings.storefront_admin_key}
  │   │   ├── On 200/404: mark_released()
  │   │   └── On patch failure within grace: skip (retry next cycle)
  │   │       On patch failure past grace: mark_forced()
  │   └── On still-running + within grace: skip (wait next cycle)
```

**Watchdog configuration** (`settings.toml` → dynaconf):
```toml
lease_watchdog_enabled = true
lease_watchdog_poll_interval_seconds = 60
lease_watchdog_grace_period_seconds = 300
storefront_url = ""          # base URL of the storefront (global, not per-lease)
storefront_admin_key = ""    # X-Admin-Key for storefront admin endpoints
                             # inject via provisioning-secrets profile in production
```

`storefront_url` and `storefront_admin_key` are global settings on the provisioning service — one provisioning service instance serves one storefront. They are not stored per-lease.

**On-demand trigger:** `POST /api/v1/system/check-leases` runs one watchdog cycle immediately. Used by operators and tests to avoid waiting for the 60-second timer. Returns `{ activated, checked, released, forced, skipped }`.

**Leases API:**
```
POST   /api/v1/leases                  Register a new lease (called by storefront)
GET    /api/v1/leases                  List leases (filter: status, vm_host, escrow_uid)
GET    /api/v1/leases/{lease_id}       Get one lease by internal ID
PATCH  /api/v1/leases/{lease_id}       Partial update (status, check_job_id, lease_end_utc)
GET    /api/v1/leases/by-escrow/{uid}  Lookup by escrow_uid (storefront recovery path)
DELETE /api/v1/leases/{lease_id}/cancel  Cancel a lease before expiry
```

---

#### `monitor` action — what it returns

`monitor` runs a series of `virsh` commands against the named VM on the target host and returns structured JSON. Fields returned via the job's `result.resources`:

- `cpu.usage_percent` — calculated from two `virsh domstats` samples 1 second apart
- `cpu.vcpus_provisioned`
- `memory.used_mb`, `memory.available_mb`, `memory.usage_percent`
- `storage.allocation_gb`, `storage.capacity_gb`, `storage.usage_percent` — host-side view via `virsh domblkinfo`
- `storage.guest_total/used/available` — guest-side via `virsh domfsinfo` (requires `qemu-guest-agent` installed in VM; returns N/A if not)
- `network_interfaces` — list of interface names found via `virsh domiflist`

`monitor` fails if the VM doesn't exist or isn't in `running` state.

**`monitor` is not called automatically.** Nothing in the codebase polls `monitor` on a schedule. It must be submitted as an explicit provisioning job.

---

#### `check` action — host capacity

`check` (no `vm_target` required) reports total vs. allocated vs. available resources on a KVM host:
- vCPUs: physical cores via `nproc` vs. sum of vCPUs across all running VMs
- RAM: from `/proc/meminfo` vs. sum of `Max memory` across running VMs
- GPUs: counts NVIDIA/AMD GPU PCIe functions (`.0` only) via `lspci`, checks which are attached to VMs via `virsh dumpxml`

Useful for pre-flight capacity checking before a `create` job.

---

#### Provisioning API Endpoints (`main.py` / `api/routes.py`, port `8081`)

- `GET  /health` — checks API, database connectivity, and job processing loop liveness; returns `{"status": "ok"|"degraded", "checks": {...}}`
- `POST /jobs` — submit a provisioning job; returns `{"job_id": "...", "status": "queued"}`; accepts `X-Agent-ID` header (required when auth is enabled)
- `GET  /jobs` — list jobs with pagination (`offset`/`limit`), status filter, sort; authenticated agents see only their own jobs (seller or buyer role)
- `GET  /jobs/{job_id}` — full job status including params, result, error, and retry metadata
- `GET  /jobs/{job_id}/credentials` — returns credentials for the requesting agent; **requires `X-Agent-ID` header always** (regardless of `ENABLE_AUTH`); sellers get root+tenant, buyers get tenant only
- `GET  /jobs/{job_id}/logs` — raw Ansible stdout+stderr for the job; credentials are redacted in storage but paths/keys may appear; logs update in near-real-time while job is running
- `POST /jobs/{job_id}/cancel` — cancels a queued job, or sends `SIGTERM` to the Ansible PID if the job is running

#### Ansible Diagnostic Endpoints (unified API, port `8081`)

Previously a separate worker admin API on port 8082; now folded into the main API under `/api/v1/ansible/`.

- `GET /health` — checks API, database, and job processing loop liveness
- `GET /inventory` — parses the Ansible INI inventory file and returns all hosts with their `ansible_host` values and inline vars; supports `?search=<substring>` for hostname filtering
- `GET /inventory/{host}/connectivity` — runs `ansible -m ping` against a single named host, exercising the complete auth path (inventory parse → SSH key → Ansible execute); returns `{"reachable": true/false, "detail": "..."}` — returns HTTP 200 either way, only 404 if host not in inventory

#### Test mock controller (`/test/*`)

Only mounted when `mock` is in `ACTIVE_PROFILES`. Never present in production or staging.

Provides an HTTP API for configuring `ProgrammableMockAnsibleService` rules and waiting for job lifecycle events without polling loops.

In provisioning-service integration tests, `/test/*` callers use a fresh
`ProgrammableMockAnsibleService` wired through `container.resolved_ansible_service`
for the lifetime of the test client. The regular provisioning API integration
fixtures may still use a `MagicMock` at the Ansible subprocess boundary when a
test needs call assertions such as `start_playbook.assert_called_once()`.
`POST /test/evaluate-job` is a typed JSON-body route backed by
`EvaluateJobRequest`; request/response model imports must stay concrete at
module scope so FastAPI binds the payload as a body rather than a query
parameter.

**Endpoints:**

```
POST   /test/mock-rules                    Add a when→then mock rule
GET    /test/mock-rules                    List active rules
DELETE /test/mock-rules/{rule_id}          Remove a rule
POST   /test/mock-rules/{rule_id}/resume   Release a paused job gate
GET    /test/jobs/summary                  Status counts (non-blocking)
GET    /test/jobs/drain                    Long-poll until all jobs terminal
GET    /test/jobs/{job_id}/wait            Long-poll until one job is terminal
```

**Mock rule schema:**
```json
{
  "rule_id": "my-ww1-create",
  "match": {"vm_action": "create", "vm_host": "ww1"},
  "pause_before_result": true,
  "result_stdout": "...",
  "fail_with": null
}
```

Rules are evaluated in insertion order. The first rule whose `match` dict is a subset of the incoming `AnsibleJobParams` fields wins. `match: {}` is a catch-all. If no rule matches, `_FAKE_STDOUT` success path runs.

`pause_before_result: true` makes `wait_for_playbook` block on an `asyncio.Event` until `POST /test/mock-rules/{rule_id}/resume` is called. This allows tests to assert on mid-flight job state without any `asyncio.sleep` polling.

**`ProgrammableMockAnsibleService`** is activated instead of `MockAnsibleService` when `mock` is in `ACTIVE_PROFILES`. It extends `MockAnsibleService` with the rule dict and per-rule `asyncio.Event` gates. Both are in `services/mock_ansible_service.py`.

**Rule matching seam:** `AnsibleJobService._process_job` injects the `AnsibleJobParams` onto the `AnsibleRun` handle as `run._params` immediately after `start_playbook`. `ProgrammableMockAnsibleService.wait_for_playbook` reads `getattr(run, "_params", None)` to match rules. The real `AnsibleRun` dataclass ignores unknown attributes; this is a zero-cost test seam.

**Job-done event seam:** After every job reaches a terminal state, `_process_job` calls `getattr(self._ansible, "notify_job_done", None)` — a no-op on the real `AnsibleService`. `ProgrammableMockAnsibleService.notify_job_done` fires a per-job `asyncio.Event` stored in `_job_done_events`, which `GET /test/jobs/{job_id}/wait` awaits. This replaces any `asyncio.sleep` polling in test code.

**`global.adminApiKey` for provisioning test controller:** The e2e test pod mounts the storefront agent secret profile which carries `{component}.admin_api_key` — this is the same key the storefront's `AdminAuthMiddleware` enforces. The provisioning test controller (`/test/*`) does not enforce the admin key separately; it is only mounted in the `mock` profile and access is network-scoped within the cluster.

---

#### Operational Visibility — what you can see and where

| Question | Where to look |
|---|---|
| Is the provisioning service healthy? | `GET /health` (API) and `GET /health` (worker admin) |
| What jobs exist and their statuses? | `GET /jobs?status=<filter>` |
| Why did a job fail? | `GET /jobs/{id}` (error field) + `GET /jobs/{id}/logs` (raw Ansible output) |
| Is Ansible able to reach the KVM host? | `GET /inventory/{host}/connectivity` (worker admin) |
| What VMs exist on the host? | Submit a `list` job, check `result` when succeeded |
| What resources are available on the host? | Submit a `check` job |
| What are the resource usage stats for a running VM? | Submit a `monitor` job |
| Did the lease-end cleanup actually run? | SSH to KVM host: `cat /var/log/vm-lease-end/<vm_name>/lease_end_*.log` — no API visibility |
| What `at` jobs are pending on the host? | SSH to KVM host: `atq` — no API visibility |
| Is a VM stuck in `running` state in Ansible mid-job? | `GET /api/v1/jobs/{id}` — `process_id` field gives the Ansible PID (same container as the API) |

---

**Key source layout:**
```
provisioning-service/src/
├── controllers/                # Handles Http Routing concerns.
├── services/                   # For internal business logic
├── models/                     # Request and Response objects for controllers
├── middleware/
│   ├── auth.py                 # AgentAuthMiddleware (ERC-8004 X-Agent-ID enforcement)
│   └── rate_limit.py           # AgentRateLimitMiddleware (sliding window per agent)
├── db/
│   ├── models.py               # AnsibleJob + Credential SQLAlchemy models (table: ansible_jobs)
│   └── database.py
├── config/
│   ├── config.yml              # Environment schema (mostly empty — structure documentation)
│   ├── config-docker.yml       # IaC paths + ansible_cfg for standalone container runs
│   └── config-local.yml.example  # Developer override template (copy to config-local.yml)
├── container.py                # dependency-injector DeclarativeContainer
├── config.py                   # Profile-aware dynaconf loader
├── settings.toml               # Committed base defaults
└── main.py                     # FastAPI app + lifespan (starts job processing loop)
```

---

#### Configuration System

The provisioning service uses a profile-based configuration system. Resolution order (highest priority first):

1. `PROVISIONING_*` environment variables — last-resort escape hatch only
2. `config/config-<profile>.yml` files (one per entry in `ACTIVE_PROFILES`)
3. `config/config.yml` (environment schema — mostly empty, documents structure)
4. `settings.toml` (committed base defaults)

**Available profiles:**
- `local` — developer overrides; copy `config/config-local.yml.example` to `config/config-local.yml` (gitignored) and set `ACTIVE_PROFILES=local` in `.env`
- `docker` — baked into the image via `ENV ACTIVE_PROFILES="docker"`; supplies IaC paths and `ansible_cfg` for standalone container runs
- `production` — used in Kubernetes; rendered from Helm `values.yaml` into a ConfigMap mounted at `CONFIG_DIRECTORY`
- `provisioning-secrets` — used in Kubernetes alongside `production`; rendered from a Helm Secret into `config-provisioning-secrets.yml` mounted at `CONFIG_DIRECTORY`. Carries sensitive keys that must not appear in a ConfigMap plaintext (`ssh_decryption_key`, `inventory_ini`).
- `mock` — initializes `MockAnsibleService` with deterministic fake results and no subprocess calls. Intended for docker-compose and e2e tests where no real KVM hardware is available.

**Helm configuration policy — all config travels through the profile system:**

Pods set only `ACTIVE_PROFILES` and `CONFIG_DIRECTORY` as environment variables. All application settings travel through mounted ConfigMap or Secret files, never as individual `env` entries in the pod spec. This rule applies equally to the application Deployment and to helm test pods.

The reasoning: environment variables are the highest-priority override layer in dynaconf. Injecting individual settings as env vars silently overrides anything an operator configures in a profile file, defeating the purpose of the profile system. The only acceptable env vars on a pod are the profile resolver variables (`ACTIVE_PROFILES`, `CONFIG_DIRECTORY`) and the subprocess-required `ANSIBLE_CONFIG`.

**Pattern for secrets in Kubernetes:**

Secrets that cannot be placed in a ConfigMap (key material, sensitive credentials) are stored as a Kubernetes Secret whose data contains a `config-<profile>.yml` key. The Secret is mounted as a volume at `CONFIG_DIRECTORY`; the profile name is added to `ACTIVE_PROFILES`. This is identical to the ConfigMap approach — the dynaconf loader sees no difference between a file mounted from a ConfigMap and one mounted from a Secret.

Example — the provisioning-secrets profile:
```
Secret data key:  config-provisioning-secrets.yml
Mount path:       /app/config/config-provisioning-secrets.yml
ACTIVE_PROFILES:  production,provisioning-secrets
```

**`mockMode` (Helm provisioning subchart):** Setting `provisioning.mockMode: true` in the umbrella `values.yaml` appends `mock` to `ACTIVE_PROFILES` in the provisioning Deployment, which causes `container.py`'s `_make_ansible_service()` factory to select `ProgrammableMockAnsibleService` instead of the real `AnsibleService`. The `config-mock.yml` profile (bundled in the image) sets `ansible_cfg` and `playbook_path` to safe no-op values. `mockMode` is `true` in the default umbrella values (dev/CI cluster) and must be set to `false` for production deployments that run real Ansible against KVM hosts.

The same pattern applies to helm test pods. The shared `test-config` ConfigMap provides non-secret values (service URLs, feature flags) merged by the `helm` profile. Test pods that need secret material mount an additional Secret volume as a second profile.

**Why `ENV` vars are not used for application config:**

Environment variables are the highest-priority override layer. Baking application config into `ENV` instructions in a Dockerfile means any operator trying to change a value via a profile file is silently overridden — the opposite of the intended behaviour. The Dockerfile therefore only sets `ACTIVE_PROFILES` and `CONFIG_DIRECTORY`.

The one exception is `ANSIBLE_CONFIG`: this is consumed by the `ansible-playbook` subprocess via `os.environ` rather than by Python code, so it cannot travel through dynaconf. It is read from `settings.ansible_cfg` at lifespan startup and written to `os.environ` before the first playbook run.

**Helm ConfigMap approach:**

The Helm chart renders the entire `config:` block from `values.yaml` directly into `config-production.yml` using `{{ .Values.config | toYaml }}`. Adding a new non-secret config key requires only a `values.yaml` change — no Deployment template changes needed. Secret keys go into the `sshDecryptionKey` Secret block in `values.yaml`, which renders into `config-provisioning-secrets.yml`.

---

#### Ansible Inventory and SSH Key — How They Are Provided at Runtime

There are three distinct inputs the provisioning service needs from outside the container. Before documenting them, a terminology clarification that the codebase conflates:

**Ansible inventory vs. KVM hosts — these are different things:**

- **Ansible inventory** — an INI file telling Ansible *how to connect* to machines: aliases, IPs, SSH users, key paths, and group memberships. In the implemented design this is a *rendered artifact* produced from the `hosts` DB table immediately before each playbook run, not a file maintained on disk.

- **KVM/libvirt host** — a bare-metal machine running the KVM hypervisor and `libvirt` daemon. Libvirt's own state lives on each machine in `/etc/libvirt/` and is managed via `virsh`. The provisioning service never talks to libvirt directly — Ansible SSHes into the KVM machine and runs `virsh` commands there.

---

**1. SSH private key** (`~/.ssh/id_ed25519`)

The provisioning service authenticates Ansible SSH connections using keys stored per host in the `hosts` table. Two key storage modes are supported:

- **`path`** — `ssh_key_value` is a filesystem path (e.g. `/home/appuser/.ssh/id_ed25519`). The default Helm chart mounts the operator's key at this path via a Kubernetes Secret volume. Hosts sharing the same physical key all reference the same path.
- **`embedded`** — `ssh_key_value` stores Fernet-encrypted PEM key material in the database. Requires `ssh_decryption_key` delivered via the `provisioning-secrets` config profile. At job execution time `AnsibleService.write_inventory()` decrypts the key and writes it to a temp file alongside the rendered inventory; both are cleaned up in the `finally` block.

The Dockerfile uses a direct `CMD ["uvicorn", ...]` entrypoint.

---

**2. Golden image credentials**

Golden image credentials (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`, `golden_gcs_bucket`, `golden_gcs_project`) are first-class keys in `settings.toml` and the config profile system.

- **Locally** — set in `config/config-local.yml`
- **In Kubernetes** — set in the `config:` block of Helm `values.yaml`; rendered into `config-production.yml` by the ConfigMap

---

**3. Host registry**

The `hosts` DB table is the single source of truth for KVM host inventory. The Ansible INI file is an *input format only* — it is never read at runtime except as input to `POST /hosts/import` or the `inventory_ini` startup seeder.

**`hosts` table columns:** `name` (PK, Ansible alias), `kvm_host` (IP), `ssh_user`, `ssh_key_type` (`"path"` | `"embedded"`), `ssh_key_value`, `gpu_count`, `enabled`, `created_at`, `updated_at`.

**Column naming:** `kvm_host` and `ssh_user` — decoupled from Ansible's own variable names (`ansible_host`, `ansible_user`). Ansible variables are only introduced when the INI is rendered for a playbook run.

**REST API:**
```
GET    /api/v1/hosts/               List enabled hosts (DB query)
POST   /api/v1/hosts/               Register a host (JSON body)
POST   /api/v1/hosts/import         Bulk-import from Ansible INI block (upsert, append-only)
GET    /api/v1/hosts/{host}         Host details
PUT    /api/v1/hosts/{host}         Update connection details
POST   /api/v1/hosts/{host}/enable  Re-enable a disabled host
POST   /api/v1/hosts/{host}/disable Soft-delete (sets enabled=False)
GET    /api/v1/hosts/{host}/capacity       Submit capacity check job
GET    /api/v1/hosts/{host}/connectivity   Run ansible -m ping
```

**Upsert / append-only semantics:** `POST /hosts/import` upserts rows — hosts present in the INI are inserted or updated; hosts absent from the INI are never disabled or removed. This preserves job history FK integrity (jobs reference `vm_host` by name string).

**Disable vs. delete:** There is no hard delete endpoint. `POST /hosts/{host}/disable` sets `enabled=False`. Disabled hosts are excluded from `GET /hosts/` (default) and from inventory rendering.

**Inventory rendering for Ansible:** `AnsibleService.write_inventory(hosts)` renders a temp INI file from DB rows immediately before each playbook run, deleted in the `finally` block — the same contract as `build_vars_file`. The rendered group is always `[kvm_hosts]`.

**Inventory seeding at startup:** `main.py` seeds the hosts table once during lifespan startup using the following logic:

- **Skip if the table is non-empty.** If any hosts are already registered (from a previous startup or via the API), seeding is skipped entirely. Operator changes made through the API are never overwritten on pod restart. To force a re-import, use `POST /api/v1/hosts/import` which always upserts regardless of table state.
- **Source 1 — `inventory_ini` setting** (Helm/Kubernetes): the `provisioning-secrets` config profile carries this value. Used when deploying via Helm.
- **Source 2 — `inventory_path` on disk** (Docker): the `docker` config profile sets `inventory_path` to the IAC hosts file baked into the image. Used when running the container standalone without a Helm-injected INI.

**`[kvm_hosts]` group only:** `_parse_ini` imports only entries under the `[kvm_hosts]` INI group. Other groups in the IAC inventory (e.g. `[frp_servers]`, `[provisioning_servers]`) describe infrastructure that manages the provisioning service itself and are not relevant to VM provisioning.

**`gpus=` variable mapping:** The IAC inventory uses `gpus=N` to declare GPU count. `_parse_ini` maps this to the `gpu_count` column. `ansible_ssh_private_key_file=` is stored verbatim as the key path. All other Ansible variables are ignored.

**`SystemService.ansible_readiness`** reads host count and SSH key diagnostics from the `hosts` DB table. `SshKeyInfo` has a `key_type` field: `path`-type hosts have their key file stat'd and SHA-256'd; `embedded`-type hosts report `exists=True` with no SHA-256 (key is encrypted at rest).

---

### `compute-provisioning-iac` (submodule)

**Role:** Infrastructure-as-code for the physical layer. A git submodule.

Contains Ansible roles and Terraform modules used by both the provisioning worker (at runtime) and operators (to set up seller hardware).

**Ansible roles:**
- `vm-setup` — prepares a KVM host: GPU passthrough, KVM networking, golden image build (Packer + Ubuntu Noble), FRP client config, security hardening
- `vm-management` — day-2 VM operations: create/destroy/start/stop, GPU assignment, lease management
- `frp-setup` — sets up FRP server (fast reverse proxy) for buyer network access to VMs
- `docker-app` — deploys Docker-based apps to a host

**Terraform modules:** GCP-focused (Cloud Run, artifact registry, service accounts, Redis, ZeroTier controller). Used for the production/staging/sandbox cloud deployment of the non-hardware services.

**TODO:** Document the GPU passthrough setup and any constraints on host hardware.

---

#### FRP Topology — How Buyers Reach Their VMs

FRP (Fast Reverse Proxy) is the network access mechanism that allows a buyer to SSH into a provisioned VM without the seller's KVM host being publicly addressable. It is optional — the playbook falls back to direct port forwarding when `frp_server_addr` is not provided — but it is the intended production path.

**The three machines involved:**

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  FRP Server  (separate public VPS, not the KVM host) │
│  Runs: frps (FRP server daemon)                      │
│  Ports: 7000 (control), 7002–8000 (proxy range)     │
│  Domain: frp-admin.<domain>  (Nginx + TLS)           │
│  Dashboard: port 7001, localhost-only                │
└──────────────┬──────────────────────────────────────┘
               │  persistent TLS tunnel (port 7000)
               ▼
┌─────────────────────────────────────────────────────┐
│  KVM Host  (seller's bare-metal machine)             │
│  Runs: frpc (FRP client daemon), libvirt, VMs        │
│  frpc config: /etc/frp/frpc.toml                    │
│  One [[proxies]] block added per VM at create time   │
└──────────────┬──────────────────────────────────────┘
               │  internal KVM bridge network
               ▼
┌─────────────────────────────────────────────────────┐
│  Guest VM  (tenant's compute, private IP)            │
│  SSH port 22 — not directly reachable               │
└─────────────────────────────────────────────────────┘
```

**How the FRP server is deployed:**

The `frp-setup` Ansible role, invoked via `playbooks/frp/frp-server-setup.yaml` targeting the `[frp_servers]` inventory group, configures a standalone public VPS as the FRP server. This is a one-time operator setup step, separate from the provisioning service's job flow. The role:

- Installs `frps` as a systemd service
- Configures token-based auth (`auth.token`) and TLS
- Opens the port range `7002–8000` for proxy connections via UFW
- Installs Nginx to reverse-proxy the FRP dashboard (`port 7001`, localhost-only) to `https://frp-admin.<domain>` with a Let's Encrypt certificate
- Saves the generated `auth_token` and `dashboard_password` to a local credentials JSON file for use when provisioning VMs

**How the KVM host gets its FRP client:**

The `vm-setup` Ansible role (host preparation, not per-VM) installs `frpc` as a systemd service on the KVM host with a base `frpc.toml` pointing at the FRP server. At this stage the config has no proxy entries — it just establishes the persistent control connection to the FRP server.

**What happens at VM creation:**

When a `create` job runs with `frp_server_addr` set, the playbook:

1. Queries the FRP dashboard API (`https://frp-admin.<domain>/api/proxy/tcp`) to find existing proxy names and allocate a unique 6-character subdomain suffix for the new VM.
2. Queries the same API to find an unused port in the `7002–8000` range for the VM's remote port.
3. Appends a new `[[proxies]]` block to `/etc/frp/frpc.toml` on the KVM host (using Ansible `blockinfile` with a marker comment `# ANSIBLE MANAGED BLOCK FOR VM <vm_name>`):
   ```toml
   [[proxies]]
   name = "vm-<subdomain>"
   type = "tcp"
   localIP = "<vm_internal_ip>"
   localPort = 22
   remotePort = <allocated_port>
   subdomain = "<subdomain>"
   transport.useEncryption = true
   ```
4. Restarts `frpc` to pick up the new entry.

The FRP server then accepts connections on `<remotePort>` and tunnels them through the persistent KVM host connection to the VM's internal SSH port 22.

**What the buyer receives:**

The `vm_creation_data` JSON returned by the playbook (and stored in `job.result`) contains two SSH access modes depending on whether FRP was used:

| Field | FRP mode | Direct port-forward mode |
|---|---|---|
| `frp.enabled` | `true` | `false` |
| `frp.remote_port` | allocated port (e.g. `7045`) | N/A |
| `frp.subdomain` | e.g. `a3b9f2` | N/A |
| `frp.domain` | e.g. `arkhainet.whitewidget.tech` | N/A |
| `authentication.tenant.ssh_commands.external` | `ssh -i <key> -p 7045 vmname@a3b9f2.arkhainet.whitewidget.tech` | `ssh -i <key> -p <port> vmname@<kvm_host_ip>` |
| `authentication.tenant.ssh_commands.internal` | `ssh -i <key> vmname@<vm_internal_ip>` | same |

The provisioning client (`service/clients/provisioning.py`) normalizes the result and substitutes `frp.domain` as `vm_host_ip` when FRP is active, so the rest of the agent code sees a consistent connection-details shape regardless of mode.

**VM teardown and FRP cleanup:**

The cleanup script written to `/usr/local/bin/cleanup_vm_<name>.sh` on the KVM host at create time includes removal of the FRP proxy block (sed delete on the `ANSIBLE MANAGED BLOCK FOR VM <name>` markers in `frpc.toml`) and a `frpc` restart. This runs as part of the `at`-scheduled lease expiry. The FRP server retains no persistent state — the proxy entry disappears as soon as `frpc` reconnects without it.

**Fallback mode (no FRP):**

When `frp_server_addr` is not provided in the create request, the playbook instead:
- Picks a random unused port in the range `10000–65000` on the KVM host
- Adds an iptables `PREROUTING` DNAT rule forwarding `<kvm_host_ip>:<port>` → `<vm_internal_ip>:22`
- Opens the port via UFW/firewalld
- Returns `<kvm_host_ip>` and `<port>` as the external SSH coordinates

This mode requires the KVM host to have a publicly reachable IP, which is not always the case and exposes the host's public IP to buyers.

**Operational notes:**

- The FRP server is infrastructure the seller operator must provision and maintain separately — it is not deployed or managed by the provisioning service's job system.
- The `frp_server_addr`, `frp_domain`, and `frp_dashboard_password` are passed into every `create` job (either per-request or from the provisioning service's config defaults `FRP_SERVER_ADDR`, `FRP_DOMAIN`, `FRP_DASHBOARD_PASSWORD`). They are seller-global values in the current design.
- The FRP dashboard at `https://frp-admin.<domain>` shows all active proxy connections — this is currently the only way to get a live view of which VMs have active tunnels, since the provisioning service has no VM state table. This is another facet of the visibility gap described in TODO item 4.

**Tech debt:**
The following items represent known architectural deficiencies in `provisioning-service` that are planned for remediation. They are documented here to provide context when working on this service.

> **TODO(client-compat): The provisioning-service package currently exposes its modules at the flat `client.*` level (e.g. `from client.provisioning_client import ...`) because setuptools maps `src/` directly as the package root. To expose a clean `provisioning_service.*` namespace, all internal imports within the package would need to be converted from bare names (e.g. `from models.jobs_model import ...`) to relative imports (e.g. `from .models.jobs_model import ...`). Until that refactor is done, `service/clients/provisioning.py` imports from `client.provisioning_client` rather than `provisioning_service.client.provisioning_client`.

> **TODO(smoke-tests):** The provisioning smoke tests in `integration-tests/tests/smoke/test_provisioning_smoke.py` use raw `httpx` calls rather than `SyncProvisioningClient`. They should be updated to use the canonical client following the pattern established the service integration tests.

#### `escrow_uid` on jobs — deal linkage and recovery

The `ansible_jobs` table now carries an `escrow_uid` column (nullable, indexed). The storefront passes this when submitting a provisioning job for a settled deal. It enables the storefront to recover the provisioning job_id after a crash by querying `GET /api/v1/jobs?escrow_uid=<uid>` rather than losing the mapping.

`escrow_uid` is surfaced in:
- `AnsibleJobParams.escrow_uid` (internal DTO)
- `JobStatusResponse.escrow_uid` (HTTP response)
- `GET /api/v1/jobs?escrow_uid=<uid>` filter on the list endpoint
- `ProvisioningClient.list_jobs(escrow_uid=...)` on both async and sync clients

The `provisioning_job_id` is surfaced in `GET /settle/{escrow_uid}/status` on the storefront so the buyer can traverse: storefront settle status → `provisioning_job_id` → provisioning `GET /jobs/{id}`.

---

### CLIs

There are four console scripts, each a separate distributable. They
split by concern (runtime vs. tooling vs. operator infra) rather than
by buyer-vs-seller role. Built with Typer; config is read from a
single TOML file at `$XDG_CONFIG_HOME/arkhai/config.toml` (override
with `--config <path>`).

| CLI | Package | Role | Top-level groups |
|---|---|---|---|
| `market` | `buyer/` | Buyer runtime (pure HTTP client) | `buy`, `negotiate`, `order`, `escrow reclaim`, `network join/get-peers`, `config`, `logs` |
| `market-storefront` | `storefront/` | Seller runtime | `register`, `serve`, `provide`, `escrow claim/refund`, `portfolio import-csv`, `network join/get-peers`, `config`, `logs` |
| `market-policy` | `policy/` | Policy authoring tool | `train`, `eval`, `export` |
| `market-infra` | `infra/` | Market-operator infra (one process per market) | `chain up/deploy-contracts`, `registry start`, `network install/create/add` |

The two runtimes (`market`, `market-storefront`) share `network join`
and `get-peers` because each operator manages their own ZeroTier
membership. The owner-side actions (`install` / `create` / `add`)
live in `market-infra` because they are run once per market by the
trust authority, not per-agent.

Deployment shells just compose CLI verbs:

- **Docker (storefront image):** `entrypoint.sh` brings up the
  ZeroTier daemon, then runs `market-storefront register` and
  `exec market-storefront serve`.
- **Helm:** the init container runs
  `./entrypoint.sh market-storefront register --chain-id N` and the
  main container runs `./entrypoint.sh market-storefront serve` —
  same image, two CLI verbs.

`market-storefront serve` only forwards `host` and `port` into
`server.run_serve()`. The old inline publish-loop flags were removed
with the storefront publish loop; the CLI/server argument contract is
covered by a storefront unit test because a mismatch crashes the
container before any integration or e2e test can run.

See `docs/cli-redesign-plan.md` for the rationale and migration
table behind the current 4-CLI surface.

---

## Deployment Topology

### Local Dev (compose)

```
compose/external.yml — Anvil node + one-shot contract deployer (the "external"
                       chain layer; in prod this is a live RPC, not run here)
compose/market.yml   — registry-service
compose/seller.yml   — storefront server + provisioning service (unified)
```

There is no `compose/buyer.yml` anymore — the buyer is the `market`
CLI invoked from the host or another container, not a long-running
service. The seller container reads its config from a TOML file
mounted at `/etc/arkhai/config.toml` (set via `XDG_CONFIG_HOME=/etc`);
the `.env` flow used by the previous symmetric topology has been
retired.

### Production / Staging — Helm (`helm/`)

The intended production deployment path is a single Helm umbrella chart named `arkhai-node-operator` located at `helm/`. It manages all runtime services as conditional subcharts and is the target for `helm upgrade --install`.

**Chart structure:**
```
helm/
├── Chart.yaml              # Umbrella chart; declares subchart dependencies
├── values.yaml             # Single source of truth for all configuration
├── _helpers.tpl
├── Makefile                # init, template, deploy, test, forward/unforward
├── templates/
│   └── tests/test-config.yaml  # Shared ConfigMap for helm test pods
└── charts/
    ├── test-env/           # Anvil node (condition: test-env.enabled)
    ├── registry/           # registry-service (condition: registry.enabled)
    ├── storefront/         # storefront-service (condition: agents>0)
    ├── provisioning/       # Unified provisioning service (condition: provisioning.enabled)
    └── validate-contracts/ # Helm test: chain connectivity check
```

**Kubernetes objects deployed:**

| Subchart | Deployments | Services |
|---|---|---|
| `test-env` | 1 (Anvil) | 1 NodePort :8545 |
| `registry` | 1 | 1 NodePort :8080 |
| `storefront` | 1 | 1 NodePort :8001 |
| `provisioning` | 1 (unified API + job loop) | 1 ClusterIP (:8081) |

**Startup ordering** is enforced by init containers:
- The seller agent waits on RPC (`eth_blockNumber` poll) and registry (`/health` poll) before starting
- The provisioning container has no init containers or startup dependencies
- The test-env container has no init containers or startup dependencies

**Secrets:**
- Seller agent private key + wallet address → `Secret` per agent, sourced from `values.yaml` `secret.privKey` / `secret.walletAddress`, or an externally pre-created secret
- SSH private key for Ansible → `Secret` mounted as a volume at `/home/appuser/.ssh/id_ed25519` (mode 0400); set via `--set-file provisioning.sshKey.sshPrivateKey=$(SSH_KEY_FILE)` at deploy time or by providing a pre-existing Secret

**Global values** propagated to all subcharts:
- `global.imageRepository` — optional registry prefix for all images
- `global.rpc.{host,port,chainId}` — single source of truth for the Anvil/chain coordinates
- `global.registry.{host,port,identity_address,...}` — registry service coordinates and contract addresses
- `global.provisioning.{host,port}` — provisioning service coordinates

**Helm Makefile targets:**
```
make init              # helm dependency update
make template          # render full chart to stdout (dry-run)
make template-module MODULE=<subchart>   # render a single subchart
make deploy            # helm upgrade --install (SSH_KEY_FILE=~/.ssh/id_ed25519)
make test              # helm test --logs (runs all test pods)
make test-module MODULE=<subchart>       # run tests for one subchart
make forward           # kubectl port-forward all services to localhost
make unforward         # kill all port-forwards
```

**Port-forward map** (local dev against a deployed cluster):
```
localhost:8545  → test-env (Anvil RPC)
localhost:8080  → registry
localhost:8001  → seller storefront
localhost:8081  → provisioning API (also handles ansible inventory + connectivity endpoints)
```

**Helm test suite:**
- `validate-contracts` — verifies RPC connectivity and contract deployment by running `pytest -m contracts` against the integration test image
- `registry` — environment smoke test
- `storefront` — environment smoke test
- `provisioning` — environment smoke test (no provisioning test pod currently defined in source)
- All tests share a ConfigMap (`{release}-test-config`) injected as `config-helm.yml`, containing resolved RPC URLs, contract addresses, and agent URLs

**Persistence:**
- Storefront agents, registry, and provisioning each back their SQLite onto a per-service ReadWriteOnce PVC: `/var/lib/arkhai` (storefront, per-agent), `/var/lib/arkhai-registry` (registry), `/app/data` (provisioning). Pod restarts no longer wipe negotiation history, registry index, or lease state. Each chart pins `strategy: Recreate` (RWO can't have two pods attached), sets `securityContext.fsGroup: 1000` so `appuser` can write the freshly-mounted volume, and annotates the PVC with `helm.sh/resource-policy: keep` so `helm uninstall` doesn't reap the disk. A `persistence.enabled` toggle in each subchart's `values.yaml` falls back to `emptyDir` for kind/CI/local-iteration without a StorageClass.
- Agent ID persistence across pod restarts is handled by `seller.onchain_agent_id` in config (a Helm value). On first deploy with `agentId: ""` and `autoRegister: true`, the service registers and logs the assigned ID. Operators pin that ID in `values.yaml` and flip `autoRegister: false` to prevent accidental re-registration. The compose flow (which used `ONCHAIN_AGENT_ID=` env var clearing to force re-registration on fresh Anvil) is unchanged.

**Notable gaps / fitness questions to investigate:**
- `test-env.enabled: true` in the default values — in production this needs to be `false` and `global.rpc.*` overridden to point at a live chain
- `replicaCount` exists for the storefront and provisioning API but running multiple replicas of either without shared persistent storage would be incorrect (RWO PVC permits one attached pod)

**GKE Autopilot constraints:**

Two chart features are incompatible with GKE Autopilot's security policy and
must be disabled for all GKE-hosted deployments:

1. **ZeroTier networking** — the storefront requires `NET_ADMIN`/`SYS_MODULE`
   Linux capabilities and a writable `/dev/net/tun` hostPath volume for the
   ZeroTier daemon. Autopilot forbids both cluster-wide. The storefront chart
   exposes `zerotierEnabled` (default `true`); set `storefront.zerotierEnabled:
   false` in the GKE values overlay. The application runtime is unaffected when
   `seller.zerotier_network` is absent from `config.toml` — `entrypoint.sh` is
   fail-soft on daemon startup and all ZeroTier code paths are conditional.
   In GKE deployments the storefront is reachable via the API gateway instead.

2. **e2e-tests secret conflict** — the `helm/charts/e2e-tests/templates/secret.yaml`
   template renders the credentials Secret unconditionally. In GKE environments,
   External Secrets Operator (ESO) manages this Secret, causing a Helm ownership
   conflict on install. **Fix:** add a `{{- if .Values.createSecret | default true }}`
   guard to `secret.yaml` and add `createSecret: true` to
   `helm/charts/e2e-tests/values.yaml`. Then set `e2e-tests.createSecret: false`
   in the GKE values overlay (the ops repo already does this). Until the patch
   is applied, set `e2e-tests.enabled: false` in the GKE overlay.

**Resource inventory seeding** follows the same pattern as provisioning host inventory:

*Three delivery mechanisms, in priority order:*
1. **`seller.resources_csv_inline`** (Helm) — raw CSV content injected via the per-agent Secret. Set via `make deploy RESOURCES_CSV_FILE=/path/to/resources.csv`, which passes `--set-file storefront.agents[0].secret.resourcesCsvInline=<path>` to `helm upgrade`. The CSV is stored in the Kubernetes Secret alongside the wallet key and rendered into the dynaconf profile that the storefront reads at startup. This is the production path — no CSV file ever touches the container image.
2. **`seller.resources_csv_path`** (compose / local dev) — path to a CSV file on disk, bind-mounted into the container by `make deploy-seller-agent` via `RESOURCES_CSV_FILE` (defaults to `storefront/src/market_storefront/data/ww1-machine.csv`). Used by the docker-run compose flow.
3. **`POST /api/v1/admin/portfolio/resources/import`** — admin endpoint for runtime clobber. Accepts a CSV file upload and upserts regardless of current table state. Used for inventory updates without restarting the pod.

*Startup seeding is idempotent*: if the resources table already has rows (e.g. from a previous startup or a prior import call), seeding is skipped. Pod restarts do not overwrite operator changes. To force a full re-seed, use the import endpoint.

The full-deal e2e scenario uses the admin import path: it carries an inline CSV fixture and imports the exact compute row it needs through `SyncStorefrontClient.admin_import_resources()` during readiness. This keeps the test self-contained and prevents it from depending on `ww1-machine.csv` being mounted into the storefront container.

The CSV files in `storefront/src/market_storefront/data/*.csv` are excluded from the container image via `.dockerignore`. They exist in the source tree as reference/default inventory for local dev (used by the compose bind-mount path) but are not baked into the image.

**Helm test pods:**
- `validate-contracts` — verifies RPC connectivity and contract deployment (`-m contracts`)
- `registry` — environment smoke test (`-m registry`)
- `storefront` — environment smoke test (`-m storefront`)
- `provisioning` — environment smoke test (`-m provisioning_smoke`)

Smoke test pods live in their respective subcharts and are designed to run in production environments (they test only stateless endpoint reachability and auth enforcement, not deal flow).

**`e2e-tests` subchart** (`helm/charts/e2e-tests/`) — optional, `enabled: false` by default. Contains the full buyer-seller deal lifecycle test and the buyer/seller credential Secret it needs. Never enabled in production. Enable with `--set e2e-tests.enabled=true` for dev/CI runs.

The subchart is self-contained: it owns all its own credentials and mounts nothing from the storefront subchart's Secrets (Option C). Config is assembled from two dynaconf profiles:
- `"helm"` — `config-helm.yml` from the shared `{release}-test-config` ConfigMap (non-secret topology: service URLs, chain ID, registry addresses, seller API URL, buyer `chain_rpc_url` composed from `global.rpc.*`)
- `"e2e-secret"` — `config-e2e-secret.yml` from the subchart's own Secret (seller private key, wallet address, admin API key; buyer private key, wallet address)

`ACTIVE_PROFILES: "helm,e2e-secret"`. The admin API key prefers `e2e-tests.seller.adminApiKey` when set, falls back to `global.adminApiKey` so it only needs to be set in one place for a standard deployment.

---

## Build & Init Flow

```
make build
  ├── build-buyer                # PyInstaller → buyer/dist/market
  ├── build-market-contract-deployer
  ├── build-test-env
  │     └── build-anvil-state   # Runs deployer against fresh Anvil, saves state.json
  └── build-runtime-images (parallel)
        ├── build-registry       # arkhai:registry / arkhai:registry-<sha>
        ├── build-storefront     # arkhai:storefront / arkhai:storefront-<sha>
        └── build-provisioning   # arkhai:provisioning / arkhai:provisioning-<sha>
```

Wheel builds happen separately via `make dist` (called automatically by
`build-runtime-images`):

```
make dist
  ├── dist-storefront-client  → .dist/arkhai_storefront_client-*.whl
  ├── dist-registry           → .dist/arkhai_registry_client-*.whl
  ├── dist-provisioning       → .dist/provisioning_service-*.whl
  ├── dist-storefront         → .dist/market_storefront-*.whl      (Docker builds only)
  ├── dist-policy             → .dist/market_policy-*.whl          (Docker builds only)
  ├── dist-service            → .dist/market_service-*.whl         (Docker builds only)
  └── dist-infra              → .dist/market_infra-*.whl           (Docker builds only)
```

---

## Artifact Registry Publishing

Built runtime artifacts are published to GCP Artifact Registry in the `compute-market-internal-infra` 
repo. The registries and their IAM are managed there; this repo only pushes.

**Artifact inventory:**

| Artifact | AR format | Repo key | Tag at push |
|---|---|---|---|
| Docker images (registry, storefront, provisioning) | DOCKER | `docker` | git short SHA |
| Helm chart (`arkhai-node-operator`) | DOCKER (OCI) | `helm` | git short SHA |
| `arkhai-storefront-client` wheel | PYTHON | `python` | wheel version |
| `arkhai-registry-client` wheel | PYTHON | `python` | wheel version |
| `provisioning-service` wheel | PYTHON | `python` | wheel version |
| `market` CLI binary | GENERIC | `cli` | git short SHA |

The four internal-only wheels (`market-storefront`, `market-policy`,
`market-service`, `market-infra`) are consumed only via `--find-links` inside
Docker builds and are never pushed to AR.

**Push flow:**

```
make build
make push-runtime-artifacts [AR_PROJECT=compute-market-1-dev]
  ├── push-images   # docker tag + docker push × 3
  ├── push-helm     # helm push (OCI)
  ├── push-wheels   # gcloud existence check + uv publish for missing wheels
  └── push-cli      # gcloud artifacts generic upload
```

**Image naming convention:** All service images share the image name `arkhai`
in the docker repository, distinguished by tag. This matches `image.name: arkhai`
in each subchart's `values.yaml`. The full AR path is:

```
us-central1-docker.pkg.dev/<project>/<project>-docker/arkhai:<tag>
```

**Tag model:** The `push-images` target uses a `push_image` macro that pushes
two tags per service on every push:

- `arkhai:<service>-<sha>-` — immutable identity (e.g. `storefront-bb5db95`)
- `arkhai:<service>` — mutable bare tag (e.g. `storefront`); overwritten on each push

GKE cluster deployments pull the bare `<service>` tag by default (matches
`image.tag: <service>` in each subchart's `values.yaml`). The SHA tag provides
an audit trail and supports rollback. Per-service SHA disambiguation
(e.g. `storefront-bb5db95` vs `registry-bb5db95`) is necessary because all
services share the `arkhai` image name in the same docker repository.

Python wheels are addressed by package version and filename, so `push-wheels`
uses `gcloud artifacts versions describe` before each upload and skips versions
that already exist. A changed wheel must still get a version bump before
publishing; Artifact Registry will not replace an existing wheel with the same
package/version/filename. Semver tags (`<version>-rc.N` for preprod,
`<version>` for prod) are applied at promotion time by the
`compute-market-ops` CI/CD pipeline — never by this repo.

**Dev wheel overwrite path:** during dev-cluster iteration, use
`make clobber-wheels` to delete the current published versions of
`arkhai-storefront-client`, `arkhai-registry-client`, and
`provisioning-service`, then immediately re-upload the local `.dist/` wheels.
This is intentionally separate from `push-wheels` because it mutates the Python
repository by deleting package versions. Use it only for development
repositories; preprod/prod wheel changes should bump package versions instead.

**Wheel duplicate diagnostic:** if `make push-wheels` fails with a 400 while
uploading a wheel, first check whether that package version already exists:

```sh
gcloud artifacts versions list \
  --project=compute-market-1-dev \
  --location=us-central1 \
  --repository=compute-market-1-dev-python \
  --package=provisioning-service
```

Use the target `AR_PROJECT` and package name as needed.

**Targeting an environment:**

```sh
make push-runtime-artifacts                                   # dev (default)
make push-runtime-artifacts AR_PROJECT=compute-market-1-preprod
make push-runtime-artifacts AR_PROJECT=compute-market-1-prod
```

**One-time machine setup:** before the first push, configure the Docker
credential helper and ensure ADC is set up:

```sh
gcloud auth configure-docker us-central1-docker.pkg.dev   # covers docker + helm OCI
gcloud auth application-default login                      # covers wheels + CLI upload
```

See the `compute-market-internal-infra` README for full ADC setup instructions.

---

## Known Issues & Areas of Concern

> This section should be expanded as investigation proceeds.

- **Agent SQLite statefulness:** The agent carries significant local state in SQLite (policy configs, negotiation history, resource portfolio). Behavior around container restarts, state migration, and concurrent access is a known problem area. Details TBD.

- **`ONCHAIN_AGENT_ID` clearing:** Both compose files explicitly clear `ONCHAIN_AGENT_ID=` to force re-registration on every fresh Anvil restart. This indicates the agent does not cleanly detect stale on-chain registrations on its own.

- **Negotiation orphans:** The existence of `negotiation_watchdog.py` implies negotiations can get stuck. The trigger conditions and recovery behavior need documentation.

- **SQLite INTEGER overflow for token amounts with `decimals > 0`:** `negotiation_messages` stores `our_price`, `their_price`, and `proposed_price` as `INTEGER` columns (signed 64-bit, max `2**63 - 1 ≈ 9.2 × 10**18`). `accepted_escrows[i].price_per_hour` is stored in uint256-domain (already decimal-scaled at advertisement), and the negotiation pipeline carries those values into `our_price` / `their_price` unchanged. Any token with 18 decimals and a human-readable per-hour price above ~9.2 billion will overflow at the SQLite write. **Workaround in e2e tests:** use `decimals: 0` on the MOCK test token so the advertised `price_per_hour` is already in base units. **Fix:** change `our_price`, `their_price`, `proposed_price` in `negotiation_messages` from `INTEGER` to `TEXT` and parse at read time. The `accepted_escrows` JSON column already serializes `price_per_hour` as a string-of-digits to dodge this on the listing side; the price-tracking columns need the same treatment.

- **`@policy_callable` domain callables are dead code:** `domain/compute/agent/app/policy/store.py` callables for negotiation (`negotiation_guard_always_negotiate_on_price_diff`, `negotiation_action_price_interval_concession`, `negotiation_respond_to_make_offer`, etc.) all have `if True: return None` at the top because the `NegotiationEvent`, `AcceptOfferEvent`, and `MakeOfferEvent` classes they depended on were removed. The storefront's negotiation rounds are driven entirely by `NegotiationStrategy` in `market_policy.negotiation_strategy` (not the callable chain). These callables will need to be either rewired to the new event model or deleted as part of the negotiation refactor.

- **`perform_registration` logs "Invalid explicit agent ID" when `ownerOf()` returns a tuple:** On the local Anvil state, `identityRegistry.ownerOf(agent_id).call()` returns a 2-tuple instead of a plain address string (ABI mismatch). The `except Exception` block in `registration.py` catches this, sets `agent_id = None`, and falls through to blockchain event search which recovers correctly. The `[REGISTRATION] Invalid explicit agent ID N: (addr, addr)` log line is expected and non-fatal. **Fix:** handle tuple returns explicitly in `registration.py` by unpacking `owner = result[0] if isinstance(result, (list, tuple)) else result`.

- **Buyer's initial offer must meet the seller's floor price:** `_extract_initial_price_from_order()` returns `accepted_escrows[0].price_per_hour` (already in uint256-domain base units) as the seller's `our_price`. The `BisectionStrategy` in `maximize` direction exits with `"price_unreasonable"` if `their_price < our_price / 1.5`, and does not counter. If the buyer's `BUYER_INITIAL_PRICE` in the e2e test is below this floor, the seller exits at round 0 and `force-accept` returns 409. **Rule:** `BUYER_INITIAL_PRICE >= accepted_escrows[0].price_per_hour` in the e2e test constants.

- **`negotiation_respond_to_make_offer` and related domain callables:** These are all no-ops until the `NegotiationEvent` model is restored. The domain callable chain currently plays no role in round-by-round negotiation decisions. Restoring it (or removing these callables) is part of the planned negotiation refactor.

- **`wait_for_registry_agent` retries past transient network states:** `"timeout"` and `"unreachable"` returned by `registry_auth_check._probe()` are transient network conditions. The wait loop retries past `"agent_not_found"`, `"timeout"`, and `"unreachable"`. Only definitive states (`"ok"`, `"owner_mismatch"`, `"unconfigured"`, `"owner_unknown"`, `"wallet_unconfigured"`, `"http_*"`) exit the loop immediately.

- **Global pause state persists across e2e test runs:** The storefront's `_GLOBALLY_PAUSED` flag (toggled by `POST /admin/pause` — distinct from per-listing `paused=True`) is in-process memory, not reset between `pytest` sessions. Neither full-deal scenario currently calls global `admin_pause` (storefront integration tests do, but those have their own teardown). The risk is a developer or external script having toggled it manually; the next `/negotiate/new` then 503s with `{"reason": "global"}` regardless of any per-listing state. The `ensure_storefront_resumed` autouse fixture in `integration-tests/tests/e2e/roles/scenarios/conftest.py` mitigates this by calling `admin_resume()` in module teardown. If running against a live environment that may have been left paused, execute `curl -X POST http://localhost:8001/admin/resume -H "X-Admin-Key: <key>"` before running.

- **Resource CSV importer DB path mismatch:** `scripts/import_resources_csv.py` resolves the target SQLite path via `--db-path` CLI arg → `AGENT_DB_PATH` env var → `CONFIG.agent_db_path` (in that order). Before this was fixed, the fallback was `/tmp/agent.db`, which differs from the server's `CONFIG.agent_db_path` (`./src/market_storefront/data/sell-agent/agent.db` in the compose stack). The importer silently seeded the wrong database; the server had zero resources and rejected all `/negotiate/new` calls with `409 no_matching_inventory`. **Fix:** `compose/seller.yml` now passes `--db-path src/market_storefront/data/sell-agent/agent.db` explicitly; the script fallback now reads `CONFIG.agent_db_path`. **Detection:** `GET /api/v1/system/status` now exposes `resource_count` as a top-level field; a value of `0` immediately signals this misconfiguration. The smoke test `test_resource_portfolio_seeded` in `test_storefront_smoke.py` asserts `resource_count > 0` and fails with a remediation command if not.

 The `EventSyncService` in the registry polls on-chain events every 60 s. On a fresh stack the initial sync (`sync_from_start`) may not complete before the e2e test reaches stage 03b (resume + publish). `publish_order_to_registry` issues `POST /agents/{canonical_id}/listings` against the registry; if the agent is not yet indexed, the registry returns 404 and the publish silently fails (`registry_status="error"` in the response). Stage 03b then fails its `registry_status == "published"` assertion, causing all negotiation stages to cascade-skip. Stage 03c (`TestStage03c_SellerAgentIndexed`) was added to gate on indexing completion via the new `GET /api/v1/system/sync/wait-for-agent` long-poll endpoint before any negotiation stage runs. **The `wait-for-agent` endpoint is the canonical pattern for this class of problem**: when a test needs to gate on an async background service completing a unit of work, add an admin/system endpoint that blocks server-side until the condition is met, then call it once from the test. This avoids client-side polling loops (fragile, sleep-based) and makes the wait observable (the endpoint logs the elapsed time).

- **`settings.SELLER.AGENT_ID` discrepancy in config files:** The e2e config files (`config/config-local.yml`, `config/config-docker.yml`) have `seller.agent_id: "eip155:31337:...:2"`. On a fresh Anvil the sentinel agent registers as ID 0 and the seller as ID 1, making `:2` stale. Stage 03c no longer uses this value — it calls `storefront.wait_for_registry_agent_ready()` which uses the storefront's live runtime agent ID. The `SELLER.AGENT_ID` value is still used by `SyncProvisioningClient` (as the `X-Agent-ID` header) and smoke tests. Update it to match `curl http://localhost:8080/agents` output for the seller's wallet when rebuilding the Anvil state.

- **E2e test dependency graph is not mechanically verified:** The `require_state(deal_state, "field")` chain between stages is enforced by convention only. A field set by one stage but not consumed by `require_state` in any downstream stage is a silent gap — the first failure cascades to a skip rather than a fail in the stage that actually needed it. A field name typo in a `require_state` call produces the same symptom: `getattr(deal_state, "nonexistent_field", None)` silently returns `None` and the test skips regardless of pipeline state. **Rule:** when adding a new `DealState` field, always verify that at least one downstream `require_state` call consumes it, and that the field name in `require_state` exactly matches the attribute name on `DealState`. This gap class cannot be caught by unit or integration tests — it is a property of the test's own dependency graph.

---

# Planned Rework

## Storefront

### 1. Remove event queue infrastructure in storefront

**Status:** Planned.

**Problem:** The event queue path (`is_event_queue_enabled()`, `queue_event()`,
`configure_default_ingestion()`, `enable_event_queue` and `enable_redis_ingest`
config fields) is dead code in the request path. `ListingService` was refactored
to a synchronous orchestrator model, eliminating all `is_event_queue_enabled()`
branches from the service layer. The redis ingest path (`start_redis_subscriber`,
 `stop_redis_subscriber`) in `agent.py` is the only remaining consumer and has no tests.

**Planned fix:**
1. Remove `enable_event_queue` and `enable_redis_ingest` from `Config` and `config.toml`.
2. Remove `configure_default_ingestion()` call from `agent.py`.
3. Remove `start_redis_subscriber` / `stop_redis_subscriber` calls from `_startup_tasks`.
4. Delete `utils/event_ingestion.py` (or retain only the `stage_event()` audit-log
   helper if it is used elsewhere — confirm before deleting).
5. Remove redis dependency from `pyproject.toml` if no other code requires it.

---

### 2. Remove TraderAgent class and root_agent shim from agent.py in storefront

**Status:** Planned.

**Problem:** `agent.py` still contains the `TraderAgent` class and a `_RootAgentShim`
instance named `root_agent`. The shim was introduced as a transitional adapter: it
forwards `._sqlite_client`, `._alkahest_client`, and `._process_event_with_pipeline`
attribute accesses to the `PolicyPipelineService` singleton in the container. This
exists because several functions in `agent.py` were not yet migrated to the service
layer when the FastAPI conversion landed, but all callers have since been removed.

**Planned fix:**
1. Verify no remaining code references `root_agent` or `TraderAgent` outside of `agent.py`.
2. Delete `TraderAgent`, `_RootAgentShim`, and `root_agent = _RootAgentShim()` from `agent.py`.
3. Move any remaining utilities still in `agent.py` (`_serialize_context_for_storage`,
   `_serialize_outcome_for_storage`, `_parse_domain_event`) to appropriate utils modules.
4. Rename `agent.py` to `startup.py` to reflect its actual remaining responsibility:
   background task management (`_startup_tasks`, `_ensure_agent_identity`,
   `_start_heartbeat`, `_preflight_provisioning`, `process_queued_events`).

---

### 3. Storefront config unification (TOML singleton → dynaconf profiles)

**Status:** Planned.

**Problem:** The storefront uses a bespoke TOML singleton (`CONFIG` in
`market_storefront.utils.config`) loaded once at import time via a custom
`load_user_config()` / `get_dotted()` chain. This is a different system
from the profile-based dynaconf loader used by the provisioning service
and the integration test suite. The inconsistency creates friction:
- Secrets and environment-specific overrides require a separate `config.toml`
  mount rather than profile files; there is no equivalent of the
  `provisioning-secrets` profile pattern for the storefront.
- The test suite cannot inject per-test config overrides cleanly — tests
  monkeypatch `_USER_CFG` directly, which is fragile.
- Adding a new config key requires touching the `Config` dataclass, the
  `load_config()` function, and every Helm template that renders the TOML —
  three places instead of one.

**Planned fix:** Migrate the storefront config to dynaconf profiles
following the provisioning service pattern:
- Replace `load_user_config()` / `get_dotted()` with `dynaconf.Dynaconf`
  with profile resolution via `ACTIVE_PROFILES` and `CONFIG_DIRECTORY`.
- The rendered `config.toml` becomes one profile file (`config-seller.yml`
  or similar) mounted from a Kubernetes Secret.
- The `Config` dataclass and `load_config()` are replaced by a thin
  validated wrapper over `settings.*` keys, or removed in favour of direct
  `settings` attribute access.
- Helm test pods consume the same profile files as the service pods,
  eliminating the separate `config-{component}-secret.yml` key that the
  storefront Secret currently emits for the test pod.

This is a prerequisite for clean secret injection (wallet keys, API keys)
via the standard Helm Secret + profile pattern.

---

### 4. Storefront GKE secret injection — chart-side split landed

**Status:** Helm chart split implemented (`a8db7d4`). Ops-repo bootstrap may
still need follow-up; full dynaconf migration (item 3) remains.

**What landed at the chart layer:** `helm/charts/storefront/` now emits two
artifacts per agent:

- a **ConfigMap** carrying non-sensitive runtime knobs (chain URLs, log paths,
  mode flags, seller agent identity, provisioning + negotiation sub-tables)
  rendered as `config.toml`
- a **Secret** carrying only sensitive values (wallet `address` + `private_key`,
  `admin_api_key`, `gemini_key`, inline `resources_csv`) rendered as
  `config.secrets.toml`

The runtime loader (`service/src/service/config_loader.py`) deep-merges the
two files under `/etc/arkhai/` so the Python config tree keeps its existing
shape — only the on-disk layering changed. Independent `checksum/config` and
`checksum/secrets` annotations on the Deployment isolate rollouts to whichever
source changed; flipping a log level no longer churns the Secret. Local-dev
callers reading a single `~/.config/arkhai/config.toml` are unaffected (the
overlay step is a no-op when only the base file exists). A `make test-render`
target in `helm/` runs `helm template` and asserts the structural invariants
(mount paths, key layout, no `private_key` leak into the ConfigMap, independent
checksums) without needing a cluster.

**What this means for rotation:** wallet key, admin key, and inline resources
CSV are now in a separate Secret object from the ConfigMap; they can be
rotated/edited independently of non-sensitive config without re-bundling.

**Still outstanding:**

1. Full dynaconf-profile migration (item 3 above) — the layered loader is a
   precursor; the storefront still uses the bespoke TOML singleton at
   `market_storefront.utils.config`.
2. Ops-repo (`compute-market-1-ops`) follow-ups: whether the
   `bootstrap-storefront-secret` flow has been simplified to write
   `config.secrets.toml` directly rather than rendering a full `config.toml`,
   and whether the duplicate `simple-market-service-admin-api-key` Secret
   Manager entry is still needed, depends on what the ops repo has done since
   this chart split landed. Cross-reference `compute-market-1-ops`
   `ARCHITECTURE.md § OPS-REWORK-1` before assuming.

---

## Registry Service

### 1. Registry as shared marketplace infrastructure (not per-node)

**Status:** Planned.

**Problem:** The `registry-service` is currently deployed as a subchart of the `arkhai-node-operator` Helm chart, implying it is part of every provider node's deployment. In practice the registry is a shared marketplace service — there is one per market, not one per provider. Multiple seller nodes should all register with and publish orders to the same registry instance run by the marketplace operator. Bundling it with the provider chart conflates the marketplace operator role with the provider role.

**Planned fix:** Make `registry` an optional subchart (add `condition: registry.enabled`, default `false`). Provider deployments point at an externally-operated registry via `global.registry.api_url`. Only marketplace operator deployments enable the subchart. Document the two deployment topologies (operator vs. provider) in the Helm `values.yaml` and in this file.

---

### 2. Event sync full-history gap

**Status:** Workaround landed (`4ae2bbf`); planned fix still pending.

**Problem:** `EventSyncService.sync_from_start()` only scans the last 1000
blocks for `Registered`, `MetadataSet`, and `URIUpdated` events. On a live
chain with registrations months ago this window misses all historical agents.
The registry's agent count is therefore a function of how recently agents
registered, not how many are actually on-chain.

**Workaround in place:** `REGISTRY_START_BLOCK` env (read in
`registry-service/src/config.py`) lets a fresh indexer backfill from a known
earlier block — typically the IdentityRegistry's deployment block — instead of
"last 1000 blocks". Unset behaviour is unchanged. This is enough to bring a
new indexer up to date on a known chain but still leaves the 1000-block sliding
window in place for steady-state polling.

**Planned fix:** Replace the sliding window with a full enumeration using view
functions: call `totalSupply()` on the IdentityRegistry to get the count of
registered agents, then call `ownerOf(id)` and `tokenURI(id)` for each token
ID from 0 to `totalSupply()-1`. This is a set of pure read calls with no event
history dependency, works correctly on any RPC provider, and is immune to
block range limits. The periodic sync can still use event filtering for
incremental updates after the initial full enumeration.

---

#### 1. Golden image configuration (`management-vars.yaml`)

**Problem:** The `golden-image-build` Ansible role writes `management-vars.yaml` to the operator's local machine with root SSH credentials for the golden image. The provisioning service reads these credentials through the standard dynaconf profile system, but the key names in `management-vars.yaml` do not match the names in `settings.toml`.

**What the provisioning service needs from `management-vars.yaml`:**
- `golden_root_ssh_filename` → maps to `settings.golden_root_ssh_filename`
- `golden_root_ssh_password` → maps to `settings.golden_root_ssh_password`
- `golden_image_name` → maps to `settings.golden_image_name`
- `golden_gcs_bucket` and `golden_gcs_project` → in `settings.toml`

**Decision:** The Ansible role should write `management-vars.yaml` keys using the exact names that dynaconf expects (matching `settings.toml`). The operator then includes the relevant keys in the Helm `values.yaml` `config:` block. No separate loader class or file-format adapter is needed.

> **TODO(management-vars):** Update `golden-image-build.yml` in `compute-provisioning-iac` to write key names matching `settings.toml` (`golden_root_ssh_filename`, `golden_root_ssh_password`, `golden_image_name`). Document the operator workflow for getting `management-vars.yaml` into the Kubernetes Secret in `compute-provisioning-iac/README.md`.

**`VmActionRequest` — shared optional body:**

Simple lifecycle actions (`start`, `shutdown`, `reboot`, `destroy`, `undefine`, `monitor`, `reset-password`, `cancel_expiry`) share one optional body model `VmActionRequest(buyer_agent_id, max_retries)`. The `build_simple_params(action, host, body, vm_name)` helper in `vm_request_model.py` produces `AnsibleJobParams` from path parameters + this body. `CreateVmRequest` and `ScheduleVmExpiryRequest` remain distinct classes with their own fields.

**`HostController.check_capacity` — future:** should eventually accept optional resource filter parameters (`vcpus`, `ram_mb`, `gpu_count`) and return ranked hosts with sufficient capacity — useful for the agent's pre-flight check before a `create` job.

### 2. Lease expiry watchdog

**Status:** Implemented.

**What was implemented:**
- `vm_leases` table tracks active leases; `LeaseStatus`: `pending`→`active`→`releasing`→`released`/`forced`/`cancelled`
- `LeaseService` — CRUD + lifecycle transitions
- `LeaseLifecycleService.check_leases()` — per-cycle logic:
  1. Activate pending leases whose `lease_start_utc` has passed (`list_pending_to_activate`)
  2. Submit check Ansible job for expired active leases; transition to `releasing` (`list_due` + `begin_releasing`)
  3. Poll check jobs for `releasing` leases; PATCH storefront resource when confirmed; handle grace period
- `LeaseWatchdog` — thin asyncio timer that calls `check_leases()` every 60 seconds
- `POST /api/v1/system/check-leases` — on-demand trigger for operators and tests; returns `{activated, checked, released, forced, skipped}`
- `POST /api/v1/leases` — storefront calls this after provisioning to register a lease
- Full CRUD leases API: `GET /api/v1/leases`, `PATCH /api/v1/leases/{id}`, `by-escrow`, `cancel`
- Storefront `PATCH /api/v1/admin/portfolio/resources/{resource_id}` — general-purpose partial resource update
- Storefront `resource_poller.py` removed (tombstoned). Storefront `_spawn_publish_loop()` removed.
- `storefront_url` / `storefront_admin_key` are global provisioning service settings. Helm renders `storefront_url` into the provisioning production config profile and `storefront_admin_key` into the `provisioning-secrets` profile. The default chart topology points the watchdog at the release's `storefront-bob` Service; non-standard topologies override `provisioning.storefront.url`.

**Remaining gap — check job result interpretation:**
`LeaseLifecycleService._process_releasing_lease` currently polls the check job status but treats `succeeded` and `failed` uniformly (both proceed to patch the storefront). A future iteration should parse the check job result's `available_gpus` field: if `available_gpus > 0` the VM is confirmed gone and the patch proceeds normally; if `available_gpus == 0` the VM may still be running (late `at` daemon, cleanup race) and the watchdog should wait another cycle before forcing. This requires `AnsibleJobService._build_result_payload` to consistently expose `result.available.gpus` for the `check` action.

The `at`-based scheduling on the KVM host still runs as before — the check job is a verification step, not a replacement for the `at` cleanup.

---

## Service Design Decisions

This section records design decisions reached through implementation experience. It exists so that the reasoning is available to future sessions without having to re-derive it from code.

---

### E2E Test Architecture for Event-Driven Services

**Context:** The e2e test validates a system that is conceptually event-driven (policy dispatch, settlement pipeline, provisioning) but is implemented as a synchronous orchestrator with an audit-log event stream (the `stage_events` SQLite table).

**Testing pattern for each pipeline stage:**

Each stage has two parts — a dry-run and an advance:

```
stage Na:  dry-run   — call the admin "what would you do?" endpoint
           validate  — assert the expected action before any state is changed

stage Nb:  advance   — call the real endpoint (often with paused=True to control pacing)
           validate  — read from the stage_event stream to confirm what happened
```

**Concrete example:**

```python
def stage_1a_evaluate_create():
    # dry-run: what would policy do?
    result = admin_client.policy_evaluate(offer=..., demand=...)
    assert result["action"] == "make_offer"

def stage_1b_create_listing():
    # advance: create in paused state (not published to registry yet)
    resp = admin_client.create_listing(offer=..., demand=..., paused=True)
    assert resp.listing_id is not None
    # audit: confirm listing appears in stage_event stream
    event = wait_for_stage_event(stage="discovery", event="listing_created")
    assert event["listing_id"] == resp.listing_id
```

**Admin "what would you do?" endpoints** (dry-run, no side effects):
- `POST /api/v1/admin/listings/evaluate-create` → `AdminEvaluateCreateResponse`
- `POST /api/v1/admin/listings/{listing_id}/evaluate-close` → `AdminEvaluateCloseResponse`
- `POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate` → `EvaluateNegotiateResponse` (runs the configured negotiation strategy against a synthetic buyer offer; returns `would_negotiate=False` if the strategy would exit immediately)
- `POST /api/v1/system/policy/evaluate` → `PolicyEvaluateResponse`

These call the policy consultation step only — `PolicyService.evaluate_*_listing_policy()` — without executing any action. They exist specifically to enable the stage-Na validation pattern.

**The event stream as the observable:** `GET /api/v1/system/events` (`SyncStorefrontClient.wait_for_stage_event()`) provides a cursor-based poll over the `stage_events` SQLite audit log. This is the mechanism for validating "what did you do?" without polling the resource directly or using `asyncio.sleep`. See `wait_for_stage_event` in `integration-tests/tests/e2e/roles/scenarios/conftest.py`.

**The pause/advance pattern for multi-step pipelines:** Create resources with `paused=True` to prevent them from propagating to the next pipeline stage before the test has validated the current stage. Use admin endpoints (`resume`, `advance`, `force-accept`) to advance one step at a time. This is how the e2e test controls pacing through the negotiation → settlement → provisioning pipeline without race conditions.

**What the e2e test deliberately does NOT test:** The two-line event-queue adapter (see orchestration section above). Everything else in the service layer is exercised by the stage-by-stage dry-run + advance + stream-inspect pattern.

---

### Admin Endpoint Conventions

**Admin vs operator vs buyer endpoints:**

| Audience | Auth | URL prefix | Example |
|---|---|---|---|
| Operator tooling / scripts | `X-Admin-Key` | `/api/v1/admin/` | `POST /api/v1/admin/pause` |
| Buyer agents (external) | EIP-191 buyer sig | `/api/v1/negotiate/`, `/api/v1/settle/` | `POST /api/v1/negotiate/new` |
| Seller tools | EIP-191 seller sig | `/api/v1/listings/create` etc. | `POST /api/v1/listings/create` |
| Public read | none | `/api/v1/listings`, `/health` | `GET /api/v1/listings` |

**Admin auth implementation:** `require_admin_key` is a FastAPI `Security()` dependency using `APIKeyHeader(name="X-Admin-Key")`. It is applied via `_key=Depends(require_admin_key)` in the `__init__` of admin CBV classes — NOT at the router constructor level (which causes `fastapi_utils @cbv` route registration failures).

**Swagger Authorize button:** The `X-Admin-Key` security scheme is registered in the custom `openapi()` function in `server.py`. The Authorize button appears at the top of the Swagger UI, pre-filled keys persist across page reloads (`persistAuthorization: True`).

**Swagger behind API gateways:** Services that are exposed behind a stripped
path prefix configure FastAPI with the service's gateway `root_path` at app
construction time. FastAPI uses `root_path` when rendering `/docs`, so Swagger
UI fetches the prefixed OpenAPI URL (for example `/storefront/openapi.json`)
instead of the domain root `/openapi.json`. The custom OpenAPI function still
adds a matching `servers` entry so Swagger's generated curl examples and "try
it out" requests target the gateway prefix. The two settings serve different
parts of the Swagger flow and should remain in sync.

**Buyer-facing EIP-191 auth:** Buyer endpoints (`/api/v1/negotiate/*`, `/api/v1/settle/*`) use EIP-191 signatures in `X-Signature` + `X-Timestamp` headers. This is not a standard OpenAPI security scheme; it is documented in each endpoint's OpenAPI `description`. Auth is verified by calling `buyer_auth._verify(request, operation, resource_id, claimed_address)` directly inside the handler — not via `Depends()` — to avoid `fastapi_utils @cbv` + method-level `Depends` interaction issues. Tests bypass auth via `unittest.mock.patch.object(buyer_auth, "_verify", return_value=None)`.

## Testing Strategy

> **Test execution context:** The e2e / system integration test suite runs from a **Helm test pod** inside the cluster. It cannot import or instantiate service code in-process. All assertions are made over HTTP against live services using typed client libraries. This affects every layer of the test design: there is no `ASGITransport`, no monkeypatching of service internals, and no direct DB reads from the test pod. Visibility into service state is provided exclusively through HTTP endpoints — which is why the storefront and provisioning service expose rich read APIs rather than relying on direct DB inspection.

This section defines the testing conventions for the Arkhai Market Stack. It exists to give every contributor a consistent mental model of what each test level is responsible for, what it is explicitly not responsible for, and how the levels relate to each other. New tests should be placed at the lowest level that can meaningfully exercise the behaviour in question.

### Four-Level Hierarchy

#### 1. Unit Tests

**What they cover:** Classes in isolation. A unit test instantiates one class, passes in mocked collaborators for all injected dependencies, and asserts on the return value or side effects of a specific method.

**What they do not cover:** Orchestration — if a function's sole purpose is to call other functions in sequence, that function does not have meaningful unit tests. The correctness of the sequence is an integration test concern. Lower-level functions that are the final abstraction before an external boundary (a database write, a subprocess invocation) are similarly not meaningful to unit test in isolation; their behaviour is validated by integration tests against the real boundary or a well-defined mock of it.

**What to focus on in this codebase:**
- `AnsibleService`: `_build_vm_vars` (YAML serialisation of every field combination), `_extract_ssh_port` / `_extract_tenant_user` / `_extract_ansible_json` (output parsers against representative playbook output strings).
- `AnsibleJobService`: `_build_params` (dict → `AnsibleJobParams` mapping), `_redact_logs` (regex redaction), `_calculate_retry_delay` (backoff arithmetic), `_should_retry_error` (error string matching), `_build_result_payload` (structured result assembly from `AnsibleRunResult`).
- `models/vm_request_model.py`: `CreateVmRequest` Pydantic validation (FRP cross-field rule, field constraints), `ScheduleVmExpiryRequest` required field, `build_simple_params` action routing.
- `HostService`: `seed_from_ini` (INI parsing, upsert idempotency), `register_host` with `embedded` key (Fernet encryption round-trip), `render_inventory_ini` (correct `[kvm_hosts]` group + variable output), `list_hosts(enabled_only=True)` filter.

**Mocking convention:** Use `unittest.mock.MagicMock` / `AsyncMock` for injected collaborators. Do not patch module-level imports; instead, pass mocks in via the constructor (the DI design makes this natural).

#### 2. Integration Tests

**What they cover:** End-to-end HTTP request → response paths with the full application stack running (FastAPI app, real SQLite DB, DI container wired) and a controlled mock at the external I/O boundary. Orchestration logic, the job processing loop, retry behaviour, and error propagation are all validated here.

**What they do not cover:** Every edge case of data transformation logic — that belongs in unit tests. Integration tests need one representative case per external mock behaviour, not exhaustive parametrisation.

**External boundary definition:** Any I/O that crosses a process boundary. In this codebase that means:
- Ansible subprocess invocations — mocked at `AnsibleService` (replace `start_playbook` / `wait_for_playbook` / `check_connectivity`)
- The ERC-8004 registry HTTP call in `AgentAuthMiddleware` — bypassed by disabling auth (`enable_auth=false` in test settings)

**Test setup pattern:** Use `httpx.AsyncClient` with `ASGITransport` against the real `app` instance, injected via the canonical `FooClient(transport=...)` constructor. Override container providers for `AnsibleService` before the test and restore them after. See `src/tests/integration/conftest.py` for the full fixture implementation.

**Client contract verification:** Integration tests call `ProvisioningClient` methods directly against the in-process app. Route strings, request body shapes, and response parsing are owned by the client — no raw HTTP calls appear in test code. If the API renames a field or changes a route, the client method raises `ProvisioningError` and the test fails immediately.

**The "no raw calls" rule — two legitimate exceptions:**

The rule is absolute for happy-path tests. Two narrow exceptions are permitted:

1. **Rejection-path tests** — testing server-side validation of inputs the typed client deliberately refuses to construct (e.g., asserting a 422 on a malformed body that `CreateVmRequest` Pydantic validation would reject before it ever reaches the HTTP layer). These tests verify the *server's* validation boundary, not the client's. They use `client._client.post(...)` (async) or a raw `httpx` call with the same `ASGITransport`. They must: (a) only assert on status codes, never on response body field names; (b) be clearly commented as rejection-path tests.

2. **Service-internal state setup** — inserting DB rows directly via `db_session.add(...)` to establish precondition state that cannot be expressed through any HTTP API endpoint. This is not an HTTP call at all; it is the standard test-setup pattern documented above.

Any other use of `_request`, `_client.get/post`, or raw `httpx` in an integration test is a gap that requires either adding a method to the canonical client or restructuring the test. The comment `"not yet a client method"` is a deferred debt marker, not a permanent exemption — it must reference a tracking item and be resolved before the gap accumulates.

**State setup convention:** Test precondition state (e.g., a job row that must already exist before the endpoint under test is called) should be created through the HTTP API where feasible. Use direct DB factory functions only for state that is not expressible through any API endpoint — this keeps integration tests honest about the API contract.

**Async test discipline — no sleeps:** Tests that exercise the background job processing loop must never use `asyncio.sleep` or `await asyncio.wait_for(..., timeout=...)` to wait for side effects. These approaches always produce intermittent failures. The correct pattern uses the `on_job_started` seam on `AsyncJobQueue`:

```python
job_dispatched = asyncio.Event()

def _on_started(job_id: str) -> None:
    job_dispatched.set()

job_queue._on_job_started = _on_started

response = await client.post("/api/v1/hosts/ww1/vms/", json={...})
await asyncio.wait_for(job_dispatched.wait(), timeout=5.0)
# Now safe to poll GET /api/v1/jobs/{job_id} for terminal state
```

`AsyncJobQueue.__init__` accepts `on_job_started: Optional[Callable[[str], None]]` as a test seam. It is `None` in production and zero-cost.

#### 3. Smoke Tests (Deployment Validation)

**What they cover:** Stateless, idempotent verification that a deployed stack is wired correctly — services can reach each other, authentication headers are enforced, health endpoints return 200, expected routes exist. These run as Helm test hooks in Kubernetes.

**What they do not cover:** Service semantics. By the time a smoke test runs, the semantics have already been validated by integration tests. A smoke test for the provisioning service should verify that `GET /health` returns 200 and that `POST /api/v1/hosts/ww1/vms/` returns 401 without an `X-Agent-ID` header — it should not submit a real provisioning job and poll for completion.

**Current location:** `helm/templates/tests/` as Kubernetes Job resources executed by `helm test`.

#### 4. System Integration Tests (End-to-End)

**What they cover:** Cross-service contracts — scenarios that require two or more services to interact over the network to produce a meaningful result. Examples: a buyer agent successfully negotiating with a seller agent and reaching a settled on-chain state; a provisioning job triggered by an agent completing and the buyer receiving credentials.

**What they do not cover:** Anything already covered by the three levels above. System integration tests are expensive to run and brittle to maintain; they should be minimal in count and cover only the cross-service contract, not any service's internal logic.

**Current location:** `integration-tests/tests/e2e/` — the `roles/` subtree organises tests by deployment layer (external chain, market registry, seller node) and negotiation stage (discovery, negotiation, settlement). This is planned to move to a separate project as the stack matures.

#### Full-Deal E2E Test — two scenarios

The full-deal scenario exists in two parallel variants under
`tests/e2e/roles/scenarios/`, sharing the readiness + listing + provisioning
stages but diverging on how the buyer drives negotiation and settle:

| File | Marker | Buyer side |
|---|---|---|
| `test_full_deal.py` | `e2e_deal` | Synthetic — `SyncStorefrontClient.negotiate_new()` + admin `force_accept`, dry-run + advance at every stage (matches the "E2E Test Architecture for Event-Driven Services" pattern below) |
| `test_full_deal_buyer_cli.py` | `e2e_deal_buyer_cli` | Production — `market negotiate` and `market settle` subprocesses against a hermetic XDG state dir; cross-process state is observed via the buyer's run-log JSONL |

Both run via `make test-module MODULE=<marker>`. They share the readiness
phases (00a–00h), policy/listing/publish phases (01a–04a), settle dry-run
(08a/08c), the gate-release + ready/credentials terminal phases (09a–09c),
and the lease-expiry phases (10a–11b). Sequential tests use
`require_state(deal_state, "field_name")` so the first failure is the
actionable one; downstream stages skip rather than cascade-fail.

`DealState` in `scenarios/conftest.py` is the union of fields each scenario
needs. Fields used only by the buyer-CLI variant (`buyer_run_id`,
`settle_run_handle`, `vm_host`, …) stay `None` in the synthetic run, and the
autouse `reap_buyer_settle_subprocess` teardown is a no-op when
`settle_run_handle` is None.

**Synthetic-buyer stages (`test_full_deal.py`):**

| Test | Stage | Observable |
|---|---|---|
| 00a–00h | Readiness | storefront/registry/provisioning health, negotiation-strategy probe, provisioning mock-mode wiring, alkahest config, storefront↔provisioning link |
| 00f | Resource seed | `POST /api/v1/admin/portfolio/resources/import` upserts the inline e2e compute CSV |
| 01a / 01b | Policy dry-run + seed | `POST /api/v1/system/policy/evaluate`; `POST /admin/policy/seed` |
| 02a / 02b | Create listing | dry-run `evaluate-create` then `POST /api/v1/listings/create paused=True` |
| 03a / 03c / 03b | Publish & index | `POST /api/v1/listings/validate-publish` → `wait-for-agent` long-poll → resume publishes to registry |
| 04a | Primary registry visibility | listing visible on registry |
| 05a / 05b | Negotiate | `evaluate-negotiate` → `POST /negotiate/new`; assert `round_decided` event with decision=counter |
| 06b | Force-accept + terminal | guard no prior exit/accept; `POST .../force-accept` → accept; thread terminal=success |
| 07 | Provision gate | `add_mock_rule(pause_before_result=True)` |
| 07b | Verify escrow | buyer creates real escrow via alkahest; `POST /api/v1/admin/settle/{uid}/verify` → valid |
| 08a / 08c | Settle + provisioning-job dry-runs | `evaluate-settle` (captures `vm_host`/`vm_target`); `POST /test/evaluate-job` (matches gate rule) |
| 08b | Submit settle + job queued | `POST /api/v1/settle/{uid}`; `wait_for_stage_event(resource_reserved)`; `provisioning_job_id` surfaced |
| 09a | Gate release + ansible succeeds | `resume_rule`; `wait_for_job` (long-poll) → succeeded |
| 09b | Ready + credentials + listing closed | `wait_for_settlement` → ready; `GET /api/v1/settle/{uid}/status` → tenant credentials; listing accepted/closed |
| 09c | Lease registered | `GET /api/v1/leases/by-escrow/{uid}` → active/pending |
| 10a / 10b | Lease expiry setup + watchdog advances | pause watchdog, patch `lease_end_utc` past, arm check-gate mock; watchdog transitions lease to `releasing` |
| 11a / 11b | Releasing state stable + resource released | check-gate released; resource patched `available` via `PATCH /api/v1/admin/portfolio/resources/{id}` |

**Buyer-CLI variant divergence (`test_full_deal_buyer_cli.py`):**

- **05b** — `market negotiate --listing-id … --max-price 12000 --duration-hours 1 --yes` runs synchronously to terminal. Bisection on both sides converges in ~1 round (buyer ceiling above seller's first counter). Test asserts subprocess `rc=0`, run-log `run_ended.status=agreed`, and seller-side `round_decided` stage_event.
- **06b deleted** — `force_accept` coverage stays in `storefront/tests/integration/test_negotiations_api.py`.
- **07** — only arms the provisioning gate; escrow creation moves out.
- **08i** — `market settle --from <run_id>` started as a **background subprocess**. It creates the real on-chain escrow under the buyer's wallet, POSTs `/api/v1/settle/{uid}`, then blocks on its status-poll loop at the armed provisioning gate. Test waits for `escrow_created` event in the run-log, captures uid, then proceeds through 07b/08b/09a as normal.
- **09b** — observes ready from the buyer side: `wait_for_event(settle_terminal, status="ready")` from the buyer run-log, asserts `tenant_credentials` in the event body, waits for the background `market settle` subprocess to exit cleanly (`Popen.wait(timeout=10)`, `rc=0`).
- Rest of the flow (09c, 10a–11b) matches the synthetic variant.

**`_build_provisioning_job_spec` seam:**

```
POST /api/v1/settle/{uid}
  ├── getRecordFromChain  verify_escrow_for_settlement()
  ├── doWork              _build_provisioning_job_spec(reserve=True)  ← extracted seam
  └── submitJob           asyncio.create_task(_run_settlement_job_bg())
```

`evaluate_settle` calls `_build_provisioning_job_spec(reserve=False)`. The real flow calls it with `reserve=True` (atomically marks resource reserved). `select_available_compute_vm(reserve=False)` is the read-only inventory lookup used by the evaluate path; `select_available_compute_vm(reserve=True)` is the write path used by the real flow. `reserve_available_compute_vm` is a deprecated alias for `select_available_compute_vm(reserve=True)`. The dry-run service passes its request-scoped/injected SQLite client into `_build_provisioning_job_spec`; the helper only falls back to the process-global client when no client is supplied. This keeps in-process integration tests on the same database for listing lookup and inventory selection.

**Provisioning evaluate-job endpoint (test controller):**

`POST /test/evaluate-job` on the provisioning service's test controller. Accepts `{host, vm_target, ssh_pubkey, vm_action}`, returns `{params_valid, host_exists, rule_matched, would_pause, errors}`. Checks host existence in inventory and which mock rule (if any) would match the job params. No job is created. Used by e2e stage 9a.

**`/api/v1/negotiate/new` signing and escrow terms:** `StorefrontClient.negotiate_new()` and `SyncStorefrontClient.negotiate_new()` add EIP-191 `X-Signature` and `X-Timestamp` headers automatically. They accept `listing_id`, `buyer_address`, `initial_price`, `duration_seconds`, `buyer_agent_url`, `ssh_public_key`, `token`, and `escrow_expiration_unix`, then build the structured `provision_terms` and `escrow_terms_proposal` body required by the server. The buyer proposal's `fields["token"]` must match one of the listing's `accepted_escrows[i].fields.token` advertisements; omitting it makes the helper send the zero address, which is only valid for listings without a typed payment token. If an e2e test raises `TypeError: SyncStorefrontClient.negotiate_new() got an unexpected keyword argument 'token'`, the runtime is importing a stale `arkhai-storefront-client` install. Rebuild the wheel and reinstall consumers with `make reinit` so `uv.lock` is re-resolved against the current `.dist/` wheel.

**Current full-deal details:** stage 03c uses the storefront's
`GET /api/v1/system/wait-for-registry-agent` long-poll, not a direct
registry wait. The full-deal happy path assumes one primary registry; private
registry auth and multi-registry fan-out/fan-in belong in separate
topology-specific e2e tests. Stage 07 creates the real buyer escrow and arms
the mock provisioning gate. The test imports its own inline compute resource
CSV and pins the offer to that row with `resource_id`, so settlement must
reserve the e2e-seeded row rather than any matching inventory row from a
mounted startup file. Stage 08b waits for `provision/job_submitted` and
asserts the reserved resource is the inline e2e-seeded row. Stage 09c
asserts provisioning registered an active/pending lease for the escrow via
`GET /api/v1/leases/by-escrow/{uid}`. Admin pause/resume and forced
resource release are intentionally outside the full-deal happy path; they
belong in separate smoke or e2e tests for operator interventions.

**Pre-negotiation inventory guard:** `/api/v1/negotiate/new` enforces immediate-deal inventory availability through `PolicyService.consult_pre_negotiation_guards()`, not by hard-coding inventory lookup inside the controller. The default `negotiate_request.default.v1` composite contains `negotiate.guard.has_matching_inventory`; if no available resource matches the listing offer, the guard returns `REJECT_OFFER` with `reason="no_matching_inventory"`, which the controller maps to HTTP 409. In-process integration tests that assert this behavior must wire `container.resolved_policy_service` with a real `PolicyService`; otherwise `start_sync_negotiation(..., policy_service=None)` deliberately skips policy-owned guards and only validates infrastructure invariants such as pause state and listing status.

**`ensure_storefront_resumed` teardown:** An `autouse=True` module-scoped fixture in `conftest.py` that unconditionally calls `admin_resume()` if `get_system_status().paused` is True after the module finishes. This targets the **global** `_GLOBALLY_PAUSED` flag (`POST /admin/pause|resume`), not the per-listing `paused=True` flag the synthetic scenario flips at 02b/03b. Neither full-deal scenario currently calls global `admin_pause`, but the fixture stays in place so a future test or a manually-paused live environment cannot strand the next run in 503.

**`wait_for_stage_event` helper:** In `conftest.py`. Wraps `SyncStorefrontClient.wait_for_stage_event()` with pytest-friendly timeout error. Used at stage 08b to await the `resource_reserved` event (provisioning job queued) without a sleep loop. The underlying client method polls `GET /api/v1/system/events` with a cursor and 500ms interval. For stages where the observable is a background job reaching terminal state rather than a discrete pipeline event, prefer a server-side long-poll (see `wait_for_settlement` below).

**`wait_for_registry_agent_ready` (storefront client):** `SyncStorefrontClient.wait_for_registry_agent_ready(timeout=90.0)` calls `GET /api/v1/system/wait-for-registry-agent` — a single server-side long-poll on the storefront. The storefront calls `registry_auth_check()` (which fetches `GET /agents/{canonical}` from the registry using the storefront's live runtime agent ID) every 1 s until the result is definitive (anything other than `"agent_not_found"`), or the timeout elapses. Returns `RegistryAgentReadyResponse(ready, registry_auth, elapsed_ms)`. Used at stage 03c. **Advantage over querying the registry directly:** no agent ID config is needed — the storefront uses its own live runtime ID (set by `_ensure_agent_identity` at startup), so the wait is correct regardless of what numeric ID was assigned on-chain.

**`wait_for_settlement` (storefront client):** `SyncStorefrontClient.wait_for_settlement(escrow_uid, timeout=60.0)` calls `GET /api/v1/admin/settle/{uid}/wait` — a server-side long-poll on the admin settle controller. The storefront polls `load_settlement_job` every 1 s until the job status is `"ready"` or `"failed"`, or the timeout elapses (server-enforced max 120 s). Returns `SettleWaitResponse(ready, status, provisioning_job_id, elapsed_ms)`. Used at stage 09b. Returns immediately if the job is already in a terminal state when called. Callers must check `result.ready` (timeout flag) and `result.status` (the actual job state). The admin-only auth boundary is intentional: this endpoint surfaces internal settlement job state that the buyer does not need; the buyer's observable is the existing `GET /settle/{uid}/status` point-in-time read.

**Pattern: server-side long-poll for background work.** Any time a test needs to gate on a background task completing a unit of work, add an admin/system endpoint that blocks server-side until the condition is met, then call it once from the test. This is preferable to client-side polling loops for two reasons: the wait is observable (the endpoint logs elapsed time), and it avoids the mismatch between client timeout and server-side poll interval that caused the stage 09b flakiness. The `wait-for-registry-agent` and `wait-for-settlement` endpoints are the canonical examples of this pattern.

**`GET /api/v1/system/status` top-level fields:** In addition to `checks`, the full diagnostic status endpoint exposes three top-level fact fields (admin key required):
- `agent_id` — the storefront's canonical `eip155:…` agent ID (from live runtime state; `None` if not yet registered)
- `chain_id` — the EVM chain ID (from `CONFIG.chain_id` or RPC fallback; `None` if both fail)
- `resource_count` — number of rows in the local `resources` table. `0` immediately signals that the CSV importer wrote to a different SQLite path than the server reads — the root cause of `no_matching_inventory` 409s. Exposed by `SyncStorefrontClient.get_system_status().resource_count`.

**Provisioning gate pattern:** Stage 07 arms the gate via `ProvisioningTestClient.add_mock_rule` with `pause_before_result=True`; stage 09a calls `resume_rule` then `wait_for_job` (long-poll, no sleep). The gate decouples settle-submitted (08b) from job-succeeded (09a), so the test can assert on the intermediate state (`resource_reserved` stage_event, `provisioning_job_id` surfaced) before the Ansible mock completes.

**Topology requirements:**
- Storefront with `admin_api_key` set; `settings.SELLER.ADMIN_API_KEY` and `settings.SELLER.PRIVATE_KEY`
- Registry reachable; `settings.REGISTRY.API_URL`
- Provisioning with `ACTIVE_PROFILES=mock`; `settings.PROVISIONING.API_URL`
- Buyer wallet: `settings.BUYER.PRIVATE_KEY`, `settings.BUYER.WALLET_ADDRESS`
- `settings.SELLER.WALLET_ADDRESS` (for EIP-191 signing of `POST /orders/create`)

**`ProvisioningTestClient`** (`integration-tests/src/provisioning_test_client.py`) — sync HTTP client for the `/test/*` endpoints. Not part of `SyncProvisioningClient`; test infra only. Methods: `add_mock_rule`, `list_mock_rules`, `delete_mock_rule`, `resume_rule`, `job_summary`, `wait_for_job` (long-poll), `drain` (long-poll).

### Coverage Contract Between Levels

Each level has a defined jurisdiction. Duplicating coverage across levels creates maintenance burden without safety benefit:

| Concern | Unit | Integration | Smoke | System |
|---|---|---|---|---|
| Data transformation / parsing logic | ✅ exhaustive | one happy path | ❌ | ❌ |
| Pydantic validation rules | ✅ exhaustive | ❌ | ❌ | ❌ |
| Orchestration / job lifecycle | ❌ | ✅ exhaustive | ❌ | ❌ |
| Retry / backoff arithmetic | ✅ | one case | ❌ | ❌ |
| Auth middleware enforcement | ❌ | ✅ | one case | ❌ |
| Client ↔ API contract | ❌ | ✅ | ❌ | ❌ |
| Service-to-service wiring | ❌ | ❌ | ✅ | ❌ |
| Cross-service negotiation flow | ❌ | ❌ | ❌ | ✅ |

### Test File Layout

**provisioning-service** (reference layout):
```
provisioning-service/src/tests/
├── unit/
│   ├── conftest.py              # mock_settings fixture
│   └── services/
└── integration/
    ├── conftest.py              # app fixture, container overrides, DB setup, fake_ansible
    └── test_{controller}.py
```

**registry-service**:
```
registry-service/tests/
├── conftest.py                  # db_session fixture (in-memory SQLite), sign_order_auth helper
├── unit/
│   ├── test_agent_id_lookup.py  # find_agent_by_id — canonical ID parsing, case folding
│   ├── test_event_sync.py       # EventSyncService — chain event processing, error handling
│   ├── test_order_auth_utils.py # EIP-191 signature verification helpers (exhaustive)
│   ├── test_filter_eval.py      # build_criteria + evaluate_all — spec-driven listing
│   │                            # filter semantics (replaces the deleted matches_resource_filters)
│   └── test_filter_spec.py      # YAML loader, FilterDecl validation, ETag stability + sensitivity
└── integration/
    ├── conftest.py              # RegistryClient wired to in-process app via httpx ASGITransport;
    │                            # shared agent/order fixtures; Hardhat key constants
    ├── test_agents.py           # GET /agents, GET /agents/{id}, GET /agents/search,
    │                            # POST /agents/register, POST /agents/{id}/heartbeat
    ├── test_api_keys.py         # REQUIRE_API_KEY mode auth flow
    ├── test_filter_spec.py      # GET /filter-spec full HTTP path + ETag header
    ├── test_listings.py         # GET /listings, GET /listings/{id}, POST /agents/{id}/listings,
    │                            # GET /agents/{id}/listings, DELETE /listings/{id}, full lifecycle
    ├── test_listings_filtering.py # spec-driven query params (gpu_model, ram_gb_min lower-bound
    │                            # alias, token array projection, If-Match 412, unknown filter 400)
    ├── test_validate_publish.py # JSON Schema dry-run cases (happy + each rejection class)
    └── test_system.py           # GET /health (including 503 on DB failure),
                                 # GET /api/v1/system/config, /sync, /stats
```

**Client contract enforcement in registry-service integration tests:**

All integration tests import `RegistryClient` from the `arkhai-registry-client` wheel and exercise the API exclusively through it.  The transport is `httpx.ASGITransport(app=app)` — real HTTP through the full FastAPI stack, no network socket.  If the API renames a field or changes a response shape, the client's `from_dict` parser will either raise or silently drop the field, and the assertion will fail immediately.  The `get_db` dependency is overridden per-test to yield the fixture's isolated in-memory SQLite session.

The two legitimate raw-call exceptions (rejection-path tests and `db_session` state setup) apply here exactly as documented in the provisioning-service section above. All previously-raw calls to `/api/v1/system/config`, `/api/v1/system/sync`, `/api/v1/system/stats`, and `PUT /listings/{id}` have been replaced with typed client methods in `arkhai-registry-client` 0.2.0. Version 0.3.0 added `validate_publish_listing()` (`POST /api/v1/listings/validate-publish`) on both `RegistryClient` and `SyncRegistryClient`, plus `ValidatePublishRequest` and `ValidatePublishResponse` models. **Current version: 0.7.0.** The 0.7.0 line added `ListingRequest.seller` and `ValidatePublishRequest.seller` (`""` default) to align with filter-spec v2, which makes `seller` a required publish-candidate field — the storefront populates it from `BASE_URL_OVERRIDE`/seller URL.

**service package (`market-service`)**:
```
service/tests/
├── unit/
│   ├── test_signing.py
│   ├── test_heartbeat.py
│   ├── test_role.py
│   ├── test_alkahest.py
│   ├── test_config_loader.py
│   ├── test_token.py
│   └── test_erc8004_blockchain.py   # pure-function tests (rpc_url conversion, canonical ID)
└── integration/
    └── test_abi_alignment.py        # ABI codec alignment — see pattern below
```

**ABI alignment test pattern (`service/tests/integration/test_abi_alignment.py`):**

The `service.clients.erc8004.registration` module constructs Python dicts that are passed to web3's ABI codec as `MetadataEntry` struct arguments. If the dict field names don't match the ABI component names, web3 raises `KeyError` during `encode_abi()` before any transaction is broadcast. This is the failure mode that caused the `'metadataKey'` registration crash when the vendored ABI was updated from a hand-pasted version.

The integration tests guard this invariant by calling `contract.encode_abi()` against the real vendored ABI using a provider-less `Web3()` instance — no Anvil, no deployment, no network:

```python
def test_register_with_metadata_encodes_without_error(contract):
    metadata = _build_metadata_entries("agent", {"name": "agent"})
    encoded = contract.encode_abi("register", args=["http://example/reg", metadata])
    assert encoded
```

The `_build_metadata_entries()` helper in `registration.py` is the single authoritative source for struct field names — all metadata construction goes through it. When the ABI is updated, `test_metadata_entry_field_names_match_abi_struct` fails with an explicit message pointing at `_build_metadata_entries`.

**Status / planned rework:**

| Status | Problem | Planned fix |
|---|---|---|
| TODO | No EVM-level test for registration *logic* (detecting existing agents, idempotent updates, event parsing) | Option A: add `eth-tester[py-evm]` to service dev deps; add fixture that deploys IdentityRegistry bytecode into `EthereumTesterProvider`; write tests for `register_onchain_from_config` against local EVM. Requires bytecode available in repo (currently only ABI is vendored). Evaluate after erc-8004-contracts compilation artifacts are stable. |

**integration-tests**:
```
integration-tests/
├── conftest.py                  # CLI options (--profile, --config-dir); sets env vars pre-import
├── src/                         # Shared clients and settings (not test files)
│   ├── agent_client.py          # SyncStorefrontClient adapter shim (see Re-export shims)
│   ├── registry_client.py       # SyncRegistryClient re-export shim
│   ├── settings.py              # dynaconf settings loader
│   └── web3_client.py           # Web3 connection helper
└── tests/
    ├── conftest.py              # Session fixtures: w3, rpc_settings, registry_settings,
    │                            # buyer_settings, seller_settings, min_eth_balance
    ├── helpers/                 # Shared helpers used by both smoke and e2e tests
    │   ├── addresses.py
    │   ├── polling.py
    │   ├── registry_helpers.py
    │   └── sqlite_reader.py
    ├── fixtures/                # Shared pytest fixtures (ABIs, etc.)
    ├── smoke/                   # Smoke tests — stateless deployment validation
    │   ├── test_contracts_smoke.py     # On-chain contract bytecode + owner()
    │   ├── test_registry_smoke.py      # Registry reachability, health, seeding
    │   ├── test_wallets_smoke.py       # Wallet balance + key/address consistency
    │   ├── test_provisioning_smoke.py  # Provisioning API health, host registry, auth
    │   └── test_storefront_smoke.py    # Seller storefront reachability + registration
    └── e2e/                     # System integration tests — cross-service scenarios
        └── roles/               # Organised by deployment layer and negotiation stage
            ├── conftest.py      # Imports layer fixtures (external_world, market_registry, seller_node)
            ├── helpers/         # deal.py (full deal flow helper), erc20.py
            ├── layers/          # test_external.py, test_market.py, test_seller.py
            └── stages/
                └── discovery/test_buyer.py
```


### Problem
Python packages in this monorepo need to consume each other (e.g. the storefront imports the provisioning service client). Relative path imports across project directories are fragile — they encode layout assumptions and break when projects move. Native extension wheels (those with platform/ABI tags like `cp312-cp312-linux_x86_64`) must be compiled inside the target Docker environment; this is why `alkahest-py` ships pre-built wheels for each platform in `storefront/packages/`. Pure Python wheels (`py3-none-any`) have no such constraint and can be built safely on the host.

### Current Approach: `--find-links` flat wheel directory

Pure Python internal packages are built as wheels and placed in `.dist/` at the monorepo root before Docker images are built. Docker images consume them via `uv sync --find-links /dist`.

**Build sequence:**

```
make dist          →  uv build for each pure-Python package  →  .dist/*.whl
make build         →  docker build (COPY .dist/ /dist/, uv sync --find-links /dist)
```

`make dist` runs automatically as a prerequisite of `make build-runtime-images`.

**Guard:** `make dist-provisioning` asserts the output wheel filename ends in `-none-any.whl`. If a C extension or Rust crate is ever added to a package, the build fails loudly with an error directing the developer to move compilation inside the Docker build context.

**Why `--find-links` is passed on the CLI, not in `pyproject.toml`:**

`find-links` encodes a filesystem path. The path differs between environments:

- **Docker:** `.dist/` is copied to `/dist/` inside the image; `uv sync --find-links /dist` is passed in the `RUN` instruction.
- **Local dev:** `.dist/` lives at the monorepo root; `uv sync` and `uv run` must be invoked with `--find-links ../.dist` (set in each sub-project's Makefile targets). Note: `UV_FIND_LINKS` is **not** equivalent — it is not read by `uv sync` or `uv lock`; only the `--find-links` CLI flag works for dependency resolution.

Setting `find-links` in `pyproject.toml` bakes one of these paths into the lockfile and breaks the other context. Setting it via `UV_FIND_LINKS` on the command line means the path stays out of version-controlled files entirely.

**Rule:** `pyproject.toml` and `uv.lock` files must never contain `find-links` entries or `[tool.uv.sources]` path references for `market-service`, `provisioning-service`, `arkhai-storefront-client`, or `arkhai-registry-client`. These packages are resolved exclusively from wheels in `.dist/`.

**Why not `uv.sources` editable installs:** Editable path references (`{ path = "../service", editable = true }`) are resolved relative to the project root at lockfile generation time, then embedded in `uv.lock`. Inside Docker the relative path no longer exists, causing resolution failures. The wheel approach avoids this by making both the path and the mechanism context-specific (CLI flag, not lockfile entry).

### Internal wheel packages

Three pure-Python internal packages are distributed as wheels:

| Package | Wheel name | Source | Primary consumers |
|---------|-----------|--------|-------------------|
| `market-service` | `market_service-*.whl` | `service/` | `core`, `integration-tests` |
| `provisioning-service` | `provisioning_service-*.whl` | `provisioning-service/` | `integration-tests`, `service` |
| `arkhai-storefront-client` | `arkhai_storefront_client-*.whl` | `storefront-client/` | `storefront`, `integration-tests`, `provisioning-service` |
| `arkhai-registry-client` | `arkhai_registry_client-*.whl` | `registry-client/` | `integration-tests` |

`arkhai-storefront-client` exists as a separate lightweight package to avoid pulling `market-storefront`'s heavyweight dependencies (`pufferlib`, `torch`, native RL wheels under the `[rl]` extra) into projects that only need the HTTP client and EIP-191 signing helper. The canonical implementation lives in `storefront-client/src/storefront_client/client.py` and exposes `StorefrontClient` (async) and `SyncStorefrontClient` (sync).

**Dependency direction note — provisioning-service → arkhai-storefront-client:**

The provisioning service depends on `arkhai-storefront-client` for two call sites:
1. `lease_lifecycle_service._patch_storefront_resource()` — PATCH storefront resource on lease expiry
2. `system_service.get_status()` — probe storefront reachability for the diagnostic status endpoint

This inverts the conceptual layer (provisioning is infrastructure; storefront is a consumer). It does not create a circular import — `storefront-client` has no dependency on `provisioning-service`. The `make dist` ordering already builds `arkhai-storefront-client` before `provisioning-service`, so wheel resolution is correct.

**TODO:** If the dependency direction becomes a maintenance problem, extract the two call sites into a thin `StorefrontCallbackClient` inside `provisioning-service/src/client/storefront_callback_client.py` that wraps `httpx` directly for just the two endpoints needed (`GET /health`, `PATCH /api/v1/admin/portfolio/resources/{id}`). This keeps `provisioning-service` self-contained without a wheel dependency on the storefront layer.

**`arkhai-storefront-client` versioning policy:**

`arkhai-storefront-client` encodes two contracts with the agent server (`storefront/src/market_storefront/agent.py`) that are not enforced at import time — mismatches produce silent 403s or wrong response shapes at runtime:

1. **Auth message format** — `_build_auth_headers` must match `_check_agent_request_auth` in `agent.py`:
   - `create_order` → `"create_order:<agent_wallet_address>:<timestamp>"`
   - `close_listing` → `"close_order:<listing_id>:<timestamp>"`

2. **Endpoint signatures** — `/listings/create`, `/listings/close`, `/alerts/resource` request/response shapes.

When either contract changes: bump `version` in `storefront-client/pyproject.toml`, update the minimum version constraint in all consuming `pyproject.toml` files, rebuild the wheel with `make dist-storefront-client`, and run `make init` in each consumer. Keep all changes in one commit so the version boundary is auditable in git history. See `storefront-client/README.md` for the full checklist.

### Distribution path

**Internal builds (Docker images):** `.dist/` wheels are consumed via
`--find-links` inside Docker `RUN` instructions. This path is unchanged.

**External distribution:** The three client packages (`arkhai-storefront-client`,
`arkhai-registry-client`, `provisioning-service`) are published to GCP Artifact
Registry via `make push-wheels`. See the `## Artifact Registry Publishing`
section for the full push flow.

**PEP 503 local index (optional):** `scripts/gen_simple_index.py .dist/` generates
a local `simple/` index. Useful if a consumer needs `--index` rather than
`--find-links`. No structural changes to the wheel build are needed.

### Canonical client design pattern

Every service that has HTTP consumers provides two client classes with identical method signatures:

```
FooClient          — async, backed by httpx.AsyncClient
SyncFooClient      — sync,  backed by httpx.Client
```

Both classes:
- **Own their HTTP session internally** — callers never create or pass a session object
- **Accept a `transport=` kwarg at construction** for in-process test injection
- **Raise a typed `FooClientError`** (subclass of `Exception`) on non-2xx responses
- **Return typed model objects** from all methods — no raw dicts exposed

```python
# Production (real network)
client = SyncRegistryClient("http://registry:8080")
agents = client.list_agents(limit=10)

# In-process integration test (no network socket)
client = RegistryClient("http://test", transport=httpx.ASGITransport(app=app))
agents = await client.list_agents(limit=10)
```

**Why httpx, not aiohttp:** `httpx` provides both `AsyncClient` and `Client` with identical interfaces, and crucially supports `ASGITransport` for driving ASGI apps (FastAPI) in-process without a network socket. `aiohttp` has no ASGI transport and requires a `ClientSession` to be passed per-call, which leaks transport concerns into callers.

**No session argument:** Methods do not accept a session. The client owns its session lifecycle. Use the client as a context manager or call `close()` explicitly:

```python
async with RegistryClient("http://registry:8080") as client:
    health = await client.get_health()

# or
client = SyncRegistryClient("http://registry:8080")
try:
    health = client.get_health()
finally:
    client.close()
```

**No module-level wrapper functions:** Functions like `provision_machine_async()` or `schedule_vm_expiry_async()` that wrap client methods are removed. Callers instantiate the client and call methods directly.

**Transport injection for integration tests:** Service integration tests use `FooClient` (async) with `httpx.ASGITransport(app=app)`. The fixture wires `get_db` override and yields the client — tests call methods, never route strings:

```python
@pytest_asyncio.fixture
async def registry_client(db_session):
    app.dependency_overrides[get_db] = lambda: ...
    async with RegistryClient("http://test", transport=httpx.ASGITransport(app=app)) as client:
        yield client
    app.dependency_overrides.clear()

async def test_list_orders(registry_client):
    result = await registry_client.list_orders()   # no route strings
    assert result.orders == []
```

**`SyncFooClient` for smoke tests:** Smoke tests run against real deployed endpoints over a real network socket. They use `SyncFooClient` directly — no shims, no `asyncio.run()`:

```python
client = SyncRegistryClient(base_url=registry_api_url)
health = client.get_health()
```

**Iteration workflow for wheel consumers:** When iterating on a client package during development, use `make reinit` (not `make init`) to force reinstallation and re-resolution to the latest version in `.dist/`:

```
make dist-registry          # rebuild wheel
cd registry-service && make reinit && make test-integration
```

`reinit` runs `uv sync --upgrade-package <pkg> --reinstall-package <pkg>`. The `--upgrade-package` flag is essential: without it, `uv` re-installs whatever version is **pinned in the local `uv.lock`** rather than resolving the latest available wheel from `.dist/`. If `uv.lock` was generated when an older wheel was the only option, subsequent `make dist` runs that produce a higher version are silently ignored by `--reinstall-package` alone. `--upgrade-package` forces uv to re-resolve the constraint against the current contents of `.dist/` and update `uv.lock` to the new version.

### Client package inventory

| Package | Wheel | Async client | Sync client | Consumers |
|---|---|---|---|---|
| `arkhai-storefront-client` | `arkhai_storefront_client-*.whl` | `StorefrontClient` | `SyncStorefrontClient` | `storefront`, `integration-tests` |
| `registry-client/` | `arkhai_registry_client-*.whl` | `RegistryClient` | `SyncRegistryClient` | `integration-tests`, `registry-service` tests |
| `provisioning-service/src/client/` | `provisioning_service-*.whl` | `ProvisioningClient` | `SyncProvisioningClient` | `storefront`, `integration-tests`, `service` shim |

`arkhai-storefront-client` is currently at **version 0.9.0**. The 0.8.0 bump was a breaking rename: `negotiate_new()` and `negotiate_counter()` now take `token` (was `payment_token`) and populate `fields["token"]` to match the on-chain `ERC20EscrowObligation.ObligationData` key. Earlier 0.7.0 bumps added: EIP-191 signing built into `negotiate_new()` on both `StorefrontClient` and `SyncStorefrontClient` (callers no longer build auth headers manually); structured negotiation terms built from scalar helper args; `settle()` method (`POST /api/v1/settle/{uid}`) with EIP-191 auth; `get_settle_status()` method (`GET /api/v1/settle/{uid}/status`) with EIP-191 auth; `evaluate_create_listing()` method (`POST /api/v1/admin/listings/evaluate-create`); `evaluate_negotiate()` method (`POST /api/v1/admin/listings/{id}/evaluate-negotiate`); `EvaluateNegotiateResponse`, `SettleResponse`, `SettleStatusResponse` models.

`provisioning-service` bundles its client inside the service wheel (under `src/client/`) because the request/response models (`CreateVmRequest`, `JobStatusResponse`, etc.) are shared between the server and client. Consumers import as `from client.provisioning_client import ProvisioningClient`.

### Re-export shims

**`integration-tests/src/agent_client.py`:** a compatibility adapter wrapping `SyncStorefrontClient` from the wheel. Preserves the `AgentClient` interface expected by the smoke tests (constructor-level `agent_wallet_address`, `get_registration_file()`, single-arg `create_order()`). The docstring in that file lists the steps to remove it once the smoke tests are updated to call `SyncStorefrontClient` directly.

**`integration-tests/src/registry_client.py`:** re-exports `SyncRegistryClient as RegistryClient` from the canonical wheel. Preserved for the smoke test import path `from src.registry_client import RegistryClient`. A future task can update the smoke test imports and delete this file.

---

## Provisioning Service Planned Rework

This section documents architectural decisions reached for the provisioning service
multi-provider refactor. Items are sequenced and cross-referenced with the
`compute-market-internal-infra` ops repo ARCHITECTURE.md planned work section.

### Background: Resource Pool Architecture

The provisioning service is being extended from a single-provider (Ansible/KVM)
system to a multi-provider, multi-pool system. The driver is GCP deployment: GPU
workloads on GCE cannot use nested VM provisioning (GPU passthrough from L1 GCE VM
to L2 nested VM is not a supported GCP configuration), so a GCP Compute API provider
is needed alongside the existing Ansible provider.

The design uses a `ComputeProvider` abstraction with per-lease pool selection via a
`PoolSelectorService` (label/tag matching analogous to Kubernetes node selectors). This allows a single provisioning service deployment to route leases to different providers and pool types based on the lease's resource requirements.

**Provider types planned:**
- `AnsibleProvider` — existing path, SSH into a KVM host and run `virt-install`.
  Requires pre-provisioned hosts in the `hosts` table.
- `GCPComputeProvider` — new, calls GCP Compute API directly. No pre-provisioned
  hosts required. Teardown via Compute API (independent of VM-internal state).

**Pool types:**
- `kvm_host` — Physical hosts in a data center or VMs acting as KVM hosts, Ansible provider
- `gce_vm` — GCE VMs as direct-access compute, GCP provider (GPU)

### Data Model Changes

**New table: `resource_pools`**
```sql
CREATE TABLE resource_pools (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,  -- 'ansible' | 'gcp'
    pool_type       TEXT NOT NULL,  -- 'kvm_host | 'gce_vm'
	pool_config     TEXT FOREIGN KEY
    label           TEXT,
    policy_tags     JSON,           -- used by node selector service to choose a resource pool
);

CREATE TABLE gcp_pool_configs (
    id           TEXT PRIMARY KEY,
    project      TEXT,
    region       TEXT,
    zone         TEXT,
);
```

**Modified tables (migrations, backwards compatible):**
- `hosts`: add `pool_id TEXT REFERENCES resource_pools(id)`
- `vms`: add `pool_id TEXT REFERENCES resource_pools(id)` (nullable; set at VM
  creation time)
- `jobs`: add `provider_log_ref TEXT` (nullable; for GCP jobs, stores GCE operation
  ID for Cloud Logging cross-reference)
- `leases`: no changes

Initialization pattern for resource_pools and gcp_pool_configs should mirror host inventory seeding (populate on startup from file, admin enabled clobber endpoint for reconcilation). This will require an additional volume mount in the helm chart to support seeding from a file managed in the compute-market-internal-infra repo.

### New Service Classes

**`ComputeProvider` (ABC)** — `create_vm`, `destroy_vm`, `get_capacity`,
`get_status`. All providers implement this interface.

**`AnsibleProvider(ComputeProvider)`** — extracts existing Ansible job runner logic.
Behavior identical to current implementation; this is a rename/extraction, not a
rewrite. Existing tests continue to pass.

**`GCPComputeProvider(ComputeProvider)`** — calls `google-cloud-compute` SDK.
`create_vm` uses Compute API create with data from lease and gcp_pool_config.
`destroy_vm` uses Compute API delete (no SSH required — critical security improvement).
Authenticates via Workload Identity Federation (WIF annotation on provisioning KSA).

**`ResourcePoolService`** — CRUD for resource pools; lookup by ID and tag filter.
JOIN with gcp_pool_config when provider is gcp

**`PoolSelectorService`** — pool selection given a lease request. v1: priority-ordered tag
matching. Designed to extend to scoring (cost, utilization) in a future item.

Design intended to mirror Kubernetes node selectors.

**`ProviderRegistry`** — maps `pool.provider` string to `ComputeProvider` instance.
Constructed in DI container at startup.

### Modified Service Classes

**`LeaseService`** — calls `PoolSelectorService.select_pool(request)` before VM creation,
then dispatches to the selected pool's provider. All existing Ansible calls route
through `AnsibleProvider` unchanged.

**`LeaseWatchdog`** — looks up the lease's pool on expiry, dispatches to the pool's
provider for `destroy_vm`. Replaces hardcoded Ansible teardown dispatch.

**`mockMode` flag** — becomes a `MockProvider` registered in `ProviderRegistry` rather
than a service-level branch. Helm values flag preserved for backwards compatibility.

### New Pool Controller

All gated by existing admin API key auth.

`POST /api/v1/pools` — create a resource pool. Body: pool table fields.

`GET /api/v1/pools` — list pools with tags and host counts.

### GCP Provider e2e Test Scenario

A new e2e scenario (addition to `integration-tests/tests/e2e/`) validates the GCP
provider without mock provisioning:

1. `POST /api/v1/pools` — create a `gce_vm` pool.
2. `POST /system/lease-watchdog/pause` — hold expiry for inspection.
3. Full storefront → negotiate → settle → provisioning flow (reuse existing helpers).
4. Poll `GET /api/v1/jobs/{id}` until GCE VM is running (90-second timeout).
5. Verify SSH credentials returned; attempt SSH to GCE external IP.
6. `POST /system/lease-watchdog/resume` — trigger expiry.
7. Poll until lease `expired`; verify GCE instance deleted via Compute API.

This scenario validates the watchdog pause/resume admin endpoints, that GCPComputeProvider
creates real VMs, and that teardown is Compute-API-based (no SSH key required on the VM).

---

| Term | Meaning |
|---|---|
| Alkahest | Arkhai's smart contract suite for peer-to-peer agreements and escrow |
| ERC-8004 | Ethereum standard for on-chain agent identity (ERC-721-based) |
| Storefront | The seller-side HTTP server (`market-storefront serve`); the only running agent process in the negotiation flow |
| Canonical agent ID | `eip155:{chainId}:{registryAddress}:{tokenId}` |
| FRP | Fast Reverse Proxy — used to give buyers network access to their VMs |
| Anvil | Local EVM testnet node from Foundry |
| EIP-191 | Personal-message signature scheme used to authenticate buyer→seller HTTP request bodies |
| Policy callable | A registered function that evaluates a negotiation event and may return an action |
| Order | A published offer in the registry; carries `offer_resource`, `accepted_escrows`, status. The listing-create API still takes `{offer, demand}` and translates `demand` into `accepted_escrows` at the write boundary — `demand_resource` no longer exists as a stored column. |
