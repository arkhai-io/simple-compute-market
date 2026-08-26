## Context

`SettlementSQLiteRepository.finish_settlement_operation` writes
`mechanism_state=COALESCE(?, mechanism_state)`. A non-null value replaces the
whole column; a null one leaves it alone. There is no merge, and that is
deliberate: mechanism state is the adapter's own vocabulary, and merging would
accumulate keys from answers that no longer hold.

`_finish_manual` is the only writer that merges, and it does so explicitly:
`{**record.mechanism_state, MANUAL_REASON_KEY: code}`. Its comment states the
invariant — "a state that requires human action while withholding its reason is
unrepairable". It holds at the instant of parking and not afterwards.

The park itself is durable and lives elsewhere: `materialization_state`,
`condition_state`, `collection_state`, and `reclaim_state` each record
`manual_required` in their own column, and `hosted_public_status` reads all
four. So an obligation stays parked while the reason for it does not.

Reproduced from a real `us_ach_debit.v1` lane and reduced to a unit test: park
the collection, then reconcile status once with an adapter that returns the
state it derives rather than the state it was handed, which is what every real
adapter does.

## Goals / Non-Goals

**Goals:**

- The reason an obligation is parked lasts exactly as long as the park.
- One fix, in the layer that owns both the park and the key.

**Non-Goals:**

- Merging mechanism state generally. Replacement is correct for everything
  else, and this change preserves one key rather than changing the rule.
- Changing what parks an obligation, or the vocabulary of reasons.
- Inventing a reason where none was ever recorded. If a park arrived without
  one, this change does not manufacture one; it stops one from being lost.

## Decisions

**D1 — Carry the reason forward in the runtime, not the adapter.** The adapter
answers for the authority's current view. It is asked for status, the authority
says the funding is available, and that answer is true — the refusal was of the
collection. The adapter has no way to know the marketplace is still parked,
because the park lives in the marketplace's own operation rows. The runtime has
both, so the rule belongs there and every mechanism inherits it.

**D2 — Fill only an absent reason.** A write that names its own reason is
describing a park it knows about, which is newer and more specific than the one
being carried. Preserving the old one over it would pin the first failure
forever.

**D3 — Decide "still parked" from the operation states, not from the incoming
status.** A status answer of `ready` does not unpark an obligation whose
collection was refused, which is the whole shape of the observed defect. The
four operation states are what `hosted_public_status` reads, so they are what
the reason must track.

**D4 — Let the park clear the reason.** When no operation state is
`manual_required` any more, nothing is carried, and the next write drops the
key as it does today. A reason that outlived its park would be worse than one
that vanished: it would describe a deal that has since recovered.

## Risks / Trade-offs

- **One key now behaves differently from the rest of mechanism state.** That is
  the point, and it is why it is documented at the write rather than left for a
  reader to infer from behaviour. The alternative — every adapter remembering
  to re-emit a reason it cannot see the need for — is the arrangement that
  produced the defect.
- **A stale reason during recovery.** An obligation that is parked on one
  operation and progressing on another keeps the parked operation's reason,
  which is correct: it is still parked, and that is still why.
