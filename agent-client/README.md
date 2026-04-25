# agent-client

Lightweight async HTTP client for the Arkhai agent REST API.

Distributed as a pure-Python wheel (`agent_client-*.whl`) via the monorepo
`.dist/` directory. Consumed by `integration-tests` and any other project
that needs to call the agent over HTTP without depending on the full
`market-core` package.

## Usage

```python
from agent_client import AgentClient
import aiohttp

client = AgentClient("http://seller-agent:8001", private_key="0x...")
async with aiohttp.ClientSession() as session:
    resp = await client.create_order(
        session,
        agent_wallet_address="0xSellerWallet",
        offer={...},
        demand={...},
    )
```

## Versioning policy

**`agent-client` versioning must stay in lockstep with the agent API.**

This package encodes two contracts that are not enforced by Python's type
system at import time — mismatches produce silent 403s or unexpected
response shapes at runtime, not import errors:

### 1. Auth message format

The EIP-191 signed message format is defined in `_check_agent_request_auth`
in `core/agent/app/agent.py`:

```
create_order  →  "create_order:<agent_wallet_address>:<timestamp>"
close_order   →  "close_order:<order_id>:<timestamp>"
```

If this format changes in `agent.py`, bump `agent-client` version and
update `_build_auth_headers` in `client.py` in the same commit.

### 2. Endpoint signatures

`/orders/create`, `/orders/close`, `/alerts/resource` request and response
shapes are defined in `core/agent/app/agent.py`. If any field is added,
removed, or renamed, bump the `agent-client` version and update the
corresponding method in `client.py`.

### Version bump checklist

When either contract changes:

1. Update `client.py` to match the new server behaviour.
2. Bump `version` in `agent-client/pyproject.toml`.
3. Update the minimum version constraint in every consuming project's
   `pyproject.toml` (currently: `integration-tests`).
4. Run `make dist-agent-client` to rebuild the wheel.
5. Run `make init` in each consuming project to pick up the new wheel.

Keeping these steps in a single commit makes the version boundary auditable
in git history.
