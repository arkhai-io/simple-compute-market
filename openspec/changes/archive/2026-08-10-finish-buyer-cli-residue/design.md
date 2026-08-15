## Context

Listing detail already renders demands, and buyer helpers accept the current run-log forms. `escrow_selection` filters candidates, then chooses interactively or uses positive balance/list order. `BuyerPolicy` has compatibility and price derivation but no preference contract, despite permanent architecture assigning payment-choice policy to the buyer policy layer.

## Goals / Non-Goals

**Goals:** typed constrained preference, deterministic fallback, clear precedence, invalid-output safety.

**Non-Goals:** compatibility bypass, negotiation strategy, or removal of current run-log input forms.

## Decisions

- Invoke policy preference only after compatibility, chain, token, and other authoritative
  constraints produce the candidate set.
- `BuyerPolicy.prefer_settlement` is an optional synchronous callable receiving
  `tuple[SettlementPreferenceCandidate, ...]` plus a frozen
  `SettlementPreferenceContext`. Candidates expose only an opaque positional identity,
  chain, escrow address, token, and primary unit price; they do not expose mutable
  orchestration state.
- A hook may return one candidate identity, an ordered tuple of unique candidate
  identities, or `None`. Every returned identity must belong to the input set. Invalid,
  duplicate, exceptional, or inconsistent repeated output emits a warning and falls back
  without selecting outside the constrained set.
- Preserve explicit interactive user choice as final authority: preference is not invoked
  for an interactive selection. In noninteractive mode, valid preference precedes positive
  token balance, which precedes the original constrained-list order.
- Zero candidates remains an error at the caller boundary; one candidate is returned
  without invoking preference.

## Risks / Trade-offs

- **[Policy output is nondeterministic]** → Require stable tie handling and focused repeatability tests.
- **[Preference leaks compatibility responsibility]** → Filter before invocation and validate returned identities.
- **[Existing custom policies break]** → Add an optional default method or protocol evolution with compatibility tests rather than requiring every policy immediately.

## Permanent Documentation Promotion

Preference ownership and precedence belong in `openspec/specs/buyer-orchestration/spec.md`; rationale belongs in `architecture.md`. Current accepted run-log forms should be described as present compatibility, not historical migration.

## Validation record

- Kit policy: 7 tests passed; the changed protocol module passed mypy and Ruff.
- Core buyer: 35 tests passed, including constrained candidate views, zero/one
  short-circuiting, valid selection/ranking, interactive authority, fallback precedence,
  and invalid, duplicate, exceptional, and inconsistent hook output.
- VM buyer: 158 tests passed, including CLI and accepted run-log compatibility.
- API-credit buyer: 16 tests passed.
- The complete wheel distribution build, focused import/type checks, strict validation of
  this change and the permanent buyer spec, and comment hygiene passed.
- Repository-wide strict validation still reports six unrelated pre-existing active-change
  failures: `add-buyer-vm-connectivity-terms`, `fix-vm-fulfillment-capacity-boundary`,
  `negotiation-driven-capacity-resize`, `pool-declared-offering-modes`,
  `refactor-e2e-fulfillment-lifecycle`, and `structured-capacity-requirements`.
