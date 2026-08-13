# Design

## Grounding

Audited against `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`.

### What the issue engine already does

`src/issue_discovery/issues.py`:

- `IssuePacketGenerator.generate()` builds candidates from failed phases and
  from workaround failures.
- A fingerprint is a slug, derived from a classifier match where the collected
  evidence matches a known pattern, and from the phase and command where it does
  not. The unmatched case produces a generic candidate rather than a guessed
  root cause — a conservative default worth preserving.
- `_readiness_for` assigns a state; filing requires `ready_to_file` unless
  forced.
- `IssueRepository.create()` prints the command under `--dry-run`, checks the
  body against redaction rules, searches open issues for the fingerprint, prints
  the duplicate's URL and returns success if one exists, and otherwise shells
  out to `gh issue create`.
- The duplicate search requests `number,title,state,url` and uses `state` only
  for display.

So: create exists, duplicate detection exists, redaction gating exists, and
`state` is already on hand for a reopen decision that is not made. Update,
reopen, suppression, and any cleanup consideration are absent.

## Decisions

### Three quantities, kept apart by construction

A run that offered twelve requests and observed nine successes supports three
incompatible readings: the product refused three, the harness only managed to
offer nine, or the product served twelve and the observer missed three. The
numbers are identical.

So the projection names three measurements and never derives one from another:

- **Offered demand** — what the harness put to the product, counted from the
  actor's frozen requests and their release, not from responses.
- **Served capacity** — what the product completed, counted from product-owned
  outcomes.
- **Load-generator limit** — where the harness itself was the constraint: an
  actor that failed to start, missed its release, or was still preparing when
  the barrier fired.

A quantity that cannot be attributed to exactly one of the three is not reported
as any of them. It is reported as unattributed, with the events that made it
ambiguous.

Rejected: a single throughput figure with the caveats in prose. The number
outlives the prose. It gets pasted into a summary, and a load-generator ceiling
becomes a product capacity claim one copy-paste later.

Rejected: deriving load-generator limit as the residual — offered minus served
minus refused. It is arithmetically tempting and it silently absorbs every
observation gap into a category that reads like a harness problem, which is the
flattering direction to be wrong in.

### Absence is not zero

A metric the run could not derive is recorded absent, with the reason. Never
defaulted.

The failure this prevents is specific: a collector that did not run produces no
teardown events, a projection that defaults to zero reports zero residue, and a
run that left resources behind is recorded as clean. The defaulted value is
indistinguishable from the measured one and reads as reassurance.

Rejected: omitting the field entirely when underivable. A consumer cannot
distinguish "not measured" from "not applicable to this scenario", and one of
those is a gap and the other is not.

### The projection is a pure function of the corpus

Same events in, same result out. No ambient clock, no ordering by wall time
where causal ordering is available, no identifiers that vary between projections
of one corpus.

This is what makes a result reviewable: a reviewer can re-project the corpus and
get the same answer, and a disagreement is about the events or about the
projection, never about when it was run.

Rejected: ordering by observed timestamp. Timestamps come from several
processes, and a projection whose result depends on clock skew is not one two
people can check against each other.

### Evidence classes bound claims, and are checked

Every result carries the class of claim it supports. A mock, dry-run, fixture,
or rehearsal result is not live, capacity, or production evidence, and a result
whose class does not admit a claim cannot carry that claim — the projection
refuses to attach it rather than attaching it with a qualifier.

Rejected: a disclaimer field. It relies on the reader, and the reader is
frequently a later summary that keeps the number and drops the field.

### Cleanup gates filing, and cleanup failure is its own finding

A finding whose run left residue is not filing-ready. The residue is itself a
finding, of its own class, not a note attached to the defect the run was
investigating.

The reason to separate them: a run that finds a genuine product defect *and*
fails to clean up has produced two facts, and attaching the second to the first
means it gets closed when the first is fixed. Cleanup failures also recur across
unrelated scenarios, which is the signature of an infrastructure problem rather
than a product one.

### Expected refusals are suppressed at projection, not at filing

A refusal that matched its declared signature is an expected outcome. It never
becomes a candidate.

Suppressing later — generating the candidate and filtering it before filing — is
worse in a specific way: the candidate exists in the run artifacts, and the next
person to read the artifacts directly rather than the filed issues finds a
defect that was never a defect.

### Update and reopen use the state already fetched

The duplicate search already retrieves `state`. Recurrence against an open issue
records recurrence; against a closed one, reopens. Neither files a second issue.

Both are issue-lifecycle mutations the engine did not previously perform, and
both stay behind the existing readiness and redaction gates. That is the whole
of the mutation surface this change adds.

### Absence of mutation is structural

The engine gains no code path that creates a comment, a branch, a pull request,
or a merge. A draft fix is an artifact in the working tree, with a
candidate-packet fallback when even that is not permitted.

Tests assert on the reachable surface rather than on behaviour under a flag,
because a promise not to mutate is exactly the control that failed before: the
archival branch's boundary was a design intent, and a wrapper script satisfied
every test while violating it.

## Open questions

### What is the series identity of a re-run after a product change?

A series is immutable once established, so a later run extends it. But a run
against a different product revision is arguably not the same series, and
treating it as one produces a trend line across a discontinuity.

Provisional: the product revision is part of series identity, so a revision
change starts a new series and comparison across them is explicit rather than
implied. Revisit if it fragments series faster than they accumulate meaning.

### Should a suppressed expected refusal be counted?

Suppression keeps it out of candidates. Whether the projection should still
report "three expected refusals occurred" is a separate question — it is
evidence the scenario did what it declared, and its absence would be
suspicious.

Provisional: counted in the result, absent from candidates. A scenario that
declared three refusals and produced none has a finding, and that finding is
only visible if the count is reported.
