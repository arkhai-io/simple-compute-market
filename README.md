<p align="center">
  <a href="https://compute.arkhai.io/">
    <img src="https://github.com/arkhai-io.png" alt="Arkhai" width="160">
  </a>
</p>

# Simple Compute Market

**Open infrastructure for programmable markets, starting with compute.**

Simple Compute Market, or SCM, is a shared, machine-readable market layer for buyers, sellers, operators, applications, and agents.

It provides reusable infrastructure for discovery, signed negotiation, explicit agreement, settlement, fulfillment, and recovery. Market participants keep control of their policies, infrastructure, counterparties, and deployment model.

Compute is the first domain. Custom versioned domain contracts can extend the same machinery to markets for storage, bandwidth, information, and other assets; the implemented domains in this repository are listed below.

If you're looking for a traditional, managed compute marketplace experience while still retaining lots of control over you business decisions, check out [Arkhai Compute](https://compute.arkhai.io/), our managed service layer over SCM. The underlying protocol and self-hosted software remain open.

- [Buyer quickstart](./docs/buyer-quickstart.md)
- [Seller quickstart](./docs/seller-quickstart.md)
- [Registry quickstart](./docs/indexer-quickstart.md)
- [Architecture](./docs/development/ARCHITECTURE.md)
- [Roadmap](./docs/development/ROADMAP.md)
- [Managed service](https://compute.arkhai.io/)

## Why SCM?

Compute capacity is siloed, and buyer requirements are diverse. The terms, payment methods, and delivery systems are rarely uniform.

Most marketplaces solve this by placing discovery, pricing, payment, and fulfillment under one platform. SCM separates those responsibilities into independently operated protocol roles connected through signed interfaces.

- **Buyers** choose registries, storefronts, requirements, and purchasing policies.
- **Sellers** operate sovereign storefronts, and publish offers, negotiate, and coordinate settlement.
- **Seller-side resource services** control provisioning or other domain-specific delivery.
- **Registries** validate and index listings for discovery under operator-defined schemas and access rules.

Applications and agents use the same machine-readable interfaces as the CLI. Each deployment chooses its domains, policies, settlement mechanisms, integrations, and topology.

No canonical role owns discovery, payment, and fulfillment together.

## What makes the market programmable?

SCM exposes market decisions as explicit software interfaces rather than fixed platform workflows.

- **Versioned domain contracts** define what is listed, negotiated, delivered, and returned.
- **Participant-controlled policies** decide how buyers compare offers and how buyers and sellers evaluate proposals.
- **Signed negotiation rounds** produce an explicit agreement or no deal.
- **Settlement mechanisms** turn agreements into financial or non-financial obligations.
- **Fulfillment adapters** connect accepted agreements to seller-owned infrastructure.
- **Evidence and recovery records** make accepted transactions inspectable and resumable.
- **Independent deployment** lets each role run in the topology chosen by its operator.

The market core stays consistent while each domain supplies its own resource vocabulary and deterministic interpretation. Kits, adapters, composition roots, and seller-side services provide the reusable lifecycle machinery around it.

SCM is inspired by [Compositional Game Theory](https://github.com/arkhai-io/cgt) as a practical pattern language for composing smaller decisions with explicit inputs and outputs. SCM applies that idea through signed role interfaces, registered policies, and independently composed market capabilities; it does not claim to strictly implement formal CGT or its guarantees.

Buyer aggregation policies can negotiate with candidate sellers sequentially or in parallel, compare completed agreements, race for the fastest result, or apply custom selection logic.

Learn more:

- [Market roles](./docs/roles.md)
- [Policies and configuration](./docs/configuration.md)

## Core, kits, and domains

SCM separates reusable market machinery from the resource being traded.

```text
composition root
    ├── core role machinery
    ├── domain vocabulary and deterministic interpretation
    └── kit mechanisms and authorities
```

### Core: the common market grammar

`core/` defines the structures and role behavior that apply across markets.

Core includes:

- schema-opaque buyer, storefront, and registry orchestration;
- domain-neutral message, terms, agreement, and settlement-plan carriers;
- typed handoffs and control flow between market phases;
- contracts for loading domain contributions and reusable mechanisms;
- domain-neutral clients and role interfaces.

Core does not need to understand GPUs, virtual machines, physical hosts, API keys, or quotas. It carries versioned domain data without interpreting it.

### Kits: reusable market capabilities

`kit/` contains capabilities that several domains can compose without copying their implementations.

Kits include:

- identity and configuration;
- buyer and seller policy;
- negotiation runtime;
- settlement mechanisms and settlement servicing;
- site and physical-capacity authority;
- resource-pool management;
- capacity publication;
- fulfillment scheduling;
- delivery sinks;
- storefront application composition.

A kit owns the reusable lifecycle of a capability. A domain supplies the values, validation, and hooks needed to use it.

For example:

- the negotiation kit owns signed round ordering, persistence, and terminal-state handling;
- a domain supplies the proposal schema and the policy that decides whether to accept, counter, reject, or exit;
- the settlement kit owns obligation identity, retries, recovery, and servicing;
- a settlement mechanism supplies the actions required to fund, verify, collect, reclaim, or otherwise complete an obligation.

A market installs only the kits it needs.

### Domains: what the market trades

`domains/` defines the resource or service being exchanged.

A domain owns:

- listing and query vocabulary;
- provision and service terms;
- domain-specific validation;
- fixed and negotiable fields;
- domain-specific fulfillment requirements and hooks;
- evidence projections and result semantics;
- buyer-visible result vocabulary.

The repository currently includes:

- **Virtual machines** — compute shape, image, access, lease, provisioning, credentials, and teardown.
- **Bare metal** — physical-host requirements, site allocation, SSH access, lease lifecycle, and capacity restoration.
- **API credits** — service, quantity, credential disposition, quota issuance, and consumption.

The API-credit domain reuses the same discovery, negotiation, settlement, and storefront machinery as the physical domains. It bypasses physical-capacity scheduling because its fulfillment result is a credential and quota rather than an allocated machine.

### Composition roots: runnable roles

A composition root is the wiring boundary for one executable or service role. It combines core role machinery with installed domain contributions and the required kits, mechanisms, authorities, and infrastructure adapters.

The buyer executable and registry behavior are core-owned and load domain contributions from below. Storefront and provisioning roots assemble the shared role machinery with their selected domain runtimes and adapters. A storefront composition may install one or more domain contributions without making core interpret their schemas.

Deployment configuration then decides which runnable roles share a process or network and where each service runs. This allows markets to reuse the same core while making different choices about policy, settlement, infrastructure, and delivery.

Read the [architecture reference](./docs/development/ARCHITECTURE.md) for the complete dependency and composition model.

## How a market transaction works

```text
Seller ── publishes signed listing ──> Registry
                                           │
Buyer ───── discovers candidates ──────────┘
  │
  ├── applies buyer policy
  │
  └── negotiates signed rounds ──────> Storefront
                                           │
                                      explicit agreement
                                           │
                                           ▼
                                    settlement plan
                                           │
                                           ▼
                              obligation materialization
                                           │
                                           ▼
                           funding or readiness, when required
                                           │
                                           ▼
                              domain fulfillment, when applicable
                                           │
                                           ▼
                              evidence and condition evaluation
                                           │
                                           ▼
                           collection, completion, or reclaim
```

The lifecycle is:

1. **Describe** — the seller publishes attributed terms.
2. **Discover** — the buyer finds and compares candidates.
3. **Accept or negotiate** — the parties exchange signed decisions.
4. **Agree** — both parties accept one explicit set of terms.
5. **Plan** — the accepted agreement produces explicit settlement obligations.
6. **Prepare** — the selected mechanism materializes those obligations and establishes any required funding or readiness.
7. **Deliver or introduce** — provisioning domains fulfill the accepted resource; contact exchange instead completes through an authenticated introduction.
8. **Evaluate and resolve** — configured evidence and conditions drive collection, completion, reclaim, or another terminal outcome.

The exact ordering is mechanism-dependent, and settlement servicing may continue after fulfillment.

Listed-price acceptance is the default. Operators may enable signed scalar negotiation for supported markets. Current scalar policies vary the payment amount; quantity, duration, and other terms remain pinned or validated unless the domain explicitly supports otherwise.

## Choose your path

### Buy compute or service access

Use the `market` CLI to discover listings, inspect compatible settlement options, negotiate, purchase, and recover accepted transactions.

[Read the buyer quickstart →](./docs/buyer-quickstart.md)

### Sell virtual machines

Publish VM capacity and connect accepted agreements to seller-operated KVM provisioning.

[Read the VM seller quickstart →](./docs/seller-quickstart.md)

### Sell bare-metal capacity

Publish whole-host offers backed by site capacity, SSH access, teardown, and capacity restoration.

[Read the bare-metal seller quickstart →](./docs/bare-metal-seller-quickstart.md)

### Sell API access

Offer prepaid API credits backed by credential issuance and quota enforcement rather than physical provisioning.

[Read the API-credit cookbook →](./docs/cookbooks/vllm-apicredits-seller.md)

### Deploy market infrastructure

Configure a registry, participant access, domains, policies, settlement mechanisms, integrations, and deployment topology.

[Read the registry operator quickstart →](./docs/indexer-quickstart.md)

Optional networking and connectivity guides:

- [FRP reverse-proxy setup for VM subdomains](./docs/seller-frp-setup.md)
- [Private ZeroTier overlay setup](./docs/zerotier-setup.md)

### Add another domain

Define a versioned resource schema, negotiation terms, settlement requirements, fulfillment contract, evidence, and result vocabulary.

[Read the domain-authoring guide →](./docs/domain-authoring/)

## Supported domains

### Virtual machines

Physical compute with capacity admission, reservation, scheduling, provider execution, credential delivery, lease management, and teardown.

This is the primary reference domain. Mock and live KVM paths are documented.

### Bare metal

Whole-host capacity with site-backed admission, assignment, SSH access, lifecycle management, teardown, and capacity restoration.

### API services

Nonphysical access delivered through credentials and quota. API-service domains retain discovery, negotiation, settlement, evidence, and recovery while bypassing physical-capacity scheduling.

The repository includes an API-credit authority, buyer and seller components, a sample application, and Python, TypeScript, and Rust middleware.

### Custom domains

A custom domain can provide another versioned market contract while reusing the shared market roles and selected kits.

See the [domain-authoring guide](./docs/domain-authoring/).

## Settlement mechanisms

SCM does not require one universal payment or commitment rail.

### Alkahest — `alkahest.v1`

Conditional EVM escrow using the exact chain, asset, and conditions advertised by the seller.

Participants need the applicable wallet, RPC access, gas, and asset.

### Contact exchange — `contact-exchange.v1`

A non-financial mechanism that completes an agreement through a durable, authenticated introduction instead of payment custody.

It is currently composed end to end for the bare-metal domain.

### Managed payments

[Arkhai Compute](https://compute.arkhai.io/) provides a managed payment option alongside SCM's independently operated settlement mechanisms.

See the [settlement specifications](./openspec/specs/README.md) and [current release status](./docs/development/ROADMAP.md#hosted-settlement-release-status).

## Repository map

```text
simple-compute-market/
├── core/           # Domain-neutral contracts and role implementations
├── kit/            # Reusable market capabilities
├── domains/        # Domain contracts and implementations
│   ├── vms/
│   ├── bare_metal/
│   └── apicredits/
├── provisioning/   # Physical-capacity and provisioning authority
├── compose/        # Reusable Docker Compose stacks
├── compose.*.yml    # Domain and development Compose configurations
├── docker-compose.yml
├── helm/           # Kubernetes/Helm deployments
├── e2e-tests/       # Smoke and complete-deal scenarios
├── dev-env/        # Development environment and state generation
├── scripts/        # Build, installation, review, and validation scripts
├── tools/          # Developer and issue-discovery tools
├── manifests/      # Hosted-settlement release trust manifests
├── make/           # Shared Makefile targets
├── Makefile        # Root build, test, and validation entry points
├── install.sh      # Installation entry point
├── openspec/
│   ├── specs/      # Authoritative implemented contracts
│   └── changes/    # Proposed changes and implementation plans
├── docs/           # User, operator, architecture, and development guides
├── .github/
│   └── workflows/  # GitHub Actions workflows
├── AGENTS.md       # Repository engineering guidance
├── README.md
└── LICENSE
```

Selected paths shown. `compose.*.yml` groups the root-level Compose configurations; hidden agent settings, configuration examples, and individual helper files are omitted.

## Open-source public good

SCM is released under the [MIT License](./LICENSE).

- SCM has no SCM-native token.
- The open protocol and self-hosted software impose no Arkhai transaction fee.
- Sellers, infrastructure providers, networks, settlement providers, registry operators, and managed services may charge their own fees.
- [Arkhai Compute](https://compute.arkhai.io/) is a separate managed-service layer; its current and planned charges are separate from the open protocol.
- Each role can be deployed and adapted independently.
- Commercial integration, managed operation, or support does not change the open-source license.

## Development

Before making a non-trivial change, read:

1. [`AGENTS.md`](./AGENTS.md)
2. [OpenSpec contributor workflow](./openspec/README.md)
3. [Architecture](./docs/development/ARCHITECTURE.md)
4. The applicable [capability specification](./openspec/specs/README.md)
5. The applicable [active change](./openspec/changes/README.md)

Run the code-level test suites:

```bash
make test
```

Run documentation and comment-hygiene validation:

```bash
make check-comment-hygiene
```

Validate OpenSpec documents:

```bash
bunx @fission-ai/openspec@latest validate --all --strict
```

Relevant documentation:

- [Documentation index](./docs/)
- [Market roles](./docs/roles.md) and [configuration](./docs/configuration.md)
- [Architecture](./docs/development/ARCHITECTURE.md) and [deployment model](./docs/development/DEPLOYMENT_AND_CONFIG.md)
- [Domain-authoring guide](./docs/domain-authoring/)
- [Testing guide](./docs/development/TESTING.md)
- [Manual validation runbook](./docs/development/VALIDATION_RUNBOOK.md)

## Security

SCM handles signing credentials, payment state, provisioned infrastructure, and issued API credentials.

- Never place signing secrets, wallet keys, payment credentials, action URLs, provider payloads, or issued API credentials in public configuration.
- Pin the exact registries, authorities, environments, settlement mechanisms, and releases you trust.
- Treat local fixtures and development payment runs as development evidence.
- Review the [deployment model](./docs/development/DEPLOYMENT_AND_CONFIG.md) and [testing boundaries](./docs/development/TESTING.md) before production use.

## License

[MIT](./LICENSE) © Arkhai
