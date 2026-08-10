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

### Publication and the capacity client are grouped because listings depend on capacity

A publication runtime derives listings from available capacity, so extracting one without
the other leaves the seam cutting between a derivation and its input. They are smaller
together than the settlement group and share a single data flow.

### The capacity client's size gap is the thing to analyse, not to assume

556 lines against 217 is too large to be explained by codecs and configuration alone.
Plausible sources: multi-site aggregation and placement, the projection cache, and
site-pinned claim routing — all of which are arguably generic and arguably VM-specific
depending on whether a second domain ever aggregates sites.

The change must decide per capability rather than moving the whole file or none of it.
The default should be to extract only what a second consumer demonstrably needs, since
generalizing a capability with one consumer produces an abstraction shaped entirely by
that consumer.

`site_projection_cache` and `multi_registry_client` exist only in the VM storefront and
are deliberately out of scope for the same reason: no second consumer exists to shape
them.

### Claim construction stays domain-owned

What a claim contains is domain semantics — a compute claim carries dimensions, a credits
claim carries units. The client's reserve, commit, and release handling is not. This is
the cleanest division in the change and should be stated so the extraction does not drag
claim shape into kit.

## Risks / Trade-offs

- **[Over-extracting the capacity client]** → Named above. Extract what a second
  consumer needs; leave single-consumer capabilities in the domain.
- **[Under-extracting and leaving bare metal unable to reserve]** → The opposite failure.
  The completion test is whether bare metal can reserve and publish by composition.
- **[Claim shape drifts into kit]** → Would reintroduce the compute-vocabulary problem
  that `kit/site` already demonstrates.
- **[Collides with in-flight capacity work]** → Goals 2, 3, and 5 all modify capacity
  client behavior. Extraction after those land is likely cheaper than during.

## Migration Plan

Extract, compose all three domains, remove every copy, then packaging follow-through.
Rollback is a code revert; no persisted state or wire surface changes.

## Open Questions

- **Should this extraction wait for the in-flight changes that modify the same code?**
  Extracting during active modification means repeated rebasing; extracting after means
  those changes land in one domain and need porting. Deferrable to sequencing, and the
  answer may differ per concern.
