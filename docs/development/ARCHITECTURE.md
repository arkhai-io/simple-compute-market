# Arkhai Market Stack — Architecture Reference

> **Purpose:** This document is intended to initialize AI-assisted development sessions with accurate, up-to-date context about the repository structure, service responsibilities, data flows, and known problem areas. Treat it as a living document — update it as understanding deepens.
>
> **Pending architectural work** lives in [`TODO.md`](TODO.md). This file is for current-state context — what the system is and why it's shaped the way it is — not for tracking todos.

---

## Repository Overview

**Simple Compute Market** is a reference implementation of an agent-driven compute marketplace. Autonomous buyer and seller agents discover each other, negotiate prices, and settle agreements on-chain using Alkahest smart contracts. Physical compute (VMs) is provisioned post-settlement via Ansible.

The stack is designed so that in production, multiple independent seller nodes each run their own agent + provisioning stack, while buyers can be ephemeral (a CLI invocation or a long-running agent). The `test-env` component exists only for local development.

---

## Organizing Principle: composition from above and below

The README frames this as a market for "anything"; the structural test that makes that framing real is:

> **A behavior belongs in the market core (composed "from above") if and only if it is invariant across every possible listing schema. If it varies by schema, it is a utility composed "from below" that the core invokes through an injected hook** — and "requiring the hook" is the from-above part; "implementing it" is from-below.

- **From above** — the role contracts (buyer, seller, indexer) and the three market processes (discovery, negotiation/aggregation, settlement), expressed purely in terms of injected dependencies and schema-opaque primitives. `core_buyer.run_buy(...)` is already this shape: a linear discover→negotiate→settle flow with high-level `negotiate` and `settle` hooks. The current compute instantiation still adapts legacy finer-grained hooks (`build_escrow_proposal`, `build_escrow_terms`, `create_escrow`, …) into that surface.
- **From below** — concrete, mutually-independent utilities: negotiation middlewares (`arkhai-kit-policy`), identity schemes (`arkhai-kit-identity`), generic schemas (`arkhai-core`), settlement kits (`arkhai-kit-alkahest`), shared config (`arkhai-kit-config`), infra clients (chain, registry-client). The defining property is "depended on, never depending up into the skeleton" — not "packaged as one wheel."
- **A market instantiation** for a given asset class / listing schema wires from-below implementations into the from-above hooks, and *uses* the from-below utilities inside those implementations.

Negotiation is an exchange of **messages** — opaque, schema-defined units passed between participants. The invariant the core rests on is that settlement composes with negotiation:

```
terms   = negotiate(messages…)
receipt = settle(terms)
```

Negotiation reduces a message history to a `Terms` value; settlement consumes that `Terms` to produce a `Receipt`. That is the whole of what the core knows about the exchange:

1. messages flow between participants (opaque content);
2. a negotiation terminates by reducing its history to `Terms`;
3. `settle(Terms) → Receipt`;
4. settlement runs and reports success or failure.

Everything else is schema-defined: message content (offer, counter, bid, acceptance are schema vocabulary), how a participant chooses its next message, and how `Terms` are validated. Seller-advertised fields (`accepted_escrows`, `min_price`, `max_duration_seconds`, …) are listing data; a policy decides whether to read them as a whitelist, a floor, a ceiling, or a soft predicate, and whether a mismatched message draws a rejection, a counter, a correction, or an acceptance. Every dimension of a message — price, escrow shape, duration — is handled the same way: by the negotiation chain, against the advertised data.

Settlement verification requires both sides to derive the same `Terms`. That holds because `negotiate` is a pure reduction over a shared message history; the seller echoes the canonical confirmed message (the `accepted_*` fields on the wire response) so both histories stay identical.

### What the core owns vs what schemas supply

The core owns the *structure* of the exchange: the round loop, the signed request/response transport, history persistence, the middleware-chain execution semantics (a middleware that returns a value terminates the chain; returning none passes context to the next), and the determinism contract above. Schemas supply a small number of hooks within that structure.

The composition wants two behavior hooks. `run_buy` now exposes only that
surface. The previous fine-grained compute hooks are kept as adapter
factories outside the core orchestration call:

- **`negotiate`** — a per-turn message policy, `respond(history) → message | terms`, run by the core's negotiation engine. Today's `chain`, `derive_prices`, opening-message construction (`build_escrow_proposal`), and the buyer's commit (`confirm_settlement`) all belong here: each is a decision a participant makes during its turn.
- **`settle`** — `Terms → Receipt`. Today's `build_escrow_terms` + `create_escrow` are one hook — "materialize the on-chain shape, then submit it" is internal factoring.

On the seller side, `start_sync_negotiation` and
`continue_sync_negotiation` own the signed HTTP protocol, thread
persistence, and stage events. They delegate each policy decision to an
injectable seller round hook. The hook contract carries only protocol-visible
inputs (`listing`, message `history`, requested duration, and optional
strategy label); the implementation decides what extra side inputs or private
state it needs. The default compute hook captures the storefront DB adapter
behind the callable, takes an available-inventory snapshot for the compute
inventory guard, then runs the configured middleware chain to produce a
`NegotiationDecision`. The generic negotiation tables store only the protocol
transcript, terminal state, and agreed terms.

Two hooks merge when the core does nothing between them: `build_escrow_terms → create_escrow` is a pure sequence. They stay separate when a core-enforced boundary sits in the gap — the determinism contract between `negotiate` and `settle` is such a boundary, so those remain two phases with `Terms` as the typed handoff. Hooks need not be interchangeable across schemas to warrant separation; a schema's `negotiate` and `settle` are co-designed and don't cross-compose. The core's leverage is the structure it provides around the hooks, not the count of hooks.

The structure baked into the core is the structure shared by every market shape currently in view — request/response rounds driven by a middleware chain. A negotiation of a different shape (a sealed-bid auction, a continuous order book, an oracle-priced take-it-or-leave-it) would motivate factoring the round engine into a swappable protocol layer beneath the `settle ∘ negotiate` composition; until such a market is concrete, the round/chain model is part of the core.

### The registry is the schema-centralizing point

The indexer registry plays the platform role of existing compute markets: it is where a listing schema is *declared* (on the wire via `filter-spec.yaml`) and centralized. A registry typically serves a single schema, and the realistic first driver of the core/instantiation split is not a different asset class but **heterogeneous listing schemas within "compute"** that don't make sense on the same registry. Under this model a per-schema instantiation is the *registry operator's* deliverable: the core ships the from-above skeleton + the from-below kit; an operator stands up a registry and publishes a schema (its `filter-spec.yaml` plus the typed client counterpart, versioned together) and the storefront/buyer plugins that wire kit implementations into core hooks. The registry is already the most complete instance of this — it stores `offer_resource` as an opaque blob and drives discovery off a swappable filter-spec, with zero schema-specific code.

### Package layout (the principle, implemented)

The core/kit/domain extraction is complete; the package graph expresses
the principle, and distribution names mirror it
(`arkhai-{core,kit,vms}-*`; the `arkhai-` prefix drops once publishing
moves under the organization's PyPI scope). Import names and console
scripts (`market`, `market-storefront`, `market-policy`) are unchanged.

| Layer | Distribution (path) | Role |
|---|---|---|
| core | `arkhai-core` (`core/`) | protocol-carrier wheel: negotiation/settlement wire shapes both roles must derive identically. Stdlib + pydantic only. |
| core | `arkhai-core-buyer` (`core/buyer/`) | buyer role shell: `market` console script, verb skeleton, `market.buyer_plugins` entry-point discovery, `run_buy` orchestration, registry fan-in |
| core | `arkhai-core-storefront` (`core/storefront/`) | storefront role shell (library, framework-free): sync-negotiation protocol, registry publication, stage log, auth, HTTP models, capacity-client contract |
| core | `arkhai-core-registry` (`core/registry/`) | registry service; schema injected as `filter-spec.yaml` config |
| core | `arkhai-core-registry-client`, `arkhai-core-storefront-client` | protocol clients |
| kit | `arkhai-kit-identity`, `arkhai-kit-policy`, `arkhai-kit-alkahest`, `arkhai-kit-config` | from-below capabilities; alkahest is the first *settlement-mechanism codec* |
| domain | `arkhai-vms-buyer` (`domains/vms/buyer/`) | no console script — publishes the `vms.compute` plugin the core `market` CLI discovers |
| domain | `arkhai-vms-storefront` (`domains/vms/storefront/`) | the VM storefront executable/composition root (FastAPI adapters over core) |
| domain | `arkhai-vms-provisioning` (`domains/vms/provisioning/service/`) | the VM fulfillment executor service |

The VM *concept* modules (`domains/vms/{listings,negotiation,settlement,provisioning}`)
are not separate wheels: they ship inside the buyer/storefront wheels
and implement core hook shapes by injection, without importing core.

Executable ownership splits by role: the buyer binary is core-owned
with domain schema plugins (one binary, many registry schemas; without
plugins it degrades to generic `--filter` browsing, never a concrete
market); storefront executables are domain-owned, one process per
market schema domain (multi-domain operators run parallel processes
sharing the capacity layer underneath); the registry is core + schema
config.

Three rules are mechanically enforced, not just documented:
kit and concept modules import no core/composition packages
(`domains/vms/storefront/tests/unit/test_architecture_imports.py`);
`market_core` imports nothing beyond stdlib + pydantic
(`core/tests/unit/test_carrier_purity.py`); core never imports
`domains.*` (plugin inversion on the buyer, injected hooks on the
storefront).

Remaining divergences are aggregated in [`TODO.md`](TODO.md) → "Core
Stack"; the two design records are
[`design-market-core-extraction.md`](design-market-core-extraction.md)
(decisions behind the split) and
[`design-settlement-lifecycle-and-capacity.md`](design-settlement-lifecycle-and-capacity.md)
(the follow-on behavior work: settlement lifecycles, mechanism-neutral
plan carrier, site authority).

### Technology Anchors

| Concern | Technology |
|---|---|
| On-chain settlement / escrow | [Alkahest](https://github.com/arkhai-io/alkahest) contracts |
| Seller identity | Pluggable scheme registry (EIP-191 wallet by default; see `arkhai-kit-identity`) |
| Buyer ↔ seller protocol | Plain HTTP request/response, EIP-191-signed bodies |
| Seller server framework | FastAPI / Starlette + uvicorn |
| Buyer | Pure HTTP client — `market` CLI, no server |
| VM automation | Ansible (via `domains/vms/provisioning/iac`) |
| Job queue | In-process `asyncio.Queue` (no external queue dependency) |
| Overlay networking (optional) | ZeroTier |
| Local dev chain | Anvil (Foundry) |

---

## Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EVM Chain (Alkahest)                         │
│   Alkahest escrow obligation + arbiter contracts                    │
└──────────────────┬──────────────────────┬───────────────────────────┘
                   │ events / txns         │ events / txns
         ┌─────────▼──────────┐   ┌───────▼─────────────────┐
         │  arkhai-core-registry  │   │  storefront             │
         │  :8080             │   │  :8001 (seller only)    │
         │  FastAPI indexer   │◄──┤  FastAPI                │
         │  SQLite/Postgres   │   │  market-storefront serve│
         └─────────▲──────────┘   └────────────┬────────────┘
                   │  GET /listings            │ HTTP (provisioning API)
                   │  signed reqs    ┌─────────▼───────────────┐
                   │                 │ arkhai-vms-provisioning    │
         ┌─────────┴──────────┐      │   API  :8081  (FastAPI) │
         │  buyer (`market`)  ├─────▶│   Job loop (in-process) │
         │  pure HTTP client  │ HTTP └────────┬────────────────┘
         │  no server         │ buyer→seller  │ asyncio.Queue
         │  signed bodies     │      ┌────────▼────────────────┐
         └────────────────────┘      │  Ansible playbooks      │
                                     │  (compute-provisioning- │
                                     │   iac tree)        │
                                     └─────────────────────────┘

 ┌──────────────┐   ┌────────────────────────────────────────┐
 │  test-env    │   │  Participant CLIs                       │
 │  Anvil node  │   │   market           — buyer runtime     │
 │  (dev only)  │   │   market-storefront — seller runtime   │
 └──────────────┘   │   market-policy    — train/eval/export    │
                    └────────────────────────────────────────┘
```

Negotiation flow: the buyer's `market buy`/`market negotiate`
discovers seller orders from `arkhai-core-registry`, then issues
synchronous signed POSTs against the seller's storefront
(`/negotiate`, `/listings/...`, `/settle/{escrow_uid}`). The seller's
storefront runs the request through a per-round middleware chain
(configured in `[negotiation] policies`), decides counter/accept/exit, and
returns the next round inline. There are no push messages and no
symmetric agent-to-agent protocol — the buyer drives every round.

---

## Component Summaries

### `test-env`

**Role:** Local development chain fixture.

An Anvil (Foundry) instance with Alkahest contracts pre-deployed and chain state saved to `test-env/state/state.json`. The Dockerfile loads this snapshot at startup, giving a deterministic chain for every dev session. Restarting the container resets chain state.

In production this component is absent — the agent and registry configs point to a live RPC endpoint (e.g., Base Sepolia or mainnet).

**Key facts:**
- Default port: `8545`
- State is generated by the root `build-anvil-state` Makefile target, which runs `test-env/generate_state.py` — it spins up alkahest's `EnvTestManager`, funds the test wallets, and writes the `anvil_dumpState` snapshot to `test-env/state/state.json`
- The same script writes the deployed Alkahest contract addresses to `domains/vms/storefront/.../data/alkahest_anvil_addresses.json`, which the seller container ships and the buyer reads

---

### `arkhai-core-registry`

**Role:** Listings registry — discovery surface for the marketplace.

FastAPI service that stores published listings and serves them through a filter-spec-driven `GET /listings` query API. Sellers publish via signed `POST /listings` (the publishing identity + signature ride in the body); buyers fetch via the discovery query. A listing is owned by a **publisher** — a principal identified by one or more signing `(scheme, identifier)` identities (today a single `eip191` wallet). Publisher + identity rows are created lazily on first signed publication — the signature is the trust anchor, so no chain-walk is needed. Listings carry `storefront_url` (where a buyer negotiates), joined from the owning publisher.

**Ports:** `8080` (default)

**Databases:**
- Dev: SQLite (`registry.db`)
- Prod: PostgreSQL

**Key APIs:**
- `POST /listings` — publish/update a listing (signed body: publishing identity + signature). Lazily creates the publisher.
- `GET /listings` — global order book query; query params are **spec-driven** (resolved against `filter-spec.yaml` — see below), not a hardcoded signature. `?publisher=<identifier>` narrows to one publisher.
- `GET /listings/{listing_id}` — single listing
- `PUT /listings/{listing_id}` / `DELETE /listings/{listing_id}` — update/remove; signature verified against the listing's publisher identity (owner-scoped)
- `GET /publishers` — list publishers; `?identifier=` resolves a publisher by a signing identity
- `GET /publishers/{publisher_id}` — the publisher entity: `storefront_url`, `identities`, `created_at`
- `POST /api/v1/listings/validate-publish` — JSON Schema dry-run check of a publish candidate against `filter-spec.yaml`'s `listing_shape` (Draft 2020-12); used by the buyer/seller pre-publish path
- `GET /api/v1/filter-spec` — current filter spec; ETag-tagged for client caching

**Indexer-maintained schema — registry owns the filter vocabulary:**

The filter vocabulary is registry-maintained, schema-driven, and
self-describing via `filter-spec.yaml`. Adding a new discovery filter is a
YAML edit, not a route signature change in the registry, and not a code
change in the storefront or any client wheel.

What the spec carries:

- `listing_shape` — JSON Schema for what a valid publish candidate looks like
  (offer-side resource axes, escrow shape requirements, required fields).
  This is what `validate-publish` runs Draft 2020-12 against.
- `filters` — declarative list of supported `GET /listings` query parameters.
  Each declaration names the parameter, the JSONPath it resolves against on
  listing dicts, the operator (`equals`, `in`, `lower_bound`, `upper_bound`,
  `contains`, …), and an optional `on_missing` policy.
- Enums like `gpu_model` (Blackwell back to Volta + workstation + consumer
  cards) live here. The storefront treats hardware fields as plain `str`;
  the registry is the single enforcement point so sellers can list any
  hardware string but discovery is gated centrally.

Filter evaluation lives in `core/registry/src/api/filter_eval.py`:
`build_criteria(spec, params)` compiles the spec + request params into
parsed JSONPath criteria; `evaluate_all(criteria, listing)` returns the
matching listings. Array-projection paths (`accepted_escrows[*]...`) are
supported via jsonpath-ng. The storefront's `GET /api/v1/listings` is a
slim local-enumeration view (`status`, `paused`, `limit`, `offset`) —
discovery goes through the registry; the storefront is the seller's local
state surface. `arkhai-core-registry-client.list_listings()` and the
storefront-client equivalent take a filter param dict that the caller
composes from the active spec.

**ETag protocol for spec-vs-query consistency:** `GET /filter-spec` returns
an `ETag` header that's a sha256 over the canonical JSON of the loaded YAML.
Buyers cache the spec by URL+ETag and pass `If-Match: <etag>` on
`GET /listings`. On ETag mismatch the registry returns **412 Precondition
Failed** rather than silently honouring a query built against a stale spec.
`If-Match` is optional — clients that don't care about spec drift can omit
it.

**Where the YAML lives and how it ships:** `core/registry/filter-spec.yaml`
in source, copied into both build stages of the registry Docker image.
Loaded once at import via `lru_cache`; path overridable via
`REGISTRY_FILTER_SPEC_PATH` env var. To rotate the spec without rebuilding
the image, mount the new YAML over the baked one and restart the registry;
buyers detect the change via the ETag on the next `/filter-spec` fetch.

**Publisher identity format:** scheme-tagged `(scheme, identifier)` pairs.
The default and only built-in scheme is `eip191`, whose identifier is
the lowercase 0x hex wallet address. A publisher may hold more than one
identity (the seam for cross-chain/cross-scheme linking); today it holds
one. Listings are published via signed `POST /listings` and the registry
creates the publisher + identity rows lazily on first publication. Custom
schemes register via `market_identity.register_identity_scheme(verifier)`.

**Source layout:**
```
core/registry/src/
├── api/             # FastAPI routes (publisher_routes, listing_routes, system_routes)
├── db/              # SQLAlchemy models (publishers, identities, listings, api_keys) + Alembic migrations
├── types/
└── main.py
```


---

### `storefront` (Seller-side server)

**Role:** The seller's HTTP server. Hosts the `/listings/...`,
`/negotiate`, `/settle/{escrow_uid}`, `/alerts/resource`, and
`.well-known/agent-wallet.json` endpoints that buyers and the
provisioning service call. Runs as `market-storefront serve` (uvicorn,
FastAPI/Starlette). Internally it uses Alkahest for on-chain escrow
operations.

**Ports:** `8001` (default seller port; `port` in storefront.toml).

**Startup sequence:** `entrypoint.sh` starts the ZeroTier daemon,
then `exec market-storefront serve`. The lifespan hook joins the
configured ZeroTier network if any, initializes the negotiation
thread store, seeds resources from CSV if the table is empty, probes
the configured alkahest contract addresses on each chain, starts the
negotiation watchdog, and preflights the provisioning service.

Identity is the wallet address (`settings.wallet.address`) — no
on-chain registration step and nothing to register ahead of time. The
storefront becomes known to a registry the first time it publishes a
listing (the registry creates its publisher row lazily).

**Compute inventory and dynamic listings:**

For compute resources, the storefront owns the market-facing inventory
projection and allocation ledger. The provisioning service owns execution
facts about VMs and leases; it does not decide what should be advertised
to buyers.

The storefront stores concrete imported resources in `resources`. Those
rows are grouped into `compute_inventory_pools`, with
`compute_pool_members` linking each concrete `resource_id` to a pool.
Existing resources are backfilled into one-member pools. Multiple rows
can opt into fungible capacity by sharing `attribute.pool_id` in the CSV
or import payload; listings can then represent capacity across equivalent
machines without exposing which machine will satisfy the lease.

`derived_compute_listings` records generated listing identity for each
advertised GPU slice. Single-resource pools keep the legacy
`resource_id:gpus:N` listing key for compatibility; fungible pools use
`pool:{pool_id}:gpus:{N}`. Reconciliation closes and reopens derived
listings from pool/member feasibility, not just aggregate capacity: a
slice is advertised only when at least one remaining member can satisfy
that slice after current holds are subtracted.

`compute_allocations` is the storefront-side capacity ledger. It records
the market correlation (`listing_id`, `order_id`, `negotiation_id`,
`escrow_uid`), selected capacity (`pool_id`, `member_id`, concrete
`resource_id`, GPU count), and fulfillment callback metadata. A
negotiated offer may pin either a concrete `resource_id` or a fungible
`pool_id`; reservation resolves fungible pool terms to a concrete member
at allocation time.

Execution lifecycle facts come back through admin-boundary fulfillment
callbacks: `/api/v1/admin/fulfillment/events/started`,
`/usage-started`, `/release-started`, `/capacity-released`, and
`/failed`. Those callbacks advance `compute_allocations`; the reconciler
then updates dynamic listings from the allocation ledger.

**Key source layout:**
```
domains/vms/storefront/src/market_storefront/
├── cli.py                  # `market-storefront` console-script entry
├── server.py               # FastAPI app, lifespan, run_serve()
├── container.py            # Resolved service singletons (populated in lifespan)
├── startup.py              # Startup-task helpers:
│                           #   _startup_tasks, _preflight_provisioning,
│                           #   _probe_chain_addresses, _maybe_join_zerotier_network
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
│   ├── domain_models.py      # Domain types: ComputeResource, Listing, ProvisionTerms, …
│   ├── listing_models.py     # HTTP shapes: ListingFilterParams, CreateListingRequest, …
│   ├── negotiation_models.py # HTTP shapes: NegotiateNewRequest, ForceAcceptRequest, …
│   ├── settle_models.py      # HTTP shapes: SettleRequest, SettleStatusResponse
│   └── system_models.py      # HTTP shapes: HealthResponse, SystemStatusResponse, …
├── services/
│   ├── listing_service.py         # ListingService: create/close/refund/claim/reclaim/…
│   ├── alkahest_service.py        # build_client(): AlkahestClient factory
│   ├── negotiation_service.py     # NegotiationService: advance/force-accept/list/get
│   ├── publication_service.py     # Registry publication/close orchestration
│   ├── fulfillment_service.py     # VM fulfillment orchestration for settled escrows
│   └── system_service.py          # SystemService: health/seed/evaluate + registry checks
├── groups/                 # CLI groups: config, escrow, network
├── cli_publish.py, cli_portfolio.py, cli_logs.py, cli_common.py
├── negotiation_watchdog.py
├── utils/
│   ├── config.py, sqlite_client.py
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
│  │ controller  │ │  controller  │ │  controller  │ │ controller │ │
│  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └─────┬──────┘ │
│         │               │                │               │        │
│  ┌──────▼───────────────▼────────────────▼───────────────▼──────┐ │
│  │                   SQLiteClient                                │ │
│  │  listings · negotiation_threads · negotiation_messages        │ │
│  │  stage_events · policy_config · resources                     │ │
│  │  compute_inventory_pools · compute_pool_members               │ │
│  │  derived_compute_listings · compute_allocations               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              sync_negotiation.py  (request-scoped)            │ │
│  │                                                               │ │
│  │  start_sync_negotiation()   continue_sync_negotiation()       │ │
│  │         │                            │                        │ │
│  │         └──────────┬─────────────────┘                        │ │
│  │                    ▼                                           │ │
│  │         _load_storefront_chain()                              │ │
│  │              │                                                │ │
│  │    ┌─────────┴──────────────────────────┐                    │ │
│  │    │  run_negotiation_chain(history,ctx)│                    │ │
│  │    │   ◦ has_matching_inventory_guard   │                    │ │
│  │    │   ◦ escrow_shape_guard             │                    │ │
│  │    │   ◦ max_rounds_guard               │                    │ │
│  │    │   ◦ bisection (or rl) ← terminal   │                    │ │
│  │    └─────────┬──────────────────────────┘                    │ │
│  │              ▼                                                 │ │
│  │    NegotiationDecision {action, price, reason}                │ │
│  │              │                                                │ │
│  │    stage_event("negotiation","round_decided",                  │ │
│  │               decision, decision_reason)  ──► stage_events DB │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  Background tasks                                                   │
│  ┌─────────────────────┐                                           │
│  │ negotiation_watchdog│                                           │
│  └─────────────────────┘                                           │
│                                                                     │
│  Compute allocation/listing lifecycle owned by storefront pools,    │
│  allocations, and fulfillment callbacks from provisioning           │
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
`(chain_name, escrow_address)` tuple plus `literal_fields: dict` (the
obligation-data keys the seller has fixed: `token`, `arbiter`, etc.) and
`rates: list[RateValue]` (every rate-bearing obligation field with its
`per` unit and rate `value` in base units). The seller is saying "I will
accept payment via *these* escrow contracts on *these* chains, with
*these* field values pinned, at *these* rates." Multiple entries allow
multi-chain or multi-contract offers (mainnet ERC20 + a Base Sepolia
ERC20 alongside a hypothetical ERC721 escrow).

`literal_fields` is **shape-only** — present keys are advertised values;
absent keys are open for the buyer to propose. Whether an advertised
value is a hard constraint or a negotiable default is the seller's
negotiation policy's concern, not protocol infrastructure. A rate-bearing
field (e.g. `amount` for ERC20) is never in `literal_fields` — it lives
in `rates` so duration scaling stays explicit. The on-chain
`ObligationData.amount` is derived at settlement as
`primary_rate × duration_seconds / 3600` after the negotiation agrees a
rate and duration. Empty `rates` = hidden reserve (the seller publishes
no advertised rate; negotiation establishes one via the strategy's
`default_min_price`).

Readers use `primary_rate_value` for the generic headline rate.
Token-shaped flows may additionally use `accepted_token_address`, but
that helper is not universal: native-token, attestation, and some bundle
escrows have no top-level `literal_fields.token`.

**Round-0 wire shape:** `POST /api/v1/negotiate/new` carries two structured
fields:

- `provision_terms: ProvisionTerms` — `{kind, payload}`. What the seller
  will deliver off-chain. The core treats `payload` as opaque; the current
  compute adapter interprets `kind="compute.v1"` as
  `{duration_seconds, ssh_public_key, compute_resource?}` and the seller's
  settlement/provisioning pipeline reads those compute fields as the single
  source of truth for what to provision.
- `escrow_proposal: EscrowProposal` — `{chain_name, escrow_address, fields,
  literal_fields, rates, expiration_unix}`. The buyer picks one of the
  listing's `accepted_escrows` by `(chain_name, escrow_address)` and supplies
  its literal pins in `literal_fields` (e.g. `{"token": …}`). The proposal
  retains a `fields` dict as the carrier for the per-round negotiation
  amount (`fields["amount"]`) — rate-bearing values negotiate as a single
  absolute scalar once the duration is fixed at round 0. `amount` is
  intentionally **not** on the listing-side advertisement: it's derived at
  settlement from `primary_rate × duration / 3600`.

The default seller policy validates escrow shape inside the negotiation
chain. `escrow_shape_guard` matches the buyer's
`(chain_name, escrow_address)` against the listing's `accepted_escrows` and
rejects both out-of-set proposals and literal-field mismatches. The protocol
layer's `_validate_escrow_proposal` only canonicalizes non-rejected
proposals by merging matched listing `literal_fields` and `rates`; it does
not decide whether an out-of-set proposal is rejected, corrected, or
allowed. On non-rejection paths, `NegotiateNewResponse` echoes both as
`accepted_provision_terms` and `accepted_escrow_proposal`, and accept paths
additionally echo `accepted_escrow_terms`: concrete `EscrowTerms`
materialized from the final proposal, agreed amount, duration, and arbiter
demands. Split settlement flows consume those concrete terms directly and
fall back to proposal materialization only for older run logs.

**Settlement is a byte-compare, not a dispatch:** `EscrowTerms`
(`market_core.schemas.EscrowTerms`) is the settlement artifact — a flat mirror
of the alkahest `ObligationData` struct:
`{maker, chain_name, escrow_contract, obligation_data, expiration_unix}`.
The settlement verifier reads the on-chain obligation by UID and
byte-compares against materialized `EscrowTerms.obligation_data`. Adding a
new escrow kind is primarily a codec-registration change: all tierable
and non-tierable Alkahest escrow obligation variants under
`contracts/src/obligations/escrow` are registered, and the buyer submit
hook resolves each term's `(chain_name, escrow_contract)` to a codec via
`market_alkahest.alkahest.get_escrow_kind_codec_by_address`. The
proposal-to-terms materializer owns the final obligation data shape.
Codec-boundary tests cover every registered kind; compose-backed
settlement e2e coverage currently exercises native-token and ERC1155
escrows through buyer, storefront, and provisioning.

A negotiation accept produces `list[EscrowTerms]` so multi-escrow designs
(payment + seller penalty deposit, block-by-block schedules) are expressible
without a wrapper type. Today every list is length-1 (single buyer-made
escrow); the rest is forward shape.

`CreateListingRequest` requires `accepted_escrows: list[dict]`.
`ListingService.create_listing` validates the body, writes the listing
row via `sqlite_client.upsert_listing`, then (unless `paused=True`)
publishes to the configured registries. Close is the symmetric
procedural path: SQLite update → registry unpublish. No policy step
gates either operation. `domains.vms.listings.pricing.extract_initial_price_from_order`
reads the primary rate via `primary_rate_value(accepted_escrows[0])`; its
storefront binding supplies `[seller.pricing].default_min_price` as the
hidden-reserve fallback for empty `rates`.

**Escrow templates (CSV → `accepted_escrows`):** sellers populate
`accepted_escrows` per-resource via the templates DSL in the resource CSV:
`escrow_templates.<name>` blocks in `storefront.toml` declare the
`(chain, escrow_address, literal_fields, rate_slots)` shape; the CSV
references templates by name with per-slot rate values
(`"usdc_anvil:amount=150; eth_pool:eth=0.001"`, or the single-slot sugar
`"usdc_anvil=150"`). The importer materializes one `accepted_escrows`
entry per template at import time; `cli_publish._publish_round` scales
token-backed rate values by the token's decimals before publishing.
Non-token templates use their declared base units directly. The legacy
"broadcast min_price across every CHAINS entry" path remains as the
fallback for rows without a templates cell.

---

**Procedural request path + three pluggable policy hooks:**

The storefront is a request/response service over negotiation state,
market-facing inventory, and the allocation ledger. Listing
create/close/refund/claim/reclaim calls are procedural
`ListingService` operations. Compute lease execution is not stored as a
listing state; settlement reserves a `compute_allocations` row, the
provisioning service reports lifecycle facts through fulfillment
callbacks, and the dynamic listing reconciler opens/closes registry
listings from the resulting pool availability. The three places where
policy plugs in are:

- **Buyer-side aggregation** (buyer-only) — `aggregate(negotiate, listings)`
  in `domains/vms/buyer/aggregation.py` owns the iteration shape across
  listing candidates. Built-ins: `best_price`, `cheapest_first`,
  `registry_order`. Custom strategies plug in via entry-point or file
  discovery.
- **Seller-side per-round negotiation policies** (seller-only) — an
  ordered list of middlewares with signature
  `(history, context) -> (Maybe<Response>, Context)`. Guards short-
  circuit with `reject`/`exit` when their preconditions fail; the
  terminal policy (`bisection` or `rl`) always returns
  `counter`/`accept`/`exit`. Configured per-storefront in
  `[negotiation] policies = [...]` in `storefront.toml`.
- **Storefront fulfillment failure policy** (seller-only) — a configured
  ordered action list behind provisioning failure and
  `/api/v1/admin/fulfillment/events/failed`. Built-ins are
  `release_capacity`, `emit_event`, `webhook`, and `refund`; the default
  repairs capacity/listings and emits a stage event. The `refund` action
  is the seller-side "send already-claimed assets back" path; token escrows
  dispatch through the selected escrow codec. Rows without a stored escrow
  proposal are skipped rather than deriving refund details from listing
  defaults. Buyer-side `reclaim_expired` is a separate post-expiry escape hatch
  and is not a seller refund.

The negotiation hooks live in `arkhai-kit-policy` (package: `kit/policy/`, import:
`market_policy`); the buyer and seller import from the same wheel. The
negotiation data model is symmetric — `NegotiationRound`,
`NegotiationContext`, `NegotiationDecision` are shared. Each side
instantiates its own chain. The fulfillment failure policy lives in the
storefront because it operates on seller inventory, settlement records,
refunds, and operator alerting.

**Built-in negotiation middlewares:**

- `has_matching_inventory_guard` — round 0 only; the seller's storefront
  projection must contain matching compute capacity for the listing's
  `offer_resource` attributes. The offer may pin a concrete
  `resource_id` or a fungible `pool_id`; otherwise the guard checks the
  imported portfolio. Rejects with `no_matching_inventory` if not.
- `escrow_shape_guard` — the buyer's real `(chain_name, escrow_address)`
  must select one listing `accepted_escrows` entry, and every key on that
  entry's `literal_fields` must equal the buyer's value in
  `escrow_proposal.literal_fields`. Rejects with
  `escrow_not_in_accepted_set` or `escrow_field_mismatch` otherwise.
- `max_rounds_guard` — exits with `max_rounds_reached` once
  `len(history) >= [negotiation].max_rounds` (default 5).
- `bisection_middleware` — terminal. Bisects between `our_price` (the
  listing's primary rate) and `their_price` (the peer's latest offer);
  accepts within ~1% convergence, counters at midpoint when feasible,
  exits with `price_unreasonable` when `their_price < our_price / 1.5`
  (maximize) or symmetrically (minimize).
- `rl_middleware` — terminal (optional). Lazy-imports torch + the
  pufferlib checkpoint at
  `domains/vms/negotiation/rl/models/arkhai_negotiator_seller.pt`
  (or `_buyer.pt`). Exits with `torch_unavailable` if torch isn't
  installed.

**Chain runner:** `run_negotiation_chain(chain, history, context)` in
`kit/policy/src/market_policy/negotiation_middleware.py`. Loops middlewares in order;
returns the first `Some<Response>`; raises if the chain exhausts (the
terminal middleware must always return `Some`).

**Negotiation direction:** determined by
`domains.vms.listings.strategy.determine_strategy_from_resources()`.
Listings carry an `offer_resource`; the payment side lives in
`accepted_escrows`. Seller offering `ComputeResource` → direction
`"maximize"` (highest price the buyer will pay). The buyer's CLI runs in
`"minimize"` from the other side.

**Policy loader:** `_load_storefront_chain()` in `sync_negotiation.py`
reads `[negotiation] policies` from `storefront.toml`. If it is a list,
the names are resolved via `load_negotiation_chain()`. If it is a
`[negotiation.policies]` table, the storefront keeps the default seller
guards and adds an escrow-kind dispatcher that maps the selected
proposal's Alkahest escrow kind to a configured terminal/chain. Back-
compat: if `policies` is absent and the legacy `policy_mode` is set,
synthesize `["has_matching_inventory_guard", "escrow_shape_guard",
policy_mode]`. Custom middlewares are picked up by file discovery via
`[negotiation] extra_policy_paths = [...]`. See
[docs/configuration.md](../configuration.md) for the full reference
including built-in policies, the buyer's aggregation policy, and how
to write a custom one.

**`our_price` source:** the terminal middleware reads it via
`domains.vms.listings.pricing.extract_initial_price_from_order()`, with
the storefront passing its configured default minimum price for hidden
reserve listings. This calls `primary_rate_value(accepted_escrows[0])`.
It is the seller's price floor — the buyer's opening offer must be at or
above this value for the seller to counter rather than exit immediately.

**`checks.negotiation_strategy` in system status:** `GET /api/v1/system/status`
includes a `negotiation_strategy` check that instantiates the configured
chain and runs a synthetic maximize probe. If the terminal middleware
would exit on the probe (e.g. `"rl (exit_on_probe: torch_unavailable)"`),
the check surfaces this before any negotiation is attempted. The smoke
test (`test_negotiation_strategy_viable`) and e2e stage 00d both assert
on this field.

**`checks` degraded-status evaluation:** Each check value is evaluated
by `_check_is_healthy(key, value)` in `system_service.py` rather than
against a fixed set of `"ok"` literals. This is because
`negotiation_strategy` returns a human-readable name (e.g. `"bisection"`)
on success rather than the literal `"ok"`. The `_check_is_healthy`
function treats the `negotiation_strategy` key specially: healthy unless
the value contains `"exit_on_probe"` or starts with `"unknown:"` /
`"error:"`. All other check keys use the literal set `{"ok",
"unconfigured", "agent_not_found", "indexing"}`. When adding a new check
to `get_status()` whose success value is not `"ok"`, either: (a) return
`"ok"` on success and put the diagnostic name in a separate top-level
fact field, or (b) add a key-specific rule to `_check_is_healthy`.

**`domains/` tree — not installed, on sys.path:** holds the RL training
+ inference code that's outside the procedural runtime — specifically
`domains/vms/negotiation/rl/torch_arkhai_strategy.py` (loads the
pufferlib checkpoint at inference time, called by `rl_middleware`) and
`domains/vms/training/` (the standalone train + eval CLIs). The tree
is not a pip-installable package — it's copied into the Docker image at
`/app/domains/` and requires `/app` on `sys.path` (Dockerfile sets
`ENV PYTHONPATH="/app"`). `arkhai_common` requires `gymnasium`;
importing it without the ML extra installed fails — that's expected and
the `rl_middleware` exit-on-probe path surfaces it cleanly.

**Local state — SQLite:** the storefront maintains a SQLite database
(`seller.db_path`) containing policy configuration, order history,
negotiation threads, and the resource portfolio. This is a known area
of complexity — see [Known Issues in TODO.md](./TODO.md#known-issues--areas-of-concern).

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

#### Storefront API Surface (`controllers/`)

The storefront exposes a structured REST API via a `controllers/` package,
mirroring the provisioning service's controller pattern. All controllers
are mounted in `server.py` alongside the `a2a_app` routes.

**System controller** (`controllers/system_controller.py`) — HTTP layer only; all logic in `services/system_service.py`:
```
GET  /health                            Kubernetes liveness/readiness probe (DB ping only — no outbound calls)
GET  /api/v1/system/health              Versioned alias
GET  /api/v1/system/status              Diagnostic snapshot: DB health + registry connectivity check + global pause state
GET  /api/v1/system/events              Stage event log — historical JSON query or live SSE tail (admin key required)
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

Note: this is a **local enumeration view**, not a discovery API. Discovery
filters (`gpu_model`, `region`, `ram_gb_min`, `token`, etc.) live on the
registry's spec-driven filter evaluator. Buyer-side discovery queries
`GET /listings` on a registry with `filter-spec.yaml`-declared parameters;
the storefront's listings endpoint is for the seller looking at their own
state.

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
  │    initial_amount, duration,  │                              │
  │    proposal,                  │                              │
  │    signature, timestamp}      │                              │
  │                              │── verify EIP-191 sig ────────►│
  │                              │◄─ ok ────────────────────────│
  │                              │── check global pause ─────────►│
  │                              │◄─ not paused ─────────────────│
  │                              │── load listing ───────────────►│
  │                              │◄─ listing row ────────────────│
  │                              │                              │
  │                              │  _load_storefront_chain()    │
  │                              │  determine_direction()        │
  │                              │  run_negotiation_chain(...)   │
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
| `negotiation_started` | `/negotiate/new` accepted (sig valid, not paused) | `listing_id`, `buyer_address`, opening amount/proposal |
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
- `our_price` in every `round_decided` event equals `primary_rate_value(accepted_escrows[0])` from the listing (the seller's floor; stored in uint256-domain base units — decimal-scaled at advertisement time, not at read time)
- A `round_decided` with `decision=exit` means the negotiation is already in terminal `failure` state — `force-accept` will return 409
- The `round` field in messages is 0-indexed for the buyer's initial offer; the seller's response is round 1, subsequent buyer counters are round 2, etc.
```

**Admin controller** (`controllers/admin_controller.py`):
```
POST  /api/v1/admin/pause    Set globally paused = True — admin key required
POST  /api/v1/admin/resume   Set globally paused = False — admin key required
GET   /api/v1/admin/status   Live counts: active_negotiations, open_orders, paused_orders
POST  /api/v1/admin/portfolio/resources/import
      Runtime inventory CSV import/upsert — admin key required.
      Resources that share attribute.pool_id join the same fungible
      compute_inventory_pools row; otherwise they remain one-member pools.
PATCH /api/v1/admin/portfolio/resources/{resource_id}
      Partial update of a resource row — admin key required.
      Body: { state?, attributes? } — only non-None fields written.
      Used for operator recovery, compatibility, and test state manipulation.
      Returns: full updated row + updated=true/false (idempotent flag).
      404 if resource_id does not exist.
POST  /api/v1/admin/portfolio/reservations
      Force-reserve compute capacity without buyer negotiation — admin key
      required. Writes compute_allocations and returns the selected
      pool_id/member_id/resource_id.
POST  /api/v1/admin/portfolio/release-reservations
      Bulk-release all held (reserved or leased) resources — admin key required.
      Sledgehammer for local/e2e recovery; normal lifecycle release should use
      fulfillment callbacks.
POST  /api/v1/admin/fulfillment/events/started
POST  /api/v1/admin/fulfillment/events/usage-started
POST  /api/v1/admin/fulfillment/events/release-started
POST  /api/v1/admin/fulfillment/events/capacity-released
POST  /api/v1/admin/fulfillment/events/failed
      Provisioning-service callbacks for execution lifecycle facts. These
      update compute_allocations and let the derived-listing reconciler
      republish or close listings from the new market-side capacity state.
```

#### Admin API Key

A global admin API key gates all admin-only endpoints. Read from
`CONFIG.admin_api_key` (`admin_api_key` top-level in storefront.toml, or
injected via the Helm secrets profile as a `config-storefront-secrets.yml`
entry). Enforced by `AdminAuthMiddleware` via the `X-Admin-Key` header.
When `admin_api_key` is `None` (local dev default), the middleware is a
no-op.

Protected paths: any route under `/admin/`, and any route ending in `/pause`,
`/resume`, `/advance`, or `/force-accept`.

**`global.adminApiKey`:** `values.yaml` carries `global.adminApiKey` (default `"test-api-key"` for the test cluster). The `agentConfigToml` helper renders it as `admin_api_key` (top-level) in the mounted `storefront.toml`. The per-agent secret profile (`config-{component}-secret.yml`) also carries it under `{component}.admin_api_key` so the e2e test pod can read it via dynaconf without a separate secret mount.

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
`listings_controller.py` reads the flag from the request body → adds it to `OrderCreateEvent.data["paused"]`
→ `oc_action_make_offer_from_order_create` in `domains/vms/negotiation/policies.py`
propagates it into `action.parameters["paused"]`
→ `listing_service.py` writes the listing to SQLite with `paused=1` and
**skips** `publication_service.publish_order_to_registry`.
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

### VM Buyer CLI (Pure HTTP client)

**Role:** The buyer side of the market. There is no buyer server, no
agent runtime, no SQLite database — only the `market` console script
(packaged and implemented under `domains/vms/buyer`).

`market buy` is a one-shot orchestrator: it queries
`arkhai-core-registry` for matching seller orders, runs synchronous
negotiations against each candidate seller's storefront (POST
`/negotiate`, signed bodies), and on agreement creates the on-chain
escrow via `alkahest_py` directly from the CLI process before POSTing
`/settle/{escrow_uid}` and polling for fulfillment. `market negotiate`
is the same loop bound to a single known seller; both share
`domains.vms.buyer.buy_orchestrator`.

The negotiation chain the buyer runs is built from the same
`arkhai-kit-policy` middlewares the seller uses — both sides instantiate
the chain via `load_negotiation_chain([...])`, with `bisection` as the
default terminal (or `rl` behind the optional torch extra). Round-by-
round events land in a per-run JSONL log under
`$XDG_STATE_HOME/arkhai/buy-runs/<run_id>.jsonl` rather than a database.

**Key source layout:**
```
domains/vms/buyer/
├── cli.py                  # `market` console-script entry
├── *_cli.py                # buy, negotiate, settle, listing, escrow, chain,
│                           # network, config, logs
├── buy_orchestrator.py     # the one-shot buy flow
├── buyer_client.py         # signed HTTP client for /negotiate, /api/v1/settle
├── deal_helpers.py         # run-log recovery + chain settings helpers
├── aggregation.py          # across-seller aggregation policies
├── run_log.py              # JSONL run logs under XDG_STATE_HOME
└── common.py               # config-resolution + REPO_ROOT helpers
```

`market settle --from <run_id>` is the post-agreement half of the flow: it
reads the agreed terms from the run-log JSONL, creates the on-chain escrow
under the buyer's wallet via `make_create_escrow_fn`, then POSTs
`/api/v1/settle/{uid}` and polls for fulfillment. Both buyer and seller
configure the negotiation chain via `[negotiation].policies` (ordered
list, or per-kind table) in their respective TOMLs; the buyer's default
(`["buyer_escrow_shape_guard", "bisection"]`) and the seller's
(`["has_matching_inventory_guard", "escrow_shape_guard", "bisection"]`)
differ in the appropriate guards. Both honour the legacy
`policy_mode = "bisection"|"rl"` key for back-compat.

---

### `policy` (`arkhai-kit-policy`)

Shared negotiation machinery + the RL training/eval tool. Two surfaces:

- **Library**: `market_policy.{negotiation_middleware,
  negotiation_thread, identity, ports}` — imported by both buyer and
  seller. The middleware shape (`NegotiationContext`,
  `NegotiationDecision`, `register_negotiation_middleware`,
  `load_negotiation_chain`, `run_negotiation_chain`) is the public
  surface; built-in middlewares (`bisection_middleware`,
  `has_matching_inventory_guard`, `escrow_shape_guard`,
  `max_rounds_guard`, `buyer_escrow_shape_guard`,
  `accept_exact_listing`, and amount-policy aliases for ERC20,
  native-token, and ERC1155) ship registered. The shared
  escrow-kind dispatcher is constructed from config rather than
  registered as a plain global middleware.
- **CLI**: `market-policy train / eval / export` — invoked by policy
  authors to produce RL checkpoints that the `rl` terminal middleware
  loads at inference time.

The CLI lives here (not in either runtime) because policy authoring is
a tooling concern separate from the buyer or seller process.

---

### `arkhai-vms-provisioning`

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
| `agent_id` | Identity of the storefront that submitted the job (its wallet address) — informational provenance, not access control |
| `buyer_agent_id` | Identity of the buyer (tenant) — informational provenance |

**Credentials** are stored separately in the `credentials` table (joined to job by `job_id`), split by role:
- `root` — root password and SSH key path on host
- `tenant` — tenant password and SSH commands (internal + external via FRP)

`GET /jobs/{job_id}/credentials` returns every role for the job; the
provisioning service does not gate per-caller. The storefront is the sole
caller and decides which credentials to surface to which tenant.

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

**`VmActionRequest` — shared optional body:** Simple lifecycle actions (`start`, `shutdown`, `reboot`, `destroy`, `undefine`, `monitor`, `reset-password`, `cancel_expiry`) share one optional body model `VmActionRequest(buyer_agent_id, max_retries)`. The `build_simple_params(action, host, body, vm_name)` helper in `vm_request_model.py` produces `AnsibleJobParams` from path parameters + this body. `CreateVmRequest` and `ScheduleVmExpiryRequest` remain distinct classes with their own fields.

---

#### Lease Lifecycle — execution facts and storefront callbacks

The provisioning service owns VM execution lifecycle via the `vm_leases`
table and the `LeaseWatchdog` background task. The storefront owns
negotiation, market-facing listings, and compute allocation state. When
settlement reserves capacity, the storefront records a
`compute_allocations` row with the selected `pool_id`, `member_id`, and
concrete `resource_id`; after the VM create job succeeds, provisioning
registers the execution lease via `POST /api/v1/leases`.

The host-side `lease_end` `at` job is best-effort and must not block
settlement readiness. The `LeaseWatchdog` is the authoritative
provisioning release path, but it reports lifecycle facts to the
storefront through `/api/v1/admin/fulfillment/events/*` callbacks. The
storefront updates `compute_allocations` from those callbacks and derives
listing open/closed state from pool availability. The older
`PATCH /api/v1/admin/portfolio/resources/{resource_id}` path remains an
operator/compatibility resource-state mutation, not the normal dynamic
listing release mechanism.

**`vm_leases` table:**

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | Internal lease ID |
| `resource_id` | TEXT | Storefront-assigned concrete resource identifier selected for this lease (e.g. `compute-kvm1-001`). Application-level FK — unvalidated by the provisioning service. |
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
| `released` | Capacity release reported to the storefront successfully |
| `forced` | Grace period elapsed; release was reported without VM confirmation |
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
  │   │   ├── POST {settings.storefront_url}/api/v1/admin/fulfillment/events/capacity-released
  │   │   │     body: { escrow_uid, resource_id, provider_lease_id?, ... }
  │   │   │     headers: X-Admin-Key: {settings.storefront_admin_key}
  │   │   ├── On callback success: mark_released()
  │   │   └── On callback failure within grace: skip (retry next cycle)
  │   │       On callback failure past grace: mark_forced()
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
- `POST /jobs` — submit a provisioning job; returns `{"job_id": "...", "status": "queued"}`
- `GET  /jobs` — list jobs with pagination (`offset`/`limit`), status filter, sort
- `GET  /jobs/{job_id}` — full job status including params, result, error, and retry metadata
- `GET  /jobs/{job_id}/credentials` — returns every role's credentials for the job; the storefront (sole caller) decides which to surface to which tenant
- `GET  /jobs/{job_id}/logs` — raw Ansible stdout+stderr for the job; credentials are redacted in storage but paths/keys may appear; logs update in near-real-time while job is running
- `POST /jobs/{job_id}/cancel` — cancels a queued job, or sends `SIGTERM` to the Ansible PID if the job is running

Every route except `/health` and the docs routes is gated by `StorefrontAuthMiddleware`: when `storefront_admin_key` is set, the caller must present it as `X-Admin-Key`. This is the operator's `admin_api_key` — the same shared secret the provisioning→storefront lease callback presents — so the storefront↔provisioning hop can cross an untrusted network. The storefront is the only caller; credentials are always mediated back through it, never served to tenants directly.

#### Ansible Diagnostic Endpoints (unified API, port `8081`)

Mounted on the main API under `/api/v1/ansible/`.

- `GET /health` — checks API, database, and job processing loop liveness
- `GET /inventory` — parses the Ansible INI inventory file and returns all hosts with their `ansible_host` values and inline vars; supports `?search=<substring>` for hostname filtering
- `GET /inventory/{host}/connectivity` — runs `ansible -m ping` against a single named host, exercising the complete auth path (inventory parse → SSH key → Ansible execute); returns `{"reachable": true/false, "detail": "..."}` — returns HTTP 200 either way, only 404 if host not in inventory

#### Test mock controller (`/test/*`)

Only mounted when `mock` is in `ACTIVE_PROFILES`. Never present in production or staging.

Provides an HTTP API for configuring `ProgrammableMockAnsibleService` rules and waiting for job lifecycle events without polling loops.

In arkhai-vms-provisioning integration tests, `/test/*` callers use a fresh
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
  "rule_id": "my-kvm1-create",
  "match": {"vm_action": "create", "vm_host": "kvm1"},
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
domains/vms/provisioning/service/src/
├── controllers/                # Handles Http Routing concerns.
├── services/                   # For internal business logic
├── models/                     # Request and Response objects for controllers
├── middleware/
│   ├── auth.py                 # StorefrontAuthMiddleware (shared X-Admin-Key gate)
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

### `domains/vms/provisioning/iac`

**Role:** Infrastructure-as-code for the physical layer.

Contains Ansible roles and Terraform modules used by both the provisioning worker (at runtime) and operators (to set up seller hardware).

**Ansible roles:**
- `vm-setup` — prepares a KVM host: GPU passthrough, KVM networking, golden image build (Packer + Ubuntu Noble), FRP client config, security hardening
- `vm-management` — day-2 VM operations: create/destroy/start/stop, GPU assignment, lease management
- `frp-setup` — sets up FRP server (fast reverse proxy) for buyer network access to VMs
- `docker-app` — deploys Docker-based apps to a host

**Terraform modules:** GCP-focused (Cloud Run, artifact registry, service accounts, Redis, ZeroTier controller). Used for the production/staging/sandbox cloud deployment of the non-hardware services.

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
| `frp.domain` | e.g. `vm.arkhai.io` | N/A |
| `authentication.tenant.ssh_commands.external` | `ssh -i <key> -p 7045 vmname@a3b9f2.vm.arkhai.io` | `ssh -i <key> -p <port> vmname@<kvm_host_ip>` |
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
- The FRP dashboard at `https://frp-admin.<domain>` shows all active proxy connections — this is currently the only way to get a live view of which VMs have active tunnels, since the provisioning service has no VM state table.

#### `escrow_uid` on jobs — deal linkage and recovery

The `ansible_jobs` table carries an `escrow_uid` column (nullable, indexed). The storefront passes this when submitting a provisioning job for a settled deal. It enables the storefront to recover the provisioning job_id after a crash by querying `GET /api/v1/jobs?escrow_uid=<uid>` rather than losing the mapping.

`escrow_uid` is surfaced in:
- `AnsibleJobParams.escrow_uid` (internal DTO)
- `JobStatusResponse.escrow_uid` (HTTP response)
- `GET /api/v1/jobs?escrow_uid=<uid>` filter on the list endpoint
- `ProvisioningClient.list_jobs(escrow_uid=...)` on both async and sync clients

The `provisioning_job_id` is surfaced in `GET /settle/{escrow_uid}/status` on the storefront so the buyer can traverse: storefront settle status → `provisioning_job_id` → provisioning `GET /jobs/{id}`.

---

### CLIs

There are three console scripts, each a separate distributable. They
split by concern (runtime vs. tooling) rather than
by buyer-vs-seller role. Built with Typer; config is read from a TOML
file under `$XDG_CONFIG_HOME/arkhai/` — `buyer.toml` for the buyer's
`market` CLI, `storefront.toml` for `market-storefront` and the
storefront server (override either with `--config <path>`).

| CLI | Package | Role | Top-level groups |
|---|---|---|---|
| `market` | `domains/vms/buyer/` | Buyer runtime (pure HTTP client) | `buy`, `negotiate`, `order`, `escrow reclaim`, `network join/get-peers`, `config`, `logs` |
| `market-storefront` | `domains/vms/storefront/` | Seller runtime | `register`, `serve`, `provide`, `escrow claim/refund`, `portfolio import-csv`, `network join/get-peers`, `config`, `logs` |
| `market-policy` | `kit/policy/` | Policy authoring tool | `train`, `eval`, `export` |

The two runtimes (`market`, `market-storefront`) share `network join`
and `get-peers` because each participant manages their own ZeroTier
membership. The owner-side actions (`install` / `create` / `add`) are
Make targets in `scripts/zerotier/`, run by whoever stands up the overlay.

Deployment shells just compose CLI verbs:

- **Docker (storefront image):** `entrypoint.sh` brings up the
  ZeroTier daemon, then runs `market-storefront register` and
  `exec market-storefront serve`.
- **Helm:** the init container runs
  `./entrypoint.sh market-storefront register --chain-id N` and the
  main container runs `./entrypoint.sh market-storefront serve` —
  same image, two CLI verbs.

`market-storefront serve` only forwards `host` and `port` into
`server.run_serve()`. The CLI/server argument contract is covered by a
storefront unit test because a mismatch crashes the container before any
integration or e2e test can run.

See `docs/cli-redesign-plan.md` for the rationale behind the current
4-CLI surface.

---

## Deployment Topology

### Local Dev (compose)

```
compose/external.yml     — Anvil node + one-shot contract deployer (the "external"
                           chain layer; in prod this is a live RPC, not run here)
compose/registry.dev.yml — arkhai-core-registry against the dev chain
                           (compose/registry.yml is the operator-facing variant)
compose/seller.yml       — storefront server + provisioning service (unified)
```

There is no `compose/buyer.yml` — the buyer is the `market`
CLI invoked from the host or another container, not a long-running
service. The seller container reads its config from a TOML file
mounted at `/etc/arkhai/storefront.toml` (set via `XDG_CONFIG_HOME=/etc`);
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
    ├── registry/           # arkhai-core-registry (condition: registry.enabled)
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
- The storefront waits on RPC (`eth_blockNumber` poll) and registry (`/health` poll) before starting
- The provisioning container has no init containers or startup dependencies
- The test-env container has no init containers or startup dependencies

**Secrets:**
- Storefront private key + wallet address → `Secret` per storefront, sourced from `values.yaml` `secret.privKey` / `secret.walletAddress`, or an externally pre-created secret
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
- Storefront agents, registry, and provisioning each back their SQLite onto a per-service ReadWriteOnce PVC: `/var/lib/arkhai` (storefront, per-agent), `/var/lib/arkhai-registry` (registry), `/app/data` (provisioning). This preserves negotiation history, registry index, and lease state across pod restarts. Each chart pins `strategy: Recreate` (RWO can't have two pods attached), sets `securityContext.fsGroup: 1000` so `appuser` can write the freshly-mounted volume, and annotates the PVC with `helm.sh/resource-policy: keep` so `helm uninstall` doesn't reap the disk. A `persistence.enabled` toggle in each subchart's `values.yaml` falls back to `emptyDir` for kind/CI/local-iteration without a StorageClass.
- Agent identity persistence across pod restarts is trivial: the storefront's identity is its EIP-191 wallet address from `[wallet]` in storefront.toml. No per-chain on-chain registration, no ID to pin.

**Storefront chart layout — ConfigMap + Secret split:** `helm/charts/storefront/`
emits two artifacts per agent:

- a **ConfigMap** carrying non-sensitive runtime knobs (chain URLs, log paths,
  mode flags, top-level identity scalars, `[provisioning]` + `[negotiation]`
  sub-tables) rendered as `storefront.toml`
- a **Secret** carrying only sensitive values (`[wallet]` `address` +
  `private_key`, top-level `admin_api_key`, `[integrations]` `gemini_api_key`,
  top-level `resources_csv_inline`) rendered as `storefront.secrets.toml`

The runtime config tree is assembled by `dynaconf` in
`domains/vms/storefront/src/market_storefront/utils/config.py`, which layers (highest
priority last): the committed defaults in
`domains/vms/storefront/src/market_storefront/settings.toml`, the ConfigMap
`/etc/arkhai/storefront.toml`, the Secret
`/etc/arkhai/storefront.secrets.toml`, and `STOREFRONT_*` environment
variables. `settings.toml` documents every supported key and its default;
overlay files supply only what differs from defaults. Callers access values
via direct attribute traversal on the module-level `settings` singleton —
e.g. `settings.port`, `settings.wallet.private_key`,
`settings.provisioning.service_url`, `settings.registry.urls`. Three
composites computed once at import are exported as module constants:
`AGENT_ID` (validated identifier), `AGENT_NAME` (falls back to `AGENT_ID`),
and `BASE_URL_OVERRIDE` (ZeroTier placeholder resolution applied to
`settings.base_url`). One composite `chain_id()` is a function call because
it falls back to a live `eth_chainId` RPC when `[chain] chain_id` is unset.

The storefront's TOML file pair is **role-scoped** — buyer and seller no
longer share a single config file. The buyer CLI reads `buyer.toml` +
`buyer.secrets.toml`; the storefront server *and* `market-storefront`
CLI both read `storefront.toml` + `storefront.secrets.toml`. When the
same operator runs both buyer and seller on one machine (e.g. a
seller-also-buyer setup), each role has its own wallet and own file pair.

Independent `checksum/config` and `checksum/secrets` annotations on the
Deployment isolate rollouts to whichever source changed — flipping a log
level does not churn the Secret. Local-dev callers reading
`~/.config/arkhai/storefront.toml` go through the same loader; the overlay
step is a no-op when only the base file exists. A `make test-render` target
in `helm/` runs `helm template` and asserts the structural invariants
(mount paths, key layout, no `private_key` leak into the ConfigMap,
independent checksums) without needing a cluster.

Wallet key, admin key, and inline resources CSV are in the Secret object;
they rotate independently of non-sensitive config.

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
   `zerotier_network` is absent from `storefront.toml` — `entrypoint.sh` is
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
2. **`seller.resources_csv_path`** (compose / local dev) — path to a CSV file on disk, bind-mounted into the container by `make deploy-storefront` via `RESOURCES_CSV_FILE` (defaults to `domains/vms/storefront/src/market_storefront/data/kvm1-machine.csv`). Used by the docker-run compose flow.
3. **`POST /api/v1/admin/portfolio/resources/import`** — admin endpoint for runtime clobber. Accepts a CSV file upload and upserts regardless of current table state. Used for inventory updates without restarting the pod.

*Startup seeding is idempotent*: if the resources table already has rows (e.g. from a previous startup or a prior import call), seeding is skipped. Pod restarts do not overwrite operator changes. To force a full re-seed, use the import endpoint.

The full-deal e2e scenario uses the admin import path: it carries an inline CSV fixture and imports the exact compute row it needs through `SyncStorefrontClient.admin_import_resources()` during readiness. This keeps the test self-contained and prevents it from depending on `kvm1-machine.csv` being mounted into the storefront container.

The CSV files in `domains/vms/storefront/src/market_storefront/data/*.csv` are excluded from the container image via `.dockerignore`. They exist in the source tree as reference/default inventory for local dev (used by the compose bind-mount path) but are not baked into the image.

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
make build                       # production artifacts
  ├── dist                       # internal wheels → .dist/
  ├── build-buyer                # PyInstaller → domains/vms/buyer/dist/market
  ├── build-registry             # arkhai:registry / arkhai:registry-<sha>
  ├── build-storefront           # arkhai:storefront / arkhai:storefront-<sha>
  └── build-provisioning         # arkhai:provisioning / arkhai:provisioning-<sha>

make build-dev                   # build + the local e2e stack
  ├── build                      # (above)
  ├── build-test-env             # arkhai:test-env (Anvil + baked state)
  │     └── build-anvil-state   # generate_state.py → test-env/state/state.json
  └── build-test-image           # arkhai:integration-tests
```

Wheel builds happen separately via `make dist` (called automatically by
`build`):

```
make dist
  ├── dist-storefront-client  → .dist/arkhai_storefront_client-*.whl
  ├── dist-registry           → .dist/arkhai_registry_client-*.whl
  ├── dist-arkhai-core-buyer         → .dist/core_buyer-*.whl
  ├── dist-arkhai-core-storefront    → .dist/core_storefront-*.whl
  ├── dist-provisioning       → .dist/provisioning_service-*.whl
  ├── dist-storefront         → .dist/market_storefront-*.whl      (Docker builds only)
  ├── dist-policy             → .dist/market_policy-*.whl          (Docker builds only)
  ├── dist-identity           → .dist/market_identity-*.whl        (Docker builds only)
  ├── dist-core               → .dist/market_core-*.whl            (Docker builds only)
  ├── dist-alkahest           → .dist/market_alkahest-*.whl        (Docker builds only)
  └── dist-config             → .dist/market_config-*.whl          (Docker builds only)
```

---

## Artifact Registry Publishing

Built runtime artifacts are published to GCP Artifact Registry in the `compute-market-internal-infra` 
repo. The registries and their IAM are managed there; this repo only pushes.

**Artifact inventory:**

| Artifact | AR format | Repo key | Tag at push |
|---|---|---|---|
| Docker images (registry, storefront, provisioning) | DOCKER | `docker` | git short SHA |
| Docker dev images (test-env, integration-tests) | DOCKER | `docker` | git short SHA |
| Helm chart (`arkhai-node-operator`) | DOCKER (OCI) | `helm` | git short SHA |
| `arkhai-core-storefront-client` wheel | PYTHON | `python` | wheel version |
| `arkhai-core-registry-client` wheel | PYTHON | `python` | wheel version |
| `arkhai-vms-provisioning` wheel | PYTHON | `python` | wheel version |
| `market` CLI binary | GENERIC | `cli` | git short SHA |

The internal-only wheels (`arkhai-vms-storefront`, `arkhai-kit-policy`) are consumed only via `--find-links` inside
Docker builds and are never pushed to AR.

**Push flow:**

```
make build
make push-runtime-artifacts [AR_PROJECT=compute-market-1-dev]
  ├── push-images   # docker tag + docker push × 3
  ├── push-helm     # helm push (OCI)
  ├── push-wheels   # gcloud existence check + uv publish for missing wheels
  └── push-cli      # gcloud artifacts generic upload

make build-dev
make push-dev-images [AR_PROJECT=compute-market-1-dev]
  ├── arkhai:test-env
  └── arkhai:integration-tests
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
`arkhai-core-storefront-client`, `arkhai-core-registry-client`, and
`arkhai-vms-provisioning`, then immediately re-upload the local `.dist/` wheels.
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
  --package=arkhai-vms-provisioning
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

## Service Design Decisions

This section records design decisions reached through implementation experience. It exists so that the reasoning is available to future sessions without having to re-derive it from code.

---

### E2E Test Architecture: Stage-by-Stage Validation

**Context:** The e2e test validates the synchronous-orchestrator pipeline (policy dispatch, settlement, provisioning) using its append-only `stage_events` SQLite audit log as the only inter-stage observable. The test reads from that log between stages to confirm what happened — never from internal state — and gates progress via the orchestrator's dry-run and pause/advance affordances.

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
def stage_05a_evaluate_negotiate():
    # dry-run: would the negotiation chain produce a counter for this opener?
    result = admin_client.evaluate_negotiate(listing_id, proposal=...)
    assert result.would_negotiate is True
    assert result.decision in ("counter", "accept")

def stage_05b_negotiate_new():
    # advance: actually start the negotiation
    resp = await client.negotiate_new(
        listing_id=...,
        initial_amount=...,
        proposal_fields=...,
        literal_fields=...,
        ...
    )
    assert resp.action in ("counter", "accept")
    # audit: confirm the round_decided event appears in stage_event stream
    event = wait_for_stage_event(stage="negotiation", event="round_decided")
    assert event["negotiation_id"] == resp.negotiation_id
```

**Admin "what would you do?" endpoints** (dry-run, no side effects):
- `POST /api/v1/admin/listings/{listing_id}/evaluate-negotiate` → `EvaluateNegotiateResponse` — runs the configured negotiation chain against a synthetic buyer offer; returns `would_negotiate=False` if the terminal middleware would exit immediately.
- `POST /api/v1/admin/settle/{escrow_uid}/evaluate-settle` → dry-run settlement readiness check.

Listing create/close are now procedural (no policy step to dry-run), so
their `evaluate-create` / `evaluate-close` admin endpoints were dropped
in the procedural-policy refactor. The e2e stage-Na pattern survives
via the remaining dry-run endpoints + the `stage_events` audit stream.

**The event stream as the observable:** `GET /api/v1/system/events` (`SyncStorefrontClient.wait_for_stage_event()`) provides a cursor-based poll over the `stage_events` SQLite audit log. This is the mechanism for validating "what did you do?" without polling the resource directly or using `asyncio.sleep`. See `wait_for_stage_event` in `integration-tests/tests/e2e/roles/scenarios/conftest.py`.

**The pause/advance pattern for multi-step pipelines:** Create resources with `paused=True` to prevent them from propagating to the next pipeline stage before the test has validated the current stage. Use admin endpoints (`resume`, `advance`, `force-accept`) to advance one step at a time. This is how the e2e test controls pacing through the negotiation → settlement → provisioning pipeline without race conditions.

**What the e2e test deliberately does NOT test:** The hypothetical event-queue adapter described in the orchestration section above — it isn't built. Everything else in the service layer is exercised by the stage-by-stage dry-run + advance + stream-inspect pattern.

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

## State Management and Schema Migration Strategy

### Database topology

Each service owns exactly one database. Cross-service database sharing does not occur; the per-service SQLite file-per-service design structurally prevents it. The registry is the exception: it runs SQLite in development but is architecturally designed for Postgres in production.

| Service | Migration framework | Storage | Startup behaviour |
|---|---|---|---|
| Registry | Alembic (`alembic_version` table, 14 migrations) | SQLite (dev), Postgres-ready | `create_all` bootstraps missing tables, then startup stamps or upgrades Alembic state depending on whether `alembic_version` exists. |
| Storefront | Custom `schema_migrations` table, per-migration tracking | SQLite | Applied in lifespan hook via `SQLiteClient` constructor |
| Provisioning | Custom `schema_migrations` table, per-migration tracking | SQLite | Applied in lifespan hook via `init_db()` |

---

### Migration placement — current state and target

**Current state:** All three services apply schema migrations inside the main service container's startup sequence. This conflates migration concerns with service startup and makes migration failures indistinguishable from application crashes in Kubernetes pod status.

**Target for SQLite services (storefront, provisioning):**

A Kubernetes init container in the pod executes migrations before the main container starts. Both containers use the same image but different entrypoints — the init container runs a migration CLI command, the main container runs the service. A `Init:Error` pod status is unambiguously a migration failure; it cannot be confused with an application crash.

The main container adds a **schema version guard** in its startup code: before serving any traffic it reads the current schema version from the tracking table, compares it against the version the running code expects, and if there is drift it exits with a message like:

```
Database schema is at version 3, service expects version 4.
Run the migration before starting the service:
  docker run <image> python -m db.migrate       (docker / local)
  kubectl apply -f migrate-job.yaml              (Kubernetes, if init container not configured)
```

This guard matters equally for non-Kubernetes deployments — local dev, docker-compose — where init containers do not apply. The service must never silently boot against a mismatched schema and return errors only when a query hits a missing column.

**Target for the registry (Postgres, future):**

A Helm pre-upgrade hook Job connects directly to Postgres and runs `alembic upgrade head` before the Deployment rollout begins. If the Job fails, `helm upgrade` returns an error and the running Deployment is untouched. No pod lifecycle is involved in the migration path. This pattern is enabled by Postgres not being bound to a ReadWriteOnce volume.

Implementation of the init container pattern and the Helm pre-upgrade Job are tracked in `TODO.md`. Until implemented, startup-time migration remains in place; under the `strategy: Recreate` deployment model, the PVC detaches from the old pod before the new pod can attach it, so the migration and service startup are already serialized.

---

### Schema change policy

**Additive-only by default.** The policy for all schema changes:

- New columns must be nullable or carry a default value
- New tables and new indexes may be added freely
- Column renames, type changes, and column drops are not permitted in a single release

**Non-additive changes use expand-contract across releases:**

When a change cannot be expressed as purely additive, it is decomposed into two separately-deployable phases:

- *Expand phase (Release N):* Add new columns or tables alongside old. Application code writes to both old and new. Old columns remain present and readable by already-deployed service versions.
- *Contract phase (Release N+1):* Drop deprecated columns or tables. Application code reads only from the new schema. Old columns are no longer written.

The deprecation window is **k=1**: deprecated schema is removed in the release after the one that introduced the deprecation. Operators on a version behind the expand phase will receive the schema change without disruption; operators more than one release behind must upgrade sequentially through the expand-phase release before applying the contract-phase release. For specific changes requiring longer lead time, k > 1 may be applied and communicated directly to ecosystem partners.

**Large-table guard.** Migrations that backfill or transform existing rows should check the row count before executing. If the count exceeds a threshold (starting value TBD, the migration should fail fast with instructions on how to proceed.

---

### Registry client compatibility constraint

The registry is shared infrastructure. A schema or API change that breaks compatibility with running storefront or provisioning service versions affects the entire ecosystem of operators simultaneously — not just those who have upgraded. This is categorically different from a brief pod restart outage on a per-operator service.

**Non-additive registry schema or API changes are blocked until the registry runs on Postgres with a gradual rollout pattern.**

Postgres enables running old and new registry versions concurrently against the same database, giving operators a defined compatibility window to upgrade their storefront and provisioning service versions before the old API is retired. SQLite on a ReadWriteOnce PVC fundamentally cannot support concurrent pod versions.

Until this infrastructure is in place, all registry schema and API changes must be backward-compatible with at least the immediately preceding release of `arkhai-core-registry-client`. The expand-contract policy makes individual releases additive, satisfying this requirement.

---

### State persistence

All three service Helm subcharts default to `persistence.enabled: true`, creating a ReadWriteOnce PVC backed by the cluster's default StorageClass. Each Deployment uses `strategy: Recreate` to enforce single-writer access (RWO volumes cannot attach to multiple pods simultaneously), and `helm.sh/resource-policy: keep` ensures `helm uninstall` does not delete the PVC.

The Helm subcharts expose a `persistence.existingClaim` parameter: when set, the chart mounts the named PVC without creating one; when empty, existing behaviour is unchanged.

---

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
- The `StorefrontAuthMiddleware` X-Admin-Key gate — open in tests because the test settings leave `storefront_admin_key` empty

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

response = await client.post("/api/v1/hosts/kvm1/vms/", json={...})
await asyncio.wait_for(job_dispatched.wait(), timeout=5.0)
# Now safe to poll GET /api/v1/jobs/{job_id} for terminal state
```

`AsyncJobQueue.__init__` accepts `on_job_started: Optional[Callable[[str], None]]` as a test seam. It is `None` in production and zero-cost.

#### 3. Smoke Tests (Deployment Validation)

**What they cover:** Stateless, idempotent verification that a deployed stack is wired correctly — services can reach each other, authentication headers are enforced, health endpoints return 200, expected routes exist. These run as Helm test hooks in Kubernetes.

**What they do not cover:** Service semantics. By the time a smoke test runs, the semantics have already been validated by integration tests. A smoke test for the provisioning service should verify that `GET /health` returns 200 and that `POST /api/v1/hosts/kvm1/vms/` returns 401 without a valid `X-Admin-Key` header — it should not submit a real provisioning job and poll for completion.

**Current location:** `helm/templates/tests/` as Kubernetes Job resources executed by `helm test`.

#### 4. System Integration Tests (End-to-End)

**What they cover:** Cross-service contracts — scenarios that require two or more services to interact over the network to produce a meaningful result. Examples: a buyer agent successfully negotiating with a seller agent and reaching a settled on-chain state; a provisioning job triggered by an agent completing and the buyer receiving credentials.

**What they do not cover:** Anything already covered by the three levels above. System integration tests are expensive to run and brittle to maintain; they should be minimal in count and cover only the cross-service contract, not any service's internal logic.

**Current location:** `integration-tests/tests/e2e/` — the `roles/` subtree organises tests by deployment layer (external chain, market registry, seller node) and negotiation stage (discovery, negotiation, settlement).

#### Full-Deal E2E Test — two scenarios

The full-deal scenario exists in two parallel variants under
`tests/e2e/roles/scenarios/`, sharing the readiness + listing + provisioning
stages but diverging on how the buyer drives negotiation and settle:

| File | Marker | Buyer side |
|---|---|---|
| `test_full_deal.py` | `e2e_deal` | Synthetic — `SyncStorefrontClient.negotiate_new()` + admin `force_accept`, dry-run + advance at every stage (matches the "Stage-by-Stage Validation" pattern below) |
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
| 02a / 02b | Create listing | `POST /api/v1/listings/create paused=True` (procedural — no dry-run step) |
| 03a / 03b | Publish | `POST /api/v1/listings/validate-publish` → resume publishes to registry (the publisher is created lazily on this first signed publish) |
| 04a | Primary registry visibility | listing visible on registry |
| 05a / 05b | Negotiate | `evaluate-negotiate` → `POST /negotiate/new`; assert `round_decided` event with decision=counter |
| 06b | Force-accept + terminal | guard no prior exit/accept; `POST .../force-accept` → accept; thread terminal=success |
| 07 | Provision gate | `add_mock_rule(pause_before_result=True)` |
| 07b | Verify escrow | buyer creates real escrow via alkahest; `POST /api/v1/admin/settle/{uid}/verify` → valid |
| 08a / 08c | Settle + provisioning-job dry-runs | `evaluate-settle` (captures `vm_host`/`vm_target`); `POST /test/evaluate-job` (matches gate rule) |
| 08b | Submit settle + job queued | `POST /api/v1/settle/{uid}`; `wait_for_stage_event(resource_reserved)`; `provisioning_job_id` surfaced |
| 09a | Gate release + ansible succeeds | `resume_rule`; `wait_for_job` (long-poll) → succeeded |
| 09b | Ready + credentials + capacity held | `wait_for_settlement` → ready; `GET /api/v1/settle/{uid}/status` → tenant credentials; 1x listing closes while capacity is held |
| 09c | Lease registered | `GET /api/v1/leases/by-escrow/{uid}` → active/pending |
| 10a / 10b | Lease expiry setup + watchdog advances | pause watchdog, patch `lease_end_utc` past, arm check-gate mock; watchdog transitions lease to `releasing` |
| 11a / 11b | Releasing state stable + capacity released | check-gate released; provisioning reports `/api/v1/admin/fulfillment/events/capacity-released` and the storefront releases the matching allocation |

**Buyer-CLI variant divergence (`test_full_deal_buyer_cli.py`):**

- **05b** — `market negotiate --listing-id … --max-price 12000 --duration-hours 1 --yes` runs synchronously to terminal. Bisection on both sides converges in ~1 round (buyer ceiling above seller's first counter). Test asserts subprocess `rc=0`, run-log `run_ended.status=agreed`, and seller-side `round_decided` stage_event.
- **06b deleted** — `force_accept` coverage stays in `domains/vms/storefront/tests/integration/test_negotiations_api.py`.
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

`evaluate_settle` calls `_build_provisioning_job_spec`, which uses the
read-only `select_available_compute_vm` (no state change, no reservation).
The real flow (`fulfill_compute_obligation`) calls
`reserve_available_compute_vm` directly to atomically mark the resource
reserved. The dry-run service passes its request-scoped/injected SQLite
client into `_build_provisioning_job_spec`; the helper only falls back to
the process-global client when no client is supplied. This keeps in-process
integration tests on the same database for listing lookup and inventory
selection.

**Provisioning evaluate-job endpoint (test controller):**

`POST /test/evaluate-job` on the provisioning service's test controller. Accepts `{host, vm_target, ssh_pubkey, vm_action}`, returns `{params_valid, host_exists, rule_matched, would_pause, errors}`. Checks host existence in inventory and which mock rule (if any) would match the job params. No job is created. Used by e2e stage 9a.

**`/api/v1/negotiate/new` signing and escrow terms:**
`StorefrontClient.negotiate_new()` and
`SyncStorefrontClient.negotiate_new()` add EIP-191 `X-Signature` and
`X-Timestamp` headers automatically. They accept `listing_id`,
`buyer_address`, `initial_amount`, `duration_seconds`, `buyer_agent_url`,
`ssh_public_key`, `chain_name`, `escrow_address`,
`escrow_expiration_unix`, `proposal_fields`, `literal_fields`, `rates`,
and `demands`, plus `token` as a convenience for token-shaped scalar
flows. The helper builds the structured `provision_terms` and
`escrow_proposal` body required by the server. If `literal_fields` is
omitted, the legacy helper default injects `literal_fields.token =
0x000...000`; if callers pass an explicit empty dict, it remains empty,
which is required for native-token escrows. For token-shaped flows, the
buyer proposal's token literal must match the selected listing
`accepted_escrows[i].literal_fields.token`; non-token escrows are matched
by their own `(chain_name, escrow_address, literal_fields, rates)` shape
and by the configured negotiation policy. If an e2e test raises
`TypeError: SyncStorefrontClient.negotiate_new() got an unexpected keyword
argument`, the runtime is importing a stale `arkhai-core-storefront-client`
install. Rebuild the wheel and reinstall consumers with `make reinit` so
`uv.lock` is re-resolved against the current `.dist/` wheel.

**Current full-deal details:** publishing is lazy — the publisher row is
created on the first signed publish (stage 03b), so there is no
index-before-publish wait. The full-deal happy path assumes one primary registry; private
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

**Pre-negotiation inventory guard:** `/api/v1/negotiate/new` enforces immediate-deal inventory availability via the `has_matching_inventory_guard` middleware in the configured negotiation chain (round 0 only — `len(history) == 0`). If no available resource matches the listing's `offer_resource`, the middleware short-circuits with `action="reject", reason="no_matching_inventory"`, which the controller maps to HTTP 409. The default chain in `storefront.toml` puts this middleware first, so the check happens before any rate negotiation.

**`ensure_storefront_resumed` teardown:** An `autouse=True` module-scoped fixture in `conftest.py` that unconditionally calls `admin_resume()` if `get_system_status().paused` is True after the module finishes. This targets the **global** `_GLOBALLY_PAUSED` flag (`POST /admin/pause|resume`), not the per-listing `paused=True` flag the synthetic scenario flips at 02b/03b. Neither full-deal scenario currently calls global `admin_pause`, but the fixture stays in place so a future test or a manually-paused live environment cannot strand the next run in 503.

**`wait_for_stage_event` helper:** In `conftest.py`. Wraps `SyncStorefrontClient.wait_for_stage_event()` with pytest-friendly timeout error. Used at stage 08b to await the `resource_reserved` event (provisioning job queued) without a sleep loop. The underlying client method polls `GET /api/v1/system/events` with a cursor and 500ms interval. For stages where the observable is a background job reaching terminal state rather than a discrete pipeline event, prefer a server-side long-poll (see `wait_for_settlement` below).

**`wait_for_settlement` (storefront client):** `SyncStorefrontClient.wait_for_settlement(escrow_uid, timeout=60.0)` calls `GET /api/v1/admin/settle/{uid}/wait` — a server-side long-poll on the admin settle controller. The storefront polls `load_settlement_job` every 1 s until the job status is `"ready"` or `"failed"`, or the timeout elapses (server-enforced max 120 s). Returns `SettleWaitResponse(ready, status, provisioning_job_id, elapsed_ms)`. Used at stage 09b. Returns immediately if the job is already in a terminal state when called. Callers must check `result.ready` (timeout flag) and `result.status` (the actual job state). The admin-only auth boundary is intentional: this endpoint surfaces internal settlement job state that the buyer does not need; the buyer's observable is the existing `GET /settle/{uid}/status` point-in-time read.

**Pattern: server-side long-poll for background work.** Any time a test needs to gate on a background task completing a unit of work, add an admin/system endpoint that blocks server-side until the condition is met, then call it once from the test. This is preferable to client-side polling loops for two reasons: the wait is observable (the endpoint logs elapsed time), and it avoids the mismatch between client timeout and server-side poll interval that caused the stage 09b flakiness. The `wait-for-settlement` endpoint is the canonical example of this pattern.

**`GET /api/v1/system/status` top-level fields:** In addition to `checks`, the full diagnostic status endpoint exposes three top-level fact fields (admin key required):
- `agent_id` — the storefront's identity: its lowercase `eip191` wallet address. This is the `X-Agent-ID` it presents to the provisioning service, so consumers read it here to address jobs the storefront owns. `None` if no wallet is configured.
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

**arkhai-vms-provisioning** (reference layout):
```
domains/vms/provisioning/service/src/tests/
├── unit/
│   ├── conftest.py              # mock_settings fixture
│   └── services/
└── integration/
    ├── conftest.py              # app fixture, container overrides, DB setup, fake_ansible
    └── test_{controller}.py
```

**arkhai-core-registry**:
```
core/registry/tests/
├── conftest.py                  # db_session fixture (in-memory SQLite), sign_order_auth helper
├── unit/
│   ├── test_order_auth_utils.py # EIP-191 signature verification helpers (exhaustive)
│   ├── test_filter_eval.py      # build_criteria + evaluate_all — spec-driven listing
│   │                            # filter semantics
│   └── test_filter_spec.py      # YAML loader, FilterDecl validation, ETag stability + sensitivity
└── integration/
    ├── conftest.py              # RegistryClient wired to in-process app via httpx ASGITransport;
    │                            # publisher/identity/listing fixtures; Hardhat key constants
    ├── test_publishers.py       # GET /publishers (list + resolve-by-identifier), GET /publishers/{id}
    ├── test_eip191_publish.py   # signed POST /listings lazily creates publisher + identity
    ├── test_api_keys.py         # read/write API-key gates + key scopes
    ├── test_filter_spec.py      # GET /filter-spec full HTTP path + ETag header
    ├── test_listings.py         # POST /listings, GET /listings{,/{id}}, ?publisher= filter,
    │                            # PUT/DELETE owner-scoped auth, full lifecycle
    ├── test_listings_filtering.py # spec-driven query params (gpu_model, ram_gb_min lower-bound
    │                            # alias, token array projection, If-Match 412, unknown filter 400)
    ├── test_validate_publish.py # JSON Schema dry-run cases (happy + each rejection class)
    └── test_system.py           # GET /health (including 503 on DB failure), GET /api/v1/system/stats
```

**Client contract enforcement in arkhai-core-registry integration tests:**

All integration tests import `RegistryClient` from the `arkhai-core-registry-client` wheel and exercise the API exclusively through it.  The transport is `httpx.ASGITransport(app=app)` — real HTTP through the full FastAPI stack, no network socket.  If the API renames a field or changes a response shape, the client's `from_dict` parser will either raise or silently drop the field, and the assertion will fail immediately.  The `get_db` dependency is overridden per-test to yield the fixture's isolated in-memory SQLite session.

The two legitimate raw-call exceptions (rejection-path tests and `db_session` state setup) apply here exactly as documented in the arkhai-vms-provisioning section above. `RegistryClient` and `SyncRegistryClient` expose typed methods covering `/api/v1/system/stats`, `GET /publishers{,/{id}}`, `POST /listings`, `PUT`/`DELETE /listings/{id}`, and `validate_publish_listing()` (`POST /api/v1/listings/validate-publish`) with `ValidatePublishRequest`/`ValidatePublishResponse` models. `ListingRequest` and `ValidatePublishRequest` carry a `storefront_url` field (`""` default) to satisfy the filter-spec's required-publish-candidate constraint; the storefront populates it from `BASE_URL_OVERRIDE`/its storefront URL.

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
            ├── conftest.py      # Imports layer fixtures (external_world, registry_layer, seller_node)
            ├── helpers/         # deal.py (full deal flow helper), erc20.py
            ├── layers/          # test_external.py, test_registry.py, test_seller.py
            └── stages/
                └── discovery/test_buyer.py
```


### Problem
Python packages in this monorepo need to consume each other (e.g. the storefront imports the provisioning service client). Relative path imports across project directories are fragile — they encode layout assumptions and break when projects move. Native extension wheels (those with platform/ABI tags like `cp312-cp312-linux_x86_64`) must be compiled inside the target Docker environment; this is why `alkahest-py` ships pre-built wheels for each platform in `domains/vms/storefront/packages/`. Pure Python wheels (`py3-none-any`) have no such constraint and can be built safely on the host.

### Current Approach: `--find-links` flat wheel directory

Pure Python internal packages are built as wheels and placed in `.dist/` at the monorepo root before Docker images are built. Docker images consume them via `uv sync --find-links /dist`.

**Build sequence:**

```
make dist          →  uv build for each pure-Python package  →  .dist/*.whl
make build         →  docker build (COPY .dist/ /dist/, uv sync --find-links /dist)
```

`make dist` runs automatically as a prerequisite of `make build`.

**Guard:** `make dist-provisioning` asserts the output wheel filename ends in `-none-any.whl`. If a C extension or Rust crate is ever added to a package, the build fails loudly with an error directing the developer to move compilation inside the Docker build context.

**Why `--find-links` is passed on the CLI, not in `pyproject.toml`:**

`find-links` encodes a filesystem path. The path differs between environments:

- **Docker:** `.dist/` is copied to `/dist/` inside the image; `uv sync --find-links /dist` is passed in the `RUN` instruction.
- **Local dev:** `.dist/` lives at the monorepo root; `uv sync` and `uv run` must be invoked with `--find-links ../.dist` (set in each sub-project's Makefile targets). Note: `UV_FIND_LINKS` is **not** equivalent — it is not read by `uv sync` or `uv lock`; only the `--find-links` CLI flag works for dependency resolution.

Setting `find-links` in `pyproject.toml` bakes one of these paths into the lockfile and breaks the other context. Setting it via `UV_FIND_LINKS` on the command line means the path stays out of version-controlled files entirely.

**Rule:** downstream `pyproject.toml` and `uv.lock` files must never contain `find-links` entries or `[tool.uv.sources]` path references for wheel-consumed internal packages (`arkhai-kit-identity`, `arkhai-core`, `arkhai-core-buyer`, `arkhai-core-storefront`, `arkhai-kit-alkahest`, `arkhai-kit-config`, `arkhai-vms-provisioning`, `arkhai-core-storefront-client`, or `arkhai-core-registry-client`). These packages are resolved exclusively from wheels in `.dist/` outside their owning package's local dev environment.

**Why not `uv.sources` editable installs:** Editable path references are resolved relative to the project root at lockfile generation time, then embedded in `uv.lock`. Inside Docker that relative path does not exist, causing resolution failures. The wheel approach makes both the path and the mechanism context-specific (CLI flag, not lockfile entry).

### Internal wheel packages

Nine pure-Python internal packages are distributed as wheels:

| Package | Wheel name | Source | Primary consumers |
|---------|-----------|--------|-------------------|
| `arkhai-kit-identity` | `market_identity-*.whl` | `kit/identity/` | `arkhai-core`, `arkhai-core-registry`, `storefront` |
| `arkhai-core` | `market_core-*.whl` | `core/` | `arkhai-kit-alkahest`, `storefront` |
| `arkhai-core-buyer` | `core_buyer-*.whl` | `core/buyer/` | `buyer` |
| `arkhai-core-storefront` | `core_storefront-*.whl` | `core/storefront/` | `storefront` |
| `arkhai-kit-alkahest` | `market_alkahest-*.whl` | `kit/alkahest/` | `buyer`, `storefront`, `integration-tests` |
| `arkhai-kit-config` | `market_config-*.whl` | `kit/config/` | `buyer`, `storefront` |
| `arkhai-vms-provisioning` | `provisioning_service-*.whl` | `domains/vms/provisioning/service/` | `integration-tests`, `storefront` |
| `arkhai-core-storefront-client` | `arkhai_storefront_client-*.whl` | `core/storefront-client/` | `storefront`, `integration-tests`, `arkhai-vms-provisioning` |
| `arkhai-core-registry-client` | `arkhai_registry_client-*.whl` | `core/registry-client/` | `integration-tests` |

`arkhai-core-storefront-client` exists as a separate lightweight package to avoid pulling `arkhai-vms-storefront`'s heavyweight dependencies (`pufferlib`, `torch`, native RL wheels under the `[rl]` extra) into projects that only need the HTTP client and EIP-191 signing helper. The canonical implementation lives in `core/storefront-client/src/storefront_client/client.py` and exposes `StorefrontClient` (async) and `SyncStorefrontClient` (sync).

**Dependency direction note — arkhai-vms-provisioning → arkhai-core-storefront-client:**

The provisioning service depends on `arkhai-core-storefront-client` for two call sites:
1. `lease_lifecycle_service._patch_storefront_resource()` — PATCH storefront resource on lease expiry
2. `system_service.get_status()` — probe storefront reachability for the diagnostic status endpoint

This inverts the conceptual layer (provisioning is infrastructure; storefront is a consumer). It does not create a circular import — `storefront-client` has no dependency on `arkhai-vms-provisioning`. The `make dist` ordering already builds `arkhai-core-storefront-client` before `arkhai-vms-provisioning`, so wheel resolution is correct.

**`arkhai-core-storefront-client` versioning policy:**

`arkhai-core-storefront-client` encodes two contracts with the storefront server that are not enforced at import time — mismatches produce silent 403s or wrong response shapes at runtime:

1. **Auth message format** — `_build_auth_headers` must match `domains/vms/storefront/src/market_storefront/middleware/seller_auth.py`:
   - `create_listing` → `"create_listing:<agent_wallet_address>:<timestamp>"`
   - `close_listing` → `"close_listing:<listing_id>:<timestamp>"`

2. **Endpoint signatures** — `/api/v1/listings/create`,
   `/api/v1/listings/{listing_id}/close`, and `/alerts/resource`
   request/response shapes.

When either contract changes: bump `version` in `core/storefront-client/pyproject.toml`, update the minimum version constraint in all consuming `pyproject.toml` files, rebuild the wheel with `make dist-storefront-client`, and run `make init` in each consumer. Keep all changes in one commit so the version boundary is auditable in git history. See `core/storefront-client/README.md` for the full checklist.

### Distribution path

**Internal builds (Docker images):** `.dist/` wheels are consumed via
`--find-links` inside Docker `RUN` instructions. This path is unchanged.

**External distribution:** The three client packages (`arkhai-core-storefront-client`,
`arkhai-core-registry-client`, `arkhai-vms-provisioning`) are published to GCP Artifact
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
cd core/registry && make reinit && make test-integration
```

`reinit` runs `uv sync --upgrade-package <pkg> --reinstall-package <pkg>`. The `--upgrade-package` flag is essential: without it, `uv` re-installs whatever version is **pinned in the local `uv.lock`** rather than resolving the latest available wheel from `.dist/`. If `uv.lock` was generated when an older wheel was the only option, subsequent `make dist` runs that produce a higher version are silently ignored by `--reinstall-package` alone. `--upgrade-package` forces uv to re-resolve the constraint against the current contents of `.dist/` and update `uv.lock` to the new version.

### Client package inventory

| Package | Wheel | Async client | Sync client | Consumers |
|---|---|---|---|---|
| `arkhai-core-storefront-client` | `arkhai_storefront_client-*.whl` | `StorefrontClient` | `SyncStorefrontClient` | `storefront`, `integration-tests` |
| `core/registry-client/` | `arkhai_registry_client-*.whl` | `RegistryClient` | `SyncRegistryClient` | `integration-tests`, `arkhai-core-registry` tests |
| `domains/vms/provisioning/service/src/client/` | `provisioning_service-*.whl` | `ProvisioningClient` | `SyncProvisioningClient` | `storefront`, `integration-tests` |

`arkhai-core-storefront-client` exposes EIP-191-signed methods on both
`StorefrontClient` (async) and `SyncStorefrontClient` (sync):

- `negotiate_new()` / `negotiate_counter()` — take `token` and populate
  `fields["token"]` to match the on-chain `ERC20EscrowObligation.ObligationData`
  key; signing headers are added internally.
- `settle()` — `POST /api/v1/settle/{uid}` with EIP-191 auth.
- `get_settle_status()` — `GET /api/v1/settle/{uid}/status` with EIP-191
  auth.
- `evaluate_negotiate()` — `POST /api/v1/admin/listings/{id}/evaluate-negotiate`.

The wheel ships `EvaluateNegotiateResponse`, `SettleResponse`, and
`SettleStatusResponse` typed models alongside these methods.

`arkhai-vms-provisioning` bundles its client inside the service wheel (under `src/client/`) because the request/response models (`CreateVmRequest`, `JobStatusResponse`, etc.) are shared between the server and client. Consumers import as `from client.provisioning_client import ProvisioningClient`.

| Term | Meaning |
|---|---|
| Alkahest | Arkhai's smart contract suite for peer-to-peer agreements and escrow |
| Storefront | The seller-side HTTP server (`market-storefront serve`); the only running agent process in the negotiation flow |
| Identity | Scheme-tagged `(scheme, identifier)` pair; default scheme is `eip191` with the wallet address as identifier |
| FRP | Fast Reverse Proxy — used to give buyers network access to their VMs |
| Anvil | Local EVM testnet node from Foundry |
| EIP-191 | Personal-message signature scheme used to authenticate buyer↔seller HTTP request bodies |
| Policy callable | A registered function that evaluates a negotiation event and may return an action |
| Order | A published offer in the registry; carries `offer_resource`, `accepted_escrows`, status. The listing-create API requires `accepted_escrows` directly. |
