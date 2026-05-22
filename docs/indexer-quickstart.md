# Indexer quickstart

How to stand up your own indexer registry. Reasons to run one:

- **Curate which sellers can publish and which buyers can query**
  (bearer-token auth, §4).
- **No third-party rate limits.**
- **Custom `filter-spec.yaml`** — the vocabulary for `gpu_model`,
  `region`, etc. is per-indexer.
- **Solo testing** — no fanout.

`compose/seller.yml` is registry-agnostic, so an indexer can run on
the same host as a seller or anywhere else.

## 1. Compose

Put `compose.registry.yml` next to `compose/seller.yml` (or wherever you
like) and share its network:

```yaml
services:
  registry:
    image: arkhai:registry
    ports: ["8080:8080"]
    environment:
      - DATABASE_URL=sqlite:///./indexer.db
      - CHAIN_ID=84532
      - RPC_URL=https://base-sepolia.infura.io/v3/<YOUR_KEY>
      - IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e
      - REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713
      # Backfill past your earliest agent registration. Without this the
      # first sync only walks the last 1000 blocks and silently drops
      # any historical agent.
      - REGISTRY_START_BLOCK=41707000
      - PORT=8080
      - HOST=0.0.0.0
      # See §4 for the auth-on variant. Leave these out for a fully
      # public registry — anyone can publish and query.
    networks:
      - seller
    restart: unless-stopped

networks:
  seller:
```

Don't mark the network `external: true` — the first `up -d` would fail
because it doesn't exist yet.

Bring it up:

```bash
docker compose -f compose.registry.yml up -d
# or, sharing a stack with a seller:
docker compose -f compose/seller.yml -f compose.registry.yml up -d
```

## 2. Wire sellers and buyers

In each storefront / buyer TOML:

```toml
[registry]
urls = ["http://<INDEXER_HOST>:8080"]
```

When the indexer and seller share a docker network, use the service
name: `urls = ["http://registry:8080"]`.

## 3. Checks

```bash
curl -sf http://<INDEXER_HOST>:8080/health

docker compose logs registry | grep -i "Synced up to block"

curl -s http://<INDEXER_HOST>:8080/filter-spec | jq

# Listings — note the full canonical agent ID, URL-encoded:
curl -s "http://<INDEXER_HOST>:8080/agents/eip155%3A84532%3A0x8004A818BFB912233c491871b3d84c89A494BD9e%3A<N>/listings" \
  | jq
```

## 4. Bearer-token auth (optional)

To gate publishes and queries behind shared secrets, add these to the
`registry` service env:

```yaml
      - REGISTRY_REQUIRE_API_KEY=true
      # Gates /admin/api-keys for minting/revoking per-user keys.
      - REGISTRY_ADMIN_API_KEY=admin-secret-rotate-this
      # Seeds one api_keys row on first boot if the table is empty.
      # Lets you come up with one operator-known key without a
      # separate admin orchestration step.
      - REGISTRY_BOOTSTRAP_API_KEY=shared-bootstrap-token
```

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
