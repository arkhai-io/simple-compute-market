# storefront-client

Async and synchronous HTTP clients for the Arkhai storefront REST API.

Distributed as a pure-Python wheel (`arkhai_storefront_client-*.whl`) via
the monorepo `.dist/` directory.

## Usage

### Async (application code)

```python
from storefront_client import StorefrontClient

client = StorefrontClient("http://seller-storefront:8001", private_key="0x...")
async with client:
    reg = await client.get_registration()
    resp = await client.create_listing(
        agent_wallet_address="0xSellerWallet",
        offer={...},
        demand={...},
    )
```

### Sync (CLI commands, smoke tests, scripts)

```python
from storefront_client import SyncStorefrontClient

with SyncStorefrontClient("http://seller-storefront:8001", private_key="0x...") as client:
    reg = client.get_registration()
    resp = client.create_listing(
        agent_wallet_address="0xSellerWallet",
        offer={...},
        demand={...},
    )
```

## Surface

Both clients cover:

- `GET  /.well-known/erc-8004-registration.json`  → `get_registration`
- `POST /listings/create`                            → `create_listing`
- `POST /api/v1/listings/{listing_id}/close`         → `close_listing`
- `POST /listings/refund`                            → `refund_listing`
- `POST /listings/claim`                             → `claim_listing`
- `POST /listings/discover`                          → `discover_listings`
- `POST /alerts/resource`                          → `send_resource_alert`

Responses parse into typed dataclasses (`StorefrontOrderCreateResponse`,
etc.); the raw JSON is preserved on each model's `.extra` field for
forward-compat with new server fields.

## Versioning policy

**`storefront-client` versioning must stay in lockstep with the
storefront API.** Two contracts are not enforced by Python's type
system — mismatches produce silent 403s or unexpected response shapes
at runtime, not import errors:

### 1. Auth message format

```
create_listing   →  "create_listing:<agent_wallet_address>:<timestamp>"
close_listing    →  "close_listing:<listing_id>:<timestamp>"
refund_listing   →  "refund_listing:<listing_id>:<timestamp>"
claim_listing    →  "claim_listing:<listing_id>:<timestamp>"
discover_listings → "discover_listings:<listing_id>:<timestamp>"
```

If this format changes in `storefront/src/market_storefront/agent.py`,
bump `storefront-client` version and update `_build_auth_headers` in
`client.py` in the same commit.

### 2. Endpoint signatures

`/api/v1/listings/create`, `/api/v1/listings/{listing_id}/close`,
`/api/v1/listings/{listing_id}/refund`, `/listings/{claim,discover}`,
and `/alerts/resource` request and response shapes. If any field is
added, removed, or renamed, bump the version and update the
corresponding method in `client.py`.

### Version bump checklist

1. Update `client.py` and `models.py` to match the new server behaviour.
2. Bump `version` in `core/storefront-client/pyproject.toml`.
3. Run `make dist-storefront-client` to rebuild the wheel.
4. Run `make reinit` in each consuming project to pick up the new wheel.
