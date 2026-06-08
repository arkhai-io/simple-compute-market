# Registry Indexer

FastAPI service that stores published marketplace listings and serves
them through a filter-spec-driven discovery API. Sellers publish via
signed `POST /agents/{wallet}/listings`; buyers query `GET /listings`.

After the pluggable-identity refactor the registry doesn't read any
on-chain contracts. Agent rows are created lazily on first signed
publication — signature recovery is the trust anchor.

## Features

- `GET /listings` with filter-spec-driven discovery (filters declared
  in `filter-spec.yaml`; ETag-gated invalidation).
- `POST /agents/{wallet}/listings` lazy-creates agent rows on first
  signed publication.
- Scheme-tagged identity storage: `(scheme, identifier)` is the canonical
  agent key. `eip191` (wallet address) is the only built-in scheme.
- Optional API-key auth, gated independently for read and write
  (`REGISTRY_REQUIRE_READ_API_KEY`, `REGISTRY_REQUIRE_WRITE_API_KEY`);
  keys carry a read/write scope.

## Quick start (local docker-compose)

```bash
# From repo root — brings up anvil (contracts pre-baked), registry, both
# storefronts and provisioning.
docker compose up -d

# Direct registry probe (no API key required by default):
curl http://localhost:8080/health
curl http://localhost:8080/agents
curl 'http://localhost:8080/listings?limit=10'
```

## Running standalone

```bash
cd registry-service
uv sync
DATABASE_URL=sqlite:///./indexer.db uv run uvicorn src.main:app --port 8080
```

## API key auth

Read access (discovery, lookups) and write access (publish/update/delete
listings, heartbeat) gate independently via `REGISTRY_REQUIRE_READ_API_KEY`
and `REGISTRY_REQUIRE_WRITE_API_KEY`. When a gate is on, the matching
routes require `Authorization: Bearer <key>` against an active row in
`api_keys`; write routes additionally require the key's scope to be
`write` (a write key also satisfies reads). Operators mint keys via
`POST /admin/api-keys` (gated by `REGISTRY_ADMIN_API_KEY`), passing
`scope: read|write`; a single write-scoped bootstrap key can be seeded
via `REGISTRY_BOOTSTRAP_API_KEY` on first start.

## Database

- Dev: SQLite (`DATABASE_URL=sqlite:///./indexer.db`)
- Production: Postgres (`DATABASE_URL=postgresql://...`)

Schema is managed by Alembic. Apply migrations with `make migrate`.

## API endpoints

Service documentation is served at `/docs` (Swagger UI). The interesting
endpoints:

- `GET /health`
- `GET /agents` / `GET /agents/{agent_id}` / `GET /agents/search`
- `POST /agents/{wallet}/listings` (signed)
- `GET /agents/{wallet}/listings`
- `GET /listings` (filter-spec-driven discovery)
- `PUT /listings/{listing_id}` (signed)
- `DELETE /listings/{listing_id}` (signed)
- `GET /filter-spec` (returns the active filter spec + ETag)
- `POST /admin/api-keys` (admin)
- `GET /api/v1/system/config`
- `GET /api/v1/system/stats`

## Identity format

Agents are keyed on `(scheme, identifier)`. The default and only
built-in scheme is `eip191` with the lowercase wallet address as
identifier. Legacy ERC-8004 canonical agent IDs (`eip155:...`) still
resolve via a back-compat lookup on the deprecated `agents.agent_id`
column for rows that pre-date the migration.

Custom schemes can register via
`market_identity.register_identity_scheme(verifier)` in a fork.
