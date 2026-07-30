# Capability Documentation Index

This directory describes the implemented system by capability.

- `spec.md` is the normative, machine-validated contract: observable behavior, invariants, ownership, and acceptance scenarios.
- `architecture.md` is optional durable explanatory context: conceptual models, design motivation, trade-offs, relationships, and current limits.
- [`docs/development/ARCHITECTURE.md`](../../docs/development/ARCHITECTURE.md) is the repository-wide map connecting the capabilities.
- [`openspec/changes/`](../changes/) contains proposed transitions and temporary implementation plans.

An architecture companion does not replace a normative requirement. When explanatory prose states behavior implementations must satisfy, the owning `spec.md` must also express that invariant. OpenSpec currently validates and synchronizes only `spec.md`; changes that accept durable rationale must name the companion-file promotion explicitly.

## Capabilities

| Capability | Normative contract | Architecture and rationale |
|---|---|---|
| API credits | [Spec](api-credits/spec.md) | [Architecture](api-credits/architecture.md) |
| Buyer orchestration | [Spec](buyer-orchestration/spec.md) | [Architecture](buyer-orchestration/architecture.md) |
| Compute provisioning contract | [Spec](compute-provisioning-contract/spec.md) | — |
| Deployment and state | [Spec](deployment-state/spec.md) | [Architecture](deployment-state/architecture.md) |
| Fulfillment | [Spec](fulfillment/spec.md) | [Architecture](fulfillment/architecture.md) |
| Market composition | [Spec](market-composition/spec.md) | [Architecture](market-composition/architecture.md) |
| Negotiation protocol | [Spec](negotiation-protocol/spec.md) | [Architecture](negotiation-protocol/architecture.md) |
| Physical provisioning | [Spec](physical-provisioning/spec.md) | [Architecture](physical-provisioning/architecture.md) |
| Planning governance | [Spec](planning-governance/spec.md) | — |
| Registry discovery | [Spec](registry-discovery/spec.md) | [Architecture](registry-discovery/architecture.md) |
| Resource-pool management | [Spec](resource-pool-management/spec.md) | [Architecture](resource-pool-management/architecture.md) |
| Review artifacts | [Spec](review-artifacts/spec.md) | [Architecture](review-artifacts/architecture.md) |
| Settlement servicing | [Spec](settlement-servicing/spec.md) | [Architecture](settlement-servicing/architecture.md) |
| Site capacity | [Spec](site-capacity/spec.md) | [Architecture](site-capacity/architecture.md) |
| Storefront publication | [Spec](storefront-publication/spec.md) | [Architecture](storefront-publication/architecture.md) |
| Testing and compatibility | [Spec](test-compatibility/spec.md) | [Architecture](test-compatibility/architecture.md) |

## Reading order

For a cross-cutting change:

1. Start with the repository-wide architecture map.
2. Read the owning capability's `architecture.md` for design intent and limits.
3. Read its `spec.md` for the enforceable current contract.
4. Inspect active changes for proposed deltas before editing either permanent document.
