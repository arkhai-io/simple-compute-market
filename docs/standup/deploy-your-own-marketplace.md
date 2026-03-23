# Deploy Your Own Marketplace

Use this path when you are starting from zero and need to stand up your own SMS
marketplace rather than joining an existing one.

This is the newcomer deployment bridge between:

- high-level navigation in [Get Started](../get-started.md)
- the full bootstrap sequence in [Production Stand-Up Overview](overview.md)
- the day-2 operator wrapper in [Platform Quickstart](platform-quickstart.md)

Canonical doc paths:

- `docs/standup/overview.md`
- `docs/standup/platform-quickstart.md`

## Who This Is For

- a platform owner deploying a new marketplace
- an operator or coordinating agent that needs to stand up the full live stack
  before buyers and sellers can use it

## What You Need Before You Start

- cloud and network resources for a real deployment
- operator-owned secrets and SSH keys kept outside the repo
- at least one buyer agent and one seller agent lane for the first canary
- one current documented live lane, which defaults to Ethereum Sepolia in the
  production quickstarts

## The Bootstrap Sequence

Follow [Production Stand-Up Overview](overview.md) from top to bottom. The
canonical bring-up sequence is:

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

The overview is the zero-to-live deployment path. Do not start with the
platform wrapper alone if you have not prepared the shared secrets, registry,
provisioning service, agents, and inventory yet.

## When To Switch To The Operator Wrapper

After the bootstrap sequence is in place, use
[Platform Quickstart](platform-quickstart.md) for the repeatable operator
surface:

- `deploy` to render envs, preflight the chain profile, roll out live targets,
  and refresh agent ids
- `verify` to run the repo deployment gates against the rendered bundle
- `canary` to drive the production-facing canary path

## Success Criteria

Treat this path as complete only when:

- the full stand-up sequence in [Production Stand-Up Overview](overview.md)
  finishes cleanly
- the platform wrapper in [Platform Quickstart](platform-quickstart.md) can run
  `deploy`, `verify`, and `canary` against the resulting marketplace
- buyers and sellers can proceed to their own quickstarts without additional
  operator-only bootstrap steps
