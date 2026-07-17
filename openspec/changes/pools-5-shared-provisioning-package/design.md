## Context

See `proposal.md` for the supersession finding: the originally-planned
`core/provisioning`/`core_provisioning` package should not be created,
because `provisioning/compute`/`compute_provisioning` already exists and
`market-platform-compute-30-extract-service` already owns extracting the
remaining generic machinery there.

This design.md intentionally stays minimal. Detailed decisions (exact
module layout, what moves vs. what stays VM-local) belong to the
design-review pass the activation condition triggers, not to this
placeholder.

## Goals / Non-Goals

See proposal.md.

## Decisions

### 1. The ownership rule already exists; this change only extends its scope

`physical-provisioning`'s "Compute-owned caller contract" requirement
already establishes that shared, executor-neutral models belong in
`compute_provisioning` rather than the VM domain. This change's only
concrete claim is that `pools-2`/`pools-3`'s scheduler and provider
contracts should eventually follow the same rule — not a new ownership
principle, an extension of scope for one already decided.

## Risks / Trade-offs

- **Premature extraction risk.** Moving these contracts before a second
  domain needs them risks designing a boundary against a sample size of
  one, the same anti-pattern the original POOLS-5 plan was written to
  avoid duplicating VM-domain code — just in the opposite direction.

## Migration Plan

None yet. A migration plan belongs to the design-review pass triggered by
the activation condition, once its actual scope is known.
