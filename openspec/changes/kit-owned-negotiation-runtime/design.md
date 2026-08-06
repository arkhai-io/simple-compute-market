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

### The protocol is the mechanism; everything domain-shaped is already a hook

The negotiation runtime already calls out to the domain contract for codecs and for the
seller policy hook. Those call sites are the seam, and they are why this concern is
extractable at all despite its size — the domain-specific parts are already named and
injected rather than interleaved.

What is not yet separated is configuration: timeouts, watchdog intervals, and escrow
proposal handling read from a domain's own settings module. Those become supplied values.

### The two copies have diverged, and the VM one is ahead

The VM implementation carries guards the API-credits one does not. Extraction must not
quietly impose VM guards on API credits, nor quietly drop them.

Each guard needs a deliberate disposition: universal and therefore kit-owned, or
compute-specific and therefore a domain-supplied hook. `_reject_unsupported_resource_shape_request`
is the clearest example — it compares a requested resource shape against a listing's,
which is meaningless for a domain whose offer has no shape.

Getting this wrong in either direction is the main risk in the change, and it is why the
comparison in task 1.2 is a task rather than an assumption.

### Bare metal gains a working negotiation for the first time

It has no implementation, so composing it is not a swap but an addition. Its suites will
exercise a protocol path it has never run, and gaps found there are bare-metal findings
rather than extraction defects.

## Risks / Trade-offs

- **[A VM guard is imposed on a domain it does not fit]** → The main risk. Each guard
  gets an explicit disposition rather than travelling with the mechanism.
- **[The two copies' terminal-state vocabularies differ]** → Likely; they persist to
  different schemas. The vocabulary is domain-supplied, the sweep is not.
- **[914 lines is too large to move in one section]** → Break by protocol phase — round
  zero, continuation, accept — rather than by file, and land each with all three domains
  composed.
- **[Extraction collides with in-flight negotiation changes]** → Goal 2 and Goal 5 both
  modify this runtime. Sequencing matters more here than for the sibling extractions;
  coordinate rather than rebasing repeatedly.

## Migration Plan

Extract, compose all three domains, remove every copy, then packaging follow-through.
Rollback is a code revert; no persisted state or wire surface changes.

## Open Questions

- **Should this extraction wait for the in-flight changes that modify the same code?**
  Extracting during active modification means repeated rebasing; extracting after means
  those changes land in one domain and need porting. Deferrable to sequencing, and the
  answer may differ per concern.
