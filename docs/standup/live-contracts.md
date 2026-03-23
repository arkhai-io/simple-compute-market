# Live Role Contracts

This document freezes the shared live contracts that production-facing role
flows must follow before buyer, seller, support, platform, and host-specific
entrypoints evolve independently.

## Shared Contract Areas

The shared live contract covers:

- the public endpoint model
- the auth/signing model
- the agent identity model
- the artifact schema
- the lifecycle states
- the cleanup semantics
- the support correlation contract

These shared contracts apply across:

- buyer
- seller
- platform
- support
- host

## Public Endpoint Model

Every production-facing flow should distinguish between:

- `request_url`: the URL the local caller actually uses
- `auth_url`: the canonical URL the remote service verifies for signatures

When no proxy or tunnel is involved, the `request_url` and `auth_url` may be
the same. When a proxy, tunnel, or load balancer exists, both values must still
be explicit in the artifact schema.

## Auth/Signing Model

Role flows that mutate market state must sign requests against the canonical
`auth_url`, not against whatever transport-specific `request_url` a human or
agent happens to use.

That shared auth/signing model is what keeps:

- buyer purchase requests
- seller publish requests
- support cleanup requests

consistent across direct, proxied, and tunneled access patterns.

## Agent Identity Model

Market-facing roles use canonical agent identities:

- buyer agent
- seller agent

Administrative roles still produce artifacts, but they are not themselves
market agents:

- platform
- support
- host

This keeps the agent identity model aligned with the protocol while leaving
infrastructure administration under operator or service identities.

## Artifact Schema

Every role-facing flow should emit a structured artifact with the same top-level
shape:

- `schema_version`
- `role`
- `action`
- `status`
- `created_at`
- `endpoints`
- `correlation`
- `details`

The shared artifact schema must support common correlation keys such as:

- `order_id`
- `job_id`
- `vm_target`

and endpoint keys such as:

- `request_url`
- `auth_url`

## Lifecycle States

Role flows should use clear terminal and non-terminal lifecycle states. At the
artifact layer, the shared states are:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Role-specific inner states may exist, but the outer artifact should still map
back to these lifecycle states.

## Cleanup Semantics

Every production-facing role flow must define what cleanup means:

- buyer and seller flows close orders and optionally reclaim a VM
- support flows may close orders, destroy, and undefine
- platform flows may roll back or redeploy
- host flows may undo enrollment or mark the host unavailable

Cleanup semantics must be explicit in the role docs and recoverable from the
artifact alone.

## Support Correlation

Support tooling must be able to correlate a live issue across:

- order IDs
- job IDs
- VM targets
- request_url and auth_url
- buyer and seller agent identities

That support correlation contract is what lets a support operator reason about a
broken or completed run without reconstructing hidden context from logs alone.
