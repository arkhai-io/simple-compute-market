# Role-separated integration tests

Tests are organized around the **deployment topology** of the marketplace:
four independent layers and a five-stage pipeline, with buyer and seller
as independent roles within each stage.

## The four layers

These correspond to four independently-deployed units of software, each
run by a different party in production:

1. **External** — the EVM chain with Alkahest + ERC-8004 contracts.
   Run by: nobody in this repo (it's a real chain).
   Dev stand-in: `compose/external.yml` (Anvil + contract deployer).

2. **Market** — the registry that indexes orders and agents.
   Run by: a marketplace operator (infra provider).
   Deployment: `compose/market.yml`.

3. **Seller node** — a seller's agent + their own provisioning service.
   Run by: each independent seller, on their own machine.
   Deployment: `compose/seller.yml`.

4. **Buyer node** — a buyer's agent.
   Run by: each independent buyer, on their own machine.
   Deployment: `compose/buyer.yml`.

Layer fixtures (`external_world`, `market_registry`, `seller_node`,
`buyer_node`) correspond 1:1 to these units. A buyer-perspective test
depends on `external_world + market_registry + buyer_node`. A seller
test depends on `external_world + market_registry + seller_node`. A
cross-role test depends on all four.

## Structure

```
roles/
├── layers/                      # Layer verification + fixtures
│   ├── test_external.py         # Chain + contracts → external_world
│   ├── test_market.py           # Registry → market_registry
│   ├── test_seller.py           # Seller's agent + provisioning → seller_node
│   └── test_buyer.py            # Buyer's agent → buyer_node
│
├── stages/                      # Five marketplace stages
│   ├── discovery/               # Seller publishes, buyer finds matches
│   │   ├── conftest.py          # Input: layers ready. Output: published order.
│   │   ├── test_seller.py
│   │   └── test_buyer.py
│   ├── negotiation/             # Price agreement
│   ├── settlement/              # Escrow + acceptance
│   ├── provision/               # Machine provisioned, credentials delivered
│   └── post_settlement/         # Lease expiry, token settlement, resource freed
│
└── scenarios/                   # Cross-stage tests that don't decompose cleanly
```

## Design principles

1. **Real infrastructure.** Anvil is a real EVM. The registry is a real
   FastAPI service. Agents are real processes. The only "fake" component
   is mock provisioning mode, which stands in for a real VM host and is
   opaque to the tested role anyway.

2. **Chinese Room counterparty.** When testing buyer behavior, the seller
   agent (from `compose/seller.yml`) plays its role but is treated as a
   black box. The test only asserts buyer-observable properties.

3. **User-visible assertions.** Tests assert outcomes the user cares about:
   "my token balance decreased by the agreed price", "I can SSH into the
   machine I paid for". Not internal state transitions.

4. **Thin wrappers around real code paths.** Tests import and call the
   same library functions the agents use (e.g. `RegistryClient.match_orders`)
   rather than re-implementing them. This keeps test assumptions aligned
   with agent behavior.

5. **Stage isolation via output fixtures.** Each stage's `conftest.py`
   exposes an output fixture representing "state after this stage". Later
   stages consume it. Tests for the stage itself override or introspect
   how the output was produced.

## Running

Docker-compose must be up with all four layers running. For local
development, the root `docker-compose.yml` bundles them:

```bash
# All role tests, mock provisioning (fast)
PROVISIONING_MODE=mock docker compose up -d
uv run pytest tests/roles/ -v

# Just the layer verification
uv run pytest tests/roles/layers/ -v

# A single stage
uv run pytest tests/roles/stages/discovery/ -v

# Just the seller side of discovery
uv run pytest tests/roles/stages/discovery/test_seller.py -v
```
