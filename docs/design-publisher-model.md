# Registry publisher model — design + scope

Replaces the registry's ERC-8004 "agent" concept with a publisher model:
a listing is owned by a publisher, and a publisher is identified by one or
more signing identities. See `ARCHITECTURE.md` → "Organizing Principle"
for why settlement parameters stay opaque to the indexer.

## Background

The registry began as an ERC-8004 agent indexer. An "agent" was an
on-chain identity — an NFT in the IdentityRegistry — with an agent card
(name, A2A/MCP endpoints, supported trust models), reputation and
validation registries, and health monitoring. A background EventSync
watched the chain and indexed those identities, so a storefront was
registered and indexed independently of any listing it published.

Identity is now an Ethereum address that signs: a request is
authenticated by recovering the signer from an EIP-191 signature. Under
that model an "agent" carries no remaining content — a row created for a
publishing wallet has an empty agent card, no token URI, no on-chain
registration, no health. One fact persists: a wallet published a listing
and can authorize changes to it. That is a publisher.

## The model

A **publisher** owns listings. It is identified by one or more
**identities**, each a `(scheme, identifier)` pair — today a single
`eip191` wallet address. A **listing** belongs to a publisher.

| Table | Columns | Notes |
|---|---|---|
| `publishers` | `publisher_id` (PK, surrogate), `storefront_url`, `created_at` | The principal. `storefront_url` is where buyers reach it to negotiate — was the per-listing `seller` field. |
| `identities` | `id`, `publisher_id` (FK), `scheme`, `identifier`, `created_at`; unique `(scheme, identifier)` | A verified signing identity. One `eip191` row per publisher today; the seam for linking more. |
| `listings` | `listing_id` (PK), `publisher_id` (FK), `offer_resource`, `accepted_escrows`, `max_duration_seconds`, `oracle_address`, `status`, timestamps | Escrow/settlement params opaque. |

Lazy creation: on the first signed publish from identity `(eip191, W)`,
the registry looks up the identity; on a miss it creates a publisher
(setting `storefront_url` from the publish payload) and the identity row.
Nothing is registered ahead of time — the publisher exists because it
published.

`publisher_id` is local to each indexer. Correlating a publisher across
registries happens through the shared `(scheme, identifier)` claims, not
the surrogate id.

## Settlement parameters stay opaque

A listing's `accepted_escrows` is settlement-schema data. The indexer
stores it and filters on the paths its `filter-spec.yaml` declares (e.g.
`literal_fields.token`); it does not interpret escrow semantics.

The payment recipient is part of that opaque data, not registry
structure. In the alkahest settlement schema a specific recipient is one
composable demand — `AllArbiter([RecipientArbiter, …], [encode(recipient),
…])` — encoded into the escrow's demand bytes and checked at settlement.
Generalized, the recipient is a parameter of `settle`, defined by the
settlement schema. A future per-escrow recipient (decoupling payee from
signer, enabling non-EVM or per-chain payout) is a settlement-side change
and adds no registry table or column.

Today the recipient is not in the listing at all: the buyer fetches the
seller's single wallet from `/.well-known/agent-wallet.json` and reuses it
as the recipient on every chain, which is why cross-chain currently means
"EVM chains sharing one address." That constraint is independent of this
refactor.

## Routes

| Before | After |
|---|---|
| `POST /agents/{wallet}/listings` | `POST /listings` — publishing identity + signature in the signed body |
| `GET /agents/{wallet}/listings` | `GET /listings?publisher=<identifier>` |
| `PUT /listings/{id}`, `DELETE /listings/{id}` | unchanged; signature verified against the listing's publisher identity |
| `GET /listings`, `GET /listings/{id}` | unchanged; response carries `storefront_url` (joined from the publisher) |
| `GET /agents/{id}` | `GET /publishers/{publisher_id}` — the publisher entity: `storefront_url`, `identities` (the `(scheme, identifier)` list), `created_at` |
| `GET /agents` | `GET /publishers` — list publishers; optional `?identifier=` / `?scheme=` filter to resolve a publisher by a signing identity |
| `GET /agents/search` | removed — agent-card search has nothing to query under the publisher model |
| `POST /agents/{id}/heartbeat` | removed |

A publisher is addressed in the path by its surrogate `publisher_id` (the
value listings carry); the `?identifier=` filter on the list endpoint is
the lookup-by-signing-identity path.

Signature messages are unchanged: `create_listing:<identifier>:<ts>`,
`update_listing:<listing_id>:<ts>`, `delete_listing:<listing_id>:<ts>`.

## Removed

- Registry: `GET /agents/search` and `POST /agents/{id}/heartbeat` (the
  list and single-agent GETs become the publisher endpoints above); the
  `AgentMetadataEntry` and `HealthCheck` tables; the agent health-check
  background service; `/api/v1/system/sync` EventSync reporting and
  `/api/v1/system/sync/wait-for-agent`; the legacy ERC-8004 columns
  (`agent_id`, `chain_id`, `identity_registry`, `onchain_agent_id`,
  `registry_address`, `token_uri`, agent metadata, health status,
  heartbeat); the vestigial `listings.buyer` column.
- Storefront: `/api/v1/system/wait-for-registry-agent`,
  `wait_for_registry_agent` / `registry_auth_check` /
  `_registry_auth_per_chain`, the `registry_auth` field in
  `/system/status`, the stale `register` CLI doc text.
- registry-client: `search_agents`, `heartbeat`, `wait_for_agent_indexed`.
  `list_agents` / `get_agent` become `list_publishers` / `get_publisher`,
  and `AgentSummary` / `AgentListResponse` become `Publisher` /
  `PublisherListResponse`.
- storefront-client: `wait_for_registry_agent_ready` (async + sync) and
  `RegistryAgentReadyResponse`.
- e2e: the "agent indexed" stages (`SellerAgentIndexed` in the full deal;
  `BobIndexed` / `AliceIndexed` in multi-registry). They assert an agent
  is indexed before publishing; the lazy model replaces that with "the
  publisher exists after publishing."

## Migration

`init_db()` builds fresh databases from the models, so a clean checkout
gets the three-table shape directly. The Alembic migration transforms an
existing database: create `publishers` and `identities`, add
`listings.publisher_id`, move each agent row to a publisher (plus an
eip191 identity) and repoint its listings, set `storefront_url` from the
agent's listings' `seller`, then drop `agents`, `agent_metadata`,
`health_checks`, and `listings.{agent_id, seller, buyer}`.

## Phases

Each phase keeps its package's own tests green; the end-to-end suite goes
green at the last phase, once the wire change has landed across packages.

1. **Registry** — models, migration, lazy publisher/identity creation,
   route changes, remove agent routes + health-check service + metadata
   tables. Registry suite rewritten and green.
2. **registry-client** — drop agent methods/models, point publish/query at
   the new routes, bump the wheel.
3. **storefront + storefront-client** — remove the wait-for-registry-agent
   flow and `registry_auth`, repoint the publish path, hoist
   `storefront_url`, bump storefront-client. Storefront suite green.
4. **e2e** — delete the agent-indexed stages, assert the publisher resolves
   after publish; rebuild images and run the full-deal and multi-registry
   suites green.

## Deferred / non-goals

- Multiple identities per publisher in practice. The `identities` table
  admits more than one `(scheme, identifier)`, but linking them needs a
  cross-signing protocol — each claimed key signs an attestation binding
  it to the publisher — which is out of scope.
- Per-chain or non-EVM payout. Decoupling the recipient from the signing
  identity is a settlement-schema change, independent of these tables.
- External identity aggregation. Whether identity linking is authoritative
  per-registry or projected from a shared layer is unresolved; the model
  forecloses neither.
- A feedback / reputation table. The `publishers` row is the FK anchor
  such a table would join to, but it is not built here.

## File map

```
registry-service/src/db/models.py             publishers + identities + listings; drop Agent/AgentMetadataEntry/HealthCheck
registry-service/alembic/versions/014_*.py     the transform migration
registry-service/src/api/publisher_routes.py    GET /publishers, GET /publishers/{id} (was agent_routes.py)
registry-service/src/api/listing_routes.py     publish/query repointed to the publisher model
registry-service/src/api/utils.py              ensure_publisher_for_identity (was ensure_agent_for_eip191)
registry-service/src/api/system_routes.py      drop /sync EventSync + /sync/wait-for-agent
registry-service/src/services/health_check.py  removed
registry-client/src/registry_client/           drop agent methods/models; publish/query route change
storefront/.../services/system_service.py      drop wait_for_registry_agent / registry_auth
storefront/.../controllers/system_controller.py  drop the wait-for-registry-agent endpoint
storefront/.../utils/multi_registry_client.py  drop wait_for_agent_indexed
storefront-client/.../client.py                drop wait_for_registry_agent_ready
integration-tests/tests/e2e/...                drop the agent-indexed stages
```

## References

- `ARCHITECTURE.md` → "Organizing Principle: composition from above and
  below" — settlement is from-below; the registry is schema-authority for
  the listing and discovery shape.
- ERC-8004 removal: commits `bf3b1d5` (drop the identity scheme),
  `bc947a9` (drop the contracts submodules).
