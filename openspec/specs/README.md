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
| Marketplace identity | [Spec](marketplace-identity/spec.md) | [Architecture](marketplace-identity/architecture.md) |
| Negotiation protocol | [Spec](negotiation-protocol/spec.md) | [Architecture](negotiation-protocol/architecture.md) |
| Physical provisioning | [Spec](physical-provisioning/spec.md) | [Architecture](physical-provisioning/architecture.md) |
| Planning governance | [Spec](planning-governance/spec.md) | — |
| Registry discovery | [Spec](registry-discovery/spec.md) | [Architecture](registry-discovery/architecture.md) |
| Resource-pool management | [Spec](resource-pool-management/spec.md) | [Architecture](resource-pool-management/architecture.md) |
| Review artifacts | [Spec](review-artifacts/spec.md) | [Architecture](review-artifacts/architecture.md) |
| Settlement configuration | [Spec](settlement-configuration/spec.md) | [Architecture](settlement-configuration/architecture.md) |
| Settlement servicing | [Spec](settlement-servicing/spec.md) | [Architecture](settlement-servicing/architecture.md) |
| Site capacity | [Spec](site-capacity/spec.md) | [Architecture](site-capacity/architecture.md) |
| Storefront publication | [Spec](storefront-publication/spec.md) | [Architecture](storefront-publication/architecture.md) |
| Testing and compatibility | [Spec](test-compatibility/spec.md) | [Architecture](test-compatibility/architecture.md) |

## Hosted settlement acceptance ownership

Hosted settlement acceptance spans two capabilities, with no third test
topology contract:

| Durable decision | Owning permanent documentation |
|---|---|
| Provider-neutral scripted outcomes prove only Arkhai journal, retry, reconciliation, inbox, and idempotency behavior at the hosted producer's internal provider boundary | [`test-compatibility/spec.md`](test-compatibility/spec.md) and [`test-compatibility/architecture.md`](test-compatibility/architecture.md) |
| Supported Stripe behavior is accepted only by the marketplace-owned protected `stripe-test` system lane | [`test-compatibility/spec.md`](test-compatibility/spec.md), [`test-compatibility/architecture.md`](test-compatibility/architecture.md), and [`docs/development/TESTING.md`](../../docs/development/TESTING.md) |
| Protected reports keep marketplace consumer identity separate from the hosted manifest, client, image, signed repository/workflow/source identity, and protected producer-run identity and apply one sanitization/failure taxonomy | [`test-compatibility/spec.md`](test-compatibility/spec.md) and [`docs/development/TESTING.md`](../../docs/development/TESTING.md) |
| Hosted financial E2E composes only ordinary signed production client/service artifacts, with role-scoped prerequisites and fail-closed activation | [`deployment-state/spec.md`](deployment-state/spec.md), [`deployment-state/architecture.md`](deployment-state/architecture.md), and [`docs/development/DEPLOYMENT_AND_CONFIG.md`](../../docs/development/DEPLOYMENT_AND_CONFIG.md) |
| Marketplace/authority ownership and the producer/consumer release boundary | [`docs/development/ARCHITECTURE.md`](../../docs/development/ARCHITECTURE.md) |
| Current operator commands and staged evidence fields | [`e2e-tests/tests/e2e/roles/README.md`](../../e2e-tests/tests/e2e/roles/README.md) |

## Reading order

For a cross-cutting change:

1. Start with the repository-wide architecture map.
2. Read the owning capability's `architecture.md` for design intent and limits.
3. Read its `spec.md` for the enforceable current contract.
4. Inspect active changes for proposed deltas before editing either permanent document.
