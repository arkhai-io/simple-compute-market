# Simple Compute Market

A reference implementation of an open compute market: buyers find sellers through a listings registry, negotiate prices peer-to-peer over signed HTTP, and settle on-chain with escrow-backed obligations via [Alkahest](https://github.com/arkhai-io/alkahest). Buyers run a CLI, sellers run a storefront server, the registry is a listings index, and provisioning is the seller's own service.

Compute is the concrete domain. The architectural pattern — userland buyer, storefront, and registry roles with peer-to-peer negotiation and escrowed settlement — is intended to be portable; another asset class substitutes the resource schemas, escrow contracts, and execution modules.

## Design notes

[Compositional Game Theory (CGT)](https://github.com/arkhai-io/cgt) frames multi-agent interactions as compositions of atomic games — indivisible agent decisions with clear input/output contracts — combined into larger sequential and parallel structures. The protocol exposes its primitives as discrete affordances (signed HTTP endpoints, CLI commands, registered middlewares), so behaviors like multi-agent coordination, participants that buy and sell dynamically, and meta-strategies that adapt across markets can be built by composing those primitives externally. The buyer's cross-listing aggregation policy and both sides' per-round negotiation policy chains are instances of this shape.

## Repository layout

- `buyer/` — Buyer CLI (`market` console script)
- `storefront/` — Seller server + admin CLI (`market-storefront` console script)
- `provisioning-service/` — VM provisioning microservice
- `service/` — Shared infra clients (chain, alkahest, registry indexer) used by both buyer and storefront
- `policy/` — Shared negotiation middleware machinery
- `registry-service/` — Listings registry / indexer API (FastAPI)
- `registry-client/` — Async + sync Python client for the registry HTTP API
- `compose/` — Docker Compose stacks for the seller side
- `helm/` — Kubernetes/Helm charts for production seller + registry deployments
- `infra/zerotier/` — ZeroTier controller scripts
- `docs/` — Architecture notes, quickstarts, configuration reference

## Getting started

Pick the role you're standing up:

- **Buy compute** → [`docs/buyer-quickstart.md`](./docs/buyer-quickstart.md)
- **Sell compute** → [`docs/seller-quickstart.md`](./docs/seller-quickstart.md)
- **Run your own indexer registry** → [`docs/indexer-quickstart.md`](./docs/indexer-quickstart.md)
- **Add FRP reverse-proxy for VM subdomains (seller)** → [`docs/seller-frp-setup.md`](./docs/seller-frp-setup.md)
- **Set up a private ZeroTier overlay (operator)** → [`docs/zerotier-setup.md`](./docs/zerotier-setup.md)

A typical buy, once `buyer.toml` is in place:

```bash
market listing list --gpu-model H200
market buy --gpu-model H200 --duration-hours 1
```

The CLI handles negotiation rounds, creates the on-chain escrow, polls for provisioning, and prints the connection + tenant credentials when the VM is ready.

## Reference

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — end-to-end design: components, request flow, on-chain schema, negotiation policy machinery
- [`docs/configuration.md`](./docs/configuration.md) — config reference: bundled negotiation + aggregation policies and how to write custom ones

