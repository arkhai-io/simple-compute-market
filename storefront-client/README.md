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
    resp = await client.create_order(
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
    resp = client.create_order(
        agent_wallet_address="0xSellerWallet",
        offer={...},
        demand={...},
    )
```

## Surface

Both clients cover:

- `GET  /.well-known/erc-8004-registration.json`  → `get_registration`
- `POST /orders/create`                            → `create_order`
- `POST /orders/close`                             → `close_order`
- `POST /orders/refund`                            → `refund_order`
- `POST /orders/claim`                             → `claim_order`
- `POST /orders/discover`                          → `discover_orders`
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
create_order   →  "create_order:<agent_wallet_address>:<timestamp>"
close_order    →  "close_order:<order_id>:<timestamp>"
refund_order   →  "refund_order:<order_id>:<timestamp>"
claim_order    →  "claim_order:<order_id>:<timestamp>"
discover_orders → "discover_orders:<order_id>:<timestamp>"
```

If this format changes in `storefront/src/market_storefront/agent.py`,
bump `storefront-client` version and update `_build_auth_headers` in
`client.py` in the same commit.

### 2. Endpoint signatures

`/orders/{create,close,refund,claim,discover}`, `/alerts/resource`
request and response shapes. If any field is added, removed, or
renamed, bump the version and update the corresponding method in
`client.py`.

### Version bump checklist

1. Update `client.py` and `models.py` to match the new server behaviour.
2. Bump `version` in `storefront-client/pyproject.toml`.
3. Run `make dist-storefront-client` to rebuild the wheel.
4. Run `make reinit` in each consuming project to pick up the new wheel.
