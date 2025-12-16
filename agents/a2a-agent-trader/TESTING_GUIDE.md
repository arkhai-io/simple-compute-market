# Testing Guide: Registry Discovery for Market Orders

This guide walks you through testing the bidirectional market order discovery flow.

## Prerequisites

1. **Copy environment files** (if not already done):
   ```bash
   cp .env.example .env          # Maker agent
   cp .env.b.example .env.b      # Taker agent
   ```

2. **Ensure registry database is migrated**:
   ```bash
   cd ../../erc-8004-registry-py
   alembic upgrade head
   ```

3. **Configure blockchain settings** (if testing on-chain features):
   - Run `make test-env` first to get the RPC URL
   - Update `.env` and `.env.b` with:
     - `CHAIN_RPC_URL=<rpc_url_from_test-env>`
     - `AGENT_PRIV_KEY=<test_private_key>`
     - `AGENT_WALLET_ADDRESS=<test_wallet_address>`

## Step-by-Step Testing

### Step 1: Start the Test Blockchain Environment (test-env)

**Terminal 1** - Start the local blockchain test environment:
```bash
cd agents/a2a-agent-trader
make test-env
```

This spins up an `EnvTestManager` which provides:
- Local blockchain RPC endpoint
- Contract addresses for Alkahest (escrow/settlement)
- Test wallets (alice, bob) with pre-funded tokens

**Important**: Keep this terminal open. The test environment will print:
- `rpc_url`: Use this for `CHAIN_RPC_URL` in your .env files
- `addresses`: Contract addresses for Alkahest
- `mock_addresses`: Mock ERC20 token addresses

**Note**: You'll need to configure your `.env` files with the RPC URL from test-env output if you want to test on-chain escrow features. For basic registry discovery testing, you can skip blockchain features.

### Step 2: Start the Registry/Indexer

**Terminal 2** - Start the ERC-8004 registry:
```bash
cd erc-8004-registry-py
uv run uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

Verify it's running:
```bash
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "healthy", "service": "erc-8004-indexer", "version": "0.1.0"}
```

### Step 3: Start the Maker Agent

**Terminal 3** - Start the maker agent:
```bash
cd agents/a2a-agent-trader
make serve-a2a ENV_FILE=.env
```

Or manually:
```bash
export $(cat .env | xargs) && uv run uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```

Verify it's running:
```bash
curl http://localhost:8000/health
```

### Step 4: Start the Taker Agent

**Terminal 4** - Start the taker agent:
```bash
cd agents/a2a-agent-trader
make serve-a2a ENV_FILE=.env.b PORT=8001
```

Or manually:
```bash
export $(cat .env.b | xargs) && uv run uvicorn app.server:app --host 0.0.0.0 --port 8001 --reload
```

Verify it's running:
```bash
curl http://localhost:8001/health
```

### Step 5: Register Agents (Optional but Recommended)

Register both agents with the registry so they can discover each other:

**Register Maker Agent:**
```bash
curl -X POST http://localhost:8080/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "0x0000000000000000000000000000000000000000",
    "agentCard": {
      "name": "Maker Agent",
      "description": "Agent that creates market orders",
      "url": "http://localhost:8000",
      "version": "0.1.0"
    },
    "agentId": "maker_agent"
  }'
```

**Register Taker Agent:**
```bash
curl -X POST http://localhost:8080/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "0x0000000000000000000000000000000000000000",
    "agentCard": {
      "name": "Taker Agent",
      "description": "Agent that accepts market orders",
      "url": "http://localhost:8001",
      "version": "0.1.0"
    },
    "agentId": "taker_agent"
  }'
```

### Step 6: Trigger a Resource Alert (Surplus Scenario)

Send a resource alert to the **maker agent** to trigger order creation. This simulates low utilization (surplus), which will create an order offering compute and demanding tokens:

```bash
curl -X POST http://localhost:8000/alerts/resource \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "resource_imbalance",
    "resource": {
      "gpu_model": "H200",
      "quantity": 1,
      "sla": 90.0,
      "region": "California, US"
    },
    "value": 0.05,
    "label": "LOW UTILIZATION",
    "threshold": "<=0.30"
  }'
```

**What happens:**
1. Maker agent receives the alert
2. Agent policies decide to create a market order (surplus: offer compute, demand tokens)
3. Order is created and published to the registry
4. `make_offer()` queries the registry for matching orders
5. Taker agent's orders are discovered (if any exist)
6. Offer is sent to matching agents

### Step 7: Check Registry for Published Orders

Verify the order was published to the registry:

```bash
# List all orders
curl http://localhost:8080/orders?status=open

# List maker agent's orders
curl http://localhost:8080/agents/maker_agent/orders
```

### Step 8: Trigger a Resource Alert (Deficit Scenario)

To test the bidirectional flow, send a deficit alert (high demand) which creates an order offering tokens and demanding compute:

```bash
curl -X POST http://localhost:8000/alerts/resource \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "resource_imbalance",
    "resource": {
      "gpu_model": "H200",
      "quantity": 1,
      "sla": 90.0,
      "region": "California, US"
    },
    "value": 0.95,
    "label": "HIGH DEMAND",
    "threshold": ">=0.70"
  }'
```

This creates a deficit order (offer tokens, demand compute).

### Step 9: Monitor Logs

Watch the logs for all services to see the discovery and matching process:

**Test Blockchain Logs** (Terminal 1 - test-env):
- Look for: RPC URL and contract addresses printed at startup
- Keep terminal open - blockchain must stay running

**Registry Logs** (Terminal 2):
- Look for: `POST /agents/{agent_id}/orders` requests
- Look for: `GET /orders` queries
- Look for: Order creation and updates

**Maker Agent Logs** (Terminal 3):
- Look for: `[REGISTRY] Published order ... to registry`
- Look for: `[REGISTRY] Found X matching orders`
- Look for: `[REGISTRY] Sending offer to agent at ...`
- Look for: `[TOOL] Creating order for resource`

**Taker Agent Logs** (Terminal 4):
- Look for: `[A2A] Received event from remote agent`
- Look for: `[TOOL] Accepting offer`
- Look for: Order discovery and matching

## Testing Order Matching

### Test Bidirectional Matching

1. **Create a surplus order** (maker offers compute):
   - Send LOW UTILIZATION alert to maker agent
   - Order: `offer_resource=ComputeResource`, `demand_resource=TokenResource`

2. **Create a deficit order** (taker offers tokens):
   - Send HIGH DEMAND alert to taker agent
   - Order: `offer_resource=TokenResource`, `demand_resource=ComputeResource`

3. **Verify matching**:
   - Maker's compute offer should match taker's compute demand
   - Maker's token demand should match taker's token offer
   - Orders should be discovered bidirectionally

### Query Orders Directly

```bash
# Query orders with filters
curl "http://localhost:8080/orders?offer_resource_type=compute&status=open"
curl "http://localhost:8080/orders?demand_resource_type=compute&status=open&bidirectional=true"
```

## Expected Flow Summary

```
1. Alert → Maker Agent
   ↓
2. Maker creates MarketOrder (surplus: compute for tokens)
   ↓
3. Order published to Registry
   ↓
4. make_offer() queries Registry for matching orders
   ↓
5. Registry returns matching orders (bidirectional matching)
   ↓
6. Maker sends offer to Taker agent(s)
   ↓
7. Taker receives offer and can accept
   ↓
8. Order status updated in Registry (accepted)
   ↓
9. Settlement flow begins
```

## Troubleshooting

### Registry Not Found
- Check: `INDEXER_URL=http://localhost:8080` in both .env files
- Verify registry is running: `curl http://localhost:8080/health`

### Orders Not Matching
- Check order status: must be `"open"` to match
- Verify resource types match bidirectionally
- Check logs for matching logic errors

### Agents Not Discovering Each Other
- Ensure both agents are registered with registry
- Check `ENABLE_REGISTRY_DISCOVERY=true` in both .env files
- Verify agent IDs match registration: `maker_agent` and `taker_agent`

### Port Conflicts
- Change ports in .env files if 8000/8001 are in use
- Update `BASE_URL_OVERRIDE` and `REMOTE_AGENT_URL_OVERRIDE` accordingly

## Advanced Testing

### Test with Multiple Agents

1. Create `.env.c` for a third agent (port 8002)
2. Start third agent
3. Register with registry
4. Send alerts to multiple agents
5. Verify orders are discovered across all agents

### Test Order Cleanup

Orders older than 7 days or with `closed`/`expired` status are automatically cleaned up. Check logs for `[CLEANUP]` messages.

### Test Fallback Behavior

Disable registry discovery to test fallback:
```bash
# In .env, set:
ENABLE_REGISTRY_DISCOVERY=false
```

This should fall back to `REMOTE_AGENT_URL_OVERRIDE` for direct agent-to-agent communication.

