# Production Stand-Up Overview

This is the canonical entry point for standing up the deployed full stack.
Start here before using the canary runbooks.

This path assumes:

- real ZeroTier networking
- real ERC-8004 registry
- real async provisioning API and worker
- real FRP routing
- real seller inventory
- no `mock` provisioning

Use a dedicated deployment namespace for the first full-stack run. On GCP, that
means a dedicated GCP project rather than a shared project.

## Required External Resources

Before you start, gather or provision:

- a GCP project for images, buckets, and service accounts
- one ZeroTier controller or existing ZeroTier network
- one FRP gateway host
- one provisioning host
- one or more KVM hosts from `compute-provisioning-iac/ansible/inventory/hosts`
- PostgreSQL for the registry
- PostgreSQL for async provisioning
- Redis for the async provisioning job queue
- an authenticated chain RPC endpoint for Base Sepolia
- seller and buyer canary wallets plus a tenant SSH keypair

## Bring-Up Sequence

Follow these documents in order:

1. [Local Secret Layout](local-secrets.md)
2. [Deployable Image Selection](image-selection.md)
3. [Contract Address Bootstrap](contracts.md)
4. [ZeroTier and FRP](zerotier-frp.md)
5. [Registry Deployment](registry.md)
6. [Provisioning Deployment](provisioning.md)
7. [Seller Agent Deployment](agent-seller.md)
8. [Buyer Agent Deployment](agent-buyer.md)
9. [Resource Seeding](resource-seeding.md)
10. [Canary Validation](canary.md)

Supporting references:

- [Deployment Input Checklist](../deployment-input-checklist.md)
- [Clean-Room Acceptance Checklist](../clean-room-acceptance.md)
- [Seller Quickstart](seller-quickstart.md)
- [Human Buyer Walkthrough](human-buyer.md)
- [Buyer Quickstart](buyer-quickstart.md)
- [Support Quickstart](support-quickstart.md)
- [Platform Quickstart](platform-quickstart.md)
- [Host Quickstart](host-quickstart.md)
- [Lessons Learned](lessons-learned.md)
- [Live Role Contracts](live-contracts.md)
- [End-to-End Runbook](../e2e-runbook.md)
- [Production Canary Runbook](../production-canary.md)
- [End-to-End Deployment Test Plan](../e2e-deployment-test-plan.md)

Use `docs/clean-room-acceptance.md` as the tracked final checklist before
signing off the stand-up path as clean-room ready.

## Success Criteria

An operator is ready to move into live canary validation when all of the
following are true:

- registry health is green over the deployed URL
- provisioning health is green over the deployed URL
- seller and buyer agent cards resolve over their deployed ZeroTier URLs
- seller inventory is seeded and visible at `/resources/portfolio`
- buyer and seller agent IDs are registered and canonical `eip155:` IDs
- the async provisioning service can preflight at least one candidate KVM host

Once those are true, continue with [Canary Validation](canary.md).
