## Context

The planning migration removed the monolithic architecture/backlog documents, but its first pass created a mixed-audience `KNOWN_ISSUES.md`. Buyer, seller, registry, provisioner, and test-author guidance should instead live where that role looks for setup and troubleshooting. OpenSpec owns current normative contracts and proposed changes.

## Goals / Non-Goals

**Goals:**
- Give every verified documentation gap a named role audience and a role-facing destination.
- Keep current normative behavior in the owning capability spec and intended changes in active changes.
- Remove mixed generic issue pages after their entries are classified and moved.

**Non-Goals:**
- Do not duplicate normative requirements or implementation plans in role-facing prose.
- Do not publish unverified recovery instructions.

## Decisions

- Classify each entry as current role guidance, current normative behavior, or intended change before writing prose.
- Put buyer/seller/registry/provisioner behavior in that role's quickstart or operator guide; put test architecture in the e2e contributor guide.
- Keep unresolved negotiation-watchdog recovery in this change until code and focused tests establish the safe procedure.
- Link role guides to OpenSpec when readers need the normative contract or an intended change; do not restate the change plan.
- Delete generic issue pages rather than maintaining a second taxonomy.

## Risks / Trade-offs

- Role-specific material can be duplicated accidentally across quickstarts; link to one owning page when audiences overlap.
- Current behavior may be undesirable; documenting it in a spec does not close or supersede a change intended to alter it.
