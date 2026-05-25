# Indexer quickstart

How to stand up your own indexer registry. Reasons to run one:

- **Curate which sellers can publish and which buyers can query**
  (bearer-token auth, §6).
- **No third-party rate limits.**
- **Custom `filter-spec.yaml`** — the vocabulary for `gpu_model`,
  `region`, etc. is per-indexer.
- **Solo testing** — no fanout.

`compose/seller.yml` is registry-agnostic, so an indexer can run on
the same host as a seller or anywhere else.

## 1. Build the image

```bash
make build-registry
```

Produces `arkhai:registry`.

## 2. Configure

```bash
cp config.registry.env.example config.registry.env
$EDITOR config.registry.env
```

Fill in:

- `RPC_URL` — your Base Sepolia RPC endpoint.
- `REGISTRY_ADMIN_API_KEY` — operator-only secret used to mint/revoke
  per-user keys at `/admin/api-keys`. Generate with `openssl rand -hex 32`.
- `REGISTRY_BOOTSTRAP_API_KEY` — the bearer token sellers and buyers
  will use until per-user keys are minted. Same `openssl rand -hex 32`
  pattern. This is the shared secret you give out.

Defaults already set: chain ID 84532, ERC-8004 contract addresses,
`REGISTRY_START_BLOCK` (deep enough to catch historical agents),
`REGISTRY_REQUIRE_API_KEY=true` (private indexer).

For a fully public indexer (anyone can publish and query) set
`REGISTRY_REQUIRE_API_KEY=false` and drop the two key vars.

## 3. Bring it up

```bash
docker compose -f compose/registry.yml up -d

# or, sharing a docker network with a seller stack:
docker compose -f compose/seller.yml -f compose/registry.yml up -d
```

The compose file mounts a named volume at `/app/data` so the sqlite
state persists across restarts.

## 4. Wire sellers and buyers

In each storefront / buyer TOML:

```toml
[registry]
urls = ["http://<INDEXER_HOST>:8080"]
```

When the indexer and seller share a docker network, use the service
name: `urls = ["http://registry:8080"]`.

## 5. Checks

```bash
curl -sf http://<INDEXER_HOST>:8080/health

docker compose logs registry | grep -i "Synced up to block"

curl -s http://<INDEXER_HOST>:8080/filter-spec | jq

# Listings — note the full canonical agent ID, URL-encoded:
curl -s "http://<INDEXER_HOST>:8080/agents/eip155%3A84532%3A0x8004A818BFB912233c491871b3d84c89A494BD9e%3A<N>/listings" \
  | jq
```

## 6. Bearer-token auth

`config.registry.env.example` ships with `REGISTRY_REQUIRE_API_KEY=true`
already set. To disable auth (fully public indexer) flip it to `false`
and drop the two key vars.

Flow:

- Admin mints/revokes per-user keys: `POST /admin/api-keys` with
  `Authorization: Bearer <REGISTRY_ADMIN_API_KEY>`.
- Sellers and buyers send `Authorization: Bearer <api_key>` on every
  request, configured via each side's `[registry.auth]` block. Keys
  must match the URL in `[registry] urls` exactly (scheme, host, port,
  no trailing slash).

In the seller / buyer TOML:

```toml
[registry.auth]
"http://<INDEXER_HOST>:8080" = "<api_key>"
```
