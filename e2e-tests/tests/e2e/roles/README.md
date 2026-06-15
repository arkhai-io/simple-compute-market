# Role-separated integration tests

Tests are organized around the **deployment topology** of the marketplace:
four independent layers and a five-stage pipeline, with buyer and seller
as independent roles within each stage.

## The four layers

These correspond to four independently-deployed units of software, each
run by a different party in production:

1. **External** — the EVM chain with Alkahest contracts.
   Run by: nobody in this repo (it's a real chain).
   Dev stand-in: `compose/external.yml` (Anvil + contract deployer).

2. **Registry** — the indexer service that lists orders and agents so
   buyers and sellers can discover each other.
   Run by: a marketplace operator (infra provider).
   Deployment: `compose/registry.yml` (operator-facing) or
   `compose/registry.dev.yml` (dev rig variant).

3. **Seller node** — a seller's agent + their own provisioning service.
   Run by: each independent seller, on their own machine.
   Deployment: `compose/seller.yml`.

4. **Buyer node** — a buyer's agent.
   Run by: each independent buyer, on their own machine.
   Deployment: `compose/buyer.yml`.

Layer fixtures (`external_world`, `registry_layer`, `seller_node`,
`buyer_node`) correspond 1:1 to these units. A buyer-perspective test
depends on `external_world + registry_layer + buyer_node`. A seller
test depends on `external_world + registry_layer + seller_node`. A
cross-role test depends on all four.

## Structure

```
roles/
├── conftest.py                  # shared role fixtures (buyer_cli + the layer fixtures)
├── buyer_cli.py                 # BuyerCli subprocess wrapper + buyer_cli fixtures
├── layers/                      # Layer liveness + fixtures
│   ├── test_external.py         # Chain + contracts → external_world
│   ├── test_registry.py         # Registry/indexer → registry_layer
│   └── test_seller.py           # Seller's storefront + provisioning → seller_node
│
└── scenarios/                   # Full multi-step deals, organized by domain
    ├── vms/                     # VM compute market — most scenarios live here, and
    │   ├── conftest.py          #   they share its conftest (VM autouse fixtures:
    │   ├── escrow_helper.py     #   host registration, storefront resume, resource
    │   ├── test_full_deal.py    #   release) + escrow_helper.
    │   ├── test_full_deal_buyer_cli.py
    │   ├── test_buy_oneshot_buyer_cli.py
    │   ├── test_compute_dynamic_listings.py
    │   ├── test_multi_registry.py        # registry fan-out, on the VM vehicle
    │   └── test_non_erc20_settlement.py  # settlement variants, on the VM vehicle
    ├── apitokens/               # API-tokens market (its own bring-up; no VM conftest)
    │   └── test_tokens_deal_buyer_cli.py
    └── core/                    # settlement-mechanism scenarios with no domain service
        └── test_alkahest_escrow_codecs.py
```

Scenarios are grouped by domain because most are single-domain. The
domain a scenario lives under is decided by what it actually needs: a
scenario sits in `vms/` if it drives the VM storefront/provisioning
(so it shares that conftest's fixtures), in `apitokens/` if it drives
the tokens stack, and in `core/` if it touches no domain service at all
(e.g. round-tripping Alkahest codecs against the chain). `multi_registry`
and `non_erc20_settlement` are really core capabilities — registry
fan-out, non-ERC20 settlement — but ride the VM domain as their test
vehicle, so they live in `vms/`. Selection is by pytest marker, so this
grouping is purely navigational and does not change how tests are run.

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
development, the root `docker-compose.yml` bundles every domain on one
shared dev chain (it `include:`s `compose.dev.yml` + each
`domains/<domain>/compose.yml`). A single domain can be brought up on its
own via its wrapper — `docker compose -f compose.vms.yml up` or
`docker compose -f compose.apitokens.yml up` — but the role tests below
expect the full stack:

```bash
# Bring the stack up (mock provisioning, fast)
PROVISIONING_MODE=mock docker compose up -d

# Tests select by marker (see the markers table in pyproject.toml); the
# Makefile wraps this as `make test-module MODULE=<marker>`.
uv run pytest -m e2e_deal_buyer_cli -v     # a VM deal scenario
uv run pytest -m e2e_tokens_deal -v        # the API-tokens deal scenario

# Or by path — the layer liveness checks, or one domain's scenarios:
uv run pytest tests/e2e/roles/layers/ -v
uv run pytest tests/e2e/roles/scenarios/apitokens/ -v
uv run pytest tests/e2e/roles/scenarios/vms/ -v
```
