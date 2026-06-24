# Simple Compute Market

Simple Compute Market is a reference implementation of an open compute market. Buyers find sellers through a listings registry, negotiate prices peer-to-peer over signed HTTP, and settle on-chain with escrow-backed obligations via [Alkahest](https://github.com/arkhai-io/alkahest). Buyers run a CLI; sellers run a storefront server; the registry is only a listings index; provisioning stays with the seller's own service.

Compute is the concrete domain, but the goal is the pattern: userland buyer, storefront, and registry roles with peer-to-peer negotiation and escrowed settlement. Another asset class should be able to reuse that shape by substituting its own resource schemas, escrow contracts, and execution modules.

## Design notes

Simple Compute Market is inspired by [Compositional Game Theory (CGT)](https://github.com/arkhai-io/cgt), which frames multi-agent interactions as compositions of atomic games: indivisible agent decisions with clear input/output contracts, combined into larger sequential and parallel structures. The protocol exposes its primitives as signed HTTP endpoints, CLI commands, and registered middleware, so behaviors like multi-agent coordination, participants that buy and sell dynamically, and meta-strategies that adapt across markets can be built by composing those primitives externally. The buyer-side aggregation hook is one example: it receives candidate listings plus a per-listing negotiation callback, then decides whether to run those negotiations sequentially, in parallel, or through a custom scoring rule. Both sides' per-round negotiation policy chains follow the same pattern.

## Repository layout

- `domains/vms/buyer/` — VM buyer CLI (`market` console script)
- `domains/vms/storefront/` — VM seller server + admin CLI (`market-storefront` console script)
- `domains/vms/provisioning/service/` — VM provisioning microservice
- `kit/alkahest/`, `kit/config/`, `kit/identity/` — Shared from-below helpers for chain settlement, config, and identity
- `kit/policy/` — Shared negotiation middleware machinery
- `core/registry/` — Listing registry API (FastAPI)
- `core/registry-client/` — Async + sync Python client for the registry HTTP API
- `core/storefront-client/` — Async + sync Python client for the storefront HTTP API
- `compose/` — Docker Compose stacks for the seller side
- `helm/` — Kubernetes/Helm charts for production seller + registry deployments
- `scripts/zerotier/` — ZeroTier controller scripts
- `docs/` — User/operator quickstarts and configuration reference (developer/internal docs live under `docs/development/`)
- `scripts/` — Repo-root wrappers for build, install, validation, and clean-room workflows
- `tools/` — Repo-owned developer and validation tools

## Getting started

Pick the role you're standing up:

- **Buy compute** → [`docs/buyer-quickstart.md`](./docs/buyer-quickstart.md)
- **Sell compute** → [`docs/seller-quickstart.md`](./docs/seller-quickstart.md)
- **Run your own listing registry** → [`docs/indexer-quickstart.md`](./docs/indexer-quickstart.md)
- **Add FRP reverse-proxy for VM subdomains (seller)** → [`docs/seller-frp-setup.md`](./docs/seller-frp-setup.md)
- **Set up a private ZeroTier overlay (operator)** → [`docs/zerotier-setup.md`](./docs/zerotier-setup.md)

A typical buy, once `buyer.toml` is in place:

```bash
market listing list --gpu-model H200
market buy --gpu-model H200 --duration-hours 1
```

The CLI handles negotiation rounds, creates the on-chain escrow, polls for provisioning, and prints the connection + tenant credentials when the VM is ready.

Validation and issue-discovery docs:

- **Manual validation runbook** → [`docs/development/VALIDATION_RUNBOOK.md`](./docs/development/VALIDATION_RUNBOOK.md)
- **Issue discovery harness** → [`docs/development/ISSUE_DISCOVERY.md`](./docs/development/ISSUE_DISCOVERY.md)
- **Repo tooling overview** → [`tools/README.md`](./tools/README.md)

## Reference

- [`docs/development/ARCHITECTURE.md`](./docs/development/ARCHITECTURE.md) — end-to-end design: components, request flow, on-chain schema, negotiation policy machinery
- [`docs/configuration.md`](./docs/configuration.md) — config reference: bundled negotiation + aggregation policies and how to write custom ones
