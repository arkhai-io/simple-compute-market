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

## Agent ID Format (ERC-8004 Canonical)

Agents are identified using **ERC-8004 canonical IDs** following the format:

```text
eip155:{chainId}:{identityRegistry}:{numericAgentId}
```

Example: `eip155:1337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:22`

Where:

- `eip155`: Namespace (Ethereum Improvement Proposal 155)
- `chainId`: Blockchain network identifier (e.g., 1337 for Anvil, 84532 for Base Sepolia)
- `identityRegistry`: ERC-8004 Identity Registry contract address
- `numericAgentId`: Numeric ERC-721 tokenId assigned by the registry (e.g., `22`)

**Two Types of Agent IDs:**

1. **Numeric Agent ID**: The ERC-721 tokenId returned from on-chain registration (e.g., `22`)
2. **Canonical Agent ID**: The full formatted identifier combining chain, registry, and numeric ID (e.g., `eip155:1337:0x...:22`)

**Important**: The canonical ID is built **after** on-chain registration. You register on-chain to receive the numeric agent ID, then construct the canonical ID from it. The canonical ID is used consistently across all Indexer APIs.

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

# Health Check Configuration (OPT-IN - disabled by default)
ENABLE_HEALTH_CHECKS=false
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

## Local Development with Anvil

For local development, you can use [Anvil](https://getfoundry.sh/anvil/overview/) (a local Ethereum node) instead of connecting to testnet.

Quick start:

```bash
# 1. Start Anvil in a separate terminal
anvil

# 2. Deploy ERC-8004 contracts to Anvil
# Navigate to erc-8004-contracts/ and run deployment scripts

# 3. Update .env with Anvil configuration:
# CHAIN_ID=1337
# RPC_URL=http://localhost:8545
# Update contract addresses to your deployed addresses

# 4. Run with local config
uvicorn src.main:app --reload
```

## Startup Order

**Recommended**: Start the Indexer **before** starting your agents for best experience.

1. **Start Indexer First**:

   ```bash
   cd erc-8004-registry-py
   make serve
   ```

   Or manually:

   ```bash
   uv run uvicorn src.main:app --host 0.0.0.0 --port 8080
   ```

2. **Then Start Agents**: Your agents can now:
   - Register on-chain (works independently, but Indexer will sync immediately)
   - Send authenticated heartbeats (requires Indexer)
   - Discover other agents via Indexer API (requires Indexer)

**Why Start Indexer First?**

- **Event Sync**: Indexer can immediately sync agent registrations as they happen
- **Heartbeats**: Agents can send heartbeats right away (requires Indexer)
- **Discovery**: Agents can discover other agents immediately (requires Indexer)

**What if Indexer Starts After Agents?**

- ✅ **No problem!** Agents can register on-chain anytime (independent of Indexer)
- ✅ **Auto-sync**: When Indexer starts, event sync will automatically catch up on all on-chain registrations
- ✅ **Backfill**: Event sync performs initial sync on startup to index any missed registrations

**Note**: While agents can register on-chain independently, the Indexer must be running for:
- Agent discovery via `/agents` endpoint
- Heartbeat processing
- Real-time event synchronization

## Running the Server

### Using Makefile (Recommended)

The Makefile provides a convenient way to start the server with ZeroTier support:

```bash
# Start server (defaults to port 8080)
make serve

# Start on custom port
make serve PORT=9000

# With ZeroTier network (set ZEROTIER_NETWORK in .env or environment)
# The server will automatically join the ZeroTier network on startup
make serve
```

**ZeroTier Integration**: If `ZEROTIER_NETWORK` is set in your `.env` file or environment, the server will automatically:

- Check for ZeroTier CLI installation
- Join the specified ZeroTier network
- Display the ZeroTier node ID for authorization
- Leave the network gracefully on shutdown

After starting, send your ZeroTier node ID to the network controller to get authorized:

```bash
sudo zerotier-cli info | cut -d " " -f3
```

### Manual Development

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

## Agent Integration

### Registration Workflow

**Recommended Approach: Register On-Chain, Indexer Auto-Syncs**

The recommended workflow is for agents to register directly on-chain using the ERC-8004 IdentityRegistry contract. The Indexer will automatically discover and index these registrations via its event sync service.

**Registration Flow:**

1. **Agent registers on-chain** → Your agent code calls the ERC-8004 IdentityRegistry contract's `register()` function directly
   - This happens entirely on-chain, independent of the Indexer
   - Returns a numeric agent ID (ERC-721 tokenId)
   - Private keys stay secure in your agent code

2. **Indexer automatically syncs** → The Indexer's event sync service detects the on-chain registration event
   - No API calls needed from your agent
   - Indexer automatically indexes the agent into its database
   - Agent becomes discoverable via Indexer API

3. **Agent uses canonical ID** → Build and use the canonical ID format for all interactions
   - Format: `eip155:{chainId}:{identityRegistry}:{numericAgentId}`
   - Use this ID for heartbeats, discovery, and other Indexer API calls

**Why this approach?**

- ✅ **Secure**: Private keys never leave your agent code
- ✅ **Decentralized**: Registration happens on-chain, not dependent on Indexer availability
- ✅ **Automatic**: Indexer automatically discovers and indexes agents via event sync
- ✅ **Standard**: Follows ERC-8004 best practices
- ✅ **Flexible**: Works even if Indexer is temporarily offline (will sync when back online)

**Important Notes:**

- The Indexer must be running for event sync to work (but agents can register on-chain anytime)
- If an agent registers on-chain before the Indexer starts, the event sync will catch up on startup
- Event sync monitors both new registrations and metadata updates automatically

### On-Chain Registration

Agents should register on-chain using the ERC-8004 IdentityRegistry contract.

**On-Chain Registration Steps:**

1. **Call `register()` function** → Interact directly with the ERC-8004 IdentityRegistry contract
   - Pass your agent's token URI (pointing to your agent card JSON)
   - Optionally include metadata entries
   - Returns a numeric agent ID (e.g., `22`) - this is the ERC-721 tokenId
   - Use environment variables for secure private key management
   - Estimate and manage transaction costs (gas)
   - Handle blockchain errors gracefully

2. **Build canonical ID** → Format: `eip155:{chainId}:{identityRegistry}:{numericAgentId}`
   - Example: `eip155:1337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:22`
   - Where `22` is the numeric agent ID from step 1

3. **Indexer auto-syncs** → The Indexer's event sync service automatically detects your registration
   - No additional API calls needed
   - Agent becomes available in Indexer database
   - Can be discovered via `/agents` endpoint

4. **Use canonical ID** → Include it in heartbeats and other Indexer API calls

### Agent Heartbeat

Agents send authenticated periodic heartbeats to maintain health status:

- Sign message: `"heartbeat:{canonicalAgentId}:{timestamp}"`
- Use EIP-191 personal sign format
- Timestamp must be within 5 minutes of current time
- Send to `/agents/{canonicalAgentId}/heartbeat` endpoint

### Discovery

Clients query the Indexer to discover available agents using the `/agents` endpoint with filters.

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

The Indexer automatically syncs on-chain events to keep its database up-to-date:

**Synced Events:**

- **AgentRegistered**: New agent registrations (primary method for agent discovery)
- **MetadataSet**: Agent metadata updates
- **UriUpdated**: Agent token URI updates

**How Event Sync Works:**

1. **On Startup**: Performs initial sync to catch up on any registrations that happened while Indexer was offline
2. **Real-Time Monitoring**: Continuously watches for new events on-chain
3. **Automatic Indexing**: When an agent registers on-chain, the Indexer automatically:
   - Detects the `AgentRegistered` event
   - Fetches agent metadata from the token URI
   - Stores agent information in the database
   - Makes the agent discoverable via API

**Benefits:**

- ✅ Agents register on-chain independently (no Indexer dependency)
- ✅ Indexer automatically discovers all on-chain registrations
- ✅ No manual API calls needed for registration
- ✅ Handles missed events with periodic backfill
- ✅ Works even if Indexer was offline during registration

**Note**: The event sync service runs automatically when the Indexer starts. Ensure the Indexer is running for agents to be discoverable, but agents can register on-chain at any time.

## Health Monitoring

**Agent-initiated heartbeats (default)**: Agents send authenticated heartbeats to the Indexer to indicate they are alive. Heartbeats are cryptographically signed by the agent's owner address for security.

**Indexer-initiated health checks (opt-in)**: The health check service can optionally monitor agents by:

1. Monitoring agent heartbeats (configurable TTL)
2. Checking agent endpoints if heartbeat is stale
3. Updating health status (healthy/stale/unreachable)
4. Recording health check history

Health checks are **disabled by default**. To enable, set `ENABLE_HEALTH_CHECKS=true` in your environment. Health check interval and settings are configurable via environment variables.

## Orders API

The Orders API is served by the Indexer (FastAPI). When running locally on the default port, API docs are available at:

- Swagger UI: `http://localhost:8080/docs`
- OpenAPI JSON: `http://localhost:8080/openapi.json`
- ReDoc: `http://localhost:8080/redoc`

### Publish or Update an Order

```http
POST /agents/{agent_id}/orders
```

- `agent_id` must be the canonical ERC-8004 agent ID (`eip155:...`).
- `order_id` is required and unique; reusing an `order_id` updates the existing order.
- `status` defaults to `open` if not provided.

Example:

```bash
curl -X POST "http://localhost:8080/agents/{agent_id}/orders" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "order-123",
    "order_maker": "http://localhost:8001/.well-known/agent-card.json",
    "offer_resource": {"type": "compute", "region": "us-west"},
    "demand_resource": {"type": "token", "symbol": "USDC"},
    "duration_hours": 1,
    "status": "open"
  }'
```

### List Orders for an Agent

```http
GET /agents/{agent_id}/orders
```

Query params:

- `status` (optional): `open`, `closed`, `accepted`, `expired`
- `limit` (default 50, max 200)
- `offset` (default 0)

Example:

```bash
curl "http://localhost:8080/agents/{agent_id}/orders?status=open"
```

### Query Orders (Global)

```http
GET /orders
```

Query params:

- `offer_resource_type` (e.g., `compute` or `token`)
- `demand_resource_type` (e.g., `compute` or `token`)
- `region`
- `gpu_model`
- `sla`
- `status` (default `open`)
- `bidirectional` (default `false`)
- `limit` (default 50, max 200)
- `offset` (default 0)

Example:

```bash
curl "http://localhost:8080/orders?status=open&offer_resource_type=compute&region=us-west"
```

### Update an Order

```http
PUT /orders/{order_id}
```

Use this to mark an order as accepted/closed/expired or to set `order_taker` and attestations. Updating one order can also update its symmetric counterpart.

Example:

```bash
curl -X PUT "http://localhost:8080/orders/{order_id}" \
  -H "Content-Type: application/json" \
  -d '{"status":"accepted","order_taker":"http://localhost:8002/.well-known/agent-card.json"}'
```

### Delete an Order

```http
DELETE /orders/{order_id}
```

Example:

```bash
curl -X DELETE "http://localhost:8080/orders/{order_id}"
```

## Development

### Project Structure

```text
erc-8004-registry-py/
├── src/
│   ├── contracts/        # Contract ABIs and interaction logic
│   ├── db/               # Database models and migrations
│   ├── api/              # REST API routes
│   ├── services/         # Health checks, indexing, sync
│   ├── types/           # Type definitions
│   └── main.py          # Entry point
├── alembic/             # Database migrations
├── pyproject.toml
└── README.md
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

### Container

**Build the image:**

```bash
cd erc-8004-registry-py/
docker build -t erc-8004-registry .
```

**Run locally with an env file:**

```bash
docker run --env-file .env.development -p 8080:8080 erc-8004-registry
```

### CI/CD - Automated Builds

The project includes GitHub Actions for automated Docker image builds and pushes to **Docker Hub**.

**Automated builds trigger on:**
- Push to `main` or `develop` branches
- New release tags (`v*.*.*`)
- Manual workflow dispatch

**Pre-built images available at:**
```
whitewidget/arkhai-erc-8004-registry:latest
whitewidget/arkhai-erc-8004-registry:v1.0.0
```

**Deploy using pre-built image:**

```bash
# Pull and run (public images, no auth needed)
docker pull whitewidget/arkhai-erc-8004-registry:latest
docker run --env-file .env -p 8080:8080 whitewidget/arkhai-erc-8004-registry:latest

# Or use docker-compose
docker-compose up -d
```

**Setup CI/CD for your repository:**

Only 2 GitHub secrets needed:
- `DOCKERHUB_USERNAME` - Your Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token (Read & Write)

See detailed instructions in [../.github/CI-CD-SETUP.md](../.github/CI-CD-SETUP.md) and [../.github/SECRETS-CHECKLIST.md](../.github/SECRETS-CHECKLIST.md).

### Security Best Practices

#### 🔒 Environment Variables & Secrets Management

**⚠️ CRITICAL: Never commit secrets to version control**

The Dockerfile has been configured with **empty values** for sensitive environment variables. This prevents credentials from being baked into Docker image layers.

**Required Environment Variables:**

**Sensitive (must be provided at runtime):**
- `DATABASE_URL` - PostgreSQL connection string with credentials
- `RPC_URL` - Blockchain RPC endpoint URL with API key

**Non-sensitive (have defaults, can be overridden):**
- `CHAIN_ID` - Default: 84532 (Base Sepolia)
- `IDENTITY_REGISTRY_ADDRESS`
- `REPUTATION_REGISTRY_ADDRESS`
- `VALIDATION_REGISTRY_ADDRESS`
- `PORT` - Default: 8080
- `HOST` - Default: 0.0.0.0
- `ENABLE_HEALTH_CHECKS` - Default: false
- `HEALTH_CHECK_INTERVAL` - Default: 60
- `ENDPOINT_CHECK_TIMEOUT` - Default: 10
- `HEARTBEAT_TTL_SECS` - Default: 60
- `LOG_LEVEL` - Default: info

#### Secure Deployment Methods

**1. Using Docker Compose (Recommended for Development)**

```bash
# 1. Create .env file from sample (do this once)
cp .env.sample .env

# 2. Edit .env with your actual credentials
nano .env

# 3. Run with docker-compose (reads .env automatically)
docker-compose up
```

**2. Using Docker Run with Environment File**

```bash
docker build -t erc-8004-registry .
docker run --env-file .env -p 8080:8080 erc-8004-registry
```

**3. Using Docker Run with Individual Variables**

```bash
docker run -p 8080:8080 \
  -e DATABASE_URL="postgresql://user:pass@host/db" \
  -e RPC_URL="https://base-sepolia.infura.io/v3/YOUR_API_KEY" \
  -e CHAIN_ID=84532 \
  erc-8004-registry
```

**4. Using Docker Secrets (Production - Swarm/Kubernetes)**

For production deployments, use your orchestration platform's secrets management:

**Docker Swarm:**
```bash
echo "postgresql://..." | docker secret create db_url -
docker service create \
  --name erc-8004-registry \
  --secret db_url \
  --secret rpc_url \
  erc-8004-registry
```

**Kubernetes:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: erc-8004-secrets
type: Opaque
stringData:
  DATABASE_URL: postgresql://...
  RPC_URL: https://...
---
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: registry
    image: erc-8004-registry
    envFrom:
    - secretRef:
        name: erc-8004-secrets
```

#### Security Checklist

- [x] `.env` is in `.gitignore` (never commit it)
- [x] Sensitive ENV variables have empty defaults in Dockerfile
- [x] Credentials are provided at runtime, not build time
- [x] Docker image runs as non-root user (`appuser`)
- [ ] Use secrets management in production (Vault, AWS Secrets Manager, etc.)
- [ ] Rotate credentials regularly
- [ ] Use read-only database credentials where possible
- [ ] Enable network policies to restrict container access
- [ ] Scan images for vulnerabilities regularly

#### Image Security Best Practices

```bash
# Scan for vulnerabilities
docker scan erc-8004-registry

# Verify no secrets in image layers
docker history erc-8004-registry

# Check running container for exposed secrets
docker exec <container_id> env
```

#### What NOT to Do

❌ **Never hardcode credentials in Dockerfile:**
```dockerfile
# BAD - credentials baked into image layers
ENV DATABASE_URL=postgresql://user:password@host/db
```

❌ **Never commit .env files to git**

❌ **Never build images with secrets as build args in CI/CD logs**

✅ **Instead:** Use runtime environment variables or secrets management systems

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

## Resources

- [ERC-8004 Specification](https://eips.ethereum.org/EIPS/eip-8004)
- [ERC-8004 Contracts](https://github.com/erc-8004/erc-8004-contracts)
- [Base Sepolia](https://docs.base.org/docs/networks/base-sepolia/)
- [Agent0 SDK](https://sdk.ag0.xyz/)
