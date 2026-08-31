## Why

Buyer listing-demand rendering and compatibility with current accepted run-log forms are already implemented. The remaining gap is policy-owned preference among settlement tuples that have already passed compatibility, chain, token, and balance constraints; current orchestration falls back to interaction or list order.

## What Changes

- Narrow the change to a typed buyer-policy preference hook over compatible settlement candidates.
- Define precedence between policy preference, interactive selection, positive-balance fallback, and deterministic default behavior.
- Reject invalid policy output without selecting an incompatible tuple.
- Preserve existing listing rendering and accepted run-log forms as baseline rather than migration tasks.
- State: **Planned after wheel-only dependency cleanup; public policy behavior should stabilize before typing ratchets.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `buyer-orchestration`: Buyer policy may rank or select among already-compatible settlement choices without bypassing compatibility constraints.

## Dependencies and Related Changes

- Can proceed in parallel with `remove-relative-uv-sources` but precedes `type-core-packages` for the affected public policy interface.

## Non-Goals

- Do not introduce a negotiation strategy or make incompatible settlement mechanisms selectable.
- Do not remove observable compatibility with accepted current run-log forms.
- Do not add migration-history commentary to production code.

## Impact

Touches `kit/policy` buyer policy protocol, core buyer escrow selection, domain policy implementations if any, CLI behavior tests, and permanent buyer orchestration documentation.
