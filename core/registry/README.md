# Listing Registry

FastAPI service that stores published marketplace listings and serves
them through a filter-spec-driven discovery API. Publishers authenticate
mutations with the body-bound marketplace signature version 2 contract.
Stable publisher rows and listings are owned through canonical
`{scheme, identifier}` principal bindings.

## Features

- `GET /listings` with filter-spec-driven discovery (filters declared
  in `filter-spec.yaml`; ETag-gated invalidation).
- `POST /listings` lazily creates a stable publisher on first verified
  publication.
- Ed25519 and EIP-191 principals use the same signer-injected wire contract.
- Publisher identity rotation requires proofs by both the current and
  replacement principals, with bounded overlap and explicit retirement.
- Optional API-key auth, gated independently for read and write
  (`REGISTRY_REQUIRE_READ_API_KEY`, `REGISTRY_REQUIRE_WRITE_API_KEY`);
  keys carry a read/write scope.
- Authority-authenticated self-description at
  `/.well-known/arkhai/registry-descriptor.json`.

## Quick start (local docker-compose)

```bash
# From repo root — brings up anvil (contracts pre-baked), registry, both
# storefronts and provisioning.
docker compose up -d

# Direct registry probe (no API key required by default):
curl http://localhost:8080/health
curl http://localhost:8080/publishers
curl 'http://localhost:8080/listings?limit=10'
```

## Running standalone

```bash
cd core/registry
uv sync
DATABASE_URL=sqlite:///./indexer.db uv run uvicorn src.main:app --port 8080
```

## API key auth

Read access (discovery, lookups) and write access (publish/update/delete
listings and publisher rotation) gate independently via `REGISTRY_REQUIRE_READ_API_KEY`
and `REGISTRY_REQUIRE_WRITE_API_KEY`. When a gate is on, the matching
routes require `Authorization: Bearer <key>` against an active row in
`api_keys`; write routes additionally require the key's scope to be
`write` (a write key also satisfies reads). Operators mint keys via
`POST /admin/api-keys` (gated by `REGISTRY_ADMIN_API_KEY`), passing
`scope: read|write`; a single write-scoped bootstrap key can be seeded
via `REGISTRY_BOOTSTRAP_API_KEY` on first start.

## Registry descriptor

Startup requires `REGISTRY_DESCRIPTOR_BASE_URL`,
`REGISTRY_DESCRIPTOR_DISPLAY_NAME`, and
`REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY`. The service combines those public
operator assertions with the active authority signer, filter-spec schema, and
read gate. If reads require an API key,
`REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER` is also required; public
registries reject that setting.

Authenticated buyers, sellers, and services can bootstrap from only a URL and
their own signer with `RegistryClient.bootstrap_registry_descriptor()`. That
method verifies the response against the principals carried in the descriptor
before returning it. A normally constructed, externally pinned client uses
`get_registry_descriptor()` instead. The endpoint does not require the registry
read key, so a caller can discover the acquisition pointer first. Its signed
response proves possession of the registry signing credential; it is not
third-party endorsement of the operator or URL.

## Database

- Dev: SQLite (`DATABASE_URL=sqlite:///./indexer.db`)
- Production: Postgres (`DATABASE_URL=postgresql://...`)

Schema is managed by Alembic. Apply migrations with `make migrate`.

## API endpoints

Service documentation is served at `/docs` (Swagger UI). The interesting
endpoints:

- `GET /health`
- `GET /publishers` / `GET /publishers/{publisher_id}`
- `POST /listings` (marketplace signature version 2)
- `GET /listings` (filter-spec-driven discovery)
- `PUT /listings/{listing_id}` (marketplace signature version 2)
- `DELETE /listings/{listing_id}` (marketplace signature version 2)
- `POST /publishers/{publisher_id}/identity-rotations`
- `POST /publishers/{publisher_id}/identity-rotations/{nonce}/retire`
- `GET /filter-spec` (returns the active filter spec + ETag)
- `GET /.well-known/arkhai/registry-descriptor.json` (signed self-description)
- `POST /admin/api-keys` (admin)
- `GET /api/v1/system/config`
- `GET /api/v1/system/stats`

## Identity format

Publishers have stable local IDs and one or more lifecycle bindings to strict
marketplace principals. EIP-191 identifiers are normalized lowercase
addresses; Ed25519 identifiers are canonical unpadded base64url public keys.
Authorization compares the complete principal, never identifier text alone.
Legacy valid owner addresses migrate to EIP-191 principals before the version
2 routes serve traffic; malformed, duplicate, or incomplete populations abort.
