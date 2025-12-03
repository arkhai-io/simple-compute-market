# Agent Integration with ERC-8004 Registry

This document explains how agents (like `a2a-agent-trader`) integrate with the ERC-8004 registry for discovery, registration, and health monitoring.

## Overview

The ERC-8004 registry serves as the central hub for agent discovery and trust. Agents register themselves on-chain via ERC-8004 contracts, while the registry maintains an off-chain index for fast queries and health monitoring.

## Architecture Flow

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│                 │         │                  │         │                 │
│   Agent         │────────▶│  ERC-8004        │────────▶│  Blockchain     │
│  (a2a-agent)   │ Register│  Contracts       │         │  (Base Sepolia) │
│                 │         │                  │         │                 │
└─────────────────┘         └──────────────────┘         └─────────────────┘
       │                              │
       │                              │
       │ Heartbeat                    │ Event Sync
       │                              │
       ▼                              ▼
┌─────────────────┐         ┌──────────────────┐
│                 │         │                  │
│  erc-8004-      │◀────────│  Off-chain       │
│  registry-py    │  Query  │  Database        │
│                 │         │  (SQLite/PG)     │
└─────────────────┘         └──────────────────┘
       ▲
       │
       │ Discover
       │
┌─────────────────┐
│                 │
│   Clients/      │
│   Discoverers   │
└─────────────────┘
```

## Integration Points

### 1. Agent Registration

Agents register themselves on-chain via ERC-8004 IdentityRegistry, then the registry syncs this data to its off-chain database.

#### On-Chain Registration (Recommended)

```python
from web3 import Web3
from src.contracts.identity_registry import IdentityRegistryClient
from src.types import NetworkConfig, AgentMetadata

# Initialize registry client
network_config = NetworkConfig(
    chain_id=84532,  # Base Sepolia
    rpc_url="https://sepolia.base.org",
    identity_registry="0x8004AA63c570c570eBF15376c0dB199918BFe9Fb",
    # ... other addresses
)

# Use agent's wallet for registration
registry_client = IdentityRegistryClient(
    network_config,
    private_key=os.getenv("AGENT_PRIV_KEY")
)

# Prepare agent card metadata
agent_card_uri = "https://ipfs.io/ipfs/Qm..."  # Upload agent card to IPFS
metadata = [
    AgentMetadata(key="agentName", value="Trading Agent"),
    AgentMetadata(key="agentUrl", value="https://agent.example.com"),
    AgentMetadata(key="agentVersion", value="1.0.0"),
]

# Register on-chain
tx_hash = registry_client.register(
    to=agent_wallet_address,
    token_uri=agent_card_uri,
    metadata=metadata
)

# Wait for confirmation
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
agent_id = receipt.logs[0].args.agentId  # Extract agent ID from event
```

#### Off-Chain Registration (Quick Start)

For development or when on-chain registration isn't immediately needed:

```python
import requests

# Register via registry API
response = requests.post(
    "http://localhost:8080/agents/register",
    json={
        "agent_card": {
            "name": "Trading Agent",
            "description": "AI agent for trading computational resources",
            "url": "https://agent.example.com",
            "version": "1.0.0",
            "skills": [...],
            "capabilities": {"streaming": True}
        },
        "owner": "0x...",  # Agent wallet address
        "labels": {
            "category": "trading",
            "environment": "production"
        }
    }
)

agent_data = response.json()
agent_id = agent_data["id"]
```

### 2. Heartbeat Mechanism

Agents send periodic heartbeats to maintain their health status in the registry.

```python
import asyncio
import aiohttp
from datetime import datetime

class AgentHeartbeat:
    def __init__(self, registry_url: str, agent_id: str, interval: int = 30):
        self.registry_url = registry_url
        self.agent_id = agent_id
        self.interval = interval
        self.is_running = False
    
    async def start(self):
        """Start sending heartbeats"""
        self.is_running = True
        while self.is_running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.registry_url}/agents/{self.agent_id}/heartbeat"
                    ) as response:
                        if response.status == 200:
                            print(f"[{datetime.now()}] Heartbeat sent successfully")
                        else:
                            print(f"[{datetime.now()}] Heartbeat failed: {response.status}")
            except Exception as e:
                print(f"[{datetime.now()}] Heartbeat error: {e}")
            
            await asyncio.sleep(self.interval)
    
    def stop(self):
        """Stop sending heartbeats"""
        self.is_running = False

# In your agent startup code
heartbeat = AgentHeartbeat(
    registry_url="http://localhost:8080",
    agent_id=agent_id,
    interval=30  # Send heartbeat every 30 seconds
)
asyncio.create_task(heartbeat.start())
```

### 3. Agent Discovery

Clients and other agents can discover registered agents through the registry API.

#### Search for Agents

```python
import requests

# Search by keyword
response = requests.get(
    "http://localhost:8080/agents/search",
    params={"q": "trading"}
)

agents = response.json()["items"]
for agent in agents:
    print(f"Found agent: {agent['name']} ({agent['id']})")
    print(f"  Status: {agent['status']}")
    print(f"  URL: {agent['url']}")

# List agents with filters
response = requests.get(
    "http://localhost:8080/agents",
    params={
        "q": "trading",
        "limit": 10,
        "offset": 0
    }
)

agents = response.json()["items"]
```

#### Get Agent Details

```python
# Get full agent details
response = requests.get(
    f"http://localhost:8080/agents/{agent_id}"
)

agent = response.json()
print(f"Agent: {agent['id']}")
print(f"  Chain ID: {agent['chainId']}")
print(f"  Registry: {agent['registryAddress']}")
print(f"  Token URI: {agent['tokenURI']}")
print(f"  Health Status: {agent['healthStatus']}")
print(f"  Metadata: {agent['metadata']}")
```

### 4. Health Monitoring

The registry automatically monitors agent health through:
- **Heartbeat tracking**: Agents that don't send heartbeats are marked as stale
- **Endpoint checking**: The registry periodically checks agent endpoints
- **Status updates**: Health status is updated in real-time

Agents should:
1. Send heartbeats regularly (every 30-60 seconds)
2. Ensure their endpoint is accessible
3. Respond to health check requests

### 5. On-Chain Identity Resolution

Agents can resolve their ERC-8004 identity from on-chain data:

```python
from src.contracts.identity_registry import IdentityRegistryClient

# Get agent identity from on-chain
registry_client = IdentityRegistryClient(network_config)
agent_id = 123  # ERC-721 token ID

# Get agent details
token_uri = registry_client.get_token_uri(agent_id)
owner = registry_client.get_owner(agent_id)
agent_name = registry_client.get_metadata(agent_id, "agentName")

# Construct full identity
agent_identity = {
    "namespace": "eip155",
    "chainId": network_config.chain_id,
    "identityRegistry": network_config.identity_registry,
    "agentId": agent_id,
    "tokenURI": token_uri,
    "owner": owner,
    "name": agent_name
}
```

## Complete Agent Integration Example

Here's a complete example of how an agent integrates with the registry:

```python
import os
import asyncio
import aiohttp
from src.contracts.identity_registry import IdentityRegistryClient
from src.types import NetworkConfig, AgentMetadata

class AgentRegistryIntegration:
    def __init__(self):
        self.agent_id = None
        self.registry_url = os.getenv("REGISTRY_URL", "http://localhost:8080")
        self.network_config = NetworkConfig(
            chain_id=int(os.getenv("CHAIN_ID", "84532")),
            rpc_url=os.getenv("RPC_URL"),
            identity_registry=os.getenv("IDENTITY_REGISTRY_ADDRESS"),
            # ... other addresses
        )
        self.heartbeat_task = None
    
    async def register_agent(self, agent_card: dict, agent_wallet: str):
        """Register agent with the registry"""
        # Option 1: Register via API (off-chain, faster)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.registry_url}/agents/register",
                json={
                    "agent_card": agent_card,
                    "owner": agent_wallet,
                    "labels": {
                        "environment": os.getenv("ENVIRONMENT", "development")
                    }
                }
            ) as response:
                if response.status == 201:
                    data = await response.json()
                    self.agent_id = data["id"]
                    print(f"Agent registered: {self.agent_id}")
                    return self.agent_id
                else:
                    error = await response.text()
                    raise Exception(f"Registration failed: {error}")
    
    async def start_heartbeat(self, interval: int = 30):
        """Start sending heartbeats"""
        if not self.agent_id:
            raise ValueError("Agent must be registered first")
        
        async def heartbeat_loop():
            while True:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.registry_url}/agents/{self.agent_id}/heartbeat"
                        ) as response:
                            if response.status == 200:
                                print(f"Heartbeat sent: {self.agent_id}")
                            else:
                                print(f"Heartbeat failed: {response.status}")
                except Exception as e:
                    print(f"Heartbeat error: {e}")
                
                await asyncio.sleep(interval)
        
        self.heartbeat_task = asyncio.create_task(heartbeat_loop())
    
    async def discover_agents(self, query: str = None):
        """Discover other agents"""
        url = f"{self.registry_url}/agents/search" if query else f"{self.registry_url}/agents"
        params = {"q": query} if query else {}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("items", [])
                else:
                    return []
    
    async def get_agent_details(self, agent_id: str):
        """Get details of a specific agent"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.registry_url}/agents/{agent_id}"
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None
    
    def stop(self):
        """Stop heartbeat"""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()

# Usage in agent code
async def main():
    integration = AgentRegistryIntegration()
    
    # Register agent
    agent_card = {
        "name": "Trading Agent",
        "description": "AI agent for trading",
        "url": "https://agent.example.com",
        "version": "1.0.0",
        "skills": [...],
        "capabilities": {"streaming": True}
    }
    
    agent_id = await integration.register_agent(
        agent_card,
        os.getenv("AGENT_WALLET_ADDRESS")
    )
    
    # Start heartbeat
    await integration.start_heartbeat(interval=30)
    
    # Discover other agents
    trading_agents = await integration.discover_agents("trading")
    print(f"Found {len(trading_agents)} trading agents")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        integration.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

## Integration Checklist

For agents integrating with the ERC-8004 registry:

- [ ] **Registration**
  - [ ] Register agent on-chain via IdentityRegistry (production)
  - [ ] Or register via registry API (development)
  - [ ] Store agent ID for future operations

- [ ] **Heartbeat**
  - [ ] Implement heartbeat mechanism
  - [ ] Send heartbeats every 30-60 seconds
  - [ ] Handle heartbeat failures gracefully

- [ ] **Discovery**
  - [ ] Query registry for other agents
  - [ ] Filter agents by capabilities/skills
  - [ ] Cache agent information locally

- [ ] **Health**
  - [ ] Ensure agent endpoint is accessible
  - [ ] Respond to health check requests
  - [ ] Monitor own health status via registry

- [ ] **On-Chain Identity**
  - [ ] Resolve agent identity from blockchain
  - [ ] Verify agent ownership
  - [ ] Use ERC-8004 identity for trust verification

## Benefits of Integration

1. **Discoverability**: Agents can be discovered by clients and other agents
2. **Trust**: On-chain registration provides verifiable identity
3. **Health Monitoring**: Automatic health tracking and status updates
4. **Reputation**: Can integrate with ReputationRegistry for feedback
5. **Validation**: Can request validation via ValidationRegistry
6. **Interoperability**: Standard ERC-8004 format ensures compatibility

## Environment Variables

Agents should configure these environment variables:

```bash
# Registry Configuration
REGISTRY_URL=http://localhost:8080  # or production URL

# Blockchain Configuration (for on-chain registration)
CHAIN_ID=84532
RPC_URL=https://sepolia.base.org
IDENTITY_REGISTRY_ADDRESS=0x8004AA63c570c570eBF15376c0dB199918BFe9Fb
AGENT_PRIV_KEY=0x...  # For on-chain operations
AGENT_WALLET_ADDRESS=0x...  # Agent's wallet address

# Agent Configuration
AGENT_ID=...  # Set after registration
HEARTBEAT_INTERVAL=30  # Seconds between heartbeats
```

## Error Handling

Agents should handle these scenarios:

1. **Registry Unavailable**: Cache agent data, retry registration
2. **Heartbeat Failures**: Log errors, continue operation
3. **Registration Conflicts**: Handle duplicate registrations
4. **Network Issues**: Implement retry logic with exponential backoff

## Best Practices

1. **Registration**: Register once on startup, store agent ID persistently
2. **Heartbeats**: Send heartbeats regularly but don't block on failures
3. **Discovery**: Cache discovered agents to reduce API calls
4. **Health**: Monitor own endpoint health independently
5. **Security**: Never expose private keys, use environment variables
6. **Logging**: Log all registry interactions for debugging

## Future Enhancements

- **Reputation Integration**: Submit and query reputation scores
- **Validation Requests**: Request validation from validators
- **Agent-to-Agent Communication**: Use registry for agent discovery in A2A protocols
- **Multi-Chain Support**: Register on multiple chains for redundancy

