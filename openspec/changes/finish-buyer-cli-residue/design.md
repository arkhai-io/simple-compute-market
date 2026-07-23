## Context

Listing detail already renders demands, and buyer helpers accept the current run-log forms. `escrow_selection` filters candidates, then chooses interactively or uses positive balance/list order. `BuyerPolicy` has compatibility and price derivation but no preference contract, despite permanent architecture assigning payment-choice policy to the buyer policy layer.

## Goals / Non-Goals

**Goals:** typed constrained preference, deterministic fallback, clear precedence, invalid-output safety.

**Non-Goals:** compatibility bypass, negotiation strategy, or removal of current run-log input forms.

## Decisions

- Invoke policy preference only after compatibility and environment constraints produce the candidate set.
- Pass immutable typed candidate views and context needed for preference; do not expose mutable orchestration state.
- Permit ranking or one selected candidate only if every returned identity belongs to the input set; invalid/exceptional output falls back actionably without selecting outside the set.
- Preserve explicit interactive user choice as final authority when interaction is requested. In noninteractive mode, valid policy preference precedes balance/list-order fallback.
- Zero candidates remains an error; one candidate needs no policy decision.

## Risks / Trade-offs

- **[Policy output is nondeterministic]** → Require stable tie handling and focused repeatability tests.
- **[Preference leaks compatibility responsibility]** → Filter before invocation and validate returned identities.
- **[Existing custom policies break]** → Add an optional default method or protocol evolution with compatibility tests rather than requiring every policy immediately.

## Permanent Documentation Promotion

Preference ownership and precedence belong in `openspec/specs/buyer-orchestration/spec.md`; rationale belongs in `architecture.md`. Current accepted run-log forms should be described as present compatibility, not historical migration.
