# agent-client

Async and synchronous HTTP clients for the Arkhai agent REST API.

Distributed as a pure-Python wheel (`arkhai_agent_client-*.whl`) via the
monorepo `.dist/` directory.

## Usage

### Async (application code)

```python
from agent_client import AgentClient

client = AgentClient("http://seller-agent:8001", private_key="0x...")
async with client:
    reg = await client.get_registration()
    resp = await client.create_order(
        agent_wallet_address="0xSellerWallet",
        offer={...},
        demand={...},
    )
```

### Sync (smoke tests, scripts)

```python
from agent_client import SyncAgentClient

client = SyncAgentClient("http://seller-agent:8001", private_key="0x...")
reg = client.get_registration()
client.close()
```

## Versioning policy

**`agent-client` versioning must stay in lockstep with the agent API.**

Two contracts are not enforced by Python's type system — mismatches produce
silent 403s or unexpected response shapes at runtime, not import errors:

### 1. Auth message format

```
create_order  →  "create_order:<agent_wallet_address>:<timestamp>"
close_order   →  "close_order:<order_id>:<timestamp>"
```

If this format changes in `agent.py`, bump `agent-client` version and update
`_build_auth_headers` in `client.py` in the same commit.

### 2. Endpoint signatures

`/orders/create`, `/orders/close`, `/alerts/resource` request and response
shapes. If any field is added, removed, or renamed, bump the version and
update the corresponding method in `client.py`.

### Version bump checklist

1. Update `client.py` to match the new server behaviour.
2. Bump `version` in `agent-client/pyproject.toml`.
3. Run `make dist-agent-client` to rebuild the wheel.
4. Run `make reinit` in each consuming project to pick up the new wheel.
