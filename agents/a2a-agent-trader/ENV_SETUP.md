# Environment Setup for Maker and Taker Agents

This directory contains example environment files for running two agents in a maker/taker configuration.

## Quick Setup

1. **Copy the example files to create your environment files:**

```bash
# For maker agent
cp .env.example .env

# For taker agent  
cp .env.b.example .env.b
```

2. **Customize the files as needed** (see configuration details below)

3. **Register agents and get ONCHAIN_AGENT_ID** (see registration section below)

## Agent Registration and ONCHAIN_AGENT_ID Setup

### Step 1: Configure Blockchain Settings

Before registering, ensure your `.env` and `.env.b` files have blockchain configuration:

```bash
# Required for on-chain registration
CHAIN_RPC_URL=http://localhost:8545  # Or your testnet RPC URL
IDENTITY_REGISTRY_ADDRESS=0x...       # ERC-8004 Identity Registry contract address
AGENT_PRIV_KEY=0x...                  # Private key for signing transactions
AGENT_WALLET_ADDRESS=0x...            # Wallet address (derived from private key)
AUTO_REGISTER=true                     # Enable auto-registration on startup
```

### Step 2: Start Agents for Auto-Registration

When you start an agent with `AUTO_REGISTER=true`, it will automatically register on-chain:

```bash
# Terminal 1 - Maker Agent (will auto-register)
make serve-a2a ENV_FILE=.env

# Terminal 2 - Taker Agent (will auto-register)
make serve-a2a ENV_FILE=.env.b PORT=8001
```

### Step 3: Find the ONCHAIN_AGENT_ID from Logs

After registration, check the agent logs for the agent ID. Look for lines like:

```text
[ONCHAIN REGISTRATION] ✓ On-chain registration complete. TX: 0x..., Agent ID: 22
```

or

```text
[ONCHAIN REGISTRATION] ✓ Using existing agent ID: 22
```

The **Agent ID** (e.g., `22`) is your `ONCHAIN_AGENT_ID`.

### Step 4: Add ONCHAIN_AGENT_ID to Environment Files

Add the agent ID to your `.env` files:

**For Maker Agent (.env):**

```bash
# Add this line with the agent ID from logs
ONCHAIN_AGENT_ID=22
```

**For Taker Agent (.env.b):**

```bash
# Add this line with the agent ID from logs (will be different)
ONCHAIN_AGENT_ID=23
```

### Alternative: Manual Registration

If you prefer to register manually or need to find an existing agent ID:

1. **Query the registry for your wallet address:**

   ```bash
   # Replace with your wallet address
   curl "http://localhost:8080/agents?owner=0xYOUR_WALLET_ADDRESS"
   ```

2. **Or check blockchain events directly** (requires web3 tools):
   - Query the Identity Registry contract for `Registered` events
   - Filter by your wallet address as the `owner` parameter

### Registration Notes

- **Each agent gets a unique agent ID**: If you run multiple agents with different wallet addresses, each will get its own agent ID
- **Agent ID is numeric**: The `ONCHAIN_AGENT_ID` should be a plain number (e.g., `22`, not `eip155:1337:0x...:22`)
- **Canonical ID is built automatically**: The agent will build the full canonical ID (`eip155:chainId:registry:agentId`) automatically using `ONCHAIN_AGENT_ID`, `CHAIN_ID`, and `IDENTITY_REGISTRY_ADDRESS`
- **Idempotent registration**: If `ONCHAIN_AGENT_ID` is set, the agent will use that ID instead of registering a new one

## Configuration Differences

### Maker Agent (.env)

- `AGENT_ID=maker_agent` - Unique identifier for the maker agent
- `PORT=8000` - Port for the maker agent server
- `BASE_URL_OVERRIDE=http://localhost:8000` - Base URL for maker agent
- `REMOTE_AGENT_URL_OVERRIDE=http://localhost:8001` - Points to taker agent
- `POLICY_DB_PATH=/tmp/policies_maker.db` - Separate database file
- `ONCHAIN_AGENT_ID=22` - Numeric agent ID from on-chain registration (see registration section above)

### Taker Agent (.env.b)

- `AGENT_ID=taker_agent` - Unique identifier for the taker agent
- `PORT=8001` - Port for the taker agent server
- `BASE_URL_OVERRIDE=http://localhost:8001` - Base URL for taker agent
- `REMOTE_AGENT_URL_OVERRIDE=http://localhost:8000` - Points to maker agent
- `POLICY_DB_PATH=/tmp/policies_taker.db` - Separate database file
- `ONCHAIN_AGENT_ID=23` - Numeric agent ID from on-chain registration (see registration section above)

## Running the Agents

### Option 1: Using Makefile with ENV_FILE

```bash
# Terminal 1 - Maker Agent
make serve-a2a ENV_FILE=.env

# Terminal 2 - Taker Agent
make serve-a2a ENV_FILE=.env.b PORT=8001
```

### Option 2: Using environment variables directly

```bash
# Terminal 1 - Maker Agent
export $(cat .env | xargs) && uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Taker Agent
export $(cat .env.b | xargs) && uv run uvicorn app.server:app --host 0.0.0.0 --port 8001 --reload
```

## Key Configuration Variables

### On-Chain Registration

- `AUTO_REGISTER=true` - Enable automatic registration on agent startup
- `CHAIN_RPC_URL=http://localhost:8545` - Blockchain RPC endpoint
- `IDENTITY_REGISTRY_ADDRESS=0x...` - ERC-8004 Identity Registry contract address
- `AGENT_PRIV_KEY=0x...` - Private key for signing registration transactions
- `AGENT_WALLET_ADDRESS=0x...` - Wallet address (derived from private key)
- `ONCHAIN_AGENT_ID=22` - **Numeric agent ID from on-chain registration** (see registration section above)

### Registry Discovery

- `ENABLE_REGISTRY_DISCOVERY=true` - Enables registry-based agent discovery
- `INDEXER_URL=http://localhost:8080` - URL of the ERC-8004 registry/indexer
- `REGISTRY_ORDER_TIMEOUT=30` - Timeout for registry API calls (seconds)
- `MAX_DISCOVERY_AGENTS=10` - Maximum number of agents to contact

## Important Notes

1. **Registry Must Be Running First**: Start the ERC-8004 registry/indexer before starting agents:

   ```bash
   cd ../../erc-8004-registry-py
   uv run uvicorn src.main:app --host 0.0.0.0 --port 8080
   ```

2. **Separate Databases**: Each agent uses a separate policy database file to avoid conflicts.

3. **Port Configuration**: Ensure ports 8000 and 8001 are available, or update the PORT values in both files.

4. **Bidirectional Orders**: The registry discovery supports both:
   - **Surplus orders**: Maker offers compute, demands tokens
   - **Deficit orders**: Maker offers tokens, demands compute

## Testing the Flow

1. **Configure environment files** (`.env` and `.env.b`) with blockchain settings
2. **Start the registry/indexer** (port 8080)
3. **Start the maker agent** (port 8000) with `.env` - it will auto-register on-chain
4. **Get ONCHAIN_AGENT_ID from maker logs** and add to `.env`
5. **Start the taker agent** (port 8001) with `.env.b` - it will auto-register on-chain
6. **Get ONCHAIN_AGENT_ID from taker logs** and add to `.env.b`
7. **Restart both agents** (if needed) to ensure they use the correct agent IDs
8. Send a resource alert to the maker agent to trigger order creation
9. The maker agent will publish the order to the registry
10. The taker agent will discover the order and can accept it

## Troubleshooting

- **Port conflicts**: Change PORT values if 8000/8001 are in use
- **Registry connection**: Ensure INDEXER_URL points to running registry
- **Database conflicts**: Use separate POLICY_DB_PATH for each agent
- **Agent discovery**: Check logs for registry connection errors
- **ONCHAIN_AGENT_ID not found**:
  - Check agent logs for registration success message
  - Look for lines containing "Agent ID:" in the logs
  - Ensure `AUTO_REGISTER=true` is set in your `.env` file
  - Verify blockchain credentials (`CHAIN_RPC_URL`, `AGENT_PRIV_KEY`, `IDENTITY_REGISTRY_ADDRESS`) are correct
- **Order publishing fails**: Ensure `ONCHAIN_AGENT_ID` is set correctly in your `.env` file (must be numeric, e.g., `22`)
- **Multiple agent IDs**: Each wallet address gets its own agent ID - ensure each agent uses a different wallet/private key
