# Design

## Context

At implementation time the domain-local files were 1,324 lines for VM and 652
lines for API credits. Bare metal still had no synchronous negotiation runtime.
The larger VM count included later hosted-settlement, resource-shape, and
capacity-hold work that had landed after the proposal's original measurement.

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

### Drift disposition

The two copies shared round creation, transcript append/load, seller-policy
evaluation, terminal success/failure, and acceptance persistence, but differed
at every domain-shaped edge:

- VM alone rejected a round-zero compute resource shape that disagreed with the
  listing and derived duration/start terms for accepted VM service.
- API credits alone validated quota and existing-key ownership, multiplied its
  price bound by quantity, persisted quantity/key intent, and treated service
  terms as durationless.
- Each domain built different accepted artifacts and used a different
  best-effort post-acceptance hold.
- VM had accumulated the stricter principal, listing-state, and acceptance
  guards; API credits had the same protocol states but fewer pre-effect checks.

The resolution makes canonical buyer/seller and authenticated-actor checks,
recorded-listing resolution, terminal-state rejection, transcript ordering, and
the single acceptance chokepoint universal. It keeps resource-shape validation,
quota/key validation, price reference, configuration, agreement terms,
artifact construction, accepted-input persistence, and hold placement in
injected domain hooks. Continuation additionally asks the selected domain to
compare its persisted accepted inputs with the transcript before policy or
acceptance effects. This adopts the VM protocol guards for every domain without
adopting VM payload semantics.

### Bare-metal consumption

Bare metal still has no caller in this change's starting checkout. The kit API
therefore exposes opening and continuation resolvers plus one complete opaque
domain hook set; the bare-metal storefront composition track can supply its own
codecs and policy without importing VM or API-credit code. VM and API credits
are the concrete migrations in this changeset.

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

Extract the mechanism, compose every existing VM and API-credit caller, remove
both copies, expose the complete seam for the bare-metal composition track, then
complete packaging. Rollback is a code revert; no persisted state or wire
surface changes.

## Resolved sequencing

The extraction landed behind injected adapters after the in-flight VM and
API-credit behavior was present. Domain-local lifecycle modules were deleted,
so subsequent negotiation changes must modify the kit protocol or the owning
domain hook rather than patching one of two copies.
