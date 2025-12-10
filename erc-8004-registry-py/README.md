# ERC-8004 Indexer (Python)

A Python/FastAPI service that integrates with ERC-8004 smart contracts for agent registration, discovery, and health monitoring. This Indexer provides a REST API server with off-chain indexing for fast queries while maintaining on-chain data integrity.

## Features

- **Agent Registration**: Register agents on-chain via ERC-8004 IdentityRegistry
- **Agent Discovery**: Search and list agents with fast off-chain indexing
- **Health Monitoring**: Automatic health checks via heartbeat and endpoint monitoring
- **Event Sync**: Real-time synchronization of on-chain events to off-chain database
- **Multi-Database Support**: Works with SQLite (development) and PostgreSQL (production)
- **Base Sepolia Integration**: Pre-configured for Base Sepolia testnet

## Architecture

The Indexer consists of:

1. **Contract Integration Layer**: Interacts with ERC-8004 smart contracts using `web3.py`
2. **Off-Chain Database**: Fast queries and health status tracking using SQLAlchemy
3. **Event Sync Service**: Synchronizes on-chain events to the database
4. **Health Check Service**: Optional service that monitors agent endpoints (disabled by default)
5. **REST API Server**: FastAPI-based API for agent management

## Prerequisites

- Python 3.10+
- uv or pip
- Database: SQLite (dev) or PostgreSQL (prod)

## Installation

1. Clone the repository and navigate to the Indexer directory:

```bash
cd erc-8004-registry-py
```

2. Install dependencies with uv:

```bash
uv sync
```

Or with pip:

```bash
pip install -e .
```

## Local Development with Anvil

For local development, you can use [Anvil](https://book.getfoundry.sh/anvil/) (a local Ethereum node) instead of connecting to testnet. See [docs/ANVIL_SETUP.md](./docs/ANVIL_SETUP.md) for detailed instructions.

Quick start:
```bash
# 1. Start Anvil in a separate terminal
anvil

# 2. Deploy ERC-8004 contracts to Anvil
# (See docs/ANVIL_SETUP.md for deployment instructions)

# 3. Copy and configure local environment
cp .env.local.example .env.local
# Update contract addresses in .env.local

# 4. Run with local config
export $(cat .env.local | xargs) && uvicorn src.main:app --reload
```

3. Set up environment variables:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Database (SQLite for dev, PostgreSQL for prod)
DATABASE_URL=sqlite:///./registry.db

# Blockchain Configuration - Base Sepolia
CHAIN_ID=84532
RPC_URL=https://sepolia.base.org

# ERC-8004 Contract Addresses (Base Sepolia)
IDENTITY_REGISTRY_ADDRESS=0x8004AA63c570c570eBF15376c0dB199918BFe9Fb
REPUTATION_REGISTRY_ADDRESS=0x8004bd8daB57f14Ed299135749a5CB5c42d341BF
VALIDATION_REGISTRY_ADDRESS=0x8004C269D0A5647E51E121FeB226200ECE932d55

# Server Configuration
PORT=8080
HOST=0.0.0.0

# Health Check Configuration
ENABLE_HEALTH_CHECKS=true
HEALTH_CHECK_INTERVAL=60
ENDPOINT_CHECK_TIMEOUT=10
HEARTBEAT_TTL_SECS=60

# Logging
LOG_LEVEL=info
```

4. Run database migrations:

```bash
alembic upgrade head
```

## Startup Order

**Important**: Start the Indexer **before** starting your agents.

1. **Start Indexer First**:
   ```bash
   cd erc-8004-registry-py
   uv run uvicorn src.main:app --host 0.0.0.0 --port 8080
   ```

2. **Then Start Agents**: Your agents can now register and interact with the Indexer.

**Why Indexer first?**
- Agents can register via Indexer API (requires Indexer)
- Agents can send authenticated heartbeats (requires Indexer)  
- Agents can discover other agents (requires Indexer)
- Event sync will catch up on any on-chain registrations that happened before Indexer started

**Note**: If an agent registers on-chain before the Indexer starts, the event sync service will automatically index it when the Indexer starts.

## Running the Server

### Development

```bash
uvicorn src.main:app --reload --port 8080
```

Or with uv:

```bash
uv run uvicorn src.main:app --reload --port 8080
```

### Production

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080
```

The server will start on `http://localhost:8080` (or your configured port).

## API Endpoints

### Health Check

```http
GET /health
```

Returns service health status.

### Register Agent

The Indexer supports three registration formats:

**Option 1: ERC-8004 Registration File (Recommended)**

```http
POST /agents/register
Content-Type: application/json

{
  "registrationFile": {
    "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
    "name": "Weather Agent",
    "description": "Provides weather information",
    "image": "https://example.com/agent.png",
    "endpoints": [
      {
        "name": "A2A",
        "endpoint": "https://agent.example.com",
        "version": "0.3.0",
        "a2aSkills": []
      }
    ],
    "registrations": [],
    "supportedTrust": ["reputation"],
    "active": true,
    "x402support": false,
    "updatedAt": 1704067200
  },
  "owner": "0x...",
  "labels": {"category": "weather"}
}
```

**Option 2: Registration File URL**

```http
POST /agents/register
Content-Type: application/json

{
  "registrationFileUrl": "https://yourdomain.com/agents/my-agent.json",
  "owner": "0x...",
  "labels": {"category": "weather"}
}
```

**Option 3: Legacy Agent Card Format (Backward Compatible)**

```http
POST /agents/register
Content-Type: application/json

{
  "agentCard": {
    "name": "Weather Agent",
    "description": "Provides weather information",
    "url": "https://agent.example.com",
    "version": "1.0.0",
    "skills": [...],
    "capabilities": {"streaming": true}
  },
  "owner": "0x...",
  "labels": {"category": "weather"}
}
```

**Note**: Full on-chain registration requires wallet integration. This endpoint stores agents in the Indexer for fast discovery. See [docs/WALLET_INTEGRATION.md](./docs/WALLET_INTEGRATION.md) for on-chain registration.

### Get Agent

```http
GET /agents/{agentId}
```

Returns agent details including metadata and health status.

### List Agents

```http
GET /agents?q=weather&endpoint_type=A2A&trust_model=reputation&limit=25&offset=0
```

Query parameters:
- `q`: Search query (optional)
- `endpoint_type`: Filter by endpoint type (A2A, MCP, etc.) (optional)
- `trust_model`: Filter by trust model (reputation, validation, etc.) (optional)
- `limit`: Maximum results (default: 25, max: 200)
- `offset`: Pagination offset (default: 0)

### Search Agents

```http
GET /agents/search?q=weather
```

Performs text search across agents.

### Heartbeat

```http
POST /agents/{agentId}/heartbeat
Content-Type: application/json

{
  "signature": "0x...",
  "timestamp": 1234567890
}
```

Updates agent's last heartbeat timestamp and sets status to healthy.

**Authentication**: If the agent has an owner address registered, heartbeats must include a cryptographic signature. The signature is generated by signing the message `"heartbeat:{agentId}:{timestamp}"` using EIP-191 personal sign format with the agent's private key. The timestamp must be within 5 minutes of the current time.

## Database Configuration

### SQLite (Development)

```env
DATABASE_URL=sqlite:///./registry.db
```

### PostgreSQL (Production)

```env
DATABASE_URL=postgresql://user:password@localhost:5432/registry
```

Ensure PostgreSQL is running and the database exists:

```bash
createdb registry
```

## Event Synchronization

The Indexer automatically syncs on-chain events:

- **AgentRegistered**: New agent registrations
- **MetadataUpdated**: Agent metadata updates

The sync service:
- Performs initial sync on startup
- Watches for new events in real-time
- Handles missed events with periodic backfill

## Health Monitoring

**Agent-initiated heartbeats (default)**: Agents send authenticated heartbeats to the Indexer to indicate they are alive. Heartbeats are cryptographically signed by the agent's owner address for security.

**Indexer-initiated health checks (opt-in)**: The health check service can optionally monitor agents by:

1. Monitoring agent heartbeats (configurable TTL)
2. Checking agent endpoints if heartbeat is stale
3. Updating health status (healthy/stale/unreachable)
4. Recording health check history

Health checks are **disabled by default**. To enable, set `ENABLE_HEALTH_CHECKS=true` in your environment. Health check interval and settings are configurable via environment variables.

## Development

### Project Structure

```
erc-8004-registry-py/
├── src/
│   ├── contracts/        # Contract ABIs and interaction logic
│   ├── db/               # Database models and migrations
│   ├── api/              # REST API routes
│   ├── services/         # Health checks, indexing, sync
│   ├── types/           # Type definitions
│   └── main.py          # Entry point
├── docs/                 # Documentation (14 markdown files)
│   ├── INTEGRATION_WITH_YOUR_AGENTS.md
│   ├── RECOMMENDED_REGISTRATION_WORKFLOW.md
│   ├── AGENT_REGISTRATION_EXAMPLES.md
│   ├── DOCUMENTATION_INDEX.md
│   └── ... (see docs/DOCUMENTATION_INDEX.md for complete list)
├── alembic/             # Database migrations
├── pyproject.toml
└── README.md            # Main entry point
```

### Building

The project uses Python directly, no build step required.

### Running Migrations

```bash
alembic upgrade head
```

## Configuration

All configuration is done via environment variables. See `.env.example` for available options.

### Base Sepolia Contract Addresses

- **IdentityRegistry**: `0x8004AA63c570c570eBF15376c0dB199918BFe9Fb`
- **ReputationRegistry**: `0x8004bd8daB57f14Ed299135749a5CB5c42d341BF`
- **ValidationRegistry**: `0x8004C269D0A5647E51E121FeB226200ECE932d55`

## Production Deployment

1. **Database**: Use PostgreSQL with connection pooling
2. **Environment**: Set secure environment variables
3. **Monitoring**: Enable logging and health checks
4. **Scaling**: Deploy behind load balancer if needed

## Troubleshooting

### Database Connection Issues

- Verify `DATABASE_URL` format is correct
- Ensure database exists and is accessible
- Check database user permissions

### Event Sync Issues

- Verify RPC URL is accessible
- Check contract addresses are correct for the network
- Review logs for sync errors

### Health Check Failures

- Verify agent URLs are accessible
- Check firewall rules allow health check traffic
- Review health check interval settings

## License

MIT

## Agent Integration

For detailed information on how agents integrate with the Indexer, see [docs/AGENT_INTEGRATION.md](./docs/AGENT_INTEGRATION.md).

Quick overview:
- **Registration**: Agents register on-chain via ERC-8004 or via Indexer API
- **Heartbeat**: Agents send authenticated periodic heartbeats to maintain health status (default)
- **Discovery**: Clients query the Indexer to discover available agents
- **Health Monitoring**: Indexer can optionally monitor agent endpoints (opt-in, disabled by default)

## Wallet Integration

For on-chain registration and wallet operations, see [docs/WALLET_INTEGRATION.md](./docs/WALLET_INTEGRATION.md).

Quick overview:
- **Private Keys**: Use environment variables for secure key management
- **On-Chain Registration**: Register agents via ERC-8004 IdentityRegistry
- **Gas Management**: Estimate and manage transaction costs
- **Error Handling**: Handle blockchain errors gracefully

## Agent Registration Examples

For practical examples of registering your agents from the `agents/` folder, see [docs/AGENT_REGISTRATION_EXAMPLES.md](./docs/AGENT_REGISTRATION_EXAMPLES.md).

Quick example:
```bash
# Register trader agent
curl -X POST "http://localhost:8080/agents/register" \
  -H "Content-Type: application/json" \
  -d '{
    "registrationFile": {
      "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
      "name": "A2A Trader Agent",
      "description": "AI agent for trading computational resources",
      "endpoints": [{
        "name": "A2A",
        "endpoint": "http://localhost:8001/",
        "version": "0.3.0",
        "a2aSkills": []
      }],
      "supportedTrust": ["reputation"],
      "active": true,
      "updatedAt": '$(date +%s)'
    },
    "owner": "0x...",
    "labels": {"category": "trading"}
  }'
```

## Recommended Registration Workflow

For the **recommended workflow** for registering agents on-chain, see [docs/RECOMMENDED_REGISTRATION_WORKFLOW.md](./docs/RECOMMENDED_REGISTRATION_WORKFLOW.md).

**Quick summary:**
1. Create ERC-8004 registration file in your agent code
2. Host registration file on HTTP/IPFS
3. Register on-chain directly from agent code (not via Indexer API)
4. Indexer automatically syncs via event sync service

**Why this approach?**
- ✅ Secure: Private keys stay in agent code
- ✅ Flexible: Works with or without Indexer running
- ✅ Standard: Follows ERC-8004 best practices
- ✅ Automatic: Indexer auto-indexes on-chain registrations

## Documentation

For complete documentation, see [docs/DOCUMENTATION_INDEX.md](./docs/DOCUMENTATION_INDEX.md).

**Quick Links:**
- [Integration with Your Agents](./docs/INTEGRATION_WITH_YOUR_AGENTS.md) - **START HERE** for practical integration
- [Recommended Registration Workflow](./docs/RECOMMENDED_REGISTRATION_WORKFLOW.md) - Best practices
- [Agent Registration Examples](./docs/AGENT_REGISTRATION_EXAMPLES.md) - Code examples
- [Wallet Integration](./docs/WALLET_INTEGRATION.md) - Security and wallet operations
- [ERC-8004 Format](./docs/ERC8004_FORMAT.md) - Format specification
- [Agent Integration Guide](./docs/AGENT_INTEGRATION.md) - Integration patterns
- [Anvil Setup](./docs/ANVIL_SETUP.md) - Local development

## Resources

- [ERC-8004 Specification](https://eips.ethereum.org/EIPS/eip-8004)
- [ERC-8004 Contracts](https://github.com/erc-8004/erc-8004-contracts)
- [Base Sepolia](https://docs.base.org/docs/networks/base-sepolia/)
- [Agent0 SDK](https://sdk.ag0.xyz/)

