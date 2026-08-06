# Design

## Context

Per-domain line counts and the absence of these concerns in bare metal are recorded in
`kit-storefront-composition-seam`'s `design.md`, measured 2026-08-06. Re-verify before
implementing.

## Goals / Non-Goals

**Goals:** one implementation of these concerns, composed by every domain; bare metal
gains them.

**Non-Goals:** behavior change, sibling concerns, layout churn, core changes.

## Decisions

### Group the three, because they are one control flow

Settlement jobs, claim servicing, and failure policy call each other. Extracting
`settlement_jobs` alone would put a kit module in the middle of a domain-owned failure
path, which is a worse layering violation than the duplication it replaces.

### The domain supplies verification and plan construction, not orchestration

Escrow verification and settlement plan construction are genuinely domain-specific — what
counts as a valid escrow and what obligations a deal produces differ per domain. Both are
already contract capabilities (`settlement.verify`, `settlement.build_plan`), so the seam
exists.

Orchestration, retry, idempotency, and resume behavior are not domain-specific and are
exactly where two hand-maintained copies drift.

### Failure policy actions are a vocabulary, not a mechanism

The VM implementation is more than twice the size of the API-credits one, and most of
the difference is the set of actions it can take. The mechanism — evaluate a failure,
select actions, apply them idempotently — is shared; the action set is domain-supplied.

Recorded because the size gap invites the conclusion that VM's failure policy is
domain-specific in its entirety, which would leave the largest of the three unextracted.

## Risks / Trade-offs

- **[The three-way grouping makes the change large]** → Accepted; splitting them cuts
  through one control flow. Break into sections by lifecycle stage.
- **[Failure actions are treated as mechanism and generalized]** → Would push compute
  vocabulary into kit. The action set is domain-supplied.
- **[Resume and idempotency behavior differs between copies]** → This is durable-state
  behavior, so a silent choice here can corrupt in-flight deals rather than merely
  changing behavior. Compare explicitly before moving.
- **[In-flight settlement changes collide]** → `add-settlement-plan-shapes` is building
  generic per-obligation lifecycle in this area. Coordinate; it may be cheaper to extract
  after it lands, or to have it land onto the kit implementation.

## Migration Plan

Extract, compose all three domains, remove every copy, then packaging follow-through.
Rollback is a code revert; no persisted state or wire surface changes.

## Open Questions

- **Should this extraction wait for the in-flight changes that modify the same code?**
  Extracting during active modification means repeated rebasing; extracting after means
  those changes land in one domain and need porting. Deferrable to sequencing, and the
  answer may differ per concern.
