## Context

See proposal.md — Why. The shape that matters:

- `request_eligible_pretransfer_refund` (`network.py:795-809`) retries on a
  substring match against `"authenticated HTTP 409:"` and
  `"authenticated HTTP 503:"` in a `RuntimeError`'s message. It has the status
  code but not the authority's own error code, and it treats the two statuses as
  one class.
- The authority already returns a structured code alongside the status:
  `operation_conflict`, `reversal_unsupported`, `funding_relation_missing`
  (`authority.py:4531-4550`). The information the wait needs is already on the
  wire.
- `us_bank_transfer.v1` carries the exact reversal policy `(RETURN,)`
  (`config.py:108-113`) while the other two profiles carry `(CANCEL, REFUND)`,
  so this is the profile where a permanent refusal is most likely and least
  visible.

## Goals / Non-Goals

**Goals:**
- A wait retries only what can change, and says what stopped it when something
  cannot.
- The run's diagnostic carries the authority's own code for this path.

**Non-Goals:**
- Deciding whether `us_bank_transfer.v1` reclaim is achievable. This change
  makes that answerable; it does not answer it.
- Any change to authority behavior, reversal selection, or per-profile policy.

## Decisions

### Retry is decided by the authority's code, not by HTTP status

`operation_conflict` is retryable — it is the compare-and-set race the wait
exists for. Everything else this path can return ends the wait.

*Alternatives considered.* Keeping the status-based match and adding a shorter
deadline — rejected: it makes a permanent refusal fail faster while still not
saying what it was, which is the actual complaint. Treating all 503 as retryable
because the status means "temporarily unavailable" — rejected: the authority uses
503 for `funding_relation_missing`, which for a push-funded obligation is a
statement about the funding's shape and will not become true by waiting.

Deciding on the code rather than the status also means a new authority code
arrives as an immediate, named refusal rather than being silently absorbed into
the retry loop for three minutes.

### The refusal replaces the diagnostic, not the stage

The stage stays `marketplace_lifecycle`, because that is where the lane was. The
diagnostic's `code` becomes the authority's code instead of
`convergence_timeout`. Stage and cause answer different questions and the
current report conflates them.

### An exhausted wait keeps its last refusal

A timeout that says only that a stage did not converge cannot be told apart from
one that never got an answer. Carrying the last refusal into the timeout costs
one field and removes that ambiguity.

## Risks / Trade-offs

- **A refusal classified permanent that is in fact transient would end a lane
  early** → the classification is allowlist-shaped: `operation_conflict` retries
  and everything else stops, so a genuinely transient new code fails visibly and
  is corrected by naming it, rather than being hidden by a blanket retry.
- **A lane that used to pass by outlasting a slow authority would now fail** →
  acceptable and intended: retrying `reversal_unsupported` never produced a pass,
  and if some code did rely on the wait absorbing a slow start, that is a
  timing dependency worth surfacing.

## Migration Plan

None. The change is confined to the harness's wait and diagnostic construction;
no persisted state, wire contract, or deployment input is affected. Reverting is
a code revert.
