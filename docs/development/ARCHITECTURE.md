# Arkhai Market Stack — Architecture Overview

This page is a non-normative orientation guide. Current behavioral and architectural contracts live in [`openspec/specs/`](../../openspec/specs/); proposed work lives in [`openspec/changes/`](../../openspec/changes/). Do not add requirements or backlog items here.

## System shape

Arkhai is a reference implementation of an agent-driven marketplace. Buyers discover seller listings through a shared registry, negotiate through signed synchronous HTTP rounds, materialize settlement plans, and service their obligations over time. Seller storefronts publish market-facing capacity and delegate authoritative physical allocation and fulfillment to site/provisioning services.

```text
buyer (`market`) ── discovery ──> registry
       │                            ▲
       └─ signed negotiation ──> storefront
                                  │
                                  ├─ settlement/claims ──> EVM / Alkahest
                                  └─ capacity/fulfillment ──> site authority + provisioner
```

Local development adds an Anvil fixture. Production permits independently operated registries, seller stacks, and ephemeral or long-running buyers.

## Composition model

Core role packages own schema-opaque market control flow. Domain packages own deterministic listing/message/Terms/materialization/receipt semantics for one market. Kit packages supply reusable identity, policy, settlement-mechanism, configuration, site, and provisioning capabilities from below. Concrete composition roots inject domain and kit implementations into core roles.

The normative dependency and plugin contracts are in the [market composition specification](../../openspec/specs/market-composition/spec.md).

## Capability map

| Area | Normative specification |
|---|---|
| Core/kit/domain boundaries and executable ownership | [Market composition](../../openspec/specs/market-composition/spec.md) |
| Registry publication and schema-driven discovery | [Registry discovery](../../openspec/specs/registry-discovery/spec.md) |
| Buyer-driven rounds and deterministic Terms | [Negotiation protocol](../../openspec/specs/negotiation-protocol/spec.md) |
| Plans, claims, heartbeats, and mechanism codecs | [Settlement servicing](../../openspec/specs/settlement-servicing/spec.md) |
| Seller surfaces and listing publication | [Storefront publication](../../openspec/specs/storefront-publication/spec.md) |
| Capacity authority, reservations, aggregation, and events | [Site capacity](../../openspec/specs/site-capacity/spec.md) |
| Resource pool administration, provider configuration, and host membership | [Resource pool management](../../openspec/specs/resource-pool-management/spec.md) |
| Scheduling, fulfillment, jobs, and lease release | [Physical provisioning](../../openspec/specs/physical-provisioning/spec.md) |
| Buyer plugins, policies, aggregation, and recovery | [Buyer orchestration](../../openspec/specs/buyer-orchestration/spec.md) |
| Deployment, persistence, migrations, and packaging | [Deployment and state](../../openspec/specs/deployment-state/spec.md) |
| Test levels, fixtures, e2e staging, and compatibility | [Testing and compatibility](../../openspec/specs/test-compatibility/spec.md) |

## Official physical-settlement vocabulary

Use **Market Agreement**, **Capacity Offering**, **Capacity Projection**, **Capacity Reservation**, **Physical Resource**, **Resource Pool**, **Physical Settlement**, **Settlement Resource**, **PhysicalSettlementScheduler**, **FulfillmentProvider**, and **Settlement Record**. Stable cross-service identities include the agreement/deal reference and `allocation_id`; `pool_id` and `resource_id` remain boundary-sensitive; scheduling establishes `settlement_resource_id`. Provider metadata stays opaque outside the provider/lifecycle boundary.

See [site capacity](../../openspec/specs/site-capacity/spec.md) and [physical provisioning](../../openspec/specs/physical-provisioning/spec.md) for the contracts behind these terms. The storefront translates negotiated terms into concrete fulfillment requirements; provisioning validates those requirements against the held allocation and owns idempotent physical dispatch, provider resolution, settlement-resource assignment, and execution against the scheduler-selected Settlement Resource. Provider-neutral fulfillment contracts live in `kit/resource-pools`, while domain-specific requirement parsing and provider translation remain with the domain.

## Planning and operations

- OpenSpec index and contributor workflow: [`openspec/README.md`](../../openspec/README.md)
- Active and deferred changes: [`openspec/changes/`](../../openspec/changes/)
- Role-facing setup and troubleshooting: [`buyer-quickstart.md`](../buyer-quickstart.md), [`seller-quickstart.md`](../seller-quickstart.md), and [`indexer-quickstart.md`](../indexer-quickstart.md)
- Configuration reference: [`../configuration.md`](../configuration.md)
- Role boundaries: [`../roles.md`](../roles.md)
- Validation runbook: [`VALIDATION_RUNBOOK.md`](VALIDATION_RUNBOOK.md)
- Release procedure: [`RELEASING.md`](RELEASING.md)

## Legacy section map

Source comments may still mention historical section names while they migrate to direct spec links:

- “Buyer negotiation policy surface” → [Buyer orchestration](../../openspec/specs/buyer-orchestration/spec.md)
- “Capacity and the Site Authority” → [Site capacity](../../openspec/specs/site-capacity/spec.md)
- “Settlement Lifecycle” → [Settlement servicing](../../openspec/specs/settlement-servicing/spec.md)
- “API-credits market domain” → [Market composition](../../openspec/specs/market-composition/spec.md), [Storefront publication](../../openspec/specs/storefront-publication/spec.md), and [Site capacity](../../openspec/specs/site-capacity/spec.md)
- “State Management and Schema Migration Strategy” → [Deployment and state](../../openspec/specs/deployment-state/spec.md)
- “Testing Strategy” → [Testing and compatibility](../../openspec/specs/test-compatibility/spec.md)
