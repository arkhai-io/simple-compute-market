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

## Configuration Differences

### Maker Agent (.env)
- `AGENT_ID=maker_agent` - Unique identifier for the maker agent
- `PORT=8000` - Port for the maker agent server
- `BASE_URL_OVERRIDE=http://localhost:8000` - Base URL for maker agent
- `REMOTE_AGENT_URL_OVERRIDE=http://localhost:8001` - Points to taker agent
- `POLICY_DB_PATH=/tmp/policies_maker.db` - Separate database file

### Taker Agent (.env.b)
- `AGENT_ID=taker_agent` - Unique identifier for the taker agent
- `PORT=8001` - Port for the taker agent server
- `BASE_URL_OVERRIDE=http://localhost:8001` - Base URL for taker agent
- `REMOTE_AGENT_URL_OVERRIDE=http://localhost:8000` - Points to maker agent
- `POLICY_DB_PATH=/tmp/policies_taker.db` - Separate database file

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

### Registry Discovery
- `ENABLE_REGISTRY_DISCOVERY=true` - Enables registry-based agent discovery
- `INDEXER_URL=http://localhost:8080` - URL of the ERC-8004 registry/indexer
- `REGISTRY_ORDER_TIMEOUT=30` - Timeout for registry API calls (seconds)
- `MAX_DISCOVERY_AGENTS=10` - Maximum number of agents to contact

### Important Notes

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

1. Start the registry/indexer (port 8080)
2. Start the maker agent (port 8000) with `.env`
3. Start the taker agent (port 8001) with `.env.b`
4. Send a resource alert to the maker agent to trigger order creation
5. The maker agent will publish the order to the registry
6. The taker agent will discover the order and can accept it

## Troubleshooting

- **Port conflicts**: Change PORT values if 8000/8001 are in use
- **Registry connection**: Ensure INDEXER_URL points to running registry
- **Database conflicts**: Use separate POLICY_DB_PATH for each agent
- **Agent discovery**: Check logs for registry connection errors

