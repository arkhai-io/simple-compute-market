## Context

The original documentation backlog mixed role guidance, normative behavior, static inventories, and unresolved implementation work. Since then, role quickstarts, domain-authoring guidance, e2e contributor documentation, permanent OpenSpec capability specifications, and companion architecture documents have established explicit owners. The generic known-issues page no longer exists.

## Goals / Non-Goals

**Goals:**
- Promote audience-owned documentation as a permanent planning rule.
- Record which legacy documentation requests are fulfilled, rejected, or still unresolved.
- Close this broad documentation change without presenting unverified behavior as guidance.

**Non-Goals:**
- Recreate endpoint, database-schema, package, port, or generated contract-address inventories.
- Publish negotiation-watchdog recovery instructions without concurrency safety evidence.
- Claim GPU passthrough validation without a supported hardware run.

## Decisions

### Promote audience ownership

Verified operational constraints belong in the guide for the buyer, seller, registry operator, provisioner, or test contributor who can act on them. Normative behavior remains in the owning capability specification, and intended behavior remains in an active change.

### Close fulfilled or inappropriate inventory requests

- Buyer and seller recovery guidance exists in their quickstarts.
- E2e staged-state and role behavior belongs in the role contributor guide.
- Settlement and domain integration rationale belongs in permanent capability architecture.
- Local development contract addresses remain generated state rather than a copied catalog.
- Database schema truth remains in migrations/code; permanent docs describe ownership and lifecycle boundaries.
- The proposed symmetric negotiation channel is obsolete because current negotiation is buyer-driven.

### Keep unresolved behavior out of documentation

Negotiation-watchdog terminalization lacks evidence that it cannot race an in-flight continuation. GPU passthrough instructions exist in the VM IaC manual but have no supported hardware validation scenario. Those outcomes require focused behavioral/evidence changes before role documentation can claim safe recovery or support.

## Risks / Trade-offs

- **[A reader wants a single exhaustive catalog]** → Link to authoritative generated/code sources and maintain task-oriented guides instead of duplicating volatile inventories.
- **[Unresolved watchdog/GPU work is forgotten]** → Record it in the campaign index as audited follow-up candidates, but do not keep this mixed broad change active.

## Promotion Record

| Decision | Permanent destination |
|---|---|
| Audience-owned operational documentation | `openspec/specs/planning-governance/spec.md` |
| Normative/spec versus architecture companion ownership | `openspec/specs/planning-governance/spec.md`, `openspec/README.md`, and `openspec/specs/README.md` |
| Repository-wide role/document map | `docs/development/ARCHITECTURE.md` |

The remaining watchdog and GPU questions are not promoted as current architecture.
